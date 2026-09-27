#!/usr/bin/env python3
"""
Capture a console-tee test fixture FROM A REAL Claude Code transcript.

Why this script exists rather than a hand-written fixture
--------------------------------------------------------
The console-tee plan (`src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`,
sha256 a605dc8c0249) makes this a named requirement, not a preference. A2.8 reads
"over a real captured transcript, not a hand-written fixture", and P2's census is the
reason: a transcript is **mostly not messages**. `user` + `assistant` are ~34% of
records across thirteen record types, and 760 of 1,026 `user` records carry
tool_results rather than human turns. A hand-written fixture is better-formed than
reality exactly where the mapper depends on the mess — so the mapper would be measured
against a file that cannot express the cases it will meet.

CLAUDE.md § Tests says the same thing in general terms: "Capture at least one fixture
from the real producer through the real reader."

What is preserved and what is redacted
--------------------------------------
A transcript carries everything a seat read — file contents, tool output, possibly
secrets from `.env` or logs — and this fixture is committed to git. So the script
preserves **structure** and redacts **content**:

    PRESERVED  record `type`; message `role`; content-block `type`; tool `name`;
               the `message.content` SHAPE (bare string vs list); nesting and key
               sets; `timestamp`; the `id`/`tool_use_id` pairing that links a
               tool_use to its tool_result; `uuid`/`parentUuid` threading;
               `is_error`; string LENGTH; embedded newlines; non-ASCII codepoints;
               JSON escape sequences; line boundaries and record order.

    REDACTED   every other string leaf, character by character: [a-z] -> 'x',
               [A-Z] -> 'X', [0-9] -> '7'. Everything else passes through, which is
               what keeps the unicode, the newlines and the escapes real.

Length-preserving substitution is deliberate. A block's `truncated` flag (A2.4) and
the byte offsets that are the wire contract's only sequence number are both length
properties, so a redaction that shortened strings would quietly change what the
fixture can test.

⚠️ This is a REDACTION, not an anonymisation proof. It is sound for the classes of
secret that appear as string VALUES. It does not defend against a secret appearing in
a structural field this script preserves, and the operator should read the manifest's
census before committing a fixture captured from a new source.

Two fixtures, two jobs
----------------------
`primary`   — a VERBATIM CONTIGUOUS record window from one real transcript, chosen by
              the predicate "the smallest window that still carries every record type
              and every content-block kind the source file contains". Contiguous
              matters: record ORDER and line boundaries are untouched, which is what
              the offset-chaining scenario measures.

`breadth`   — real records of the record types the primary window's source does not
              contain, one each, appended from other real transcripts. This one is a
              composite and the manifest says so. Its only job is A2.8's
              "an unrecognised record type is skipped rather than erroring", over the
              widest set of real types available on this host.

Usage
-----
    python3 src/tests/fixtures/cc_transcript/capture_transcript_fixture.py \
        --source <real.jsonl> [--extra <other.jsonl> ...] --out-dir <dir>

The default source list is discovered under ~/.claude/projects/, so the script has to
be RUN ON A HOST THAT HAS REAL TRANSCRIPTS. It is not part of any test tier — it is
the provenance record for the committed fixture, and `manifest.json` is its receipt.
"""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter


# ── redaction ─────────────────────────────────────────────────────────────────

# Keys whose STRING values are structural — the mapper, the offset contract or the
# tool_use/tool_result pairing reads them, so redacting them would change what the
# fixture can express. Everything not named here is content and gets redacted.
STRUCTURAL_KEYS = frozenset( [
    "type", "role", "name", "subtype", "userType", "timestamp",
    "id", "tool_use_id", "uuid", "parentUuid", "stop_reason", "model",
] )


def redact_string( text ):
    """
    Replace a string's alphanumeric content while preserving everything else.

    Requires:
        - text is a str

    Ensures:
        - returns a str of exactly len( text )
        - every [a-z] becomes 'x', every [A-Z] becomes 'X', every [0-9] becomes '7'
        - every other codepoint — whitespace, newline, punctuation, non-ASCII — is
          passed through unchanged
    """
    out = []
    for ch in text:
        if   "a" <= ch <= "z": out.append( "x" )
        elif "A" <= ch <= "Z": out.append( "X" )
        elif "0" <= ch <= "9": out.append( "7" )
        else:                  out.append( ch )
    return "".join( out )


