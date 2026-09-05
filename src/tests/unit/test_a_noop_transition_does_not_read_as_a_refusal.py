"""
Row 3bf6ad1b — a no-op transition must not answer in refusal vocabulary, and a genuine
refusal must still refuse.

🔴 WHY BOTH ARMS, AND WHY THE SECOND ONE IS NOT CEREMONY. María 🌸's standing condition on
this epic, verbatim: *"otherwise 'return success' is satisfied by never refusing
anything."* A file containing only arm A would pass just as happily against a validator
that had been gutted. The refusal arms below are what make the softening arm mean
something.

=== WHAT THE DEFECT WAS ===

Asking the store to move a row to the status it is ALREADY at used to answer:

    no-op transition 'in_progress'->'in_progress' rejected — not a legal edge

"Rejected" and "not a legal edge" describe a REFUSAL. What actually happened is that the
caller's intent is already satisfied. Those are close to opposite facts and a caller acts
differently on each. Measured cost: María hit it three times on 2026-09-05 (rows
`9c3b817a`, `bfcea79d`, `88f4dfdb`) after a client-side read timeout, and read the retry's
422 as her approval having FAILED twice. It had succeeded — one `not_approved->queued`
write per row in the event log (`lupin_db_dev` events 11428, 11435, 11448). A manager DM'd
a worker that a live row was still blocked, and had to retract it.

=== THE TRAP THIS FILE ALSO PINS ===

The obvious repair is an OVERCLAIM. Saying *"your earlier call landed"* ATTRIBUTES the
move, and a no-op is genuinely ambiguous about WHO moved the row: your own timed-out call,
another actor, and a retry of something that never needed doing are indistinguishable from
here. The only thing always true is that the row is now at the requested status.
`test_the_noop_message_does_not_claim_authorship` is what keeps a future editor from
"improving" the string back into a claim.

=== WHAT THIS FILE DOES NOT ASSERT ===

· It does NOT assert the no-op should return 2xx. That was the row's other sanctioned
  option and it was not taken — see the comment at the call site for what was and was not
  established about it. This file pins the WORDING fix only, and would keep passing if a
  later change made the no-op idempotent, because every arm keys on the message rather
  than on the status code — except `test_a_genuinely_illegal_edge_is_still_refused`, whose
  subject is a different branch entirely.
· It does NOT claim the message is good prose. It claims three checkable properties:
  the refusal vocabulary is gone, the row's current status is stated, and authorship is
  disclaimed.
"""

import pytest

from cosa.rest import task_store_rules as rules


# The vocabulary a REFUSAL is allowed to use and a no-op is not. "rejected" and "not a
# legal edge" are the two the defect actually shipped; the rest are the near neighbours an
# editor would reach for while rewording, which is the moment this guard exists to catch.
REFUSAL_WORDS = ( "rejected", "not a legal edge", "refused", "illegal", "forbidden", "denied" )

# Phrases that would ATTRIBUTE the move to the caller. Each is a real sentence somebody
# might write while trying to be helpful, which is why they are listed rather than
# described.
AUTHORSHIP_PHRASES = (
    "your call landed",
    "your earlier call landed",
    "the first call did land",
    "your call succeeded",
    "already applied by you",
    "you already moved",
)


def _noop_errors( status ):
    """The validator's answer to a same->same transition, with no repoint/refresh payload."""
    return rules.validate_transition( status, status, "standing" )


def _the_noop_error( status ):
    """The single no-op error, or an assertion failure naming what came back instead."""
    errors = _noop_errors( status )
    hits   = [ e for e in errors if "no-op transition" in e ]
    assert len( hits ) == 1, f"{status}->{status} produced {errors!r}, expected exactly one no-op error"
    return hits[ 0 ]


# ---------------------------------------------------------------------------------------
# The population. Everything below quantifies over it, so it is named and proved non-empty
# rather than assumed — an empty corpus passes every per-item assertion in a loop.
# ---------------------------------------------------------------------------------------

NOOP_STATUSES = tuple( s for s in rules.VALID_STATUSES if s not in rules.TERMINAL_STATUSES )


def test_the_corpus_is_not_empty_positive_control():
    """
    THE CONTROL WITHOUT WHICH THE PARAMETRIZED ARMS BELOW PROVE NOTHING. If
    `NOOP_STATUSES` were ever empty — a rename, a refactor of the enums — every loop over
    it would pass by vacuity and this file would go green while measuring nothing.
    """
    assert len( NOOP_STATUSES ) >= 5, f"expected the live statuses, got {NOOP_STATUSES!r}"
    assert "queued" in NOOP_STATUSES and "in_progress" in NOOP_STATUSES
    assert not ( set( NOOP_STATUSES ) & set( rules.TERMINAL_STATUSES ) )


# ---------------------------------------------------------------------------------------
# ARM A — the no-op does not read as a refusal
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize( "status", NOOP_STATUSES )
def test_a_noop_does_not_answer_in_refusal_vocabulary( status ):
    message = _the_noop_error( status ).lower()
    for word in REFUSAL_WORDS:
        assert word not in message, (
            f"{status}->{status} answered with '{word}', which describes a refusal. The "
            f"caller's intent is already satisfied — this is not one. Full message: {message}"
        )


