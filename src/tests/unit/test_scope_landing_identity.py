"""
Unit tests for the shared "where does it LAND" predicate — rows cc39cee6 and the doc-viewer false rejection.

In the container the repo is mounted at TWO prefixes, `/var/lupin` and `/var/external-projects/lupin`,
one host directory. Eleven `io/test-suite/artifacts/*-latest.log` links point at the first spelling, so
a prefix test against the second refused eleven live in-repo files (measured in `lupin-rest-dev`,
2026-09-30). The predicate now judges DIRECTORY IDENTITY (st_dev + st_ino) against the scope's own root.

An unprivileged test cannot build a real bind mount, so `_scope_registry._stat` is the seam: the tests
give one real directory the identity of the scope root, which is exactly what a bind mount does.
Everything else — links, files, the endpoint coroutine — is real, under pytest's `tmp_path`.

Tier: :7999-eligible unit (no server, no persistent state, milliseconds).
"""
import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import cosa.rest.routers._scope_registry as scope_registry
import cosa.rest.routers.docs_files as docs_files
import cosa.rest.task_store_rules as rules
from cosa.rest.routers._scope_registry import (
    ScopeConfig, landed_relative_path, landed_within_roots, resolve_in_scope,
)

ARTIFACT_LINKS = [
    "integration", "e2e-ui-half-a", "e2e-ui-half-b", "e2e-ui", "coverage-gate", "websocket",
    "unit", "smoke", "v2_eval", "pytest-direct", "typescript",
]   # the eleven live -latest.log links measured in the container


@pytest.fixture
def layout( tmp_path, monkeypatch ):
    """
    ext/lupin   = the scope root;  var/lupin = a SECOND SPELLING of it (same identity, via the stat seam)
    var/lupin-evil = a sibling that shares a name prefix with the mirror and an identity with nothing.
    """
    root   = tmp_path / "ext" / "lupin"
    mirror = tmp_path / "var" / "lupin"
    evil   = tmp_path / "var" / "lupin-evil"
    ( root / "io" / "test-suite" / "artifacts" ).mkdir( parents=True )
    ( mirror / "io" / "test-suite" / "artifacts" ).mkdir( parents=True )
    ( evil / "io" ).mkdir( parents=True )
    ( root / "src" ).mkdir()
    ( root / "src" / "note.md" ).write_text( "# a note\n" )
    ( mirror / ".env" ).write_text( "SECRET=1\n" )
    ( root / ".env" ).write_text( "SECRET=2\n" )                                 # a credential file that EXISTS in scope
    ( evil / "io" / "x.log" ).write_text( "not yours\n" )

    for name in ARTIFACT_LINKS:
        target = mirror / "io" / "test-suite" / "artifacts" / f"{name}-20260930.log"
        target.write_text( f"{name} log\n" )
        os.symlink( target, root / "io" / "test-suite" / "artifacts" / f"{name}-latest.log" )

    # The viewer serves no `.log` at all (MEDIA_TYPES), so the door is exercised with the same shape
    # under a servable extension; the receipt validator below uses the real `.log` names.
    for name in ARTIFACT_LINKS:
        target = mirror / "io" / "test-suite" / "artifacts" / f"{name}-20260930.md"
        target.write_text( f"{name} log\n" )
        os.symlink( target, root / "io" / "test-suite" / "artifacts" / f"{name}-latest.md" )

    os.symlink( "/etc/passwd", root / "src" / "etc.md" )                       # a link to /etc
    os.symlink( mirror / ".env", root / "src" / "env.md" )                      # blocklisted target via the alias
    os.symlink( evil / "io" / "x.log", root / "io" / "evil.log" )               # the sibling case
    os.symlink( tmp_path / "gone-20260727.log", root / "io" / "dangling.log" )  # target no longer exists

    real_stat = os.stat
    def aliasing_stat( path, *args, **kwargs ):
        return real_stat( root if os.fspath( path ) == str( mirror ) else path, *args, **kwargs )
    monkeypatch.setattr( scope_registry, "_stat", aliasing_stat )
    return SimpleNamespace( root=root, mirror=mirror, evil=evil, tmp=tmp_path )


@pytest.fixture
def served( layout, monkeypatch ):
    registry = { "lupin": ScopeConfig( name="lupin", root=str( layout.root ), allowed_prefixes=() ) }
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: registry )
    return registry


def _get( path ):
    return asyncio.run( docs_files.get_docs_file( path=path, scope=None, current_user={ "email": "t@lupin" } ) )


def _refused( path ):
    with pytest.raises( HTTPException ) as caught:
        _get( path )
    return caught.value


