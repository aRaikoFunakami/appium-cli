"""Tests for invocation logging in __main__.py."""

from appium_cli.__main__ import _sanitize_args


def test_sanitize_args_basic():
    result = _sanitize_args(["--ref", "e3", "--json"])
    assert result == {"ref": "e3", "json": "true"}


def test_sanitize_args_sensitive_keys():
    result = _sanitize_args(["--password", "my-secret", "--token", "abc123"])
    assert result == {"password": "***", "token": "***"}


def test_sanitize_args_text_truncation():
    long_text = "a" * 200
    result = _sanitize_args(["--text", long_text])
    assert result["text"] == "a" * 100 + "..."


def test_sanitize_args_positional():
    result = _sanitize_args(["snapshot", "--scope", "full"])
    assert result == {"_positional": "snapshot", "scope": "full"}
