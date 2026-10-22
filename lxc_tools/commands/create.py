"""lxc-tools create: create an unprivileged LXC container.

Ports the legacy ``create-lxc-project`` bash script to Python, using the
native ZFS (pyzfs), LXC and ACL backends.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


from lxc_tools import acl, distro, lxc as lxc_backend, prereq, zfs
from lxc_tools.commands import SIZE_RE, common_parser, guarded, validate
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("lxc-create", "zfs", "newuidmap", "newgidmap")

#: Distros that boot with systemd as PID 1. For unprivileged containers these
#: default to the minimal init (``--no-systemd``) because systemd cannot run
#: when the host cgroup v2 scope does not delegate the memory/pids controllers.
#: Alpine uses OpenRC and is intentionally excluded.
SYSTEMD_DISTROS = frozenset({"ubuntu", "debian", "rockylinux", "almalinux"})

#: Path (inside the container rootfs) where the minimal init script is installed
#: when ``--no-systemd`` is requested.
_INIT_SCRIPT_PATH = "/usr/local/sbin/lxc-tools-init.sh"

#: Minimal init script used when ``--no-systemd`` is requested. systemd cannot
#: run as PID 1 in an unprivileged container when the host cgroup v2 scope does
#: not delegate the memory/pids controllers, so this script brings up eth0 via
#: dhcpcd, writes the DHCP-provided DNS server to /etc/resolv.conf (falling back
#: to public resolvers only if DHCP provides none), and keeps PID 1 alive.
_INIT_SCRIPT = """#!/bin/sh
# Minimal init for lxc-tools containers created with --no-systemd.
#
# systemd cannot run as PID 1 here because the host cgroup v2 scope does not
# delegate the memory/pids controllers. This script brings up networking and
# DNS, then keeps PID 1 alive.

set -u

IFACE="eth0"

log() { echo "[lxc-tools-init] $*"; }

# --- Networking -----------------------------------------------------------
# Bring the interface up and obtain a DHCP lease. dhcpcd daemonizes and keeps
# renewing the lease in the background.
if command -v dhcpcd >/dev/null 2>&1; then
    ip link set "$IFACE" up 2>/dev/null || true
    log "requesting DHCP lease on $IFACE"
    dhcpcd -n "$IFACE" 2>&1 | sed 's/^/[lxc-tools-init] dhcpcd: /' || true
else
    log "WARNING: dhcpcd not found; $IFACE will not be configured"
fi

# --- DNS ------------------------------------------------------------------
# /etc/resolv.conf is normally a symlink to systemd-resolved, which does not
# run here. Prefer the DNS server advertised by DHCP (via `dhcpcd -U`); fall
# back to public resolvers only if DHCP provides none.
if [ -L /etc/resolv.conf ] || [ ! -s /etc/resolv.conf ]; then
    rm -f /etc/resolv.conf
fi
if ! grep -q '^nameserver' /etc/resolv.conf 2>/dev/null; then
    dns=""
    if command -v dhcpcd >/dev/null 2>&1; then
        dns=$(dhcpcd -U "$IFACE" 2>/dev/null | sed -n 's/^domain_name_servers=//p' | tr ' ' '\n' | head -1)
    fi
    if [ -n "$dns" ]; then
        printf 'nameserver %s\n' "$dns" > /etc/resolv.conf
        log "wrote DHCP-provided nameserver $dns to /etc/resolv.conf"
    else
        {
            echo "nameserver 1.1.1.1"
            echo "nameserver 8.8.8.8"
        } > /etc/resolv.conf
        log "no DHCP nameserver; wrote public fallback resolvers"
    fi
fi

