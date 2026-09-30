"""
E2E — late-answer handback: an answered ask must REACH the session that asked it.

Store rows `6f22531f` (review_request, §5 item 4) / `df698896` (tester leg).
Design: `src/rnd/v0.1.9/2026.08.01-late-answer-handback.md` §5 (E2E tier).
Revision handoff: `src/rnd/v0.1.9/2026.08.01-cascade-revision-handoff-late-answer.md`.

THE BUG BEING HUNTED — an answer that EXISTS but never ARRIVES. Rick's words:
"three action-requested notifications arrive ... then the server gets rebooted and
drops all of the currently active user sessions." The answer is written to Postgres,
then handed back only by waking an IN-MEMORY dict (`pending_responses`). A restart
wipes that dict; the row survives; the answer must then travel by catch-up. So
"the test passed" is not enough — these tests assert on what the ASKING SIDE
RECEIVED (the re-attach return value; the catch-up additionalContext), never on
what the database merely holds.

VENUE — own-server, NOT :7999/:8000 (see TODO.md 2026-08-02 venue finding + module
docstring of `_handback_e2e_server.py`). A real Lupin router stack on a throwaway
migrated Postgres DB, bounced by a genuine kill+restart. Cheech green-lit 2026-08-01.

THREE SCENARIOS:
  (a) STREAM DEATH, server ALIVE — the answer reaches the asker via the re-attach
      poll (`GET /api/notifications/response/{id}`) → RespondedEvent, no re-ask.
      (§1: "not bounce-only" — an SSE drop / reload / blip orphans a waiter too.)
  (b) ORPHANED WAITER (stream death) — closing the stream makes uvicorn cancel the
      generator, whose `finally` removes the waiter; the answer is then OWED and
      travels via catch-up. Proves the CATCH-UP travel path — NOT that a restart
      wiped a live waiter (the disconnect already removed it; Sam's 2026-08-02 catch).
  (c) LIVE WAITER WIPED BY RESTART — Rick's actual case: mid-question when the server
      bounced. HOLD the stream OPEN (waiter LIVE), assert the ask is still in-flight,
      RESTART (process death wipes the live waiter), then answer → it travels via
      catch-up. The restart is load-bearing here: deleting it makes the test red.
  (b)+(c) also assert the ack empties the owed set → surfaces exactly once (no dup).

SKIPS when Postgres is unreachable.

The executed FALSIFICATION (break the handback, predict the failure, confirm red,
restore) is recorded in the fold DM + TODO.md, not run inside this file — it edits
production source and reverts, which cannot live in a committed test.
"""

import os

# Pin the JWT secret BEFORE importing jwt_service (it reads JWT_SECRET_KEY at import)
# and force jwt auth mode. The SAME secret is handed to the server subprocess so a
# token minted here validates there.
os.environ.setdefault( "JWT_SECRET_KEY", "e2e-handback-secret-not-for-production-000" )
os.environ.setdefault( "AUTH_MODE", "jwt" )

import sys
import json
import time
import uuid
import socket
import signal
import asyncio
import threading
import subprocess
import urllib.parse
from datetime import datetime, timezone

import bcrypt
import pytest
import requests

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from alembic import command

from cosa.rest.db import database as dbm
from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import User, ApiKey
from cosa.rest.jwt_service import create_access_token
from cosa.rest.db.database import SessionLocal

from lupin_cli.claude_code.hooks.lib import answer_catchup
from lupin_cli.notifications import notify_user_sync as nus


_SERVER_PATH   = os.path.join( os.path.dirname( __file__ ), "_handback_e2e_server.py" )
_JWT_SECRET    = os.environ[ "JWT_SECRET_KEY" ]
_HUMAN_EMAIL   = "owner@handback-e2e.local"
_HUMAN_KEY     = "ck_live_" + ( "h" * 64 )          # matches ^ck_live_[A-Za-z0-9_-]{64,}$
_QUESTION      = "the question that was asked"
_ANSWER_VALUE  = "yes"


# ── low-level helpers ─────────────────────────────────────────────────────────
def _free_port():
    s = socket.socket()
    s.bind( ( "127.0.0.1", 0 ) )
    port = s.getsockname()[ 1 ]
    s.close()
    return port


