"""lxc-tools create: create an unprivileged LXC container.

Ports the legacy ``create-lxc-project`` bash script to Python, using the
native ZFS (pyzfs), LXC and ACL backends.
"""

from __future__ import annotations

import os
import re
import shutil
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
    rootfs_path = f"{lxc_path}/{name}/rootfs"
    print(f"[5/7] Converting rootfs to ZFS dataset: {container_dataset}")
    temp = Path(f"/tmp/lxc_rootfs_{name}")
    backend = zfs.ZFS()

    def convert() -> None:
        if not Path(rootfs_path).exists():
            raise prereq.PrereqError(
                f"Error: rootfs not found at {rootfs_path} after container creation."
            )
        if temp.exists():
            shutil.rmtree(temp)
        shutil.move(rootfs_path, temp)
        backend.create(container_dataset, mountpoint=rootfs_path)
        backend.mount(container_dataset)
        if not os.path.ismount(rootfs_path):
            raise prereq.PrereqError(
                f"Error: Failed to mount ZFS dataset at {rootfs_path}"
            )
        os.chown(rootfs_path, mapped_uid, mapped_uid)
        if quota:
            backend.set_quota(container_dataset, quota)
        for item in temp.iterdir():
            shutil.move(str(item), rootfs_path)
        shutil.rmtree(temp)

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
    print(f"To attach:     lxc-attach -n {name} -P {lxc_path}")
