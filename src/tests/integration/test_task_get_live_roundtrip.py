"""
Integration test — `task_get` MCP verb, live HTTP round-trip (plan 4288dd53 §7).

Drives the REAL `task_get_impl` transport against the live `get_task` REST route
(routers/tasks.py, already deployed) — the manager-sanctioned integration arm for
the uncommitted MCP verb (a :8000 snapshot with reload=False would not carry the
new verb registration; the underlying route is deployed on both servers).

READ-ONLY: uses an already-existing store row for the 200 arm and a random absent
UUID for the 404 arm — no seeding, no persistent-state mutation — so it rides
:7999 per the venue rubric (no monopoly, seconds, no writes).

Arms (plan §6 acceptance criteria):
    AC1  valid id      -> 200, FULL item incl `body` (not the terse projection)
    AC2  absent UUID   -> error dict carrying "task {id} not found" verbatim,
                          NEVER an empty success / None
    AC3  malformed id  -> the server's 422 surfaced verbatim, no client raise

Base URL parameterized via LUPIN_TASK_GET_BASE_URL (default the :7999 dev server).
A real existing task id is discovered at runtime via GET /api/tasks (terse), so the
test is self-seeding-free and does not pin a specific UUID that may age out.
"""

import os
import uuid

import pytest

from lupin_mcp.task_store_tools import task_get_impl, task_store_request


BASE_URL = os.environ.get( "LUPIN_TASK_GET_BASE_URL", "http://localhost:7999" )


def _api_key():
    """Load the same outbound X-API-Key the MCP verb uses; skip if unreadable."""
    try:
        import cosa.utils.util as du
        return du.get_api_key( "notification-api-claude-code-dev" )
    except Exception:
        return None


@pytest.fixture( scope="module" )
def api_key():
    key = _api_key()
    if key is None:
        pytest.skip( "outbound notification-api-claude-code-dev key unreadable" )
    return key


@pytest.fixture( scope="module" )
def existing_task_id( api_key ):
    """Discover one real, non-terminal store row id (read-only) for the 200 arm."""
    # A narrowing filter (status) is REQUIRED — a bare /api/tasks trips the
    # unscoped-query guard and returns an error dict, not {tasks}.
    body = task_store_request( "GET", "/api/tasks", BASE_URL, api_key, params={ "status": "queued", "terse": "true", "limit": 1 } )
    if not isinstance( body, dict ) or not body.get( "tasks" ):
        pytest.skip( f"no store rows available to fetch (got {body!r})" )
    return body[ "tasks" ][ 0 ][ "id" ]


def test_valid_id_returns_full_item_with_body( api_key, existing_task_id ):
    """AC1: valid id -> 200, full serialized item including a non-terse `body`."""
    item = task_get_impl( BASE_URL, api_key, existing_task_id )

    assert isinstance( item, dict ),                     f"expected dict, got {type( item )}"
    assert item.get( "status" ) != "error",              f"unexpected error dict: {item!r}"
    assert item.get( "id" ) == existing_task_id,         f"id mismatch: {item.get( 'id' )!r}"
    # FULL shape, not the terse projection: `body` key is present (may be None if
    # the row was created bodyless, but the KEY exists in the full serialization).
    assert "body" in item,                               f"full item missing `body` key: {sorted( item )}"


def test_absent_uuid_returns_404_error_dict( api_key ):
    """AC2: well-formed but absent UUID -> error dict, http 404, 'not found' verbatim."""
    absent = str( uuid.uuid4() )
    result = task_get_impl( BASE_URL, api_key, absent )

    assert isinstance( result, dict ),                   f"expected error dict, got {type( result )}"
    assert result is not None,                           "absent row must NEVER render as None"
    assert result.get( "status" )      == "error",       f"expected error status: {result!r}"
    assert result.get( "http_status" ) == 404,           f"expected 404: {result!r}"
    assert "not found" in str( result.get( "detail", "" ) ).lower(), f"missing verbatim detail: {result!r}"


def test_malformed_id_returns_422_passthrough( api_key ):
    """AC3: malformed id -> server's 422 surfaced verbatim, no client-side raise."""
    result = task_get_impl( BASE_URL, api_key, "not-a-uuid" )

    assert isinstance( result, dict ),                   f"expected error dict, got {type( result )}"
    assert result.get( "status" )      == "error",       f"expected error status: {result!r}"
    assert result.get( "http_status" ) == 422,           f"expected 422: {result!r}"


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
