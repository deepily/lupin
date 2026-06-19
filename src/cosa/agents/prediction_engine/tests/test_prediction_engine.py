"""
Unit tests for prediction_engine/prediction_engine.py ( the PredictionEngine singleton ).

Coverage target: 100% lines + branches + functions on production logic.
quick_smoke_test() + __main__ guard are excluded by pyproject.toml
[tool.coverage.report].exclude_also.

COST SAFETY: every external boundary is mocked — embedding provider, LanceDB
store ( ProxyDecisionEmbeddings ), LLM client ( LlmClientFactory ), DB session
( get_db / PredictionLogRepository ), requests.post, and the cu.* file/key
helpers. NO real model load, NO network, NO DB, NO API key read → ZERO API spend.

Singleton state is reset before AND after every test ( autouse fixture ).
Instance-attribute overrides ( eng._foo = lambda ... ) shadow bound methods for
a single instance — used to inject seams without importing heavy collaborators.
"""
import json
from unittest.mock import patch, MagicMock

import pytest

import cosa.agents.prediction_engine.prediction_engine as pe_mod
from cosa.agents.prediction_engine.prediction_engine import (
    PredictionEngine,
    get_prediction_engine,
)
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.agents.prediction_engine.config import (
    STRATEGY_COLD_START,
    STRATEGY_CBR_MAJORITY,
    STRATEGY_CBR_RETRIEVAL,
    STRATEGY_LLM_SYNTHESIS,
    RESPONSE_TYPE_YES_NO,
    RESPONSE_TYPE_MULTIPLE_CHOICE,
    RESPONSE_TYPE_OPEN_ENDED,
    RESPONSE_TYPE_OPEN_ENDED_BATCH,
)


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture( autouse=True )
def _reset_singleton():
    PredictionEngine.reset()
    yield
    PredictionEngine.reset()


def _engine( debug=False ):
    """Fresh default-config engine ( singleton already reset by fixture )."""
    return PredictionEngine( debug=debug )


def _store( cases=None, raises=False ):
    """A mock embedding store whose find_similar yields (sim_pct, record) tuples."""
    store = MagicMock()
    if raises:
        store.find_similar.side_effect = RuntimeError( "find_similar boom" )
    else:
        store.find_similar.return_value = [] if cases is None else cases
    return store


class _FakeConfigMgr:
    """Minimal ConfigurationManager stand-in honouring return_type coercion."""

    def __init__( self, debug_enabled=False ):
        self._debug = debug_enabled

    def get( self, key, default=None, return_type=None ):
        if key == "prediction engine debug":
            return self._debug
        if return_type == "boolean":
            return str( default ).lower() in ( "true", "1", "yes" )
        if return_type == "int":
            return int( default )
        if return_type == "float":
            return float( default )
        return default


# =========================================================================== #
# __new__ / __init__ / singleton
# =========================================================================== #
def test_singleton_identity_and_reinit_short_circuit():
    e1 = PredictionEngine( debug=True )
    e2 = PredictionEngine( debug=True )       # __new__ returns cached, __init__ hits `if self._initialized: return`
    assert e1 is e2


def test_new_double_checked_lock_inner_false_arc():
    # Cover the defensive double-checked-locking inner arc ( 74->77 ): simulate a race where
    # another thread sets _instance between the outer check and acquiring the lock. A fake lock
    # whose __enter__ populates _instance makes the inner `if cls._instance is None` False.
    PredictionEngine.reset()
    sentinel = object()

    class _RaceLock:
        def __enter__( self ):
            PredictionEngine._instance = sentinel     # simulate concurrent creation
            return self
        def __exit__( self, *a ):
            return False

    with patch.object( PredictionEngine, "_lock", _RaceLock() ):
        result = PredictionEngine.__new__( PredictionEngine )
    assert result is sentinel
    PredictionEngine.reset()


def test_init_defaults_branch():
    eng = _engine()
    assert eng.enabled is True
    assert eng.cbr_top_k == 5
    assert eng.lancedb_table == "prediction_decisions"
    assert eng._llm_client is None
    assert eng._embedding_store is None


def test_init_with_config_mgr_debug_enabled():
    cfg = _FakeConfigMgr( debug_enabled=True )
    eng = PredictionEngine( config_mgr=cfg, debug=False )
    # config path taken; debug True ( from config ) → also exercises the debug print at __init__ end
    assert eng.debug is True
    assert eng.enabled is True
    assert eng.cbr_top_k == 5
    assert isinstance( eng.similarity_threshold, float )


def test_init_with_config_mgr_debug_false():
    cfg = _FakeConfigMgr( debug_enabled=False )
    eng = PredictionEngine( config_mgr=cfg )
    assert eng.debug is False


def test_reset_clears_instance():
    e1 = PredictionEngine()
    PredictionEngine.reset()
    e2 = PredictionEngine()
    assert e1 is not e2


def test_get_prediction_engine_returns_singleton():
    e1 = get_prediction_engine()
    e2 = get_prediction_engine()
    assert e1 is e2 is PredictionEngine()


def test_register_invalidator_registered_reset():
    # the module-level register_invalidator wired PredictionEngine.reset under "prediction_engine"
    from cosa.config.cache_registry import _registered_names
    assert "prediction_engine" in _registered_names()


# =========================================================================== #
# _get_embedding_provider / _get_embedding_store / _get_llm_client ( lazy loaders )
# =========================================================================== #
def test_get_embedding_provider_success_and_cache():
    eng = _engine()
    sentinel = object()
    with patch( "cosa.memory.embedding_provider.get_embedding_provider", return_value=sentinel ) as gp:
        assert eng._get_embedding_provider() is sentinel
        # cached: second call does not re-import / re-create
        assert eng._get_embedding_provider() is sentinel
    assert gp.call_count == 1


def test_get_embedding_provider_failure_returns_none():
    eng = _engine( debug=True )
    with patch( "cosa.memory.embedding_provider.get_embedding_provider", side_effect=RuntimeError( "no gpu" ) ):
        assert eng._get_embedding_provider() is None


