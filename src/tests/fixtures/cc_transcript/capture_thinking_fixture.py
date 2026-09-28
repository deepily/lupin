#!/usr/bin/env python3
"""
Capture a transcript window that carries a NON-EMPTY `thinking` block.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §3 (render rule) and
§4 (B4.13, B4.14). Row 27760534, phase 2. Ruled by Mr. Radio 2026-09-27: *"CAPTURE,
don't invent"*.

Why a SECOND fixture rather than an edit to `primary.jsonl`
-----------------------------------------------------------
`primary.jsonl` is FAITHFUL and this script does not replace it. Measured 2026-09-27 on
sha `f047719d9`:

    map_records( primary.jsonl, budget=0 ) -> 29 blocks
      text 7 (len 19..1300) · tool_call 9 (312..3783) · tool_result 8 (39..24430)
      thinking 5 — len min=0, MAX=0

All five of its `thinking` blocks are empty, and that is **not** a redaction artifact:
`redact_string` preserves length exactly (the sibling `signature` on those same blocks
survives at 1028-2044 chars), and the source transcript
`57238c9d-c227-469e-b707-13b7752a7399.jsonl` carries 145 thinking blocks of which 145 are
empty. The capture was correct; the source simply had no thinking text.

🔴 THE PROBLEM THAT CREATES, WHICH IS A TEST PROBLEM AND NOT A FIXTURE BUG. With every
thinking block at zero length, **no assertion over rendered text can tell a client that
RENDERS an empty thinking block from one that DROPS it** — both produce the same empty
output. That is the trap
`src/tests/unit/notifications_js/both_clients_issue_the_same_request_for_every_control.test.ts`
records in its own header: an id of `t1` made an encoded and an unencoded client
byte-identical, so the test measured nothing in either direction. A dropped block is
indistinguishable from a block that never arrived, which is the one failure a live console
cannot have.

🔴 AND THE SHAPE IS REAL, NOT HYPOTHETICAL. Sweeping the 40 most recently modified
transcripts under `~/.claude/projects/` on 2026-09-27: **3,046 thinking blocks, 2,901
empty, 145 non-empty, 0 `redacted_thinking`**. Eleven of the 39 files carrying any thinking
have at least one non-empty block. So a pane fed only `primary.jsonl` has never rendered a
thinking block with words in it, while roughly one block in twenty in production has them.

What this script selects
------------------------
The **smallest contiguous record window** covering all five of:

    a non-empty `thinking` block   — the shape primary.jsonl lacks entirely
    an EMPTY `thinking` block      — so one fixture pins both arms of the fold
    a `text` block                 — the markdown path, for the §3 two-render-paths rule
    a `tool_use` block             — the plain-text path
    a `tool_result` block          — the plain-text path, and the role-vs-kind rule
    a tool payload carrying `#`    — B4.13: a markdown renderer turns it into a heading
    a tool payload carrying indent — B4.13: a markdown renderer turns it into a code block

Both thinking arms in ONE window is the point. A client that drops empty blocks and a
client that renders them give different answers over this fixture. So do a one-renderer
and a two-renderer client, because the same window carries tool payloads with `#` and
with indented lines — the characters B4.13 names. Neither difference is visible in
`primary.jsonl`, whose thinking blocks are all empty and whose tool payloads carry no `#`
and no backticks at all (measured 2026-09-27).

⚠️ THE LAST TWO SHAPES ARE WHY THE WINDOW IS CHOSEN THIS WAY RATHER THAN MINIMALLY. An
earlier cut of this script required only the first five and produced a clean 12-record
window from a different source — which carried no `#` and no backtick anywhere, so it
could not have told a single-renderer implementation from a two-renderer one. It is
recorded here rather than quietly replaced: a fixture that cannot discriminate is the
failure this whole file exists to prevent, and it is easy to build one by accident.

Redaction
---------
The SAME redactor as `capture_transcript_fixture.py`, imported rather than re-implemented
— one rule, one implementation. It is a PREDICATE, not a blocklist: every string leaf not
reached through a structural key has `a-z -> x`, `A-Z -> X`, `0-9 -> 7`, with length,
whitespace, punctuation and non-ASCII preserved. So keys, tokens, emails and private paths
are destroyed **by construction** rather than by a list of things to look for, which is a
list that goes stale silently (CLAUDE.md § "Writing a rule or a guard").

Length preservation is what makes the fixture still useful: a redacted non-empty thinking
block is still non-empty, so "the text renders" remains assertable.

Usage
-----
    python3 src/tests/fixtures/cc_transcript/capture_thinking_fixture.py \\
        --source ~/.claude/projects/<project>/<uuid>.jsonl \\
        --out-dir src/tests/fixtures/cc_transcript

Re-run it rather than editing the fixture by hand; the manifest's sha is what
`test_cc_transcript_thinking_fixture.py` pins, and a hand edit makes the manifest vouch
for bytes it never saw.
"""

