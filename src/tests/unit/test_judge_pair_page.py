"""Rick's page for the forecast-pair labels: blind share, disputes and page script."""

import json
import re
import runpy
import shutil
import subprocess
import sys

import pytest

import cosa.utils.util as cu
from cosa.repo.labelling import errors as er
from cosa.repo.labelling import rick_page as rp
from cosa.research.judge_validation import pair_page as pp
from cosa.utils.file_hash import file_sha256

SCHEMA = { "questions": [ { "header": "Where", "question": "Where to run it?",
                            "options": [ { "label": "Test", "description": "the test server" }, { "label": "Dev" } ] } ] }


def write_lines( path, rows ):
    """Write rows as JSON Lines and return the path as text."""
    path.write_text( "".join( json.dumps( row ) + "\n" for row in rows ), encoding="utf-8" )
    return str( path )


def inputs( folder, count=10, differ=( "p01", "p02" ) ):
    """
    Write a synthetic set of the shape draw.py writes, and two readers' labels.

    Reader two flips material_error on the pairs named in differ, and differs in kind alone on p03.
    """
    cards = [ { "pair_id": f"p{i:02d}", "notification_id": f"n{i:02d}", "field_key": "answer", "actual_text": f"job {i}", "response_type": "yes_no", "message": f"Run job {i}?", "abstract": None,
                "options": None, "answer": f"yes [comment: only on test, job {i}]", "arm": "SECRET-ARM" } for i in range( count ) ]
    forecasts = [ { "pair_id": f"p{i:02d}", "notification_id": f"n{i:02d}", "field_key": "answer", "predicted_text": f"on dev {i}", "model": "SECRET-MODEL" }
                  for i in range( count ) ]
    one = [ { "pair_id": f"p{i:02d}", "material_error": False, "kind": "none", "atom": None, "note": "ONE-NOTE" } for i in range( count ) ]
    two = [ dict( row, material_error=row[ "pair_id" ] in differ, note="TWO-NOTE", kind="invented condition" if row[ "pair_id" ] == "p03" else "none" ) for row in one ]
    return { "answers": write_lines( folder / "answers.jsonl", cards ), "forecasts": write_lines( folder / "forecasts.jsonl", forecasts ),
             "one": write_lines( folder / "one.jsonl", one ), "two": write_lines( folder / "two.jsonl", two ) }


def loaded( folder, **kwargs ):
    """Return ( pairs, readers ) read from a synthetic set."""
    paths   = inputs( folder, **kwargs )
    pairs   = pp.read_pairs( paths[ "answers" ], paths[ "forecasts" ] )
    readers = { name: pp.read_reader( paths[ name ], pairs ) for name in ( "one", "two" ) }
    return pairs, readers


def argv_for( paths, out, seed="s1" ):
    """Return main's arguments for a synthetic set."""
    return [ "--answers", paths[ "answers" ], "--forecasts", paths[ "forecasts" ], "--labels", f"one={paths[ 'one' ]}", "--labels", f"two={paths[ 'two' ]}",
             "--seed", seed, "--out", str( out ) ]


def test_the_join_keeps_only_the_shown_fields_so_no_arm_or_model_reaches_a_page( tmp_path ):
    pairs, readers = loaded( tmp_path )
    html           = pp.render_page( pp.page_items( pairs, sorted( pairs ), [ "p01" ], readers ), "t" )

    assert set( pairs[ "p00" ] ) == { "pair_id", "field_key", "predicted_text", "response_type", "message", "abstract", "options", "answer", "actual_text" }
    assert "SECRET" not in html


@pytest.mark.parametrize( "rows,said", [
    ( [ { "pair_id": "p00", "field_key": "answer", "predicted_text": "x" } ] * 2, "appears twice" ),
    ( [ { "pair_id": "gone", "field_key": "answer", "predicted_text": "x" } ], "held by only one file: 3" ),
    ( [], "holds no pairs" ),
] )
def test_a_forecasts_file_that_does_not_join_is_refused( tmp_path, rows, said ):
    paths = inputs( tmp_path, count=2, differ=() )
    write_lines( tmp_path / "forecasts.jsonl", rows )

    with pytest.raises( er.LabellingError, match=said ):
        pp.read_pairs( paths[ "answers" ], paths[ "forecasts" ] )


