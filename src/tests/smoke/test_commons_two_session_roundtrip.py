"""
AC11 smoke test for the inter-session commons.

Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md AC11:

> "two child Python processes (each with distinct persona) directly import
>  CommonsStore, both pointed at a shared tempfile.TemporaryDirectory().
>  One posts to coordination topic, the other reads and verifies the entry.
>  No server dependency — pure local file I/O via tempdir. Venue: :7999
>  AI-discretionary (non-destructive, fast, isolated; MCP layer bypassed
>  for Phase 1 smoke per T3 ratification)."

The point of the smoke test is to validate the cross-process file-store
contract end-to-end: posts written from one Python process are observable
by a fresh interpreter that imports the store independently and reads from
the same tempdir. This exercises the entire file format (frontmatter +
entry separator + header regex + metadata roundtrip) under realistic
process boundaries.

Venue: :7999 AI-discretionary. Uses `multiprocessing.get_context("spawn")`
which forks a fresh Python interpreter for each worker — matches the
AC10b stress-test pattern at
`src/tests/unit/commons/test_commons_store.py::test_ac10b_real_fcntl_concurrent_append`.
"""

import multiprocessing as mp
import os
import tempfile

import pytest

from lupin_mcp.commons_ask import ask_async
from lupin_mcp.commons_store import CommonsStore


# ---------- Child worker functions (must be module-level for `spawn` context) ----------


def _poster_worker( commons_root: str, body: str, persona_name: str, persona_icon: str, persona_color: str, session_id: str ) -> None:
    """Spawn-safe worker: import CommonsStore in a fresh interpreter and post one entry."""
    store = CommonsStore( commons_root )
    store.post(
        topic             = "coordination",
        body              = body,
        sender_session_id = session_id,
        persona_name      = persona_name,
        persona_icon      = persona_icon,
        persona_color     = persona_color,
        metadata          = { "kind": "status" },
    )


def _reader_worker( commons_root: str, expected_body: str, result_queue ) -> None:
    """
    Spawn-safe reader: import CommonsStore in a fresh interpreter, read the
    `coordination` topic, push (count, matched_entry_or_None) back through
    `result_queue` for the parent to assert on.
    """
    store   = CommonsStore( commons_root )
    entries = store.read( "coordination", limit=100 )
    matched = next( ( e for e in entries if e[ "body" ] == expected_body ), None )
    result_queue.put( ( len( entries ), matched ) )


def _question_poster_worker( commons_root: str, question_body: str, persona_name: str, persona_icon: str, persona_color: str, session_id: str, result_queue ) -> None:
    """Spawn-safe worker: post a question via `commons_ask.ask_async` and report back the question_id."""
    store  = CommonsStore( commons_root )
    result = ask_async(
        store             = store,
        topic             = "coordination",
        body              = question_body,
        sender_session_id = session_id,
        persona_name      = persona_name,
        persona_icon      = persona_icon,
        persona_color     = persona_color,
    )
    result_queue.put( result )


def _reply_worker( commons_root: str, in_reply_to: str, reply_body: str, persona_name: str, persona_icon: str, persona_color: str, session_id: str ) -> None:
    """Spawn-safe worker: post an answer referencing `in_reply_to` via metadata correlation."""
    store = CommonsStore( commons_root )
    store.post(
        topic             = "coordination",
        body              = reply_body,
        sender_session_id = session_id,
        persona_name      = persona_name,
        persona_icon      = persona_icon,
        persona_color     = persona_color,
        metadata          = { "kind": "answer", "in_reply_to": in_reply_to },
    )


# ---------- AC11 smoke tests ----------


@pytest.mark.timeout( 30 )
def test_ac11_two_session_roundtrip():
    """
    AC11 primary: Process A posts to `coordination`; Process B reads and
    observes A's entry with the expected body + persona stamp.
    """
    ctx = mp.get_context( "spawn" )
    with tempfile.TemporaryDirectory() as tmp:
        # Parent seeds the store so reserved-topic files exist.
        CommonsStore( tmp )

        poster = ctx.Process(
            target = _poster_worker,
            args   = ( tmp, "hello from Maria", "Maria", "🌸", "#A040A0", "sess-maria" ),
        )
        poster.start()
        poster.join( timeout=15 )
        assert poster.exitcode == 0, f"poster process exited with {poster.exitcode}"

        # Now a separate process reads and reports back what it found.
        result_q = ctx.Queue()
        reader   = ctx.Process( target=_reader_worker, args=( tmp, "hello from Maria", result_q ) )
        reader.start()
        reader.join( timeout=15 )
        assert reader.exitcode == 0, f"reader process exited with {reader.exitcode}"

        count, matched = result_q.get( timeout=5 )
        assert count == 1, f"expected 1 entry in coordination topic, found {count}"
        assert matched is not None, "reader did not find the posted entry"
        assert matched[ "body" ]          == "hello from Maria"
        assert matched[ "persona_name" ]  == "Maria"
        assert matched[ "persona_icon" ]  == "🌸"
        assert matched[ "persona_color" ] == "#A040A0"
        assert matched[ "sender_session_id" ] == "sess-maria"
        assert matched[ "metadata" ]      == { "kind": "status" }


