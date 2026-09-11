"""
Integration tests for BLOCKED-AT-MINT task creation — build 1b5483f4.

Authored by Rachel 🕊️ (Tester, Mr. Radio's 🦉 SWE crew, 2026-07-20).

GOAL under test: task_create can mint a row ALREADY status=blocked in ONE
call (today create is hard-coded status=queued). Rick's 2026-07-20 design
ruling gates it with two acceptance criteria:

  AC1 — STATUS WHITELIST: mint status = queued OR blocked ONLY. Every other
        status (claimed / in_progress / review / done / dropped / parked) is
        REJECTED at create (HTTP 422, rules violation). A true allow-list, not
        a blocklist (Tiffany R-5).

  AC2 — CALLER AUTHORIZATION: ONLY MANAGERS may mint a blocked row. A
        non-manager mint-blocked is REJECTED with HTTP 403 (authenticated but
        unauthorized — Cheech confirmed firsthand). queued mint stays open to all.

Four surfaces this chain crosses (all lupin tree):
  1. routers/tasks.py  TaskCreateIn        — status / blocked_by / next_chase_ts fields
  2. routers/tasks.py  create_task handler — whitelist + manager-guard + kind-aware chase rule
  3. db/.../task_repository.py create_item  — stamp ->blocked + persist the two fields
  4. lupin_mcp/cosa_voice_mcp.py task_create — plumb blocked_by + next_chase_ts

VENUE: :8000 monopolize-mode, SCHEDULED ONLY — submit via
POST /api/test-suite/submit (NEVER side-door). Mutates task_items/task_events
rows in the test DB → NOT :7999-eligible. Mirror of the venue posture of the
sibling suite test_task_store_integration.py.

═══════════════════════════════════════════════════════════════════════════
 MANAGER-SIGNAL MECHANISM (pinned by Mr. Radio; internals confirmed by Cheech)
═══════════════════════════════════════════════════════════════════════════
AC2 turns on the server-side predicate `is_manager_figure( session_id )`
(lupin_cli/.../manager_figure.py). The create_task handler parses the
session_id out of `created_by` ("<persona> <8-hex sid>", rsplit on last space)
and asks that predicate. It reads the session's BRIDGE FILE at
~/.claude/sessions/cc-*.json and returns True iff EITHER:
    (explicit)  bridge role == "manager", OR
    (implicit)  bridge voice_persona.name matches a NAMED entry of the
                COSA_VOICE_PREFERRED_PERSONA__<PROJECT> env chain.

Testability facts (verified firsthand — Cheech + session_bridge.py):
  • ~/.claude/sessions is bind-mounted INTO the :8000 container
    (docker-compose.yml:154) — the server reads the same dir a fixture writes.
  • Inside the container `_can_trust_host_pids()` returns False (via /.dockerenv,
    session_bridge.py:128), so find_session_path_by_id SKIPS the PID-liveness
    filter — a fixture bridge with any/fabricated PID still matches by session_id.
  • MATCH RULE: find_session_path_by_id matches known_id[:8] == session_id[:8].
    So created_by MUST end in the bridge session_id's first 8 chars.
  • SID-TAIL RULE: the handler parses the sid via regex [0-9a-f]{6,} — it MUST
    be LOWERCASE HEX. uuid4().hex is always lowercase hex, so the fixture is
    safe by construction (Cheech safety note).
  • The IMPLICIT source is DEAD in-container (COSA_VOICE_PREFERRED_PERSONA__lupin
    unset → chain resolves empty), so role="worker" is a guaranteed non-manager.

Fixture strategy (bulletproof against BOTH sources):
  • MANAGER bridge → role="manager" (EXPLICIT source; env-chain-independent).
  • WORKER bridge → role="worker" AND no voice_persona (guaranteed non-manager
    on both sources).

⚠️ RUNNER-LOCATION ASSUMPTION (flagged to the manager): this bridge-file path
   presumes the :8000 pytest runner and the server share ~/.claude/sessions
   (same host OR both via the compose mount). If that dir does NOT unify with
   the container mount, the manager path 403s and these tests fail LOUD (never
   silently green) — the correct failure, signalling to relocate the write.
═══════════════════════════════════════════════════════════════════════════
"""

import os
import json
import uuid
from pathlib import Path

import pytest
import requests
import bcrypt
import secrets

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import UserRepository, ApiKeyRepository

