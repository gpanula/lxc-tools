"""Shared helpers for the lxc-tools subcommands."""

from __future__ import annotations

import argparse
import functools
import re
import subprocess
import sys
from pathlib import Path

from lxc_tools import acl, lxc, prereq, zfs
from lxc_tools.config import Config, ConfigError

VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
SIZE_RE = re.compile(r"^[0-9]+[KkMmGgTtPpEe]([iI][bB])?$")

KNOWN_ERRORS = (
    prereq.PrereqError,
    zfs.ZFSError,
    lxc.LXCError,
    acl.ACLError,
    ConfigError,
    ValueError,
    subprocess.SubprocessError,
)


def validate(value: str, param: str) -> None:
    """Validate a user-supplied parameter against the safe-name pattern."""
    if not VALID_NAME_RE.fullmatch(value):
        raise prereq.PrereqError(
            f"Error: Parameter '{param}' ('{value}') contains invalid characters.\n"
            "Allowed: alphanumeric characters, dots, underscores, and dashes."
        )


def find_container_path(cfg: Config, name: str) -> str | None:
    """Locate a container across the privileged tier and all user tiers."""
    if (Path(cfg.priv_path) / name).is_dir():
        return cfg.priv_path
    base = Path(cfg.unpriv_base)
    if base.is_dir():
        for directory in sorted(base.iterdir()):
            if directory.is_dir() and (directory / name).is_dir():
                return str(directory)
    return None


def common_parser() -> argparse.ArgumentParser:
    """Argument parser shared by every subcommand (adds ``--dry-run``)."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Print the actions that would be taken without executing them.",
    )
    return parent


def guarded(func):
    """Run a subcommand handler and convert known errors to exit code 1."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KNOWN_ERRORS as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    return wrapper
