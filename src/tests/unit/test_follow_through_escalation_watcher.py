#!/usr/bin/env python3
"""
Unit tests for FollowThroughEscalationWatcher
(cosa.rest.follow_through_escalation_watcher).

The watcher's core is fully injectable (config / get_db / repo factory /
escalate sink / worker-hold oracle / clock / hold base-dir), so these run with
no live server, no Postgres, no real clock, and no hold files (:7999-eligible).

100% lines/branches/functions of follow_through_escalation_watcher.py:
  - the awaiting:manager convention helper (every reject branch + the match)
  - persona normalization (None / non-str / accents / emoji / punctuation)
  - sweep: flag-gate no-op, non-candidate skip, worker-hold suppression (§4.5b),
    no-block-event defensive skip, not-yet-aged, aged one-shot escalation,
    already-escalated no-refire, manager-ack clear (§4.5a)
  - awaited_since derivation (no event / ts None / naive coerce / aware passthrough)
  - the default escalation banner sink
  - the default worker-hold oracle (match / mismatch / stale / .tmp / unreadable /
    non-object / none-found / base-dir fallback)
  - daemon start/stop lifecycle + the loop's exception guard
"""
import os
import sys
import json
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.follow_through_escalation_watcher as ftw
from cosa.rest.follow_through_escalation_watcher import (
    FollowThroughEscalationWatcher,
    is_awaiting_manager,
    _norm_persona,
    ESCALATION_ACTOR,
)
from lupin_cli.claude_code.hooks.lib import heartbeat_hold as hh

NOW = datetime( 2026, 6, 17, 12, 0, tzinfo=timezone.utc )


class FakeConfig:
    def __init__( self, **vals ):
        self._vals = dict( vals )

    def get( self, key, default=None, return_type=None ):
        return self._vals.get( key, default )


@contextmanager
def _fake_db():
    yield MagicMock()


def _item( **overrides ):
    """A blocked, awaiting:manager item by default (worker krishna -> manager tiberius)."""
    m = MagicMock()
    m.id                  = "item-1"
    m.owner_persona       = "krishna"
    m.accountable_manager = "tiberius"
    m.status              = "blocked"
    m.blocked_by          = [ { "kind": "persona", "id": "tiberius" } ]
    m.title               = "awaiting manager verification"
    for k, v in overrides.items():
        setattr( m, k, v )
    return m


def _event( transition="in_progress->blocked", ts=NOW ):
    e = MagicMock()
    e.transition = transition
    e.ts         = ts
    return e


def _watcher(
    enabled       = True,
    items         = None,
    events        = None,
    escalate_fn   = None,
    hold_check_fn = None,
    multiplier    = 2,
    tick          = 60,
    now           = NOW,
):
    """
    Build a watcher over a MagicMock repo. `events` maps item.id -> [events] for
    get_events; absent ids default to a single in_progress->blocked event at NOW.
    hold_check_fn defaults to "nobody is parked" so the awaiting path is exercised.
    """
    config = FakeConfig( **{
        "follow through escalation enabled"         : enabled,
        "follow through escalation tick multiplier" : multiplier,
        "arbiter poll seconds"                      : tick,
    } )
    repo = MagicMock()
    repo.query_tasks.return_value = items if items is not None else [ ]
    ev_map = events if events is not None else { }

    def _get_events( item_id ):
        return ev_map.get( item_id, [ _event() ] )

    repo.get_events.side_effect = _get_events

    watcher = FollowThroughEscalationWatcher(
        config,
        get_db_fn     = _fake_db,
        repo_factory  = lambda session: repo,
        escalate_fn   = escalate_fn,
        hold_check_fn = hold_check_fn if hold_check_fn is not None else ( lambda persona: False ),
        now_fn        = lambda: now,
    )
    return watcher, repo


# ---------------------------------------------------------------------------
# is_awaiting_manager — the convention helper (P1)
# ---------------------------------------------------------------------------

def test_awaiting_manager_match():
    assert is_awaiting_manager( _item() ) is True


def test_awaiting_manager_rejects_non_blocked():
    assert is_awaiting_manager( _item( status="in_progress" ) ) is False


def test_awaiting_manager_rejects_no_accountable_manager():
    assert is_awaiting_manager( _item( accountable_manager=None ) ) is False
    assert is_awaiting_manager( _item( accountable_manager="" ) ) is False


