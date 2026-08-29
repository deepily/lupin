"""
Route-level smoke for the LIVE inter-session DM endpoints — `/api/dm/send` and
`/api/dm/respond` (the nested DM API that superseded the retired
`/api/commons/register-question` DM path).

History: this file originally targeted `POST /api/commons/register-question`
with `recipient_persona`/`recipient_session_id` (the Phase-0 DM-over-commons
design, 2026-05-15). That route was retired when the notification-native AI↔AI
DM API landed (`src/cosa/rest/routers/dm.py`,
`src/rnd/v0.1.8/2026.06.16-dm-api-namespace-design.md`); the old assertions
404'd. This rewrite re-points at the live routes AND closes the route-level
coverage gap on the two handlers that feed the null-inclusive recipient scanner.

What this proves (route-level, end-to-end through the real resolver):
    `post_dm_send` / `post_dm_respond` were previously `# pragma: no cover` thin
    wiring — the L4 fix (commit 1f40d0dd) gave `_resolve_dm_recipient` +
    `find_active_sessions(require_persona=False)` + `_session_id_matches` UNIT
    coverage, but the HTTP handlers that wire them together had none. These
    tests remove that pragma and drive each handler to 100% by exercising the
    real resolver (NOT mocked) against on-disk fixture bridges:

      1. a normal persona-addressed DM            → 201 (resolve-by-persona)
      2. a NULL-persona worker reached by SHORT    → 201 (the d57dbfea path:
         session id (8-char prefix)                  null persona ⇒ no name to
                                                      resolve by ⇒ reachable
                                                      ONLY by session_id)
      3. an ambiguous short-prefix recipient_      → 422 recipient_session_id_
         session_id                                  ambiguous (two candidates
                                                      share the 8-char prefix)

Venue: :7999 AI-discretionary — NON-DESTRUCTIVE. The DB persist
(`_persist_dm_send_sync`) is monkeypatched to a capture-only fake (no
notification row is written) and the notification queue is a mock, so nothing
outlives the test. The recipient scanner runs for real against real bridge
JSON files written into a `tmp_path` dir (so the default
`mtime_fn = path.stat().st_mtime` liveness gate sees genuinely-fresh files).
Fast (<5s), no shared external state — needs neither :8000 nor server monopoly.

Build approach: stripped FastAPI app mounting ONLY the dm router; auth bypass
to a fixed user_id; mock notification_queue captures dispatches; the session
enumeration (`find_active_sessions`) + sender-id builder (`build_sender_id_for_cc`)
are monkeypatched on their source module (the dm handlers re-import them lazily
at call time, so patching the source module is what the handler picks up).
"""

import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import re

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers.dm import router as dm_router
from cosa.rest.routers.notifications import get_notification_queue


# Every outbound DM body is prefixed with Rick's central EDT stamp
# "[YYYY.MM.DD at HH:MM:SS] " (2026-06-24, cosa.utils.edt_timestamp) — the SAME
# bracketed shape the arbiter pings carry. The stamp is real-now at the HTTP layer,
# so assert the prefix SHAPE + that the original body rides intact after it.
_EDT_PREFIX_RE = re.compile( r"^\[\d{4}\.\d{2}\.\d{2} at \d{2}:\d{2}:\d{2}\] " )


# A real UUID — the authenticated caller. Fixture bridges are stamped with this
# as `owner_user_id` so same-user scoping in filter_and_project_sessions admits
# them (and proves the scope check, rather than relying on the un-stamped
# graceful-passthrough branch).
_TEST_USER_ID = "11111111-2222-3333-4444-555555555555"


# ─── Session-id design ───────────────────────────────────────────────────────
# Full canonical ids are >8 chars with DISTINCT 8-char prefixes, except the
# ambiguous pair which deliberately SHARES one. The null worker's prefix is
# unique so a short-id DM resolves to exactly one candidate (the d57dbfea path).

_SID_RADIO   = "radiosess0000000001"   # prefix "radioses"
_SID_RACHEL  = "rachelsess000000002"   # prefix "rachelse"
_SID_NULL    = "null0001worker00009"   # prefix "null0001"  (persona-LESS worker)
_SID_AMBIG_A = "ambig777aaaa000010"    # shared prefix "ambig777"
_SID_AMBIG_B = "ambig777bbbb000011"    # shared prefix "ambig777"


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def captured_pushes():
    return [ ]


@pytest.fixture
def mock_notification_queue( captured_pushes ):
    class _Q:
        def push_notification( self, **kwargs ):
            captured_pushes.append( kwargs )
    return _Q()


@pytest.fixture
def persisted_rows():
    return [ ]


