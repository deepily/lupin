"""
The timeout mark guards on state="delivered". That value is correct only
while EVERY creation path that can reach the timeout waiter persists
"delivered" — and nothing in the code stops a third path appearing.

Row bf4f65c3. Mr. Radio's question, 2026-09-06: "what stops a third creation
path, and what would fire if one appeared?" The honest answers at the time
were NOTHING and NOTHING. This file is the second answer.

WHAT THIS GUARDS, AND WHY IT IS A CENSUS RATHER THAN A PROPERTY.
`routers/notifications.py:572` passes expected_state="delivered", justified in
a comment by an enumeration of the ask-creation paths taken at a88a723e:

    OFFLINE (:1279)  persists "expired", then returns a StreamingResponse
                     before any pending_responses entry exists — so no waiter,
                     so it can never reach the timeout mark.
    ONLINE  (:1315)  persists "delivered", and is the ONLY path that creates
                     the asyncio.Event the SSE generator can time out on.

"I looked and found two" is not "there can only be two". A third path added on
an ordinary afternoon makes that comment false with no test, no alarm, and no
reader going back to the sentence. These tests fail BY NAME when that happens,
which is the whole of their job: they do not decide what the new path should
do, they refuse to let it land unnoticed.

READ THE SOURCE, NOT THE IMPORTED MODULE. Importing the router would drag the
whole app in; the claim is about how the calls are WRITTEN, so `ast` over the
file is the instrument that matches the question.
"""

import ast

import cosa.utils.util as cu


PERSIST_FN    = "_persist_response_required_sync"
DEF_STATE_IDX = 13           # `state`'s position in the def, 0-based
ROUTER_REL    = "/src/cosa/rest/routers/notifications.py"

# THE HELPER IS NEVER CALLED DIRECTLY — it is HANDED to asyncio.to_thread,
# which calls it. So a search for `Call( func=Name( PERSIST_FN ) )` finds
# ZERO, and every assertion built on that population passes vacuously.
# Measured 2026-09-06: the first run of this file found 0 call sites, and its
# own positive control is what caught it. That control is why it is here.
#
# At the call site the helper occupies args[ 0 ], so `state` sits one further
# along than it does in the signature.
CALL_STATE_IDX = DEF_STATE_IDX + 1


def _router_tree():
    """
    Parse the notifications router from the tree this run resolves to.

    Requires:
        - LUPIN_ROOT resolves to a checkout containing the router

    Ensures:
        - returns ( ast.Module, source_text )

    Raises:
        - FileNotFoundError if the router is absent
    """
    path = cu.get_project_root() + ROUTER_REL
    with open( path ) as fh: source = fh.read()

    return ast.parse( source ), source


def _persist_calls( tree ):
    """
    Every call to the response-required persist helper, as AST Call nodes.

    Ensures:
        - returns the Call nodes only, never the FunctionDef
    """
    return [
        node for node in ast.walk( tree )
        if isinstance( node, ast.Call )
        and node.args
        and isinstance( node.args[ 0 ], ast.Name )
        and node.args[ 0 ].id == PERSIST_FN
    ]


def _state_literal_of( call ):
    """
    The `state` argument of one persist call, as a literal.

    Ensures:
        - returns the string when it is a plain literal
        - returns None when it is a name, an expression, or absent — an
          unreadable argument is reported, never guessed at
    """
    for kw in call.keywords:
        if kw.arg == "state":
            return kw.value.value if isinstance( kw.value, ast.Constant ) else None

    if len( call.args ) <= CALL_STATE_IDX: return None

    arg = call.args[ CALL_STATE_IDX ]

    return arg.value if isinstance( arg, ast.Constant ) else None


WAITER_NAME = "pending_responses"


