"""Tests for lxc_tools.acl pure helpers.

The ACL text parser/serializer and mask recomputation are pure functions and
are tested directly. File I/O helpers (``_read_text`` / ``_apply_text``) that
depend on pylibacl are monkeypatched.
"""

from __future__ import annotations

from pathlib import Path

from lxc_tools import acl


def test_parse_entries():
    text = (
        "user::rwx\nuser:1000:rwx\ngroup::r-x\ngroup:1000:r--\n"
        "mask::rwx\nother::---\n"
    )
    entries = acl._parse_entries(text)
    assert entries[("user", "")] == "rwx"
    assert entries[("user", "1000")] == "rwx"
    assert entries[("group", "")] == "r-x"
    assert entries[("mask", "")] == "rwx"
    assert entries[("other", "")] == "---"


def test_parse_entries_ignores_garbage():
    entries = acl._parse_entries("junk\nuser::rwx\n# comment\n")
    assert entries == {("user", ""): "rwx"}


def test_serialize_entries_canonical_order():
    entries = {
        ("other", ""): "---",
        ("user", ""): "rwx",
        ("group", ""): "r-x",
        ("mask", ""): "rwx",
        ("user", "1000"): "rwx",
    }
    lines = acl._serialize_entries(entries).splitlines()
    assert lines == [
        "user::rwx",
        "user:1000:rwx",
        "group::r-x",
        "mask::rwx",
        "other::---",
    ]


def test_recompute_mask_union_of_named():
    entries = {
        ("user", ""): "rwx",
        ("group", ""): "r-x",
        ("other", ""): "---",
        ("user", "1000"): "r-x",
        ("group", "1001"): "r--",
    }
    acl._recompute_mask(entries)
    assert entries[("mask", "")] == "r-x"


def test_recompute_mask_no_named_entries():
    entries = {("user", ""): "rwx", ("group", ""): "r-x", ("other", ""): "---"}
    acl._recompute_mask(entries)
    assert ("mask", "") not in entries


def test_has_user_execute(monkeypatch):
    def fake_read(path, default):
        return "user::rwx\nuser:1000:r-x\ngroup::r-x\nmask::r-x\nother::---\n"

    monkeypatch.setattr(acl, "_read_text", fake_read)
    assert acl.has_user_execute(Path("/tmp/x"), 1000) is True
    assert acl.has_user_execute(Path("/tmp/x"), 2000) is False


def test_ensure_user_acl_adds_entry_and_mask(monkeypatch):
    calls = {}

    def fake_read(path, default):
        return "user::rwx\ngroup::r-x\nother::---\n"

    def fake_apply(path, text, default):
        calls["text"] = text
        calls["default"] = default

    monkeypatch.setattr(acl, "_read_text", fake_read)
    monkeypatch.setattr(acl, "_apply_text", fake_apply)

    acl.ensure_user_acl(Path("/tmp/x"), 1000, "rwx")

    assert "user:1000:rwx" in calls["text"]
    assert "mask::rwx" in calls["text"]
    assert calls["default"] is False


def test_normalize_perms():
    assert acl._normalize_perms("x") == "--x"
    assert acl._normalize_perms("rx") == "r-x"
    assert acl._normalize_perms("rwx") == "rwx"
    assert acl._normalize_perms("r-x") == "r-x"


def test_ensure_user_acl_traversal_execute(monkeypatch):
    """The traversal ACL (execute-only 'x') must serialize canonically."""
    calls = {}

    def fake_read(path, default):
        return "user::rwx\ngroup::r-x\nother::---\n"

    def fake_apply(path, text, default):
        calls["text"] = text

    monkeypatch.setattr(acl, "_read_text", fake_read)
    monkeypatch.setattr(acl, "_apply_text", fake_apply)

    acl.ensure_user_acl(Path("/tmp/x"), 1000, "x")

    assert "user:1000:--x" in calls["text"]
    assert "mask::--x" in calls["text"]
