"""
The doc viewer's podcast door and its check, driven over HTTP.

The click in the page is the yes, so there is no card. The spent-card record is the real repository on a
SQLite file. The doc viewer's check runs for real on a scratch scope. The job queue is stubbed at
flow.submit, so nothing here buys audio. The clock is a list the test moves, because the claim's window
is measured against the row's own stored time.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cosa.rest import podcast_proxy as pp
from cosa.rest.middleware.api_key_auth import authenticated_account_email, require_api_key_or_jwt
from cosa.rest.postgres_models import PodcastProxySpentCard
from cosa.rest.routers import docs_files
from cosa.rest.routers import podcast_proxy as door
from cosa.rest.routers._scope_registry import ScopeConfig

RICK    = "rick@example.com"
USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER   = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
WINDOW  = 900


class _Flow:
    """Stands in for the v2 submit path: records every submit and answers like a queued job."""
    def __init__( self ):
        self.calls, self.answers, self.raises = [ ], [ ], None
    def submit( self, **kwargs ):
        self.calls.append( kwargs )
        if self.raises: raise self.raises
        job = f"pg-{len( self.calls ):08x}"
        return { "status": "waiting", "job_id": job, "queue_position": len( self.calls ) }


@pytest.fixture
def world( monkeypatch, tmp_path ):
    root = tmp_path / "repo"
    ( root / "io" / "tmp" ).mkdir( parents=True )
    cfg    = ScopeConfig( name="demo", root=str( root ), allowed_prefixes=( "io/", ) )
    engine = create_engine( f"sqlite:///{tmp_path / 'spent.db'}", connect_args={ "timeout": 10 } )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE podcast_proxy_spent_cards ( card_id CHAR(32) PRIMARY KEY, spent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "started_by VARCHAR(255) NOT NULL, scope_path TEXT NOT NULL, sha256 VARCHAR(64) NOT NULL, job_id VARCHAR(64) )" )
    sessions = sessionmaker( engine )

    @contextmanager
    def fake_db():
        session = sessions()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    clock = [ datetime.now( timezone.utc ) ]
    flow  = _Flow()
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: { "demo": cfg } )
    monkeypatch.setattr( door, "get_db", fake_db )
    monkeypatch.setattr( door, "datetime", type( "Clock", ( ), { "now": staticmethod( lambda tz=None: clock[ 0 ] ) } ) )
    monkeypatch.setattr( door, "copy_directory", lambda: str( tmp_path / "copies" ) )
    monkeypatch.setattr( pp, "max_age_seconds", lambda config_mgr=None: WINDOW )
    monkeypatch.setattr( pp, "dry_run_enabled", lambda config_mgr=None: False )
    path = root / "io" / "tmp" / "summary.md"
    path.write_text( "# A summary\n\nSome words, enough to hear.\n" )
    return { "root": root, "path": path, "flow": flow, "sessions": sessions, "copies": tmp_path / "copies", "clock": clock }


def _app( world, user_id=USER_ID, email=RICK ):
    app = FastAPI()
    app.include_router( door.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: user_id
    app.dependency_overrides[ authenticated_account_email ] = lambda: email
    app.dependency_overrides[ door.get_ask_flow ]           = lambda: world[ "flow" ]
    return TestClient( app )


def _click( world, path="demo/io/tmp/summary.md", **who ):
    return _app( world, **who ).post( "/api/podcast-proxy/from-viewer", json={ "path": path } )


def _check( world, path="demo/io/tmp/summary.md", **who ):
    return _app( world, **who ).get( "/api/podcast-proxy/from-viewer/check", params={ "path": path } )


def _code( answer ): return answer.json()[ "detail" ][ "code" ]


def _spent( world ):
    with world[ "sessions" ]() as session: return session.query( PodcastProxySpentCard ).all()


def _copies( world ):
    return sorted( p for p in world[ "copies" ].glob( "*/*" ) ) if world[ "copies" ].exists() else [ ]


# ---- the positive control ----

def test_a_click_by_a_signed_in_person_queues_one_job_for_that_person( world ):
    answer = _click( world )
    assert answer.status_code == 200, answer.text
    assert answer.json() == { "job_id": "pg-00000001", "status": "waiting", "name": "summary.md", "queue_position": 1,
                              "size": world[ "path" ].stat().st_size }
    call = world[ "flow" ].calls[ 0 ]
    assert call[ "command" ] == "agent router go to podcast generator"
    assert call[ "user_id" ] == USER_ID and call[ "user_email" ] == RICK and call[ "speak" ] is False
    assert set( call[ "args" ] ) == { "research" } and call[ "args" ][ "research" ].endswith( "summary.md" )
    rows = _spent( world )
    assert len( rows ) == 1 and rows[ 0 ].job_id == "pg-00000001" and rows[ 0 ].started_by == f"viewer:{USER_ID}"
    assert rows[ 0 ].scope_path == "demo/io/tmp/summary.md"


def test_the_claim_id_is_the_derived_one_for_this_person_file_and_bytes( world ):
    _click( world )
    facts = pp.check_source( "demo/io/tmp/summary.md", { "demo": ScopeConfig( name="demo", root=str( world[ "root" ] ), allowed_prefixes=( "io/", ) ) } )
    assert uuid.UUID( str( _spent( world )[ 0 ].card_id ) ) == pp.viewer_claim_id( USER_ID, "demo/io/tmp/summary.md", facts[ "sha256" ] )


# ---- one click, one job ----

def test_a_second_click_inside_the_window_starts_nothing_and_names_the_first_job( world ):
    _click( world )
    second = _click( world )
    assert second.status_code == 409
    assert second.json()[ "detail" ][ "code" ] == "spent" and second.json()[ "detail" ][ "job_id" ] == "pg-00000001"
    assert len( world[ "flow" ].calls ) == 1 and len( _spent( world ) ) == 1


def test_a_click_after_the_window_starts_a_second_job_on_the_same_row( world ):
    _click( world )
    world[ "clock" ][ 0 ] += timedelta( seconds=WINDOW + 60 )
    second = _click( world )
    assert second.status_code == 200, second.text
    assert len( world[ "flow" ].calls ) == 2
    rows = _spent( world )
    assert len( rows ) == 1 and rows[ 0 ].job_id == "pg-00000002"


def test_an_edited_file_is_a_new_job_inside_the_window( world ):
    _click( world )
    world[ "path" ].write_text( "# A summary\n\nDifferent words now.\n" )
    assert _click( world ).status_code == 200
    assert len( world[ "flow" ].calls ) == 2 and len( _spent( world ) ) == 2


def test_another_person_clicking_the_same_file_gets_their_own_job( world ):
    _click( world )
    other = _click( world, user_id=OTHER, email="other@example.com" )
    assert other.status_code == 200 and world[ "flow" ].calls[ 1 ][ "user_id" ] == OTHER
    assert len( _spent( world ) ) == 2


def test_a_claim_with_no_job_recorded_yet_is_reported_as_under_way( world ):
    facts = pp.check_source( "demo/io/tmp/summary.md", { "demo": ScopeConfig( name="demo", root=str( world[ "root" ] ), allowed_prefixes=( "io/", ) ) } )
    with world[ "sessions" ]() as session:
        session.add( PodcastProxySpentCard( card_id=pp.viewer_claim_id( USER_ID, "demo/io/tmp/summary.md", facts[ "sha256" ] ),
                                            started_by=f"viewer:{USER_ID}", scope_path="demo/io/tmp/summary.md", sha256=facts[ "sha256" ],
                                            spent_at=world[ "clock" ][ 0 ].replace( tzinfo=None ) ) )
        session.commit()
    answer = _click( world )
    assert answer.status_code == 409 and _code( answer ) == "claimed_no_job" and world[ "flow" ].calls == [ ]


# ---- who may click ----

def test_a_caller_with_no_login_email_is_refused_on_both_routes_and_nothing_is_written( world ):
    for answer in ( _click( world, email=None ), _check( world, email=None ) ):
        assert answer.status_code == 403 and _code( answer ) == "not_a_person"
    assert world[ "flow" ].calls == [ ] and _spent( world ) == [ ] and _copies( world ) == [ ]


# ---- what the door refuses ----

@pytest.mark.parametrize( "path,code", [
    ( "demo/io/tmp/missing.md", "not_found" ),
    ( "summary.md",             "bad_path" ),
] )
def test_a_file_the_check_refuses_is_a_400_with_the_door_code_and_claims_nothing( world, path, code ):
    answer = _click( world, path=path )
    assert answer.status_code == 400 and _code( answer ) == code
    assert world[ "flow" ].calls == [ ] and _spent( world ) == [ ]


def test_an_extension_a_podcast_cannot_read_is_wrong_kind( world ):
    ( world[ "root" ] / "io" / "tmp" / "pic.png" ).write_bytes( b"\x89PNG\r\n" )
    answer = _click( world, path="demo/io/tmp/pic.png" )
    assert answer.status_code == 400 and _code( answer ) == "wrong_kind" and _spent( world ) == [ ]


def test_an_unknown_field_in_the_body_is_refused( world ):
    answer = _app( world ).post( "/api/podcast-proxy/from-viewer", json={ "path": "demo/io/tmp/summary.md", "actor": "x" } )
    assert answer.status_code == 422


# ---- the queue fails ----

def test_a_queue_failure_removes_this_copy_releases_the_claim_and_a_retry_works( world ):
    world[ "flow" ].raises = RuntimeError( "queue down" )
    failed = _click( world )
    assert failed.status_code == 502 and _code( failed ) == "queue_failed"
    assert "card" not in failed.json()[ "detail" ][ "message" ], "a person in the viewer holds a button, not a card"
    assert _spent( world ) == [ ] and _copies( world ) == [ ]
    world[ "flow" ].raises = None
    assert _click( world ).status_code == 200 and len( _spent( world ) ) == 1


def test_a_second_attempt_that_fails_leaves_the_first_jobs_copy_on_disk( world ):
    assert _click( world ).status_code == 200
    first = _copies( world )
    assert len( first ) == 1
    world[ "clock" ][ 0 ] += timedelta( seconds=WINDOW + 60 )
    world[ "flow" ].raises = RuntimeError( "queue down" )
    assert _click( world ).status_code == 502
    assert _copies( world ) == first and first[ 0 ].read_bytes() == world[ "path" ].read_bytes()


def test_each_click_writes_its_copy_under_its_own_folder( world ):
    _click( world )
    world[ "clock" ][ 0 ] += timedelta( seconds=WINDOW + 60 )
    _click( world )
    assert len( { p.parent.name for p in _copies( world ) } ) == 2


# ---- dry run and the check ----

def test_with_the_dry_run_switch_on_the_click_claims_and_queues_nothing( world, monkeypatch ):
    monkeypatch.setattr( pp, "dry_run_enabled", lambda config_mgr=None: True )
    answer = _click( world )
    assert answer.status_code == 200 and answer.json()[ "status" ] == "dry run" and answer.json()[ "job_id" ].startswith( "dry-run-" )
    assert world[ "flow" ].calls == [ ] and _copies( world ) == [ ]
    assert _spent( world )[ 0 ].job_id == answer.json()[ "job_id" ]


def test_the_check_answers_name_and_size_and_writes_nothing( world ):
    answer = _check( world )
    assert answer.status_code == 200
    assert answer.json() == { "ok": True, "name": "summary.md", "size": world[ "path" ].stat().st_size }
    assert world[ "flow" ].calls == [ ] and _spent( world ) == [ ] and _copies( world ) == [ ]


def test_the_check_keeps_no_content( world, monkeypatch ):
    seen = { }
    real = pp.check_source
    def spy( scope_path, registry=None, keep_content=False ):
        seen[ "keep_content" ] = keep_content
        return real( scope_path, registry, keep_content )
    monkeypatch.setattr( pp, "check_source", spy )
    assert _check( world ).status_code == 200
    assert seen == { "keep_content": False }


def test_the_check_refuses_a_file_a_podcast_cannot_read_with_the_door_code( world ):
    ( world[ "root" ] / "io" / "tmp" / "pic.png" ).write_bytes( b"\x89PNG\r\n" )
    answer = _check( world, path="demo/io/tmp/pic.png" )
    assert answer.status_code == 400 and _code( answer ) == "wrong_kind"


# ---- the seat door's copy and claim are still its card id ----

def test_the_derived_id_changes_with_each_of_its_three_parts():
    base = pp.viewer_claim_id( USER_ID, "demo/a.md", "a" * 64 )
    assert base == pp.viewer_claim_id( USER_ID, "demo/a.md", "a" * 64 )
    assert len( { base, pp.viewer_claim_id( OTHER, "demo/a.md", "a" * 64 ),
                  pp.viewer_claim_id( USER_ID, "demo/b.md", "a" * 64 ),
                  pp.viewer_claim_id( USER_ID, "demo/a.md", "b" * 64 ) } ) == 4
    assert isinstance( base, uuid.UUID )