def redact_node( node, key=None ):
    """
    Redact a parsed JSON node in place-by-copy, preserving structure.

    Requires:
        - node is any JSON-decoded value
        - key is the dict key this node was reached through, or None at the root

    Ensures:
        - dict key sets, list lengths and nesting are unchanged
        - a string reached through a STRUCTURAL_KEYS key is returned verbatim
        - every other string is returned redacted by redact_string
        - numbers, booleans and None are returned unchanged
    """
    if isinstance( node, dict ):
        return { k: redact_node( v, k ) for k, v in node.items() }
    if isinstance( node, list ):
        return [ redact_node( v, key ) for v in node ]
    if isinstance( node, str ):
        if key in STRUCTURAL_KEYS: return node
        return redact_string( node )
    return node


# ── census ────────────────────────────────────────────────────────────────────

def census( records ):
    """
    Describe a record list by the properties the mapper depends on.

    Requires:
        - records is a list of dicts decoded from transcript JSONL lines

    Ensures:
        - returns a dict with record_types, content_shapes, block_kinds,
          user_records_carrying_tool_result and record_count
    """
    types  = Counter()
    kinds  = Counter()
    shapes = Counter()
    user_tool_result = 0

    for record in records:
        types[ record.get( "type", "<none>" ) ] += 1
        message = record.get( "message" )
        if not isinstance( message, dict ): continue

        content = message.get( "content" )
        if   isinstance( content, str  ): shapes[ "str"  ] += 1
        elif isinstance( content, list ): shapes[ "list" ] += 1
        else:                             shapes[ type( content ).__name__ ] += 1

        if not isinstance( content, list ): continue
        carries_tool_result = False
        for block in content:
            if not isinstance( block, dict ): continue
            kinds[ block.get( "type", "<none>" ) ] += 1
            if block.get( "type" ) == "tool_result": carries_tool_result = True
        if carries_tool_result and record.get( "type" ) == "user": user_tool_result += 1

    return {
        "record_count"                     : len( records ),
        "record_types"                     : dict( sorted( types.items() ) ),
        "content_shapes"                   : dict( sorted( shapes.items() ) ),
        "block_kinds"                       : dict( sorted( kinds.items() ) ),
        "user_records_carrying_tool_result": user_tool_result,
    }


# ── reading ───────────────────────────────────────────────────────────────────

def read_records( path ):
    """
    Read a transcript JSONL into (record, raw_line) pairs, skipping unparseable lines.

    Requires:
        - path names a readable file of newline-delimited JSON

    Ensures:
        - returns ( pairs, skipped_count ) where each pair is ( dict, raw_line_str )
        - a line that is blank, not JSON, or not a dict is counted in skipped_count
          and not returned
    """
    pairs   = []
    skipped = 0
    with open( path, encoding="utf-8" ) as handle:
        for raw in handle:
            stripped = raw.strip()
            if not stripped:
                skipped += 1
                continue
            try:
                record = json.loads( stripped )
            except ValueError:
                skipped += 1
                continue
            if not isinstance( record, dict ):
                skipped += 1
                continue
            pairs.append( ( record, stripped ) )
    return pairs, skipped


def message_features( record ):
    """
    Describe one record by the MESSAGE-SHAPED properties the block mapper reads.

    Record types are deliberately NOT part of this. The mapper's rule for a record
    type it does not recognise is "skip it" (§2 item 1a), and proving that needs one
    record of the type, not a contiguous run — so rare bookkeeping types are the
    breadth fixture's job. What the PRIMARY fixture has to carry is the message mess:
    both `message.content` shapes, every content-block kind, and a `user` record whose
    content is a tool_result rather than a human turn.

    Requires:
        - record is a dict decoded from one transcript JSONL line

    Ensures:
        - returns a set of ( facet, value ) pairs drawn from the record's message
        - returns an empty set for a record with no dict `message`
    """
    message = record.get( "message" )
    if not isinstance( message, dict ): return set()

    content = message.get( "content" )
    shape   = "str" if isinstance( content, str ) else "list" if isinstance( content, list ) else "other"
    found   = { ( "shape", shape ) }

    if isinstance( content, list ):
        carries_tool_result = False
        for block in content:
            if not isinstance( block, dict ): continue
            found.add( ( "kind", block.get( "type", "<none>" ) ) )
            if block.get( "type" ) == "tool_result": carries_tool_result = True
        if carries_tool_result and record.get( "type" ) == "user":
            found.add( ( "role_kind_mismatch", "user_carrying_tool_result" ) )
    return found


