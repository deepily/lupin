#!/usr/bin/env python3
"""
Find assertions whose expected values are INTERCHANGEABLE — a triage aid for one
recognisable sub-shape of fixture blindness.

WHAT THIS FINDS, AND IT IS NARROW ON PURPOSE
--------------------------------------------
CLAUDE.md's fourth reading of a surviving mutant: an assertion can be present, correct,
and named for exactly the thing that broke, while the FIXTURE cannot tell the difference.
The mechanically-findable case is **values that repeat**:

    assert result == { "migrated": 1, "skipped": 1 }   # swapping them changes nothing
    assert counts  == ( 1, 1 )                          # same
    assert params  == { "limit": 0, "offset": 0 }       # same

If two expected values are equal, then swapping the two things they describe cannot
change the outcome — so that assertion measures their SUM, not their identity, whatever
its name says. `{ "migrated": 2, "skipped": 1 }` discriminates; `1 / 1` does not.

🔴 WHAT THIS IS NOT, AND THE DISTINCTION IS THE WHOLE POINT
----------------------------------------------------------
**It finds BLIND ASSERTIONS. It does not find UNDEFENDED BEHAVIOUR.** Discrimination
very often lives in a SIBLING assertion this probe cannot see:

    assert first[ "alpha" ]  == ( 1, 1 )   # flagged — blind on its own
    assert second[ "alpha" ] == ( 1, 0 )   # not flagged — and it covers the swap

Measured 2026-08-30 on the first two hits adjudicated: BOTH were covered elsewhere. One
by the adjacent line above; one — `{ "limit": 0, "offset": 0 }` — by two sibling tests in
the same file, confirmed by actually swapping `limit` and `offset` in the source
(mutated sha `80a636b90dea`, rc=1).

⇒ **Every hit still needs a mutation to adjudicate.** This narrows WHERE to point one.
A repeat is legal, common, and usually fine. Treating this output as a defect list would
be an instrument certifying itself by counting hits nobody adjudicated — which is the
exact failure the probe exists to help find.

🔴 WHAT IT CANNOT SEE — THE RECALL SIDE, AND IT IS THE BIGGER HALF
-----------------------------------------------------------------
The caveat above is about PRECISION: hits that turn out fine. This one is about RECALL, and a
zero from this probe is the more dangerous output, because a zero reads like an all-clear.

**Measured 2026-08-30.** Run over `src/tests/unit/scripts` — 32 test files — it reports ZERO
hits in `test_watch_hook_events.py`, a file of 63 tests.

🔴 **THE FIRST VERSION OF THIS RECEIPT CLAIMED TWICE WHAT IT COULD SHOW** (Clayton, 2026-08-30,
checking the file instead of accepting the claim). It said the file "contains BOTH" of the blind
fixtures Maya found by mutation. **Only one of them is still in it.** Checked line by line at
72157c17:

    line 123   REPAIRED - now `assert root.is_absolute()` plus the parents[ 2 ] equality,
               which is Maya's kill. The blind `.exists()` form is GONE, so a probe that
               does not flag it has missed NOTHING.

    line 218   STILL BLIND, verbatim: `_hhmmss( "2026.06.06 @ 01:45 abc" ) == "01:45:00"`.
               "abc" has no digits, so the `.zfill( 2 )` under test is a no-op and the
               assertion cannot see it either way. The probe does not flag it.

⇒ **One real miss, not two** - and the survivor is the better example, because it is a blind
assertion sitting in the tree right now that this probe cannot see. Its BEHAVIOUR is defended,
by the sibling at line 228 using "7ms" - the precision caveat above running the other way:
blind assertion, covered behaviour.

**A LARGER AND PROPERLY-CONSTITUTED SAMPLE — Clayton, 2026-08-30, and it is HIS measurement, not
this author's.** He first probed a set of five blind fixtures and got zero hits, then withdrew
his own result for the same reason he had just corrected in mine: he had run against the
REPAIRED tree (his tip 72157c17 has Chloé's adoption e23ef98c as an ancestor), so all five were
already fixed and a zero proved nothing. He re-ran against the true pre-repair snapshot taken
from Chloé's worktree at 17:32:51, **verifying each sample actually CONTAINS the blindness
before counting a miss**. **Probe reports ZERO hits on all five**, in
`test_thread_attribution_plugin.py` and `test_probe_commons_post_direct.py`:

    1. line numbers (30, 10, 20) recorded in an order that is already what a sort would give
    2. a THIRD_PARTY path under /usr/lib with no /src/ in it, rejected by the first clause
    3. one file per thread, so sort_keys=True and sort_keys=False give identical output
    4. OUT and PREFIX defaults executed at import and never asserted
    5. a truncate-only _FakeStore

**None of them repeats a literal**, which is why this probe cannot see any of them. Note what
shapes 1 and 3 have in common with Maya's cases: the fixture chose data for which the operation
under test — sorting — is a NO-OP, so the assertion passes whether or not the sort happens.

So the citable statement is **0 of 5 found, on a named sample**: Chloé's pre-`e23ef98c` worktree
snapshot, 17:32:51 on 2026-08-30, measured by Clayton.

⚠️ **THAT SEQUENCE IS THE METHOD, not a footnote about one reviewer.** A recall check run against
a tree where the blindness has been repaired reports zero and means nothing, and it looks
identical to one that means something. **Verify the sample still contains what you claim the
probe missed, and say which tree you ran in.**

The two shapes, so the point survives the line numbers going stale:

    # blind: Path( "" ) is RELATIVE, and pytest runs from the repo root, so the wrong
    # answer and the right answer name the same file
    assert ( root / "src" / "scripts" / "watch-hook-events.py" ).exists()

    # blind: "abc" has no digits, so ss is already "00" — two characters — and the
    # .zfill( 2 ) under test is a no-op either way
    assert whe._hhmmss( "2026.06.06 @ 01:45 abc" ) == "01:45:00"

Neither has a repeated literal ANYWHERE. There is nothing for this probe to match, so it finds
nothing, and it would find nothing on a hundred more like them.

**Why, stated as the rule rather than the two cases.** Repeated expected values are the corner
of fixture blindness that leaves a SYNTACTIC trace. The family is much larger: a fixture is
blind whenever the data it chose cannot distinguish right from wrong — because the value makes
the operation a no-op, because the wrong answer coincides with the right one under that input,
because the environment supplies what the code was supposed to. **None of those repeat
anything.** They are properties of what the value MEANS to the code under test, and no scanner
reading the test file can know that.

⇒ **This probe answers "where do expected values repeat?" — a question with a mechanical
answer. It does not answer "which fixtures cannot discriminate?", and the two are not close
enough for a zero on the first to say anything about the second.**

⇒ **A file with no hits has not been cleared. It has not been examined.** Only a mutation
tells you whether a fixture can see what its name claims.

⚠️ **AND THIS IS A DEMONSTRATION THAT RECALL IS NOT TOTAL — IT IS NOT A MEASUREMENT OF RECALL.**
Neither number on this page is large. **Precision rests on TWO adjudicated hits** (both covered
elsewhere, named above); the recall evidence is **two known blind fixtures in one file**. Two
and two. A rate cannot be computed from either.

🔴 **A "20-HIT ADJUDICATION, PRECISION 5-25%" FIGURE WAS IN CIRCULATION FOR THIS PROBE AND IT IS
UNCITABLE — DO NOT REPEAT IT** (Rachel, 2026-08-30, refusing to approve until it was named or
cut: *"name the twenty - when, which hits, what each resolved to - or cut it and say two"*).
It could not be named. It reached this author in a session memento, was repeated in review DMs
and in a commit message as though measured, and **the only adjudication evidence in this repo is
the two hits above** - which this file's docstring and its own printed footer have said all
along. **The page contradicted itself, and the smaller, true number was the one already written
down.**

⇒ **A figure that arrives without its receipts is a rumour with a provenance, and inheriting it
from a prior session is not provenance.** Cut it and state what can be shown.

**Recall has no denominator, and that — not the quality of the evidence — is why it cannot be
rated.** A recall rate is (blind fixtures found) / (blind fixtures that exist). The numerator is
obtainable. **The denominator is not: nobody can enumerate the blind fixtures in this repo**,
because a fixture's blindness is a fact about what its data means to the code under test, and
the only way to establish it is to mutate that code and watch. You can always find more by
mutating more. There is no point at which the set is known to be complete, so there is nothing
to divide by.

🔴 **AN EARLIER CUT OF THIS PARAGRAPH GAVE THE WRONG REASON, AND THE WRONG REASON WAS THE
DANGEROUS PART** (Clayton 😎, 2026-08-30, refusing to approve until it was fixed). It said a
recall figure taken over mutation-found fixtures would be "the instrument certifying itself
against its own reach." **That is backwards.** Mutation is a DIFFERENT instrument from this
probe — it executes the code, this reads the source — so checking the probe against
mutation-found fixtures is exactly the independent second reading that certification rule asks
for. The old wording discouraged the one kind of evidence that would strengthen this page.

⇒ **Measuring the probe against known blind fixtures is legitimate and worth doing.** It yields
*"it missed N of the M we know about"* — a real statement about a named sample. It does not
yield a recall rate, and the difference is the denominator, not the method.

⇒ **Quote either as a count against a NAMED sample — "2 of 2 adjudicated hits were covered
elsewhere", "missed 2 of the 2 blind fixtures known in that file" — never as a bare rate.** A
ratio over a sample you name is honest and useful; what this page cannot support is an
unqualified precision or recall *rate*, which implies a population neither number has.

EXIT CODES
    0  scanned, no interchangeable-value assertions found — NOT an all-clear:
       it means nothing MATCHED, never that no fixture is blind (see recall, above)
    1  findings present (a TRIAGE queue, never a defect count)
    2  nothing could be scanned — no readable files matched

Usage:
    PYTHONPATH=src python src/scripts/find_interchangeable_assertions.py [ROOT]
                                                                        [--json]
                                                                        [--limit N]
"""

