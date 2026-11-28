"""
Tests for src/scripts/arm_forecast_pairs.py.

The database is a real scratch copy and the three arms run through their own jobs.
Only two things are replaced. The model transport answers from the prompt it is given, and the embedder reads the text.
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import cosa.utils.util as cu
from cosa.agents.prediction_engine import answer_history_forecast, context_baseline
from cosa.research.preference_replay.scratch_db import scratch_session
from cosa.rest.postgres_models import Notification, PredictionArmForecast

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import arm_forecast_pairs as afp   # noqa: E402

OWNER = uuid.uuid4()
START = datetime( 2026, 9, 20, 12, 0, tzinfo=timezone.utc )
JWT   = { "user_id": str( OWNER ), "method": "jwt" }


def uid( number ):
    """Give a fixed card id."""
    return str( uuid.UUID( int=( 0xabc << 116 ) + number ) )   # letters, so SQLite never reads the hex as a number


def card( number, response_type, value, message="Deploy the build now?", options=None, source="ui", hours=0 ):
    """Make one answered notification."""
    asked = START + timedelta( hours=hours or number )
    return Notification( id=uuid.UUID( uid( number ) ), sender_id="s@x", recipient_id=OWNER, message=message, type="custom", priority="medium", state="responded",
                         response_requested=True, response_type=response_type, response_options=options, created_at=asked, responded_at=asked + timedelta( minutes=1 ),
                         response_value={ "value": value, "source": source, "answered_by": JWT } )


CHOICE = { "questions": [ { "header": "Plan", "question": "Which plan?", "options": [ { "label": "Fast" }, { "label": "Safe" } ] } ] }
BATCH  = { "questions": [ { "header": "len", "question": "How long?", "input_type": "text" } ] }


class Embed:
    """An embedder whose vector depends on the text's first letter."""

    encoder = "test-encoder"

    def __init__( self, cache_path=None ):
        self.cache_path = cache_path
        self.flushed    = 0

    def __call__( self, words ): return [ 1.0, 0.001 * ( ord( words[ :1 ] or "a" ) % 7 ) ] + [ 0.0 ] * 766

    def flush( self ): self.flushed += 1


class Engine:
    """The one part of the engine the case store reads: a classifier."""

    class classifier:
        @staticmethod
        def classify( message, sender_id=None ): return ( "general", 1.0 )


class LiveSession:
    """A scratch session standing in for the live one; SQLite has no read-only transaction."""

    def __init__( self, real ):
        self.real      = real
        self.read_only = False

    def execute( self, statement ):
        self.read_only = "SET TRANSACTION READ ONLY" in str( statement )

    def query( self, *args ): return self.real.query( *args )

    def rollback( self ): self.real.rollback()


def test_eligible_without_meaning_keeps_only_earlier_human_answers_of_the_owner():
    base = { "answer_source": "human", "owner_user_id": "me", "ratification_state": None, "responded_at": START }
    good, late = { **base, "id": "good" }, { **base, "id": "late", "responded_at": START + timedelta( days=2 ) }
    cases = [ good, late, { **base, "id": "other", "owner_user_id": "x" }, { **base, "id": "auto", "answer_source": "unknown" },
              { **base, "id": "down", "ratification_state": "rejected" } ]
    assert [ c[ "id" ] for c in afp.eligible_without_meaning( None, cases, "me", START + timedelta( days=1 ) ) ] == [ "good" ]


def test_add_missing_columns_restores_a_dropped_column_and_makes_the_meaning_table( tmp_path ):
    path = str( tmp_path / "old.sqlite" )
    with scratch_session( path ) as session:
        session.execute( text( "ALTER TABLE prediction_arm_forecast DROP COLUMN applicability" ) )
        session.commit()
        assert afp.add_missing_columns( session.get_bind() ) == [ "prediction_arm_forecast.applicability" ]
        assert session.execute( text( "SELECT count(*) FROM answer_meaning" ) ).scalar() == 0
        assert session.query( PredictionArmForecast ).all() == []
        assert afp.add_missing_columns( session.get_bind() ) == []


