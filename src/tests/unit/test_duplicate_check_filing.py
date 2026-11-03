"""The filing of duplicate rows, with every store write faked."""
import json
import re

import pytest

from cosa.rest import task_store_rules as rules
from lupin_mcp import duplicate_check_filing as ff

WINDOW = { "start": "aaa", "end": "bbb", "commits": 1 }


def finding( ident="d-1", name="a1", text="def a1(): pass", session="s-1", others=None ):
    """Ensures: returns one finding in the shape file_findings takes."""
    return { "id": ident, "name": name, "file": f"client/{name}.py", "line": 3, "text": text, "session_id": session, "window": WINDOW,
             "others": others if others is not None else [ { "id": "d-9", "name": "twin", "file": "server/twin.py" } ] }


class Store:
    """A store that keeps rows in memory and can fail the way the real one does."""

    def __init__( self, create=None, query=None ):
        self.rows, self.created, self.probes = {}, [], []
        self.on_create, self.on_query = create, query

    def query( self, key ):
        self.probes.append( key )
        if self.on_query is not None: return self.on_query
        hit = key in self.rows
        return True, 200, { "tasks": [ self.rows[ key ] ] if hit else [], "count": 1 if hit else 0 }

    def create( self, payload ):
        self.created.append( payload )
        if self.on_create is not None: return self.on_create
        self.rows[ payload[ "correlation_key" ] ] = payload
        return True, 201, payload


def resolver( source, persona="Tiberius" ):
    """Ensures: returns a stand-in resolver that answers the given source."""
    return lambda session_id, declared_manager=None: { "manager_session_id": "m", "manager_persona": persona if source == "lineage" else declared_manager, "source": source }


def run_once( tmp_path, findings, store, resolve=None, declared="Cheech", roster=( "Cheech", "Tiberius" ) ):
    """Ensures: files the findings in the folder and returns the summary."""
    return ff.file_findings( findings, tmp_path, store, declared, list( roster ), resolve or resolver( "lineage" ) )


def test_the_key_is_the_definition_id_and_text_hash_never_the_day_and_matches_the_epic_pattern():
    key = ff.correlation_key( "d-1", "def a(): pass" )
    assert re.fullmatch( r"epic:[a-z0-9._-]+", key ) and key.startswith( "epic:dupcheck-" ) and len( key ) == len( "epic:dupcheck-" ) + 16
    assert key == ff.correlation_key( "d-1", "def a(): pass" ) and key != ff.correlation_key( "d-2", "def a(): pass" ) and key != ff.correlation_key( "d-1", "def a(): pass  " )
    assert ff.content_hash( "x" ) == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"


def test_a_seat_with_a_lineage_manager_sends_the_row_to_that_manager():
    got = ff.manager_for( "s-1", "Cheech", [ "Cheech" ], resolver( "lineage", "Tiberius" ) )
    assert got == { "manager": "Tiberius", "rung": "lineage", "note": "manager found from the seat's spawn lineage" }


def test_a_reaped_seat_falls_to_the_configured_manager_when_the_roster_names_them_whatever_the_case_or_accent():
    got = ff.manager_for( "s-1", "María", [ "maria", "Cheech" ], resolver( "declared" ) )
    assert got[ "rung" ] == "declared" and got[ "manager" ] == "María"


def test_a_configured_manager_that_is_not_on_the_roster_is_unresolved_and_still_the_owner():
    got = ff.manager_for( "s-1", "manager-on-duty", [ "Cheech" ], resolver( "declared" ) )
    assert got == { "manager": "manager-on-duty", "rung": "unresolved", "note": "manager unresolved" }


def test_no_session_at_all_is_unresolved_and_never_asks_the_resolver():
    def never( *a, **k ): pytest.fail( "the resolver was asked" )
    assert ff.manager_for( None, "Cheech", [ "Cheech" ], never )[ "rung" ] == "unresolved"
    assert ff.manager_for( "s-1", "Cheech", [ "Cheech" ], resolver( "unresolved" ) )[ "rung" ] == "unresolved"


