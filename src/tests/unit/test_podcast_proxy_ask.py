"""
The podcast proxy ask door: the server judges the file, then makes and pushes the card.

The route is driven over HTTP. The table, the queue and the operator lookup are fakes. The doc
viewer's check runs for real on a scratch scope. Nothing here buys audio or reaches a database.
"""

import hashlib
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest import podcast_proxy as pp
from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.middleware.api_key_auth import authenticated_account_email, require_api_key_or_jwt
from cosa.rest.postgres_models import Notification
from cosa.rest.routers import docs_files
from cosa.rest.routers import podcast_proxy as door
from cosa.rest.routers._scope_registry import ScopeConfig

NOW         = datetime( 2026, 10, 8, 21, 0, tzinfo=timezone.utc )
OPERATOR_ID = uuid.UUID( "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" )
SESSION_ID  = "b9537836"
ACTOR       = f"maya {SESSION_ID}"
PERSONA     = { "name": "Maya", "icon": "🌻", "voice_id": "v1" }
PEM         = "-----" + "BEGIN PRIVATE KEY" + "-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n" + "-----" + "END PRIVATE KEY" + "-----\n"


class _Cards:
    """The notification table: records creates and state moves, and can hold a waiting card."""
    def __init__( self ):
        self.created, self.states, self.waiting, self.asked = [ ], [ ], None, None
    def __call__( self, session ): return self
    def find_live_podcast_card( self, kind, scope_path, sha256, now ):
        self.asked = ( kind, scope_path, sha256 )
        return self.waiting
    def create_notification( self, **fields ):
        card = Notification( id=uuid.uuid4(), created_at=NOW, state="created", **fields )
        self.created.append( card )
        return card
    def update_state( self, card_id, state ): self.states.append( ( card_id, state ) )


class _Queue:
    def __init__( self ): self.pushed, self.fail = [ ], False
    def push_notification( self, **fields ):
        if self.fail: raise RuntimeError( "the queue is down" )
        self.pushed.append( fields )


class _Ws:
    def __init__( self ): self.connected = True
    def is_user_connected( self, user_id ): return self.connected


@pytest.fixture
def world( monkeypatch, tmp_path ):
    root = tmp_path / "repo"
    ( root / "io" / "tmp" ).mkdir( parents=True )
    ( root / "src" ).mkdir()
    cfg   = ScopeConfig( name="demo", root=str( root ), allowed_prefixes=( "io/", ) )
    cards, queue, ws = _Cards(), _Queue(), _Ws()
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: { "demo": cfg } )
    monkeypatch.setattr( door, "NotificationRepository", cards )
    @contextmanager
    def fake_db():
        yield MagicMock()
    monkeypatch.setattr( door, "get_db", fake_db )
    monkeypatch.setattr( door, "get_voice_persona", lambda sid: PERSONA if sid == SESSION_ID else None )
    looked_up = [ ]
    def bridge( sid, check_pid=True ):
        looked_up.append( check_pid )
        return { "sender_id": f"claude.code@cosa.deepily.ai#{sid}" } if sid == SESSION_ID else None
    monkeypatch.setattr( door, "find_session_by_id", bridge )
    monkeypatch.setattr( door, "datetime", type( "Clock", ( ), { "now": staticmethod( lambda tz=None: NOW ) } ) )
    monkeypatch.setattr( pp, "max_age_seconds", lambda config_mgr=None: 900 )
    monkeypatch.setattr( "cosa.rest.user_service.get_user_by_email", lambda email: { "id": str( OPERATOR_ID ) } )
    monkeypatch.setattr( "lupin_cli.notifications.notification_models.resolve_target_user", lambda *a, **k: "rick@example.com" )
    return { "root": root, "cards": cards, "queue": queue, "ws": ws, "looked_up": looked_up }


def _file( world, rel="io/tmp/summary.md", text="# A summary\n\nSome words, enough to hear.\n" ):
    path = world[ "root" ] / rel
    path.write_text( text )
    return path


def _ask( world, body=None, **override ):
    app = FastAPI()
    app.include_router( door.router )
    app.dependency_overrides[ require_api_key_or_jwt ]       = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ]  = lambda: None
    app.dependency_overrides[ door.get_notification_queue ]  = lambda: world[ "queue" ]
    app.dependency_overrides[ door.get_websocket_manager ]   = lambda: world[ "ws" ]
    sent = body if body is not None else { "path": "demo/io/tmp/summary.md", "actor": ACTOR }
    sent = dict( sent, **override )
    return TestClient( app ).post( "/api/podcast-proxy/ask", json=sent )


