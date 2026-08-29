"""
The falsifier for the four ERROR rates: a rate the harness CANNOT observe must not
print as 0.0.

Same defect family as row 2ec6ad9c (the cache metrics), one instrument over. The cache
family was narrowed onto `is_outcome_observed`; the four error rates were deliberately
left on the wider `answered` denominator, on the reasoning — stated in
is_outcome_observed's own docstring — that "a waiting response is still a completed
*request*". That is true about the REQUEST and beside the point about the RATE. What
these four rates read is the TERMINAL OUTCOME, and on a waiting row that evidence is
absent rather than negative, so the numerator is structurally 0 while the denominator
is full.

MEASURED on ts-f06f5961 (io/v2-flow/eval-2026-08-25-19-31-31/records.jsonl): 200
answered, **0** outcome-observed, all 200 carrying `payload.status == "waiting"`, and
`reported_route_reason` returning only `args_none` (122) and `unknown_command` (78) —
not one of the four error reasons. All four rates published 0.0.
(An earlier draft of this note said "every status None". That read a TOP-LEVEL `status`
key which does not exist; the field lives in `payload`. Same conclusion, wrong evidence,
so it is corrected rather than left standing.) A reader takes four zeros beside a 200-request
table as "no errors occurred"; it meant "nothing was observable".

⚠️ VERIFIED BOTH WAYS, and the first attempt at this header was wrong. Run against the
pre-fix module 7 of these 10 fail and 3 pass — the rates read 0.0 where they must read None.
The INVARIANT tests are split deliberately: those asserting only PRE-EXISTING keys
(`test_a_fully_observed_pass_is_completely_unchanged`,
`test_routing_and_latency_denominators_were_not_touched`,
`test_the_cache_family_denominator_was_not_touched`) are exactly the 3 that pass on BOTH
versions, which is the only way they can prove the fix moved nothing that was already
correct — that is the "does not affect fully observed runs" requirement, discharged by
execution rather than by assertion. An invariant test
that references a key the old code lacks cannot run against the old code, so it proves
nothing about it — my first draft made exactly that mistake on three of them.
"""

import os
import sys


def _load_module():
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import v2_eval
    return v2_eval


ve = _load_module()

_MATH = "agent router go to math"


def _waiting( utterance="u", route_reason="args_none" ):
    """The async agent path's real shape: enqueued, answered 200, outcome NOT yet observable."""
    return {
        "utterance"        : utterance,
        "expected_command" : _MATH,
        "ok"               : True,
        "status_code"      : 200,
        "payload"          : {
            "path"           : "agent",
            "status"         : ve.STATUS_WAITING,
            "route_reason"   : route_reason,
            "answer"         : None,
            "command"        : _MATH,
            "snapshot_id"    : None,
            "similarity"     : None,
            "wrote_snapshot" : False,
            "cache_hit"      : False,
            "timings_ms"     : { "t_first_useful": 418.4 },
        },
        "client_span_ms"   : 444.8,
    }


def _resolved( utterance="u", route_reason=None ):
    """A row whose work FINISHED — the only kind that can carry an error reason."""
    return {
        "utterance"        : utterance,
        "expected_command" : _MATH,
        "ok"               : True,
        "status_code"      : 200,
        "payload"          : {
            "path"           : "replay",
            "status"         : "done",
            "route_reason"   : route_reason,
            "answer"         : "42",
            "command"        : _MATH,
            "similarity"     : 99.0,
            "wrote_snapshot" : True,
            "cache_hit"      : True,
            "timings_ms"     : { "t_first_useful": 12.0 },
        },
        "client_span_ms"   : 15.0,
    }


_RATE_KEYS = ( "replay_failure_rate", "router_error_rate",
               "extract_error_rate",  "agent_error_rate" )


# ---------------------------------------------------------------------------
# The defect. These FAIL on the pre-fix code, where every rate read 0.0.
# ---------------------------------------------------------------------------
def test_a_pass_where_nothing_resolved_reports_no_error_rate_at_all():
    m = ve.compute_metrics( [ _waiting( f"u{i}" ) for i in range( 100 ) ] )
    for key in _RATE_KEYS:
        assert m[ key ] is None, (
            f"{key} is {m[ key ]!r} over a pass in which NOTHING resolved — a rate computed "
            "from zero observations is a confident zero from a blind instrument"
        )


