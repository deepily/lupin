"""
Unit tests for the wiki-librarian queue: rollups, pending file and sync.

Venue: :7999-eligible. The store is a fake that records every call; nothing touches the network.
"""
import json
import os

import pytest

from cosa.repo.symindex import librarian_queue as lq

STALE   = { "kind": "stale", "page": "doc-lint-gate", "symbol": "cosa.repo.doc_lint.gate.main", "was": "a", "now": "b" }
ORPHAN  = { "kind": "orphan", "symbol": "cosa.rest.x.Y", "package": "cosa.rest" }
NOPAGE  = { "kind": "orphan_package", "package": "cosa.utils", "count": 4 }
UNIDX   = { "kind": "unindexed", "page": "lonely" }


class FakeStore:
    """Records calls and answers from settable results."""

    def __init__( self, rows=None ):
        self.rows          = rows or []
        self.query_result  = None
        self.create_result = ( True, 201, {} )
        self.amend_result  = ( True, 200, {} )
        self.close_result  = ( True, 200, {} )
        self.created       = []
        self.amended       = []
        self.closed        = []

    def query( self, correlation_key ):
        self.queried = correlation_key
        return self.query_result or ( True, 200, { "tasks": self.rows } )

    def create( self, payload ):
        self.created.append( payload )
        return self.create_result

    def amend( self, item_id, note ):
        self.amended.append( ( item_id, note ) )
        return self.amend_result

    def close( self, item_id, reason ):
        self.closed.append( ( item_id, reason ) )
        return self.close_result


def make( tmp_path, store=None, notify=None ):
    lines = []
    lib   = lq.Librarian( store or FakeStore(), str( tmp_path / "pending.jsonl" ), lines.append, notify=notify )
    return lib, lines


def row_for( package, findings, row_id="id-1" ):
    title, body = lq.render_rollup( package, findings )
    return { "id": row_id, "title": title, "body": body }


def test_finding_package_reads_the_package_key_then_the_symbol_then_falls_back_to_wiki():
    assert lq.finding_package( ORPHAN ) == "cosa.rest"
    assert lq.finding_package( STALE ) == "cosa.repo"
    assert lq.finding_package( UNIDX ) == lq.WIKI_PACKAGE


def test_group_by_package_keeps_input_order_and_an_empty_list_gives_an_empty_dict():
    groups = lq.group_by_package( [ STALE, ORPHAN, NOPAGE, UNIDX, dict( STALE, symbol="cosa.repo.x.y" ) ] )
    assert list( groups ) == [ "cosa.repo", "cosa.rest", "cosa.utils", "wiki" ]
    assert len( groups[ "cosa.repo" ] ) == 2
    assert lq.group_by_package( [] ) == {}


def test_fingerprint_ignores_order_and_changes_with_content():
    assert lq.fingerprint( [ STALE, ORPHAN ] ) == lq.fingerprint( [ ORPHAN, STALE ] )
    assert lq.fingerprint( [ STALE ] ) != lq.fingerprint( [ dict( STALE, now="c" ) ] )
    assert len( lq.fingerprint( [] ) ) == 40


def test_render_rollup_counts_kinds_lists_details_and_ends_with_the_fingerprint():
    title, body = lq.render_rollup( "cosa.rest", [ ORPHAN, STALE, ORPHAN ] )
    assert title == lq.ROLLUP_PREFIX + "cosa.rest"
    assert "orphan 2, stale 1" in body
    assert "- stale page=doc-lint-gate symbol=cosa.repo.doc_lint.gate.main" in body
    assert "more" not in body
    assert lq.read_fingerprint( body ) == lq.fingerprint( [ ORPHAN, STALE, ORPHAN ] )


def test_render_rollup_cuts_the_detail_list_and_says_how_many_more():
    findings = [ dict( ORPHAN, symbol=f"cosa.rest.m.f{i}" ) for i in range( lq.DETAIL_LIMIT + 7 ) ]
    body     = lq.render_rollup( "cosa.rest", findings )[ 1 ]
    assert body.count( "\n- orphan" ) == lq.DETAIL_LIMIT
    assert "- and 7 more" in body