# --- Keep PID 1 alive -----------------------------------------------------
log "network setup complete; entering idle"
exec sleep infinity
"""


def normalize_create_args(
    distro: str, release: str, arch: str, quota: str | None
) -> tuple[str, str, str, str]:
    """Apply the 4-argument quota shorthand and default quota.

    Mirrors the legacy script: if the arch slot holds a size and no explicit
    quota was given, the size is treated as the quota and arch defaults to
    amd64. Returns ``(distro, release, arch, quota)``.
    """
    if quota is None and re.fullmatch(SIZE_RE, arch):
        quota = arch
        arch = "amd64"
    quota = quota or "10G"
    return distro, release, arch, quota


def validate_arch_not_quota(arch: str) -> None:
    """Reject a size value in the arch slot of the explicit 5-argument form."""
    if re.fullmatch(SIZE_RE, arch):
        raise prereq.PrereqError(
            "Error: '<arch>' looks like a quota size, not an architecture.\n"
            "Usage: lxc-tools create <container_name> [distro] [release] [arch] [quota]\n"
            "Example: lxc-tools create my-app ubuntu lts amd64 64G"
        )


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "create",
        parents=[common_parser()],
        help="Create an unprivileged LXC container.",
        description=(
            "Automates the creation of unprivileged LXC containers with ZFS "
            "backing and secure bind mounts to the project directory."
        ),
    )
    parser.add_argument(
        "container_name", metavar="container_name",
        help="Name of the container to create.",
    )
    parser.add_argument(
        "distro", nargs="?", default="ubuntu",
        help="Distribution name (default: ubuntu).",
    )
    parser.add_argument(
        "release", nargs="?", default="lts",
        help="Release codename or 'lts' (default: lts).",
    )
    parser.add_argument(
        "arch", nargs="?", default="amd64",
        help="Architecture (default: amd64).",
    )
    parser.add_argument(
        "quota", nargs="?", default=None,
        help="ZFS disk quota for the container (e.g. 20G, default: 10G).",
    )
    parser.add_argument(
        "--no-systemd",
        action="store_true",
        default=None,
        help=(
            "Use a minimal init instead of systemd. This is the default for "
            "systemd-based distros (ubuntu, debian, rockylinux, almalinux) "
            "because systemd cannot run as PID 1 in an unprivileged container "
            "when the host cgroup v2 scope does not delegate the memory/pids "
            "controllers. The init script brings up eth0 and DNS automatically."
        ),
    )
    parser.add_argument(
        "--systemd",
        action="store_true",
        help=(
            "Force systemd as PID 1 (opt out of the default minimal init). "
            "Only use this when the host delegates the memory/pids controllers."
        ),
    )
    parser.set_defaults(func=run)


def _parse_size_bytes(size_str: str) -> int:
    """Parse human readable size string like '10G', '500M' to bytes."""
    units = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
    match = re.match(r"^(\d+)\s*([kmgtKMGT])?$", size_str.strip())
    if not match:
        return 10 * 1024**3
    num, unit = match.groups()
    multiplier = units.get(unit.lower(), 1024**3) if unit else 1
    return int(num) * multiplier


def _format_bytes(bytes_val: float) -> str:
    """Format bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_val < 1024.0 or unit == "TB":
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} TB"


def _check_disk_space(lxc_path: str, quota: str) -> None:
    """Verify target storage and temp directory have sufficient free space."""
    buffer_bytes = 2 * 1024**3
    quota_bytes = _parse_size_bytes(quota)
    required_target_bytes = quota_bytes + buffer_bytes

    # Find closest existing parent path for target
    target_path = Path(lxc_path)
    while not target_path.exists() and target_path != target_path.parent:
        target_path = target_path.parent

    if target_path.exists():
        free_target = shutil.disk_usage(target_path).free
        if free_target < required_target_bytes:
            raise prereq.PrereqError(
                f"Error: Insufficient space on target storage ({target_path}).\n"
                f"  Required:  {_format_bytes(required_target_bytes)} (quota {quota} + 2 GB buffer)\n"
                f"  Available: {_format_bytes(free_target)}"
            )

    temp_dir = Path(tempfile.gettempdir())
    if temp_dir.exists():
        free_temp = shutil.disk_usage(temp_dir).free
        if free_temp < buffer_bytes:
            raise prereq.PrereqError(
                f"Error: Insufficient temporary space in {temp_dir}.\n"
                f"  Required:  {_format_bytes(buffer_bytes)} (2 GB buffer)\n"
                f"  Available: {_format_bytes(free_temp)}"
            )


