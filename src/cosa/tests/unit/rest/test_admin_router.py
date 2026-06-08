"""
Unit tests for cosa.rest.routers.admin — the admin router ( 14 endpoints + 4 helpers ).

Every endpoint is exercised by DIRECT call. Per handoff Gotcha 2, every Depends parameter
( admin_user = Depends( require_admin ), snapshot_mgr = Depends( get_snapshot_manager ) ) and
every Request is passed EXPLICITLY so no FieldInfo object leaks into a branch decision. Per
Gotcha 1, get_snapshot_manager ( which does `import lupin_app.main as main_module` ) is tested
with the dual-key _patch_fastapi_main helper; all other snapshot endpoints receive an explicit
mock snapshot_mgr, sidestepping the import entirely.

All collaborators are mocked at the router namespace ( cosa.rest.routers.admin.<fn> ); the
admin_service / user_service functions are already 100% elsewhere and are NOT re-tested.
ZERO real DB / vector-store / network / process re-exec, ZERO API spend.

Covers:
    - get_snapshot_manager      ( dual-key main-module patch )
    - get_users                 ( success / exception 500 )
    - get_user                  ( not-found 404 / success )
    - update_roles              ( not-found 404 / cannot-remove 400 / invalid 400 / other 500 / success; client-None arm )
    - update_status             ( not-found 404 / cannot-deactivate 400 / other 500 / success; client-None arm )
    - reset_user_password       ( not-found 404 / other 500 / success; client-None arm )
    - create_user_endpoint      ( invalid/already/duplicate/password 400 / other 500 / success; client-None arm )
    - delete_user_endpoint      ( not-found 404 / cannot-delete 400 / sole-admin 400 / other 500 / success;
                                  request_body None + present reason arms; client-None arm )
    - batch_delete_users        ( mixed results, reason present + default )
    - search_snapshots          ( empty-q / whitespace-q / threshold lo+hi / limit lo+hi / success + synonyms arms / 500 )
    - get_snapshot_details      ( not-found 404 / success / generic 500 )
    - delete_snapshot           ( not-found 404 / delete-true / delete-false 500 / generic 500 )
    - get_snapshot_preview      ( not-found 404 / list-code+long+gist / non-list-code+empty+fallback / generic 500 )
    - get_similar_snapshots     ( source-404 / success debug T + F / code-except T+F / expl-except T+F / generic 500 )
    - _refresh_source_allowed   ( wrong-env / disabled / enabled )
    - _reexec_process           ( os.execv invoked )
    - refresh_source            ( forbidden 403 / accepted + delayed-reexec task body )
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi import HTTPException

import cosa.rest.routers.admin as admin
from cosa.rest.routers.admin import (
    get_snapshot_manager,
    get_users,
    get_user,
    update_roles,
    update_status,
    reset_user_password,
    create_user_endpoint,
    delete_user_endpoint,
    batch_delete_users_endpoint,
    search_snapshots,
    get_snapshot_details,
    delete_snapshot,
    get_snapshot_preview,
    get_similar_snapshots,
    _refresh_source_allowed,
    _reexec_process,
    refresh_source,
)


ADMIN = { "user_id": "admin-1", "email": "admin@example.com" }


def _patch_fastapi_main( mock_main ):
    """
    Ensures:
        - Patches BOTH the lupin_app package and its .main submodule ( Gotcha 1 dual-key )
          so `import lupin_app.main as main_module` resolves to mock_main
    """
    pkg = MagicMock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _req( client_host="1.2.3.4" ):
    """
    Ensures:
        - Returns a request stand-in whose .client.host is client_host, or .client None
    """
    if client_host is None:
        return SimpleNamespace( client=None )
    return SimpleNamespace( client=SimpleNamespace( host=client_host ) )


def _ns( **kw ):
    """Ensures: returns a SimpleNamespace request-body stand-in ( no Pydantic validation )."""
    return SimpleNamespace( **kw )


def _snap( **kw ):
    """
    Ensures:
        - Returns a SimpleNamespace snapshot with sensible defaults for the fields the
          router reads; overridable per test
    """
    base = {
        "id_hash"                   : "abc12345def",
        "question"                  : "What is 2+2?",
        "question_normalized"       : "what is 2 2",
        "question_gist"             : "addition",
        "answer"                    : "4",
        "answer_conversational"     : "It is four.",
        "runtime_stats"             : { "ms": 12 },
        "code"                      : [ "print( 4 )" ],
        "solution_summary"          : "adds two numbers",
        "solution_summary_gist"     : "addition gist",
        "synonymous_questions"      : { "what's two plus two": 99.0 },
        "synonymous_question_gists" : { "two plus two": 98.0 },
        "created_date"              : "2026-06-01T00:00:00Z",
        "user_id"                   : "uid-1",
    }
    base.update( kw )
    return SimpleNamespace( **base )


class TestGetSnapshotManager( unittest.TestCase ):
    """
    Tests for the get_snapshot_manager dependency.

    Ensures:
        - Resolves main_module.snapshot_mgr via the dual-key lupin_app.main patch
    """

    def test_returns_main_module_snapshot_mgr( self ):
        """
        Ensures:
            - The global snapshot manager from lupin_app.main is returned
        """
        sentinel = object()
        mock_main = MagicMock()
        mock_main.snapshot_mgr = sentinel
        with _patch_fastapi_main( mock_main ):
            self.assertIs( get_snapshot_manager(), sentinel )


class TestGetUsers( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the get_users endpoint.

    Ensures:
        - Success returns a paginated UserListResponse; a service error -> 500
    """

    async def test_success( self ):
        """
        Ensures:
            - list_users results are wrapped in UserListResponse with pagination metadata
        """
        with patch( "cosa.rest.routers.admin.list_users", return_value=( [ { "id": "u1" } ], 1 ) ):
            resp = await get_users( limit=100, offset=0, admin_user=ADMIN )
        self.assertEqual( resp.total, 1 )
        self.assertEqual( resp.limit, 100 )
        self.assertEqual( resp.users, [ { "id": "u1" } ] )

    async def test_exception_raises_500( self ):
        """
        Ensures:
            - A list_users failure is wrapped as 500
        """
        with patch( "cosa.rest.routers.admin.list_users", side_effect=Exception( "db down" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_users( admin_user=ADMIN )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestGetUser( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the get_user endpoint.

    Ensures:
        - Missing user -> 404; found user -> UserDetailsResponse
    """

    def _details( self ):
        return {
            "id"                 : "u1",
            "email"              : "u1@x.io",
            "roles"              : [ "user" ],
            "email_verified"     : True,
            "is_active"          : True,
            "created_at"         : "2026-06-01T00:00:00Z",
            "last_login_at"      : None,
            "audit_log_count"    : 3,
            "failed_login_count" : 0,
        }

    async def test_not_found_raises_404( self ):
        """
        Ensures:
            - get_user_details returning falsy raises 404
        """
        with patch( "cosa.rest.routers.admin.get_user_details", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_user( user_id="u1", admin_user=ADMIN )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_success( self ):
        """
        Ensures:
            - Details are returned as UserDetailsResponse
        """
        with patch( "cosa.rest.routers.admin.get_user_details", return_value=self._details() ):
            resp = await get_user( user_id="u1", admin_user=ADMIN )
        self.assertEqual( resp.id, "u1" )
        self.assertEqual( resp.audit_log_count, 3 )


class TestUpdateRoles( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the update_roles endpoint.

    Ensures:
        - Failure messages map to 404 / 400 ( cannot-remove or invalid ) / 500; success -> MessageResponse
        - The client-None branch resolves admin_ip to "unknown"
    """

    def _call( self, ret, client_host="1.2.3.4" ):
        return patch( "cosa.rest.routers.admin.update_user_roles", return_value=ret ), client_host

    async def _run( self, ret, client_host="1.2.3.4" ):
        with patch( "cosa.rest.routers.admin.update_user_roles", return_value=ret ):
            return await update_roles( user_id="u1", request_body=_ns( roles=[ "user" ] ),
                                       request=_req( client_host ), admin_user=ADMIN )

    async def test_not_found_raises_404( self ):
        """Ensures: a 'not found' message maps to 404 ( client-None arm )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "User not found", None ), client_host=None )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_cannot_remove_raises_400( self ):
        """Ensures: a 'cannot remove' message maps to 400 ( first or-operand )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "cannot remove last admin role", None ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_invalid_raises_400( self ):
        """Ensures: an 'invalid' message maps to 400 ( second or-operand )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "invalid role specified", None ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_other_raises_500( self ):
        """Ensures: an unclassified failure maps to 500 ( else arm )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "database meltdown", None ) )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success( self ):
        """Ensures: a successful update returns MessageResponse with the updated user."""
        resp = await self._run( ( True, "roles updated", { "id": "u1", "roles": [ "admin" ] } ) )
        self.assertEqual( resp.message, "roles updated" )
        self.assertEqual( resp.user[ "roles" ], [ "admin" ] )


class TestUpdateStatus( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the update_status endpoint.

    Ensures:
        - Failure messages map to 404 / 400 ( cannot-deactivate ) / 500; success -> MessageResponse
        - The client-None branch resolves admin_ip to "unknown"
    """

    async def _run( self, ret, client_host="1.2.3.4" ):
        with patch( "cosa.rest.routers.admin.toggle_user_status", return_value=ret ):
            return await update_status( user_id="u1", request_body=_ns( is_active=False ),
                                        request=_req( client_host ), admin_user=ADMIN )

    async def test_not_found_raises_404( self ):
        """Ensures: a 'not found' message maps to 404 ( client-None arm )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "User not found", None ), client_host=None )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_cannot_deactivate_raises_400( self ):
        """Ensures: a 'cannot deactivate' message maps to 400."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "cannot deactivate yourself", None ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_other_raises_500( self ):
        """Ensures: an unclassified failure maps to 500."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "boom", None ) )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success( self ):
        """Ensures: a successful toggle returns MessageResponse."""
        resp = await self._run( ( True, "status updated", { "id": "u1", "is_active": False } ) )
        self.assertEqual( resp.message, "status updated" )


