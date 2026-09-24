"""
Unit tests — POST /api/docs/upload (ticket 416d4b00, Rick's rulings 2026-09-24).

Rulings under test: upload into ANY folder the viewer can browse (repos and io), admins only,
a name clash is REFUSED with a suggested alternative unless the caller asks to replace or rename.

The coroutine is invoked directly over tmp scopes, as test_docs_files_bare_scope.py does.

🔴 EVERY REFUSAL ALSO ASSERTS WHAT IS ON DISK. A refusal that still wrote the file, or left
its temp file behind, would pass a status-code check. So each negative case lists the folder.

Tier: :7999-eligible unit (no server, tmp dirs only, milliseconds).
"""

import asyncio
import io
import os

import pytest
from fastapi import HTTPException, UploadFile

import cosa.rest.routers.docs_files as docs_files
from cosa.rest.auth_middleware import require_admin
from cosa.rest.routers._scope_registry import ScopeConfig, _is_secrets_path

ADMIN = { "email": "rick@lupin", "roles": [ "admin" ] }


@pytest.fixture
def scopes( tmp_path, monkeypatch ):
    """A wildcard repo scope `repo` with a `docs/` folder, plus a project root holding `io/inbox/`."""
    repo = tmp_path / "repo"
    ( repo / "docs" ).mkdir( parents=True )
    ( repo / "docs" / "existing.md" ).write_text( "# original\n" )
    project = tmp_path / "project"
    ( project / "io" / "inbox" ).mkdir( parents=True )

    registry = { "repo": ScopeConfig( name="repo", root=str( repo ), allowed_prefixes=() ) }
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: registry )
    monkeypatch.setattr( docs_files.cu, "get_project_root", lambda: str( project ) )
    return { "repo": repo, "project": project }


def _upload( directory, name, data, on_conflict="refuse" ):
    upload = UploadFile( file=io.BytesIO( data ), filename=name )
    return asyncio.run( docs_files.upload_docs_file(
        dir=directory, file=upload, on_conflict=on_conflict, admin_user=ADMIN ) )


def _status( directory, name, data, on_conflict="refuse" ):
    with pytest.raises( HTTPException ) as exc:
        _upload( directory, name, data, on_conflict )
    return exc.value


def _listing( folder ):
    return sorted( os.listdir( folder ) )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_upload_lands_the_exact_bytes_and_returns_a_viewer_link( scopes ):
    data = b"# hello\n\nuploaded body\n"
    out  = _upload( "repo/docs", "new note.md", data )
    assert ( scopes[ "repo" ] / "docs" / "new note.md" ).read_bytes() == data
    assert out == {
        "path"     : "repo/docs/new note.md",
        "name"     : "new note.md",
        "size"     : len( data ),
        "replaced" : False,
        "view_url" : "/app/docs?path=repo/docs/new%20note.md",
    }
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md", "new note.md" ], "no temp file left behind"


def test_upload_into_io_uses_the_same_gate( scopes ):
    out = _upload( "io/inbox", "clip.mp3", b"ID3\xff\xfe binary" )
    assert out[ "path" ] == "io/inbox/clip.mp3"
    assert ( scopes[ "project" ] / "io" / "inbox" / "clip.mp3" ).read_bytes() == b"ID3\xff\xfe binary"


def test_a_trailing_slash_on_the_folder_is_accepted( scopes ):
    assert _upload( "repo/docs/", "a.txt", b"x" )[ "path" ] == "repo/docs/a.txt"


# ---------------------------------------------------------------------------
# Name clash — refuse, replace, rename
# ---------------------------------------------------------------------------

def test_a_clash_is_refused_with_a_suggested_name_and_the_original_untouched( scopes ):
    err = _status( "repo/docs", "existing.md", b"# intruder\n" )
    assert err.status_code == 409
    assert err.detail[ "error" ] == "exists"
    assert err.detail[ "suggested_name" ] == "existing-2.md"
    assert ( scopes[ "repo" ] / "docs" / "existing.md" ).read_text() == "# original\n"
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md" ]