def _maint_engine( server_url ):
    return create_engine( server_url, isolation_level="AUTOCOMMIT" )


def _bcrypt( raw ):
    return bcrypt.hashpw( raw.encode( "utf-8" ), bcrypt.gensalt() ).decode( "utf-8" )


def _seed_bridge( bridge_dir, hash8, persona_name ):
    """
    Write a session-bridge file so `_voice_persona_for_sender_id` stamps
    `sender_persona = persona_name` on the ask row. `find_session_path_by_id`
    matches the 8-char prefix of the file's `session_id`, so it must start with
    `hash8`; `get_voice_persona` returns the non-empty `voice_persona` dict.
    """
    os.makedirs( bridge_dir, exist_ok=True )
    session_id = f"{hash8}-0000-4000-8000-000000000000"
    payload = {
        "session_id"    : session_id,
        "voice_persona" : {
            "name"     : persona_name,
            "icon"     : "👑",
            "color"    : "#3F51B5",
            "voice_id" : "pNInz6obpgDQGcFmaJgB",
            "borrowed" : False,
        },
    }
    # The filename PID must be a LIVE process — `find_session_by_id` skips bridge
    # files whose PID is dead (a stale-session guard). This test process is alive
    # for the whole run, so use its PID; each scenario gets its own bridge dir so
    # the shared PID does not collide.
    path = os.path.join( bridge_dir, f"cc-{os.getpid()}.json" )
    with open( path, "w" ) as f:
        json.dump( payload, f )
    return session_id


# ── the own-server, driven by the test ───────────────────────────────────────
class _OwnServer:
    """A real Lupin router stack (subprocess) on a throwaway DB; restartable."""

    def __init__( self, env, port ):
        self.env  = env
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.proc = None

    def start( self ):
        self.proc = subprocess.Popen(
            [ sys.executable, _SERVER_PATH ],
            env    = self.env,
            stdout = subprocess.PIPE,
            stderr = subprocess.STDOUT,
            text   = True,
        )
        self._wait_ready()

    def _wait_ready( self, timeout=45 ):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                out = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError( f"own-server exited early:\n{out[-3000:]}" )
            try:
                r = requests.get(
                    f"{self.base}/api/notifications/answers-owed",
                    params  = { "persona": "readiness" },
                    headers = { "X-API-Key": "bad" },
                    timeout = 2,
                )
                if r.status_code == 401:              # route live + auth wired
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep( 0.5 )
        raise RuntimeError( "own-server did not become ready in time" )

    def restart( self ):
        """Genuine kill+restart — wipes pending_responses + the WS registry; DB survives."""
        self.stop()
        self.start()

    def stop( self ):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal( signal.SIGTERM )
            try:
                self.proc.wait( timeout=10 )
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait( timeout=5 )


# ── the "online" target user (a live WS keeps is_user_connected True) ─────────
class _OnlineUser:
    """
    Holds a real authenticated queue WebSocket open in a background thread so the
    ask's target user counts as connected (the ONLINE response-required path that
    registers a waiter + creates a state='delivered', owed-eligible row).
    """

    def __init__( self, port, session_id, jwt ):
        self.port       = port
        self.session_id = session_id
        self.jwt        = jwt
        self._ready     = threading.Event()
        self._stop      = threading.Event()
        self._err       = None
        self._thread    = None

    def start( self ):
        self._thread = threading.Thread( target=self._run, daemon=True )
        self._thread.start()
        if not self._ready.wait( timeout=15 ):
            raise RuntimeError( "WS did not connect in time" )
        if self._err:
            raise RuntimeError( f"WS online failed: {self._err}" )

    def _run( self ):
        try:
            asyncio.run( self._aio() )
        except Exception as e:                        # pragma: no cover - defensive
            self._err = repr( e )
            self._ready.set()

    async def _aio( self ):
        import websockets
        uri = f"ws://127.0.0.1:{self.port}/ws/queue/{urllib.parse.quote( self.session_id )}"
        async with websockets.connect( uri, open_timeout=10 ) as ws:
            await ws.send( json.dumps( {
                "type"              : "auth_request",
                "token"             : self.jwt,
                "subscribed_events" : [ "auth_success", "auth_error", "connect" ],
            } ) )
            resp = json.loads( await asyncio.wait_for( ws.recv(), timeout=10 ) )
            if resp.get( "type" ) != "auth_success":
                self._err = f"auth not successful: {resp}"
                self._ready.set()
                return
            self._ready.set()
            # Keep the socket in active_connections until told to stop.
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for( ws.recv(), timeout=0.5 )
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

    def stop( self ):
        self._stop.set()


