"""The filing of duplicate rows, with every store write faked."""
import datetime
import hashlib
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


DAY = datetime.date( 2026, 11, 7 )


def run_once( tmp_path, findings, store, declared="Cheech", roster=( "Cheech", "Tiberius" ) ):
    """Ensures: files the findings in the folder and returns the summary."""
    return ff.file_findings( findings, tmp_path, store, declared, list( roster ), DAY )



def test_the_key_is_the_definition_id_and_text_hash_never_the_day_and_matches_the_epic_pattern():
    key = ff.correlation_key( "d-1", "def a(): pass" )
    assert re.fullmatch( r"epic:[a-z0-9._-]+", key ) and key.startswith( "epic:dupcheck-" ) and len( key ) == len( "epic:dupcheck-" ) + 16
    assert key == ff.correlation_key( "d-1", "def a(): pass" ) and key != ff.correlation_key( "d-2", "def a(): pass" ) and key != ff.correlation_key( "d-1", "def a(): pass  " )
    assert ff.content_hash( "x" ) == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"


def test_the_owner_is_the_roster_persona_that_matches_the_configured_manager_whatever_the_case_or_accent():
    got = ff.triage_owner( "María", [ "Tiberius", "maria" ] )
    assert got[ "owner" ] == "maria" and "is on the roster" in got[ "note" ]


def test_a_role_label_that_is_not_on_the_roster_falls_to_the_first_roster_persona_and_says_so():
    got = ff.triage_owner( "manager-on-duty", [ "Cheech", "Tiberius" ] )
    assert got[ "owner" ] == "cheech" and "'manager-on-duty'" in got[ "note" ] and "first roster persona" in got[ "note" ]


def test_an_empty_roster_fails_loudly_and_a_blank_entry_is_not_a_persona():
    with pytest.raises( ff.NoTriageOwner, match="no manager on the roster" ): ff.triage_owner( "manager-on-duty", [] )
    with pytest.raises( ff.NoTriageOwner ): ff.triage_owner( "Cheech", [ "", None ] )


def test_the_run_key_is_the_sorted_finding_keys_hashed_so_the_same_set_has_the_same_row_key():
    assert ff.run_key( [ "b", "a" ] ) == ff.run_key( [ "a", "b" ] ) != ff.run_key( [ "a" ] )
    assert re.fullmatch( r"epic:dupcheck-run-[0-9a-f]{16}", ff.run_key( [ "a" ] ) )
    assert ff.run_key( [ "a", "b" ] ) == "epic:dupcheck-run-" + hashlib.sha256( b"a\nb" ).hexdigest()[ :16 ]


def test_the_row_is_p5_with_no_status_a_fixed_creator_with_no_session_and_the_persona_as_owner_and_accountable():
    f   = finding()
    row = ff.triage_payload( [ f ], { "owner": "cheech", "note": "n" }, DAY )
    assert row[ "priority" ] == "P5" and "status" not in row and row[ "created_by" ] == ff.CREATED_BY and row[ "item_class" ] == "task"
    assert not re.search( r"[0-9a-f]{8}-[0-9a-f]{4}", row[ "created_by" ] ), "no session id: the store must read the caller as a worker"
    assert row[ "owner_persona" ] == row[ "accountable_manager" ] == "cheech" and row[ "finding_keys" ] == [ ff.correlation_key( "d-1", f[ "text" ] ) ]
    assert row[ "correlation_key" ] == ff.run_key( row[ "finding_keys" ] )