@pytest.mark.timeout( 30 )
def test_ac11_two_session_distinct_personas():
    """
    Both sessions post; parent reads all entries and confirms BOTH persona stamps
    are visible in the topic with correct per-entry attribution.
    """
    ctx = mp.get_context( "spawn" )
    with tempfile.TemporaryDirectory() as tmp:
        CommonsStore( tmp )

        maria_proc = ctx.Process(
            target = _poster_worker,
            args   = ( tmp, "Maria here", "Maria", "🌸", "#A040A0", "sess-maria" ),
        )
        tiberius_proc = ctx.Process(
            target = _poster_worker,
            args   = ( tmp, "Tiberius here", "Tiberius", "🌑", "#3F51B5", "sess-tiberius" ),
        )
        maria_proc.start()
        tiberius_proc.start()
        for p in ( maria_proc, tiberius_proc ):
            p.join( timeout=15 )
            assert p.exitcode == 0

        # Parent reads from the same tempdir.
        parent_store = CommonsStore( tmp )
        entries      = parent_store.read( "coordination", limit=100 )
        assert len( entries ) == 2

        by_session = { e[ "sender_session_id" ]: e for e in entries }
        assert "sess-maria"    in by_session
        assert "sess-tiberius" in by_session
        assert by_session[ "sess-maria"    ][ "persona_icon" ] == "🌸"
        assert by_session[ "sess-tiberius" ][ "persona_icon" ] == "🌑"
        assert by_session[ "sess-maria"    ][ "body" ]         == "Maria here"
        assert by_session[ "sess-tiberius" ][ "body" ]         == "Tiberius here"


@pytest.mark.timeout( 30 )
def test_ac11_two_session_question_answer_roundtrip():
    """
    Cross-process Q/A correlation: Process A posts a question via `ask_async`;
    Process B reads it, posts a reply with `metadata.in_reply_to = question_id`;
    parent confirms the reply is correlated to the question.
    """
    ctx = mp.get_context( "spawn" )
    with tempfile.TemporaryDirectory() as tmp:
        CommonsStore( tmp )

        # Process A asks
        q_result_q = ctx.Queue()
        asker      = ctx.Process(
            target = _question_poster_worker,
            args   = ( tmp, "anyone seen the build?", "Maria", "🌸", "#A040A0", "sess-maria", q_result_q ),
        )
        asker.start()
        asker.join( timeout=15 )
        assert asker.exitcode == 0

        ask_result  = q_result_q.get( timeout=5 )
        question_id = ask_result[ "question_id" ]
        assert question_id

        # Process B replies
        replier = ctx.Process(
            target = _reply_worker,
            args   = ( tmp, question_id, "build is green", "Tiberius", "🌑", "#3F51B5", "sess-tiberius" ),
        )
        replier.start()
        replier.join( timeout=15 )
        assert replier.exitcode == 0

        # Parent verifies correlation
        parent_store = CommonsStore( tmp )
        entries      = parent_store.read( "coordination", limit=100 )
        assert len( entries ) == 2

        question = next( e for e in entries if e[ "metadata" ].get( "kind" ) == "question" )
        answer   = next( e for e in entries if e[ "metadata" ].get( "kind" ) == "answer" )
        assert question[ "metadata" ][ "question_id" ] == question_id
        assert answer  [ "metadata" ][ "in_reply_to" ] == question_id
        assert answer  [ "body" ]                       == "build is green"
        assert answer  [ "persona_name" ]               == "Tiberius"


if __name__ == "__main__":
    # Standalone runner so the smoke test is executable directly per the
    # project's per-module quick_smoke_test convention. Calls each test
    # in turn and reports tabular pass/fail.
    print( "Running AC11 two-session commons smoke tests..." )
    tests = [
        ( "test_ac11_two_session_roundtrip",                  test_ac11_two_session_roundtrip                  ),
        ( "test_ac11_two_session_distinct_personas",          test_ac11_two_session_distinct_personas          ),
        ( "test_ac11_two_session_question_answer_roundtrip",  test_ac11_two_session_question_answer_roundtrip  ),
    ]
    rows = [ ]
    for name, fn in tests:
        try:
            fn()
            rows.append( ( name, "PASS" ) )
        except Exception as e:
            rows.append( ( name, f"FAIL ({type( e ).__name__}: {e})" ) )
    print( "\nResults:" )
    print( f"{'TEST':<55} {'STATUS'}" )
    print( "-" * 80 )
    for name, status in rows:
        print( f"{name:<55} {status}" )
    failed = [ r for r in rows if r[ 1 ] != "PASS" ]
    if failed:
        raise SystemExit( 1 )
