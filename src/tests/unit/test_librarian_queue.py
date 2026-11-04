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
        self.created       = []
        self.amended       = []

    def query( self, correlation_key ):
        self.queried = correlation_key
        return self.query_result or ( True, 200, { "tasks": self.rows } )

    def create( self, payload ):
        self.created.append( payload )
        return self.create_result

    def amend( self, item_id, note ):
        self.amended.append( ( item_id, note ) )
        return self.amend_result



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


def test_read_fingerprint_takes_the_last_line_because_an_amendment_appends_to_the_body():
    original = "head\nrollup-fingerprint: " + "a" * 40
    amended  = original + "\n\n[amendment]\nnew text\nrollup-fingerprint: " + "b" * 40
    assert lq.read_fingerprint( amended ) == "b" * 40


def test_a_rollup_amended_once_is_unchanged_on_the_next_run_and_amends_only_once(tmp_path):
    first   = [ ORPHAN ]
    second  = [ ORPHAN, dict( ORPHAN, symbol="cosa.rest.z.Z" ) ]
    title, original = lq.render_rollup( "cosa.rest", first )
    _, new_body     = lq.render_rollup( "cosa.rest", second )
    stored          = original + "\n\n[amendment]\n" + new_body
    store           = FakeStore( [ { "id": "id-1", "title": title, "body": stored } ] )
    lib, _          = make( tmp_path, store )
    counts          = lib.sync( second, "idx" )
    assert counts[ "unchanged" ] == 1 and counts[ "amended" ] == 0 and store.amended == []


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
    counts = lib.sync( [ STALE, ORPHAN, UNIDX ], "idx" )
    assert counts == { "created": 3, "amended": 0, "unchanged": 0, "cleared": 0, "waiting": 0, "deferred": 0, "pending": 0 }
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
    counts  = lib.sync( [ STALE, ORPHAN, dict( ORPHAN, symbol="cosa.rest.z.Z" ) ], "idx" )
    assert counts[ "unchanged" ] == 1 and counts[ "amended" ] == 1 and counts[ "created" ] == 0
    assert store.amended[ 0 ][ 0 ] == "id-changed"
    assert "orphan 2" in store.amended[ 0 ][ 1 ]


def test_a_failed_amend_is_logged_and_not_counted(tmp_path):
    store              = FakeStore( [ row_for( "cosa.rest", [ ORPHAN ], "id-x" ) ] )
    store.amend_result = ( False, 500, { "error": "boom" } )
    lib, lines         = make( tmp_path, store )
    counts             = lib.sync( [ ORPHAN, dict( ORPHAN, symbol="cosa.rest.z.Z" ) ], "idx" )
    assert counts[ "amended" ] == 0
    assert any( "amend failed" in line for line in lines )


def test_a_clean_package_gets_one_clear_notice_and_the_manager_is_told_and_nothing_is_closed(tmp_path):
    rollup = row_for( "cosa.rest", [ ORPHAN ], "id-old" )
    miss   = { "id": "id-miss", "title": lq.MISS_PREFIX + "pkg.sym", "body": "x" }
    other  = { "id": "id-other", "title": "[LUPIN] something else", "body": "" }
    store  = FakeStore( [ rollup, miss, other ] )
    said   = []
    lib    = lq.Librarian( store, str( tmp_path / "pending.jsonl" ), lambda line: None, notify=said.append )
    counts = lib.sync( [], "idx-1" )
    assert counts[ "cleared" ] == 1 and counts[ "waiting" ] == 0
    assert [ item for item, _ in store.amended ] == [ "id-old" ]
    note = store.amended[ 0 ][ 1 ]
    assert note.startswith( lq.CLEARED_TAG + " idx-1" ) and "manager_attestation" in note
    assert not hasattr( store, "close" ) and len( said ) == 1 and "close each with a manager_attestation" in said[ 0 ]