# ── HTTP flow helpers (the real asking + answering + catch-up surfaces) ───────
def _ask_and_kill_stream( base, api_key, sender_id, timeout_s=60 ):
    """
    Drive a real response-required ask over SSE, capture the opening ack frame's
    notification_id, then CLOSE the stream mid-ask (stream death). Returns the id.
    """
    params = {
        "message"            : _QUESTION,
        "response_requested" : "true",
        "response_type"      : "yes_no",
        "response_default"   : "no",
        "target_user"        : _HUMAN_EMAIL,
        "sender_id"          : sender_id,
        "timeout_seconds"    : str( timeout_s ),
        "type"               : "custom",
        "priority"           : "high",
    }
    resp = requests.post(
        f"{base}/api/notify",
        params  = params,
        headers = { "X-API-Key": api_key },
        stream  = True,
        timeout = ( 5, 30 ),
    )
    assert resp.status_code == 200, f"/api/notify failed: {resp.status_code} {resp.text[:300]}"
    nid = None
    for line in resp.iter_lines():
        if not line:
            continue
        decoded = line.decode( "utf-8" )
        if decoded.startswith( "data: " ):
            evt = json.loads( decoded[ 6: ] )
            if evt.get( "status" ) == "ack":
                nid = evt.get( "notification_id" )
                break
    resp.close()                                       # ← STREAM DEATH mid-ask
    assert nid, "no opening ack frame captured — cannot re-attach"
    return nid


class _LiveAsk:
    """
    Drive a real response-required ask and HOLD its SSE stream OPEN — the asking
    coroutine stays blocked in `asyncio.wait_for(response_event.wait())`, so the
    server-side waiter in `pending_responses` is LIVE. This is the difference
    scenario (c) needs: closing the client stream (as `_ask_and_kill_stream` does)
    makes uvicorn cancel the generator, whose `finally` DELETES the waiter — so a
    later restart would wipe nothing. Keeping the stream open leaves a real live
    waiter for the restart to destroy by process death (Rick's mid-question bounce).
    """

    def __init__( self, base, api_key, sender_id, timeout_s=120 ):
        self.base       = base
        self.api_key    = api_key
        self.sender_id  = sender_id
        self.timeout_s  = timeout_s
        self.nid        = None
        self.terminal   = None                          # set if a terminal SSE event arrived
        self._resp      = None
        self._ack       = threading.Event()
        self._thread    = None

    def start( self ):
        self._thread = threading.Thread( target=self._run, daemon=True )
        self._thread.start()
        if not self._ack.wait( timeout=15 ):
            raise RuntimeError( "no ack frame from the held-open ask" )
        assert self.nid, "held-open ask produced no notification_id"

    def _run( self ):
        params = {
            "message"            : _QUESTION,
            "response_requested" : "true",
            "response_type"      : "yes_no",
            "response_default"   : "no",
            "target_user"        : _HUMAN_EMAIL,
            "sender_id"          : self.sender_id,
            "timeout_seconds"    : str( self.timeout_s ),
            "type"               : "custom",
            "priority"           : "high",
        }
        try:
            self._resp = requests.post(
                f"{self.base}/api/notify",
                params  = params,
                headers = { "X-API-Key": self.api_key },
                stream  = True,
                timeout = ( 5, self.timeout_s + 10 ),
            )
            for line in self._resp.iter_lines():        # BLOCKS here → waiter stays live
                if not line:
                    continue
                decoded = line.decode( "utf-8" )
                if not decoded.startswith( "data: " ):
                    continue
                evt = json.loads( decoded[ 6: ] )
                status = evt.get( "status" )
                if status == "ack":
                    self.nid = evt.get( "notification_id" )
                    self._ack.set()
                elif status in ( "responded", "expired", "offline", "error" ):
                    self.terminal = status
                    break
        except Exception:
            # The stream breaking (e.g. the server was restarted out from under it)
            # is EXPECTED in scenario (c) — the waiter died with the process.
            pass

    def is_in_flight( self ):
        """True while the ask is still blocked with no terminal event — the waiter is LIVE."""
        return self.terminal is None and self._thread is not None and self._thread.is_alive()

    def stop( self ):
        try:
            if self._resp is not None:
                self._resp.close()
        except Exception:
            pass


