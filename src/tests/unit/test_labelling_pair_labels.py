"""
Pair labels: the choice-to-boolean rule, and the store a reviewer's page writes.

Packets come from the real producer, export_packets, and labels are read back through the real reader, read_labels.
"""
import json

import pytest

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl

CLOCK = lambda: "2026-10-26T21:00:00+00:00"


def make_packet( tmp_path, count=3 ):
    """Write a two-reviewer packet folder with the real exporter and return rick's packet path."""
    items = [ it.make_item( it.SEMDUP_PAIR, f"pair-{n}", { "a": f"def a{n}(): pass", "b": f"def b{n}(): pass" } ) for n in range( count ) ]
    return pk.export_packets( items, [ "rick", "other" ], "seed", tmp_path )[ "rick" ]


def test_the_rule_maps_as_proposed_to_same_job_and_none_to_not():
    assert pl.SAME_JOB_OF_CHOICE == { pk.AS_PROPOSED: True, pk.NONE: False }
    assert pk.OTHER not in pl.SAME_JOB_OF_CHOICE


def test_same_job_reads_a_label_and_refuses_other():
    assert pl.same_job( { "item_id": "x", "choice": pk.AS_PROPOSED } ) is True
    assert pl.same_job( { "item_id": "x", "choice": pk.NONE } ) is False
    with pytest.raises( er.LabellingError ) as e: pl.same_job( { "item_id": "x", "choice": pk.OTHER } )
    assert e.value.code == er.BAD_LABEL


def test_unsure_is_a_note_prefix_and_user_note_strips_it():
    assert pl.is_unsure( { "note": "UNSURE: hmm" } ) and pl.user_note( { "note": "UNSURE: hmm" } ) == "hmm"
    assert pl.user_note( { "note": "UNSURE:" } ) == ""
    assert not pl.is_unsure( { "note": "unsure: hmm" } ) and pl.user_note( { "note": "plain" } ) == "plain"


def test_names_come_from_the_packet_file_name( tmp_path ):
    assert pl.reviewer_of( tmp_path / "packet-rick.jsonl" ) == "rick"
    assert pl.labels_path( tmp_path / "packet-rick.jsonl" ) == tmp_path / "labels-rick.jsonl"
    for bad in ( "packet-.jsonl", "packet-a b.jsonl", "rick.jsonl", "packet-rick.txt" ):
        with pytest.raises( er.LabellingError ) as e: pl.reviewer_of( tmp_path / bad )
        assert e.value.code == er.BAD_ITEM


def test_load_items_gives_id_a_b_only_in_packet_order( tmp_path ):
    path  = make_packet( tmp_path )
    items = pl.load_items( path )
    assert [ sorted( i ) for i in items ] == [ [ "a", "b", "item_id" ] ] * 3
    assert [ i[ "item_id" ] for i in items ] == [ json.loads( l )[ "item_id" ] for l in path.read_text().splitlines() ]


def test_load_items_refuses_a_leak_and_a_need_item( tmp_path ):
    leak = tmp_path / "packet-rick.jsonl"
    leak.write_text( json.dumps( { "item_id": "p", "type": "semdup_pair", "payload": { "a": "x", "b": "y", "verdict": "SAME" } } ) + "\n" )
    with pytest.raises( er.LabellingError ) as e: pl.load_items( leak )
    assert e.value.code == er.PACKET_LEAK
    need = tmp_path / "packet-need.jsonl"
    need.write_text( json.dumps( it.make_item( it.NEED_KEY, "n", { "need": "x", "key_sources": [ "s" ] } ) ) + "\n" )
    with pytest.raises( er.LabellingError ) as e: pl.load_items( need )
    assert e.value.code == er.BAD_ITEM


