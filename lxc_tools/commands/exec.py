"""lxc-tools exec: execute a command inside a running LXC container.

Runs commands inside the container as root via lxc-attach. By default, takes
an automatic ZFS snapshot before execution unless configured otherwise or
opted out with ``--no-snapshot``.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

from lxc_tools import lxc as lxc_backend, prereq, zfs
from lxc_tools.commands import common_parser, find_container_path, guarded, validate
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("lxc-attach", "lxc-info", "zfs")


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "exec",
        parents=[common_parser()],
        help="Execute a command inside a running container.",
        description=(
            "Executes a command inside a running LXC container. Automatically "
            "creates a pre-execution ZFS snapshot by default."
        ),
    )
    parser.add_argument(
        "container_name", metavar="container_name", help="Name of the running container."
    )
    parser.add_argument(
        "--snapshot",
        dest="snapshot",
        action="store_true",
        default=None,
        help="Force taking a pre-execution snapshot (overrides config).",
    )
    parser.add_argument(
        "--no-snapshot",
        dest="no_snapshot",
        action="store_true",
        default=False,
        help="Skip taking a pre-execution snapshot.",
    )
    parser.add_argument(
        "--snapshot-tag",
        default=None,
        help="Custom tag for the pre-execution snapshot.",
    )
    parser.add_argument(
        "command",
        nargs="+",
        metavar="COMMAND",
        help="Command and arguments to execute inside the container.",
    )
    parser.set_defaults(func=run)


def _cmd_slug(cmd_args: list[str]) -> str:
    """Generate a clean 1-word slug from the command line for snapshot naming."""
    if not cmd_args:
        return "cmd"
    base = Path(cmd_args[0]).name
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", base)[:16]
    return cleaned or "cmd"


@guarded
def run(args) -> int:
    prereq.ensure_root_or_reexec()
    user = prereq.resolve_current_user()
    require_member_of(user)
    require_binaries(_BINARIES)
    cfg = load_config()

    name = args.container_name
    validate(name, "container_name")

    cmd = args.command
    if not cmd:
        raise prereq.PrereqError("Error: No command specified to execute.")

    # Locate container
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
        path = f"{cfg.unpriv_base}/{user}"
        if not (Path(path) / name).is_dir():
            raise prereq.PrereqError(f"Error: Container '{name}' not found in {path}.")
        dataset = f"{cfg.zfs_pool}/lxc/unprivileged/{user}/{name}"

    # Check container is running
    _, state, _, _, _ = lxc_backend.container_info(path, name)
    if state != "RUNNING":
        raise prereq.PrereqError(
            f"Error: Container '{name}' is {state}. Start it first with:\n"
            f"  lxc-tools start {name}"
        )

    # Determine snapshot decision
    should_snapshot: bool
    if args.no_snapshot:
        should_snapshot = False
    elif args.snapshot or args.snapshot_tag:
        should_snapshot = True
    else:
        should_snapshot = cfg.exec_snapshot

    if should_snapshot:
        backend = zfs.ZFS()
        if backend.exists(dataset):
            if args.snapshot_tag:
                tag = args.snapshot_tag
            else:
                slug = _cmd_slug(cmd)
                tag = f"pre-exec-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}"
            validate(tag, "tag")
            print(f"Taking pre-execution snapshot: {dataset}@{tag}")

            def do_snap() -> None:
                backend.snapshot(dataset, tag)

            prereq.dry_or(args.dry_run, f"  Snapshotting {dataset}@{tag}", do_snap)

    rc, stdout, stderr = lxc_backend.execute(name, path, cmd, dry_run=args.dry_run)
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if stderr:
        print(stderr, file=sys.stderr, end="" if stderr.endswith("\n") else "\n")
    return rc