def test_the_title_starts_with_lupin_and_says_the_job_the_day_and_the_question_and_the_body_says_why_and_what_to_do():
    row = ff.triage_payload( [ finding(), finding( "d-2", "b2", "def b2(): pass" ) ], { "owner": "cheech", "note": "n" }, DAY )
    assert row[ "title" ] == "[LUPIN] Duplicate check 7 Nov: decide whether 2 new function(s) should reuse existing ones" and len( row[ "title" ] ) <= 120
    assert "Why this row exists" in row[ "body" ] and "What to do" in row[ "body" ] and "DUPCHECK-VERDICT" in row[ "body" ] and "Owner: cheech (n)" in row[ "body" ]
    assert "a1 (client/a1.py:3, d-1) repeats: twin in server/twin.py" in row[ "body" ] and "b2 (client/b2.py:3, d-2)" in row[ "body" ] and "aaa..bbb" in row[ "body"]


def test_a_finding_from_a_result_file_carries_its_key_and_needs_no_text():
    f = ff.for_record( finding() )
    assert ff.triage_payload( [ f ], { "owner": "cheech", "note": "n" }, DAY )[ "finding_keys" ] == [ f[ "correlation_key" ] ]



def test_a_run_with_many_findings_files_one_row_and_a_second_run_and_the_next_days_run_file_none( tmp_path ):
    store = Store()
    many  = [ finding( "d-1", "a1", "def a1(): pass" ), finding( "d-2", "a2", "def a2(): pass" ), finding( "d-3", "a3", "def a3(): pass" ) ]
    first = run_once( tmp_path, many, store )
    assert len( first[ "filed" ] ) == 1 and len( store.created ) == 1, "three findings, one row"
    assert "finding_keys" not in store.created[ 0 ], "the store is sent the payload without the filer's own bookkeeping"
    for _ in range(2):                                                                     # the same day, then the next
        again = run_once( tmp_path, many, store )
        assert again == { "filed": [], "already_filed": [], "queued_for_retry": [], "refused": [] }, "every finding is already on the first row: no row, no probe"
    assert len( store.created ) == 1 and len( store.probes ) == 1
    assert len( ( tmp_path / ff.TRIAGED_FILE ).read_text().splitlines() ) == 3


def test_a_run_with_no_findings_files_no_row_and_asks_for_no_owner( tmp_path ):
    got = ff.file_findings( [], tmp_path, Store(), "x", [], DAY )
    assert got == { "filed": [], "already_filed": [], "queued_for_retry": [], "refused": [] } and not ( tmp_path / ff.TRIAGED_FILE ).exists()


def test_a_run_with_findings_and_an_empty_roster_raises_before_anything_is_sent( tmp_path ):
    store = Store()
    with pytest.raises( ff.NoTriageOwner ): run_once( tmp_path, [ finding() ], store, roster=() )
    assert store.created == [] and store.probes == [] and not ( tmp_path / ff.TRIAGED_FILE ).exists()


def test_the_day_comes_from_the_findings_when_none_is_given_and_a_given_day_wins( tmp_path ):
    store = Store()
    ff.file_findings( [ { **finding(), "day": "2026-09-30" } ], tmp_path, store, "Cheech", [ "Cheech" ] )
    assert store.created[ 0 ][ "title" ].startswith( "[LUPIN] Duplicate check 30 Sep:" )
    other = Store()
    ff.file_findings( [ { **finding( "d-2", "b2", "def b2(): pass" ), "day": "2026-09-30" } ], tmp_path, other, "Cheech", [ "Cheech" ], datetime.date( 2026, 1, 2 ) )
    assert other.created[ 0 ][ "title" ].startswith( "[LUPIN] Duplicate check 2 Jan:" )


def test_the_default_day_is_today_and_the_row_is_owned_by_the_roster_persona( tmp_path ):
    store = Store()
    ff.file_findings( [ finding() ], tmp_path, store, "manager-on-duty", [ "Cheech" ] )
    row = store.created[ 0 ]
    assert row[ "owner_persona" ] == "cheech" and f"{datetime.date.today().day} {datetime.date.today().strftime( '%b' )}" in row[ "title" ]


