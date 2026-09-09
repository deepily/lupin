"""
A REQUEST WAITS FOREVER; A DENIAL CLOSES IT — row c9fafb9d, rules 3 and 4.

Rick's semantics, 2026-09-09 ~17:40 and ~18:55, relayed by Mr. Radio 🦉:

    · a request PERSISTS until he acts on it — no expiry, no timeout
    · a TIMEOUT leaves it PENDING. A timeout is NOT a denial
    · a DENIAL closes the row and forces a RE-FILE
    · the verdict is recorded ON THE REQUEST ROW, not carried by a notification

🔴 THE DEFECT THESE ARMS EXIST TO CATCH IS A REACH FOR THE NEAREST SIMILAR THING. The tree
already holds `TaskPromotionTicket` — `resolves_by` stamped at mint, a background resolver,
a sweeper that marks an unanswered ticket `stalled`. All of that is EXPIRY, and expiry is
what Rick ruled against. An implementer building the request door from that machinery gets
a request that dies on a clock, and every test written over it stays green.

⚠️ THE STRONGEST ARM HERE IS A SIGNATURE CHECK, NOT A VALUE CHECK. Asserting that a
day-old request is still pending only proves today's code does not age it; the next edit
could add a deadline and that assertion would still pass, because the test would simply
never supply one. `test_nothing_in_this_module_can_be_told_the_time` asserts instead that
these functions TAKE NO CLOCK — there is nothing to age a request against. A rule that
depends on remembering is not installed.
"""

import inspect

import pytest

from cosa.rest import task_request_lifecycle   as life
from cosa.rest import task_approval_settings   as approval


ALL_STATES = ( life.REQUEST_PENDING, life.REQUEST_APPROVED, life.REQUEST_DENIED )


# ---------------------------------------------------------------------------
# THE VOCABULARY — a control before the arms that depend on it
# ---------------------------------------------------------------------------

def test_the_three_states_and_which_of_them_are_finished():
    assert life.REQUEST_STATES == frozenset( ALL_STATES )
    assert life.REQUEST_TERMINAL_STATES == frozenset(
        { life.REQUEST_APPROVED, life.REQUEST_DENIED } )
    assert life.REQUEST_PENDING not in life.REQUEST_TERMINAL_STATES, (
        "pending is terminal, which would mean a request nobody answered is finished"
    )


def test_the_verbs_come_from_the_approval_module_and_are_not_a_second_copy():
    """
    A re-export, asserted as one. Two modules each holding their own idea of which moves
    are requestable agree until somebody adds a third, and the copy is usually the one
    that is wrong.
    """
    assert life.REQUESTABLE_MOVES is approval.REQUESTABLE_MOVES
    assert life.REQUESTABLE_MOVES == frozenset(
        { approval.MOVE_ADMIT, approval.MOVE_DEMOTE } )


# ---------------------------------------------------------------------------
# SILENCE — the ruling, and the ruling made structural
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "state", ALL_STATES )
def test_silence_changes_nothing_whatever_the_state( state ):
    assert life.outcome_of_silence( state ) == state


def test_a_pending_request_is_still_pending_and_is_NOT_denied():
    """
    🔴 THE DISTINCTION RICK DREW HIMSELF, and the one an implementer is most likely to
    collapse. "Defaults to no" protects against silence GRANTING; it does not mean silence
    DENIES. A pending request authorises nothing AND requires no re-file — it is simply
    still in front of him.
    """
    state = life.outcome_of_silence( life.REQUEST_PENDING )

    assert state == life.REQUEST_PENDING
    assert state != life.REQUEST_DENIED,        "silence denied a request Rick has not answered"
    assert not life.grants_the_move( state ),   "silence granted the move — 'defaults to no' is broken"
    assert not life.is_terminal( state ),       "an unanswered request was treated as finished"
    assert not life.requires_a_refile( state ), "an unanswered request demanded a re-file, which would double-ask him"


def test_nothing_in_this_module_can_be_told_the_time():
    """
    🔴 THE STRUCTURAL ARM, AND THE ONE THAT SURVIVES A FUTURE EDIT. Every value assertion
    above is satisfied by code that ages requests but was never handed a clock by this
    test. This one asserts the ABSENCE of the parameter: no function here accepts a
    deadline, a timestamp, an elapsed time or a now, so there is nothing to age a request
    against.

    ⚠️ IT IS A NAME-BASED PREDICATE AND THAT IS ITS LIMIT, SAID PLAINLY. Somebody could add
    a clock under a name this does not recognise. It catches the ordinary way the defect
    arrives — a `now` or a `deadline` parameter added in good faith — and it is not proof
    that no clock can ever reach here. That proof would need the storage layer, which
    nobody has ruled yet.
    """
    clocklike = ( "now", "when", "clock", "time", "deadline", "elapsed", "expires",
                  "expiry", "resolves_by", "ts", "timestamp", "age", "since", "until" )

    checked = 0
    for name, fn in vars( life ).items():
        if not callable( fn ) or getattr( fn, "__module__", None ) != life.__name__: continue
        checked += 1
        params = set( inspect.signature( fn ).parameters )
        offenders = sorted( p for p in params
                            if any( word in p.lower() for word in clocklike ) )
        assert not offenders, (
            f"`{name}` accepts {offenders}. A request PERSISTS until Rick acts (his ruling, "
            f"2026-09-09) — giving this module a clock is how it grows an expiry, which is "
            f"the exact machinery `TaskPromotionTicket` already has and that he ruled out."
        )

    assert checked >= 5, (
        f"the loop inspected only {checked} functions, so passing means very little. "
        f"A loop over nothing satisfies every assertion inside it."
    )


