"""
The banner must name the count for the family whose cell sits under it.

RESIDUAL OF ROW e7aa19bf, found while verifying that pin rather than while building it.
`errors_unobserved_n` was computed (v2_eval.py:800) and published (:887) and then NEVER
RENDERED — it appeared in no path of `render_report`. The banner and the "responses not
observed" table row both read `cache_unobserved_n`, while the four error-rate cells sat
directly beneath them.

THE TWO FAMILIES DO NOT COUNT OVER THE SAME BASE SET:

    cache  observed out of `ok`        [ r for r in records if r["ok"] ]
    errors observed out of `answered`  [ r for r in records if r["status_code"] == 200 ]

On a run where every HTTP success is a 200 and every 200 is an HTTP success those sets
coincide and the wrong count happens to be the right number — which is precisely why this
went unnoticed. They are not the same set by construction, and a number that is correct
about one family being read as a statement about another is the same defect class the
tenth pin exists for.

⚠️ SCOPE, stated because the neighbouring row 2ebe4ccb is the argument for stating it: these
fixtures prove HOW THE REPORT RENDERS a given records shape. They do NOT claim a live run
produces a diverging shape — that would be a claim about producers and a fixture cannot
carry it. The divergence here is constructed deliberately to force the two derivations
apart so the rendering can be told which one it used.
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


def _waiting():
    """Answered 200, HTTP-ok, outcome not yet observable — in BOTH base sets."""
    return {
        "utterance" : "u", "expected_command" : _MATH,
        "ok" : True, "status_code" : 200,
        "payload" : {
            "path" : "agent", "status" : ve.STATUS_WAITING, "route_reason" : "args_none",
            "answer" : None, "command" : _MATH, "snapshot_id" : None, "similarity" : None,
            "wrote_snapshot" : False, "cache_hit" : False,
            "timings_ms" : { "t_first_useful" : 418.4 },
        },
        "client_span_ms" : 444.8,
    }


def _resolved():
    """Work finished — observed in both families."""
    return {
        "utterance" : "u", "expected_command" : _MATH,
        "ok" : True, "status_code" : 200,
        "payload" : {
            "path" : "replay", "status" : "done", "route_reason" : None,
            "answer" : "42", "command" : _MATH, "similarity" : 99.0,
            "wrote_snapshot" : True, "cache_hit" : True,
            "timings_ms" : { "t_first_useful" : 12.0 },
        },
        "client_span_ms" : 15.0,
    }


def _ok_but_not_answered():
    """
    THE DIVERGENCE. HTTP-ok so it enters the CACHE base set, but not a 200 so it never
    enters the ERRORS base set. One such row makes the two unobserved counts differ.
    """
    return {
        "utterance" : "u", "expected_command" : _MATH,
        "ok" : True, "status_code" : 503,
        "payload" : {
            "path" : "agent", "status" : ve.STATUS_WAITING, "route_reason" : "args_none",
            "answer" : None, "command" : _MATH, "snapshot_id" : None, "similarity" : None,
            "wrote_snapshot" : False, "cache_hit" : False,
            "timings_ms" : { "t_first_useful" : 9.0 },
        },
        "client_span_ms" : 11.0,
    }


def _report( records ):
    m = ve.compute_metrics( records )
    return m, ve.render_report(
        m, m, ve.threshold_table( records ),
        { "p50_delta_ms" : None, "p95_delta_ms" : None },
        "simple", "2026-08-25", 1024, 5,
    )


class TestTheTwoDerivationsArePinnedApart:

    def test_the_counts_actually_differ_on_a_diverging_shape( self ):
        # The instrument before the reading: if these were equal the rendering test
        # below would pass for the wrong reason.
        m, _ = _report( [ _waiting(), _waiting(), _ok_but_not_answered() ] )
        assert m[ "cache_unobserved_n" ]  == 3
        assert m[ "errors_unobserved_n" ] == 2
        assert m[ "cache_unobserved_n" ] != m[ "errors_unobserved_n" ]

    def test_the_banner_carries_BOTH_counts_not_just_the_cache_one( self ):
        _, report = _report( [ _waiting(), _waiting(), _ok_but_not_answered() ] )
        assert "3 of 3 HTTP-successful responses not observed" in report
        assert "2 of 2 answered (200) responses not observed" in report

    def test_each_clause_names_the_family_it_speaks_for( self ):
        _, report = _report( [ _waiting(), _ok_but_not_answered() ] )
        assert "cold cache:"  in report
        assert "cold errors:" in report

    def test_the_error_count_is_no_longer_absent_from_the_report( self ):
        # The residual itself: pre-fix, errors_unobserved_n appeared in NO render path.
        m, report = _report( [ _waiting(), _waiting(), _ok_but_not_answered() ] )
        assert str( m[ "errors_unobserved_n" ] ) in report


class TestNothingElseMoved:

    def test_a_fully_observed_pass_emits_no_unobserved_clause_at_all( self ):
        # ⚠️ Assert on the CLAUSE, not on the words "not observed" — the metric table
        # carries a permanent row LABEL ("responses not observed (still waiting)")
        # whatever the count is. My first draft asserted the substring and failed here
        # for that reason: the label was doing the matching, not a banner clause.
        _, report = _report( [ _resolved(), _resolved() ] )
        assert "cold cache:"  not in report
        assert "cold errors:" not in report
        assert "warm cache:"  not in report
        assert "warm errors:" not in report

    def test_coinciding_base_sets_still_report_both_families( self ):
        # The common case: no diverging row, so the counts agree. Both clauses are still
        # emitted — the reader is told each family's denominator rather than being left
        # to assume they are the same set.
        m, report = _report( [ _waiting(), _waiting() ] )
        assert m[ "cache_unobserved_n" ] == m[ "errors_unobserved_n" ] == 2
        assert "cold cache:"  in report
        assert "cold errors:" in report