def test_a_cleared_rollup_is_waiting_on_the_next_run_and_is_not_amended_again(tmp_path):
    rollup = row_for( "cosa.rest", [ ORPHAN ], "id-old" )
    rollup[ "body" ] += "\n\n[amendment]\n" + lq.clear_note( "cosa.rest", "idx-1" )
    store  = FakeStore( [ rollup ] )
    lib, _ = make( tmp_path, store )
    counts = lib.sync( [], "idx-2" )
    assert counts[ "waiting" ] == 1 and counts[ "cleared" ] == 0 and store.amended == []


def test_findings_that_return_after_a_clear_notice_amend_the_rollup_even_with_the_same_fingerprint(tmp_path):
    rollup = row_for( "cosa.rest", [ ORPHAN ], "id-old" )
    rollup[ "body" ] += "\n\n[amendment]\n" + lq.clear_note( "cosa.rest", "idx-1" )
    store  = FakeStore( [ rollup ] )
    lib, _ = make( tmp_path, store )
    counts = lib.sync( [ ORPHAN ], "idx-2" )
    assert counts[ "amended" ] == 1 and counts[ "unchanged" ] == 0
    assert not lq.is_cleared( rollup[ "body" ] + "\n\n[amendment]\n" + store.amended[ 0 ][ 1 ] )


def test_a_failed_clear_notice_is_logged_and_not_counted(tmp_path):
    store              = FakeStore( [ row_for( "cosa.rest", [ ORPHAN ], "id-old" ) ] )
    store.amend_result = ( False, 500, "no" )
    lib, lines         = make( tmp_path, store )
    assert lib.sync( [], "idx" )[ "cleared" ] == 0
    assert any( "clear notice failed" in line for line in lines )


def test_the_closing_receipt_passes_the_stores_own_rule_and_a_file_receipt_alone_does_not():
    from cosa.rest.task_store_rules import validate_receipt_refs
    assert validate_receipt_refs( lq.closing_receipt( "cosa.rest", "idx-1" ), require_checkable=True ) == []
    assert validate_receipt_refs( { "log_line": "lupin/src/x.py:1" }, require_checkable=True ) != []
    assert validate_receipt_refs( {}, require_checkable=True ) != []
    assert len( lq.closing_receipt( "p" * 400, "idx" )[ "manager_attestation" ] ) == 255


def test_is_cleared_reads_the_last_notice_against_the_last_fingerprint():
    fp = lq.FINGERPRINT_TAG + " " + "a" * 40
    assert lq.is_cleared( None ) is False and lq.is_cleared( fp ) is False
    assert lq.is_cleared( fp + "\n" + lq.CLEARED_TAG + " s" ) is True
    assert lq.is_cleared( fp + "\n" + lq.CLEARED_TAG + " s\n" + fp ) is False
    assert lq.is_cleared( lq.CLEARED_TAG + " s" ) is True


def test_owner_and_manager_are_two_settings_on_the_created_row(tmp_path):
    store = FakeStore()
    lib   = lq.Librarian( store, str( tmp_path / "pending.jsonl" ), lambda line: None, owner="tiffany", manager="rio" )
    lib.sync( [ ORPHAN ], "idx" )
    assert store.created[ 0 ][ "owner_persona" ] == "tiffany" and store.created[ 0 ][ "accountable_manager" ] == "rio"


def test_a_refused_create_goes_to_the_pending_file_and_notifies_once(tmp_path):
    store               = FakeStore()
    store.create_result = ( False, 422, { "detail": "ratio" } )
    said                = []
    lib, lines          = make( tmp_path, store, notify=said.append )
    counts              = lib.sync( [ STALE, ORPHAN ], "idx" )
    assert counts[ "pending" ] == 2 and counts[ "created" ] == 0
    assert len( lq.read_pending( lib.pending_path ) ) == 2
    assert len( said ) == 1 and "2 wiki-librarian rows" in said[ 0 ]
    assert any( "create held" in line for line in lines )


def test_a_refused_create_without_a_notify_callable_still_holds_the_row(tmp_path):
    store               = FakeStore()
    store.create_result = ( False, 422, "ratio" )
    lib, _              = make( tmp_path, store )
    assert lib.sync( [ ORPHAN ], "idx" )[ "pending" ] == 1


