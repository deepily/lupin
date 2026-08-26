"""
The falsifier for row 2ec6ad9c: a cache metric the harness CANNOT observe must not
print as 0.0.

MEASURED 2026-08-25 (io/v2-flow/eval-2026-08-25-16-53-36/records.jsonl): every one of
the 200 responses came back `status="waiting"` — the v2 agent path enqueues and returns,
so the answer lands later. `wrote_snapshot` is False and `similarity` is None on all 200
records because nothing had finished, NOT because the cache missed. The harness reported
cache_hit_rate 0.0, cache_candidate_rate 0.0, and a §6a table of zeros at every floor.

The 2026-08-21 run over the same corpus on the same harness carried `status="done"` on
291 of 300 responses with replay firing 83 times and similarity present on 158 — which
is why this is an instrument regression rather than a property of the corpus.

⚠️ EVERY TEST HERE THAT MATTERS FAILS ON THE PRE-FIX CODE. That is the point: a test
that passes before the change is not a test of the change. The negative-control and
denominator-invariant tests pass both ways ON PURPOSE — they are what proves the fix
did not buy its honesty by moving somebody else's denominator.
"""

import os
import sys

import pytest


def _load_module():
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import v2_eval
    return v2_eval


ve = _load_module()

_MATH = "agent router go to math"


def _waiting( utterance="u", path="agent", command=_MATH, expected=_MATH ):
    """A record shaped exactly like the async agent path's real response: enqueued, unanswered."""
    return {
        "utterance"        : utterance,
        "expected_command" : expected,
        "ok"               : True,
        "status_code"      : 200,
        "payload"          : {
            "path"           : path,
            "status"         : "waiting",
            "route_reason"   : "args_none",
            "answer"         : None,
            "command"        : command,
            "snapshot_id"    : None,
            "similarity"     : None,
            "wrote_snapshot" : False,
            "cache_hit"      : False,
            "timings_ms"     : { "t_first_useful": 418.4 },
        },
        "client_span_ms"   : 444.8,
    }


def _done( utterance="u", path="replay", similarity=99.0, command=_MATH, expected=_MATH ):
    """A record from the SYNCHRONOUS era — the work finished before the harness moved on."""
    return {
        "utterance"        : utterance,
        "expected_command" : expected,
        "ok"               : True,
        "status_code"      : 200,
        "payload"          : {
            "path"           : path,
            "status"         : "done",
            "answer"         : "42",
            "command"        : command,
            "similarity"     : similarity,
            "wrote_snapshot" : True,
            "cache_hit"      : path == "replay",
            "timings_ms"     : { "t_first_useful": 12.0 },
        },
        "client_span_ms"   : 20.0,
    }


# ---------------------------------------------------------------------------
# THE FALSIFIER — red on the pre-fix code
# ---------------------------------------------------------------------------
def test_cache_rates_are_unmeasurable_when_every_response_is_still_waiting():
    """0.0 meant 'never hit'. On an all-waiting pass it must mean 'could not see'."""
    records = [ _waiting( utterance=f"u{i}" ) for i in range( 5 ) ]
    m       = ve.compute_metrics( records )

    assert m[ "cache_measurable" ]     is False
    assert m[ "cache_hit_rate" ]       is None      # was 0.0
    assert m[ "cache_candidate_rate" ] is None      # was 0.0
    assert m[ "cache_observed_n" ]   == 0
    assert m[ "cache_unobserved_n" ] == 5


def test_threshold_table_is_unmeasurable_when_every_response_is_still_waiting():
    """§6a printed 0.0 at every floor, which reads as a decisive threshold finding. It is not one."""
    records = [ _waiting( utterance=f"u{i}" ) for i in range( 5 ) ]
    table   = ve.threshold_table( records )

    assert len( table ) == len( ve.THRESHOLD_FLOORS )
    for row in table:
        assert row[ "hit_rate" ] is None, f"floor {row['floor']} still reports {row['hit_rate']}"
        assert row[ "measurable" ] is False


