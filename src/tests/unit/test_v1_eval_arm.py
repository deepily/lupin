#!/usr/bin/env python3
"""
Unit coverage for the CJ Flow v1-arm eval client (src/scripts/v1_eval_arm.py),
including the four independent-review fixes (2026-08-15 review, Extra 2 🪨):

  F1 — the cross-arm-comparable latency is CLIENT send → observed completion
       (not RUNNING→COMPLETED, which dropped v1's pre-queue work); server spans
       are informational sub-spans only.
  F2 — routing is scored over MAPPABLE utterances only, the SAME exclusion both
       arms, with the excluded count + corpus share reported (not forced misses).
  F3 — a COLD pass with cache_hit_rate > 0 is a contaminated baseline → the run
       fails loudly (EvalIntegrityError).
  F4 — collect_fn must block until terminal; a non-terminal return is scored as a
       failure (no_completion), never a completion.

Target: 100% lines + branches + functions on the pure surface. Live IO seams
(_default_push_fn / _default_collect_fn / load_v1_class_to_command / __main__)
are pragma'd boundaries.

Venue: :7999-eligible / local — pure + seam-injected (no IO, no server).
"""
import os
import sys

import pytest

_src = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
_scr = os.path.join( _src, "scripts" )
for _p in ( _src, _scr ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

import v1_eval_arm as v1   # noqa: E402

MAP        = { "CalendarAgent": "agent go calendar" }   # mappable command: "agent go calendar"
INELIGIBLE = "agent router go to deep research"          # agentic — not in the map values


# ───────────────────────────────────────────── resolve_command

def test_resolve_command_mapped():
    assert v1.resolve_command( "CalendarAgent", MAP ) == "agent go calendar"

def test_resolve_command_none_and_blank_agent_type():
    assert v1.resolve_command( None, MAP ) is None
    assert v1.resolve_command( "", MAP ) is None

def test_resolve_command_unmapped_class_is_none():
    assert v1.resolve_command( "MysteryAgent", MAP ) is None


# ───────────────────────────────────────────── span_ms_between

def test_span_positive():
    assert v1.span_ms_between( 1.0, 1.5 ) == 500.0

def test_span_missing_endpoint_is_none():
    assert v1.span_ms_between( None, 1.5 ) is None
    assert v1.span_ms_between( 1.0, None ) is None

def test_span_negative_is_none():
    assert v1.span_ms_between( 1.5, 1.0 ) is None


# ───────────────────────────────────────────── _classify_degradation

def test_degradation_named_path():
    assert v1._classify_degradation( { "degradation_path": "router_error" } ) == "router_error"

def test_degradation_error_falls_back_to_agent_error():
    assert v1._classify_degradation( { "error": "boom" } ) == "agent_error"

def test_degradation_clean_and_unknown_name_are_none():
    assert v1._classify_degradation( { "error": None } ) is None
    assert v1._classify_degradation( { "degradation_path": "nope" } ) is None


# ───────────────────────────────────────────── transition parsing

def test_iso_to_epoch_valid_and_invalid():
    import datetime as _dt
    iso      = "2026-08-15T10:00:00+00:00"
    expected = _dt.datetime.fromisoformat( iso ).timestamp()
    assert v1._iso_to_epoch( iso ) == expected
    assert v1._iso_to_epoch( None ) is None
    assert v1._iso_to_epoch( 12345 ) is None
    assert v1._iso_to_epoch( "not-a-date" ) is None

def test_parse_transitions_full_sequence():
    events = [
        { "to_state": "queued",    "timestamp": "2026-08-15T10:00:00+00:00" },
        { "to_state": "running",   "timestamp": "2026-08-15T10:00:01+00:00" },
        { "to_state": "completed", "timestamp": "2026-08-15T10:00:02+00:00",
          "metadata": { "is_cache_hit": True, "agent_type": "CalendarAgent" } },
    ]
    tr = v1.parse_transitions( events )
    assert tr[ "completed_ts" ] - tr[ "running_ts" ] == pytest.approx( 1.0 )
    assert tr[ "metadata" ][ "agent_type" ] == "CalendarAgent"

def test_parse_transitions_failure_leaves_no_completion():
    events = [ { "to_state": "running", "timestamp": "2026-08-15T10:00:01+00:00" },
               { "to_state": "failed",  "timestamp": "2026-08-15T10:00:02+00:00", "metadata": { "error": "x" } } ]
    tr = v1.parse_transitions( events )
    assert tr[ "completed_ts" ] is None and tr[ "metadata" ] is None and tr[ "running_ts" ] is not None

def test_parse_transitions_empty():
    assert v1.parse_transitions( [ ] ) == { "queued_ts": None, "running_ts": None,
                                            "completed_ts": None, "metadata": None }


# ───────────────────────────────────────────── build_class_to_command

class _Math: pass
class _Cal:  pass

def test_build_class_to_command_inverts_mode_map():
    m, amb = v1.build_class_to_command( { "math": _Math, "calendar": _Cal } )
    assert m == { "_Math": "agent router go to math", "_Cal": "agent router go to calendar" } and amb == [ ]

def test_build_class_to_command_ambiguous_class_dropped():
    m, amb = v1.build_class_to_command( { "math": _Math, "maths": _Math } )
    assert "_Math" not in m and amb == [ "_Math" ]

def test_build_class_to_command_same_command_not_ambiguous():
    m, amb = v1.build_class_to_command( { "a": _Math, "b": _Math }, template="fixed" )
    assert m == { "_Math": "fixed" } and amb == [ ]

def test_build_class_to_command_non_class_value_uses_str():
    m, amb = v1.build_class_to_command( { "m": "raw" } )
    assert m == { "raw": "agent router go to m" } and amb == [ ]


# ───────────────────────────────────────────── assemble_v1_record

def _ok_transitions( **meta ):
    md = { "is_cache_hit": True, "agent_type": "CalendarAgent" }
    md.update( meta )
    return { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": 10.25, "metadata": md }

def test_assemble_push_failed_no_job_id():
    r = v1.assemble_v1_record( "u", "agent go calendar", { }, { }, MAP, send_ts=1.0, recv_ts=1.4 )
    assert r.ok is False and r.failure == "push_failed" and r.routing_eligible is True

def test_assemble_push_result_not_a_dict():
    r = v1.assemble_v1_record( "u", "agent go calendar", None, { }, MAP, send_ts=1.0, recv_ts=1.4 )
    assert r.ok is False and r.failure == "push_failed"

def test_assemble_no_completion_missing_metadata():
    tr = { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": 10.2, "metadata": None }
    r  = v1.assemble_v1_record( "u", "agent go calendar", { "job_id": "j1" }, tr, MAP, send_ts=1.0, recv_ts=1.4 )
    assert r.ok is False and r.failure == "no_completion" and r.running_ts == 10.0

def test_assemble_no_completion_missing_completed_ts():
    tr = { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": None, "metadata": { "is_cache_hit": False } }
    r  = v1.assemble_v1_record( "u", "agent go calendar", { "job_id": "j1" }, tr, MAP, send_ts=1.0, recv_ts=1.4 )
    assert r.ok is False and r.failure == "no_completion"

def test_assemble_bad_span_when_client_span_uncomputable():
    # completion observed, but no recv_ts ⇒ client span None ⇒ bad_span
    r = v1.assemble_v1_record( "u", "agent go calendar", { "job_id": "j1" },
                               _ok_transitions(), MAP, send_ts=1.0, recv_ts=None )
    assert r.ok is False and r.failure == "bad_span" and r.client_span_ms is None

def test_assemble_ok_client_span_and_server_subspans():
    r = v1.assemble_v1_record( "u", "agent go calendar", { "job_id": "j1" },
                               _ok_transitions( error="boom" ), MAP, send_ts=1.0, recv_ts=1.4 )
    assert r.ok is True and r.failure is None
    assert r.client_span_ms == pytest.approx( 400.0 )           # F1: recv-send, client clock
    assert r.server_compute_ms == 250.0 and r.server_wall_ms == 750.0   # informational sub-spans
    assert r.actual_command == "agent go calendar" and r.is_cache_hit is True
    assert r.degradation == "agent_error" and r.routing_eligible is True

def test_assemble_ok_ineligible_command_and_unmapped():
    r = v1.assemble_v1_record( "u", INELIGIBLE, { "job_id": "j1" },
                               _ok_transitions( is_cache_hit=0, agent_type="MysteryAgent" ),
                               MAP, send_ts=1.0, recv_ts=1.4 )
    assert r.ok is True and r.is_cache_hit is False
    assert r.actual_command is None and r.routing_eligible is False   # F2: excluded, not a forced miss

def test_assemble_mappable_commands_override():
    # explicit mappable set overrides the map's own values
    r = v1.assemble_v1_record( "u", "custom cmd", { "job_id": "j1" }, _ok_transitions(),
                               MAP, send_ts=1.0, recv_ts=1.4, mappable_commands=[ "custom cmd" ] )
    assert r.routing_eligible is True


# ───────────────────────────────────────────── run_v1_pass

def _counter_clock( start=1.0, step=0.2 ):
    state = { "t": start }
    def _c():
        v = state[ "t" ]; state[ "t" ] = round( v + step, 6 ); return v
    return _c

def test_run_pass_preserves_order_and_collects_on_success():
    collected = []
    def push( u ): return { "job_id": f"job-{u}" }
    def collect( jid ): collected.append( jid ); return _ok_transitions()
    pairs = [ ( "a", "agent go calendar" ), ( "b", "agent go calendar" ) ]
    recs = v1.run_v1_pass( pairs, push_fn=push, collect_fn=collect, class_to_command=MAP,
                           clock=_counter_clock() )
    assert [ r.utterance for r in recs ] == [ "a", "b" ] and collected == [ "job-a", "job-b" ]
    assert all( r.ok and r.client_span_ms is not None for r in recs )

def test_run_pass_push_failure_short_circuits_collect():
    calls = []
    def push( u ): return { "error": "down" }
    def collect( jid ): calls.append( jid ); return { }
    recs = v1.run_v1_pass( [ ( "a", "agent go calendar" ) ], push_fn=push, collect_fn=collect,
                           class_to_command=MAP, clock=_counter_clock() )
    assert calls == [ ] and recs[ 0 ].failure == "push_failed" and recs[ 0 ].recv_ts is None

def test_run_pass_push_non_dict_short_circuits():
    calls = []
    def push( u ): return None
    def collect( jid ): calls.append( jid ); return { }
    recs = v1.run_v1_pass( [ ( "a", "agent go calendar" ) ], push_fn=push, collect_fn=collect,
                           class_to_command=MAP, clock=_counter_clock() )
    assert calls == [ ] and recs[ 0 ].failure == "push_failed"


# ───────────────────────────────────────────── compute_v1_metrics

def _rec( ok=True, cache=False, client=200.0, compute=100.0, wall=400.0, actual="agent go calendar",
          expected="agent go calendar", eligible=True, degradation=None, failure=None ):
    return v1.V1Record( utterance="u", expected_command=expected, actual_command=actual,
                        is_cache_hit=cache, routing_eligible=eligible,
                        client_span_ms=client if ok else None, server_compute_ms=compute if ok else None,
                        server_wall_ms=wall if ok else None, ok=ok, failure=failure, degradation=degradation )

def test_metrics_full_with_exclusion():
    recs = [
        _rec( cache=True, client=100.0 ),
        _rec( cache=False, client=300.0, actual="wrong command", degradation="router_error" ),
        _rec( expected=INELIGIBLE, eligible=False, actual=None ),   # excluded from routing (F2)
        _rec( ok=False, failure="push_failed", degradation="agent_error" ),
    ]
    m = v1.compute_v1_metrics( recs )
    assert m[ "n" ] == 4 and m[ "ok_n" ] == 3
    assert m[ "routing_eligible_n" ] == 2 and m[ "routing_excluded_n" ] == 1   # only the ineligible-command rec
    assert m[ "routing_excluded_share" ] == 0.25       # 1 of 4 utterances excluded from routing
    assert m[ "routing_accuracy" ] == 0.5              # 1 of 2 eligible routed right
    assert m[ "cache_hit_rate" ] == pytest.approx( 1 / 3, abs=1e-4 )
    assert m[ "client_p50_ms" ] is not None and m[ "server_compute_p50_ms" ] is not None
    assert m[ "server_wall_p50_ms" ] is not None
    assert m[ "degradation_paths_seen" ] == [ "agent_error", "router_error" ]

def test_metrics_empty_rates_are_none_not_zero():
    m = v1.compute_v1_metrics( [ ] )
    assert m[ "failure_rate" ] is None and m[ "routing_accuracy" ] is None
    assert m[ "cache_hit_rate" ] is None and m[ "routing_excluded_share" ] is None
    assert m[ "client_p50_ms" ] is None and m[ "server_compute_p50_ms" ] is None
    assert m[ "spans" ] == [ ] and m[ "degradation_paths_seen" ] == [ ]


# ───────────────────────────────────────────── run_two_pass (F3, F4)

def _warming_seams():
    seen = { }
    def push( u ):
        n = seen.get( u, 0 ); seen[ u ] = n + 1
        return { "job_id": f"{u}#{n}" }
    def collect( jid ):
        return { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": 10.25,
                 "metadata": { "is_cache_hit": jid.endswith( "#1" ), "agent_type": "CalendarAgent" } }
    return push, collect

def test_run_two_pass_cold_empty_then_warm_cache():
    push, collect = _warming_seams()
    res = v1.run_two_pass( [ ( "a", "agent go calendar" ) ], push_fn=push, collect_fn=collect,
                           class_to_command=MAP, clock=_counter_clock() )
    assert res[ "cold" ][ "cache_hit_rate" ] == 0.0 and res[ "warm" ][ "cache_hit_rate" ] == 1.0

def test_run_two_pass_f3_cold_not_cold_raises():
    def push( u ): return { "job_id": "j1" }
    def collect( jid ):                                 # cache hit on the COLD pass ⇒ contaminated
        return { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": 10.25,
                 "metadata": { "is_cache_hit": True, "agent_type": "CalendarAgent" } }
    with pytest.raises( v1.EvalIntegrityError ):
        v1.run_two_pass( [ ( "a", "agent go calendar" ) ], push_fn=push, collect_fn=collect,
                         class_to_command=MAP, clock=_counter_clock() )

def test_run_two_pass_f3_bypass_when_assert_cold_false():
    def push( u ): return { "job_id": "j1" }
    def collect( jid ):
        return { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": 10.25,
                 "metadata": { "is_cache_hit": True, "agent_type": "CalendarAgent" } }
    res = v1.run_two_pass( [ ( "a", "agent go calendar" ) ], push_fn=push, collect_fn=collect,
                           class_to_command=MAP, clock=_counter_clock(), assert_cold=False )
    assert res[ "cold" ][ "cache_hit_rate" ] == 1.0    # contamination surfaced, not raised

def test_f4_non_terminal_collect_return_is_failure_not_completion():
    # collect_fn returns partial transitions (still running: no completed_ts/metadata).
    def push( u ): return { "job_id": "j1" }
    def collect( jid ): return { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": None, "metadata": None }
    recs = v1.run_v1_pass( [ ( "a", "agent go calendar" ) ], push_fn=push, collect_fn=collect,
                           class_to_command=MAP, clock=_counter_clock() )
    assert recs[ 0 ].ok is False and recs[ 0 ].failure == "no_completion"   # never a fabricated completion


# ───────────────────────────────────────────── run_v1_baseline

def test_run_v1_baseline_composes():
    def fake_load( name, limit=None ): return [ ( "a", "agent go calendar" ), ( "b", "agent go calendar" ) ]
    def fake_sample( pairs, n, seed ): return pairs, { "seed": seed, "under_quota": [ ] }
    push, collect = _warming_seams()
    res = v1.run_v1_baseline( seed=7, n_per_command=5, push_fn=push, collect_fn=collect,
                              class_to_command=MAP, clock=_counter_clock(),
                              load_corpus_fn=fake_load, sample_fn=fake_sample )
    assert res[ "cold" ][ "cache_hit_rate" ] == 0.0 and res[ "warm" ][ "cache_hit_rate" ] == 1.0
    assert res[ "manifest" ][ "seed" ] == 7 and res[ "sampled_n" ] == 2
    assert v1.V1_PIN_SHA in res[ "report" ] and "seed       : 7" in res[ "report" ]


# ───────────────────────────────────────────── truncate guard (F3, :8000)

def test_assert_test_db_accepts_test_target():
    assert v1.assert_test_db( "postgresql://u:p@localhost/lupin_db_test" ) is None

def test_assert_test_db_refuses_dev_target():
    with pytest.raises( v1.EvalIntegrityError ):
        v1.assert_test_db( "postgresql://u:p@localhost/lupin_db_dev" )

def test_assert_test_db_accepts_v1baseline_target():
    # the dedicated v1-baseline db is on the allow-list (design constraint A)
    assert v1.assert_test_db( "postgresql://u:p@localhost/lupin_db_v1baseline" ) is None

def test_assert_test_db_refuses_prefix_smuggle():
    # exact db-NAME match: a name that merely CONTAINS an allowed name is refused
    with pytest.raises( v1.EvalIntegrityError ):
        v1.assert_test_db( "postgresql://u:p@localhost/lupin_db_test_shadow" )

def test_assert_test_db_refuses_empty_db_name():
    # an unparented url (trailing slash, no db name) yields "" -> refused
    with pytest.raises( v1.EvalIntegrityError ):
        v1.assert_test_db( "postgresql://u:p@localhost/" )

def test_assert_test_db_refuses_non_string():
    with pytest.raises( v1.EvalIntegrityError ):
        v1.assert_test_db( None )

def test_db_name_strips_query_suffix():
    assert v1._db_name( "postgresql://u:p@h:5432/lupin_db_test?sslmode=require" ) == "lupin_db_test"
    assert v1._db_name( "postgresql://u:p@h:5432/lupin_db_v1baseline" ) == "lupin_db_v1baseline"

def test_db_name_ignores_query_and_fragment_slash():
    # de9c32d0 hole (Cheech): a '/lupin_db_test' smuggled into the query or fragment
    # must NOT become the db name — the PATH (lupin_db_dev) wins.
    assert v1._db_name( "postgresql://u:p@h:5432/lupin_db_dev?options=-c search_path=/lupin_db_test" ) == "lupin_db_dev"
    assert v1._db_name( "postgresql://u:p@h:5432/lupin_db_dev#/lupin_db_test" ) == "lupin_db_dev"

def test_assert_test_db_refuses_query_or_fragment_smuggled_test_name():
    for url in (
        "postgresql://u:p@h:5432/lupin_db_dev?options=-c search_path=/lupin_db_test",
        "postgresql://u:p@h:5432/lupin_db_dev#/lupin_db_test",
    ):
        with pytest.raises( v1.EvalIntegrityError ):
            v1.assert_test_db( url )


# ─────────────────────────────────── measured-sha stamp (root-cause countermeasure)

def test_sha_matches_variants():
    assert v1._sha_matches( "b0735467abcdef", "b0735467" ) is True   # full sha vs short pin
    assert v1._sha_matches( "b0735467", "b0735467" ) is True         # exact
    assert v1._sha_matches( "deadbeef", "b0735467" ) is False        # mismatch
    assert v1._sha_matches( "", "b0735467" ) is False                # empty observed
    assert v1._sha_matches( "b0735467", "" ) is False                # empty expected

def test_assert_measured_sha_accepts_full_and_short():
    assert v1.assert_measured_sha( "b0735467deadbeef" ) == "b0735467deadbeef"
    assert v1.assert_measured_sha( "b0735467" ) == "b0735467"

def test_assert_measured_sha_raises_on_wrong_tree():
    with pytest.raises( v1.EvalIntegrityError ):
        v1.assert_measured_sha( "deadbeef" )

def test_assert_measured_sha_raises_on_non_string_and_empty():
    with pytest.raises( v1.EvalIntegrityError ):
        v1.assert_measured_sha( None )
    with pytest.raises( v1.EvalIntegrityError ):
        v1.assert_measured_sha( "" )

class _FakeEngine:
    def __init__( self, url ): self.url = url

class _FakeConn:
    """A connection whose url and executor are ONE object — no decoupled db_url."""
    def __init__( self, url ):
        self.engine   = _FakeEngine( url )
        self.executed = []
    def execute( self, sql ): self.executed.append( sql )

def test_truncate_snapshots_derives_url_and_runs_on_test_db():
    conn  = _FakeConn( "postgresql://u:p@localhost/lupin_db_test" )
    table = v1.truncate_snapshots( conn )
    assert table == v1.SNAPSHOT_TABLE
    assert conn.executed == [ f"TRUNCATE TABLE {v1.SNAPSHOT_TABLE}" ]

def test_truncate_snapshots_never_executes_on_wrong_db():
    conn = _FakeConn( "postgresql://u:p@localhost/lupin_db_dev" )
    with pytest.raises( v1.EvalIntegrityError ):
        v1.truncate_snapshots( conn )
    assert conn.executed == [ ]               # url derived from the SAME conn; TRUNCATE never fired


# ───────────────────────────────────────────── reporting

def test_report_header_stamps_pin_sha_and_seed():
    h = v1.build_report_header( seed=1024, corpus="simple", n_per_command=60, base_url="http://x" )
    assert v1.V1_PIN_SHA in h and "1024" in h and "CLIENT send" in h

def test_fmt_none_and_value():
    assert v1._fmt( None ) == "<n/a>" and v1._fmt( 12.34 ) == "12.3"

def test_render_report_with_values():
    m = v1.compute_v1_metrics( [ _rec( cache=True, client=100.0 ) ] )
    out = v1.render_v1_report( m, seed=7, corpus="simple", n_per_command=60, base_url="http://x" )
    assert "routing_accuracy      : 100.0%" in out and "client_p50_ms         : 100.0" in out
    assert "server_compute_p50_ms" in out and v1.V1_PIN_SHA in out

def test_render_report_with_none_rates():
    m = v1.compute_v1_metrics( [ ] )
    out = v1.render_v1_report( m, seed=7, corpus="simple", n_per_command=60, base_url="http://x" )
    assert "routing_accuracy      : <n/a>%" in out and "degradation_seen      : (none)" in out
    assert "client_p50_ms         : <n/a>" in out


# ───────────────────────────────────────────── CLI

def test_arg_parser_defaults_and_overrides():
    args = v1.build_arg_parser().parse_args( [ "--seed", "99", "--n-per-command", "30", "--base-url", "http://h" ] )
    assert args.seed == 99 and args.n_per_command == 30 and args.base_url == "http://h"
    assert args.corpus == "simple" and args.limit is None


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
