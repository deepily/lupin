"""
notify() must record BOTH ends of its own call — row 03355649.

THE DEFECT. A `notify()` delivered its message and then never returned; the
harness reported "timed out after 660s" for work that had finished ~30 seconds
in. The caller's natural remedy for a reported failure is a re-send, so a false
negative here buys a duplicate announcement.

WHAT WAS MEASURED before this instrument existed, across the fleet's
hook-events.jsonl:
  · 12,420 notify calls; 1,717 (13.8%) have a PreToolUse and no PostToolUse
    ever, while the session went on logging. Controls on the same log, sharing
    every confound: get_session_info 0.27%, task_query 2.60%.
  · Matched notify calls are FAST — p50 0s, p90 1s, p99 120s. So the 13.8% is a
    cliff, not the tail of a slow distribution.
  · Of the 414 such calls since 2026-08-20, 411 have a notifications row inside
    a 125s window and 239 of those are already `delivered`. Shuffling which
    session each call belonged to drops that to 15.8% (5 trials, 12.6–17.6%);
    shifting the times +6h drops it to 9.2%. The message lands; the CALL goes
    missing.

WHAT COULD NOT BE ANSWERED. Every wait in the handler is bounded, so it cannot
itself produce 660s — that says where the hang is NOT. Whether the handler
RETURNED and the response was lost above it was unanswerable, because nothing
recorded the return. These tests pin the witness that answers it: an entry event
and a return event sharing one call_id.
"""
import json

import pytest

from lupin_mcp import cosa_voice_mcp as cv


@pytest.fixture
def events( tmp_path, monkeypatch ):
    """Capture every log_to_stream call the module makes, without touching the real log."""
    seen = []
    monkeypatch.setattr( cv, "log_to_stream",
                         lambda hook, payload, extra=None: seen.append( ( hook, extra ) ) )
    return seen


def _notify_events( seen ):
    return [ extra for hook, extra in seen if hook == "mcp_notify" ]


def test_a_completed_call_records_entry_and_return_under_one_call_id( events, monkeypatch ):
    """
    THE DISCRIMINATOR. Two events, one call_id. Entry-without-return means the
    handler is where it hangs; entry AND return with no PostToolUse means the
    handler finished and the response was lost above it.
    """
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: "Notification sent (queued)" )

    assert cv._notify_impl( message="hello" ) == "Notification sent (queued)"

    entry, ret = _notify_events( events )
    assert entry[ "phase" ] == "entry"
    assert ret[ "phase" ]   == "return"
    assert entry[ "call_id" ] == ret[ "call_id" ]
    assert ret[ "outcome" ] == "Notification sent (queued)"


def test_the_entry_event_lands_BEFORE_the_send( events, monkeypatch ):
    """
    The whole point is to witness a call that never comes back. An entry event
    written after the send would be absent from exactly the calls it exists to
    catch — the instrument would be blind to its own defect.
    """
    at_send = {}
    def _send( **kw ):
        at_send[ "seen" ] = list( _notify_events( events ) )
        return "ok"
    monkeypatch.setattr( cv, "_notify_send", _send )

    cv._notify_impl( message="hello" )
    assert [ e[ "phase" ] for e in at_send[ "seen" ] ] == [ "entry" ]


def test_the_return_event_carries_an_elapsed_time( events, monkeypatch ):
    """A witness that says only 'it returned' cannot tell a 30ms call from a 300s one."""
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: "ok" )
    cv._notify_impl( message="hello" )

    entry, ret = _notify_events( events )
    assert "elapsed_ms" not in entry            # nothing has elapsed yet
    assert isinstance( ret[ "elapsed_ms" ], int ) and ret[ "elapsed_ms" ] >= 0


def test_an_exception_still_records_a_return_and_then_propagates( events, monkeypatch ):
    """
    A raise is a KIND of return, and it must not read as a hang. The exception
    itself is unchanged — the witness observes, it does not swallow.
    """
    def _boom( **kw ):
        raise RuntimeError( "transport gone" )
    monkeypatch.setattr( cv, "_notify_send", _boom )

    with pytest.raises( RuntimeError, match="transport gone" ):
        cv._notify_impl( message="hello" )

    entry, ret = _notify_events( events )
    assert ret[ "phase" ] == "raised"
    assert ret[ "outcome" ] == "RuntimeError"
    assert entry[ "call_id" ] == ret[ "call_id" ]


def test_a_broken_logger_cannot_break_notify( monkeypatch ):
    """
    An instrument that can break the path it measures is worse than no
    instrument. The call must still deliver and still return its own value.
    """
    def _explode( *a, **kw ):
        raise OSError( "log volume full" )
    monkeypatch.setattr( cv, "log_to_stream", _explode )
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: "Notification sent (queued)" )

    assert cv._notify_impl( message="hello" ) == "Notification sent (queued)"