def test_import_live_copies_only_the_answered_cards_the_copy_lacks():
    with scratch_session() as scratch, scratch_session() as live:
        scratch.add( card( 1, "yes_no", "yes" ) )
        scratch.commit()
        unanswered = card( 3, "yes_no", "yes" )
        unanswered.responded_at = None
        live.add_all( [ card( 1, "yes_no", "no" ), card( 2, "open_ended", "later" ), unanswered ] )
        live.commit()
        wrapped = LiveSession( live )
        assert afp.import_live( scratch, wrapped ) == 1
        assert wrapped.read_only
        assert { str( n.id ): n.response_value[ "value" ] for n in scratch.query( Notification ) } == { uid( 1 ): "yes", uid( 2 ): "later" }


def test_the_id_lists_read_the_sample_and_the_records( tmp_path ):
    types = tmp_path / "types.json"
    types.write_text( json.dumps( { "b:0": "open_ended_batch", "b:1": "open_ended_batch", "a:0": "open_ended", "c:0": "yes_no" } ) )
    records = tmp_path / "records.jsonl"
    records.write_text( "".join( json.dumps( { "id": i, "response_type": t } ) + "\n" for i, t in ( ( "m", "multiple_choice" ), ( "y", "yes_no" ), ( "n", "multiple_choice" ) ) ) )
    assert afp.sample_open_ids( str( types ) ) == [ "a", "b" ]
    assert afp.archive_ids( str( records ) ) == [ "y", "m", "n" ]


@pytest.mark.parametrize( "kind, forecast, actual, rows", [
    ( "yes_no", None, "yes", [] ),
    ( "yes_no", { "value": "no" }, "yes", [] ),
    ( "yes_no", { "value": "yes" }, "yes", [ ( "", None, None ) ] ),
    ( "yes_no", { "value": "yes", "qualifier": "only after tests" }, "yes [comment: after lunch]", [ ( "", "only after tests", "after lunch" ) ] ),
    ( "open_ended", { "gist": "ship it" }, "hold it", [ ( "", "ship it", "hold it" ) ] ),
    ( "open_ended", { "acts": {} }, "hold it", [] ),
    ( "open_ended_batch", { "fields": { "len": { "gist": "short" } } }, '{"answers":{"len":"long","other":"x"}}', [ ( "len", "short", "long" ) ] ),
    ( "open_ended_batch", { "gist": "no fields" }, '{"answers":{"len":"long"}}', [] ),
    ( "multiple_choice", { "answers": { "Plan": "Fast" } }, '{"answers":{"Plan":"Safe"}}', [ ( "Plan", "Fast", "Safe" ) ] ),
    ( "multiple_choice", { "answers": { "Plan": [ "Fast", "Safe" ] }, "qualifier": "today" }, '{"answers":{"Plan":["Safe"]}}', [ ( "Plan", "Fast; Safe; today", "Safe" ) ] ),
    ( "multiple_choice", { "fields": { "Plan": { "write_in": "neither one" } } }, '{"answers":{"Plan":"typed"}}', [ ( "Plan", "neither one", "typed" ) ] ),
    ( "multiple_choice", { "fields": { "Plan": { "reframe": "wrong question" } } }, '{"answers":{"Plan":"typed"}}', [ ( "Plan", "wrong question", "typed" ) ] ),
    ( "multiple_choice", { "answers": {} }, '{"answers":{"Plan":"Safe"}}', [] ),
    ( "multiple_choice", { "answers": { "Plan": "Fast" } }, '{"answers":{"Plan":[]}}', [] ),
    ( "multiple_choice", { "answers": { "Plan": "Fast" } }, "not an answers map", [] ),
] )
def test_texts_of( kind, forecast, actual, rows ):
    assert afp.texts_of( kind, forecast, actual ) == rows


PLAN_CARD = { "response_type": "multiple_choice", "options": CHOICE }