import argparse
import ast
import collections
import json
import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )


DEFAULT_ROOT = "src/tests"
TEST_GLOB    = "test_*.py"


def literal_of( node ):
    """
    The comparable literal a node carries, or None when it is not a plain literal.

    Requires:
        - node is any AST node

    Ensures:
        - returns repr( value ) for an int / str / float / bool constant
        - returns None for everything else, including None itself — an expression
          this probe cannot compare is not evidence of anything
        - never raises
    """
    if isinstance( node, ast.Constant ) and isinstance( node.value, ( int, str, float, bool ) ):
        return repr( node.value )
    return None


def repeated_in( node ):
    """
    The repeated literal inside one dict / tuple / list node, or None.

    Requires:
        - node is any AST node

    Ensures:
        - returns ( value, times, total ) when the node is a Dict/Tuple/List whose
          elements are ALL plain literals, there are at least 2 of them, and at least
          one value appears more than once
        - returns None when the container is uniform-free (every value distinct), too
          short, mixed with non-literals, or not a container at all
        - a container of entirely-equal values reports times == total
        - never raises
    """
    if   isinstance( node, ast.Dict ):                     values = node.values
    elif isinstance( node, ( ast.Tuple, ast.List ) ):      values = node.elts
    else:                                                  return None

    literals = [ literal_of( value ) for value in values ]
    if len( literals ) < 2 or any( item is None for item in literals ): return None

    counts       = collections.Counter( literals )
    value, times = counts.most_common( 1 )[ 0 ]
    if times < 2: return None
    return ( value, times, len( literals ) )


