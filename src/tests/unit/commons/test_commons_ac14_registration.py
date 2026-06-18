"""
AC14 smoke verification for Phase 2 step 8.

Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md AC14.

Verifies that the `commons` router has the two endpoints registered as expected.
A full TestClient-on-app integration test against `src/lupin_app/main.py` is
heavyweight (GPU model loading + database init), so we verify at the router
level — the same routes will then be mounted on the app via
`app.include_router(commons.router)` in main.py.

This test does NOT contribute to the 100% coverage gate (per AC12), but it
DOES gate that the route registration didn't silently break.
"""

import pytest

from cosa.rest.routers.commons import router as commons_router


def test_ac14_active_sessions_route_registered():
    """GET /api/commons/active-sessions appears in the router's routes."""
    paths = { r.path for r in commons_router.routes }
    assert "/api/commons/active-sessions" in paths, f"missing route; got {paths}"


def test_ac14_broadcast_to_cc_sessions_route_registered():
    """POST /api/commons/broadcast-to-cc-sessions appears in the router's routes."""
    paths = { r.path for r in commons_router.routes }
    assert "/api/commons/broadcast-to-cc-sessions" in paths, f"missing route; got {paths}"


def test_ac14_active_sessions_is_get():
    """The /active-sessions endpoint is registered as GET, not POST."""
    for r in commons_router.routes:
        if r.path == "/api/commons/active-sessions":
            assert "GET" in r.methods, f"expected GET in {r.methods}"
            return
    pytest.fail( "route /api/commons/active-sessions not found" )


def test_ac14_broadcast_is_post():
    """The /broadcast-to-cc-sessions endpoint is registered as POST, not GET."""
    for r in commons_router.routes:
        if r.path == "/api/commons/broadcast-to-cc-sessions":
            assert "POST" in r.methods, f"expected POST in {r.methods}"
            return
    pytest.fail( "route /api/commons/broadcast-to-cc-sessions not found" )


def test_ac14_router_prefix_and_tag():
    """Router has the expected /api/commons prefix + commons tag."""
    assert commons_router.prefix == "/api/commons"
    assert "commons" in commons_router.tags


# ─── register-question endpoints — REMOVED (cosa-voice token-reduction Phase 4) ─
# The POST/DELETE /api/commons/register-question routes — and their pure-logic
# cores (execute_register_question / execute_unregister_question) + the
# CommonsQuestionWatcher daemon — were physically DELETED (full-removal pass,
# 2026-06-17): the legacy DM claim-check path is superseded by the
# notification-native dm_send / POST /api/dm/send path. The two assertions below
# guard that the routes stay deregistered (cutover regression guard).
# Plan: src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/03-phase4-legacy-commons-dm-retirement-proposal.md §9


def test_register_question_post_route_deregistered():
    """POST /api/commons/register-question is NO LONGER registered (Phase 4 cutover)."""
    paths = { r.path for r in commons_router.routes }
    assert "/api/commons/register-question" not in paths, f"route should be retired; got {paths}"


def test_register_question_delete_route_deregistered():
    """DELETE /api/commons/register-question/{question_id} is NO LONGER registered (Phase 4 cutover)."""
    paths = { r.path for r in commons_router.routes }
    assert "/api/commons/register-question/{question_id}" not in paths, f"route should be retired; got {paths}"
