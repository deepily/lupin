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

NAMES, ADDED 2026-09-16 (row 8d043758, ruling (b)). The scan used to be blind to a
node reaching an assertion through a variable or a helper, and six real hazards
sat behind a green ratchet: `sentinel( p.root, "partial" )`, `dateNow()` twice,
and three node-to-node identity checks through plain names. It now resolves ONE
HOP: a `const`/`let`/`var` whose right-hand side terminates in a DOM call, and an
arrow helper whose expression body or `return` does. The binding in force is the
nearest one above the call. Name resolution applies to the aborting verbs only —
a failing `notStrictEqual( node, node )` was measured surviving at 205 MB.

KNOWN LIMIT, stated rather than hidden: this is a textual scan, not a type
checker. It does not follow two hops (`const a = q(); const b = a;`), function
parameters, `function` declarations, destructuring, or a reassignment
(`el = q()`), and "nearest binding above" is not lexical scope. A clean run is
not proof of absence. Real type-awareness needs the ESLint rule above — and as of
2026-09-16 no ESLint config covers `src/tests` at all.
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

# ── Names: a node reaching the operand through a binding (row 8d043758) ─────────
#
# Only the POSITIVE family. Measured 2026-09-16, four capped arms, happy-dom registered:
# `strictEqual( node, null )` failing was killed past 2048 MB; `notStrictEqual( node, node )`,
# `( null, null )` and `( obj, obj )` failing all survived under 250 MB. A failing negative
# assertion does not deep-inspect its operands. The inline rule above still covers the
# negative family; narrowing it is a separate ruling, not a side effect of this one.
ABORTING_VERBS = { "equal", "strictEqual", "deepEqual", "deepStrictEqual" }

_IDENT     = r"[A-Za-z_$][\w$]*"
_BINDING   = re.compile( r"\b(?:const|let|var)\s+(" + _IDENT + r")\s*(?::[^=;\n]*?)?=(?![=>])" )
_ARROW     = re.compile( r"^(?:async\s+)?(?:\([^()]*\)|" + _IDENT + r")\s*(?::[^=]*?)?=>\s*" )
_RETURN    = re.compile( r"\breturn\s+" )
_CAST      = re.compile( r"\s+as\s+[\w$.<>\[\]|&\s]+$" )
_NAME_HEAD = re.compile( r"^(" + _IDENT + r")\s*!?\s*" )
_TAIL      = re.compile( r"^\s*!?\s*(?:as\s+[\w$.<>\[\]|&\s]+)?$" )
# A newline does not end an expression when the next line continues it or this one is open.
_CONTINUES = re.compile( r"\s*(?:[.?:&|+\-*/,]|as\b)" )
_OPEN_TAIL = re.compile( r"(?:=>|[=?:&|+\-*/,])[ \t]*$" )

Binding   = collections.namedtuple( "Binding", "offset kind dom" )
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


def _expression_end( text, index ):
    """
    The offset where the expression starting at `index` ends.

    Requires:
        - index is inside `text` or at its end

    Ensures:
        - stops at a depth-0 `;`, at an unmatched closer, or at a depth-0 newline
          that neither continues onto the next line nor leaves this one open
        - returns len( text ) when none of those occur
    """
    depth = 0
    while index < len( text ):
        ch = text[ index ]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0: return index
            depth -= 1
        elif depth == 0 and ch == ";":
            return index
        elif ( depth == 0 and ch == "\n"
               and not _CONTINUES.match( text, index + 1 )
               and not _OPEN_TAIL.search( text, max( 0, index - 40 ), index ) ):
            return index
        index += 1
    return index


def _is_comparison( expr ):
    """
    True when `expr` is a COMPARISON at its top level, and so evaluates to a boolean.

    🔴 WHY THIS EXISTS (measured 2026-09-17, row f5768ee4's guard disagreeing with
    itself). `DOM_TERMINAL` is anchored at the END of the operand, so
    `a.parentElement === select.parentElement` matched — the expression ends in
    `.parentElement` — and the guard flagged an operand whose value is `true` or
    `false`. The same guard passed `select.closest( ".x" ) !== null`, which ends in
    `null`. So whether a boolean comparison was flagged depended on which side of it
    happened to end in a DOM accessor, and the advice the failure message gives
    ("assert a BOOLEAN of the comparison") was itself reported as a violation.

    The hazard is absent for a comparison: `assert.equal( false, true )` failing
    renders two booleans, which is what the four capped arms in 2026-09-16 measured
    as surviving under 250 MB. Only a NODE reaching an operand deep-inspects the
    happy-dom graph.

    Requires:
        - expr is the operand's source text

    Ensures:
        - True when a `===`, `!==`, `==` or `!=` sits at bracket depth 0
        - False when every such operator is nested inside brackets, so
          `q( root.querySelector( "x" ) === y ).parentElement` still terminates in DOM
        - never raises
    """
    depth = 0
    index = 0
    while index < len( expr ):
        ch = expr[ index ]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch in "=!" and expr[ index + 1 : index + 2 ] == "=":
            # `=`/`!` followed by `=`: one of == === != !==. An arrow `=>` cannot
            # reach here (it is `=` then `>`), and a lone `=` is an assignment, not
            # an operand of an assert call.
            return True
        index += 1
    return False


