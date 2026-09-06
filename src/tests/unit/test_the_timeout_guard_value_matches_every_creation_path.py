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


def test_the_offline_path_returns_before_it_can_ever_be_timed_out():
    """
    The half of the argument that is about ORDER, not about a value.

    "expired" is a safe thing for the offline path to persist ONLY because
    that path never acquires a waiter — it returns its StreamingResponse
    before `pending_responses` is touched. If it ever started creating an
    entry, an "expired" row would reach the timeout mark and the guard would
    refuse a legitimate expiry.
    """
    _, source = _router_tree()

    offline_at = source.index( 'progress_group_id, "expired",' )
    online_at  = source.index( 'progress_group_id, "delivered",' )
    waiter_at  = source.index( "pending_responses[notification_id] = {" )

    assert offline_at < online_at < waiter_at, (
        "the offline persist, the online persist and the pending_responses entry are no longer in "
        f"that order (offline={offline_at}, online={online_at}, waiter={waiter_at}). The claim that "
        "the offline path cannot be timed out rests on it returning before any waiter exists."
    )

    between = source[ offline_at : online_at ]
    assert "pending_responses[" not in between, (
        "the offline branch now touches pending_responses, so an ask persisted 'expired' can reach "
        "the timeout mark — where expected_state='delivered' will refuse it. Re-derive the guard value."
    )
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
