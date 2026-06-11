"""
Unit tests for quote-aware pytest_args parsing (2026-06-11 fix).

Pre-fix, `agentic_job_factory` word-split pytest_args with a plain
`str.split()`, so a quoted `-k "a or b"` expression shattered into
['-k', '"a', 'or', 'b"'] — pytest read the bare `or` as a file argument and
exited 4: a silent zero-test run that LOOKED submitted. Found independently
by two sessions on 2026-06-11.

Post-fix: `shlex.split` honors quoting; unbalanced quotes raise a loud
ValueError at submit time, which `/api/test-suite/submit` maps to HTTP 400.

Tier: :7999-eligible unit (no server, no persistent state).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.agentic_job_factory import create_agentic_job


_COMMAND = "agent router go to test suite"


def _make_job( pytest_args_raw ):
    """Run the factory's test-suite branch with the given raw pytest_args."""
    args_dict = { "test_types": "integration", "dry_run": True }
    if pytest_args_raw is not None:
        args_dict[ "pytest_args" ] = pytest_args_raw
    return create_agentic_job(
        command    = _COMMAND,
        args_dict  = args_dict,
        user_id    = "uid-1",
        user_email = "test@lupin",
        session_id = "sess-1",
    )


class TestPytestArgsQuoteAwareSplit:
    """Factory-level parsing of the pytest_args string."""

    def test_quoted_k_expression_survives_as_one_value( self ):
        """THE regression: -k "a or b" must reach pytest as ONE -k value."""
        job = _make_job( '-k "popover_open or popover_borrowed"' )
        assert job.pytest_args == [ "-k", "popover_open or popover_borrowed" ]

    def test_plain_space_separated_unchanged( self ):
        """Backward-compat: unquoted strings split exactly as before."""
        job = _make_job( "-v -k test_auth" )
        assert job.pytest_args == [ "-v", "-k", "test_auth" ]

    def test_mixed_quoted_and_plain_tokens( self ):
        job = _make_job( '-x -k "a and not b" --maxfail=2' )
        assert job.pytest_args == [ "-x", "-k", "a and not b", "--maxfail=2" ]

    def test_single_quotes_also_honored( self ):
        job = _make_job( "-k 'auth or visual'" )
        assert job.pytest_args == [ "-k", "auth or visual" ]

    def test_list_passthrough_preserved( self ):
        job = _make_job( [ "-v", "-k", "a or b" ] )
        assert job.pytest_args == [ "-v", "-k", "a or b" ]

    def test_semantic_none_yields_empty( self ):
        for raw in ( "none", "default", "skip", "" ):
            assert _make_job( raw ).pytest_args == []

    def test_absent_key_yields_empty( self ):
        assert _make_job( None ).pytest_args == []

    def test_unbalanced_quote_raises_loud_valueerror( self ):
        """Malformed quoting must fail at submit — the silent alternative is
        exactly the zero-test run this fix removes."""
        with pytest.raises( ValueError ) as exc_info:
            _make_job( '-k "popover_open or' )
        assert "pytest_args" in str( exc_info.value )


class TestSubmitEndpointMapsValueErrorTo400:
    """Router-level: the loud ValueError surfaces as HTTP 400, not 500."""

    @pytest.fixture
    def client( self ):
        from cosa.rest.auth import get_current_user
        from cosa.rest.routers import test_suite as test_suite_router

        app = FastAPI()
        app.include_router( test_suite_router.router )
        app.dependency_overrides[ get_current_user ] = lambda: { "uid": "uid-1", "email": "test@lupin" }
        app.dependency_overrides[ test_suite_router.get_todo_queue ] = lambda: object()
        return TestClient( app )

    def test_unbalanced_quotes_return_400_with_context( self, client ):
        response = client.post(
            "/api/test-suite/submit",
            json={ "test_types": "integration", "dry_run": True, "pytest_args": '-k "auth or' },
        )
        assert response.status_code == 400
        assert "pytest_args" in response.json()[ "detail" ]
