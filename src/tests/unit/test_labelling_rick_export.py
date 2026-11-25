"""
Reading back Rick's exported answers into the gold store.
"""
import json

import pytest

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import gold_store as gs
from cosa.repo.labelling import items as it
from cosa.repo.labelling import rick_export as rx
from cosa.repo.labelling import rick_page as rp


def card_item( item_id, stance="yes", options=None, recommendation=None, answer="yes" ):
    """Return an answer_meaning_card item."""
    return it.make_item( it.ANSWER_CARD, item_id, { "card_text": "Question?", "options": options or [], "recommendation": recommendation, "answer": answer, "stance_class": stance } )


def packet():
    """Return a packet with a yes/no, a multiple-choice and an open item."""
    blind = [ card_item( "n1:0" ), card_item( "n2:1", stance="none", options=[ "A", "B" ], recommendation="A", answer="A" ), card_item( "n3:0", stance="none" ) ]
    refs  = { "n1:0": { "notification_id": "n1", "field_key": "answer" }, "n2:1": { "notification_id": "n2", "field_key": "Gate" }, "n3:0": { "notification_id": "n3", "field_key": "answer" } }
    return { "name": "dev-sample", "blind": blind, "disputes": [], "refs": refs }


def exported( **over ):
    """Return one exported line."""
    return { "item_id": "n1:0", "relation": "support", "note": "", "seconds": 4.5, "ts": "2026-11-24T23:00:00.000Z", **over }


def code_of( fn, *args ):
    """Return the code of the LabellingError that fn raises."""
    with pytest.raises( er.LabellingError ) as e: fn( *args )
    return e.value.code


def test_a_list_or_an_object_with_lines_reads_and_an_empty_export_is_valid():
    lines = [ exported(), exported( item_id="n3:0", relation="answers", seconds=0, note="why" ) ]
    assert rx.read_export( json.dumps( lines ) ) == lines
    assert rx.read_export( json.dumps( { "lines": lines } ) ) == lines
    assert rx.read_export( "[]" ) == []


@pytest.mark.parametrize( "bad", [
    "not json", "5", json.dumps( { "lines": "x" } ), json.dumps( [ "x" ] ), json.dumps( [ { "item_id": "n1:0" } ] ),
    json.dumps( [ { **exported(), "extra": 1 } ] ), json.dumps( [ exported( item_id=" " ) ] ), json.dumps( [ exported( relation="" ) ] ),
    json.dumps( [ exported( ts=3 ) ] ), json.dumps( [ exported( note=None ) ] ), json.dumps( [ exported( seconds=-1 ) ] ),
    json.dumps( [ exported( seconds="4" ) ] ), json.dumps( [ exported( seconds=True ) ] ), json.dumps( [ exported(), exported() ] ) ] )
def test_a_malformed_export_is_refused_by_name( bad ):
    assert code_of( rx.read_export, bad ) == er.BAD_LABEL


SECTIONS = { "blind share": [ "n1:0", "n2:1" ], "reader disagreements": [ "n3:0" ] }
PAGE     = rp.page_id( [ "n1:0", "n2:1", "n3:0" ] )


def test_a_batch_id_names_the_page_and_the_section_slug():
    assert rx.batch_id_of( "abc", "Reader disagreements!" ) == "rick-abc-reader-disagreements"


def test_each_line_becomes_one_gold_line_from_rick_with_the_cards_own_ids_and_stance():
    lines = [ exported(), exported( item_id="n2:1", relation="agrees", ts="2026-11-24T23:01:00.000Z", note="n", seconds=9 ) ]
    assert rx.gold_lines( lines, packet(), SECTIONS ) == [
        { "item_id": "n1:0", "notification_id": "n1", "field_key": "answer", "relation": "support", "card_stance": "yes", "source": "human", "reader": "rick", "batch_id": f"rick-{PAGE}-blind-share", "ts": "2026-11-24T23:00:00.000Z" },
        { "item_id": "n2:1", "notification_id": "n2", "field_key": "Gate", "relation": "agrees", "card_stance": "none", "source": "human", "reader": "rick", "batch_id": f"rick-{PAGE}-blind-share", "ts": "2026-11-24T23:01:00.000Z" } ]


