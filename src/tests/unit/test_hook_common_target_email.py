#!/usr/bin/env python3
"""
Unit tests for the env-first, ~/.lupin/config file-fallback resolution of the
notification target email in hook_common (bug ef10c5b6, 2026-07-15).

Target: 100% line + branch + function coverage of the three new/changed
functions —
    hook_common._config_file_path
    hook_common._read_email_from_config_file
    hook_common.get_target_email

Why this matters (defense-in-depth, fix (b)): the SessionStart hello-world
notification is a fresh Claude Code session's ONLY birth certificate on the
operator's focus bar, and send_tts() no-ops SILENTLY when get_target_email()
returns None. A tmux-server restart froze a non-login global env with no
LUPIN_DEV_EMAIL, so every new session went invisible until it happened to push
an MCP-side notification. The file fallback resolves the operator's recipient
from ~/.lupin/config's `[<active-env>] global_notification_recipient` (the same
INI the cosa-voice tooling reads) so a lost env can never again silence
registration. The environment variable keeps precedence.

These tests are hermetic: every case either delenv's LUPIN_DEV_EMAIL or sets it
explicitly, and every file-fallback case points LUPIN_CONFIG_FILE at a tmp file
— so the developer's real shell env and real ~/.lupin/config never leak in.
"""
import configparser

import pytest

from lupin_cli.claude_code.hooks.lib import hook_common as hc


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_config( path, environments=None, sections=None ):
    """Build a minimal INI config file mirroring ~/.lupin/config's shape."""
    parser = configparser.ConfigParser()
    if environments is not None:
        parser[ "environments" ] = environments
    for name, body in ( sections or {} ).items():
        parser[ name ] = body
    with open( path, "w", encoding="utf-8" ) as handle:
        parser.write( handle )
    return path


# ── _config_file_path — the two resolution branches ───────────────────────────

def test_config_file_path_honors_env_override( tmp_path, monkeypatch ):
    # LUPIN_CONFIG_FILE set (non-empty) → that path verbatim (test-hermetic).
    target = tmp_path / "myconfig"
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( target ) )
    assert hc._config_file_path() == target


def test_config_file_path_default_when_env_unset( monkeypatch ):
    # env UNSET → ~/.lupin/config (production default). Constructs a path only —
    # no file I/O — so it does not depend on the host actually having the file.
    from pathlib import Path
    monkeypatch.delenv( "LUPIN_CONFIG_FILE", raising=False )
    assert hc._config_file_path() == Path.home() / ".lupin" / "config"


def test_config_file_path_empty_env_falls_back_to_default( monkeypatch ):
    # An EMPTY LUPIN_CONFIG_FILE is falsy → default path (not the empty override).
    from pathlib import Path
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", "" )
    assert hc._config_file_path() == Path.home() / ".lupin" / "config"


# ── _read_email_from_config_file — every branch ───────────────────────────────

def test_read_email_missing_file_returns_none( tmp_path, monkeypatch ):
    # parser.read() returns [] for a missing file (no raise) → the `if not read`
    # branch → None.
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( tmp_path / "does-not-exist" ) )
    assert hc._read_email_from_config_file() is None


def test_read_email_resolves_active_env_recipient( tmp_path, monkeypatch ):
    # Happy path: [environments] default → [<env>] global_notification_recipient.
    cfg = _write_config(
        tmp_path / "config",
        environments = { "default": "local" },
        sections     = { "local": { "global_notification_recipient": "rick@example.com" } },
    )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
    assert hc._read_email_from_config_file() == "rick@example.com"


def test_read_email_strips_recipient_whitespace( tmp_path, monkeypatch ):
    cfg = _write_config(
        tmp_path / "config",
        environments = { "default": "testing" },
        sections     = { "testing": { "global_notification_recipient": "  padded@example.com  " } },
    )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
    assert hc._read_email_from_config_file() == "padded@example.com"


def test_read_email_no_environments_pointer_returns_none( tmp_path, monkeypatch ):
    # File parses but [environments] default is absent → env_name empty → None.
    cfg = _write_config(
        tmp_path / "config",
        sections = { "local": { "global_notification_recipient": "rick@example.com" } },
    )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
    assert hc._read_email_from_config_file() is None


