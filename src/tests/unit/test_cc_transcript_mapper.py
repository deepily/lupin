#!/usr/bin/env python3
"""
A2.8 — the block mapper's rules, over the REAL captured transcript, not a hand-written fixture.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §2 item 1, AC A2.8.

Why the real fixture and not a hand-rolled one
----------------------------------------------
CLAUDE.md § Tests: "Capture at least one fixture from the real producer through the real
reader. A hand-written fixture is better-formed than reality, exactly where a parser depends
on the mess." Every structural assertion here runs over
`src/tests/fixtures/cc_transcript/primary.jsonl`, a verbatim redacted window captured from a
real lupin transcript, and is cross-checked against the census in its `manifest.json` —
which was computed by a DIFFERENT seat's script. Two routes to the same numbers.

Venue: :7999-eligible — no server, no network, no writes outside tmp_path, sub-second.
"""

import json
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.cc_transcript_mapper import (
    BLOCK_KIND_BY_CONTENT_TYPE,
    DISPLAYABLE_RECORD_TYPES,
    map_record,
    map_records,
)

LUPIN_ROOT   = os.environ.get( "LUPIN_ROOT", os.getcwd() )
FIXTURE_DIR  = os.path.join( LUPIN_ROOT, "src", "tests", "fixtures", "cc_transcript" )
PRIMARY      = os.path.join( FIXTURE_DIR, "primary.jsonl" )
BREADTH      = os.path.join( FIXTURE_DIR, "breadth.jsonl" )
MANIFEST     = os.path.join( FIXTURE_DIR, "manifest.json" )


def _read_jsonl( path ):
    """
    Read a JSONL file into a list of records.

    Ensures:
        - returns the parsed dict records, skipping blank lines
    """
    records = [ ]
    with open( path, "r" ) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append( json.loads( line ) )
    return records


@pytest.fixture( scope="module" )
def primary_records():
    """The real captured transcript window."""
    assert os.path.exists( PRIMARY ), f"fixture missing: {PRIMARY}"
    records = _read_jsonl( PRIMARY )
    assert records, "the primary fixture parsed to ZERO records — every assertion below would vacuously pass"
    return records


@pytest.fixture( scope="module" )
def manifest():
    """The fixture's census, computed by the capture script — the independent side."""
    assert os.path.exists( MANIFEST ), f"manifest missing: {MANIFEST}"
    with open( MANIFEST, "r" ) as f:
        return json.load( f )


# ── the census cross-check ────────────────────────────────────────────────────

def test_the_mapper_agrees_with_the_manifest_census_kind_for_kind( primary_records, manifest ):
    """
    Per-kind agreement with a census this test did not compute.

    This is the assertion that caught a real defect. A first cut of the mapper skipped any
    block whose text was empty, which looked harmless — but the fixture is REDACTED, and
    redaction empties `thinking` text to "". So the skip made the whole thinking path
    unreachable by the only real-transcript fixture available: the branch existed and no
    test could enter it. The mapper emitted 0 thinking blocks while the census counted 5.

    Both sides are pinned to something the other does not derive: the census comes from
    `capture_transcript_fixture.py`, the block counts come from the mapper.
    """
    census = manifest[ "primary" ][ "census" ][ "block_kinds" ]
    shapes = manifest[ "primary" ][ "census" ][ "content_shapes" ]

    blocks = map_records( primary_records, budget=0 )
    counts = { }
    for block in blocks:
        counts[ block[ "kind" ] ] = counts.get( block[ "kind" ], 0 ) + 1

    # `tool_use` is the transcript's name for the content type; `tool_call` is the wire kind.
    assert counts.get( "thinking" )    == census[ "thinking" ]
    assert counts.get( "tool_call" )   == census[ "tool_use" ]
    assert counts.get( "tool_result" ) == census[ "tool_result" ]

    # `text` covers BOTH content shapes: the list-borne text blocks and the bare-string
    # `user` content, which the census counts separately as content_shapes["str"].
    assert counts.get( "text" ) == census[ "text" ] + shapes[ "str" ], (
        f"text blocks {counts.get( 'text' )} != census text {census[ 'text' ]} + "
        f"bare-string contents {shapes[ 'str' ]}"
    )


