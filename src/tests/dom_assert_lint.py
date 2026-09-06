"""
Never assert a DOM node as the ACTUAL value — row `f5768ee4`.

THE MECHANISM, measured on row `32c58572` (three runs per cell):

    happy-dom element + FAILING assert  → killed 3/3
    happy-dom element + PASSING assert  → survives
    plain object      + FAILING assert  → survives
    no happy-dom                        → survives

`node:assert` builds its failure diff by deep-inspecting the ACTUAL value. On a
happy-dom element that walk goes element → ownerDocument → defaultView → the
whole Window graph and never terminates: ~2.5 GB/s, linear, until the kernel
intervenes.

⇒ THE RULE: never pass a DOM node as an OPERAND of an assertion — on EITHER
side. The node may be produced and inspected freely; it must not be a thing the
assertion is holding at the moment it fails.

🔴 EITHER SIDE, MEASURED 2026-09-06 (Rio ⚡) — THIS RULE USED TO SAY "ACTUAL"
AND THAT WAS TOO NARROW. The prose above describes the diff as a walk of the
ACTUAL value, and the scanner guarded only the first argument. Five arms, one
variable, every arm capped in `jstest.slice`, happy-dom registered in all five:

    ACTUAL      EXPECTED    assertion   result
    ─────────────────────────────────────────────────────────────────────
    DOM node    null        FAILS       OOM, exit 134   ← the known killer
    null        DOM node    FAILS       OOM, exit 134   ← THE EXPECTED SIDE
    DOM node    DOM node    FAILS       OOM, exit 134
    plain obj   plain obj   FAILS       survives, 90 MB ← negative control
    DOM node    same node   PASSES      survives, 79 MB ← negative control

`node:assert` renders BOTH operands to build its diff, so the side the node sits
on is irrelevant. Both OOM arms abort identically with V8's
`CALL_AND_RETRY_LAST Allocation failed`. The two negative controls are what make
the two positives mean something — without them the probe could have been
killing every arm.

⚠️ THE BLIND SIDE WAS REAL AND UNPOPULATED, and both halves matter. At the time
of the measurement the tree carried ZERO expected-side-only sites across 161
`*.test.ts` files and 5,603 equal-family calls — so this widening remediates
nothing and costs no baseline entry. It closes a LATENT hazard, and it is cheap
precisely because it was done while the count was zero. That zero carries a
five-case positive control (the census correctly flagged a planted
expected-side violation, a planted actual-side one, a both-sides one, and
cleared two safe projections) — an uncontrolled zero here would be
indistinguishable from a census that could not see the second argument at all.

⇒ THE REMEDY: assert a PRIMITIVE PROJECTION — `textContent`, `id`, a count, a
boolean.

🔴 BUT NOT `tagName`/`className` FOR AN IDENTITY COMPARISON, AND THIS LINT'S OWN
MESSAGE USED TO SAY OTHERWISE. When the assertion means *these are the SAME
node*, projecting to a tag or a class WEAKENS it — two different elements share
a tag every day, so the projected assertion passes where the original would
fail. The correct primitive for identity is a BOOLEAN OF THE COMPARISON:

    ✅ assert.ok( a === b, "the control survived the disclosure" )
    ❌ assert.equal( a.tagName, b.tagName )        // passes for any two <div>s

Measured instance: `task_controls_survive_the_disclosure.test.ts:155`, where
following this file's own earlier advice would have turned the test green while
making it blind. Pick the projection that preserves what the assertion MEANT —
`textContent`/`id`/count for a value question, a boolean for an identity one.

🔴 WHY THIS IS PYTHON AND NOT AN ESLINT RULE, which the row preferred.
An ESLint rule would be the better instrument and it would RUN NOWHERE. There is
no ESLint config covering `src/tests` (the `lint` script points at
`src/lupin_app/static/js/multiplexer/` only), and the natural place to wire a new
TS-facing check is the TypeScript tier — which is under a standing ban and is not
executing. A check wired into a banned tier is a check that cannot fire, which is
the exact defect class row f5768ee4 exists to stop. This scanner runs in the
PYTHON unit tier, which runs freely on :7999 today. Move it to ESLint when the
tier is un-banned AND an ESLint config actually covers these files.

WHAT IT FLAGS: an `assert.<equal-family>(...)` EITHER of whose first two
arguments TERMINATES in a DOM-returning call or property. Terminating is the
load-bearing word: `assert.equal( el.textContent, "x" )` is CORRECT and must not
be flagged — it ends in a primitive projection. Both
`assert.equal( root.querySelector(".x"), null )` and
`assert.equal( 0, root.querySelector(".x") )` are violations, because when the
query DOES find a node the failure diff walks it from whichever side it sits on.

KNOWN LIMIT, stated rather than hidden: this is a textual scan, not a type
checker. It cannot see a DOM node reaching an assertion through a variable
(`const el = q(); assert.equal( el, null )`), so a clean run is not proof of
absence. It catches the shape that is written 276 times in this repo, and it is
mechanical. Real type-awareness needs the ESLint rule above.
"""
import collections
import re
from pathlib import Path