@guarded
def run(args) -> int:
    prereq.ensure_root_or_reexec()
    user = prereq.resolve_current_user()
    user_info = prereq.get_user_info(user)
    require_member_of(user)
    require_binaries(_BINARIES)
    cfg = load_config()

    name = args.container_name
    distro_name, release, arch, quota = normalize_create_args(
        args.distro, args.release, args.arch, args.quota
    )

    validate(name, "container_name")
    validate(distro_name, "distro")
    validate(release, "release")
    validate(arch, "arch")
    validate(quota, "quota")
    validate_arch_not_quota(arch)

    mapped_uid, mapped_range = prereq.read_subid_map("/etc/subuid", user)

    release = distro.resolve_lts(distro_name, release, run_as_user=user)

    lxc_path = f"{cfg.unpriv_base}/{user}"
    zfs_root = f"{cfg.zfs_pool}/lxc/unprivileged/{user}"

    _check_disk_space(lxc_path, quota)

    print(
        f"--- Starting creation of unprivileged container: {name} "
        f"for user: {user} ---"
    )


    _configure_local_lxc(
        cfg, user, user_info, zfs_root, lxc_path, mapped_uid, mapped_range, args.dry_run
    )
    _ensure_zfs_dataset(
        cfg, user, user_info, zfs_root, lxc_path, mapped_uid, args.dry_run
    )
    _ensure_project_dir(cfg, user, user_info, name, mapped_uid, args.dry_run)
    _apply_acls(cfg, mapped_uid, name, args.dry_run)
    _create_container(name, lxc_path, distro_name, release, arch, user, args.dry_run)
    _convert_rootfs_to_zfs(name, lxc_path, zfs_root, quota, mapped_uid, args.dry_run)
    _add_bind_mount(cfg, name, lxc_path, args.dry_run)
    if _resolve_no_systemd(args, distro_name):
        _configure_init(name, lxc_path, mapped_uid, args.dry_run)
    _print_summary(name, user, cfg.project_dir, lxc_path)
    return 0


def _resolve_no_systemd(args, distro_name: str) -> bool:
    """Resolve whether to use the minimal init for a container.

    Precedence:
    1. ``--systemd`` forces systemd (returns False).
    2. ``--no-systemd`` forces the minimal init (returns True).
    3. Otherwise, systemd-based distros default to the minimal init.
    """
    if getattr(args, "systemd", False):
        return False
    if getattr(args, "no_systemd", False):
        return True
    return distro_name.lower() in SYSTEMD_DISTROS


def _configure_local_lxc(
    cfg, user, user_info, zfs_root, lxc_path, mapped_uid, mapped_range, dry_run
) -> None:
    lxc_conf_dir = Path(user_info.home) / ".config" / "lxc"
    print(f"[0/7] Configuring local LXC environment in {lxc_conf_dir}")

    def ensure_dir() -> None:
        lxc_conf_dir.mkdir(parents=True, exist_ok=True)
        os.chown(lxc_conf_dir, user_info.uid, user_info.gid)

    prereq.dry_or(dry_run, "  Configuring local LXC environment", ensure_dir)

    lxc_conf = lxc_conf_dir / "lxc.conf"
    if not lxc_conf.exists():
        content = (
            f"lxc.lxcpath = {lxc_path}\n"
            f"lxc.bdev.zfs.root = {zfs_root}\n"
        )

        def write_lxc_conf() -> None:
            prereq.write_file_owned(lxc_conf, content, user_info.uid, user_info.gid, 0o644)

        prereq.dry_or(dry_run, f"  Writing {lxc_conf}", write_lxc_conf)

    default_conf = lxc_conf_dir / "default.conf"
    if not default_conf.exists():
        content = (
            "lxc.net.0.type = veth\n"
            f"lxc.net.0.link = {cfg.bridge}\n"
            "lxc.net.0.flags = up\n"
            f"lxc.idmap = u 0 {mapped_uid} {mapped_range}\n"
            f"lxc.idmap = g 0 {mapped_uid} {mapped_range}\n"
        )

        def write_default_conf() -> None:
            prereq.write_file_owned(
                default_conf, content, user_info.uid, user_info.gid, 0o644
            )

        prereq.dry_or(dry_run, f"  Writing {default_conf}", write_default_conf)