def _submit_answer( base, nid, value=_ANSWER_VALUE ):
    """POST the answer as the UI would (the /notify/response endpoint takes no auth)."""
    r = requests.post(
        f"{base}/api/notify/response",
        json    = { "notification_id": nid, "response_value": { "value": value, "source": "ui" } },
        timeout = 10,
    )
    assert r.status_code == 200, f"/api/notify/response failed: {r.status_code} {r.text[:300]}"


def _get_owed( base, api_key, persona ):
    r = requests.get(
        f"{base}/api/notifications/answers-owed",
        params  = { "persona": persona, "limit": 100 },
        headers = { "X-API-Key": api_key },
        timeout = 10,
    )
    assert r.status_code == 200, f"/answers-owed failed: {r.status_code} {r.text[:300]}"
    return r.json()


def _ack_owed( base, api_key, nid ):
    r = requests.post(
        f"{base}/api/notifications/answers-owed/ack",
        json    = { "notification_id": nid },
        headers = { "X-API-Key": api_key },
        timeout = 10,
    )
    assert r.status_code == 200, f"/answers-owed/ack failed: {r.status_code} {r.text[:300]}"


def _make_fetch_fn( base, api_key ):
    """A real fetch_fn for answer_catchup.surface_owed_answers, pointed at the own-server."""
    def fetch( persona, session_hash8, since=None, limit=answer_catchup.DEFAULT_LIMIT ):
        params = { "persona": persona, "limit": str( limit ) }
        if session_hash8:
            params[ "session_hash8" ] = session_hash8
        if since:
            params[ "since" ] = since
        r = requests.get(
            f"{base}/api/notifications/answers-owed",
            params  = params,
            headers = { "X-API-Key": api_key },
            timeout = 10,
        )
        if r.status_code != 200:
            return ( False, [], False )
        body    = r.json()
        answers = body.get( "answers", [] )
        return ( True, answers, len( answers ) >= limit )
    return fetch


# ── fixture: throwaway DB + seeded human/api-key + base server env ────────────
@pytest.fixture( scope="module" )
def handback_ctx( tmp_path_factory ):
    """
    Create a throwaway DB migrated to head, seed the human owner + a real bcrypt
    api-key, and yield the base subprocess env + connection facts. Drops the DB on
    teardown. SKIPS when Postgres is unreachable.
    """
    server_url = dbm.engine.url                        # lupin_db_dev — params source ONLY (never written)
    db_name    = f"handback_e2e_{os.getpid()}"

    try:
        eng = _maint_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text( f'DROP DATABASE IF EXISTS "{db_name}"' ) )
            conn.execute( text( f'CREATE DATABASE "{db_name}"' ) )
        eng.dispose()
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable — skipping handback e2e: {e}" )

    throwaway_url = server_url.set( database=db_name ).render_as_string( hide_password=False )
    command.upgrade( build_alembic_config( database_url=throwaway_url ), "head" )

    # Seed the human owner + api-key DIRECTLY in the throwaway DB. We repoint the
    # in-process engine at the throwaway just for this seed, then restore it — the
    # test process must never write to lupin_db_dev.
    saved = ( dbm.engine, dbm.SessionLocal, dbm.ScopedSession )
    from sqlalchemy.orm import sessionmaker, scoped_session
    tw_engine  = create_engine( throwaway_url )
    tw_session = sessionmaker( autocommit=False, autoflush=False, bind=tw_engine )
    dbm.engine, dbm.SessionLocal, dbm.ScopedSession = tw_engine, tw_session, scoped_session( tw_session )

    human_id = uuid.uuid4()
    s = tw_session()
    try:
        s.add( User( id=human_id, email=_HUMAN_EMAIL, password_hash="x", email_verified=True,
                     is_active=True, is_protected=False, roles={ "roles": [ "user" ] },
                     created_at=datetime.now( timezone.utc ) ) )
        s.add( ApiKey( id=uuid.uuid4(), user_id=human_id, key_hash=_bcrypt( _HUMAN_KEY ),
                       description="handback e2e human", is_active=True,
                       created_at=datetime.now( timezone.utc ) ) )
        s.commit()
    finally:
        s.close()

    dbm.engine, dbm.SessionLocal, dbm.ScopedSession = saved
    tw_engine.dispose()

    human_jwt = create_access_token( str( human_id ), _HUMAN_EMAIL, [ "user" ] )

    # LUPIN_HOOK_SESSIONS_DIR is set per-boot (each scenario has its own bridge dir).
    base_env = dict( os.environ )
    base_env.update( {
        "LUPIN_ROOT"              : os.getcwd(),
        "LUPIN_CONFIG_MGR_CLI_ARGS": os.environ.get( "LUPIN_CONFIG_MGR_CLI_ARGS", "" ),
        "AUTH_MODE"               : "jwt",
        "JWT_SECRET_KEY"          : _JWT_SECRET,
        "DB_NAME"                 : db_name,
        "DB_HOST"                 : server_url.host or "localhost",
        "DB_PORT"                 : str( server_url.port or 5432 ),
        "DB_USER"                 : server_url.username or "lupin_dev",
        "DB_PASSWORD"             : server_url.password or os.environ.get( "DB_PASSWORD", "" ),
    } )

    ctx = {
        "server_url" : server_url,
        "db_name"    : db_name,
        "human_id"   : str( human_id ),
        "human_jwt"  : human_jwt,
        "human_key"  : _HUMAN_KEY,
        "base_env"   : base_env,
    }
    yield ctx

    eng = _maint_engine( server_url )
    with eng.connect() as conn:
        conn.execute( text(
            "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
            "WHERE datname = :db AND pid <> pg_backend_pid()"
        ), { "db": db_name } )
        conn.execute( text( f'DROP DATABASE IF EXISTS "{db_name}"' ) )
    eng.dispose()


