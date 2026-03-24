"""
Integration Tests for Queue !self Filter

Tests the new 'Not My Jobs' (!self) queue filter on /api/get-queue endpoints.
Validates data correctness: disjoint sets, complete coverage, and 403 for non-admin.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via clean_test_db fixture)
"""

import pytest
import requests
import time

from .conftest import BASE_URL


def register_and_login( email, password ):
    """
    Register a user and login, returning (access_token, user_id).

    Requires:
        - email and password are valid
        - Server is running

    Ensures:
        - Returns tuple of (access_token, user_id)

    Raises:
        - AssertionError if registration or login fails
    """
    reg = requests.post(
        f"{BASE_URL}/auth/register",
        json={ "email": email, "password": password }
    )
    assert reg.status_code == 201, f"Registration failed: {reg.status_code} {reg.text}"

    login = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password }
    )
    assert login.status_code == 200, f"Login failed: {login.status_code} {login.text}"

    data   = login.json()
    token  = data[ "tokens" ][ "access_token" ]
    uid    = data[ "user" ][ "id" ]
    return token, uid


def make_admin( email ):
    """
    Assign admin role to an existing user via direct DB access.

    Requires:
        - User with given email exists in database

    Ensures:
        - User has roles ["user", "admin"]
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories import UserRepository

    with get_db() as session:
        user_repo = UserRepository( session )
        user      = user_repo.get_by_email( email )
        if user:
            user.roles = [ "user", "admin" ]


def relogin( email, password ):
    """
    Re-login to get a fresh token (needed after role change).

    Requires:
        - User exists and password is correct

    Ensures:
        - Returns fresh access_token reflecting current roles
    """
    login = requests.post(
        f"{BASE_URL}/auth/login",
        json={ "email": email, "password": password }
    )
    assert login.status_code == 200
    return login.json()[ "tokens" ][ "access_token" ]


def push_job( token, question, session_id="test_session" ):
    """
    Submit a job to the todo queue.

    Requires:
        - Valid auth token

    Ensures:
        - Returns response from /api/push
    """
    return requests.post(
        f"{BASE_URL}/api/push",
        json={ "question": question, "websocket_id": session_id },
        headers={ "Authorization": f"Bearer {token}" }
    )


def get_queue( token, queue_name="todo", user_filter=None ):
    """
    Query a queue with optional user_filter.

    Requires:
        - Valid auth token

    Ensures:
        - Returns parsed JSON response from /api/get-queue/{queue_name}
    """
    url = f"{BASE_URL}/api/get-queue/{queue_name}"
    if user_filter is not None:
        url += f"?user_filter={user_filter}"

    resp = requests.get( url, headers={ "Authorization": f"Bearer {token}" } )
    return resp


def extract_job_ids( queue_response_json, queue_name="todo" ):
    """
    Extract job IDs from a queue response.

    Requires:
        - queue_response_json is the parsed JSON from get_queue

    Ensures:
        - Returns set of job_id strings
    """
    key  = f"{queue_name}_jobs_metadata"
    jobs = queue_response_json.get( key, [] )
    return { job[ "job_id" ] for job in jobs }


# ---------------------------------------------------------------------------
# !self Filter Authorization Tests
# ---------------------------------------------------------------------------

class TestNotSelfFilterAuthorization:
    """Tests that !self filter respects role-based access control."""

    def test_regular_user_not_self_forbidden( self, clean_test_db ):
        """
        Regular user attempting !self filter receives 403 Forbidden.

        Requires:
            - Authenticated as regular (non-admin) user

        Ensures:
            - 403 status code returned
            - Error message mentions 'admin'
        """
        token, _ = register_and_login( "regular@notself.com", "TestPassword123!" )

        resp = get_queue( token, "todo", user_filter="!self" )

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        assert "admin" in resp.json()[ "detail" ].lower()

    def test_admin_not_self_returns_200( self, clean_test_db ):
        """
        Admin user with !self filter receives 200 OK.

        Requires:
            - Authenticated as admin user

        Ensures:
            - 200 status code returned
            - Response contains expected metadata fields
        """
        token, uid = register_and_login( "admin@notself.com", "TestPassword123!" )
        make_admin( "admin@notself.com" )
        token = relogin( "admin@notself.com", "TestPassword123!" )

        resp = get_queue( token, "todo", user_filter="!self" )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "filtered_by" in data
        assert data[ "filtered_by" ].startswith( "!" ), f"filtered_by should start with '!', got: {data[ 'filtered_by' ]}"
        assert data[ "is_admin_view" ] is True


# ---------------------------------------------------------------------------
# !self Filter Data Correctness Tests
# ---------------------------------------------------------------------------

class TestNotSelfFilterData:
    """Tests that !self filter returns correct job sets."""

    def test_admin_not_self_excludes_own_jobs( self, clean_test_db ):
        """
        Admin's own jobs do NOT appear in !self results.

        Requires:
            - Admin submits a job
            - Admin queries with !self

        Ensures:
            - Admin's own job is NOT in the result set
        """
        # Create admin and submit a job
        token, uid = register_and_login( "admin2@notself.com", "TestPassword123!" )
        make_admin( "admin2@notself.com" )
        token = relogin( "admin2@notself.com", "TestPassword123!" )

        push_resp = push_job( token, "Admin's own question", "admin_session" )
        assert push_resp.status_code == 200
        admin_job_id = push_resp.json().get( "job_id" )

        # Small delay for queue processing
        time.sleep( 0.5 )

        # Query own jobs (default)
        own_resp = get_queue( token, "todo" )
        own_data = own_resp.json()
        own_job_ids = extract_job_ids( own_data, "todo" )

        # Query !self
        notself_resp = get_queue( token, "todo", user_filter="!self" )
        notself_data = notself_resp.json()
        notself_job_ids = extract_job_ids( notself_data, "todo" )

        # Admin's job should be in own but NOT in !self
        if admin_job_id and admin_job_id in own_job_ids:
            assert admin_job_id not in notself_job_ids, \
                f"Admin's job {admin_job_id} should NOT appear in !self results"

    def test_own_and_not_self_results_are_disjoint( self, clean_test_db ):
        """
        Jobs returned by 'own' and '!self' have zero overlap.

        Requires:
            - Admin user exists
            - Jobs exist in the queue

        Ensures:
            - No job_id appears in both own and !self result sets
        """
        token, uid = register_and_login( "admin3@notself.com", "TestPassword123!" )
        make_admin( "admin3@notself.com" )
        token = relogin( "admin3@notself.com", "TestPassword123!" )

        # Submit a job as admin
        push_job( token, "Disjoint test question", "disjoint_session" )
        time.sleep( 0.5 )

        # Query both modes
        own_resp     = get_queue( token, "todo" )
        notself_resp = get_queue( token, "todo", user_filter="!self" )

        own_ids     = extract_job_ids( own_resp.json(), "todo" )
        notself_ids = extract_job_ids( notself_resp.json(), "todo" )

        # Verify disjoint
        overlap = own_ids & notself_ids
        assert len( overlap ) == 0, f"Overlap found between own and !self: {overlap}"

    def test_own_plus_not_self_equals_all( self, clean_test_db ):
        """
        own ∪ !self = * (complete coverage of all jobs).

        Requires:
            - Two users submit jobs
            - Admin queries all three modes

        Ensures:
            - Union of own + !self job IDs equals * (all) job IDs
        """
        # Create two users
        admin_token, _ = register_and_login( "admin4@notself.com", "TestPassword123!" )
        make_admin( "admin4@notself.com" )
        admin_token = relogin( "admin4@notself.com", "TestPassword123!" )

        user_token, _ = register_and_login( "user4@notself.com", "TestPassword123!" )

        # Each submits a job
        push_job( admin_token, "Admin question for union test", "admin_union_session" )
        push_job( user_token, "User question for union test", "user_union_session" )
        time.sleep( 0.5 )

        # Query all three modes as admin
        own_resp     = get_queue( admin_token, "todo" )
        notself_resp = get_queue( admin_token, "todo", user_filter="!self" )
        all_resp     = get_queue( admin_token, "todo", user_filter="*" )

        own_ids     = extract_job_ids( own_resp.json(), "todo" )
        notself_ids = extract_job_ids( notself_resp.json(), "todo" )
        all_ids     = extract_job_ids( all_resp.json(), "todo" )

        union_ids = own_ids | notself_ids

        # Verify complete coverage
        assert union_ids == all_ids, \
            f"own ∪ !self should equal *.\n" \
            f"  own:     {own_ids}\n" \
            f"  !self:   {notself_ids}\n" \
            f"  union:   {union_ids}\n" \
            f"  all (*): {all_ids}\n" \
            f"  missing: {all_ids - union_ids}\n" \
            f"  extra:   {union_ids - all_ids}"

    def test_not_self_works_across_queue_types( self, clean_test_db ):
        """
        !self filter works for all queue types (todo, done, dead).

        Requires:
            - Admin user exists

        Ensures:
            - All queue types accept !self and return valid responses
        """
        token, _ = register_and_login( "admin5@notself.com", "TestPassword123!" )
        make_admin( "admin5@notself.com" )
        token = relogin( "admin5@notself.com", "TestPassword123!" )

        for queue_name in [ "todo", "done", "dead" ]:
            resp = get_queue( token, queue_name, user_filter="!self" )
            assert resp.status_code == 200, \
                f"!self filter failed for {queue_name}: {resp.status_code} {resp.text}"
            data = resp.json()
            assert data[ "filtered_by" ].startswith( "!" ), \
                f"{queue_name}: filtered_by should start with '!', got: {data[ 'filtered_by' ]}"