class TestTheDoorServesLinksIntoASecondSpellingOfItsOwnRoot:

    @pytest.mark.parametrize( "name", ARTIFACT_LINKS )
    def test_each_of_the_eleven_latest_links_serves( self, served, name ):
        response = _get( f"lupin/io/test-suite/artifacts/{name}-latest.md" )
        assert response.status_code == 200
        assert f"{name} log" in response.body.decode()

    def test_a_link_to_etc_is_refused( self, served ):
        assert _refused( "lupin/src/etc.md" ).status_code == 400

    def test_the_sibling_that_shares_a_name_prefix_is_refused( self, served ):
        exc = _refused( "lupin/io/evil.log" )
        assert exc.status_code == 400 and "escapes" in exc.detail.lower()

    def test_the_floor_blocklist_is_applied_to_the_LANDED_path( self, served ):
        # typed `src/env.md` is innocent; it lands on `<alias>/.env`, which the floor blocks
        exc = _refused( "lupin/src/env.md" )
        assert exc.status_code == 400 and "blocklist" in exc.detail.lower()

    def test_a_dangling_outside_link_answers_exactly_what_an_existing_outside_link_answers( self, served ):
        # row 9b80ef75 (a): a different answer lets whoever planted a link probe whether an outside path exists
        dangling = _refused( "lupin/io/dangling.log" )
        existing = _refused( "lupin/src/etc.md" )
        assert dangling.status_code == existing.status_code == 400
        assert "escapes" in dangling.detail.lower() and "escapes" in existing.detail.lower()

    def test_a_dangling_link_that_would_land_inside_the_scope_is_a_plain_404( self, served, layout ):
        os.symlink( layout.root / "src" / "ghost.md", layout.root / "src" / "inner-dangling.md" )
        assert _refused( "lupin/src/inner-dangling.md" ).status_code == 404

    def test_an_ordinary_file_still_serves( self, served ):
        assert _get( "lupin/src/note.md" ).status_code == 200


class TestThePredicate:

    def test_identity_not_spelling_decides( self, layout ):
        assert landed_within_roots( str( layout.mirror / "io" / "x" ), [ str( layout.root ) ] ) is True
        assert landed_within_roots( str( layout.evil / "io" / "x.log" ), [ str( layout.root ) ] ) is False

    def test_the_relative_form_is_taken_from_the_matching_ancestor( self, layout ):
        assert landed_relative_path( str( layout.mirror / ".env" ), str( layout.root ) ) == ".env"
        assert landed_relative_path( str( layout.root ), str( layout.root ) ) == ""

    def test_an_unstatable_root_is_skipped_not_raised( self, layout ):
        assert landed_within_roots( str( layout.root / "src" ), [ str( layout.tmp / "no-such-root" ) ] ) is False

    def test_a_symlinked_scope_ROOT_still_accepts_its_own_files( self, layout, monkeypatch ):
        # the trap: resolving the child but not the root refuses everything under a symlinked root
        monkeypatch.undo()
        link = layout.tmp / "rootlink"
        os.symlink( layout.root, link )
        cfg = ScopeConfig( name="lupin", root=str( link ), allowed_prefixes=() )
        assert resolve_in_scope( cfg, "src/note.md" ) == os.path.realpath( layout.root / "src" / "note.md" )

    def test_dangling_outside_link_raises_the_same_ValueError_as_an_existing_outside_link( self, layout ):
        cfg = ScopeConfig( name="lupin", root=str( layout.root ), allowed_prefixes=() )
        for name in ( "io/dangling.log", "src/etc.md" ):
            with pytest.raises( ValueError, match="escapes scope root" ):
                resolve_in_scope( cfg, name )


class TestReceiptPathsUseTheSamePredicate:
    """cc39cee6: `_validate_scoped_path` used normpath, so containment judged the typed name and `isfile` the target."""

    def _check( self, layout, value ):
        return rules._validate_scoped_path( value, { "lupin": str( layout.root ) } )

    def test_a_link_to_etc_is_refused_as_an_escape( self, layout ):
        errors = self._check( layout, "lupin/src/etc.md" )
        assert len( errors ) == 1 and "escapes its scope root" in errors[ 0 ]

    def test_the_sibling_is_refused( self, layout ):
        assert "escapes" in self._check( layout, "lupin/io/evil.log" )[ 0 ]

    @pytest.mark.parametrize( "name", ARTIFACT_LINKS )
    def test_the_eleven_latest_links_are_accepted( self, layout, name ):
        assert self._check( layout, f"lupin/io/test-suite/artifacts/{name}-latest.log" ) == [ ]

    def test_a_dangling_outside_link_reads_exactly_like_an_existing_outside_link( self, layout ):
        # row 9b80ef75 (a)
        assert self._check( layout, "lupin/io/dangling.log" )[ 0 ].replace( "io/dangling.log", "X" ) \
            == self._check( layout, "lupin/src/etc.md" )[ 0 ].replace( "src/etc.md", "X" )

    def test_a_dangling_link_that_would_land_inside_reads_as_missing( self, layout ):
        os.symlink( layout.root / "src" / "ghost.md", layout.root / "src" / "inner-dangling.md" )
        assert "does not exist" in self._check( layout, "lupin/src/inner-dangling.md" )[ 0 ]

    def test_a_blocklisted_receipt_answers_the_same_whether_or_not_the_file_exists( self, layout ):
        # row 9b80ef75 (b): a receipt naming a credential file must not confirm that it exists
        present = self._check( layout, "lupin/.env" )
        absent  = self._check( layout, "lupin/sub/.env" )
        assert len( present ) == 1 and "blocklist" in present[ 0 ]
        assert present[ 0 ].replace( "lupin/.env", "X" ) == absent[ 0 ].replace( "lupin/sub/.env", "X" )

    def test_the_blocklist_judges_the_LANDED_path_of_a_link( self, layout ):
        # typed `src/env.md` is innocent; it lands on `<alias>/.env`
        assert "blocklist" in self._check( layout, "lupin/src/env.md" )[ 0 ]

    def test_an_ordinary_file_is_accepted_and_a_missing_one_is_not( self, layout ):
        assert self._check( layout, "lupin/src/note.md" ) == [ ]
        assert "does not exist" in self._check( layout, "lupin/src/ghost.md" )[ 0 ]