def test_a_held_row_survives_a_restart_and_is_created_on_the_next_run_once(tmp_path):
    refusing               = FakeStore()
    refusing.create_result = ( False, 422, "ratio" )
    first, _               = make( tmp_path, refusing )
    first.sync( [ ORPHAN ], "idx" )
    assert len( lq.read_pending( first.pending_path ) ) == 1
    accepting              = FakeStore()
    second, _              = make( tmp_path, accepting )
    counts                 = second.sync( [ ORPHAN ], "idx" )
    assert counts[ "created" ] == 1 and counts[ "pending" ] == 0
    assert len( accepting.created ) == 1
    assert not os.path.exists( second.pending_path )


def test_a_pending_entry_that_is_still_refused_is_kept_once_even_when_the_package_is_still_dirty(tmp_path):
    store               = FakeStore()
    store.create_result = ( False, 422, "ratio" )
    lib, _              = make( tmp_path, store )
    lib.sync( [ ORPHAN ], "idx" )
    again, _            = make( tmp_path, store )
    counts              = again.sync( [ ORPHAN ], "idx" )
    assert counts[ "pending" ] == 1
    assert len( lq.read_pending( again.pending_path ) ) == 1


def test_a_pending_entry_whose_row_now_exists_is_dropped(tmp_path):
    title, body = lq.render_rollup( "cosa.rest", [ ORPHAN ] )
    lq.write_pending( str( tmp_path / "pending.jsonl" ), [ { "title": title, "body": body, "status": 422 } ] )
    store  = FakeStore( [ { "id": "id-1", "title": title, "body": body } ] )
    lib, _ = make( tmp_path, store )
    counts = lib.sync( [ ORPHAN ], "idx" )
    assert counts == { "created": 0, "amended": 0, "unchanged": 1, "cleared": 0, "waiting": 0, "deferred": 0, "pending": 0 }
    assert store.created == []
    assert not os.path.exists( lib.pending_path )


def test_an_unreadable_store_raises_and_leaves_the_pending_file_alone(tmp_path):
    path = str( tmp_path / "pending.jsonl" )
    lq.write_pending( path, [ { "title": "t", "body": "b", "status": 422 } ] )
    store              = FakeStore()
    store.query_result = ( False, None, { "error": "down" } )
    lib, _             = make( tmp_path, store )
    with pytest.raises( RuntimeError, match="query failed" ):
        lib.sync( [ ORPHAN ], "idx" )
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


def many( n ):
    return [ dict( ORPHAN, package=f"pkg.p{i}", symbol=f"pkg.p{i}.m.f" ) for i in range( n ) ]


def test_the_create_cap_defers_the_rest_without_pending_or_a_notice(tmp_path):
    store  = FakeStore()
    said   = []
    lib    = lq.Librarian( store, str( tmp_path / "pending.jsonl" ), lambda line: None, notify=said.append, max_creates=2 )
    counts = lib.sync( many( 5 ), "idx" )
    assert counts[ "created" ] == 2 and counts[ "deferred" ] == 3 and counts[ "pending" ] == 0
    assert len( store.created ) == 2 and said == [] and not os.path.exists( lib.pending_path )


def test_a_cap_run_drains_the_backlog_over_several_runs(tmp_path):
    findings = many( 5 )
    titles   = set()
    for _ in range( 3 ):
        store = FakeStore( [ { "id": f"i{n}", "title": t, "body": lq.render_rollup( t[ len( lq.ROLLUP_PREFIX ): ], [ f for f in findings if f[ "package" ] == t[ len( lq.ROLLUP_PREFIX ): ] ] )[ 1 ] } for n, t in enumerate( sorted( titles ) ) ] )
        lib   = lq.Librarian( store, str( tmp_path / "pending.jsonl" ), lambda line: None, max_creates=2 )
        lib.sync( findings, "idx" )
        titles |= { p[ "title" ] for p in store.created }
    assert len( titles ) == 5


