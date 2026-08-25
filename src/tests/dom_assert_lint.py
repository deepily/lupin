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

⇒ THE RULE: never pass a DOM node as the ACTUAL value of an assertion. Assert a
PRIMITIVE PROJECTION instead — `tagName`, `id`, `textContent`, a boolean, a
count. The node may be produced and inspected freely; it must not be the thing
the assertion is holding at the moment it fails.

🔴 WHY THIS IS PYTHON AND NOT AN ESLINT RULE, which the row preferred.
An ESLint rule would be the better instrument and it would RUN NOWHERE. There is
no ESLint config covering `src/tests` (the `lint` script points at
`src/lupin_app/static/js/multiplexer/` only), and the natural place to wire a new
TS-facing check is the TypeScript tier — which is under a standing ban and is not
executing. A check wired into a banned tier is a check that cannot fire, which is
the exact defect class row f5768ee4 exists to stop. This scanner runs in the
PYTHON unit tier, which runs freely on :7999 today. Move it to ESLint when the
tier is un-banned AND an ESLint config actually covers these files.

WHAT IT FLAGS: an `assert.<equal-family>(...)` whose FIRST argument TERMINATES in
a DOM-returning call or property. Terminating is the load-bearing word:
`assert.equal( el.textContent, "x" )` is CORRECT and must not be flagged — it
ends in a primitive projection. `assert.equal( root.querySelector(".x"), null )`
is a violation, because when the query DOES find a node the failure diff walks it.

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


def _first_argument( text, index ):
    """
    The source text of the first call argument, from `index` to the top-level comma.

    Requires:
        - index points just past the opening paren of a call

    Ensures:
        - nested parens/brackets/braces do not terminate the scan
        - returns the stripped argument source
    """
    depth = 0
    out   = []
    while index < len( text ):
        ch = text[ index ]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0: break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        out.append( ch )
        index += 1
    return "".join( out ).strip()


def scan_text( text, path="<memory>" ):
    """Every violation in one file's source. Returns a list of Violation."""
    found = []
    for match in ASSERT_CALL.finditer( text ):
        arg = _first_argument( text, match.end() )
        if DOM_TERMINAL.search( arg ):
            found.append( Violation( str( path ), text[ : match.start() ].count( "\n" ) + 1, arg ) )
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
