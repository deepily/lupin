"""
D-V1 — the auth-lane negative control for the late-answer handback (§4.4 / §7).
Store row `7bb0a7df` (P1). Rick's ONE hard precondition.

WHAT THE PLAN FEARED (§7): the catch-up fetch reading the listener's ambient
service-account `self._user_id` instead of the X-API-Key lane → a correct-looking,
SILENTLY EMPTY list. D-V1 is the negative control that must prove the seeded owed
row comes BACK — "an empty result is NOT the pass signal."

WHAT WE FOUND (Rachel, verified independently; Clayton concurs): the trap is
CLOSED BY CONSTRUCTION, which is STRONGER than "the fetch happens to use the right
lane." The endpoint (`get_answers_owed` at notifications.py:1561) takes
authenticated_user_id from require_api_key_or_jwt but NEVER uses it; the repo query
(`get_answers_owed_for_persona`) is persona-keyed ALONE (ruling 6). And
`answer_catchup._fetch_owed` has no user_id parameter at all. So `self._user_id`
cannot scope the fetch by any path.

This test proves that on REAL credentials through the REAL route, in-process:
  1. POSITIVE — seed an owed row for the human owner; call the endpoint with the
     human's real X-API-Key (validated by the real require_api_key_or_jwt bcrypt
     path); assert the row is PRESENT (anchored — never an empty-result green).
  2. IDENTITY-AGNOSTIC CONTROL — call with a DIFFERENT valid key (a service
     account, standing in for the listener's ambient identity); assert the row is
     STILL present. This is the negative control proper: a non-owner identity does
     NOT suppress the row, because the query never consults the caller.
  3. AUTH GATE — a bogus key is 401 (the lane still authenticates).
  4. RED-PROOF (injected misrouting, per Clayton's prescription) — patch the repo
     query to additionally filter recipient_id == the service account (the exact
     "route through self._user_id" misrouting), call as anyone; the human-owned row
     VANISHES → red. This is what proves the POSITIVE assertion is falsifiable and
     that the persona-only query is what keeps the answer reachable.

Venue: in-process TestClient + a self-cleaning throwaway DB migrated to head. No
shared-infra bounce (:7999 runs old code with lupin_db_dev un-migrated — the §3
reload-off trap; sidestepped here). SKIPS when Postgres is unreachable. The full
live round-trip via the test-suite scheduler is DEFERRED until lupin_db_test
carries migration 3da5c0d1eee6 (María's venue call, 2026-08-01).

NOTE (filed separately as a bug row): the same persona-only query means the
endpoint AUTHENTICATES but does not AUTHORIZE — any valid key can pull any
persona's owed answers. Orthogonal to this precondition; not fixed here.
"""
import os
import uuid
from datetime import datetime, timezone
from unittest import mock

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError

from alembic import command

from cosa.rest.db import database as db_module
from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import User, Notification, ApiKey
from cosa.rest.db.repositories import notification_repository as nr_module
import cosa.rest.routers.notifications as notif_module
from cosa.rest.routers.notifications import router


_THROWAWAY_DB = f"answers_owed_authlane_{os.getpid()}"
_PERSONA      = "authlane_persona"
# require_api_key_or_jwt enforces the format ^ck_live_[A-Za-z0-9_-]{64,}$ BEFORE
# bcrypt validation, so the raw keys must be well-formed (64+ chars after ck_live_).
_HUMAN_KEY    = "ck_live_" + ( "h" * 64 )
_SVC_KEY      = "ck_live_" + ( "s" * 64 )

_ENDPOINT = "/api/notifications/answers-owed"


def _server_url():
    db_module.swap_database( "testing" )
    return db_module.engine.url


def _maintenance_engine( server_url ):
    return create_engine( server_url, isolation_level="AUTOCOMMIT" )


def _bcrypt( raw ):
    return bcrypt.hashpw( raw.encode( "utf-8" ), bcrypt.gensalt() ).decode( "utf-8" )


