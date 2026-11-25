"""
Tests for src/scripts/build_item_card_types.py.

The database is a scratch copy of the notifications table, the same one the sample builder is tested on.
"""
import contextlib
import hashlib
import json
import sys

import pytest

import cosa.utils.util as cu
from cosa.repo.labelling import errors as er
from test_build_answer_card_sample import add, cohort, db   # noqa: F401  (the db fixture)

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import build_item_card_types as bic   # noqa: E402


def packet_of( cards ):
    """Return a packet with one item per ( card, number ) pair."""
    blind = [ { "item_id": f"{c}:{n}", "type": "answer_meaning_card", "payload": {} } for c, n in cards ]
    return { "blind": blind, "refs": { b[ "item_id" ]: { "notification_id": b[ "item_id" ].split( ":" )[ 0 ], "field_key": "answer" } for b in blind } }


def test_every_item_takes_the_type_of_its_card():
    packet = packet_of( [ ( "c1", 0 ), ( "c2", 0 ), ( "c2", 1 ) ] )
    assert bic.card_types( packet, { "yes_no": [ "c1" ], "multiple_choice": [ "c2" ], "open_ended": [] } ) == { "c1:0": "yes_no", "c2:0": "multiple_choice", "c2:1": "multiple_choice" }


def test_an_item_with_no_ref_or_a_card_in_no_type_or_in_two_types_is_refused():
    packet = packet_of( [ ( "c1", 0 ) ] )
    del packet[ "refs" ][ "c1:0" ]
    for bad, pop in ( ( packet, { "yes_no": [ "c1" ] } ), ( packet_of( [ ( "c1", 0 ) ] ), { "yes_no": [ "zz" ] } ), ( packet_of( [ ( "c1", 0 ) ] ), { "yes_no": [ "c1" ], "open_ended": [ "c1" ] } ) ):
        with pytest.raises( er.LabellingError ) as e: bic.card_types( bad, pop )
        assert e.value.code == er.BAD_ITEM


def test_main_writes_the_mapping_once_and_prints_the_hashes_a_reader_can_check( db, tmp_path, capsys ):   # noqa: F811
    yes   = add( db )
    mc    = add( db, "multiple_choice", value={ "answers": { "H": "x" } } )
    open1 = add( db, "open_ended", value={ "value": "text" } )
    packet = tmp_path / "packet.json"
    packet.write_text( json.dumps( packet_of( [ ( yes, 0 ), ( mc, 0 ), ( mc, 1 ), ( open1, 0 ) ] ) ), encoding="utf-8" )
    out   = tmp_path / "types.json"
    scope = lambda: contextlib.nullcontext( db )   # noqa: E731
    argv  = [ "--packet", str( packet ), "--out", str( out ), "--cohort", cohort( tmp_path, [ yes, mc ] ) ]
    assert bic.main( argv, session_scope=scope ) == 0
    receipt = json.loads( capsys.readouterr().out )
    assert json.loads( out.read_text( encoding="utf-8" ) ) == { f"{yes}:0": "yes_no", f"{mc}:0": "multiple_choice", f"{mc}:1": "multiple_choice", f"{open1}:0": "open_ended" }
    assert receipt[ "file_sha256" ] == hashlib.sha256( out.read_bytes() ).hexdigest() and receipt[ "items" ] == 4
    assert receipt[ "items_by_type" ] == { "yes_no": 1, "multiple_choice": 2, "open_ended": 1, "open_ended_batch": 0 }
    assert receipt[ "population" ][ "yes_no" ] == { "count": 1, "sha256": hashlib.sha256( yes.encode() ).hexdigest() }
    assert bic.main( argv, session_scope=scope ) == 2 and "never overwritten" in capsys.readouterr().err


def test_main_refuses_an_unreadable_packet_or_a_card_with_no_type_and_writes_nothing( db, tmp_path, capsys ):   # noqa: F811
    scope = lambda: contextlib.nullcontext( db )   # noqa: E731
    base  = [ "--out", str( tmp_path / "t.json" ), "--cohort", cohort( tmp_path, [] ) ]
    assert bic.main( [ "--packet", str( tmp_path / "absent.json" ), *base ], session_scope=scope ) == 2
    stray = tmp_path / "packet.json"
    stray.write_text( json.dumps( packet_of( [ ( "not-a-card", 0 ) ] ) ), encoding="utf-8" )
    assert bic.main( [ "--packet", str( stray ), *base ], session_scope=scope ) == 2 and "cannot build the mapping" in capsys.readouterr().err
    assert not ( tmp_path / "t.json" ).exists()


def test_main_opens_the_configured_database_when_no_session_is_given( db, tmp_path, capsys, monkeypatch ):   # noqa: F811
    import cosa.rest.db.database as database
    monkeypatch.setattr( database, "get_db", lambda: contextlib.nullcontext( db ) )
    yes    = add( db )
    packet = tmp_path / "packet.json"
    packet.write_text( json.dumps( packet_of( [ ( yes, 0 ) ] ) ), encoding="utf-8" )
    assert bic.main( [ "--packet", str( packet ), "--out", str( tmp_path / "t.json" ), "--cohort", cohort( tmp_path, [ yes ] ) ] ) == 0

