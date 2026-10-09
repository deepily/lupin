"""
The seat tool against the server's real podcast doors, in one process.

The ask, start and card-status doors and the notification response route are the real handlers behind
one FastAPI app. The tool's own transport is the real one, with its HTTP call routed into that app.
The fakes are the notification table, the spent-card database (a SQLite file), the persona lookup and
the job queue. The queue is stubbed at the submit call, so nothing here buys audio.
"""
import subprocess
import sys
import types
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
from cosa.rest.postgres_models import Notification
from cosa.rest.db.repositories.podcast_proxy_spent_repository import PodcastProxySpentRepository
from cosa.rest.routers import docs_files
from cosa.rest.routers import notifications as notification_routes
from cosa.rest.routers import podcast_proxy as door
from cosa.rest.routers._scope_registry import ScopeConfig
from cosa.rest import task_promotion_gate as gate
from lupin_mcp import podcast_for_rick as pfr
from lupin_mcp import task_store_tools as tst

NOW         = datetime( 2026, 10, 8, 21, 0, tzinfo=timezone.utc )
OPERATOR_ID = uuid.UUID( "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" )
SESSION_ID  = "b9537836"
ACTOR       = f"maya {SESSION_ID}"
RICK        = "rick@example.com"
OPERATOR    = { "user_id": "u-1", "account_email": RICK, "method": "jwt" }
PERSONA     = { "name": "Maya", "icon": "x", "voice_id": "v1" }
STABLE_ID    = "b9537836-25ae-4da8-8b49-a7eb248912ad"
RESPUN_ID    = "c0ffee01"
OTHER_ID     = "0badc0de"
OTHER_STABLE = "0badc0de-1111-4222-8333-444444444444"


CLOCK = { "now": NOW }   # the doors' clock; a test moves it to age a card


class Cards:
    """
    The notification table. Ask creates, the status doors read, the answer route updates.

    find_live_podcast_card mirrors the real query's conditions: the same kind, the same path, the same
    bytes (sha256), still unanswered and not yet expired. The real query uses Postgres JSON operators, which
    SQLite cannot run, so the conditions are held here and the operators are not.
    """
    def __init__( self ): self.rows = { }
    def __call__( self, session ): return self
    def find_live_podcast_card( self, kind, scope_path, sha256, now ):
        def live( card ):
            payload = card.payload or { }
            return ( payload.get( "kind" ) == kind and payload.get( "scope_path" ) == scope_path and payload.get( "sha256" ) == sha256
                     and card.state != "responded" and card.expires_at is not None and card.expires_at > now )
        return next( ( c for c in self.rows.values() if live( c ) ), None )
    def create_notification( self, **fields ):
        card = Notification( id=uuid.uuid4(), created_at=NOW, state="created", **fields )
        self.rows[ card.id ] = card
        return card
    def update_state( self, card_id, state ): self.rows[ card_id ].state = state
    def get_by_id( self, card_id ): return self.rows.get( card_id )

    def update_response( self, card_id, response_value ):
        card = self.rows[ card_id ]
        card.state, card.responded_at, card.response_value = "responded", CLOCK[ "now" ], response_value
        return card

    def answer( self, card_id, value="yes", source="ui", answered_by=None ):
        """Write an answer onto the row; only the timed-out default needs this."""
        card = self.rows[ uuid.UUID( str( card_id ) ) ]
        card.state, card.responded_at = "responded", NOW + timedelta( seconds=30 )
        card.response_value = { "value": value, "source": source, "answered_by": answered_by or dict( OPERATOR ) }


class Flow:
    """The v2 submit path, recorded and never run."""
    def __init__( self ): self.calls, self.raises = [ ], None
    def submit( self, **kwargs ):
        self.calls.append( kwargs )
        if self.raises: raise self.raises
        return { "status": "waiting", "job_id": "pg-1a2b3c4d", "queue_position": 1 }


class Queue:
    def push_notification( self, **fields ): pass


class Ws:
    def is_user_connected( self, user_id ): return True
    def emit_to_user_or_listener_sync( self, **kwargs ): pass


def git( cwd, *args ):
    subprocess.run( [ "git", "-C", str( cwd ), *args ], check=True, capture_output=True,
                    env={ "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e", "PATH": "/usr/bin:/bin" } )


