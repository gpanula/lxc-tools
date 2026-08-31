"""Tests for lxc-tools create command and disk space pre-flight checks."""

from __future__ import annotations

import collections
import pytest

from lxc_tools.commands.create import (
    _check_disk_space,
    _format_bytes,
    _parse_size_bytes,
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

