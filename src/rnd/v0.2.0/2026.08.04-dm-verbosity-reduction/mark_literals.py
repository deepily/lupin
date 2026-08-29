"""
Extraction-recall labeling harness for arm 4 Phase 1.

Applies the plan's §1 HARD+SOFT taxonomy to a stratified sample of real DM
bodies and marks every matched span, so a human reader can hunt for what the
current regexes MISS. This addresses the expert review's issue 2: the corpus
only ground-truths literals the current regexes already detect.

Requires:
    - corpus_path points at a readable jsonl with a "body" field per record

Ensures:
    - prints a stratified sample with every taxonomy match wrapped in <<...>>
    - unmarked high-entropy text is exactly what the reader must label
"""

import json
import re
import sys
from collections import defaultdict

# ── The plan's §1 taxonomy, as regexes. HARD tier first (higher precedence). ──
HARD_PATTERNS = [
    ( "backticked",  re.compile( r"`[^`\n]+`" ) ),
    ( "uuid",        re.compile( r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b" ) ),
    ( "file_line",   re.compile( r"\b[\w./-]+\.\w{1,5}:\d+\b" ) ),
    ( "iso_date",    re.compile( r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.+-]+)?\b" ) ),
    ( "path",        re.compile( r"(?<![\w/])(?:~|\.{1,2})?/[\w.-]+(?:/[\w.-]+)+/?" ) ),
    ( "sha_or_sid",  re.compile( r"\b[0-9a-f]{7,40}\b" ) ),
    ( "port",        re.compile( r":\d{2,5}\b" ) ),
]

SOFT_PATTERNS = [
    ( "dquoted",     re.compile( r"\"[^\"\n]{1,120}\"" ) ),
    ( "const_name",  re.compile( r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b" ) ),
    ( "num_unit",    re.compile( r"\b\d+(?:\.\d+)?\s?(?:s|ms|m|h|d|k|K|MB|GB|%|x|×|/day|/M)\b" ) ),
]

ALL_PATTERNS = HARD_PATTERNS + SOFT_PATTERNS


def find_spans( text ):
    """
    Collect non-overlapping matches, HARD tier winning ties.

    Requires:
        - text is a string

    Ensures:
        - returns a list of ( start, end, kind ) sorted by start
        - no two returned spans overlap
    """
    candidates = []
    for kind, pattern in ALL_PATTERNS:
        for match in pattern.finditer( text ):
            candidates.append( ( match.start(), match.end(), kind ) )

    # Longest-first, then earliest, so a sha inside backticks loses to the span.
    candidates.sort( key=lambda s: ( -( s[1] - s[0] ), s[0] ) )

    taken = []
    for start, end, kind in candidates:
        if any( start < t_end and end > t_start for t_start, t_end, _ in taken ):
            continue
        taken.append( ( start, end, kind ) )

    taken.sort( key=lambda s: s[0] )
    return taken


def mark( text ):
    """
    Wrap every taxonomy match in <<kind|literal>> for visual scanning.

    Requires:
        - text is a string

    Ensures:
        - returns text with matches wrapped, original ordering preserved
    """
    spans = find_spans( text )
    out   = []
    prev  = 0
    for start, end, kind in spans:
        out.append( text[prev:start] )
        out.append( f"<<{kind}|{text[start:end]}>>" )
        prev = end
    out.append( text[prev:] )
    return "".join( out )


def band( word_count ):
    """
    Bucket a body into the plan's §1 length bands.

    Requires:
        - word_count is a non-negative integer

    Ensures:
        - returns one of the four band labels used throughout the plan
    """
    if word_count <  80: return "<80"
    if word_count < 150: return "80-150"
    if word_count < 250: return "150-250"
    return "250+"


def main( corpus_path, per_band=6 ):
    by_band = defaultdict( list )

    with open( corpus_path ) as handle:
        for line in handle:
            line = line.strip()
            if not line: continue
            try:
                record = json.loads( line )
            except json.JSONDecodeError:
                continue
            body = record.get( "body" ) or ""
            if not body: continue
            by_band[ band( len( body.split() ) ) ].append( body )

    print( "# Extraction-recall sample — taxonomy matches wrapped in <<kind|literal>>\n" )
    print( "Corpus bodies by band:" )
    for name in [ "<80", "80-150", "150-250", "250+" ]:
        print( f"  {name:8s} {len( by_band[name] ):5d}" )
    print()

    for name in [ "<80", "80-150", "150-250", "250+" ]:
        bodies = by_band[ name ]
        if not bodies: continue
        # Deterministic stride sample — no RNG, reproducible across runs.
        stride = max( 1, len( bodies ) // per_band )
        picked = bodies[::stride][:per_band]
        print( f"\n{'='*100}\n## BAND {name}  ({len( bodies )} bodies, showing {len( picked )})\n{'='*100}" )
        for index, body in enumerate( picked ):
            print( f"\n--- {name} #{index} ---" )
            print( mark( body ) )


if __name__ == "__main__":
    corpus   = sys.argv[1]
    per_band = int( sys.argv[2] ) if len( sys.argv ) > 2 else 6
    main( corpus, per_band )