def test_the_row_is_p5_with_no_status_a_fixed_creator_with_no_session_and_the_manager_as_owner():
    f   = finding()
    row = ff.row_payload( f, { "manager": "Tiberius", "rung": "lineage", "note": "n" } )
    assert row[ "priority" ] == "P5" and "status" not in row and row[ "created_by" ] == ff.CREATED_BY
    assert not re.search( r"[0-9a-f]{8}-[0-9a-f]{4}", row[ "created_by" ] ), "no session id: the store must read the caller as a worker"
    assert row[ "owner_persona" ] == row[ "accountable_manager" ] == "Tiberius" and row[ "correlation_key" ] == ff.correlation_key( "d-1", f[ "text" ] )
    assert "lineage" in row[ "body" ] and "twin" in row[ "body" ] and "aaa..bbb" in row[ "body" ] and row[ "item_class" ] == "task"


def test_a_seeded_duplicate_files_one_row_and_a_second_run_and_the_next_days_run_file_none( tmp_path ):
    store = Store()
    first = run_once( tmp_path, [ finding() ], store )
    assert len( first[ "filed" ] ) == 1 and len( store.created ) == 1
    for _ in range( 2 ):                                                                   # the same day, then the next
        again = run_once( tmp_path, [ finding() ], store )
        assert again[ "filed" ] == [ ] and len( again[ "already_filed" ] ) == 1
    assert len( store.created ) == 1


def test_a_changed_text_is_a_new_key_and_files_a_new_row( tmp_path ):
    store = Store()
    run_once( tmp_path, [ finding() ], store )
    run_once( tmp_path, [ finding( text="def a1(): return 2" ) ], store )
    assert len( store.created ) == 2


def test_a_transport_failure_is_spooled_and_the_next_run_files_it_first_and_clears_the_spool( tmp_path ):
    down  = Store( create=( False, None, { "error": "refused" } ) )
    first = run_once( tmp_path, [ finding() ], down )
    assert len( first[ "queued_for_retry" ] ) == 1 and len( ff.read_pending( tmp_path ) ) == 1
    up    = Store()
    later = run_once( tmp_path, [ finding( "d-2", "b2", "def b2(): pass" ) ], up )
    assert [ k[ "key" ] for k in later[ "filed" ] ] == [ ff.correlation_key( "d-1", "def a1(): pass" ), ff.correlation_key( "d-2", "def b2(): pass" ) ], "the spooled row goes first"
    assert not ( tmp_path / ff.PENDING_FILE ).exists()


def test_a_failed_probe_queues_the_row_without_creating_one_so_a_row_is_never_filed_twice( tmp_path ):
    store = Store( query=( False, None, { "error": "refused" } ) )
    got   = run_once( tmp_path, [ finding() ], store )
    assert len( got[ "queued_for_retry" ] ) == 1 and store.created == [ ]


def test_a_ratio_gate_refusal_keeps_the_row_for_the_next_run( tmp_path ):
    gated = Store( create=( False, 422, { "error": f"{ff.GATED_PHRASE}: in the last window the fleet created 9 and closed 0." } ) )
    got   = run_once( tmp_path, [ finding() ], gated )
    assert len( got[ "queued_for_retry" ] ) == 1 and got[ "queued_for_retry" ][ 0 ][ "status" ] == 422 and len( ff.read_pending( tmp_path ) ) == 1
    again = run_once( tmp_path, [ finding() ], Store() )
    assert len( again[ "filed" ] ) == 1 and not ( tmp_path / ff.PENDING_FILE ).exists()


def test_the_store_ratio_gate_still_opens_its_refusal_with_the_phrase_the_filing_looks_for():
    assert rules.ratio_gate_advisory( 9, 0, allow_below=1.0 ).startswith( ff.GATED_PHRASE )
    assert rules.ratio_gate_advisory( 20, 2, allow_below=1.0 ).startswith( ff.GATED_PHRASE )


