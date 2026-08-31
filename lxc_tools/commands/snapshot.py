"""lxc-tools snapshot: create a ZFS snapshot of a container's rootfs.

Supports unprivileged containers for regular users and any container for root.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from lxc_tools import prereq, zfs
from lxc_tools.commands import common_parser, find_container_path, guarded, validate
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("zfs",)


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "snapshot",
        parents=[common_parser()],
        help="Create a ZFS snapshot of a container.",
        description=(
            "Takes an instant ZFS snapshot of the container's rootfs dataset "
            "to provide a rollback/restore point."
        ),
    )
    parser.add_argument(
        "container_name", metavar="container_name", help="Name of the container."
    )
    parser.add_argument(
        "tag",
        nargs="?",
        default=None,
        help="Snapshot tag name (default: auto-generated timestamp snap-YYYYMMDD-HHMMSS).",
    )
    parser.set_defaults(func=run)


@guarded
def run(args) -> int:
    prereq.ensure_root_or_reexec()
    user = prereq.resolve_current_user()
    require_member_of(user)
    require_binaries(_BINARIES)
    cfg = load_config()

    name = args.container_name
    validate(name, "container_name")

    tag = args.tag
    if not tag:
        tag = f"snap-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    validate(tag, "tag")

    if user == "root":
        path = find_container_path(cfg, name)
        if path is None:
            raise prereq.PrereqError(f"Error: Container '{name}' not found in any path.")
        # Determine dataset name
        if path == cfg.priv_path:
            dataset = f"{cfg.zfs_pool}/lxc/privileged/{name}"
        else:
            owner = Path(path).name
            dataset = f"{cfg.zfs_pool}/lxc/unprivileged/{owner}/{name}"
    else:
        path = f"{cfg.unpriv_base}/{user}"
        if not (Path(path) / name).is_dir():
            raise prereq.PrereqError(f"Error: Container '{name}' not found in {path}.")
        dataset = f"{cfg.zfs_pool}/lxc/unprivileged/{user}/{name}"

    backend = zfs.ZFS()
    if not backend.exists(dataset):
        raise prereq.PrereqError(f"Error: ZFS dataset '{dataset}' does not exist.")

    full_snap = f"{dataset}@{tag}"
    print(f"Creating snapshot '{full_snap}'...")

    def do_snap() -> None:
        backend.snapshot(dataset, tag)

    prereq.dry_or(args.dry_run, f"  Snapshotting {dataset}@{tag}", do_snap)
    print(f"Snapshot '{tag}' created for container '{name}'.")
    return 0
