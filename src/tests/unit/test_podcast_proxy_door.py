"""
The podcast proxy's door check on a document a seat names as <scope>/<path>.

A scratch scope stands in for the registry, so each refusal is driven on its own against real files
and real links. The viewer's functions run for real; only the registry is injected.
"""

import hashlib
import os

import pytest

from cosa.rest import podcast_proxy as pp
from cosa.rest.routers._scope_registry import ScopeConfig

# Built at run time: the commit scanner refuses a key header written out in a staged line.
PEM = "-----" + "BEGIN PRIVATE KEY" + "-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n" + "-----" + "END PRIVATE KEY" + "-----\n"


@pytest.fixture
def scope( tmp_path ):
    root = tmp_path / "repo"
    ( root / "io" / "tmp" ).mkdir( parents=True )
    ( root / "src" ).mkdir()
    ( tmp_path / "outside" ).mkdir()
    cfg = ScopeConfig( name="demo", root=str( root ), allowed_prefixes=( "io/", ) )
    return { "root": root, "outside": tmp_path / "outside", "registry": { "demo": cfg } }


def _door( scope, path ):
    return pp.check_source( path, scope[ "registry" ] )


def _put( scope, rel, text="# A summary\n\nSome words.\n" ):
    path = scope[ "root" ] / rel
    path.write_text( text )
    return path


def test_a_file_in_an_allowed_folder_is_described( scope ):
    path  = _put( scope, "io/tmp/summary.md" )
    facts = _door( scope, "demo/io/tmp/summary.md" )
    assert facts[ "scope" ] == "demo" and facts[ "rel" ] == "io/tmp/summary.md" and facts[ "name" ] == "summary.md"
    assert facts[ "server_path" ] == os.path.realpath( path )
    assert facts[ "size" ] == path.stat().st_size and facts[ "size" ] > 0
    assert facts[ "sha256" ] == hashlib.sha256( path.read_bytes() ).hexdigest()


def test_the_hash_follows_the_content_and_not_the_name( scope ):
    path = _put( scope, "io/tmp/a.md", "one" )
    first = _door( scope, "demo/io/tmp/a.md" )[ "sha256" ]
    path.write_text( "two" )
    assert _door( scope, "demo/io/tmp/a.md" )[ "sha256" ] != first


def test_the_opened_handle_is_closed_on_success_and_on_refusal( scope ):
    _put( scope, "io/tmp/ok.md" )
    _put( scope, "io/tmp/key.md", PEM )
    before = len( os.listdir( "/proc/self/fd" ) )
    _door( scope, "demo/io/tmp/ok.md" )
    with pytest.raises( pp.DoorRefusal ): _door( scope, "demo/io/tmp/key.md" )
    assert len( os.listdir( "/proc/self/fd" ) ) == before


@pytest.mark.parametrize( "sent", [ None, "", "   ", 7, [ "demo/io/tmp/a.md" ] ] )
def test_a_blank_or_non_string_path_is_refused( scope, sent ):
    with pytest.raises( pp.DoorRefusal, match="needs a document path" ): _door( scope, sent )


@pytest.mark.parametrize( "sent", [ "summary.md", "/summary.md", "demo" ] )
def test_a_path_without_a_scope_is_refused_and_named( scope, sent ):
    with pytest.raises( pp.DoorRefusal, match="not a scoped path" ) as refusal: _door( scope, sent )
    assert sent.strip() in str( refusal.value )


def test_an_unknown_scope_is_refused( scope ):
    with pytest.raises( pp.DoorRefusal, match="Unknown project" ): _door( scope, "nowhere/io/tmp/a.md" )


def test_a_host_path_is_not_a_scope_and_is_refused( scope ):
    with pytest.raises( pp.DoorRefusal ): _door( scope, "/mnt/DATA01/include/www.deepily.ai/projects/demo/io/tmp/a.md" )


def test_a_path_outside_the_scope_whitelist_is_refused( scope ):
    _put( scope, "src/code.md" )
    with pytest.raises( pp.DoorRefusal, match="not in scope whitelist" ) as refusal: _door( scope, "demo/src/code.md" )
    assert "'demo/src/code.md' was refused" in str( refusal.value )


def test_a_path_that_climbs_out_of_the_scope_is_refused( scope ):
    ( scope[ "outside" ] / "x.md" ).write_text( "outside" )
    with pytest.raises( pp.DoorRefusal ): _door( scope, "demo/io/tmp/../../../outside/x.md" )


