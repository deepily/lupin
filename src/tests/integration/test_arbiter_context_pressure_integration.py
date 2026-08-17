"""
Integration tests for GET /api/arbiter/context-pressure — the published
per-persona context-headroom service (design 2026.06.09, Rick's Decisions 1-5;
built P1 commit 4a3d27a, live on :8001 since Rick's deploy restart).

Authored by Krishna 🦚 (implementer, for Tiberius 👑). The unit suite
(`src/tests/unit/test_arbiter_router.py`) overrides `require_api_key_or_jwt`
and monkeypatches the :8001 pull to test ROUTING in isolation. THIS suite
exercises the REAL credential against a live server + auth DB AND the real
:8001 upstream — the full published-surface contract end to end.

VENUE: :8000 monopolize-mode, SCHEDULED ONLY. The auth path needs a real DB
credential (the seeded test_api_key mutates the test DB) → NOT :7999-eligible
and must NEVER be side-door-injected. Submit via POST /api/test-suite/submit.
Base URL via `LUPIN_TEST_BASE_URL` (default http://localhost:8000), per the
integration convention.

LIVE-FLEET CAVEAT: the persona map reflects whatever CC fleet is alive at run
time (possibly empty at an off-peak slot). Assertions therefore pin the
CONTRACT (shape, policy echo, summary arithmetic, per-record budget-math
self-consistency) — never specific persona names or counts. The budget-math
"known fixture" is each live measured record itself: every published number
must satisfy the §3 formulas exactly (ceiling = round(window×fraction),
headroom = ceiling − occupancy, sign-honest status).
"""

import os

import pytest
import requests
import bcrypt
import secrets
import uuid

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import UserRepository, ApiKeyRepository


BASE_URL             = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
ENDPOINT             = f"{BASE_URL}/api/arbiter/context-pressure"
FLEET_STATE_ENDPOINT = f"{BASE_URL}/api/arbiter/fleet-state"

# The §6 policy keys as deployed (lupin-app.ini, Decision 5). JSON object keys
# are strings, so the policy echo stringifies the window sizes.
EXPECTED_POLICY = { "1000000": 0.50, "200000": 0.75, "default": 0.50 }

# unnamed_live_seats joined the summary when nameless live seats became visible
# (row 9c720767) — a seat with no persona allocated is reported explicitly now,
# not omitted.
SUMMARY_KEYS = { "personas", "unnamed_live_seats", "within_budget", "over_budget", "idle_or_unknown" }


# ── test_api_key fixture (replicated from the proven test_notification_auth.py /
#    test_arbiter_fleet_snapshot_integration.py pattern, so this suite is
#    self-contained; seeds a real service-account + API key in the test DB). ────
@pytest.fixture
def test_api_key( clean_test_db ):
    """Create a test API key and store its bcrypt hash in the test database."""
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
            description = "Arbiter context-pressure integration test key",
        )
        key_id  = str( api_key_obj.id )
        user_id = str( user.id )

    yield {
        "api_key" : api_key,
        "user_id" : user_id,
        "key_id"  : key_id,
        "email"   : email,
    }

    # Explicit teardown (clean_test_db also drops tables; kept for clarity).
    with get_db() as session:
        ApiKeyRepository( session ).delete( uuid.UUID( key_id ) )
        UserRepository( session ).delete( uuid.UUID( user_id ) )


def _get_live_section( headers ):
    """
    GET the section and FAIL LOUDLY when it is not the live published object.

    The endpoint's degrade envelopes ({status:"unreachable"} when :8001 is down,
    {status:"awaiting"} when the deployed arbiter predates the writer or has not
    ticked yet) are correct API behavior but a FAILED deploy precondition for
    this suite — the task is to verify the LIVE service, so we assert them away
    with a diagnostic rather than skipping silently.
    """
    r = requests.get( ENDPOINT, headers=headers, timeout=10 )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    assert body.get( "status" ) not in ( "unreachable", "awaiting" ), \
        f"live context_pressure section not published — deploy precondition failed: {body}"
    return body


class TestContextPressureAuth:
    """The credential matrix against the live server + auth DB (C2 contract)."""

    def test_get_missing_auth_returns_401( self ):
        """No credential → 401 with the canonical 'Missing auth' message."""
        r = requests.get( ENDPOINT, timeout=10 )
        assert r.status_code == 401, f"{r.status_code}: {r.text}"
        assert "Missing auth" in r.json()[ "detail" ]

    def test_get_malformed_api_key_returns_401( self ):
        """A non-ck_live_ key fails the format regex → 401."""
        r = requests.get( ENDPOINT, headers={ "X-API-Key": "not-a-valid-key" }, timeout=10 )
        assert r.status_code == 401, f"{r.status_code}: {r.text}"
        assert "Invalid API key format" in r.json()[ "detail" ]

    def test_get_valid_api_key_returns_200( self, test_api_key ):
        """A real seeded X-API-Key is accepted → 200 ('anyone with the API key')."""
        r = requests.get( ENDPOINT, headers={ "X-API-Key": test_api_key[ "api_key" ] }, timeout=10 )
        assert r.status_code == 200, f"{r.status_code}: {r.text}"

    def test_get_valid_jwt_returns_200( self, auth_headers ):
        """A real Bearer JWT (conftest auth_headers) is accepted → 200."""
        r = requests.get( ENDPOINT, headers=auth_headers, timeout=10 )
        assert r.status_code == 200, f"{r.status_code}: {r.text}"