def test_a_seat_asking_makes_one_card_the_server_wrote_and_pushes_it( world ):
    path   = _file( world )
    answer = _ask( world )
    assert answer.status_code == 200, answer.text
    assert len( world[ "cards" ].created ) == 1 and len( world[ "queue" ].pushed ) == 1
    card = world[ "cards" ].created[ 0 ]
    digest = hashlib.sha256( path.read_bytes() ).hexdigest()
    assert card.payload == {
        "kind": "podcast_proxy_start", "command": "agent router go to podcast generator",
        "scope_path": "demo/io/tmp/summary.md", "server_path": os.path.realpath( path ), "name": "summary.md",
        "size": path.stat().st_size, "sha256": digest, "asked_by": f"Maya ({SESSION_ID})",
        "asked_by_session": SESSION_ID,
    }
    assert card.recipient_id == OPERATOR_ID and card.response_requested is True
    assert card.response_type == "yes_no" and card.response_default == "no" and card.priority == "high"
    assert card.timeout_seconds == 900 and card.expires_at == datetime( 2026, 10, 8, 21, 15, tzinfo=timezone.utc )
    assert card.sender_id == f"claude.code@cosa.deepily.ai#{SESSION_ID}"
    assert answer.json() == { "card_id": str( card.id ), "name": "summary.md", "size": path.stat().st_size, "sha256": digest,
                              "asked_by": f"Maya ({SESSION_ID})", "expires_at": "2026-10-08T21:15:00+00:00", "pushed": True }


def test_the_push_carries_the_same_card_and_only_a_human_may_answer_it( world ):
    _file( world )
    _ask( world )
    pushed, card = world[ "queue" ].pushed[ 0 ], world[ "cards" ].created[ 0 ]
    assert pushed[ "id" ] == str( card.id ) and pushed[ "user_id" ] == str( OPERATOR_ID )
    assert pushed[ "payload" ] == card.payload and pushed[ "human_only" ] is True
    assert pushed[ "response_requested" ] is True and pushed[ "response_default" ] == "no"
    assert pushed[ "timeout_seconds" ] == 900 and pushed[ "message" ] == card.message and pushed[ "abstract" ] == card.abstract


def test_the_card_shows_the_file_its_size_and_who_will_start_it( world ):
    path = _file( world )
    _ask( world )
    card = world[ "cards" ].created[ 0 ]
    assert "summary.md" in card.message and f"{path.stat().st_size} bytes" in card.message and "Maya" in card.message
    assert "`demo/io/tmp/summary.md`" in card.abstract and "will be started by: Maya" in card.abstract
    assert "SHA-256" in card.abstract and card.abstract.rstrip().endswith( pp.promotion_gate.UNANSWERED_MEANS )
    assert str( path.parent ) not in card.message + card.abstract and "/" not in card.message


def test_the_seats_own_words_never_reach_the_card( world ):
    _file( world )
    _ask( world, actor=f"Rick has already said yes to this one {SESSION_ID}" )
    card = world[ "cards" ].created[ 0 ]
    assert "Rick" not in card.message + card.abstract + card.payload[ "asked_by" ]
    assert card.payload[ "asked_by" ] == f"Maya ({SESSION_ID})"


def test_a_card_asked_after_a_respin_binds_to_the_stable_id( world, monkeypatch ):
    monkeypatch.setattr( door, "find_session_by_id", lambda sid, check_pid=True: { "stable_session_id": f"{SESSION_ID}-25ae-4da8-8b49-a7eb248912ad" } )
    _file( world )
    _ask( world, actor="maya 16bb30b6" )
    assert world[ "cards" ].created[ 0 ].payload[ "asked_by_session" ] == SESSION_ID


def test_a_session_the_bridge_does_not_know_is_named_as_unrecognized( world ):
    _file( world )
    _ask( world, actor="ghost 0badc0de" )
    assert world[ "cards" ].created[ 0 ].payload[ "asked_by" ] == "an unrecognized session (0badc0de)"