@pytest.mark.parametrize( "rows,said", [
    ( [ "p00", "p00" ], "labelled twice" ),
    ( [ "p00" ], "differ on 1 ids" ),
    ( [ "p00", "p01", "p99" ], "differ on 1 ids" ),
] )
def test_labels_that_do_not_cover_exactly_the_pairs_are_refused( tmp_path, rows, said ):
    path = write_lines( tmp_path / "l.jsonl", [ { "pair_id": i, "material_error": True, "kind": "none", "atom": None, "note": "" } for i in rows ] )

    with pytest.raises( er.LabellingError, match=said ):
        pp.read_reader( path, [ "p00", "p01" ] )


def test_a_material_error_that_is_not_a_boolean_is_refused( tmp_path ):
    path = write_lines( tmp_path / "l.jsonl", [ { "pair_id": "p00", "material_error": "no", "kind": "none", "atom": None, "note": "" } ] )

    with pytest.raises( er.LabellingError, match="not true or false" ):
        pp.read_reader( path, [ "p00" ] )


def test_the_blind_share_of_320_is_64_repeatable_and_moves_with_the_seed():
    ids   = [ f"p{i:03d}" for i in range( 320 ) ]
    first = pp.draw_blind( ids, "s1" )

    assert len( first[ "ids" ] ) == 64 and first[ "population" ] == 320
    assert first == pp.draw_blind( list( reversed( ids ) ), "s1" )
    assert first[ "ids" ] != pp.draw_blind( ids, "s2" )[ "ids" ]
    assert first[ "ids_sha256" ] == rp.ids_sha256( first[ "ids" ] )


def test_only_a_difference_in_material_error_is_a_dispute( tmp_path ):
    _, readers = loaded( tmp_path )

    assert readers[ "one" ][ "p03" ][ "kind" ] != readers[ "two" ][ "p03" ][ "kind" ]
    assert pp.disputed_ids( readers[ "one" ], readers[ "two" ] ) == [ "p01", "p02" ]


def test_the_reader_reads_the_files_the_draw_itself_wrote( tmp_path ):
    """The fixtures are draw.write_sample's own output on made-up pairs, unedited."""
    folder = cu.get_project_root() + "/src/tests/fixtures/judge_pair_page/"
    with open( folder + "draw.json", encoding="utf-8" ) as handle:
        receipt = json.load( handle )
    for name in ( "reader-answers.jsonl", "reader-forecasts.jsonl" ):
        assert file_sha256( folder + name ) == receipt[ "files" ][ name ], name

    pairs = pp.read_pairs( folder + "reader-answers.jsonl", folder + "reader-forecasts.jsonl" )
    items = pp.page_items( pairs, sorted( pairs ), [], {} )
    shown = { item[ "card_text" ]: item for item in items }

    assert len( pairs ) == receipt[ "drawn" ] == 6
    picked = shown[ "Made-up multiple_choice question 0?" ]
    assert ( picked[ "question" ], picked[ "answer" ], picked[ "forecast" ] ) == ( "Colour", "Colour: Green", "" )
    assert picked[ "options" ] == "Colour\n- Green: made up\n- Blue: made up"
    plain = shown[ "Made-up yes_no question 2?" ]
    assert ( plain[ "question" ], plain[ "answer" ], plain[ "forecast" ], plain[ "options" ] ) == ( "", "yes [comment: paint it green]", "paint it green", "" )
    view = drive( tmp_path, [ [ "view" ] ], items=[ plain ] )[ "views" ][ 0 ]
    assert view[ "answer" ] == "yes [comment: paint it green]" and view[ "options" ] == "none" and view[ "forecast" ] == "paint it green" and view[ "actual" ] == "paint it green"


def test_section_a_holds_no_reader_label_and_section_b_holds_both( tmp_path ):
    pairs, readers = loaded( tmp_path )
    items          = pp.page_items( pairs, [ "p01", "p00" ], [ "p01" ], readers )

    assert [ item[ "key" ] for item in items ] == [ "A:p00", "A:p01", "B:p01" ]
    assert all( item[ "readers" ] == [] for item in items[ :2 ] )
    assert "NOTE" not in json.dumps( items[ :2 ] )
    assert [ ( r[ "name" ], r[ "material_error" ], r[ "note" ] ) for r in items[ 2 ][ "readers" ] ] == [ ( "one", False, "ONE-NOTE" ), ( "two", True, "TWO-NOTE" ) ]


