"""
The archive replay, over the synthetic 50-target export and model doubles.

Everything here is synthetic. The models are doubles, the embeddings are stand-in vectors and the database is a scratch copy.
So nothing reaches a live model, the embedding service or a GPU. A run of the real archive is a local-data run, not a test.

Each group names what it would catch:
  - a fixture ask predicted, or a chunk predicted twice or never   -> test_*_evaluation_*, test_a_stopped_run_*
  - an answer extracted twice after a restart                       -> test_a_stopped_run_*
  - a twin running ahead of the first stage                         -> test_the_twins_*
  - a pairing that reads the wrong arm, or counts an abstention     -> test_the_report_*
"""

import json
import os
from datetime import timedelta

import pytest

from cosa.agents.prediction_engine import opus_twins, principles_forecast
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay import archive_replay as ar
from cosa.research.preference_replay import extractor_replay as er
from cosa.research.preference_replay.replay_loop import ENGINE_ARM
from cosa.research.preference_replay.scratch_db import scratch_session
from cosa.research.preference_replay.service_embeddings import CachedServiceEmbedder
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PreferenceEvidence

FIXTURE = os.path.join( os.path.dirname( __file__ ), "fixtures", "episode_view", "synthetic-context-50.json" )


class Failed( Exception ):
    """A failed model call, as the baseline's contract declares it."""


class Haiku:
    """
    A baseline double that always forecasts the first option, and records every call.

    It holds the contract principles_forecast checks: model, timeout, errors, version, build_prompts, parse and complete.
    """
    model             = "haiku-x"
    timeout_seconds   = 30
    errors            = ( Failed, )
    predictor_version = "c0-v1"

    def __init__( self, fail_for=None ):
        self.calls    = []
        self.fail_for = fail_for

    def build_prompts( self, episode ):
        """Give the baseline's own prompts, which depend on the card."""
        return "SYSTEM", f"USER {episode[ 'message' ]}"

    async def complete( self, model, system, user, timeout_seconds=None ):
        """Record the call and answer, or fail for the card named."""
        self.calls.append( ( model, user ) )
        if self.fail_for is not None and self.fail_for in user: raise Failed( "the model failed" )
        return "ok"

    def parse( self, text, episode ):
        """Forecast yes for a yes/no card and each field's first option for a choice."""
        if episode[ "response_type" ] == "yes_no": return { "value": "yes", "confidence": 0.9 }
        return { "answers": { f[ "key" ]: f[ "options" ][ 0 ][ "label" ] for f in episode[ "fields" ] if f[ "options" ] }, "confidence": 0.9 }


def _open_embedder( tmp_path ):
    """Make an embedder over stand-in vectors, with its side file in the test folder."""
    return CachedServiceEmbedder( str( tmp_path / "embeddings.json" ), embed=er.stand_in_vector, encoder="test-encoder:v1" )


def _models( session, embed, c0=None, caps=( 2, 2, 1, 1 ) ):
    """Make the model arms over the scratch session, with a recording baseline."""
    c0    = Haiku() if c0 is None else c0
    gates = { ar.ARM_BASELINE: principles_forecast.CapGate( caps[ 0 ] ), ar.ARM_PRINCIPLES: principles_forecast.CapGate( caps[ 1 ] ),
              ar.TWIN_ARMS[ 0 ]: principles_forecast.CapGate( caps[ 2 ] ), ar.TWIN_ARMS[ 1 ]: principles_forecast.CapGate( caps[ 3 ] ) }
    return ar.ModelArms( ar.locked_sessions( session.get_bind() ), c0, embed, embed.encoder, f"{ar.EXTRACTOR_MODEL}:{ar.PROMPT_VERSION}", gates ), c0


@pytest.fixture
def export():
    """Load the synthetic export."""
    with open( FIXTURE, encoding="utf-8" ) as handle: return json.load( handle )


@pytest.fixture
def archive( tmp_path, export ):
    """
    Write the synthetic export as the two archive files and a fixture file of five targets.

    Ensures:
        - returns ( asks path, non-asks path, fixture path, fixture ids ); asks are the notifications that request a response
    """
    rows     = { r[ "notification" ][ "id" ]: r[ "notification" ] for r in export[ "records" ].values() }
    rows.update( { t[ "target_notification" ][ "id" ]: t[ "target_notification" ] for t in export[ "targets" ] } )
    asks     = [ r for r in rows.values() if r[ "response_requested" ] ]
    others   = [ r for r in rows.values() if not r[ "response_requested" ] ]
    ask_file = tmp_path / "asks.jsonl"
    non_file = tmp_path / "nonasks.jsonl"
    ask_file.write_text( "\n".join( json.dumps( r ) for r in asks ) + "\n" )
    non_file.write_text( "\n".join( json.dumps( r ) for r in others ) + ( "\n" if others else "" ) )
    chosen   = export[ "targets" ][ :5 ]
    fixture  = tmp_path / "fixture.json"
    fixture.write_text( json.dumps( { "targets": chosen } ) )
    return str( ask_file ), str( non_file ), str( fixture ), { t[ "target_notification" ][ "id" ] for t in chosen }


