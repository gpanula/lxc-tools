"""Shared pytest fixtures for the lxc-tools test suite.

These tests are pure-logic: they exercise the parsing, precedence, resolution
and helper layers without requiring root privileges or the native ZFS/LXC/ACL
bindings. System-facing boundaries are mocked with ``monkeypatch``.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def config_files(tmp_path, monkeypatch):
    """Point the config loader at three temporary files and return their paths.

    The three paths mirror the documented precedence order (system, user,
    local), from lowest to highest precedence.
    """
    paths = [
        tmp_path / "etc-lxc-tools.conf",
        tmp_path / "user-lxc-tools.conf",
        tmp_path / "local-lxc-tools.conf",
    ]
    monkeypatch.setattr("lxc_tools.config.CONFIG_PATHS", tuple(paths))
    return paths