@pytest.mark.parametrize( "answered, forecast, differs", [
    ( '"Safe"',               { "answers": { "Plan": "Safe" } }, False ),
    ( '"Safe"',               { "answers": { "Plan": "Fast" }, "qualifier": "today" }, True ),
    ( '["Safe","Fast"]',      { "answers": { "Plan": [ "Fast", " Safe " ] } }, False ),
    ( '["Safe"]',             { "answers": { "Plan": [ "Fast", "Safe" ] } }, True ),
    ( '"Safe"',               { "fields": { "Plan": { "write_in": "a third plan" } } }, True ),
    ( '"something of my own"', { "fields": { "Plan": { "write_in": "a third plan" } } }, False ),
] )
def test_option_mismatch_compares_the_choice_and_not_the_words( answered, forecast, differs ):
    card = { **PLAN_CARD, "actual_value": '{"answers":{"Plan":' + answered + '}}' }
    assert afp.option_mismatch( card, "Plan", forecast ) is differs


def test_option_mismatch_reads_a_yes_no_stance_and_open_pairs_carry_none():
    card = { "response_type": "yes_no", "actual_value": "no [comment: x]", "options": None }
    assert [ afp.option_mismatch( card, "", { "value": v } ) for v in ( "no", "yes" ) ] == [ False, True ]
    pairs, _ = afp.make_pairs( { "c": { "response_type": "open_ended", "actual_value": "a", "options": None } }, [ ( "c", "C0", { "gist": "b" } ) ], { "C0": "h" } )
    assert "option_mismatch" not in pairs[ 0 ]


@pytest.mark.parametrize( "kind, forecast, actual", [
    ( "yes_no", { "value": "yes", "qualifier": "ONLY-IF" }, "yes" ),
    ( "multiple_choice", { "answers": { "Plan": "Fast" }, "qualifier": "ONLY-IF" }, '{"answers":{"Plan":"Safe"}}' ),
    ( "multiple_choice", { "fields": { "Plan": { "write_in": "typed" } }, "qualifier": "ONLY-IF" }, '{"answers":{"Plan":"Safe"}}' ),
    ( "open_ended", { "gist": "ship it", "qualifier": "ONLY-IF" }, "hold" ),
    ( "open_ended_batch", { "fields": { "len": { "gist": "short" }, "who": { "gist": "me" } }, "qualifier": "ONLY-IF" }, '{"answers":{"len":"long","who":"you"}}' ),
] )
def test_no_card_type_drops_the_forecasts_conditions( kind, forecast, actual ):
    rows = afp.texts_of( kind, forecast, actual )
    assert rows and all( "ONLY-IF" in predicted for _, predicted, _ in rows )


def test_a_batch_field_with_no_gist_makes_no_row_even_with_conditions():
    assert afp.texts_of( "open_ended_batch", { "fields": {}, "qualifier": "ONLY-IF" }, '{"answers":{"len":"long"}}' ) == []


@pytest.mark.parametrize( "said, points_back", [
    ( "yes, as in earlier answers", True ), ( "the same as their Previous pick", True ), ( "declines like last time", True ), ( "approves, as the owner did", True ),
    ( "ship it before lunch", False ), ( None, False ),
] )
def test_refers_to_earlier( said, points_back ):
    assert afp.refers_to_earlier( said ) is points_back


def test_joined_writes_each_shape():
    assert [ afp._joined( None ), afp._joined( ( "a", "b" ) ), afp._joined( 3 ) ] == [ None, "a; b", "3" ]


def test_make_pairs_blinds_the_arm_and_flags_a_literal_mismatch():
    cards = { "c1": { "response_type": "yes_no", "actual_value": "yes [comment: Wait]", "options": None }, "c2": { "response_type": "yes_no", "actual_value": "yes", "options": None } }
    pairs, key = afp.make_pairs( cards, [ ( "c1", "C0", { "value": "yes" } ), ( "c1", "B1", { "value": "yes", "qualifier": " wait " } ),
                                          ( "c2", "C0", { "value": "yes" } ), ( "absent", "C0", { "value": "yes" } ) ], { "C0": "haiku", "B1": "haiku" } )
    one = hashlib.sha256( b"c1||C0" ).hexdigest()[ :16 ]
    assert [ p[ "pair_id" ] for p in pairs ] == sorted( key ) and len( pairs ) == 3
    assert key[ one ] == { "arm": "C0", "model": "haiku" }
    by_id = { p[ "pair_id" ]: p for p in pairs }
    assert by_id[ one ] == { "pair_id": one, "notification_id": "c1", "response_type": "yes_no", "field_key": "", "predicted_text": None, "actual_text": "Wait", "literal_mismatch": True,
                             "refers_to_earlier": False, "option_mismatch": False }
    assert [ by_id[ afp.pair_id_of( c, "", a ) ][ "literal_mismatch" ] for c, a in ( ( "c1", "B1" ), ( "c2", "C0" ) ) ] == [ False, False ]
    assert not { "arm", "model" } & set( by_id[ one ] )


