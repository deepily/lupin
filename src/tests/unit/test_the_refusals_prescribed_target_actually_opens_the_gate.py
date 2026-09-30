"""
THE GATE'S OWN REMEDY, FED BACK INTO THE GATE — row aba30387, defect (3).

The refusal says "Close or finish N more rows before filing this one." That sentence is
a PROMISE about a future state: close N, and the next create goes through. Nothing tested
that promise. `test_the_refusal_says_how_many_more_to_close` asserts the message contains
a hardcoded "12" — a claim about the STRING, not about the gate.

🔴 MEASURED 2026-09-04, live: at created=209, closed=184, allow_below=1.10 the message
says "close or finish 6 more rows", i.e. reach closed=190. At closed=190 the gate STILL
REFUSES. A caller who does exactly what they were told spends six closures and is turned
away again. This file is what would have caught it.

MECHANISM — IEEE float, not logic. `209/1.10 = 189.99999999999997`, mathematically exactly
190.0 but the double lands just under, so `math.floor` gives 189 and the `+1` recovers only
190 — which sits ON the boundary the gate opens STRICTLY below.

⚠️ THE `+1` EXISTS PRECISELY FOR THIS CASE. The function's own comment says so and names
the guard meant to catch it. That guard runs created=14, closed=3 at the DEFAULT threshold
of 1.0, where `14/1.0` is EXACT — so the float error never appears. No arm in that file
exercises a non-integer threshold. The code was right in intent, the test was right about
what it tested, and nothing in the suite could notice this going wrong: CLAUDE.md's THIRD
STATE, UNGUARDED. It became reachable the day the operator dial moved off 1.0.

⇒ SO THE ASSERTION HERE IS DELIBERATELY NOT A NUMBER. It reads the count out of the gate's
own message and feeds the resulting target back into the gate. A test that pins a number
can only ever restate the arithmetic it is checking; this one cannot pass unless the
promise is true.
"""

import re

import pytest

from cosa.rest import task_store_rules as rules


TARGET = re.compile( r"finish (\d+) more row" )


def prescribed_target( created, closed, allow_below ):
    """
    The `closed` count the refusal TELLS the caller to reach.

    Requires:
        - the gate refuses at (created, closed, allow_below)

    Ensures:
        - returns closed + N, where N is the count named in the gate's own message
        - fails the test loudly if the gate did not refuse, or the message carries no
          count — an unparsed message must never silently become a passing assertion
    """
    message = rules.ratio_gate_advisory( created=created, closed=closed, allow_below=allow_below )
    assert message is not None, (
        f"expected a REFUSAL at created={created} closed={closed} allow_below={allow_below}; "
        f"got an allow, so there is no prescription to check"
    )
    match = TARGET.search( message )
    assert match is not None, f"the refusal names no count to close: {message!r}"
    return closed + int( match.group( 1 ) )


# --------------------------------------------------------------------------------------
# The control — this file measures nothing if the gate is not refusing in the first place
# --------------------------------------------------------------------------------------

def test_the_gate_actually_refuses_the_cases_this_file_prescribes_from():
    """
    🔴 ASSERT THE CONTROL EXISTS BEFORE ASSERTING WHAT IT DOES. Every arm below reads a
    count out of a refusal. If the gate allowed these inputs there would be no message,
    no count, and the loop would assert nothing while passing. GREEN IN BOTH ARMS — before
    the fix and after — so a later red means the PROMISE broke, not the setup.
    """
    for created, closed, allow_below in ( ( 209, 184, 1.10 ), ( 14, 3, 1.0 ), ( 110, 95, 1.10 ) ):
        assert rules.ratio_gate_advisory(
            created=created, closed=closed, allow_below=allow_below
        ) is not None, f"expected a refusal at {created}/{closed} @ {allow_below}"