def test_the_fixture_actually_exercises_every_kind_the_mapper_claims( primary_records ):
    """
    The instrument can find something — all four kinds appear.

    A negative result is worth nothing until the same search has returned a positive one
    (CLAUDE.md § Reporting a measurement). If a kind never appears in the fixture, every
    assertion about it below is vacuous.
    """
    kinds = { block[ "kind" ] for block in map_records( primary_records, budget=0 ) }
    for expected in ( "text", "thinking", "tool_call", "tool_result" ):
        assert expected in kinds, f"the fixture produced no {expected!r} block — assertions about it would be vacuous"


# ── rule (a): unknown record types are skipped, by default not by enumeration ──

def test_an_invented_record_type_is_skipped_silently( ):
    """
    A type nobody enumerated is skipped, not raised on.

    The type set is demonstrably not closed — `atis-latch` and `cost-state` appear in recent
    transcripts and not in older ones — so the rule must be "map what you know". This feeds a
    type invented for the test, which by construction is in nobody's ignore-list.
    """
    record = { "type": "a-type-that-has-never-existed", "message": { "role": "assistant",
               "content": [ { "type": "text", "text": "should not appear" } ] } }
    assert map_record( record ) == [ ]


def test_a_malformed_record_is_skipped_with_the_same_silence( ):
    """
    Malformed input is skipped exactly like an unknown type — no raise, no partial block.

    The second half of A2.8's discriminate-check: feed a record type invented for the test
    and assert it is skipped, then feed a malformed one and assert the same.
    """
    assert map_record( None )                                          == [ ]
    assert map_record( "not a dict" )                                  == [ ]
    assert map_record( 17 )                                            == [ ]
    assert map_record( { } )                                           == [ ]
    assert map_record( { "type": "assistant" } )                       == [ ]
    assert map_record( { "type": "assistant", "message": None } )       == [ ]
    assert map_record( { "type": "assistant", "message": "a string" } ) == [ ]
    assert map_record( { "type": "assistant", "message": { "content": 42 } } ) == [ ]


def test_every_breadth_record_type_is_skipped_rather_than_crashing( ):
    """
    The breadth fixture is one real record per type ABSENT from the primary window.

    Six real record types — bridge-session, cost-state, file-history-delta,
    file-history-snapshot, relocated, worktree-state — none of them displayable. The mapper
    must skip all six, and skipping is what "a transcript is mostly not messages" means in
    practice.
    """
    assert os.path.exists( BREADTH ), f"fixture missing: {BREADTH}"
    records = _read_jsonl( BREADTH )
    assert records, "the breadth fixture parsed to ZERO records — this test would vacuously pass"
    assert map_records( records ) == [ ]


# ── rule (b): kind comes from the content block, never the role ────────────────

def test_a_user_record_carrying_a_tool_result_is_not_a_human_turn( primary_records, manifest ):
    """
    The defect this rule exists to prevent, asserted over real records.

    760 of the 1,026 `user` records in the plan's census carry tool_results. A role-based
    mapping would render three quarters of them as fake human turns — the machine's own tool
    output attributed to the person. The fixture carries 8 such records.
    """
    expected = manifest[ "primary" ][ "census" ][ "user_records_carrying_tool_result" ]
    assert expected > 0, "the fixture holds no tool-result-bearing user record — this test would be vacuous"

    tool_results_from_user = 0
    for record in primary_records:
        if record.get( "type" ) != "user": continue
        for block in map_record( record ):
            if block[ "kind" ] == "tool_result":
                tool_results_from_user += 1
                # The ROLE still says user — that is the transcript's own framing and is
                # preserved. What must NOT happen is the KIND following the role.
                assert block[ "role" ] == "user"

    assert tool_results_from_user == expected, (
        f"{tool_results_from_user} tool_result blocks mapped from user records, census says {expected}"
    )


