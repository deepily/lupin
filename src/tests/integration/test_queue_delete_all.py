"""
Integration tests for the DELETE /api/queue/{name}/all and
DELETE /api/job-history/all route-ordering fix.

Background (2026-04-21):
    DELETE /api/queue/done/all was returning 404 on the test server because
    the parameterized DELETE /api/queue/{queue_name}/{job_id} route was
    defined BEFORE the literal DELETE /api/queue/{queue_name}/all in
    src/cosa/rest/routers/queues.py. FastAPI matched the parameterized route
    first, bound job_id="all", failed to find a job with that id, and raised
    404. The same latent defect existed for DELETE /api/job-history/all vs
    DELETE /api/job-history/{job_id}.

    Fix: reorder route declarations so the literal /all routes precede their
    /{id} siblings.

These tests lock in the routing behavior. They verify:
  - Both /all endpoints reach their bulk handlers (HTTP 200).
  - Invalid queue name on /all surfaces as HTTP 400 from the bulk handler's
    own validation, proving /all is the matched route — a 404 here would
    mean the parameterized route shadowed us again.
  - Both /{id} endpoints still behave correctly (HTTP 404 on unknown ids)
    — the literal /all route is specific to the exact path segment "all"
    and must not intercept other ids.

Queue-content semantics (how many items the bulk delete removes) are
intentionally out of scope here — the bug is pure routing, and seeding the
live in-memory queues from an HTTP integration test would require either
flaky pushes-and-waits or in-process queue access that HTTP doesn't expose.
The bulk handler logic itself was already correct when the endpoints were
unreachable; this file guards the route table, nothing else.
"""

import pytest
import requests

from tests.integration.conftest import BASE_URL, get_auth_header
from tests.helpers.job_history_seed import seed_job_history_records


class TestQueueBulkDeleteRouteOrdering:
    """Lock-in: DELETE /api/queue/{name}/all must not be shadowed by /{job_id}."""

    @pytest.mark.parametrize( "queue_name", [ "todo", "run", "done", "dead" ] )
    def test_delete_all_returns_200_not_shadowed_404( self, create_test_user, queue_name ):
        """
        DELETE /api/queue/{queue_name}/all reaches the bulk handler (HTTP 200)
        rather than falling through to the parameterized /{job_id} handler,
        which would bind job_id="all" and raise 404.
        """
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.delete(
            f"{BASE_URL}/api/queue/{queue_name}/all",
            headers=headers
        )

        assert response.status_code == 200, (
            f"Regression: DELETE /api/queue/{queue_name}/all returned "
            f"{response.status_code}; expected 200. Body: {response.text}"
        )
        data = response.json()
        assert data[ "status" ]     == "deleted"
        assert data[ "queue_name" ] == queue_name
        assert isinstance( data[ "items_deleted" ], int )
        assert "timestamp" in data

    def test_delete_all_invalid_queue_name_returns_400_not_404( self, create_test_user ):
        """
        DELETE /api/queue/bogus/all returns 400 from the bulk handler's own
        queue-name validation — proof the /all route is the one matched.
        A 404 here would mean the parameterized /{job_id} route shadowed us.
        """
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.delete(
            f"{BASE_URL}/api/queue/bogus/all",
            headers=headers
        )

        assert response.status_code == 400, (
            f"Regression: DELETE /api/queue/bogus/all returned "
            f"{response.status_code}; expected 400 from the /all handler's "
            f"queue-name validation. 404 would indicate the routing fix "
            f"regressed and the parameterized /{{job_id}} handler intercepted."
        )

    def test_delete_single_job_unknown_id_still_404( self, create_test_user ):
        """
        DELETE /api/queue/done/{unknown_id} still returns 404 — the
        parameterized route survives the reorder for non-"all" path segments.
        """
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.delete(
            f"{BASE_URL}/api/queue/done/nonexistent-job-id-xyz",
            headers=headers
        )

        assert response.status_code == 404, (
            f"Parameterized DELETE /api/queue/{{queue_name}}/{{job_id}} "
            f"returned {response.status_code} for an unknown id; expected 404."
        )


class TestJobHistoryBulkDeleteRouteOrdering:
    """Lock-in: DELETE /api/job-history/all must not be shadowed by /{job_id}."""

    def test_delete_all_returns_200_not_shadowed_404( self, create_test_user ):
        """
        DELETE /api/job-history/all reaches the bulk handler (HTTP 200)
        rather than falling through to the parameterized /{job_id} handler,
        which would bind job_id="all" and raise 404.

        Seeds 3 rows so the handler has non-zero work to do, but the
        routing assertion would hold even for items_deleted=0.
        """
        headers = get_auth_header( create_test_user[ "access_token" ] )

        seed_job_history_records(
            user_id    = create_test_user[ "user_id" ],
            user_email = create_test_user[ "email" ],
            records    = [ { "id_suffix": f"bulk-{i}" } for i in range( 3 ) ]
        )

        response = requests.delete(
            f"{BASE_URL}/api/job-history/all",
            headers=headers
        )

        assert response.status_code == 200, (
            f"Regression: DELETE /api/job-history/all returned "
            f"{response.status_code}; expected 200. Body: {response.text}"
        )
        data = response.json()
        assert data[ "status" ] == "deleted"
        assert isinstance( data[ "items_deleted" ], int )
        assert data[ "items_deleted" ] >= 3
        assert data[ "days_filter" ] == "all"
        assert "timestamp" in data

    def test_delete_single_history_unknown_id_still_404( self, create_test_user ):
        """
        DELETE /api/job-history/{unknown_id} still returns 404 — the
        parameterized route survives the reorder.
        """
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.delete(
            f"{BASE_URL}/api/job-history/nonexistent-history-id-xyz",
            headers=headers
        )

        assert response.status_code == 404, (
            f"Parameterized DELETE /api/job-history/{{job_id}} returned "
            f"{response.status_code} for an unknown id; expected 404."
        )