def test_report_says_unmeasurable_and_never_prints_a_zero_cache_cell():
    """A reader must be unable to mistake the cell for a measurement."""
    records = [ _waiting( utterance=f"u{i}" ) for i in range( 5 ) ]
    m       = ve.compute_metrics( records )
    report  = ve.render_report(
        m, m, ve.threshold_table( records ),
        { "p50_delta_ms": None, "p95_delta_ms": None },
        "simple", "2026-08-25", 1024, 5,
    )

    assert ve.UNMEASURABLE_CELL in report
    # The two cache rate rows must carry no numeric cell at all.
    for label in ( "cache-hit rate", "cache-candidate rate" ):
        row = next( line for line in report.splitlines() if line.startswith( f"| {label} |" ) )
        assert "0.0" not in row, row
        assert row.count( ve.UNMEASURABLE_CELL ) == 2, row
    # §6a must not render a table of zeros.
    assert "| 100.0 | 0.0 |" not in report
    assert "not observed" in report


def test_report_names_how_many_responses_were_not_observed():
    """'Unmeasurable' without a count is a shrug; the reader needs the size of the hole."""
    records = [ _waiting( utterance=f"u{i}" ) for i in range( 5 ) ]
    m       = ve.compute_metrics( records )
    report  = ve.render_report(
        m, m, ve.threshold_table( records ),
        { "p50_delta_ms": None, "p95_delta_ms": None },
        "simple", "2026-08-25", 1024, 5,
    )
    assert "5 of 5" in report
    assert 'status "waiting"' in report


# ---------------------------------------------------------------------------
# THE DENOMINATOR INVARIANT — this is what the rejected fix would have broken
# ---------------------------------------------------------------------------
def test_waiting_does_not_move_any_other_denominator():
    """
    The obvious fix — making is_completed_ok reject "waiting" — flips every request to
    not-ok and silently shrinks the denominator under routing, latency and the error
    rates. This asserts that did NOT happen: only the cache family is allowed to move.
    """
    records = [ _waiting( utterance=f"u{i}" ) for i in range( 5 ) ]
    m       = ve.compute_metrics( records )

    assert m[ "n" ]                   == 5
    assert m[ "n_ok" ]                == 5     # unchanged: the server answered and reported no error
    assert m[ "n_incomplete" ]        == 0
    assert m[ "n_http_error" ]        == 0
    assert m[ "n_answered" ]          == 5
    assert m[ "routing_eligible_n" ]  == 5     # the rejected fix drops this to 0
    assert m[ "routing_accuracy" ]    == 1.0
    assert m[ "p50_first_useful_ms" ] == 418.4
    assert m[ "client_p50_ms" ]       == 444.8
    # ⚠️ THESE FOUR CHANGED FROM 0.0 TO None (row 647f3733 follow-up, 2026-08-25), and the
    # line they replace carried a claim the data does not support. It read:
    #     assert m[ "replay_failure_rate" ] == 0.0  # honest: replay is attempted synchronously
    # If replay really were attempted synchronously before the enqueue, a waiting row could
    # carry replay_error and the rate would be honest. MEASURED across all 12
    # io/v2-flow/eval-*/records.jsonl files — 300 rows carrying one of the four error
    # reasons — the pairing is:
    #     replay_error  done 163 · failed  99
    #     agent_error   done  13 · failed  25
    #     waiting: ZERO, for all four reasons
    # Not one error reason has ever been observed on a waiting row. So on an all-waiting
    # pass the numerator is structurally 0 and a 0.0 is a confident zero from a blind
    # instrument — the identical defect this file was written to kill, one metric family
    # over. `None` renders "unmeasurable"; see test_v2_eval_unobserved_error_rates.py.
    #
    # WHAT THIS TEST STILL GUARDS IS UNCHANGED: every assertion above this comment — n,
    # n_ok, n_incomplete, n_answered, routing_eligible_n, routing_accuracy and both latency
    # numbers — is untouched. Only the error family moved, and only onto the observation
    # predicate the cache family already uses.
    assert m[ "replay_failure_rate" ] is None
    assert m[ "router_error_rate" ]   is None
    assert m[ "extract_error_rate" ]  is None
    assert m[ "agent_error_rate" ]    is None


