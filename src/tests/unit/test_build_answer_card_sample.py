"""
Tests for src/scripts/build_answer_card_sample.py.

The database is a scratch copy of the notifications table. The committed filter is the real one, so a
Stop-hook card is dropped by Rachel's title match and not by a copy of it. A changed rule fails a named test.
"""

import contextlib
import json
import sys
import uuid
from datetime import datetime, timezone

import pytest

import cosa.utils.util as cu
from cosa.repo.labelling import errors as er
from cosa.repo.labelling import voice_batches as vb
from cosa.research.preference_replay.scratch_db import scratch_session
from cosa.rest.postgres_models import Notification

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import build_answer_card_sample as bas   # noqa: E402

RECIPIENT = uuid.uuid4()
STOP      = "Stop hook: Anything else?"


class Session:
    """
    A session over the scratch copy.

    SQLite has no read-only transaction, so that statement passes. It keeps uuids as bare hex, so the
    ids of the title query come back dashed, as Postgres returns them.
    """

    def __init__( self, real ): self.real = real

    def execute( self, statement, params=None ):
        if "SET TRANSACTION" in str( statement ): return None
        if params is None: return self.real.execute( statement )
        return [ ( str( uuid.UUID( str( row[ 0 ] ) ) ), ) for row in self.real.execute( statement, params ) ]

    def __getattr__( self, name ): return getattr( self.real, name )


@pytest.fixture
def db():
    with scratch_session() as real: yield Session( real )


def add( db, response_type="yes_no", value=None, source="ui", state="responded", title="A title", message="A question?", options=None, **extra ):
    value = { "value": "yes" } if value is None and response_type in ( "yes_no", "open_ended" ) else value
    if isinstance( value, dict ) and "source" not in value and source is not None: value = dict( value, source=source )
    row = dict( id=uuid.uuid4(), sender_id="s", recipient_id=RECIPIENT, message=message, type="task", priority="medium", title=title,
                created_at=datetime( 2026, 11, 1, tzinfo=timezone.utc ), response_requested=True, state=state, response_type=response_type,
                response_value=value, response_options=options )
    row.update( extra )
    db.add( Notification( **row ) )
    db.commit()
    return str( row[ "id" ] )


def questions( *specs ):
    return { "questions": [ { "header": h, "question": f"{h}?", "options": [ { "label": o, "recommended": r } for o, r in opts ],
                              **( { "input_type": "text" } if not opts else {} ) } for h, opts in specs ] }


def cohort( tmp_path, ids ):
    path = tmp_path / "cohort.jsonl"
    path.write_text( "".join( json.dumps( { "id": one } ) + "\n" for one in ids ) )
    return str( path )


def row_of( db, nid ): return db.query( Notification ).filter( Notification.id == uuid.UUID( nid ) ).one()


def test_the_quotas_are_the_576_cards_of_the_row():
    assert bas.QUOTAS == { "yes_no": 200, "multiple_choice": 180, "open_ended": 100, "open_ended_batch": 96 } and sum( bas.QUOTAS.values() ) == 576


def test_only_a_persons_own_answer_counts( db ):
    own = add( db )
    assert bas.counts_as_answer( row_of( db, own ) )
    assert not bas.counts_as_answer( row_of( db, add( db, source="timeout_default" ) ) )
    assert not bas.counts_as_answer( row_of( db, add( db, source="api" ) ) )
    assert not bas.counts_as_answer( row_of( db, add( db, source=None ) ) )
    assert not bas.counts_as_answer( row_of( db, add( db, options={ "review_card": True } ) ) )


