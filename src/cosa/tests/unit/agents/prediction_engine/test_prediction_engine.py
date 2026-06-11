"""
Unit tests for cosa.agents.prediction_engine.prediction_engine.PredictionEngine.

PredictionEngine is a thread-safe singleton that predicts notification responses
(yes_no / multiple_choice / open_ended / open_ended_batch) via CBR retrieval over a
LanceDB store plus optional LLM synthesis, and logs outcomes to prediction_log.

These tests isolate the engine from all heavy collaborators — the embedding provider,
the LanceDB store, the LLM client, and the DB session — using small fakes + monkeypatch
on the in-method import sites. Every public method and every dispatch/validation branch
is exercised: singleton/reset, both __init__ config arcs, the lazy-loaders (success /
exception / cached), predict() dispatch (disabled / each type / unknown / error),
the four _predict_* strategies (cold-start arcs, CBR majority vote, single/multi-select
validation+constraint, two-tier exact-match vs LLM-synthesis vs LLM-fallback), the
static parsers, embedding generation (local + HTTP fallback), record_outcome, and
get_accuracy_summary.

`quick_smoke_test` is coverage-excluded (house style); its assertions are harvested here.

Authored by Rachel 🕊️ for the CoSA 100% coverage campaign (prediction_engine group).
"""

import json

import pytest

from cosa.agents.prediction_engine.prediction_engine import (
    PredictionEngine,
    get_prediction_engine,
)
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.agents.prediction_engine import config as cfg


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeStore:
    """A stand-in for ProxyDecisionEmbeddings exposing find_similar + add_decision."""

    def __init__( self, cases=None, raise_on_find=False ):
        self._cases         = cases if cases is not None else []
        self._raise_on_find = raise_on_find
        self.added          = []

    def find_similar( self, **kwargs ):
        if self._raise_on_find:
            raise RuntimeError( "boom-find" )
        return self._cases

    def add_decision( self, **kwargs ):
        self.added.append( kwargs )


class FakeProvider:
    """A stand-in for the embedding provider: returns a fixed vector (or raises)."""

    def __init__( self, vector=None, raise_on_generate=False ):
        self._vector = vector if vector is not None else [ 0.1, 0.2, 0.3 ]
        self._raise  = raise_on_generate

    def generate_embedding( self, text, content_type="prose" ):
        if self._raise:
            raise RuntimeError( "boom-embed" )
        return self._vector


class FakeLlmClient:
    """A stand-in LLM client: returns a canned XML response (or raises)."""

    def __init__( self, response="", raise_on_run=False ):
        self._response = response
        self._raise    = raise_on_run

    def run( self, prompt ):
        if self._raise:
            raise RuntimeError( "boom-llm" )
        return self._response


def _case( similarity_pct, **record ):
    """Build a ( similarity_pct, record ) CBR tuple."""
    return ( similarity_pct, record )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    """A fresh, default-config engine with lazy collaborators left unset."""
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    yield eng
    PredictionEngine.reset()


@pytest.fixture
def wired_engine():
    """Engine pre-wired with a fake provider so _generate_embedding returns a vector."""
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._embedding_provider = FakeProvider( vector=[ 0.5, 0.5, 0.5 ] )
    yield eng
    PredictionEngine.reset()


# ---------------------------------------------------------------------------
# Singleton / init / convenience
# ---------------------------------------------------------------------------

def test_singleton_identity_and_init_runs_once( engine ):
    """Second construction returns the same instance and does NOT re-run __init__."""
    again = PredictionEngine( debug=True )
    assert again is engine
    # debug stayed False — the second __init__ early-returned on _initialized.
    assert engine.debug is False


def test_get_prediction_engine_returns_singleton( engine ):
    assert get_prediction_engine() is engine


def test_reset_clears_singleton():
    PredictionEngine.reset()
    a = PredictionEngine()
    PredictionEngine.reset()
    b = PredictionEngine()
    assert a is not b
    PredictionEngine.reset()


def test_init_defaults_without_config():
    """No config_mgr → defaults branch populates every tunable from config.py."""
    PredictionEngine.reset()
    eng = PredictionEngine()
    assert eng.enabled is cfg.DEFAULT_ENABLED
    assert eng.cbr_top_k == cfg.DEFAULT_CBR_TOP_K
    assert eng.similarity_threshold == cfg.DEFAULT_CBR_SIMILARITY_THRESHOLD
    assert eng.lancedb_table == cfg.DEFAULT_LANCEDB_TABLE
    assert eng.open_ended_cbr_top_k == cfg.DEFAULT_OPEN_ENDED_CBR_TOP_K
    PredictionEngine.reset()


def test_init_with_config_mgr_reads_keys():
    """A config_mgr drives every key via .get(...) and ORs debug."""
    class FakeConfig:
        def get( self, key, default=None, return_type=None ):
            table = {
                "prediction engine enabled"                       : True,
                "prediction engine debug"                         : False,
                "prediction engine cbr top k"                     : 9,
                "prediction engine cbr similarity threshold"      : 0.8,
                "prediction engine confidence threshold"          : 0.65,
                "prediction engine lancedb table"                 : "tbl_x",
                "prediction engine embedding fallback port"       : 1234,
                "prediction engine open ended cbr top k"          : 7,
                "prediction engine open ended cbr threshold"      : 0.9,
                "prediction engine open ended llm spec key"       : "spec/x",
                "prediction engine open ended prompt template"    : "/src/conf/p.txt",
                "prediction hint vote approved weight"            : 2.0,
                "prediction hint vote rejected weight"            : 2.0,
                "prediction hint voting enabled"                  : True,
                "prediction hint vote min confidence threshold"   : 0.5,
            }
            return table[ key ]

    PredictionEngine.reset()
    eng = PredictionEngine( config_mgr=FakeConfig(), debug=True )
    assert eng.enabled is True
    assert eng.cbr_top_k == 9
    assert eng.similarity_threshold == 0.8
    assert eng.lancedb_table == "tbl_x"
    assert eng._server_port == 1234
    assert eng.open_ended_cbr_threshold == 0.9
    assert eng._llm_spec_key == "spec/x"
    assert eng.hint_vote_approved_weight == 2.0
    assert eng.hint_vote_rejected_weight == 2.0
    assert eng.hint_voting_enabled is True
    assert eng.hint_vote_min_confidence_threshold == 0.5
    # debug = config(False) OR debug(True) = True
    assert eng.debug is True
    PredictionEngine.reset()


