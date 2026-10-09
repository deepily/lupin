"""
The podcast proxy start door and the card status door, driven over HTTP.

The notification table is a fake that holds prepared cards. The spent-card record is the real
repository on a SQLite file, so the primary key really decides. The doc viewer's check runs for real
on a scratch scope, and the job queue is stubbed at flow.submit: nothing here buys audio.
"""

import hashlib
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cosa.rest import podcast_proxy as pp
from cosa.rest import task_promotion_gate as gate
from cosa.rest.db.repositories.podcast_proxy_spent_repository import PodcastProxySpentRepository
from cosa.rest.middleware.api_key_auth import authenticated_account_email, require_api_key_or_jwt
from cosa.rest.postgres_models import Notification, PodcastProxySpentCard
from cosa.rest.routers import docs_files
from cosa.rest.routers import podcast_proxy as door
from cosa.rest.routers._scope_registry import ScopeConfig

NOW         = datetime( 2026, 10, 8, 21, 0, tzinfo=timezone.utc )
MADE_AT     = NOW - timedelta( minutes = 2 )
OPERATOR_ID = uuid.UUID( "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" )
SESSION_ID  = "b9537836"
ACTOR       = f"maya {SESSION_ID}"
RICK        = "rick@example.com"
OPERATOR    = { "user_id": "u-1", "account_email": RICK, "method": "jwt" }


class _Cards:
    def __init__( self ): self.rows = { }
    def __call__( self, session ): return self
    def get_by_id( self, card_id ): return self.rows.get( card_id )


class _Flow:
    """Stands in for the v2 submit path: records every submit and answers like a queued job."""
    def __init__( self ):
        self.calls, self.answer, self.raises, self.hook = [ ], { "status": "waiting", "job_id": "pg-1a2b3c4d", "queue_position": 3 }, None, None
    def submit( self, **kwargs ):
        self.calls.append( kwargs )
        if self.hook: self.hook()
        if self.raises: raise self.raises
        return dict( self.answer )


@pytest.fixture( autouse=True )
def accounts( monkeypatch ):
    monkeypatch.setattr( gate, "approver_persona_for_account", lambda email: { RICK: "rick" }.get( email ) )


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
    cards, flow = _Cards(), _Flow()
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: { "demo": cfg } )
    monkeypatch.setattr( door, "NotificationRepository", cards )
    monkeypatch.setattr( door, "get_db", fake_db )
    monkeypatch.setattr( door, "datetime", type( "Clock", ( ), { "now": staticmethod( lambda tz=None: NOW ) } ) )
    bridge = { }
    monkeypatch.setattr( door, "find_session_by_id", lambda sid, check_pid=True: bridge.get( sid ) )
    monkeypatch.setattr( door, "copy_directory", lambda: str( tmp_path / "copies" ) )
    monkeypatch.setattr( pp, "max_age_seconds", lambda config_mgr=None: 900 )
    monkeypatch.setattr( pp, "dry_run_enabled", lambda config_mgr=None: False )
    monkeypatch.setattr( "cosa.rest.user_service.get_user_by_id", lambda user_id: { "id": user_id, "email": RICK } )
    world = { "root": root, "cards": cards, "flow": flow, "sessions": sessions, "copies": tmp_path / "copies", "bridge": bridge, "registry": { "demo": cfg } }
    world[ "path" ] = root / "io" / "tmp" / "summary.md"
    world[ "path" ].write_text( "# A summary\n\nSome words, enough to hear.\n" )
    return world


def _card( world, **overrides ):
    """A card the ask door would have written for the scratch file, answered yes by the operator."""
    facts   = pp.check_source( "demo/io/tmp/summary.md", world[ "registry" ] )
    fields  = dict(
        id=uuid.uuid4(), sender_id="x", recipient_id=OPERATOR_ID, message="m", type="custom", priority="high",
        response_requested=True, response_type="yes_no", state="responded", responded_at=MADE_AT + timedelta( seconds=30 ),
        payload=pp.card_payload( facts, f"Maya ({SESSION_ID})", SESSION_ID ), created_at=MADE_AT, expires_at=MADE_AT + timedelta( seconds=900 ),
        response_value={ "value": "yes", "source": "ui", "answered_by": dict( OPERATOR ) },
    )
    fields.update( overrides )
    card = Notification( **fields )
    world[ "cards" ].rows[ card.id ] = card
    return card