@pytest.mark.parametrize( "status", NOOP_STATUSES )
def test_the_noop_message_states_the_row_is_already_at_the_requested_status( status ):
    """
    The ONE fact a no-op always establishes. Everything else about it is unknowable from
    here, so this is the only positive claim the message is allowed to make.
    """
    message = _the_noop_error( status )
    assert "ALREADY" in message,     f"the message must say the row is already there: {message}"
    assert f"'{status}'" in message, f"the message must NAME the status: {message}"


@pytest.mark.parametrize( "status", NOOP_STATUSES )
def test_the_noop_message_does_not_claim_authorship( status ):
    """
    THE OVERCLAIM GUARD. Row 3bf6ad1b named this before anybody built the fix, because the
    helpful repair and the wrong repair are one sentence apart.
    """
    message = _the_noop_error( status ).lower()
    for phrase in AUTHORSHIP_PHRASES:
        assert phrase not in message, (
            f"the message claims the CALLER moved the row ('{phrase}'). Who moved it is not "
            f"knowable from a no-op. Full message: {message}"
        )
    assert "who moved" in message, (
        f"the message must actively disclaim authorship, not merely omit it — a caller who "
        f"is not told will infer. Full message: {message}"
    )


# ---------------------------------------------------------------------------------------
# ARM B — a genuine refusal still refuses, in refusal vocabulary
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize( "terminal", rules.TERMINAL_STATUSES )
def test_a_genuinely_illegal_edge_is_still_refused( terminal ):
    """
    `done -> queued` and its siblings. Named in the row as the arm that stops arm A from
    being satisfied by a validator that refuses nothing.
    """
    errors = rules.validate_transition( terminal, "queued", "standing" )
    assert errors, f"{terminal}->queued must be refused"
    joined = " ".join( errors ).lower()
    assert "terminal" in joined and "append-only" in joined, joined
    assert "no-op" not in joined, "a terminal source is not a no-op — it must not borrow that wording"


def test_a_park_from_not_approved_is_still_refused():
    """
    The second refusal the row names by hand. It is a DIFFERENT branch from the terminal
    one — `validate_park`, not the adjacency check — so it is a genuinely independent
    reading of "refusals still refuse", not a restatement of the arm above.
    """
    errors = rules.validate_transition(
        "not_approved", "parked", "standing",
        park_reason   = "quoting the row's own decisive sentence",
        next_chase_ts = "2026-09-06T09:00:00-04:00",
    )
    joined = " ".join( errors ).lower()
    assert "cannot park from 'not_approved'" in joined, joined


def test_an_invalid_target_status_is_still_refused():
    errors = rules.validate_transition( "queued", "bogus_status", "standing" )
    assert len( errors ) == 1 and "must be one of" in errors[ 0 ], errors


# ---------------------------------------------------------------------------------------
# THE SCOPE PROOF — why softening this branch cannot soften a real refusal
# ---------------------------------------------------------------------------------------

def test_the_noop_message_reaches_only_genuine_noops():
    """
    🔴 THE LOAD-BEARING TEST, AND IT IS A MEASUREMENT RATHER THAN A READING.

    The reasoning that makes the reword safe is: this branch is unreachable on a genuinely
    illegal edge, so no illegal edge is being softened. That is derivable from the
    `LEGAL_TRANSITIONS` comprehension — and a derivation is exactly the thing that goes
    quietly wrong when somebody hand-lists the graph or adds a status. So it is measured
    EXHAUSTIVELY over all ordered pairs instead, every run.

    Measured at 5535272a: 7 of 100 pairs, every one same->same.

    If a future change makes this branch reachable on a from != to pair, this test fails
    and whoever is standing there learns that the softened wording now covers something
    that ought to be refused.
    """
    statuses = rules.VALID_STATUSES
    reached  = [
        ( f, t )
        for f in statuses for t in statuses
        if any( "no-op transition" in e for e in rules.validate_transition( f, t, "standing" ) )
    ]

    assert reached, "positive control: the no-op branch must be reachable at all"
    offenders = [ ( f, t ) for f, t in reached if f != t ]
    assert not offenders, (
        f"the no-op wording now reaches {offenders} — pairs where from != to. Those are real "
        f"edges, and softening the vocabulary on them hides a refusal."
    )
    assert len( reached ) == len( NOOP_STATUSES ), (
        f"expected one no-op pair per non-terminal status ({len( NOOP_STATUSES )}), got "
        f"{len( reached )}: {reached}"
    )


def test_a_blocked_repoint_and_a_park_refresh_are_not_treated_as_noops():
    """
    THE ARM THAT STOPS THE SCOPE PROOF FROM PROVING TOO MUCH. `blocked->blocked` and
    `parked->parked` are same->same pairs that are LEGAL when they carry a real repoint or
    refresh payload. The count above is taken with no such payload, so this pins that the
    carve-outs still work and that the test above is measuring the no-op case rather than
    a validator that lost them.
    """
    repoint = rules.validate_transition(
        "blocked", "blocked", "standing",
        blocked_by            = [ { "kind": "persona", "id": "tiffany" } ],
        next_chase_ts         = "2026-09-06T09:00:00-04:00",
        current_blocked_by    = [ { "kind": "persona", "id": "rio" } ],
        current_next_chase_ts = "2026-09-05T09:00:00-04:00",
    )
    assert not any( "no-op transition" in e for e in repoint ), repoint

    refresh = rules.validate_transition(
        "parked", "parked", "standing",
        park_reason   = "a re-frozen quote",
        next_chase_ts = "2026-09-06T09:00:00-04:00",
    )
    assert not any( "no-op transition" in e for e in refresh ), refresh
