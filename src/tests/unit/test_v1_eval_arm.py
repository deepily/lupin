#!/usr/bin/env python3
"""
Unit coverage for the CJ Flow v1-arm eval client (src/scripts/v1_eval_arm.py).

Proves the pure record-assembly + metric tree with fakes and NO server: the
push-failed / no-completion / bad-span / ok paths, the routing-command map seam
(unmapped class ⇒ miss, never a fabricated hit), the queue-dwell-excluding span,
and the metric rates that go None (not 0.0) when their denominator is empty.

Target: 100% lines + branches + functions on the pure surface. The live IO seams
(_default_push_fn, __main__) are pragma'd no-cover boundaries.

Venue: :7999-eligible / local — pure + seam-injected (no IO, no server).
"""
import os
import sys

import pytest

# Bootstrap: src + src/scripts on path (same convention as test_v2_eval).
_src = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
_scr = os.path.join( _src, "scripts" )
for _p in ( _src, _scr ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

import v1_eval_arm as v1   # noqa: E402


# ───────────────────────────────────────────── resolve_command

def test_resolve_command_mapped():
    assert v1.resolve_command( "CalendarAgent", { "CalendarAgent": "agent go calendar" } ) == "agent go calendar"

def test_resolve_command_none_agent_type():
    assert v1.resolve_command( None, { "X": "y" } ) is None
    assert v1.resolve_command( "", { "X": "y" } ) is None          # blank ⇒ None

def test_resolve_command_unmapped_class_is_none():
    assert v1.resolve_command( "UnknownAgent", { "CalendarAgent": "c" } ) is None   # miss, not fabricated


# ───────────────────────────────────────────── span_ms_between

def test_span_positive():
    assert v1.span_ms_between( 100.0, 100.5 ) == 500.0

def test_span_missing_endpoint_is_none():
    assert v1.span_ms_between( None, 100.5 ) is None
    assert v1.span_ms_between( 100.0, None ) is None

def test_span_negative_is_none():
    assert v1.span_ms_between( 100.5, 100.0 ) is None              # out of order ⇒ corrupt, not a measurement


# ───────────────────────────────────────────── _classify_degradation

def test_degradation_named_path():
    assert v1._classify_degradation( { "degradation_path": "router_error" } ) == "router_error"

def test_degradation_error_falls_back_to_agent_error():
    assert v1._classify_degradation( { "error": "boom" } ) == "agent_error"

def test_degradation_clean_is_none():
    assert v1._classify_degradation( { "error": None } ) is None
    assert v1._classify_degradation( { "degradation_path": "not_a_real_path" } ) is None   # unknown name ⇒ None


# ───────────────────────────────────────────── assemble_v1_record

def _ok_transitions( **meta ):
    md = { "is_cache_hit": True, "agent_type": "CalendarAgent" }
    md.update( meta )
    # queued 9.5 → running 10.0 → completed 10.25:
    #   compute span = 250ms (running→completed), wall-clock = 750ms (queued→completed)
    return { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": 10.25, "metadata": md }

MAP = { "CalendarAgent": "agent go calendar" }

def test_assemble_push_failed_no_job_id():
    r = v1.assemble_v1_record( "u", "agent go calendar", { }, { }, MAP )
    assert r.ok is False and r.failure == "push_failed" and r.job_id is None

def test_assemble_push_result_not_a_dict():
    r = v1.assemble_v1_record( "u", "c", None, { }, MAP )               # non-dict push_result
    assert r.ok is False and r.failure == "push_failed"

def test_assemble_no_completion_missing_metadata():
    tr = { "running_ts": 10.0, "completed_ts": 10.2, "metadata": None }
    r  = v1.assemble_v1_record( "u", "c", { "job_id": "j1" }, tr, MAP )
    assert r.ok is False and r.failure == "no_completion" and r.running_ts == 10.0

def test_assemble_no_completion_missing_completed_ts():
    tr = { "running_ts": 10.0, "completed_ts": None, "metadata": { "is_cache_hit": False } }
    r  = v1.assemble_v1_record( "u", "c", { "job_id": "j1" }, tr, MAP )
    assert r.ok is False and r.failure == "no_completion"

def test_assemble_bad_span_out_of_order():
    tr = { "running_ts": 10.5, "completed_ts": 10.0, "metadata": { "agent_type": "CalendarAgent" } }
    r  = v1.assemble_v1_record( "u", "agent go calendar", { "job_id": "j1" }, tr, MAP )
    assert r.ok is False and r.failure == "bad_span" and r.span_ms is None

def test_assemble_ok_records_command_cachehit_span_degradation():
    r = v1.assemble_v1_record( "u", "agent go calendar", { "job_id": "j1" },
                               _ok_transitions( error="boom" ), MAP )
    assert r.ok is True and r.failure is None
    assert r.actual_command == "agent go calendar" and r.is_cache_hit is True
    assert r.span_ms == 250.0 and r.degradation == "agent_error"
    assert r.wall_clock_ms == 750.0                 # queued→completed, dwell included

def test_assemble_ok_without_queued_ts_has_no_wall_clock():
    tr = _ok_transitions()
    tr.pop( "queued_ts" )                            # dwell anchor not observed
    r  = v1.assemble_v1_record( "u", "agent go calendar", { "job_id": "j1" }, tr, MAP )
    assert r.ok is True and r.span_ms == 250.0       # compute span still gates ok
    assert r.wall_clock_ms is None                   # wall-clock informational, absent

def test_assemble_ok_cachehit_false_and_unmapped_command():
    r = v1.assemble_v1_record( "u", "agent go calendar", { "job_id": "j1" },
                               _ok_transitions( is_cache_hit=0, agent_type="MysteryAgent" ), MAP )
    assert r.ok is True and r.is_cache_hit is False and r.actual_command is None   # miss


# ───────────────────────────────────────────── run_v1_pass

def test_run_pass_preserves_order_and_collects_on_success():
    collected = []
    def push( u ): return { "job_id": f"job-{u}" }
    def collect( jid ): collected.append( jid ); return _ok_transitions()
    pairs = [ ( "a", "agent go calendar" ), ( "b", "agent go calendar" ) ]
    recs = v1.run_v1_pass( pairs, push_fn=push, collect_fn=collect, class_to_command=MAP )
    assert [ r.utterance for r in recs ] == [ "a", "b" ]           # order preserved
    assert collected == [ "job-a", "job-b" ] and all( r.ok for r in recs )

def test_run_pass_push_failure_short_circuits_collect():
    calls = []
    def push( u ): return { "error": "down" }                      # no job_id
    def collect( jid ): calls.append( jid ); return { }
    recs = v1.run_v1_pass( [ ( "a", "c" ) ], push_fn=push, collect_fn=collect, class_to_command=MAP )
    assert calls == [ ] and recs[ 0 ].failure == "push_failed"     # collect never called

def test_run_pass_push_non_dict_short_circuits():
    calls = []
    def push( u ): return None
    def collect( jid ): calls.append( jid ); return { }
    recs = v1.run_v1_pass( [ ( "a", "c" ) ], push_fn=push, collect_fn=collect, class_to_command=MAP )
    assert calls == [ ] and recs[ 0 ].failure == "push_failed"


# ───────────────────────────────────────────── build_class_to_command

class _Math: pass
class _Cal:  pass

def test_build_class_to_command_inverts_mode_map():
    m, amb = v1.build_class_to_command( { "math": _Math, "calendar": _Cal } )
    assert m == { "_Math": "agent router go to math", "_Cal": "agent router go to calendar" }
    assert amb == [ ]

def test_build_class_to_command_ambiguous_class_is_dropped():
    # one class reachable from TWO modes ⇒ two commands ⇒ dropped, named, not guessed
    m, amb = v1.build_class_to_command( { "math": _Math, "maths": _Math } )
    assert "_Math" not in m and amb == [ "_Math" ]

def test_build_class_to_command_same_command_not_ambiguous():
    # same class + a mode-independent template ⇒ same command ⇒ NOT ambiguous
    m, amb = v1.build_class_to_command( { "a": _Math, "b": _Math }, template="fixed" )
    assert m == { "_Math": "fixed" } and amb == [ ]

def test_build_class_to_command_non_class_value_uses_str():
    m, amb = v1.build_class_to_command( { "m": "raw" } )
    assert m == { "raw": "agent router go to m" } and amb == [ ]


# ───────────────────────────────────────────── run_two_pass

def test_run_two_pass_cold_empty_then_warm_cache():
    seen = { }
    def push( u ):
        n = seen.get( u, 0 ); seen[ u ] = n + 1
        return { "job_id": f"{u}#{n}" }
    def collect( jid ):
        warm = jid.endswith( "#1" )                     # 2nd occurrence ⇒ warm cache hit
        return { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": 10.25,
                 "metadata": { "is_cache_hit": warm, "agent_type": "CalendarAgent" } }
    res = v1.run_two_pass( [ ( "a", "agent go calendar" ) ], push_fn=push, collect_fn=collect,
                           class_to_command=MAP )
    assert res[ "cold" ][ "cache_hit_rate" ] == 0.0     # nothing cached on the cold pass
    assert res[ "warm" ][ "cache_hit_rate" ] == 1.0     # the warm pass replays


# ───────────────────────────────────────────── compute_v1_metrics

def _rec( ok=True, cache=False, span=200.0, wall=None, actual="agent go calendar",
          expected="agent go calendar", degradation=None, failure=None ):
    return v1.V1Record( utterance="u", expected_command=expected, actual_command=actual,
                        is_cache_hit=cache, span_ms=span if ok else None,
                        wall_clock_ms=wall, ok=ok, failure=failure, degradation=degradation )

def test_metrics_full():
    recs = [
        _rec( cache=True, span=100.0, wall=400.0 ),
        _rec( cache=False, span=300.0, wall=900.0, actual="wrong command", degradation="router_error" ),
        _rec( ok=False, failure="push_failed", degradation="agent_error" ),
    ]
    m = v1.compute_v1_metrics( recs )
    assert m[ "n" ] == 3 and m[ "ok_n" ] == 2
    assert m[ "failure_rate" ] == 0.3333          # _rate rounds to 4 places
    assert m[ "routing_accuracy" ] == 0.5                          # 1 of 2 ok routed right
    assert m[ "cache_hit_rate" ] == 0.5
    assert m[ "compute_p50_ms" ] is not None and m[ "compute_p95_ms" ] is not None
    assert m[ "wall_clock_p50_ms" ] is not None and m[ "wall_clock_p95_ms" ] is not None
    assert m[ "degradation_paths_seen" ] == [ "agent_error", "router_error" ]
    assert sorted( m[ "spans" ] ) == [ 100.0, 300.0 ]
    assert sorted( m[ "wall_clock_spans" ] ) == [ 400.0, 900.0 ]   # wall-clock > compute (dwell)

def test_metrics_empty_rates_are_none_not_zero():
    m = v1.compute_v1_metrics( [ ] )
    assert m[ "n" ] == 0 and m[ "ok_n" ] == 0
    assert m[ "failure_rate" ] is None and m[ "routing_accuracy" ] is None
    assert m[ "cache_hit_rate" ] is None
    assert m[ "compute_p50_ms" ] is None and m[ "compute_p95_ms" ] is None
    assert m[ "wall_clock_p50_ms" ] is None and m[ "wall_clock_p95_ms" ] is None
    assert m[ "degradation_paths_seen" ] == [ ] and m[ "spans" ] == [ ] and m[ "wall_clock_spans" ] == [ ]


# ───────────────────────────────────────────── run_v1_baseline

def test_run_v1_baseline_composes_corpus_sample_twopass_report():
    def fake_load( name, limit=None ):
        return [ ( "a", "agent go calendar" ), ( "b", "agent go calendar" ) ]
    def fake_sample( pairs, n, seed ):
        return pairs, { "seed": seed, "n_per_command": n, "under_quota": [ ] }
    seen = { }
    def push( u ):
        n = seen.get( u, 0 ); seen[ u ] = n + 1
        return { "job_id": f"{u}#{n}" }
    def collect( jid ):
        return { "queued_ts": 9.5, "running_ts": 10.0, "completed_ts": 10.25,
                 "metadata": { "is_cache_hit": jid.endswith( "#1" ), "agent_type": "CalendarAgent" } }
    res = v1.run_v1_baseline( seed=7, n_per_command=5, push_fn=push, collect_fn=collect,
                              class_to_command=MAP, load_corpus_fn=fake_load, sample_fn=fake_sample )
    assert res[ "cold" ][ "cache_hit_rate" ] == 0.0 and res[ "warm" ][ "cache_hit_rate" ] == 1.0
    assert res[ "manifest" ][ "seed" ] == 7 and res[ "sampled_n" ] == 2
    assert v1.V1_PIN_SHA in res[ "report" ] and "seed       : 7" in res[ "report" ]


# ───────────────────────────────────────────── reporting

def test_report_header_stamps_pin_sha_and_seed():
    h = v1.build_report_header( seed=1024, corpus="simple", n_per_command=60, base_url="http://x" )
    assert v1.V1_PIN_SHA in h and "1024" in h and "queue dwell EXCLUDED" in h

def test_fmt_none_and_value():
    assert v1._fmt( None ) == "<n/a>"
    assert v1._fmt( 12.34 ) == "12.3"

def test_render_report_with_values():
    m = v1.compute_v1_metrics( [ _rec( cache=True, span=100.0, wall=400.0 ) ] )
    out = v1.render_v1_report( m, seed=7, corpus="simple", n_per_command=60, base_url="http://x" )
    assert "routing_accuracy  : 100.0%" in out and "cache_hit_rate    : 100.0%" in out
    assert "compute_p50_ms    : 100.0" in out and "wall_clock_p50_ms : 400.0" in out
    assert v1.V1_PIN_SHA in out

def test_render_report_with_none_rates():
    m = v1.compute_v1_metrics( [ ] )
    out = v1.render_v1_report( m, seed=7, corpus="simple", n_per_command=60, base_url="http://x" )
    assert "routing_accuracy  : <n/a>%" in out and "degradation_seen  : (none)" in out
    assert "wall_clock_p50_ms : <n/a>" in out


# ───────────────────────────────────────────── CLI

def test_arg_parser_defaults_and_overrides():
    args = v1.build_arg_parser().parse_args( [ "--seed", "99", "--n-per-command", "30", "--base-url", "http://h" ] )
    assert args.seed == 99 and args.n_per_command == 30 and args.base_url == "http://h"
    assert args.corpus == "simple" and args.limit is None


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
