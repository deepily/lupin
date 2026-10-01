"""
Unit tests for row 5dd6baaa: the io door judges where a path LANDS by directory identity, not by spelling.

`get_io_file` tested containment with `full_path.startswith( io_base + os.sep )`. In the container the
repo is mounted at two prefixes (`/var/lupin` and `/var/external-projects/lupin`, one host directory),
so a link under `io/` aimed at the OTHER spelling of `io/` was refused as outside it, and a directory
link that did land had its listing keyed by a `../..` relative form. Same defect class as rows
cc39cee6 and ae634018; the live links happen to use the matching spelling, so this is latent.

An unprivileged test cannot build a bind mount, so `_scope_registry._stat` is the seam: the tests give one
real directory the identity of `io/`, which is what a bind mount does. Everything else is real, under
pytest's `tmp_path`. Shape follows `test_io_files_symlink_laundering.py`.

Tier: :7999-eligible unit (no server, no persistent state, milliseconds).
"""
import asyncio
import os

import pytest
from fastapi import HTTPException

import cosa.rest.routers._scope_registry as scope_registry
import cosa.rest.routers.io_files as io_files

ORDINARY = "# reached through the second spelling\n"


@pytest.fixture
def project( tmp_path, monkeypatch ):
    """root/io is the door's base; mirror/ is a second spelling of it; io-evil/ is a name-prefix sibling."""
    root   = tmp_path / "proj"
    mirror = tmp_path / "var" / "io-mirror"
    evil   = tmp_path / "var" / "io-mirror-evil"
    odd    = tmp_path / "var" / ".credentials-mirror"      # a second spelling whose OWN NAME matches a floor pattern
    ( root / "io" ).mkdir( parents=True )
    ( mirror / "subdir" ).mkdir( parents=True )
    evil.mkdir( parents=True )
    odd.mkdir( parents=True )
    ( odd / "z.md" ).write_text( "# fine, but its mount is named like a credential\n" )
    os.symlink( odd / "z.md", root / "io" / "z.md" )
    ( mirror / "x.md" ).write_text( ORDINARY )
    ( mirror / ".env" ).write_text( "canary-5dd6baaa-never-served\n" )
    ( mirror / "subdir" / "inner.md" ).write_text( "# inner\n" )
    ( evil / "y.md" ).write_text( "# not yours\n" )

    os.symlink( mirror / "x.md",    root / "io" / "x.md" )
    os.symlink( mirror / ".env",    root / "io" / "env.md" )          # innocent name, blocked landing
    os.symlink( mirror / "subdir",  root / "io" / "linkdir" )
    os.symlink( evil / "y.md",      root / "io" / "evil.md" )
    os.symlink( "/etc/passwd",      root / "io" / "etc.md" )
    os.symlink( tmp_path / "gone.md", root / "io" / "dangling.md" )

    real_stat = os.stat
    io_dir    = str( root / "io" )
    monkeypatch.setattr( scope_registry, "_stat",
                         lambda path, *a, **k: real_stat( io_dir if os.fspath( path ) in ( str( mirror ), str( odd ) ) else path, *a, **k ) )
    monkeypatch.setattr( io_files.cu, "get_project_root", lambda: str( root ) )
    return root


def _get( path ):
    return asyncio.run( io_files.get_io_file( path=path, download=False, current_user={ "uid": "t" } ) )


def _refused( path ):
    with pytest.raises( HTTPException ) as caught:
        _get( path )
    return caught.value


class TestTheSecondSpellingServes:

    def test_a_link_into_the_second_spelling_of_io_is_served( self, project ):
        response = _get( "x.md" )
        assert response.status_code == 200 and ORDINARY.strip() in response.body.decode()

    def test_a_mount_whose_own_NAME_matches_a_floor_pattern_does_not_taint_the_file( self, project ):
        # The blocklist re-judge must see the path RELATIVE TO io/ (`z.md`). The old relpath form is
        # `../../var/.credentials-mirror/z.md`, whose `.credentials-mirror` segment matches `^\\.credentials`
        # and would refuse a clean file. This is the case the first fixture could not tell apart.
        response = _get( "z.md" )
        assert response.status_code == 200

    def test_a_directory_link_is_listed_by_its_landed_relative_path( self, project, monkeypatch ):
        seen = {}
        def fake_list( **kwargs ):
            seen.update( kwargs )
            return {}
        monkeypatch.setattr( io_files, "list_directory", fake_list )
        _get( "linkdir" )
        # `subdir` is where it landed, relative to the matching ancestor — never `../../var/io-mirror/subdir`
        assert seen[ "rel_dir" ] == "subdir"


class TestRefusals:

    def test_the_sibling_that_shares_a_name_prefix_is_refused( self, project ):
        exc = _refused( "evil.md" )
        assert exc.status_code == 400 and "within io/" in exc.detail

    def test_a_link_to_etc_is_refused( self, project ):
        assert _refused( "etc.md" ).status_code == 400

    def test_the_blocklist_is_judged_on_the_LANDED_name( self, project ):
        exc = _refused( "env.md" )
        assert exc.status_code == 400 and "blocklist" in exc.detail.lower()

    def test_a_dangling_link_is_a_404_like_any_missing_file( self, project ):
        exc = _refused( "dangling.md" )
        missing = _refused( "never-existed.md" )
        assert exc.status_code == 404 == missing.status_code
        assert exc.detail.replace( "dangling.md", "X" ) == missing.detail.replace( "never-existed.md", "X" )
