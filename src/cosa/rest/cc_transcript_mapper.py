#!/usr/bin/env python3
"""
Map Claude Code transcript JSONL records to console display blocks.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §2 item 1, ACs A2.4/A2.8.

A transcript is mostly not messages
-----------------------------------
Census of 8,115 records across four recent lupin transcripts (plan, P2): `user` +
`assistant` are **34%** of records, spread over THIRTEEN record types — `attachment`,
`system`, `mode`, `atis-latch`, `last-prompt`, `ai-title`, `file-history-snapshot`,
`queue-operation`, `permission-mode`, `file-history-delta`, `cost-state` and more. So the
mapper's normal case is a record it does not display.

Three rules, each one a defect someone would otherwise ship
-----------------------------------------------------------
**(a) Unknown record types are SKIPPED BY DEFAULT, not by enumeration.** The type set is
demonstrably not closed: `atis-latch` and `cost-state` appear in recent files and not in
older ones. So the predicate is "map the types you know, skip everything else" — never a
list of things to ignore, which is a list that goes stale silently
(CLAUDE.md § "Writing a rule or a guard": write the predicate, not the enumeration).

**(b) A block's `kind` comes from the CONTENT BLOCK's type, never from the record's role.**
760 of the 1,026 `user` records in the census carry tool_results. Mapping on role would
render three quarters of them as fake human turns — the reader would see the machine's own
tool output attributed to the person.

**(c) `message.content` has two shapes.** A bare string in 260 cases, a list in the rest.
Both are real and both must map.

`thinking` is emitted, and folded by the client
-----------------------------------------------
Ruling OSQ-7: shown folded and expandable, like tool results. It is not a rare case —
`thinking` outnumbered assistant `text` 424 to 520 in the census. The mapper emits it as
`kind: thinking`; the fold is the client's business, not this module's.
"""

import cosa.utils.util as cu


# The record types that can carry displayable content. Anything else is skipped — see
# rule (a): this is a list of what we KNOW, never a list of what to ignore.
DISPLAYABLE_RECORD_TYPES = frozenset( [ "assistant", "user" ] )

# Content-block types we render, mapped to the wire `kind`. A content block whose type is
# absent from here is skipped: it is structure, not output.
BLOCK_KIND_BY_CONTENT_TYPE = {
    "text"        : "text",
    "thinking"    : "thinking",
    "tool_use"    : "tool_call",
    "tool_result" : "tool_result",
}


def map_records( records, budget=0 ):
    """
    Map transcript records to display blocks, in file order.

    Requires:
        - records is an iterable of parsed JSONL records (dicts); non-dicts are skipped
        - budget is a non-negative int byte budget per block; **0 means UNBOUNDED**, the
          sense `routers/tasks.py` already uses in this tree — not "allow nothing"

    Ensures:
        - returns a list of blocks, each { ts, role, kind, text, truncated }
        - a record whose `type` is not displayable is skipped silently (rule a)
        - a block's `kind` comes from the content block's type, never the record's role
          (rule b)
        - both a bare-string and a list `message.content` are handled (rule c)
        - a block over `budget` is truncated with truncated=True; the full text stays
          available over REST
        - never raises on malformed input
    """
    blocks = [ ]
    for record in records:
        blocks.extend( map_record( record, budget=budget ) )
    return blocks


def map_record( record, budget=0 ):
    """
    Map ONE transcript record to zero or more display blocks.

    Requires:
        - record is a parsed JSONL record; anything else yields []
        - budget is a non-negative int; 0 means unbounded

    Ensures:
        - returns [] for a non-dict, for an unrecognised `type`, and for a record whose
          message carries no content block of a recognised type — all silently, because a
          transcript is mostly not messages
        - a recognised block with EMPTY text is still emitted; see the note in
          `_map_content_block` for why dropping it hid the whole thinking path
        - returns one block per renderable content block, in order
        - never raises
    """
    if not isinstance( record, dict ): return [ ]
    if record.get( "type" ) not in DISPLAYABLE_RECORD_TYPES: return [ ]

    message = record.get( "message" )
    if not isinstance( message, dict ): return [ ]

    ts   = record.get( "timestamp" ) or ""
    role = message.get( "role" ) or record.get( "type" ) or ""

    content = message.get( "content" )

    # Rule (c), shape one: a bare string. Only a human turn arrives this way, so `text` is
    # the right kind — but it is still the CONTENT's shape deciding it, not the role.
    if isinstance( content, str ):
        return [ _block( ts, role, "text", content.strip(), budget ) ]

    if not isinstance( content, list ): return [ ]

    # Rule (c), shape two: a list of content blocks.
    blocks = [ ]
    for raw_block in content:
        mapped = _map_content_block( ts, role, raw_block, budget )
        if mapped is not None:
            blocks.append( mapped )
    return blocks


