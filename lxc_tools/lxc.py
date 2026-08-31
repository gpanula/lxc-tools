"""LXC backend.

Container lifecycle operations must run as the container's owning user so the
unprivileged / mapped-UID model is preserved. Because the lxc-tools CLI elevates
to root via auto-sudo, user-tier lifecycle operations are dispatched through
``sudo -u <user> <lxc-* CLI>`` -- identical to the legacy bash scripts.

The python3-lxc binding (``import lxc``) is used where the current process
already runs as the correct user and for read-oriented inspection: listing
containers, reading state, IPs and the autostart config. Two deliberate
subprocess escapes remain because the binding has no equivalent:

* ``lxc-create -t download -- --list``  -- release listing for LTS resolution
* ``lxc-stop -k``                       -- the binding exposes no hard-kill

Install the optional binding with::

    sudo apt install python3-lxc liblxc-dev        # system binding
    or inside the venv:  pip install lxc-python3
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
from typing import Optional

INSTALL_HINT = (
    "LXC Python bindings are optional for read/inspect paths. Install with:\n"
    "  sudo apt install python3-lxc liblxc-dev\n"
    "  or inside the venv:  pip install lxc-python3"
)


class LXCError(Exception):
    """Raised for LXC backend failures."""


def _load_lxc():
    """Import the python3-lxc binding, or return None if unavailable."""
    try:
        import lxc  # type: ignore

        return lxc
    except ImportError:
        return None


def run_as(
    user: Optional[str], argv: list[str], *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run ``argv``, optionally dropping to ``user`` via ``sudo -u``."""
    cmd = argv
    if user and user != "root" and os.geteuid() == 0:
        cmd = ["sudo", "-u", user, *argv]
    return subprocess.run(
        cmd, check=check, text=True, capture_output=True
    )


def _run(user: Optional[str], argv: list[str]) -> subprocess.CompletedProcess[str]:
    proc = run_as(user, argv)
    if proc.returncode != 0:
        raise LXCError(
            f"Command failed ({' '.join(argv)}):\n{proc.stderr.strip()}"
        )
    return proc


# -- lifecycle (dispatched via sudo -u to preserve the unprivileged model) -----

def create(
    name: str,
    path: str,
    distro: str,
    release: str,
    arch: str,
    user: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """Create an unprivileged container from the download template."""
    description = (
        f"Creating LXC container template '{name}' ({distro}/{release}/{arch}) "
        f"in {path}"
    )
    print(description)
    if dry_run:
        return
    _run(
        user,
        [
            "lxc-create", "-n", name, "-P", path, "-t", "download", "--",
            "-d", distro, "-r", release, "-a", arch,
        ],
    )


def start(
    name: str, path: str, user: Optional[str] = None, dry_run: bool = False
) -> None:
    """Start a container (as ``user`` when a privilege drop is required)."""
    if dry_run:
        return
    _run(user, ["lxc-start", "-n", name, "-P", path])


def stop(
    name: str,
    path: str,
    user: Optional[str] = None,
    kill: bool = False,
    dry_run: bool = False,
) -> None:
    """Stop a container. ``kill`` performs a hard shutdown via lxc-stop -k."""
    action = "killing" if kill else "stopping"
    print(f"{action.capitalize()} container '{name}'...")
    if dry_run:
        return
    argv = ["lxc-stop", "-n", name, "-P", path]
    if kill:
        argv.append("-k")
    _run(user, argv)


def destroy(
    name: str, path: str, user: Optional[str] = None, dry_run: bool = False
) -> None:
    """Destroy a container (as ``user`` when a privilege drop is required)."""
    print(f"Destroying LXC container '{name}'...")
    if dry_run:
        return
    _run(user, ["lxc-destroy", "-n", name, "-P", path])


def info(name: str, path: str, user: Optional[str] = None) -> str:
    """Return ``lxc-info`` output for verification/display."""
    proc = run_as(user, ["lxc-info", "-n", name, "-P", path])
    if proc.returncode != 0:
        raise LXCError(f"lxc-info failed for '{name}':\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def execute(
    name: str,
    path: str,
    command: list[str],
    dry_run: bool = False,
) -> tuple[int, str, str]:
    """Execute a command inside the container via lxc-attach.

    Returns (returncode, stdout, stderr).
    """
    if dry_run:
        print(f"[dry-run] would run in container '{name}': {' '.join(command)}")
        return 0, "", ""
    proc = subprocess.run(
        ["lxc-attach", "-n", name, "-P", path, "--", *command],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr



# -- inspection (native binding preferred, CLI fallback) -----------------------

def list_names(path: str) -> list[str]:
    """Return container names in ``path``."""
    lxc_mod = _load_lxc()
    if lxc_mod is not None:
        try:
            return sorted(lxc_mod.list_containers(config_path=path))
        except Exception:
            pass
    proc = _run(None, ["lxc-ls", "-1", "-P", path])
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def container_info(path: str, name: str) -> tuple[str, str, str, str, str]:
    """Return (name, state, ipv4, ipv6, autostart) for a container."""
    lxc_mod = _load_lxc()
    if lxc_mod is not None:
        try:
            container = lxc_mod.Container(name, path)
            ipv4 = ",".join(container.get_ips(family=socket.AF_INET))
            ipv6 = ",".join(container.get_ips(family=socket.AF_INET6))
            try:
                autostart = container.get_config_item("lxc.start.auto") or "0"
            except Exception:
                autostart = "0"
            return name, container.state, ipv4, ipv6, autostart
        except Exception:
            pass
    proc = _run(
        None,
        ["lxc-ls", "-f", "-P", path, "-F", "NAME,STATE,IPV4,IPV6,AUTOSTART"],
    )
    for line in proc.stdout.splitlines():
        columns = line.split()
        if columns and columns[0] == name:
            if len(columns) >= 5:
                return columns[0], columns[1], columns[2], columns[3], columns[4]
            return name, columns[1] if len(columns) > 1 else "UNKNOWN", "", "", ""
    return name, "UNKNOWN", "", "", ""


def list_download_releases(
    distro: str, user: Optional[str] = None
) -> list[str]:
    """Return available numerical releases for ``distro`` from the download template."""
    proc = run_as(
        user,
        [
            "lxc-create", "-n", f"lts_lookup_{os.getpid()}", "-P", "/tmp",
            "-t", "download", "--", "--list",
        ],
    )
    releases: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == distro:
            if re.fullmatch(r"[0-9.]+", parts[1]):
                releases.append(parts[1])
    return releases


def list_templates(
    distro: Optional[str] = None, user: Optional[str] = None
) -> list[dict[str, str]]:
    """Return list of available templates from the download backend."""
    proc = run_as(
        user,
        [
            "lxc-create", "-n", f"tpl_lookup_{os.getpid()}", "-P", "/tmp",
            "-t", "download", "--", "--list",
        ],
    )
    results: list[dict[str, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] not in ("---", "DIST"):
            d, r, a, v = parts[0], parts[1], parts[2], parts[3]
            if distro and d.lower() != distro.lower():
                continue
            results.append({
                "distro": d,
                "release": r,
                "arch": a,
                "variant": v,
                "build": parts[4] if len(parts) > 4 else "",
            })
    return results


