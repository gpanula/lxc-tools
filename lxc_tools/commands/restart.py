"""lxc-tools restart: restart an LXC container.

Composes the stop and start flows in-process rather than shelling out to
separate executables (as the legacy script did).
"""

from __future__ import annotations

from types import SimpleNamespace

from lxc_tools import prereq
from lxc_tools.commands import common_parser, guarded
from lxc_tools.commands import start as start_cmd
from lxc_tools.commands import stop as stop_cmd


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "restart",
        parents=[common_parser()],
        help="Restart an LXC container.",
        description="Restarts an LXC container by stopping and then starting it.",
    )
    parser.add_argument(
        "container_name", metavar="container_name",
        help="Name of the container to restart.",
    )
    parser.set_defaults(func=run)


@guarded
def run(args) -> int:
    prereq.ensure_root_or_reexec()
    name = args.container_name
    print(f"--- Restarting container: {name} ---")

    stop_args = SimpleNamespace(container_name=name, kill=False, dry_run=args.dry_run)
    if stop_cmd.run(stop_args) != 0:
        return 1

    start_args = SimpleNamespace(container_name=name, dry_run=args.dry_run)
    if start_cmd.run(start_args) != 0:
        return 1

    print("--- Restart complete! ---")
    return 0
