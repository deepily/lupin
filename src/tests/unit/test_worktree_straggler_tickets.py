"""
The worktree janitor opens ONE store row per tree refused for more than a day, and drops
it when the tree is gone (Rick's ruling, 2026-09-29, broadcast 0457564c).
"""

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import cosa.agents.shared.worktree_straggler_tickets as st

NOW   = datetime( 2026, 9, 29, 14, 0, tzinfo=timezone.utc )
SEAT  = "/repo/lupin/.claude/worktrees/seat-cc-author-mr-radio-1"
HAND  = "/repo/lupin-mobile/.claude/worktrees/tiffany-doc-viewer"


class MemStore:
    """An in-memory store that records every call and honours find_open by key."""

    def __init__( self, fail_create=False, fail_drop=False ):
        self.rows, self.dropped, self.creates = {}, [], 0
        self.fail_create, self.fail_drop = fail_create, fail_drop

    def find_open( self, key ):
        return next( ( i for i, r in self.rows.items() if r[ "correlation_key" ] == key ), None )

    def create( self, **row ):
        if self.fail_create: raise RuntimeError( "db down" )
        self.creates += 1
        i = f"id{len( self.rows )}"
        self.rows[ i ] = row
        return i

    def drop( self, ticket_id, reason ):
        if self.fail_drop: raise RuntimeError( "db down" )
        self.dropped.append( ( ticket_id, reason ) )


class Log:
    def __init__( self ): self.events = []
    def __call__( self, event, **fields ): self.events.append( ( event, fields ) )


def _sync( refused, state, store, log=None, now=NOW, idle=None, exists=lambda p: True, **kw ):
    return st.sync_straggler_tickets( refused, state, store, log or Log(), now=now,
                                      idle_hours_fn=( ( lambda p: idle ) if idle is not None else None ),
                                      exists_fn=exists, **kw )


# ── owner / project / key ─────────────────────────────────────────────────────────────

def test_a_seat_tree_is_owned_by_its_spawning_manager():
    assert st.owner_for_tree( SEAT ) == { "owner": "mr radio", "accountable": "mr radio", "creator_recorded": True }


@pytest.mark.parametrize( "path", [ HAND, "/r/.claude/worktrees/seat-rachel", "/r/.claude/worktrees/seat-cc-author-x" ] )
def test_a_tree_with_no_recorded_creator_goes_to_maria( path ):
    assert st.owner_for_tree( path ) == { "owner": "maria", "accountable": "maria", "creator_recorded": False }


def test_project_is_the_repo_holding_the_tree():
    assert st.project_for_tree( HAND ) == "lupin-mobile"
    assert st.project_for_tree( "/somewhere/else" ) == "lupin"


def test_the_key_is_one_per_tree():
    assert st.straggler_key( SEAT + "/" ) == "worktree:" + SEAT


def test_the_row_names_the_tree_its_blockers_and_the_missing_creator():
    row = st.compose_row( HAND, [ f"f{i}" for i in range( 12 ) ], "2026-09-28T10:00:00+00:00", True )
    assert row[ "title" ] == "[LUPIN-MOBILE] Refused worktree straggler: tiffany-doc-viewer"
    assert HAND in row[ "body" ] and "`f9`" in row[ "body" ] and "`f10`" not in row[ "body" ]
    assert "… and 2 more" in row[ "body" ]
    assert "(estimated from when the tree went idle)" in row[ "body" ]
    assert "No creator recorded" in row[ "body" ]
    assert ( row[ "owner" ], row[ "accountable" ], row[ "project" ] ) == ( "maria", "maria", "lupin-mobile" )
    seat_row = st.compose_row( SEAT, [ "x" ], "t", False )
    assert "No creator recorded" not in seat_row[ "body" ] and "estimated" not in seat_row[ "body" ]


# ── the 24h clock ─────────────────────────────────────────────────────────────────────

def test_a_fresh_refusal_waits_a_day( tmp_path ):
    state, store = str( tmp_path / "s.json" ), MemStore()
    out = _sync( { SEAT: [ "io/x" ] }, state, store )
    assert out[ "pending" ] == 1 and store.creates == 0
    out = _sync( { SEAT: [ "io/x" ] }, state, store, now=NOW + timedelta( hours=23, minutes=59 ) )
    assert out[ "pending" ] == 1 and store.creates == 0
    out = _sync( { SEAT: [ "io/x" ] }, state, store, now=NOW + timedelta( hours=24 ) )
    assert out[ "opened" ] == [ SEAT ] and store.creates == 1


def test_a_first_sighting_is_backdated_by_idle_time_minus_the_janitor_threshold( tmp_path ):
    state, store = str( tmp_path / "s.json" ), MemStore()
    out = _sync( { SEAT: [ "io/x" ] }, state, store, idle=30.0 )     # refused since 24h ago
    assert out[ "opened" ] == [ SEAT ]
    rec = json.load( open( state ) )[ "trees" ][ SEAT ]
    assert rec == { "first_refused_at": "2026-09-28T14:00:00+00:00", "estimated": True, "ticket_id": "id0" }


