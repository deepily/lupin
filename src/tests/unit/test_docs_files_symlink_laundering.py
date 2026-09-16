"""
Unit tests for row 9ab0bddb: the doc viewer judges a path where it LANDS, not as typed.

`resolve_in_scope` used `os.path.normpath`, which never follows a symlink. A link with
an innocent name planted inside a scope root therefore passed every guard in
`get_docs_file` while `open()` read the file it pointed at. Krishna's demonstration:
`sc/notes.json -> .claude/settings.local.json` was ADMITTED and its contents served.

Every symlink here is built under pytest's `tmp_path`, never in the repo. The endpoint
coroutine is invoked directly with `_get_scope_registry` monkeypatched, the same way
`test_docs_files_bare_scope.py` does it.

Tier: :7999-eligible unit (no server, no persistent state, milliseconds).
"""

import asyncio
import os

import pytest
from fastapi import HTTPException

import cosa.rest.routers.docs_files as docs_files
from cosa.rest.routers._scope_registry import ScopeConfig, resolve_in_scope


SECRET = '{"SECRET":"pwned"}'


@pytest.fixture
def scope_root( tmp_path ):
    """
    A scope root holding a credentials file, an ordinary note, and three symlinks.

    Ensures:
        - root/.claude/settings.local.json holds SECRET (floor-blocked by name)
        - root/src/notes.md is an ordinary in-scope file
        - root/private/plan.md sits outside the `src/` whitelist
        - root/src/notes.json   -> .claude/settings.local.json  (same-scope laundering)
        - root/src/plan.md      -> private/plan.md               (whitelist laundering)
        - root/src/outside.md   -> a file OUTSIDE the root        (escape)
        - root/src/alias.md     -> src/notes.md                   (benign in-scope link)
    """
    root = tmp_path / "scope"
    ( root / ".claude" ).mkdir( parents=True )
    ( root / "src" ).mkdir()
    ( root / "private" ).mkdir()

    ( root / ".claude" / "settings.local.json" ).write_text( SECRET )
    ( root / "src" / "notes.md" ).write_text( "# ordinary note\n" )
    ( root / "private" / "plan.md" ).write_text( "# private plan\n" )
    ( tmp_path / "elsewhere.md" ).write_text( "# outside the root\n" )

    os.symlink( root / ".claude" / "settings.local.json", root / "src" / "notes.json" )
    os.symlink( root / "private" / "plan.md", root / "src" / "plan.md" )
    os.symlink( tmp_path / "elsewhere.md", root / "src" / "outside.md" )
    os.symlink( root / "src" / "notes.md", root / "src" / "alias.md" )
    return root


@pytest.fixture
def fake_registry( scope_root, monkeypatch ):
    """Patch the registry to one scope whose whitelist is `src/` only."""
    registry = {
        "sc": ScopeConfig( name="sc", root=str( scope_root ), allowed_prefixes=( "src/", ) )
    }
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: registry )
    return registry


def _get( path ):
    """Invoke the endpoint coroutine directly; return the response object."""
    return asyncio.run(
        docs_files.get_docs_file( path=path, scope=None, current_user={ "email": "test@lupin" } )
    )


def _refused( path ):
    """Return the HTTPException the door raises for `path`; fail if it serves."""
    with pytest.raises( HTTPException ) as exc_info:
        _get( path )
    return exc_info.value


class TestLaunderingRefused:

    def test_symlink_to_blocklisted_file_in_same_scope_is_refused( self, fake_registry ):
        """The row's own demonstration: typed path clean, landed path is a credential file."""
        exc = _refused( "sc/src/notes.json" )
        assert exc.status_code == 400
        assert "blocklist" in exc.detail.lower()
        assert "pwned" not in exc.detail

    def test_symlink_to_file_outside_whitelist_is_refused( self, fake_registry ):
        exc = _refused( "sc/src/plan.md" )
        assert exc.status_code == 400
        assert "whitelist" in exc.detail.lower()

    def test_symlink_escaping_the_root_is_refused( self, fake_registry ):
        exc = _refused( "sc/src/outside.md" )
        assert exc.status_code == 400
        assert "escapes scope root" in exc.detail.lower()


class TestPositiveControls:
    """Without these the tests above prove only that the door can say no."""

    def test_ordinary_in_scope_file_is_served( self, fake_registry ):
        response = _get( "sc/src/notes.md" )
        assert response.status_code == 200
        assert "ordinary note" in response.body.decode()

    def test_symlink_landing_on_an_allowed_file_is_served( self, fake_registry ):
        response = _get( "sc/src/alias.md" )
        assert response.status_code == 200
        assert "ordinary note" in response.body.decode()

    def test_scope_root_listing_still_served( self, fake_registry ):
        response = _get( "sc/" )
        assert response.status_code == 200


class TestResolveInScopeFollowsSymlinks:

    def test_returns_the_landed_path_not_the_typed_one( self, scope_root ):
        cfg = ScopeConfig( name="sc", root=str( scope_root ), allowed_prefixes=() )
        landed = resolve_in_scope( cfg, "src/notes.json" )
        assert landed == os.path.realpath( scope_root / ".claude" / "settings.local.json" )

    def test_symlink_escaping_the_root_raises( self, scope_root ):
        cfg = ScopeConfig( name="sc", root=str( scope_root ), allowed_prefixes=() )
        with pytest.raises( ValueError ):
            resolve_in_scope( cfg, "src/outside.md" )