def test_a_gold_line_has_exactly_the_store_fields_and_the_store_accepts_it( tmp_path ):
    out = rx.gold_lines( [ exported() ], packet(), { "s": [ "n1:0" ] } )
    assert set( out[ 0 ] ) == set( gs.LINE_KEYS )
    assert gs.append_gold( tmp_path / "g.jsonl", out ) == 1


def test_an_item_outside_the_page_or_a_relation_the_card_does_not_allow_is_refused():
    assert code_of( rx.gold_lines, [ exported( item_id="n3:0", relation="answers" ) ], packet(), { "s": [ "n1:0" ] } ) == er.BAD_LABEL
    assert code_of( rx.gold_lines, [ exported( item_id="zz:0" ) ], packet(), { "s": [ "zz:0" ] } ) == er.BAD_LABEL
    broken = packet()
    del broken[ "refs" ][ "n1:0" ]
    assert code_of( rx.gold_lines, [ exported() ], broken, { "s": [ "n1:0" ] } ) == er.BAD_LABEL
    for line in ( exported( relation="agrees" ), exported( item_id="n2:1", relation="no_recommendation_on_card" ), exported( item_id="n3:0", relation="support" ) ):
        assert code_of( rx.gold_lines, [ line ], packet(), SECTIONS ) == er.BAD_LABEL


def files( tmp_path, lines, sections=None ):
    """Write the export, packet and sections files; return the argv beginning."""
    ( tmp_path / "export.json" ).write_text( json.dumps( lines ), encoding="utf-8" )
    ( tmp_path / "packet.json" ).write_text( json.dumps( packet() ), encoding="utf-8" )
    ( tmp_path / "sections.json" ).write_text( json.dumps( SECTIONS if sections is None else sections ), encoding="utf-8" )
    return [ "--export", str( tmp_path / "export.json" ), "--packet", str( tmp_path / "packet.json" ), "--sections", str( tmp_path / "sections.json" ),
             "--store", str( tmp_path / "gold.jsonl" ), "--archive-dir", str( tmp_path / "archive" ) ]


def test_main_stores_the_lines_archives_the_export_once_and_reports_what_is_left( tmp_path, capsys ):
    argv = files( tmp_path, [ exported(), exported( item_id="n2:1", relation="expands_recommendation" ) ] )
    assert rx.main( argv ) == 0
    summary = json.loads( capsys.readouterr().out )
    stored  = gs.read_gold( tmp_path / "gold.jsonl" )
    assert [ l[ "relation" ] for l in stored ] == [ "support", "expands_recommendation" ] and { l[ "batch_id" ] for l in stored } == { f"rick-{PAGE}-blind-share" }
    assert summary[ "written" ] == 2 and summary[ "items_on_page" ] == 3 and summary[ "unanswered" ] == 1
    assert summary[ "human_labelled_by_stance" ] == { "yes": 1, "no": 0, "neither": 0, "none": 1 }
    saved = tmp_path / "archive" / summary[ "archived_as" ].split( "/" )[ -1 ]
    assert saved.exists() and json.loads( saved.read_text( encoding="utf-8" ) )[ 0 ][ "item_id" ] == "n1:0"
    assert rx.main( argv ) == 0
    assert len( list( ( tmp_path / "archive" ).iterdir() ) ) == 1


def test_main_with_an_empty_export_writes_no_store_line_and_still_succeeds( tmp_path, capsys ):
    assert rx.main( files( tmp_path, [] ) ) == 0
    assert json.loads( capsys.readouterr().out )[ "written" ] == 0 and not ( tmp_path / "gold.jsonl" ).exists()


def test_main_refuses_a_bad_export_or_an_unreadable_file_and_writes_nothing( tmp_path, capsys ):
    argv = files( tmp_path, [ exported( item_id="zz:0" ) ] )
    assert rx.main( argv ) == 2 and "cannot read the export" in capsys.readouterr().err
    assert not ( tmp_path / "gold.jsonl" ).exists() and not ( tmp_path / "archive" ).exists()
    assert rx.main( [ "--export", str( tmp_path / "absent.json" ), *argv[ 2: ] ] ) == 2


def test_main_stops_with_exit_three_on_a_damaged_store_and_archives_nothing( tmp_path, capsys ):
    argv = files( tmp_path, [ exported() ] )
    ( tmp_path / "gold.jsonl" ).write_text( '{"torn": ', encoding="utf-8" )
    assert rx.main( argv ) == 3 and "gold store refused" in capsys.readouterr().err
    assert not ( tmp_path / "archive" ).exists()
