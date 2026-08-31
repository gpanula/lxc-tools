"""lxc-tools snapshots: list ZFS snapshots for a container."""

from __future__ import annotations

from pathlib import Path

from lxc_tools import prereq, zfs
from lxc_tools.commands import common_parser, find_container_path, guarded, validate
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("zfs",)


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "snapshots",
        parents=[common_parser()],
        help="List ZFS snapshots for a container.",
        description="Lists all ZFS snapshots available for a given container.",
    )
    parser.add_argument(
        "container_name", metavar="container_name", help="Name of the container."
    )
    parser.set_defaults(func=run)


@guarded
def run(args) -> int:
    user = prereq.effective_user()
    require_binaries(_BINARIES)
    cfg = load_config()

    name = args.container_name
    validate(name, "container_name")

    if user == "root":
        path = find_container_path(cfg, name)
        if path is None:
            raise prereq.PrereqError(f"Error: Container '{name}' not found in any path.")
        if path == cfg.priv_path:
            dataset = f"{cfg.zfs_pool}/lxc/privileged/{name}"
        else:
            owner = Path(path).name
            dataset = f"{cfg.zfs_pool}/lxc/unprivileged/{owner}/{name}"
    else:
        require_member_of(user)
        path = f"{cfg.unpriv_base}/{user}"
        if not (Path(path) / name).is_dir():
            raise prereq.PrereqError(f"Error: Container '{name}' not found in {path}.")
        dataset = f"{cfg.zfs_pool}/lxc/unprivileged/{user}/{name}"

    backend = zfs.ZFS()
    snapshots = backend.list_snapshots(dataset)

    print(f"--- Snapshots for Container: {name} ---")
    print(f"Dataset: {dataset}")
    print("")
    if not snapshots:
        print("No snapshots found.")
        return 0

    header = f"{'TAG':<25} {'USED':<10} {'REFERENCED':<12} {'CREATION'}"
    print(header)
    print("-" * len(header))
    for s in snapshots:
        print(f"{s['tag']:<25} {s['used']:<10} {s['referenced']:<12} {s['creation']}")
    return 0