def test_cache_excluded_n_still_counts_the_command_rule_not_the_observation_gap():
    """The two exclusions answer different questions and must be reported separately."""
    records = [ _waiting( utterance=f"u{i}" ) for i in range( 3 ) ] + [
        _waiting( utterance="w", command="agent router go to weather",
                  expected="agent router go to weather" ),
    ]
    m = ve.compute_metrics( records )
    assert m[ "cache_excluded_n" ]   == 1   # weather is not snapshotable — a command-rule exclusion
    assert m[ "cache_unobserved_n" ] == 4   # all four were unobserved — a different fact


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL — a synchronous pass must still report real numbers
# ---------------------------------------------------------------------------
def test_synchronous_pass_still_reports_a_real_cache_hit_rate():
    """If the fix fired on observed data it would erase the metric it exists to protect."""
    records = [
        _done( utterance="a", path="replay",       similarity=99.0 ),
        _done( utterance="b", path="replay",       similarity=97.0 ),
        _done( utterance="c", path="agent",        similarity=None ),
        _done( utterance="d", path="receptionist", similarity=None,
               command="agent router go to receptionist" ),
    ]
    m = ve.compute_metrics( records )

    assert m[ "cache_measurable" ]      is True
    assert m[ "cache_observed_n" ]     == 4
    assert m[ "cache_unobserved_n" ]   == 0
    assert m[ "cache_hit_rate" ]       == 0.5
    assert m[ "cache_candidate_rate" ] == 0.5
    table = { row[ "floor" ]: row[ "hit_rate" ] for row in ve.threshold_table( records ) }
    assert table[ 98.0 ] == 0.25
    assert table[ 95.0 ] == 0.5


def test_a_mixed_pass_measures_over_the_observed_rows_only():
    """Partial observation is measurable — over what was observed, and the gap is published."""
    records = [
        _done( utterance="a", path="replay", similarity=99.0 ),
        _done( utterance="b", path="agent",  similarity=None ),
        _waiting( utterance="c" ),
        _waiting( utterance="d" ),
    ]
    m = ve.compute_metrics( records )

    assert m[ "cache_measurable" ]      is True
    assert m[ "cache_observed_n" ]     == 2
    assert m[ "cache_unobserved_n" ]   == 2
    assert m[ "cache_hit_rate" ]       == 0.5    # 1 replay over the 2 OBSERVED cacheable rows
    assert m[ "cache_candidate_rate" ] == 0.5


def test_report_warns_when_only_some_responses_were_observed():
    records = [ _done( utterance="a", path="replay", similarity=99.0 ), _waiting( utterance="c" ) ]
    m       = ve.compute_metrics( records )
    report  = ve.render_report(
        m, m, ve.threshold_table( records ),
        { "p50_delta_ms": None, "p95_delta_ms": None },
        "simple", "2026-08-25", 1024, 2,
    )
    assert "1 of 2" in report
    # Partial observation is still a MEASUREMENT: the cells carry numbers, and only the
    # banner mentions the word. (The banner explains the rule; it is not a verdict here.)
    for label in ( "cache-hit rate", "cache-candidate rate" ):
        row = next( line for line in report.splitlines() if line.startswith( f"| {label} |" ) )
        assert ve.UNMEASURABLE_CELL not in row, row
    assert "| 100.0 |" in report   # the §6a table is printed, not refused


# ---------------------------------------------------------------------------
# is_outcome_observed — the predicate itself, over the flow's whole vocabulary
# ---------------------------------------------------------------------------
@pytest.mark.parametrize( "status", [ "done", "failed", "needs_input", "expired", "parked", "rejected" ] )
def test_every_terminal_status_the_flow_emits_counts_as_observed( status ):
    record = _waiting()
    record[ "payload" ][ "status" ] = status
    assert ve.is_outcome_observed( record ) is True


