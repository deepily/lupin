"""
Finalizing a set and verifying its manifest, on a 400-row fixture.
"""
import copy
import json

import pytest

from lupin_mcp.reuse_needset import draft, finalize, schema
from lupin_mcp.reuse_needset import errors as er

COMMIT  = "0123456789abcdef0123456789abcdef01234567"
DRAFTER = { "model": draft.DRAFTER_MODEL, "prompt_version": "v1", "server": "max-plan" }
AGREED  = { "choice": "AS_PROPOSED", "symbols": [], "final_source": "agreed" }
FROZEN  = { "index_manifest": "a" * 64, "symbols_sha": "b" * 40, "vector_build_info_sha": "c" * 64 }


def checked( need, result="agree" ):
    """Return a copy of a drafted need, checked with the given result."""
    out = copy.deepcopy( need )
    out[ "check" ], out[ "status" ] = { "model": "claude-opus-5-5", "result": result, "note": "n", "mechanical": [] }, "checked"
    schema.validate_need( out )
    return out


def build_set( nothing=( 60, 40 ), matched=( 180, 120 ), model_agreed_nothing=0, disputed_model_agreed=0 ):
    """
    Return ( needs, labels ) for a set with the given ( ts, py ) counts.

    The first model_agreed_nothing nothing needs and the first disputed_model_agreed disputed matched needs carry a model-agreed label.
    """
    needs, labels = [], {}
    for lang, count in zip( ( "ts", "py" ), nothing ):
        for i in range( count ):
            need = checked( schema.new_need( "nothing", lang, None, None, [], None, None, f"A function that does {lang} job number {i} and returns the answer.", COMMIT, DRAFTER ) )
            needs.append( need )
            labels[ need[ "id" ] ] = dict( AGREED )
    for lang, count in zip( ( "ts", "py" ), matched ):
        for i in range( count ):
            result = "disagree" if i < disputed_model_agreed else "agree"
            need   = checked( schema.new_need( "near_copy", lang, f"pkg.{lang}.m{i}", None, [ f"pkg.{lang}.k{i}" ], lang, "twin", "A function that adds up a list of numbers until a ceiling.", COMMIT, DRAFTER ), result )
            needs.append( need )
            labels[ need[ "id" ] ] = { "choice": None, "symbols": None, "final_source": "model_agreed" } if result == "agree" and i % 2 == 0 else dict( AGREED )
    for need in [ n for n in needs if n[ "kind" ] == "nothing" ][ :model_agreed_nothing ]: labels[ need[ "id" ] ] = { "choice": None, "symbols": None, "final_source": "model_agreed" }
    for need in [ n for n in needs if n[ "kind" ] != "nothing" and n[ "check" ][ "result" ] != "agree" ][ :disputed_model_agreed ]: labels[ need[ "id" ] ] = { "choice": None, "symbols": None, "final_source": "model_agreed" }
    return needs, labels


def write_set( tmp_path, kappa=0.62, **kwargs ):
    """Finalize a fixture set into tmp_path and return the manifest path."""
    needs, labels = build_set( **kwargs )
    finalize.finalize( needs, labels, kappa, 7, COMMIT, FROZEN, tmp_path )
    return tmp_path / finalize.MANIFEST_FILE


def condition( path, expected=None ):
    """Return the condition name verify_manifest fails with, and its detail."""
    with pytest.raises( er.NeedsetError ) as e: finalize.verify_manifest( path, expected )
    assert e.value.code == er.MANIFEST_MISMATCH
    name, _, detail = e.value.detail.partition( ": " )
    return name, detail


def rewrite_rows( tmp_path, change ):
    """Apply change to the final rows, write them back and keep the manifest's sha in step."""
    final = tmp_path / finalize.FINAL_FILE
    rows  = [ change( json.loads( l ) ) for l in final.read_text().splitlines() ]
    final.write_text( "".join( json.dumps( r, sort_keys=True ) + "\n" for r in rows ), encoding="utf-8" )
    manifest = tmp_path / finalize.MANIFEST_FILE
    data = json.loads( manifest.read_text() )
    data[ "final_sha256" ] = finalize.file_sha256( final )
    manifest.write_text( json.dumps( data ), encoding="utf-8" )


def test_a_400_row_set_passes_and_its_manifest_holds_the_counts_the_seed_and_the_sha( tmp_path ):
    path = write_set( tmp_path )
    finalize.verify_manifest( path )
    manifest = json.loads( path.read_text() )
    ids = [ json.loads( l )[ "id" ] for l in ( tmp_path / finalize.FINAL_FILE ).read_text().splitlines() ]
    assert manifest[ "counts" ] == { "rows": 400, "matched": 300, "nothing": 100, "ts": 240, "py": 160 } and manifest[ "kappa" ] == 0.62 and manifest[ "seed" ] == 7
    assert manifest[ "source_commit" ] == COMMIT and manifest[ "final_sha256" ] == finalize.file_sha256( tmp_path / finalize.FINAL_FILE ) and ids == sorted( ids )