def _start( world, card_id, actor=ACTOR, body=None ):
    app = FastAPI()
    app.include_router( door.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    app.dependency_overrides[ door.get_ask_flow ]      = lambda: world[ "flow" ]
    sent = body if body is not None else { "card_id": str( card_id ), "actor": actor }
    return TestClient( app ).post( "/api/podcast-proxy/start", json=sent )


def _code( answer ): return answer.json()[ "detail" ][ "code" ]


def _spent( world ):
    with world[ "sessions" ]() as session: return session.query( PodcastProxySpentCard ).all()


# ---- the positive control ----

def test_a_yes_on_a_server_made_card_starts_one_job_for_the_operator( world ):
    card   = _card( world )
    answer = _start( world, card.id )
    assert answer.status_code == 200, answer.text
    assert answer.json() == { "card_id": str( card.id ), "job_id": "pg-1a2b3c4d", "status": "waiting", "name": "summary.md", "queue_position": 3 }
    assert len( world[ "flow" ].calls ) == 1
    call = world[ "flow" ].calls[ 0 ]
    assert call[ "command" ] == "agent router go to podcast generator" and call[ "user_id" ] == str( OPERATOR_ID ) and call[ "user_email" ] == RICK
    assert call[ "speak" ] is False and set( call[ "args" ] ) == { "research" }


def test_with_the_dry_run_switch_off_a_yes_queues_a_real_job( world ):
    card   = _card( world )
    answer = _start( world, card.id )
    assert answer.status_code == 200 and answer.json()[ "status" ] == "waiting" and len( world[ "flow" ].calls ) == 1
    assert _spent( world )[ 0 ].job_id == "pg-1a2b3c4d" and world[ "copies" ].exists()


def test_with_the_dry_run_switch_on_the_checks_and_the_claim_run_and_no_job_is_queued( world, monkeypatch ):
    monkeypatch.setattr( pp, "dry_run_enabled", lambda config_mgr=None: True )
    card   = _card( world )
    answer = _start( world, card.id )
    assert answer.status_code == 200, answer.text
    assert answer.json() == { "card_id": str( card.id ), "job_id": f"dry-run-{str( card.id )[ :8 ]}", "status": "dry run",
                              "name": "summary.md", "queue_position": None }
    assert world[ "flow" ].calls == [ ] and not world[ "copies" ].exists()
    rows = _spent( world )
    assert len( rows ) == 1 and rows[ 0 ].card_id == card.id and rows[ 0 ].job_id == f"dry-run-{str( card.id )[ :8 ]}"
    assert rows[ 0 ].sha256 == hashlib.sha256( world[ "path" ].read_bytes() ).hexdigest()
    again = _start( world, card.id )
    assert again.status_code == 409 and _code( again ) == "spent"


def test_a_dry_run_still_refuses_what_a_real_start_refuses( world, monkeypatch ):
    monkeypatch.setattr( pp, "dry_run_enabled", lambda config_mgr=None: True )
    card = _card( world, response_value={ "value": "no", "source": "ui", "answered_by": dict( OPERATOR ) } )
    answer = _start( world, card.id )
    assert answer.status_code == 403 and _code( answer ) == "not_yes" and _spent( world ) == [ ]


def test_the_job_reads_a_copy_the_server_made_and_not_the_seats_file( world ):
    card = _card( world )
    _start( world, card.id )
    research = world[ "flow" ].calls[ 0 ][ "args" ][ "research" ]
    assert research == str( world[ "copies" ] / str( card.id ) / "summary.md" ) and research != str( world[ "path" ] )
    assert open( research, "rb" ).read() == world[ "path" ].read_bytes()
    assert oct( os.stat( research ).st_mode & 0o777 ) == oct( 0o640 )


def test_the_copy_holds_the_bytes_that_were_judged_even_if_the_file_changes_after_the_check( world, monkeypatch ):
    card   = _card( world )
    judged = world[ "path" ].read_bytes()
    def operator_then_rewrite( user_id ):
        world[ "path" ].write_bytes( b"# Swapped after the check\n\nDifferent words.\n" )
        return { "id": user_id, "email": RICK }
    monkeypatch.setattr( "cosa.rest.user_service.get_user_by_id", operator_then_rewrite )
    answer = _start( world, card.id )
    assert answer.status_code == 200, answer.text
    research = world[ "flow" ].calls[ 0 ][ "args" ][ "research" ]
    assert open( research, "rb" ).read() == judged and world[ "path" ].read_bytes() != judged


def test_the_spent_record_names_the_card_the_starter_the_file_and_the_job( world ):
    card = _card( world )
    _start( world, card.id )
    rows = _spent( world )
    assert len( rows ) == 1
    assert rows[ 0 ].card_id == card.id and rows[ 0 ].started_by == ACTOR and rows[ 0 ].scope_path == "demo/io/tmp/summary.md"
    assert rows[ 0 ].sha256 == hashlib.sha256( world[ "path" ].read_bytes() ).hexdigest() and rows[ 0 ].job_id == "pg-1a2b3c4d"


# ---- every refusal of the stored card, each on its own ----

def test_a_card_that_does_not_exist_is_a_404( world ):
    answer = _start( world, uuid.uuid4() )
    assert answer.status_code == 404 and _code( answer ) == "no_card" and world[ "flow" ].calls == [ ]


@pytest.mark.parametrize( "overrides,code", [
    ( { "payload": { "kind": "unpark_ask", "task_id": "x", "move": "parked->queued" } },        "bad_card" ),
    ( { "payload": None },                                                                         "bad_card" ),
    ( { "response_requested": False },                                                             "bad_card" ),
    ( { "responded_at": None, "state": "delivered", "response_value": None },                     "not_answered" ),
    ( { "state": "expired" },                                                                      "not_answered" ),
    ( { "response_value": { "value": "yes", "source": "timeout_default", "answered_by": dict( OPERATOR ) } }, "default_answer" ),
    ( { "response_value": { "value": "no", "source": "ui", "answered_by": dict( OPERATOR ) } },   "not_yes" ),
    ( { "response_value": { "value": "yes", "source": "ui", "answered_by": { "user_id": "u-2", "account_email": None, "method": "api_key" } } }, "wrong_login" ),
    ( { "created_at": MADE_AT - timedelta( hours=1 ) },                                            "too_old" ),
] )
def test_each_card_refusal_is_its_own_code_and_starts_nothing( world, overrides, code ):
    card   = _card( world, **overrides )
    answer = _start( world, card.id )
    assert answer.status_code == 403 and _code( answer ) == code, answer.text
    assert world[ "flow" ].calls == [ ] and _spent( world ) == [ ] and not world[ "copies" ].exists()


def test_a_payload_with_an_extra_or_missing_key_is_not_the_servers_card( world ):
    base = _card( world ).payload
    for changed in ( dict( base, extra="x" ), { k: v for k, v in base.items() if k != "sha256" }, dict( base, command="agent router go to math" ) ):
        card = _card( world, payload=changed )
        assert _code( _start( world, card.id ) ) == "bad_card"


def test_a_different_session_than_the_asker_cannot_start_it( world ):
    card   = _card( world )
    answer = _start( world, card.id, actor="sam 0badc0de" )
    assert answer.status_code == 403 and _code( answer ) == "wrong_session" and "Maya" in answer.json()[ "detail" ][ "message" ]
    assert world[ "flow" ].calls == [ ]


STABLE_ID  = "b9537836-25ae-4da8-8b49-a7eb248912ad"
RESPUN_ID  = "16bb30b6"


def _seat( world, stable, *ids ):
    """The bridge record a seat keeps: one stable id, and the id of each of its sessions."""
    for known in ids: world[ "bridge" ][ known ] = { "stable_session_id": stable }


def test_a_respun_seat_with_the_same_stable_id_resumes_and_starts_its_card( world ):
    _seat( world, STABLE_ID, SESSION_ID, RESPUN_ID )
    card   = _card( world )
    answer = _start( world, card.id, actor=f"maya {RESPUN_ID}" )
    assert answer.status_code == 200, answer.text
    assert len( world[ "flow" ].calls ) == 1 and len( _spent( world ) ) == 1


def test_a_different_stable_id_is_wrong_session_even_with_a_known_bridge( world ):
    _seat( world, STABLE_ID, SESSION_ID )
    _seat( world, "0badc0de-1111-4222-8333-444444444444", "0badc0de" )
    card   = _card( world )
    answer = _start( world, card.id, actor="sam 0badc0de" )
    assert answer.status_code == 403 and _code( answer ) == "wrong_session"
    assert world[ "flow" ].calls == [ ] and _spent( world ) == [ ]


def test_binding_id_is_the_stable_prefix_when_the_bridge_has_one_and_the_id_otherwise():
    assert pp.binding_id( RESPUN_ID, { "stable_session_id": STABLE_ID } ) == SESSION_ID
    assert pp.binding_id( SESSION_ID, { "stable_session_id": STABLE_ID } ) == SESSION_ID
    assert pp.binding_id( RESPUN_ID, { "session_id": "x" } ) == RESPUN_ID
    assert pp.binding_id( RESPUN_ID, None ) == RESPUN_ID


def test_an_actor_without_a_session_id_is_a_400( world ):
    card   = _card( world )
    answer = _start( world, card.id, actor="maya" )
    assert answer.status_code == 400 and _code( answer ) == "bad_actor"


def test_a_card_exactly_at_the_maximum_age_still_starts_and_one_second_over_does_not( world ):
    on_time = _card( world, created_at=NOW - timedelta( seconds=900 ) )
    assert _start( world, on_time.id ).status_code == 200
    late = _card( world, created_at=NOW - timedelta( seconds=901 ) )
    assert _code( _start( world, late.id ) ) == "too_old"


def test_an_unknown_field_in_the_body_is_a_422( world ):
    card = _card( world )
    assert _start( world, card.id, body={ "card_id": str( card.id ), "actor": ACTOR, "path": "x" } ).status_code == 422
    assert _start( world, card.id, body={ "card_id": "not-a-uuid", "actor": ACTOR } ).status_code == 422


# ---- the file, checked again at start ----

def test_a_file_changed_after_the_yes_is_refused_as_a_hash_mismatch( world ):
    card = _card( world )
    world[ "path" ].write_text( "# A different summary\n\nOther words.\n" )
    answer = _start( world, card.id )
    assert answer.status_code == 409 and _code( answer ) == "hash_mismatch" and "sha256" in answer.json()[ "detail" ][ "message" ]
    assert world[ "flow" ].calls == [ ] and _spent( world ) == [ ]


def test_a_file_the_door_now_refuses_is_a_409_file_refused( world ):
    card = _card( world )
    world[ "path" ].unlink()
    answer = _start( world, card.id )
    assert answer.status_code == 409 and _code( answer ) == "file_refused" and "demo/io/tmp/summary.md" in answer.json()[ "detail" ][ "message" ]
    assert world[ "flow" ].calls == [ ]


def test_a_file_swapped_for_one_of_equal_size_is_still_a_hash_mismatch( world ):
    card = _card( world )
    text = world[ "path" ].read_text()
    world[ "path" ].write_text( text[ ::-1 ] )
    assert world[ "path" ].stat().st_size == card.payload[ "size" ] and _code( _start( world, card.id ) ) == "hash_mismatch"


# ---- one yes, one job ----

def test_a_second_start_of_the_same_card_is_spent_and_queues_nothing_more( world ):
    card = _card( world )
    assert _start( world, card.id ).status_code == 200
    again = _start( world, card.id )
    assert again.status_code == 409 and _code( again ) == "spent"
    assert len( world[ "flow" ].calls ) == 1 and len( _spent( world ) ) == 1


def test_two_starts_at_the_same_moment_queue_exactly_one_job( world ):
    card, barrier, answers = _card( world ), threading.Barrier( 2 ), [ ]
    world[ "flow" ].hook = lambda: None
    original = door.PodcastProxySpentRepository.claim
    def synchronized( self, *args ):
        barrier.wait( 10 )
        return original( self, *args )
    door.PodcastProxySpentRepository.claim = synchronized
    try:
        threads = [ threading.Thread( target=lambda: answers.append( _start( world, card.id ) ) ) for _ in range( 2 ) ]
        for thread in threads: thread.start()
        for thread in threads: thread.join( 60 )
    finally:
        door.PodcastProxySpentRepository.claim = original
    assert sorted( answer.status_code for answer in answers ) == [ 200, 409 ], [ a.text for a in answers ]
    assert len( world[ "flow" ].calls ) == 1 and len( _spent( world ) ) == 1


# ---- the queue fails after the claim: undo it, say so, let the same card try again ----

def test_a_queue_failure_is_logged_with_its_cause_and_the_answer_keeps_it_out( world, capsys ):
    card = _card( world )
    world[ "flow" ].raises = RuntimeError( "connection to /var/lib/secret.sock refused" )
    answer = _start( world, card.id )
    assert "secret.sock" not in answer.text
    assert "secret.sock" in capsys.readouterr().out


def test_a_claim_with_no_job_is_claimed_no_job_on_start_and_on_status_and_is_not_released( world ):
    card = _card( world )
    with world[ "sessions" ]() as session:
        assert PodcastProxySpentRepository( session ).claim( card.id, ACTOR, "demo/io/tmp/summary.md", "0" * 64 )
        session.commit()
    answer = _start( world, card.id )
    assert answer.status_code == 409 and _code( answer ) == "claimed_no_job" and answer.json()[ "detail" ][ "message" ] == "A start of that card is under way, or one did not finish. Read the card status again before asking Rick."
    assert world[ "flow" ].calls == [ ] and len( _spent( world ) ) == 1 and _spent( world )[ 0 ].job_id is None
    status = _status( world, card.id ).json()
    assert status[ "state" ] == "claimed_no_job" and status[ "spent" ] is True and status[ "job_id" ] is None


def test_a_second_start_during_the_queue_call_is_told_a_start_is_under_way_and_starts_nothing( world ):
    card, seen = _card( world ), [ ]
    world[ "flow" ].hook = lambda: seen.append( _start( world, card.id ) )
    first = _start( world, card.id )
    assert first.status_code == 200 and len( world[ "flow" ].calls ) == 1
    assert seen[ 0 ].status_code == 409 and _code( seen[ 0 ] ) == "claimed_no_job"
    assert "under way" in seen[ 0 ].json()[ "detail" ][ "message" ] and len( _spent( world ) ) == 1


def test_a_queue_that_raises_releases_the_claim_and_the_card_can_start_again( world ):
    card = _card( world )
    world[ "flow" ].raises = RuntimeError( "the queue is down" )
    answer = _start( world, card.id )
    assert answer.status_code == 502 and _code( answer ) == "queue_failed" and "the queue is down" not in answer.text
    assert "start the same card again" in answer.json()[ "detail" ][ "message" ] and _spent( world ) == [ ]
    assert not ( world[ "copies" ] / str( card.id ) ).exists(), "the failed start left its copy behind"
    world[ "flow" ].raises = None
    assert _start( world, card.id ).status_code == 200 and len( _spent( world ) ) == 1


@pytest.mark.parametrize( "answer", [ { "status": "failed", "error": "agentic_build_error" }, { "status": "needs_input" }, { "status": "waiting", "job_id": None } ] )
def test_a_queue_answer_that_is_not_a_queued_job_is_a_queue_failure( world, answer ):
    card = _card( world )
    world[ "flow" ].answer = answer
    result = _start( world, card.id )
    assert result.status_code == 502 and _code( result ) == "queue_failed" and _spent( world ) == []


def test_a_copy_that_cannot_be_written_releases_the_claim( world, tmp_path ):
    card = _card( world )
    ( tmp_path / "copies" ).write_text( "a file where the folder should be" )
    answer = _start( world, card.id )
    assert answer.status_code == 502 and _code( answer ) == "queue_failed" and _spent( world ) == [ ] and world[ "flow" ].calls == [ ]


def test_a_missing_operator_account_is_a_404_and_spends_nothing( world, monkeypatch ):
    card = _card( world )
    monkeypatch.setattr( "cosa.rest.user_service.get_user_by_id", lambda user_id: None )
    answer = _start( world, card.id )
    assert answer.status_code == 404 and _code( answer ) == "no_operator" and _spent( world ) == [ ]


# ---- the card status door ----

def _status( world, card_id ):
    app = FastAPI()
    app.include_router( door.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app ).get( f"/api/podcast-proxy/card/{card_id}" )


def test_the_status_of_a_waiting_card_names_the_file_and_is_not_spent( world ):
    card   = _card( world, responded_at=None, state="delivered", response_value=None )
    answer = _status( world, card.id )
    assert answer.status_code == 200
    assert answer.json() == { "card_id": str( card.id ), "scope_path": "demo/io/tmp/summary.md", "name": "summary.md", "size": card.payload[ "size" ],
                              "sha256": card.payload[ "sha256" ], "asked_by_session": SESSION_ID, "state": "waiting",
                              "expires_at": ( MADE_AT + timedelta( seconds=900 ) ).isoformat(), "spent": False, "job_id": None }


@pytest.mark.parametrize( "overrides,state", [
    ( { },                                                                                                           "yes" ),
    ( { "response_value": { "value": "no", "source": "ui", "answered_by": dict( OPERATOR ) } },                       "no" ),
    ( { "response_value": { "value": "no", "source": "timeout_default", "answered_by": dict( OPERATOR ) } },          "default_answer" ),
    ( { "response_value": { "value": "yes", "source": "ui", "answered_by": { "user_id": "u", "account_email": None, "method": "api_key" } } }, "wrong_login" ),
    ( { "responded_at": None, "state": "expired", "response_value": None },                                          "expired" ),
    ( { "responded_at": None, "state": "delivered", "response_value": None, "expires_at": NOW - timedelta( seconds=1 ) }, "expired" ),
    ( { "responded_at": None, "state": "created", "response_value": None, "expires_at": None },                       "waiting" ),
] )
def test_the_status_state_follows_the_stored_answer( world, overrides, state ):
    card = _card( world, **overrides )
    assert _status( world, card.id ).json()[ "state" ] == state


def test_the_status_of_a_spent_card_carries_the_job_id( world ):
    card = _card( world )
    _start( world, card.id )
    body = _status( world, card.id ).json()
    assert body[ "spent" ] is True and body[ "job_id" ] == "pg-1a2b3c4d"


@pytest.mark.parametrize( "make", [ lambda w: uuid.uuid4(), lambda w: _card( w, payload={ "kind": "unpark_ask" } ).id, lambda w: _card( w, payload=None ).id ] )
def test_the_status_of_something_that_is_not_a_podcast_card_is_a_404( world, make ):
    answer = _status( world, make( world ) )
    assert answer.status_code == 404 and _code( answer ) == "no_card"


def test_the_assembled_application_serves_every_podcast_door_with_its_verb():
    from lupin_app.main import app
    verbs = { }
    for route in app.routes:
        if getattr( route, "path", "" ).startswith( "/api/podcast-proxy/" ): verbs.setdefault( route.path, set() ).update( route.methods )
    assert verbs == { "/api/podcast-proxy/ask": { "POST" }, "/api/podcast-proxy/start": { "POST" }, "/api/podcast-proxy/card/{card_id}": { "GET" },
                      "/api/podcast-proxy/from-viewer": { "POST" }, "/api/podcast-proxy/from-viewer/check": { "GET" } }


def test_a_stale_copy_of_the_same_card_is_replaced_and_a_planted_link_is_not_followed( world, tmp_path ):
    card   = _card( world )
    folder = world[ "copies" ] / str( card.id )
    folder.mkdir( parents=True )
    victim = tmp_path / "victim.txt"
    victim.write_text( "keep me" )
    os.symlink( victim, folder / "summary.md" )
    assert _start( world, card.id ).status_code == 200
    assert victim.read_text() == "keep me" and ( folder / "summary.md" ).read_bytes() == world[ "path" ].read_bytes()
    assert not ( folder / "summary.md" ).is_symlink()


def test_removing_a_copy_that_is_not_there_does_nothing( tmp_path ):
    pp.remove_copy( str( tmp_path / "copies" ), uuid.uuid4() )


def test_the_copies_live_under_io_podcast_proxy_in_the_project_root( monkeypatch ):
    monkeypatch.undo()
    from cosa.rest.routers import podcast_proxy as real
    import cosa.utils.util as cu
    assert real.copy_directory() == os.path.join( cu.get_project_root(), "io", "podcast-proxy" )


def test_a_card_whose_stored_path_differs_from_the_file_now_is_a_hash_mismatch_even_with_equal_bytes( world ):
    card = _card( world )
    card.payload = dict( card.payload, server_path="/var/lupin/io/tmp/some-other-copy.md" )
    answer = _start( world, card.id )
    assert answer.status_code == 409 and _code( answer ) == "hash_mismatch" and "server_path" in answer.json()[ "detail" ][ "message" ]


def test_a_planted_link_is_never_written_through_even_when_the_stale_copy_check_is_skipped( world, tmp_path, monkeypatch ):
    folder = world[ "copies" ] / "planted"
    folder.mkdir( parents=True )
    victim = tmp_path / "victim.txt"
    victim.write_text( "keep me" )
    os.symlink( victim, folder / "summary.md" )
    monkeypatch.setattr( pp.os.path, "lexists", lambda path: False )
    with pytest.raises( FileExistsError ): pp.write_copy( str( world[ "copies" ] ), "planted", "summary.md", b"new bytes" )
    assert victim.read_text() == "keep me"