def test_refused_attempts_spend_the_cap_and_pending_entries_are_retried_first(tmp_path):
    held = lq.render_rollup( "pkg.p0", [ dict( ORPHAN, package="pkg.p0", symbol="pkg.p0.m.f" ) ] )
    lq.write_pending( str( tmp_path / "pending.jsonl" ), [ { "title": held[ 0 ], "body": held[ 1 ], "status": 422 } ] )
    store               = FakeStore()
    store.create_result = ( False, 422, "ratio" )
    lib                 = lq.Librarian( store, str( tmp_path / "pending.jsonl" ), lambda line: None, max_creates=2 )
    counts              = lib.sync( many( 4 ), "idx" )
    assert len( store.created ) == 2 and store.created[ 0 ][ "title" ] == held[ 0 ]
    assert counts[ "deferred" ] == 2 and counts[ "pending" ] == 2


def test_a_pending_entry_the_cap_keeps_back_stays_in_the_file_untouched(tmp_path):
    entry = { "title": lq.ROLLUP_PREFIX + "pkg.p0", "body": "b", "status": 422 }
    lq.write_pending( str( tmp_path / "pending.jsonl" ), [ entry ] )
    store = FakeStore()
    lib   = lq.Librarian( store, str( tmp_path / "pending.jsonl" ), lambda line: None, max_creates=0 )
    counts = lib.sync( [], "idx" )
    assert counts[ "deferred" ] == 1 and counts[ "pending" ] == 1 and store.created == []
    assert lq.read_pending( lib.pending_path ) == [ entry ]


def test_a_miss_row_is_not_counted_against_the_cap(tmp_path):
    lib = lq.Librarian( FakeStore(), str( tmp_path / "pending.jsonl" ), lambda line: None, max_creates=0 )
    assert lib.hold_or_create( lq.MISS_PREFIX + "pkg.sym", "b" ) == "created"


def test_a_failed_manager_notice_is_logged_for_a_clear_and_for_a_refused_create(tmp_path):
    rollup = row_for( "cosa.rest", [ ORPHAN ], "id-old" )
    lib, lines = make( tmp_path, FakeStore( [ rollup ] ), notify=lambda text: False )
    lib.sync( [], "idx-1" )
    assert any( "manager notice failed" in line and "are clear" in line for line in lines )
    refusing = FakeStore()
    refusing.create_result = ( False, 422, "ratio" )
    lib, lines = make( tmp_path, refusing, notify=lambda text: False )
    lib.sync( [ ORPHAN ], "idx" )
    assert any( "manager notice failed" in line and "not created" in line for line in lines )


def test_a_rollup_still_waiting_for_its_close_notifies_the_manager_again_each_run(tmp_path):
    rollup = row_for( "cosa.rest", [ ORPHAN ], "id-old" )
    rollup[ "body" ] += "\n\n[amendment]\n" + lq.clear_note( "cosa.rest", "idx-1" )
    said = []
    lib, _ = make( tmp_path, FakeStore( [ rollup ] ), notify=said.append )
    assert lib.sync( [], "idx-2" )[ "waiting" ] == 1
    assert len( said ) == 1 and "1 wiki-librarian rollup" in said[ 0 ] and "still clear" in said[ 0 ]


# ---- two corpora, one store ----


class KeyedStore( FakeStore ):
    """Answers each query with only the rows under the asked correlation key."""

    def __init__( self, rows ):
        super().__init__( rows )
        self.queries = []

    def query( self, correlation_key ):
        self.queries.append( correlation_key )
        return True, 200, { "tasks": [ r for r in self.rows if r[ "correlation_key" ] == correlation_key ] }


def mobile_lib( tmp_path, store ):
    return lq.Librarian( store, str( tmp_path / "pending-mobile.jsonl" ), lambda line: None, owner="tiffany", manager="tiffany",
                         correlation_key=lq.MOBILE_CORRELATION_KEY, rollup_prefix=lq.MOBILE_ROLLUP_PREFIX )