def test_the_population_cuts_the_stop_hook_cards_with_the_filter_and_keeps_only_answers( db, tmp_path ):
    keep, stop, late = add( db ), add( db, title=STOP ), add( db, source="timeout_default" )
    mc    = add( db, "multiple_choice", value={ "answers": { "H": "x" } } )
    open1 = add( db, "open_ended", value={ "value": "text" } )
    open2 = add( db, "open_ended", value={ "value": "t" }, state="expired" )
    open3 = add( db, "open_ended", value={ "value": "t" }, source="timeout_default" )
    batch = add( db, "open_ended_batch", value={ "answers": { "H": "t" } } )
    stray = add( db )   # answered but not in the cohort: left out
    got   = bas.population( db, cohort( tmp_path, [ keep, stop, late, mc ] ) )
    assert got[ "population" ] == { "yes_no": [ keep ], "multiple_choice": [ mc ], "open_ended": [ open1 ], "open_ended_batch": [ batch ] }
    assert got[ "stop_hook_dropped" ] == 1 and stray not in got[ "rows" ] and open2 not in got[ "rows" ] and open3 not in got[ "rows" ]
    assert set( got[ "rows" ] ) == { keep, mc, open1, batch }


def test_the_draw_is_seeded_uniform_and_independent_of_input_order():
    ids = [ f"id{n:03d}" for n in range( 100 ) ]
    one = bas.draw( ids, 20, "s", "yes_no" )
    assert one == bas.draw( list( reversed( ids ) ), 20, "s", "yes_no" ) and len( set( one ) ) == 20 and set( one ) <= set( ids )
    assert one != bas.draw( ids, 20, "other", "yes_no" ) and one != bas.draw( ids, 20, "s", "multiple_choice" )
    assert bas.draw( ids, 100, "s", "yes_no" ) == ids


def test_a_type_short_of_its_quota_stops_the_build():
    with pytest.raises( ValueError, match="fewer than the quota of 3" ): bas.draw( [ "a" ], 3, "s", "yes_no" )


def test_a_yes_no_card_is_one_item_with_its_stance_and_a_message_that_repeats_the_title_is_not_doubled( db ):
    nid  = add( db, value={ "value": "yes [comment: but later]" }, title="Merge now", message="Merge now, or wait?", abstract="Details" )
    made, blanks = bas.card_items( row_of( db, nid ) )
    ( item, ref ), = made
    assert blanks == 0 and ref == { "notification_id": nid, "field_key": "answer" } and item[ "item_id" ] == f"{nid}:0"
    assert item[ "payload" ] == { "card_text": "Merge now, or wait?\nDetails", "options": [], "recommendation": None,
                                  "answer": "yes [comment: but later]", "stance_class": "yes" }


def test_a_title_that_is_not_in_the_message_stays_and_a_missing_title_is_skipped( db ):
    first  = bas.card_items( row_of( db, add( db, title="Heading", message="Body" ) ) )[ 0 ][ 0 ][ 0 ]
    second = bas.card_items( row_of( db, add( db, title=None, message="Body" ) ) )[ 0 ][ 0 ][ 0 ]
    assert first[ "payload" ][ "card_text" ] == "Heading\nBody" and second[ "payload" ][ "card_text" ] == "Body"


def test_a_yes_no_string_with_no_stance_and_an_open_ended_answer_are_stance_class_none( db ):
    text  = bas.card_items( row_of( db, add( db, value={ "value": "Maybe later" } ) ) )[ 0 ][ 0 ][ 0 ]
    free  = bas.card_items( row_of( db, add( db, "open_ended", value={ "value": "yes please" } ) ) )[ 0 ][ 0 ][ 0 ]
    assert text[ "payload" ][ "stance_class" ] == "none" and free[ "payload" ][ "stance_class" ] == "none" and free[ "payload" ][ "answer" ] == "yes please"


def test_a_blank_answer_gives_no_item_and_is_counted( db ):
    assert bas.card_items( row_of( db, add( db, "open_ended", value={ "value": "  " } ) ) ) == ( [], 1 )


