#!/usr/bin/env python3
"""
A2.1 and A2.9 — the byte-offset tail, and the two BACKWARD read verbs ruling Q6 needs.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §2 items 1 and 4 (P4).
Module under test: `cosa/utils/transcript_tail.py`.

The property that matters most
-----------------------------
A2.1: a reader starting at `from_offset=N` receives every byte from N onward, in order, with
NO GAP AND NO REPEAT. That is asserted here by reassembling the whole file from a sequence of
polls and comparing to the file's own records — not by spot-checking a few offsets, because a
gap and a repeat can cancel in a count.

Venue: :7999-eligible — no server, no network, `tmp_path` only, sub-second.
"""

import json
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.utils.transcript_tail import (
    read_tail_bytes,
    read_window_before,
    read_window_from,
    tail_jsonl,
)

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
PRIMARY    = os.path.join( LUPIN_ROOT, "src", "tests", "fixtures", "cc_transcript", "primary.jsonl" )


def _write_jsonl( path, records ):
    """
    Write records as JSONL, returning the byte size written.

    Ensures:
        - every record is one line terminated by \\n, so offsets land on line boundaries
    """
    with open( path, "w" ) as f:
        for record in records:
            f.write( json.dumps( record ) + "\n" )
    return os.path.getsize( path )


def _numbered( count, start=0 ):
    """Records carrying their own index, so a gap or a repeat is visible in the payload."""
    return [ { "type": "assistant", "n": i } for i in range( start, start + count ) ]


@pytest.fixture
def transcript( tmp_path ):
    """A ten-record JSONL file under tmp_path."""
    path = tmp_path / "t.jsonl"
    _write_jsonl( path, _numbered( 10 ) )
    return path


# ── A2.1: every byte from N onward, in order, no gap and no repeat ─────────────

def test_polling_from_zero_reassembles_the_file_with_no_gap_and_no_repeat( tmp_path ):
    """
    A2.1 as a reassembly, not a spot check.

    A gap and a repeat can cancel out in a record COUNT, so the assertion compares the
    ordered sequence of payloads. Records are appended between polls, which is the live case.
    """
    path   = tmp_path / "grow.jsonl"
    seen   = [ ]
    offset = 0

    _write_jsonl( path, _numbered( 3 ) )
    records, offset, rotated = tail_jsonl( path, offset )
    seen.extend( r[ "n" ] for r in records )
    assert rotated is False

    # Append more, poll again — the second poll must start exactly where the first stopped.
    with open( path, "a" ) as f:
        for record in _numbered( 4, start=3 ):
            f.write( json.dumps( record ) + "\n" )
    records, offset, _ = tail_jsonl( path, offset )
    seen.extend( r[ "n" ] for r in records )

    with open( path, "a" ) as f:
        for record in _numbered( 3, start=7 ):
            f.write( json.dumps( record ) + "\n" )
    records, offset, _ = tail_jsonl( path, offset )
    seen.extend( r[ "n" ] for r in records )

    assert seen   == list( range( 10 ) ), "a gap or a repeat — the reassembled order is wrong"
    assert offset == os.path.getsize( path )


def test_a_poll_from_a_midpoint_offset_starts_exactly_there( transcript ):
    """
    The server starts where the client asked; it never silently jumps to the end.

    Reads the whole file once to learn a real line boundary, then re-reads from it.
    """
    first, boundary, _ = tail_jsonl( transcript, 0 )
    assert len( first ) == 10

    # Re-read from a boundary discovered by a partial read, not a guessed number.
    partial, mid, _ = tail_jsonl( transcript, 0 )
    assert mid == boundary

    with open( transcript, "rb" ) as f:
        data = f.read()
    third_line_end = data.index( b"\n", data.index( b"\n", data.index( b"\n" ) + 1 ) + 1 ) + 1

    rest, end, _ = tail_jsonl( transcript, third_line_end )
    assert [ r[ "n" ] for r in rest ] == [ 3, 4, 5, 6, 7, 8, 9 ]
    assert end == os.path.getsize( transcript )


def test_nothing_new_returns_no_records_and_the_same_offset( transcript ):
    """offset == size is the quiet case, and it must not report rotation."""
    _, end, _ = tail_jsonl( transcript, 0 )
    records, offset, rotated = tail_jsonl( transcript, end )
    assert records == [ ]
    assert offset  == end
    assert rotated is False


