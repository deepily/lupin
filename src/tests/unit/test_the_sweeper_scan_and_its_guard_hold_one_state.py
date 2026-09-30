"""
The sweeper's SCAN and its GUARD hold the same state literal in two places —
this is what fires the day they stop agreeing. Store row `bf4f65c3`.

THE GAP THIS CLOSES, and it is not the one the sibling census closes.
`test_the_timeout_guard_value_matches_every_creation_path.py` looks at the
CREATION paths: it fires if a third path persists a state the guard does not
expect. It says nothing about the SCAN. Two hardcoded literals decide whether
this sweeper writes anything at all:

    get_expired_notifications()   filter( Notification.state == 'delivered' )
    sweep_once                    mark_expired( ..., expected_state="delivered" )

Nothing ties them together. Widen the scan to a second state — an ordinary
change, and exactly the kind somebody makes to make a sweeper reach further —
and every newly-scanned row becomes permanently REFUSED: the guard's WHERE
clause matches zero rows, mark_expired returns None, and the pass reports
success having written nothing. `refused` climbs, `swept` stays at zero, and
nobody is watching a counter.

⇒ A SILENT NO-OP WEARING A GREEN. That is the same shape as the defect this
whole row exists to fix, arriving from the other side: there the sweeper wrote
when it should not have, here it declines to write when it should.

FOUND BY MR. RADIO 🦉'S QUESTION, 2026-09-06 — "is `delivered` a naming choice
inside your module, or a CONTRACT VALUE something else branches on?" Measured
in answering it: 3 branches on Notification.state in the repository, and
ZERO schema-level constraint — `state` is a plain Mapped[str] with no Enum, no
CHECK, no server_default, so the database will accept any string. Nothing below
this test stands between a widened scan and a quiet sweeper.

⚠️ THE MECHANISM IS MEASURED; THE EXPOSURE IS DERIVED. Nobody has widened that
filter. This guards a reachable state, not an observed incident, and it is
recorded that way on purpose.

WHY TEXT AND NOT BEHAVIOUR. A behavioural test would need the two literals to
already disagree to have anything to observe, which is the situation this
exists to prevent. The claim here is about the SOURCE — that one value appears
in both places — so the source is the instrument that matches the question.
The sibling census file makes the same argument for the same reason.
"""

import ast
import re

import cosa.utils.util as cu


REPO_REL    = "/src/cosa/rest/db/repositories/notification_repository.py"
SWEEPER_REL = "/src/cosa/rest/notification_expiry_sweeper.py"

SCAN_FN  = "get_expired_notifications"
GUARD_KW = "expected_state"


def _source( rel ):
    """
    Read one project source file as text.

    Requires:
        - rel is a project-root-relative path beginning with a slash

    Ensures:
        - returns the file's text, resolved from LUPIN_ROOT at CALL time so a
          worktree reads its OWN tree rather than the main checkout
    """
    with open( cu.get_project_root() + rel ) as f: return f.read()


def _scan_state_literals():
    """
    Every string the scan's state filter is compared against.

    Requires:
        - the repository module parses

    Ensures:
        - returns the list of literals appearing in a `Notification.state == "..."`
          or `Notification.state.in_( [...] )` comparison INSIDE get_expired_notifications
        - returns [] when the function has no state filter at all, which is a
          finding rather than a pass — the callers assert non-empty
    """
    tree = ast.parse( _source( REPO_REL ) )

    fns = [ n for n in ast.walk( tree )
            if isinstance( n, ast.FunctionDef ) and n.name == SCAN_FN ]
    assert len( fns ) == 1, (
        f"expected exactly 1 definition of {SCAN_FN}, found {len( fns )} — the "
        "population this test reasons about is not what it thinks it is"
    )

    literals = []
    for node in ast.walk( fns[ 0 ] ):
        # Notification.state == "..."
        if isinstance( node, ast.Compare ) and _is_state_attr( node.left ):
            for comp in node.comparators:
                if isinstance( comp, ast.Constant ) and isinstance( comp.value, str ):
                    literals.append( comp.value )
        # Notification.state.in_( [ ... ] )
        if ( isinstance( node, ast.Call )
             and isinstance( node.func, ast.Attribute )
             and node.func.attr == "in_"
             and _is_state_attr( node.func.value ) ):
            for arg in node.args:
                if isinstance( arg, ( ast.List, ast.Tuple ) ):
                    literals += [ e.value for e in arg.elts
                                  if isinstance( e, ast.Constant ) and isinstance( e.value, str ) ]

    return literals


