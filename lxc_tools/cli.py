"""lxc-tools command line entry point."""

from __future__ import annotations

import argparse
import sys

from lxc_tools import __version__
from lxc_tools.commands import KNOWN_ERRORS
from lxc_tools.commands import create, list as list_cmd
from lxc_tools.commands import remove, restart, start, stop

DESCRIPTION = (
    "Manage unprivileged LXC containers with ZFS backing and secure bind "
    "mounts to a shared project directory."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lxc-tools",
        description=DESCRIPTION,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the actions that would be taken without executing them.",
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND"
    )
    create.add_parser(subparsers)
    start.add_parser(subparsers)
    stop.add_parser(subparsers)
    list_cmd.add_parser(subparsers)
    remove.add_parser(subparsers)
    restart.add_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KNOWN_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
