"""Tests for shared command helpers and create-arg normalization."""

from __future__ import annotations

import pytest

from lxc_tools.commands import SIZE_RE, find_container_path, validate
from lxc_tools.commands.create import normalize_create_args, validate_arch_not_quota
from lxc_tools.config import Config
from lxc_tools.prereq import PrereqError


@pytest.mark.parametrize(
    "value", ["my-app", "app_1", "container.2", "a", "A-1.2_3", "0"]
)
def test_validate_accepts_safe_names(value):
    validate(value, "container_name")  # should not raise


@pytest.mark.parametrize(
    "value", ["", "bad name", "a;b", "x/../y", "-lead", "a$b", "a b"]
)
def test_validate_rejects_unsafe_names(value):
    with pytest.raises(PrereqError):
        validate(value, "container_name")


@pytest.mark.parametrize(
    "value", ["64G", "10GiB", "512m", "1T", "5kiB", "2P", "3E"]
)
def test_size_re_matches_sizes(value):
    assert SIZE_RE.fullmatch(value)


@pytest.mark.parametrize(
    "value", ["amd64", "64", "64GB", "G", "", "10Gx", "x64"]
)
def test_size_re_rejects_non_sizes(value):
    assert not SIZE_RE.fullmatch(value)


def test_normalize_shorthand_size_in_arch_slot():
    assert normalize_create_args("ubuntu", "lts", "64G", None) == (
        "ubuntu", "lts", "amd64", "64G",
    )


def test_normalize_explicit_quota_keeps_arch():
    assert normalize_create_args("ubuntu", "lts", "amd64", "20G") == (
        "ubuntu", "lts", "amd64", "20G",
    )


def test_normalize_default_quota():
    assert normalize_create_args("ubuntu", "lts", "amd64", None) == (
        "ubuntu", "lts", "amd64", "10G",
    )


def test_validate_arch_not_quota_rejects_size():
    with pytest.raises(PrereqError):
        validate_arch_not_quota("64G")


def test_validate_arch_not_quota_accepts_arch():
    validate_arch_not_quota("amd64")  # should not raise


def test_find_container_path_priv_first(tmp_path):
    priv = tmp_path / "priv"
    (priv / "system-app").mkdir(parents=True)
    cfg = Config(priv_path=str(priv), unpriv_base=str(tmp_path / "unpriv"))
    assert find_container_path(cfg, "system-app") == str(priv)


def test_find_container_path_user_tiers(tmp_path):
    unpriv = tmp_path / "unpriv"
    (unpriv / "alice" / "web").mkdir(parents=True)
    (unpriv / "bob").mkdir()
    cfg = Config(priv_path=str(tmp_path / "priv"), unpriv_base=str(unpriv))
    assert find_container_path(cfg, "web") == str(unpriv / "alice")


def test_find_container_path_missing(tmp_path):
    cfg = Config(priv_path=str(tmp_path / "priv"), unpriv_base=str(tmp_path / "unpriv"))
    assert find_container_path(cfg, "ghost") is None