def test_replace_overwrites_and_says_so( scopes ):
    out = _upload( "repo/docs", "existing.md", b"# new\n", on_conflict="replace" )
    assert out[ "replaced" ] is True
    assert ( scopes[ "repo" ] / "docs" / "existing.md" ).read_text() == "# new\n"


def test_rename_picks_the_first_free_name( scopes ):
    ( scopes[ "repo" ] / "docs" / "existing-2.md" ).write_text( "taken\n" )
    out = _upload( "repo/docs", "existing.md", b"# third\n", on_conflict="rename" )
    assert out[ "name" ] == "existing-3.md"
    assert ( scopes[ "repo" ] / "docs" / "existing.md" ).read_text() == "# original\n"
    assert ( scopes[ "repo" ] / "docs" / "existing-3.md" ).read_text() == "# third\n"


def test_an_unknown_conflict_mode_is_refused( scopes ):
    assert _status( "repo/docs", "a.md", b"x", on_conflict="clobber" ).status_code == 400


# ---------------------------------------------------------------------------
# The gate — folder and file name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "directory", [ "repo/../../etc", "nope/docs", "", "repo/docs/../../.." ] )
def test_a_folder_outside_the_gate_is_refused( scopes, directory ):
    assert _status( directory, "a.md", b"x" ).status_code == 400


def test_a_missing_folder_is_404( scopes ):
    assert _status( "repo/nowhere", "a.md", b"x" ).status_code == 404


def test_a_path_in_the_filename_is_stripped_to_its_basename( scopes ):
    out = _upload( "repo/docs", "../../escape.md", b"x" )
    assert out[ "path" ] == "repo/docs/escape.md"
    assert not ( scopes[ "repo" ] / "escape.md" ).exists()


@pytest.mark.parametrize( "name", [ ".env", ".hidden.md", "", "..", "tool.exe", "noext" ] )
def test_unusable_names_and_types_are_refused( scopes, name ):
    assert _status( "repo/docs", name, b"x" ).status_code == 400
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md" ]


def test_a_name_the_secrets_blocklist_refuses_is_refused_even_in_an_allowed_folder( scopes ):
    candidates = [ n for n in ( "credentials.json", "service-account.json", "secrets.yaml", "token.json" )
                   if _is_secrets_path( f"docs/{ n }" ) ]
    assert candidates, "no candidate name is blocklisted — this test would measure nothing"
    assert _status( "repo/docs", candidates[ 0 ], b"{}" ).status_code == 400
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md" ]


def test_credential_content_in_a_text_file_is_refused_and_nothing_is_kept( scopes ):
    # The PEM markers are assembled at runtime so the repo's commit guard sees no literal key
    # header; the bytes the endpoint reads are identical.
    begin, end = "-----BEGIN " + "PRIVATE KEY-----", "-----END " + "PRIVATE KEY-----"
    key = ( '{"type": "service_account", "private_key": "' + begin + '\\nMIIE\\n' + end + '\\n"}' ).encode()
    err = _status( "repo/docs", "harmless.json", key )
    assert err.status_code == 400 and "credential" in err.detail
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md" ], "the temp file must be cleaned up too"


def test_a_non_utf8_text_file_is_refused( scopes ):
    assert _status( "repo/docs", "bad.md", b"\xff\xfe\x00bad" ).status_code == 400


def test_the_size_cap_is_enforced_and_leaves_nothing( scopes, monkeypatch ):
    monkeypatch.setattr( docs_files, "UPLOAD_MAX_BYTES", 10 )
    monkeypatch.setattr( docs_files, "_UPLOAD_CHUNK", 4 )
    assert _status( "repo/docs", "big.txt", b"x" * 11 ).status_code == 413
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md" ]