def test_get_embedding_store_success_and_cache():
    eng = _engine()
    fake_store = object()
    with patch( "cosa.agents.decision_proxy.proxy_decision_embeddings.ProxyDecisionEmbeddings", return_value=fake_store ) as P, \
         patch( "cosa.utils.util.get_project_root", return_value="/tmp/root" ):
        assert eng._get_embedding_store() is fake_store
        assert eng._get_embedding_store() is fake_store
    assert P.call_count == 1


def test_get_embedding_store_failure_returns_none():
    eng = _engine( debug=True )
    with patch( "cosa.agents.decision_proxy.proxy_decision_embeddings.ProxyDecisionEmbeddings", side_effect=RuntimeError( "lancedb down" ) ), \
         patch( "cosa.utils.util.get_project_root", return_value="/tmp/root" ):
        assert eng._get_embedding_store() is None


# ---- prod bug #11 FIXED (Tiberius) — _get_llm_client wrong-import ------------------------ #
# prediction_engine.py:990 imported LlmClientFactory from cosa.agents.llm_client (no such symbol)
# instead of cosa.agents.llm_client_factory → ImportError swallowed by the bare except →
# _get_llm_client() always returned None → the LLM-synthesis tier of open-ended prediction was
# dead, silently falling back to CBR retrieval. Import corrected; 991-992 now reachable + covered
# by test_get_llm_client_CONTRACT below. The armed xfail-strict tripwire + buggy-behaviour PIN
# were de-armed/removed once the import was fixed.

def test_get_llm_client_CONTRACT_returns_client_when_factory_available():
    """
    CORRECT contract ( bug #11 fixed ): with a working LlmClientFactory available via its real
    module, _get_llm_client() returns the constructed client. Exercises the now-reachable 991-992.
    """
    eng = _engine()
    client = object()
    factory = MagicMock()
    factory.get_client.return_value = client
    with patch( "cosa.agents.llm_client_factory.LlmClientFactory", return_value=factory ):
        assert eng._get_llm_client() is client


def test_get_llm_client_factory_failure_hits_except_branch():
    # factory construction raises → except branch ( debug print ) → returns None.
    # Covers 990-991 ( import ok, factory() raises ), 993-994 ( except ).
    eng = _engine( debug=True )
    with patch( "cosa.agents.llm_client_factory.LlmClientFactory", side_effect=RuntimeError( "factory boom" ) ):
        assert eng._get_llm_client() is None


def test_get_llm_client_cache_hit_skips_load():
    # cache-hit branch ( self._llm_client already set ) returns the cached client without the
    # buggy load path. Legitimate: the cache branch is correct code independent of the bug.
    eng = _engine()
    sentinel = object()
    eng._llm_client = sentinel
    assert eng._get_llm_client() is sentinel


# =========================================================================== #
# predict() — dispatch + guards
# =========================================================================== #
def test_predict_disabled_returns_cold_start():
    eng = _engine()
    eng.enabled = False
    result = eng.predict( { "message": "Should I proceed?", "response_type": "yes_no" } )
    assert result.strategy == STRATEGY_COLD_START
    assert result.metadata[ "reason" ] == "engine_disabled"


@pytest.mark.parametrize( "rtype", [
    RESPONSE_TYPE_YES_NO, RESPONSE_TYPE_MULTIPLE_CHOICE,
    RESPONSE_TYPE_OPEN_ENDED, RESPONSE_TYPE_OPEN_ENDED_BATCH,
] )
def test_predict_dispatches_each_type_to_cold_start_when_no_cases( rtype ):
    eng = _engine( debug=True )
    eng._generate_embedding = lambda text: [ 0.1, 0.2 ]
    eng._get_embedding_store = lambda: _store( cases=[] )
    result = eng.predict( { "message": "x", "response_type": rtype, "sender_id": "s" } )
    assert result.response_type == rtype
    assert result.strategy == STRATEGY_COLD_START


def test_predict_unknown_type_returns_cold_start():
    eng = _engine()
    eng._generate_embedding = lambda text: [ 0.1 ]
    result = eng.predict( { "message": "x", "response_type": "weird_type" } )
    assert result.strategy == STRATEGY_COLD_START
    assert result.metadata[ "reason" ] == "unsupported_type_weird_type"


def test_predict_swallows_dispatch_exception():
    eng = _engine( debug=True )
    eng._generate_embedding = lambda text: [ 0.1 ]
    def _boom( *a, **k ):
        raise RuntimeError( "kaboom" )
    eng._predict_yes_no = _boom
    result = eng.predict( { "message": "x", "response_type": "yes_no" } )
    assert result.strategy == STRATEGY_COLD_START
    assert result.metadata[ "reason" ] == "prediction_error"
    assert "kaboom" in result.metadata[ "error" ]


# =========================================================================== #
# _predict_yes_no
# =========================================================================== #
def test_yes_no_no_embedding():
    eng = _engine()
    r = eng._predict_yes_no( "msg", "permission", None )
    assert r.strategy == STRATEGY_COLD_START
    assert r.metadata[ "reason" ] == "no_embedding"