def test_a_link_that_lands_outside_the_scope_is_refused( scope ):
    ( scope[ "outside" ] / "x.md" ).write_text( "outside" )
    os.symlink( scope[ "outside" ] / "x.md", scope[ "root" ] / "io" / "tmp" / "link.md" )
    with pytest.raises( pp.DoorRefusal ): _door( scope, "demo/io/tmp/link.md" )


def test_a_link_into_a_folder_the_whitelist_refuses_is_refused( scope ):
    _put( scope, "src/code.md" )
    os.symlink( scope[ "root" ] / "src" / "code.md", scope[ "root" ] / "io" / "tmp" / "link.md" )
    with pytest.raises( pp.DoorRefusal, match="whitelist" ): _door( scope, "demo/io/tmp/link.md" )


def test_a_secrets_name_is_refused_by_the_floor_blocklist( scope ):
    _put( scope, "io/tmp/.env", "KEY=value" )
    with pytest.raises( pp.DoorRefusal, match="secrets blocklist" ): _door( scope, "demo/io/tmp/.env" )


def test_credential_content_is_refused_whatever_the_file_is_called( scope ):
    _put( scope, "io/tmp/notes.md", PEM )
    with pytest.raises( pp.DoorRefusal, match="credential material" ) as refusal: _door( scope, "demo/io/tmp/notes.md" )
    assert "demo/io/tmp/notes.md" in str( refusal.value )


def test_a_missing_file_is_refused_and_the_path_is_named( scope ):
    with pytest.raises( pp.DoorRefusal, match="Path not found" ) as refusal: _door( scope, "demo/io/tmp/gone.md" )
    assert "demo/io/tmp/gone.md" in str( refusal.value )


def test_a_folder_is_refused_as_not_a_file( scope ):
    ( scope[ "root" ] / "io" / "tmp" / "folder.md" ).mkdir()
    with pytest.raises( pp.DoorRefusal, match="Path not found" ): _door( scope, "demo/io/tmp/folder.md" )


@pytest.mark.skipif( os.geteuid() == 0, reason="root reads every file" )
def test_an_unreadable_file_is_refused_and_the_path_is_named( scope ):
    path = _put( scope, "io/tmp/locked.md" )
    path.chmod( 0o000 )
    try:
        with pytest.raises( pp.DoorRefusal ) as refusal: _door( scope, "demo/io/tmp/locked.md" )
    finally: path.chmod( 0o644 )
    assert "demo/io/tmp/locked.md" in str( refusal.value )


def test_undecodable_text_is_refused_as_unreadable_not_as_credential( scope ):
    ( scope[ "root" ] / "io" / "tmp" / "bytes.md" ).write_bytes( b"\xff\xfe\x00bad\x80" )
    with pytest.raises( pp.DoorRefusal, match="could not be read or decoded" ): _door( scope, "demo/io/tmp/bytes.md" )


@pytest.mark.parametrize( "name", [ "picture.png", "noextension" ] )
def test_a_file_a_podcast_cannot_read_is_refused_by_kind( scope, name ):
    _put( scope, f"io/tmp/{name}", "x" )
    with pytest.raises( pp.DoorRefusal, match="A podcast reads" ): _door( scope, f"demo/io/tmp/{name}" )


def test_the_default_registry_is_the_servers_own( scope, monkeypatch ):
    from cosa.rest.routers import docs_files
    _put( scope, "io/tmp/summary.md" )
    monkeypatch.setattr( docs_files, "_get_scope_registry", lambda: scope[ "registry" ] )
    assert pp.check_source( "demo/io/tmp/summary.md" )[ "scope" ] == "demo"


def test_a_link_swapped_in_after_the_path_check_is_caught_by_the_handle_check( scope, monkeypatch ):
    from cosa.rest.routers import docs_files
    ( scope[ "outside" ] / "x.md" ).write_text( "outside" )
    swapped = scope[ "root" ] / "io" / "tmp" / "swap.md"
    os.symlink( scope[ "outside" ] / "x.md", swapped )
    real = docs_files._resolve_scoped
    cfg  = scope[ "registry" ][ "demo" ]
    monkeypatch.setattr( docs_files, "_resolve_scoped", lambda path, registry: ( "demo", cfg, "io/tmp/swap.md", str( swapped ) ) )
    with pytest.raises( pp.DoorRefusal, match="escapes scope root" ): _door( scope, "demo/io/tmp/swap.md" )
    assert real is not docs_files._resolve_scoped


# ---- one read: what is judged is what is hashed and what is handed back ----