def smallest_covering_window( pairs ):
    """
    Find the smallest contiguous record window carrying every message-shaped feature.

    This is the PREDICATE the plan's "write the predicate, not the enumeration" rule
    asks for: the window is derived from what the source file actually contains, so a
    source carrying a new content-block kind widens the window automatically rather
    than needing this function edited.

    Requires:
        - pairs is a non-empty list of ( record, raw_line ) as read_records returns

    Ensures:
        - returns ( start, end ) as a half-open index range into pairs
        - the slice pairs[ start:end ] carries every ( facet, value ) pair that
          message_features finds anywhere in pairs
        - no strictly shorter contiguous window satisfies that
    """
    per_record = [ message_features( record ) for record, _ in pairs ]
    required   = set()
    for found in per_record: required |= found

    have  = Counter()
    best  = ( 0, len( pairs ) )
    start = 0
    for end in range( 1, len( pairs ) + 1 ):
        for feature in per_record[ end - 1 ]: have[ feature ] += 1
        while len( [ f for f in have if have[ f ] > 0 ] ) == len( required ):
            if ( end - start ) < ( best[ 1 ] - best[ 0 ] ): best = ( start, end )
            for feature in per_record[ start ]:
                have[ feature ] -= 1
                if have[ feature ] == 0: del have[ feature ]
            start += 1
    return best


# ── writing ───────────────────────────────────────────────────────────────────

def grow_window_to_min_bytes( pairs, start, end, min_bytes ):
    """
    Extend a contiguous window until its raw byte span reaches min_bytes.

    Why a minimum at all: ruling Q6 caps the backlog at ~64 KB and A2.9 pages
    BACKWARDS from an offset. A fixture smaller than the cap cannot distinguish
    "the last 64 KB" from "the whole file", so the `tail_bytes` arm would pass
    against a forward-only implementation — which is the exact discrimination A2.9
    says it must prove. The minimum is derived from the ruled cap, not chosen.

    Requires:
        - pairs is a list of ( record, raw_line ) as read_records returns
        - 0 <= start <= end <= len( pairs )
        - min_bytes is a non-negative int

    Ensures:
        - returns ( new_start, new_end ) with new_start <= start and new_end >= end
        - the raw byte span of pairs[ new_start:new_end ] is >= min_bytes, unless the
          whole file is smaller, in which case the whole file is returned
        - growth is balanced: it extends forward and backward alternately, so the
          covering window stays inside the result rather than sitting at one edge
    """
    def span_bytes( lo, hi ):
        return sum( len( raw.encode( "utf-8" ) ) + 1 for _, raw in pairs[ lo:hi ] )

    new_start, new_end = start, end
    forward = True
    while span_bytes( new_start, new_end ) < min_bytes:
        if new_start == 0 and new_end == len( pairs ): break
        if forward and new_end   < len( pairs ): new_end   += 1
        elif not forward and new_start > 0:      new_start -= 1
        elif new_end   < len( pairs ):           new_end   += 1
        elif new_start > 0:                      new_start -= 1
        forward = not forward
    return new_start, new_end


def write_fixture( out_path, redacted_records ):
    """
    Write redacted records as JSONL and return ( byte_size, sha256_hex ).

    Requires:
        - out_path is a writable path
        - redacted_records is a list of JSON-serialisable dicts

    Ensures:
        - the file is newline-terminated, one compact JSON record per line
        - returns the file's byte size and its sha256 hex digest
    """
    body = "".join(
        json.dumps( record, ensure_ascii=False, separators=( ",", ":" ) ) + "\n"
        for record in redacted_records
    )
    raw = body.encode( "utf-8" )
    with open( out_path, "wb" ) as handle: handle.write( raw )
    return len( raw ), hashlib.sha256( raw ).hexdigest()


def discover_transcripts( root ):
    """
    List every transcript JSONL under a Claude Code projects root, largest first.

    Requires:
        - root is a directory path (it need not exist)

    Ensures:
        - returns a list of absolute paths to *.jsonl files directly inside each
          project directory, ordered by descending byte size
        - returns [] when root does not exist
    """
    if not os.path.isdir( root ): return []
    found = []
    for project in sorted( os.listdir( root ) ):
        project_dir = os.path.join( root, project )
        if not os.path.isdir( project_dir ): continue
        for name in sorted( os.listdir( project_dir ) ):
            if name.endswith( ".jsonl" ): found.append( os.path.join( project_dir, name ) )
    found.sort( key=lambda p: os.path.getsize( p ), reverse=True )
    return found