def test_yes_no_no_store():
    eng = _engine()
    eng._get_embedding_store = lambda: None
    r = eng._predict_yes_no( "msg", "permission", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_embedding_store"


def test_yes_no_find_similar_raises_then_cold_start():
    eng = _engine( debug=True )
    eng._get_embedding_store = lambda: _store( raises=True )
    r = eng._predict_yes_no( "msg", "permission", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_yes_no_no_similar_cases():
    eng = _engine()
    eng._get_embedding_store = lambda: _store( cases=[] )
    r = eng._predict_yes_no( "msg", "permission", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_yes_no_majority_vote_with_qualifier():
    eng = _engine( debug=True )
    cases = [
        ( 90.0, { "decision_value": "yes" } ),
        ( 80.0, { "decision_value": "yes [comment: keep the old ones]" } ),
        ( 70.0, { "decision_value": "no" } ),
    ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_yes_no( "msg", "permission", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_MAJORITY
    assert r.predicted_value == "yes"
    assert r.predicted_qualifier == "keep the old ones"
    assert r.metadata[ "votes" ] == { "yes": 2, "no": 1 }
    assert r.confidence == pytest.approx( 0.9 * ( 2 / 3 ) )
    assert r.metadata[ "qualifier_similarity" ] == pytest.approx( 0.8 )


def test_yes_no_majority_vote_no_qualifier():
    # winning-side cases have no qualifier → winning_qualifier stays None → metadata None
    eng = _engine()
    cases = [ ( 95.0, { "decision_value": "no" } ), ( 60.0, { "decision_value": "no" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_yes_no( "msg", "permission", [ 0.1 ] )
    assert r.predicted_value == "no"
    assert r.predicted_qualifier is None
    assert r.metadata[ "qualifier_similarity" ] is None


# =========================================================================== #
# _extract_valid_options ( staticmethod )
# =========================================================================== #
def test_extract_valid_options_none():
    assert PredictionEngine._extract_valid_options( None ) is None


def test_extract_valid_options_dict_full():
    opts = { "questions": [ {
        "header": "DB", "multi_select": False,
        "options": [ { "label": "PG" }, { "label": "MySQL" }, { "nope": 1 } ],
    } ] }
    result = PredictionEngine._extract_valid_options( opts )
    assert result == { "DB": { "labels": { "PG", "MySQL" }, "multi_select": False } }


def test_extract_valid_options_json_string():
    opts = json.dumps( { "questions": [ { "header": "H", "options": [ { "label": "A" } ] } ] } )
    result = PredictionEngine._extract_valid_options( opts )
    assert result == { "H": { "labels": { "A" }, "multi_select": False } }


def test_extract_valid_options_camelcase_multiselect_and_question_fallback():
    opts = { "questions": [ {
        "question": "Pick features", "multiSelect": True,
        "options": [ { "label": "A" }, { "label": "B" } ],
    } ] }
    result = PredictionEngine._extract_valid_options( opts )
    assert result[ "Pick features" ][ "multi_select" ] is True


def test_extract_valid_options_invalid_json_string_returns_none():
    assert PredictionEngine._extract_valid_options( "not json {" ) is None


def test_extract_valid_options_parsed_non_dict_returns_none():
    assert PredictionEngine._extract_valid_options( "[1, 2, 3]" ) is None


def test_extract_valid_options_no_questions_returns_none():
    assert PredictionEngine._extract_valid_options( { "foo": "bar" } ) is None


def test_extract_valid_options_non_dict_non_str_returns_none():
    assert PredictionEngine._extract_valid_options( 12345 ) is None


def test_extract_valid_options_header_without_labels_skipped_returns_none():
    opts = { "questions": [ { "header": "H", "options": [] } ] }
    assert PredictionEngine._extract_valid_options( opts ) is None


def test_extract_valid_options_typeerror_in_options_returns_none():
    # opt_list is a non-iterable int → `for opt in 123` raises TypeError → except → None
    opts = { "questions": [ { "header": "H", "options": 123 } ] }
    assert PredictionEngine._extract_valid_options( opts ) is None


# =========================================================================== #
# _predict_multiple_choice
# =========================================================================== #
def test_mc_no_embedding():
    eng = _engine()
    r = eng._predict_multiple_choice( "m", "approach", None )
    assert r.metadata[ "reason" ] == "no_embedding"


def test_mc_no_store():
    eng = _engine()
    eng._get_embedding_store = lambda: None
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_embedding_store"


def test_mc_find_similar_raises_then_cold():
    eng = _engine( debug=True )
    eng._get_embedding_store = lambda: _store( raises=True )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_mc_no_similar_cases():
    eng = _engine()
    eng._get_embedding_store = lambda: _store( cases=[] )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_mc_single_select_majority_no_options():
    eng = _engine( debug=True )
    cases = [
        ( 90.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ),
        ( 80.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ),
        ( 70.0, { "decision_value": json.dumps( { "answers": { "DB": "MySQL" } } ) } ),
    ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_MAJORITY
    assert r.predicted_value == { "answers": { "DB": "PG" } }
    assert r.metadata[ "multi_select" ] is False


def test_mc_parse_none_continue_then_valid():
    eng = _engine()
    cases = [
        ( 90.0, { "decision_value": "not json at all" } ),       # parsed None → continue
        ( 80.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ),
    ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.predicted_value == { "answers": { "DB": "PG" } }
    assert r.metadata[ "valid_cases" ] == 1


def test_mc_all_parse_none_cold_start():
    eng = _engine()
    cases = [ ( 90.0, { "decision_value": "garbage" } ), ( 80.0, { "decision_value": "" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_valid_mc_cases"


def test_mc_multi_select_data_detected():
    eng = _engine( debug=True )
    cases = [
        ( 90.0, { "decision_value": json.dumps( { "answers": { "Feat": [ "A", "B" ] } } ) } ),
        ( 80.0, { "decision_value": json.dumps( { "answers": { "Feat": [ "A" ] } } ) } ),
    ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.metadata[ "multi_select" ] is True
    # A in 2/2 → selected; B in 1/2 == 50% threshold → selected
    assert sorted( r.predicted_value[ "answers" ][ "Feat" ] ) == [ "A", "B" ]


def test_mc_options_force_multi_select_overrides_data():
    eng = _engine()
    cases = [
        ( 90.0, { "decision_value": json.dumps( { "answers": { "Feat": "A" } } ) } ),
        ( 80.0, { "decision_value": json.dumps( { "answers": { "Feat": "A" } } ) } ),
    ]
    options = { "questions": [ { "header": "Feat", "multi_select": True,
                                 "options": [ { "label": "A" }, { "label": "B" } ] } ] }
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.metadata[ "multi_select" ] is True


def test_mc_single_validation_winner_valid_kept():
    eng = _engine()
    cases = [ ( 90.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ) ]
    options = { "questions": [ { "header": "DB", "multi_select": False,
                                 "options": [ { "label": "PG" }, { "label": "MySQL" } ] } ] }
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.predicted_value == { "answers": { "DB": "PG" } }
    assert r.metadata[ "constrained" ] is False


def test_mc_single_validation_winner_invalid_fallback_to_valid_voted():
    eng = _engine( debug=True )
    cases = [
        ( 90.0, { "decision_value": json.dumps( { "answers": { "DB": "Mongo" } } ) } ),
        ( 80.0, { "decision_value": json.dumps( { "answers": { "DB": "Mongo" } } ) } ),
        ( 70.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ),
    ]
    options = { "questions": [ { "header": "DB", "multi_select": False,
                                 "options": [ { "label": "PG" } ] } ] }   # Mongo invalid
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.predicted_value == { "answers": { "DB": "PG" } }
    assert r.metadata[ "constrained" ] is True


def test_mc_single_validation_no_valid_voted_cold_start():
    eng = _engine()
    cases = [ ( 90.0, { "decision_value": json.dumps( { "answers": { "DB": "Mongo" } } ) } ) ]
    options = { "questions": [ { "header": "DB", "multi_select": False,
                                 "options": [ { "label": "PG" } ] } ] }
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.metadata[ "reason" ] == "no_valid_options_after_filtering"


def test_mc_multi_validation_filters_invalid_labels():
    eng = _engine( debug=True )
    cases = [
        ( 90.0, { "decision_value": json.dumps( { "answers": { "Feat": [ "A", "B", "X" ] } } ) } ),
        ( 80.0, { "decision_value": json.dumps( { "answers": { "Feat": [ "A", "B", "X" ] } } ) } ),
    ]
    options = { "questions": [ { "header": "Feat", "multi_select": True,
                                 "options": [ { "label": "A" }, { "label": "B" } ] } ] }
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.predicted_value[ "answers" ][ "Feat" ] == [ "A", "B" ]
    assert r.metadata[ "constrained" ] is True


def test_mc_multi_validation_all_invalid_cold_start():
    eng = _engine()
    cases = [
        ( 90.0, { "decision_value": json.dumps( { "answers": { "Feat": [ "X", "Y" ] } } ) } ),
        ( 80.0, { "decision_value": json.dumps( { "answers": { "Feat": [ "X", "Y" ] } } ) } ),
    ]
    options = { "questions": [ { "header": "Feat", "multi_select": True,
                                 "options": [ { "label": "A" } ] } ] }
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.metadata[ "reason" ] == "no_valid_options_after_filtering"


def test_mc_validation_header_not_in_options_kept_as_is():
    eng = _engine()
    cases = [ ( 90.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ) ]
    # options define a DIFFERENT header → option_info None for "DB" → keep prediction
    options = { "questions": [ { "header": "Other", "multi_select": False,
                                 "options": [ { "label": "Z" } ] } ] }
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.predicted_value == { "answers": { "DB": "PG" } }


# =========================================================================== #
# _tally_multi_select_votes
# =========================================================================== #
def test_tally_threshold_and_fallback():
    eng = _engine()
    # valid_cases = 4 → threshold 2.0 ; A:3 ( >=2 selected ), B:1 ( <2 not selected )
    # second header all below threshold → fallback to highest ( C:1 )
    header_counts = { "H1": { "A": 3, "B": 1 }, "H2": { "C": 1 } }
    predicted, avg = eng._tally_multi_select_votes( header_counts, valid_cases=4 )
    assert predicted[ "H1" ] == [ "A" ]
    assert predicted[ "H2" ] == [ "C" ]
    assert 0.0 < avg <= 1.0


# =========================================================================== #
# _parse_mc_decision_value / _parse_batch_decision_value ( staticmethods )
# =========================================================================== #
@pytest.mark.parametrize( "val", [ "", "   " ] )
def test_parse_mc_empty_returns_none( val ):
    assert PredictionEngine._parse_mc_decision_value( val ) is None


def test_parse_mc_valid():
    assert PredictionEngine._parse_mc_decision_value( '{"answers":{"H":"x"}}' ) == { "answers": { "H": "x" } }


def test_parse_mc_dict_without_answers_returns_none():
    assert PredictionEngine._parse_mc_decision_value( '{"foo":1}' ) is None


def test_parse_mc_invalid_json_returns_none():
    assert PredictionEngine._parse_mc_decision_value( "nope" ) is None


@pytest.mark.parametrize( "val", [ "", "   " ] )
def test_parse_batch_empty_returns_input( val ):
    assert PredictionEngine._parse_batch_decision_value( val ) == val


def test_parse_batch_valid_dict():
    assert PredictionEngine._parse_batch_decision_value( '{"answers":{"H":"x"}}' ) == { "answers": { "H": "x" } }


def test_parse_batch_dict_without_answers_returns_raw():
    assert PredictionEngine._parse_batch_decision_value( '{"foo":1}' ) == '{"foo":1}'


def test_parse_batch_invalid_json_returns_raw():
    assert PredictionEngine._parse_batch_decision_value( "raw text" ) == "raw text"


# =========================================================================== #
# _build_synthesis_prompt
# =========================================================================== #
def test_build_synthesis_prompt_injects_template_and_cases():
    eng = _engine()
    template = ( "Example: {{PYDANTIC_XML_EXAMPLE}}\n"
                 "Q: {current_question}\nN: {case_count}\nCases:\n{formatted_cases}" )
    cases = [ ( 90.0, { "question": "old q", "decision_value": "old a" } ) ]
    with patch( "cosa.utils.util.get_file_as_string", return_value=template ), \
         patch( "cosa.utils.util.get_project_root", return_value="/root" ):
        prompt = eng._build_synthesis_prompt( "current q", cases )
    assert "Q: current q" in prompt
    assert "N: 1" in prompt
    assert "<case n=\"1\" similarity=\"0.9\">" in prompt
    assert "</stop>" in prompt           # xml example terminated with stop tag
    assert "old q" in prompt and "old a" in prompt


# =========================================================================== #
# _predict_open_ended
# =========================================================================== #
def test_oe_no_embedding():
    eng = _engine()
    r = eng._predict_open_ended( "m", "input", None )
    assert r.metadata[ "reason" ] == "no_embedding"


def test_oe_no_store():
    eng = _engine()
    eng._get_embedding_store = lambda: None
    r = eng._predict_open_ended( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_embedding_store"


def test_oe_find_similar_raises_then_cold():
    eng = _engine( debug=True )
    eng._get_embedding_store = lambda: _store( raises=True )
    r = eng._predict_open_ended( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_oe_no_similar():
    eng = _engine()
    eng._get_embedding_store = lambda: _store( cases=[] )
    r = eng._predict_open_ended( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_oe_tier1_exact_match():
    eng = _engine( debug=True )
    cases = [ ( 95.0, { "question": "What name?", "decision_value": "use snake_case" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_open_ended( "what name?", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_RETRIEVAL
    assert r.predicted_value == "use snake_case"
    assert r.metadata[ "tier" ] == "exact_match"


def test_oe_tier2_llm_synthesis_success():
    eng = _engine( debug=True )
    cases = [ ( 88.0, { "question": "different q", "decision_value": "ans" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    eng._build_synthesis_prompt = lambda message, sc: "PROMPT"
    client = MagicMock()
    client.run.return_value = (
        "<open_ended_synthesis_response>"
        "<predicted_answer>synthesized answer</predicted_answer>"
        "<reasoning>because</reasoning>"
        "<confidence>0.5</confidence>"
        "</open_ended_synthesis_response>"
    )
    eng._get_llm_client = lambda: client
    r = eng._predict_open_ended( "current q", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_LLM_SYNTHESIS
    assert r.predicted_value == "synthesized answer"
    # final confidence = min( max_sim 0.88, llm 0.5 ) = 0.5
    assert r.confidence == pytest.approx( 0.5 )


def test_oe_tier2_client_none_falls_back_to_retrieval():
    eng = _engine( debug=True )
    cases = [ ( 88.0, { "question": "different q", "decision_value": "fallback ans" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    eng._build_synthesis_prompt = lambda message, sc: "PROMPT"
    eng._get_llm_client = lambda: None          # → RuntimeError → except → fallback
    r = eng._predict_open_ended( "current q", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_RETRIEVAL
    assert r.predicted_value == "fallback ans"
    assert r.metadata[ "tier" ] == "llm_fallback"


def test_oe_tier2_llm_run_raises_falls_back():
    eng = _engine()
    cases = [ ( 88.0, { "question": "different q", "decision_value": "fb" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    eng._build_synthesis_prompt = lambda message, sc: "PROMPT"
    client = MagicMock()
    client.run.side_effect = RuntimeError( "llm down" )
    eng._get_llm_client = lambda: client
    r = eng._predict_open_ended( "current q", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_RETRIEVAL
    assert r.metadata[ "tier" ] == "llm_fallback"
    assert "llm down" in r.metadata[ "llm_error" ]


# =========================================================================== #
# _predict_open_ended_batch
# =========================================================================== #
def test_oeb_no_embedding():
    eng = _engine()
    r = eng._predict_open_ended_batch( "m", "input", None )
    assert r.metadata[ "reason" ] == "no_embedding"


def test_oeb_no_store():
    eng = _engine()
    eng._get_embedding_store = lambda: None
    r = eng._predict_open_ended_batch( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_embedding_store"


def test_oeb_find_similar_raises_then_cold():
    eng = _engine( debug=True )
    eng._get_embedding_store = lambda: _store( raises=True )
    r = eng._predict_open_ended_batch( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_oeb_no_similar():
    eng = _engine()
    eng._get_embedding_store = lambda: _store( cases=[] )
    r = eng._predict_open_ended_batch( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_oeb_tier1_exact_match_json_parsed():
    eng = _engine( debug=True )
    dv = json.dumps( { "answers": { "Topic": "quantum" } } )
    cases = [ ( 95.0, { "question": "details?", "decision_value": dv } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_open_ended_batch( "details?", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_RETRIEVAL
    assert r.predicted_value == { "answers": { "Topic": "quantum" } }
    assert r.metadata[ "tier" ] == "exact_match"


def test_oeb_tier2_llm_synthesis_success():
    eng = _engine( debug=True )
    cases = [ ( 88.0, { "question": "diff", "decision_value": "x" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    eng._build_synthesis_prompt = lambda message, sc: "PROMPT"
    client = MagicMock()
    client.run.return_value = (
        "<open_ended_synthesis_response>"
        "<predicted_answer>{\"answers\": {\"Topic\": \"AI\"}}</predicted_answer>"
        "<reasoning>r</reasoning><confidence>0.9</confidence>"
        "</open_ended_synthesis_response>"
    )
    eng._get_llm_client = lambda: client
    r = eng._predict_open_ended_batch( "current", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_LLM_SYNTHESIS
    assert r.predicted_value == { "answers": { "Topic": "AI" } }


def test_oeb_tier2_client_none_fallback():
    eng = _engine()
    dv = json.dumps( { "answers": { "T": "v" } } )
    cases = [ ( 88.0, { "question": "diff", "decision_value": dv } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    eng._build_synthesis_prompt = lambda message, sc: "PROMPT"
    eng._get_llm_client = lambda: None
    r = eng._predict_open_ended_batch( "current", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_RETRIEVAL
    assert r.predicted_value == { "answers": { "T": "v" } }
    assert r.metadata[ "tier" ] == "llm_fallback"


def test_oeb_tier2_llm_raises_fallback():
    eng = _engine( debug=True )
    cases = [ ( 88.0, { "question": "diff", "decision_value": "plain" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    eng._build_synthesis_prompt = lambda message, sc: "PROMPT"
    client = MagicMock()
    client.run.side_effect = RuntimeError( "boom" )
    eng._get_llm_client = lambda: client
    r = eng._predict_open_ended_batch( "current", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_RETRIEVAL
    assert r.metadata[ "tier" ] == "llm_fallback"


# =========================================================================== #
# _get_llm_client / _cosine_similarity
# =========================================================================== #
def test_cosine_similarity_of_unit_vectors():
    eng = _engine()
    assert eng._cosine_similarity( [ 1.0, 0.0 ], [ 1.0, 0.0 ] ) == pytest.approx( 1.0 )
    assert eng._cosine_similarity( [ 1.0, 0.0 ], [ 0.0, 1.0 ] ) == pytest.approx( 0.0 )


# =========================================================================== #
# _enrich_with_embedding_similarity
# =========================================================================== #
def test_enrich_predicted_none_returns_early():
    eng = _engine()
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s", predicted_value=None )
    actual = { "value": "x" }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED )
    assert "_embedding_similarity" not in actual


def test_enrich_open_ended_injects_similarity():
    eng = _engine()
    eng._generate_embedding = lambda text: [ 1.0, 0.0 ]
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s", predicted_value="hello" )
    actual = { "value": "world" }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED )
    assert actual[ "_embedding_similarity" ] == pytest.approx( 1.0 )


def test_enrich_open_ended_non_str_predicted_value_coerced():
    eng = _engine()
    eng._generate_embedding = lambda text: [ 1.0, 0.0 ]
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s", predicted_value=12345 )
    actual = { "value": "world" }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED )
    assert "_embedding_similarity" in actual


def test_enrich_open_ended_empty_text_returns_early():
    eng = _engine()
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s", predicted_value="hello" )
    actual = { "value": "" }      # actual_text empty → early return, no injection
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED )
    assert "_embedding_similarity" not in actual


def test_enrich_open_ended_embedding_none_skips():
    eng = _engine()
    eng._generate_embedding = lambda text: None
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s", predicted_value="hello" )
    actual = { "value": "world" }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED )
    assert "_embedding_similarity" not in actual


def test_enrich_batch_injects_per_header():
    eng = _engine()
    eng._generate_embedding = lambda text: [ 1.0, 0.0 ]
    pr = PredictionResult( response_type="open_ended_batch", category="c", strategy="s",
                           predicted_value={ "answers": { "Topic": "ai" } } )
    actual = { "answers": { "Topic": "ml" } }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED_BATCH )
    assert actual[ "_embedding_similarity" ] == { "Topic": pytest.approx( 1.0 ) }


def test_enrich_batch_non_dict_predicted_returns_early():
    eng = _engine()
    pr = PredictionResult( response_type="open_ended_batch", category="c", strategy="s",
                           predicted_value="not a dict" )
    actual = { "answers": { "Topic": "ml" } }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED_BATCH )
    assert "_embedding_similarity" not in actual


def test_enrich_batch_empty_actual_answers_returns_early():
    eng = _engine()
    pr = PredictionResult( response_type="open_ended_batch", category="c", strategy="s",
                           predicted_value={ "answers": { "Topic": "ai" } } )
    actual = { "answers": {} }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED_BATCH )
    assert "_embedding_similarity" not in actual


def test_enrich_batch_empty_header_text_continues():
    eng = _engine()
    eng._generate_embedding = lambda text: [ 1.0, 0.0 ]
    pr = PredictionResult( response_type="open_ended_batch", category="c", strategy="s",
                           predicted_value={ "answers": { "Topic": "ai" } } )
    # actual header "Topic" has empty text → continue (skip) → header_sims empty → no injection
    actual = { "answers": { "Topic": "" } }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED_BATCH )
    assert "_embedding_similarity" not in actual


def test_enrich_swallows_exception():
    eng = _engine( debug=True )
    def _raise( text ):
        raise RuntimeError( "embed boom" )
    eng._generate_embedding = _raise
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s", predicted_value="hello" )
    actual = { "value": "world" }
    # exception inside try → caught → no propagation, no injection
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED )
    assert "_embedding_similarity" not in actual


# =========================================================================== #
# record_outcome
# =========================================================================== #
def _patch_db():
    """Context-manager patches for get_db + PredictionLogRepository. Returns (patchers)."""
    gdb = patch( "cosa.rest.db.database.get_db" )
    repo = patch( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository" )
    return gdb, repo


def test_record_outcome_str_actual_value():
    eng = _engine( debug=True )
    eng._store_decision = lambda *a, **k: None
    pr = PredictionResult( response_type="yes_no", category="permission", strategy="cbr_majority_vote",
                           predicted_value="yes", confidence=0.8 )
    gdb, repo = _patch_db()
    with gdb as mock_gdb, repo as MockRepo:
        eng.record_outcome( "nid-1", pr, "yes", "yes_no" )
        MockRepo.return_value.log_prediction.assert_called_once()
        MockRepo.return_value.update_outcome.assert_called_once()


def test_record_outcome_dict_actual_value():
    eng = _engine()
    eng._store_decision = lambda *a, **k: None
    pr = PredictionResult( response_type="multiple_choice", category="approach", strategy="cbr_majority_vote",
                           predicted_value={ "answers": { "DB": "PG" } }, confidence=0.7 )
    gdb, repo = _patch_db()
    with gdb, repo as MockRepo:
        eng.record_outcome( "nid-2", pr, { "answers": { "DB": "PG" } }, "multiple_choice" )
        MockRepo.return_value.update_outcome.assert_called_once()


def test_record_outcome_other_actual_value_coerced():
    eng = _engine()
    eng._store_decision = lambda *a, **k: None
    pr = PredictionResult( response_type="yes_no", category="c", strategy="s", predicted_value="yes", confidence=0.5 )
    gdb, repo = _patch_db()
    with gdb, repo:
        eng.record_outcome( "nid-3", pr, 42, "yes_no" )   # int → {"value": "42"}


def test_record_outcome_open_ended_calls_enrich_and_strips_transient():
    eng = _engine()
    eng._store_decision = lambda *a, **k: None
    # enrich injects a transient _embedding_similarity which must be stripped before db write
    eng._generate_embedding = lambda text: [ 1.0, 0.0 ]
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s",
                           predicted_value="hello", confidence=0.6 )
    gdb, repo = _patch_db()
    with gdb, repo as MockRepo:
        eng.record_outcome( "nid-4", pr, { "value": "world" }, "open_ended" )
        _, kwargs = MockRepo.return_value.update_outcome.call_args
        assert all( not k.startswith( "_" ) for k in kwargs[ "actual_value" ] )


def test_record_outcome_swallows_exception():
    eng = _engine( debug=True )
    gdb = patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "db down" ) )
    pr = PredictionResult( response_type="yes_no", category="c", strategy="s", predicted_value="yes", confidence=0.5 )
    with gdb:
        eng.record_outcome( "nid-5", pr, "yes", "yes_no" )   # must not raise


# =========================================================================== #
# _store_decision
# =========================================================================== #
def _engine_with_store_provider( provider_emb=None ):
    eng = _engine()
    store = MagicMock()
    provider = MagicMock()
    provider.generate_embedding.return_value = provider_emb if provider_emb is not None else [ 0.1, 0.2 ]
    eng._get_embedding_store    = lambda: store
    eng._get_embedding_provider = lambda: provider
    return eng, store, provider


def test_store_decision_store_none_returns_early():
    eng = _engine()
    eng._get_embedding_store    = lambda: None
    eng._get_embedding_provider = lambda: MagicMock()
    pr = PredictionResult( response_type="yes_no", category="c", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, "yes", "yes_no" )   # no exception, nothing stored


def test_store_decision_no_message_returns_early():
    eng, store, _ = _engine_with_store_provider()
    pr = PredictionResult( response_type="yes_no", category="c", strategy="s", metadata={} )
    eng._store_decision( "nid", pr, "yes", "yes_no" )
    store.add_decision.assert_not_called()


def test_store_decision_str_mc_with_answers():
    eng, store, _ = _engine_with_store_provider()
    pr = PredictionResult( response_type="multiple_choice", category="approach", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, json.dumps( { "answers": { "DB": "PG" } } ), "multiple_choice" )
    _, kwargs = store.add_decision.call_args
    assert json.loads( kwargs[ "decision_value" ] ) == { "answers": { "DB": "PG" } }


def test_store_decision_str_mc_without_answers_wraps_other():
    eng, store, _ = _engine_with_store_provider()
    pr = PredictionResult( response_type="multiple_choice", category="approach", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, json.dumps( { "foo": 1 } ), "multiple_choice" )
    _, kwargs = store.add_decision.call_args
    assert json.loads( kwargs[ "decision_value" ] ) == { "answers": { "_other": '{"foo": 1}' } }


def test_store_decision_str_mc_invalid_json_wraps_other():
    eng, store, _ = _engine_with_store_provider()
    pr = PredictionResult( response_type="multiple_choice", category="approach", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, "not json", "multiple_choice" )
    _, kwargs = store.add_decision.call_args
    assert json.loads( kwargs[ "decision_value" ] ) == { "answers": { "_other": "not json" } }


def test_store_decision_str_non_mc_passthrough():
    eng, store, _ = _engine_with_store_provider()
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, "free text answer", "open_ended" )
    _, kwargs = store.add_decision.call_args
    assert kwargs[ "decision_value" ] == "free text answer"


def test_store_decision_dict_with_answers():
    eng, store, _ = _engine_with_store_provider()
    pr = PredictionResult( response_type="multiple_choice", category="c", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, { "answers": { "H": "v" } }, "multiple_choice" )
    _, kwargs = store.add_decision.call_args
    assert json.loads( kwargs[ "decision_value" ] ) == { "answers": { "H": "v" } }


def test_store_decision_dict_with_value():
    eng, store, _ = _engine_with_store_provider()
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, { "value": "hello" }, "open_ended" )
    _, kwargs = store.add_decision.call_args
    assert kwargs[ "decision_value" ] == "hello"


def test_store_decision_dict_empty_falls_back_to_str():
    eng, store, _ = _engine_with_store_provider()
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, {}, "open_ended" )    # no answers, no value → str({})
    _, kwargs = store.add_decision.call_args
    assert kwargs[ "decision_value" ] == "{}"


def test_store_decision_non_str_non_dict_coerced():
    eng, store, _ = _engine_with_store_provider()
    pr = PredictionResult( response_type="open_ended", category="c", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, 99, "open_ended" )
    _, kwargs = store.add_decision.call_args
    assert kwargs[ "decision_value" ] == "99"


def test_store_decision_swallows_exception():
    eng, store, provider = _engine_with_store_provider()
    provider.generate_embedding.side_effect = RuntimeError( "embed boom" )
    eng.debug = True
    pr = PredictionResult( response_type="yes_no", category="c", strategy="s",
                           metadata={ "original_message": "q" } )
    eng._store_decision( "nid", pr, "yes", "yes_no" )   # must not raise
    store.add_decision.assert_not_called()


# =========================================================================== #
# get_accuracy_summary
# =========================================================================== #
def test_get_accuracy_summary_success():
    eng = _engine()
    summary = { "window_days": 30, "total_predictions": 5, "accuracy_rate": 0.8 }
    gdb = patch( "cosa.rest.db.database.get_db" )
    repo = patch( "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository" )
    with gdb, repo as MockRepo:
        MockRepo.return_value.get_accuracy_summary.return_value = summary
        assert eng.get_accuracy_summary() == summary


def test_get_accuracy_summary_exception_returns_error_dict():
    eng = _engine( debug=True )
    with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "db down" ) ):
        result = eng.get_accuracy_summary( window_days=7 )
    assert result[ "window_days" ] == 7
    assert result[ "total_predictions" ] == 0
    assert "db down" in result[ "error" ]


# =========================================================================== #
# _generate_embedding
# =========================================================================== #
def test_generate_embedding_empty_text_returns_none():
    eng = _engine()
    assert eng._generate_embedding( "" ) is None
    assert eng._generate_embedding( "   " ) is None


def test_generate_embedding_local_provider_success():
    eng = _engine()
    provider = MagicMock()
    provider.generate_embedding.return_value = [ 0.1, 0.2 ]
    eng._get_embedding_provider = lambda: provider
    assert eng._generate_embedding( "text" ) == [ 0.1, 0.2 ]


def test_generate_embedding_provider_none_uses_http():
    eng = _engine( debug=True )
    eng._get_embedding_provider = lambda: None
    eng._generate_embedding_via_http = lambda text: [ 9.9 ]
    assert eng._generate_embedding( "text" ) == [ 9.9 ]


def test_generate_embedding_provider_returns_none_falls_through_to_http():
    eng = _engine()
    provider = MagicMock()
    provider.generate_embedding.return_value = None
    eng._get_embedding_provider = lambda: provider
    eng._generate_embedding_via_http = lambda text: [ 8.8 ]
    assert eng._generate_embedding( "text" ) == [ 8.8 ]


def test_generate_embedding_provider_raises_falls_through_to_http():
    eng = _engine( debug=True )
    provider = MagicMock()
    provider.generate_embedding.side_effect = RuntimeError( "cuda oom" )
    eng._get_embedding_provider = lambda: provider
    eng._generate_embedding_via_http = lambda text: [ 7.7 ]
    assert eng._generate_embedding( "text" ) == [ 7.7 ]


# =========================================================================== #
# _generate_embedding_via_http
# =========================================================================== #
def test_http_embedding_no_api_key_returns_none():
    eng = _engine( debug=True )
    with patch( "cosa.utils.util.get_api_key", return_value=None ):
        assert eng._generate_embedding_via_http( "text" ) is None


def test_http_embedding_success():
    eng = _engine()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = { "embedding": [ 0.1, 0.2, 0.3 ] }
    with patch( "cosa.utils.util.get_api_key", return_value="key" ), \
         patch( "requests.post", return_value=resp ):
        assert eng._generate_embedding_via_http( "text" ) == [ 0.1, 0.2, 0.3 ]


def test_http_embedding_non_200_returns_none():
    eng = _engine( debug=True )
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "server error"
    with patch( "cosa.utils.util.get_api_key", return_value="key" ), \
         patch( "requests.post", return_value=resp ):
        assert eng._generate_embedding_via_http( "text" ) is None


def test_http_embedding_request_raises_returns_none():
    eng = _engine( debug=True )
    with patch( "cosa.utils.util.get_api_key", return_value="key" ), \
         patch( "requests.post", side_effect=RuntimeError( "conn refused" ) ):
        assert eng._generate_embedding_via_http( "text" ) is None


# =========================================================================== #
# Branch-completeness: debug-False arcs in the OE/OEB tiers + _enrich edge arcs
# ( the debug-True arcs are covered above; these cover the `if self.debug:` False skips )
# =========================================================================== #
def test_oe_tier1_exact_match_debug_false():
    eng = _engine( debug=False )
    cases = [ ( 95.0, { "question": "Q?", "decision_value": "A" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_open_ended( "q?", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_RETRIEVAL


def test_oe_tier2_synthesis_debug_false():
    eng = _engine( debug=False )
    cases = [ ( 88.0, { "question": "diff", "decision_value": "x" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    eng._build_synthesis_prompt = lambda message, sc: "PROMPT"
    client = MagicMock()
    client.run.return_value = (
        "<open_ended_synthesis_response><predicted_answer>ans</predicted_answer>"
        "<reasoning>r</reasoning><confidence>0.5</confidence></open_ended_synthesis_response>"
    )
    eng._get_llm_client = lambda: client
    r = eng._predict_open_ended( "current", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_LLM_SYNTHESIS


def test_oeb_tier1_exact_match_debug_false():
    eng = _engine( debug=False )
    dv = json.dumps( { "answers": { "T": "v" } } )
    cases = [ ( 95.0, { "question": "Q?", "decision_value": dv } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    r = eng._predict_open_ended_batch( "q?", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_CBR_RETRIEVAL


def test_oeb_tier2_synthesis_debug_false():
    eng = _engine( debug=False )
    cases = [ ( 88.0, { "question": "diff", "decision_value": "x" } ) ]
    eng._get_embedding_store = lambda: _store( cases=cases )
    eng._build_synthesis_prompt = lambda message, sc: "PROMPT"
    client = MagicMock()
    client.run.return_value = (
        "<open_ended_synthesis_response><predicted_answer>plain</predicted_answer>"
        "<reasoning>r</reasoning><confidence>0.9</confidence></open_ended_synthesis_response>"
    )
    eng._get_llm_client = lambda: client
    r = eng._predict_open_ended_batch( "current", "input", [ 0.1 ] )
    assert r.strategy == STRATEGY_LLM_SYNTHESIS


def test_enrich_neither_response_type_falls_through_to_exit():
    # response_type is neither OE nor OEB → if False, elif False → method exits without injecting.
    # ( record_outcome only calls _enrich for OE/OEB, so this exercises the defensive elif-False arc. )
    eng = _engine()
    eng._generate_embedding = lambda text: [ 1.0, 0.0 ]
    pr = PredictionResult( response_type="yes_no", category="c", strategy="s", predicted_value="hello" )
    actual = { "value": "world" }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_YES_NO )
    assert "_embedding_similarity" not in actual


def test_enrich_batch_embedding_none_continues_loop_multi_header():
    # 2 headers, embeddings both None → per-header `if pred_emb is not None and actual_emb is not None`
    # False → loop continues to the next header ( the 1070->1060 back-arc ).
    eng = _engine()
    eng._generate_embedding = lambda text: None
    pr = PredictionResult( response_type="open_ended_batch", category="c", strategy="s",
                           predicted_value={ "answers": { "H1": "a", "H2": "b" } } )
    actual = { "answers": { "H1": "x", "H2": "y" } }
    eng._enrich_with_embedding_similarity( actual, pr, RESPONSE_TYPE_OPEN_ENDED_BATCH )
    assert "_embedding_similarity" not in actual
