"""
The day-before re-check of a frozen need set, on a real index before and after an edit.

Both generations come from symindex.build on one fixture tree, so ids, pins and docstrings are the real ones.
"""
import json
import os
import stat

import pytest

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates import freshness as fr
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import finalize, freeze, keys, revalidate, schema
from tests.unit.symindex_helpers import make_repo
from tests.unit.test_reuse_needset_final import AGREED, COMMIT, DRAFTER, checked
from tests.unit.test_reuse_needset_keys import absence_world

EXPECTED = { "rows": 5, "matched": 4, "nothing": 1, "ts": 0, "py": 5 }
BEFORE   = ( 'def alpha( x ):\n    """Adds one."""\n    return x + 1\n\n\ndef beta( x ):\n    """Doubles."""\n    return x * 2\n\n\n'
             'def delta( x ):\n    """Negates."""\n    return -x\n' )
AFTER    = ( 'def alpha_renamed( x ):\n    """Adds one."""\n    return x + 1\n\n\ndef delta( x ):\n    """Negates."""\n    return -x\n\n\n'
             'def gamma_new( x ):\n    """Negates the value."""\n    return 0 - x\n\n\ndef lookup_new( x ):\n    """Looks a thing up."""\n    return x\n' )
SENTENCES = [ f"A function that does job number {n} and hands the result back to the caller after a check." for n in range( 5 ) ]


def sym( gen, name ):
    """Return the id in a generation whose name is name."""
    return next( i for i, r in revalidate.read_index( gen ).items() if r[ "name" ] == name )


def vectors_for( base, name, gen ):
    """Write a vector set folder with real build info for a generation."""
    folder = base / name
    folder.mkdir()
    fr.write_build_info( folder, sx_build.read_header( gen ), "2026-10-25T12:00:00+00:00" )
    return folder


def world( base, edit=AFTER ):
    """
    Freeze a 5-need set on the first tree, then build the index of the edited tree.

    Returns a namespace-like dict: set folder, root, old and new generations, new vectors, the needs by name.
    """
    root = make_repo( base, "tree" )
    ( root / "pkg" / "extra.py" ).write_text( BEFORE, encoding="utf-8" )
    old  = sx_build.build( root, base / "out_old" )[ "gen_dir" ]
    keyed = { "alpha": [ sym( old, "alpha" ) ], "beta": [ sym( old, "beta" ) ], "delta": [ sym( old, "delta" ) ], "public_fn": [ sym( old, "public_fn" ) ] }
    needs = [ checked( schema.new_need( "near_copy", "py", f"seed.{n}", None, k, "py", "twin", SENTENCES[ i ], COMMIT, DRAFTER ) ) for i, ( n, k ) in enumerate( keyed.items() ) ]
    needs.append( checked( schema.new_need( "nothing", "py", None, None, [], None, None, SENTENCES[ 4 ], COMMIT, DRAFTER ) ) )
    folder = base / "set"
    folder.mkdir()
    identity = freeze.freeze( old, vectors_for( base, "vec_old", old ), folder / freeze.FROZEN_DIR )
    finalize.finalize( needs, { n[ "id" ]: dict( AGREED ) for n in needs }, 0.6, 1, COMMIT, identity, folder )
    ( root / "pkg" / "extra.py" ).write_text( edit, encoding="utf-8" )
    new = sx_build.build( root, base / "out_new" )[ "gen_dir" ]
    return { "folder": folder, "root": root, "old": old, "new": new, "vectors": vectors_for( base, "vec_new", new ), "needs": needs, "ids": { n: n for n in keyed } }


def find( w, index ):
    """Return the need whose key is the symbol named index (a name in the first tree)."""
    sid = sym( w[ "old" ], index )
    return next( n for n in w[ "needs" ] if n[ "key" ][ "symbols" ] == [ sid ] )


def fake_evidence( w ):
    """Return an evidence function: a new twin for delta, new definitions for the nothing need."""
    twin, lookup = sym( w[ "new" ], "gamma_new" ), sym( w[ "new" ], "lookup_new" )
    old_one      = sym( w[ "new" ], "public_fn" )
    table        = { SENTENCES[ 2 ]: { "words": [ twin ], "vectors": [ old_one ] }, SENTENCES[ 4 ]: { "words": [ old_one, lookup ], "vectors": [ lookup ] } }
    return lambda text: table.get( text, { "words": [], "vectors": [] } )


def source_of( w ): return revalidate.source_reader( w[ "root" ], revalidate.read_index( w[ "new" ] ) )


def code_of( call ):
    """Return the NeedsetError code a call raises."""
    with pytest.raises( er.NeedsetError ) as e: call()
    return e.value.code