def _ensure_zfs_dataset(
    cfg, user, user_info, zfs_root, lxc_path, mapped_uid, dry_run
) -> None:
    print(f"[1/7] Checking ZFS dataset: {zfs_root}")
    backend = zfs.ZFS()
    if backend.exists(zfs_root):
        return

    def create_dataset() -> None:
        backend.create_recursive(zfs_root)
        os.chown(lxc_path, user_info.uid, user_info.gid)
        os.chmod(lxc_path, 0o750)
        # Traversal ACL for the container root on the user's path.
        acl.ensure_user_acl(Path(lxc_path), mapped_uid, "x")

    prereq.dry_or(dry_run, f"  Creating dataset {zfs_root}", create_dataset)


def _ensure_project_dir(cfg, user, user_info, name, mapped_uid, dry_run) -> None:
    subdir = Path(cfg.project_dir) / name

    def create_dir() -> None:
        subdir.mkdir(parents=True, exist_ok=True)
        # Own the project directory (and any pre-existing contents) by the
        # mapped UID so the container's root (UID 0 -> mapped_uid) can read and
        # write the bind mount directly. Without this, files copied in by the
        # host user (e.g. UID 1000) map to an unmapped UID inside the container
        # and appear as 'nobody', making them unwritable.
        os.chown(subdir, mapped_uid, mapped_uid)
        for path in subdir.rglob("*"):
            try:
                os.chown(path, mapped_uid, mapped_uid)
            except PermissionError:
                pass

    prereq.dry_or(dry_run, f"[2/7] Creating project directory: {subdir}", create_dir)


def _apply_acls(cfg, mapped_uid, name, dry_run) -> None:
    base = Path(cfg.project_dir)
    subdir = base / name
    print(f"[3/7] Applying ACLs (Mapped UID: {mapped_uid}) to {subdir}")

    def apply_acls() -> None:
        if base.is_dir() and not acl.has_user_execute(base, mapped_uid):
            acl.ensure_user_acl(base, mapped_uid, "x")
        acl.set_user_acl_recursive(subdir, mapped_uid, "rwx")
        acl.set_default_acl_recursive(subdir, mapped_uid, "rwx")

    prereq.dry_or(dry_run, "  Applying ACLs", apply_acls)


def _create_container(
    name, lxc_path, distro_name, release, arch, user, dry_run
) -> None:
    print("[4/7] Creating LXC container template (this may take a minute)...")
    lxc_backend.create(name, lxc_path, distro_name, release, arch, user=user, dry_run=dry_run)


