#!/usr/bin/env python3
"""
Guard: the console-tee fixture is a CAPTURED transcript, not a hand-written one.

Why this file exists
--------------------
The console-tee plan (`src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`,
sha256 a605dc8c0249) makes the fixture's provenance a named requirement. A2.8 reads
"over a real captured transcript, not a hand-written fixture", and P2's census is the
reason: `user` + `assistant` are ~34% of records across thirteen record types, and 760
of 1,026 `user` records carry tool_results rather than human turns.

But "capture it from the real producer" is an instruction, and CLAUDE.md § "Writing a
rule or a guard" says a rule that depends on remembering is not installed. Nothing
stops a later hand keeping the filename and writing the records by hand — at which
point every test over it still passes, and the plan's requirement has been quietly
retired with no failing test anywhere. This file is the control.

What it asserts, and what it deliberately does not
--------------------------------------------------
It asserts the fixture carries the message MESS the mapper depends on: both
`message.content` shapes, every content-block kind, `user` records whose content is a
tool_result rather than a human turn, record types beyond the message ones, and a
committed sha that matches the bytes on disk. A hand-written fixture would have to
reproduce all of that to get past here — which is most of the way to capturing one.

It does NOT claim to prove the file came off a real seat. A determined hand could
satisfy every assertion below synthetically. The honest statement is that this guard
raises the cost of a hand-written fixture above the cost of running the capture
script, and that `manifest.json` is where the provenance actually lives.

⚠️ It also does not test the block mapper. There is no mapper yet; A2.8 tests that,
against this fixture, once the Implementer's server lands.

Venue: :7999-eligible — pure module, reads two committed files, no server, no network,
no writes, sub-second.
"""

import hashlib
import json
import os
import sys

import pytest

# Bootstrap — this file is read before `cosa` is guaranteed importable
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

FIXTURE_DIR   = os.path.join( _src_path, "tests", "fixtures", "cc_transcript" )
PRIMARY_PATH  = os.path.join( FIXTURE_DIR, "primary.jsonl" )
BREADTH_PATH  = os.path.join( FIXTURE_DIR, "breadth.jsonl" )
MANIFEST_PATH = os.path.join( FIXTURE_DIR, "manifest.json" )

# Ruling Q6 caps the backlog at ~64 KB. A fixture at or below the cap cannot tell
# "the last 64 KB" from "the whole file", so A2.9's tail_bytes arm would pass against
# a forward-only server — the exact discrimination it is written to prove.
Q6_BACKLOG_CAP_BYTES = 65536


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_jsonl( path ):
    """
    Read a JSONL fixture into a list of dicts, failing loudly on any bad line.

    A fixture is committed data, not input from the wild: a line this cannot parse is
    a corrupted fixture, and skipping it silently is how a fixture shrinks without
    anyone noticing. `read_records` in the capture script skips; this does not.

    Requires:
        - path names a readable newline-delimited JSON file

    Ensures:
        - returns a list of dicts, one per non-empty line, in file order

    Raises:
        - AssertionError naming the line number if a line is not a JSON object
    """
    records = []
    with open( path, encoding="utf-8" ) as handle:
        for lineno, raw in enumerate( handle, start=1 ):
            stripped = raw.strip()
            if not stripped: continue
            try:
                record = json.loads( stripped )
            except ValueError as error:
                raise AssertionError( f"{path}:{lineno} is not parseable JSON: {error}" )
            assert isinstance( record, dict ), f"{path}:{lineno} is JSON but not an object"
            records.append( record )
    return records


def _block_kinds( records ):
    """Return the set of content-block `type` values across every list-shaped message."""
    kinds = set()
    for record in records:
        message = record.get( "message" )
        if not isinstance( message, dict ): continue
        content = message.get( "content" )
        if not isinstance( content, list ): continue
        for block in content:
            if isinstance( block, dict ): kinds.add( block.get( "type" ) )
    return kinds


def _content_shapes( records ):
    """Return the set of `message.content` python shapes seen, as 'str' / 'list'."""
    shapes = set()
    for record in records:
        message = record.get( "message" )
        if not isinstance( message, dict ): continue
        content = message.get( "content" )
        if   isinstance( content, str  ): shapes.add( "str" )
        elif isinstance( content, list ): shapes.add( "list" )
    return shapes


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture( scope="module" )
def manifest():
    assert os.path.isfile( MANIFEST_PATH ), (
        f"{MANIFEST_PATH} is missing. The fixture's provenance lives in the manifest; "
        f"without it nobody can say which transcript this came from. Re-run "
        f"src/tests/fixtures/cc_transcript/capture_transcript_fixture.py"
    )
    with open( MANIFEST_PATH, encoding="utf-8" ) as handle:
        return json.load( handle )