import argparse
import hashlib
import json
import os
import sys

# The redactor is imported, never re-implemented — see the module docstring. This file
# sits beside its source, so the directory is on the path when run as a script; when
# imported as a module the package path resolves it instead.
sys.path.insert( 0, os.path.dirname( os.path.abspath( __file__ ) ) )

from capture_transcript_fixture import read_records, redact_node, write_fixture  # noqa: E402


# The five block shapes the window must cover, each a (name, predicate) pair. Written as
# predicates over a content block rather than as a list of type strings, so a shape is
# described by what it IS rather than by a name that may drift.
def _is_nonempty_thinking( block ):
    return block.get( "type" ) == "thinking" and block.get( "thinking", "" ) != ""


def _is_empty_thinking( block ):
    return block.get( "type" ) == "thinking" and block.get( "thinking", "" ) == ""


def _is_text( block ):
    return block.get( "type" ) == "text"


def _is_tool_use( block ):
    return block.get( "type" ) == "tool_use"


def _is_tool_result( block ):
    return block.get( "type" ) == "tool_result"


def _tool_payload_text( block ):
    """
    Render a tool block's payload as text for the markdown-mangling predicates.

    Requires:
        - block is a dict content block

    Ensures:
        - returns a str for a tool_use / tool_result block, "" for anything else
        - never raises on a payload that is a str, a list, a dict or absent
    """
    if block.get( "type" ) not in ( "tool_use", "tool_result" ): return ""
    payload = block.get( "content" )
    if payload is None: payload = block.get( "input" )
    if payload is None: return ""
    if isinstance( payload, str ): return payload
    return json.dumps( payload, ensure_ascii=False )


def _tool_carries_hash( block ):
    """A tool payload carrying '#', which a markdown renderer turns into a heading."""
    return "#" in _tool_payload_text( block )


def _tool_carries_indent( block ):
    """A tool payload carrying indentation, which a markdown renderer turns into a code block."""
    text = _tool_payload_text( block )
    return "\n  " in text or "\n\t" in text or "\\n  " in text or "\\t" in text


REQUIRED_SHAPES = (
    ( "nonempty_thinking", _is_nonempty_thinking ),
    ( "empty_thinking",    _is_empty_thinking    ),
    ( "text",              _is_text              ),
    ( "tool_use",          _is_tool_use          ),
    ( "tool_result",       _is_tool_result       ),
    # B4.13's two — a single-renderer implementation mangles these and a two-renderer
    # one does not, so without them the fixture cannot tell the designs apart.
    ( "hash_in_tool",      _tool_carries_hash    ),
    ( "indent_in_tool",    _tool_carries_indent  ),
)


def record_shapes( record ):
    """
    Name the required shapes a single record carries.

    Requires:
        - record is a parsed JSONL record (any JSON value; non-dicts are tolerated)

    Ensures:
        - returns a set of shape names drawn from REQUIRED_SHAPES
        - returns an empty set for a record with no list-shaped `message.content`
        - never raises on malformed input
    """
    if not isinstance( record, dict ): return set()
    message = record.get( "message" )
    if not isinstance( message, dict ): return set()
    content = message.get( "content" )
    if not isinstance( content, list ): return set()

    found = set()
    for block in content:
        if not isinstance( block, dict ): continue
        for name, predicate in REQUIRED_SHAPES:
            if predicate( block ): found.add( name )
    return found


def smallest_covering_window( records ):
    """
    Find the shortest contiguous record span covering every required shape.

    Requires:
        - records is a list of parsed JSONL records

    Ensures:
        - returns ( start, end ) inclusive indices of the shortest covering span
        - raises SystemExit with a diagnostic naming the MISSING shapes when no span
          covers all of them — never returns a partial window silently

    Raises:
        - SystemExit if the source carries no covering window
    """
    shapes_at  = [ record_shapes( r ) for r in records ]
    reachable  = set().union( *shapes_at ) if shapes_at else set()
    required   = { name for name, _ in REQUIRED_SHAPES }
    missing    = required - reachable
    if missing:
        raise SystemExit(
            f"this source cannot produce the fixture: it carries no {sorted( missing )}.\n"
            f"It has {sorted( reachable )}. Pick another transcript — a source with no "
            f"non-empty thinking block is the common case (2,901 of 3,046 blocks swept on "
            f"2026-09-27 were empty), not a bug in this script."
        )

    best  = None
    start = 0
    have  = { }
    for end, shapes in enumerate( shapes_at ):
        for name in shapes: have[ name ] = have.get( name, 0 ) + 1
        while required <= set( have ):
            if best is None or ( end - start ) < ( best[ 1 ] - best[ 0 ] ):
                best = ( start, end )
            for name in shapes_at[ start ]:
                have[ name ] -= 1
                if have[ name ] == 0: del have[ name ]
            start += 1
    return best