class TestResetUserPassword( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the reset_user_password endpoint.

    Ensures:
        - Failure maps to 404 ( not found ) / 500; success returns the temporary password
        - The client-None branch resolves admin_ip to "unknown"
    """

    async def _run( self, ret, client_host="1.2.3.4", user_data=None ):
        with patch( "cosa.rest.routers.admin.admin_reset_password", return_value=ret ), \
             patch( "cosa.rest.user_service.get_user_by_id", return_value=user_data ):
            return await reset_user_password( user_id="u1", request_body=_ns( reason="audit" ),
                                              request=_req( client_host ), admin_user=ADMIN )

    async def test_not_found_raises_404( self ):
        """Ensures: a 'not found' message maps to 404 ( client-None arm )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "User not found", None ), client_host=None )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_other_raises_500( self ):
        """Ensures: an unclassified failure maps to 500."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "crypto failure", None ) )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success_returns_temp_password( self ):
        """Ensures: a successful reset returns the temp password and minimal user data."""
        resp = await self._run( ( True, "reset ok", "Temp!234" ),
                                user_data={ "id": "u1", "email": "u1@x.io" } )
        self.assertEqual( resp.temporary_password, "Temp!234" )
        self.assertEqual( resp.user[ "email" ], "u1@x.io" )


class TestCreateUserEndpoint( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the create_user_endpoint.

    Ensures:
        - Failure messages map to 400 ( invalid / already / duplicate / password ) or 500; success -> 201 model
        - The client-None branch resolves admin_ip to "unknown"
    """

    async def _run( self, ret, client_host="1.2.3.4" ):
        with patch( "cosa.rest.routers.admin.admin_create_user", return_value=ret ):
            return await create_user_endpoint( request_body=_ns( email="n@x.io", password="pw", roles=[ "user" ] ),
                                               request=_req( client_host ), admin_user=ADMIN )

    async def test_invalid_raises_400( self ):
        """Ensures: an 'invalid' message maps to 400 ( first or-operand; client-None arm )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "invalid email", None ), client_host=None )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_already_raises_400( self ):
        """Ensures: an 'already' message maps to 400 ( second or-operand )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "email already exists", None ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_duplicate_raises_400( self ):
        """Ensures: a 'duplicate' message maps to 400 ( third or-operand )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "duplicate account", None ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_password_raises_400( self ):
        """Ensures: a 'password' message maps to 400 ( elif arm )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "password too weak", None ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_other_raises_500( self ):
        """Ensures: an unclassified failure maps to 500 ( else arm )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "server meltdown", None ) )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success( self ):
        """Ensures: a successful create returns CreateUserResponse with the user id."""
        resp = await self._run( ( True, "created", { "id": "new-1", "email": "n@x.io" } ) )
        self.assertEqual( resp.user_id, "new-1" )
        self.assertEqual( resp.message, "created" )


class TestDeleteUserEndpoint( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the delete_user_endpoint.

    Ensures:
        - Failure maps to 404 / 400 ( cannot-delete or sole-admin ) / 500; success -> MessageResponse
        - request_body None and request_body-with-reason both handled; client-None arm
    """

    async def _run( self, ret, request_body=None, client_host="1.2.3.4" ):
        with patch( "cosa.rest.routers.admin.admin_delete_user", return_value=ret ) as mock_del:
            result = await delete_user_endpoint( user_id="u1", request=_req( client_host ),
                                                 admin_user=ADMIN, request_body=request_body )
            return result, mock_del

    async def test_not_found_raises_404( self ):
        """Ensures: a 'not found' message maps to 404 ( request_body None -> reason '' ; client-None arm )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "User not found" ), request_body=None, client_host=None )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_cannot_delete_raises_400( self ):
        """Ensures: a 'cannot delete' message maps to 400 ( first or-operand )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "cannot delete yourself" ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_sole_admin_raises_400( self ):
        """Ensures: a 'sole admin' message maps to 400 ( second or-operand )."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "cannot remove sole admin" ) )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_other_raises_500( self ):
        """Ensures: an unclassified failure maps to 500."""
        with self.assertRaises( HTTPException ) as ctx:
            await self._run( ( False, "kaboom" ) )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_success_with_reason( self ):
        """Ensures: a successful delete with a reason returns MessageResponse and forwards the reason."""
        result, mock_del = await self._run( ( True, "deleted" ), request_body=_ns( reason="cleanup" ) )
        self.assertEqual( result.message, "deleted" )
        self.assertEqual( mock_del.call_args.kwargs[ "reason" ], "cleanup" )


class TestBatchDeleteUsers( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the batch_delete_users_endpoint.

    Ensures:
        - Mixed per-user results are tallied into total_deleted / total_failed
        - reason present is forwarded; reason absent uses the default
    """

    async def test_mixed_results_with_reason( self ):
        """Ensures: a 2-user batch with one success + one failure tallies 1/1."""
        with patch( "cosa.rest.routers.admin.admin_delete_user",
                    side_effect=[ ( True, "deleted" ), ( False, "sole admin" ) ] ):
            resp = await batch_delete_users_endpoint(
                request_body=_ns( user_ids=[ "u1", "u2" ], reason="bulk cleanup" ),
                request=_req(), admin_user=ADMIN )
        self.assertEqual( resp.total_deleted, 1 )
        self.assertEqual( resp.total_failed, 1 )
        self.assertEqual( len( resp.results ), 2 )

    async def test_default_reason_client_none( self ):
        """Ensures: a single-user batch with no reason uses the default ( client-None arm )."""
        with patch( "cosa.rest.routers.admin.admin_delete_user",
                    return_value=( True, "deleted" ) ) as mock_del:
            resp = await batch_delete_users_endpoint(
                request_body=_ns( user_ids=[ "u1" ], reason=None ),
                request=_req( None ), admin_user=ADMIN )
        self.assertEqual( resp.total_deleted, 1 )
        self.assertEqual( mock_del.call_args.kwargs[ "reason" ], "Batch delete from admin UI" )