def test_options_are_written_out_and_an_unknown_shape_is_shown_whole():
    assert pp.options_text( None ) == ""
    assert pp.options_text( SCHEMA ) == "Where: Where to run it?\n- Test: the test server\n- Dev"
    assert pp.options_text( { "questions": [ { "header": "H", "question": "Q?" } ] } ) == "H: Q?"
    assert json.loads( pp.options_text( [ "x", "y" ] ) ) == [ "x", "y" ]


def test_an_answer_with_picks_is_written_by_header_and_any_other_is_left_as_it_is():
    assert pp.answer_text( json.dumps( { "answers": { "Where": "Test", "When": [ "now", "later" ] } } ) ) == "Where: Test\nWhen: now, later"
    assert pp.answer_text( "yes [comment: only on test]" ) == "yes [comment: only on test]"
    assert pp.answer_text( "[1, 2]" ) == "[1, 2]"
    assert pp.answer_text( None ) == ""


def test_the_page_needs_nothing_outside_and_carries_the_offered_choices( tmp_path ):
    pairs, readers = loaded( tmp_path )
    items          = pp.page_items( pairs, [ "p00" ], [], readers )
    html           = pp.render_page( items, "A <title>" )

    assert not re.search( r"(src|href)\s*=\s*[\"']https?:|@import|url\(", html )
    assert "<title>A &lt;title&gt;</title>" in html and "__" not in html.split( "<script" )[ 0 ]
    assert "var KINDS    = " + rp.embed_json( list( pp.KINDS ) ) + ";" in html
    assert re.search( r'PAGE_ID  = "(\w+)"', html ).group( 1 ) == rp.page_id( [ "A:p00" ] )
    with pytest.raises( er.LabellingError ):
        pp.render_page( [], "t" )


def drive( tmp_path, steps, items=None, saved=None ):
    """Run judge_pair_page_driver.js on a built page under node and return what it reports."""
    if shutil.which( "node" ) is None: pytest.skip( "node is not installed" )
    if items is None:
        pairs, readers = loaded( tmp_path )
        items          = pp.page_items( pairs, [ "p00", "p01" ], [ "p01", "p02" ], readers )
    page, script = tmp_path / "page.html", tmp_path / "steps.json"
    page.write_text( pp.render_page( items, "t" ), encoding="utf-8" )
    script.write_text( json.dumps( steps ), encoding="utf-8" )
    command = [ "node", cu.get_project_root() + "/src/tests/unit/judge_pair_page_driver.js", str( page ), str( script ) ]
    if saved is not None:
        ( tmp_path / "saved.json" ).write_text( json.dumps( saved ), encoding="utf-8" )
        command.append( str( tmp_path / "saved.json" ) )
    result = subprocess.run( command, capture_output=True, text=True, timeout=60 )
    assert result.returncode == 0, result.stderr
    return json.loads( result.stdout.strip().splitlines()[ -1 ] )


def test_a_disputed_pair_of_the_blind_share_shows_no_reader_until_it_is_labelled_blind( tmp_path ):
    """Items are A:p00, A:p01, B:p01, B:p02."""
    out = drive( tmp_path, [
        [ "go", 1 ], [ "view" ],
        [ "go", 2 ], [ "choose", "material_error", "yes" ], [ "note", "peeked" ], [ "view" ],
        [ "go", 3 ], [ "view" ],
        [ "go", 1 ], [ "choose", "material_error", "no" ], [ "go", 2 ], [ "view" ],
        [ "go", 1 ], [ "choose", "kind", "none" ], [ "go", 2 ], [ "view" ],
    ] )
    blind, locked, other, half, opened = out[ "views" ]

    assert blind[ "readersbox" ] == "none" and "NOTE" not in blind[ "readers" ]
    assert "section A first" in locked[ "readers" ] and "NOTE" not in locked[ "readers" ]
    assert locked[ "note_disabled" ] is True and all( b[ "disabled" ] for b in locked[ "choices" ] + locked[ "kinds" ] )
    assert "ONE-NOTE" in other[ "readers" ] and "TWO-NOTE" in other[ "readers" ]
    assert "section A first" in half[ "readers" ]
    assert "material error yes" in opened[ "readers" ] and not any( b[ "disabled" ] for b in opened[ "choices" ] )
    assert "B:p01" not in out[ "saved" ][ "answers" ]