@pytest.mark.parametrize( "kwargs, name", [
    ( { "nothing": ( 60, 39 ) }, "ROWS" ), ( { "nothing": ( 61, 40 ) }, "ROWS" ), ( { "nothing": ( 60, 39 ), "matched": ( 180, 121 ) }, "KINDS" ), ( { "matched": ( 179, 121 ) }, "LANGS" ),
    ( { "model_agreed_nothing": 1 }, "HUMAN" ), ( { "disputed_model_agreed": 1 }, "HUMAN" ) ] )
def test_each_count_and_each_human_source_condition_fails_by_name( tmp_path, kwargs, name ):
    assert condition( write_set( tmp_path, **kwargs ) )[ 0 ] == name


def test_a_matched_row_with_an_empty_key_fails_as_an_invalid_row( tmp_path ):
    path = write_set( tmp_path )
    done = []

    def empty( r ):
        if r[ "kind" ] != "nothing" and not done:
            done.append( 1 )
            r[ "key" ][ "symbols" ] = []
        return r

    rewrite_rows( tmp_path, empty )
    name, detail = condition( path )
    assert name == "ROWS" and "non-empty key" in detail


def test_a_nothing_row_with_a_key_fails_as_an_invalid_row( tmp_path ):
    path = write_set( tmp_path )
    rewrite_rows( tmp_path, lambda r: dict( r, key=dict( r[ "key" ], symbols=[ "x.y" ] ) ) if r[ "kind" ] == "nothing" else r )
    assert condition( path )[ 0 ] == "ROWS"


def test_a_changed_byte_is_a_sha_mismatch( tmp_path ):
    path  = write_set( tmp_path )
    final = tmp_path / finalize.FINAL_FILE
    final.write_text( final.read_text().replace( '"note": "n"', '"note": "m"', 1 ), encoding="utf-8" )
    assert condition( path )[ 0 ] == "SHA"


def test_a_smoke_row_in_the_set_is_refused_even_with_the_sha_in_step( tmp_path ):
    path = write_set( tmp_path )
    done = []

    def mark( r ):
        if not done:
            done.append( 1 )
            return dict( r, smoke=True )
        return r

    rewrite_rows( tmp_path, mark )
    assert condition( path )[ 0 ] == "SMOKE"


@pytest.mark.parametrize( "change", [ lambda m: m.pop( "kappa" ), lambda m: m.update( kappa=None ), lambda m: m.update( kappa=True ), lambda m: m.update( kappa="0.6" ) ] )
def test_a_manifest_without_a_numeric_kappa_fails( tmp_path, change ):
    path = write_set( tmp_path )
    data = json.loads( path.read_text() )
    change( data )
    path.write_text( json.dumps( data ), encoding="utf-8" )
    assert condition( path )[ 0 ] == "KAPPA"


def test_a_missing_file_or_a_file_that_is_not_json_fails_as_files( tmp_path ):
    path = write_set( tmp_path )
    ( tmp_path / finalize.FINAL_FILE ).write_text( "{not json\n", encoding="utf-8" )
    assert condition( path )[ 0 ] == "FILES"
    ( tmp_path / finalize.FINAL_FILE ).unlink()
    assert condition( path )[ 0 ] == "FILES"
    assert condition( tmp_path / "nowhere" / finalize.MANIFEST_FILE )[ 0 ] == "FILES"


def test_a_row_that_is_not_final_or_not_a_need_fails_as_rows( tmp_path ):
    path = write_set( tmp_path )
    rewrite_rows( tmp_path, lambda r: dict( r, status="checked" ) )
    assert condition( path )[ 0 ] == "ROWS"
    ( tmp_path / "b" ).mkdir()
    path2 = write_set( tmp_path / "b" )
    rewrite_rows( tmp_path / "b", lambda r: { k: v for k, v in r.items() if k != "final" } )
    assert condition( path2 )[ 0 ] == "ROWS"
    final = tmp_path / finalize.FINAL_FILE
    final.write_text( "[1]\n" * 400, encoding="utf-8" )
    assert condition( path )[ 0 ] == "ROWS"


def test_other_counts_can_be_asked_for( tmp_path ):
    path = write_set( tmp_path, nothing=( 1, 1 ), matched=( 2, 1 ) )
    finalize.verify_manifest( path, { "rows": 5, "matched": 3, "nothing": 2, "ts": 3, "py": 2 } )
    assert condition( path )[ 0 ] == "ROWS"


