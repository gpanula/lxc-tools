"""lxc-tools rollback: roll back a container to a ZFS snapshot.

If the container is currently running, stops it safely, rolls back, and
restarts it unless ``--no-restart`` is specified.
"""

from __future__ import annotations

from pathlib import Path

from lxc_tools import lxc as lxc_backend, prereq, zfs
from lxc_tools.commands import common_parser, find_container_path, guarded, validate
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("zfs", "lxc-info", "lxc-start", "lxc-stop")


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "rollback",
        parents=[common_parser()],
        help="Roll back a container to a ZFS snapshot.",
        description=(
            "Rolls back the container's rootfs dataset to a specified snapshot. "
            "If running, stops the container, performs rollback, and restarts it."
        ),
    )
    parser.add_argument(
        "container_name", metavar="container_name", help="Name of the container."
    )
    parser.add_argument("tag", metavar="tag", help="Snapshot tag name to roll back to.")
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Do not restart the container if it was running prior to rollback.",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force rollback without interactive confirmation.",
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
    tag = args.tag
    validate(name, "container_name")
    validate(tag, "tag")

    if user == "root":
        path = find_container_path(cfg, name)
        if path is None:
            raise prereq.PrereqError(f"Error: Container '{name}' not found in any path.")
        if path == cfg.priv_path:
            dataset = f"{cfg.zfs_pool}/lxc/privileged/{name}"
            exec_user = None
        else:
            owner = Path(path).name
            dataset = f"{cfg.zfs_pool}/lxc/unprivileged/{owner}/{name}"
            exec_user = owner
    else:
        path = f"{cfg.unpriv_base}/{user}"
        if not (Path(path) / name).is_dir():
            raise prereq.PrereqError(f"Error: Container '{name}' not found in {path}.")
        dataset = f"{cfg.zfs_pool}/lxc/unprivileged/{user}/{name}"
        exec_user = user

    backend = zfs.ZFS()
    if not backend.exists(dataset):
        raise prereq.PrereqError(f"Error: ZFS dataset '{dataset}' does not exist.")

    # Check snapshot existence
    snapshots = [s["tag"] for s in backend.list_snapshots(dataset)]
    if tag not in snapshots:
        raise prereq.PrereqError(
            f"Error: Snapshot '{tag}' not found for dataset '{dataset}'.\n"
            f"Available: {', '.join(snapshots) if snapshots else '(none)'}"
        )

    # Check if container is running
    _, state, _, _, _ = lxc_backend.container_info(path, name)
    was_running = state == "RUNNING"

    if not args.force and not args.dry_run:
        print(f"WARNING: Rolling back '{name}' to snapshot '{tag}' will discard all changes made since that snapshot.")
        confirm = input("Are you sure you want to proceed? [y/N] ")
        if confirm.strip().lower() not in ("y", "yes"):
            print("Rollback cancelled.")
            return 0

    print(f"--- Rolling back container: {name} to snapshot: {tag} ---")


    if was_running:
        print("[1/3] Stopping container...")
        lxc_backend.stop(name, path, user=exec_user, kill=True, dry_run=args.dry_run)
    else:
        print("[1/3] Container is stopped.")

    print(f"[2/3] Rolling back ZFS dataset: {dataset}@{tag}...")

    def do_rollback() -> None:
        backend.rollback(dataset, tag, destroy_newer=True)

    prereq.dry_or(args.dry_run, f"  Rolling back {dataset}@{tag}", do_rollback)

    if was_running and not args.no_restart:
        print("[3/3] Restarting container...")
        lxc_backend.start(name, path, user=exec_user, dry_run=args.dry_run)
        print(f"Container '{name}' rolled back to '{tag}' and restarted successfully.")
    else:
        print(f"[3/3] Container '{name}' rolled back to '{tag}' (stopped).")

    return 0