# --------------------------------------------------------------------------------------
# The promise
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "created, closed, allow_below, why",
    [
        ( 209, 184, 1.10, "TODAY'S LIVE CASE — the one that cost john six closures" ),
        ( 209, 183, 1.10, "maria's refusal, same numerator, one fewer closed" ),
        (  55,  40, 1.10, "exact boundary: 55/1.10 is a whole number" ),
        ( 110,  90, 1.10, "exact boundary at a round numerator" ),
        (  99,  80, 1.10, "exact boundary, 99/1.10 = 90" ),
        ( 132, 100, 1.10, "exact boundary, 132/1.10 = 120" ),
        (  14,   3, 1.00, "the ORIGINAL guard's case — threshold 1.0, division exact" ),
        (  10,   2, 1.00, "a second exact-threshold case, to keep 1.0 covered here too" ),
        (  75,  50, 1.50, "a non-1.1 threshold, exact boundary" ),
        (  90,  70, 0.90, "a threshold BELOW 1.0, exact boundary" ),
    ],
)
def test_closing_what_the_refusal_asks_for_actually_opens_the_gate( created, closed, allow_below, why ):
    """
    🔴 THE ONE THIS FILE EXISTS FOR, and the assertion maria named: "the test should assert
    that closing what it asks for allows the next create."

    Note what is NOT here: a hardcoded expected count. The number comes out of the gate's
    own message, so this arm stays true whatever the arithmetic becomes — it pins the
    PROMISE, not the implementation.
    """
    target = prescribed_target( created, closed, allow_below )
    verdict = rules.ratio_gate_advisory( created=created, closed=target, allow_below=allow_below )
    assert verdict is None, (
        f"THE GATE BROKE ITS OWN PROMISE ({why}). At created={created} closed={closed} "
        f"allow_below={allow_below} it said to reach closed={target}, and at closed={target} "
        f"(ratio {created/target:.6f}) it STILL REFUSES: {verdict}"
    )


def test_the_prescribed_target_is_the_SMALLEST_one_that_opens_the_gate():
    """
    The mirror arm, and it is what stops the obvious wrong fix. Adding a fudge factor —
    +2, or a ceil, or rounding the threshold — would satisfy every arm above while telling
    callers to close MORE rows than they need to. That is a different way of being wrong
    about the same sentence, and it would look like a fix.

    ⇒ So: one fewer than the prescribed target must still REFUSE.
    """
    for created, closed, allow_below in (
        ( 209, 184, 1.10 ), ( 55, 40, 1.10 ), ( 110, 90, 1.10 ), ( 14, 3, 1.00 ), ( 90, 70, 0.90 )
    ):
        target = prescribed_target( created, closed, allow_below )
        assert rules.ratio_gate_advisory(
            created=created, closed=target - 1, allow_below=allow_below
        ) is not None, (
            f"at created={created} allow_below={allow_below} the gate prescribed "
            f"closed={target}, but closed={target - 1} ALREADY opens it — the refusal is "
            f"asking for more closures than it needs"
        )


# --------------------------------------------------------------------------------------
# THE PROOF ARM — maria's spec, verbatim, 2026-09-04
#
#   RULE   a guard whose two sides share a source is a tautology. Do not commit it.
#   SIDE A parse the number out of the rendered refusal string the caller sees.
#   SIDE B call the gate function at that number. Assert it ALLOWS.
#   PROOF  feed side B a number side A did not produce. Test must die. If it passes,
#          the sides share a source.
#
# 🔴 AND SHE WAS RIGHT ABOUT THE FILE ABOVE. `prescribed_target` (side A) reads the count
# out of the rendered message; side B calls the gate at that number. AFTER the fix, the
# count is itself derived from the SAME comparison side B makes — so the promise assertion
# is true by construction and cannot fail. M1 kills only because it reverts to a prior,
# independent implementation. A test whose whole power is "catches the old code" is
# decoration against the new one.
#
# ⚠️ ONE CORRECTION TO MY OWN CONCESSION, because "decoration" is not quite the whole
# truth either and the difference is what the next reader needs. The ARITHMETIC half is
# tautological. The RENDERING half is not: side A parses the string a caller actually
# sees, so interpolating the wrong variable, an off-by-one in the f-string, or dropping
# the count entirely is caught — and none of those is reachable from the comparison. What
# follows closes the arithmetic half; the rendering half was already real.
# --------------------------------------------------------------------------------------

from fractions import Fraction


