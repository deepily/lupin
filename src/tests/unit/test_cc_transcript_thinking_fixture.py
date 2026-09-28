#!/usr/bin/env python3
"""
Guard the `thinking.jsonl` fixture — the one that can tell a dropped block from a
rendered one.

Row 27760534, phase 2. Plan §3 (render rule) and §4 (B4.13, B4.14).
Ruled by Mr. Radio 2026-09-27: *"CAPTURE, don't invent."*

WHY THIS FIXTURE EXISTS, IN ONE PARAGRAPH
------------------------------------------
`primary.jsonl` is faithful and this does not replace it. But measured 2026-09-27 on sha
`f047719d9`, all five of its `thinking` blocks have zero-length text, and so do all 145
in its source transcript. That is not a redaction artifact — `redact_string` preserves
length exactly, and the `signature` on those same blocks survives at 1028-2044 chars.

🔴 THE CONSEQUENCE IS A TEST PROBLEM, NOT A FIXTURE BUG. With every thinking block empty,
**no assertion over rendered text can distinguish a client that RENDERS an empty thinking
block from one that DROPS it.** Both produce nothing. A dropped block is indistinguishable
from a block that never arrived, which is the one failure a live console cannot have —
and over `primary.jsonl` alone, nothing in either client would catch it.

It is the trap `both_clients_issue_the_same_request_for_every_control.test.ts` records in
its own header: an id of `t1` made an encoded and an unencoded client byte-identical, so
the test measured nothing in either direction. The fixture is the whole measurement.

AND THE SHAPE IS REAL. Sweeping the 40 most recently modified transcripts under
`~/.claude/projects/` on 2026-09-27: **3,046 thinking blocks, 2,901 empty, 145 non-empty,
0 `redacted_thinking`**; 11 of the 39 files carrying any thinking have at least one
non-empty block. So roughly one thinking block in twenty in production has words in it,
and a pane fed only `primary.jsonl` has never rendered one.

WHAT THIS FILE ASSERTS
----------------------
That the fixture on disk is the bytes its manifest vouches for, that redaction held, and
— the part that matters — that the fixture **can still discriminate**. A fixture that has
quietly lost its non-empty thinking block, or its `#`, would leave every test written over
it green and blind. Those assertions are the reason this file exists; the sha pin is what
makes them true of the bytes actually on disk.

Venue `:7999` — pure file reads and a pure-function mapper call, no server, well under a
second. It qualifies on all three of the CLAUDE.md § Testing venues criteria.
"""

import hashlib
import json
import os
import sys

import pytest


_here     = os.path.dirname( os.path.abspath( __file__ ) )          # src/tests/unit
_src_path = os.path.dirname( os.path.dirname( _here ) )             # src

FIXTURE_DIR   = os.path.join( _src_path, "tests", "fixtures", "cc_transcript" )
THINKING_PATH = os.path.join( FIXTURE_DIR, "thinking.jsonl" )
MANIFEST_PATH = os.path.join( FIXTURE_DIR, "thinking-manifest.json" )

# The capture script sits beside its fixture rather than on the import path.
if FIXTURE_DIR not in sys.path: sys.path.insert( 0, FIXTURE_DIR )

from capture_thinking_fixture import (           # noqa: E402
    REQUIRED_SHAPES,
    census,
    record_shapes,
    smallest_covering_window,
)

from cosa.rest.cc_transcript_mapper import map_records   # noqa: E402


# ── reading ───────────────────────────────────────────────────────────────────

@pytest.fixture( scope="module" )
def manifest():
    assert os.path.exists( MANIFEST_PATH ), (
        f"{MANIFEST_PATH} is missing. The fixture's provenance lives in the manifest; "
        f"re-run capture_thinking_fixture.py rather than writing one by hand."
    )
    with open( MANIFEST_PATH, encoding="utf-8" ) as handle:
        return json.load( handle )


@pytest.fixture( scope="module" )
def records():
    with open( THINKING_PATH, encoding="utf-8" ) as handle:
        return [ json.loads( line ) for line in handle if line.strip() ]


@pytest.fixture( scope="module" )
def blocks( records ):
    """The fixture as the REAL mapper renders it — real producer through real reader."""
    return map_records( records, budget=0 )


# ── the fixture is the bytes the manifest vouches for ─────────────────────────

