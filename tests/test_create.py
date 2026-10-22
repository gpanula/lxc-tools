"""Tests for lxc-tools create command and disk space pre-flight checks."""

from __future__ import annotations

import collections
import pytest

from lxc_tools.commands.create import (
    _INIT_SCRIPT,
    _INIT_SCRIPT_PATH,
    _check_disk_space,
    _configure_init,
    _ensure_project_dir,
    _format_bytes,
    _parse_size_bytes,
    _resolve_no_systemd,
    normalize_create_args,
)
from lxc_tools.prereq import PrereqError


def test_normalize_create_args():
    assert normalize_create_args("ubuntu", "lts", "amd64", None) == (
        "ubuntu",
        "lts",
        "amd64",
        "10G",
    )
    assert normalize_create_args("alpine", "3.21", "5G", None) == (
        "alpine",
        "3.21",
        "amd64",
        "5G",
    )
    assert normalize_create_args("debian", "bookworm", "arm64", "20G") == (
        "debian",
        "bookworm",
        "arm64",
        "20G",
    )


def test_parse_size_bytes():
    assert _parse_size_bytes("10G") == 10 * 1024**3
    assert _parse_size_bytes("500M") == 500 * 1024**2
    assert _parse_size_bytes("2T") == 2 * 1024**4
    assert _parse_size_bytes("1024K") == 1024 * 1024
    assert _parse_size_bytes("invalid") == 10 * 1024**3


def test_format_bytes():
    assert _format_bytes(1024) == "1.00 KB"
    assert _format_bytes(1024**2 * 50) == "50.00 MB"
    assert _format_bytes(1024**3 * 7) == "7.00 GB"


Usage = collections.namedtuple("Usage", ["total", "used", "free"])


def test_check_disk_space_sufficient(monkeypatch, tmp_path):
    # 50 GB free
    monkeypatch.setattr(
        "shutil.disk_usage",
        lambda p: Usage(100 * 1024**3, 50 * 1024**3, 50 * 1024**3),
    )
    # Should not raise
    _check_disk_space(str(tmp_path), "10G")


def test_check_disk_space_target_insufficient(monkeypatch, tmp_path):
    # 5 GB free (needed: 10G quota + 2GB buffer = 12GB)
    monkeypatch.setattr(
        "shutil.disk_usage",
        lambda p: Usage(100 * 1024**3, 95 * 1024**3, 5 * 1024**3),
    )
    with pytest.raises(PrereqError, match="Insufficient space on target storage"):
        _check_disk_space(str(tmp_path), "10G")


def test_check_disk_space_temp_insufficient(monkeypatch, tmp_path):
    import tempfile

    temp_dir_str = tempfile.gettempdir()

    def fake_usage(p):
        if str(p) == temp_dir_str:
            return Usage(10 * 1024**3, 9500 * 1024**2, 500 * 1024**2)
        return Usage(100 * 1024**3, 50 * 1024**3, 50 * 1024**3)

    monkeypatch.setattr("shutil.disk_usage", fake_usage)
    with pytest.raises(PrereqError, match="Insufficient temporary space"):
        _check_disk_space(str(tmp_path), "5G")


def test_configure_init_writes_script_and_config(tmp_path):
    """_configure_init installs the init script and sets lxc.init.cmd."""
    name = "my-app"
    lxc_path = tmp_path / "lxc"
    container_dir = lxc_path / name
    rootfs = container_dir / "rootfs"
    rootfs.mkdir(parents=True)
    config_file = container_dir / "config"
    config_file.write_text("lxc.uts.name = my-app\n", encoding="utf-8")

    _configure_init(name, str(lxc_path), 100000, dry_run=False)

    # Init script written and executable.
    init_target = rootfs / _INIT_SCRIPT_PATH.lstrip("/")
    assert init_target.is_file()
    assert init_target.read_text(encoding="utf-8") == _INIT_SCRIPT
    assert init_target.stat().st_mode & 0o111

    # Config now references lxc.init.cmd.
    content = config_file.read_text(encoding="utf-8")
    assert f"lxc.init.cmd = {_INIT_SCRIPT_PATH}" in content


