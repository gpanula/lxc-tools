"""Tests for the lxc-tools CLI argument parsing."""

from __future__ import annotations

import pytest

from lxc_tools.cli import build_parser


def parse(argv):
    return build_parser().parse_args(argv)


def test_parse_create_defaults():
    args = parse(["create", "my-app"])
    assert args.command == "create"
    assert args.container_name == "my-app"
    assert args.distro == "ubuntu"
    assert args.dry_run is False


def test_parse_create_full_args():
    args = parse(["create", "my-app", "debian", "lts", "amd64", "20G"])
    assert args.container_name == "my-app"
    assert args.distro == "debian"
    assert args.release == "lts"
    assert args.arch == "amd64"
    assert args.quota == "20G"


def test_dry_run_before_subcommand():
    args = parse(["--dry-run", "create", "my-app"])
    assert args.command == "create"
    assert args.dry_run is True


def test_dry_run_after_subcommand():
    args = parse(["remove", "my-app", "--dry-run"])
    assert args.command == "remove"
    assert args.dry_run is True


def test_list_active():
    args = parse(["list", "--active"])
    assert args.command == "list"
    assert args.active is True
    assert args.stopped is False


def test_list_stopped():
    args = parse(["list", "--stopped"])
    assert args.command == "list"
    assert args.stopped is True
    assert args.active is False


def test_stop_kill():
    args = parse(["stop", "my-app", "--kill"])
    assert args.command == "stop"
    assert args.kill is True


def test_remove_force():
    args = parse(["remove", "my-app", "--force"])
    assert args.command == "remove"
    assert args.force is True


def test_restart_parses():
    args = parse(["restart", "my-app"])
    assert args.command == "restart"
    assert args.container_name == "my-app"


def test_missing_command_fails():
    with pytest.raises(SystemExit) as excinfo:
        parse([])
    assert excinfo.value.code == 2


def test_unknown_command_fails():
    with pytest.raises(SystemExit) as excinfo:
        parse(["frobnicate"])
    assert excinfo.value.code == 2


def test_version_exits_zero():
    with pytest.raises(SystemExit) as excinfo:
        parse(["--version"])
    assert excinfo.value.code == 0
