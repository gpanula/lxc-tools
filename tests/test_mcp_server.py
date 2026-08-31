"""Tests for the FastMCP server adapter (lxc_tools.mcp_server).

These tests are pure-logic: they verify CLI argument construction, result
rendering and error handling by mocking ``subprocess.run`` and ``shutil.which``.
No LXC/ZFS/ACL bindings or root privileges are required.
"""

from __future__ import annotations

import subprocess

import pytest

from lxc_tools import mcp_server
from lxc_tools.mcp_server import (
    MCPServerError,
    _resolve_cli,
    _run_cli,
    config_dump,
    container_info,
    create_container,
    list_containers,
    remove_container,
    restart_container,
    start_container,
    stop_container,
)


class FakeProc:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def fake_cli(monkeypatch):
    """Point _resolve_cli at a fake binary and capture invocations."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return FakeProc(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(mcp_server, "_resolve_cli", lambda: "/usr/local/bin/lxc-tools")
    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_resolve_cli_missing(monkeypatch):
    monkeypatch.setattr(
        mcp_server, "shutil", type("S", (), {"which": lambda *_: None})()
    )
    with pytest.raises(MCPServerError):
        _resolve_cli()


def test_run_cli_ok(fake_cli):
    result = _run_cli("list")
    assert result.ok
    assert result.summary() == "ok"
    assert fake_cli == [["/usr/local/bin/lxc-tools", "list"]]


def test_run_cli_error_renders_exit_code(fake_cli):
    fake_cli.clear()
    mcp_server.subprocess.run = lambda argv, **kw: FakeProc(
        returncode=1, stdout="", stderr="boom"
    )
    result = _run_cli("start", "x")
    assert not result.ok
    assert "Error (exit 1)" in result.summary()
    assert "boom" in result.summary()


def test_create_container_defaults(fake_cli):
    out = create_container("my-app")
    assert out == "ok"
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "create", "my-app", "ubuntu", "lts", "amd64"]
    ]


def test_create_container_full_args(fake_cli):
    create_container("my-app", distro="debian", release="lts", arch="amd64", quota="20G")
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "create", "my-app", "debian", "lts", "amd64", "20G"]
    ]


def test_create_container_quota_without_arch(fake_cli):
    # A quota must never land in the release/arch positional slot.
    create_container("my-app", distro="debian", quota="20G")
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "create", "my-app", "debian", "lts", "amd64", "20G"]
    ]


def test_create_container_dry_run(fake_cli):
    create_container("my-app", dry_run=True)
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "create", "my-app", "ubuntu", "lts", "amd64", "--dry-run"]
    ]


def test_start_container(fake_cli):
    start_container("my-app")
    assert fake_cli == [["/usr/local/bin/lxc-tools", "start", "my-app"]]


def test_stop_container_kill(fake_cli):
    stop_container("my-app", kill=True)
    assert fake_cli == [["/usr/local/bin/lxc-tools", "stop", "my-app", "--kill"]]


def test_restart_container_dry_run(fake_cli):
    restart_container("my-app", dry_run=True)
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "restart", "my-app", "--dry-run"]
    ]


def test_list_containers_active(fake_cli):
    list_containers(active=True)
    assert fake_cli == [["/usr/local/bin/lxc-tools", "list", "--active"]]


def test_list_containers_stopped(fake_cli):
    list_containers(stopped=True)
    assert fake_cli == [["/usr/local/bin/lxc-tools", "list", "--stopped"]]


def test_list_containers_plain(fake_cli):
    list_containers()
    assert fake_cli == [["/usr/local/bin/lxc-tools", "list"]]


def test_remove_container_force(fake_cli):
    remove_container("my-app", force=True)
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "remove", "my-app", "--force"]
    ]


def test_remove_container_dry_run(fake_cli):
    remove_container("my-app", dry_run=True)
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "remove", "my-app", "--dry-run"]
    ]


def test_container_info_not_found(monkeypatch):
    monkeypatch.setattr(
        mcp_server, "load_config", lambda: type("C", (), {
            "priv_path": "/rpool/lxc/privileged",
            "unpriv_base": "/rpool/lxc/unprivileged",
        })()
    )
    monkeypatch.setattr(
        mcp_server, "_find_container_path", lambda cfg, name: None
    )
    assert "not found" in container_info("ghost")


def test_container_info_found(monkeypatch):
    monkeypatch.setattr(
        mcp_server, "load_config", lambda: type("C", (), {
            "priv_path": "/rpool/lxc/privileged",
            "unpriv_base": "/rpool/lxc/unprivileged",
        })()
    )
    monkeypatch.setattr(
        mcp_server, "_find_container_path", lambda cfg, name: "/rpool/lxc/privileged"
    )
    monkeypatch.setattr(
        mcp_server.lxc_backend,
        "container_info",
        lambda path, name: ("my-app", "RUNNING", "10.0.3.5", "", "1"),
    )
    out = container_info("my-app")
    assert "state: RUNNING" in out
    assert "ipv4: 10.0.3.5" in out


def test_config_dump(monkeypatch):
    monkeypatch.setattr(
        mcp_server, "load_config", lambda: type("C", (), {
            "zfs_pool": "mypool",
            "priv_path": "/mypool/lxc/privileged",
            "unpriv_base": "/mypool/lxc/unprivileged",
            "project_dir": "/opt/project",
            "bridge": "lxcbr0",
        })()
    )
    out = config_dump()
    assert "zfs_pool: mypool" in out
    assert "bridge: lxcbr0" in out


def test_list_templates(monkeypatch):
    monkeypatch.setattr(
        mcp_server.lxc_backend,
        "list_templates",
        lambda distro=None: [
            {"distro": "alpine", "release": "3.21", "arch": "amd64", "variant": "default", "build": "20260830"}
        ],
    )
    out = mcp_server.list_templates()
    assert "alpine" in out
    assert "3.21" in out


def test_list_templates_empty(monkeypatch):
    monkeypatch.setattr(
        mcp_server.lxc_backend,
        "list_templates",
        lambda distro=None: [],
    )
    out = mcp_server.list_templates(distro="unknown")
    assert "No templates found for distro 'unknown'." in out


def test_snapshot_container(fake_cli):
    mcp_server.snapshot_container("my-app", tag="pre-update")
    assert fake_cli == [["/usr/local/bin/lxc-tools", "snapshot", "my-app", "pre-update"]]


def test_rollback_container(fake_cli):
    mcp_server.rollback_container("my-app", tag="pre-update", no_restart=True, force=True)
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "rollback", "my-app", "pre-update", "--no-restart", "--force"]
    ]


def test_list_snapshots(fake_cli):
    mcp_server.list_snapshots("my-app")
    assert fake_cli == [["/usr/local/bin/lxc-tools", "snapshots", "my-app"]]


def test_exec_container_default(fake_cli):
    mcp_server.exec_container("my-app", "apk add curl")
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "exec", "my-app", "--", "apk", "add", "curl"]
    ]


def test_exec_container_no_snapshot(fake_cli):
    mcp_server.exec_container("my-app", "whoami", no_snapshot=True)
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "exec", "my-app", "--no-snapshot", "--", "whoami"]
    ]


def test_exec_container_custom_tag(fake_cli):
    mcp_server.exec_container("my-app", "apk add git", snapshot="before-git")
    assert fake_cli == [
        ["/usr/local/bin/lxc-tools", "exec", "my-app", "--snapshot-tag", "before-git", "--", "apk", "add", "git"]
    ]



