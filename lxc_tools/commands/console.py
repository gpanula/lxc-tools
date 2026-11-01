"""lxc-tools console: attach to a container's console via lxc-console.

The console is the out-of-band path into a container whose networking or sshd
is broken. It requires ``lxc.tty.max`` in the container config; without it
``lxc-console`` fails with an opaque error, so this command checks first.
"""

from __future__ import annotations

from pathlib import Path

from lxc_tools import lxc as lxc_backend, prereq
from lxc_tools.commands import (
    common_parser,
    guarded,
    resolve_running_container,
    validate,
)
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("lxc-console", "lxc-info")


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "console",
        parents=[common_parser()],
        help="Attach to a running container's console.",
        description=(
            "Attaches to the container console via lxc-console. Useful when "
            "SSH is unavailable. Requires 'lxc.tty.max' in the container config."
        ),
    )
    parser.add_argument(
        "container_name",
        metavar="container_name",
        help="Name of the running container.",
    )
    parser.add_argument(
        "-t",
        "--tty",
        type=int,
        default=None,
        metavar="N",
        help="Console tty number (default: 0).",
    )
    parser.set_defaults(func=run)


def _require_tty_configured(name: str, path: str) -> None:
    """Assert the container config declares ``lxc.tty.max``."""
    config_file = Path(path) / name / "config"
    try:
        content = config_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise prereq.PrereqError(
            f"Error: Could not read container config {config_file}: {exc}"
        ) from exc
    if "lxc.tty.max" not in content:
        raise prereq.PrereqError(
            f"Error: Container '{name}' has no console tty configured.\n"
            f"Add 'lxc.tty.max = 4' to {config_file} and restart the container."
        )


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
    _require_tty_configured(name, path)

    return lxc_backend.console(
        name, path, tty=args.tty, dry_run=args.dry_run
    )