def test_the_fixture_matches_the_sha_the_manifest_committed( manifest ):
    """
    The bytes on disk are the bytes the manifest's census was taken over.

    Without this, every census assertion below is about a file that may have been edited
    since the manifest was written — the manifest would be vouching for bytes it never saw.
    """
    with open( THINKING_PATH, "rb" ) as handle:
        digest = hashlib.sha256( handle.read() ).hexdigest()
    assert digest == manifest[ "sha256" ], (
        f"{THINKING_PATH} does not match the manifest's sha256.\n"
        f"  on disk  : {digest}\n"
        f"  manifest : {manifest[ 'sha256' ]}\n"
        f"Either the fixture was hand-edited or the manifest is stale. Re-run "
        f"capture_thinking_fixture.py rather than editing either by hand."
    )


def test_the_manifest_names_its_source_and_the_window_it_cut( manifest ):
    """Provenance a reader can re-derive: which transcript, which records, which rule."""
    assert manifest[ "source_basename" ].endswith( ".jsonl" )
    assert manifest[ "kind" ].startswith( "verbatim contiguous record window" )
    assert "non-empty" in manifest[ "selection_rule" ].lower()

    window = manifest[ "window" ]
    assert window[ "start_record_index" ] <= window[ "end_record_index" ]

    source_count = manifest[ "source_census" ][ "record_count" ]
    assert source_count > manifest[ "census" ][ "record_count" ], (
        "the window covers the whole source file, so nothing was actually selected"
    )


def test_every_line_ends_on_a_complete_record():
    """
    The tailer's complete-line rule holds over this fixture.

    A blank line or a missing final newline would make the fixture exercise a shape the
    tailer never emits, so a test over it would be measuring an impossible input.
    """
    with open( THINKING_PATH, "rb" ) as handle: raw = handle.read()
    assert raw.endswith( b"\n" ),  "thinking.jsonl does not end with a newline"
    assert b"\n\n" not in raw,     "thinking.jsonl contains a blank line"


# ── redaction held ────────────────────────────────────────────────────────────

# Strings that appear throughout the real transcripts on this host and must not survive
# into a committed fixture. This list is a courtesy; the redactor is a PREDICATE — every
# non-structural string leaf is substituted — so it destroys secret shapes by
# construction rather than by matching this list.
LEAK_PROBES = [ "DATA01", "rruiz", "deepily", "sk-ant", "Bearer ", "ANTHROPIC" ]

# The positive control. CLAUDE.md § "Reporting a measurement": prove your instrument can
# find something. Without these, six zeros above are indistinguishable from six
# mis-spelled greps over a file that is one byte long.
STRUCTURE_PROBES = [
    '"type":"assistant"', '"type":"thinking"', '"type":"text"',
    '"type":"tool_use"',  '"type":"tool_result"',
]


@pytest.mark.parametrize( "probe", LEAK_PROBES )
def test_no_real_host_string_survived_the_redaction( probe ):
    """A transcript carries whatever the seat read. This fixture is in git."""
    with open( THINKING_PATH, encoding="utf-8" ) as handle: body = handle.read()
    assert probe not in body, f"{THINKING_PATH} still contains {probe!r} — redaction did not hold"


@pytest.mark.parametrize( "probe", STRUCTURE_PROBES )
def test_the_leak_probe_can_find_something( probe ):
    """
    The positive control for the test above.

    A negative result is worth nothing until the same search has been watched to return a
    positive one. These use the same read and the same `in` test, over the same file.
    """
    with open( THINKING_PATH, encoding="utf-8" ) as handle: body = handle.read()
    assert probe in body, (
        f"{probe!r} not found in thinking.jsonl — the leak probes above are searching a "
        f"file that does not contain what it should, so their zeros mean nothing"
    )


# ── the fixture can still discriminate — the whole point ──────────────────────

def test_the_fixture_carries_BOTH_thinking_arms( blocks ):
    """
    🔴 THE ASSERTION THIS FILE EXISTS FOR.

    One empty thinking block and one with words in it, in the same window. A client that
    drops empty blocks and one that renders them give DIFFERENT answers over this fixture;
    over `primary.jsonl` they give the same answer, because every block there is empty.

    If this ever goes red, every render test written over this fixture has silently
    stopped measuring the thing it was written for.
    """
    thinking = [ b for b in blocks if b[ "kind" ] == "thinking" ]
    empty    = [ b for b in thinking if b[ "text" ] == "" ]
    nonempty = [ b for b in thinking if b[ "text" ] != "" ]

    assert empty, (
        "no EMPTY thinking block — a client that drops empty blocks would now pass, "
        "because there is nothing here for it to drop"
    )
    assert nonempty, (
        "no NON-EMPTY thinking block — this fixture has degenerated into primary.jsonl, "
        "where a renderer and a dropper are indistinguishable"
    )


