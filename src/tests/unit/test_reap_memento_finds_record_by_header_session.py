"""
The reap finds a seat's io record by the session id in its header, not by file name.

Two seats wrote valid records as `mr-radio-author-d9d3c344.md` and `john-c007a72f.md`.
The reap read only the bare slot, which held another session's record, and answered
prior_holder_present. These tests pin the directory lookup by header.
"""

import datetime

from lupin_mcp import reap_memento

UTC  = datetime.timezone.utc
_NOW = datetime.datetime( 2026, 10, 14, 22, 30, 0, tzinfo=UTC )
_TS  = "2026-10-14T22:27:00+00:00"
_DIR = "/repo/io/mementos"


def _record( persona, sid8, written_at=_TS ):
    return ( f"<!-- memento-record: persona={persona} session_id={sid8} "
             f"written_at={written_at} slot=io -->\n" + ( "x" * 1200 ) )


def _resolve( files, persona="Maya", sid8="d9d3c344", listing=None ):
    names = listing if listing is not None else [ p.rsplit( "/", 1 )[ -1 ] for p in files
                                                  if p.startswith( _DIR + "/" ) ]
    return reap_memento.verify_seat_memento_at_any_readable_slot(
        "/repo", persona, sid8, _NOW,
        read_text_fn=lambda p: files.get( str( p ) ),
        list_dir_fn=lambda d: names if str( d ) == _DIR else [] )


def test_record_under_a_name_the_slot_derivation_does_not_produce_is_found():
    files = { f"{_DIR}/maya.md"                       : _record( "maya", "b1188cac" ),
              f"{_DIR}/mr-radio-author-d9d3c344.md"   : _record( "mr-radio-author", "d9d3c344" ) }
    usable, reason, slot = _resolve( files )
    assert usable is True
    assert str( slot ) == f"{_DIR}/mr-radio-author-d9d3c344.md"
    assert "found by header session_id" in reason


def test_a_name_that_carries_no_session_suffix_is_still_found_by_its_header():
    files = { f"{_DIR}/notes.md": _record( "maya", "d9d3c344" ) }
    usable, _reason, slot = _resolve( files )
    assert usable is True and str( slot ).endswith( "/notes.md" )


def test_a_prior_holders_record_is_never_adopted():
    files = { f"{_DIR}/maya.md"            : _record( "maya", "b1188cac" ),
              f"{_DIR}/john-c007a72f.md"   : _record( "john", "c007a72f" ) }
    usable, reason, slot = _resolve( files )
    assert usable is False
    assert str( slot ) == f"{_DIR}/maya.md"
    assert "prior holder" in reason


def test_a_matching_record_that_is_stale_is_not_usable():
    files = { f"{_DIR}/x-d9d3c344.md": _record( "x", "d9d3c344", written_at="2026-10-13T01:00:00+00:00" ) }
    usable, _reason, _slot = _resolve( files )
    assert usable is False


def test_unreadable_non_markdown_and_headerless_files_are_skipped():
    files = { f"{_DIR}/readme.txt": "hi", f"{_DIR}/hand.md": "no header here" }
    usable, _r, _s = _resolve( files, listing=[ "readme.txt", "hand.md", "gone.md" ] )
    assert usable is False


def test_the_default_directory_lister_returns_nothing_for_a_missing_directory( tmp_path ):
    assert reap_memento._default_list_dir( str( tmp_path / "absent" ) ) == []


def test_the_default_directory_lister_lists_a_real_directory( tmp_path ):
    ( tmp_path / "a.md" ).write_text( "x" )
    assert reap_memento._default_list_dir( str( tmp_path ) ) == [ "a.md" ]


def test_coordinate_mementos_verifies_without_asking_when_the_record_is_elsewhere( monkeypatch, tmp_path ):
    io = tmp_path / "io" / "mementos"
    io.mkdir( parents=True )
    ( io / "mr-radio-author-d9d3c344.md" ).write_text( _record( "mr-radio-author", "d9d3c344" ) )
    asked = []
    ident = { "persona": "Maya", "session_id": "d9d3c344-0000-0000-0000-000000000000", "cwd": str( tmp_path ) }
    monkeypatch.setattr( reap_memento, "seat_repo_root", lambda i: str( tmp_path ) )
    out = reap_memento.coordinate_mementos(
        { "seat": ident }, write_memento=True, now_fn=lambda: _NOW,
        dm_fn=lambda *a: asked.append( a ), sleep_fn=lambda s: None )
    assert out[ "seat" ][ "status" ] == "verified" and asked == []


def test_an_unknown_seat_session_adopts_nothing():
    files = { f"{_DIR}/a.md": _record( "a", "d9d3c344" ) }
    assert reap_memento._find_record_by_header_session(
        _DIR, "", lambda p: files.get( str( p ) ), lambda d: [ "a.md" ] ) is None