def test_a_partial_trailing_line_is_left_for_the_next_poll( tmp_path ):
    """
    The partial-write case, which is the normal state of a file being appended to.

    A reader that consumed the partial line would emit a truncated record AND leave the
    offset mid-line, corrupting every subsequent poll.
    """
    path = tmp_path / "partial.jsonl"
    with open( path, "w" ) as f:
        f.write( json.dumps( { "type": "assistant", "n": 0 } ) + "\n" )
        f.write( '{"type": "assistant", "n": 1' )        # no closing brace, no newline

    records, offset, _ = tail_jsonl( path, 0 )
    assert [ r[ "n" ] for r in records ] == [ 0 ]
    assert offset < os.path.getsize( path ), "the partial line was consumed"

    # Completing the line makes it readable, from the SAME offset.
    with open( path, "a" ) as f:
        f.write( '}\n' )
    records, offset, _ = tail_jsonl( path, offset )
    assert [ r[ "n" ] for r in records ] == [ 1 ]
    assert offset == os.path.getsize( path )


def test_a_file_holding_only_a_partial_line_yields_nothing( tmp_path ):
    """No complete line yet — not an error, just nothing to show."""
    path = tmp_path / "onlypartial.jsonl"
    path.write_text( '{"type": "assistant"' )
    records, offset, rotated = tail_jsonl( path, 0 )
    assert ( records, offset, rotated ) == ( [ ], 0, False )


# ── A2.3(b): the shrink is REPORTED, and the replay is withheld ────────────────

def test_a_shrink_reports_rotation_and_returns_no_records( tmp_path ):
    """
    The defect this module exists to avoid.

    `tail_session_file` treats offset > size as rotation and silently re-reads from 0,
    returning the whole file as new bytes. Here rotation is the third return value and NO
    records come with it — otherwise the pane replays the entire transcript as fresh output
    with no signal to reset the epoch.
    """
    path = tmp_path / "rot.jsonl"
    _write_jsonl( path, _numbered( 10 ) )
    _, end, _ = tail_jsonl( path, 0 )

    _write_jsonl( path, _numbered( 2 ) )                 # truncated in place, now shorter

    records, offset, rotated = tail_jsonl( path, end )
    assert rotated is True
    assert records == [ ], "the replayed records were emitted — this is the silent-replay defect"
    assert offset  == 0,  "the offset must reset so the next poll reads the new file cleanly"


def test_the_poll_after_a_rotation_reads_the_new_file_from_the_top( tmp_path ):
    """Rotation withholds once; it does not lose the new content."""
    path = tmp_path / "rot2.jsonl"
    _write_jsonl( path, _numbered( 10 ) )
    _, end, _ = tail_jsonl( path, 0 )
    _write_jsonl( path, _numbered( 2, start=100 ) )

    _, offset, rotated = tail_jsonl( path, end )
    assert rotated is True

    records, _, rotated = tail_jsonl( path, offset )
    assert rotated is False
    assert [ r[ "n" ] for r in records ] == [ 100, 101 ]


# ── never raises ──────────────────────────────────────────────────────────────

def test_a_missing_file_returns_the_offset_unchanged_and_never_raises( tmp_path ):
    """
    ⚠️ The silent-empty hazard, asserted so its shape is on record.

    A missing path is indistinguishable from a quiet seat. That is deliberate — a tailer must
    not die because a seat vanished mid-poll — and it is exactly why `transcript_path` must be
    opened VERBATIM: a path rewritten against the wrong root reads as "quiet" forever.
    """
    missing = tmp_path / "nope.jsonl"
    assert tail_jsonl( missing, 0 )   == ( [ ], 0, False )
    assert tail_jsonl( missing, 512 ) == ( [ ], 512, False )
    assert read_tail_bytes( missing, 100 )      == ( [ ], 0, 0 )
    assert read_window_before( missing, 100, 0 ) == ( [ ], 0, 0 )
    assert read_window_from( missing, 7, 0 )     == ( [ ], 7, 7 )


def test_a_directory_in_place_of_a_file_never_raises( tmp_path ):
    """getsize succeeds on a directory but the open fails — the second OSError path."""
    directory = tmp_path / "adir"
    directory.mkdir()
    assert tail_jsonl( directory, 0 )        == ( [ ], 0, False )
    assert read_window_from( directory, 0, 0 ) == ( [ ], 0, 0 )


def test_blank_and_malformed_lines_are_skipped_not_fatal( tmp_path ):
    """A transcript with junk in it still yields its good records."""
    path = tmp_path / "junk.jsonl"
    path.write_text(
        '{"type": "assistant", "n": 0}\n'
        "\n"
        "   \n"
        "not json at all\n"
        "[1, 2, 3]\n"                                     # valid JSON, not an object
        '"a bare string"\n'
        '{"type": "assistant", "n": 1}\n'
    )
    records, offset, _ = tail_jsonl( path, 0 )
    assert [ r[ "n" ] for r in records ] == [ 0, 1 ]
    assert offset == os.path.getsize( path )


