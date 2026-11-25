"""
The agreement report: Rick against each reader, and the readers against each other.
"""
import json

import pytest

from cosa.repo.labelling import agreement_report as ar
from cosa.repo.labelling import errors as er
from cosa.repo.labelling import gold_store as gs
from cosa.repo.labelling import rick_export as rx
from cosa.repo.labelling import rick_page as rp

BLIND    = rx.batch_id_of( "abc", rp.DRAW_SECTION )
DISPUTES = rx.batch_id_of( "abc", "reader disagreements" )


def line( item, relation, source="ai_reader", reader="reader-1", batch="b", ts="2026-11-24T10:00:00+00:00" ):
    """Return one gold line."""
    return { "item_id": item, "notification_id": f"n-{item}", "field_key": "answer", "relation": relation, "card_stance": "yes",
             "source": source, "reader": reader, "batch_id": batch, "ts": ts }


def rick( item, relation, batch=BLIND, ts="2026-11-24T10:00:00+00:00" ):
    """Return one of Rick's lines."""
    return line( item, relation, source="human", reader="rick", batch=batch, ts=ts )


def test_a_known_pair_list_gives_the_worked_kappa_and_the_bar_reading():
    pairs = [ ( "support", "support" ), ( "support", "dissent" ), ( "dissent", "dissent" ), ( "dissent", "dissent" ) ]
    got   = ar.kappa_or_none( pairs )
    assert got == { "n": 4, "kappa": 0.5, "reason": None, "raw_agreement": 0.75, "meets_bar": False }
    perfect = ar.kappa_or_none( [ ( "support", "support" ), ( "dissent", "dissent" ) ] )
    assert perfect[ "kappa" ] == 1.0 and perfect[ "meets_bar" ] is True


def test_a_kappa_that_cannot_be_computed_is_none_with_its_reason_and_never_zero_or_one():
    one = ar.kappa_or_none( [ ( "support", "support" ), ( "support", "support" ) ] )
    assert one[ "kappa" ] is None and one[ "meets_bar" ] is None and "one category" in one[ "reason" ] and one[ "n" ] == 2 and one[ "raw_agreement" ] == 1.0
    none = ar.kappa_or_none( [] )
    assert none == { "n": 0, "kappa": None, "reason": ar.NO_PAIRS, "raw_agreement": None, "meets_bar": None }


def test_an_error_other_than_undefined_kappa_is_not_swallowed():
    with pytest.raises( er.LabellingError ) as e: ar.kappa_or_none( [ ( "support", "not-a-label" ) ] )
    assert e.value.code == er.BAD_LABEL


def test_the_latest_line_of_a_labeller_counts_and_other_labellers_are_left_out():
    lines = [ line( "a", "support" ), line( "a", "dissent" ), line( "b", "agrees" ), line( "a", "answers", reader="reader-2" ), rick( "a", "support" ) ]
    assert ar.relations_by_item( lines, gs.SOURCE_READER, "reader-1" ) == { "a": "dissent", "b": "agrees" }
    assert ar.relations_by_item( lines, gs.SOURCE_READER, "reader-1", batch_suffix="-x" ) == {}
    assert ar.relations_by_item( lines, gs.SOURCE_READER, "reader-2" ) == { "a": "answers" }


def test_only_rick_blind_share_lines_count_and_his_dispute_section_lines_do_not():
    lines = [ rick( "a", "support" ), rick( "b", "dissent", batch=DISPUTES ), rick( "c", "agrees" ), rick( "c", "expands_recommendation" ) ]
    assert ar.rick_blind_share( lines ) == { "a": "support", "c": "expands_recommendation" }
    assert BLIND.endswith( ar.BLIND_SUFFIX ) and not DISPUTES.endswith( ar.BLIND_SUFFIX ) and ar.BLIND_SUFFIX == "blind-share"


def test_a_later_line_from_the_dispute_batch_never_overrides_the_blind_share_label():
    lines = [ rick( "a", "support", ts="2026-11-24T10:00:00+00:00" ), rick( "a", "dissent", batch=DISPUTES, ts="2026-11-24T11:00:00+00:00" ),
              rick( "b", "agrees", ts="2026-11-24T10:00:00+00:00" ), rick( "b", "expands_recommendation", ts="2026-11-24T12:00:00+00:00" ) ]
    assert ar.rick_blind_share( lines ) == { "a": "support", "b": "expands_recommendation" }
    both = lines + [ line( "a", "support", reader="reader-1" ), line( "a", "support", reader="reader-2" ) ]
    assert ar.report( both, { "a": "yes_no" } )[ "rick_against" ][ "reader-1" ][ "all" ][ "raw_agreement" ] == 1.0


