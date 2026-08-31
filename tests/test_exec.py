"""Tests for lxc-tools exec subcommand."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from lxc_tools.commands import exec as exec_cmd
from lxc_tools.config import Config
from lxc_tools.prereq import PrereqError


class FakeZFS:
    def __init__(self, exists_result=True):
        self._exists = exists_result
        self.snapshots_taken = []

    def exists(self, dataset: str) -> bool:
        return self._exists

    def snapshot(self, dataset: str, snap_name: str) -> str:
        self.snapshots_taken.append((dataset, snap_name))
        return f"{dataset}@{snap_name}"


def test_exec_default_takes_snapshot(monkeypatch, tmp_path):
    unpriv = tmp_path / "unpriv" / "alice"
    (unpriv / "app").mkdir(parents=True)
    cfg = Config(
        priv_path=str(tmp_path / "priv"),
        unpriv_base=str(tmp_path / "unpriv"),
        zfs_pool="mypool",
        exec_snapshot=True,
    )

    monkeypatch.setattr(exec_cmd.prereq, "ensure_root_or_reexec", lambda: None)
    monkeypatch.setattr(exec_cmd.prereq, "resolve_current_user", lambda: "alice")
    monkeypatch.setattr(exec_cmd, "require_member_of", lambda u: None)
    monkeypatch.setattr(exec_cmd, "require_binaries", lambda b: None)
    monkeypatch.setattr(exec_cmd, "load_config", lambda: cfg)

    fake_zfs = FakeZFS()
    monkeypatch.setattr(exec_cmd.zfs, "ZFS", lambda: fake_zfs)
    monkeypatch.setattr(exec_cmd.lxc_backend, "container_info", lambda p, n: (n, "RUNNING", "", "", "0"))

    executed = []
    monkeypatch.setattr(
        exec_cmd.lxc_backend,
        "execute",
        lambda n, p, c, dry_run=False: (executed.append((n, c)), (0, "ok", ""))[1],
    )

    args = argparse.Namespace(
        container_name="app",
        command=["apk", "add", "curl"],
        snapshot=None,
        no_snapshot=False,
        snapshot_tag=None,
        dry_run=False,
    )
    ret = exec_cmd.run(args)
    assert ret == 0
    assert len(fake_zfs.snapshots_taken) == 1
    assert "pre-exec" in fake_zfs.snapshots_taken[0][1]
    assert "apk" in fake_zfs.snapshots_taken[0][1]
    assert executed == [("app", ["apk", "add", "curl"])]


def test_exec_no_snapshot_flag(monkeypatch, tmp_path):
    unpriv = tmp_path / "unpriv" / "alice"
    (unpriv / "app").mkdir(parents=True)
    cfg = Config(
        priv_path=str(tmp_path / "priv"),
        unpriv_base=str(tmp_path / "unpriv"),
        zfs_pool="mypool",
        exec_snapshot=True,
    )

    monkeypatch.setattr(exec_cmd.prereq, "ensure_root_or_reexec", lambda: None)
    monkeypatch.setattr(exec_cmd.prereq, "resolve_current_user", lambda: "alice")
    monkeypatch.setattr(exec_cmd, "require_member_of", lambda u: None)
    monkeypatch.setattr(exec_cmd, "require_binaries", lambda b: None)
    monkeypatch.setattr(exec_cmd, "load_config", lambda: cfg)

    fake_zfs = FakeZFS()
    monkeypatch.setattr(exec_cmd.zfs, "ZFS", lambda: fake_zfs)
    monkeypatch.setattr(exec_cmd.lxc_backend, "container_info", lambda p, n: (n, "RUNNING", "", "", "0"))
    monkeypatch.setattr(
        exec_cmd.lxc_backend, "execute", lambda n, p, c, dry_run=False: (0, "ok", "")
    )

    args = argparse.Namespace(
        container_name="app",
        command=["whoami"],
        snapshot=None,
        no_snapshot=True,
        snapshot_tag=None,
        dry_run=False,
    )
    ret = exec_cmd.run(args)
    assert ret == 0
    assert fake_zfs.snapshots_taken == []


def test_exec_yolo_config_with_snapshot_override(monkeypatch, tmp_path):
    unpriv = tmp_path / "unpriv" / "alice"
    (unpriv / "app").mkdir(parents=True)
    # exec_snapshot=False in config
    cfg = Config(
        priv_path=str(tmp_path / "priv"),
        unpriv_base=str(tmp_path / "unpriv"),
        zfs_pool="mypool",
        exec_snapshot=False,
    )

    monkeypatch.setattr(exec_cmd.prereq, "ensure_root_or_reexec", lambda: None)
    monkeypatch.setattr(exec_cmd.prereq, "resolve_current_user", lambda: "alice")
    monkeypatch.setattr(exec_cmd, "require_member_of", lambda u: None)
    monkeypatch.setattr(exec_cmd, "require_binaries", lambda b: None)
    monkeypatch.setattr(exec_cmd, "load_config", lambda: cfg)

    fake_zfs = FakeZFS()
    monkeypatch.setattr(exec_cmd.zfs, "ZFS", lambda: fake_zfs)
    monkeypatch.setattr(exec_cmd.lxc_backend, "container_info", lambda p, n: (n, "RUNNING", "", "", "0"))
    monkeypatch.setattr(
        exec_cmd.lxc_backend, "execute", lambda n, p, c, dry_run=False: (0, "ok", "")
    )

    # Without override -> no snapshot
    args = argparse.Namespace(
        container_name="app",
        command=["whoami"],
        snapshot=None,
        no_snapshot=False,
        snapshot_tag=None,
        dry_run=False,
    )
    ret = exec_cmd.run(args)
    assert ret == 0
    assert fake_zfs.snapshots_taken == []

    # With --snapshot override -> snapshot taken
    args_snap = argparse.Namespace(
        container_name="app",
        command=["apk", "add", "git"],
        snapshot=True,
        no_snapshot=False,
        snapshot_tag=None,
        dry_run=False,
    )
    ret2 = exec_cmd.run(args_snap)
    assert ret2 == 0
    assert len(fake_zfs.snapshots_taken) == 1


def test_exec_stopped_container_raises(monkeypatch, tmp_path):
    unpriv = tmp_path / "unpriv" / "alice"
    (unpriv / "app").mkdir(parents=True)
    cfg = Config(
        priv_path=str(tmp_path / "priv"),
        unpriv_base=str(tmp_path / "unpriv"),
        zfs_pool="mypool",
    )

    monkeypatch.setattr(exec_cmd.prereq, "ensure_root_or_reexec", lambda: None)
    monkeypatch.setattr(exec_cmd.prereq, "resolve_current_user", lambda: "alice")
    monkeypatch.setattr(exec_cmd, "require_member_of", lambda u: None)
    monkeypatch.setattr(exec_cmd, "require_binaries", lambda b: None)
    monkeypatch.setattr(exec_cmd, "load_config", lambda: cfg)
    monkeypatch.setattr(exec_cmd.lxc_backend, "container_info", lambda p, n: (n, "STOPPED", "", "", "0"))

    args = argparse.Namespace(
        container_name="app",
        command=["whoami"],
        snapshot=None,
        no_snapshot=False,
        snapshot_tag=None,
        dry_run=False,
    )
    ret = exec_cmd.run(args)
    assert ret == 1