@pytest.fixture( scope="module" )
def authlane_ctx():
    """
    Throwaway DB → upgrade head → repoint the GLOBAL engine/SessionLocal so BOTH the
    endpoint's get_db and the auth middleware's get_db use it → seed users + real
    bcrypt api_keys + one owed row. Yields (client, seeded_ids). Restores globals and
    drops the DB on teardown. SKIPS when Postgres is unreachable.
    """
    server_url = _server_url()
    try:
        eng = _maintenance_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
            conn.execute( text( f'CREATE DATABASE "{_THROWAWAY_DB}"' ) )
        eng.dispose()
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable — skipping D-V1 auth-lane test: {e}" )

    throwaway_url = server_url.set( database=_THROWAWAY_DB ).render_as_string( hide_password=False )
    command.upgrade( build_alembic_config( database_url=throwaway_url ), "head" )

    # ── repoint the global engine so get_db() (endpoint + auth) hits the throwaway ──
    saved = ( db_module.engine, db_module.SessionLocal, db_module.ScopedSession )
    tw_engine  = create_engine( throwaway_url )
    tw_session = sessionmaker( autocommit=False, autoflush=False, bind=tw_engine )
    db_module.engine        = tw_engine
    db_module.SessionLocal  = tw_session
    db_module.ScopedSession = scoped_session( tw_session )

    human_id = uuid.uuid4()
    svc_id   = uuid.uuid4()
    notif_id = uuid.uuid4()

    s = tw_session()
    try:
        for uid, email in ( ( human_id, "owner@dv1.local" ), ( svc_id, "svc@dv1.local" ) ):
            s.add( User( id=uid, email=email, password_hash="x", email_verified=True,
                         is_active=True, is_protected=False, roles={ "roles": [ "user" ] },
                         created_at=datetime.now( timezone.utc ) ) )
        s.add( ApiKey( id=uuid.uuid4(), user_id=human_id, key_hash=_bcrypt( _HUMAN_KEY ),
                       description="dv1 human", is_active=True, created_at=datetime.now( timezone.utc ) ) )
        s.add( ApiKey( id=uuid.uuid4(), user_id=svc_id, key_hash=_bcrypt( _SVC_KEY ),
                       description="dv1 service acct", is_active=True, created_at=datetime.now( timezone.utc ) ) )
        # the owed row: answered, undelivered, owned by the HUMAN, keyed by persona P
        s.add( Notification( id=notif_id, sender_id="cc@lupin#humansess", recipient_id=human_id,
                             message="the question that was asked", type="task", priority="high",
                             created_at=datetime.now( timezone.utc ), sender_persona=_PERSONA,
                             response_requested=True, responded_at=datetime.now( timezone.utc ),
                             answer_delivered_at=None, state="created" ) )
        s.commit()
    finally:
        s.close()

    # The age cap reads lupin_app.main.config_mgr, which is None under a router-only
    # TestClient (no full-app startup). Stub it to the INI default (24h) — the age cap
    # is not what D-V1 tests, and the seeded row is fresh, so the default never excludes it.
    age_patch = mock.patch.object( notif_module, "_undelivered_max_age_hours", lambda: 24 )
    age_patch.start()
    # get_local_timestamp() also reads the (None) module config_mgr; it only stamps the
    # response envelope's timestamp — irrelevant to the auth lane / query under test.
    ts_patch = mock.patch.object( notif_module, "get_local_timestamp", lambda: "2026-08-01T00:00:00" )
    ts_patch.start()

    app = FastAPI()
    app.include_router( router )
    client = TestClient( app )

    yield client, { "human_id": human_id, "svc_id": svc_id, "notif_id": str( notif_id ) }

    # ── restore globals + drop throwaway ──
    ts_patch.stop()
    age_patch.stop()
    tw_engine.dispose()
    db_module.engine, db_module.SessionLocal, db_module.ScopedSession = saved
    eng = _maintenance_engine( server_url )
    with eng.connect() as conn:
        conn.execute( text(
            "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
            "WHERE datname = :db AND pid <> pg_backend_pid()"
        ), { "db": _THROWAWAY_DB } )
        conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
    eng.dispose()