def test_only_the_findings_not_yet_on_a_row_go_on_the_next_runs_row( tmp_path ):
    store = Store()
    run_once( tmp_path, [ finding() ], store )
    got = run_once( tmp_path, [ finding(), finding( "d-2", "b2", "def b2(): pass" ) ], store )
    assert len( got[ "filed" ] ) == 1 and len( store.created ) == 2 and store.created[ 1 ][ "title" ].count( "1 new function" ) == 1 and "b2" in store.created[ 1 ][ "body" ] and "a1" not in store.created[ 1 ][ "body" ].split( "\n\n", 1 )[ 1 ]


def test_a_changed_text_is_a_new_finding_and_goes_on_a_new_row( tmp_path ):
    store = Store()
    run_once( tmp_path, [ finding() ], store )
    run_once( tmp_path, [ finding( text="def a1(): return 2" ) ], store )
    assert len( store.created ) == 2


def test_a_row_the_store_already_holds_is_recorded_as_triaged_so_its_findings_are_not_listed_again( tmp_path ):
    store = Store()
    run_once( tmp_path, [ finding() ], store )
    ( tmp_path / ff.TRIAGED_FILE ).unlink()                                                # a lost triaged file: the row is still in the store
    got = run_once( tmp_path, [ finding() ], store )
    assert len( got[ "already_filed" ] ) == 1 and len( store.created ) == 1 and len( ( tmp_path / ff.TRIAGED_FILE ).read_text().splitlines() ) == 1


def test_a_transport_failure_is_spooled_and_the_next_run_files_it_first_and_clears_the_spool( tmp_path ):
    down  = Store( create=( False, None, { "error": "refused" } ) )
    first = run_once( tmp_path, [ finding() ], down )
    assert len( first[ "queued_for_retry" ] ) == 1 and len( ff.read_pending( tmp_path ) ) == 1
    up    = Store()
    later = run_once( tmp_path, [ finding( "d-2", "b2", "def b2(): pass" ) ], up )
    first_key = ff.run_key( [ ff.correlation_key( "d-1", "def a1(): pass" ) ] )
    assert [ k[ "key" ] for k in later[ "filed" ] ] == [ first_key, ff.run_key( [ ff.correlation_key( "d-2", "def b2(): pass" ) ] ) ], "the spooled row goes first"
    assert not ( tmp_path / ff.PENDING_FILE ).exists() and len( ( tmp_path / ff.TRIAGED_FILE ).read_text().splitlines() ) == 2, "both rows' findings are triaged once filed"


def test_a_failed_probe_queues_the_row_without_creating_one_so_a_row_is_never_filed_twice( tmp_path ):
    store = Store( query=( False, None, { "error": "refused" } ) )
    got   = run_once( tmp_path, [ finding() ], store )
    assert len( got[ "queued_for_retry" ] ) == 1 and store.created == [ ]


def store_422( detail ):
    """
    Ensures: returns the body of a real 422 raised as the task router raises it.

    A minimal FastAPI app raises HTTPException( 422, detail ) exactly as routers/tasks.py does, and FastAPI
    serialises it. The body is read back from the response, never written by hand.
    """
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    app = FastAPI()

    @app.post( "/create" )
    def create():
        """Ensures: raises the 422 the router raises."""
        raise HTTPException( status_code=422, detail=detail )

    reply = TestClient( app ).post( "/create" )
    assert reply.status_code == 422
    return reply.json()


def gated_text():
    """Ensures: returns the refusal text the store's ratio gate gives."""
    return rules.ratio_gate_advisory( 377, 314, allow_below=1.20 )


def test_the_real_gated_422_body_carries_the_phrase_under_detail_as_the_live_result_file_shows():
    body = store_422( gated_text() )
    assert list( body ) == [ "detail" ] and str( body ).startswith( "{'detail': 'New tickets are gated: in the last window THE FLEET created 377 and closed 314" )


