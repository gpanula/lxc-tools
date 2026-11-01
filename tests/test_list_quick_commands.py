"""Tests for the QUICK COMMANDS hints printed by ``lxc-tools list``.

The hints are copy-pasteable, so every label must be a real subcommand name.
A capitalised label ("Start:") reads like a valid command but fails with
"invalid choice" because argparse subcommands are case-sensitive.
"""

from __future__ import annotations

import argparse

from lxc_tools.cli import build_parser
from lxc_tools.commands import list as list_cmd


def _subcommand_names() -> set[str]:
    """Return the set of registered subcommand names."""
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("no subparsers found on the top-level parser")


def test_quick_command_labels_are_registered_subcommands():
    names = _subcommand_names()
    for label, _ in list_cmd.QUICK_COMMANDS:
        assert label in names, f"quick-command label '{label}' is not a subcommand"


def test_quick_command_labels_are_lowercase():
    for label, _ in list_cmd.QUICK_COMMANDS:
        assert label == label.lower(), f"label '{label}' is not lowercase"


def test_quick_command_invocations_use_the_label():
    for label, command in list_cmd.QUICK_COMMANDS:
        assert f"lxc-tools {label} " in command, (
            f"hint '{command}' does not invoke 'lxc-tools {label}'"
        )


def test_quick_commands_include_console_and_attach():
    labels = {label for label, _ in list_cmd.QUICK_COMMANDS}
    assert "console" in labels
    assert "attach" in labels
    assert "console-log" in labels