def test_a_multiple_choice_card_gives_one_item_per_answered_header_with_options_and_the_recommended_label( db ):
    opts = questions( ( "Pick", [ ( "Alpha (Recommended)", True ), ( "Beta", False ) ] ), ( "Many", [ ( "x", False ), ( "y", False ) ] ), ( "Skipped", [ ( "p", False ) ] ) )
    nid  = add( db, "multiple_choice", value={ "answers": { "Pick": "Beta", "Many": [ "x", "y" ], "Skipped": [] } }, options=opts )
    made, blanks = bas.card_items( row_of( db, nid ) )
    assert blanks == 1 and [ r[ "field_key" ] for _, r in made ] == [ "Pick", "Many" ] and [ i[ "item_id" ] for i, _ in made ] == [ f"{nid}:0", f"{nid}:1" ]
    first, second = made[ 0 ][ 0 ][ "payload" ], made[ 1 ][ 0 ][ "payload" ]
    assert first[ "options" ] == [ "Alpha (Recommended)", "Beta" ] and first[ "recommendation" ] == "Alpha (Recommended)" and first[ "answer" ] == "Beta"
    assert second[ "recommendation" ] is None and second[ "answer" ] == "x, y" and first[ "card_text" ].endswith( "Pick?" )
    assert first[ "stance_class" ] == second[ "stance_class" ] == "none"


def test_a_batch_card_gives_a_text_item_per_header_and_a_stance_word_there_is_not_a_stance( db ):
    opts = questions( ( "One", [] ), ( "Two", [] ) )
    nid  = add( db, "open_ended_batch", value={ "answers": { "One": "yes", "Two": "words" } }, options=opts )
    made, _ = bas.card_items( row_of( db, nid ) )
    assert [ i[ "payload" ][ "answer" ] for i, _ in made ] == [ "yes", "words" ] and [ i[ "payload" ][ "stance_class" ] for i, _ in made ] == [ "none", "none" ]
    assert made[ 0 ][ 0 ][ "payload" ][ "options" ] == []


def test_a_header_less_field_is_keyed_answer_and_an_unreadable_answer_map_gives_nothing( db ):
    opts = { "questions": [ { "question": "Q?", "options": [ { "label": "a" } ] } ] }
    nid  = add( db, "multiple_choice", value={ "answers": { "x": "a" } }, options=opts )
    assert bas.card_items( row_of( db, nid ) ) == ( [], 1 )
    bad  = add( db, "multiple_choice", value={ "weird": 1 }, options=opts )
    assert bas.card_items( row_of( db, bad ) ) == ( [], 1 )


def test_a_header_less_field_with_an_answer_is_keyed_answer( db, monkeypatch ):
    monkeypatch.setattr( bas, "parse_field_selections", lambda value: { None: { "selected": [ "a" ] } } )
    opts = { "questions": [ { "question": "Q?", "options": [ { "label": "a" } ] } ] }
    ( item, ref ), = bas.card_items( row_of( db, add( db, "multiple_choice", value={ "answers": {} }, options=opts ) ) )[ 0 ]
    assert ref[ "field_key" ] == "answer" and item[ "payload" ][ "answer" ] == "a"


def test_an_item_that_fails_its_validator_stops_loudly( db ):
    with pytest.raises( er.LabellingError ): bas.card_items( row_of( db, add( db, message="  ", title=None, value={ "value": "yes" } ) ) )


def small_world( db, tmp_path ):
    ids  = [ add( db, value={ "value": "yes" if n % 2 else "no" }, message=f"Question {n}?" ) for n in range( 6 ) ]
    ids += [ add( db, title=STOP ) ]
    mc   = [ add( db, "multiple_choice", value={ "answers": { "H": "b" } }, options=questions( ( "H", [ ( "a", True ), ( "b", False ) ] ) ), message=f"M{n}?" ) for n in range( 4 ) ]
    op   = [ add( db, "open_ended", value={ "value": f"text {n}" }, message=f"O{n}?" ) for n in range( 3 ) ]
    ba   = [ add( db, "open_ended_batch", value={ "answers": { "A": "t", "B": "u" } }, options=questions( ( "A", [] ), ( "B", [] ) ) ) for _ in range( 2 ) ]
    return cohort( tmp_path, ids + mc )


QUOTAS_SMALL = { "yes_no": 4, "multiple_choice": 3, "open_ended": 2, "open_ended_batch": 2 }