def test_finalize_refuses_a_smoke_need_an_unchecked_need_a_missing_label_and_a_kappa_that_is_not_a_number( tmp_path ):
    needs, labels = build_set( nothing=( 1, 1 ), matched=( 1, 1 ) )
    smoke = dict( needs[ 2 ], smoke=True )
    with pytest.raises( er.NeedsetError ) as e: finalize.finalize( [ smoke ], { smoke[ "id" ]: AGREED }, 0.5, 1, COMMIT, FROZEN, tmp_path )
    assert e.value.code == er.BAD_NEED
    drafted = schema.new_need( "near_copy", "py", "pkg.a.f", None, [ "pkg.b.g" ], "py", "twin", "A function that adds up a list of numbers until a ceiling.", COMMIT, DRAFTER )
    with pytest.raises( er.NeedsetError ) as e: finalize.finalize( [ drafted ], { drafted[ "id" ]: AGREED }, 0.5, 1, COMMIT, FROZEN, tmp_path )
    assert e.value.code == er.BAD_NEED
    with pytest.raises( er.NeedsetError ) as e: finalize.finalize( needs, { k: v for k, v in list( labels.items() )[ 1: ] }, 0.5, 1, COMMIT, FROZEN, tmp_path )
    assert e.value.detail.startswith( "LABELS" )
    for bad in ( None, True, "0.5" ):
        with pytest.raises( er.NeedsetError ) as e: finalize.finalize( needs, labels, bad, 1, COMMIT, FROZEN, tmp_path )
        assert e.value.detail.startswith( "KAPPA" )


def test_a_label_of_other_replaces_the_key_and_raises_its_version():
    need = checked( schema.new_need( "near_copy", "py", "pkg.a.f", None, [ "pkg.b.g" ], "py", "twin", "A function that adds up a list of numbers until a ceiling.", COMMIT, DRAFTER ) )
    row  = finalize.final_row( need, { "choice": "OTHER", "symbols": [ "pkg.c.h" ], "final_source": "rick_tiebreak" } )
    assert row[ "key" ][ "symbols" ] == [ "pkg.c.h" ] and row[ "key" ][ "version" ] == 2 and row[ "key" ][ "provenance" ] == "reviewer_confirmed" and row[ "status" ] == "final"
    assert row[ "final" ] == { "choice": "OTHER", "symbols": [ "pkg.c.h" ], "final_source": "rick_tiebreak" } and need[ "key" ][ "symbols" ] == [ "pkg.b.g" ] and need[ "status" ] == "checked"
    kept = finalize.final_row( need, AGREED )
    assert kept[ "key" ] == need[ "key" ]


@pytest.mark.parametrize( "kind, choice", [ ( "matched", "NONE" ), ( "nothing", "OTHER" ), ( "nothing", "NONE" ) ] )
def test_a_label_that_rejects_a_need_stops_the_finalize( kind, choice ):
    need = ( checked( schema.new_need( "near_copy", "py", "pkg.a.f", None, [ "pkg.b.g" ], "py", "twin", "A function that adds up a list of numbers until a ceiling.", COMMIT, DRAFTER ) )
             if kind == "matched" else checked( schema.new_need( "nothing", "py", None, None, [], None, None, "A function that renames files in a folder to lower case.", COMMIT, DRAFTER ) ) )
    with pytest.raises( er.NeedsetError ) as e: finalize.final_row( need, { "choice": choice, "symbols": [ "x.y" ] if choice == "OTHER" else [], "final_source": "agreed" } )
    assert e.value.detail.startswith( "REJECTED" )


def test_finalize_refuses_a_repeated_need_id( tmp_path ):
    needs, labels = build_set( nothing=( 1, 1 ), matched=( 1, 1 ) )
    with pytest.raises( er.NeedsetError ) as e: finalize.finalize( needs + [ copy.deepcopy( needs[ 0 ] ) ], labels, 0.5, 1, COMMIT, FROZEN, tmp_path )
    assert e.value.code == er.MANIFEST_MISMATCH and e.value.detail.startswith( "IDS" ) and needs[ 0 ][ "id" ] in e.value.detail


def test_a_copied_row_with_the_sha_in_step_fails_as_a_repeated_id( tmp_path ):
    path = write_set( tmp_path )
    rows = [ json.loads( l ) for l in ( tmp_path / finalize.FINAL_FILE ).read_text().splitlines() ]
    twin = next( r for r in rows if r[ "kind" ] == "nothing" )
    nth  = [ r[ "id" ] for r in rows if r[ "kind" ] == "nothing" and r[ "write_lang" ] == twin[ "write_lang" ] ][ 1 ]
    rewrite_rows( tmp_path, lambda r: copy.deepcopy( twin ) if r[ "id" ] == nth else r )
    name, detail = condition( path )
    assert name == "IDS" and "399 unique ids in 400 rows" in detail