def test_it_says_the_instrument_was_blind_and_how_many_it_could_not_see():
    m = ve.compute_metrics( [ _waiting( f"u{i}" ) for i in range( 100 ) ] )
    assert m[ "errors_measurable"   ] is False
    assert m[ "errors_observed_n"   ] == 0
    assert m[ "errors_unobserved_n" ] == 100
    # n_answered stays truthful — both denominators are visible to a reader.
    assert m[ "n_answered" ] == 100


def test_the_blind_cell_says_unmeasurable_rather_than_a_number():
    m = ve.compute_metrics( [ _waiting( f"u{i}" ) for i in range( 10 ) ] )
    for key in _RATE_KEYS:
        assert ve._fmt_error_rate( m, key ) == ve.UNMEASURABLE_CELL


def test_a_waiting_row_does_not_dilute_a_real_rate():
    """One resolved replay_error among 99 waiting rows is a rate of 1.0, not 0.01."""
    records = [ _resolved( "u0", ve.ROUTE_REPLAY_ERROR ) ]
    records += [ _waiting( f"u{i}" ) for i in range( 1, 100 ) ]
    m = ve.compute_metrics( records )
    assert m[ "errors_observed_n" ] == 1
    assert m[ "replay_failure_rate" ] == 1.0, (
        "the one row that could be observed WAS a replay failure; diluting it by 99 rows "
        "that reported nothing turns a 100%-of-what-we-saw failure into a 1% footnote"
    )


def test_the_cell_carries_the_denominator_so_a_sliver_cannot_pass_for_a_verdict():
    records = [ _resolved( "u0", ve.ROUTE_REPLAY_ERROR ) ]
    records += [ _waiting( f"u{i}" ) for i in range( 1, 100 ) ]
    m = ve.compute_metrics( records )
    assert ve._fmt_error_rate( m, "replay_failure_rate" ) == "1.0 (n=1)"


# ---------------------------------------------------------------------------
# The invariants. These pass BOTH ways on purpose — they prove the fix did not
# buy its honesty by moving a denominator that was already correct.
# ---------------------------------------------------------------------------
def test_a_fully_observed_pass_is_completely_unchanged():
    """
    When every answered row resolved, the new denominator IS the old one.

    PRE-EXISTING KEYS ONLY, on purpose — this must run against the pre-fix module too, or
    it cannot testify that the numbers there are unchanged. Verified: passes both ways.
    """
    records = [ _resolved( f"u{i}", ve.ROUTE_AGENT_ERROR if i < 5 else None )
                for i in range( 100 ) ]
    m = ve.compute_metrics( records )
    assert m[ "n_answered" ] == 100
    assert m[ "agent_error_rate" ] == 0.05        # 5/100, exactly as before the change
    assert m[ "replay_failure_rate" ] == 0.0      # a REAL zero: 100 rows looked at, none failed


def test_the_new_fields_describe_that_same_fully_observed_pass( ):
    """The new-key half of the invariant above. Post-fix only, by construction."""
    records = [ _resolved( f"u{i}", ve.ROUTE_AGENT_ERROR if i < 5 else None )
                for i in range( 100 ) ]
    m = ve.compute_metrics( records )
    assert m[ "errors_observed_n" ] == m[ "n_answered" ] == 100
    assert m[ "errors_measurable" ] is True
    assert m[ "errors_unobserved_n" ] == 0


def test_a_real_zero_and_a_blind_zero_are_now_distinguishable():
    """The whole point: both used to print 0.0."""
    looked = ve.compute_metrics( [ _resolved( f"u{i}" ) for i in range( 50 ) ] )
    blind  = ve.compute_metrics( [ _waiting(  f"u{i}" ) for i in range( 50 ) ] )
    assert looked[ "agent_error_rate" ] == 0.0 and looked[ "errors_measurable" ] is True
    assert blind[  "agent_error_rate" ] is None and blind[  "errors_measurable" ] is False
    assert ve._fmt_error_rate( looked, "agent_error_rate" ) == "0.0 (n=50)"
    assert ve._fmt_error_rate( blind,  "agent_error_rate" ) == ve.UNMEASURABLE_CELL


def test_the_cache_family_denominator_was_not_touched():
    """This fix must not move the metric family row 2ec6ad9c already fixed."""
    records = [ _resolved( f"u{i}" ) for i in range( 40 ) ]
    records += [ _waiting( f"w{i}" ) for i in range( 60 ) ]
    m = ve.compute_metrics( records )
    assert m[ "cache_observed_n"   ] == 40
    assert m[ "cache_unobserved_n" ] == 60
    assert m[ "cache_measurable"   ] is True