from lupin_mcp.task_store_tools import task_create_impl, task_query_impl


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
ENDPOINT = f"{BASE_URL}/api/tasks"

# The bridge directory the server-side predicate reads (session_bridge.SESSION_DIR).
# Constructed identically here so writer and reader agree by construction.
SESSION_DIR = Path.home() / ".claude" / "sessions"

# The two mintable statuses (AC1 allow-list) and everything the allow-list
# must REJECT at create time.
MINTABLE_STATUSES     = ( "queued", "blocked" )
NON_MINTABLE_STATUSES = ( "claimed", "in_progress", "review", "done", "dropped", "parked" )

# A well-formed ->blocked payload (I3: blocked REQUIRES a typed ref + a chase ts).
BLOCK_REFS     = [ { "kind": "user", "id": "rick" } ]
BLOCK_CHASE_TS = "2026-07-21T09:00:00-04:00"


def _write_bridge( session_id: str, *, role: str, persona_name=None ) -> Path:
    """
    Write a minimal session bridge file the server-side is_manager_figure reads.

    Requires:
        - session_id is a >=8-char LOWERCASE-HEX string (so the handler's
          sid-tail regex [0-9a-f]{6,} extracts it from created_by, and the
          8-char prefix match in find_session_path_by_id lands)
        - role is the bridge role ("manager" → explicit manager source)
        - persona_name None omits voice_persona entirely (guaranteed non-manager
          on the implicit source); a string sets voice_persona.name

    Ensures:
        - a cc-*.json file (no "buffer"/"listener" in the name) exists in
          SESSION_DIR carrying session_id + role (+ voice_persona.name when
          provided); returns its Path
    """
    SESSION_DIR.mkdir( parents=True, exist_ok=True )
    data = { "session_id": session_id, "stable_session_id": session_id, "role": role }
    if persona_name is not None:
        data[ "voice_persona" ] = { "name": persona_name }
    path = SESSION_DIR / f"cc-test-blockmint-{session_id}.json"
    path.write_text( json.dumps( data ) )
    return path


def _new_sid() -> str:
    """A fresh lowercase-hex session id (dashes stripped) — always [0-9a-f], unique per use."""
    return uuid.uuid4().hex


@pytest.fixture
def manager_created_by():
    """Yield a created_by whose bridge resolves is_manager_figure → True (explicit role=manager)."""
    sid  = _new_sid()
    path = _write_bridge( sid, role="manager", persona_name="mr radio" )
    yield f"mr_radio {sid[:8]}"
    path.unlink( missing_ok=True )


@pytest.fixture
def worker_created_by():
    """Yield a created_by whose bridge resolves is_manager_figure → False (role=worker, no persona)."""
    sid  = _new_sid()
    path = _write_bridge( sid, role="worker", persona_name=None )
    yield f"worker {sid[:8]}"
    path.unlink( missing_ok=True )


@pytest.fixture
def test_api_key( clean_test_db ):
    """Create a test API key + service-account user; yield the raw key. (Mirror of the sibling suite.)"""
    api_key   = "ck_live_" + secrets.token_urlsafe( 48 )
    key_bytes = api_key.encode( "utf-8" )
    salt      = bcrypt.gensalt( rounds=12 )
    key_hash  = bcrypt.hashpw( key_bytes, salt ).decode( "utf-8" )

    email = f"test-{uuid.uuid4()}@test.com"

    with get_db() as session:
        user_repo = UserRepository( session )
        user = user_repo.create_user(
            email         = email,
            password_hash = "dummy_hash",
            roles         = [ "service_account" ],
        )
        user.email_verified = True
        user.is_active      = True

        api_key_repo = ApiKeyRepository( session )
        api_key_obj  = api_key_repo.create_key(
            user_id     = user.id,
            key_hash    = key_hash,
            description = "blocked-at-mint integration test key",
        )
        key_id  = str( api_key_obj.id )
        user_id = str( user.id )

    yield { "api_key": api_key, "user_id": user_id, "key_id": key_id, "email": email }

    with get_db() as session:
        ApiKeyRepository( session ).delete( uuid.UUID( key_id ) )
        UserRepository( session ).delete( uuid.UUID( user_id ) )