def findings_in_source( text, path ):
    """
    Every interchangeable-value assertion in one source file.

    Requires:
        - text is the file's source; path is its display name

    Ensures:
        - returns a list of dicts with path / line / value / times / total, in source
          order, at most ONE per assert statement (the first container that repeats)
        - returns [ ] for a file with no asserts, and for one that does not parse —
          an unparseable file is not a finding
        - never raises
    """
    try:
        tree = ast.parse( text )
    except ( SyntaxError, ValueError ):
        return [ ]

    findings = [ ]
    for node in ast.walk( tree ):
        if not isinstance( node, ast.Assert ): continue
        for sub in ast.walk( node.test ):
            repeated = repeated_in( sub )
            if repeated is None: continue
            value, times, total = repeated
            findings.append( {
                "path"  : path,
                "line"  : node.lineno,
                "value" : value,
                "times" : times,
                "total" : total,
            } )
            break
    return sorted( findings, key=lambda item: item[ "line" ] )


def scan( paths, read_fn ):
    """
    Scan every path and return ( findings, files_read ).

    Requires:
        - paths is an iterable of file paths
        - read_fn( path ) -> source text, or raises when unreadable

    Ensures:
        - a path that cannot be read is SKIPPED and not counted in files_read, so an
          unreadable file never reports as a clean one
        - returns ( findings, files_read ) with findings in ( path, line ) order
        - never raises
    """
    findings   = [ ]
    files_read = 0
    for path in paths:
        try:
            text = read_fn( path )
        except Exception:
            continue
        files_read += 1
        findings.extend( findings_in_source( text, path ) )
    return ( sorted( findings, key=lambda item: ( item[ "path" ], item[ "line" ] ) ), files_read )


def _default_paths( root ):   # pragma: no cover - filesystem seam
    """Ensures: sorted test-file paths under `root`."""
    import pathlib
    return [ str( p ) for p in sorted( pathlib.Path( root ).rglob( TEST_GLOB ) ) ]


def _default_read( path ):    # pragma: no cover - filesystem seam
    """Ensures: the file's text."""
    with open( path, encoding="utf-8" ) as handle: return handle.read()