# ---------------------------------------------------------------------------
# THE VERDICTS
# ---------------------------------------------------------------------------

def test_only_an_approval_grants_the_move():
    assert life.grants_the_move( life.REQUEST_APPROVED ) is True
    assert life.grants_the_move( life.REQUEST_PENDING )  is False
    assert life.grants_the_move( life.REQUEST_DENIED )   is False


def test_only_a_denial_forces_a_refile():
    assert life.requires_a_refile( life.REQUEST_DENIED )   is True
    assert life.requires_a_refile( life.REQUEST_PENDING )  is False
    assert life.requires_a_refile( life.REQUEST_APPROVED ) is False


def test_a_denial_and_a_timeout_are_not_the_same_thing():
    """
    Both leave the move unauthorised, so `grants_the_move` cannot tell them apart — and a
    test that only checked that would pass with the two collapsed. What separates them is
    whether the manager must ask again, which is Rick's own words for the difference.
    """
    denied, pending = life.REQUEST_DENIED, life.REQUEST_PENDING

    assert life.grants_the_move( denied ) == life.grants_the_move( pending ) is False
    assert life.requires_a_refile( denied ) != life.requires_a_refile( pending ), (
        "a denial and an unanswered request demand the same thing of the manager, so the "
        "distinction Rick drew has been collapsed"
    )
    assert life.is_terminal( denied ) != life.is_terminal( pending )


# ---------------------------------------------------------------------------
# WHO MAY ANSWER — rules 1 and 2, one layer over
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "verdict", [ life.REQUEST_APPROVED, life.REQUEST_DENIED ] )
def test_the_operator_records_a_verdict_on_a_pending_request( verdict ):
    """
    🔴 THE POSITIVE ARM. Without it every refusal below is satisfied by a function that
    refuses everybody, which would be a worse defect than the one being guarded.
    """
    assert life.refusal_for_verdict( life.REQUEST_PENDING, verdict,
                                     actor_is_operator=True ) is None


@pytest.mark.parametrize( "verdict", [ life.REQUEST_APPROVED, life.REQUEST_DENIED ] )
def test_a_manager_may_not_answer_its_own_request( verdict ):
    """
    If a manager could answer here, the request door would BE a way to promote without
    Rick — the thing it exists to prevent. Rules 1 and 2, one layer over.
    """
    refusal = life.refusal_for_verdict( life.REQUEST_PENDING, verdict,
                                        actor_is_operator=False )
    assert refusal, f"a non-operator recorded '{verdict}' on a request"
    assert "operator" in refusal.lower()


def test_pending_is_not_a_verdict_anyone_can_record():
    refusal = life.refusal_for_verdict( life.REQUEST_PENDING, life.REQUEST_PENDING,
                                        actor_is_operator=True )
    assert refusal, "'pending' was accepted as a verdict, making un-answering reachable"
    assert "not a verdict" in refusal


@pytest.mark.parametrize( "state",   [ life.REQUEST_APPROVED, life.REQUEST_DENIED ] )
@pytest.mark.parametrize( "verdict", [ life.REQUEST_APPROVED, life.REQUEST_DENIED ] )
def test_an_answered_request_cannot_be_answered_again( state, verdict ):
    """
    Includes the same-verdict case on purpose — `approved -> approved` is not a harmless
    no-op if it rewrites who answered and when.
    """
    refusal = life.refusal_for_verdict( state, verdict, actor_is_operator=True )
    assert refusal, f"a '{state}' request accepted a second verdict '{verdict}'"
    assert "re-file" in refusal.lower() or "refile" in refusal.lower(), (
        "the refusal does not say what to do instead — a dead end wearing a refusal, which "
        "this row's acceptance forbids"
    )


def test_the_refusals_are_three_distinct_sentences():
    """
    ⚠️ A CALLER WHO CANNOT TELL THE THREE APART CANNOT ACT. "You are not the operator",
    "that is not a verdict" and "this one is already answered" call for three different
    next steps, and a shared message would make the reader guess which.
    """
    not_operator = life.refusal_for_verdict( life.REQUEST_PENDING,  life.REQUEST_APPROVED, False )
    not_verdict  = life.refusal_for_verdict( life.REQUEST_PENDING,  life.REQUEST_PENDING,  True )
    already      = life.refusal_for_verdict( life.REQUEST_APPROVED, life.REQUEST_DENIED,   True )

    assert len( { not_operator, not_verdict, already } ) == 3, (
        "two of the three refusals are byte-identical"
    )
    # The ORDER is load-bearing: a non-operator sending a junk verdict must be told about
    # authority first, because that is the fact that stops them, and telling them their
    # verdict is malformed would send them to fix the wrong thing.
    assert life.refusal_for_verdict( life.REQUEST_APPROVED, life.REQUEST_PENDING,
                                     actor_is_operator=False ) == not_operator