def label( index, error="yes", kind="none" ):
    """Return the steps that give one item both choices."""
    return [ [ "go", index ], [ "choose", "material_error", error ], [ "choose", "kind", kind ] ]


def test_a_blind_answer_cannot_change_once_its_readers_have_been_shown( tmp_path ):
    """A:p01 is answered, B:p01 is viewed, then every way of editing A:p01 is tried."""
    out = drive( tmp_path, label( 1 ) + [ [ "view" ], [ "go", 2 ], [ "go", 1 ], [ "choose", "material_error", "no" ],
                                          [ "choose", "kind", "different action" ], [ "note", "after peeking" ], [ "view" ], [ "go", 0 ], [ "view" ] ] )
    before, after, other = out[ "views" ]

    assert before[ "lockedbox" ] == "none" and not any( b[ "disabled" ] for b in before[ "choices" ] )
    assert after[ "lockedbox" ] == "block" and after[ "note_disabled" ] is True
    assert all( b[ "disabled" ] for b in after[ "choices" ] + after[ "kinds" ] )
    assert [ ( l[ "material_error" ], l[ "kind" ], l[ "note" ], l[ "readers_seen" ] ) for l in out[ "export" ] ] == [ ( "yes", "none", "", True ) ]
    assert other[ "lockedbox" ] == "none" and out[ "saved" ][ "seen" ] == { "p01": True }


def test_the_lock_holds_across_a_reload( tmp_path ):
    saved = drive( tmp_path, label( 1 ) + [ [ "go", 2 ], [ "go", 0 ] ] )[ "saved" ]   # left on A:p00, so a reload shows no reader
    assert saved[ "position" ] == 0

    out = drive( tmp_path, [ [ "go", 1 ], [ "choose", "material_error", "no" ], [ "view" ] ], saved=saved )

    assert out[ "views" ][ 0 ][ "lockedbox" ] == "block"
    assert out[ "export" ][ 0 ][ "material_error" ] == "yes"


def test_a_restore_neither_replaces_a_locked_answer_nor_loses_the_lock( tmp_path ):
    blind  = { "pair_id": "p01", "section": "A", "material_error": "yes", "kind": "none", "note": "", "ts": "2026-11-29T10:00:00Z" }
    later  = dict( blind, material_error="no", ts="2026-11-29T12:00:00Z" )
    locked = dict( blind, readers_seen=True )
    seen_b = dict( blind, section="B", ts="2026-11-29T11:00:00Z" )
    edit   = [ [ "go", 1 ], [ "choose", "material_error", "cant_tell" ] ]
    here   = drive( tmp_path, label( 1, "yes" ) + [ [ "go", 2 ], [ "restore", json.dumps( [ dict( later, ts="2099-01-01T00:00:00Z" ) ] ) ] ] )
    fresh  = drive( tmp_path, [ [ "restore", json.dumps( [ locked ] ) ] ] + edit )
    by_b   = drive( tmp_path, [ [ "restore", json.dumps( [ blind, seen_b ] ) ] ] + edit )
    over   = drive( tmp_path, label( 1, "no" ) + [ [ "restore", json.dumps( [ later, locked ] ) ] ] + edit )

    assert [ here[ "export" ][ 0 ][ "material_error" ], fresh[ "export" ][ 0 ][ "material_error" ] ] == [ "yes", "yes" ]
    assert by_b[ "export" ][ 0 ][ "material_error" ] == "yes" and by_b[ "export" ][ 0 ][ "readers_seen" ] is True
    assert over[ "export" ][ 0 ][ "material_error" ] == "yes" and over[ "saved" ][ "seen" ] == { "p01": True }