def test_mobile_prefix_and_key_differ_from_lupins_and_the_lupin_prefix_does_not_match_a_mobile_title():
    assert lq.MOBILE_CORRELATION_KEY.startswith( "epic:" ) and lq.MOBILE_CORRELATION_KEY != lq.CORRELATION_KEY
    assert not lq.MOBILE_ROLLUP_PREFIX.startswith( lq.ROLLUP_PREFIX ) and not lq.ROLLUP_PREFIX.startswith( lq.MOBILE_ROLLUP_PREFIX )


def test_render_rollup_takes_the_corpus_prefix_and_defaults_to_lupins():
    assert lq.render_rollup( "lib.ui", [ ORPHAN ], lq.MOBILE_ROLLUP_PREFIX )[ 0 ] == lq.MOBILE_ROLLUP_PREFIX + "lib.ui"
    assert lq.render_rollup( "lib.ui", [ ORPHAN ] )[ 0 ] == lq.ROLLUP_PREFIX + "lib.ui"


def test_a_mobile_rollup_is_created_for_the_mobile_owner_under_the_mobile_key_and_title( tmp_path ):
    store = KeyedStore( [] )
    counts = mobile_lib( tmp_path, store ).sync( [ dict( ORPHAN, package="lib.ui" ) ], "dart-sha" )
    assert counts[ "created" ] == 1 and store.queries == [ lq.MOBILE_CORRELATION_KEY ]
    made = store.created[ 0 ]
    assert made[ "owner_persona" ] == "tiffany" and made[ "accountable_manager" ] == "tiffany"
    assert made[ "correlation_key" ] == lq.MOBILE_CORRELATION_KEY and made[ "title" ] == lq.MOBILE_ROLLUP_PREFIX + "lib.ui"


def test_a_lupin_rollup_is_still_created_for_the_lupin_owner_under_the_lupin_key( tmp_path ):
    store = KeyedStore( [] )
    lib, _ = make( tmp_path, store )
    lib.sync( [ ORPHAN ], "sha" )
    made = store.created[ 0 ]
    assert made[ "owner_persona" ] == "cheech" and made[ "correlation_key" ] == lq.CORRELATION_KEY and made[ "title" ].startswith( lq.ROLLUP_PREFIX )


def test_neither_corpus_clears_or_amends_the_other_corpus_rollups( tmp_path ):
    mobile_row = { **row_for( "lib.ui", [ dict( ORPHAN, package="lib.ui" ) ], "m1" ), "correlation_key": lq.MOBILE_CORRELATION_KEY }
    mobile_row[ "title" ] = lq.MOBILE_ROLLUP_PREFIX + "lib.ui"
    lupin_row  = { **row_for( "cosa.rest", [ ORPHAN ], "l1" ), "correlation_key": lq.CORRELATION_KEY }
    store = KeyedStore( [ mobile_row, lupin_row ] )
    lib, _ = make( tmp_path, store )
    counts = lib.sync( [ ORPHAN ], "sha" )                                  # lupin sync with a finding for cosa.rest only
    assert counts[ "cleared" ] == 0 and counts[ "unchanged" ] == 1 and store.amended == [] and store.created == []
    empty = KeyedStore( [ mobile_row, lupin_row ] )
    mobile_lib( tmp_path, empty ).sync( [], "dart-sha" )                    # mobile sync with no findings clears only its own row
    assert [ item for item, _ in empty.amended ] == [ "m1" ]


def test_clearing_a_mobile_rollup_names_the_bare_package_in_the_note( tmp_path ):
    title, body = lq.render_rollup( "lib.ui", [ dict( ORPHAN, package="lib.ui" ) ], lq.MOBILE_ROLLUP_PREFIX )
    store = KeyedStore( [ { "id": "m1", "title": title, "body": body, "correlation_key": lq.MOBILE_CORRELATION_KEY } ] )
    mobile_lib( tmp_path, store ).sync( [], "dart-sha" )
    assert store.amended == [ ( "m1", lq.clear_note( "lib.ui", "dart-sha" ) ) ]
    assert "for lib.ui at index" in store.amended[ 0 ][ 1 ]