def open_up( folder ):
    """Make a frozen folder writable so pytest can remove it."""
    for r, _, _ in os.walk( folder ): os.chmod( r, 0o755 )


def test_the_report_lists_the_renamed_and_the_deleted_key_the_new_twin_and_the_new_near_a_nothing_need( tmp_path ):
    w   = world( tmp_path )
    got = revalidate.revalidate( w[ "folder" ], w[ "new" ], fake_evidence( w ), 2, source_of( w ), EXPECTED )
    rep = got[ "report" ]
    alpha, beta, delta, nothing = find( w, "alpha" ), find( w, "beta" ), find( w, "delta" ), w[ "needs" ][ 4 ]
    assert rep[ "broken_keys" ] == sorted( [ { "need": alpha[ "id" ], "symbol": sym( w[ "old" ], "alpha" ), "state": "renamed", "renamed_to": sym( w[ "new" ], "alpha_renamed" ) },
                                             { "need": beta[ "id" ], "symbol": sym( w[ "old" ], "beta" ), "state": "deleted", "renamed_to": None } ], key=lambda b: b[ "need" ] )
    assert rep[ "new_twins" ] == { delta[ "id" ]: [ sym( w[ "new" ], "gamma_new" ) ] }
    assert rep[ "near_nothing" ] == { nothing[ "id" ]: [ sym( w[ "new" ], "lookup_new" ) ] }
    assert ( rep[ "added" ], rep[ "removed" ], rep[ "flagged" ] ) == ( 3, 2, 4 )
    assert rep[ "frozen" ] == { k: json.loads( ( w[ "folder" ] / finalize.MANIFEST_FILE ).read_text() )[ k ] for k in freeze.IDENTITY_KEYS }
    open_up( w[ "folder" ] )


def test_flags_are_sorted_with_their_reasons_and_the_items_hold_no_reason_and_show_the_candidates( tmp_path ):
    w     = world( tmp_path )
    got   = revalidate.revalidate( w[ "folder" ], w[ "new" ], fake_evidence( w ), 2, source_of( w ), EXPECTED )
    byid  = { f[ "id" ]: f[ "reasons" ] for f in got[ "flags" ] }
    ids   = [ f[ "id" ] for f in got[ "flags" ] ]
    assert ids == sorted( ids ) and len( ids ) == 4
    assert byid[ find( w, "alpha" )[ "id" ] ] == [ "broken_key" ] and byid[ find( w, "beta" )[ "id" ] ] == [ "broken_key" ]
    assert byid[ find( w, "delta" )[ "id" ] ] == [ "new_twin_candidate" ] and byid[ w[ "needs" ][ 4 ][ "id" ] ] == [ "near_nothing_need" ]
    assert find( w, "public_fn" )[ "id" ] not in byid
    items = { i[ "item_id" ]: i for i in got[ "items" ] }
    assert [ i[ "item_id" ] for i in got[ "items" ] ] == ids
    text  = json.dumps( got[ "items" ] )
    assert "broken_key" not in text and "new_twin" not in text and "near_nothing" not in text and "reasons" not in text and "renamed_to" not in text
    shown = items[ find( w, "delta" )[ "id" ] ][ "payload" ][ "key_sources" ]
    assert len( shown ) == 2 and any( "def delta" in s for s in shown ) and any( "def gamma_new" in s for s in shown )
    beta_id = sym( w[ "old" ], "beta" )
    assert items[ find( w, "beta" )[ "id" ] ][ "payload" ][ "key_sources" ] == [ f"{beta_id} (no longer in the index; it was function beta(x): Doubles.)" ]
    alpha_shown = items[ find( w, "alpha" )[ "id" ] ][ "payload" ][ "key_sources" ]
    assert len( alpha_shown ) == 2 and alpha_shown[ 0 ].startswith( sym( w[ "new" ], "alpha_renamed" ) + "\ndef alpha_renamed" ) and "no longer in the index" in alpha_shown[ 1 ]
    assert items[ w[ "needs" ][ 4 ][ "id" ] ][ "payload" ][ "nothing_exists" ] is True and "def lookup_new" in items[ w[ "needs" ][ 4 ][ "id" ] ][ "payload" ][ "hits" ][ 0 ]
    open_up( w[ "folder" ] )


def test_only_the_first_top_ids_of_each_list_count_as_near( tmp_path ):
    w   = world( tmp_path )
    one = revalidate.revalidate( w[ "folder" ], w[ "new" ], fake_evidence( w ), 1, source_of( w ), EXPECTED )[ "report" ]
    assert one[ "near_nothing" ] == { w[ "needs" ][ 4 ][ "id" ]: [ sym( w[ "new" ], "lookup_new" ) ] }
    only_tail = lambda text: { "words": [ sym( w[ "new" ], "public_fn" ), sym( w[ "new" ], "gamma_new" ) ], "vectors": [] }
    assert revalidate.revalidate( w[ "folder" ], w[ "new" ], only_tail, 1, source_of( w ), EXPECTED )[ "report" ][ "new_twins" ] == {}
    open_up( w[ "folder" ] )