def test_awaiting_manager_rejects_empty_blocked_by():
    assert is_awaiting_manager( _item( blocked_by=None ) ) is False
    assert is_awaiting_manager( _item( blocked_by=[ ] ) ) is False


def test_awaiting_manager_rejects_non_dict_ref():
    assert is_awaiting_manager( _item( blocked_by=[ "tiberius" ] ) ) is False


def test_awaiting_manager_rejects_non_persona_kind():
    assert is_awaiting_manager( _item( blocked_by=[ { "kind": "item", "id": "tiberius" } ] ) ) is False


def test_awaiting_manager_rejects_persona_other_than_manager():
    assert is_awaiting_manager( _item( blocked_by=[ { "kind": "persona", "id": "someone-else" } ] ) ) is False


# ---------------------------------------------------------------------------
# _norm_persona
# ---------------------------------------------------------------------------

def test_norm_persona_none_and_non_string_and_empty():
    assert _norm_persona( None ) == ""
    assert _norm_persona( 123 ) == ""
    assert _norm_persona( "" ) == ""


def test_norm_persona_strips_accents_emoji_punct_space():
    assert _norm_persona( "María 🌸" ) == "maria"
    assert _norm_persona( "Mr. Radio 🦉" ) == "mrradio"
    assert _norm_persona( "mr radio" ) == "mrradio"
    assert _norm_persona( "Krishna" ) == "krishna"


# ---------------------------------------------------------------------------
# sweep_once
# ---------------------------------------------------------------------------

def test_sweep_disabled_is_noop_no_db():
    w, repo = _watcher( enabled=False )
    assert w.sweep_once() == { "enabled": False, "escalated": 0, "candidates": 0 }
    repo.query_tasks.assert_not_called()                       # flag OFF → no DB access at all


def test_sweep_skips_non_candidates():
    not_awaiting = _item( id="x", blocked_by=[ ] )             # blocked but not the convention
    w, repo = _watcher( enabled=True, items=[ not_awaiting ] )
    assert w.sweep_once() == { "enabled": True, "escalated": 0, "candidates": 0 }


def test_sweep_escalates_aged_item_once_with_args():
    captured = [ ]
    aged_block = { "a": [ _event( ts=NOW - timedelta( seconds=300 ) ) ] }   # 300s > T_escalate(120)
    w, repo = _watcher(
        enabled=True, items=[ _item( id="a" ) ], events=aged_block,
        escalate_fn=lambda item, manager, worker, awaited_since: captured.append(
            ( item.id, manager, worker, awaited_since )
        ),
    )
    result = w.sweep_once()
    assert result == { "enabled": True, "escalated": 1, "candidates": 1 }
    assert captured == [ ( "a", "tiberius", "krishna", NOW - timedelta( seconds=300 ) ) ]
    assert "a" in w._escalated                                 # one-shot marker set


def test_sweep_not_yet_aged_does_not_escalate():
    recent = { "a": [ _event( ts=NOW - timedelta( seconds=60 ) ) ] }        # 60s <= T_escalate(120)
    captured = [ ]
    w, repo = _watcher( enabled=True, items=[ _item( id="a" ) ], events=recent,
                        escalate_fn=lambda *a: captured.append( a ) )
    assert w.sweep_once() == { "enabled": True, "escalated": 0, "candidates": 1 }
    assert captured == [ ] and w._escalated == set()


def test_sweep_no_block_event_is_defensive_skip():
    no_block = { "a": [ _event( transition="->queued" ) ] }    # never went ->blocked
    w, repo = _watcher( enabled=True, items=[ _item( id="a" ) ], events=no_block )
    assert w.sweep_once() == { "enabled": True, "escalated": 0, "candidates": 1 }
    assert w._escalated == set()


def test_sweep_one_shot_no_refire_on_second_pass():
    aged = { "a": [ _event( ts=NOW - timedelta( seconds=300 ) ) ] }
    calls = [ ]
    w, repo = _watcher( enabled=True, items=[ _item( id="a" ) ], events=aged,
                        escalate_fn=lambda *a: calls.append( a ) )
    assert w.sweep_once()[ "escalated" ] == 1
    assert w.sweep_once()[ "escalated" ] == 0                  # already escalated → never re-fire
    assert len( calls ) == 1 and "a" in w._escalated