def test_a_gated_422_in_the_real_body_shape_keeps_the_row_for_the_next_run( tmp_path ):
    gated = Store( create=( False, 422, store_422( gated_text() ) ) )
    got   = run_once( tmp_path, [ finding() ], gated )
    assert len( got[ "queued_for_retry" ] ) == 1 and got[ "queued_for_retry" ][ 0 ][ "status" ] == 422 and got[ "refused" ] == [ ] and len( ff.read_pending( tmp_path ) ) == 1
    again = run_once( tmp_path, [ finding() ], Store() )
    assert len( again[ "filed" ] ) == 1 and not ( tmp_path / ff.PENDING_FILE ).exists()


def test_a_gated_422_the_client_wrapped_under_error_keeps_the_row_for_the_next_run( tmp_path ):
    gated = Store( create=( False, 422, { "error": f"{ff.GATED_PHRASE}: in the last window the fleet created 9 and closed 0." } ) )
    got   = run_once( tmp_path, [ finding() ], gated )
    assert len( got[ "queued_for_retry" ] ) == 1 and got[ "refused" ] == [ ] and len( ff.read_pending( tmp_path ) ) == 1


@pytest.mark.parametrize( "detail", [ { "errors": [ "owner_persona is not a persona" ] }, "a title is required", "Rows are gated by something else" ] )
def test_any_other_422_in_the_real_body_shape_is_refused_and_not_retried( tmp_path, detail ):
    got = run_once( tmp_path, [ finding() ], Store( create=( False, 422, store_422( detail ) ) ) )
    assert len( got[ "refused" ] ) == 1 and got[ "queued_for_retry" ] == [ ] and not ( tmp_path / ff.PENDING_FILE ).exists()


@pytest.mark.parametrize( "body, expected", [ ( { "detail": f"{ff.GATED_PHRASE}: x" }, True ), ( { "error": f"{ff.GATED_PHRASE}: x" }, True ), ( { "detail": [ f"{ff.GATED_PHRASE}: x" ] }, True ),
                                              ( { "detail": { "errors": [ "other" ] } }, False ), ( { "detail": [ "other" ] }, False ), ( { }, False ) ] )
def test_gated_reads_the_text_of_detail_or_error_whatever_its_shape( body, expected ):
    assert ff.gated( body ) is expected


def test_the_phrase_under_any_other_status_is_refused_not_queued( tmp_path ):
    got = run_once( tmp_path, [ finding() ], Store( create=( False, 403, { "detail": f"{ff.GATED_PHRASE}: a worker may not." } ) ) )
    assert len( got[ "refused" ] ) == 1 and got[ "queued_for_retry" ] == [ ]


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
    assert not ( tmp_path / ff.TRIAGED_FILE ).exists(), "a queued row triages nothing"


def test_a_spooled_row_from_before_the_triage_row_has_no_finding_keys_and_is_still_sent( tmp_path ):
    old = { "item_class": "task", "title": "Duplicate: a in b repeats 1 existing definition(s)", "project": "lupin", "correlation_key": "epic:dupcheck-0123456789abcdef", "priority": "P5" }
    ff.write_pending( tmp_path, [ old ] )
    store = Store()
    got   = run_once( tmp_path, [], store )
    assert [ k[ "key" ] for k in got[ "filed" ] ] == [ old[ "correlation_key" ] ] and store.created == [ old ] and not ( tmp_path / ff.PENDING_FILE ).exists()
    assert ( tmp_path / ff.TRIAGED_FILE ).read_text() == "", "no findings to mark"


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
    monkeypatch.setattr( client, "query_by_correlation_key", lambda s, k, key, every_state=False: seen.append( ( "query", s, k, key, every_state ) ) or ( True, 200, { "count": 0 } ) )
    monkeypatch.setattr( client, "create_task", lambda s, k, p: seen.append( ( "create", s, k, p ) ) or ( True, 201, { } ) )
    live = ff.LiveStore()
    live.query( "epic:dupcheck-x" )
    live.create( { "title": "t" } )
    assert seen == [ ( "query", { "api_base_url": "http://x" }, "key-read", "epic:dupcheck-x", True ), ( "create", { "api_base_url": "http://x" }, "key-read", { "title": "t" } ) ]
    given = ff.LiveStore( settings={ "api_base_url": "http://y" }, api_key="given" )
    assert given.settings == { "api_base_url": "http://y" } and given.api_key == "given"


