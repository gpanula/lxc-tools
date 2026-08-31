"""Tests for lxc_tools.distro LTS resolution."""

from __future__ import annotations

from lxc_tools import distro
from lxc_tools import lxc as lxc_backend


def test_version_key():
    assert distro._version_key("3.18") == (3, 18)
    assert distro._version_key("9.3.1") == (9, 3, 1)


def test_non_lts_passthrough():
    assert distro.resolve_lts("ubuntu", "noble", run_as_user="alice") == "noble"


def test_ubuntu_lts_from_python(monkeypatch):
    monkeypatch.setattr(distro, "_ubuntu_lts_python", lambda: "noble")
    assert distro.resolve_lts("ubuntu", "lts", run_as_user="alice") == "noble"


def test_ubuntu_lts_fallback_to_cli(monkeypatch):
    monkeypatch.setattr(distro, "_ubuntu_lts_python", lambda: None)
    monkeypatch.setattr(distro, "_ubuntu_lts_cli", lambda: "jammy")
    assert distro.resolve_lts("ubuntu", "lts", run_as_user="alice") == "jammy"


def test_ubuntu_lts_hard_fallback(monkeypatch):
    monkeypatch.setattr(distro, "_ubuntu_lts_python", lambda: None)
    monkeypatch.setattr(distro, "_ubuntu_lts_cli", lambda: None)
    assert distro.resolve_lts("ubuntu", "lts", run_as_user="alice") == distro._UBUNTU_FALLBACK


def test_debian_lts_from_python(monkeypatch):
    monkeypatch.setattr(distro, "_debian_stable_python", lambda: "bookworm")
    assert distro.resolve_lts("debian", "lts", run_as_user="alice") == "bookworm"


def test_debian_lts_fallback(monkeypatch):
    monkeypatch.setattr(distro, "_debian_stable_python", lambda: None)
    monkeypatch.setattr(distro, "_debian_stable_cli", lambda: "trixie")
    assert distro.resolve_lts("debian", "lts", run_as_user="alice") == "trixie"


def test_alpine_uses_download_list_highest(monkeypatch):
    monkeypatch.setattr(
        lxc_backend, "list_download_releases",
        lambda d, user=None: ["3.14", "3.18", "3.16"],
    )
    assert distro.resolve_lts("alpine", "lts", run_as_user="alice") == "3.18"


def test_alpine_empty_list_falls_back_to_latest(monkeypatch):
    monkeypatch.setattr(lxc_backend, "list_download_releases", lambda d, user=None: [])
    assert distro.resolve_lts("alpine", "lts", run_as_user="alice") == "latest"


def test_lts_keyword_case_insensitive(monkeypatch):
    monkeypatch.setattr(distro, "_ubuntu_lts_python", lambda: "noble")
    assert distro.resolve_lts("ubuntu", "LTS", run_as_user="alice") == "noble"


def test_unknown_distro_passthrough():
    assert distro.resolve_lts("custom", "lts", run_as_user="alice") == "lts"


def test_ubuntu_lts_real_binding(monkeypatch):
    """Regression: lts() returns a str, so slicing must never return a char."""
    import distro_info

    monkeypatch.setattr(
        distro, "_ubuntu_lts_python", lambda: distro_info.UbuntuDistroInfo().lts()
    )
    resolved = distro.resolve_lts("ubuntu", "lts", run_as_user="alice")
    # Must be a real codename (>= 3 chars), never a single character.
    assert len(resolved) > 1
    assert resolved != "e"