def _boot_server( ctx, bridge_dir ):
    port = _free_port()
    env  = dict( ctx[ "base_env" ] )
    env[ "PORT" ]                    = str( port )
    env[ "LUPIN_HOOK_SESSIONS_DIR" ] = bridge_dir     # where the server resolves sender_persona
    srv = _OwnServer( env, port )
    srv.start()
    return srv


# ── SCENARIO (a): stream death, server ALIVE → re-attach delivers, no re-ask ──
def test_stream_death_answer_reaches_asker_via_reattach( handback_ctx, tmp_path ):
    """
    Kill the SSE stream mid-ask, answer from the UI, and assert the answer REACHES
    the asking session via the re-attach poll — mapped to a responded outcome, never
    a re-ask. The row is left delivered (setter a) so catch-up won't double-deliver.
    """
    ctx        = handback_ctx
    hash8      = "aa111111"
    persona    = "handback_persona_a"
    bridge_dir = str( tmp_path / "bridges" )
    _seed_bridge( bridge_dir, hash8, persona )
    sender_id = f"claude.code@lupin.deepily.ai#{hash8}"

    srv = _boot_server( ctx, bridge_dir )
    online = _OnlineUser( srv.port, "clever dolphin", ctx[ "human_jwt" ] )
    try:
        online.start()

        nid = _ask_and_kill_stream( srv.base, ctx[ "human_key" ], sender_id )

        # Control (non-vacuity): before the human answers, a re-attach poll must NOT
        # report responded — otherwise a later "responded" proves nothing.
        pre = nus._reattach_after_stream_death(
            nid, remaining_seconds=0, base_url=srv.base,
            headers={ "X-API-Key": ctx[ "human_key" ] },
        )
        assert pre.status != "responded", f"re-attach reported responded BEFORE any answer: {pre}"

        _submit_answer( srv.base, nid )

        # The asking side recovers the answer via the re-attach poll — this return
        # value IS what the asking process hands back to the model.
        got = nus._reattach_after_stream_death(
            nid, remaining_seconds=30, base_url=srv.base,
            headers={ "X-API-Key": ctx[ "human_key" ] },
        )
        assert got.status == "responded", f"answer did not reach the asker as 'responded': {got}"
        assert got.response_value == _ANSWER_VALUE, got
        assert got.default_used is False, "a real human answer must not be flagged default_used"
        assert got.reattach_state == "reattach_armed", got
    finally:
        online.stop()
        srv.stop()