def _waiter_creating_sites( tree ):
    """
    Every site that can CREATE an entry in the timeout waiter map.

    A PREDICATE, not a list of syntaxes. Rio's finding, 2026-09-06: the
    census above counts persist calls, and the safety argument is about the
    WAITER — a different population, with nothing enforcing their agreement.
    An enumeration of spellings (`= {`, `= dict(...)`, `.setdefault`) would
    inherit the very defect it is here to close, so this asks the shape of
    the write instead:

        pending_responses[ <anything> ] = <anything>      an Assign whose
                                                          target subscripts
                                                          the name DIRECTLY
        pending_responses.setdefault( ... ) / .update( ... )

    A nested write — `pending_responses[ id ][ "k" ] = v` — subscripts a
    Subscript, not the Name, so it is excluded: it mutates an entry that
    already exists and cannot bring a new waiter into being.

    Ensures:
        - returns the AST nodes, so callers read a real lineno rather than a
          character offset into text that may repeat
    """
    sites = []

    for node in ast.walk( tree ):
        if isinstance( node, ast.Assign ):
            for target in node.targets:
                if (     isinstance( target, ast.Subscript )
                     and isinstance( target.value, ast.Name )
                     and target.value.id == WAITER_NAME ):
                    sites.append( node )

        elif ( isinstance( node, ast.Call )
               and isinstance( node.func, ast.Attribute )
               and isinstance( node.func.value, ast.Name )
               and node.func.value.id == WAITER_NAME
               and node.func.attr in ( "setdefault", "update" ) ):
            sites.append( node )

    return sites


def _persist_line_by_state( tree ):
    """
    The line number of each persist call, keyed by the state it writes.

    Ensures:
        - returns { state_literal: lineno }, derived from the censused Call
          nodes rather than from a text search
    """
    return { _state_literal_of( call ) : call.lineno for call in _persist_calls( tree ) }


def test_the_persist_helper_is_findable_at_all():
    """
    The positive control. Every other test here asserts something about a set
    of call sites; an empty set passes all of them vacuously, and an empty
    result and a wrong-population result print the same thing.
    """
    tree, source = _router_tree()

    assert PERSIST_FN in source, f"{PERSIST_FN} is not in the router at all — this guard is aimed at the wrong file"

    defs = [
        node for node in ast.walk( tree )
        if isinstance( node, ast.FunctionDef ) and node.name == PERSIST_FN
    ]
    assert len( defs ) == 1, f"expected exactly 1 definition of {PERSIST_FN}, found {len( defs )}"

    args = [ a.arg for a in defs[ 0 ].args.args ]
    assert args[ DEF_STATE_IDX ] == "state", (
        f"positional {DEF_STATE_IDX} of {PERSIST_FN} is '{args[ DEF_STATE_IDX ]}', not 'state' — "
        "the signature moved and this guard is reading the wrong argument"
    )

    assert _persist_calls( tree ), (
        f"{PERSIST_FN} is defined but this guard finds no call site. It looks for the helper being "
        "handed to asyncio.to_thread as args[ 0 ]; if the router now reaches it some other way, "
        "every census below is running over an EMPTY population and passing for that reason."
    )


def test_exactly_two_creation_paths_persist_a_response_required_ask():
    """
    The census, with its size asserted. A third call site reddens here.

    This does NOT say a third path is wrong. It says the comment at
    routers/notifications.py:572 enumerated two, and somebody has to come
    back and re-derive whether "delivered" is still the right guard value.
    """
    tree, _ = _router_tree()
    calls   = _persist_calls( tree )

    assert len( calls ) == 2, (
        f"{len( calls )} creation paths call {PERSIST_FN}, not the 2 enumerated at a88a723e "
        "(offline->'expired', online->'delivered'). A path was added or removed: go and re-derive "
        "whether expected_state='delivered' at routers/notifications.py:572 is still correct, "
        "then update this count and that comment together."
    )


def test_every_creation_path_persists_a_state_the_timeout_guard_expects():
    """
    The values, not just the count. Two call sites both passing "created"
    would satisfy the census above and break the guard.
    """
    tree, _ = _router_tree()
    states  = sorted( _state_literal_of( c ) for c in _persist_calls( tree ) )

    assert None not in states, (
        "a creation path passes a non-literal state, so this guard cannot read it. "
        "An argument it cannot read is reported rather than assumed safe — go and check by hand "
        "whether that path can reach the timeout mark, and whether 'delivered' still guards it."
    )
    assert states == [ "delivered", "expired" ], (
        f"creation paths persist {states}, not ['delivered', 'expired']. "
        "routers/notifications.py:572 guards on expected_state='delivered' and will now REFUSE to "
        "expire any ask created in a state outside that set — silently, since a refusal returns None."
    )