def render( findings, files_read, limit ):
    """
    The human-readable report, INCLUDING the caveat that makes it usable.

    Requires:
        - findings is scan()'s list; files_read is its count; limit is a positive int

    Ensures:
        - the caveat is printed whether or not there are findings — a triage aid that
          hides its own boundary is the thing it exists to catch
        - at most `limit` sites are listed, and the count of any remainder is stated
        - never raises
    """
    print( f"\nINTERCHANGEABLE-VALUE ASSERTIONS — {files_read} test files scanned\n" )
    for finding in findings[ :limit ]:
        print( f"  {finding[ 'path' ]}:{finding[ 'line' ]}  "
               f"value {finding[ 'value' ]} appears {finding[ 'times' ]} of {finding[ 'total' ]}" )
    if len( findings ) > limit:
        print( f"  … and {len( findings ) - limit} more (raise --limit to see them)" )
    if not findings:
        # 🔴 A ZERO RUN IS THE OUTPUT MOST LIKELY TO BE MISREAD, so it says so HERE rather
        # than only in the docstring (Chloé, 2026-08-30). A consumer reading stdout never
        # opens this file, and "no findings" from a triage aid reads as an all-clear.
        print( "  NOT FOUND — and NOT the same as none present." )
        print( "  This probe matches REPEATED expected values, the one shape of fixture" )
        print( "  blindness with a syntactic trace. A fixture blind because its value makes" )
        print( "  the operation a no-op, or because the wrong answer coincides with the right" )
        print( "  one, repeats nothing and CANNOT be found here. Measured: it returns zero on" )
        print( "  a file carrying a blind assertion at src/tests/unit/scripts/" )
        print( "  test_watch_hook_events.py. A file with no hits has not been cleared —" )
        print( "  it has not been examined. Only a mutation clears it." )

    print( "\nWHAT THIS LIST IS — read before filing anything" )
    print( "  FINDS      : assertions whose expected values REPEAT, so a swap between the two"
           " things they describe cannot change the outcome." )
    print( "  DOES NOT   : find undefended behaviour. Discrimination often lives in a SIBLING"
           " assertion this probe cannot see." )
    print( "  MEASURED   : the two hits adjudicated so far (2026-08-30) were BOTH covered"
           " elsewhere — one by the adjacent line, one by two sibling tests. Two is the"
           " whole adjudicated sample; there is no larger one." )
    print( "  MISSES     : returns zero on a file that carries a blind assertion — recall is"
           " demonstrably not total, and its rate is unknown (no denominator)." )
    print( "  SO         : every hit needs a mutation to adjudicate. This narrows where to point"
           " one; it does not replace one, and it is NEVER a defect count." )


def main( argv=None ):
    """
    Requires:
        - argv is a list of command-line arguments, or None for sys.argv[ 1: ]

    Ensures:
        - returns 2 when no file could be read, 1 when findings exist, else 0
        - --json emits the findings plus files_read and the caveat key
        - never raises
    """
    parser = argparse.ArgumentParser( description="Find assertions whose expected values are interchangeable" )
    parser.add_argument( "root", nargs="?", default=DEFAULT_ROOT )
    parser.add_argument( "--json", action="store_true", help="emit findings as JSON" )
    parser.add_argument( "--limit", type=int, default=40, help="how many sites to print" )
    args = parser.parse_args( argv )

    findings, files_read = scan( _default_paths( args.root ), _default_read )

    if files_read == 0:
        print( f"✗ no readable test files under {args.root} — this is NOT a clean result",
               file=sys.stderr )
        return 2

    if args.json:
        print( json.dumps( {
            "files_read" : files_read,
            "findings"   : findings,
            "caveat"     : ( "Blind ASSERTIONS, not undefended BEHAVIOUR. Discrimination often "
                             "lives in a sibling assertion this probe cannot see; every hit needs "
                             "a mutation to adjudicate. Never a defect count." ),
            "recall"     : ( "An empty findings list is NOT an all-clear. This probe matches "
                             "repeated expected values only — the one shape of fixture blindness "
                             "with a syntactic trace. Blindness from a no-op value, or from a "
                             "wrong answer that coincides with the right one, repeats nothing and "
                             "cannot be found here. Measured: zero hits on a file carrying a blind "
                             "assertion. Recall is demonstrably not total and its rate is unknown." ),
        }, indent=2 ) )
    else:
        render( findings, files_read, args.limit )

    return 1 if findings else 0


if __name__ == "__main__":   # pragma: no cover - entry point
    sys.exit( main() )
