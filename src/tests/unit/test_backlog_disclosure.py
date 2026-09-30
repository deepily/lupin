"""
Unit tests for the drained-backlog disclosure header (row 298af249).

The defect this guards: `drain_voice_buffer` is uncapped and `format_voice_context`
used to emit every drained message as a flat run of blocks, so a session that had
been busy received a wall with nothing in it saying it WAS a wall. Measured
2026-08-30 — a review approval arrived as buffered message #78 of 78 and did not
register; the manager read the silence as "the reviewer has not finished".

These tests hold BOTH halves of the contract:
    - above the threshold, the run announces its own depth, FIRST
    - nothing is ever dropped — disclosure is not a cap, because turning a
      hard-to-read delivery into a silent non-delivery is strictly worse
"""

import pytest

from lupin_cli.claude_code.hooks.lib.hook_common import (
    format_backlog_header,
    format_voice_context,
    BACKLOG_HEADER_PREFIX,
    BACKLOG_HEADER_THRESHOLD,
    VOICE_LINE_PREFIX,
)


def _voice( text ):
    return { "message": text, "direction": "human_to_ai" }


def _dm( text, persona="Tiberius" ):
    return { "message": text, "direction": "ai_to_ai", "sender_persona": persona }


# ── format_backlog_header ────────────────────────────────────────────────────

@pytest.mark.parametrize( "count", [ 0, 1, BACKLOG_HEADER_THRESHOLD - 1, BACKLOG_HEADER_THRESHOLD ] )
def test_at_or_under_the_threshold_there_is_no_header( count ):
    """A handful of messages reads fine as itself; a header on every drain is noise."""
    assert format_backlog_header( count ) == ""


def test_one_over_the_threshold_is_the_first_count_that_discloses():
    """The boundary is `>`, not `>=` — asserted at the exact edge, not near it."""
    assert format_backlog_header( BACKLOG_HEADER_THRESHOLD ) == ""
    assert format_backlog_header( BACKLOG_HEADER_THRESHOLD + 1 ) != ""


def test_the_header_names_the_exact_count():
    """
    The count is the whole payload. A header saying "several messages" would leave
    the reader exactly as unable to judge the run as no header at all.
    """
    header = format_backlog_header( 78 )
    assert "78" in header
    assert header.startswith( BACKLOG_HEADER_PREFIX )


def test_the_header_tells_the_reader_a_verdict_may_be_anywhere_in_the_run():
    """
    The measured harm was a reader treating the run as one conversation and
    replying to its head. The header has to say the opposite in words.
    """
    header = format_backlog_header( 78 ).lower()
    assert "not one conversation" in header
    assert "verdict" in header or "approval" in header


def test_the_threshold_is_injectable_so_the_boundary_is_testable_without_the_default():
    assert format_backlog_header( 3, threshold=2 ) != ""
    assert format_backlog_header( 3, threshold=3 ) == ""


def test_the_header_carries_no_message_content():
    """
    A header that quoted a message could itself bury the others — the exact defect
    one level down. It is allowed to know the COUNT and nothing else.
    """
    header = format_backlog_header( 9 )
    assert "\n" not in header


# ── format_voice_context integration ─────────────────────────────────────────

def test_a_small_drain_is_untouched():
    msgs  = [ _voice( "one" ), _voice( "two" ) ]
    out   = format_voice_context( msgs )
    assert not out.startswith( BACKLOG_HEADER_PREFIX )
    assert out.count( "\n" ) == 1


def test_a_deep_drain_leads_with_the_header():
    """
    LEADS. A header under the wall is read at the same moment as the thing it was
    meant to warn about, which is no warning at all.
    """
    msgs = [ _voice( f"m{i}" ) for i in range( BACKLOG_HEADER_THRESHOLD + 3 ) ]
    out  = format_voice_context( msgs )
    assert out.splitlines()[ 0 ].startswith( BACKLOG_HEADER_PREFIX )