def test_compare_pairs_only_shared_items_and_splits_by_type_with_untyped_items_in_all_only():
    first  = { "a": "support", "b": "support", "c": "dissent", "d": "agrees", "x": "support" }
    second = { "a": "support", "b": "dissent", "c": "dissent", "d": "agrees" }
    types  = { "a": "yes_no", "b": "yes_no", "c": "yes_no", "d": "multiple_choice", "z": "open_ended" }
    got    = ar.compare( first, second, types )
    assert set( got ) == { "all", "yes_no", "multiple_choice", "open_ended" }
    assert got[ "all" ][ "n" ] == 4 and got[ "yes_no" ][ "n" ] == 3 and got[ "multiple_choice" ][ "n" ] == 1
    assert got[ "open_ended" ] == { "n": 0, "kappa": None, "reason": ar.NO_PAIRS, "raw_agreement": None, "meets_bar": None }
    assert got[ "multiple_choice" ][ "kappa" ] is None and "one category" in got[ "multiple_choice" ][ "reason" ]


def world():
    """Return ( lines, types ): Rick's 4 blind items and 1 dispute item, both readers on all 5."""
    items  = { "a": "yes_no", "b": "yes_no", "c": "multiple_choice", "d": "multiple_choice", "e": "open_ended" }
    lines  = [ rick( "a", "support" ), rick( "b", "dissent" ), rick( "c", "agrees" ), rick( "d", "wrote_own_answer" ), rick( "e", "answers", batch=DISPUTES ) ]
    r1     = { "a": "support", "b": "support", "c": "agrees", "d": "wrote_own_answer", "e": "answers" }
    r2     = { "a": "support", "b": "dissent", "c": "agrees", "d": "expands_recommendation", "e": "re_frame" }
    lines += [ line( i, r, reader="reader-1" ) for i, r in r1.items() ] + [ line( i, r, reader="reader-2" ) for i, r in r2.items() ]
    return lines, items


def test_the_report_holds_rick_against_each_reader_on_his_blind_share_and_the_readers_against_each_other():
    lines, types = world()
    got = ar.report( lines, types )
    assert got[ "bar" ] == 0.7 and got[ "rick_items" ] == 4
    assert got[ "rick_against" ][ "reader-1" ][ "all" ][ "n" ] == 4 and got[ "rick_against" ][ "reader-1" ][ "all" ][ "raw_agreement" ] == 0.75
    assert got[ "rick_against" ][ "reader-2" ][ "all" ][ "n" ] == 4 and got[ "rick_against" ][ "reader-2" ][ "all" ][ "raw_agreement" ] == 0.75
    assert got[ "rick_against" ][ "reader-2" ][ "yes_no" ][ "kappa" ] == 1.0 and got[ "rick_against" ][ "reader-1" ][ "yes_no" ][ "kappa" ] == 0.0
    assert got[ "readers_against_each_other" ][ "all" ][ "n" ] == 5 and got[ "readers_against_each_other" ][ "open_ended" ][ "n" ] == 1
    assert got[ "rick_against" ][ "reader-1" ][ "open_ended" ][ "n" ] == 0


def test_with_no_label_from_rick_every_kappa_is_none_with_a_reason():
    lines = [ line( "a", "support" ), line( "a", "support", reader="reader-2" ) ]
    got   = ar.report( lines, { "a": "yes_no" } )
    assert got[ "rick_items" ] == 0 and got[ "rick_against" ][ "reader-1" ][ "all" ][ "reason" ] == ar.NO_PAIRS
    assert got[ "readers_against_each_other" ][ "all" ][ "kappa" ] is None and "one category" in got[ "readers_against_each_other" ][ "all" ][ "reason" ]


def files( tmp_path ):
    """Write a store and a types file; return the argv."""
    lines, types = world()
    store = tmp_path / "gold.jsonl"
    gs.append_gold( store, lines )
    ( tmp_path / "types.json" ).write_text( json.dumps( types ), encoding="utf-8" )
    return [ "--types", str( tmp_path / "types.json" ), "--store", str( store ) ]


def test_main_prints_the_report_with_the_types_file_hash_and_writes_it_once( tmp_path, capsys ):
    import hashlib
    argv = files( tmp_path )
    out  = tmp_path / "report.json"
    assert ar.main( [ *argv, "--out", str( out ) ] ) == 0
    got  = json.loads( capsys.readouterr().out )
    assert got[ "card_types" ] == { "file": str( tmp_path / "types.json" ), "sha256": hashlib.sha256( ( tmp_path / "types.json" ).read_bytes() ).hexdigest(), "items": 5 }
    assert json.loads( out.read_text( encoding="utf-8" ) ) == got and got[ "rick_items" ] == 4
    assert ar.main( [ *argv, "--out", str( out ) ] ) == 2


def test_main_without_out_prints_only_and_a_missing_or_damaged_input_gives_exit_two( tmp_path, capsys ):
    argv = files( tmp_path )
    assert ar.main( argv ) == 0 and json.loads( capsys.readouterr().out )[ "bar" ] == 0.7
    assert ar.main( [ "--types", str( tmp_path / "absent.json" ), *argv[ 2: ] ] ) == 2
    ( tmp_path / "gold.jsonl" ).write_text( '{"torn": ', encoding="utf-8" )
    assert ar.main( argv ) == 2 and "cannot read" in capsys.readouterr().err
