"""
Router training-label audit + line-by-line move tool.

Classifies every utterance in the math-agent training file into the three
buckets named in the 2026-08-21 spec, assigns a destination label under a
NAMED rule, checks for duplicates against the calculator file, and emits an
audit CSV so a reviewer can refute the call line by line.

Two rules are implemented. Neither is chosen by this script -- the caller
names one, and the CSV records which one produced the destinations.

    capability  Label CALCULATOR iff the utterance maps to one of the three
                operations CalculatorAgent actually implements (convert /
                compare_prices / mortgage, per CalcIntent.VALID_OPERATIONS).
                Everything else -- bare arithmetic included -- stays MATH.

    arithmetic  Bucket 1 (bare arithmetic) and the +-*/-only half of bucket 3
                (word problems needing only the four operations on the stated
                numbers) go to CALCULATOR. Bucket 2 and any bucket-3 item
                needing a formula, a rate, a unit conversion, or an unknown
                stays MATH.

The bucket assignment is a KEYWORD HEURISTIC and is not a measurement. It is
emitted so a human can overrule it per line; it is never a substitute for one.

Usage:
    python src/scripts/router_label_audit.py --rule capability
    python src/scripts/router_label_audit.py --rule arithmetic --audit-csv out.csv
    python src/scripts/router_label_audit.py --rule arithmetic --apply
    python src/scripts/router_label_audit.py --rule capability --records io/.../records.jsonl
"""

import os
import re
import sys
import csv
import json
import argparse
from collections import Counter

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set -- export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from cosa.agents.calculator.conversion_tables import ALIASES, ALL_CATEGORIES

MATH_FILE = "src/ephemera/prompts/data/synthetic-data-agent-routing-math.txt"
CALC_FILE = "src/ephemera/prompts/data/synthetic-data-agent-routing-calculator.txt"

MATH_LABEL = "agent router go to math"
CALC_LABEL = "agent router go to calculator"

# Unit vocabulary taken from the agent's OWN conversion tables -- not invented here.
_KNOWN_UNITS = set( ALIASES.keys() )
for table, _name in ALL_CATEGORIES: _KNOWN_UNITS |= set( table.keys() )

# Aliases that are also ordinary English words -- matching them as units manufactures
# conversions that are not there ("in the form a x squared" is not inches).
_AMBIGUOUS_ALIASES = { "in", "c", "f", "m", "t", "s", "cup", "cups", "ton", "tons", "mi" }
_KNOWN_UNITS -= _AMBIGUOUS_ALIASES

_MORTGAGE_RE   = re.compile( r"\b(mortgage|refinanc\w*|down payment|amortiz\w*|apy|apr|compound interest|auto loan|car loan|personal loan|monthly payment|principal)\b", re.I )
_PRICE_RE      = re.compile( r"\b(cheaper|better deal|best deal|price per|unit price|per ounce|per pound|which costs|compare (the )?price)", re.I )
_CONVERT_RE    = re.compile( r"\b(convert|how many|what'?s|what is)\b", re.I )