def _report( request, lines ):
    """
    Print the census to the terminal, on GREEN as well as on red.

    Mr. Radio 🦉's requirement, 2026-09-06: a guard must say what it SCANNED,
    by name, not only assert a count. `print()` will not do it — pytest
    captures stdout and shows it only when a test fails, which is precisely
    the run where you already know something is wrong. The terminal writer
    bypasses capture, so the denominator is on screen when the file is green
    and a reader can catch it being wrong.

    Ensures:
        - writes nothing that could fail the test; a reporting error is not
          a finding about the code under test
    """
    writer = request.config.get_terminal_writer()
    for line in lines: writer.line( "[census] " + line )


def test_the_census_reports_what_it_scanned( request ):
    """
    THE DENOMINATOR, BY NAME.

    Every other test here asserts on a population. This one publishes it —
    each persist site with the state it writes, each waiter site, and the
    counts — so the corpus is visible rather than implied. A guard that
    cannot state its own denominator is telling you about its corpus, not
    about your code.

    It asserts the two floors as well, so it can never report a corpus it
    did not actually find: an empty discovery prints an empty list AND goes
    red, rather than printing nothing and passing.
    """
    tree, _  = _router_tree()
    persists = [ ( call.lineno, _state_literal_of( call ) ) for call in _persist_calls( tree ) ]
    waiters  = [ node.lineno for node in _waiter_creating_sites( tree ) ]

    _report( request, [
        f"router          : {ROUTER_REL}",
        f"persist sites   : {len( persists )} -> " + ", ".join(
            f"{PERSIST_FN}@{lineno} state={state!r}" for lineno, state in persists
        ),
        f"waiter sites    : {len( waiters )} -> " + ", ".join(
            f"{WAITER_NAME}@{lineno}" for lineno in waiters
        ),
    ] )

    assert persists, (
        f"the census scanned {ROUTER_REL} and found NO calls to {PERSIST_FN}. Every population "
        "assertion in this file would pass vacuously — the file is aimed at the wrong thing."
    )
    assert waiters, (
        f"the census scanned {ROUTER_REL} and found NO site creating a {WAITER_NAME} entry. The "
        "ordering proof below has nothing to order against."
    )


def test_exactly_one_site_creates_the_timeout_waiter():
    """
    RIO ⚡'s FINDING, 2026-09-06, and it is the one this file was missing.

    Every other test here censuses PERSIST calls. The safety argument is
    about the WAITER: "expired" is safe for the offline path only because
    that path never acquires one. Those are two different populations, and
    nothing made them agree — a future path that creates a pending_responses
    entry WITHOUT going through the persist helper is invisible to a census
    of persist calls, and would hand an "expired" row to the timeout mark
    where expected_state="delivered" refuses it.

    It also makes the ordering test below sound. `source.index()` returns the
    FIRST occurrence and asserts nothing about how many there are; pinning
    the population at one is what earns the right to speak of "the" waiter.

    Measured at 1ed335f8: exactly one, routers/notifications.py:1340.
    """
    tree, _ = _router_tree()
    sites   = _waiter_creating_sites( tree )

    assert len( sites ) == 1, (
        f"expected exactly 1 site creating a {WAITER_NAME} entry, found {len( sites )} at lines "
        f"{[ node.lineno for node in sites ]}. A second waiter is a second way to reach the timeout "
        "mark, and it needs its own ruling on which state it may expire from — the census in this "
        "file speaks only for paths that go through " + PERSIST_FN + "."
    )


