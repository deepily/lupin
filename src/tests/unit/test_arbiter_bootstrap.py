#!/usr/bin/env python3
"""
Unit tests for arbiter_bootstrap — v2.2 lane B1 (standing-cadence startup
submission + single-instance guard + degrade-safe). 100% line+branch+function
on the guard + submit LOGIC (build_arbiter_job is the pragma'd IO boundary,
exercised at the :8000 tier like LupinArbiterGateway.from_environment).
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.arbiter_bootstrap import (
    arbiter_already_present, submit_arbiter_if_absent, submit_arbiter_if_enabled,
    quick_smoke_test,
)
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


class _ArbiterJob:
    JOB_TYPE = ArbiterConsumerJob.JOB_TYPE   # "heartbeat_arbiter"


class _OtherJob:
    JOB_TYPE = "deep_research"


class _NoTypeJob:
    pass   # no JOB_TYPE attr → must be treated as non-arbiter


class _Queue:
    def __init__( self, jobs=None ):
        self.queue_list = list( jobs or [ ] )
    def push( self, job ):
        self.queue_list.append( job )


class _Flow:
    """The v2 AskFlow seam (step 12). The arbiter no longer pushes onto the queue
    itself; it submits, and the flow's queued executor does the pushing. Recording
    the submit is the same assertion the old `todo.queue_list[-1] is job` made."""
    def __init__( self ):
        self.submitted = [ ]
    def submit( self, job=None, **kwargs ):
        self.submitted.append( ( job, kwargs ) )
        return { "status": "waiting", "job_id": getattr( job, "id_hash", "fake" ) }


# ── arbiter_already_present ────────────────────────────────────────────────────

class TestGuard:
    def test_absent( self ):
        assert arbiter_already_present( _Queue(), _Queue() ) is False

    def test_present_in_todo( self ):
        assert arbiter_already_present( _Queue( [ _ArbiterJob() ] ), _Queue() ) is True

    def test_present_in_run( self ):
        assert arbiter_already_present( _Queue(), _Queue( [ _ArbiterJob() ] ) ) is True

    def test_other_jobs_do_not_count( self ):
        assert arbiter_already_present( _Queue( [ _OtherJob() ] ), _Queue( [ _OtherJob() ] ) ) is False

    def test_job_without_job_type_ignored( self ):
        assert arbiter_already_present( _Queue( [ _NoTypeJob() ] ), _Queue() ) is False

    def test_queue_without_queue_list_treated_empty( self ):
        class _Bare:  # no queue_list attr
            pass
        assert arbiter_already_present( _Bare(), _Bare() ) is False


# ── submit_arbiter_if_absent ───────────────────────────────────────────────────

class TestSubmit:
    def test_submits_when_absent( self ):
        todo, run, logs, flow = _Queue(), _Queue(), [ ], _Flow()
        job = submit_arbiter_if_absent( todo, run, object(),
                                        job_builder=lambda cfg: _ArbiterJob(), log=logs.append,
                                        ask_flow=flow )
        assert job is not None
        assert flow.submitted[ -1 ][ 0 ] is job     # submitted through the flow, not pushed
        assert todo.queue_list == [ ]               # and NOT pushed onto the queue directly
        assert any( "submitted" in m for m in logs )

    def test_noop_when_present( self ):
        todo, run, logs, flow = _Queue( [ _ArbiterJob() ] ), _Queue(), [ ], _Flow()
        job = submit_arbiter_if_absent( todo, run, object(),
                                        job_builder=lambda cfg: _ArbiterJob(), log=logs.append,
                                        ask_flow=flow )
        assert job is None
        assert flow.submitted == [ ]                # nothing new submitted
        assert any( "already present" in m for m in logs )

    def test_builder_failure_swallowed_degrade_safe( self ):
        todo, run, logs, flow = _Queue(), _Queue(), [ ], _Flow()
        def _boom( cfg ):
            raise RuntimeError( "config unavailable" )
        job = submit_arbiter_if_absent( todo, run, object(), job_builder=_boom, log=logs.append,
                                        ask_flow=flow )
        assert job is None
        assert flow.submitted == [ ]                # nothing submitted
        assert any( "degrade-safe" in m for m in logs )   # logged, not raised

    def test_missing_flow_is_degrade_safe_and_says_so( self ):
        """No flow is a wiring bug, but the arbiter is an ADDITIVE OBSERVER — it must
        log and return, never take startup down. The raise inside is caught by the
        same degrade-safe guard that catches a builder failure."""
        todo, run, logs = _Queue(), _Queue(), [ ]
        job = submit_arbiter_if_absent( todo, run, object(),
                                        job_builder=lambda cfg: _ArbiterJob(), log=logs.append )
        assert job is None
        assert todo.queue_list == [ ]
        assert any( "no ask_flow" in m for m in logs )
        assert any( "degrade-safe" in m for m in logs )

    def test_default_log_is_print( self ):
        # exercise the default log= (print) path without asserting stdout
        todo, run = _Queue(), _Queue()
        job = submit_arbiter_if_absent( todo, run, object(), job_builder=lambda cfg: _ArbiterJob(),
                                        ask_flow=_Flow() )
        assert job is not None


# ── submit_arbiter_if_enabled — R0 gate (T1-T5) ────────────────────────────────

class _FlagCfg:
    """Fake config manager for the R0 flag; counts get() calls (read-once contract)."""
    _ABSENT = object()
    def __init__( self, value=_ABSENT ):
        self._value    = value
        self.get_calls = 0
    def get( self, key, default=None, return_type="string" ):
        self.get_calls += 1
        return default if self._value is self._ABSENT else self._value


def _recording_submit():
    calls = [ ]
    def submit( todo, run, cfg, log=print, ask_flow=None ):
        calls.append( ( todo, run, cfg, ask_flow ) )
        return "JOB"
    return submit, calls


class TestR0Gate:
    def test_t1_flag_true_submits_once( self ):
        submit, calls = _recording_submit()
        out = submit_arbiter_if_enabled( _Queue(), _Queue(), _FlagCfg( "true" ),
                                         submit_fn=submit, log=lambda *a: None )
        assert out == "JOB" and len( calls ) == 1

    def test_t2_flag_false_skips_with_disabled_log( self ):
        submit, calls = _recording_submit()
        logs = [ ]
        out = submit_arbiter_if_enabled( _Queue(), _Queue(), _FlagCfg( "false" ),
                                         submit_fn=submit, log=logs.append )
        assert out is None and calls == [ ]
        assert any( "DISABLED" in m for m in logs )

    def test_t3_absent_defaults_true_submits( self ):
        submit, calls = _recording_submit()
        out = submit_arbiter_if_enabled( _Queue(), _Queue(), _FlagCfg(),       # key absent → default true
                                         submit_fn=submit, log=lambda *a: None )
        assert out == "JOB" and len( calls ) == 1

    def test_t4_malformed_coerces_false_and_warns( self ):
        submit, calls = _recording_submit()
        logs = [ ]
        out = submit_arbiter_if_enabled( _Queue(), _Queue(), _FlagCfg( "garbage" ),
                                         submit_fn=submit, log=logs.append )
        assert out is None and calls == [ ]
        assert any( "WARNING" in m for m in logs )       # loud-warn on typo (ruling D)
        assert any( "DISABLED" in m for m in logs )

    def test_the_flow_reaches_the_inner_submit( self ):
        """The gate is a pass-through for ask_flow. A gate that read the flag correctly
        and dropped the flow would leave the arbiter unable to reach the queue, and
        every other test here would still pass."""
        submit, calls = _recording_submit()
        flow = _Flow()
        submit_arbiter_if_enabled( _Queue(), _Queue(), _FlagCfg( "true" ),
                                   submit_fn=submit, log=lambda *a: None, ask_flow=flow )
        assert calls[ 0 ][ 3 ] is flow

    def test_t5_flag_read_once( self ):
        cfg = _FlagCfg( "true" )
        submit, _ = _recording_submit()
        submit_arbiter_if_enabled( _Queue(), _Queue(), cfg, submit_fn=submit, log=lambda *a: None )
        assert cfg.get_calls == 1                          # read-once contract


def test_quick_smoke_test():
    assert quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )


# ── 6929f4ac: build_arbiter_job wires the outward-twin hold reader ─────────────
# Wiring-only regression guard (Rachel's deploy-honesty catch): build_arbiter_job
# is the pragma'd IO boundary, but the hold_reader_fn WIRING must not silently
# regress. We patch the one real-IO hop (LupinArbiterGateway.from_environment) and
# feed a defaults-returning fake config, then assert the seam resolves to read_hold.

class _DefaultsCfg:
    """config_mgr stub: every key returns the caller's default (exercises the
    build_arbiter_job param reads with valid ctor-passing defaults)."""
    def get( self, key, default=None, return_type=None ):
        return default


def test_build_arbiter_job_wires_real_hold_reader( monkeypatch ):
    from cosa.rest import arbiter_bootstrap as ab
    from cosa.agents.heartbeat_arbiter.arbiter_gateway import LupinArbiterGateway
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import read_hold_via_bridge

    class _FakeGW:
        def who( self, retention_hours=24 ): return [ ]
        def send_to( self, r, b, metadata=None ): pass
        def post( self, t, b ): pass
        def read( self, topic, since=None, limit=50 ): return [ ]

    monkeypatch.setattr( LupinArbiterGateway, "from_environment",
                         classmethod( lambda cls, **kw: _FakeGW() ) )
    job = ab.build_arbiter_job( _DefaultsCfg() )
    # row 011f1f90: this gated-OFF in-process path wires the resilient per-session reader
    # DIRECTLY (no log_fn wrapper — no journal on the dead path), so identity still holds.
    # The live :8001 factory wraps it in a lambda to thread log_fn; that one is behavioral.
    assert job._hold_reader_fn is read_hold_via_bridge       # non-None AND resolves to the bridge reader
    assert job.user_gate_resurface_seconds == 1800           # default ceiling threaded