def test_sweep_manager_ack_clears_marker():
    aged = { "a": [ _event( ts=NOW - timedelta( seconds=300 ) ) ] }
    w, repo = _watcher( enabled=True, items=[ _item( id="a" ) ], events=aged,
                        escalate_fn=lambda *a: None )
    assert w.sweep_once()[ "escalated" ] == 1 and "a" in w._escalated
    # manager acked → item left blocked → absent from the query (§4.5a)
    repo.query_tasks.return_value = [ ]
    assert w.sweep_once() == { "enabled": True, "escalated": 0, "candidates": 0 }
    assert w._escalated == set()                               # marker cleared


def test_sweep_worker_hold_suppresses_and_clears_marker():
    aged = { "a": [ _event( ts=NOW - timedelta( seconds=300 ) ) ] }
    parked = { "on": False }
    w, repo = _watcher( enabled=True, items=[ _item( id="a" ) ], events=aged,
                        escalate_fn=lambda *a: None,
                        hold_check_fn=lambda persona: parked[ "on" ] )
    assert w.sweep_once()[ "escalated" ] == 1 and "a" in w._escalated
    # worker now declares a valid hold → documented park, not a silent stall (§4.5b)
    parked[ "on" ] = True
    result = w.sweep_once()
    assert result == { "enabled": True, "escalated": 0, "candidates": 1 }   # still a candidate, but suppressed
    assert w._escalated == set()                               # marker cleared


# ---------------------------------------------------------------------------
# _awaited_since
# ---------------------------------------------------------------------------

def test_awaited_since_none_when_no_block_event():
    w, repo = _watcher( enabled=True )
    repo.get_events.side_effect = None
    repo.get_events.return_value = [ _event( transition="->queued" ) ]
    assert w._awaited_since( repo, _item() ) is None


def test_awaited_since_none_when_ts_missing():
    w, repo = _watcher( enabled=True )
    repo.get_events.side_effect = None
    repo.get_events.return_value = [ _event( transition="in_progress->blocked", ts=None ) ]
    assert w._awaited_since( repo, _item() ) is None


def test_awaited_since_coerces_naive_to_utc():
    naive = datetime( 2026, 6, 17, 10, 0 )                     # no tzinfo
    w, repo = _watcher( enabled=True )
    repo.get_events.side_effect = None
    repo.get_events.return_value = [ _event( ts=naive ) ]
    got = w._awaited_since( repo, _item() )
    assert got == naive.replace( tzinfo=timezone.utc ) and got.tzinfo is timezone.utc


def test_awaited_since_uses_latest_block_event():
    w, repo = _watcher( enabled=True )
    repo.get_events.side_effect = None
    repo.get_events.return_value = [
        _event( transition="in_progress->blocked", ts=NOW - timedelta( hours=2 ) ),
        _event( transition="blocked->in_progress", ts=NOW - timedelta( hours=1 ) ),
        _event( transition="in_progress->blocked", ts=NOW - timedelta( minutes=5 ) ),
    ]
    assert w._awaited_since( repo, _item() ) == NOW - timedelta( minutes=5 )


# ---------------------------------------------------------------------------
# _t_escalate / config
# ---------------------------------------------------------------------------

def test_t_escalate_is_live_tick_times_multiplier():
    w, _ = _watcher( enabled=True, tick=90, multiplier=3 )
    assert w._t_escalate() == 270


# ---------------------------------------------------------------------------
# default escalation banner sink
# ---------------------------------------------------------------------------

def test_default_escalation_signal_logs_banner( monkeypatch ):
    calls = [ ]
    monkeypatch.setattr( ftw.du, "print_banner", lambda *a, **k: calls.append( a[ 0 ] ) )
    aged = { "a": [ _event( ts=NOW - timedelta( seconds=300 ) ) ] }
    w, repo = _watcher( enabled=True, items=[ _item( id="a" ) ], events=aged )   # default escalate_fn
    w.sweep_once()
    assert len( calls ) == 1 and "aged awaiting:manager item a" in calls[ 0 ]


# ---------------------------------------------------------------------------
# _default_hold_check — the §4.5 worker-hold oracle
# ---------------------------------------------------------------------------