def test_the_non_empty_thinking_block_has_enough_text_to_assert_on( blocks ):
    """
    Length, not just non-emptiness.

    A one-character thinking block is technically non-empty and practically useless: a
    renderer test needs a distinctive substring it can find on screen.
    """
    nonempty = [ b for b in blocks if b[ "kind" ] == "thinking" and b[ "text" ] ]
    assert nonempty, "no non-empty thinking block at all"
    longest = max( len( b[ "text" ] ) for b in nonempty )
    assert longest >= 100, (
        f"the longest non-empty thinking block is {longest} chars, which is too short to "
        f"anchor a rendering assertion on"
    )


@pytest.mark.parametrize( "kind", [ "text", "thinking", "tool_call", "tool_result" ] )
def test_the_fixture_carries_every_kind_the_mapper_emits( blocks, kind ):
    """
    All four wire kinds, so one fixture drives every arm of the render rule.

    §3: `text` renders as markdown; `tool_call` and `tool_result` render as plain text;
    an unrecognised kind renders as plain text. `thinking` is folded (OSQ-7). A fixture
    missing a kind leaves that arm unexercised in BOTH clients at once.
    """
    assert any( b[ "kind" ] == kind for b in blocks ), (
        f"no {kind!r} block in the fixture — that render arm is unexercised"
    )


@pytest.mark.parametrize( "char, what_markdown_would_do", [
    ( "#", "turn it into a heading" ),
    ( "*", "turn it into a list or emphasis" ),
    ( "`", "turn it into a code span" ),
] )
def test_a_tool_payload_carries_the_characters_markdown_would_mangle( blocks, char, what_markdown_would_do ):
    """
    B4.13's subject matter, pinned in the fixture rather than assumed.

    §3's rule is that tool content does NOT go through the markdown renderer — the hazard
    is MANGLING, not injection. A single-renderer implementation must fail B4.13, and it
    can only fail it if the fixture's tool payload actually carries these characters.

    ⚠️ An earlier capture of this fixture, from a different source, carried NO `#` and NO
    backtick anywhere. It looked fine and could not have told the two designs apart. That
    is why this is asserted rather than trusted.
    """
    tool_text = "".join(
        b[ "text" ] for b in blocks if b[ "kind" ] in ( "tool_call", "tool_result" )
    )
    assert char in tool_text, (
        f"no tool payload in the fixture contains {char!r}, which a markdown renderer "
        f"would {what_markdown_would_do}. B4.13 cannot discriminate over this fixture."
    )


def test_a_tool_payload_carries_indented_lines( blocks ):
    """Indentation is the fourth mangle: a markdown renderer turns it into a code block."""
    tool_text = "".join(
        b[ "text" ] for b in blocks if b[ "kind" ] in ( "tool_call", "tool_result" )
    )
    assert "\n  " in tool_text or "\n\t" in tool_text, (
        "no tool payload carries an indented line, so a markdown renderer's code-block "
        "mangling would not show up over this fixture"
    )


def test_the_mapper_maps_kind_from_the_content_block_not_the_role( blocks ):
    """
    Rule (b) of the mapper, exercised rather than restated.

    A `tool_result` arrives on a record whose role is `user`. A role-based mapping would
    render it as a human turn. This fixture carries that shape, so the rule is watched.
    """
    tool_results = [ b for b in blocks if b[ "kind" ] == "tool_result" ]
    assert tool_results, "no tool_result block — the role-vs-kind rule is unexercised"
    assert any( b[ "role" ] == "user" for b in tool_results ), (
        "no tool_result arrives on a `user` record, so a role-based mapper would pass "
        "this fixture — the very defect mapper rule (b) exists to prevent"
    )


# ── the capture script's own selection logic ──────────────────────────────────

def test_record_shapes_tolerates_every_malformed_record():
    """Never raises on input the real transcripts genuinely contain."""
    for junk in ( None, 42, "a string", [ ], { }, { "message": None },
                  { "message": { } }, { "message": { "content": "a bare string" } },
                  { "message": { "content": [ None, 7, "x" ] } } ):
        assert record_shapes( junk ) == set()


