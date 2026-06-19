#!/usr/bin/env python3
"""
Unit tests for TaskChaseConsumer (cosa.rest.task_chase_consumer).

The daemon's core is injectable (config / get_db / repo factory / signal / clock),
so these run with no live server, no Postgres, and no real clock (:7999-eligible).
100% lines/branches/functions of task_chase_consumer.py — flag-gate no-op,
chase pass (signal + re-arm, status untouched), read-only stall report, daemon
start/stop lifecycle, and the loop's exception guard.
"""
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.task_chase_consumer as tcc
from cosa.rest.task_chase_consumer import TaskChaseConsumer, CHASE_ACTOR

NOW = datetime( 2026, 6, 15, 12, 0, tzinfo=timezone.utc )


class FakeConfig:
    def __init__( self, **vals ):
        self._vals = dict( vals )

    def get( self, key, default=None, return_type=None ):
        return self._vals.get( key, default )


@contextmanager
def _fake_db():
    yield MagicMock()


def _due_item( **overrides ):
    m = MagicMock()
    m.id                  = "id-1"
    m.owner_persona       = "krishna"
    m.accountable_manager = "tiberius"
    m.title               = "blocked thing"
    m.status              = "blocked"
    m.next_chase_ts       = NOW
    for k, v in overrides.items():
        setattr( m, k, v )
    return m


def _consumer( enabled=True, due=None, signal_fn=None, interval=300, backoff=1800 ):
    config = FakeConfig( **{
        "task store chase enabled"          : enabled,
        "task store chase interval seconds"  : interval,
        "task store chase backoff seconds"   : backoff,
    } )
    repo = MagicMock()
    repo.query_chase_due.return_value = due if due is not None else [ ]
    consumer = TaskChaseConsumer(
        config, get_db_fn=_fake_db, repo_factory=lambda session: repo,
        signal_fn=signal_fn, now_fn=lambda: NOW,
    )
    return consumer, repo


# ---------------------------------------------------------------------------
# sweep_once
# ---------------------------------------------------------------------------

def test_sweep_disabled_is_noop_no_db():
    c, repo = _consumer( enabled=False )
    assert c.sweep_once() == { "enabled": False, "chased": 0 }
    repo.query_chase_due.assert_not_called()                  # flag OFF → no DB access at all


def test_sweep_enabled_chases_each_due_item_with_backoff():
    signalled = [ ]
    a, b = _due_item( id="a" ), _due_item( id="b" )
    c, repo = _consumer( enabled=True, due=[ a, b ], signal_fn=signalled.append, backoff=1800 )

    assert c.sweep_once() == { "enabled": True, "chased": 2 }
    assert signalled == [ a, b ]                              # signalled, in due order
    assert repo.apply_chase.call_count == 2
    kwargs = repo.apply_chase.call_args.kwargs
    assert kwargs[ "actor" ] == CHASE_ACTOR and kwargs[ "authority" ] == "standing"
    assert kwargs[ "next_chase_ts" ] == NOW + timedelta( seconds=1800 )   # re-armed with the backoff


def test_sweep_enabled_zero_due():
    c, repo = _consumer( enabled=True, due=[ ] )
    assert c.sweep_once() == { "enabled": True, "chased": 0 }
    repo.apply_chase.assert_not_called()


# ---------------------------------------------------------------------------
# stall_report (read-only, flag-independent)
# ---------------------------------------------------------------------------

def test_stall_report_serializes_overdue_both_ts_branches():
    c, repo = _consumer( enabled=False, due=[ _due_item( id="a", next_chase_ts=NOW ),
                                              _due_item( id="b", next_chase_ts=None ) ] )
    report = c.stall_report()
    assert len( report ) == 2
    assert report[ 0 ][ "id" ] == "a" and report[ 0 ][ "next_chase_ts" ] == NOW.isoformat()
    assert report[ 1 ][ "next_chase_ts" ] is None             # None branch of the ternary
    repo.apply_chase.assert_not_called()                      # read-only


# ---------------------------------------------------------------------------
# default signal sink
# ---------------------------------------------------------------------------

def test_default_signal_logs_a_banner( monkeypatch ):
    calls = [ ]
    monkeypatch.setattr( tcc.du, "print_banner", lambda *a, **k: calls.append( a[ 0 ] ) )
    c, repo = _consumer( enabled=True, due=[ _due_item() ], signal_fn=None )   # default signal
    c.sweep_once()
    assert len( calls ) == 1 and "overdue blocked item" in calls[ 0 ]


# ---------------------------------------------------------------------------
# daemon lifecycle
# ---------------------------------------------------------------------------

def test_start_disabled_returns_false_no_thread():
    c, repo = _consumer( enabled=False )
    assert c.start() is False
    assert c._thread is None


def test_start_enabled_spawns_then_double_start_false_then_stop():
    c, repo = _consumer( enabled=True, due=[ ] )
    assert c.start() is True
    try:
        assert c._thread is not None and c._thread.is_alive()
        assert c.start() is False                             # already running → no second thread
    finally:
        c.stop()
    assert not c._thread.is_alive()


def test_stop_without_start_is_noop():
    c, repo = _consumer( enabled=True )
    c.stop()                                                  # no thread — must not raise


def test_loop_guards_sweep_exceptions( monkeypatch ):
    c, repo = _consumer( enabled=True, interval=0 )
    monkeypatch.setattr( tcc.du, "print_banner", lambda *a, **k: None )
    calls = { "n": 0 }

    def boom():
        calls[ "n" ] += 1
        c._stop_event.set()                                   # exit the loop after this iteration
        raise RuntimeError( "transient DB blip" )

    monkeypatch.setattr( c, "sweep_once", boom )
    c._loop()                                                 # must NOT propagate the exception
    assert calls[ "n" ] == 1


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