def _pull( client, key, persona=_PERSONA ):
    return client.get( _ENDPOINT, params={ "persona": persona, "limit": 100 },
                       headers={ "X-API-Key": key } )


def _row_present( body, notif_id ):
    answers = body.get( "answers", [] ) if isinstance( body, dict ) else []
    return any( str( a.get( "notification_id" ) ) == notif_id or str( a.get( "id" ) ) == notif_id
                for a in answers )


def test_dv1_positive_human_key_returns_owed_row( authlane_ctx ):
    """The human owner's real X-API-Key pulls the seeded owed row — PRESENT, not empty."""
    client, ids = authlane_ctx
    resp = _pull( client, _HUMAN_KEY )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _row_present( body, ids[ "notif_id" ] ), (
        f"owed row must be PRESENT via the human X-API-Key lane (owed_count={body.get('owed_count')})"
    )


def test_dv1_identity_agnostic_service_account_key_still_returns_row( authlane_ctx ):
    """
    A DIFFERENT valid key (service account — the listener's ambient identity) STILL
    returns the human-owned row: the query never consults the caller, so self._user_id
    cannot suppress it. This is the negative control the precondition asked for.
    """
    client, ids = authlane_ctx
    resp = _pull( client, _SVC_KEY )
    assert resp.status_code == 200, resp.text
    assert _row_present( resp.json(), ids[ "notif_id" ] ), (
        "the service-account identity must NOT suppress the owed row (persona-keyed by construction)"
    )


def test_dv1_bogus_key_is_rejected( authlane_ctx ):
    """The lane still AUTHENTICATES — a bogus key is 401/403, not a silent empty."""
    client, _ = authlane_ctx
    resp = _pull( client, "totally-bogus-key" )
    assert resp.status_code in ( 401, 403 ), resp.text


def test_dv1_redproof_recipient_scoping_would_vanish_the_row( authlane_ctx ):
    """
    RED-PROOF (Clayton's prescribed misrouting): if the query were rerouted through
    the caller identity — a recipient_id == service-account filter — the human-owned
    owed row VANISHES. This proves the positive assertion is falsifiable and that the
    persona-only query is exactly what keeps the answer reachable.
    """
    client, ids = authlane_ctx
    svc_uuid = ids[ "svc_id" ]
    real = nr_module.NotificationRepository.get_answers_owed_for_persona

    def _misrouted( self, sender_persona, limit=100, max_age_hours=None, since=None ):
        # the exact "route through self._user_id" defect: scope by a recipient identity
        return self.session.query( Notification ).filter(
            Notification.sender_persona == sender_persona,
            Notification.response_requested == True,
            Notification.responded_at.isnot( None ),
            Notification.answer_delivered_at.is_( None ),
            Notification.recipient_id == svc_uuid,      # <-- the misrouting
        ).all()

    # sanity: unpatched, the row is present (guards against a vacuous red)
    assert _row_present( _pull( client, _SVC_KEY ).json(), ids[ "notif_id" ] )

    with mock.patch.object( nr_module.NotificationRepository, "get_answers_owed_for_persona", _misrouted ):
        resp = _pull( client, _SVC_KEY )
        assert resp.status_code == 200, resp.text
        assert not _row_present( resp.json(), ids[ "notif_id" ] ), (
            "with a recipient_id==self._user_id filter the human-owned row must VANISH (the silent-empty defect)"
        )

    # restored automatically: the row is reachable again
    assert _row_present( _pull( client, _SVC_KEY ).json(), ids[ "notif_id" ] )