def test_read_email_env_pointer_but_missing_recipient_returns_none( tmp_path, monkeypatch ):
    # env pointer resolves to a section that lacks the recipient key → None
    # (covers the `recipient or None` empty arm via the fallback="" path).
    cfg = _write_config(
        tmp_path / "config",
        environments = { "default": "local" },
        sections     = { "local": { "some_other_key": "x" } },
    )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
    assert hc._read_email_from_config_file() is None


def test_read_email_empty_recipient_value_returns_none( tmp_path, monkeypatch ):
    # Recipient key present but whitespace-only → stripped to "" → None.
    cfg = _write_config(
        tmp_path / "config",
        environments = { "default": "local" },
        sections     = { "local": { "global_notification_recipient": "   " } },
    )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
    assert hc._read_email_from_config_file() is None


def test_read_email_malformed_ini_returns_none( tmp_path, monkeypatch ):
    # A file with no section header raises MissingSectionHeaderError
    # (a configparser.Error) → except branch → None.
    bad = tmp_path / "config"
    bad.write_text( "key = value with no section header\n", encoding="utf-8" )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( bad ) )
    assert hc._read_email_from_config_file() is None


def test_read_email_binary_file_returns_none( tmp_path, monkeypatch ):
    # Undecodable bytes raise UnicodeDecodeError during read → except branch → None.
    binary = tmp_path / "config"
    binary.write_bytes( b"\xff\xfe\x00\x81\x82" )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( binary ) )
    assert hc._read_email_from_config_file() is None


# ── get_target_email — env precedence + file fallback ─────────────────────────

def test_env_takes_precedence_over_file( tmp_path, monkeypatch ):
    # Env set AND a valid config present → env wins (precedence contract).
    cfg = _write_config(
        tmp_path / "config",
        environments = { "default": "local" },
        sections     = { "local": { "global_notification_recipient": "file@example.com" } },
    )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
    monkeypatch.setenv( "LUPIN_DEV_EMAIL", "env@example.com" )
    assert hc.get_target_email() == "env@example.com"


def test_env_value_is_stripped( monkeypatch ):
    monkeypatch.setenv( "LUPIN_DEV_EMAIL", "  padded-env@example.com  " )
    assert hc.get_target_email() == "padded-env@example.com"


def test_empty_env_falls_back_to_file( tmp_path, monkeypatch ):
    cfg = _write_config(
        tmp_path / "config",
        environments = { "default": "local" },
        sections     = { "local": { "global_notification_recipient": "file@example.com" } },
    )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
    monkeypatch.setenv( "LUPIN_DEV_EMAIL", "" )
    assert hc.get_target_email() == "file@example.com"


def test_whitespace_env_falls_back_to_file( tmp_path, monkeypatch ):
    # Truthy-but-blank env → `env_email and env_email.strip()` is False → file.
    cfg = _write_config(
        tmp_path / "config",
        environments = { "default": "local" },
        sections     = { "local": { "global_notification_recipient": "file@example.com" } },
    )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
    monkeypatch.setenv( "LUPIN_DEV_EMAIL", "    " )
    assert hc.get_target_email() == "file@example.com"


def test_unset_env_falls_back_to_file( tmp_path, monkeypatch ):
    # env var entirely absent (None) → short-circuits at `env_email` → file.
    cfg = _write_config(
        tmp_path / "config",
        environments = { "default": "development" },
        sections     = { "development": { "global_notification_recipient": "dev@example.com" } },
    )
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( cfg ) )
    monkeypatch.delenv( "LUPIN_DEV_EMAIL", raising=False )
    assert hc.get_target_email() == "dev@example.com"


def test_no_env_and_no_file_returns_none( tmp_path, monkeypatch ):
    # The pre-bug silent-None state — now reached ONLY when BOTH sources are empty.
    monkeypatch.setenv( "LUPIN_CONFIG_FILE", str( tmp_path / "absent" ) )
    monkeypatch.delenv( "LUPIN_DEV_EMAIL", raising=False )
    assert hc.get_target_email() is None


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
