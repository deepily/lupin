"""
The doc viewer judges the object it OPENED, not the path string it checked — row 39b3035b.

The defect, pre-existing (measured against 5e7f02c0c and d446c7b12 alike): `_resolve_scoped` resolves
the path with realpath and judges where it landed, then `_serve` opens the SAME STRING a moment
later. A peer who can swap a directory component for a symlink in between redirects the read (or the
upload's write) to a place the judgement never saw. A name-based NOFOLLOW would break the eleven legitimate
`*-latest.log` links, so the fix opens first and then judges what the open file descriptor
actually is (`/proc/self/fd`, Linux only), and serves or writes through that descriptor.

🔴 EVERY ARM THAT SWAPS HAS A CONTROL THAT DOES NOT. The swap is performed by wrapping the real
resolver, so it happens AFTER the real judgement and BEFORE the open — the exact window. All files are
real files in tmp_path; nothing about the filesystem is mocked.
"""
import asyncio
import io
import os

import pytest
from fastapi import HTTPException, UploadFile

import cosa.rest.routers.docs_files as docs_files
from cosa.rest.routers._scope_registry import ScopeConfig

ADMIN = { "email": "rick@lupin", "roles": [ "admin" ] }
USER  = { "email": "someone@lupin", "roles": [] }


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """A scope `repo` restricted to `docs/`, a real folder docs/dir, and an outside tree to escape to."""
    repo    = tmp_path / "repo"
    outside = tmp_path / "outside"
    private = repo / "private"
    for d in ( repo / "docs" / "dir", repo / "docs" / "up", outside, private ):
        d.mkdir( parents=True, exist_ok=True )
    ( repo / "docs" / "dir" / "f.md" ).write_text( "public\n" )
    ( outside / "f.md" ).write_text( "SECRET OUTSIDE\n" )
    ( private / "f.md" ).write_text( "PRIVATE INSIDE BUT NOT WHITELISTED\n" )

    cfg = ScopeConfig( name="repo", root=str( repo ), allowed_prefixes=( "docs", ) )
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: { "repo": cfg } )
    monkeypatch.setattr( docs_files, "_upload_registry", lambda: { "repo": cfg } )
    return { "repo": repo, "outside": outside, "private": private, "cfg": cfg }


def _swap_dir_for_symlink( directory, target ):
    """Replace a real directory with a symlink to `target`, keeping the original beside it."""
    os.rename( directory, f"{directory}.bak" )
    os.symlink( target, directory )


def _get( path ):
    return asyncio.run( docs_files.get_docs_file( path=path, scope=None, current_user=USER ) )


def _upload( directory, name, data ):
    upload = UploadFile( file=io.BytesIO( data ), filename=name )
    return asyncio.run( docs_files.upload_docs_file( dir=directory, file=upload, on_conflict="refuse", admin_user=ADMIN ) )


# ── READ ────────────────────────────────────────────────────────────────────

def test_control_an_unswapped_read_is_served( world ):
    assert _get( "repo/docs/dir/f.md" ).body == b"public\n"


@pytest.mark.parametrize( "landing", [ "outside", "private" ] )
def test_a_component_swapped_after_the_check_is_refused_not_served( world, monkeypatch, landing ):
    """
    `outside` lands beyond the scope root; `private` lands INSIDE the root but outside the whitelist
    (`docs`). The first is an escape, the second a whitelist bypass — both are judged on the opened file.
    """
    real = docs_files.resolve_in_scope

    def swapping( scope_cfg, rel ):
        landed = real( scope_cfg, rel )
        _swap_dir_for_symlink( str( world[ "repo" ] / "docs" / "dir" ), str( world[ landing ] ) )
        return landed

    monkeypatch.setattr( docs_files, "resolve_in_scope", swapping )
    with pytest.raises( HTTPException ) as exc:
        _get( "repo/docs/dir/f.md" )
    assert exc.value.status_code == 400
    assert "SECRET" not in str( exc.value.detail ) and "PRIVATE" not in str( exc.value.detail )


def test_a_binary_read_is_judged_on_the_opened_file_too( world, monkeypatch ):
    ( world[ "repo" ] / "docs" / "dir" / "p.png" ).write_bytes( b"\x89PNG-public" )
    ( world[ "outside" ] / "p.png" ).write_bytes( b"\x89PNG-OUTSIDE" )
    real = docs_files.resolve_in_scope

    def swapping( scope_cfg, rel ):
        landed = real( scope_cfg, rel )
        _swap_dir_for_symlink( str( world[ "repo" ] / "docs" / "dir" ), str( world[ "outside" ] ) )
        return landed

    monkeypatch.setattr( docs_files, "resolve_in_scope", swapping )
    with pytest.raises( HTTPException ) as exc:
        _get( "repo/docs/dir/p.png" )
    assert exc.value.status_code == 400


def test_an_unswapped_binary_read_streams_the_pinned_file( world ):
    ( world[ "repo" ] / "docs" / "dir" / "p.png" ).write_bytes( b"\x89PNG-public" )
    response = _get( "repo/docs/dir/p.png" )
    assert response.path.startswith( "/proc/self/fd/" )
    assert response.background is not None
    asyncio.run( response.background() )   # the descriptor is closed by the response's own task


# ── WRITE ───────────────────────────────────────────────────────────────────

def test_control_an_unswapped_upload_lands_in_the_folder( world ):
    out = _upload( "repo/docs/up", "n.md", b"hello" )
    assert out[ "name" ] == "n.md"
    assert ( world[ "repo" ] / "docs" / "up" / "n.md" ).read_bytes() == b"hello"