def test_read_fingerprint_handles_none_missing_and_present():
    assert lq.read_fingerprint( None ) is None
    assert lq.read_fingerprint( "no line here" ) is None
    assert lq.read_fingerprint( "x\nrollup-fingerprint: " + "a" * 40 + "\n" ) == "a" * 40


def test_pending_file_round_trips_skips_bad_lines_and_empty_removes_it(tmp_path):
    path = str( tmp_path / "sub" / "pending.jsonl" )
    assert lq.read_pending( path ) == []
    lq.write_pending( path, [] )
    lq.write_pending( path, [ { "title": "a", "body": "b", "status": 422 } ] )
    with open( path, "a", encoding="utf-8" ) as handle: handle.write( "not json\n[1, 2]\n" )
    assert lq.read_pending( path ) == [ { "title": "a", "body": "b", "status": 422 } ]
    assert not os.path.exists( path + ".tmp" )
    lq.write_pending( path, [] )
    assert not os.path.exists( path )


def test_sync_creates_one_row_per_package_under_the_epic_key(tmp_path):
    store = FakeStore()
    lib, _ = make( tmp_path, store )
    counts = lib.sync( [ STALE, ORPHAN, UNIDX ] )
    assert counts == { "created": 3, "amended": 0, "unchanged": 0, "closed": 0, "pending": 0 }
    assert store.queried == lq.CORRELATION_KEY
    assert sorted( p[ "title" ] for p in store.created ) == sorted( lq.ROLLUP_PREFIX + n for n in ( "cosa.repo", "cosa.rest", "wiki" ) )
    assert { p[ "correlation_key" ] for p in store.created } == { "epic:wiki-librarian" }
    assert { p[ "owner_persona" ] for p in store.created } == { "cheech" }
    assert not os.path.exists( lib.pending_path )


def test_sync_leaves_an_unchanged_rollup_alone_and_amends_a_changed_one(tmp_path):
    same    = row_for( "cosa.repo", [ STALE ], "id-same" )
    changed = row_for( "cosa.rest", [ ORPHAN ], "id-changed" )
    store   = FakeStore( [ same, changed ] )
    lib, _  = make( tmp_path, store )
    counts  = lib.sync( [ STALE, ORPHAN, dict( ORPHAN, symbol="cosa.rest.z.Z" ) ] )
    assert counts[ "unchanged" ] == 1 and counts[ "amended" ] == 1 and counts[ "created" ] == 0
    assert store.amended[ 0 ][ 0 ] == "id-changed"
    assert "orphan 2" in store.amended[ 0 ][ 1 ]


def test_a_failed_amend_is_logged_and_not_counted(tmp_path):
    store              = FakeStore( [ row_for( "cosa.rest", [ ORPHAN ], "id-x" ) ] )
    store.amend_result = ( False, 500, { "error": "boom" } )
    lib, lines         = make( tmp_path, store )
    counts             = lib.sync( [ ORPHAN, dict( ORPHAN, symbol="cosa.rest.z.Z" ) ] )
    assert counts[ "amended" ] == 0
    assert any( "amend failed" in line for line in lines )


def test_a_rollup_whose_package_is_clean_is_closed_and_a_miss_row_is_not(tmp_path):
    rollup = row_for( "cosa.rest", [ ORPHAN ], "id-old" )
    miss   = { "id": "id-miss", "title": lq.MISS_PREFIX + "pkg.sym", "body": "x" }
    other  = { "id": "id-other", "title": "[LUPIN] something else", "body": "" }
    store  = FakeStore( [ rollup, miss, other ] )
    lib, _ = make( tmp_path, store )
    counts = lib.sync( [] )
    assert counts[ "closed" ] == 1
    assert store.closed == [ ( "id-old", "the package has no wiki lint findings" ) ]


def test_a_failed_close_is_logged_and_not_counted(tmp_path):
    store              = FakeStore( [ row_for( "cosa.rest", [ ORPHAN ], "id-old" ) ] )
    store.close_result = ( False, 409, "no" )
    lib, lines         = make( tmp_path, store )
    assert lib.sync( [] )[ "closed" ] == 0
    assert any( "close failed" in line for line in lines )