class TestSearchSnapshots( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the search_snapshots endpoint.

    Ensures:
        - Empty / whitespace q, out-of-range threshold ( lo + hi ) and limit ( lo + hi ) -> 400
        - Success builds and sorts results; the synonyms-present and synonyms-absent arms both run
        - A search failure -> 500
    """

    async def test_empty_q_raises_400( self ):
        """Ensures: an empty q raises 400 ( first or-operand )."""
        with self.assertRaises( HTTPException ) as ctx:
            await search_snapshots( q="", admin_user=ADMIN, snapshot_mgr=MagicMock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_whitespace_q_raises_400( self ):
        """Ensures: a whitespace-only q raises 400 ( second or-operand )."""
        with self.assertRaises( HTTPException ) as ctx:
            await search_snapshots( q="   ", admin_user=ADMIN, snapshot_mgr=MagicMock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_threshold_too_low_raises_400( self ):
        """Ensures: threshold < 0 raises 400."""
        with self.assertRaises( HTTPException ) as ctx:
            await search_snapshots( q="x", threshold=-1.0, admin_user=ADMIN, snapshot_mgr=MagicMock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_threshold_too_high_raises_400( self ):
        """Ensures: threshold > 100 raises 400."""
        with self.assertRaises( HTTPException ) as ctx:
            await search_snapshots( q="x", threshold=101.0, admin_user=ADMIN, snapshot_mgr=MagicMock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_limit_too_low_raises_400( self ):
        """Ensures: limit < 1 raises 400."""
        with self.assertRaises( HTTPException ) as ctx:
            await search_snapshots( q="x", limit=0, admin_user=ADMIN, snapshot_mgr=MagicMock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_limit_too_high_raises_400( self ):
        """Ensures: limit > 100 raises 400."""
        with self.assertRaises( HTTPException ) as ctx:
            await search_snapshots( q="x", limit=101, admin_user=ADMIN, snapshot_mgr=MagicMock() )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_success_sorts_and_handles_synonyms( self ):
        """
        Ensures:
            - Results are built ( one with synonyms, one without ) and sorted descending by score
        """
        snap_with_syn = _snap( id_hash="aaa", synonymous_questions={ "syn one": 90.0, "syn two": 80.0 } )
        snap_no_syn   = _snap( id_hash="bbb", synonymous_questions={} )
        mgr = MagicMock()
        mgr.get_snapshots_by_question.return_value = [ ( 70.0, snap_with_syn ), ( 95.0, snap_no_syn ) ]
        with patch.object( admin._config_mgr, "get", return_value=False ):
            resp = await search_snapshots( q="add", threshold=80.0, limit=50, admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( resp.total, 2 )
        self.assertEqual( resp.results[ 0 ].score, 95.0 )    # sorted descending
        self.assertEqual( resp.query, "add" )

    async def test_search_failure_raises_500( self ):
        """Ensures: a search error is wrapped as 500."""
        mgr = MagicMock()
        mgr.get_snapshots_by_question.side_effect = Exception( "index error" )
        with patch.object( admin._config_mgr, "get", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                await search_snapshots( q="add", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestGetSnapshotDetails( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the get_snapshot_details endpoint.

    Ensures:
        - Missing snapshot -> 404; found -> full SnapshotDetailResponse; generic error -> 500
    """

    async def test_not_found_raises_404( self ):
        """Ensures: a missing snapshot raises 404 ( re-raised through except HTTPException )."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = None
        with self.assertRaises( HTTPException ) as ctx:
            await get_snapshot_details( id_hash="x", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_success( self ):
        """Ensures: a found snapshot returns the full detail model."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap()
        resp = await get_snapshot_details( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( resp.id_hash, "abc12345def" )
        self.assertEqual( resp.answer, "4" )
        self.assertEqual( resp.synonymous_questions, { "what's two plus two": 99.0 } )

    async def test_generic_exception_raises_500( self ):
        """Ensures: a non-HTTP error is wrapped as 500."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.side_effect = Exception( "boom" )
        with self.assertRaises( HTTPException ) as ctx:
            await get_snapshot_details( id_hash="x", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestDeleteSnapshot( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the delete_snapshot endpoint.

    Ensures:
        - Missing -> 404; delete True -> success message; delete False -> 500; generic error -> 500
    """

    async def test_not_found_raises_404( self ):
        """Ensures: a missing snapshot raises 404."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = None
        with self.assertRaises( HTTPException ) as ctx:
            await delete_snapshot( id_hash="x", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_delete_success( self ):
        """Ensures: a successful physical delete returns the success message."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap()
        mgr.delete_snapshot.return_value = True
        resp = await delete_snapshot( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertIn( "deleted successfully", resp.message )

    async def test_delete_returns_false_raises_500( self ):
        """Ensures: a delete returning False raises 500."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap()
        mgr.delete_snapshot.return_value = False
        with self.assertRaises( HTTPException ) as ctx:
            await delete_snapshot( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 500 )

    async def test_generic_exception_raises_500( self ):
        """Ensures: a non-HTTP error during delete is wrapped as 500."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.side_effect = Exception( "boom" )
        with self.assertRaises( HTTPException ) as ctx:
            await delete_snapshot( id_hash="x", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestGetSnapshotPreview( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the get_snapshot_preview endpoint.

    Ensures:
        - Missing -> 404
        - list-code + long-code ( "..." ) + present gist; non-list-code + empty + gist fallback; generic -> 500
    """

    async def test_not_found_raises_404( self ):
        """Ensures: a missing snapshot raises 404."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = None
        with self.assertRaises( HTTPException ) as ctx:
            await get_snapshot_preview( id_hash="x", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_list_code_long_uses_gist( self ):
        """
        Ensures:
            - List code longer than 300 chars is truncated with "..." and the present gist is used
        """
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap( code=[ "L" * 400 ], solution_summary_gist="concise gist" )
        resp = await get_snapshot_preview( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertTrue( resp.code_preview.endswith( "..." ) )
        self.assertEqual( resp.solution_summary_gist, "concise gist" )

    async def test_non_list_code_empty_falls_back_to_summary( self ):
        """
        Ensures:
            - Non-list code yields an empty preview ( no "..." ) and an empty gist falls back to solution_summary
        """
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap( code="not-a-list", solution_summary_gist="",
                                                     solution_summary="verbose explanation" )
        resp = await get_snapshot_preview( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( resp.code_preview, "" )
        self.assertEqual( resp.solution_summary_gist, "verbose explanation" )

    async def test_generic_exception_raises_500( self ):
        """Ensures: a non-HTTP error is wrapped as 500."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.side_effect = Exception( "boom" )
        with self.assertRaises( HTTPException ) as ctx:
            await get_snapshot_preview( id_hash="x", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestGetSimilarSnapshots( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the get_similar_snapshots endpoint ( the heaviest ).

    Ensures:
        - Source-not-found -> 404
        - Success with debug True ( all debug-print arms + preview branches ) and debug False
        - Code- and explanation-similarity inner exceptions are swallowed ( debug True + False arms )
        - A generic outer error -> 500
    """

    def _matches( self ):
        """
        Ensures:
            - Returns a [(score, snap)] list mixing long/short question, long/empty code, long/empty summary
              to exercise every preview branch in the result-building loop
        """
        long_snap  = _snap( id_hash="long", question="Q" * 150, code=[ "C" * 500 ],
                            solution_summary="S" * 250, solution_summary_gist="g1" )
        short_snap = _snap( id_hash="short", question="short q", code=[],
                            solution_summary="", solution_summary_gist="" )
        return [ ( 88.0, long_snap ), ( 91.0, short_snap ) ]

    async def test_source_not_found_raises_404( self ):
        """Ensures: a missing source snapshot raises 404 ( debug False )."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = None
        with patch.object( admin._config_mgr, "get", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_similar_snapshots( id_hash="x", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_success_debug_true( self ):
        """Ensures: with debug True, both result sets build and all debug-print arms execute."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap()
        mgr.get_snapshots_by_code_similarity.return_value = self._matches()
        mgr.get_snapshots_by_solution_similarity.return_value = self._matches()
        with patch.object( admin._config_mgr, "get", return_value=True ):
            resp = await get_similar_snapshots( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( resp.total_code_matches, 2 )
        self.assertEqual( resp.total_explanation_matches, 2 )

    async def test_success_debug_false( self ):
        """Ensures: with debug False the debug-print arms are skipped; empty matches exit the loops."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap()
        mgr.get_snapshots_by_code_similarity.return_value = []
        mgr.get_snapshots_by_solution_similarity.return_value = []
        with patch.object( admin._config_mgr, "get", return_value=False ):
            resp = await get_similar_snapshots( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( resp.total_code_matches, 0 )

    async def test_code_similarity_exception_debug_true( self ):
        """Ensures: a code-similarity failure is swallowed ( debug-True print arm )."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap()
        mgr.get_snapshots_by_code_similarity.side_effect = Exception( "code search boom" )
        mgr.get_snapshots_by_solution_similarity.return_value = []
        with patch.object( admin._config_mgr, "get", return_value=True ):
            resp = await get_similar_snapshots( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( resp.total_code_matches, 0 )

    async def test_code_similarity_exception_debug_false( self ):
        """Ensures: a code-similarity failure is swallowed ( debug-False arm )."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap()
        mgr.get_snapshots_by_code_similarity.side_effect = Exception( "code search boom" )
        mgr.get_snapshots_by_solution_similarity.return_value = []
        with patch.object( admin._config_mgr, "get", return_value=False ):
            resp = await get_similar_snapshots( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( resp.total_code_matches, 0 )

    async def test_explanation_similarity_exception_debug_true( self ):
        """Ensures: an explanation-similarity failure is swallowed ( debug-True print arm )."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap()
        mgr.get_snapshots_by_code_similarity.return_value = []
        mgr.get_snapshots_by_solution_similarity.side_effect = Exception( "expl search boom" )
        with patch.object( admin._config_mgr, "get", return_value=True ):
            resp = await get_similar_snapshots( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( resp.total_explanation_matches, 0 )

    async def test_explanation_similarity_exception_debug_false( self ):
        """Ensures: an explanation-similarity failure is swallowed ( debug-False arm )."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.return_value = _snap()
        mgr.get_snapshots_by_code_similarity.return_value = []
        mgr.get_snapshots_by_solution_similarity.side_effect = Exception( "expl search boom" )
        with patch.object( admin._config_mgr, "get", return_value=False ):
            resp = await get_similar_snapshots( id_hash="abc12345def", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( resp.total_explanation_matches, 0 )

    async def test_generic_exception_raises_500( self ):
        """Ensures: a non-HTTP outer error is wrapped as 500."""
        mgr = MagicMock()
        mgr.get_snapshot_by_id.side_effect = Exception( "boom" )
        with patch.object( admin._config_mgr, "get", return_value=False ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_similar_snapshots( id_hash="x", admin_user=ADMIN, snapshot_mgr=mgr )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestRefreshSourceAllowed( unittest.TestCase ):
    """
    Tests for the _refresh_source_allowed guard.

    Ensures:
        - Wrong env -> (False, reason); disabled config -> (False, reason); both set -> (True, env)
    """

    def test_wrong_env_disallowed( self ):
        """Ensures: a non-test env returns (False, reason)."""
        with patch.dict( os.environ, { "LUPIN_ENV": "prod" }, clear=False ):
            allowed, detail = _refresh_source_allowed()
        self.assertFalse( allowed )
        self.assertIn( "must be test/testing", detail )

    def test_config_disabled_disallowed( self ):
        """Ensures: a test env with the config disabled returns (False, reason)."""
        with patch.dict( os.environ, { "LUPIN_ENV": "test" }, clear=False ), \
             patch.object( admin._config_mgr, "get", return_value=False ):
            allowed, detail = _refresh_source_allowed()
        self.assertFalse( allowed )
        self.assertIn( "is false", detail )

    def test_enabled_allowed( self ):
        """Ensures: a testing env with the config enabled returns (True, env)."""
        with patch.dict( os.environ, { "LUPIN_ENV": "testing" }, clear=False ), \
             patch.object( admin._config_mgr, "get", return_value=True ):
            allowed, detail = _refresh_source_allowed()
        self.assertTrue( allowed )
        self.assertEqual( detail, "testing" )


class TestReexecProcess( unittest.TestCase ):
    """
    Tests for _reexec_process.

    Ensures:
        - os.execv is invoked with the python -m lupin_app.main argv ( never actually re-execs )
    """

    def test_invokes_execv( self ):
        """Ensures: os.execv is called once with the expected interpreter + module argv."""
        with patch( "os.execv" ) as mock_execv:
            _reexec_process()
        mock_execv.assert_called_once()
        args = mock_execv.call_args.args
        self.assertEqual( args[ 1 ], [ sys.executable, "-m", "lupin_app.main" ] )


class TestRefreshSource( unittest.IsolatedAsyncioTestCase ):
    """
    Tests for the refresh_source endpoint.

    Ensures:
        - Disallowed -> 403; allowed -> 202 model + a scheduled delayed-reexec task that re-execs
    """

    async def test_disallowed_raises_403( self ):
        """Ensures: when the guard denies, 403 is raised."""
        with patch( "cosa.rest.routers.admin._refresh_source_allowed", return_value=( False, "nope" ) ):
            with self.assertRaises( HTTPException ) as ctx:
                await refresh_source( background_tasks=MagicMock(), admin_user=ADMIN )
        self.assertEqual( ctx.exception.status_code, 403 )

    async def test_allowed_schedules_reexec( self ):
        """
        Ensures:
            - When allowed, a RefreshSourceResponse is returned and the scheduled task re-execs
        """
        bt = MagicMock()
        with patch( "cosa.rest.routers.admin._refresh_source_allowed", return_value=( True, "test" ) ), \
             patch.dict( os.environ, { "LUPIN_ENV": "test" }, clear=False ):
            resp = await refresh_source( background_tasks=bt, admin_user=ADMIN )
        self.assertEqual( resp.status, "refreshing" )
        self.assertEqual( resp.env, "test" )
        bt.add_task.assert_called_once()

        # Exercise the scheduled closure body ( sleep mocked, re-exec mocked )
        task = bt.add_task.call_args.args[ 0 ]
        with patch( "cosa.rest.routers.admin._reexec_process" ) as mock_reexec, \
             patch( "asyncio.sleep", new=AsyncMock() ):
            await task()
        mock_reexec.assert_called_once()


if __name__ == "__main__":
    unittest.main()