class TestContextPressurePublishedObject:
    """The §4 published-object contract, against the LIVE writer output."""

    def test_persona_keyed_object_with_policy_and_summary( self, test_api_key ):
        """Live section carries generated_at + the §6 policy echo + personas map + §4 summary."""
        body = _get_live_section( { "X-API-Key": test_api_key[ "api_key" ] } )
        assert isinstance( body[ "generated_at" ], str ) and body[ "generated_at" ]
        assert body[ "policy" ] == EXPECTED_POLICY
        assert isinstance( body[ "personas" ], dict )
        assert isinstance( body[ "unnamed_seats" ], list )        # nameless live seats, reported explicitly
        for rec in body[ "unnamed_seats" ]:
            assert rec[ "persona" ] is None, rec                  # a nameless row states persona null
        assert set( body[ "summary" ].keys() ) == SUMMARY_KEYS

    def test_summary_arithmetic_is_consistent( self, test_api_key ):
        """summary.personas == len(personas), summary.unnamed_live_seats ==
        len(unnamed_seats), and the three status buckets partition ALL live
        seats — named AND nameless — exactly."""
        body    = _get_live_section( { "X-API-Key": test_api_key[ "api_key" ] } )
        summary = body[ "summary" ]
        assert summary[ "personas" ]           == len( body[ "personas" ] )
        assert summary[ "unnamed_live_seats" ] == len( body[ "unnamed_seats" ] )
        assert ( summary[ "within_budget" ] + summary[ "over_budget" ] + summary[ "idle_or_unknown" ] ) \
               == summary[ "personas" ] + summary[ "unnamed_live_seats" ]

    def test_budget_math_self_consistent_on_live_records( self, test_api_key ):
        """
        §3 budget math holds EXACTLY on every live measured record (the 'known
        fixture' is the published record itself): ceiling = round(window ×
        fraction), both headrooms = ceiling − their occupancy basis, fraction
        matches the policy for that window, and status is SIGN-HONEST
        (over_budget iff current headroom < 0 — negatives published, not clamped).
        """
        body = _get_live_section( { "X-API-Key": test_api_key[ "api_key" ] } )
        for persona, rec in body[ "personas" ].items():
            if rec[ "occupancy_tokens" ] is None:
                # unmeasured (idle/dead/unknown) — no false zero published
                assert rec[ "status" ] in ( "idle", "dead", "unknown" ), f"{persona}: {rec}"
                assert rec[ "headroom_tokens_current" ] is None, f"{persona}: {rec}"
                continue
            window   = rec[ "window_size" ]
            fraction = rec[ "budget_fraction" ]
            expected_fraction = body[ "policy" ].get( str( window ), body[ "policy" ][ "default" ] )
            assert fraction == expected_fraction, f"{persona}: {rec}"
            assert rec[ "budget_ceiling_tokens" ]   == round( window * fraction ), f"{persona}: {rec}"
            assert rec[ "headroom_tokens_current" ] == rec[ "budget_ceiling_tokens" ] - rec[ "occupancy_tokens" ], f"{persona}: {rec}"
            assert rec[ "headroom_tokens_forward" ] == rec[ "budget_ceiling_tokens" ] - rec[ "next_prompt_estimate" ], f"{persona}: {rec}"
            expected_status = "over_budget" if rec[ "headroom_tokens_current" ] < 0 else "within_budget"
            assert rec[ "status" ] == expected_status, f"{persona}: {rec}"

    def test_section_also_rides_fleet_state_composite( self, test_api_key ):
        """
        Decision 3's free rider: the same section appears under the
        /api/arbiter/fleet-state composite (the :7999/:8000 proxy forwards the
        whole :8001/state body), persona-for-persona with the dedicated surface.
        """
        headers   = { "X-API-Key": test_api_key[ "api_key" ] }
        section   = _get_live_section( headers )
        composite = requests.get( FLEET_STATE_ENDPOINT, headers=headers, timeout=10 )
        assert composite.status_code == 200, f"{composite.status_code}: {composite.text}"
        body = composite.json()
        assert "context_pressure" in body, f"composite lacks the section: {list( body.keys() )}"
        riding = body[ "context_pressure" ]
        assert riding.get( "status" ) not in ( "unreachable", "awaiting" ), riding
        assert riding[ "policy" ] == section[ "policy" ]
        assert set( riding[ "summary" ].keys() ) == SUMMARY_KEYS
        # same fleet, modulo a writer tick between the two GETs
        assert isinstance( riding[ "personas" ], dict )


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
