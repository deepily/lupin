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
        todo, run, logs = _Queue(), _Queue(), [ ]
        job = submit_arbiter_if_absent( todo, run, object(),
                                        job_builder=lambda cfg: _ArbiterJob(), log=logs.append )
        assert job is not None
        assert todo.queue_list[ -1 ] is job        # pushed to TODO
        assert any( "submitted" in m for m in logs )

    def test_noop_when_present( self ):
        todo, run, logs = _Queue( [ _ArbiterJob() ] ), _Queue(), [ ]
        job = submit_arbiter_if_absent( todo, run, object(),
                                        job_builder=lambda cfg: _ArbiterJob(), log=logs.append )
        assert job is None
        assert len( todo.queue_list ) == 1          # nothing new pushed
        assert any( "already present" in m for m in logs )

    def test_builder_failure_swallowed_degrade_safe( self ):
        todo, run, logs = _Queue(), _Queue(), [ ]
        def _boom( cfg ):
            raise RuntimeError( "config unavailable" )
        job = submit_arbiter_if_absent( todo, run, object(), job_builder=_boom, log=logs.append )
        assert job is None
        assert todo.queue_list == [ ]               # nothing pushed
        assert any( "degrade-safe" in m for m in logs )   # logged, not raised

    def test_default_log_is_print( self ):
        # exercise the default log= (print) path without asserting stdout
        todo, run = _Queue(), _Queue()
        job = submit_arbiter_if_absent( todo, run, object(), job_builder=lambda cfg: _ArbiterJob() )
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
    def submit( todo, run, cfg, log=print ):
        calls.append( ( todo, run, cfg ) )
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

    def test_t5_flag_read_once( self ):
        cfg = _FlagCfg( "true" )
        submit, _ = _recording_submit()
        submit_arbiter_if_enabled( _Queue(), _Queue(), cfg, submit_fn=submit, log=lambda *a: None )
        assert cfg.get_calls == 1                          # read-once contract


def test_quick_smoke_test():
    assert quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
