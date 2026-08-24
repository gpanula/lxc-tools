"""LTS release resolution for the supported distributions.

``ubuntu`` and ``debian`` prefer the ``python3-distro-info`` module and fall
back to the ``ubuntu-distro-info`` / ``debian-distro-info`` CLIs. ``alpine``,
``rockylinux`` and ``almalinux`` resolve to the highest numerical release
advertised by the LXC download template.
"""

from __future__ import annotations

import subprocess
from typing import Optional

from lxc_tools import lxc as lxc_backend

_UBUNTU_FALLBACK = "jammy"
_DEBIAN_FALLBACK = "bookworm"


def _run_cli(cli: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [cli, *args], capture_output=True, text=True, check=False
    )


def _ubuntu_lts_python() -> Optional[str]:
    try:
        from distro_info import UbuntuDistroInfo  # type: ignore

        lts = UbuntuDistroInfo().lts()
        return lts[-1] if lts else None
    except Exception:
        return None


def _debian_stable_python() -> Optional[str]:
    try:
        from distro_info import DebianDistroInfo  # type: ignore

        return DebianDistroInfo().stable()
    except Exception:
        return None


def _ubuntu_lts_cli() -> Optional[str]:
    proc = _run_cli("ubuntu-distro-info", ["--lts"])
    if proc.returncode == 0:
        return proc.stdout.strip() or None
    return None


def _debian_stable_cli() -> Optional[str]:
    proc = _run_cli("debian-distro-info", ["--stable"])
    if proc.returncode == 0:
        return proc.stdout.strip() or None
    return None


def _version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def resolve_lts(
    distro: str, release: str, run_as_user: Optional[str] = None
) -> str:
    """Resolve the ``lts`` keyword to a concrete release for ``distro``."""
    if release.lower() != "lts":
        return release

    print(f"Resolving 'lts' for {distro}...")

    if distro == "ubuntu":
        resolved = _ubuntu_lts_python() or _ubuntu_lts_cli() or _UBUNTU_FALLBACK
    elif distro == "debian":
        resolved = _debian_stable_python() or _debian_stable_cli() or _DEBIAN_FALLBACK
    elif distro in ("alpine", "rockylinux", "almalinux"):
        releases = lxc_backend.list_download_releases(distro, user=run_as_user)
        resolved = max(releases, key=_version_key) if releases else "latest"
    else:
        resolved = release

    print(f"Resolved 'lts' to: {resolved}")
    return resolved