def _write_bridge( tmp: Path, sid: str ) -> Path:
    """Write a real bridge JSON file (fresh mtime) and return its Path."""
    bridge = {
        "stable_session_id" : sid,
        "session_id"        : sid,
        "owner_user_id"     : _TEST_USER_ID,
        "last_activity_iso" : "2026-06-17T12:00:00+00:00",
        "speakerphone_on"   : False,
        "idle_detection"    : { "last_interaction_at" : time.time() },
    }
    path = tmp / f"cc-{sid}.json"
    path.write_text( json.dumps( bridge ) )
    return path


@pytest.fixture
def fixture_sessions( tmp_path ):
    """
    Five live sessions as the (Path, session_id, persona) 3-tuples that
    `find_active_sessions` yields. The null worker carries persona `{}` exactly
    as `find_active_sessions(require_persona=False)` projects a persona-less
    bridge.
    """
    def persona( name ):
        return { "name": name, "icon": "🌸", "color": "#F06292" }

    return [
        ( _write_bridge( tmp_path, _SID_RADIO ),   _SID_RADIO,   persona( "radio"    ) ),
        ( _write_bridge( tmp_path, _SID_RACHEL ),  _SID_RACHEL,  persona( "rachel"   ) ),
        ( _write_bridge( tmp_path, _SID_NULL ),    _SID_NULL,    { } ),
        ( _write_bridge( tmp_path, _SID_AMBIG_A ), _SID_AMBIG_A, persona( "ambigone" ) ),
        ( _write_bridge( tmp_path, _SID_AMBIG_B ), _SID_AMBIG_B, persona( "ambigtwo" ) ),
    ]


@pytest.fixture
def app_and_state( mock_notification_queue, persisted_rows, fixture_sessions, monkeypatch ):
    """Stripped app mounting the dm router + patched session enumeration + persist."""
    # The dm handlers lazily `from lupin_cli...session_bridge import
    # find_active_sessions, build_sender_id_for_cc` AT CALL TIME, so patching
    # the SOURCE module is what they pick up.
    def _fake_find_active_sessions( stale_threshold_seconds: int = 43200, require_persona: bool = True ):
        # The DM resolver always calls this with require_persona=False; honor the
        # contract so a persona-required caller would still get only personas.
        if require_persona:
            return [ t for t in fixture_sessions if t[ 2 ] ]
        return list( fixture_sessions )

    monkeypatch.setattr(
        "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_sessions",
        _fake_find_active_sessions,
    )
    monkeypatch.setattr(
        "lupin_cli.claude_code.hooks.lib.session_bridge.build_sender_id_for_cc",
        lambda session_id=None: f"claude.code@lupin.deepily.ai#{ ( session_id or '' )[ :8 ] }",
    )

    # DB-boundary persist → capture-only fake (no notification row written). The
    # real _persist_dm_send_sync has its own unit coverage (TestPersistDmSendSync
    # in src/cosa/tests/unit/rest/test_dm_send_endpoint.py); here we keep the
    # smoke non-destructive while still exercising the full handler wiring.
    def _fake_persist( **kwargs ):
        persisted_rows.append( kwargs )
        return f"row-{ len( persisted_rows ) }"

    monkeypatch.setattr( "cosa.rest.routers.dm._persist_dm_send_sync", _fake_persist )

    app = FastAPI()
    app.include_router( dm_router )

    async def _fake_auth():
        return _TEST_USER_ID
    app.dependency_overrides[ require_api_key_or_jwt ] = _fake_auth
    app.dependency_overrides[ get_notification_queue ] = lambda: mock_notification_queue

    return app


@pytest.fixture
def client( app_and_state ):
    return TestClient( app_and_state )


# ─── /api/dm/send ────────────────────────────────────────────────────────────


def test_dm_send_persona_addressed_returns_201( client, captured_pushes, persisted_rows ):
    """recipient_persona='radio' → 201 + ai_to_ai dispatch resolved to the radio session."""
    resp = client.post(
        "/api/dm/send",
        json = {
            "sender_session_id" : "sid_asker",
            "sender_project"   : "lupin",              # REQUIRED on the DM write path (gate 1fa05b16)
            "body"             : "ready for review",
            "recipient_persona": "radio",
            "sender_persona"   : "tiffany",
            "sender_icon"      : "💍",
        },
    )
    import uuid
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data[ "recipient_persona" ] == "radio"
    assert data[ "recipient_session" ] == _SID_RADIO
    assert data[ "dispatched" ] is True
    # message_id is the persisted DB id; with no thread_id supplied, thread_id
    # seeds from a freshly-generated uuid (a NEW thread) — a parseable uuid4.
    assert data[ "message_id" ] == "row-1"
    assert str( uuid.UUID( data[ "thread_id" ] ) ) == data[ "thread_id" ]

    # The DM persisted + pushed once, carrying the ai_to_ai provenance.
    assert len( persisted_rows ) == 1
    assert persisted_rows[ 0 ][ "direction" ] == "ai_to_ai"
    assert len( captured_pushes ) == 1
    push = captured_pushes[ 0 ]
    assert push[ "direction" ]      == "ai_to_ai"
    # Central EDT prefix lands on the outbound body; original text rides intact after it.
    assert _EDT_PREFIX_RE.match( push[ "message" ] )
    assert push[ "message" ].endswith( " ready for review" )
    # No double-stamp: exactly one bracketed prefix on the body.
    assert push[ "message" ].count( "] " ) == 1
    # The persisted row carries the SAME stamped body the recipient sees.
    assert persisted_rows[ 0 ][ "message" ] == push[ "message" ]
    assert push[ "sender_persona" ] == "tiffany"
    assert push[ "job_id" ]         == _SID_RADIO[ :8 ]


