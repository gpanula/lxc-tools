"""POSIX ACL operations backed by pylibacl (``import posix1e``).

Install::

    sudo apt install libacl1-dev
    pip install pylibacl

Implementation notes:

* ACL text is read, edited and re-applied so only the target user entry is
  added/modified while all other entries are preserved (setfacl ``-m``
  semantics). The mask is recomputed as the union of named entries, matching
  setfacl's automatic mask adjustment.
* Default ACLs are seeded from the access ACL so they always contain the
  required base entries (user/group/other), mirroring ``setfacl -d -m``.
* Recursive operations walk the tree with ``os.walk``; default ACLs are applied
  to directories only (they are meaningless on regular files).
"""

from __future__ import annotations

import os
from pathlib import Path

INSTALL_HINT = (
    "POSIX ACL support requires pylibacl. Install with:\n"
    "  sudo apt install libacl1-dev\n"
    "  pip install pylibacl"
)


class ACLError(Exception):
    """Raised for ACL backend failures."""


def _load_posix1e():
    try:
        import posix1e  # type: ignore

        return posix1e
    except ImportError:
        raise ACLError(INSTALL_HINT)


def _acl_type(posix1e, default: bool) -> object:
    """Return the ACL type constant, preferring the ``ACL_TYPE_*`` API."""
    name = "ACL_TYPE_DEFAULT" if default else "ACL_TYPE_ACCESS"
    acl_type = getattr(posix1e, name, None)
    return acl_type


def _read_text(path: Path, default: bool) -> str:
    posix1e = _load_posix1e()
    acl_type = _acl_type(posix1e, default)
    try:
        if acl_type is not None:
            acl = posix1e.ACL(file=str(path), type=acl_type)
        else:  # older pylibacl API without ACL_TYPE_* constants
            acl = posix1e.ACL(file=str(path), default=default)
        return str(acl)
    except Exception:
        # Missing ACL, unsupported type kwarg, or unreadable path.
        return ""


def _apply_text(path: Path, text: str, default: bool) -> None:
    posix1e = _load_posix1e()
    acl_type = _acl_type(posix1e, default)
    try:
        acl = posix1e.ACL(text=text)
        if acl_type is not None:
            acl.applyto(str(path), acl_type)
        else:
            acl.applyto(str(path))
    except Exception as exc:
        raise ACLError(f"Failed to apply ACL to {path}: {exc}") from exc


def _normalize_perms(perms: str) -> str:
    """Return a canonical three-character permset.

    POSIX ACL text requires one of ``rwx`` (present) or ``-`` (absent) for
    each of read/write/execute, e.g. ``'x'`` -> ``'--x'``, ``'rx'`` -> ``'r-x'``.
    """
    return "".join(c if c in perms else "-" for c in "rwx")


def _parse_entries(text: str) -> dict[tuple[str, str], str]:
    entries: dict[tuple[str, str], str] = {}
    for line in text.splitlines():
        parts = line.strip().split(":")
        # Valid setfacl-style lines have exactly three parts, e.g.:
        #   user::rwx | user:1000:rwx | group::r-x | group:1000:r-- | mask::rwx
        if len(parts) != 3:
            continue
        tag, qual, perms = (part.strip() for part in parts)
        if not tag or not perms:
            continue
        entries[(tag, qual)] = _normalize_perms(perms)
    return entries


_TAG_RANK = {"user": 0, "group": 1, "mask": 2, "other": 3}


def _serialize_entries(entries: dict[tuple[str, str], str]) -> str:
    def sort_key(item: tuple[tuple[str, str], str]) -> tuple[int, int]:
        tag, qual = item[0]
        return (_TAG_RANK.get(tag, 9), int(qual) if qual else -1)

    lines = []
    for (tag, qual), perms in sorted(entries.items(), key=sort_key):
        if qual:
            lines.append(f"{tag}:{qual}:{perms}")
        else:
            lines.append(f"{tag}::{perms}")
    return "\n".join(lines)


def _recompute_mask(entries: dict[tuple[str, str], str]) -> None:
    named = [
        perms
        for (tag, qual), perms in entries.items()
        if qual and tag in ("user", "group")
    ]
    if not named:
        return
    # The mask is the union of the named entries, expressed as a canonical
    # three-character permset with '-' placeholders.
    mask = "".join(
        perm if any(perm in value for value in named) else "-" for perm in "rwx"
    )
    entries[("mask", "")] = mask


def has_user_execute(path: Path, uid: int) -> bool:
    """Return True if ``uid`` already has an execute bit in the access ACL."""
    entries = _parse_entries(_read_text(path, default=False))
    perms = entries.get(("user", str(uid)), "")
    return "x" in perms


def ensure_user_acl(path: Path, uid: int, perms: str = "rwx") -> None:
    """Add or modify a named user entry in the access ACL of ``path``."""
    entries = _parse_entries(_read_text(path, default=False))
    entries[("user", str(uid))] = _normalize_perms(perms)
    _recompute_mask(entries)
    _apply_text(path, _serialize_entries(entries), default=False)


def set_user_acl_recursive(root: Path, uid: int, perms: str = "rwx") -> None:
    """Apply an access ACL to ``root`` and every entry beneath it."""
    for current, _dirs, files in os.walk(root):
        ensure_user_acl(Path(current), uid, perms)
        for name in files:
            ensure_user_acl(Path(current) / name, uid, perms)


def set_default_acl_recursive(root: Path, uid: int, perms: str = "rwx") -> None:
    """Apply a default ACL to every directory beneath (and including) ``root``."""
    for current, dirs, _files in os.walk(root):
        _ensure_default_acl(Path(current), uid, perms)
        for name in dirs:
            _ensure_default_acl(Path(current) / name, uid, perms)


def _ensure_default_acl(path: Path, uid: int, perms: str = "rwx") -> None:
    # Seed the default ACL from the access ACL so the base entries (user_obj,
    # group_obj, other) are always present -- this is what setfacl -d does.
    entries = _parse_entries(_read_text(path, default=False))
    entries[("user", str(uid))] = _normalize_perms(perms)
    _recompute_mask(entries)
    _apply_text(path, _serialize_entries(entries), default=True)
