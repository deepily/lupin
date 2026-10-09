#!/usr/bin/env python3
"""
`task_query( blocked_by_persona=... )`: what waits on me, as one scoped read.

The filter travels one path: the MCP tool, `task_query_impl`, `GET /api/tasks`, five repository
methods and one shared `_apply_scalar_filters`. Three things can go wrong, and each has a test:

    1. the clause is not an exact JSONB containment of {kind: persona, id: <name>}
    2. a caller of the shared helper, or a repo call in the route, leaves the argument out.
       One page, count or breakdown then ignores the filter and disagrees with the rest.
       The default is None, so nothing fails.
    3. the guard that rejects bare full-store pulls treats the new filter as no filter at all

The call-site guard reads syntax trees and carries a negative control.
The same walk over a copy with one argument removed must name the call it lost.
The real-database proof is `src/tests/integration/test_task_query_blocked_by_persona_realdb.py`.

Venue: :7999-eligible. Query objects are compiled, never executed; the router runs over a MagicMock repository.
"""
import ast
import inspect
import os
import sys
import textwrap
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_store_rules as rules
from cosa.rest.db.repositories import task_repository as repository_module
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks

FILTER = "blocked_by_persona"

REPO_METHODS = ( "query_tasks", "count_tasks", "count_tasks_by_status", "count_tasks_by_priority", "count_tasks_by_project" )


def _compiled( **kwargs ):
    query = TaskRepository._apply_scalar_filters(
        Session().query( TaskItem ), None, None, None, None, None, None, None, None, None, **kwargs
    )
    compiled = query.statement.compile( dialect = postgresql.dialect() )
    return str( compiled ), list( compiled.params.values() )


def _calls_missing_the_argument( source, scope, matches ):
    """Return how many calls match, and the lines of those that do not pass the filter."""
    tree = ast.parse( source )
    if scope is not None:
        tree = next( node for node in ast.walk( tree ) if isinstance( node, ast.FunctionDef ) and node.name == scope )
    found = [ node for node in ast.walk( tree ) if isinstance( node, ast.Call ) and matches( node ) ]
    return len( found ), [ node.lineno for node in found if FILTER not in { kw.arg for kw in node.keywords } ]


def _is_helper_call( node ):
    return isinstance( node.func, ast.Attribute ) and node.func.attr == "_apply_scalar_filters"


def _is_repo_call( node ):
    return ( isinstance( node.func, ast.Attribute ) and node.func.attr in REPO_METHODS
             and isinstance( node.func.value, ast.Name ) and node.func.value.id == "repo" )


# ── 1. the clause ─────────────────────────────────────────────────────────────

def test_the_clause_is_a_jsonb_containment_of_the_exact_persona_ref():
    sql, params = _compiled( blocked_by_persona = "tiffany" )
    assert "blocked_by @>" in sql
    assert [ { "kind": "persona", "id": "tiffany" } ] in params


def test_NEGATIVE_CONTROL_without_the_filter_no_containment_is_added():
    assert "@>" not in _compiled()[ 0 ]


# ── 2. every caller passes it ─────────────────────────────────────────────────

def test_every_repository_method_passes_the_filter_to_the_shared_helper():
    source = inspect.getsource( repository_module )
    total, missing = _calls_missing_the_argument( source, None, _is_helper_call )
    assert total == 5, f"expected five callers of _apply_scalar_filters, found {total}"
    assert not missing, f"callers that drop {FILTER}: lines {missing}"


def test_every_repo_call_in_the_query_route_passes_the_filter():
    total, missing = _calls_missing_the_argument( inspect.getsource( tasks ), "query_tasks", _is_repo_call )
    assert total == 7, f"expected seven repo calls in the query route, found {total}"
    assert not missing, f"repo calls that drop {FILTER}: lines {missing}"


def test_NEGATIVE_CONTROL_the_walk_names_a_call_that_lost_the_argument():
    source  = inspect.getsource( tasks )
    lines   = source.splitlines()
    mutated = "\n".join( line for line in lines if FILTER not in line )
    total, missing = _calls_missing_the_argument( mutated, "query_tasks", _is_repo_call )
    assert total == 7 and len( missing ) == 7


def test_the_repository_methods_accept_the_filter():
    for name in REPO_METHODS:
        assert FILTER in inspect.signature( getattr( TaskRepository, name ) ).parameters, name


# ── 3. the unscoped guard ─────────────────────────────────────────────────────

def test_the_filter_alone_is_a_scoping_filter():
    assert FILTER in rules.SCOPING_FILTERS
    assert rules.is_unscoped( { FILTER: "tiffany" } ) is False
    assert rules.is_unscoped( { FILTER: None } ) is True


# ── the route, over a mocked repository ───────────────────────────────────────

@pytest.fixture
def repo( monkeypatch ):
    fake = MagicMock()
    fake.query_tasks.return_value                  = [ ]
    fake.count_tasks.return_value                  = 0
    fake.count_tasks_by_status.return_value        = { }
    fake.count_tasks_by_priority.return_value      = { }
    fake.count_tasks_by_project.return_value       = { }
    fake.statuses_for_ids.return_value             = { }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


def _client():
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: None
    return TestClient( app )


def test_the_page_route_forwards_the_canonical_persona_to_its_four_repo_calls( repo ):
    r = _client().get( "/api/tasks", params = { FILTER: "Tiffany", "project": "lupin" } )
    assert r.status_code == 200, r.text
    calls = [ c for c in repo.method_calls if c[ 0 ] in REPO_METHODS ]
    assert { c[ 0 ] for c in calls } == { "query_tasks", "count_tasks", "count_tasks_by_project" }
    assert len( calls ) == 4, "the page, the total, the held-rows count and the by-project count"
    assert all( c.kwargs[ FILTER ] == "tiffany" for c in calls )


def test_the_count_route_forwards_it_to_all_three_counts( repo ):
    r = _client().get( "/api/tasks", params = { FILTER: "tiffany", "count_only": "true" } )
    assert r.status_code == 200, r.text
    for name in ( "count_tasks", "count_tasks_by_status", "count_tasks_by_priority" ):
        assert getattr( repo, name ).call_args.kwargs[ FILTER ] == "tiffany", name


def test_without_the_parameter_every_call_carries_none( repo ):
    r = _client().get( "/api/tasks", params = { "owner_persona": "sam" } )
    assert r.status_code == 200, r.text
    assert all( c.kwargs[ FILTER ] is None for c in repo.method_calls if c[ 0 ] in REPO_METHODS )
    assert repo.query_tasks.called