# Bucket 2 markers: symbolic algebra, geometry, calculus, and the named branches
# of mathematics the math file carries its own headers for.
_SYMBOLIC_RE   = re.compile(
    r"(\bx\s*\^|\bx\s*squared|\bsolve for\b|\bequation\b|\binequalit\w*|\bfactor\b|\bsimplify\b|"
    r"\bderivative\b|\bintegral\b|\blimit\b|\bcalculus\b|\bpolynomial\b|\bquadratic\b|\bslope\b|"
    r"\bsine\b|\bcosine\b|\btangent\b|\btrig\w*|\bradian\b|\blogarithm\b|\blog base\b|\bexponent\w*\b|"
    r"\barea\b|\bperimeter\b|\bvolume\b|\bcircumference\b|\bhypotenuse\b|\bpythagorean\b|\btriangle\b|"
    r"\bcircle\b|\brectangle\b|\bsquare root\b|\bangle\b|\bpolygon\b|\bpentagon\b|\boctagon\b|"
    r"\bprobabilit\w*|\bpermutation\b|\bcombination\b|\bstandard deviation\b|\bmedian\b|\bmean\b|"
    r"\bregression\b|\bprime\b|\bdivisor\b|\bmodul\w*|\bgcd\b|\blcm\b|\birrational\b|\bset theory\b|"
    r"\bsyllogism\b|\bmatrix\b|\bvector\b|\bfraction\b|\bpercent\w*|\bratio\b|\bmean value theorem\b|"
    r"\bodds\b|\bexpected value\b|\bdivisib\w*|\blottery\b|"
    # Spoken-variant algebra: "what's the value of x in 4x minus 7 equals 9?" carries no
    # "equation", no caret and no "squared", so the markers above all miss it.
    r"\b\d+\s*[xy]\b|\bvalue of [a-z]\b|\bsolution to\b|\bwhen [xy] (is|=|equals)\b|"
    r"\b[xy] (plus|minus|times|equals)\b|\bwhat (is|'s|’s|are) [xy]\b|"
    r"\bvariable\b|\bfunction\b|\bformula\b|\bproof\b|\bprove\b|\btheorem\b|\bsequence\b|\bseries\b)", re.I )

# Bucket 1 markers: the four operations stated over bare numerals, no scenario.
_ARITH_OP_RE   = re.compile(
    r"\b(plus|minus|times|divided by|divide|multiply|multiplied|subtract|add|sum|product|quotient|"
    r"remainder|total of|difference between|goes? into)\b", re.I )
_NUMERAL_RE    = re.compile( r"\d" )

# Bucket 3 markers: a scenario wrapping the numbers.
_SCENARIO_RE   = re.compile(
    r"\b(if (i|you|a|an|the)\b|a (car|tank|train|store|shop|farmer|worker|company|jacket|book)\b|"
    r"\bbuy\b|\bcost\b|\bprice\b|\bdiscount\b|\bhow far\b|\bhow long\b|\bhow much (will|would|do|does)\b)", re.I )

# Bucket-3 disqualifiers under the `arithmetic` rule: needs more than +-*/ on the stated numbers.
_NEEDS_MORE_RE = re.compile(
    r"\b(per hour|per minute|per second|miles per|km per|kilometers per|speed|rate|mph|"
    r"liters|litres|gallons|kilometers|kilometres|miles|meters|metres|feet|inches|"
    r"interest|percent|%|discount|area|perimeter|volume|circumference|"
    r"how long will it take|fill(ed)? by|empt\w+|km/h|kph|mph|m/s|"
    r"every (hour|minute|day|second|week|month|year))\b", re.I )


def _norm( line ):
    """
    Normalize an utterance for duplicate comparison.

    Requires:
        - line is a string

    Ensures:
        - returns a lowercase, whitespace-collapsed string with curly quotes folded
    """
    s = line.strip().lower()
    s = s.replace( "’", "'" ).replace( "‘", "'" ).replace( "“", '"' ).replace( "”", '"' )
    s = re.sub( r"\s+", " ", s )
    return s


def _units_in( text ):
    """
    Return the set of calculator-known unit tokens appearing in text.

    Requires:
        - text is a string

    Ensures:
        - returns a set of tokens drawn from the calculator's own unit tables
    """
    words = set( re.findall( r"[a-z_]+", text.lower() ) )
    return words & _KNOWN_UNITS


def _categories_of( units ):
    """
    Map unit tokens to the calculator's conversion categories.

    Requires:
        - units is an iterable of unit token strings

    Ensures:
        - returns the set of category names those tokens resolve to
    """
    cats = set()
    for u in units:
        canonical = ALIASES.get( u, u )
        for table, name in ALL_CATEGORIES:
            if canonical in table: cats.add( name )
    return cats


