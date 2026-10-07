"""
The io door judges the file it opened, not the path string it checked.

`get_io_file` resolved a path with realpath and judged where it landed, then read the same
string a moment later. A peer who could swap a directory component for a symlink in between
redirected the read. The door now opens first, judges where the descriptor landed, and serves
through it.

Every arm that swaps has a control that does not. The swap wraps the real `os.path.realpath`,
so it runs after the real judgement and before the open. All files are real files in tmp_path.
"""
import asyncio
import os

import pytest
from fastapi import HTTPException

import cosa.rest.routers.io_files as io_files

USER = { "email": "someone@lupin", "roles": [] }

OUTSIDE_TEXT = "SECRET OUTSIDE\n"


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """A project root with io/dir/{f.md,p.png}, an outside tree, and a blocked name in io/."""
    root    = tmp_path / "proj"
    outside = tmp_path / "outside"
    for d in ( root / "io" / "dir", outside ):
        d.mkdir( parents=True )
    ( root / "io" / "dir" / "f.md"  ).write_text( "public\n" )
    ( root / "io" / "dir" / "p.png" ).write_bytes( b"\x89PNG-public" )
    ( root / "io" / ".env"          ).write_text( "blocked by name\n" )
    ( outside / "f.md"  ).write_text( OUTSIDE_TEXT )
    ( outside / "p.png" ).write_bytes( b"\x89PNG-OUTSIDE" )
    monkeypatch.setattr( io_files.cu, "get_project_root", lambda: str( root ) )
    return { "root": root, "io": root / "io", "outside": outside }


def _get( path, download=False ):
    return asyncio.run( io_files.get_io_file( path=path, download=download, current_user=USER ) )


def _swap_after_resolve( monkeypatch, victim_suffix, swap ):
    """Wrap realpath so `swap()` runs once, after the real judgement of `victim_suffix`."""
    real  = os.path.realpath
    fired = []

    def swapping( p, *args, **kwargs ):
        landed = real( p, *args, **kwargs )
        if not fired and str( p ).endswith( victim_suffix ):
            fired.append( p )
            swap()
        return landed

    monkeypatch.setattr( os.path, "realpath", swapping )
    return fired


def _dir_to_outside( world ):
    def swap():
        os.rename( world[ "io" ] / "dir", world[ "io" ] / "dir.bak" )
        os.symlink( world[ "outside" ], world[ "io" ] / "dir" )
    return swap


def _open_fds():
    return len( os.listdir( "/proc/self/fd" ) )


# ── controls: no swap ───────────────────────────────────────────────────────

def test_control_an_unswapped_text_read_is_served( world ):
    assert _get( "dir/f.md" ).body == b"public\n"


def test_control_an_unswapped_binary_read_streams_the_pinned_file_and_closes_it( world ):
    before   = _open_fds()
    response = _get( "dir/p.png" )
    assert response.path.startswith( "/proc/self/fd/" ) and response.background is not None
    assert _open_fds() == before + 1, "the descriptor stays open until the response has been sent"
    asyncio.run( response.background() )
    assert _open_fds() == before


def test_control_an_unswapped_download_attaches_with_the_real_filename_and_closes_it( world ):
    before   = _open_fds()
    response = _get( "dir/f.md", download=True )
    assert response.path.startswith( "/proc/self/fd/" )
    assert response.headers[ "content-disposition" ].startswith( "attachment" ) and "f.md" in response.headers[ "content-disposition" ]
    asyncio.run( response.background() )
    assert _open_fds() == before


# ── the swap: each arm is refused on the opened file ───────────────────────

@pytest.mark.parametrize( "name,download", [ ( "f.md", False ), ( "f.md", True ), ( "p.png", False ) ] )
def test_a_component_swapped_after_the_check_is_refused_not_served( world, monkeypatch, name, download ):
    """Kills the mutant that opens the string again, in the text, download and binary arms."""
    fired = _swap_after_resolve( monkeypatch, f"dir/{name}", _dir_to_outside( world ) )
    with pytest.raises( HTTPException ) as exc:
        _get( f"dir/{name}", download=download )
    assert fired, "the swap never fired: this test would pass for the wrong reason"
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid path: must be within io/ directory"


