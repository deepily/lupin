"""
Regression guard: dual-container auth parity.

Purpose:
    Catch the case where a required test user (from env vars) exists in
    lupin_db_dev but has not been propagated to lupin_db_test via the
    companion seed script (src/scripts/seed_test_companions.py).

    This was the root cause of the 2026-04-13 test-container login 401:
    `interactive.job.tester@lupin.deepily.ai` was in dev but missing
    from test, so /auth/login on :8000 returned 401.

Topology (2026-04-12+):
    - Host  :7999 -> lupin-rest-dev  container (lupin_db_dev)
    - Host  :8000 -> lupin-rest-test container (lupin_db_test)
    - Inside any container: :7999

If only one container is running, this test skips the missing side rather
than failing — the point is to guarantee parity across reachable containers.
"""

import os
import pytest
import requests


DEV_URL  = "http://localhost:7999"
TEST_URL = "http://localhost:8000"


def _server_up( container_url: str ) -> bool:
    try:
        r = requests.get( f"{container_url}/health", timeout=5 )
        return r.status_code == 200
    except Exception:
        return False


def _get_creds() -> tuple:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/PASSWORD not set" )
    return email, password


@pytest.mark.parametrize( "container_url,label", [
    ( DEV_URL,  "dev (:7999)"  ),
    ( TEST_URL, "test (:8000)" ),
] )
def test_login_succeeds_on_reachable_containers( container_url, label ):
    """
    Hitting /auth/login with the canonical test credentials must return 200
    and a bearer access_token on every reachable container.
    """
    if not _server_up( container_url ):
        pytest.skip( f"Container {label} not reachable at {container_url}" )

    email, password = _get_creds()

    r = requests.post(
        f"{container_url}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )

    assert r.status_code == 200, (
        f"Login on {label} failed: HTTP {r.status_code} — {r.text}\n"
        "If this is the test container, check that the user is seeded into "
        "lupin_db_test via src/scripts/seed_test_companions.py (COMPANION_EMAILS)."
    )
    body = r.json()
    assert "tokens" in body and "access_token" in body[ "tokens" ], (
        f"Login on {label} missing tokens.access_token — response: {body}"
    )
    assert body[ "user" ][ "email" ] == email


def test_at_least_one_container_is_reachable():
    """Sanity: don't let a silent env failure mark every parametrize case as skipped."""
    assert _server_up( DEV_URL ) or _server_up( TEST_URL ), (
        "Neither :7999 (dev) nor :8000 (test) is reachable — "
        "nothing to validate."
    )
