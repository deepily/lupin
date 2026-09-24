"""
Unit tests — repo docs serve audio, video and PDF as raw bytes (ticket 668aa0a3, 2026-09-24).

Rick ruled "button + media": the doc viewer must open and download sound, video and PDF from
any registered repo, not only from io/. The endpoint coroutine is invoked directly over a tmp
scope, as test_docs_files_bare_scope.py does — no live server.

🔴 THE BYTES ARE THE ASSERTION. A binary routed down the TEXT branch is decoded as utf-8 and
either 500s or arrives mangled; FileResponse streams it untouched. So each case plants bytes
that are NOT valid utf-8 and compares what the response would send.

Tier: :7999-eligible unit (no server, no persistent state, milliseconds).
"""

import asyncio

import pytest
from fastapi.responses import FileResponse

import cosa.rest.routers.docs_files as docs_files
from cosa.rest.routers._scope_registry import ScopeConfig

# \xff\xfe… is invalid utf-8, so a text-branch read cannot reproduce it.
NOT_UTF8 = b"\xff\xfe\x00\x81binary\x9f" + bytes( range( 256 ) )

CASES = [
    ( "clip.mp3",  "audio/mpeg"      ),
    ( "clip.wav",  "audio/wav"       ),
    ( "movie.mp4", "video/mp4"       ),
    ( "movie.webm","video/webm"      ),
    ( "paper.pdf", "application/pdf" ),
]


@pytest.fixture
def media_scope( tmp_path, monkeypatch ):
    for name, _ in CASES:
        ( tmp_path / name ).write_bytes( NOT_UTF8 )
    registry = { "media": ScopeConfig( name="media", root=str( tmp_path ), allowed_prefixes=() ) }
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: registry )
    return tmp_path


def _get( path ):
    return asyncio.run( docs_files.get_docs_file( path=path, scope=None, current_user={ "email": "t@lupin" } ) )


@pytest.mark.parametrize( "name, media_type", CASES )
def test_binary_media_streams_untouched_bytes( media_scope, name, media_type ):
    response = _get( f"media/{ name }" )
    assert isinstance( response, FileResponse ), f"{ name } went down the text branch"
    assert response.media_type == media_type
    with open( response.path, "rb" ) as f:
        assert f.read() == NOT_UTF8


def test_every_new_type_is_registered_and_binary():
    assert len( CASES ) == 5, "the parametrize list must not be empty or shrink silently"
    for name, media_type in CASES:
        ext = "." + name.rsplit( ".", 1 )[ 1 ]
        assert docs_files.MEDIA_TYPES[ ext ] == media_type
        assert media_type.startswith( docs_files.BINARY_MEDIA_PREFIXES )


def test_text_still_takes_the_text_branch( media_scope ):
    ( media_scope / "notes.md" ).write_text( "# still text\n" )
    response = _get( "media/notes.md" )
    assert not isinstance( response, FileResponse )
    assert response.body == b"# still text\n"