# ── SCENARIO (b): orphaned waiter (stream death) → catch-up delivers, no dup ──
def test_orphaned_waiter_answer_travels_via_catchup( handback_ctx, tmp_path ):
    """
    ORPHANED-WAITER travel (§1: "not bounce-only" — a client reload / network blip /
    closed tab). Kill the SSE stream — uvicorn cancels the generator, whose `finally`
    removes the waiter — then answer. With no live waiter the answer is stored and
    OWED. Assert it TRAVELS to the asking session via catch-up (the additionalContext
    a returning/next-turn session receives), and the ack empties the owed set so it
    surfaces exactly once — no duplicate re-ask.

    ⚠️ SCOPE: this proves the CATCH-UP travel of an ALREADY-orphaned answer. It does
    NOT prove a restart wiped a LIVE waiter — the stream close already removed it
    (deleting the restart here would still pass). Scenario (c) is the live-waiter
    case; the restart is intentionally omitted here so the name means exactly this.
    """
    ctx        = handback_ctx
    hash8      = "bb222222"
    persona    = "handback_persona_b"
    bridge_dir = str( tmp_path / "bridges" )
    hwm_dir    = str( tmp_path / "hwm" )
    _seed_bridge( bridge_dir, hash8, persona )
    sender_id  = f"claude.code@lupin.deepily.ai#{hash8}"
    session_id = f"{hash8}-0000-4000-8000-000000000000"

    srv = _boot_server( ctx, bridge_dir )
    online = _OnlineUser( srv.port, "wise otter", ctx[ "human_jwt" ] )
    try:
        online.start()
        nid = _ask_and_kill_stream( srv.base, ctx[ "human_key" ], sender_id )

        # Control (non-vacuity): before the human answers, nothing is owed — the row
        # exists but responded_at is NULL, so the owed predicate excludes it.
        assert _get_owed( srv.base, ctx[ "human_key" ], persona )[ "owed_count" ] == 0, \
            "owed set must be EMPTY before the human answers (guards a vacuous pass)"

        # Answer with the waiter already orphaned by the stream close — the answer is
        # stored + owed (no live waiter to wake).
        _submit_answer( srv.base, nid )

        # PROVE IT TRAVELLED — assert on what the ASKER RECEIVES, not what the DB holds.
        # surface_owed_answers() returns the additionalContext injected into the asking
        # session's next turn; it drives the REAL reconcile over the REAL endpoint.
        fetch_fn = _make_fetch_fn( srv.base, ctx[ "human_key" ] )
        ctx_str  = answer_catchup.surface_owed_answers(
            session_id, persona=persona, fetch_fn=fetch_fn, base_dir=hwm_dir,
        )
        assert _QUESTION in ctx_str, f"the asker did not receive the question in catch-up: {ctx_str!r}"
        assert _ANSWER_VALUE in ctx_str, f"the asker did not receive the answer value in catch-up: {ctx_str!r}"

        # The endpoint envelope carries the load-bearing fields (rulings 6/7).
        owed = _get_owed( srv.base, ctx[ "human_key" ], persona )
        assert owed[ "owed_count" ] == 1, owed
        env = owed[ "answers" ][ 0 ]
        assert env[ "question" ] == _QUESTION, env
        assert env[ "response_value" ][ "value" ] == _ANSWER_VALUE, env
        assert env[ "responded_at" ], "envelope must carry responded_at"

        # NO DUPLICATE RE-ASK — ack (consume) empties the owed set, and a second
        # catch-up surfaces nothing (dedup + owed-empty). Fails toward see-once.
        _ack_owed( srv.base, ctx[ "human_key" ], nid )
        assert _get_owed( srv.base, ctx[ "human_key" ], persona )[ "owed_count" ] == 0, \
            "after ack the answer must leave the owed set (ruling 2: row stays in table, not owed)"
        second = answer_catchup.surface_owed_answers(
            session_id, persona=persona, fetch_fn=fetch_fn, base_dir=hwm_dir,
        )
        assert second == "", f"catch-up re-surfaced an already-consumed answer (duplicate): {second!r}"
    finally:
        online.stop()
        srv.stop()