@pytest.mark.parametrize( "idle", [ 3.0, float( "inf" ) ] )
def test_an_idle_time_that_cannot_backdate_starts_the_clock_now( tmp_path, idle ):
    state = str( tmp_path / "s.json" )
    _sync( { SEAT: [ "io/x" ] }, state, MemStore(), idle=idle )
    assert json.load( open( state ) )[ "trees" ][ SEAT ][ "estimated" ] is False


def test_an_idle_probe_that_raises_starts_the_clock_now( tmp_path ):
    state = str( tmp_path / "s.json" )
    def boom( p ): raise OSError( "gone" )
    st.sync_straggler_tickets( { SEAT: [ "x" ] }, state, MemStore(), Log(), now=NOW, idle_hours_fn=boom,
                               exists_fn=lambda p: True )
    assert json.load( open( state ) )[ "trees" ][ SEAT ][ "first_refused_at" ] == "2026-09-29T14:00:00+00:00"


# ── one row per tree ──────────────────────────────────────────────────────────────────

def test_a_ticketed_tree_is_never_ticketed_twice( tmp_path ):
    state, store = str( tmp_path / "s.json" ), MemStore()
    _sync( { SEAT: [ "io/x" ] }, state, store, idle=40.0 )
    out = _sync( { SEAT: [ "io/x" ] }, state, store, now=NOW + timedelta( hours=5 ) )
    assert store.creates == 1 and out[ "opened" ] == [] and out[ "adopted" ] == []


def test_an_open_row_under_the_key_is_adopted_not_duplicated( tmp_path ):
    state, store = str( tmp_path / "s.json" ), MemStore()
    store.rows[ "pre" ] = { "correlation_key": st.straggler_key( SEAT ) }
    out = _sync( { SEAT: [ "io/x" ] }, state, store, idle=40.0 )
    assert out[ "adopted" ] == [ SEAT ] and store.creates == 0
    assert json.load( open( state ) )[ "trees" ][ SEAT ][ "ticket_id" ] == "pre"


# ── closing ───────────────────────────────────────────────────────────────────────────

def test_a_tree_that_is_gone_has_its_row_dropped_and_leaves_the_sidecar( tmp_path ):
    state, store, log = str( tmp_path / "s.json" ), MemStore(), Log()
    _sync( { SEAT: [ "io/x" ] }, state, store, idle=40.0 )
    out = _sync( {}, state, store, log=log, exists=lambda p: False )
    assert out[ "closed" ] == [ SEAT ]
    assert store.dropped == [ ( "id0", f"worktree {SEAT} absent at 2026-09-29T14:00:00+00:00 (janitor poll)" ) ]
    assert json.load( open( state ) )[ "trees" ] == {}
    assert log.events[ -1 ][ 0 ] == "worktree_straggler_tickets"


def test_a_gone_tree_without_a_row_just_leaves_the_sidecar( tmp_path ):
    state, store = str( tmp_path / "s.json" ), MemStore()
    _sync( { SEAT: [ "io/x" ] }, state, store )                     # pending, no ticket
    out = _sync( {}, state, store, exists=lambda p: False )
    assert out[ "closed" ] == [] and store.dropped == []
    assert json.load( open( state ) )[ "trees" ] == {}


def test_a_tree_still_on_disk_but_not_refused_keeps_its_row( tmp_path ):
    state, store = str( tmp_path / "s.json" ), MemStore()
    _sync( { SEAT: [ "io/x" ] }, state, store, idle=40.0 )
    out = _sync( {}, state, store, exists=lambda p: True )
    assert out[ "closed" ] == [] and store.dropped == []
    assert SEAT in json.load( open( state ) )[ "trees" ]


# ── failure isolation ─────────────────────────────────────────────────────────────────

def test_an_open_failure_is_logged_and_retried_next_poll( tmp_path ):
    state, log = str( tmp_path / "s.json" ), Log()
    out = _sync( { SEAT: [ "io/x" ] }, state, MemStore( fail_create=True ), log=log, idle=40.0 )
    assert out[ "errors" ] == [ f"{SEAT}: open failed: db down" ]
    assert log.events[ 0 ][ 0 ] == "worktree_straggler_open_failed"
    store = MemStore()
    assert _sync( { SEAT: [ "io/x" ] }, state, store )[ "opened" ] == [ SEAT ]


def test_a_close_failure_keeps_the_entry_for_the_next_poll( tmp_path ):
    state, log = str( tmp_path / "s.json" ), Log()
    _sync( { SEAT: [ "io/x" ] }, state, MemStore(), idle=40.0 )
    out = _sync( {}, state, MemStore( fail_drop=True ), log=log, exists=lambda p: False )
    assert out[ "errors" ] == [ f"{SEAT}: close failed: db down" ]
    assert log.events[ 0 ][ 0 ] == "worktree_straggler_close_failed"
    assert SEAT in json.load( open( state ) )[ "trees" ]


