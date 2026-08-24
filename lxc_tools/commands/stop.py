"""lxc-tools stop: stop an LXC container.

Regular users stop containers in their own unprivileged path. Root searches
the privileged tier first and then all user tiers. ``--kill`` performs a hard
shutdown.
"""

from __future__ import annotations

from pathlib import Path

from lxc_tools import lxc as lxc_backend, prereq
from lxc_tools.commands import common_parser, find_container_path, guarded
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("lxc-stop", "lxc-info")


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "stop",
        parents=[common_parser()],
        help="Stop an LXC container.",
        description=(
            "Stops an LXC container. Regular users stop containers in their own "
            "unprivileged path; root searches privileged and then all user paths."
        ),
    )
    parser.add_argument(
        "--kill", "-k",
        action="store_true",
        help="Force immediate shutdown (hard kill). May be given before or after the name.",
    )
    parser.add_argument(
        "container_name", metavar="container_name", help="Name of the container to stop."
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

    if user == "root":
        path = find_container_path(cfg, name)
        if path is None:
            raise prereq.PrereqError(
                f"Error: Container '{name}' not found in any path."
            )
        print(f"Stopping container '{name}' in path: {path}")
        lxc_backend.stop(name, path, user=None, kill=args.kill, dry_run=args.dry_run)
    else:
        path = f"{cfg.unpriv_base}/{user}"
        if not (Path(path) / name).is_dir():
            raise prereq.PrereqError(
                f"Error: Container '{name}' not found in {path}."
            )
        print(f"Stopping container '{name}' as user {user}...")
        lxc_backend.stop(name, path, user=user, kill=args.kill, dry_run=args.dry_run)

    if not args.dry_run:
        print(lxc_backend.info(name, path))
    return 0
