"""lxc-tools attach: open an interactive shell inside a running container.

Unlike ``exec``, this inherits stdio so the caller gets a real terminal. No
pre-execution snapshot is taken: an interactive shell may be used for hours,
so snapshotting on entry would be misleading and would accumulate snapshots.
"""

from __future__ import annotations

import argparse

from lxc_tools import lxc as lxc_backend, prereq
from lxc_tools.commands import (
    common_parser,
    guarded,
    resolve_running_container,
    validate,
)
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("lxc-attach", "lxc-info")


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "attach",
        parents=[common_parser()],
        help="Attach an interactive shell to a running container.",
        description=(
            "Attaches an interactive shell to a running LXC container as root "
            "by default. Use --user to attach as a non-root user inside the "
            "container. No snapshot is taken."
        ),
    )
    parser.add_argument(
        "container_name",
        metavar="container_name",
        help="Name of the running container.",
    )
    parser.add_argument(
        "--user",
        metavar="NAME",
        default=None,
        help=(
            "Attach as this user inside the container (resolved to uid/gid via "
            "the container's /etc/passwd). Default: root."
        ),
    )
    # NOTE: dest must not be "command" -- argparse stores the subcommand name
    # in ``args.command``, and REMAINDER would clobber it.
    #
    # REMAINDER is required (not ``nargs="*"``) because the top-level parser
    # consumes a bare ``--`` before the subparser ever sees it; REMAINDER
    # captures everything after the container name verbatim. The consequence is
    # that ``--user`` must precede the container name.
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        metavar="COMMAND",
        help="Optional command to run instead of an interactive shell.",
    )
    parser.set_defaults(func=run)


def _resolve_uid_gid(name: str, path: str, username: str) -> tuple[int, int]:
    """Resolve ``username`` to (uid, gid) inside the container.

    The lookup runs inside the container so it reflects the container's own
    /etc/passwd rather than the host's.
    """
    rc, stdout, stderr = lxc_backend.execute(
        name, path, ["id", "-u", username]
    )
    if rc != 0:
        raise prereq.PrereqError(
            f"Error: User '{username}' does not exist in container '{name}'.\n"
            f"{stderr.strip()}"
        )
    uid = int(stdout.strip())

    rc, stdout, stderr = lxc_backend.execute(
        name, path, ["id", "-g", username]
    )
    if rc != 0:
        raise prereq.PrereqError(
            f"Error: Could not resolve primary group for '{username}'.\n"
            f"{stderr.strip()}"
        )
    gid = int(stdout.strip())
    return uid, gid


@guarded
def run(args) -> int:
    prereq.ensure_root_or_reexec()
    user = prereq.resolve_current_user()
    require_member_of(user)
    require_binaries(_BINARIES)
    cfg = load_config()

    name = args.container_name
    validate(name, "container_name")

    path = resolve_running_container(cfg, name, user)

    uid = gid = None
    if args.user:
        validate(args.user, "user")
        uid, gid = _resolve_uid_gid(name, path, args.user)

    cmd = list(args.cmd) if args.cmd else []
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    command = cmd or None
    return lxc_backend.attach(
        name,
        path,
        command=command,
        uid=uid,
        gid=gid,
        dry_run=args.dry_run,
    )
