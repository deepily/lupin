"""
Unit tests for the bare-external-scope no-slash fix in `get_docs_file`
(2026-06-11 robustness item).

Pre-fix, `?path=claude-plans` (no trailing slash) → 400 "Missing project
prefix" while `?path=claude-plans/` listed the scope root and the built-in
`io` scope listed at its bare name. Post-fix, a bare path naming a REGISTERED
project lists that project's root; unregistered bare names keep the 400.

The endpoint coroutine is invoked directly with `_get_scope_registry`
monkeypatched to a fake registry over a tmp directory — no live server, no
ConfigurationManager.

Tier: :7999-eligible unit (no server, no persistent state, milliseconds).
"""

import asyncio
import json

import pytest
from fastapi import HTTPException

import cosa.rest.routers.docs_files as docs_files
from cosa.rest.routers._scope_registry import ScopeConfig


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def scope_root( tmp_path ):
    """A fake claude-plans scope root holding one markdown plan."""
    ( tmp_path / "2026.06.11-sample-plan.md" ).write_text( "# sample plan\n" )
    return tmp_path


@pytest.fixture
def fake_registry( scope_root, monkeypatch ):
    """Patch the process-lifetime registry to a single wildcard external scope."""
    registry = {
        "claude-plans": ScopeConfig(
            name             = "claude-plans",
            root             = str( scope_root ),
            allowed_prefixes = (),
        )
    }
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: registry )
    return registry


def _get( path ):
    """Invoke the endpoint coroutine directly; return the response object."""
    return asyncio.run(
        docs_files.get_docs_file( path=path, scope=None, current_user={ "email": "test@lupin" } )
    )


def _listing( response ):
    return json.loads( response.body )


# ═════════════════════════════════════════════════════════════════════════════
# Test cases
# ═════════════════════════════════════════════════════════════════════════════

class TestBareRegisteredScope:
    """Bare registered-project name lists the scope root."""

    def test_bare_registered_project_lists_root( self, fake_registry ):
        response = _get( "claude-plans" )
        listing  = _listing( response )
        assert listing[ "kind" ]  == "directory"
        assert listing[ "scope" ] == "claude-plans"
        names = [ e[ "name" ] for e in listing[ "entries" ] ]
        assert "2026.06.11-sample-plan.md" in names

    def test_bare_name_parity_with_trailing_slash( self, fake_registry ):
        """`?path=claude-plans` and `?path=claude-plans/` return the SAME listing."""
        assert _listing( _get( "claude-plans" ) ) == _listing( _get( "claude-plans/" ) )


class TestBareNameGuardsPreserved:
    """Everything that 400'd before the fix still 400s."""

    def test_bare_unregistered_name_still_400s( self, fake_registry ):
        with pytest.raises( HTTPException ) as exc_info:
            _get( "anything" )
        assert exc_info.value.status_code == 400
        assert "project prefix" in exc_info.value.detail.lower()

    def test_bare_retired_docs_scope_400s( self, fake_registry ):
        """`docs` is retired and never registered — bare form stays 400."""
        with pytest.raises( HTTPException ) as exc_info:
            _get( "docs" )
        assert exc_info.value.status_code == 400

    def test_empty_path_still_400s( self, fake_registry ):
        with pytest.raises( HTTPException ) as exc_info:
            _get( "" )
        assert exc_info.value.status_code == 400
        assert "empty path" in exc_info.value.detail.lower()

    def test_bare_secrets_name_blocked_before_registry_lookup( self, fake_registry ):
        """The universal floor fires BEFORE the bare-name registry check."""
        with pytest.raises( HTTPException ) as exc_info:
            _get( ".env" )
        assert exc_info.value.status_code == 400
        assert "blocklist" in exc_info.value.detail.lower()

    def test_unknown_project_with_slash_still_400s( self, fake_registry ):
        with pytest.raises( HTTPException ) as exc_info:
            _get( "this-project-does-not-exist/foo.md" )
        assert exc_info.value.status_code == 400
        assert "unknown project" in exc_info.value.detail.lower()