def test_human_cards_leaves_out_a_default_and_a_value_that_is_not_text():
    with scratch_session() as session:
        odd = card( 3, "yes_no", "yes" )
        odd.response_value = { "value": { "a": 1 }, "source": "ui" }
        session.add_all( [ card( 1, "yes_no", "yes" ), card( 2, "yes_no", "yes", source="timeout_default" ), odd ] )
        session.commit()
        assert afp.human_cards( session, [ uid( 1 ), uid( 2 ), uid( 3 ) ] ) == { uid( 1 ): { "response_type": "yes_no", "actual_value": "yes", "options": None } }


def test_stored_forecasts_prefers_the_copy_and_count_table_counts( tmp_path ):
    records, twins = tmp_path / "records.jsonl", tmp_path / "twins.jsonl"
    records.write_text( json.dumps( { "id": uid( 1 ), "arms": { "A0": { "forecast": { "value": "yes" } }, "C0": { "forecast": None } } } ) + "\n" )
    twins.write_text( json.dumps( { "id": uid( 1 ), "arms": { "C0-opus": { "forecast": None } } } ) + "\n" )
    with scratch_session() as session:
        session.add( card( 1, "yes_no", "yes" ) )
        session.add( PredictionArmForecast( notification_id=uuid.UUID( uid( 1 ) ), arm="C0", forecast={ "value": "yes" }, input_cutoff=START ) )
        session.commit()
        found = afp.stored_forecasts( session, str( records ), str( twins ) )
    assert found == { ( uid( 1 ), "A0" ): { "value": "yes" }, ( uid( 1 ), "C0" ): { "value": "yes" }, ( uid( 1 ), "C0-opus" ): None }
    cards  = { uid( 1 ): { "response_type": "yes_no", "actual_value": "yes [comment: x]", "options": None } }
    models = afp.arm_models( "h", "o" )
    pairs, key = afp.make_pairs( cards, [ ( c, a, f ) for ( c, a ), f in { **found, ( "gone", "A0" ): None }.items() ], models )
    table = afp.count_table( pairs, key, { **found, ( "gone", "A0" ): None }, cards )
    assert table[ "A0" ][ "yes_no" ] == { "cards": 1, "abstained": 0, "pairs": 1, "literal_mismatch": 1, "option_mismatch": 0, "refers_to_earlier": 0 }
    assert table[ "C0-opus" ][ "yes_no" ] == { "cards": 1, "abstained": 1, "pairs": 0, "literal_mismatch": 0, "option_mismatch": 0, "refers_to_earlier": 0 }
    assert [ models[ a ] for a in ( "C0", "answer_history", "B1-opus", "engine" ) ] == [ "h", "h", "o", "none" ]


def test_write_outputs_writes_a_manifest_and_never_overwrites( tmp_path ):
    out = tmp_path / "pairs"
    afp.write_outputs( str( out ), [ { "pair_id": "p" } ], { "p": { "arm": "C0" } }, { "pairs": 1 }, [ { "notification_id": "n" } ] )
    lines = ( out / afp.MANIFEST_NAME ).read_text().splitlines()
    assert lines == [ f"{hashlib.sha256( ( out / n ).read_bytes() ).hexdigest()}  {n}" for n in ( "pairs.jsonl", "key.json", "receipt.json", "cards.jsonl" ) ]
    assert ( out / "cards.jsonl" ).read_text() == '{"notification_id": "n"}\n'
    with pytest.raises( FileExistsError ): afp.write_outputs( str( out ), [], {}, {}, [] )
    assert ( out / "pairs.jsonl" ).read_text() == '{"pair_id": "p"}\n'