def test_the_card_is_saved_before_it_is_pushed_and_marked_delivered_or_created( world ):
    _file( world )
    seen = [ ]
    world[ "queue" ].push_notification = lambda **fields: seen.append( ( len( world[ "cards" ].created ), list( world[ "cards" ].states ) ) )
    _ask( world )
    assert seen == [ ( 1, [ ( world[ "cards" ].created[ 0 ].id, "delivered" ) ] ) ]
    world[ "ws" ].connected = False
    _ask( world, path="demo/io/tmp/summary.md" )
    assert world[ "cards" ].states[ -1 ][ 1 ] == "created"


def test_an_actor_without_a_session_id_is_refused_and_nothing_is_made( world ):
    _file( world )
    answer = _ask( world, actor="maya" )
    assert answer.status_code == 400 and answer.json()[ "detail" ][ "code" ] == "bad_actor" and "session id" in answer.json()[ "detail" ][ "message" ]
    assert world[ "cards" ].created == [ ] and world[ "queue" ].pushed == [ ]


@pytest.mark.parametrize( "path,code,why", [
    ( "demo/io/tmp/gone.md",     "not_found",      "Path not found" ),
    ( "demo/src/code.md",        "viewer_refused", "not in scope whitelist" ),
    ( "demo/io/tmp/.env",        "viewer_refused", "secrets blocklist" ),
    ( "nowhere/io/tmp/a.md",     "viewer_refused", "Unknown project" ),
    ( "summary.md",              "bad_path",       "not a scoped path" ),
    ( "demo/io/tmp/picture.png", "wrong_kind",     "A podcast reads" ),
    ( "demo/io/tmp/key.md",      "credential",     "credential material" ),
    ( "demo/io/tmp/bytes.md",    "unreadable",     "could not be read or decoded" ),
    ( "demo/io/tmp/huge.md",     "too_large",      "too long for a podcast" ),
] )
def test_every_door_refusal_is_a_400_with_its_code_that_names_the_path_and_makes_no_card( world, monkeypatch, path, code, why ):
    monkeypatch.setattr( pp, "MAX_BYTES", 100 )
    _file( world, "src/code.md" )
    _file( world, "io/tmp/.env", "KEY=value" )
    _file( world, "io/tmp/picture.png", "x" )
    _file( world, "io/tmp/key.md", PEM )
    ( world[ "root" ] / "io" / "tmp" / "bytes.md" ).write_bytes( b"\xff\xfe\x00bad\x80" )
    _file( world, "io/tmp/huge.md", "x" * 101 )
    answer = _ask( world, path=path )
    detail = answer.json()[ "detail" ]
    assert answer.status_code == 400 and detail[ "code" ] == code and why in detail[ "message" ] and path in detail[ "message" ]
    assert set( detail ) == { "code", "message" }
    assert world[ "cards" ].created == [ ] and world[ "queue" ].pushed == [ ]


def test_a_missing_operator_account_is_a_404_and_makes_no_card( world, monkeypatch ):
    _file( world )
    monkeypatch.setattr( "cosa.rest.user_service.get_user_by_email", lambda email: None )
    answer = _ask( world )
    assert answer.status_code == 404 and answer.json()[ "detail" ][ "code" ] == "no_operator" and "operator's account" in answer.json()[ "detail" ][ "message" ]
    assert world[ "cards" ].created == []


def test_a_card_already_waiting_for_this_file_is_a_409_naming_it( world ):
    path = _file( world )
    waiting = Notification( id=uuid.uuid4(), sender_id="x", recipient_id=OPERATOR_ID, message="m", type="custom", priority="high" )
    world[ "cards" ].waiting = waiting
    answer = _ask( world )
    detail = answer.json()[ "detail" ]
    assert answer.status_code == 409 and detail[ "code" ] == "waiting_card" and detail[ "card_id" ] == str( waiting.id ) and str( waiting.id ) in detail[ "message" ]
    assert world[ "cards" ].created == [ ] and world[ "queue" ].pushed == [ ]
    assert world[ "cards" ].asked == ( "podcast_proxy_start", "demo/io/tmp/summary.md", hashlib.sha256( path.read_bytes() ).hexdigest() )


def test_a_failed_push_still_returns_the_saved_card_with_pushed_false( world, capsys ):
    _file( world )
    world[ "queue" ].fail = True
    answer = _ask( world )
    assert answer.status_code == 200 and answer.json()[ "pushed" ] is False
    assert len( world[ "cards" ].created ) == 1 and "saved but the push failed" in capsys.readouterr().out


