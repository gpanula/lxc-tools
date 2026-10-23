"""FastMCP server exposing lxc-tools as MCP tools for AI agents.

This module is a thin adapter over the existing ``lxc-tools`` CLI. It does not
import the LXC/ZFS/ACL backends directly; instead it invokes the installed
``lxc-tools`` console script via ``subprocess`` and maps exit codes to
structured tool results.

Running as a normal user, the CLI auto-elevates to root via ``sudo`` (re-exec)
and dispatches user-tier lifecycle operations with ``sudo -u <user>``, exactly
as documented in ``AGENT_SETUP.md``. This preserves the existing sudoers trust
model (``/etc/sudoers.d/lxc-automation``) without requiring a root daemon.

Run the server with::

    lxc-tools-mcp                 # console script (stdio transport)
    python -m lxc_tools.mcp_server
    fastmcp run lxc_tools.mcp_server
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from lxc_tools import lxc as lxc_backend
from lxc_tools.config import load_config

#: Name advertised to MCP clients.
SERVER_NAME = "lxc-tools"

#: Console script invoked for every lifecycle operation.
CLI_BINARY = "lxc-tools"

#: Default timeout (seconds) for a single CLI invocation. Long-running
#: operations (e.g. ``create``, which downloads a template and converts the
#: rootfs to ZFS) can exceed an MCP client's own request timeout; without a
#: bound here the server would block indefinitely and the client would sever
#: the connection, orphaning the server process. Override with the
#: ``LXC_MCP_TIMEOUT`` environment variable.
DEFAULT_CLI_TIMEOUT = 300


class MCPServerError(Exception):
    """Raised when the underlying CLI cannot be located or executed."""


@dataclass(frozen=True)
class CommandResult:
    """Captured result of a CLI invocation."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def summary(self) -> str:
        """Return a compact, agent-friendly rendering of the result."""
        if self.ok:
            return self.stdout.strip() or self.stderr.strip() or "(no output)"
        out = self.stdout.strip()
        err = self.stderr.strip()
        body = f"{out}\n{err}".strip() if out and err else (out or err or "(no output)")
        return f"Error (exit {self.returncode}):\n{body}"



def _resolve_cli() -> str:
    """Return the path to the ``lxc-tools`` console script."""
    path = shutil.which(CLI_BINARY)
    if path:
        return path
    raise MCPServerError(
        f"Could not locate the '{CLI_BINARY}' executable on PATH. "
        "Install lxc-tools (pip install -e .) and ensure it is on PATH."
    )


def _cli_timeout() -> float:
    """Return the CLI invocation timeout in seconds.

    Reads ``LXC_MCP_TIMEOUT`` (seconds) from the environment, falling back to
    ``DEFAULT_CLI_TIMEOUT``. A value <= 0 disables the timeout.
    """
    raw = os.environ.get("LXC_MCP_TIMEOUT")
    if raw is None or raw == "":
        return DEFAULT_CLI_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_CLI_TIMEOUT