def test_init_debug_print_arc( capsys ):
    """debug=True exercises the init debug-print line."""
    PredictionEngine.reset()
    PredictionEngine( debug=True )
    assert "[PredictionEngine] Initialized" in capsys.readouterr().out
    PredictionEngine.reset()


# ---------------------------------------------------------------------------
# Lazy loaders
# ---------------------------------------------------------------------------

def test_get_embedding_provider_success( engine, monkeypatch ):
    sentinel = object()
    monkeypatch.setattr(
        "cosa.memory.embedding_provider.get_embedding_provider",
        lambda debug=False: sentinel,
    )
    assert engine._get_embedding_provider() is sentinel
    # Cached on second call (no re-import needed).
    assert engine._get_embedding_provider() is sentinel


def test_get_embedding_provider_failure_returns_none( engine, monkeypatch ):
    def boom( debug=False ):
        raise RuntimeError( "no provider" )
    monkeypatch.setattr( "cosa.memory.embedding_provider.get_embedding_provider", boom )
    engine.debug = True
    assert engine._get_embedding_provider() is None


def test_get_embedding_provider_cached_short_circuit( engine ):
    engine._embedding_provider = "already"
    assert engine._get_embedding_provider() == "already"


def test_get_embedding_store_success( engine, monkeypatch ):
    captured = {}
    class FakeProxy:
        def __init__( self, **kwargs ):
            captured.update( kwargs )
    monkeypatch.setattr(
        "cosa.agents.decision_proxy.proxy_decision_embeddings.ProxyDecisionEmbeddings",
        FakeProxy,
    )
    store = engine._get_embedding_store()
    assert isinstance( store, FakeProxy )
    assert captured[ "table_name" ] == engine.lancedb_table
    assert captured[ "embedding_dim" ] == 768
    # cached
    assert engine._get_embedding_store() is store


def test_get_embedding_store_failure_returns_none( engine, monkeypatch ):
    def boom( **kwargs ):
        raise RuntimeError( "no store" )
    monkeypatch.setattr(
        "cosa.agents.decision_proxy.proxy_decision_embeddings.ProxyDecisionEmbeddings",
        boom,
    )
    engine.debug = True
    assert engine._get_embedding_store() is None


# ---------------------------------------------------------------------------
# predict() dispatch
# ---------------------------------------------------------------------------

def test_predict_disabled_returns_engine_disabled( engine ):
    engine.enabled = False
    result = engine.predict( { "message": "Should I proceed?", "response_type": "yes_no" } )
    assert result.strategy == cfg.STRATEGY_COLD_START
    assert result.metadata[ "reason" ] == "engine_disabled"


def test_predict_unknown_type_is_cold_start( wired_engine, monkeypatch ):
    monkeypatch.setattr( wired_engine, "_generate_embedding", lambda text: [ 0.1 ] )
    result = wired_engine.predict( { "message": "hi", "response_type": "carrier_pigeon" } )
    assert result.strategy == cfg.STRATEGY_COLD_START
    assert result.metadata[ "reason" ] == "unsupported_type_carrier_pigeon"


def test_predict_dispatches_to_each_type( wired_engine, monkeypatch ):
    """Each known response_type routes to its handler (handlers stubbed to identify)."""
    monkeypatch.setattr( wired_engine, "_generate_embedding", lambda text: [ 0.1 ] )
    monkeypatch.setattr( wired_engine, "_predict_yes_no", lambda *a: "YN" )
    monkeypatch.setattr( wired_engine, "_predict_multiple_choice", lambda *a, **k: "MC" )
    monkeypatch.setattr( wired_engine, "_predict_open_ended", lambda *a: "OE" )
    monkeypatch.setattr( wired_engine, "_predict_open_ended_batch", lambda *a: "OEB" )
    assert wired_engine.predict( { "message": "m", "response_type": "yes_no" } ) == "YN"
    assert wired_engine.predict( { "message": "m", "response_type": "multiple_choice" } ) == "MC"
    assert wired_engine.predict( { "message": "m", "response_type": "open_ended" } ) == "OE"
    assert wired_engine.predict( { "message": "m", "response_type": "open_ended_batch" } ) == "OEB"


def test_predict_handler_exception_is_cold_start( wired_engine, monkeypatch ):
    monkeypatch.setattr( wired_engine, "_generate_embedding", lambda text: [ 0.1 ] )
    def boom( *a ):
        raise RuntimeError( "handler-fail" )
    monkeypatch.setattr( wired_engine, "_predict_yes_no", boom )
    wired_engine.debug = True
    result = wired_engine.predict( { "message": "m", "response_type": "yes_no" } )
    assert result.strategy == cfg.STRATEGY_COLD_START
    assert result.metadata[ "reason" ] == "prediction_error"
    assert "handler-fail" in result.metadata[ "error" ]


# ---------------------------------------------------------------------------
# _predict_yes_no
# ---------------------------------------------------------------------------

def test_yes_no_no_embedding( engine ):
    r = engine._predict_yes_no( "m", "permission", None )
    assert r.strategy == cfg.STRATEGY_COLD_START and r.metadata[ "reason" ] == "no_embedding"