@pytest.mark.parametrize( "kind,answer,shared", [
    ( "yes_no", "no [comment: not today]", "Both answered no." ),
    ( "yes_no", "hmm", "" ),
    ( "multiple_choice", '{"answers": {"Where": "Test"}}', pp.SAME_CHOICE ),
    ( "open_ended", "do it later", "" ),
] )
def test_the_page_says_what_the_two_sides_already_agree_on( tmp_path, kind, answer, shared ):
    pairs, readers = loaded( tmp_path )
    pairs[ "p00" ].update( response_type=kind, answer=answer, actual_text=None, predicted_text=None )

    items = pp.page_items( pairs, [ "p00" ], [], readers )
    view  = drive( tmp_path, [ [ "view" ] ], items=items )[ "views" ][ 0 ]

    assert items[ 0 ][ "shared" ] == shared
    assert view[ "sharedbox" ] == ( "block" if shared else "none" ) and view[ "shared" ] == shared
    assert view[ "actual" ] == view[ "forecast" ] == "no condition added"


def test_a_label_is_saved_and_exported_only_once_it_has_both_choices( tmp_path ):
    out = drive( tmp_path, [
        [ "view" ], [ "note", "early note" ], [ "choose", "material_error", "cant_tell" ], [ "view" ],
        [ "next" ], [ "choose", "kind", "different action" ], [ "choose", "material_error", "yes" ], [ "note", "wrong server" ], [ "prev" ], [ "view" ],
    ] )

    assert [ ( line[ "pair_id" ], line[ "section" ], line[ "material_error" ], line[ "kind" ], line[ "note" ] ) for line in out[ "export" ] ] == [
        ( "p01", "A", "yes", "different action", "wrong server" ) ]
    assert set( out[ "export" ][ 0 ] ) == { "pair_id", "section", "material_error", "kind", "note", "ts" }
    assert out[ "saved" ][ "answers" ][ "A:p00" ][ "note" ] == "early note"
    assert out[ "views" ][ 0 ][ "done" ] == "0 of 4 done" and out[ "views" ][ 2 ][ "done" ] == "1 of 4 done"
    assert [ b[ "text" ] for b in out[ "views" ][ 2 ][ "choices" ] if b[ "chosen" ] ] == [ "Can't tell" ]
    assert out[ "views" ][ 2 ][ "note" ] == "early note"
    assert out[ "key" ].startswith( "rick-pairs:" )


def test_the_page_resumes_where_it_was_saved( tmp_path ):
    saved = { "answers": { "A:p01": { "material_error": "no", "kind": "none", "note": "kept", "ts": "2026-11-29T10:00:00Z" } }, "position": 1 }

    view = drive( tmp_path, [ [ "view" ] ], saved=saved )[ "views" ][ 0 ]

    assert view[ "pos" ] == "Item 2 of 4" and view[ "note" ] == "kept" and view[ "done" ] == "1 of 4 done"


def test_next_unlabelled_skips_what_is_done_and_says_when_nothing_is_left( tmp_path ):
    labelled = lambda index: [ [ "go", index ], [ "choose", "material_error", "no" ], [ "choose", "kind", "none" ] ]
    steps    = labelled( 1 ) + [ [ "go", 0 ], [ "nextopen" ], [ "view" ] ] + labelled( 0 ) + labelled( 2 ) + labelled( 3 ) + [ [ "nextopen" ], [ "view" ] ]

    first, last = drive( tmp_path, steps )[ "views" ]

    assert first[ "pos" ] == "Item 3 of 4"
    assert last[ "exportstatus" ].startswith( "Every item has an answer" )


def test_an_export_restores_into_a_fresh_page_and_a_newer_answer_is_kept( tmp_path ):
    old  = { "pair_id": "p00", "section": "A", "material_error": "no", "kind": "none", "note": "old", "ts": "2026-11-29T10:00:00Z" }
    new  = dict( old, material_error="yes", kind="false permission", note="new", ts="2026-11-29T11:00:00Z" )
    kept = { "answers": { "A:p00": { "material_error": "cant_tell", "kind": "none", "note": "mine", "ts": "2026-11-30T00:00:00Z" } }, "position": 0 }

    fresh = drive( tmp_path, [ [ "restore", json.dumps( [ new, old ] ) ], [ "view" ] ] )
    held  = drive( tmp_path, [ [ "restore", json.dumps( [ new ] ) ], [ "view" ] ], saved=kept )

    assert fresh[ "export" ] == [ new ]
    assert fresh[ "views" ][ 0 ][ "restorestatus" ].startswith( "Restored 1 answers (of 1" )
    assert held[ "export" ][ 0 ][ "note" ] == "mine" and held[ "views" ][ 0 ][ "restorestatus" ].startswith( "Restored 0 answers" )