@pytest.fixture( scope="module" )
def primary():
    return _read_jsonl( PRIMARY_PATH )


@pytest.fixture( scope="module" )
def breadth():
    return _read_jsonl( BREADTH_PATH )


# ── the fixture is intact and is the one the manifest describes ────────────────

@pytest.mark.parametrize( "slot, path", [ ( "primary", PRIMARY_PATH ), ( "breadth", BREADTH_PATH ) ] )
def test_each_fixture_matches_the_sha_the_manifest_committed( manifest, slot, path ):
    """
    The bytes on disk are the bytes the manifest's census was taken over.

    Without this, every census assertion below is about a file that may have been
    edited since the manifest was written — the manifest would be vouching for bytes
    it never saw. This is the pin that makes the rest of the file mean something.
    """
    with open( path, "rb" ) as handle: digest = hashlib.sha256( handle.read() ).hexdigest()
    assert digest == manifest[ slot ][ "sha256" ], (
        f"{path} does not match manifest['{slot}']['sha256'].\n"
        f"  on disk  : {digest}\n"
        f"  manifest : {manifest[ slot ][ 'sha256' ]}\n"
        f"Either the fixture was edited without re-running the capture script, or the "
        f"manifest is stale. Re-run capture_transcript_fixture.py rather than editing "
        f"either by hand."
    )


def test_the_manifest_names_the_transcript_and_the_window_it_cut( manifest ):
    """
    Provenance is recorded, not implied: a source file, a record window, a census.

    CLAUDE.md § "Reporting a measurement" — name the population before you trust a
    result. A fixture with no recorded source is a population nobody can name.
    """
    primary_manifest = manifest[ "primary" ]
    assert primary_manifest[ "source_basename" ].endswith( ".jsonl" )
    assert primary_manifest[ "kind" ].startswith( "verbatim contiguous record window" )

    window = primary_manifest[ "window" ]
    assert window[ "end_record_index" ] > window[ "start_record_index" ]

    # The window is a strict slice of a larger real file — not the whole thing dressed
    # up as a window. If start is 0 and end is the source's record count, "contiguous
    # window" is doing no work and the size claim below is about an entire transcript.
    source_count = primary_manifest[ "source_census" ][ "record_count" ]
    assert source_count > primary_manifest[ "census" ][ "record_count" ], (
        "the manifest's window covers the whole source file, so nothing was selected"
    )


# ── the fixture carries the mess the mapper depends on (A2.8 / P2) ─────────────

def test_primary_carries_both_message_content_shapes( primary ):
    """
    P2 measured `message.content` as a bare string in 260 cases and a list in the rest.

    §2 item 1(c) makes handling both a mapper rule. A fixture with only one shape
    cannot fail a mapper that handles only that one — the test would be green and the
    other shape unwatched.
    """
    shapes = _content_shapes( primary )
    assert shapes == { "str", "list" }, (
        f"expected both message.content shapes, got {sorted( shapes )}. A mapper that "
        f"handles only one shape would pass against this fixture."
    )


def test_primary_carries_every_content_block_kind( primary ):
    """
    All four kinds P2 counted are present: text, thinking, tool_use, tool_result.

    `thinking` is here because OSQ-7 ruled it shown folded — it is rendered content,
    not noise, and P2 counted it outnumbering assistant `text` 424 to 520.
    """
    kinds = _block_kinds( primary )
    for required in ( "text", "thinking", "tool_use", "tool_result" ):
        assert required in kinds, f"content-block kind '{required}' absent; got {sorted( kinds )}"


def test_primary_carries_user_records_whose_content_is_a_tool_result( primary ):
    """
    The single most consequential property in P2's census, and the reason for the rule
    "a block's `kind` comes from the content block's type, never from the record's
    role" (§3 wire contract). 760 of 1,026 `user` records carry tool_results, so a
    role-based mapper renders three quarters of them as fake human turns.

    This asserts the fixture can CATCH that mapper. Without such a record present, a
    role-based mapper passes.
    """
    offenders = 0
    for record in primary:
        if record.get( "type" ) != "user": continue
        message = record.get( "message" )
        if not isinstance( message, dict ): continue
        content = message.get( "content" )
        if not isinstance( content, list ): continue
        if any( isinstance( b, dict ) and b.get( "type" ) == "tool_result" for b in content ):
            offenders += 1

    assert offenders > 0, (
        "no `user` record in the fixture carries a tool_result, so a mapper that reads "
        "`kind` off the record's ROLE would pass every test over this fixture — which "
        "is the defect §2 item 1(c) names"
    )