# ── SCENARIO (c): LIVE waiter wiped by a real restart → catch-up delivers ────
def test_live_waiter_wiped_by_restart_answer_travels_via_catchup( handback_ctx, tmp_path ):
    """
    THE REPORTED DEFECT, VERBATIM — mid-question when the server bounced. HOLD the
    SSE stream OPEN so the server-side waiter stays LIVE, assert the ask is still
    in-flight, then RESTART the server (process death wipes the live waiter), then
    answer. With the waiter gone the answer is stored + OWED and must TRAVEL via
    catch-up. This is the case scenario (b) cannot reach: here the restart destroys a
    genuinely live waiter, not one already removed by a client disconnect.

    ⚠️ RED-PROOF property: deleting `srv.restart()` here makes it FAIL — the live
    waiter survives, the answer wakes it (setter a → delivered), owed_count stays 0,
    and the owed assertions go red. That is what makes the restart load-bearing.
    """
    ctx        = handback_ctx
    hash8      = "cc333333"
    persona    = "handback_persona_c"
    bridge_dir = str( tmp_path / "bridges" )
    hwm_dir    = str( tmp_path / "hwm" )
    _seed_bridge( bridge_dir, hash8, persona )
    sender_id  = f"claude.code@lupin.deepily.ai#{hash8}"
    session_id = f"{hash8}-0000-4000-8000-000000000000"

    srv    = _boot_server( ctx, bridge_dir )
    online = _OnlineUser( srv.port, "brave heron", ctx[ "human_jwt" ] )
    live   = _LiveAsk( srv.base, ctx[ "human_key" ], sender_id )
    try:
        online.start()
        live.start()                                   # holds the SSE stream OPEN
        nid = live.nid

        # The waiter is LIVE: the ask is still blocked with no terminal event — this is
        # exactly what (b) lacks, so here the restart destroys a genuinely live waiter.
        assert live.is_in_flight(), "ask must still be in-flight (waiter LIVE) before the restart"
        assert _get_owed( srv.base, ctx[ "human_key" ], persona )[ "owed_count" ] == 0, \
            "nothing owed before the answer (row exists, responded_at NULL)"

        # ── the bounce: process death wipes the LIVE waiter; the durable row survives ──
        srv.restart()
        online.stop()

        # Answer AFTER the bounce — the live waiter is gone, so the answer is owed.
        _submit_answer( srv.base, nid )

        # PROVE IT TRAVELLED — the additionalContext the asking session's next turn gets.
        fetch_fn = _make_fetch_fn( srv.base, ctx[ "human_key" ] )
        ctx_str  = answer_catchup.surface_owed_answers(
            session_id, persona=persona, fetch_fn=fetch_fn, base_dir=hwm_dir,
        )
        assert _QUESTION in ctx_str, f"the asker did not receive the question in catch-up: {ctx_str!r}"
        assert _ANSWER_VALUE in ctx_str, f"the asker did not receive the answer value in catch-up: {ctx_str!r}"

        owed = _get_owed( srv.base, ctx[ "human_key" ], persona )
        assert owed[ "owed_count" ] == 1, owed
        env = owed[ "answers" ][ 0 ]
        assert env[ "question" ] == _QUESTION, env
        assert env[ "response_value" ][ "value" ] == _ANSWER_VALUE, env

        # NO DUPLICATE RE-ASK — ack empties the owed set; a second catch-up is silent.
        _ack_owed( srv.base, ctx[ "human_key" ], nid )
        assert _get_owed( srv.base, ctx[ "human_key" ], persona )[ "owed_count" ] == 0, \
            "after ack the answer must leave the owed set (ruling 2)"
        second = answer_catchup.surface_owed_answers(
            session_id, persona=persona, fetch_fn=fetch_fn, base_dir=hwm_dir,
        )
        assert second == "", f"catch-up re-surfaced an already-consumed answer (duplicate): {second!r}"
    finally:
        live.stop()
        online.stop()
        srv.stop()


def isolated_unit_test():
    """Run this module in isolation for the smoke-runner harness."""
    import time as _t
    start = _t.time()
    code  = pytest.main( [ __file__, "-q", "-p", "no:cacheprovider" ] )
    return ( code == 0 ), _t.time() - start, f"pytest exit {code}"


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} ask-answer handback e2e in {secs:.1f}s — {msg}" )
