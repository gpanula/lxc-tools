"""Tests for the attach / console / console-log commands and backends."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lxc_tools import lxc
from lxc_tools.cli import build_parser
from lxc_tools.commands import console as console_cmd
from lxc_tools.commands import console_log


def parse(argv):
    return build_parser().parse_args(argv)


def _fake_proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# -- CLI parsing -------------------------------------------------------------


def test_parse_attach_defaults():
    args = parse(["attach", "my-app"])
    assert args.command == "attach"
    assert args.container_name == "my-app"
    assert args.user is None
    assert args.cmd == []


def test_parse_attach_with_user():
    # --user must precede the container name: REMAINDER captures everything
    # after it verbatim.
    args = parse(["attach", "--user", "ubuntu", "my-app"])
    assert args.user == "ubuntu"
    assert args.container_name == "my-app"


def test_parse_attach_with_command():
    # REMAINDER consumes the ``--`` separator itself.
    args = parse(["attach", "my-app", "--", "uname", "-a"])
    assert args.command == "attach"
    assert args.container_name == "my-app"
    assert args.cmd == ["uname", "-a"]


def test_parse_console_defaults():
    args = parse(["console", "my-app"])
    assert args.command == "console"
    assert args.tty is None


def test_parse_console_tty():
    args = parse(["console", "my-app", "-t", "2"])
    assert args.tty == 2


def test_parse_console_log_defaults():
    args = parse(["console-log", "my-app"])
    assert args.command == "console-log"
    assert args.lines == console_log.DEFAULT_LINES
    assert args.follow is False


def test_parse_console_log_follow():
    args = parse(["console-log", "my-app", "-n", "20", "-f"])
    assert args.lines == 20
    assert args.follow is True


# -- attach backend ----------------------------------------------------------


def test_attach_builds_argv_and_inherits_stdio(monkeypatch):
    captured = {}

    def fake_run(argv):
        captured["argv"] = argv
        return _fake_proc(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    rc = lxc.attach("c", "/p")
    assert rc == 0
    assert captured["argv"] == ["lxc-attach", "-n", "c", "-P", "/p"]


def test_attach_passes_uid_gid(monkeypatch):
    captured = {}

    def fake_run(argv):
        captured["argv"] = argv
        return _fake_proc(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    lxc.attach("c", "/p", uid=1000, gid=1000)
    assert captured["argv"] == [
        "lxc-attach", "-n", "c", "-P", "/p",
        "--uid", "1000", "--gid", "1000",
    ]


def test_attach_passes_command_after_separator(monkeypatch):
    captured = {}

    def fake_run(argv):
        captured["argv"] = argv
        return _fake_proc(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    lxc.attach("c", "/p", command=["uname", "-a"])
    assert captured["argv"] == [
        "lxc-attach", "-n", "c", "-P", "/p", "--", "uname", "-a",
    ]


def test_attach_dry_run_does_not_exec(monkeypatch):
    def fail(argv):
        raise AssertionError("subprocess.run must not be called in dry-run")

    monkeypatch.setattr("subprocess.run", fail)
    assert lxc.attach("c", "/p", dry_run=True) == 0


# -- console backend ---------------------------------------------------------


def test_console_builds_argv(monkeypatch):
    captured = {}

    def fake_run(argv):
        captured["argv"] = argv
        return _fake_proc(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    lxc.console("c", "/p")
    assert captured["argv"] == ["lxc-console", "-n", "c", "-P", "/p"]


def test_console_passes_tty(monkeypatch):
    captured = {}

    def fake_run(argv):
        captured["argv"] = argv
        return _fake_proc(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    lxc.console("c", "/p", tty=3)
    assert captured["argv"] == [
        "lxc-console", "-n", "c", "-P", "/p", "-t", "3",
    ]


# -- console tty preflight ---------------------------------------------------


def test_require_tty_configured_accepts_present_key(tmp_path):
    container = tmp_path / "c"
    container.mkdir()
    (container / "config").write_text("lxc.tty.max = 4\n", encoding="utf-8")
    console_cmd._require_tty_configured("c", str(tmp_path))


def test_require_tty_configured_rejects_missing_key(tmp_path):
    container = tmp_path / "c"
    container.mkdir()
    (container / "config").write_text("lxc.arch = linux64\n", encoding="utf-8")
    with pytest.raises(Exception) as exc:
        console_cmd._require_tty_configured("c", str(tmp_path))
    assert "lxc.tty.max" in str(exc.value)


# -- console-log tail --------------------------------------------------------


def test_tail_returns_last_n_lines(tmp_path):
    log = tmp_path / "console.log"
    log.write_text("".join(f"line{i}\n" for i in range(10)), encoding="utf-8")
    assert console_log._tail(log, 3) == ["line7\n", "line8\n", "line9\n"]


def test_tail_zero_lines_returns_empty(tmp_path):
    log = tmp_path / "console.log"
    log.write_text("a\nb\n", encoding="utf-8")
    assert console_log._tail(log, 0) == []


def test_console_log_path_reads_absolute_config_value(tmp_path):
    container = tmp_path / "c"
    container.mkdir()
    target = tmp_path / "elsewhere.log"
    (container / "config").write_text(
        f"lxc.console.logfile = {target}\n", encoding="utf-8"
    )
    assert console_log._console_log_path(str(tmp_path), "c") == target


def test_console_log_path_resolves_relative_config_value(tmp_path):
    container = tmp_path / "c"
    container.mkdir()
    (container / "config").write_text(
        "lxc.console.logfile = console.log\n", encoding="utf-8"
    )
    assert console_log._console_log_path(str(tmp_path), "c") == (
        container / "console.log"
    )


def test_console_log_path_falls_back_when_unconfigured(tmp_path):
    container = tmp_path / "c"
    container.mkdir()
    (container / "config").write_text("lxc.arch = linux64\n", encoding="utf-8")
    assert console_log._console_log_path(str(tmp_path), "c") == (
        container / "console.log"
    )
