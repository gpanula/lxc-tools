"""Tests for lxc_tools.lxc backend."""

from __future__ import annotations

from types import SimpleNamespace

from lxc_tools import lxc


def _fake_proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_as_adds_sudo_prefix_when_root(monkeypatch):
    captured = {}

    def fake_run(cmd, check=False, text=True, capture_output=True):
        captured["cmd"] = cmd
        return _fake_proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("os.geteuid", lambda: 0)

    lxc.run_as("alice", ["lxc-start", "-n", "c", "-P", "/p"])
    assert captured["cmd"] == [
        "sudo", "-u", "alice", "lxc-start", "-n", "c", "-P", "/p",
    ]


def test_run_as_no_prefix_when_not_root(monkeypatch):
    captured = {}

    def fake_run(cmd, check=False, text=True, capture_output=True):
        captured["cmd"] = cmd
        return _fake_proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("os.geteuid", lambda: 1000)

    lxc.run_as(None, ["lxc-ls", "-1"])
    assert captured["cmd"] == ["lxc-ls", "-1"]


def test_run_as_skips_prefix_for_root_user(monkeypatch):
    captured = {}

    def fake_run(cmd, check=False, text=True, capture_output=True):
        captured["cmd"] = cmd
        return _fake_proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("os.geteuid", lambda: 0)

    lxc.run_as("root", ["lxc-ls", "-1"])
    assert captured["cmd"] == ["lxc-ls", "-1"]


def test_list_download_releases_parses_numeric_only(monkeypatch):
    out = (
        "alpine  3.14  x86_64  static  2023-01-01\n"
        "alpine  3.18  x86_64  static  2023-06-01\n"
        "debian  bookworm  amd64  static  -\n"
        "ubuntu  jammy  amd64  static  -\n"
    )
    monkeypatch.setattr(lxc, "run_as", lambda user, argv: _fake_proc(stdout=out))
    assert lxc.list_download_releases("alpine", user="alice") == ["3.14", "3.18"]


def test_list_download_releases_nonzero_returns_empty(monkeypatch):
    monkeypatch.setattr(lxc, "run_as", lambda user, argv: _fake_proc(returncode=1))
    assert lxc.list_download_releases("alpine") == []


def test_container_info_cli_fallback(monkeypatch):
    monkeypatch.setattr(lxc, "_load_lxc", lambda: None)
    out = (
        "NAME STATE IPV4 IPV6 AUTOSTART\n"
        "my-app RUNNING 10.0.3.5 ::1 1\n"
    )
    monkeypatch.setattr(lxc, "_run", lambda user, argv: _fake_proc(stdout=out))
    assert lxc.container_info("/path", "my-app") == (
        "my-app", "RUNNING", "10.0.3.5", "::1", "1",
    )


def test_container_info_cli_fallback_unknown(monkeypatch):
    monkeypatch.setattr(lxc, "_load_lxc", lambda: None)
    out = "NAME STATE IPV4 IPV6 AUTOSTART\nother RUNNING 10.0.3.5 ::1 1\n"
    monkeypatch.setattr(lxc, "_run", lambda user, argv: _fake_proc(stdout=out))
    assert lxc.container_info("/path", "my-app") == ("my-app", "UNKNOWN", "", "", "")


def test_container_info_native_binding(monkeypatch):
    class FakeContainer:
        state = "STOPPED"

        def __init__(self, name, path):
            pass

        def get_ips(self, family=None):
            return ["10.0.3.6"]

        def get_config_item(self, key):
            return "1"

    class FakeLxc:
        @staticmethod
        def Container(name, path):
            return FakeContainer(name, path)

    monkeypatch.setattr(lxc, "_load_lxc", lambda: FakeLxc())
    assert lxc.container_info("/path", "my-app") == (
        "my-app", "STOPPED", "10.0.3.6", "10.0.3.6", "1",
    )