@pytest.fixture
def engine():
    """Give the real engine with embedding made to fail, so a stored vector must be used."""
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "the replay embedded a message" )
    yield eng
    PredictionEngine.reset()


@pytest.fixture
def loaded( tmp_path, archive, engine ):
    """
    Give a file-backed scratch session with the archive loaded and the asks built.

    Ensures:
        - yields ( session, asks, evaluation ids, embedder, work folder, fixture ids )
    """
    asks_path, non_path, fixture_path, fixture = archive
    work  = ar.WorkFolder( str( tmp_path ) )
    embed = _open_embedder( tmp_path )
    with scratch_session( work.database ) as session:
        ar.load_archive( session, asks_path, non_path )
        asks = er.asks_from_session( session, engine, embed )
        yield session, asks, ar.evaluation_ids( asks, ar.fixture_ids( fixture_path ) ), embed, work, fixture


def test_the_archive_loads_once_and_a_second_load_leaves_it_alone( tmp_path, archive ):
    asks_path, non_path, _, _ = archive
    with scratch_session( str( tmp_path / "x.sqlite" ) ) as session:
        first = ar.load_archive( session, asks_path, non_path )
        assert first == session.query( Notification ).count() and first > 100
        assert ar.load_archive( session, asks_path, non_path ) == 0
        assert session.query( Notification ).count() == first


def test_the_evaluation_leaves_out_the_fixture_and_untyped_asks_and_keeps_replay_order( loaded ):
    session, asks, ids, _, _, fixture = loaded
    assert not set( ids ) & fixture and len( ids ) > 100
    kinds = { a[ "id" ]: a[ "response_type" ] for a in asks }
    assert {kinds[ i ] for i in ids} <= set( ar.ELIGIBLE_TYPES )
    times = { a[ "id" ]: a[ "asked_at" ] for a in asks }
    assert [ times[ i ] for i in ids ] == sorted( times[ i ] for i in ids )
    assert {a[ "id" ] for a in asks if a[ "id" ] in fixture} == fixture, "a fixture ask must stay in the case list"


def _first_stage( loaded, chunk=40, ids=None, models=None, out=None ):
    """Run the first stage over the synthetic asks with the canned extractor."""
    session, asks, all_ids, embed, work, _ = loaded
    models = models if models is not None else _models( session, embed )[ 0 ]
    engine = PredictionEngine( debug=False )
    return ar.run_first_stage( session, asks, all_ids if ids is None else ids, engine, embed, models, work, query_fn=er.canned_model, chunk=chunk, out=out or ( lambda line: None ) )