@pytest.mark.parametrize( "text,said", [
    ( "not json", "not valid JSON" ),
    ( "{}", "not a list" ),
    ( '[ { "pair_id": "p00" } ]', "lacks pair_id, section or ts" ),
    ( '[ { "pair_id": "p99", "section": "A", "ts": "2026-11-29T10:00:00Z" } ]', "not on this page" ),
    ( '[ { "pair_id": "p00", "section": "A", "ts": "2026-11-29T10:00:00Z", "material_error": "maybe", "kind": "none" } ]', "not one the page offers" ),
] )
def test_a_restore_that_is_not_this_pages_export_changes_nothing( tmp_path, text, said ):
    out = drive( tmp_path, [ [ "restore", text ], [ "view" ] ] )

    assert said in out[ "views" ][ 0 ][ "restorestatus" ] and out[ "export" ] == []


def test_main_writes_the_page_and_a_receipt_with_the_seed_and_the_drawn_ids( tmp_path, capsys ):
    paths = inputs( tmp_path )
    out   = tmp_path / "page.html"

    assert pp.main( argv_for( paths, out ) ) == 0

    receipt = json.loads( ( tmp_path / "page.html.receipt.json" ).read_text( encoding="utf-8" ) )
    assert receipt == json.loads( capsys.readouterr().out )
    assert receipt[ "draw" ][ "seed" ] == "s1" and len( receipt[ "draw" ][ "ids" ] ) == 2
    assert receipt[ "draw" ][ "ids_sha256" ] == rp.ids_sha256( receipt[ "draw" ][ "ids" ] )
    assert receipt[ "disputed_ids" ] == [ "p01", "p02" ] and receipt[ "items" ] == 4
    assert set( receipt[ "inputs_sha256" ] ) == { "answers", "forecasts", "one", "two" }
    assert out.read_text( encoding="utf-8" ).startswith( "<!DOCTYPE html>" )


def test_main_never_overwrites_a_page( tmp_path, capsys ):
    out = tmp_path / "page.html"
    out.write_text( "mine", encoding="utf-8" )

    assert pp.main( argv_for( inputs( tmp_path ), out ) ) == 2
    assert out.read_text( encoding="utf-8" ) == "mine" and "never overwritten" in capsys.readouterr().err


@pytest.mark.parametrize( "names", [ ( "one", ), ( "one", "two", "three" ), ( "one", "one" ), ( "one", "two", "two" ) ] )
def test_main_takes_two_differently_named_readers_and_writes_nothing_otherwise( tmp_path, capsys, names ):
    """Every labels file here is readable, so only the count of readers can refuse."""
    paths  = inputs( tmp_path )
    labels = [ part for name in names for part in ( "--labels", f"{name}={paths[ 'one' ]}" ) ]
    argv   = [ "--answers", paths[ "answers" ], "--forecasts", paths[ "forecasts" ], *labels, "--seed", "s1", "--out", str( tmp_path / "page.html" ) ]

    assert pp.main( argv ) == 2
    assert not ( tmp_path / "page.html" ).exists() and "two different readers" in capsys.readouterr().err


def test_main_refuses_an_unreadable_file_and_writes_nothing( tmp_path, capsys ):
    out = tmp_path / "page.html"

    assert pp.main( argv_for( inputs( tmp_path ), out ) + [ "--answers", "nowhere" ] ) == 2
    assert not out.exists() and "cannot build the page" in capsys.readouterr().err


def test_run_as_a_module_exits_with_mains_code( tmp_path, monkeypatch ):
    """An output that exists makes main return 2, so the exit code is main's and not argparse's."""
    out = tmp_path / "page.html"
    out.write_text( "mine", encoding="utf-8" )
    monkeypatch.setattr( sys, "argv", [ "pair_page", *argv_for( inputs( tmp_path ), out ) ] )
    monkeypatch.delitem( sys.modules, "cosa.research.judge_validation.pair_page" )

    with pytest.raises( SystemExit ) as stopped:
        runpy.run_module( "cosa.research.judge_validation.pair_page", run_name="__main__" )

    assert stopped.value.code == 2