def _mint_body( created_by: str, **overrides ) -> dict:
    """Assemble a create body carrying the given (manager/worker) created_by identity."""
    body = {
        "item_class"      : "task",
        "title"           : f"blocked-at-mint probe {uuid.uuid4()}",
        "project"         : "lupin",
        "created_by"      : created_by,
        # MANDATORY since 2026-09-08 (epic-key guard ENFORCING). Without it every create
        # in this file answered 422 "no epic key" before reaching the door under test.
        "correlation_key" : "epic:unassigned",
        # P5 so the priority firewall (workers file P5) cannot be the gate that answers.
        "priority"        : "P5",
    }
    body.update( overrides )
    return body


def _post( headers: dict, body: dict ):
    return requests.post( ENDPOINT, json=body, headers=headers, timeout=10 )


def _assert_refused_by_the_create_door( r ):
    """A 403 from THIS door, not from the priority firewall or the blocked-mint guard."""
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
    assert "holding area" in r.text, f"403 came from a different gate: {r.text}"


# ═══════════════════════════════════════════════════════════════════════════
# 🔨 RETIRED AND REWRITTEN — 2026-09-11, row 2d786391 (María 🌸)
#
# Rick's 2026-07-20 one-call blocked mint (AC2 above) was RETIRED by his own ruling of
# 2026-09-08 (commits a5943777 + 6e356c9d): "I want to refuse a live status on create
# except in the case of P0 tickets", and then, asked about blocked: no — "Holding is now
# the only way onto the board, P0 aside." The 2026-09-11 landing added one exemption:
# the operator's validated login, because his New Ticket card names status="queued".
#
# ⇒ For an API-key seat, manager or worker, an explicit `queued` or `blocked` at P1–P5
#   is now REFUSED 403 and writes nothing; an omitted status lands in `not_approved`.
# ⇒ The allow-list (AC1, 422 for claimed/in_progress/...) is UNCHANGED: validation runs
#   before the door, so a junk status is still told it is junk.
# ⇒ Each old test is kept by NAME in the docstring of the test that replaced it, so a
#   reader who remembers "the manager blocked mint round-trips" finds why it no longer does.
# ═══════════════════════════════════════════════════════════════════════════

class TestALiveMintIsRefusedAtTheCreateDoor:
    """Was TestBlockedAtMintManagerAllowed. A MANAGER seat's live mint now goes nowhere."""

    def test_manager_blocked_mint_is_refused_and_writes_nothing( self, test_api_key, manager_created_by ):
        """Replaces test_manager_mints_blocked_row_persists_and_round_trips and
        test_manager_blocked_mint_stamps_blocked_creation_event (no row → no event)."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        marker  = f"mgr-blocked-{uuid.uuid4()}"
        r = _post( headers, _mint_body(
            manager_created_by,
            title         = marker,
            status        = "blocked",
            blocked_by    = BLOCK_REFS,
            next_chase_ts = BLOCK_CHASE_TS,
        ) )
        _assert_refused_by_the_create_door( r )
        q = requests.get( ENDPOINT, headers=headers, timeout=10,
                          params={ "project": "lupin", "limit": 500, "include_terminal": True } )
        assert all( t[ "title" ] != marker for t in q.json()[ "tasks" ] ), "a refused blocked mint leaked a row"

    def test_manager_default_mint_lands_in_holding_and_explicit_queued_is_refused( self, test_api_key, manager_created_by ):
        """Replaces test_manager_queued_mint_still_works_default_and_explicit."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }

        # omitted status → the holding area (the :8000 INI has the holding default ON)
        default = _post( headers, _mint_body( manager_created_by ) )
        assert default.status_code == 201, default.text
        assert default.json()[ "status" ] == "not_approved", default.json()

        # explicit status=queued → refused, and the refusal names the way out
        explicit = _post( headers, _mint_body( manager_created_by, status="queued" ) )
        _assert_refused_by_the_create_door( explicit )
        assert "OMIT" in explicit.text