def _terminates_in_dom( expr ):
    """True when `expr`, stripped of a trailing `!` and `as <Type>`, ends in a DOM call or property."""
    expr = expr.strip().rstrip( "!" )
    expr = _CAST.sub( "", expr ).strip().rstrip( "!" )
    if _is_comparison( expr ): return False
    return bool( DOM_TERMINAL.search( expr ) )


def name_bindings( text ):
    """
    Every one-hop `const`/`let`/`var` binding in `text`, keyed by name.

    A binding is a "helper" when its right-hand side is an arrow function, and a
    "value" otherwise. `dom` records whether it yields a DOM node: a value whose
    expression terminates in one, or a helper whose expression body or any
    `return` expression does.

    Ensures:
        - returns { name: [ Binding( offset, kind, dom ), ... ] } in source order
        - a name bound more than once keeps every binding, so the caller can pick
          the one in force at a given offset
    """
    table = collections.defaultdict( list )
    for match in _BINDING.finditer( text ):
        rhs   = text[ match.end() : _expression_end( text, match.end() ) ].strip()
        arrow = _ARROW.match( rhs )
        if arrow is None:
            table[ match.group( 1 ) ].append( Binding( match.start(), "value", _terminates_in_dom( rhs ) ) )
            continue
        body = rhs[ arrow.end(): ].strip()
        if body.startswith( "{" ):
            returns = [ body[ r.end() : _expression_end( body, r.end() ) ] for r in _RETURN.finditer( body ) ]
            dom     = any( _terminates_in_dom( r ) for r in returns )
        else:
            dom = _terminates_in_dom( body )
        table[ match.group( 1 ) ].append( Binding( match.start(), "helper", dom ) )
    return table


def _named_operand_is_dom( operand, table, offset ):
    """
    True when `operand` is a bare name, or one call of a name, whose binding in
    force at `offset` yields a DOM node.

    "In force" is the nearest binding ABOVE the call. That is not real scope, and it
    is deliberately the cheap approximation that fixed the measured collision
    (`const body = document.body` poisoning a later `const body = { tasks }`).

    Ensures:
        - `el`, `el!`, `el as T`            → a "value" binding must be DOM
        - `q()`, `q( a, b )!`, `q() as T`   → a "helper" binding must be DOM
        - anything following the name or its call (`.textContent`, `?.x`) → False
    """
    operand = operand.strip()
    head    = _NAME_HEAD.match( operand )
    if head is None: return False
    rest   = operand[ head.end(): ]
    called = rest.startswith( "(" )
    if called:
        close = _expression_end( rest, 1 )
        if close >= len( rest ) or rest[ close ] != ")": return False
        rest = rest[ close + 1: ]
    if not _TAIL.match( rest ): return False
    prior = [ b for b in table.get( head.group( 1 ), [] ) if b.offset < offset ]
    if not prior: return False
    binding = prior[ -1 ]
    return binding.dom and binding.kind == ( "helper" if called else "value" )


def scan_text( text, path="<memory>" ):
    """
    Every violation in one file's source. Returns a list of Violation.

    ONE Violation per offending CALL, never one per offending operand — a call
    with a DOM node on both sides is one place to fix, and counting it twice
    would make the ratchet's numbers stop matching the edits that move them.

    Two ways in: an operand that terminates in a DOM call written inline (every
    equal-family verb), or an operand that reaches a DOM node through a one-hop
    name (the aborting verbs only — see ABORTING_VERBS).
    """
    found = []
    table = None
    for match in ASSERT_CALL.finditer( text ):
        actual, expected = _operand_arguments( text, match.end() )
        hit = None
        # Through `_terminates_in_dom`, NOT `DOM_TERMINAL` directly: the helper is
        # where the boolean-comparison exemption lives, and calling the regex here
        # bypassed it. That is how `a.parentElement === b.parentElement` — a boolean,
        # and the very form the failure message tells people to write — was reported
        # as a violation while `x !== null` was not (measured 2026-09-17).
        if   _terminates_in_dom( actual   ): hit = actual
        elif _terminates_in_dom( expected ): hit = expected
        elif match.group( 1 ) in ABORTING_VERBS:
            if table is None: table = name_bindings( text )
            if   _named_operand_is_dom( actual,   table, match.start() ): hit = actual
            elif _named_operand_is_dom( expected, table, match.start() ): hit = expected
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