def classify_bucket( line ):
    """
    Assign the three-bucket label named in the spec.

    Requires:
        - line is a non-empty utterance string

    Ensures:
        - returns one of "1-bare-arithmetic", "2-symbolic", "3-word-problem", "0-routing-phrase"

    Raises:
        - ValueError if line is blank
    """
    if not line.strip(): raise ValueError( "classify_bucket() requires a non-empty line" )

    text = line.strip()
    has_numeral = bool( _NUMERAL_RE.search( text ) )
    spelled_num = re.search( r"\b(one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty)\b", text, re.I )

    # Routing phrases carry no problem at all ("Open up the math agent for me").
    if not has_numeral and not spelled_num and not _SYMBOLIC_RE.search( text ):
        return "0-routing-phrase"

    if _SYMBOLIC_RE.search( text ):  return "2-symbolic"
    if _SCENARIO_RE.search( text ):  return "3-word-problem"
    if _ARITH_OP_RE.search( text ) and has_numeral: return "1-bare-arithmetic"
    return "2-symbolic"


def destination_capability( line ):
    """
    Destination under the `capability` rule.

    Requires:
        - line is a non-empty utterance string

    Ensures:
        - returns (label, reason) where label is the calculator or math routing command
    """
    text = line.strip()

    if _MORTGAGE_RE.search( text ): return CALC_LABEL, "maps to calc op: mortgage"
    if _PRICE_RE.search( text ):    return CALC_LABEL, "maps to calc op: compare_prices"

    units = _units_in( text )
    cats  = _categories_of( units )
    # convert() only works within one category -- km-to-liters is not a conversion,
    # it is a rate problem, and belongs to the math agent.
    if len( units ) >= 2 and len( cats ) == 1 and _CONVERT_RE.search( text ):
        return CALC_LABEL, f"maps to calc op: convert ({sorted( units )})"

    return MATH_LABEL, "no CalcIntent operation covers it"


def destination_arithmetic( line ):
    """
    Destination under the `arithmetic` rule.

    Requires:
        - line is a non-empty utterance string

    Ensures:
        - returns (label, reason) where label is the calculator or math routing command
    """
    bucket = classify_bucket( line )
    text   = line.strip()

    if bucket == "1-bare-arithmetic": return CALC_LABEL, "bucket 1: bare arithmetic"
    if bucket == "3-word-problem":
        if _NEEDS_MORE_RE.search( text ):
            return MATH_LABEL, "bucket 3: needs a formula, rate, unit, or unknown"
        return CALC_LABEL, "bucket 3: only +-*/ on the stated numbers"
    return MATH_LABEL, f"bucket {bucket}"


RULES = { "capability": destination_capability, "arithmetic": destination_arithmetic }


def read_utterances( path ):
    """
    Read a corpus file, returning (line_number, raw_line) for content lines only.

    Requires:
        - path names a readable UTF-8 text file

    Ensures:
        - returns a list of (1-based line number, raw line) skipping blanks and # comments
    """
    out = []
    with open( path, encoding="utf-8" ) as fh:
        for n, raw in enumerate( fh.read().split( "\n" ), start=1 ):
            if raw.strip() and not raw.strip().startswith( "#" ): out.append( (n, raw) )
    return out


def duplicate_check( movers, calc_lines ):
    """
    Report utterances that already exist in the calculator corpus.

    Requires:
        - movers is a list of raw utterance strings proposed for the calculator file
        - calc_lines is a list of (line number, raw line) already in the calculator file

    Ensures:
        - returns (list of collisions against the calculator file, list of collisions within movers)
    """
    existing = { _norm( raw ) for _n, raw in calc_lines }
    seen     = set()
    cross    = []
    internal = []
    for raw in movers:
        key = _norm( raw )
        if key in existing: cross.append( raw )
        if key in seen:     internal.append( raw )
        seen.add( key )
    return cross, internal


def recount_cold( records_path, decide ):
    """
    Recompute cold-pass routing accuracy on the math-expected set under new labels.

    Requires:
        - records_path names a records.jsonl from a v2 paired eval
        - decide is a callable taking an utterance and returning (label, reason)

    Ensures:
        - returns a dict of counts before and after relabelling, with no interpretive rule
          applied to the router's own output
    """
    rows = [ json.loads( l ) for l in open( records_path, encoding="utf-8" ) if l.strip() ]
    cold = [ r for r in rows if r[ "pass_kind" ] == "cold" and r[ "expected_command" ] == MATH_LABEL ]

    before = sum( 1 for r in cold if r[ "payload" ].get( "command" ) == MATH_LABEL )
    after  = 0
    moved  = 0
    for r in cold:
        new_expected, _reason = decide( r[ "utterance" ] )
        if new_expected != MATH_LABEL: moved += 1
        if r[ "payload" ].get( "command" ) == new_expected: after += 1

    return {
        "n"                 : len( cold ),
        "correct_before"    : before,
        "correct_after"     : after,
        "relabelled"        : moved,
        "routed_by_router"  : dict( Counter( r[ "payload" ].get( "command" ) for r in cold ) ),
    }