# Hand-written, by a person, from the definition "the smallest c with created/c < threshold".
# 🔴 THIS TABLE IS THE POINT: it does not come from `ratio_gate_advisory`, from the router,
# or from any float in the production path. It is the DIFFERENT PROVENANCE the comparison
# needs in order to be able to fail at all.
EXPECTED_TARGET = {
    ( 209, 1.10 ) : 191,
    (  55, 1.10 ) :  51,
    ( 110, 1.10 ) : 101,
    (  99, 1.10 ) :  91,
    ( 132, 1.10 ) : 121,
    (  14, 1.00 ) :  15,
    (  10, 1.00 ) :  11,
    (  75, 1.50 ) :  51,
    (  90, 0.90 ) : 101,
}


def oracle_target( created, allow_below ):
    """
    The smallest `closed` that opens the gate, in EXACT RATIONAL ARITHMETIC.

    No IEEE float anywhere: `Fraction( 1.10 ).limit_denominator( 10**6 )` is 11/10, the
    threshold the operator MEANS, not the double that is a hair above it. So this oracle
    cannot inherit the very error the fix is about — which is the whole reason it is fit
    to check the fix.

    Ensures:
        - returns the least c >= 1 with Fraction( created, c ) < Fraction( allow_below )
        - never raises for created >= 0 and allow_below > 0
    """
    threshold = Fraction( allow_below ).limit_denominator( 10 ** 6 )
    c = 1
    while Fraction( created, c ) >= threshold:
        c += 1
    return c


def test_the_hand_written_table_and_the_rational_oracle_agree():
    """
    The oracle checks the table; the table checks the oracle. Two independent provenances,
    neither of them the code under test — so a mistyped literal cannot quietly become the
    expected value, and a wrong oracle cannot either. GREEN IN BOTH ARMS.
    """
    for ( created, allow_below ), expected in EXPECTED_TARGET.items():
        assert oracle_target( created, allow_below ) == expected, (
            f"hand-written {expected} disagrees with the rational oracle "
            f"{oracle_target( created, allow_below )} at created={created} thr={allow_below}"
        )


@pytest.mark.parametrize( "created, closed, allow_below", [
    ( 209, 184, 1.10 ), ( 209, 183, 1.10 ), (  55,  40, 1.10 ), ( 110,  90, 1.10 ),
    (  99,  80, 1.10 ), ( 132, 100, 1.10 ), (  14,   3, 1.00 ), (  10,   2, 1.00 ),
    (  75,  50, 1.50 ), (  90,  70, 0.90 ),
] )
def test_the_rendered_count_matches_a_source_the_gate_cannot_move( created, closed, allow_below ):
    """
    🔴 THE ARM THAT IS NOT A TAUTOLOGY. Side A is the number in the string the caller reads.
    The expected value comes from the hand-written table, cross-checked by the rational
    oracle. Neither is derived from `ratio_gate_advisory`, so the two sides of this `==`
    have DIFFERENT PROVENANCE and it can genuinely fail.
    """
    assert prescribed_target( created, closed, allow_below ) == EXPECTED_TARGET[ ( created, allow_below ) ]


def test_feeding_side_B_a_number_side_A_did_not_produce_kills_the_test():
    """
    🔴 maria's PROOF ARM, implemented as she specified it: feed side B a number side A did
    not produce, and the promise must DIE. If it survived, the two sides would be welded
    and every green above would be meaningless.

    Both directions, because a guard that only rejects too-small numbers would pass a fix
    that tells callers to close far more rows than they need:
        target - 1  must REFUSE  (side A was not being too generous)
        target + 1  must ALLOW   (so asserting "refuses" at target+1 would fail) — the
                    promise assertion is therefore sensitive to the exact number, which is
                    what "the sides can disagree" means operationally.
    """
    for created, closed, allow_below in ( ( 209, 184, 1.10 ), ( 55, 40, 1.10 ), ( 14, 3, 1.00 ) ):
        target = prescribed_target( created, closed, allow_below )

        below = rules.ratio_gate_advisory( created=created, closed=target - 1, allow_below=allow_below )
        assert below is not None, (
            f"PROOF ARM FAILED: side B ALLOWS at {target - 1}, a number side A did not "
            f"produce (it said {target}). The sides share a source and every promise arm "
            f"in this file is a tautology."
        )

        above = rules.ratio_gate_advisory( created=created, closed=target + 1, allow_below=allow_below )
        assert above is None, (
            f"PROOF ARM FAILED: side B REFUSES at {target + 1}, past the number side A "
            f"produced ({target}) — the gate is not monotonic in `closed`, and neither "
            f"side of this file means what it says."
        )