def census( records ):
    """
    Describe the window by the properties the mapper and the renderers depend on.

    Requires:
        - records is a list of parsed JSONL records

    Ensures:
        - returns a dict carrying record_count, record_types, block_kinds and the
          thinking split that is this fixture's whole reason for existing
    """
    record_types = { }
    block_kinds  = { }
    thinking_empty = 0
    thinking_nonempty = 0
    thinking_lengths  = [ ]

    for record in records:
        if not isinstance( record, dict ): continue
        rtype = record.get( "type", "<none>" )
        record_types[ rtype ] = record_types.get( rtype, 0 ) + 1

        message = record.get( "message" )
        if not isinstance( message, dict ): continue
        content = message.get( "content" )
        if not isinstance( content, list ): continue
        for block in content:
            if not isinstance( block, dict ): continue
            btype = block.get( "type", "<none>" )
            block_kinds[ btype ] = block_kinds.get( btype, 0 ) + 1
            if btype == "thinking":
                text = block.get( "thinking", "" )
                thinking_lengths.append( len( text ) )
                if text == "": thinking_empty += 1
                else:          thinking_nonempty += 1

    return {
        "record_count"      : len( records ),
        "record_types"      : dict( sorted( record_types.items() ) ),
        "block_kinds"       : dict( sorted( block_kinds.items() ) ),
        "thinking_empty"    : thinking_empty,
        "thinking_nonempty" : thinking_nonempty,
        "thinking_len_min"  : min( thinking_lengths ) if thinking_lengths else None,
        "thinking_len_max"  : max( thinking_lengths ) if thinking_lengths else None,
    }


def main( argv=None ):
    """
    Capture the thinking fixture and its manifest.

    Requires:
        - --source names a readable transcript JSONL carrying a covering window
        - --out-dir names a writable directory

    Ensures:
        - writes thinking.jsonl and thinking-manifest.json into --out-dir
        - the manifest records the source basename, the window, both censuses and the
          fixture's sha256 — the provenance a reader needs to re-derive it
        - returns 0 on success
    """
    parser = argparse.ArgumentParser( description="Capture a window carrying a non-empty thinking block." )
    parser.add_argument( "--source",  required=True, help="the real transcript to cut the window from" )
    parser.add_argument( "--out-dir", required=True, help="where thinking.jsonl and its manifest are written" )
    args = parser.parse_args( argv )

    source          = os.path.expanduser( args.source )
    pairs, skipped  = read_records( source )
    records         = [ record for record, _raw in pairs ]
    if not records:
        raise SystemExit( f"{source} parsed to zero records" )

    start, end = smallest_covering_window( records )
    window     = records[ start : end + 1 ]
    redacted   = [ redact_node( r ) for r in window ]

    out_dir             = os.path.expanduser( args.out_dir )
    fixture_path        = os.path.join( out_dir, "thinking.jsonl" )
    size_bytes, digest  = write_fixture( fixture_path, redacted )

    manifest = {
        "generated_by"   : "src/tests/fixtures/cc_transcript/capture_thinking_fixture.py",
        "plan"           : "src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md",
        "row"            : "27760534",
        "ruled_by"       : "Mr. Radio, 2026-09-27: capture, don't invent",
        "why"            : (
            "primary.jsonl's five thinking blocks are all zero-length, so no assertion over "
            "rendered text can tell a client that renders an empty thinking block from one "
            "that drops it. This window carries BOTH arms plus the three other block kinds, "
            "so the fold, the drop and the two render paths are all discriminable."
        ),
        "source_basename": os.path.basename( source ),
        "kind"           : "verbatim contiguous record window, redacted",
        "selection_rule" : (
            "smallest contiguous window covering a NON-EMPTY thinking block, an EMPTY "
            "thinking block, a text block, a tool_use block and a tool_result block"
        ),
        "window"         : { "start_record_index": start, "end_record_index": end },
        "bytes"          : size_bytes,
        "sha256"         : digest,
        "source_unparseable_lines" : skipped,
        "census"         : census( redacted ),
        "source_census"  : census( records ),
        "redaction"      : {
            "rule": (
                "imported verbatim from capture_transcript_fixture.redact_node — every "
                "string leaf not reached through a structural key is substituted "
                "a-z->x, A-Z->X, 0-9->7; length, whitespace, newlines, punctuation and "
                "non-ASCII preserved"
            ),
        },
    }

    manifest_path = os.path.join( out_dir, "thinking-manifest.json" )
    with open( manifest_path, "w", encoding="utf-8" ) as handle:
        json.dump( manifest, handle, indent=2, sort_keys=True )
        handle.write( "\n" )

    print( f"wrote {fixture_path} ({manifest['bytes']:,} bytes, sha256 {digest[:12]})" )
    print( f"wrote {manifest_path}" )
    print( f"window: records {start}..{end} of {len( records )}" )
    print( f"census: {json.dumps( manifest['census'], indent=2 )}" )
    return 0


if __name__ == "__main__":
    raise SystemExit( main() )