def test_record_shapes_names_the_shapes_a_record_carries():
    """The predicate finds what it should, so its empty answers mean something."""
    record = { "message": { "content": [
        { "type": "thinking",    "thinking": "words here" },
        { "type": "thinking",    "thinking": "" },
        { "type": "text",        "text": "prose" },
        { "type": "tool_use",    "input": { "cmd": "# heading\n  indented" } },
        { "type": "tool_result", "content": "plain" },
    ] } }
    found = record_shapes( record )
    assert "nonempty_thinking" in found
    assert "empty_thinking"    in found
    assert "text"              in found
    assert "tool_use"          in found
    assert "tool_result"       in found
    assert "hash_in_tool"      in found
    assert "indent_in_tool"    in found


# ── the NEGATIVE arms — each predicate must also say NO ───────────────────────
#
# 🔴 THESE EXIST BECAUSE THE TEST ABOVE, ON ITS OWN, IS SATISFIED BY A BROKEN PREDICATE.
# Found by Rio ⚡ in review, 2026-09-27, and confirmed by mutation before it was believed:
# rewriting `_is_nonempty_thinking` to `return block.get( "type" ) == "thinking"` — so that
# an EMPTY thinking block counts as a non-empty one — left all 33 tests GREEN.
#
# The presence-only assertions above cannot catch it, because a predicate that says YES to
# everything still says YES to the thing they look for. And the committed-fixture check is
# no help either: it uses `record_shapes` to verify a fixture that `record_shapes` selected,
# so both sides of the comparison trace back to one implementation. That is a tautology
# wearing an assertion's clothes (CLAUDE.md § Tests) — if the selector is wrong, the
# selection and the check are wrong together and agree perfectly.
#
# The fix is to pin the side the selector cannot move: what each predicate must REFUSE.

def test_an_empty_thinking_block_is_not_counted_as_a_non_empty_one():
    """
    🔴 THE ARM THAT KILLS A YES-TO-EVERYTHING PREDICATE.

    This is the whole distinction the fixture is built on. If it collapses, the capture
    script will happily select a window whose thinking blocks are all empty — i.e. it will
    reproduce `primary.jsonl` and report success, and every test written over the result
    goes green while measuring nothing.
    """
    only_empty = { "message": { "content": [ { "type": "thinking", "thinking": "" } ] } }
    found = record_shapes( only_empty )
    assert "empty_thinking"    in found,     "an empty thinking block was not recognised at all"
    assert "nonempty_thinking" not in found, (
        "an EMPTY thinking block is being counted as a NON-EMPTY one. The capture script "
        "would now accept a window with no thinking text in it, which is exactly the "
        "fixture this file exists to avoid producing."
    )


def test_a_non_empty_thinking_block_is_not_counted_as_an_empty_one():
    """The other direction, so neither predicate can be satisfied by a constant."""
    only_full = { "message": { "content": [ { "type": "thinking", "thinking": "words" } ] } }
    found = record_shapes( only_full )
    assert "nonempty_thinking" in found
    assert "empty_thinking" not in found, (
        "a NON-EMPTY thinking block is being counted as an empty one"
    )


def test_a_tool_payload_without_a_hash_is_not_reported_as_having_one():
    """A yes-to-everything mangle predicate would let a fixture with no `#` through."""
    clean = { "message": { "content": [
        { "type": "tool_result", "content": "no structural characters at all" },
    ] } }
    found = record_shapes( clean )
    assert "tool_result"   in found
    assert "hash_in_tool"  not in found, "a payload with no '#' was reported as carrying one"
    assert "indent_in_tool" not in found, "a payload with no indentation was reported as indented"


def test_a_non_tool_block_never_reports_a_tool_mangle_shape():
    """
    The mangle predicates are scoped to TOOL payloads, not to any text that has a `#`.

    Assistant prose carrying a `#` is markdown and is SUPPOSED to render as a heading. If
    the predicate counted it, a fixture could satisfy `hash_in_tool` with prose alone and
    B4.13 would have nothing to discriminate on.
    """
    prose = { "message": { "content": [
        { "type": "text", "text": "# a real heading\n  and an indented line" },
    ] } }
    found = record_shapes( prose )
    assert "text"           in found
    assert "hash_in_tool"   not in found, "prose satisfied a TOOL-payload predicate"
    assert "indent_in_tool" not in found, "prose satisfied a TOOL-payload predicate"


