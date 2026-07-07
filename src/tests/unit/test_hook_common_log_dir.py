#!/usr/bin/env python3
"""
Unit tests for Lever P (item 6fc8d78d, 2026-07-07) — the runtime-resolved,
env-overridable hook-log directory in hook_common.

Target: 100% line + branch + function coverage of the new
    hook_common._logs_dir / _stream_log
plus the redirect behavior of log_to_stream / log_payload through them.

Why this matters: `LOGS_DIR`/`STREAM_LOG` used to be import-time constants off the
real project root, so unit tests driving the Stop-hook emit path appended synthetic
rows to the REAL production io/claude_code_hooks/logs/hook-events.jsonl (1,259+
`sidC*` rows under a monkeypatched "Mr. Radio 🦉" persona) — manufacturing a false
"Mr-Radio-only" arbiter false-poke signature. Lever P resolves the dir at CALL time
and honors LUPIN_HOOK_LOG_DIR so the conftest can redirect writes to a tmp dir.
"""
import json
import os

from lupin_cli.claude_code.hooks.lib import hook_common as hc


# ── _logs_dir — the two resolution branches ───────────────────────────────────

def test_logs_dir_honors_env_override( tmp_path, monkeypatch ):
    # LUPIN_HOOK_LOG_DIR set (non-empty) → that path verbatim (test-hermetic).
    target = tmp_path / "custom-hook-logs"
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", str( target ) )
    assert hc._logs_dir() == target


def test_logs_dir_default_when_env_unset( tmp_path, monkeypatch ):
    # env UNSET → <project root>/io/claude_code_hooks/logs (production default).
    # Must delenv to defeat the conftest autouse isolation fixture.
    monkeypatch.delenv( "LUPIN_HOOK_LOG_DIR", raising=False )
    monkeypatch.setattr( hc.cu, "get_project_root", lambda: str( tmp_path / "proj" ) )
    assert hc._logs_dir() == tmp_path / "proj" / "io" / "claude_code_hooks" / "logs"


def test_logs_dir_empty_env_falls_back_to_default( tmp_path, monkeypatch ):
    # An EMPTY LUPIN_HOOK_LOG_DIR is falsy → default path (not the empty override).
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", "" )
    monkeypatch.setattr( hc.cu, "get_project_root", lambda: str( tmp_path / "proj" ) )
    assert hc._logs_dir() == tmp_path / "proj" / "io" / "claude_code_hooks" / "logs"


# ── redirect behavior — writes land under the override, NOT the prod log ──────

def test_log_to_stream_writes_under_override_dir( tmp_path, monkeypatch ):
    target = tmp_path / "stream-logs"
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", str( target ) )
    hc.log_to_stream( "stop", { "session_id": "abc12345" },
                      extra={ "phase": "unit_probe", "marker": "lever-p" } )
    stream = target / "hook-events.jsonl"
    assert stream.exists(), "log_to_stream must create + write the redirected stream"
    rows = [ json.loads( ln ) for ln in stream.read_text().splitlines() if ln.strip() ]
    assert len( rows ) == 1
    assert rows[ 0 ][ "phase" ]  == "unit_probe"
    assert rows[ 0 ][ "marker" ] == "lever-p"
    assert rows[ 0 ][ "hook" ]   == "stop"


def test_log_payload_writes_under_override_dir( tmp_path, monkeypatch ):
    target = tmp_path / "payload-logs"
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", str( target ) )
    hc.log_payload( "smoke", { "hook_event_name": "Stop", "session_id": "def67890" } )
    # per-hook JSON file + the appended stream line both land under the override
    payload_files = list( target.glob( "smoke-*.json" ) )
    assert len( payload_files ) == 1
    body = json.loads( payload_files[ 0 ].read_text() )
    assert body[ "hook_name" ] == "smoke"
    assert ( target / "hook-events.jsonl" ).exists()


def test_log_to_stream_never_raises_on_bad_dir( tmp_path, monkeypatch ):
    # Degrade-safe contract: a log dir whose PARENT is a regular file makes
    # mkdir raise NotADirectoryError — log_to_stream must swallow it (logging
    # failure is non-fatal, never breaks a hook). Covers the except branch.
    a_file = tmp_path / "not-a-dir"
    a_file.write_text( "x" )
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", str( a_file / "logs" ) )
    hc.log_to_stream( "stop", {}, extra={ "phase": "x" } )   # must not raise