def test_prepare_work_copies_once( tmp_path ):
    archive, work = tmp_path / "archive", tmp_path / "work"
    archive.mkdir()
    ( archive / "archive.sqlite" ).write_text( "db" )
    ( archive / "embeddings.json" ).write_text( "{}" )
    database, cache = afp.prepare_work( str( archive ), str( work ) )
    ( work / "archive.sqlite" ).write_text( "changed" )
    assert afp.prepare_work( str( archive ), str( work ) ) == ( database, cache )
    assert ( work / "archive.sqlite" ).read_text() == "changed" and ( work / "embeddings.json" ).read_text() == "{}"


def test_matched_budget_refuses_no_card():
    with pytest.raises( ValueError, match="no card" ): afp.matched_budget( None, [], None, None, None, None, None )


class Transport:
    """Stands in for the SDK call: a full-answer reply built from the prompt's card type."""

    def __init__( self ): self.prompts = []

    async def __call__( self, model, system, user, query_fn=None, timeout_seconds=None, **options ):
        self.prompts.append( user )
        reply = { "acts": { a: ( 1 if a == "approve" else 0 ) for a in ( "approve", "decline", "challenge_premise", "request_information", "defer", "propose_alternative" ) },
                  "qualification": { "probability": 0.5, "conditions": [ { "text": "after the tests", "modifies_option_id": None } ] },
                  "gist": "go ahead", "whole_card_probability": 0.6 }
        if '"probabilities"' in user: reply[ "probabilities" ] = { "yes": 0.8, "no": 0.1, "neither": 0.1 }
        # the card's own part comes before the history block, so an earlier card's field is never answered for this one
        own = user.split( answer_history_forecast.BLOCK_HEADING )[ 0 ]
        if "How long?" in own: reply[ "fields" ] = { "len": { "gist": "ten minutes" } }
        elif "Which plan?" in own: reply[ "fields" ] = { "Plan": { "write_in": "a third plan" } }
        return json.dumps( reply )


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """A run 2 folder with two choice-type cards, and two open-type cards in the live database."""
    archive = tmp_path / "archive"
    archive.mkdir()
    ( archive / "embeddings.json" ).write_text( "{}" )
    earlier = card( 1, "yes_no", "yes [comment: only after tests]" )
    now     = card( 2, "yes_no", "yes [comment: tonight]", hours=5 )
    choice  = card( 3, "multiple_choice", '{"answers":{"Plan":"Safe"}}', message="Which plan?", options=CHOICE, hours=6 )
    with scratch_session( str( archive / "archive.sqlite" ) ) as session:
        session.add_all( [ earlier, now, choice ] )
        session.commit()
    ( archive / "records.jsonl" ).write_text( "".join( json.dumps( { "id": uid( n ), "response_type": t, "arms": { "A0": { "forecast": { "value": "yes" } if t == "yes_no" else { "answers": { "Plan": "Fast" } } } } } ) + "\n"
                                                        for n, t in ( ( 2, "yes_no" ), ( 3, "multiple_choice" ) ) ) )
    ( archive / "twin-records.jsonl" ).write_text( "" )
    ( archive / "report.json" ).write_text( json.dumps( { "freeze": { "bound": 5000, "fetch_multiplier": 0, "extractor_version": "x", "baseline_model": "h", "twin_model": "o" } } ) )
    ( tmp_path / "types.json" ).write_text( json.dumps( { f"{uid( 4 )}:0": "open_ended", f"{uid( 5 )}:0": "open_ended_batch" } ) )
    live = scratch_session( str( tmp_path / "live.sqlite" ) )
    session = live.__enter__()
    session.add_all( [ card( 4, "open_ended", "do it tomorrow", message="What next?", hours=7 ), card( 5, "open_ended_batch", '{"answers":{"len":"an hour"}}', message="Missing arguments", options=BATCH, hours=8 ) ] )
    session.commit()

    @contextlib.contextmanager
    def live_scope(): yield LiveSession( session )

    transport = Transport()
    monkeypatch.setattr( context_baseline.model_transport, "complete", transport )
    monkeypatch.setattr( afp, "PredictionEngine", type( "P", (), { "__new__": lambda cls, debug=False: Engine(), "reset": staticmethod( lambda: None ) } ) )
    monkeypatch.setattr( afp.principles_forecast, "retrieve_principles", lambda *a, **k: { "principles": [] } )
    yield argparse.Namespace( root=tmp_path, archive=str( archive ), live_scope=live_scope, transport=transport, types=str( tmp_path / "types.json" ) )
    live.__exit__( None, None, None )


