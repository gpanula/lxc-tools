"""Tests for snapshot, rollback, and snapshots subcommands."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from lxc_tools.commands import snapshot, rollback, snapshots
from lxc_tools.config import Config
from lxc_tools.prereq import PrereqError


class FakeZFS:
    def __init__(self, exists_result=True, snapshots_list=None):
        self._exists = exists_result
        self._snapshots = snapshots_list or [
            {"name": "mypool/lxc/unprivileged/alice/app@snap-1", "tag": "snap-1", "used": "10K", "referenced": "20M", "creation": "2026-08-30 21:00"}
        ]
        self.snapshots_taken = []
        self.rollbacks = []

    def exists(self, dataset: str) -> bool:
        return self._exists

    def snapshot(self, dataset: str, snap_name: str) -> str:
        self.snapshots_taken.append((dataset, snap_name))
        return f"{dataset}@{snap_name}"

    def rollback(self, dataset: str, snap_name: str, destroy_newer: bool = True) -> None:
        self.rollbacks.append((dataset, snap_name, destroy_newer))

    def list_snapshots(self, dataset: str) -> list[dict[str, str]]:
        return self._snapshots


def test_snapshot_run(monkeypatch, tmp_path):
    unpriv = tmp_path / "unpriv" / "alice"
    (unpriv / "app").mkdir(parents=True)
    cfg = Config(priv_path=str(tmp_path / "priv"), unpriv_base=str(tmp_path / "unpriv"), zfs_pool="mypool")

    monkeypatch.setattr(snapshot.prereq, "ensure_root_or_reexec", lambda: None)
    monkeypatch.setattr(snapshot.prereq, "resolve_current_user", lambda: "alice")
    monkeypatch.setattr(snapshot, "require_member_of", lambda u: None)
    monkeypatch.setattr(snapshot, "require_binaries", lambda b: None)
    monkeypatch.setattr(snapshot, "load_config", lambda: cfg)

    fake_zfs = FakeZFS()
    monkeypatch.setattr(snapshot.zfs, "ZFS", lambda: fake_zfs)

    args = argparse.Namespace(container_name="app", tag="pre-test", dry_run=False)
    ret = snapshot.run(args)
    assert ret == 0
    assert fake_zfs.snapshots_taken == [("mypool/lxc/unprivileged/alice/app", "pre-test")]


def test_rollback_run(monkeypatch, tmp_path):
    unpriv = tmp_path / "unpriv" / "alice"
    (unpriv / "app").mkdir(parents=True)
    cfg = Config(priv_path=str(tmp_path / "priv"), unpriv_base=str(tmp_path / "unpriv"), zfs_pool="mypool")

    monkeypatch.setattr(rollback.prereq, "ensure_root_or_reexec", lambda: None)
    monkeypatch.setattr(rollback.prereq, "resolve_current_user", lambda: "alice")
    monkeypatch.setattr(rollback, "require_member_of", lambda u: None)
    monkeypatch.setattr(rollback, "require_binaries", lambda b: None)
    monkeypatch.setattr(rollback, "load_config", lambda: cfg)

    fake_zfs = FakeZFS(snapshots_list=[{"name": "ds@snap-1", "tag": "snap-1", "used": "0", "referenced": "0", "creation": ""}])
    monkeypatch.setattr(rollback.zfs, "ZFS", lambda: fake_zfs)
    monkeypatch.setattr(rollback.lxc_backend, "container_info", lambda p, n: (n, "STOPPED", "", "", "0"))

    args = argparse.Namespace(container_name="app", tag="snap-1", force=True, no_restart=False, dry_run=False)
    ret = rollback.run(args)
    assert ret == 0
    assert fake_zfs.rollbacks == [("mypool/lxc/unprivileged/alice/app", "snap-1", True)]


def test_rollback_unknown_snapshot_raises(monkeypatch, tmp_path):
    unpriv = tmp_path / "unpriv" / "alice"
    (unpriv / "app").mkdir(parents=True)
    cfg = Config(priv_path=str(tmp_path / "priv"), unpriv_base=str(tmp_path / "unpriv"), zfs_pool="mypool")

    monkeypatch.setattr(rollback.prereq, "ensure_root_or_reexec", lambda: None)
    monkeypatch.setattr(rollback.prereq, "resolve_current_user", lambda: "alice")
    monkeypatch.setattr(rollback, "require_member_of", lambda u: None)
    monkeypatch.setattr(rollback, "require_binaries", lambda b: None)
    monkeypatch.setattr(rollback, "load_config", lambda: cfg)

    fake_zfs = FakeZFS(snapshots_list=[])
    monkeypatch.setattr(rollback.zfs, "ZFS", lambda: fake_zfs)

    args = argparse.Namespace(container_name="app", tag="ghost", force=True, no_restart=False, dry_run=False)
    # Since rollback.run is decorated with @guarded, it returns exit code 1
    ret = rollback.run(args)
    assert ret == 1


def test_snapshots_run(monkeypatch, tmp_path, capsys):
    unpriv = tmp_path / "unpriv" / "alice"
    (unpriv / "app").mkdir(parents=True)
    cfg = Config(priv_path=str(tmp_path / "priv"), unpriv_base=str(tmp_path / "unpriv"), zfs_pool="mypool")

    monkeypatch.setattr(snapshots.prereq, "effective_user", lambda: "alice")
    monkeypatch.setattr(snapshots, "require_member_of", lambda u: None)
    monkeypatch.setattr(snapshots, "require_binaries", lambda b: None)
    monkeypatch.setattr(snapshots, "load_config", lambda: cfg)

    fake_zfs = FakeZFS(snapshots_list=[{"name": "ds@snap-1", "tag": "snap-1", "used": "10K", "referenced": "20M", "creation": "2026-08-30 21:00"}])
    monkeypatch.setattr(snapshots.zfs, "ZFS", lambda: fake_zfs)

    args = argparse.Namespace(container_name="app")
    ret = snapshots.run(args)
    assert ret == 0
    captured = capsys.readouterr()
    assert "snap-1" in captured.out
    assert "10K" in captured.out