def test_the_outcome_is_truncated_so_the_witness_cannot_bloat_the_log( events, monkeypatch ):
    """The status string is a label. hook-events.jsonl is already 66 MB."""
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: "x" * 5000 )
    cv._notify_impl( message="hello" )
    assert len( _notify_events( events )[ 1 ][ "outcome" ] ) == 120


def test_every_argument_reaches_the_send_unchanged( events, monkeypatch ):
    """
    A wrapper that quietly drops a keyword would change behaviour while looking
    like instrumentation. Pin the full signature, not a sample of it.
    """
    got = {}
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: got.update( kw ) or "ok" )

    cv._notify_impl( message="m", notification_type="alert", priority="urgent",
                     abstract="a", job_id="dr-1", suppress_ding=True,
                     progress_group_id="pg-abcd1234", session_name="s",
                     _internal_call=True )

    assert got == { "message": "m", "notification_type": "alert", "priority": "urgent",
                    "abstract": "a", "job_id": "dr-1", "suppress_ding": True,
                    "progress_group_id": "pg-abcd1234", "session_name": "s",
                    "_internal_call": True }


def test_call_ids_are_distinct_across_calls( events, monkeypatch ):
    """Two calls sharing an id would make an entry-without-return unattributable."""
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: "ok" )
    cv._notify_impl( message="one" )
    cv._notify_impl( message="two" )

    ids = { e[ "call_id" ] for e in _notify_events( events ) }
    assert len( ids ) == 2


# ---------------------------------------------------------------------------
# Payload size — making the row's untested hypothesis answerable
# ---------------------------------------------------------------------------
def test_the_entry_event_carries_the_payload_SIZE( events, monkeypatch ):
    """
    Row 03355649's own open question: "WHETHER it correlates with payload size...
    a hypothesis with one data point behind it and no negative control." Nothing
    in the hook log recorded a size, so it could not be tested against the 1,717
    calls on record. It can be tested going forward now.
    """
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: "ok" )
    cv._notify_impl( message="12345", abstract="678" )

    entry, ret = _notify_events( events )
    assert entry[ "payload_bytes" ] == 8
    assert "payload_bytes" not in ret          # the call_id already ties the pair


def test_the_size_counts_BYTES_not_characters( events, monkeypatch ):
    """
    The abstracts this fleet writes are full of arrows and glyphs. A character
    count would understate exactly the large payloads the hypothesis is about.
    """
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: "ok" )
    cv._notify_impl( message="⇒🦚", abstract=None )
    assert _notify_events( events )[ 0 ][ "payload_bytes" ] == 7    # 3 + 4


@pytest.mark.parametrize( "message,abstract,expected", [
    ( "abc",  None,  3 ),
    ( "",     "",    0 ),
    ( "abc",  42,    3 ),      # a non-string part counts as zero, never raises
    ( None,   "xy",  2 ),
] )
def test_a_missing_or_odd_payload_part_counts_as_zero( message, abstract, expected ):
    assert cv._payload_bytes( message, abstract ) == expected


def test_the_payload_is_SIZED_and_never_LOGGED( events, monkeypatch ):
    """
    hook-events.jsonl is already 66 MB and every session in the fleet writes to
    it. A sizing question must not be answered by putting user-facing announcement
    text into a debug log nobody scoped for it.
    """
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: "ok" )
    secret = "MERGE CONFIRMED AND THE BRANCH IS CUT"
    cv._notify_impl( message=secret, abstract="a table plus several paragraphs" )

    blob = json.dumps( _notify_events( events ) )
    assert secret not in blob
    assert "several paragraphs" not in blob


def test_the_witness_writes_a_json_line_the_log_can_hold( tmp_path, monkeypatch ):
    """
    END-TO-END through the real writer, not the stub. A witness that only works
    against a mock is not an instrument — this runs the actual log_to_stream and
    parses what lands on disk.
    """
    from lupin_cli.claude_code.hooks.lib import hook_common
    monkeypatch.setattr( hook_common, "_logs_dir", lambda: tmp_path )
    monkeypatch.setattr( cv, "_notify_send", lambda **kw: "Notification sent (queued)" )

    cv._notify_impl( message="hello" )

    lines = [ json.loads( l ) for l in ( tmp_path / "hook-events.jsonl" ).read_text().splitlines() ]
    rows  = [ l for l in lines if l.get( "hook" ) == "mcp_notify" ]
    assert [ r[ "phase" ] for r in rows ] == [ "entry", "return" ]
    assert rows[ 0 ][ "call_id" ] == rows[ 1 ][ "call_id" ]
    assert rows[ 1 ][ "outcome" ] == "Notification sent (queued)"
