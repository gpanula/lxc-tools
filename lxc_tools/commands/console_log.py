"""lxc-tools console-log: read a container's captured init/console output.

When a container's init dies, the container simply reports STOPPED with no
trace. ``lxc.console.logfile`` captures PID 1 stdout/stderr so the failure is
diagnosable after the fact. This command reads that file.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from lxc_tools import prereq
from lxc_tools.commands import (
    common_parser,
    guarded,
    resolve_container_path,
    validate,
)
from lxc_tools.config import load_config
from lxc_tools.prereq import require_member_of

#: Default number of trailing lines to print.
DEFAULT_LINES = 100


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "console-log",
        parents=[common_parser()],
        help="Read a container's captured console/init output.",
        description=(
            "Prints the container's console log (lxc.console.logfile), which "
            "captures PID 1 stdout/stderr. Use --follow to stream it live."
        ),
    )
    parser.add_argument(
        "container_name",
        metavar="container_name",
        help="Name of the container.",
    )
    parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=DEFAULT_LINES,
        metavar="N",
        help=f"Number of trailing lines to print (default: {DEFAULT_LINES}).",
    )
    parser.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="Keep the file open and print appended output as it arrives.",
    )
    parser.set_defaults(func=run)


def _console_log_path(path: str, name: str) -> Path:
    """Return the console log path for a container.

    The path is read from ``lxc.console.logfile`` in the container config,
    because LXC resolves a relative value against the *caller's* working
    directory rather than the container directory. Reading the configured
    value is the only reliable way to find the log.
    """
    config_file = Path(path) / name / "config"
    try:
        for line in config_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("lxc.console.logfile"):
                _, _, value = stripped.partition("=")
                value = value.strip()
                if value:
                    candidate = Path(value)
                    if not candidate.is_absolute():
                        candidate = Path(path) / name / candidate
                    return candidate
    except OSError:
        pass
    # Fall back to the conventional location next to the container config.
    return Path(path) / name / "console.log"


def _tail(path: Path, lines: int) -> list[str]:
    """Return the last ``lines`` lines of ``path``."""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.readlines()[-lines:] if lines > 0 else []


@guarded
def run(args) -> int:
    user = prereq.resolve_current_user()
    require_member_of(user)
    cfg = load_config()

    name = args.container_name
    validate(name, "container_name")

    path = resolve_container_path(cfg, name, user)
    log_path = _console_log_path(path, name)

    if not log_path.is_file():
        raise prereq.PrereqError(
            f"Error: No console log for container '{name}' at {log_path}.\n"
            "The container may predate console capture. Add these to its config\n"
            "and restart it:\n"
            "  lxc.console.logfile = console.log\n"
            "  lxc.console.size = 4M\n"
            "  lxc.console.rotate = 1\n"
            "  lxc.tty.max = 4"
        )

    for line in _tail(log_path, args.lines):
        sys.stdout.write(line)
    sys.stdout.flush()

    if not args.follow:
        return 0

    # Follow mode: poll for appended data. A simple poll loop avoids the
    # inode-tracking complexity of tail -F while remaining adequate for a
    # log that only rotates on container restart.
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, 2)
        try:
            while True:
                chunk = handle.read()
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            return 0