def test_the_fixtures_together_carry_record_types_beyond_the_message_ones( primary, breadth ):
    """
    §2 item 1(a): unrecognised record types are SKIPPED, by default rather than by
    enumeration — and the type set is demonstrably not closed.

    A2.8 tests the skip. It can only do so over a fixture that actually contains types
    a mapper has no branch for, so this asserts they are present and that there are
    several of them: one such type could be special-cased by name and the skip rule
    would still be unwritten.
    """
    message_types = { "user", "assistant" }
    seen          = { r.get( "type" ) for r in primary } | { r.get( "type" ) for r in breadth }
    unrecognised  = seen - message_types

    assert len( unrecognised ) >= 8, (
        f"only {len( unrecognised )} non-message record types present "
        f"({sorted( unrecognised )}). A2.8's skip rule needs enough of them that "
        f"enumerating each by name is plainly the wrong implementation."
    )


def test_breadth_adds_types_the_primary_window_does_not_have( primary, breadth ):
    """
    The breadth file earns its place, or it is 2 KB of duplication.

    It is a composite rather than a contiguous window — the manifest says so — and its
    only job is widening the record-type set. If every type in it already appears in
    primary, it adds nothing and A2.8 should read primary alone.
    """
    primary_types = { r.get( "type" ) for r in primary }
    breadth_types = { r.get( "type" ) for r in breadth }
    assert breadth_types, "breadth.jsonl is empty"
    assert not ( breadth_types & primary_types ), (
        f"breadth repeats types primary already has: "
        f"{sorted( breadth_types & primary_types )}"
    )


# ── the fixture is large enough for the ruled backlog rules (A2.9) ─────────────

def test_primary_is_larger_than_the_ruled_backlog_cap():
    """
    A2.9 must be able to fail a forward-only server, and size is what decides that.

    Ruling Q6 caps the backlog at ~64 KB. If the fixture were at or under the cap,
    `?tail_bytes=65536` and `?since_offset=0` would return the SAME bytes, so the
    "returns the LAST N bytes, not the first" assertion would hold for an
    implementation that reads forward from zero. The fixture is sized past the cap on
    purpose — see --min-bytes in the capture script.
    """
    size = os.path.getsize( PRIMARY_PATH )
    assert size > 2 * Q6_BACKLOG_CAP_BYTES, (
        f"primary.jsonl is {size:,} bytes, which is not comfortably past ruling Q6's "
        f"{Q6_BACKLOG_CAP_BYTES:,}-byte cap. A2.9's tail_bytes arm cannot discriminate "
        f"a forward-only implementation at this size."
    )


def test_every_line_ends_on_a_complete_record():
    """
    `next_offset` always lands at the end of a complete line (§3 wire contract).

    A fixture whose last line lacks its newline would make every offset-chaining
    assertion in the integration suite depend on how the server treats a trailing
    partial line — a property of the fixture masquerading as a property of the server.
    """
    with open( PRIMARY_PATH, "rb" ) as handle: raw = handle.read()
    assert raw.endswith( b"\n" ), "primary.jsonl does not end with a newline"
    assert b"\n\n" not in raw,    "primary.jsonl contains a blank line"


# ── the redaction held (this fixture is committed to git) ──────────────────────

# Strings that appear throughout the real transcripts on this host and must not
# survive into a committed fixture. Every one is checked against BOTH files.
LEAK_PROBES = [ "DATA01", "rruiz", "deepily", "sk-ant", "Bearer ", "ANTHROPIC" ]

# The positive control. CLAUDE.md § "Reporting a measurement": prove your instrument
# can find something. Without these, six zeros above are indistinguishable from six
# mis-spelled greps over a file that is one byte long.
STRUCTURE_PROBES = [ '"type":"assistant"', '"type":"tool_result"', '"type":"thinking"' ]


@pytest.mark.parametrize( "probe", LEAK_PROBES )
def test_no_real_host_string_survived_the_redaction( probe ):
    """A transcript carries whatever the seat read. This fixture is in git."""
    for path in ( PRIMARY_PATH, BREADTH_PATH ):
        with open( path, encoding="utf-8" ) as handle: body = handle.read()
        assert probe not in body, f"{path} still contains {probe!r} — redaction did not hold"


@pytest.mark.parametrize( "probe", STRUCTURE_PROBES )
def test_the_leak_probe_can_find_something( probe ):
    """
    The positive control for the test above.

    A negative result is worth nothing until the same search has been watched to
    return a positive one. These probes use the same read and the same `in` test as
    the leak probes, over the same file.
    """
    with open( PRIMARY_PATH, encoding="utf-8" ) as handle: body = handle.read()
    assert probe in body, (
        f"{probe!r} not found in primary.jsonl — the leak probes above are searching a "
        f"file that does not contain what it should, so their zeros mean nothing"
    )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