@pytest.mark.parametrize( "top", [ 0, -1, True, "3", 2.5 ] )
def test_top_must_be_a_positive_whole_number( tmp_path, top ):
    w = world( tmp_path )
    assert code_of( lambda: revalidate.revalidate( w[ "folder" ], w[ "new" ], fake_evidence( w ), top, source_of( w ), EXPECTED ) ) == er.BAD_NEED
    open_up( w[ "folder" ] )


def test_a_manifest_that_names_another_index_or_vector_set_is_refused_before_any_diff( tmp_path ):
    w    = world( tmp_path )
    path = w[ "folder" ] / finalize.MANIFEST_FILE
    good = json.loads( path.read_text() )
    for key, code in ( ( "symbols_sha", er.INDEX_DIFFERS ), ( "vector_build_info_sha", er.VECTORS_DIFFER ) ):
        path.write_text( json.dumps( dict( good, **{ key: "0" * 40 } ) ) )
        assert code_of( lambda: revalidate.load_frozen( w[ "folder" ], EXPECTED ) ) == code
    path.write_text( json.dumps( good ) )
    manifest, needs, old = revalidate.load_frozen( w[ "folder" ], EXPECTED )
    assert manifest == good and len( needs ) == 5 and sym( w[ "old" ], "alpha" ) in old and sym( w[ "new" ], "gamma_new" ) not in old
    open_up( w[ "folder" ] )


def test_a_key_the_old_index_never_held_reads_as_deleted():
    need = { "id": "n1", "key": { "symbols": [ "ghost" ] } }
    assert revalidate.broken_keys( [ need ], {}, {} ) == [ { "need": "n1", "symbol": "ghost", "state": "deleted", "renamed_to": None } ]


def test_two_new_definitions_with_the_old_shape_are_not_called_a_rename():
    rec = lambda i: { "id": i, "file": "f.py", "kind": "function", "sig": "( x )", "doc_full": "Adds one." }
    old = { "a": rec( "a" ) }
    new = { "b": rec( "b" ), "c": rec( "c" ) }
    assert revalidate.broken_keys( [ { "id": "n", "key": { "symbols": [ "a" ] } } ], old, new )[ 0 ]["state"] == "deleted"
    assert revalidate.broken_keys( [ { "id": "n", "key": { "symbols": [ "a" ] } } ], old, { "b": rec( "b" ) } )[ 0 ][ "renamed_to" ] == "b"


def test_the_refreeze_is_refused_while_a_key_is_broken_and_writes_nothing( tmp_path ):
    w   = world( tmp_path )
    got = revalidate.revalidate( w[ "folder" ], w[ "new" ], fake_evidence( w ), 2, source_of( w ), EXPECTED )
    dest = tmp_path / "next"
    dest.mkdir()
    with pytest.raises( er.NeedsetError ) as e: revalidate.refreeze( w[ "folder" ], w[ "new" ], w[ "vectors" ], dest / "x", got, tmp_path / "r.json", EXPECTED )
    assert e.value.code == er.REVALIDATION_OPEN and ( "alpha" in e.value.detail or "beta" in e.value.detail )
    assert list( dest.iterdir() ) == []
    open_up( w[ "folder" ] )


INTACT = BEFORE + '\n\ndef gamma_new( x ):\n    """Negates the value."""\n    return 0 - x\n\n\ndef lookup_new( x ):\n    """Looks a thing up."""\n    return x\n'


def test_a_refreeze_over_unbroken_keys_writes_a_verified_manifest_with_the_new_hashes_and_the_old_ones_kept( tmp_path ):
    w    = world( tmp_path, edit=INTACT )
    got  = revalidate.revalidate( w[ "folder" ], w[ "new" ], fake_evidence( w ), 2, source_of( w ), EXPECTED )
    assert got[ "report" ][ "broken_keys" ] == []
    report = tmp_path / "r.json"
    report.write_text( json.dumps( got[ "report" ] ), encoding="utf-8" )
    dest = tmp_path / "next"
    new  = revalidate.refreeze( w[ "folder" ], w[ "new" ], w[ "vectors" ], dest, got, report, EXPECTED )
    old  = json.loads( ( w[ "folder" ] / finalize.MANIFEST_FILE ).read_text() )
    now  = freeze.identity( w[ "new" ], w[ "vectors" ] )
    assert { k: new[ k ] for k in freeze.IDENTITY_KEYS } == now and now[ "symbols_sha" ] != old[ "symbols_sha" ]
    assert new[ "refrozen_from" ] == { **{ k: old[ k ] for k in freeze.IDENTITY_KEYS }, "final_sha256": old[ "final_sha256" ], "report_sha256": finalize.file_sha256( report ) }
    assert new[ "final_sha256" ] == old[ "final_sha256" ] and ( dest / finalize.FINAL_FILE ).read_bytes() == ( w[ "folder" ] / finalize.FINAL_FILE ).read_bytes()
    assert json.loads( ( dest / finalize.MANIFEST_FILE ).read_text() ) == new and stat.S_IMODE( os.stat( dest / "frozen" / "index" / "header.json" ).st_mode ) == 0o444
    assert revalidate.load_frozen( dest, EXPECTED )[ 0 ] == new
    open_up( w[ "folder" ] ); open_up( dest )