def test_main_forecasts_then_pairs_every_arm_and_type( world ):
    work, out, said = str( world.root / "work" ), str( world.root / "pairs" ), []
    common = [ "--archive", world.archive, "--types", world.types, "--work", work, "--out", out, "--full-work", str( world.root / "full" ) ]
    assert afp.main( [ "forecast", *common, "--concurrency", "2" ], live_scope=world.live_scope, make_embed=Embed, out=said.append ) == 0
    ran = json.loads( ( world.root / "work" / "forecast-receipt.json" ).read_text() )
    assert ran[ "imported_live_rows" ] == 2 and ran[ "open_cards" ] == 2 and ran[ "archive_cards" ] == 2
    assert ran[ "ruling" ] == afp.RULING
    # the receipt names the version the rows carry, which is the override's and not the committed arm's
    with scratch_session( work + "/archive.sqlite" ) as session:
        stamped = { r.predictor_version for r in session.query( PredictionArmForecast ).filter( PredictionArmForecast.arm == "answer_history" ) }
    assert stamped == { ran[ "predictor_version" ] + ran[ "answer_history_suffix" ] }
    assert ran[ "answer_history_suffix" ] != answer_history_forecast.version_suffix()
    assert { ( a, s, n ) for a, s, _, n in ran[ "jobs" ] } == { ( "answer_history", "ran", 4 ), ( "C0", "ran", 2 ), ( "B1", "ran", 2 ) }
    # no principle is retrieved here, so the measured budget is too small for one whole answer
    assert ran[ "history_rows" ] == { "rows": 4, "showed_nothing": 4 }
    assert any( line.startswith( "[forecast] 8/8" ) for line in said )
    assert afp.main( [ "full", *common ], make_embed=Embed, out=said.append ) == 0
    assert afp.main( [ "pairs", *common ], make_embed=Embed, out=said.append ) == 0
    pairs = [ json.loads( line ) for line in ( world.root / "pairs" / "pairs.jsonl" ).read_text().splitlines() ]
    key   = json.loads( ( world.root / "pairs" / "key.json" ).read_text() )
    assert { ( key[ p[ "pair_id" ] ][ "arm" ], p[ "response_type" ] ) for p in pairs } >= { ( "A0", "yes_no" ), ( "A0", "multiple_choice" ), ( "C0", "open_ended" ), ( "B1", "open_ended_batch" ), ( "answer_history", "yes_no" ), ( "C0-full", "yes_no" ), ( "B1-full", "multiple_choice" ) }
    shown = [ json.loads( line ) for line in ( world.root / "pairs" / "cards.jsonl" ).read_text().splitlines() ]
    assert [ c[ "notification_id" ] for c in shown ] == sorted( { p[ "notification_id" ] for p in pairs } )
    assert next( c for c in shown if c[ "notification_id" ] == uid( 3 ) ) == { "notification_id": uid( 3 ), "response_type": "multiple_choice", "message": "Which plan?", "abstract": None,
                                                                              "options": CHOICE, "answer": '{"answers":{"Plan":"Safe"}}' }
    receipt = json.loads( ( world.root / "pairs" / "receipt.json" ).read_text() )
    assert receipt[ "cards" ] == { "yes_no": 1, "multiple_choice": 1, "open_ended": 1, "open_ended_batch": 1 } and receipt[ "pairs" ] == len( pairs )


