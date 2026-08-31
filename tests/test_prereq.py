"""Tests for lxc_tools.prereq."""

from __future__ import annotations

import pytest

from lxc_tools import prereq
from lxc_tools.prereq import PrereqError


def test_read_subid_map(tmp_path):
    path = tmp_path / "subuid"
    path.write_text("root:0:1\nalice:100000:65536\n", encoding="utf-8")
    assert prereq.read_subid_map(str(path), "alice") == (100000, 65536)


def test_read_subid_map_missing_user(tmp_path):
    path = tmp_path / "subuid"
    path.write_text("alice:100000:65536\n", encoding="utf-8")
    with pytest.raises(PrereqError):
        prereq.read_subid_map(str(path), "bob")


def test_require_member_of_root_is_noop(monkeypatch):
    def fail(name):
        raise AssertionError("grp.getgrnam should not be called for root")

    monkeypatch.setattr("grp.getgrnam", fail)
    prereq.require_member_of("root")


class _FakeGrp:
    gr_mem = ["alice", "bob"]


def test_require_member_of_allows_member(monkeypatch):
    monkeypatch.setattr("grp.getgrnam", lambda name: _FakeGrp())
    prereq.require_member_of("alice")


def test_require_member_of_denies_non_member(monkeypatch):
    monkeypatch.setattr("grp.getgrnam", lambda name: _FakeGrp())
    with pytest.raises(PrereqError):
        prereq.require_member_of("mallory")


def test_require_member_of_unknown_group(monkeypatch):
    def raise_key(name):
        raise KeyError(name)

    monkeypatch.setattr("grp.getgrnam", raise_key)
    with pytest.raises(PrereqError):
        prereq.require_member_of("alice")


def test_resolve_current_user_from_sudo(monkeypatch):
    monkeypatch.setenv("SUDO_USER", "alice")
    assert prereq.resolve_current_user() == "alice"


def test_resolve_current_user_fallback(monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)
    monkeypatch.setattr("getpass.getuser", lambda: "bob")
    assert prereq.resolve_current_user() == "bob"


def test_is_executable_none():
    assert prereq._is_executable(None) is False


def test_require_binaries_missing_lists_all(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(PrereqError) as excinfo:
        prereq.require_binaries(["lxc-create", "zfs"])
    assert "lxc-create" in str(excinfo.value)
    assert "zfs" in str(excinfo.value)


def test_require_binaries_present_ok(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("os.path.isfile", lambda path: True)
    monkeypatch.setattr("os.access", lambda path, mode: True)
    prereq.require_binaries(["lxc-create"])  # should not raise


def test_dry_or_skips_when_dry_run(capsys):
    calls = []
    result = prereq.dry_or(True, "would create container", lambda: calls.append(1))
    assert result is None
    assert calls == []
    assert "would create container" in capsys.readouterr().out


def test_dry_or_runs_when_not_dry_run():
    calls = []
    prereq.dry_or(False, "creating container", lambda: calls.append(1))
    assert calls == [1]