def test_a_refused_create_goes_to_the_pending_file_and_notifies_once(tmp_path):
    store               = FakeStore()
    store.create_result = ( False, 422, { "detail": "ratio" } )
    said                = []
    lib, lines          = make( tmp_path, store, notify=said.append )
    counts              = lib.sync( [ STALE, ORPHAN ] )
    assert counts[ "pending" ] == 2 and counts[ "created" ] == 0
    assert len( lq.read_pending( lib.pending_path ) ) == 2
    assert len( said ) == 1 and "2 wiki-librarian rows" in said[ 0 ]
    assert any( "create held" in line for line in lines )


def test_a_refused_create_without_a_notify_callable_still_holds_the_row(tmp_path):
    store               = FakeStore()
    store.create_result = ( False, 422, "ratio" )
    lib, _              = make( tmp_path, store )
    assert lib.sync( [ ORPHAN ] )[ "pending" ] == 1


def test_a_held_row_survives_a_restart_and_is_created_on_the_next_run_once(tmp_path):
    refusing               = FakeStore()
    refusing.create_result = ( False, 422, "ratio" )
    first, _               = make( tmp_path, refusing )
    first.sync( [ ORPHAN ] )
    assert len( lq.read_pending( first.pending_path ) ) == 1
    accepting              = FakeStore()
    second, _              = make( tmp_path, accepting )
    counts                 = second.sync( [ ORPHAN ] )
    assert counts[ "created" ] == 1 and counts[ "pending" ] == 0
    assert len( accepting.created ) == 1
    assert not os.path.exists( second.pending_path )


def test_a_pending_entry_that_is_still_refused_is_kept_once_even_when_the_package_is_still_dirty(tmp_path):
    store               = FakeStore()
    store.create_result = ( False, 422, "ratio" )
    lib, _              = make( tmp_path, store )
    lib.sync( [ ORPHAN ] )
    again, _            = make( tmp_path, store )
    counts              = again.sync( [ ORPHAN ] )
    assert counts[ "pending" ] == 1
    assert len( lq.read_pending( again.pending_path ) ) == 1


def test_a_pending_entry_whose_row_now_exists_is_dropped(tmp_path):
    title, body = lq.render_rollup( "cosa.rest", [ ORPHAN ] )
    lq.write_pending( str( tmp_path / "pending.jsonl" ), [ { "title": title, "body": body, "status": 422 } ] )
    store  = FakeStore( [ { "id": "id-1", "title": title, "body": body } ] )
    lib, _ = make( tmp_path, store )
    counts = lib.sync( [ ORPHAN ] )
    assert counts == { "created": 0, "amended": 0, "unchanged": 1, "closed": 0, "pending": 0 }
    assert store.created == []
    assert not os.path.exists( lib.pending_path )


def test_an_unreadable_store_raises_and_leaves_the_pending_file_alone(tmp_path):
    path = str( tmp_path / "pending.jsonl" )
    lq.write_pending( path, [ { "title": "t", "body": "b", "status": 422 } ] )
    store              = FakeStore()
    store.query_result = ( False, None, { "error": "down" } )
    lib, _             = make( tmp_path, store )
    with pytest.raises( RuntimeError, match="query failed" ):
        lib.sync( [ ORPHAN ] )
    assert len( lq.read_pending( path ) ) == 1


def test_hold_or_create_reports_exists_created_and_pending(tmp_path):
    title = lq.MISS_PREFIX + "pkg.sym"
    lib, _ = make( tmp_path, FakeStore( [ { "id": "i", "title": title, "body": "" } ] ) )
    assert lib.hold_or_create( title, "b" ) == "exists"
    lib, _ = make( tmp_path, FakeStore() )
    assert lib.hold_or_create( title, "b" ) == "created"
    refusing               = FakeStore()
    refusing.create_result = ( False, 422, "ratio" )
    lib, _                 = make( tmp_path, refusing )
    assert lib.hold_or_create( title, "b" ) == "pending"
    assert lib.hold_or_create( title, "b" ) == "pending"
    assert [ e[ "title" ] for e in lq.read_pending( lib.pending_path ) ] == [ title ]
