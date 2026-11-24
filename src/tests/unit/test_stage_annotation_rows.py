"""
Tests for the stage-annotation extractor and the committed annotation files.

The extractor reads a SQLite archive; these tests build a small one with the same columns.
"""

import hashlib
import importlib.util
import json
import pathlib
import sqlite3

import pytest

FIXTURES = pathlib.Path( __file__ ).resolve().parents[ 1 ] / "fixtures" / "principle_learner" / "stage_annotation"
SPEC     = importlib.util.spec_from_file_location( "extract_rows", FIXTURES / "extract_rows.py" )
rows_mod = importlib.util.module_from_spec( SPEC )
SPEC.loader.exec_module( rows_mod )

OTHER = "2668eeb4e92e400dab41be493676d210"


def _archive( path, count=23 ):
    """Build an archive with `count` matching rows and two decoys."""
    db = sqlite3.connect( path )
    db.execute( "create table notifications ( id text, title text, message text, abstract text, response_value text, response_default text, created_at text )" )
    db.execute( "create table preference_evidence ( id text, principle_id text, notification_id text, relation text, condition text, answered_at text )" )
    def add( key, principle, title, value, relation, condition ):
        db.execute( "insert into notifications values ( ?, ?, 'msg', 'abs', ?, 'yes', ? )", ( key, title, value, f"2026-09-{key[-2:]}" ) )
        db.execute( "insert into preference_evidence values ( ?, ?, ?, ?, ?, ? )", ( f"e{key}", principle, key, relation, condition, f"2026-10-{key[-2:]}" ) )
    for number in range( count ): add( f"n{number + 10}", rows_mod.PRINCIPLE_ID, "x is at their context ceiling.", json.dumps( { "value": "yes" } ), "supports", None )
    add( "n90", OTHER, "y is at their context ceiling.", json.dumps( { "value": "no" } ), "supports", None )
    add( "n91", rows_mod.PRINCIPLE_ID, "an unrelated card", json.dumps( { "value": "no" } ), "refines", "c" )
    db.commit()
    db.close()


def test_answer_text_reads_a_json_string_a_dict_and_anything_else():
    assert rows_mod.answer_text( '{"value": "no [comment: x]"}' ) == "no [comment: x]"
    assert rows_mod.answer_text( { "value": "yes" } ) == "yes"
    assert rows_mod.answer_text( '"plain"' ) == "plain"  # a JSON string that decodes to a string, not a dict: its text
    assert rows_mod.answer_text( None ) == "None"


def test_extract_returns_23_numbered_rows_with_the_relation_only_in_the_labels( tmp_path ):
    _archive( tmp_path / "a.sqlite" )
    free, labels = rows_mod.extract( str( tmp_path / "a.sqlite" ) )
    assert [ r[ "row" ] for r in free ] == list( range( 1, 24 ) ) and [ r[ "row" ] for r in labels ] == list( range( 1, 24 ) )
    assert all( "relation" not in r and "condition" not in r for r in free ) and all( r[ "relation" ] == "supports" for r in labels )
    assert free[ 0 ][ "owner_answer" ] == "yes" and free[ 0 ][ "evidence_id" ] == labels[ 0 ][ "evidence_id" ] == "en10"


@pytest.mark.parametrize( "count", [ 22, 24 ] )
def test_extract_refuses_a_population_that_is_not_23( tmp_path, count ):
    _archive( tmp_path / "a.sqlite", count )
    with pytest.raises( ValueError, match=f"found {count}" ): rows_mod.extract( str( tmp_path / "a.sqlite" ) )


def test_main_writes_both_files( tmp_path ):
    _archive( tmp_path / "a.sqlite" )
    argv = [ str( tmp_path / "a.sqlite" ), str( tmp_path / "free.json" ), str( tmp_path / "labels.json" ) ]
    assert rows_mod.main( argv ) == 0
    assert len( json.loads( ( tmp_path / "free.json" ).read_text() ) ) == 23 and "relation" in ( tmp_path / "labels.json" ).read_text()


def test_the_committed_files_agree_and_the_readme_names_their_shas():
    free        = json.loads( ( FIXTURES / "label-free-input.json" ).read_text() )
    annotation  = json.loads( ( FIXTURES / "annotation.json" ).read_text() )
    labels      = json.loads( ( FIXTURES / "labels.json" ).read_text() )
    readme      = ( FIXTURES / "README.md" ).read_text()
    assert len( free ) == len( labels ) == len( annotation[ "rows" ] ) == 23
    assert [ r[ "evidence_id" ] for r in free ] == [ r[ "evidence_id" ] for r in labels ] == [ r[ "evidence_id" ] for r in annotation[ "rows" ] ]
    assert all( "relation" not in r for r in free ) and { r[ "stage" ] for r in annotation[ "rows" ] } <= set( annotation[ "stages" ] )
    for name in ( "label-free-input.json", "annotation.json", "labels.json" ):
        assert hashlib.sha256( ( FIXTURES / name ).read_bytes() ).hexdigest() in readme, name