def _convert_rootfs_to_zfs(name, lxc_path, zfs_root, quota, mapped_uid, dry_run) -> None:
    container_dataset = f"{zfs_root}/{name}"
    rootfs_path = Path(lxc_path) / name / "rootfs"
    print(f"[5/7] Converting rootfs to ZFS dataset: {container_dataset}")
    backend = zfs.ZFS()


    def convert() -> None:
        if not rootfs_path.is_dir():
            raise prereq.PrereqError(f"Error: Container rootfs not found at {rootfs_path}")
        if backend.exists(container_dataset):
            raise prereq.PrereqError(f"Error: ZFS dataset already exists: {container_dataset}")

        temp_dir = Path(tempfile.mkdtemp(prefix=f"lxc_rootfs_{name}_"))
        tar_file = temp_dir / "rootfs.tar"
        try:
            # Archive existing rootfs preserving exact numeric UIDs/GIDs and permissions
            subprocess.run(
                ["tar", "-C", str(rootfs_path), "--numeric-owner", "-cpf", str(tar_file), "."],
                check=True,
            )
            shutil.rmtree(rootfs_path)

            backend.create(container_dataset, mountpoint=rootfs_path)
            backend.mount(container_dataset)
            if not rootfs_path.is_dir():
                raise prereq.PrereqError(
                    f"Error: Failed to mount ZFS dataset at {rootfs_path}"
                )
            os.chown(rootfs_path, mapped_uid, mapped_uid)

            if quota:
                backend.set_quota(container_dataset, quota)

            # Extract archive into newly mounted ZFS dataset
            subprocess.run(
                ["tar", "-C", str(rootfs_path), "--numeric-owner", "-xpf", str(tar_file)],
                check=True,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        # Ensure /opt/project mountpoint exists inside container rootfs
        mount_target = Path(rootfs_path) / "opt" / "project"
        mount_target.mkdir(parents=True, exist_ok=True)
        os.chown(Path(rootfs_path) / "opt", mapped_uid, mapped_uid)
        os.chown(mount_target, mapped_uid, mapped_uid)

    prereq.dry_or(dry_run, "  Converting rootfs to ZFS dataset", convert)


def _add_bind_mount(cfg, name, lxc_path, dry_run) -> None:
    config_file = Path(lxc_path) / name / "config"
    subdir = f"{cfg.project_dir}/{name}"
    mount_entry = f"lxc.mount.entry = {subdir} opt/project none bind,create=dir 0 0"
    print(f"[6/7] Adding bind mount entry to {config_file}")

    def add_mount() -> None:
        if not config_file.exists():
            raise prereq.PrereqError(f"Error: Container config not found at {config_file}")
        content = config_file.read_text(encoding="utf-8")
        if subdir in content:
            return
        with config_file.open("a", encoding="utf-8") as handle:
            handle.write(f"\n# Bind mount for project files\n{mount_entry}\n")

    prereq.dry_or(dry_run, "  Adding bind mount", add_mount)


def _configure_init(name, lxc_path, mapped_uid, dry_run) -> None:
    """Install a minimal init script and point ``lxc.init.cmd`` at it.

    Used when ``--no-systemd`` is requested. systemd cannot run as PID 1 in an
    unprivileged container when the host cgroup v2 scope does not delegate the
    memory/pids controllers, so a minimal init brings up eth0 + DNS and keeps
    PID 1 alive instead.
    """
    config_file = Path(lxc_path) / name / "config"
    rootfs_path = Path(lxc_path) / name / "rootfs"
    init_target = rootfs_path / _INIT_SCRIPT_PATH.lstrip("/")
    print(f"[6/7] Installing minimal init script ({_INIT_SCRIPT_PATH})")

    def install() -> None:
        if not config_file.exists():
            raise prereq.PrereqError(f"Error: Container config not found at {config_file}")
        if not rootfs_path.is_dir():
            raise prereq.PrereqError(f"Error: Container rootfs not found at {rootfs_path}")

        # Write the init script into the rootfs and make it executable.
        init_target.parent.mkdir(parents=True, exist_ok=True)
        init_target.write_text(_INIT_SCRIPT, encoding="utf-8")
        init_target.chmod(0o755)
        # Best-effort ownership: only meaningful when running as root (the real
        # create flow). Ignore failure so unit tests can run unprivileged.
        try:
            os.chown(init_target, mapped_uid, mapped_uid)
        except PermissionError:
            pass

        # Point lxc.init.cmd at the script (idempotent).
        content = config_file.read_text(encoding="utf-8")
        if "lxc.init.cmd" in content:
            return
        with config_file.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n# Minimal init (--no-systemd): systemd cannot run as PID 1 here\n"
                f"lxc.init.cmd = {_INIT_SCRIPT_PATH}\n"
            )

    prereq.dry_or(dry_run, "  Installing minimal init script", install)


def _print_summary(name, user, project_dir, lxc_path) -> None:
    print("[7/7] Setup complete!")
    print("-------------------------------------------------------")
    print(f"Container '{name}' is ready.")
    print(f"User:           {user}")
    print(f"Host Path:      {project_dir}/{name}")
    print(f"To start it:    lxc-tools start {name}")
    print(f"To attach:     sudo lxc-attach -n {name} -P {lxc_path}")