def test_a_state_write_failure_is_reported_not_raised( tmp_path ):
    blocker = tmp_path / "file"
    blocker.write_text( "x" )
    log = Log()
    out = _sync( { SEAT: [ "io/x" ] }, str( blocker / "sub" / "s.json" ), MemStore(), log=log )
    assert out[ "errors" ][ 0 ].startswith( "state write failed:" )
    assert log.events[ -1 ][ 0 ] == "worktree_straggler_state_write_failed"


def test_an_unchanged_state_is_not_rewritten( tmp_path ):
    state, store = str( tmp_path / "s.json" ), MemStore()
    _sync( { SEAT: [ "io/x" ] }, state, store, idle=40.0 )
    before = os.stat( state ).st_mtime_ns
    os.utime( state, ns=( before - 10**9, before - 10**9 ) )
    _sync( { SEAT: [ "io/x" ] }, state, store )
    assert os.stat( state ).st_mtime_ns == before - 10**9


@pytest.mark.parametrize( "content", [ "not json", json.dumps( [ 1 ] ), json.dumps( { "trees": [] } ) ] )
def test_a_corrupt_sidecar_reads_as_empty( tmp_path, content ):
    p = tmp_path / "s.json"
    p.write_text( content )
    assert st.load_state( str( p ) ) == {}


def test_the_default_clock_is_now():
    out = st.sync_straggler_tickets( {}, "/nonexistent/dir/s.json", MemStore(), Log() )
    assert out == { "opened": [], "adopted": [], "closed": [], "pending": 0, "errors": [] }


# ── the real store, against a fake repository ─────────────────────────────────────────

class FakeRepo:
    def __init__( self, session ): self.s = session
    def query_tasks( self, correlation_key, limit ):
        self.s.calls.append( ( "query", correlation_key, limit ) )
        return self.s.found
    def create_item( self, **kw ):
        self.s.calls.append( ( "create", kw ) )
        return SimpleNamespace( id="new-id" )
    def get_by_id_for_update( self, item_id ):
        self.s.calls.append( ( "lock", item_id ) )
        return self.s.item
    def apply_transition( self, item, to_status, actor, authority, reason ):
        self.s.calls.append( ( "transition", to_status, actor, authority, reason ) )


@pytest.fixture
def fake_db( monkeypatch ):
    import cosa.rest.db.database as db
    import cosa.rest.db.repositories.task_repository as tr
    session = SimpleNamespace( calls=[], found=[], item=None, flush=lambda: None )
    @contextmanager
    def get_db(): yield session
    monkeypatch.setattr( db, "get_db", get_db )
    monkeypatch.setattr( tr, "TaskRepository", FakeRepo )
    return session


def test_find_open_returns_the_first_live_row( fake_db ):
    store = st.RepositoryStragglerStore()
    assert store.find_open( "worktree:/x" ) is None
    fake_db.found = [ SimpleNamespace( id="abc" ) ]
    assert store.find_open( "worktree:/x" ) == "abc"
    assert fake_db.calls[ 0 ] == ( "query", "worktree:/x", 1 )


def test_create_mints_a_live_row_with_canonical_personas( fake_db ):
    row = st.compose_row( SEAT, [ "io/x" ], "t", False )
    assert st.RepositoryStragglerStore().create( **row ) == "new-id"
    kw = fake_db.calls[ 0 ][ 1 ]
    assert kw[ "status" ] == "queued" and kw[ "authority" ] == "standing"
    assert kw[ "created_by" ] == st.ARBITER_ACTOR and kw[ "priority" ] == "P3"
    assert kw[ "owner_persona" ] == "mr radio" and kw[ "accountable_manager" ] == "mr radio"
    assert kw[ "correlation_key" ] == "worktree:" + SEAT


def test_drop_moves_a_live_row_to_dropped( fake_db ):
    tid = str( uuid.uuid4() )
    fake_db.item = SimpleNamespace( status="queued" )
    st.RepositoryStragglerStore().drop( tid, "gone" )
    assert fake_db.calls == [ ( "lock", uuid.UUID( tid ) ),
                              ( "transition", "dropped", st.ARBITER_ACTOR, "standing", "gone" ) ]


@pytest.mark.parametrize( "item", [ None, SimpleNamespace( status="done" ), SimpleNamespace( status="dropped" ) ] )
def test_drop_leaves_a_missing_or_terminal_row_alone( fake_db, item ):
    fake_db.item = item
    st.RepositoryStragglerStore().drop( str( uuid.uuid4() ), "gone" )
    assert [ c[ 0 ] for c in fake_db.calls ] == [ "lock" ]


def test_quick_smoke_test_passes( capsys ):
    st.quick_smoke_test()
    assert "✓" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