@pytest.fixture
def world( monkeypatch, tmp_path ):
    # The seat's file lives in a real git checkout named for the scope, so the tool's own translation runs.
    root = tmp_path / "demo"
    ( root / "io" / "tmp" ).mkdir( parents=True )
    path = root / "io" / "tmp" / "summary.md"
    path.write_text( "# A summary\n\nSome words, enough to hear.\n" )
    git( root, "init", "-q" )
    cfg = ScopeConfig( name="demo", root=str( root ), allowed_prefixes=( "io/", ) )

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

    cards, flow = Cards(), Flow()
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: { "demo": cfg } )
    for module in ( door, notification_routes ):
        monkeypatch.setattr( module, "NotificationRepository", cards )
        monkeypatch.setattr( module, "get_db", fake_db )
    monkeypatch.setattr( notification_routes, "get_local_timestamp", lambda: NOW.isoformat() )
    monkeypatch.setattr( door, "get_voice_persona", lambda sid: PERSONA if sid in ( SESSION_ID, RESPUN_ID ) else None )
    # Two ids of ONE seat (before and after a /clear) share a stable id; another seat has its own.
    seats = {
        SESSION_ID : { "sender_id": f"claude.code@cosa.deepily.ai#{SESSION_ID}", "stable_session_id": STABLE_ID },
        RESPUN_ID  : { "sender_id": f"claude.code@cosa.deepily.ai#{RESPUN_ID}", "stable_session_id": STABLE_ID },
        OTHER_ID   : { "sender_id": f"claude.code@cosa.deepily.ai#{OTHER_ID}", "stable_session_id": OTHER_STABLE },
    }
    monkeypatch.setattr( door, "find_session_by_id", lambda sid, check_pid=True: seats.get( sid ) )
    CLOCK[ "now" ] = NOW
    monkeypatch.setattr( door, "datetime", type( "Clock", ( ), { "now": staticmethod( lambda tz=None: CLOCK[ "now" ] ) } ) )
    monkeypatch.setitem( sys.modules, "lupin_app.main", types.SimpleNamespace( config_mgr=types.SimpleNamespace( get=lambda key, default=None, return_type=None: default ) ) )
    monkeypatch.setattr( door, "copy_directory", lambda: str( tmp_path / "copies" ) )
    monkeypatch.setattr( pp, "max_age_seconds", lambda config_mgr=None: 900 )
    monkeypatch.setattr( gate, "approver_persona_for_account", lambda email: { RICK: "rick" }.get( email ) )
    monkeypatch.setattr( "cosa.rest.user_service.get_user_by_email", lambda email: { "id": str( OPERATOR_ID ) } )
    monkeypatch.setattr( "cosa.rest.user_service.get_user_by_id", lambda user_id: { "id": user_id, "email": RICK } )
    monkeypatch.setattr( "lupin_cli.notifications.notification_models.resolve_target_user", lambda *a, **k: RICK )

    app = FastAPI()
    app.include_router( door.router )
    app.include_router( notification_routes.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: None
    app.dependency_overrides[ door.get_notification_queue ] = lambda: Queue()
    app.dependency_overrides[ door.get_websocket_manager ]  = lambda: Ws()
    app.dependency_overrides[ door.get_ask_flow ]           = lambda: flow
    app.dependency_overrides[ notification_routes.get_websocket_manager ] = lambda: Ws()
    client = TestClient( app )

    # Rick's browser: the same real routers, but the request arrives on his login (no API key), as the page sends it.
    browser = FastAPI()
    browser.include_router( notification_routes.router )
    browser.dependency_overrides[ require_api_key_or_jwt ]      = lambda: OPERATOR[ "user_id" ]
    browser.dependency_overrides[ authenticated_account_email ] = lambda: RICK
    browser.dependency_overrides[ notification_routes.get_websocket_manager ] = lambda: Ws()
    rick = TestClient( browser )

    # The tool's real transport (task_store_request) with only the HTTP call routed into the app.
    monkeypatch.setattr( tst.requests, "request", lambda method, url, headers=None, json=None, params=None, timeout=None:
                         client.request( method, url.replace( "http://s", "" ), json=json ) )
    return { "path": path, "root": root, "cards": cards, "flow": flow, "sessions": sessions, "tmp": tmp_path, "rick": rick, "seat": client }


class Clock:
    def __init__( self, on_sleep=None ): self.now, self.on_sleep, self.sleeps = NOW, on_sleep, 0
    def sleep( self, seconds ):
        self.sleeps += 1
        self.now += timedelta( seconds=seconds )
        if self.on_sleep: self.on_sleep( self.sleeps )


def call( world, clock, host_path=None, card_id="", actor=ACTOR ):
    return pfr.podcast_for_rick_impl( "http://s", "key", actor, host_path if host_path is not None else str( world[ "path" ] ), card_id,
                                      sleep_fn=clock.sleep, now_fn=lambda: clock.now )


def only_card( world ): return next( iter( world[ "cards" ].rows.values() ) )


def rick_answers( world, value="yes", card_id=None ):
    """Rick answers the way his page does: through the real answer route, on his login."""
    card_id = card_id or only_card( world ).id
    answered = world[ "rick" ].post( "/api/notify/response", json={ "notification_id": str( card_id ), "response_value": value } )
    assert answered.status_code == 200, answered.text
    return answered


def test_a_yes_from_the_operator_starts_one_job_through_the_real_doors( world ):
    clock = Clock( lambda n: rick_answers( world ) if n == 2 else None )
    out = call( world, clock )
    assert out[ "status" ] == "started" and out[ "job_id" ] == "pg-1a2b3c4d" and out[ "card_id" ] == str( only_card( world ).id )
    assert len( world[ "flow" ].calls ) == 1 and clock.sleeps == 2
    assert only_card( world ).payload[ "scope_path" ] == "demo/io/tmp/summary.md"


@pytest.mark.parametrize( "value,status", [ ( "no", "declined" ), ( "neither", "declined" ) ] )
def test_an_answer_that_is_not_a_yes_starts_nothing( world, value, status ):
    assert call( world, Clock( lambda n: rick_answers( world, value ) ) )[ "status" ] == status
    assert world[ "flow" ].calls == []


def test_a_timed_out_default_starts_nothing_even_when_it_says_yes( world ):
    clock = Clock( lambda n: world[ "cards" ].answer( only_card( world ).id, value="yes", source="timeout_default" ) )
    assert call( world, clock )[ "status" ] == "default_used" and world[ "flow" ].calls == []


def test_an_unanswered_card_expires_where_the_server_says_and_starts_nothing( world ):
    out = call( world, Clock() )
    assert out[ "status" ] == "expired" and world[ "flow" ].calls == []


def test_a_file_changed_after_the_yes_is_the_servers_hash_mismatch_and_starts_nothing( world ):
    def answer_then_change( n ):
        rick_answers( world )
        world[ "path" ].write_text( "# Different\n\nOther words.\n" )
    out = call( world, Clock( answer_then_change ) )
    assert out[ "reason" ] == "hash_mismatch" and out[ "stage" ] == "start" and world[ "flow" ].calls == []


def test_a_card_answered_by_the_wrong_login_is_refused_with_the_servers_code( world ):
    def the_seat_answers_its_own_card( n ):   # on the API key, the way a seat would, not on Rick's login
        posted = world[ "seat" ].post( "/api/notify/response", headers={ "X-API-Key": "k" },
                                       json={ "notification_id": str( only_card( world ).id ), "response_value": "yes" } )
        assert posted.status_code == 200, posted.text
    out = call( world, Clock( the_seat_answers_its_own_card ) )
    assert out[ "reason" ] == "wrong_login" and world[ "flow" ].calls == []


def test_another_seat_cannot_start_the_card_it_did_not_ask( world ):
    first = call( world, Clock() )
    rick_answers( world, card_id=first[ "card_id" ] )
    out = call( world, Clock(), card_id=first[ "card_id" ], actor=f"sam {OTHER_ID}", host_path="" )
    assert out[ "reason" ] == "wrong_session" and out[ "stage" ] == "start"
    assert world[ "flow" ].calls == []


def test_a_re_spun_seat_resumes_its_own_card_through_the_real_door( world ):
    asked = call( world, Clock() )                                        # asked as session b9537836
    assert asked[ "status" ] == "expired"
    rick_answers( world, card_id=asked[ "card_id" ] )
    # After a /clear the seat's current id is c0ffee01; its stable id is unchanged, and the bridge knows both.
    out = call( world, Clock(), card_id=asked[ "card_id" ], actor=f"maya {RESPUN_ID}", host_path="" )
    assert out[ "status" ] == "started" and out[ "job_id" ] == "pg-1a2b3c4d"
    assert len( world[ "flow" ].calls ) == 1


def test_a_re_spun_seat_asking_again_finds_the_waiting_card_of_its_earlier_self( world ):
    first = call( world, Clock() )
    again = call( world, Clock(), actor=f"maya {RESPUN_ID}" )
    assert again[ "reason" ] == "card_already_waiting" and again[ "card_id" ] == first[ "card_id" ]


def test_a_second_ask_for_the_same_waiting_file_names_the_card_to_resume( world ):
    first = call( world, Clock() )
    assert first[ "status" ] == "expired"
    out = call( world, Clock() )
    assert out[ "reason" ] == "card_already_waiting" and out[ "card_id" ] == first[ "card_id" ] and "card_id=" in out[ "retry" ]


def test_a_queue_failure_releases_the_card_and_a_resume_starts_the_one_job( world ):
    world[ "flow" ].raises = RuntimeError( "the queue is down" )
    out = call( world, Clock( lambda n: rick_answers( world ) ) )
    assert out[ "reason" ] == "queue_failed" and "card_id=" in out[ "retry" ]

    world[ "flow" ].raises = None
    resumed = call( world, Clock(), card_id=out[ "card_id" ], host_path="" )
    assert resumed[ "status" ] == "started" and resumed[ "job_id" ] == "pg-1a2b3c4d"
    assert len( world[ "flow" ].calls ) == 2   # the failed submit, then the one that queued


def test_resuming_a_spent_card_reports_its_job_and_queues_nothing( world ):
    started = call( world, Clock( lambda n: rick_answers( world ) ) )
    again   = call( world, Clock(), card_id=started[ "card_id" ], host_path="" )
    assert again[ "reason" ] == "card_already_spent" and again[ "job_id" ] == "pg-1a2b3c4d"
    assert len( world[ "flow" ].calls ) == 1


def test_a_card_for_another_file_than_the_path_is_refused_before_anything_starts( world ):
    first = call( world, Clock() )
    other = world[ "root" ] / "io" / "tmp" / "other.md"
    other.write_text( "# Other\n" )
    out = call( world, Clock(), host_path=str( other ), card_id=first[ "card_id" ] )
    assert out[ "reason" ] == "card_for_a_different_file" and world[ "flow" ].calls == []


def test_the_server_refuses_a_file_the_viewer_blocks_and_the_tool_passes_its_code( world ):
    ( world[ "root" ] / "src" ).mkdir()
    blocked = world[ "root" ] / "src" / "x.md"
    blocked.write_text( "# not under an allowed prefix\n" )
    out = call( world, Clock(), host_path=str( blocked ) )
    assert out[ "stage" ] == "ask" and out[ "status" ] == "error" and out[ "detail" ][ "code" ] == out[ "reason" ]


def test_a_card_for_the_same_file_as_the_path_resumes_through_the_real_card_door( world ):
    first = call( world, Clock() )
    rick_answers( world, card_id=first[ "card_id" ] )
    out = call( world, Clock(), card_id=first[ "card_id" ] )
    assert out[ "status" ] == "started" and len( world[ "flow" ].calls ) == 1


def claim_without_a_job( world, card_id ):
    """Write the spent record a start leaves when it claimed the card and recorded no job."""
    card = world[ "cards" ].rows[ uuid.UUID( str( card_id ) ) ]
    with world[ "sessions" ]() as session:
        assert PodcastProxySpentRepository( session ).claim( card.id, ACTOR, card.payload[ "scope_path" ], card.payload[ "sha256" ] )
        session.commit()


def test_the_same_path_with_changed_bytes_gets_a_new_card_not_the_waiting_one( world ):
    first = call( world, Clock() )
    world[ "path" ].write_text( "# A summary\n\nDifferent words now.\n" )
    second = call( world, Clock() )
    assert second[ "status" ] == "expired" and second[ "card_id" ] != first[ "card_id" ]
    assert len( world[ "cards" ].rows ) == 2


def test_a_card_past_its_expiry_does_not_block_a_new_ask_for_the_same_file( world ):
    first = call( world, Clock() )
    CLOCK[ "now" ] = only_card( world ).expires_at + timedelta( seconds=1 )
    second = call( world, Clock() )
    assert second.get( "reason" ) != "card_already_waiting" and second[ "card_id" ] != first[ "card_id" ]


def test_resuming_a_claimed_no_job_card_is_refused_with_a_hint_and_nothing_polls_or_starts( world ):
    first = call( world, Clock() )
    rick_answers( world, card_id=first[ "card_id" ] )
    claim_without_a_job( world, first[ "card_id" ] )
    clock = Clock()
    out = call( world, clock, card_id=first[ "card_id" ], host_path="" )
    assert out[ "reason" ] == "claimed_no_job" and out[ "stage" ] == "card" and "Do not start it again" in out[ "retry" ]
    assert clock.sleeps == 0 and world[ "flow" ].calls == []


def test_a_start_that_meets_a_claim_with_no_job_carries_the_servers_code_and_the_hint( world ):
    def answer_and_claim( n ):
        rick_answers( world )
        claim_without_a_job( world, only_card( world ).id )
    out = call( world, Clock( answer_and_claim ) )
    assert out[ "reason" ] == "claimed_no_job" and out[ "stage" ] == "start" and "Do not start it again" in out[ "retry" ]
    assert world[ "flow" ].calls == []


def test_with_the_servers_dry_run_switch_on_the_tool_says_dry_run_and_not_started( world, monkeypatch ):
    monkeypatch.setattr( pp, "dry_run_enabled", lambda config_mgr=None: True )
    out = call( world, Clock( lambda n: rick_answers( world ) if n == 2 else None ) )
    assert out[ "status" ] == "dry run" and out[ "job_id" ] == f"dry-run-{out[ 'card_id' ][ :8 ]}"
    assert world[ "flow" ].calls == []
