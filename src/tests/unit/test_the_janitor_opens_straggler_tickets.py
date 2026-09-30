"""
The :8001 janitor hands every poll's refusals to the straggler step (row 747199ef,
Rick's ruling 2026-09-29): a tree refused for over a day becomes one store row.
"""

import json
import os
import time

from lupin_arbiter_app import fleet_arbiter_loop as fal

SEAT = "/repo/lupin/.claude/worktrees/seat-cc-author-mr-radio-1"


def _refusal( path, blockers ):
    return { "path": path, "result": { "removed": False, "skipped_reason": "ignored_files_present",
                                       "ignored_blockers": blockers } }


def _janitor( reconcile_out, straggler_fn, events ):
    return fal.make_worktree_janitor_fn(
        sandbox_root=".claude/worktrees", age_hours=6, ledger_path="/nowhere",
        notify_fn=lambda m, a: [], log_fn=lambda e, **f: events.append( ( e, f ) ),
        reconcile_fn=lambda **kw: reconcile_out, report_fn=lambda *a, **k: { "changed": False },
        straggler_fn=straggler_fn )


def test_the_straggler_step_sees_the_merged_poll_result():
    seen, events = [], []
    out = _janitor( { "swept": [ _refusal( SEAT, [ "io/x" ] ) ] },
                    lambda r: seen.append( r ) or { "opened": [ SEAT ] }, events )()
    assert seen[ 0 ][ "swept" ][ 0 ][ "path" ] == SEAT
    assert out[ "stragglers" ] == { "opened": [ SEAT ] }


def test_a_straggler_failure_is_logged_and_the_poll_result_survives():
    events = []
    def boom( r ): raise RuntimeError( "store down" )
    out = _janitor( { "swept": [] }, boom, events )()
    assert ( "worktree_straggler_error", { "error": "store down" } ) in events
    assert "stragglers" not in out and out[ "swept" ] == []


def test_no_straggler_fn_means_inert():
    out = _janitor( { "swept": [] }, None, [] )()
    assert "stragglers" not in out


class _Store:
    def __init__( self ): self.created = []
    def find_open( self, key ): return None
    def create( self, **row ):
        self.created.append( row )
        return "tid"
    def drop( self, tid, reason ): raise AssertionError( "nothing is gone" )


def test_the_real_step_tickets_a_long_idle_refused_tree( tmp_path ):
    tree = tmp_path / "repo" / ".claude" / "worktrees" / "seat-cc-author-mr-radio-1"
    ( tree / "io" ).mkdir( parents=True )
    f = tree / "io" / "x.md"
    f.write_text( "data" )
    old = time.time() - 40 * 3600
    os.utime( f, ( old, old ) )
    os.utime( tree / "io", ( old, old ) )
    os.utime( tree, ( old, old ) )
    ledger, store, events = tmp_path / "jan" / "refused.json", _Store(), []
    step = fal.make_straggler_fn( ledger_path=str( ledger ), janitor_idle_hours=6,
                                  log_fn=lambda e, **k: events.append( e ), store=store )
    out = step( { "swept": [ _refusal( str( tree ), [ "io/x.md" ] ) ], "skipped": [] } )
    assert out[ "opened" ] == [ str( tree ) ]
    assert store.created[ 0 ][ "owner" ] == "mr radio"
    state = json.loads( ( tmp_path / "jan" / "stragglers.json" ).read_text() )
    assert state[ "trees" ][ str( tree ) ][ "estimated" ] is True


def test_the_default_store_is_the_direct_repository_write( tmp_path ):
    from cosa.agents.shared import worktree_straggler_tickets as st
    captured = {}
    real = st.sync_straggler_tickets
    def spy( refused, state_path, store, log_fn, **kw ):
        captured[ "store" ] = store
        return real( refused, state_path, store, log_fn, **kw )
    import unittest.mock as um
    with um.patch.object( st, "sync_straggler_tickets", spy ):
        fal.make_straggler_fn( ledger_path=str( tmp_path / "r.json" ), janitor_idle_hours=6,
                               log_fn=lambda *a, **k: None )( { "swept": [], "skipped": [] } )
    assert isinstance( captured[ "store" ], st.RepositoryStragglerStore )


def test_the_factory_wires_a_straggler_step( monkeypatch, tmp_path ):
    captured = {}
    real = fal.make_worktree_janitor_fn
    def spy( **kw ):
        captured.update( kw )
        return real( **kw )
    monkeypatch.setattr( fal, "make_worktree_janitor_fn", spy )
    from tests.unit.test_the_janitor_sweeps_every_fleet_repo import _Gateway, _Store as _JobStore
    fal.build_fleet_arbiter_job_factory(
        _Gateway(), _JobStore(), log_fn=lambda e, **f: None,
        worktree_janitor_enabled=True, worktree_refusal_ledger_path=str( tmp_path / "l.json" ) )
    assert callable( captured[ "straggler_fn" ] )