def test_configure_init_idempotent(tmp_path):
    """_configure_init does not duplicate lxc.init.cmd on a second run."""
    name = "my-app"
    lxc_path = tmp_path / "lxc"
    container_dir = lxc_path / name
    rootfs = container_dir / "rootfs"
    rootfs.mkdir(parents=True)
    config_file = container_dir / "config"
    config_file.write_text("lxc.uts.name = my-app\n", encoding="utf-8")

    _configure_init(name, str(lxc_path), 100000, dry_run=False)
    _configure_init(name, str(lxc_path), 100000, dry_run=False)

    content = config_file.read_text(encoding="utf-8")
    assert content.count("lxc.init.cmd") == 1


def test_configure_init_missing_config_raises(tmp_path):
    """_configure_init raises when the container config is absent."""
    name = "my-app"
    lxc_path = tmp_path / "lxc"
    (lxc_path / name / "rootfs").mkdir(parents=True)

    with pytest.raises(PrereqError, match="config not found"):
        _configure_init(name, str(lxc_path), 100000, dry_run=False)


class _Args:
    """Minimal stand-in for argparse.Namespace for _resolve_no_systemd."""

    def __init__(self, no_systemd=False, systemd=False):
        self.no_systemd = no_systemd
        self.systemd = systemd


def test_resolve_no_systemd_default_systemd_distro():
    # ubuntu/debian/rockylinux/almalinux default to minimal init.
    for distro in ("ubuntu", "debian", "rockylinux", "almalinux"):
        assert _resolve_no_systemd(_Args(), distro) is True


def test_resolve_no_systemd_default_alpine():
    # alpine uses OpenRC, not systemd; no minimal init by default.
    assert _resolve_no_systemd(_Args(), "alpine") is False


def test_resolve_no_systemd_explicit_systemd():
    # --systemd forces systemd even for a systemd distro.
    assert _resolve_no_systemd(_Args(systemd=True), "ubuntu") is False


def test_resolve_no_systemd_explicit_no_systemd():
    # --no-systemd forces minimal init even for alpine.
    assert _resolve_no_systemd(_Args(no_systemd=True), "alpine") is True


def test_resolve_no_systemd_systemd_wins_over_no_systemd():
    # --systemd takes precedence over --no-systemd.
    assert _resolve_no_systemd(_Args(no_systemd=True, systemd=True), "ubuntu") is False


class _Cfg:
    def __init__(self, project_dir):
        self.project_dir = project_dir


class _UserInfo:
    def __init__(self, uid, gid):
        self.uid = uid
        self.gid = gid


def test_ensure_project_dir_chowns_to_mapped_uid(tmp_path, monkeypatch):
    """_ensure_project_dir owns the dir + contents by the mapped UID."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    # Pre-existing file owned by the host user (simulating UID 1000).
    existing = project_dir / "my-app" / "file.txt"
    existing.parent.mkdir()
    existing.write_text("x", encoding="utf-8")

    cfg = _Cfg(str(project_dir))
    user_info = _UserInfo(uid=1000, gid=1000)

    # Capture chown calls instead of actually chowning (tests run unprivileged).
    chown_calls = []
    monkeypatch.setattr(
        "lxc_tools.commands.create.os.chown",
        lambda path, uid, gid: chown_calls.append((str(path), uid, gid)),
    )

    _ensure_project_dir(cfg, "pang", user_info, "my-app", 100000, dry_run=False)

    # The directory itself is chowned to the mapped UID.
    assert (str(project_dir / "my-app"), 100000, 100000) in chown_calls
    # The pre-existing file is also chowned to the mapped UID.
    assert (str(existing), 100000, 100000) in chown_calls



