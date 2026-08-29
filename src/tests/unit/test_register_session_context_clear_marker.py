"""
Unit tests for `emit_context_clear_marker` (register_session.py, DM-verbosity
pilot item 6b).

The SessionStart hook already receives payload["source"] ∈
startup|resume|clear|compact but never read it; the downstream UUID-rotation
heuristic under-reports context clears. This helper emits one exact JSONL marker
on a clear. `log_to_stream` is monkeypatched so the tests touch no real log file.

Venue: :7999-eligible (pure unit — no server, no disk writes).
"""

import pytest

import lupin_cli.claude_code.hooks.register_session as rs


@pytest.fixture
def captured( monkeypatch ):
    calls = []
    monkeypatch.setattr( rs, "log_to_stream",
                         lambda hook_name, payload, extra=None: calls.append( ( hook_name, payload, extra ) ) )
    return calls


def test_clear_emits_marker( captured ):
    result = rs.emit_context_clear_marker( { "source": "clear", "session_id": "s-1" } )
    assert result is True
    assert len( captured ) == 1
    hook_name, _payload, extra = captured[ 0 ]
    assert hook_name == "session_start"
    assert extra == { "marker": "context_cleared", "source": "clear" }


@pytest.mark.parametrize( "source", [ "startup", "resume", "compact" ] )
def test_non_clear_sources_emit_nothing( captured, source ):
    assert rs.emit_context_clear_marker( { "source": source } ) is False
    assert captured == []


def test_absent_source_emits_nothing( captured ):
    assert rs.emit_context_clear_marker( {} ) is False
    assert captured == []