class TestALiveMintByANonManagerIsRefused:
    """Was TestBlockedAtMintNonManagerRejected."""

    def test_non_manager_blocked_mint_is_rejected_403( self, test_api_key, worker_created_by ):
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        marker  = f"worker-blocked-{uuid.uuid4()}"

        r = _post( headers, _mint_body(
            worker_created_by,
            title         = marker,
            status        = "blocked",
            blocked_by    = BLOCK_REFS,
            next_chase_ts = BLOCK_CHASE_TS,
        ) )
        # Still 403 — now answered by the create door, which runs before the manager guard.
        _assert_refused_by_the_create_door( r )

        q = requests.get( ENDPOINT, headers=headers, timeout=10, params={ "project": "lupin", "limit": 500 } )
        assert all( t[ "title" ] != marker for t in q.json()[ "tasks" ] ), "rejected blocked-mint leaked a row"

    def test_non_manager_queued_mint_is_refused( self, test_api_key, worker_created_by ):
        """Replaces test_non_manager_queued_mint_still_allowed, which pinned the exact hole
        Rick ruled closed: a worker minting queued straight onto the live board."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        r = _post( headers, _mint_body( worker_created_by, status="queued" ) )
        _assert_refused_by_the_create_door( r )


class TestBlockedAtMintStatusWhitelist:
    """AC1: a true allow-list — every non-{queued,blocked,not_approved} mint status is REJECTED (422)."""

    @pytest.mark.parametrize( "bad_status", NON_MINTABLE_STATUSES )
    def test_non_mintable_status_is_rejected( self, test_api_key, manager_created_by, bad_status ):
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        marker  = f"whitelist-{bad_status}-{uuid.uuid4()}"
        # Minted AS A MANAGER so the reject is attributable to the STATUS whitelist
        # (422 rules), not to an authorization gate (403).
        r = _post( headers, _mint_body( manager_created_by, title=marker, status=bad_status ) )
        assert r.status_code == 422, f"status={bad_status} expected 422, got {r.status_code}: {r.text}"

        q = requests.get( ENDPOINT, headers=headers, timeout=10,
                          params={ "project": "lupin", "limit": 500, "include_terminal": True } )
        assert all( t[ "title" ] != marker for t in q.json()[ "tasks" ] ), f"rejected status={bad_status} leaked a row"

    def test_asking_explicitly_for_holding_is_accepted( self, test_api_key, manager_created_by ):
        """Replaces test_mintable_statuses_accepted[queued|blocked]. The one explicit status a
        seat may still name is the one the gate would have given it."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        r = _post( headers, _mint_body( manager_created_by, status="not_approved" ) )
        assert r.status_code == 201, r.text
        assert r.json()[ "status" ] == "not_approved"

    @pytest.mark.parametrize( "live_status", MINTABLE_STATUSES )
    def test_a_well_formed_live_mint_is_refused_by_the_door_not_the_whitelist( self, test_api_key, manager_created_by, live_status ):
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        extra   = {}
        if live_status == "blocked":
            extra = { "blocked_by": BLOCK_REFS, "next_chase_ts": BLOCK_CHASE_TS }
        r = _post( headers, _mint_body( manager_created_by, status=live_status, **extra ) )
        _assert_refused_by_the_create_door( r )


class TestBlockedAtMintThroughMcpWrapper:
    """Surface 4: the MCP task_create_impl wrapper carries the door's refusal back verbatim."""

    def test_wrapper_manager_blocked_mint_is_refused( self, test_api_key, manager_created_by ):
        """Replaces test_wrapper_manager_blocked_mint_round_trips."""
        res = task_create_impl(
            api_base_url    = BASE_URL,
            api_key         = test_api_key[ "api_key" ],
            created_by      = manager_created_by,
            item_class      = "task",
            title           = f"wrapper blocked-at-mint {uuid.uuid4()}",
            project         = "lupin",
            priority        = "P5",
            correlation_key = "epic:unassigned",
            status          = "blocked",
            blocked_by      = BLOCK_REFS,
            next_chase_ts   = BLOCK_CHASE_TS,
        )
        assert res.get( "status" ) == "error", res
        assert res.get( "http_status" ) == 403, res
        assert "holding area" in json.dumps( res ), res

    def test_wrapper_non_manager_blocked_mint_rejected( self, test_api_key, worker_created_by ):
        res = task_create_impl(
            api_base_url    = BASE_URL,
            api_key         = test_api_key[ "api_key" ],
            created_by      = worker_created_by,
            item_class      = "task",
            title           = f"wrapper worker-blocked reject {uuid.uuid4()}",
            project         = "lupin",
            priority        = "P5",
            correlation_key = "epic:unassigned",
            status          = "blocked",
            blocked_by      = BLOCK_REFS,
            next_chase_ts   = BLOCK_CHASE_TS,
        )
        # The wrapper maps a live 403 to its verbatim error dict, never raising.
        assert res.get( "status" ) == "error", res
        assert res.get( "http_status" ) == 403, res