def _map_content_block( ts, role, raw_block, budget ):
    """
    Map one content block, or return None when it is not renderable.

    Requires:
        - ts and role are strings
        - raw_block is whatever sat in `message.content[]`
        - budget is a non-negative int; 0 means unbounded

    Ensures:
        - returns a block dict, or None only when the content type is unrecognised
        - the `kind` is looked up from the content block's own `type` (rule b)
        - an unrecognised content type returns None — the open-ended arm of rule (a)
        - never raises
    """
    if not isinstance( raw_block, dict ): return None

    kind = BLOCK_KIND_BY_CONTENT_TYPE.get( raw_block.get( "type" ) )
    if kind is None: return None

    # An EMPTY recognised block is still emitted. Dropping it would be the mapper silently
    # editing the record, and it has a second cost that is easy to miss: the committed
    # fixture is REDACTED, and redaction empties `thinking` text to "". A skip-if-empty rule
    # therefore made the whole thinking path UNREACHABLE by the only real-transcript fixture
    # we have — the branch existed, no test could enter it, and the census said 5 thinking
    # blocks while the mapper emitted 0. Measured 2026-09-27. Emptiness is content; absence
    # is what `kind is None` above already handles.
    return _block( ts, role, kind, _text_for( kind, raw_block ), budget )


def _text_for( kind, raw_block ):
    """
    Extract the display text for one content block.

    Each kind keeps its payload somewhere different, so this is four small cases rather
    than one clever one.

    Requires:
        - kind is one of the values in BLOCK_KIND_BY_CONTENT_TYPE
        - raw_block is a dict

    Ensures:
        - returns a stripped string, possibly empty (the caller emits it anyway)
        - a tool_call renders as `Name( … )` — the one-line chip of ruling Q2
        - never raises
    """
    if kind == "text":     return str( raw_block.get( "text" ) or "" ).strip()
    if kind == "thinking": return str( raw_block.get( "thinking" ) or "" ).strip()

    if kind == "tool_call":
        name = str( raw_block.get( "name" ) or "tool" )
        return f"{name}( {_render_tool_input( raw_block.get( 'input' ) )} )".strip()

    # tool_result: `content` is a string in some records and a list of blocks in others.
    return _flatten_result_content( raw_block.get( "content" ) )


def _render_tool_input( tool_input ):
    """
    Render a tool call's input as one short line.

    Requires:
        - tool_input is whatever sat in the tool_use block's `input`

    Ensures:
        - returns a single-line string with newlines collapsed, so a chip stays a chip
        - returns "" when there is nothing to show
        - never raises
    """
    if tool_input is None: return ""
    if isinstance( tool_input, dict ):
        rendered = ", ".join( f"{key}={_one_line( value )}" for key, value in tool_input.items() )
    else:
        rendered = _one_line( tool_input )
    return rendered


def _flatten_result_content( content ):
    """
    Flatten a tool_result's `content`, which is a string in some records and a list in others.

    Requires:
        - content is whatever sat in the tool_result block's `content`

    Ensures:
        - returns a stripped string; list items contribute their `text` when they have one
        - returns "" when nothing renderable is present
        - never raises
    """
    if isinstance( content, str ): return content.strip()
    if not isinstance( content, list ): return "" if content is None else str( content ).strip()

    parts = [ ]
    for item in content:
        if isinstance( item, dict ):
            piece = item.get( "text" )
            if piece: parts.append( str( piece ) )
        elif item is not None:
            parts.append( str( item ) )
    return "\n".join( parts ).strip()


def _one_line( value ):
    """
    Collapse a value to a single line.

    Requires:
        - value is any object

    Ensures:
        - returns its str() with CR and LF replaced by spaces
        - never raises
    """
    return str( value ).replace( "\r", " " ).replace( "\n", " " )


def _block( ts, role, kind, text, budget ):
    """
    Build one wire block, applying the byte budget.

    Requires:
        - ts, role, kind and text are strings
        - budget is a non-negative int; **0 means unbounded**, per routers/tasks.py

    Ensures:
        - returns { ts, role, kind, text, truncated }
        - truncated is True iff `text` exceeded `budget` and was cut
        - the budget is measured in BYTES of UTF-8, because that is what the offsets and
          the ring are measured in; cutting on characters would make a multi-byte block
          overrun a byte budget while reporting that it fit
        - never raises
    """
    truncated = False
    if budget > 0:
        encoded = text.encode( "utf-8" )
        if len( encoded ) > budget:
            text      = encoded[ : budget ].decode( "utf-8", errors="ignore" )
            truncated = True

    return {
        "ts"        : ts,
        "role"      : role,
        "kind"      : kind,
        "text"      : text,
        "truncated" : truncated,
    }


def quick_smoke_test():
    """
    Smoke-test the mapper against the committed real-transcript fixture.

    Requires:
        - LUPIN_ROOT resolves and the fixture is present

    Ensures:
        - prints a census of the blocks produced, or says why it could not
    """
    import json
    import os

    cu.print_banner( "cc_transcript_mapper smoke test", prepend_nl=True )

    fixture = os.path.join( cu.get_project_root(), "src", "tests", "fixtures",
                            "cc_transcript", "primary.jsonl" )
    if not os.path.exists( fixture ):
        print( f"✗ fixture not found: {fixture}" )
        return

    records = [ ]
    with open( fixture, "r" ) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append( json.loads( line ) )
                except ValueError:
                    continue

    blocks = map_records( records, budget=0 )
    census = { }
    for block in blocks:
        census[ block[ "kind" ] ] = census.get( block[ "kind" ], 0 ) + 1

    print( f"records read : {len( records )}" )
    print( f"blocks mapped: {len( blocks )}" )
    for kind in sorted( census ):
        print( f"  {kind:<12} {census[ kind ]}" )


if __name__ == "__main__":
    quick_smoke_test()
