"""lxc-tools list: list LXC projects.

Regular users list their own unprivileged projects. Root lists all privileged
and unprivileged projects on the system. ``--active`` / ``--stopped`` filter
the output. This subcommand does not auto-elevate (matching ``whoami``
semantics of the legacy script).
"""

from __future__ import annotations

from pathlib import Path

from lxc_tools import lxc as lxc_backend, prereq
from lxc_tools.commands import common_parser, guarded
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("lxc-ls",)


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "list",
        parents=[common_parser()],
        help="List LXC projects.",
        description=(
            "Lists LXC projects. Regular users list their own unprivileged "
            "projects; root lists ALL privileged and unprivileged projects."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--active", "-a", action="store_true",
        help="List only active (running) containers.",
    )
    group.add_argument(
        "--stopped", "-s", action="store_true",
        help="List only stopped containers.",
    )
    parser.set_defaults(func=run)


@guarded
def run(args) -> int:
    require_binaries(_BINARIES)
    cfg = load_config()
    user = prereq.effective_user()

    if user == "root":
        print("--- [System Tier] Privileged Containers ---")
        _print_tier(cfg.priv_path, args)
        print("")
        print("--- [User Tier] Unprivileged Containers ---")
        found_any = False
        base = Path(cfg.unpriv_base)
        if base.is_dir():
            for user_dir in sorted(base.iterdir()):
                if not user_dir.is_dir():
                    continue
                if not any(user_dir.iterdir()):
                    continue
                print(f"User: {user_dir.name}")
                _print_tier(str(user_dir), args)
                print("")
                found_any = True
        if not found_any:
            print("No unprivileged containers found.")
    else:
        require_member_of(user)
        path = f"{cfg.unpriv_base}/{user}"
        if not Path(path).is_dir():
            print(f"No projects found for user '{user}' (LXC path missing).")
            return 0
        print(f"--- Unprivileged Projects for {user} ---")
        print(f"LXC Path: {path}")
        print("")
        _print_tier(path, args)

    print("")
    print(f"Note: Associated host project folders are located in {cfg.project_dir}/")
    print("-------------------------------------------------------")
    print("QUICK COMMANDS:")
    print("  Start:   lxc-tools start <name>")
    print("  Stop:    lxc-tools stop <name>")
    print("  Restart: lxc-tools restart <name>")
    print("  Connect: sudo lxc-attach -n <name> -P <path>")

    print("  Remove:  lxc-tools remove <name>")
    print("-------------------------------------------------------")
    return 0


def _print_tier(path, args) -> None:
    if not Path(path).is_dir():
        print("None found or path missing.")
        return
    names = lxc_backend.list_names(path)
    if not names:
        print("None found or path missing.")
        return
    print("NAME STATE IPV4 IPV6 AUTOSTART")
    for name in names:
        cname, state, ipv4, ipv6, autostart = lxc_backend.container_info(path, name)
        if args.active and state != "RUNNING":
            continue
        if args.stopped and state == "RUNNING":
            continue
        print(f"{cname} {state} {ipv4} {ipv6} {autostart}")