def _hold_watcher( tmp ):
    config = FakeConfig( **{ "follow through escalation enabled": True } )
    return FollowThroughEscalationWatcher(
        config, get_db_fn=_fake_db, repo_factory=lambda s: MagicMock(),
        now_fn=lambda: NOW, hold_base_dir=str( tmp ),
    )


def test_default_hold_check_empty_persona_is_false( tmp_path ):
    w = _hold_watcher( tmp_path )
    assert w._default_hold_check( None ) is False
    assert w._default_hold_check( "" ) is False


def test_default_hold_check_matches_honored_hold( tmp_path ):
    hh.write_hold( "sess-krishna", "Krishna 🌸", "parked awaiting peer review",
                   work_owed=True, ttl_seconds=900, held_at=NOW.isoformat(), base_dir=str( tmp_path ) )
    w = _hold_watcher( tmp_path )
    assert w._default_hold_check( "krishna" ) is True


def test_default_hold_check_no_match_for_other_persona( tmp_path ):
    hh.write_hold( "sess-krishna", "Krishna 🌸", "parked", held_at=NOW.isoformat(), base_dir=str( tmp_path ) )
    w = _hold_watcher( tmp_path )
    assert w._default_hold_check( "tiberius" ) is False


def test_default_hold_check_ignores_stale_hold( tmp_path ):
    old = ( NOW - timedelta( seconds=10_000 ) ).isoformat()
    hh.write_hold( "sess-krishna", "Krishna 🌸", "stale park", ttl_seconds=900,
                   held_at=old, base_dir=str( tmp_path ) )
    w = _hold_watcher( tmp_path )
    assert w._default_hold_check( "krishna" ) is False         # not fresh → not honored


def test_default_hold_check_skips_tmp_unreadable_and_non_object( tmp_path ):
    ( tmp_path / ".heartbeat-hold-x.json.tmp" ).write_text( "ignored" )        # .tmp skipped
    ( tmp_path / ".heartbeat-hold-bad.json" ).write_text( "{not json" )         # ValueError → skipped
    ( tmp_path / ".heartbeat-hold-arr.json" ).write_text( "[]" )                # non-dict → skipped
    w = _hold_watcher( tmp_path )
    assert w._default_hold_check( "krishna" ) is False


def test_default_hold_check_no_files_is_false( tmp_path ):
    assert _hold_watcher( tmp_path )._default_hold_check( "krishna" ) is False


def test_default_hold_check_falls_back_to_project_root( tmp_path, monkeypatch ):
    hh.write_hold( "sess-krishna", "Krishna", "parked", held_at=NOW.isoformat(), base_dir=str( tmp_path ) )
    import cosa.utils.util as cu
    monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
    config = FakeConfig( **{ "follow through escalation enabled": True } )
    w = FollowThroughEscalationWatcher(
        config, get_db_fn=_fake_db, repo_factory=lambda s: MagicMock(),
        now_fn=lambda: NOW, hold_base_dir=None,                # → cu.get_project_root()
    )
    assert w._default_hold_check( "krishna" ) is True


# ---------------------------------------------------------------------------
# daemon lifecycle
# ---------------------------------------------------------------------------

def test_start_disabled_returns_false_no_thread():
    w, repo = _watcher( enabled=False )
    assert w.start() is False
    assert w._thread is None


def test_start_enabled_spawns_then_double_start_false_then_stop():
    w, repo = _watcher( enabled=True, tick=60 )
    assert w.start() is True
    try:
        assert w._thread is not None and w._thread.is_alive()
        assert w.start() is False                              # already running → no second thread
    finally:
        w.stop()
    assert not w._thread.is_alive()


def test_stop_without_start_is_noop():
    w, repo = _watcher( enabled=True )
    w.stop()                                                   # no thread — must not raise


def test_loop_guards_sweep_exceptions( monkeypatch ):
    w, repo = _watcher( enabled=True, tick=0 )
    monkeypatch.setattr( ftw.du, "print_banner", lambda *a, **k: None )
    calls = { "n": 0 }

    def boom():
        calls[ "n" ] += 1
        w._stop_event.set()                                    # exit the loop after this iteration
        raise RuntimeError( "transient DB blip" )

    monkeypatch.setattr( w, "sweep_once", boom )
    w._loop()                                                  # must NOT propagate the exception
    assert calls[ "n" ] == 1


def test_escalation_actor_constant():
    assert ESCALATION_ACTOR == "follow-through-escalation-watcher"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
