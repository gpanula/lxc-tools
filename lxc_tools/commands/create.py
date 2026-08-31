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
    _ensure_project_dir(cfg, user, user_info, name, args.dry_run)
    _apply_acls(cfg, mapped_uid, name, args.dry_run)
    _create_container(name, lxc_path, distro_name, release, arch, user, args.dry_run)
    _convert_rootfs_to_zfs(name, lxc_path, zfs_root, quota, mapped_uid, args.dry_run)
    _add_bind_mount(cfg, name, lxc_path, args.dry_run)
    _print_summary(name, user, cfg.project_dir, lxc_path)
    return 0


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


def _ensure_project_dir(cfg, user, user_info, name, dry_run) -> None:
    subdir = Path(cfg.project_dir) / name
    if subdir.is_dir():
        return

    def create_dir() -> None:
        subdir.mkdir(parents=True, exist_ok=True)
        os.chown(subdir, user_info.uid, user_info.gid)

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


def _print_summary(name, user, project_dir, lxc_path) -> None:
    print("[7/7] Setup complete!")
    print("-------------------------------------------------------")
    print(f"Container '{name}' is ready.")
    print(f"User:           {user}")
    print(f"Host Path:      {project_dir}/{name}")
    print(f"To start it:    lxc-tools start {name}")
    print(f"To attach:     sudo lxc-attach -n {name} -P {lxc_path}")