def test_build_makes_a_blind_only_packet_with_a_ref_for_every_item_and_a_receipt( db, tmp_path ):
    packet, receipt = bas.build( db, small_world( db, tmp_path ), "seed-1", "dev", QUOTAS_SMALL )
    assert set( packet ) == { "name", "blind", "disputes", "refs" } and packet[ "name" ] == "dev" and packet[ "disputes" ] == []
    assert len( packet[ "blind" ] ) == 4 + 3 + 2 + 4 and set( packet[ "refs" ] ) == { i[ "item_id" ] for i in packet[ "blind" ] }
    assert all( set( i[ "payload" ] ) == { "card_text", "options", "recommendation", "answer", "stance_class" } for i in packet[ "blind" ] )
    assert receipt == { "seed": "seed-1", "stop_hook_dropped": 1, "blank_fields_left_out": 0, "batches": 1,
                        "types": { "yes_no": { "population": 6, "cards": 4, "items": 4 }, "multiple_choice": { "population": 4, "cards": 3, "items": 3 },
                                   "open_ended": { "population": 3, "cards": 2, "items": 2 }, "open_ended_batch": { "population": 2, "cards": 2, "items": 4 } } }
    assert vb.voice_batches( packet, "seed-1", bas.CHASE_START )[ 0 ][ "batch_id" ]


def test_the_same_seed_gives_the_same_packet_and_another_seed_a_different_one( db, tmp_path ):
    path = small_world( db, tmp_path )
    one  = bas.build( db, path, "a", "dev", QUOTAS_SMALL )[ 0 ]
    assert one == bas.build( db, path, "a", "dev", QUOTAS_SMALL )[ 0 ] and one[ "refs" ] != bas.build( db, path, "b", "dev", QUOTAS_SMALL )[ 0 ][ "refs" ]


def test_build_defaults_to_the_576_card_quotas_and_stops_when_the_world_is_smaller( db, tmp_path ):
    with pytest.raises( ValueError, match="fewer than the quota of 200" ): bas.build( db, small_world( db, tmp_path ), "s", "dev" )


def test_build_counts_blank_fields_left_out( db, tmp_path ):
    nid  = add( db, "multiple_choice", value={ "answers": { "H": "b", "G": [] } }, options=questions( ( "H", [ ( "b", False ) ] ), ( "G", [ ( "c", False ) ] ) ) )
    receipt = bas.build( db, cohort( tmp_path, [ nid ] ), "s", "dev", { "multiple_choice": 1 } )[ 1 ]
    assert receipt[ "blank_fields_left_out" ] == 1 and receipt[ "types" ][ "multiple_choice" ][ "items" ] == 1


def test_main_writes_the_packet_once_prints_the_receipt_and_refuses_to_overwrite( db, tmp_path, capsys, monkeypatch ):
    cohort_path = small_world( db, tmp_path )
    out         = tmp_path / "packet.json"
    monkeypatch.setattr( bas, "QUOTAS", QUOTAS_SMALL )
    scope       = lambda: contextlib.nullcontext( db )
    assert bas.main( [ "--seed", "s", "--cohort", cohort_path, "--out", str( out ) ], session_scope=scope ) == 0
    printed = json.loads( capsys.readouterr().out )
    assert printed[ "seed" ] == "s" and json.loads( out.read_text() )[ "name" ] == "dev-sample"
    before = out.read_text()
    assert bas.main( [ "--seed", "t", "--cohort", cohort_path, "--out", str( out ), "--name", "x" ], session_scope=scope ) == 2
    assert out.read_text() == before and "never overwritten" in capsys.readouterr().err


def test_main_opens_the_configured_database_when_no_session_is_given( db, tmp_path, capsys, monkeypatch ):
    from cosa.rest.db import database
    monkeypatch.setattr( database, "get_db", lambda: contextlib.nullcontext( db ) )
    monkeypatch.setattr( bas, "QUOTAS", QUOTAS_SMALL )
    assert bas.main( [ "--seed", "s", "--cohort", small_world( db, tmp_path ), "--out", str( tmp_path / "p.json" ) ] ) == 0
    assert json.loads( capsys.readouterr().out )[ "batches" ] == 1