def test_the_offline_path_returns_before_it_can_ever_be_timed_out():
    """
    The half of the argument that is about ORDER, not about a value.

    "expired" is a safe thing for the offline path to persist ONLY because
    that path never acquires a waiter — it returns its StreamingResponse
    before `pending_responses` is touched. If it ever started creating an
    entry, an "expired" row would reach the timeout mark and the guard would
    refuse a legitimate expiry.

    THE COORDINATES ARE AST LINE NUMBERS, NOT `source.index()` (Rio, same
    finding). A character offset into text is a search for the FIRST match of
    a string that nothing pins as unique, so the wrong occurrence and the
    right one produce the same integer. These come from the very nodes the
    census above counted, so there is no second occurrence to pick the wrong
    one of.
    """
    tree, source = _router_tree()

    by_state = _persist_line_by_state( tree )
    waiters  = _waiter_creating_sites( tree )

    assert set( by_state ) == { "delivered", "expired" }, (
        f"the persist calls no longer write exactly one 'delivered' and one 'expired': {by_state}. "
        "Re-derive the guard value before reading the order."
    )
    assert len( waiters ) == 1, (
        f"expected exactly 1 waiter-creating site, found {len( waiters )} — "
        "test_exactly_one_site_creates_the_timeout_waiter carries this and names why."
    )

    offline_at = by_state[ "expired" ]
    online_at  = by_state[ "delivered" ]
    waiter_at  = waiters[ 0 ].lineno

    assert offline_at < online_at < waiter_at, (
        "the offline persist, the online persist and the waiter entry are no longer in that order "
        f"(offline={offline_at}, online={online_at}, waiter={waiter_at}). The claim that the offline "
        "path cannot be timed out rests on it returning before any waiter exists."
    )

    between = "\n".join( source.splitlines()[ offline_at : online_at - 1 ] )

    assert "return StreamingResponse(" in between, (
        "the offline branch no longer returns a StreamingResponse before the online path, so it may "
        "fall through into the waiter. Re-derive the guard value at routers/notifications.py:572."
    )


def test_the_timeout_mark_actually_passes_the_guard():
    """
    THE GAP THIS FILE ALMOST LEFT OPEN.

    Everything above establishes that "delivered" is the RIGHT value. Nothing
    above establishes that the timeout path PASSES it — and `mark_expired`
    defaults `expected_state` to None, so dropping the argument leaves the live
    path writing unconditionally while every census here stays green.

    That is the exact shape Mr. Radio ruled against on 2026-09-06: a
    none-means-any default guards the sweeper and abandons the timeout path.
    Read from the source, because the claim is about how the call is WRITTEN.
    """
    _, source = _router_tree()

    marks = [
        line.strip() for line in source.splitlines()
        if "repo.mark_expired(" in line
    ]

    assert len( marks ) == 1, (
        f"expected exactly 1 mark_expired call in the router, found {len( marks )}: {marks}. "
        "A second caller needs its own ruling on what state it may expire from."
    )
    assert 'expected_state="delivered"' in marks[ 0 ], (
        f"the timeout mark does not pass the state guard: {marks[ 0 ]}. mark_expired defaults "
        "expected_state to None, so this call now writes UNCONDITIONALLY and can stamp 'expired' "
        "over an answer a human gave while the ask was timing out."
    )


def test_the_sweeper_also_passes_the_guard():
    """
    The sweeper's own call site, for the same reason and in the same shape.

    Its behaviour is pinned by
    test_the_orphan_sweeper_never_shortens_a_human_answer_window.py against a
    stand-in repository, and against a live Postgres in
    src/tests/smoke/test_mark_expired_refuses_to_overwrite_a_live_answer.py.
    This is the cheap textual belt: both writers of this row are guarded, and
    a reader auditing that question should find both answers in one file.
    """
    path = cu.get_project_root() + "/src/cosa/rest/notification_expiry_sweeper.py"
    with open( path ) as fh: source = fh.read()

    assert "repo.mark_expired(" in source, (
        "the sweeper no longer calls mark_expired — this guard is aimed at a call that has moved"
    )
    assert 'expected_state="delivered"' in source, (
        "the sweeper does not pass the state guard, so a /respond landing between its scan and "
        "its mark is overwritten again"
    )