def test_disclosure_is_not_a_cap_every_message_still_arrives():
    """
    The load-bearing test. Turning a hard-to-read delivery into a silent
    non-delivery would be a worse defect than the one being fixed, so the count of
    delivered bodies must be untouched by the header.

    🔴 THE FIRST VERSION OF THIS TEST COULD NOT SEE A DROPPED MESSAGE (found by
    Tiberius 👑 reviewing it, 2026-08-30). It used bodies `unique-body-0` ..
    `unique-body-24` and asserted each was `in out` — but `unique-body-2` is a
    SUBSTRING of `unique-body-24`, so a formatter that dropped message 2 and kept
    24 passed it clean. The fixture, not the assertions, was the defect: the test
    was named for completeness and measured prefix collision.

    Two things fix it, and both are needed. The bodies are zero-padded so no id is
    a prefix of another, and the LINE COUNT is asserted — a substring check can
    only ever show a body is present somewhere, never that all of them are.
    """
    n    = BACKLOG_HEADER_THRESHOLD + 20
    msgs = [ _voice( f"body-{i:03d}-end" ) for i in range( n ) ]
    out  = format_voice_context( msgs )
    lines = out.splitlines()
    # header + one line per message, and nothing else
    assert len( lines ) == n + 1
    for i in range( n ):
        assert f"body-{i:03d}-end" in out


def test_the_count_reflects_FORMATTED_messages_not_drained_ones():
    """
    Blank bodies are skipped by the formatter. If the header counted the raw drain
    it would promise more messages than the reader can see — a header that is
    itself wrong is worse than none.
    """
    msgs = [ _voice( "real" ) ] * ( BACKLOG_HEADER_THRESHOLD + 1 ) + [ _voice( "   " ) ] * 5
    out  = format_voice_context( msgs )
    header = out.splitlines()[ 0 ]
    assert f"{BACKLOG_HEADER_PREFIX}{BACKLOG_HEADER_THRESHOLD + 1} messages" in header


def test_a_deep_drain_of_peer_dms_discloses_too():
    """The measured case was peer DMs, not voice — the branch must not matter."""
    msgs = [ _dm( f"approval {i}" ) for i in range( BACKLOG_HEADER_THRESHOLD + 2 ) ]
    out  = format_voice_context( msgs )
    assert out.splitlines()[ 0 ].startswith( BACKLOG_HEADER_PREFIX )


def test_an_all_blank_drain_stays_empty_and_gains_no_header():
    """A header over nothing would announce a backlog that does not exist."""
    assert format_voice_context( [ _voice( "  " ) ] * 40 ) == ""


def test_an_empty_drain_is_still_the_empty_string():
    assert format_voice_context( [] ) == ""


def test_the_run_preserves_SENDER_ORDER_not_merely_the_set_of_messages():
    """
    ORDER, asserted separately from membership (gap found by Tiberius 👑 reviewing
    250baf4b). The count-plus-unique-bodies test above pins the MULTISET: every
    message arrives, exactly once. It says nothing about SEQUENCE, and he proved
    it — `lines.reverse()` passed the whole suite 16 of 16, delivering every
    message in reverse.

    That gap cannot stand on THIS row. The measured defect it exists to guard
    against is a condenser REORDERING a message so a trailing question led and the
    verdict sank into the middle. A backlog formatter free to permute its run
    would reproduce that harm one layer down, and the header would faithfully
    announce the depth of a scrambled wall.

    Membership and order are two claims. This file now makes both.
    """
    n     = BACKLOG_HEADER_THRESHOLD + 6
    msgs  = [ _voice( f"body-{i:03d}-end" ) for i in range( n ) ]
    body  = format_voice_context( msgs ).splitlines()[ 1: ]   # drop the header
    assert body == [ f"{VOICE_LINE_PREFIX}body-{i:03d}-end" for i in range( n ) ]


def test_order_is_preserved_in_a_run_SHORT_enough_to_carry_no_header():
    """
    The no-header branch permutes just as silently, and it has no leading line to
    make a reader suspicious. Asserted separately so the guarantee does not depend
    on the run being deep enough to disclose itself.
    """
    msgs = [ _voice( f"body-{i:03d}-end" ) for i in range( 3 ) ]
    assert format_voice_context( msgs ).splitlines() == [
        f"{VOICE_LINE_PREFIX}body-{i:03d}-end" for i in range( 3 )
    ]