ASSERT_CALL = re.compile(
    r'assert\.(equal|strictEqual|deepEqual|deepStrictEqual|notEqual|notStrictEqual)\s*\('
)

# The first argument must END in one of these to be a violation. Anything
# following them (`.textContent`, `.length`, `?.id`) is a primitive projection
# and makes the assertion safe.
DOM_TERMINAL = re.compile(
    r'(?:'
    r'\.querySelector\s*\([^)]*\)|\.querySelectorAll\s*\([^)]*\)|'
    r'\.createElement\s*\([^)]*\)|\.getElementById\s*\([^)]*\)|'
    r'\.firstChild|\.lastChild|\.firstElementChild|\.lastElementChild|'
    r'\.parentElement|\.parentNode|\.nextElementSibling|\.previousElementSibling|'
    r'\.children\s*\[[^\]]*\]|\.childNodes\s*\[[^\]]*\]|'
    r'\bdocument\s*\.\s*body|\bdocument\s*\.\s*documentElement|'
    r'\.ownerDocument|\.defaultView'
    r')\s*$'
)

Violation = collections.namedtuple( "Violation", "path line expr" )


def _operand_arguments( text, index ):
    """
    The source text of the first TWO call arguments — actual and expected.

    Both are returned because `node:assert` renders both operands into its
    failure diff, so a DOM node OOMs from either side (measured 2026-09-06; the
    table is in this module's docstring). A scanner reading only the first
    argument is blind to exactly half the hazard.

    Requires:
        - index points just past the opening paren of a call

    Ensures:
        - nested parens/brackets/braces do not terminate the scan
        - returns exactly two stripped argument sources, "" for an absent one
    """
    depth = 0
    out   = []
    args  = []
    while index < len( text ) and len( args ) < 2:
        ch = text[ index ]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0: break
            depth -= 1
        elif ch == "," and depth == 0:
            args.append( "".join( out ).strip() )
            out = []
            index += 1
            continue
        out.append( ch )
        index += 1
    args.append( "".join( out ).strip() )
    return ( args + [ "", "" ] )[ :2 ]


def scan_text( text, path="<memory>" ):
    """
    Every violation in one file's source. Returns a list of Violation.

    ONE Violation per offending CALL, never one per offending operand — a call
    with a DOM node on both sides is one place to fix, and counting it twice
    would make the ratchet's numbers stop matching the edits that move them.
    """
    found = []
    for match in ASSERT_CALL.finditer( text ):
        actual, expected = _operand_arguments( text, match.end() )
        hit = None
        if   DOM_TERMINAL.search( actual   ): hit = actual
        elif DOM_TERMINAL.search( expected ): hit = expected
        if hit is not None:
            found.append( Violation( str( path ), text[ : match.start() ].count( "\n" ) + 1, hit ) )
    return found


def scan_tree( root ):
    """
    Every violation across `root`'s *.test.ts files.

    Ensures:
        - returns a list of Violation sorted by (path, line) so a diff of two
          runs is readable and a baseline file is stable
    """
    found = []
    for path in sorted( Path( root ).rglob( "*.test.ts" ) ):
        found.extend( scan_text( path.read_text( encoding="utf-8" ), path ) )
    return sorted( found, key=lambda v: ( v.path, v.line ) )


def violation_keys( violations ):
    """A set of stable `path:line` keys — the form the ratchet baseline stores."""
    return { "%s:%d" % ( v.path, v.line ) for v in violations }