def main( argv=None ):
    parser = argparse.ArgumentParser( description=__doc__ )
    parser.add_argument( "--source",  required=True, help="the real transcript the PRIMARY window is cut from" )
    parser.add_argument( "--extra",   action="append", default=[], help="another real transcript to draw breadth records from; repeatable" )
    parser.add_argument( "--auto-extra", action="store_true", help="discover extra sources under ~/.claude/projects instead of naming them" )
    parser.add_argument( "--out-dir", required=True, help="where the two fixtures and the manifest are written" )
    parser.add_argument( "--max-extra-sources", type=int, default=12, help="cap on discovered extra sources (default 12)" )
    parser.add_argument( "--min-bytes", type=int, default=3 * 65536,
                         help="grow the primary window to at least this many bytes (default 196608 = 3x ruling Q6's ~64 KB cap, so a tail page, a backward page and a remainder all fit)" )
    args = parser.parse_args( argv )

    os.makedirs( args.out_dir, exist_ok=True )

    source_pairs, source_skipped = read_records( args.source )
    if not source_pairs:
        print( f"REFUSED: no parseable records in {args.source}", file=sys.stderr )
        return 1

    start, end   = smallest_covering_window( source_pairs )
    start, end   = grow_window_to_min_bytes( source_pairs, start, end, args.min_bytes )
    window_pairs = source_pairs[ start:end ]
    source_cens  = census( [ record for record, _ in source_pairs  ] )
    window_cens  = census( [ record for record, _ in window_pairs  ] )

    primary_records = [ redact_node( record ) for record, _ in window_pairs ]
    primary_path    = os.path.join( args.out_dir, "primary.jsonl" )
    primary_bytes, primary_sha = write_fixture( primary_path, primary_records )

    # ── breadth: real records of types the primary window lacks ───────────────
    extras = list( args.extra )
    if args.auto_extra:
        home = os.path.expanduser( "~/.claude/projects" )
        for path in discover_transcripts( home ):
            if os.path.realpath( path ) == os.path.realpath( args.source ): continue
            extras.append( path )
            if len( extras ) >= args.max_extra_sources: break

    have_types     = set( window_cens[ "record_types" ] )
    breadth        = []
    breadth_origin = {}
    for path in extras:
        pairs, _ = read_records( path )
        for record, _ in pairs:
            record_type = record.get( "type", "<none>" )
            if record_type in have_types: continue
            have_types.add( record_type )
            breadth.append( redact_node( record ) )
            breadth_origin[ record_type ] = os.path.basename( path )

    breadth_path = os.path.join( args.out_dir, "breadth.jsonl" )
    breadth_bytes, breadth_sha = write_fixture( breadth_path, breadth )

    manifest = {
        "generated_by"  : "src/tests/fixtures/cc_transcript/capture_transcript_fixture.py",
        "plan"          : "src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md",
        "plan_sha256_prefix": "a605dc8c0249",
        "redaction"     : {
            "rule"            : "every string leaf not reached through a structural key is substituted a-z->x, A-Z->X, 0-9->7; length, whitespace, newlines, punctuation and non-ASCII preserved",
            "structural_keys" : sorted( STRUCTURAL_KEYS ),
        },
        "primary": {
            "kind"            : "verbatim contiguous record window, redacted",
            "source_basename" : os.path.basename( args.source ),
            "source_census"   : source_cens,
            "source_unparseable_lines": source_skipped,
            "window"          : { "start_record_index": start, "end_record_index": end },
            "census"          : window_cens,
            "bytes"           : primary_bytes,
            "sha256"          : primary_sha,
            "selection_rule"  : "smallest contiguous window covering every message-shaped feature present in the source: both content shapes, every block kind, and a user record carrying a tool_result",
        },
        "breadth": {
            "kind"            : "composite — one real record per record type absent from the primary window",
            "origins"         : breadth_origin,
            "census"          : census( breadth ),
            "bytes"           : breadth_bytes,
            "sha256"          : breadth_sha,
        },
    }
    manifest_path = os.path.join( args.out_dir, "manifest.json" )
    with open( manifest_path, "w", encoding="utf-8" ) as handle:
        json.dump( manifest, handle, indent=2, sort_keys=True, ensure_ascii=False )
        handle.write( "\n" )

    print( f"primary  : {primary_bytes:>9,} bytes  {window_cens[ 'record_count' ]} records  sha {primary_sha[ :12 ]}" )
    print( f"breadth  : {breadth_bytes:>9,} bytes  {len( breadth )} records  sha {breadth_sha[ :12 ]}" )
    print( f"manifest : {manifest_path}" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
