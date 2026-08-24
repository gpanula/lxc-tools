"""lxc-tools start: start an LXC container.

Regular users start containers in their own unprivileged path. Root searches
the privileged tier first and then all user tiers.
"""

from __future__ import annotations

from pathlib import Path

from lxc_tools import lxc as lxc_backend, prereq
from lxc_tools.commands import common_parser, find_container_path, guarded
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("lxc-start", "lxc-info")


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "start",
        parents=[common_parser()],
        help="Start an LXC container.",
        description=(
            "Starts an LXC container. Regular users start containers in their "
            "own unprivileged path; root searches privileged and then all user paths."
        ),
    )
    parser.add_argument(
        "container_name", metavar="container_name", help="Name of the container to start."
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
        print(f"Starting container '{name}' in path: {path}")
        lxc_backend.start(name, path, user=None, dry_run=args.dry_run)
    else:
        path = f"{cfg.unpriv_base}/{user}"
        if not (Path(path) / name).is_dir():
            raise prereq.PrereqError(
                f"Error: Container '{name}' not found in {path}."
            )
        print(f"Starting container '{name}' as user {user}...")
        lxc_backend.start(name, path, user=user, dry_run=args.dry_run)

    _verify(name, path, args.dry_run)
    return 0


def _verify(name, path, dry_run) -> None:
    if dry_run:
        return
    print("-------------------------------------------------------")
    print(lxc_backend.info(name, path))
    print("-------------------------------------------------------")
    print(f"Container '{name}' is active.")
    print("")
    print("To connect (Root Shell):")
    print(f"  lxc-attach -n {name} -P {path}")
    print("")
    print("To connect (Console):")
    print(f"  lxc-console -n {name} -P {path}")
    print("-------------------------------------------------------")