class HeldRowClient:
    """
    A task-store client whose creates are held rows, as the real store's are.

    Like the store, a plain read withholds a held row and a read for every state returns it.
    """

    def __init__( self ):
        self.held = { }

    def query_by_correlation_key( self, settings, api_key, key, every_state=False ):
        rows = [ self.held[ key ] ] if every_state and key in self.held else [ ]
        return True, 200, { "tasks": rows, "count": len( rows ) }

    def create_task( self, settings, api_key, payload ):
        self.held[ payload[ "correlation_key" ] ] = { **payload, "status": "not_approved" }
        return True, 201, self.held[ payload[ "correlation_key" ] ]


def test_a_second_run_over_a_held_row_files_none_and_a_lost_triaged_file_reads_the_held_row_as_already_filed( tmp_path ):
    live = ff.LiveStore( settings={ "api_base_url": "http://x" }, api_key="k" )
    live.client = HeldRowClient()
    two    = [ finding( "d-1", "a1", "def a1(): pass" ), finding( "d-2", "a2", "def a2(): pass" ) ]
    first  = run_once( tmp_path, two, live )
    second = run_once( tmp_path, two, live )
    assert len( first[ "filed" ] ) == 1 and second[ "filed" ] == [] and second[ "already_filed" ] == [] and len( live.client.held ) == 1
    ( tmp_path / ff.TRIAGED_FILE ).unlink()
    third  = run_once( tmp_path, two, live )
    assert third[ "filed" ] == [] and len( third[ "already_filed" ] ) == 1 and len( live.client.held ) == 1, "the every-state read sees the held row"


def test_a_plain_read_of_held_rows_sees_nothing_which_is_the_defect_the_every_state_read_removes():
    client = HeldRowClient()
    client.create_task( None, None, { "correlation_key": "epic:dupcheck-x" } )
    assert client.query_by_correlation_key( None, None, "epic:dupcheck-x" )[ 2 ][ "count" ] == 0
    assert client.query_by_correlation_key( None, None, "epic:dupcheck-x", every_state=True )[ 2 ][ "count" ] == 1


@pytest.mark.parametrize( "answer", [ ( False, None, { "error": "refused" } ), ( False, 500, { "detail": "boom" } ), ( False, 401, { "detail": "no key" } ) ] )
def test_a_probe_that_did_not_answer_ok_queues_the_row_and_creates_nothing( tmp_path, answer ):
    store = Store( query=answer )
    got   = run_once( tmp_path, [ finding() ], store )
    assert len( got[ "queued_for_retry" ] ) == 1 and got[ "queued_for_retry" ][ 0 ][ "status" ] == answer[ 1 ] and store.created == [ ]


def test_the_key_is_pinned_to_a_literal_so_a_change_of_its_recipe_cannot_slip_by():
    assert ff.correlation_key( "abc123", "def f(): pass" ) == "epic:dupcheck-c58ddd83a49e5bba", "sha256 of id, a colon and the text's sha256, first 16 hex digits"


def test_the_live_store_amends_a_row_with_the_line_as_the_note_through_the_hooks_client():
    seen = [ ]

    class Client:
        def amend_task( self, settings, api_key, item_id, payload ):
            seen.append( ( settings, api_key, item_id, payload ) )
            return True, 200, { "item": { } }

    live        = ff.LiveStore( settings={ "api_base_url": "http://x" }, api_key="k" )
    live.client = Client()
    assert live.amend( "row-1", "a note" ) == ( True, 200, { "item": { } } )
    assert seen == [ ( { "api_base_url": "http://x" }, "k", "row-1", { "note": "a note", "reason": ff.AMEND_REASON, "authority": "standing" } ) ]