# ── A2.9: the backward verbs ──────────────────────────────────────────────────

def test_tail_bytes_returns_the_LAST_bytes_not_the_first( transcript ):
    """
    A2.9's discriminating arm: a forward-only implementation MUST fail this.

    Ruling Q6 wants the last ~64 KB. `since_offset=0&max_bytes=N` returns the FIRST N bytes,
    and the two answers are indistinguishable unless the test compares them.
    """
    size = os.path.getsize( transcript )
    half = size // 2

    tail_records, tail_offset, tail_next = read_tail_bytes( transcript, half )
    head_records, head_offset, head_next = read_window_from( transcript, 0, half )

    assert tail_offset > head_offset, "tail_bytes is reading FORWARD from the start"
    assert tail_next  == size, "tail_bytes did not end at the file's end"
    assert [ r[ "n" ] for r in tail_records ][ -1 ] == 9, "the tail does not include the last record"
    assert [ r[ "n" ] for r in head_records ][ 0 ]  == 0, "the head does not include the first record"
    assert not set( r[ "n" ] for r in tail_records ) & { 0 }, "the tail reached the first record"


def test_tail_bytes_lands_on_a_complete_line_boundary( transcript ):
    """
    A naive seek to `size - tail_bytes` lands mid-line and the first record is silently lost
    as malformed. The window must advance past the partial first line instead.
    """
    size = os.path.getsize( transcript )
    # Choose a cut that is certain to land inside a line, not on a boundary.
    records, offset, next_offset = read_tail_bytes( transcript, ( size // 2 ) + 3 )

    with open( transcript, "rb" ) as f:
        f.seek( offset - 1 )
        assert f.read( 1 ) == b"\n", "start_offset is not just past a newline"
    assert records, "the window yielded nothing"
    assert next_offset == size


def test_tail_bytes_of_zero_means_the_whole_file( transcript ):
    """0 is unbounded here, consistent with the budget's sense elsewhere."""
    records, offset, next_offset = read_tail_bytes( transcript, 0 )
    assert offset == 0
    assert next_offset == os.path.getsize( transcript )
    assert [ r[ "n" ] for r in records ] == list( range( 10 ) )


def test_tail_bytes_larger_than_the_file_returns_the_whole_file( transcript ):
    """A 64 KB tail of a 400-byte file is the file, not an error."""
    records, offset, _ = read_tail_bytes( transcript, 1_000_000 )
    assert offset == 0
    assert len( records ) == 10


def test_before_offset_pages_backwards_and_never_crosses_its_bound( transcript ):
    """A2.9's "load earlier" arm."""
    size = os.path.getsize( transcript )
    _, tail_start, _ = read_tail_bytes( transcript, size // 2 )

    records, offset, next_offset = read_window_before( transcript, tail_start, 0 )
    assert next_offset <= tail_start, "the backward page crossed its bound"
    assert offset == 0, "with max_bytes=0 the page should reach the top of the file"
    assert [ r[ "n" ] for r in records ][ 0 ] == 0

    # The two windows together must reconstruct the file exactly once each.
    tail_records, _, _ = read_tail_bytes( transcript, size // 2 )
    assert [ r[ "n" ] for r in records ] + [ r[ "n" ] for r in tail_records ] == list( range( 10 ) )


def test_before_offset_of_zero_is_the_top_of_the_file( transcript ):
    """How a client learns to stop asking for more history."""
    assert read_window_before( transcript, 0, 100 ) == ( [ ], 0, 0 )


def test_before_offset_past_the_end_is_clamped_to_the_file( transcript ):
    """A stale before_offset must not read past EOF."""
    records, _, next_offset = read_window_before( transcript, 10 ** 9, 0 )
    assert next_offset == os.path.getsize( transcript )
    assert len( records ) == 10


def test_before_offset_with_a_max_bytes_lands_on_a_boundary( transcript ):
    """The bounded backward page also skips its partial first line."""
    size = os.path.getsize( transcript )
    records, offset, next_offset = read_window_before( transcript, size, ( size // 3 ) + 5 )
    assert records
    with open( transcript, "rb" ) as f:
        f.seek( offset - 1 )
        assert f.read( 1 ) == b"\n"
    assert next_offset == size


def test_a_backward_window_holding_no_complete_line_is_empty_not_an_error( tmp_path ):
    """A window landing entirely inside one long line yields nothing, quietly."""
    path = tmp_path / "long.jsonl"
    path.write_text( json.dumps( { "type": "assistant", "text": "z" * 500 } ) + "\n" )
    records, offset, next_offset = read_window_before( path, os.path.getsize( path ), 20 )
    assert records == [ ]
    assert offset == next_offset


def test_a_window_whose_span_is_zero_is_empty( transcript ):
    """The span<=0 guard, reached through the public verb rather than poked directly."""
    size = os.path.getsize( transcript )
    assert read_window_from( transcript, size, 0 ) == ( [ ], size, size )


# ── the forward repair verb ───────────────────────────────────────────────────

def test_since_offset_reads_forward_and_max_bytes_bounds_it( transcript ):
    """The gap-repair verb: forward from a previous next_offset."""
    _, _, first_next = read_window_from( transcript, 0, 40 )
    records, offset, next_offset = read_window_from( transcript, first_next, 0 )
    assert offset == first_next
    assert next_offset == os.path.getsize( transcript )
    assert [ r[ "n" ] for r in records ][ 0 ] > 0


def test_since_offset_past_the_end_is_clamped_and_empty( transcript ):
    """A client asking beyond EOF gets nothing, not an exception."""
    size = os.path.getsize( transcript )
    assert read_window_from( transcript, size + 500, 0 ) == ( [ ], size, size )


def test_a_negative_since_offset_is_treated_as_zero( transcript ):
    """Defensive clamp — a negative offset must not seek backwards from EOF."""
    records, offset, _ = read_window_from( transcript, -5, 0 )
    assert offset == 0
    assert len( records ) == 10


# ── against the real captured transcript ──────────────────────────────────────

def test_the_real_fixture_round_trips_through_the_forward_and_backward_verbs( ):
    """
    The same properties over real, redacted, 197 KB of captured transcript.

    A hand-written fixture is better-formed than reality exactly where a parser depends on
    the mess (CLAUDE.md § Tests), so the offset arithmetic is re-checked against the real file.
    """
    assert os.path.exists( PRIMARY ), f"fixture missing: {PRIMARY}"
    size = os.path.getsize( PRIMARY )

    whole, start, end = read_window_from( PRIMARY, 0, 0 )
    assert start == 0 and end == size
    assert len( whole ) > 1, "the fixture yielded fewer than two records"

    tail_records, tail_start, tail_end = read_tail_bytes( PRIMARY, 65536 )
    assert tail_end == size
    assert tail_start > 0, "a 64 KB tail of a 197 KB file should not start at 0"
    assert tail_records

    earlier, earlier_start, earlier_end = read_window_before( PRIMARY, tail_start, 0 )
    assert earlier_start == 0
    assert earlier_end   == tail_start
    assert len( earlier ) + len( tail_records ) == len( whole ), (
        "the backward page plus the tail do not reconstruct the file exactly — "
        "a record was dropped at the seam or counted twice"
    )


# ── the window verbs' own junk-tolerance ──────────────────────────────────────
#
# These three cases are reached through `_read_window`, which the backward verbs use and
# `tail_jsonl` does not — so the junk tests above, which all go through `tail_jsonl`, leave
# them unexercised. They were found by reading the coverage report's Missing column rather
# than by reasoning about the code, which is the honest account of how they got here.

def test_a_backward_window_with_no_newline_anywhere_is_empty( tmp_path ):
    """
    A window that lands inside a single unterminated line has no boundary to trust.

    Reached only via the skip-partial-first path, i.e. a backward read whose start is > 0.
    """
    path = tmp_path / "noeol.jsonl"
    path.write_text( "x" * 400 )                          # no newline at all
    records, offset, next_offset = read_window_before( path, 400, 50 )
    assert records == [ ]
    assert offset == next_offset == 400


def test_a_backward_window_skips_malformed_json_inside_it( tmp_path ):
    """Malformed lines inside a BACKWARD window are skipped, as they are in a forward tail."""
    path = tmp_path / "junkwin.jsonl"
    path.write_text(
        '{"type": "assistant", "n": 0}\n'
        "this line is not json\n"
        '{"type": "assistant", "n": 1}\n'
    )
    records, _, _ = read_window_before( path, os.path.getsize( path ), 0 )
    assert [ r[ "n" ] for r in records ] == [ 0, 1 ]


def test_a_backward_window_skips_valid_json_that_is_not_an_object( tmp_path ):
    """
    A JSON array or scalar parses cleanly and is still not a record.

    The branch that separates "parsed" from "usable" — a skip that a malformed-line test
    cannot reach, because this line is not malformed.
    """
    path = tmp_path / "nonobj.jsonl"
    path.write_text(
        '{"type": "assistant", "n": 0}\n'
        "[1, 2, 3]\n"
        '"a bare string"\n'
        "17\n"
        '{"type": "assistant", "n": 1}\n'
    )
    records, _, _ = read_window_before( path, os.path.getsize( path ), 0 )
    assert [ r[ "n" ] for r in records ] == [ 0, 1 ]