def test_no_user_borne_tool_result_is_ever_mapped_as_text( primary_records ):
    """
    The same rule stated as the negative, which is the arm a regression would trip.

    A role-based mapper passes the count test above by accident if it happens to emit the
    right number of blocks; it fails this one, because those blocks would carry kind `text`.
    """
    for record in primary_records:
        if record.get( "type" ) != "user": continue
        content = record.get( "message", { } ).get( "content" )
        if not isinstance( content, list ): continue
        carries_result = any( isinstance( b, dict ) and b.get( "type" ) == "tool_result" for b in content )
        if not carries_result: continue
        kinds = { block[ "kind" ] for block in map_record( record ) }
        assert "text" not in kinds, f"a tool-result-bearing user record mapped to text: {kinds}"


# ── rule (c): message.content has two shapes ──────────────────────────────────

def test_a_bare_string_content_maps_to_one_text_block( ):
    """`message.content` as a plain string — 260 of the census's cases."""
    record = { "type": "user", "timestamp": "2026-09-27T18:00:00Z",
               "message": { "role": "user", "content": "  what is the red count?  " } }
    blocks = map_record( record )
    assert len( blocks ) == 1
    assert blocks[ 0 ][ "kind" ] == "text"
    assert blocks[ 0 ][ "text" ] == "what is the red count?"
    assert blocks[ 0 ][ "role" ] == "user"
    assert blocks[ 0 ][ "ts" ]   == "2026-09-27T18:00:00Z"


def test_an_empty_bare_string_still_yields_a_block( ):
    """
    Emptiness is content; absence is what an unrecognised type handles.

    Guards the fix for the thinking-path defect: a skip-if-empty rule here is the same rule
    that hid `thinking` entirely under redaction.
    """
    record = { "type": "user", "message": { "role": "user", "content": "   " } }
    blocks = map_record( record )
    assert len( blocks ) == 1
    assert blocks[ 0 ][ "text" ] == ""


def test_a_list_content_maps_each_recognised_block_in_order( ):
    """Both shapes, and order preserved — a console that reorders is a console that lies."""
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "text",     "text": "first" },
        { "type": "thinking", "thinking": "second" },
        { "type": "tool_use", "name": "Bash", "input": { "command": "ls" } },
        { "type": "image",    "source": "ignored — unrecognised content type" },
    ] } }
    blocks = map_record( record )
    assert [ b[ "kind" ] for b in blocks ] == [ "text", "thinking", "tool_call" ]
    assert blocks[ 0 ][ "text" ] == "first"
    assert blocks[ 1 ][ "text" ] == "second"


def test_a_non_dict_inside_the_content_list_is_skipped( ):
    """A list carrying junk still yields its good blocks."""
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        "a bare string inside the list", None, 42,
        { "type": "text", "text": "survivor" },
    ] } }
    blocks = map_record( record )
    assert len( blocks ) == 1
    assert blocks[ 0 ][ "text" ] == "survivor"


# ── the thinking path, which redaction nearly hid ─────────────────────────────

def test_an_empty_thinking_block_is_still_emitted( ):
    """
    The regression guard for the defect the census caught.

    Delete the empty-text handling and this reddens while nothing else does — which is what
    "prove it watches" means. Under redaction EVERY thinking block in the fixture is empty,
    so if empties were dropped this path would be unreachable and silently uncovered.
    """
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "thinking", "thinking": "", "signature": "xxx" },
    ] } }
    blocks = map_record( record )
    assert len( blocks ) == 1
    assert blocks[ 0 ][ "kind" ]      == "thinking"
    assert blocks[ 0 ][ "text" ]      == ""
    assert blocks[ 0 ][ "truncated" ] is False