@pytest.mark.parametrize( "status, body", [ ( 403, { "error": "a worker files P5" } ), ( 500, { "error": "boom" } ), ( 422, { "error": "some other rule" } ) ] )
def test_any_other_verdict_is_recorded_as_refused_and_not_retried( tmp_path, status, body ):
    got = run_once( tmp_path, [ finding() ], Store( create=( False, status, body ) ) )
    assert got[ "refused" ][ 0 ][ "status" ] == status and body[ "error" ] in got[ "refused" ][ 0 ][ "detail" ] and not ( tmp_path / ff.PENDING_FILE ).exists()


def test_a_finding_already_in_the_spool_is_not_spooled_twice( tmp_path ):
    down = Store( create=( False, None, { "error": "x" } ) )
    run_once( tmp_path, [ finding() ], down )
    run_once( tmp_path, [ finding() ], down )
    assert len( ff.read_pending( tmp_path ) ) == 1 and len( down.created ) == 2, "one retry of the spooled row each run, the finding is not added again"


def test_the_row_goes_to_the_rung_found_per_finding( tmp_path ):
    store = Store()
    run_once( tmp_path, [ finding( session="s-1" ), finding( "d-2", "b2", "def b2(): pass", session=None ) ], store, resolver( "lineage", "Tiberius" ) )
    owners = { p[ "owner_persona" ] for p in store.created }
    assert owners == { "Tiberius", "Cheech" }, "the seat with a session reaches its lineage manager, the one without falls to the configured manager"


def test_the_spool_helpers_write_one_line_a_payload_and_remove_the_file_when_empty( tmp_path ):
    ff.write_pending( tmp_path / "sub", [ { "a": 1 }, { "b": 2 } ] )
    assert ff.read_pending( tmp_path / "sub" ) == [ { "a": 1 }, { "b": 2 } ]
    ff.write_pending( tmp_path / "sub", [ ] )
    assert ff.read_pending( tmp_path / "sub" ) == [ ] and not ( tmp_path / "sub" / ff.PENDING_FILE ).exists()
    ff.write_pending( tmp_path / "none", [ ] )


def test_the_live_store_calls_the_hooks_client_with_the_settings_and_key_it_was_given_or_reads( monkeypatch ):
    from lupin_cli.claude_code.hooks.lib import task_store_client as client, task_store_settings
    seen = []
    monkeypatch.setattr( task_store_settings, "load_task_store_settings", lambda: { "api_base_url": "http://x" } )
    monkeypatch.setattr( client, "read_api_key", lambda: "key-read" )
    monkeypatch.setattr( client, "query_by_correlation_key", lambda s, k, key: seen.append( ( "query", s, k, key ) ) or ( True, 200, { "count": 0 } ) )
    monkeypatch.setattr( client, "create_task", lambda s, k, p: seen.append( ( "create", s, k, p ) ) or ( True, 201, { } ) )
    live = ff.LiveStore()
    live.query( "epic:dupcheck-x" )
    live.create( { "title": "t" } )
    assert seen == [ ( "query", { "api_base_url": "http://x" }, "key-read", "epic:dupcheck-x" ), ( "create", { "api_base_url": "http://x" }, "key-read", { "title": "t" } ) ]
    given = ff.LiveStore( settings={ "api_base_url": "http://y" }, api_key="given" )
    assert given.settings == { "api_base_url": "http://y" } and given.api_key == "given"


def test_the_key_is_pinned_to_a_literal_so_a_change_of_its_recipe_cannot_slip_by():
    assert ff.correlation_key( "abc123", "def f(): pass" ) == "epic:dupcheck-c58ddd83a49e5bba", "sha256 of id, a colon and the text's sha256, first 16 hex digits"