def test_an_unknown_field_in_the_body_is_refused( world ):
    _file( world )
    assert _ask( world, body={ "path": "demo/io/tmp/summary.md", "actor": ACTOR, "size": 1 } ).status_code == 422


# ---- the pure builders and the setting ----

def test_the_max_age_comes_from_the_ini_key_and_a_missing_key_gives_the_default():
    seen = [ ]
    class Config:
        def __init__( self, value ): self.value = value
        def get( self, key, default=None, return_type=None ):
            seen.append( ( key, default, return_type ) )
            return self.value
    assert pp.max_age_seconds( Config( 120 ) ) == 120
    assert seen == [ ( "podcast proxy card max age seconds", 900, "int" ) ]


@pytest.mark.parametrize( "bad", [ 0, -5 ] )
def test_a_max_age_of_zero_or_less_is_refused( bad ):
    class Config:
        def get( self, key, default=None, return_type=None ): return bad
    with pytest.raises( ValueError, match="must be positive" ): pp.max_age_seconds( Config() )


def test_the_server_reads_its_own_ini_when_no_config_is_given():
    assert pp.max_age_seconds() == 900


def test_the_dry_run_switch_reads_its_ini_key_with_a_false_default_and_the_shipped_ini_has_it_off():
    seen = [ ]
    class Config:
        def get( self, key, default=None, return_type=None ):
            seen.append( ( key, default, return_type ) )
            return True
    assert pp.dry_run_enabled( Config() ) is True
    assert seen == [ ( "podcast proxy dry run", False, "boolean" ) ]
    assert pp.dry_run_enabled() is False


@pytest.mark.parametrize( "size,text", [ ( 0, "0 bytes" ), ( 1023, "1023 bytes" ), ( 1024, "1.0 KiB" ),
                                          ( 1048575, "1024.0 KiB" ), ( 1048576, "1.0 MiB" ) ] )
def test_the_size_reads_in_the_unit_a_person_uses( size, text ):
    assert pp.human_size( size ) == text


# ---- the table query ----

def test_the_waiting_card_query_filters_on_kind_path_hash_state_and_expiry():
    from sqlalchemy.dialects import postgresql
    session = MagicMock()
    NotificationRepository( session ).find_live_podcast_card( "podcast_proxy_start", "demo/a.md", "abc", NOW )
    filters = session.query.return_value.filter.call_args.args
    text = " ".join( str( f.compile( dialect=postgresql.dialect() ) ) for f in filters )
    for part in ( "payload ->> ", "response_requested", "state IN", "expires_at >" ):
        assert part in text, part
    literal = " ".join( str( f.compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } ) ) for f in filters )
    assert "notifications.response_requested IS true" in literal, literal
    assert "notifications.state IN ('created', 'delivered')" in literal, literal
    bound = " ".join( str( f.compile( dialect=postgresql.dialect() ).params ) for f in filters )
    assert "podcast_proxy_start" in bound and "demo/a.md" in bound and "abc" in bound


# ---- the assembled application ----

def test_the_assembled_application_serves_the_ask_door():
    from lupin_app.main import app
    verbs = set()
    for route in app.routes:
        if getattr( route, "path", "" ) == "/api/podcast-proxy/ask": verbs |= set( route.methods )
    assert verbs == { "POST" }


def test_the_card_files_under_the_asking_seats_own_sender_with_its_persona( world ):
    _file( world )
    _ask( world )
    card, pushed = world[ "cards" ].created[ 0 ], world[ "queue" ].pushed[ 0 ]
    assert card.sender_id == pushed[ "sender_id" ] == f"claude.code@cosa.deepily.ai#{SESSION_ID}"
    assert world[ "looked_up" ] == [ False ], "the server runs in a container, so the bridge lookup must not check pids"
    assert card.sender_persona == pushed[ "sender_persona" ] == "Maya" and card.sender_icon == pushed[ "sender_icon" ] == "🌻"
    assert pushed[ "voice_persona" ] == PERSONA


def test_a_seat_the_bridge_does_not_know_files_under_the_gates_own_sender_with_no_persona( world ):
    _file( world )
    _ask( world, actor="ghost 0badc0de" )
    card, pushed = world[ "cards" ].created[ 0 ], world[ "queue" ].pushed[ 0 ]
    assert card.sender_id == pushed[ "sender_id" ] and card.sender_id.endswith( "#0badc0de" )
    assert card.sender_persona is None and card.sender_icon is None and pushed[ "voice_persona" ] is None