def test_progress_resumes_at_first_unlabelled_then_first_unsure_then_none():
    items = [ { "item_id": f"p{n}" } for n in range( 4 ) ]
    mk    = lambda i, note="": { "item_id": i, "note": note }
    assert pl.progress( items, [] ) == { "total": 4, "labelled": 0, "unsure": 0, "resume": 0 }
    assert pl.progress( items, [ mk( "p0" ), mk( "p2" ) ] )[ "resume" ] == 1
    full = [ mk( "p0" ), mk( "p1", "UNSURE: x" ), mk( "p2" ), mk( "p3", "UNSURE:" ) ]
    assert pl.progress( items, full ) == { "total": 4, "labelled": 4, "unsure": 2, "resume": 1 }
    assert pl.progress( items, [ mk( n[ "item_id" ] ) for n in items ] )[ "resume" ] is None


def test_build_label_choice_note_and_limit():
    yes = pl.build_label( "p", "rick", True, False, "  fine ", CLOCK )
    assert yes == { "item_id": "p", "reviewer": "rick", "choice": "AS_PROPOSED", "symbols": [], "note": "fine", "ts": CLOCK() }
    assert pl.build_label( "p", "rick", False, True, "why", CLOCK )[ "choice" ] == "NONE"
    assert pl.build_label( "p", "rick", False, True, "why", CLOCK )[ "note" ] == "UNSURE: why"
    assert pl.build_label( "p", "rick", False, True, "", CLOCK )[ "note" ] == "UNSURE:"
    with pytest.raises( er.LabellingError ) as e: pl.build_label( "p", "rick", True, False, "x" * ( pl.MAX_NOTE + 1 ), CLOCK )
    assert e.value.code == er.BAD_LABEL


def test_now_text_is_iso_utc():
    assert pl.now_text().endswith( "+00:00" )


def test_save_label_writes_a_file_read_labels_accepts_and_the_loader_reads( tmp_path ):
    path = make_packet( tmp_path )
    ids  = [ i[ "item_id" ] for i in pl.load_items( path ) ]
    pl.save_label( path, ids[ 0 ], True, clock=CLOCK )
    pl.save_label( path, ids[ 1 ], False, True, "close call", clock=CLOCK )
    out = pl.labels_path( path )
    assert [ l[ "item_id" ] for l in pk.read_labels( out ) ] == ids[ :2 ]
    assert pl.same_job_labels( out ) == { ids[ 0 ]: True, ids[ 1 ]: False }
    assert not list( tmp_path.glob( "*.tmp" ) )


def test_a_re_answer_replaces_the_line_in_place_and_never_duplicates( tmp_path ):
    path = make_packet( tmp_path )
    ids  = [ i[ "item_id" ] for i in pl.load_items( path ) ]
    for n in ids: pl.save_label( path, n, True, clock=CLOCK )
    pl.save_label( path, ids[ 1 ], False, False, "changed my mind", clock=CLOCK )
    labels = pk.read_labels( pl.labels_path( path ) )
    assert [ l[ "item_id" ] for l in labels ] == ids
    assert [ ( l[ "choice" ], l[ "note" ] ) for l in labels ] == [ ( "AS_PROPOSED", "" ), ( "NONE", "changed my mind" ), ( "AS_PROPOSED", "" ) ]


def test_save_label_refuses_an_unknown_item_and_writes_nothing( tmp_path ):
    path = make_packet( tmp_path )
    with pytest.raises( er.LabellingError ) as e: pl.save_label( path, "pair-nope", True, clock=CLOCK )
    assert e.value.code == er.BAD_ITEM
    assert not pl.labels_path( path ).exists()


def test_a_failed_check_leaves_the_old_file_untouched_and_no_temp( tmp_path ):
    path = make_packet( tmp_path )
    ids  = [ i[ "item_id" ] for i in pl.load_items( path ) ]
    pl.save_label( path, ids[ 0 ], True, clock=CLOCK )
    before = pl.labels_path( path ).read_bytes()
    with pytest.raises( er.LabellingError ) as e: pl.save_label( path, ids[ 1 ], True, clock=lambda: "" )
    assert e.value.code == er.BAD_LABEL
    assert pl.labels_path( path ).read_bytes() == before
    assert not list( tmp_path.glob( "*.tmp" ) )


def test_read_existing_is_empty_before_the_first_label( tmp_path ):
    assert pl.read_existing( make_packet( tmp_path ) ) == []