def test_dm_send_null_persona_worker_by_short_sid_returns_201( client, captured_pushes ):
    """
    The d57dbfea path: a NULL-persona worker has no name to resolve by, so it is
    reachable ONLY by session_id. The manager supplies the worker's SHORT
    (8-char) id; _session_id_matches resolves the short prefix to the single
    full-id candidate → 201, recipient_persona=None.
    """
    resp = client.post(
        "/api/dm/send",
        json = {
            "sender_session_id"     : "sid_manager",
            "sender_project"       : "lupin",           # REQUIRED on the DM write path (gate 1fa05b16)
            "body"                 : "you are reachable",
            "recipient_session_id" : _SID_NULL[ :8 ],   # "null0001" — short form
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data[ "recipient_session" ] == _SID_NULL
    assert data[ "recipient_persona" ] is None          # null-persona worker
    assert data[ "dispatched" ] is True
    assert len( captured_pushes ) == 1
    assert captured_pushes[ 0 ][ "job_id" ] == _SID_NULL[ :8 ]


def test_dm_send_ambiguous_short_prefix_returns_422( client, captured_pushes ):
    """Two candidates share the 8-char prefix → 422 recipient_session_id_ambiguous, no dispatch."""
    resp = client.post(
        "/api/dm/send",
        json = {
            "sender_session_id"     : "sid_manager",
            "body"                 : "who are you",
            "recipient_session_id" : "ambig777",        # prefix of BOTH ambig A and B
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json().get( "detail" )
    assert isinstance( detail, dict )
    assert detail[ "error" ] == "recipient_session_id_ambiguous"
    assert detail[ "supplied_session_id" ] == "ambig777"
    assert "session_id_prefix" in detail[ "resolution_chain_attempted" ]
    # On resolution failure nothing is dispatched.
    assert captured_pushes == [ ]


# ─── /api/dm/respond ─────────────────────────────────────────────────────────


def test_dm_respond_threaded_reply_returns_201( client, captured_pushes, persisted_rows ):
    """
    /api/dm/respond is send-with-mandatory-threading: reply_to + thread_id are
    REQUIRED and the supplied thread_id is preserved (NOT overwritten). Proves
    the respond handler feeds the same null-inclusive resolver.
    """
    resp = client.post(
        "/api/dm/respond",
        json = {
            "sender_session_id" : "sid_asker",
            "sender_project"   : "lupin",              # REQUIRED on the DM write path (gate 1fa05b16)
            "body"             : "ack — verdict GREEN",
            "recipient_persona": "rachel",
            "reply_to"         : "msg-original-1",
            "thread_id"        : "conv-42",
            "sender_persona"   : "tiffany",
            "sender_icon"      : "💍",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data[ "recipient_persona" ] == "rachel"
    assert data[ "recipient_session" ] == _SID_RACHEL
    assert data[ "thread_id" ] == "conv-42"             # supplied thread preserved
    assert data[ "dispatched" ] is True
    assert len( captured_pushes ) == 1
    push = captured_pushes[ 0 ]
    assert push[ "reply_to" ]  == "msg-original-1"
    assert push[ "thread_id" ] == "conv-42"
    assert persisted_rows[ 0 ][ "reply_to" ] == "msg-original-1"


def test_dm_respond_ambiguous_short_prefix_returns_422( client, captured_pushes ):
    """The respond handler's 422 branch: an ambiguous recipient_session_id prefix."""
    resp = client.post(
        "/api/dm/respond",
        json = {
            "sender_session_id"     : "sid_asker",
            "body"                 : "reply into the void",
            "recipient_session_id" : "ambig777",
            "reply_to"             : "msg-original-2",
            "thread_id"            : "conv-43",
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json().get( "detail" )
    assert isinstance( detail, dict )
    assert detail[ "error" ] == "recipient_session_id_ambiguous"
    assert captured_pushes == [ ]
