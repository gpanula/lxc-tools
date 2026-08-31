"""Runtime prerequisites: privilege elevation, identity, group gate and
dependency assertions.

This module replaces the repeated boilerplate from the legacy bash scripts:

* auto-sudo re-exec (``exec sudo "$0" "$@"``)
* ``CURRENT_USER`` resolution from ``$SUDO_USER``
* the ``lxc-users`` group membership gate
* dependency checks with actionable install hints
"""

from __future__ import annotations

import getpass
import grp
import os
import pwd
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

LXC_USERS_GROUP = "lxc-users"


class PrereqError(Exception):
    """Raised when a runtime prerequisite is not satisfied."""


def ensure_root_or_reexec(argv: list[str] | None = None) -> None:
    """Re-exec via sudo if the process is not already running as root.

    Mirrors the legacy ``exec sudo "$0" "$@"`` behaviour. The exact command the
    user invoked is preserved so the console-script path is reused by sudo.
    """
    if os.geteuid() == 0:
        return
    command = argv if argv is not None else sys.argv
    try:
        os.execvp("sudo", ["sudo", *command])
    except OSError as exc:  # pragma: no cover - execvp only returns on failure
        raise PrereqError(f"Could not re-execute via sudo: {exc}") from exc
    raise PrereqError("Failed to re-execute via sudo.")  # pragma: no cover




def resolve_current_user() -> str:
    """Return the effective acting user.

    After ``sudo`` elevates the process to root, ``SUDO_USER`` identifies the
    caller; when run without sudo this falls back to the invoking user.
    """
    return os.environ.get("SUDO_USER") or getpass.getuser()


def effective_user() -> str:
    """Return the name of the effective uid (matches ``whoami`` semantics)."""
    return pwd.getpwuid(os.geteuid()).pw_name


@dataclass(frozen=True)
class UserInfo:
    name: str
    uid: int
    gid: int
    home: str


def get_user_info(username: str) -> UserInfo:
    """Look up passwd metadata for a user."""
    try:
        pw = pwd.getpwnam(username)
    except KeyError as exc:
        raise PrereqError(f"Error: Unknown user '{username}'.") from exc
    return UserInfo(name=pw.pw_name, uid=pw.pw_uid, gid=pw.pw_gid, home=pw.pw_dir)


def require_member_of(username: str, group: str = LXC_USERS_GROUP) -> None:
    """Require ``username`` to be a member of ``group`` unless it is root."""
    if username == "root":
        return
    try:
        members = grp.getgrnam(group).gr_mem
    except KeyError as exc:
        raise PrereqError(f"Error: Group '{group}' does not exist.") from exc
    if username not in members:
        raise PrereqError(
            f"Error: User '{username}' is not a member of the '{group}' group."
        )


BINARY_HINTS = {
    "lxc-create": "sudo apt update && sudo apt install lxc",
    "lxc-ls": "sudo apt update && sudo apt install lxc",
    "lxc-start": "sudo apt update && sudo apt install lxc",
    "lxc-stop": "sudo apt update && sudo apt install lxc",
    "lxc-destroy": "sudo apt update && sudo apt install lxc",
    "lxc-info": "sudo apt update && sudo apt install lxc",
    "zfs": "sudo apt update && sudo apt install zfsutils-linux",
    "setfacl": "sudo apt update && sudo apt install acl",
    "getfacl": "sudo apt update && sudo apt install acl",
    "newuidmap": "sudo apt update && sudo apt install uidmap",
    "newgidmap": "sudo apt update && sudo apt install uidmap",
    "ubuntu-distro-info": "sudo apt update && sudo apt install distro-info",
    "debian-distro-info": "sudo apt update && sudo apt install distro-info",
}


def _is_executable(path: str | None) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def require_binaries(names: Iterable[str]) -> None:
    """Assert required binaries exist and are executable, with install hints."""
    missing = [name for name in names if not _is_executable(shutil.which(name))]
    if not missing:
        return
    hints = "\n".join(
        f"  {name}: {BINARY_HINTS.get(name, 'install the matching system package')}"
        for name in missing
    )
    raise PrereqError("Error: Required tools are missing.\n" + hints)


def read_subid_map(filename: str, username: str) -> tuple[int, int]:
    """Read ``<username>:<start>:<range>`` from /etc/subuid or /etc/subgid."""
    try:
        with open(filename, "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.strip().split(":")
                if len(parts) == 3 and parts[0] == username:
                    return int(parts[1]), int(parts[2])
    except OSError as exc:
        raise PrereqError(f"Error: Could not read {filename}: {exc}") from exc
    raise PrereqError(
        f"Error: No id mapping found for user '{username}' in {filename}."
    )


def dry_or(
    dry_run: bool,
    description: str,
    func: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> object:
    """Invoke ``func`` unless dry-run is active; always report the action."""
    print(description)
    if dry_run:
        return None
    return func(*args, **kwargs)


def write_file_owned(
    path: Path, content: str, uid: int, gid: int, mode: int
) -> None:
    """Write ``content`` to ``path`` then chown/chmod to the owning user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chown(path, uid, gid)
    os.chmod(path, mode)