def test_real_evidence_runs_the_word_and_vector_search_of_the_new_index():
    stage, vectors, _ = absence_world()
    asked = []
    def embed( text ):
        asked.append( text )
        return [ 1.0, 0.0 ]
    got = revalidate.real_evidence( stage, vectors, embed, 3 )( "parse the thing" )
    assert asked == [ "parse the thing" ] and len( got[ "words" ] ) == 3 and got[ "vectors" ][ 0 ] == "pkg.m.f0" and set( got ) == { "words", "vectors" }
    assert got == keys.absence_evidence( "parse the thing", stage, vectors, [ 1.0, 0.0 ], top=3 )


def test_the_source_reader_returns_the_id_then_the_lines_of_the_definition( tmp_path ):
    w = world( tmp_path )
    assert source_of( w )( sym( w[ "new" ], "gamma_new" ) ) == sym( w[ "new" ], "gamma_new" ) + '\ndef gamma_new( x ):\n    """Negates the value."""\n    return 0 - x'
    open_up( w[ "folder" ] )


def argv( w, tmp_path, *more ):
    """Return the command line for the world."""
    return [ "--frozen-dir", str( w[ "folder" ] ), "--new-index", str( w[ "new" ] ), "--new-vectors", str( w[ "vectors" ] ), "--root", str( w[ "root" ] ),
             "--query-cache-dir", str( tmp_path / "q" ), "--out", str( tmp_path / "out" ), "--top", "2", *more ]


def test_main_writes_the_report_and_the_items_and_refuses_a_refreeze_while_a_key_is_broken( tmp_path, monkeypatch ):
    w = world( tmp_path )
    monkeypatch.setattr( finalize, "EXPECTED", EXPECTED )
    parts = lambda args: ( fake_evidence( w ), source_of( w ) )
    rep   = revalidate.main( argv( w, tmp_path ), parts )
    out   = tmp_path / "out"
    assert rep[ "flagged" ] == 4 and json.loads( ( out / revalidate.REPORT_FILE ).read_text() )[ "flags" ] and len( json.loads( ( out / "needset-revalidation-items.json" ).read_text() ) ) == 4
    assert code_of( lambda: revalidate.main( argv( w, tmp_path, "--refreeze", str( tmp_path / "next" ) ), parts ) ) == er.REVALIDATION_OPEN and not ( tmp_path / "next" ).exists()
    open_up( w[ "folder" ] )


def test_main_with_a_refreeze_writes_the_new_set_beside_the_report( tmp_path, monkeypatch ):
    w = world( tmp_path, edit=INTACT )
    monkeypatch.setattr( finalize, "EXPECTED", EXPECTED )
    revalidate.main( argv( w, tmp_path, "--refreeze", str( tmp_path / "next" ) ), lambda args: ( fake_evidence( w ), source_of( w ) ) )
    assert json.loads( ( tmp_path / "next" / finalize.MANIFEST_FILE ).read_text() )[ "refrozen_from" ][ "report_sha256" ] == finalize.file_sha256( tmp_path / "out" / revalidate.REPORT_FILE )
    open_up( w[ "folder" ] ); open_up( tmp_path / "next" )


def test_every_option_but_refreeze_is_required():
    with pytest.raises( SystemExit ): revalidate.parse_args( [ "--top", "2" ] )
    ok = revalidate.parse_args( [ "--frozen-dir", "a", "--new-index", "b", "--new-vectors", "c", "--root", "d", "--query-cache-dir", "e", "--out", "f", "--top", "2" ] )
    assert ok.top == 2 and ok.refreeze is None


def test_a_gone_line_without_an_old_record_or_a_docstring_still_names_the_id():
    assert revalidate.gone_line( "x.y", {} ) == "x.y (no longer in the index)"
    assert revalidate.gone_line( "x.y", { "x.y": { "kind": "function", "name": "y", "sig": "()", "doc_full": "" } } ) == "x.y (no longer in the index; it was function y(): )"