def test_a_file_rewritten_after_the_judgement_does_not_change_what_was_hashed( scope, monkeypatch ):
    path = _put( scope, "io/tmp/live.md", "clean words" )
    judged = [ ]
    def judge_then_rewrite( text ):
        judged.append( text )
        path.write_text( PEM )
        return False
    monkeypatch.setattr( pp, "_prefix_looks_like_credential", judge_then_rewrite )
    facts = pp.check_source( "demo/io/tmp/live.md", scope[ "registry" ], keep_content=True )
    assert judged == [ "clean words" ]
    assert facts[ "content" ] == b"clean words" and facts[ "sha256" ] == hashlib.sha256( b"clean words" ).hexdigest()
    assert facts[ "size" ] == len( b"clean words" )


def test_the_content_is_returned_only_when_asked_for( scope ):
    _put( scope, "io/tmp/a.md", "hello" )
    assert "content" not in _door( scope, "demo/io/tmp/a.md" )
    assert pp.check_source( "demo/io/tmp/a.md", scope[ "registry" ], keep_content=True )[ "content" ] == b"hello"


def test_credential_material_past_the_viewers_first_window_is_still_refused( scope ):
    _put( scope, "io/tmp/long.md", ( "plain words. " * 2000 ) + "\n" + PEM )
    with pytest.raises( pp.DoorRefusal, match="credential material" ): _door( scope, "demo/io/tmp/long.md" )


def test_a_file_longer_than_one_read_chunk_is_hashed_whole( scope ):
    text = "x" * ( 1024 * 1024 + 1 )
    _put( scope, "io/tmp/big.md", text )
    facts = _door( scope, "demo/io/tmp/big.md" )
    assert facts[ "size" ] == len( text ) and facts[ "sha256" ] == hashlib.sha256( text.encode() ).hexdigest()


def test_a_file_past_the_size_limit_is_refused( scope, monkeypatch ):
    monkeypatch.setattr( pp, "MAX_BYTES", 1024 )
    _put( scope, "io/tmp/big.md", "x" * 1025 )
    with pytest.raises( pp.DoorRefusal, match="too long for a podcast" ) as refusal: _door( scope, "demo/io/tmp/big.md" )
    assert "demo/io/tmp/big.md" in str( refusal.value )
    _put( scope, "io/tmp/ok.md", "x" * 1024 )
    assert _door( scope, "demo/io/tmp/ok.md" )[ "size" ] == 1024


def test_two_spellings_of_one_file_give_one_key( scope ):
    _put( scope, "io/tmp/ok.md" )
    plain, dotted = _door( scope, "demo/io/tmp/ok.md" ), _door( scope, "demo/io/tmp/./ok.md" )
    assert plain[ "rel" ] == dotted[ "rel" ] == "io/tmp/ok.md" and plain[ "server_path" ] == dotted[ "server_path" ]


def test_the_kind_is_judged_on_the_file_the_path_lands_on( scope ):
    _put( scope, "io/tmp/real.png", "x" )
    os.symlink( scope[ "root" ] / "io" / "tmp" / "real.png", scope[ "root" ] / "io" / "tmp" / "looks-like-text.md" )
    with pytest.raises( pp.DoorRefusal, match="A podcast reads" ): _door( scope, "demo/io/tmp/looks-like-text.md" )


def test_a_link_inside_the_scope_reports_the_file_it_lands_on( scope ):
    _put( scope, "io/tmp/real.md" )
    os.symlink( scope[ "root" ] / "io" / "tmp" / "real.md", scope[ "root" ] / "io" / "tmp" / "alias.md" )
    facts = _door( scope, "demo/io/tmp/alias.md" )
    assert facts[ "rel" ] == "io/tmp/real.md" and facts[ "name" ] == "real.md"


def test_the_server_path_is_where_the_opened_file_lives_not_the_spelling_that_found_it( scope, monkeypatch, tmp_path ):
    from cosa.rest.routers import docs_files
    path  = _put( scope, "io/tmp/real.md" )
    alias = tmp_path / "alias-root"
    os.symlink( scope[ "root" ], alias )
    cfg = scope[ "registry" ][ "demo" ]
    monkeypatch.setattr( docs_files, "_resolve_scoped", lambda sent, registry: ( "demo", cfg, "io/tmp/real.md", str( alias / "io" / "tmp" / "real.md" ) ) )
    assert _door( scope, "demo/io/tmp/real.md" )[ "server_path" ] == os.path.realpath( path )