def test_every_thinking_block_in_the_real_fixture_is_empty( primary_records ):
    """
    States the fixture property the test above depends on, so it cannot rot silently.

    If a future re-capture carries unredacted thinking text, this test fails and tells the
    next reader that the empty-block guard is no longer being exercised by real data — which
    is information, not a nuisance.
    """
    texts = [ b[ "text" ] for b in map_records( primary_records ) if b[ "kind" ] == "thinking" ]
    assert texts, "no thinking blocks in the fixture"
    assert all( t == "" for t in texts ), (
        "a thinking block in the fixture now carries text — the redaction changed, so "
        "test_an_empty_thinking_block_is_still_emitted is no longer backed by real data"
    )


# ── the budget, and the 0-means-unbounded sense ───────────────────────────────

def test_a_block_over_its_budget_is_truncated_and_flagged( ):
    """A2.4's first half, at the mapper level."""
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "text", "text": "x" * 500 },
    ] } }
    blocks = map_record( record, budget=100 )
    assert len( blocks[ 0 ][ "text" ] ) == 100
    assert blocks[ 0 ][ "truncated" ] is True


def test_budget_zero_means_unbounded_not_zero( ):
    """
    A2.4's second half, and the one most likely to be got backwards.

    `routers/tasks.py` already documents `budget == 0` as UNBOUNDED in this tree. A reader
    who assumes a `cap` would expect 0 to allow nothing, which would truncate every block to
    empty while reporting success.
    """
    long_text = "y" * 10000
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "text", "text": long_text },
    ] } }
    blocks = map_record( record, budget=0 )
    assert blocks[ 0 ][ "text" ]      == long_text
    assert blocks[ 0 ][ "truncated" ] is False


def test_the_budget_is_measured_in_bytes_not_characters( ):
    """
    A multi-byte block must not overrun a byte budget while reporting that it fit.

    The offsets and the ring are byte-measured, so a character-counting budget would let a
    block of multi-byte text exceed the byte budget with truncated=False.
    """
    # Each '€' is 3 UTF-8 bytes: 10 characters, 30 bytes.
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "text", "text": "€" * 10 },
    ] } }
    blocks = map_record( record, budget=15 )
    assert blocks[ 0 ][ "truncated" ] is True
    assert len( blocks[ 0 ][ "text" ].encode( "utf-8" ) ) <= 15


def test_truncating_mid_character_does_not_raise( ):
    """A budget landing inside a multi-byte sequence drops the partial char rather than throwing."""
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "text", "text": "€€€" },
    ] } }
    blocks = map_record( record, budget=4 )      # 4 bytes cuts the second '€' in half
    assert blocks[ 0 ][ "truncated" ] is True
    assert blocks[ 0 ][ "text" ] == "€"


# ── tool call and tool result rendering ───────────────────────────────────────

def test_a_tool_call_renders_as_a_one_line_chip( ):
    """
    Ruling Q2's one-line chip. A newline in the input must not turn a chip into a paragraph.
    """
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "tool_use", "name": "Bash", "input": { "command": "ls\n-la", "timeout": 30 } },
    ] } }
    text = map_record( record )[ 0 ][ "text" ]
    assert "\n" not in text
    assert text.startswith( "Bash( " )
    assert "command=ls -la" in text
    assert "timeout=30" in text


def test_a_tool_call_with_a_non_dict_input_still_renders( ):
    """Input is not always a dict in the wild."""
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "tool_use", "name": "Weird", "input": "a\nbare string" },
    ] } }
    text = map_record( record )[ 0 ][ "text" ]
    assert text == "Weird( a bare string )"


def test_a_tool_call_with_no_name_or_input_degrades_rather_than_raising( ):
    """A malformed tool_use is still a block; it is not an exception."""
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "tool_use" },
    ] } }
    blocks = map_record( record )
    assert len( blocks ) == 1
    assert blocks[ 0 ][ "text" ] == "tool(  )"