def test_routing_and_latency_denominators_were_not_touched():
    """is_outcome_observed's docstring warns that narrowing `ok` shrinks these silently."""
    records = [ _resolved( f"u{i}" ) for i in range( 30 ) ]
    records += [ _waiting( f"w{i}" ) for i in range( 70 ) ]
    m = ve.compute_metrics( records )
    assert m[ "n" ] == 100
    assert m[ "n_ok" ] == 100, "every row here is a completed REQUEST; `ok` must not move"
    assert m[ "routing_eligible_n" ] == 100


# ---------------------------------------------------------------------------
# THE PARTIAL CASE — the one that discriminates.
#
# A fully-blind pass and a fully-observed pass are the easy ends: the first must say
# "unmeasurable", the second must not move at all. Neither tells you the fix picked the
# RIGHT denominator, because on those two the wrong choice is either obviously broken or
# invisible. Only a partially-observed pass separates them — there the two candidate
# denominators give materially different numbers, and the test can say which one is
# published. (Mr Radio's flag, 2026-08-25.)
# ---------------------------------------------------------------------------
def test_partial_pass_scores_over_observed_not_over_answered():
    """20 resolved (4 replay errors) + 80 waiting. Over observed: 0.2. Over answered: 0.04."""
    records  = [ _resolved( f"r{i}", ve.ROUTE_REPLAY_ERROR ) for i in range( 4 ) ]
    records += [ _resolved( f"r{i}" ) for i in range( 4, 20 ) ]
    records += [ _waiting(  f"w{i}" ) for i in range( 80 ) ]
    m = ve.compute_metrics( records )

    assert m[ "errors_observed_n"   ] == 20
    assert m[ "errors_unobserved_n" ] == 80
    assert m[ "n_answered"          ] == 100, "the wider count stays published, not replaced"

    assert m[ "replay_failure_rate" ] == 0.2, (
        "4 of the 20 rows that could be looked at were replay failures. Scoring over all "
        "100 answered gives 0.04 — a fivefold understatement produced entirely by rows "
        "that reported nothing"
    )
    # State the rejected number explicitly so a future edit that reverts the denominator
    # fails HERE, naming what it did, rather than silently reading 0.04.
    assert m[ "replay_failure_rate" ] != round( 4 / 100, 4 )


def test_partial_pass_cell_shows_the_sliver_it_rests_on():
    records  = [ _resolved( f"r{i}", ve.ROUTE_REPLAY_ERROR ) for i in range( 4 ) ]
    records += [ _resolved( f"r{i}" ) for i in range( 4, 20 ) ]
    records += [ _waiting(  f"w{i}" ) for i in range( 80 ) ]
    m = ve.compute_metrics( records )
    assert ve._fmt_error_rate( m, "replay_failure_rate" ) == "0.2 (n=20)", (
        "a reader seeing 0.2 beside a 100-request table must be told it rests on 20"
    )


def test_partial_pass_keeps_the_four_rates_independent():
    """Two different error kinds in one partial pass — each over the same observed set."""
    records  = [ _resolved( f"a{i}", ve.ROUTE_AGENT_ERROR  ) for i in range( 3 ) ]
    records += [ _resolved( f"x{i}", ve.ROUTE_EXTRACT_ERROR ) for i in range( 1 ) ]
    records += [ _resolved( f"r{i}" ) for i in range( 6 ) ]
    records += [ _waiting(  f"w{i}" ) for i in range( 90 ) ]
    m = ve.compute_metrics( records )
    assert m[ "errors_observed_n"  ] == 10
    assert m[ "agent_error_rate"   ] == 0.3
    assert m[ "extract_error_rate" ] == 0.1
    assert m[ "router_error_rate"  ] == 0.0   # looked at 10, found none — a REAL zero
    assert m[ "replay_failure_rate" ] == 0.0
    assert m[ "errors_measurable"  ] is True


def test_a_single_observed_row_is_measurable_but_says_so():
    """The boundary: one observed row is evidence, and the cell must not hide how thin."""
    records  = [ _resolved( "r0", ve.ROUTE_AGENT_ERROR ) ]
    records += [ _waiting( f"w{i}" ) for i in range( 99 ) ]
    m = ve.compute_metrics( records )
    assert m[ "errors_measurable" ] is True
    assert m[ "agent_error_rate" ] == 1.0
    assert ve._fmt_error_rate( m, "agent_error_rate" ) == "1.0 (n=1)"
