"""
The seat tool against the server's real podcast doors, in one process.

The ask, start and card-status doors and the notification response route are the real handlers behind
one FastAPI app. The tool's own transport is the real one, with its HTTP call routed into that app.
The fakes are the notification table, the spent-card database (a SQLite file), the persona lookup and
the job queue. The queue is stubbed at the submit call, so nothing here buys audio.
"""
import subprocess
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


class Cards:
    """The notification table: ask creates, the status doors read, the test plays the operator."""
    def __init__( self ): self.rows, self.waiting = { }, None
    def __call__( self, session ): return self
    def find_live_podcast_card( self, kind, scope_path, sha256, now ):
        return next( ( c for c in self.rows.values() if c.payload and c.payload.get( "scope_path" ) == scope_path and c.state != "responded" ), None )
    def create_notification( self, **fields ):
        card = Notification( id=uuid.uuid4(), created_at=NOW, state="created", **fields )
        self.rows[ card.id ] = card
        return card
    def update_state( self, card_id, state ): self.rows[ card_id ].state = state
    def get_by_id( self, card_id ): return self.rows.get( card_id )

    def answer( self, card_id, value="yes", source="ui", answered_by=None ):
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
    monkeypatch.setattr( door, "get_voice_persona", lambda sid: PERSONA if sid == SESSION_ID else None )
    monkeypatch.setattr( door, "find_session_by_id", lambda sid, check_pid=True: { "sender_id": f"claude.code@cosa.deepily.ai#{sid}" } if sid == SESSION_ID else None )
    monkeypatch.setattr( door, "datetime", type( "Clock", ( ), { "now": staticmethod( lambda tz=None: NOW ) } ) )
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
    client = TestClient( app )

    # The tool's real transport (task_store_request) with only the HTTP call routed into the app.
    monkeypatch.setattr( tst.requests, "request", lambda method, url, headers=None, json=None, params=None, timeout=None:
                         client.request( method, url.replace( "http://s", "" ), json=json ) )
    return { "path": path, "root": root, "cards": cards, "flow": flow, "sessions": sessions, "tmp": tmp_path }


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


def test_a_yes_from_the_operator_starts_one_job_through_the_real_doors( world ):
    clock = Clock( lambda n: world[ "cards" ].answer( only_card( world ).id ) if n == 2 else None )
    out = call( world, clock )
    assert out[ "status" ] == "started" and out[ "job_id" ] == "pg-1a2b3c4d" and out[ "card_id" ] == str( only_card( world ).id )
    assert len( world[ "flow" ].calls ) == 1 and clock.sleeps == 2
    assert only_card( world ).payload[ "scope_path" ] == "demo/io/tmp/summary.md"


@pytest.mark.parametrize( "value,source,status", [ ( "no", "ui", "declined" ), ( "neither", "ui", "declined" ), ( "yes", "timeout_default", "default_used" ) ] )
def test_an_answer_that_is_not_a_persons_yes_starts_nothing( world, value, source, status ):
    clock = Clock( lambda n: world[ "cards" ].answer( only_card( world ).id, value=value, source=source ) )
    assert call( world, clock )[ "status" ] == status
    assert world[ "flow" ].calls == []


def test_an_unanswered_card_expires_where_the_server_says_and_starts_nothing( world ):
    out = call( world, Clock() )
    assert out[ "status" ] == "expired" and world[ "flow" ].calls == []


def test_a_file_changed_after_the_yes_is_the_servers_hash_mismatch_and_starts_nothing( world ):
    def answer_then_change( n ):
        world[ "cards" ].answer( only_card( world ).id )
        world[ "path" ].write_text( "# Different\n\nOther words.\n" )
    out = call( world, Clock( answer_then_change ) )
    assert out[ "reason" ] == "hash_mismatch" and out[ "stage" ] == "start" and world[ "flow" ].calls == []


def test_a_card_answered_by_the_wrong_login_is_refused_with_the_servers_code( world ):
    odd = { "user_id": "u-2", "account_email": None, "method": "api_key" }
    out = call( world, Clock( lambda n: world[ "cards" ].answer( only_card( world ).id, answered_by=odd ) ) )
    assert out[ "reason" ] == "wrong_login" and world[ "flow" ].calls == []


def test_another_seat_cannot_start_the_card_it_did_not_ask( world ):
    first = call( world, Clock() )
    world[ "cards" ].answer( first[ "card_id" ] )
    out = call( world, Clock(), card_id=first[ "card_id" ], actor="sam 0badc0de", host_path="" )
    assert out[ "reason" ] == "wrong_session" and out[ "stage" ] == "start"
    assert world[ "flow" ].calls == []


def test_a_second_ask_for_the_same_waiting_file_names_the_card_to_resume( world ):
    first = call( world, Clock() )
    assert first[ "status" ] == "expired"
    out = call( world, Clock() )
    assert out[ "reason" ] == "card_already_waiting" and out[ "card_id" ] == first[ "card_id" ] and "card_id=" in out[ "retry" ]


def test_a_queue_failure_releases_the_card_and_a_resume_starts_the_one_job( world ):
    world[ "flow" ].raises = RuntimeError( "the queue is down" )
    out = call( world, Clock( lambda n: world[ "cards" ].answer( only_card( world ).id ) ) )
    assert out[ "reason" ] == "queue_failed" and "card_id=" in out[ "retry" ]

    world[ "flow" ].raises = None
    resumed = call( world, Clock(), card_id=out[ "card_id" ], host_path="" )
    assert resumed[ "status" ] == "started" and resumed[ "job_id" ] == "pg-1a2b3c4d"
    assert len( world[ "flow" ].calls ) == 2   # the failed submit, then the one that queued


def test_resuming_a_spent_card_reports_its_job_and_queues_nothing( world ):
    started = call( world, Clock( lambda n: world[ "cards" ].answer( only_card( world ).id ) ) )
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
    world[ "cards" ].answer( first[ "card_id" ] )
    out = call( world, Clock(), card_id=first[ "card_id" ] )
    assert out[ "status" ] == "started" and len( world[ "flow" ].calls ) == 1
