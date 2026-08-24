"""Tests for lxc_tools.config."""

from __future__ import annotations

import pytest

from lxc_tools.config import Config, ConfigError, load_config


def test_defaults():
    cfg = load_config(environ={})
    assert cfg == Config(
        zfs_pool="rpool",
        priv_path="/rpool/lxc/privileged",
        unpriv_base="/rpool/lxc/unprivileged",
        project_dir="/opt/project",
        bridge="lxcbr0",
    )


def test_env_pool_derives_paths():
    cfg = load_config(environ={"LXC_ZFS_POOL": "mypool"})
    assert cfg.zfs_pool == "mypool"
    assert cfg.priv_path == "/mypool/lxc/privileged"
    assert cfg.unpriv_base == "/mypool/lxc/unprivileged"


@pytest.mark.parametrize(
    "env_var,attr,value",
    [
        ("LXC_ZFS_POOL", "zfs_pool", "tank"),
        ("LXC_PRIV_PATH", "priv_path", "/custom/priv"),
        ("LXC_UNPRIV_BASE", "unpriv_base", "/custom/unpriv"),
        ("BASE_PROJECT_DIR", "project_dir", "/srv/projects"),
        ("LXC_NET_LINK", "bridge", "br0"),
    ],
)
def test_env_override_each(env_var, attr, value):
    cfg = load_config(environ={env_var: value})
    assert getattr(cfg, attr) == value


def test_ini_later_precedence_wins(config_files):
    etc, user, local = config_files
    etc.write_text("[zfs]\npool = one\n", encoding="utf-8")
    user.write_text("[zfs]\npool = two\n", encoding="utf-8")
    local.write_text("[zfs]\npool = three\n", encoding="utf-8")
    cfg = load_config(environ={})
    assert cfg.zfs_pool == "three"
    assert cfg.priv_path == "/three/lxc/privileged"


def test_env_overrides_ini(config_files):
    (config_files[0]).write_text("[zfs]\npool = ini_pool\n", encoding="utf-8")
    cfg = load_config(environ={"LXC_ZFS_POOL": "env_pool"})
    assert cfg.zfs_pool == "env_pool"


def test_explicit_priv_path_not_derived(config_files):
    (config_files[0]).write_text(
        "[zfs]\npool = tank\npriv_path = /explicit/priv\n", encoding="utf-8"
    )
    cfg = load_config(environ={})
    assert cfg.priv_path == "/explicit/priv"
    # unpriv_base is still derived from the pool.
    assert cfg.unpriv_base == "/tank/lxc/unprivileged"


def test_empty_env_value_ignored():
    cfg = load_config(environ={"LXC_ZFS_POOL": ""})
    assert cfg.zfs_pool == "rpool"


def test_empty_ini_value_raises(config_files):
    (config_files[0]).write_text("[zfs]\npool =\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(environ={})


def test_malformed_ini_raises(config_files):
    (config_files[0]).write_text("not an ini :::: [[[", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(environ={})