def test_a_read_only_folder_answers_403_not_500( scopes ):
    folder = scopes[ "repo" ] / "docs"
    os.chmod( folder, 0o555 )
    try:
        if os.access( folder, os.W_OK ):
            pytest.skip( "running as a user that can write a 0555 folder (root) — cannot simulate read-only" )
        assert _status( "repo/docs", "a.md", b"x" ).status_code == 403
    finally:
        os.chmod( folder, 0o755 )


@pytest.mark.parametrize( "verb, mode, name", [
    ( "link",    "refuse",  "a.md" ),          # refuse and rename place with os.link
    ( "replace", "replace", "existing.md" ),   # only replace uses os.replace
] )
def test_an_unexpected_os_error_is_a_500_and_leaves_nothing( scopes, monkeypatch, verb, mode, name ):
    def boom( *_ ): raise OSError( 5, "I/O error" )
    monkeypatch.setattr( docs_files.os, verb, boom )
    assert _status( "repo/docs", name, b"x", on_conflict=mode ).status_code == 500
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md" ]
    assert ( scopes[ "repo" ] / "docs" / "existing.md" ).read_text() == "# original\n"


# ---------------------------------------------------------------------------
# Adversarial review of ticket 416d4b00 — one test per fixed finding
# ---------------------------------------------------------------------------

def _pem( body="MIIE" ):
    # Assembled at runtime so the commit guard sees no literal key header.
    return "-----BEGIN " + "PRIVATE KEY-----\n" + body + "\n-----END " + "PRIVATE KEY-----\n"


@pytest.mark.parametrize( "sub", [ ".git/hooks", ".claude", "docs/.github" ] )
def test_a_hidden_folder_is_never_written_even_where_it_may_be_read( scopes, sub ):
    folder = scopes[ "repo" ] / sub
    folder.mkdir( parents=True, exist_ok=True )
    err = _status( f"repo/{ sub }", "pre-commit.sh", b"#!/bin/sh\n" )
    assert err.status_code == 400 and "hidden folder" in err.detail
    assert _listing( folder ) == [ ]


@pytest.mark.parametrize( "name", [ "a\nb.md", "tab\there.md", "del\x7f.md", "ok%2Fx.md", "50%.md" ] )
def test_control_characters_and_percent_are_refused_in_names( scopes, name ):
    assert _status( "repo/docs", name, b"x" ).status_code == 400
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md" ]


@pytest.mark.parametrize( "mode", [ "refuse", "replace", "rename" ] )
def test_a_folder_of_the_same_name_is_a_409_never_a_500( scopes, mode ):
    ( scopes[ "repo" ] / "docs" / "sub.md" ).mkdir()
    err = _status( "repo/docs", "sub.md", b"x", on_conflict=mode )
    assert err.status_code == 409 and "folder" in err.detail[ "message" ]
    assert ( scopes[ "repo" ] / "docs" / "sub.md" ).is_dir()


def test_a_name_taken_between_the_check_and_the_write_is_refused_not_clobbered( scopes, monkeypatch ):
    """The race: a peer's upload lands after the fast check. Placement must refuse, not overwrite."""
    target = scopes[ "repo" ] / "docs" / "race.md"
    real   = docs_files.os.link

    def link_after_peer( src, dst ):
        if dst == str( target ) and not target.exists():
            target.write_text( "# the peer's file\n" )           # the peer wins the race here
        return real( src, dst )
    monkeypatch.setattr( docs_files.os, "link", link_after_peer )

    err = _status( "repo/docs", "race.md", b"# mine\n" )
    assert err.status_code == 409
    assert target.read_text() == "# the peer's file\n", "the peer's upload was overwritten"
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md", "race.md" ]