def _is_state_attr( node ):
    """True for the expression `Notification.state`, whatever it is compared to."""
    return ( isinstance( node, ast.Attribute ) and node.attr == "state"
             and isinstance( node.value, ast.Name ) and node.value.id == "Notification" )


def _guard_state_literals():
    """
    Every literal the sweeper passes as `expected_state`.

    Ensures:
        - returns the list of string constants passed to that keyword anywhere
          in the sweeper module
        - returns [] if the sweeper stopped passing the guard at all, which the
          callers assert against — an empty list here means the guard is gone,
          not that it agrees
    """
    tree = ast.parse( _source( SWEEPER_REL ) )
    return [ kw.value.value
             for node in ast.walk( tree ) if isinstance( node, ast.Call )
             for kw in node.keywords
             if kw.arg == GUARD_KW and isinstance( kw.value, ast.Constant )
             and isinstance( kw.value.value, str ) ]


def test_the_scan_filters_on_state_at_all():
    """
    POSITIVE CONTROL. Every assertion below reasons over a list built by an AST
    walk, and a walk that matches nothing yields an empty list that satisfies
    any `all(...)` written over it. This is what makes an empty result a
    failure instead of a silent pass.
    """
    literals = _scan_state_literals()
    assert literals, (
        f"{SCAN_FN} has no `Notification.state` comparison against a string literal. "
        "Either the scan stopped filtering by state — in which case the sweeper now "
        "reaches rows its guard can never mark, and every one of them will be counted "
        "`refused` forever — or this test's AST walk no longer matches the code it "
        "reads. Both are findings; neither is a pass."
    )


def test_the_sweeper_still_passes_a_guard_value_at_all():
    """
    POSITIVE CONTROL, the other side. Without it, deleting the guard entirely
    would leave both lists empty and the agreement assertion vacuously true.
    """
    literals = _guard_state_literals()
    assert literals, (
        f"the sweeper passes no `{GUARD_KW}=` string literal anywhere. The scan-then-mark "
        "guard is gone, and mark_expired's default writes UNCONDITIONALLY — which is the "
        "defect row bf4f65c3 exists to close, restored by deletion."
    )


def test_the_scan_and_the_guard_agree_on_exactly_one_state():
    """
    THE POINT OF THE FILE. Two hardcoded literals, one meaning.

    They are read from two different modules by two different AST walks, so
    this comparison has two independent provenances and cannot be satisfied by
    a tautology. Deriving both sides from one place would make it unfalsifiable.
    """
    scan  = sorted( set( _scan_state_literals() ) )
    guard = sorted( set( _guard_state_literals() ) )

    assert scan == guard, (
        f"the sweeper's scan admits {scan} and its guard expects {guard}.\n\n"
        "EVERY ROW IN THE DIFFERENCE IS ONE THE SWEEPER WILL SCAN AND NEVER MARK. "
        "mark_expired's WHERE clause will match zero rows for those states, return None, "
        "and sweep_once will count them under `refused` while reporting a successful pass "
        "that wrote nothing.\n\n"
        "If widening the scan was deliberate, widen the guard with it — mark_expired takes "
        "ONE expected_state, so a second admitted state needs a second call or a rethink of "
        "the guard's shape, not a wider filter and a hope."
    )