def _run_cli(*args: str) -> CommandResult:
    """Run ``lxc-tools <args>`` and capture its output.

    A timeout bounds the call so a long-running operation (e.g. ``create``)
    cannot block the server indefinitely and orphan the process when the MCP
    client gives up waiting.
    """
    timeout = _cli_timeout()
    try:
        proc = subprocess.run(
            [_resolve_cli(), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout if timeout > 0 else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise MCPServerError(
            f"Command '{CLI_BINARY} {' '.join(args)}' timed out after "
            f"{timeout:.0f}s. Increase LXC_MCP_TIMEOUT to allow longer "
            "operations."
        ) from exc
    except OSError as exc:
        raise MCPServerError(f"Failed to execute '{CLI_BINARY}': {exc}") from exc
    return CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def _spawn_background(*args: str) -> tuple[str, str]:
    """Launch ``lxc-tools <args>`` detached and return ``(job_id, log_path)``.

    The process is fully detached (new session, stdio redirected to a log file)
    so it keeps running after the MCP tool returns. This lets long-running
    operations (e.g. ``create``) run without blocking the MCP client.
    """
    job_id = f"{int(time.time())}-{os.getpid()}"
    log_dir = Path(tempfile.gettempdir()) / "lxc-tools-mcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{job_id}.log"

    with open(log_path, "w", encoding="utf-8") as log:
        subprocess.Popen(
            [_resolve_cli(), *args],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    return job_id, str(log_path)


mcp = FastMCP(SERVER_NAME)


@mcp.tool()
def create_container(
    name: str,
    distro: str = "ubuntu",
    release: str = "lts",
    arch: str = "amd64",
    quota: Optional[str] = None,
    no_systemd: Optional[bool] = None,
    systemd: bool = False,
    mac: Optional[str] = None,
    install_sshd: bool = False,
    start_sshd: bool = False,
    ssh_key: Optional[str] = None,
    user: Optional[str] = None,
    sudo: bool = False,
    nopasswd_sudo: bool = False,
    allow_tcp_forwarding: bool = False,
    background: bool = False,
    dry_run: bool = False,
) -> str:
    """Create an unprivileged LXC container with ZFS backing and a secure bind mount.

    Args:
        name: Container name (alphanumeric, dots, underscores, dashes).
        distro: Distribution name (default: ubuntu).
        release: Release codename or 'lts' (default: lts).
        arch: Architecture (default: amd64).
        quota: ZFS disk quota, e.g. '20G' (default: 10G).
        no_systemd: Force the minimal init (brings up eth0 + DNS automatically).
            Defaults to auto: systemd-based distros (ubuntu, debian, rockylinux,
            almalinux) use the minimal init; alpine uses its own init.
        systemd: Force systemd as PID 1 (opt out of the default minimal init).
        mac: Static MAC address for eth0 (e.g. '02:16:3e:aa:bb:cc').
        install_sshd: Install openssh-server on first boot.
        start_sshd: Start sshd automatically on boot.
        ssh_key: Public SSH key to append to the default user's authorized_keys.
        user: Create a non-root user with this name (same across distros).
        sudo: Grant the created user sudo access.
        nopasswd_sudo: Grant the created user password-less sudo access.
        allow_tcp_forwarding: Configure sshd with 'AllowTcpForwarding yes'.
        background: Run the create in a detached background process and return
            immediately with a job id and log path. Useful because create can
            take minutes and exceed an MCP client's request timeout.
        dry_run: Preview actions without executing destructive steps.
    """
    # Always pass distro/release/arch positionally so a later quota never lands
    # in the wrong positional slot (the CLI's 4-arg shorthand treats a size in
    # the arch slot as a quota).
    argv = ["create", name, distro, release, arch]
    if quota:
        argv.append(quota)
    if systemd:
        argv.append("--systemd")
    elif no_systemd:
        argv.append("--no-systemd")
    if mac:
        argv.extend(["--mac", mac])
    if install_sshd:
        argv.append("--install-sshd")
    if start_sshd:
        argv.append("--start-sshd")
    if ssh_key:
        argv.extend(["--ssh-key", ssh_key])
    if user:
        argv.extend(["--user", user])
    if sudo:
        argv.append("--sudo")
    if nopasswd_sudo:
        argv.append("--nopasswd-sudo")
    if allow_tcp_forwarding:
        argv.append("--allow-tcp-forwarding")
    if dry_run:
        argv.append("--dry-run")

    if background:
        job_id, log_path = _spawn_background(*argv)
        return (
            f"Container creation '{name}' submitted in the background.\n"
            f"job_id: {job_id}\n"
            f"log:    {log_path}\n"
            f"Monitor progress with: tail -f {log_path}"
        )
    return _run_cli(*argv).summary()


@mcp.tool()
def start_container(name: str, dry_run: bool = False) -> str:
    """Start an LXC container.

    Args:
        name: Container name.
        dry_run: Preview actions without executing them.
    """
    argv = ["start", name]
    if dry_run:
        argv.append("--dry-run")
    return _run_cli(*argv).summary()


@mcp.tool()
def stop_container(name: str, kill: bool = False, dry_run: bool = False) -> str:
    """Stop an LXC container.

    Args:
        name: Container name.
        kill: Force immediate shutdown (hard kill).
        dry_run: Preview actions without executing them.
    """
    argv = ["stop", name]
    if kill:
        argv.append("--kill")
    if dry_run:
        argv.append("--dry-run")
    return _run_cli(*argv).summary()


@mcp.tool()
def restart_container(name: str, dry_run: bool = False) -> str:
    """Restart an LXC container (stop, then start).

    Args:
        name: Container name.
        dry_run: Preview actions without executing them.
    """
    argv = ["restart", name]
    if dry_run:
        argv.append("--dry-run")
    return _run_cli(*argv).summary()


@mcp.tool()
def list_containers(active: bool = False, stopped: bool = False) -> str:
    """List LXC containers.

    Regular users see their own unprivileged projects; root sees all privileged
    and unprivileged projects.

    Args:
        active: List only running containers.
        stopped: List only stopped containers.
    """
    argv = ["list"]
    if active:
        argv.append("--active")
    elif stopped:
        argv.append("--stopped")
    return _run_cli(*argv).summary()


@mcp.tool()
def remove_container(name: str, force: bool = False, dry_run: bool = False) -> str:
    """Safely remove an LXC container (stops, destroys, deletes dataset + project).

    Args:
        name: Container name.
        force: Skip the confirmation prompt. Use with caution.
        dry_run: Preview actions without executing destructive steps.
    """
    argv = ["remove", name]
    if force:
        argv.append("--force")
    if dry_run:
        argv.append("--dry-run")
    return _run_cli(*argv).summary()


@mcp.tool()
def container_info(name: str) -> str:
    """Return status information for a single LXC container (read-only).

    Reports name, state, IPv4, IPv6 and autostart. The container is located
    across the privileged tier and all user tiers.

    Args:
        name: Container name.
    """
    cfg = load_config()
    path = _find_container_path(cfg, name)
    if path is None:
        return f"Error: Container '{name}' not found in any path."
    cname, state, ipv4, ipv6, autostart = lxc_backend.container_info(path, name)
    return (
        f"name: {cname}\n"
        f"state: {state}\n"
        f"ipv4: {ipv4}\n"
        f"ipv6: {ipv6}\n"
        f"autostart: {autostart}"
    )


def _find_container_path(cfg, name: str) -> Optional[str]:
    """Locate a container across the privileged tier and all user tiers."""
    from pathlib import Path

    if (Path(cfg.priv_path) / name).is_dir():
        return cfg.priv_path
    base = Path(cfg.unpriv_base)
    if base.is_dir():
        for directory in sorted(base.iterdir()):
            if directory.is_dir() and (directory / name).is_dir():
                return str(directory)
    return None


@mcp.tool()
def config_dump() -> str:
    """Return the resolved lxc-tools configuration (read-only).

    Shows the ZFS pool, privileged/unprivileged paths, project directory and
    network bridge currently in effect.
    """
    cfg = load_config()
    return (
        f"zfs_pool: {cfg.zfs_pool}\n"
        f"priv_path: {cfg.priv_path}\n"
        f"unpriv_base: {cfg.unpriv_base}\n"
        f"project_dir: {cfg.project_dir}\n"
        f"bridge: {cfg.bridge}"
    )


@mcp.tool()
def list_templates(distro: Optional[str] = None) -> str:
    """List available OS templates and releases from the LXC download server.

    Args:
        distro: Optional filter by distribution name (e.g. 'alpine', 'ubuntu', 'debian').
    """
    templates = lxc_backend.list_templates(distro=distro)
    if not templates:
        msg = f"No templates found for distro '{distro}'." if distro else "No templates found."
        return msg
    lines = [f"{'DISTRO':<15} {'RELEASE':<15} {'ARCH':<10} {'VARIANT':<10}"]
    lines.append("-" * 55)
    for tpl in templates:
        lines.append(
            f"{tpl['distro']:<15} {tpl['release']:<15} {tpl['arch']:<10} {tpl['variant']:<10}"
        )
    return "\n".join(lines)


@mcp.tool()
def snapshot_container(

    name: str, tag: Optional[str] = None, dry_run: bool = False
) -> str:
    """Create a ZFS snapshot of an LXC container's rootfs.

    Args:
        name: Container name.
        tag: Snapshot tag (default: timestamp snap-YYYYMMDD-HHMMSS).
        dry_run: Preview actions without executing them.
    """
    argv = ["snapshot", name]
    if tag:
        argv.append(tag)
    if dry_run:
        argv.append("--dry-run")
    return _run_cli(*argv).summary()


@mcp.tool()
def rollback_container(
    name: str,
    tag: str,
    no_restart: bool = False,
    force: bool = True,
    dry_run: bool = False,
) -> str:
    """Roll back an LXC container's rootfs to a specified ZFS snapshot.

    If the container is currently running, stops it safely, rolls back, and
    restarts it automatically unless no_restart is True.

    Args:
        name: Container name.
        tag: Snapshot tag to roll back to.
        no_restart: Do not restart container if it was running.
        force: Skip confirmation prompt (default: True for non-interactive agents).
        dry_run: Preview actions without executing them.
    """
    argv = ["rollback", name, tag]
    if no_restart:
        argv.append("--no-restart")
    if force:
        argv.append("--force")
    if dry_run:
        argv.append("--dry-run")
    return _run_cli(*argv).summary()


@mcp.tool()
def list_snapshots(name: str) -> str:
    """List all available ZFS snapshots for an LXC container.

    Args:
        name: Container name.
    """
    argv = ["snapshots", name]
    return _run_cli(*argv).summary()


@mcp.tool()
def exec_container(
    name: str,
    command: str,
    snapshot: Optional[str] = None,
    no_snapshot: bool = False,
    dry_run: bool = False,
) -> str:
    """Execute a command inside a running LXC container as root.

    Args:
        name: Container name.
        command: Command string to execute inside the container (e.g. 'apk add git' or 'uname -a').
        snapshot: Custom tag for pre-execution snapshot (forces snapshot creation).
        no_snapshot: Explicitly skip taking a pre-execution snapshot.
        dry_run: Preview actions without executing them.
    """
    import shlex

    argv = ["exec", name]
    if no_snapshot:
        argv.append("--no-snapshot")
    elif snapshot:
        argv.extend(["--snapshot-tag", snapshot])
    if dry_run:
        argv.append("--dry-run")
    argv.append("--")
    argv.extend(shlex.split(command))
    return _run_cli(*argv).summary()


def main() -> None:
    """Entry point: run the FastMCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()