def test_the_first_stage_predicts_every_evaluation_ask_once_in_chunks_and_records_every_arm( loaded ):
    session, asks, ids, embed, work, fixture = loaded
    lines = []
    assert _first_stage( loaded, out=lines.append ) == len( ids )
    records = ar.read_jsonl( work.records )
    assert [ r[ "id" ] for r in records ] == ids and not {r[ "id" ] for r in records} & fixture
    assert set( records[ 0 ][ "arms" ] ) == set( ar.RECORDED_ARMS )
    state = ar.load_state( work.state )
    assert state[ "done_ids" ] == ids and len( lines ) == -( -len( ids ) // 40 )
    assert all( line.startswith( "[checkpoint]" ) for line in lines ) and f"{len( ids )}/{len( ids )}" in lines[ -1 ]


class CountingExtractor:
    """A canned extractor model that counts its calls."""

    def __init__( self ): self.calls = 0

    def __call__( self, prompt, options ):
        self.calls += 1
        return er.canned_model( prompt, options )


def _first_stage_counted( loaded, **kwargs ):
    """Run the first stage with a counting extractor and give ( models, c0, counter )."""
    session, asks, ids, embed, work, _ = loaded
    models, c0 = _models( session, embed )
    counter    = CountingExtractor()
    ids        = kwargs.pop( "ids", ids )
    ar.run_first_stage( session, asks, ids, PredictionEngine( debug=False ), embed, models, work, query_fn=counter, out=lambda line: None, **kwargs )
    return models, c0, counter


def test_each_haiku_arm_makes_one_call_per_ask_and_the_principles_block_reaches_the_principles_arm( loaded ):
    ids = loaded[ 2 ]
    _, c0, _ = _first_stage_counted( loaded, chunk=40 )
    assert len( c0.calls ) == 2 * len( ids ), "one baseline call and one principles call for each ask"
    with_block = [ user for _, user in c0.calls if principles_forecast.BLOCK_HEADING in user ]
    assert with_block, "the principles the replay extracted never reached the principles arm's prompt"
    assert len( with_block ) < len( c0.calls ) / 2 + 1, "only the principles arm may carry the block"


def test_a_stopped_run_resumes_from_its_checkpoint_without_repeating_an_ask_or_an_extraction( loaded ):
    session, asks, ids, embed, work, _ = loaded
    models, c0, counter = _first_stage_counted( loaded, chunk=20, ids=ids[ :60 ] )
    assert ar.load_state( work.state )[ "done_ids" ] == ids[ :60 ] and len( c0.calls ) == 120
    before = counter.calls
    models2, c0b, counter2 = _first_stage_counted( loaded, chunk=20 )
    state = ar.load_state( work.state )
    assert state[ "done_ids" ] == ids and [ r[ "id" ] for r in ar.read_jsonl( work.records ) ] == ids
    assert len( c0b.calls ) == 2 * ( len( ids ) - 60 ), "the first 60 asks were predicted again"
    assert len( set( state[ "extracted_ids" ] ) ) == len( state[ "extracted_ids" ] ) and before + counter2.calls == len( state[ "extracted_ids" ])
    assert _first_stage_counted( loaded, chunk=20 )[ 2 ].calls == 0, "a finished run made a call"


def test_an_answer_whose_evidence_is_in_the_database_is_not_extracted_again_even_without_a_checkpoint( loaded ):
    session, asks, ids, embed, work, _ = loaded
    _, c0, _ = _first_stage_counted( loaded, chunk=40, ids=ids[ :30 ] )
    version  = f"{ar.EXTRACTOR_MODEL}:{ar.PROMPT_VERSION}"
    held     = ar.extracted_in_db( session, version )
    assert held, "the first run left no evidence to resume from"
    os.remove( work.state )
    calls_before = len( c0.calls )
    _, c0b, counter = _first_stage_counted( loaded, chunk=40, ids=ids[ :30 ] )
    answered = sorted( a[ "id" ] for a in asks if a[ "responded_at" ] is not None and a[ "responded_at" ] <= asks[ 0 ][ "responded_at" ] + timedelta( days=3650 ) )
    assert counter.calls <= len( answered ) - len( held ), "an answer with evidence on file was extracted again"
    assert len( c0b.calls ) == 0, "a card with a stored row was forecast again"


def test_a_model_failure_leaves_an_abstention_with_its_reason_and_is_charged_as_a_miss( loaded ):
    session, asks, ids, embed, work, _ = loaded
    victim  = next( a for a in asks if a[ "id" ] == ids[ 5 ] )
    models, c0 = _models( session, embed, c0=Haiku( fail_for=victim[ "message" ] ) )
    ar.run_first_stage( session, asks, ids[ :10 ], PredictionEngine( debug=False ), embed, models, work, query_fn=er.canned_model, chunk=5, out=lambda line: None )
    line = next( r for r in ar.read_jsonl( work.records ) if r[ "id" ] == victim[ "id" ] )
    for arm in ar.HAIKU_ARMS:
        assert line[ "arms" ][ arm ] == { "correct": False, "forecast": None, "reason": "model_error: Failed" }


def test_the_first_stage_checks_every_chunk_for_leakage_before_it_records_it( loaded, monkeypatch ):
    session, asks, ids, embed, work, _ = loaded
    seen_sizes = []
    monkeypatch.setattr( ar, "check_no_leakage", lambda seen: seen_sizes.append( len( seen ) ) )
    models, _ = _models( session, embed )
    ar.run_first_stage( session, asks, ids[ :12 ], PredictionEngine( debug=False ), embed, models, work, query_fn=er.canned_model, chunk=5, out=lambda line: None )
    assert seen_sizes == [ 5, 5, 2 ], "each chunk must be checked with every ask the chunk handed its arms"


def test_the_checkpoint_counts_the_asks_that_had_an_episode_history( loaded ):
    session, asks, ids, embed, work, _ = loaded
    _first_stage_counted( loaded, chunk=40 )
    state = ar.load_state( work.state )
    assert 0 < state[ "context_asks" ] < len( ids ), "the synthetic asks include some on a thread and some alone"
    log = [ json.loads( line )[ "line" ] for line in open( work.log ) ]
    assert f"{state[ 'context_asks' ]} so far" in log[ -1 ]


def test_fixed_rules_say_yes_and_pick_the_one_recommended_option_else_the_first():
    yes_no = { "response_type": "yes_no", "response_options": None }
    assert ar.fixed_rules_arm( yes_no, [] ) == { "value": "yes" }
    options = lambda *labels, **extra: { "header": extra.get( "header", "h" ), "question": "q", "options": [ { "label": label } for label in labels ], **{ k: v for k, v in extra.items() if k != "header" } }
    choice = lambda *questions: { "response_type": "multiple_choice", "response_options": { "questions": list( questions ) } }
    assert ar.fixed_rules_arm( choice( options( "A", "B" ) ), [] ) == { "answers": { "h": "A" } }
    assert ar.fixed_rules_arm( choice( options( "A", "B (Recommended)" ) ), [] ) == { "answers": { "h": "B (Recommended)" } }
    assert ar.fixed_rules_arm( choice( options( "A (Recommended)", "B (Recommended)" ) ), [] ) == { "answers": { "h": "A (Recommended)" } }
    assert ar.fixed_rules_arm( choice( options( "A", "B", multi_select=True ) ), [] ) == { "answers": { "h": [ "A" ] } }
    assert ar.fixed_rules_arm( choice( { "header": "t", "question": "q", "input_type": "text" } ), [] ) is None
    assert ar.fixed_rules_arm( choice( options( "A" ), { "header": "t", "question": "q", "input_type": "text" } ), [] ) == { "answers": { "h": "A" } }
    assert ar.fixed_rules_arm( { "response_type": "open_ended", "response_options": None }, [] ) is None


def test_the_python_search_orders_rows_by_cosine_and_cuts_at_the_limit( loaded ):
    session = loaded[ 0 ]
    class Row:
        def __init__( self, embedding ): self.embedding = embedding
    rows = [ Row( [ 1.0, 0.0 ] ), Row( [ 0.0, 1.0 ] ), Row( [ 1.0, 1.0 ] ) ]
    class Query:
        def filter( self, flt ): return self
        def all( self ): return rows
    class Fake:
        def query( self, model ): return Query()
    found = ar.scratch_topk( Fake(), None, None, [ 1.0, 0.0 ], limit=2, exclude_filter=True )
    assert [ r for _, r in found ] == [ rows[ 0 ], rows[ 2 ] ] and found[ 0 ][ 0 ] == pytest.approx( 100.0 ) and found[ 1 ][ 0 ] == pytest.approx( 70.71, abs=0.01 )


def test_state_and_lines_are_written_whole_and_read_back( tmp_path ):
    work = ar.WorkFolder( str( tmp_path ) )
    assert ar.load_state( work.state ) == { "extracted_ids": [], "done_ids": [], "not_replayable": 0, "unrebuildable": 0, "context_asks": 0 }
    ar.save_state( work.state, { "done_ids": [ "a" ] } )
    assert ar.load_state( work.state ) == { "done_ids": [ "a" ] } and not os.path.exists( f"{work.state}.tmp" )
    ar.append_lines( work.records, [ { "n": 1 }, { "n": 2 } ] )
    ar.append_lines( work.records, [ { "n": 3 } ] )
    assert ar.read_jsonl( work.records ) == [ { "n": 1 }, { "n": 2 }, { "n": 3 } ]
    ( tmp_path / "blank.jsonl" ).write_text( '{"a": 1}\n\n' )
    assert ar.read_jsonl( str( tmp_path / "blank.jsonl" ) ) == [ { "a": 1 } ]


def _twin_stage( loaded, ids, models, **kwargs ):
    """Run the twin stage over the given ids."""
    session, asks, _, _, work, _ = loaded
    lines = kwargs.pop( "lines", [] )
    return ar.run_twin_stage( session, asks, ids, models, work, out=lines.append, **kwargs )


def test_the_twins_run_only_asks_the_first_stage_recorded_and_score_each_row_like_the_harness( loaded ):
    session, asks, ids, embed, work, _ = loaded
    models, c0 = _models( session, embed )
    assert _twin_stage( loaded, ids[ :10 ], models ) == 0, "twins ran with nothing recorded"
    _first_stage_counted( loaded, chunk=10, ids=ids[ :10 ] )
    models, c0 = _models( session, embed )
    assert _twin_stage( loaded, ids[ :20 ], models ) == 10
    twin_lines = ar.read_jsonl( work.twins )
    assert [ t[ "id" ] for t in twin_lines ] == ids[ :10 ] and all( set( t[ "arms" ] ) == set( ar.TWIN_ARMS ) for t in twin_lines )
    assert len( c0.calls ) == 20, "one call per twin per ask"
    by_id = { a[ "id" ]: a for a in asks }
    for line in twin_lines:
        ask = by_id[ line[ "id" ] ]
        for arm in ar.TWIN_ARMS:
            assert line[ "arms" ][ arm ][ "correct" ] == ar._score( ask[ "response_type" ], line[ "arms" ][ arm ][ "forecast" ], ask[ "actual_value" ], ask[ "response_options" ] )
    rows = session.query( PredictionArmForecast ).filter( PredictionArmForecast.arm.in_( ar.TWIN_ARMS ) ).all()
    assert len( rows ) == 20, "one row per twin per ask"
    assert _twin_stage( loaded, ids[ :20 ], models ) == 0, "an ask the twins already ran was run again"


def test_the_twins_call_opus_not_haiku( loaded ):
    session, asks, ids, embed, work, _ = loaded
    _first_stage_counted( loaded, chunk=5, ids=ids[ :5 ] )
    c0 = Haiku()
    models, _ = _models( session, embed, c0=c0 )
    _twin_stage( loaded, ids[ :5 ], models )
    assert len( c0.calls ) == 10, "one call per twin per ask, with no retry"
    assert { model for model, _ in c0.calls } == { opus_twins.opus_model() } != { "haiku-x" }, "a twin called a model other than Opus"


def test_the_twin_stage_follows_the_first_stage_and_stops_when_every_ask_is_recorded( loaded ):
    session, asks, ids, embed, work, _ = loaded
    _first_stage_counted( loaded, chunk=10, ids=ids[ :10 ] )
    models, _ = _models( session, embed )
    sleeps = []
    def sleeper( seconds ):
        sleeps.append( seconds )
        _first_stage_counted( loaded, chunk=15, ids=ids[ :25 ] )
    lines = []
    assert _twin_stage( loaded, ids[ :25 ], models, follow=True, poll_seconds=7, sleep=sleeper, chunk=10, lines=lines ) == 25
    assert sleeps == [ 7 ] and len( ar.read_jsonl( work.twins ) ) == 25
    assert [ line.split( " asks run" )[ 0 ] for line in lines ] == [ "[twin checkpoint] 10", "[twin checkpoint] 20" ]


def test_a_twin_failure_leaves_an_abstention_with_its_reason( loaded ):
    session, asks, ids, embed, work, _ = loaded
    _first_stage_counted( loaded, chunk=5, ids=ids[ :5 ] )
    victim = next( a for a in asks if a[ "id" ] == ids[ 2 ] )
    models, _ = _models( session, embed, c0=Haiku( fail_for=victim[ "message" ] ) )
    _twin_stage( loaded, ids[ :5 ], models )
    line = next( t for t in ar.read_jsonl( work.twins ) if t[ "id" ] == victim[ "id" ] )
    for arm in ar.TWIN_ARMS:
        assert line[ "arms" ][ arm ] == { "correct": False, "forecast": None, "reason": "model_error: Failed" }


def test_a_missing_row_reads_as_no_forecast_and_the_reader_hands_the_harness_the_stored_forecast( loaded ):
    session, asks, ids, embed, work, _ = loaded
    models, _ = _models( session, embed )
    models.run( ids[ 0 ], ar.HAIKU_ARMS )
    stored = models.rows[ ( ids[ 0 ], ar.ARM_BASELINE ) ]
    assert models.reader( ar.ARM_BASELINE )( { "id": ids[ 0 ] }, [], episode_view=None, principles=None ) == stored[ 0 ] and stored[ 0 ] is not None

    async def silent( arm, ask_id ): return { "status": "not_run", "reason": "stand-in" }
    models._job = lambda arm, ask_id: silent( arm, ask_id )
    counts = models.run( ids[ 1 ], ar.HAIKU_ARMS )
    assert models.rows[ ( ids[ 1 ], ar.ARM_PRINCIPLES ) ] == ( None, "no_row" ) and counts[ ( ar.ARM_PRINCIPLES, "not_run", "stand-in" ) ] == 1


def test_the_default_models_come_from_the_ini_settings_with_the_ledger_in_the_work_folder( loaded, monkeypatch ):
    session, asks, ids, embed, work, _ = loaded
    seen = {}
    monkeypatch.setattr( ar.context_baseline, "open_ledger", lambda base_path=None, cli_path=None: seen.setdefault( "ledger", base_path ) and { } )
    models = ar.default_models( session, embed, "enc", "ext", work )
    assert seen[ "ledger" ] == work.ledger
    assert models.c0.model == ar.context_baseline.context_model() and models.c0.timeout_seconds == ar.context_baseline.context_timeout()
    assert set( models.gates ) == set( ar.HAIKU_ARMS ) | set( ar.TWIN_ARMS ) and (models.encoder, models.extractor) == ( "enc", "ext" )


def _line( ask_id, engine=False, fixed=False, baseline=False, principles=False, family="f", forecast=True ):
    """Make one first-stage line from the four correct flags, with None for an abstention."""
    arm = lambda correct: { "correct": correct, "forecast": { "value": "yes" } if forecast else None, "reason": None }
    return { "id": ask_id, "response_type": "yes_no", "family": family,
             "arms": { ENGINE_ARM: arm( engine ), ar.ARM_FIXED: arm( fixed ), ar.ARM_BASELINE: arm( baseline ), ar.ARM_PRINCIPLES: arm( principles ) } }


def _twin( ask_id, baseline_opus, principles_opus, forecast=True ):
    """Make one twin-stage line."""
    arm = lambda correct: { "correct": correct, "forecast": { "value": "yes" } if forecast else None, "reason": None }
    return { "id": ask_id, "arms": { ar.TWIN_ARMS[ 0 ]: arm( baseline_opus ), ar.TWIN_ARMS[ 1 ]: arm( principles_opus ) } }


STATE = { "not_replayable": 0, "unrebuildable": 3, "context_asks": 7, "done_ids": [], "extracted_ids": [] }


def _pairing( report, arm, baseline ):
    """Find one pairing in a report by its labels."""
    return next( p for p in report[ "pairings" ] if ( p[ "arm" ], p[ "baseline" ] ) == ( ar.LABELS.get( arm, arm ), ar.LABELS.get( baseline, baseline ) ) )


def test_the_report_pairs_each_arm_with_its_named_comparator_and_counts_discordant_pairs_both_ways():
    records = [ _line( f"a{i}", principles=True, baseline=False ) for i in range( 12 ) ] + [ _line( f"b{i}", principles=False, baseline=True ) for i in range( 2 ) ] + \
              [ _line( f"c{i}", principles=True, baseline=True ) for i in range( 3 ) ]
    report  = ar.build_report( records, [], STATE )
    first   = _pairing( report, ar.ARM_PRINCIPLES, ar.ARM_BASELINE )[ "summary" ]
    assert ( first[ "asks_replayed" ], first[ "engine_only_right" ], first[ "baseline_only_right" ], first[ "floor_met" ], first[ "verdict" ] ) == ( 17, 12, 2, True, "engine better" )
    assert first[ "arm" ] == ar.ARM_PRINCIPLES and first[ "baseline" ] == ar.ARM_BASELINE and first[ "operational_floor" ] == 10
    engine_pair = _pairing( report, ar.ARM_PRINCIPLES, ENGINE_ARM )[ "summary" ]
    assert ( engine_pair[ "engine_only_right" ], engine_pair[ "baseline_only_right" ], engine_pair[ "verdict" ] ) == ( 15, 0, "engine better" )
    assert _pairing( report, ar.ARM_BASELINE, ENGINE_ARM )[ "summary" ][ "engine_only_right" ] == 5
    assert report[ "asks" ] == 17 and report[ "context_asks" ] == 7 and report[ "unrebuildable_cases_chunk_sum" ] == 3


def test_a_pairing_below_the_floor_is_not_decisive_whatever_the_counts():
    records = [ _line( f"a{i}", principles=True, baseline=False ) for i in range( 9 ) ]
    summary = _pairing( ar.build_report( records, [], STATE ), ar.ARM_PRINCIPLES, ar.ARM_BASELINE )[ "summary" ]
    assert ( summary[ "engine_only_right" ], summary[ "floor_met" ], summary[ "verdict" ] ) == ( 9, False, "not decisive" )


def test_the_report_gives_coverage_and_accuracy_on_the_asks_answered_beside_each_verdict():
    answered  = [ _line( f"a{i}", principles=( i < 2 ) ) for i in range( 4 ) ]
    silent    = [ _line( f"s{i}", principles=False, forecast=False ) for i in range( 4 ) ]
    pairing   = _pairing( ar.build_report( answered + silent, [], STATE ), ar.ARM_PRINCIPLES, ar.ARM_BASELINE )
    assert pairing[ "arm_coverage" ] == { "asks": 8, "answered": 4, "coverage": 0.5, "correct": 2, "accuracy_on_answered": 0.5 }


def test_an_abstention_is_charged_as_a_miss_in_the_verdict_and_left_out_of_accuracy_on_answered():
    records = [ _line( "a", principles=True ), _line( "b", principles=False, forecast=False ) ]
    records[ 1 ][ "arms" ][ ar.ARM_BASELINE ][ "forecast" ] = { "value": "yes" }
    pairing = _pairing( ar.build_report( records, [], STATE ), ar.ARM_PRINCIPLES, ar.ARM_BASELINE )
    assert pairing[ "arm_coverage" ] == { "asks": 2, "answered": 1, "coverage": 0.5, "correct": 1, "accuracy_on_answered": 1.0 }
    assert pairing[ "baseline_coverage" ][ "coverage" ] == 1.0 and pairing[ "summary" ][ "baseline_correct" ] == 0


def test_an_arm_that_answered_nothing_has_no_accuracy_rather_than_a_zero():
    records = [ _line( "a", forecast=False ) ]
    assert _pairing( ar.build_report( records, [], STATE ), ar.ARM_PRINCIPLES, ar.ARM_BASELINE )[ "arm_coverage" ][ "accuracy_on_answered" ] is None


def test_an_opus_pairing_covers_only_the_asks_both_twins_ran_and_cuts_its_haiku_twin_to_the_same_asks():
    records = [ _line( f"a{i}", baseline=False, principles=False ) for i in range( 3 ) ] + [ _line( f"b{i}", baseline=True, principles=True ) for i in range( 3 ) ]
    twins   = [ _twin( f"a{i}", baseline_opus=True, principles_opus=True ) for i in range( 3 ) ]
    report  = ar.build_report( records, twins, STATE )
    opus    = _pairing( report, ar.TWIN_ARMS[ 0 ], ar.ARM_BASELINE )[ "summary" ]
    assert ( opus[ "asks_replayed" ], opus[ "engine_correct" ], opus[ "baseline_correct" ] ) == ( 3, 3, 0 ), "the Haiku twin must be read on the twins' asks only"
    assert report[ "twin_stretch" ] == 3 and _pairing( report, ar.ARM_PRINCIPLES, ar.ARM_BASELINE )[ "summary" ][ "asks_replayed" ] == 6


def test_an_opus_pairing_with_no_twin_lines_is_reported_as_not_run_with_no_verdict():
    report = ar.build_report( [ _line( "a" ) ], [], STATE )
    for arm, baseline in ( ( ar.TWIN_ARMS[ 0 ], ar.ARM_BASELINE ), ( ar.TWIN_ARMS[ 1 ], ar.ARM_PRINCIPLES ) ):
        pairing = _pairing( report, arm, baseline )
        assert pairing[ "status" ].startswith( "not run, blocked by" ) and "summary" not in pairing


def test_the_report_renders_one_row_per_pairing_with_dashes_for_what_was_not_measured():
    records = [ _line( f"a{i}", principles=True ) for i in range( 3 ) ]
    text    = ar.render_report( ar.build_report( records, [], STATE ) )
    rows    = [ line for line in text.splitlines() if line.startswith( "| " ) and not line.startswith( "| arm" ) ]
    assert len( rows ) == len( ar.PAIRINGS ) and sum( 1 for r in rows if "not run, blocked by" in r ) == 2
    assert "| B1 | C0 | 3 |" in text and "| C0-opus | C0 | not run" in text
    assert ar._pct( None ) == "-" and ar._pct( 0.5 ) == "50.0%"
    assert text.startswith( "Evaluation asks: 3; discordant-pair floor 10; asks with an episode history 7; twin stretch 0 asks." )
    empty = ar.build_report( [], [], STATE )
    assert all( "summary" not in p for p in empty[ "pairings" ] )
    assert ar._coverage( [], ar.ARM_BASELINE ) == { "asks": 0, "answered": 0, "coverage": None, "correct": 0, "accuracy_on_answered": None }


def test_main_runs_each_stage_from_the_command_line_and_the_report_stage_writes_its_file( tmp_path, archive, capsys ):
    asks_path, non_path, fixture_path, fixture = archive
    work   = ar.WorkFolder( str( tmp_path ) )
    models_made = []
    def make_models( session, embed ):
        models, _ = _models( session, embed )
        models_made.append( models )
        return models
    base = [ "--work", str( tmp_path ), "--asks", asks_path, "--non-asks", non_path, "--fixture", fixture_path, "--chunk", "50" ]
    embed = _open_embedder( tmp_path )
    lines = []
    PredictionEngine.reset()
    assert ar.main( [ "first" ] + base, query_fn=er.canned_model, embed=embed, make_models=make_models, out=lines.append ) == 0
    records = ar.read_jsonl( work.records )
    assert len( records ) > 100 and not {r[ "id" ] for r in records} & fixture and os.path.exists( work.cache )
    assert ar.main( [ "twins", "--poll-seconds", "1" ] + base, embed=embed, make_models=make_models, out=lines.append ) == 0
    assert len( ar.read_jsonl( work.twins ) ) == len( records )
    out_lines = []
    assert ar.main( [ "report", "--work", str( tmp_path ) ], out=out_lines.append ) == 0
    report = json.load( open( work.report ) )
    assert report[ "asks" ] == len( records ) and report[ "twin_stretch" ] == len( records ) and len( report[ "pairings" ] ) == 6
    assert out_lines[ 0 ].startswith( f"Evaluation asks: {len( records )};" )
    PredictionEngine.reset()


def test_the_limit_option_cuts_the_evaluation_to_the_first_asks( tmp_path, archive ):
    asks_path, non_path, fixture_path, _ = archive
    embed = _open_embedder( tmp_path )
    PredictionEngine.reset()
    argv = [ "first", "--work", str( tmp_path ), "--asks", asks_path, "--non-asks", non_path, "--fixture", fixture_path, "--chunk", "4", "--limit", "6" ]
    assert ar.main( argv, query_fn=er.canned_model, embed=embed, make_models=lambda session, e: _models( session, e )[ 0 ], out=lambda line: None ) == 0
    assert len( ar.read_jsonl( ar.WorkFolder( str( tmp_path ) ).records ) ) == 6
    PredictionEngine.reset()


def test_a_row_without_a_priority_loads_with_the_stand_in_and_a_row_with_one_keeps_it( tmp_path ):
    base = { "id": "00000000-0000-4000-8000-0000000000a1", "recipient_id": "00000000-0000-4000-8000-0000000000ab", "message": "m", "sender_id": "s", "type": "task",
             "created_at": "2026-11-05T14:00:00+00:00", "response_requested": True, "direction": "ai_to_human", "title": "t" }
    kept = { **base, "id": "00000000-0000-4000-8000-0000000000a2", "priority": "high" }
    ( tmp_path / "a.jsonl" ).write_text( json.dumps( base ) + "\n" + json.dumps( kept ) + "\n" )
    ( tmp_path / "n.jsonl" ).write_text( "" )
    with scratch_session() as session:
        assert ar.load_archive( session, str( tmp_path / "a.jsonl" ), str( tmp_path / "n.jsonl" ) ) == 2
        assert { str( n.id )[ -2: ]: n.priority for n in session.query( Notification ) } == { "a1": ar.STAND_IN_PRIORITY, "a2": "high" }


def test_the_periodic_embedder_writes_its_file_every_n_service_calls_and_never_for_a_cache_hit( tmp_path ):
    inner  = CachedServiceEmbedder( str( tmp_path / "e.json" ), embed=er.stand_in_vector, encoder="x" )
    flushes = []
    real_flush = inner.flush
    inner.flush = lambda: ( flushes.append( inner.calls ), real_flush() )
    wrapped = ar.PeriodicFlush( inner, every=2 )
    assert wrapped.encoder == "x"
    wrapped( "one" )
    assert flushes == []
    wrapped( "two" )
    assert flushes == [ 2 ]
    wrapped( "two" )
    wrapped( "three" )
    assert flushes == [ 2 ], "a cache hit or a single new call must not write"
    wrapped( "four" )
    assert flushes == [ 2, 4 ]
    wrapped.flush()
    assert flushes == [ 2, 4, 4 ] and len( json.load( open( tmp_path / "e.json" ) ) ) >= 5


def test_main_without_an_injected_embedder_builds_the_periodic_one_over_the_cached_service_embedder( tmp_path, archive, monkeypatch ):
    asks_path, non_path, fixture_path, _ = archive
    made = []
    def fake_cached( path ):
        inner = CachedServiceEmbedder( path, embed=er.stand_in_vector, encoder="test-encoder:v1" )
        made.append( inner )
        return inner
    monkeypatch.setattr( ar, "CachedServiceEmbedder", fake_cached )
    PredictionEngine.reset()
    argv = [ "first", "--work", str( tmp_path ), "--asks", asks_path, "--non-asks", non_path, "--fixture", fixture_path, "--chunk", "3", "--limit", "3" ]
    assert ar.main( argv, query_fn=er.canned_model, make_models=lambda session, e: _models( session, e )[ 0 ], out=lambda line: None ) == 0
    assert len( made ) == 1 and os.path.exists( ar.WorkFolder( str( tmp_path ) ).cache ) and len( made[ 0 ].vectors ) > 100
    PredictionEngine.reset()