def test_main_shows_history_when_the_budget_allows_it( world ):
    work = str( world.root / "work" )
    assert afp.main( [ "forecast", "--archive", world.archive, "--types", world.types, "--work", work, "--budget", "2000", "--limit", "2" ], live_scope=world.live_scope, make_embed=Embed, out=lambda line: None ) == 0
    assert any( answer_history_forecast.BLOCK_HEADING in p and "only after tests" in p for p in world.transport.prompts )
    assert answer_history_forecast.eligible_cases is not afp.eligible_without_meaning   # the override is undone after the run
    with scratch_session( work + "/archive.sqlite" ) as session: shown = afp.history_rows( session )
    assert shown[ "showed_nothing" ] < shown[ "rows" ]


def test_main_without_a_live_scope_reads_the_apps_database( world, monkeypatch ):
    from cosa.rest.db import database
    monkeypatch.setattr( database, "get_db", world.live_scope )
    seen = []
    monkeypatch.setattr( afp, "run_forecast", lambda args, session, scope, embed, out: seen.append( scope ) or {} )
    assert afp.main( [ "forecast", "--archive", world.archive, "--work", str( world.root / "w" ) ], make_embed=Embed, out=lambda line: None ) == 0
    assert seen == [ world.live_scope ]


def test_run_forecast_with_no_live_scope_imports_nothing( world ):
    work = world.root / "w2"
    database, cache = afp.prepare_work( world.archive, str( work ) )
    args = argparse.Namespace( archive=world.archive, types=world.types, work=str( work ), budget=0, limit=None, concurrency=1 )
    with scratch_session( database ) as session:
        receipt = afp.run_forecast( args, session, None, Embed( cache ), out=lambda line: None )
    assert receipt[ "imported_live_rows" ] == 0 and receipt[ "open_cards" ] == 0


def test_full_sample_is_seeded_and_capped_per_type( tmp_path ):
    records = tmp_path / "records.jsonl"
    records.write_text( "".join( json.dumps( { "id": f"y{i}", "response_type": "yes_no" } ) + "\n" for i in range( 6 ) ) + json.dumps( { "id": "m", "response_type": "multiple_choice" } ) + "\n" )
    drawn = afp.full_sample( str( records ), 2 )
    assert drawn == afp.full_sample( str( records ), 2 ) and len( drawn ) == 3 and drawn[ 2 ] == "m" and len( set( drawn[ :2 ] ) ) == 2
    assert afp.full_sample( str( records ), 0 ) == []


def test_the_full_stage_records_its_sample_before_the_first_call_and_leaves_the_archive_alone( world, monkeypatch ):
    full   = world.root / "full"
    before = hashlib.sha256( ( world.root / "archive" / "archive.sqlite" ).read_bytes() ).hexdigest()
    seen   = []
    real   = world.transport.__call__

    async def watching( *args, **kwargs ):
        seen.append( ( full / "sample.json" ).exists() )
        return await real( *args, **kwargs )

    monkeypatch.setattr( context_baseline.model_transport, "complete", watching )
    argv = [ "full", "--archive", world.archive, "--full-work", str( full ), "--per-type", "5" ]
    assert afp.main( argv, make_embed=Embed, out=lambda line: None ) == 0
    assert seen and all( seen )
    sample = json.loads( ( full / "sample.json" ).read_text() )
    assert sample[ "ids" ] == [ uid( 2 ), uid( 3 ) ] and sample[ "ids_sha256" ] == hashlib.sha256( f"{uid( 2 )}\n{uid( 3 )}\n".encode() ).hexdigest()
    assert hashlib.sha256( ( world.root / "archive" / "archive.sqlite" ).read_bytes() ).hexdigest() == before
    found, receipt = afp.full_stage_forecasts( str( full ) )
    assert sorted( found ) == [ ( uid( n ), a ) for n in ( 2, 3 ) for a in ( "B1-full", "C0-full" ) ]
    assert found[ ( uid( 2 ), "C0-full" ) ][ "qualifier" ] == "after the tests" and receipt[ "cards" ] == 2
    assert afp.main( argv, make_embed=Embed, out=lambda line: None ) == 0, "the same sample resumes"
    with pytest.raises( ValueError, match="another sample" ):
        afp.record_sample( str( full ), [ uid( 2 ) ], 1 )
    assert afp.arm_models( "h", "o" )[ "B1-full" ] == "h"