def main():
    parser = argparse.ArgumentParser( description="Audit and optionally apply router training-label moves." )
    parser.add_argument( "--rule", choices=sorted( RULES.keys() ), required=True )
    parser.add_argument( "--audit-csv", default=None, help="write the per-line audit here" )
    parser.add_argument( "--records", default=None, help="records.jsonl for the cold-pass recount" )
    parser.add_argument( "--apply", action="store_true", help="rewrite the corpus files (default: dry run)" )
    args = parser.parse_args()

    decide     = RULES[ args.rule ]
    math_path  = os.path.join( lupin_root, MATH_FILE )
    calc_path  = os.path.join( lupin_root, CALC_FILE )
    math_lines = read_utterances( math_path )
    calc_lines = read_utterances( calc_path )

    rows   = []
    movers = []
    for n, raw in math_lines:
        bucket        = classify_bucket( raw )
        label, reason = decide( raw )
        rows.append( { "line": n, "source_file": MATH_FILE, "bucket": bucket,
                       "destination": label, "reason": reason, "utterance": raw.strip() } )
        if label != MATH_LABEL: movers.append( raw )

    cross, internal = duplicate_check( movers, calc_lines )

    print( f"rule              : {args.rule}" )
    print( f"math content lines: {len( math_lines )}" )
    print( f"calc content lines: {len( calc_lines )}" )
    print( f"buckets           : {dict( Counter( r[ 'bucket' ] for r in rows ) )}" )
    print( f"destinations      : {dict( Counter( r[ 'destination' ] for r in rows ) )}" )
    print( f"proposed movers   : {len( movers )}" )
    print( f"duplicate check   : {len( cross )} already in calculator file, {len( internal )} repeated among movers" )
    for raw in cross[ :20 ]:    print( f"  DUP-CROSS    | {raw.strip()}" )
    for raw in internal[ :20 ]: print( f"  DUP-INTERNAL | {raw.strip()}" )

    if args.audit_csv:
        with open( args.audit_csv, "w", newline="", encoding="utf-8" ) as fh:
            writer = csv.DictWriter( fh, fieldnames=[ "line", "source_file", "bucket", "destination", "reason", "utterance" ] )
            writer.writeheader()
            writer.writerows( rows )
        print( f"audit csv         : {args.audit_csv}" )

    if args.records:
        stats = recount_cold( args.records, decide )
        print( f"cold recount      : {stats}" )

    if args.apply:
        if cross or internal:
            raise ValueError( f"refusing to apply: {len( cross )} cross-file and {len( internal )} internal duplicates" )
        if not movers:
            print( "apply             : nothing to move under this rule" )
            return
        moved_lines = { n for n, raw in math_lines if decide( raw )[ 0 ] != MATH_LABEL }
        with open( math_path, encoding="utf-8" ) as fh:
            all_lines = fh.read().split( "\n" )
        keep = [ raw for n, raw in enumerate( all_lines, start=1 ) if n not in moved_lines ]
        while keep and not keep[ -1 ].strip(): keep.pop()
        with open( math_path, "w", encoding="utf-8" ) as fh:
            fh.write( "\n".join( keep ) + "\n" )
        with open( calc_path, "a", encoding="utf-8" ) as fh:
            fh.write( "\n# ── MOVED FROM MATH (2026-08-21 router-label fix) ──\n\n" )
            fh.write( "\n".join( raw.strip() for raw in movers ) + "\n" )
        print( f"apply             : moved {len( movers )} lines math -> calculator" )


if __name__ == "__main__":
    main()