def test_smallest_covering_window_refuses_rather_than_returning_a_partial_one():
    """
    A source with no covering window is REFUSED, and the refusal names what is missing.

    This is the arm that matters operationally: a source with no non-empty thinking block
    is the COMMON case (2,901 of 3,046 blocks swept were empty). Returning a partial
    window would hand back a fixture that silently cannot discriminate — exactly the
    failure this whole file is about.
    """
    records = [ { "message": { "content": [ { "type": "text", "text": "only prose" } ] } } ]
    with pytest.raises( SystemExit ) as excinfo:
        smallest_covering_window( records )
    message = str( excinfo.value )
    assert "nonempty_thinking" in message, "the refusal does not name the missing shape"
    assert "another transcript" in message, "the refusal does not say what to do next"


def test_smallest_covering_window_returns_the_shortest_span():
    """
    Shortest, not merely *a* covering span.

    Proved by construction: a wide covering span, then a tight one later in the list. A
    first-fit implementation returns the wide one and this goes red.
    """
    def rec( *blocks ): return { "message": { "content": list( blocks ) } }
    think_full  = { "type": "thinking",    "thinking": "words" }
    think_empty = { "type": "thinking",    "thinking": "" }
    text        = { "type": "text",        "text": "prose" }
    tool_use    = { "type": "tool_use",    "input": "# h\n  indented" }
    tool_result = { "type": "tool_result", "content": "plain" }

    records = [
        rec( think_full ), rec( text ), rec( tool_use ),
        rec( think_empty ), rec( tool_result ),                       # wide span 0..4
        rec( think_full, think_empty, text, tool_use, tool_result ),  # tight span 5..5
    ]
    assert smallest_covering_window( records ) == ( 5, 5 )


def test_census_reports_the_thinking_split_the_fixture_turns_on( records ):
    """The manifest's census is the number a reader checks; it must be re-derivable."""
    counted = census( records )
    assert counted[ "thinking_empty" ]    >= 1
    assert counted[ "thinking_nonempty" ] >= 1
    assert counted[ "thinking_len_min" ]  == 0
    assert counted[ "thinking_len_max" ]  >= 100


def test_census_of_an_empty_record_list_is_not_a_crash():
    """The degenerate arm, so the manifest generator cannot die on a bad source."""
    counted = census( [ ] )
    assert counted[ "record_count" ]     == 0
    assert counted[ "thinking_len_min" ] is None
    assert counted[ "thinking_len_max" ] is None


def test_the_manifest_census_matches_a_fresh_one( manifest, records ):
    """
    The recorded census is re-derived, not trusted.

    A manifest that drifted from its fixture is a manifest vouching for a file it no
    longer describes — and every reader who quotes its numbers inherits that.
    """
    assert census( records ) == manifest[ "census" ]


def test_every_required_shape_is_reachable_in_the_committed_fixture( records ):
    """
    The selection predicate still holds over the bytes that shipped.

    `smallest_covering_window` guaranteed this at capture time. This asserts it of the
    file in git, which is the only version anyone runs tests against — it catches a
    fixture that was hand-edited, truncated or regenerated from a poorer source.

    ⚠️ BOUNDED, AND THE BOUND IS THE POINT (Rio ⚡, 2026-09-27). This check uses
    `record_shapes` to verify a fixture that `record_shapes` selected, so both sides trace
    back to ONE implementation: a broken predicate breaks the selection and the check
    together, and they agree perfectly. It can therefore detect a fixture that DRIFTED
    from a correct predicate, and can never detect a predicate that was wrong all along.

    What covers the other half is pinned separately and must not be deleted as redundant:
    the negative arms above (a broken predicate says YES where it must say NO) and
    `test_the_fixture_carries_BOTH_thinking_arms`, which goes through the REAL MAPPER
    rather than through `record_shapes` — a genuinely independent second opinion.
    """
    reachable = set( ).union( *( record_shapes( r ) for r in records ) )
    required  = { name for name, _ in REQUIRED_SHAPES }
    assert required <= reachable, (
        f"the committed fixture no longer covers {sorted( required - reachable )} — "
        f"it has stopped discriminating and every test over it is now blind to that arm"
    )