def test_yes_no_no_store( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: None )
    r = engine._predict_yes_no( "m", "permission", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_embedding_store"


def test_yes_no_find_similar_raises_then_cold_start( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( raise_on_find=True ) )
    engine.debug = True
    r = engine._predict_yes_no( "m", "permission", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_yes_no_no_similar_cases( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=[] ) )
    r = engine._predict_yes_no( "m", "permission", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases" and r.similar_case_count == 0


def test_yes_no_majority_vote_unanimous( engine, monkeypatch ):
    cases = [ _case( 95.0, decision_value="yes" ), _case( 80.0, decision_value="yes" ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    r = engine._predict_yes_no( "m", "permission", [ 0.1 ] )
    assert r.strategy == cfg.STRATEGY_CBR_MAJORITY
    assert r.predicted_value == "yes"
    assert r.confidence == pytest.approx( 0.95 )       # max_sim 0.95 * consistency 1.0
    assert r.metadata[ "votes" ] == { "yes": 2 }
    assert r.predicted_qualifier is None
    assert r.metadata[ "qualifier_similarity" ] is None


def test_yes_no_split_vote_confidence_and_qualifier( engine, monkeypatch ):
    """Tie→first-inserted winner; winning-side qualifier extracted from highest-sim case."""
    cases = [
        _case( 95.0, decision_value="yes [comment: only the old files]" ),
        _case( 80.0, decision_value="no" ),
    ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    engine.debug = True
    r = engine._predict_yes_no( "m", "permission", [ 0.1 ] )
    assert r.predicted_value == "yes"
    assert r.confidence == pytest.approx( 0.95 * 0.5 )
    assert r.predicted_qualifier == "only the old files"
    assert r.metadata[ "qualifier_similarity" ] == pytest.approx( 0.95 )


# ---------------------------------------------------------------------------
# _extract_valid_options (static)
# ---------------------------------------------------------------------------

def test_extract_valid_options_none():
    assert PredictionEngine._extract_valid_options( None ) is None


def test_extract_valid_options_from_dict():
    options = { "questions": [
        { "header": "DB", "multi_select": False,
          "options": [ { "label": "PG" }, { "label": "MySQL" }, "not-a-dict" ] },
    ] }
    parsed = PredictionEngine._extract_valid_options( options )
    assert parsed[ "DB" ][ "labels" ] == { "PG", "MySQL" }
    assert parsed[ "DB" ][ "multi_select" ] is False


def test_extract_valid_options_from_json_string_and_multiselect_alias():
    options = json.dumps( { "questions": [
        { "question": "Pick features", "multiSelect": True,
          "options": [ { "label": "Auth" } ] },
    ] } )
    parsed = PredictionEngine._extract_valid_options( options )
    # header falls back to the question text; multiSelect alias honored.
    assert parsed[ "Pick features" ][ "multi_select" ] is True


def test_extract_valid_options_empty_questions_returns_none():
    assert PredictionEngine._extract_valid_options( { "questions": [] } ) is None


def test_extract_valid_options_non_dict_returns_none():
    assert PredictionEngine._extract_valid_options( [ 1, 2, 3 ] ) is None


def test_extract_valid_options_no_labels_returns_none():
    options = { "questions": [ { "header": "H", "options": [ { "no_label": "x" } ] } ] }
    assert PredictionEngine._extract_valid_options( options ) is None


def test_extract_valid_options_bad_json_returns_none():
    assert PredictionEngine._extract_valid_options( "{not valid json" ) is None


# ---------------------------------------------------------------------------
# _parse_mc_decision_value / _parse_batch_decision_value (static)
# ---------------------------------------------------------------------------

def test_parse_mc_decision_value_arcs():
    assert PredictionEngine._parse_mc_decision_value( "" ) is None
    assert PredictionEngine._parse_mc_decision_value( '{"answers": {"DB": "PG"}}' ) == { "answers": { "DB": "PG" } }
    assert PredictionEngine._parse_mc_decision_value( '{"other": 1}' ) is None
    assert PredictionEngine._parse_mc_decision_value( "not json" ) is None


def test_parse_batch_decision_value_arcs():
    assert PredictionEngine._parse_batch_decision_value( "  " ) == "  "
    assert PredictionEngine._parse_batch_decision_value( '{"answers": {"A": "x"}}' ) == { "answers": { "A": "x" } }
    # Valid JSON but no answers key → raw string returned.
    assert PredictionEngine._parse_batch_decision_value( '{"k": 1}' ) == '{"k": 1}'
    # Invalid JSON → raw string returned.
    assert PredictionEngine._parse_batch_decision_value( "raw" ) == "raw"


# ---------------------------------------------------------------------------
# _predict_multiple_choice
# ---------------------------------------------------------------------------

def test_mc_no_embedding( engine ):
    r = engine._predict_multiple_choice( "m", "workflow", None )
    assert r.metadata[ "reason" ] == "no_embedding"


def test_mc_no_store( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: None )
    r = engine._predict_multiple_choice( "m", "workflow", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_embedding_store"


def test_mc_find_similar_raises_then_cold_start( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( raise_on_find=True ) )
    engine.debug = True
    r = engine._predict_multiple_choice( "m", "workflow", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_mc_no_valid_cases_when_all_unparseable( engine, monkeypatch ):
    cases = [ _case( 90.0, decision_value="not-json" ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    r = engine._predict_multiple_choice( "m", "workflow", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_valid_mc_cases"


def test_mc_single_select_majority( engine, monkeypatch ):
    cases = [
        _case( 90.0, decision_value=json.dumps( { "answers": { "DB": "PostgreSQL" } } ) ),
        _case( 70.0, decision_value=json.dumps( { "answers": { "DB": "PostgreSQL" } } ) ),
    ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.strategy == cfg.STRATEGY_CBR_MAJORITY
    assert r.predicted_value == { "answers": { "DB": "PostgreSQL" } }
    assert r.confidence == pytest.approx( 0.9 )         # max_sim 0.9 * consistency 1.0
    assert r.metadata[ "multi_select" ] is False


def test_mc_multi_select_via_data_detection( engine, monkeypatch ):
    cases = [ _case( 88.0, decision_value=json.dumps( { "answers": { "Features": [ "Auth", "Caching" ] } } ) ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    engine.debug = True
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.metadata[ "multi_select" ] is True
    assert r.predicted_value == { "answers": { "Features": [ "Auth", "Caching" ] } }


def test_mc_options_force_multiselect_and_constrain( engine, monkeypatch ):
    """options structure forces multi_select and constrains predictions to valid labels."""
    cases = [ _case( 80.0, decision_value=json.dumps( { "answers": { "Features": [ "Auth", "Bogus" ] } } ) ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    options = { "questions": [
        { "header": "Features", "multi_select": True, "options": [ { "label": "Auth" } ] },
    ] }
    engine.debug = True
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.predicted_value == { "answers": { "Features": [ "Auth" ] } }   # Bogus filtered out
    assert r.metadata[ "constrained" ] is True


def test_mc_multi_select_all_filtered_is_cold_start( engine, monkeypatch ):
    cases = [ _case( 80.0, decision_value=json.dumps( { "answers": { "Features": [ "Bogus" ] } } ) ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    options = { "questions": [
        { "header": "Features", "multi_select": True, "options": [ { "label": "Auth" } ] },
    ] }
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.metadata[ "reason" ] == "no_valid_options_after_filtering"


def test_mc_single_select_constrained_fallback_to_valid_vote( engine, monkeypatch ):
    """Winner invalid but another valid option was voted → fallback to it (constrained)."""
    cases = [
        _case( 90.0, decision_value=json.dumps( { "answers": { "DB": "MySQL" } } ) ),
        _case( 85.0, decision_value=json.dumps( { "answers": { "DB": "MySQL" } } ) ),
        _case( 60.0, decision_value=json.dumps( { "answers": { "DB": "PostgreSQL" } } ) ),
    ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    options = { "questions": [
        { "header": "DB", "multi_select": False, "options": [ { "label": "PostgreSQL" } ] },
    ] }
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.predicted_value == { "answers": { "DB": "PostgreSQL" } }
    assert r.metadata[ "constrained" ] is True


def test_mc_single_select_no_valid_vote_is_cold_start( engine, monkeypatch ):
    cases = [ _case( 90.0, decision_value=json.dumps( { "answers": { "DB": "MySQL" } } ) ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    options = { "questions": [
        { "header": "DB", "multi_select": False, "options": [ { "label": "PostgreSQL" } ] },
    ] }
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.metadata[ "reason" ] == "no_valid_options_after_filtering"


def test_mc_header_not_in_options_kept_as_is( engine, monkeypatch ):
    """A predicted header absent from the options structure is preserved (backward compat)."""
    cases = [ _case( 90.0, decision_value=json.dumps( { "answers": { "Cache": "Redis" } } ) ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    options = { "questions": [
        { "header": "DB", "multi_select": False, "options": [ { "label": "PostgreSQL" } ] },
    ] }
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.predicted_value == { "answers": { "Cache": "Redis" } }


def test_mc_skips_unparseable_case_then_uses_valid( engine, monkeypatch ):
    """An unparseable case is skipped (continue) while a valid one drives the prediction."""
    cases = [
        _case( 95.0, decision_value="garbage" ),
        _case( 90.0, decision_value=json.dumps( { "answers": { "DB": "PG" } } ) ),
    ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ] )
    assert r.predicted_value == { "answers": { "DB": "PG" } }
    assert r.metadata[ "valid_cases" ] == 1


# ---------------------------------------------------------------------------
# _tally_multi_select_votes (direct)
# ---------------------------------------------------------------------------

def test_tally_multi_select_threshold_and_fallback( engine ):
    # positive_case_mass=4 → threshold 2.0. "A"(3) >= thr selected; "B"(1) < thr excluded.
    votes = { "H1": { "A": 3, "B": 1 } }
    answers, avg = engine._tally_multi_select_votes( votes, positive_case_mass=4 )
    assert answers[ "H1" ] == [ "A" ]
    assert avg == pytest.approx( 0.75 )                 # A inclusion 3/4


def test_tally_multi_select_no_option_meets_threshold_fallback( engine ):
    # positive_case_mass=4 → threshold 2.0. Both below → fallback to highest-weighted option.
    votes = { "H1": { "A": 1, "B": 1 } }
    answers, avg = engine._tally_multi_select_votes( votes, positive_case_mass=4 )
    assert len( answers[ "H1" ] ) == 1                  # single fallback option
    assert avg == pytest.approx( 0.25 )                 # 1/4


# ---------------------------------------------------------------------------
# _predict_open_ended
# ---------------------------------------------------------------------------

def test_open_ended_no_embedding( engine ):
    r = engine._predict_open_ended( "m", "input", None )
    assert r.metadata[ "reason" ] == "no_embedding"


def test_open_ended_no_store( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: None )
    r = engine._predict_open_ended( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_embedding_store"


def test_open_ended_find_raises_then_cold_start( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( raise_on_find=True ) )
    engine.debug = True
    r = engine._predict_open_ended( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_open_ended_exact_match_tier1( engine, monkeypatch ):
    cases = [ _case( 96.0, question="What naming convention?", decision_value="snake_case" ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    engine.debug = True
    r = engine._predict_open_ended( "  what NAMING convention?  ", "input", [ 0.1 ] )
    assert r.strategy == cfg.STRATEGY_CBR_RETRIEVAL
    assert r.predicted_value == "snake_case"
    assert r.metadata[ "tier" ] == "exact_match"
    assert r.confidence == pytest.approx( 0.96 )


def test_open_ended_llm_synthesis_tier2( engine, monkeypatch ):
    cases = [ _case( 90.0, question="other q", decision_value="prior answer" ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    monkeypatch.setattr( engine, "_build_synthesis_prompt", lambda m, c: "PROMPT" )
    xml = "<open_ended_synthesis_response><predicted_answer>use kebab-case</predicted_answer>" \
          "<reasoning>pattern</reasoning><confidence>0.7</confidence></open_ended_synthesis_response>"
    monkeypatch.setattr( engine, "_get_llm_client", lambda: FakeLlmClient( response=xml ) )
    engine.debug = True
    r = engine._predict_open_ended( "new question", "input", [ 0.1 ] )
    assert r.strategy == cfg.STRATEGY_LLM_SYNTHESIS
    assert r.predicted_value == "use kebab-case"
    assert r.confidence == pytest.approx( 0.7 )         # min(0.9, 0.7)
    assert r.metadata[ "tier" ] == "llm_synthesis"


def test_open_ended_llm_unavailable_falls_back( engine, monkeypatch ):
    cases = [ _case( 90.0, question="other q", decision_value="prior answer" ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    monkeypatch.setattr( engine, "_build_synthesis_prompt", lambda m, c: "PROMPT" )
    monkeypatch.setattr( engine, "_get_llm_client", lambda: None )   # → RuntimeError → fallback
    engine.debug = True
    r = engine._predict_open_ended( "new question", "input", [ 0.1 ] )
    assert r.strategy == cfg.STRATEGY_CBR_RETRIEVAL
    assert r.predicted_value == "prior answer"
    assert r.metadata[ "tier" ] == "llm_fallback"
    assert "LLM client unavailable" in r.metadata[ "llm_error" ]


# ---------------------------------------------------------------------------
# _build_synthesis_prompt
# ---------------------------------------------------------------------------

def test_build_synthesis_prompt_injects_template_and_cases( engine, monkeypatch ):
    template = "EX={{PYDANTIC_XML_EXAMPLE}} Q={current_question} N={case_count}\n{formatted_cases}"
    monkeypatch.setattr( "cosa.utils.util.get_file_as_string", lambda path: template )
    monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: "/root" )
    cases = [ _case( 90.0, question="prior q", decision_value="prior a" ) ]
    prompt = engine._build_synthesis_prompt( "current q", cases )
    assert "Q=current q" in prompt
    assert "N=1" in prompt
    assert '<case n="1" similarity="0.9">' in prompt
    assert "<question>prior q</question>" in prompt
    assert "</stop>" in prompt                          # xml example terminated


# ---------------------------------------------------------------------------
# _predict_open_ended_batch
# ---------------------------------------------------------------------------

def test_open_ended_batch_no_embedding( engine ):
    r = engine._predict_open_ended_batch( "m", "input", None )
    assert r.metadata[ "reason" ] == "no_embedding"


def test_open_ended_batch_no_store( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: None )
    r = engine._predict_open_ended_batch( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_embedding_store"


def test_open_ended_batch_find_raises_then_cold_start( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( raise_on_find=True ) )
    engine.debug = True
    r = engine._predict_open_ended_batch( "m", "input", [ 0.1 ] )
    assert r.metadata[ "reason" ] == "no_similar_cases"


def test_open_ended_batch_exact_match_parses_json( engine, monkeypatch ):
    dv = json.dumps( { "answers": { "Topic": "AI" } } )
    cases = [ _case( 99.0, question="Q", decision_value=dv ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    engine.debug = True
    r = engine._predict_open_ended_batch( "q", "input", [ 0.1 ] )
    assert r.strategy == cfg.STRATEGY_CBR_RETRIEVAL
    assert r.predicted_value == { "answers": { "Topic": "AI" } }
    assert r.metadata[ "tier" ] == "exact_match"


def test_open_ended_batch_llm_synthesis( engine, monkeypatch ):
    cases = [ _case( 90.0, question="other", decision_value="prior" ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    monkeypatch.setattr( engine, "_build_synthesis_prompt", lambda m, c: "PROMPT" )
    answer_json = json.dumps( { "answers": { "Topic": "ML" } } )
    xml = f"<open_ended_synthesis_response><predicted_answer>{answer_json}</predicted_answer>" \
          "<reasoning>r</reasoning><confidence>0.6</confidence></open_ended_synthesis_response>"
    monkeypatch.setattr( engine, "_get_llm_client", lambda: FakeLlmClient( response=xml ) )
    engine.debug = True
    r = engine._predict_open_ended_batch( "new q", "input", [ 0.1 ] )
    assert r.strategy == cfg.STRATEGY_LLM_SYNTHESIS
    assert r.predicted_value == { "answers": { "Topic": "ML" } }
    assert r.metadata[ "tier" ] == "llm_synthesis"


def test_open_ended_batch_llm_failure_falls_back( engine, monkeypatch ):
    dv = json.dumps( { "answers": { "Topic": "AI" } } )
    cases = [ _case( 90.0, question="other", decision_value=dv ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases=cases ) )
    monkeypatch.setattr( engine, "_build_synthesis_prompt", lambda m, c: "PROMPT" )
    monkeypatch.setattr( engine, "_get_llm_client", lambda: FakeLlmClient( raise_on_run=True ) )
    engine.debug = True
    r = engine._predict_open_ended_batch( "new q", "input", [ 0.1 ] )
    assert r.strategy == cfg.STRATEGY_CBR_RETRIEVAL
    assert r.predicted_value == { "answers": { "Topic": "AI" } }
    assert r.metadata[ "tier" ] == "llm_fallback"


# ---------------------------------------------------------------------------
# _get_llm_client
# ---------------------------------------------------------------------------

def test_get_llm_client_success( engine, monkeypatch ):
    sentinel = object()
    class FakeFactory:
        def get_client( self, spec, debug=False ):
            return sentinel
    monkeypatch.setattr( "cosa.agents.llm_client_factory.LlmClientFactory", FakeFactory )
    assert engine._get_llm_client() is sentinel
    assert engine._get_llm_client() is sentinel          # cached


def test_get_llm_client_failure_returns_none( engine, monkeypatch ):
    class BoomFactory:
        def __init__( self ):
            raise RuntimeError( "no factory" )
    monkeypatch.setattr( "cosa.agents.llm_client_factory.LlmClientFactory", BoomFactory )
    engine.debug = True
    assert engine._get_llm_client() is None


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------

def test_cosine_similarity_of_unit_vectors():
    assert PredictionEngine._cosine_similarity( [ 1.0, 0.0 ], [ 1.0, 0.0 ] ) == pytest.approx( 1.0 )
    assert PredictionEngine._cosine_similarity( [ 1.0, 0.0 ], [ 0.0, 1.0 ] ) == pytest.approx( 0.0 )


# ---------------------------------------------------------------------------
# _enrich_with_embedding_similarity
# ---------------------------------------------------------------------------

def test_enrich_none_predicted_value_is_noop( wired_engine ):
    actual = { "value": "x" }
    pr = PredictionResult( response_type="open_ended", category="c", strategy="cold_start" )
    wired_engine._enrich_with_embedding_similarity( actual, pr, cfg.RESPONSE_TYPE_OPEN_ENDED )
    assert "_embedding_similarity" not in actual


def test_enrich_open_ended_injects_similarity( wired_engine, monkeypatch ):
    monkeypatch.setattr( wired_engine, "_generate_embedding", lambda t: [ 1.0, 0.0 ] )
    actual = { "value": "go ahead" }
    pr = PredictionResult( response_type="open_ended", category="c", strategy="x", predicted_value="proceed" )
    wired_engine._enrich_with_embedding_similarity( actual, pr, cfg.RESPONSE_TYPE_OPEN_ENDED )
    assert actual[ "_embedding_similarity" ] == pytest.approx( 1.0 )


def test_enrich_open_ended_empty_text_is_noop( wired_engine ):
    actual = { "value": "" }
    pr = PredictionResult( response_type="open_ended", category="c", strategy="x", predicted_value="proceed" )
    wired_engine._enrich_with_embedding_similarity( actual, pr, cfg.RESPONSE_TYPE_OPEN_ENDED )
    assert "_embedding_similarity" not in actual


def test_enrich_batch_injects_per_header( wired_engine, monkeypatch ):
    monkeypatch.setattr( wired_engine, "_generate_embedding", lambda t: [ 1.0, 0.0 ] )
    actual = { "answers": { "Topic": "ai", "Empty": "" } }
    pr = PredictionResult(
        response_type="open_ended_batch", category="c", strategy="x",
        predicted_value={ "answers": { "Topic": "AI", "Empty": "" } },
    )
    wired_engine._enrich_with_embedding_similarity( actual, pr, cfg.RESPONSE_TYPE_OPEN_ENDED_BATCH )
    # Topic compared; Empty skipped (empty actual text).
    assert "Topic" in actual[ "_embedding_similarity" ]
    assert "Empty" not in actual[ "_embedding_similarity" ]


def test_enrich_batch_empty_answers_is_noop( wired_engine ):
    actual = { "answers": {} }
    pr = PredictionResult(
        response_type="open_ended_batch", category="c", strategy="x",
        predicted_value={ "answers": { "T": "x" } },
    )
    wired_engine._enrich_with_embedding_similarity( actual, pr, cfg.RESPONSE_TYPE_OPEN_ENDED_BATCH )
    assert "_embedding_similarity" not in actual


def test_enrich_swallows_exceptions( wired_engine, monkeypatch ):
    def boom( t ):
        raise RuntimeError( "embed-fail" )
    monkeypatch.setattr( wired_engine, "_generate_embedding", boom )
    wired_engine.debug = True
    actual = { "value": "go" }
    pr = PredictionResult( response_type="open_ended", category="c", strategy="x", predicted_value="p" )
    # Should not raise.
    wired_engine._enrich_with_embedding_similarity( actual, pr, cfg.RESPONSE_TYPE_OPEN_ENDED )


# ---------------------------------------------------------------------------
# _generate_embedding / _generate_embedding_via_http
# ---------------------------------------------------------------------------

def test_generate_embedding_empty_returns_none( engine ):
    assert engine._generate_embedding( "   " ) is None


def test_generate_embedding_local_provider( engine ):
    engine._embedding_provider = FakeProvider( vector=[ 1.0, 2.0 ] )
    assert engine._generate_embedding( "text" ) == [ 1.0, 2.0 ]


def test_generate_embedding_local_fails_then_http( engine, monkeypatch ):
    engine._embedding_provider = FakeProvider( raise_on_generate=True )
    monkeypatch.setattr( engine, "_generate_embedding_via_http", lambda t: [ 9.0 ] )
    engine.debug = True
    assert engine._generate_embedding( "text" ) == [ 9.0 ]


def test_generate_embedding_no_provider_uses_http( engine, monkeypatch ):
    monkeypatch.setattr( engine, "_get_embedding_provider", lambda: None )
    monkeypatch.setattr( engine, "_generate_embedding_via_http", lambda t: [ 7.0 ] )
    engine.debug = True
    assert engine._generate_embedding( "text" ) == [ 7.0 ]


def test_http_embedding_no_api_key( engine, monkeypatch ):
    monkeypatch.setattr( "cosa.utils.util.get_api_key", lambda name: "" )
    engine.debug = True
    assert engine._generate_embedding_via_http( "text" ) is None


def test_http_embedding_success( engine, monkeypatch ):
    monkeypatch.setattr( "cosa.utils.util.get_api_key", lambda name: "KEY" )

    class FakeResp:
        status_code = 200
        def json( self ):
            return { "embedding": [ 0.1, 0.2 ] }

    monkeypatch.setattr( "requests.post", lambda *a, **k: FakeResp() )
    assert engine._generate_embedding_via_http( "text" ) == [ 0.1, 0.2 ]


def test_http_embedding_non_200( engine, monkeypatch ):
    monkeypatch.setattr( "cosa.utils.util.get_api_key", lambda name: "KEY" )

    class FakeResp:
        status_code = 500
        text = "server error"

    monkeypatch.setattr( "requests.post", lambda *a, **k: FakeResp() )
    engine.debug = True
    assert engine._generate_embedding_via_http( "text" ) is None


def test_http_embedding_request_exception( engine, monkeypatch ):
    monkeypatch.setattr( "cosa.utils.util.get_api_key", lambda name: "KEY" )
    def boom( *a, **k ):
        raise RuntimeError( "conn-refused" )
    monkeypatch.setattr( "requests.post", boom )
    engine.debug = True
    assert engine._generate_embedding_via_http( "text" ) is None


# ---------------------------------------------------------------------------
# record_outcome / _store_decision / get_accuracy_summary  (DB-mocked)
# ---------------------------------------------------------------------------

class _FakeSession:
    def __init__( self ):
        self.committed = False
    def commit( self ):
        self.committed = True


class _FakeDbCtx:
    """Context-manager stand-in for get_db()."""
    def __init__( self, session ):
        self._session = session
    def __enter__( self ):
        return self._session
    def __exit__( self, *exc ):
        return False


class _FakeRepo:
    def __init__( self, session ):
        self.session = session
        self.logged  = None
        self.outcome = None
    def log_prediction( self, **kwargs ):
        self.logged = kwargs
    def update_outcome( self, **kwargs ):
        self.outcome = kwargs
    def get_accuracy_summary( self, **kwargs ):
        return { "total_predictions": 3, "accuracy_rate": 0.66, "kwargs": kwargs }


def _patch_db( monkeypatch, session, repo_holder ):
    monkeypatch.setattr( "cosa.rest.db.database.get_db", lambda: _FakeDbCtx( session ) )
    def make_repo( s ):
        repo = _FakeRepo( s )
        repo_holder.append( repo )
        return repo
    monkeypatch.setattr(
        "cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository",
        make_repo,
    )


def test_record_outcome_happy_path_writes_and_stores( wired_engine, monkeypatch ):
    session = _FakeSession()
    repos   = []
    _patch_db( monkeypatch, session, repos )
    stored = []
    monkeypatch.setattr( wired_engine, "_store_decision", lambda *a: stored.append( a ) )
    pr = PredictionResult(
        response_type="yes_no", category="permission", strategy="cbr_majority_vote",
        predicted_value="yes", confidence=0.8, similar_case_count=2,
    )
    wired_engine.debug = True
    wired_engine.record_outcome( "notif-1", pr, "yes", "yes_no" )
    assert session.committed is True
    assert repos[ 0 ].logged[ "notification_id" ] == "notif-1"
    assert repos[ 0 ].outcome[ "accuracy_match" ] is True
    assert stored                                   # _store_decision invoked


def test_record_outcome_open_ended_enriches( wired_engine, monkeypatch ):
    session = _FakeSession()
    repos   = []
    _patch_db( monkeypatch, session, repos )
    monkeypatch.setattr( wired_engine, "_store_decision", lambda *a: None )
    enriched = []
    monkeypatch.setattr(
        wired_engine, "_enrich_with_embedding_similarity",
        lambda actual, pr, rt: enriched.append( rt ),
    )
    pr = PredictionResult( response_type="open_ended", category="c", strategy="x", predicted_value="hi" )
    wired_engine.record_outcome( "n2", pr, "hi", cfg.RESPONSE_TYPE_OPEN_ENDED )
    assert enriched == [ cfg.RESPONSE_TYPE_OPEN_ENDED ]


def test_record_outcome_normalizes_non_str_non_dict_actual( wired_engine, monkeypatch ):
    session = _FakeSession()
    repos   = []
    _patch_db( monkeypatch, session, repos )
    monkeypatch.setattr( wired_engine, "_store_decision", lambda *a: None )
    pr = PredictionResult( response_type="yes_no", category="c", strategy="x", predicted_value="42" )
    wired_engine.record_outcome( "n3", pr, 42, "yes_no" )      # int actual → str-wrapped
    assert repos[ 0 ].outcome[ "actual_value" ] == { "value": "42" }


def test_record_outcome_swallows_exception( wired_engine, monkeypatch ):
    monkeypatch.setattr( "cosa.rest.db.database.get_db", lambda: ( _ for _ in () ).throw( RuntimeError( "db-down" ) ) )
    wired_engine.debug = True
    pr = PredictionResult( response_type="yes_no", category="c", strategy="x", predicted_value="yes" )
    # Must not raise.
    wired_engine.record_outcome( "n4", pr, "yes", "yes_no" )


def test_record_outcome_strips_transient_keys( wired_engine, monkeypatch ):
    """Transient _-prefixed keys are stripped from the DB actual_value."""
    session = _FakeSession()
    repos   = []
    _patch_db( monkeypatch, session, repos )
    monkeypatch.setattr( wired_engine, "_store_decision", lambda *a: None )
    # Inject a transient key via a fake enrich.
    monkeypatch.setattr(
        wired_engine, "_enrich_with_embedding_similarity",
        lambda actual, pr, rt: actual.__setitem__( "_embedding_similarity", 0.9 ),
    )
    pr = PredictionResult( response_type="open_ended", category="c", strategy="x", predicted_value="hi" )
    wired_engine.record_outcome( "n5", pr, { "value": "hi" }, cfg.RESPONSE_TYPE_OPEN_ENDED )
    assert "_embedding_similarity" not in repos[ 0 ].outcome[ "actual_value" ]


def test_store_decision_no_store_or_provider_returns( wired_engine, monkeypatch ):
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: None )
    pr = PredictionResult( response_type="yes_no", category="c", strategy="x",
                           predicted_value="yes", metadata={ "original_message": "m" } )
    # Should simply return without raising.
    wired_engine._store_decision( "n", pr, "yes", "yes_no" )


def test_store_decision_no_message_returns( wired_engine, monkeypatch ):
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: FakeStore() )
    monkeypatch.setattr( wired_engine, "_get_embedding_provider", lambda: FakeProvider() )
    pr = PredictionResult( response_type="yes_no", category="c", strategy="x",
                           predicted_value="yes", metadata={} )
    wired_engine._store_decision( "n", pr, "yes", "yes_no" )   # no original_message → return


def test_store_decision_yes_no_string_value( wired_engine, monkeypatch ):
    store = FakeStore()
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: store )
    monkeypatch.setattr( wired_engine, "_get_embedding_provider", lambda: FakeProvider() )
    pr = PredictionResult( response_type="yes_no", category="permission", strategy="x",
                           predicted_value="yes", metadata={ "original_message": "Should I?" } )
    wired_engine._store_decision( "n", pr, "yes", "yes_no" )
    assert store.added[ 0 ][ "decision_value" ] == "yes"
    assert store.added[ 0 ][ "question" ] == "Should I?"


def test_store_decision_mc_string_with_answers( wired_engine, monkeypatch ):
    store = FakeStore()
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: store )
    monkeypatch.setattr( wired_engine, "_get_embedding_provider", lambda: FakeProvider() )
    pr = PredictionResult( response_type="multiple_choice", category="c", strategy="x",
                           predicted_value={}, metadata={ "original_message": "q" } )
    actual = json.dumps( { "answers": { "Commit": "Commit only" } } )
    wired_engine._store_decision( "n", pr, actual, "multiple_choice" )
    assert json.loads( store.added[ 0 ][ "decision_value" ] ) == { "answers": { "Commit": "Commit only" } }


def test_store_decision_mc_string_valid_json_without_answers_wraps_other( wired_engine, monkeypatch ):
    """Valid JSON string lacking an 'answers' key → wrapped under _other (the in-try else arm)."""
    store = FakeStore()
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: store )
    monkeypatch.setattr( wired_engine, "_get_embedding_provider", lambda: FakeProvider() )
    pr = PredictionResult( response_type="multiple_choice", category="c", strategy="x",
                           predicted_value={}, metadata={ "original_message": "q" } )
    wired_engine._store_decision( "n", pr, '{"foo": 1}', "multiple_choice" )
    assert json.loads( store.added[ 0 ][ "decision_value" ] ) == { "answers": { "_other": '{"foo": 1}' } }


def test_store_decision_mc_string_bad_json_wraps_other( wired_engine, monkeypatch ):
    store = FakeStore()
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: store )
    monkeypatch.setattr( wired_engine, "_get_embedding_provider", lambda: FakeProvider() )
    pr = PredictionResult( response_type="multiple_choice", category="c", strategy="x",
                           predicted_value={}, metadata={ "original_message": "q" } )
    wired_engine._store_decision( "n", pr, "{bad json", "multiple_choice" )
    assert json.loads( store.added[ 0 ][ "decision_value" ] ) == { "answers": { "_other": "{bad json" } }


def test_store_decision_dict_with_answers( wired_engine, monkeypatch ):
    store = FakeStore()
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: store )
    monkeypatch.setattr( wired_engine, "_get_embedding_provider", lambda: FakeProvider() )
    pr = PredictionResult( response_type="open_ended_batch", category="c", strategy="x",
                           predicted_value={}, metadata={ "original_message": "q" } )
    wired_engine._store_decision( "n", pr, { "answers": { "T": "x" } }, "open_ended_batch" )
    assert json.loads( store.added[ 0 ][ "decision_value" ] ) == { "answers": { "T": "x" } }


def test_store_decision_dict_with_value( wired_engine, monkeypatch ):
    store = FakeStore()
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: store )
    monkeypatch.setattr( wired_engine, "_get_embedding_provider", lambda: FakeProvider() )
    pr = PredictionResult( response_type="open_ended", category="c", strategy="x",
                           predicted_value="", metadata={ "original_message": "q" } )
    wired_engine._store_decision( "n", pr, { "value": "snake_case" }, "open_ended" )
    assert store.added[ 0 ][ "decision_value" ] == "snake_case"


def test_store_decision_dict_empty_falls_back_to_str( wired_engine, monkeypatch ):
    store = FakeStore()
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: store )
    monkeypatch.setattr( wired_engine, "_get_embedding_provider", lambda: FakeProvider() )
    pr = PredictionResult( response_type="open_ended", category="c", strategy="x",
                           predicted_value="", metadata={ "original_message": "q" } )
    wired_engine._store_decision( "n", pr, { "meta": 1 }, "open_ended" )
    assert store.added[ 0 ][ "decision_value" ] == str( { "meta": 1 } )


def test_store_decision_non_str_non_dict_actual( wired_engine, monkeypatch ):
    store = FakeStore()
    monkeypatch.setattr( wired_engine, "_get_embedding_store", lambda: store )
    monkeypatch.setattr( wired_engine, "_get_embedding_provider", lambda: FakeProvider() )
    pr = PredictionResult( response_type="open_ended", category="c", strategy="x",
                           predicted_value="", metadata={ "original_message": "q" } )
    wired_engine._store_decision( "n", pr, 99, "open_ended" )
    assert store.added[ 0 ][ "decision_value" ] == "99"


def test_store_decision_swallows_exception( wired_engine, monkeypatch ):
    def boom():
        raise RuntimeError( "store-fail" )
    monkeypatch.setattr( wired_engine, "_get_embedding_store", boom )
    wired_engine.debug = True
    pr = PredictionResult( response_type="yes_no", category="c", strategy="x",
                           predicted_value="yes", metadata={ "original_message": "m" } )
    wired_engine._store_decision( "n", pr, "yes", "yes_no" )   # must not raise


def test_get_accuracy_summary_success( wired_engine, monkeypatch ):
    session = _FakeSession()
    repos   = []
    _patch_db( monkeypatch, session, repos )
    out = wired_engine.get_accuracy_summary( window_days=7, category="permission", response_type="yes_no" )
    assert out[ "total_predictions" ] == 3
    assert out[ "kwargs" ][ "window_days" ] == 7


def test_get_accuracy_summary_exception_returns_error_dict( wired_engine, monkeypatch ):
    monkeypatch.setattr( "cosa.rest.db.database.get_db", lambda: ( _ for _ in () ).throw( RuntimeError( "db-down" ) ) )
    wired_engine.debug = True
    out = wired_engine.get_accuracy_summary( window_days=14 )
    assert out[ "total_predictions" ] == 0
    assert out[ "accuracy_rate" ] == 0.0
    assert "db-down" in out[ "error" ]