@pytest.mark.parametrize( "change, name", [
    ( lambda m: m[ "counts" ].update( rows=1 ), "COUNTS" ), ( lambda m: m[ "counts" ].update( ts=239, py=161 ), "COUNTS" ), ( lambda m: m.pop( "counts" ), "COUNTS" ),
    ( lambda m: m.update( source_commit="nope" ), "COMMIT" ), ( lambda m: m.pop( "source_commit" ), "COMMIT" ), ( lambda m: m.update( seed=None ), "SEED" ), ( lambda m: m.pop( "seed" ), "SEED" ) ] )
def test_a_manifest_that_disagrees_with_its_rows_fails_by_name( tmp_path, change, name ):
    path = write_set( tmp_path )
    data = json.loads( path.read_text() )
    change( data )
    path.write_text( json.dumps( data ), encoding="utf-8" )
    assert condition( path )[ 0 ] == name


def test_a_typed_symbol_outside_the_index_stops_the_finalize( tmp_path ):
    need = checked( schema.new_need( "near_copy", "py", "pkg.a.f", None, [ "pkg.b.g" ], "py", "twin", "A function that adds up a list of numbers until a ceiling.", COMMIT, DRAFTER ) )
    other = { need[ "id" ]: { "choice": "OTHER", "symbols": [ "pkg.c.h" ], "final_source": "rick_tiebreak" } }
    finalize.finalize( [ need ], other, 0.5, 1, COMMIT, FROZEN, tmp_path, known_symbols={ "pkg.c.h", "pkg.b.g" } )
    finalize.finalize( [ need ], other, 0.5, 1, COMMIT, FROZEN, tmp_path )
    with pytest.raises( er.NeedsetError ) as e: finalize.finalize( [ need ], other, 0.5, 1, COMMIT, FROZEN, tmp_path, known_symbols={ "pkg.b.g" } )
    assert e.value.detail.startswith( "SYMBOLS" ) and "pkg.c.h" in e.value.detail
    finalize.finalize( [ need ], { need[ "id" ]: AGREED }, 0.5, 1, COMMIT, FROZEN, tmp_path, known_symbols=set() )
    unlabelled = { need[ "id" ]: { "choice": None, "symbols": None, "final_source": "model_agreed" } }
    finalize.finalize( [ need ], unlabelled, 0.5, 1, COMMIT, FROZEN, tmp_path, known_symbols=set() )


def test_an_id_repeated_three_times_is_counted_once_among_the_unique_ids( tmp_path ):
    path = write_set( tmp_path )
    rows = [ json.loads( l ) for l in ( tmp_path / finalize.FINAL_FILE ).read_text().splitlines() ]
    nothing_ids = [ r[ "id" ] for r in rows if r[ "kind" ] == "nothing" and r[ "write_lang" ] == rows[ 0 ][ "write_lang" ] ]
    twin = next( r for r in rows if r[ "id" ] == nothing_ids[ 0 ] )
    rewrite_rows( tmp_path, lambda r: copy.deepcopy( twin ) if r[ "id" ] in nothing_ids[ 1:3 ] else r )
    name, detail = condition( path )
    assert name == "IDS" and "398 unique ids in 400 rows" in detail


def test_the_manifest_records_the_three_frozen_hashes_and_a_set_without_them_fails_by_name( tmp_path ):
    path = write_set( tmp_path )
    assert { k: json.loads( path.read_text() )[ k ] for k in FROZEN } == FROZEN
    finalize.verify_manifest( path )
    for key in FROZEN:
        stored = json.loads( path.read_text() )
        del stored[ key ]
        path.write_text( json.dumps( stored ) )
        name, detail = condition( path )
        assert name == "FROZEN" and key in detail
        write_set( tmp_path )


@pytest.mark.parametrize( "bad", [ None, "", 5 ] )
def test_finalize_refuses_an_identity_that_lacks_a_hash_before_it_writes_anything( tmp_path, bad ):
    needs, labels = build_set()
    with pytest.raises( er.NeedsetError ) as e: finalize.finalize( needs, labels, 0.5, 1, COMMIT, dict( FROZEN, symbols_sha=bad ), tmp_path )
    assert e.value.code == er.MANIFEST_MISMATCH and e.value.detail.startswith( "FROZEN" ) and not ( tmp_path / finalize.FINAL_FILE ).exists()