def test_waiting_is_the_only_deferred_status():
    assert ve.DEFERRED_STATUSES == frozenset( { "waiting" } )
    assert ve.is_outcome_observed( _waiting() ) is False


def test_a_payload_with_no_status_is_treated_as_observed():
    """Pre-contract records (and every existing unit fixture) carry no status field."""
    record = _waiting()
    del record[ "payload" ][ "status" ]
    assert ve.is_outcome_observed( record ) is True


def test_a_non_200_is_never_observed():
    record = _waiting()
    record[ "status_code" ] = 500
    record[ "ok" ]          = False
    assert ve.is_outcome_observed( record ) is False


def test_an_unparseable_payload_is_never_observed():
    record = _waiting()
    record[ "payload" ] = "not a dict"
    assert ve.is_outcome_observed( record ) is False


def test_response_status_reads_the_contract_field():
    assert ve.response_status( _waiting() ) == "waiting"
    assert ve.response_status( _done() )    == "done"


# ---------------------------------------------------------------------------
# THE REAL-RECORDS CASE — found by running the fix against the actual run,
# not by reasoning about it. eval-2026-08-25-16-53-36 has exactly ONE observed
# response per pass (a needs_input, which DOES reach the cache: the lookup runs
# at flow.py:210 and the args refusal at flow.py:285) and it carries no
# similarity. An observed-only gate called that "measurable" and printed 0.0 at
# all four floors off a denominator of 1 — the same false clean, one row wide.
# ---------------------------------------------------------------------------
def _needs_input( utterance="ni" ):
    record = _waiting( utterance=utterance, path="needs_input" )
    record[ "payload" ][ "status" ]       = "needs_input"
    record[ "payload" ][ "route_reason" ] = "args_incomplete"
    return record


def _real_shape():
    """99 enqueued-and-unanswered rows plus the single needs_input the real run observed."""
    return [ _waiting( utterance=f"u{i}" ) for i in range( 99 ) ] + [ _needs_input() ]


def test_one_observed_row_with_no_score_does_not_make_the_floor_sweep_measurable():
    table = ve.threshold_table( _real_shape() )
    for row in table:
        assert row[ "measurable" ] is False, row
    m = ve.compute_metrics( _real_shape() )
    assert m[ "cache_observed_n" ] == 1
    assert m[ "cache_scored_n" ]   == 0


def test_the_real_run_shape_never_prints_a_table_of_zeros():
    records = _real_shape()
    m       = ve.compute_metrics( records )
    report  = ve.render_report(
        m, m, ve.threshold_table( records ),
        { "p50_delta_ms": None, "p95_delta_ms": None },
        "simple", "2026-08-25-16-53-36", 1024, 20,
    )
    assert "| 100.0 | 0.0 | 0 | 0 |" not in report
    assert "| 90.0 | 0.0 | 0 | 0 |"  not in report
    assert "no table is printed for this run" in report
    assert "99 of 100" in report


def test_a_measurable_cache_cell_carries_its_own_denominator():
    """0.0 over one observed row must not read as a verdict on a hundred."""
    records = _real_shape()
    m       = ve.compute_metrics( records )
    report  = ve.render_report(
        m, m, ve.threshold_table( records ),
        { "p50_delta_ms": None, "p95_delta_ms": None },
        "simple", "2026-08-25-16-53-36", 1024, 20,
    )
    hit_row = next( line for line in report.splitlines() if line.startswith( "| cache-hit rate |" ) )
    assert "(n=1)" in hit_row, hit_row
    assert "| 0.0 |" not in hit_row, hit_row


def test_a_scored_pass_still_sweeps_the_floors():
    """Negative control for the score gate: one real similarity is enough to sweep."""
    records = [ _done( utterance="a", path="replay", similarity=99.0 ) ] + [ _needs_input() ]
    table   = { row[ "floor" ]: row for row in ve.threshold_table( records ) }
    assert all( row[ "measurable" ] for row in table.values() )
    assert table[ 98.0 ][ "hit_rate" ] == 0.5
    assert table[ 100.0 ][ "hit_rate" ] == 0.0