def test_a_folder_swapped_after_pinning_cannot_redirect_the_write( world, monkeypatch ):
    """The swap fires on the SECOND gate call, after the folder is pinned: the bytes must land in the original folder."""
    real  = docs_files._resolve_scoped
    calls = []

    def swapping( path, registry ):
        result = real( path, registry )
        calls.append( path )
        if len( calls ) == 2:
            _swap_dir_for_symlink( str( world[ "repo" ] / "docs" / "up" ), str( world[ "outside" ] ) )
        return result

    monkeypatch.setattr( docs_files, "_resolve_scoped", swapping )
    _upload( "repo/docs/up", "n.md", b"hello" )
    assert len( calls ) >= 2, "the swap never fired: this test would pass for the wrong reason"
    assert not ( world[ "outside" ] / "n.md" ).exists(), "the write followed the swapped symlink out of the scope"
    assert ( world[ "repo" ] / "docs" / "up.bak" / "n.md" ).read_bytes() == b"hello"


def test_a_folder_swapped_before_pinning_is_refused_and_nothing_is_written( world, monkeypatch ):
    real  = docs_files._resolve_scoped
    calls = []

    def swapping( path, registry ):
        result = real( path, registry )
        calls.append( path )
        if len( calls ) == 1:
            _swap_dir_for_symlink( str( world[ "repo" ] / "docs" / "up" ), str( world[ "outside" ] ) )
        return result

    monkeypatch.setattr( docs_files, "_resolve_scoped", swapping )
    with pytest.raises( HTTPException ) as exc:
        _upload( "repo/docs/up", "n.md", b"hello" )
    assert exc.value.status_code == 400
    assert [ p.name for p in world[ "outside" ].iterdir() ] == [ "f.md" ], "something was written outside the scope"


# ── the refusal branches of the new helpers, each on real files ─────────────

def test_a_swap_to_a_blocklisted_name_inside_the_whitelist_is_refused( world, monkeypatch ):
    """Lands INSIDE the root and INSIDE `docs/`, but on a path the secrets floor refuses."""
    ( world[ "repo" ] / "docs" / "credentials" ).mkdir()
    ( world[ "repo" ] / "docs" / "credentials" / "f.md" ).write_text( "x\n" )
    real = docs_files.resolve_in_scope

    def swapping( scope_cfg, rel ):
        landed = real( scope_cfg, rel )
        _swap_dir_for_symlink( str( world[ "repo" ] / "docs" / "dir" ), str( world[ "repo" ] / "docs" / "credentials" ) )
        return landed

    monkeypatch.setattr( docs_files, "resolve_in_scope", swapping )
    with pytest.raises( HTTPException ) as exc:
        _get( "repo/docs/dir/f.md" )
    assert exc.value.status_code == 400 and "secrets blocklist" in exc.value.detail


def test_a_file_that_vanished_before_the_open_is_a_404( world ):
    with pytest.raises( HTTPException ) as exc:
        docs_files._open_judged_file( str( world[ "repo" ] / "docs" / "gone.md" ), world[ "cfg" ] )
    assert exc.value.status_code == 404


def test_a_directory_is_not_a_servable_file( world ):
    with pytest.raises( HTTPException ) as exc:
        docs_files._open_judged_file( str( world[ "repo" ] / "docs" ), world[ "cfg" ] )
    assert exc.value.status_code == 404


def test_an_unlinked_inode_is_a_404_not_a_judgement( tmp_path ):
    victim = tmp_path / "v.md"
    victim.write_text( "x" )
    fd = os.open( victim, os.O_RDONLY )
    try:
        os.unlink( victim )
        with pytest.raises( HTTPException ) as exc:
            docs_files._landed_path_of_fd( fd )
        assert exc.value.status_code == 404
    finally:
        os.close( fd )


def test_a_folder_that_vanished_before_the_pin_is_a_404( world ):
    with pytest.raises( HTTPException ) as exc:
        docs_files._pin_directory( str( world[ "repo" ] / "docs" / "nope" ), world[ "cfg" ] )
    assert exc.value.status_code == 404


def test_a_text_file_that_cannot_be_decoded_is_a_500_after_the_content_check( world, monkeypatch ):
    """The read itself fails (invalid UTF-8) although the credential check was told the file is clean."""
    ( world[ "repo" ] / "docs" / "dir" / "bad.md" ).write_bytes( b"\xff\xfe\x00bad" )
    monkeypatch.setattr( "cosa.rest.routers._scope_registry.credential_verdict", lambda path: "clean" )
    with pytest.raises( HTTPException ) as exc:
        _get( "repo/docs/dir/bad.md" )
    assert exc.value.status_code == 500 and "Error reading file" in exc.value.detail


def test_a_swap_that_is_undone_after_the_pin_still_cannot_land_outside( world, monkeypatch ):
    """
    Swap BEFORE the pin, swap back BEFORE the file-path gate: the second gate then sees a clean tree, so
    only the judgement of the pinned folder itself can refuse. Without it the write goes out through the
    descriptor that was pinned while the symlink was in place.
    """
    real  = docs_files._resolve_scoped
    calls = []
    up    = world[ "repo" ] / "docs" / "up"

    def swapping( path, registry ):
        calls.append( path )
        if len( calls ) == 2:                      # undo the swap BEFORE this gate looks, so it sees a clean tree
            os.unlink( up )
            os.rename( f"{up}.bak", up )
        result = real( path, registry )
        if len( calls ) == 1:                      # swap AFTER the first gate, before the pin
            _swap_dir_for_symlink( str( up ), str( world[ "outside" ] ) )
        return result

    monkeypatch.setattr( docs_files, "_resolve_scoped", swapping )
    with pytest.raises( HTTPException ) as exc:
        _upload( "repo/docs/up", "n.md", b"hello" )
    assert exc.value.status_code == 400
    assert [ p.name for p in world[ "outside" ].iterdir() ] == [ "f.md" ], "the pinned outside folder received the write"