@pytest.mark.parametrize( "content,expected", [
    ( "a plain string result",                                  "a plain string result" ),
    ( [ { "type": "text", "text": "line one" },
        { "type": "text", "text": "line two" } ],               "line one\nline two" ),
    ( [ { "type": "text", "text": "kept" },
        { "type": "image", "source": "x" } ],                   "kept" ),
    ( [ "bare", None, 7 ],                                      "bare\n7" ),
    ( None,                                                     "" ),
    ( 42,                                                       "42" ),
    ( [ ],                                                      "" ),
] )
def test_a_tool_result_flattens_both_of_its_content_shapes( content, expected ):
    """
    `tool_result.content` is a string in some records and a list of blocks in others.

    Parametrised so a failure names WHICH shape broke rather than reporting "the flattener
    differs".
    """
    record = { "type": "user", "message": { "role": "user", "content": [
        { "type": "tool_result", "tool_use_id": "t1", "content": content },
    ] } }
    blocks = map_record( record )
    assert len( blocks ) == 1
    assert blocks[ 0 ][ "kind" ] == "tool_result"
    assert blocks[ 0 ][ "text" ] == expected


# ── shape of the wire block, and the module's own declarations ────────────────

def test_every_block_carries_the_five_wire_fields_and_a_tool_call_its_name( primary_records ):
    """
    The contract §3 publishes, asserted over every block the real fixture produces.

    A missing field is a client-side crash, and it would show up nowhere else in this file.
    """
    blocks = map_records( primary_records, budget=64 )
    assert blocks
    for block in blocks:
        # A tool_call also carries its tool's `name` (row 4559be88); no other kind does.
        expected = { "ts", "role", "kind", "text", "truncated" } | ( { "name" } if block[ "kind" ] == "tool_call" else set() )
        assert set( block ) == expected
        assert isinstance( block[ "ts" ], str )
        assert isinstance( block[ "role" ], str )
        assert isinstance( block[ "text" ], str )
        assert isinstance( block[ "truncated" ], bool )
        assert block[ "kind" ] in set( BLOCK_KIND_BY_CONTENT_TYPE.values() )


def test_a_record_without_a_timestamp_yields_an_empty_ts_not_a_crash( ):
    """A missing timestamp is a display problem, never a mapping failure."""
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "text", "text": "no stamp" },
    ] } }
    assert map_record( record )[ 0 ][ "ts" ] == ""


def test_a_message_without_a_role_falls_back_to_the_record_type( ):
    """
    The role is display metadata, so it degrades rather than failing.

    Note this is the ONE place the record's type informs a field — and it is `role`, never
    `kind`. That distinction is rule (b).
    """
    record = { "type": "assistant", "message": { "content": [ { "type": "text", "text": "x" } ] } }
    assert map_record( record )[ 0 ][ "role" ] == "assistant"


def test_the_displayable_types_are_the_two_message_types( ):
    """
    Pins the module's declaration, so widening it is a deliberate edit with a test to update.
    """
    assert DISPLAYABLE_RECORD_TYPES == frozenset( [ "assistant", "user" ] )


def test_the_content_type_to_kind_map_is_the_four_ruled_kinds( ):
    """
    `tool_use` -> `tool_call` is the only rename, and `thinking` is present per ruling OSQ-7.
    """
    assert BLOCK_KIND_BY_CONTENT_TYPE == {
        "text"        : "text",
        "thinking"    : "thinking",
        "tool_use"    : "tool_call",
        "tool_result" : "tool_result",
    }


def test_map_records_over_an_empty_iterable_is_empty_not_an_error( ):
    """A loop over nothing passes every assertion in it, so state the empty case explicitly."""
    assert map_records( [ ] ) == [ ]