def test_a_file_swapped_for_a_blocked_name_after_the_check_is_refused( world, monkeypatch ):
    def swap():
        os.rename( world[ "io" ] / "dir" / "f.md", world[ "io" ] / "dir" / "f.md.bak" )
        os.symlink( world[ "io" ] / ".env", world[ "io" ] / "dir" / "f.md" )
    fired = _swap_after_resolve( monkeypatch, "dir/f.md", swap )
    with pytest.raises( HTTPException ) as exc:
        _get( "dir/f.md" )
    assert fired
    assert ( exc.value.status_code, exc.value.detail ) == ( 400, "Path matches secrets blocklist" )


def test_a_swap_after_the_open_cannot_redirect_the_text_read( world, monkeypatch ):
    """Kills the mutant that reads the string again after the open, in the text arm."""
    real  = io_files.open_pinned
    fired = []

    def open_then_swap( full_path, judge, directory=False ):
        fd = real( full_path, judge, directory )
        fired.append( full_path )
        _dir_to_outside( world )()
        return fd

    monkeypatch.setattr( io_files, "open_pinned", open_then_swap )
    body = _get( "dir/f.md" ).body
    assert fired, "the swap never fired: this test would pass for the wrong reason"
    assert body == b"public\n" and OUTSIDE_TEXT.encode() not in body


def test_the_descriptor_is_closed_on_every_refusal( world, monkeypatch ):
    before = _open_fds()
    _swap_after_resolve( monkeypatch, "dir/f.md", _dir_to_outside( world ) )
    with pytest.raises( HTTPException ):
        _get( "dir/f.md" )
    assert _open_fds() == before


# ── the door's own answers, byte for byte ───────────────────────────────────

def test_a_file_that_is_gone_at_the_open_answers_the_doors_own_404( world, monkeypatch ):
    def gone( full_path, judge, directory=False ):
        raise io_files.PinnedPathGone( full_path )
    monkeypatch.setattr( io_files, "open_pinned", gone )
    with pytest.raises( HTTPException ) as exc:
        _get( "dir/f.md" )
    assert ( exc.value.status_code, exc.value.detail ) == ( 404, "File not found: dir/f.md" )


def test_the_string_checks_still_answer_with_the_same_words( world ):
    with pytest.raises( HTTPException ) as exc:
        _get( "dir/missing.md" )
    assert ( exc.value.status_code, exc.value.detail ) == ( 404, "File not found: dir/missing.md" )
    with pytest.raises( HTTPException ) as exc:
        _get( "dir/f.exe" if ( world[ "io" ] / "dir" / "f.exe" ).write_text( "x" ) else "" )
    assert ( exc.value.status_code, exc.value.detail ) == ( 400, "Unsupported file type: .exe" )
    with pytest.raises( HTTPException ) as exc:
        _get( ".env" )
    assert ( exc.value.status_code, exc.value.detail ) == ( 400, "Path matches secrets blocklist" )
    with pytest.raises( HTTPException ) as exc:
        _get( "../outside/f.md" )
    assert ( exc.value.status_code, exc.value.detail ) == ( 400, "Invalid path: must be within io/ directory" )


def test_a_serving_failure_closes_the_descriptor_and_answers_500( world, monkeypatch ):
    before = _open_fds()
    def boom( *args, **kwargs ): raise RuntimeError( "boom" )
    for download, name in ( ( True, "f.md" ), ( False, "p.png" ) ):
        monkeypatch.setattr( io_files, "FileResponse", boom )
        with pytest.raises( HTTPException ) as exc:
            _get( f"dir/{name}", download=download )
        assert exc.value.status_code == 500 and "boom" in exc.value.detail
    assert _open_fds() == before


def test_a_text_read_failure_closes_the_descriptor_and_answers_500( world, monkeypatch ):
    before = _open_fds()
    ( world[ "io" ] / "dir" / "bad.md" ).write_bytes( b"\xff\xfe\xfa not utf-8" )
    with pytest.raises( HTTPException ) as exc:
        _get( "dir/bad.md" )
    assert exc.value.status_code == 500 and exc.value.detail.startswith( "Error reading file" )
    assert _open_fds() == before
