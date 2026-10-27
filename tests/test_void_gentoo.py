"""Tests for Void Linux and Gentoo support."""

from __future__ import annotations

from lxc_tools import distro
from lxc_tools.commands import create


# -- release resolution ------------------------------------------------------


def test_voidlinux_lts_resolves_to_current():
    assert distro.resolve_lts("voidlinux", "lts") == "current"


def test_archlinux_lts_resolves_to_current():
    assert distro.resolve_lts("archlinux", "lts") == "current"


def test_gentoo_lts_resolves_to_current():
    assert distro.resolve_lts("gentoo", "lts") == "current"


def test_explicit_release_is_passed_through():
    assert distro.resolve_lts("voidlinux", "current") == "current"
    assert distro.resolve_lts("gentoo", "current") == "current"


# -- default distro ----------------------------------------------------------


def test_default_distro_is_voidlinux():
    assert create.DEFAULT_DISTRO == "voidlinux"


def test_voidlinux_is_not_a_systemd_distro():
    assert "voidlinux" not in create.SYSTEMD_DISTROS


def test_gentoo_is_not_a_systemd_distro():
    assert "gentoo" not in create.SYSTEMD_DISTROS


def test_voidlinux_does_not_use_minimal_init():
    """Void's runit is PID 1 directly; no lxc.init.cmd override needed."""
    args = type("A", (), {"systemd": False, "no_systemd": False})()
    assert create._resolve_no_systemd(args, "voidlinux") is False


def test_gentoo_does_not_use_minimal_init():
    args = type("A", (), {"systemd": False, "no_systemd": False})()
    assert create._resolve_no_systemd(args, "gentoo") is False


def test_ubuntu_still_uses_minimal_init():
    args = type("A", (), {"systemd": False, "no_systemd": False})()
    assert create._resolve_no_systemd(args, "ubuntu") is True


# -- provisioning script -----------------------------------------------------


def _script(**kwargs) -> str:
    defaults = dict(
        install_sshd=False,
        start_sshd=False,
        ssh_key=None,
        username=None,
        sudo=False,
        nopasswd_sudo=False,
        allow_tcp_forwarding=False,
    )
    defaults.update(kwargs)
    return create._build_provision_script(**defaults)


def test_provision_script_has_xbps_branch():
    script = _script(install_sshd=True)
    assert "xbps-install -Sy" in script
    assert "xbps-install -y openssh" in script


def test_provision_script_has_emerge_branch():
    script = _script(install_sshd=True)
    assert "emerge --sync" in script
    assert "net-misc/openssh" in script


def test_provision_script_enables_sshd_under_runit():
    script = _script(start_sshd=True)
    assert "/var/service/sshd" in script
    assert "/etc/sv/sshd" in script


def test_provision_script_enables_sshd_under_openrc():
    script = _script(start_sshd=True)
    assert "rc-update add sshd default" in script
    assert "rc-service sshd start" in script


def test_provision_script_prefers_service_manager_over_bare_sshd():
    """The bare sshd fallback must come last, after every service manager."""
    script = _script(start_sshd=True)
    runit = script.index("/var/service/sshd")
    openrc = script.index("rc-update add sshd")
    systemd = script.index("systemctl enable --now sshd")
    bare = script.index("/usr/sbin/sshd 2>/dev/null || sshd")
    assert runit < openrc < systemd < bare