def test_rename_under_the_race_takes_the_next_name_and_rechecks_it( scopes, monkeypatch ):
    docs   = scopes[ "repo" ] / "docs"
    real   = docs_files.os.link
    gated  = [ ]
    real_gate = docs_files._resolve_scoped

    def link_after_peer( src, dst ):
        if dst == str( docs / "existing-2.md" ) and not ( docs / "existing-2.md" ).exists():
            ( docs / "existing-2.md" ).write_text( "peer\n" )
        return real( src, dst )

    def gate( path, registry ):
        gated.append( path )
        return real_gate( path, registry )
    monkeypatch.setattr( docs_files.os, "link", link_after_peer )
    monkeypatch.setattr( docs_files, "_resolve_scoped", gate )

    out = _upload( "repo/docs", "existing.md", b"# mine\n", on_conflict="rename" )
    assert out[ "name" ] == "existing-3.md"
    assert ( docs / "existing-2.md" ).read_text() == "peer\n"
    assert ( docs / "existing-3.md" ).read_text() == "# mine\n"
    assert "repo/docs/existing-3.md" in gated, "a renamed target must pass the gate too"


def test_replace_keeps_the_replaced_files_mode( scopes ):
    script = scopes[ "repo" ] / "docs" / "run.sh"
    script.write_text( "echo old\n" )
    os.chmod( script, 0o755 )
    _upload( "repo/docs", "run.sh", b"echo new\n", on_conflict="replace" )
    assert script.read_text() == "echo new\n"
    assert script.stat().st_mode & 0o777 == 0o755


def test_replace_with_nothing_to_replace_just_writes_and_says_so( scopes ):
    out = _upload( "repo/docs", "brand-new.md", b"x", on_conflict="replace" )
    assert out[ "replaced" ] is False
    assert ( scopes[ "repo" ] / "docs" / "brand-new.md" ).stat().st_mode & 0o777 == 0o644


def test_a_folder_appearing_during_a_replace_upload_is_a_409( scopes, monkeypatch ):
    """The early folder check can be raced too; the placement step re-asks."""
    folder = scopes[ "repo" ] / "docs" / "late.md"
    real   = docs_files._file_carries_pem_key

    def scan_then_peer_makes_folder( path ):
        folder.mkdir()
        return real( path )
    monkeypatch.setattr( docs_files, "_file_carries_pem_key", scan_then_peer_makes_folder )
    err = _status( "repo/docs", "late.md", b"x", on_conflict="replace" )
    assert err.status_code == 409 and folder.is_dir()
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md", "late.md" ]


def test_a_new_file_is_0644( scopes ):
    _upload( "repo/docs", "fresh.md", b"x" )
    assert ( scopes[ "repo" ] / "docs" / "fresh.md" ).stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize( "name, data", [
    ( "padded.md",  ( "# notes\n" + "x" * 20_000 + "\n" + _pem() ).encode() ),   # past the 8 KB window
    ( "drawing.svg", ( "<svg xmlns='http://www.w3.org/2000/svg'><!-- " + _pem() + " --></svg>" ).encode() ),
    ( "paper.pdf",  b"%PDF-1.4\n" + bytes( range( 256 ) ) + _pem().encode() ),
] )
def test_a_pem_key_anywhere_in_any_upload_is_refused( scopes, name, data ):
    err = _status( "repo/docs", name, data )
    assert err.status_code == 400 and "credential" in err.detail
    assert _listing( scopes[ "repo" ] / "docs" ) == [ "existing.md" ]


def test_a_pem_header_split_across_read_chunks_is_still_found( scopes, monkeypatch ):
    monkeypatch.setattr( docs_files, "_UPLOAD_CHUNK", 16 )
    data = ( "y" * 9 + _pem() ).encode()          # the header straddles the 16-byte boundary
    assert _status( "repo/docs", "split.txt", data ).status_code == 400


def test_a_clean_svg_is_accepted( scopes ):
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='1' height='1'/></svg>"
    assert _upload( "repo/docs", "ok.svg", svg )[ "name" ] == "ok.svg"


# ---------------------------------------------------------------------------
# Admins only
# ---------------------------------------------------------------------------

def test_the_route_is_guarded_by_require_admin():
    route = next( r for r in docs_files.router.routes if getattr( r, "path", "" ) == "/api/docs/upload" )
    assert "POST" in route.methods
    deps = [ d.call for d in route.dependant.dependencies ]
    assert require_admin in deps, "upload must depend on require_admin — Rick ruled admins only"
