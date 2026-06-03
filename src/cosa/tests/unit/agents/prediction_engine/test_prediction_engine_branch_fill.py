"""
Branch-fill unit tests for cosa.agents.prediction_engine.prediction_engine.

Companion to test_prediction_engine.py: targets the residual branch arcs that the
main suite's happy/error paths don't traverse — the singleton double-checked-locking
race, the "no constraint needed" arms of MC option validation, the debug-OFF arms of
the two-tier OE/OEB deep paths, the embedding-enrichment skip/exit arcs, and the
provider-returns-None → HTTP-fallback arc. Each test names the exact arc it pins.

Authored by Rachel 🕊️ for the CoSA 100% coverage campaign (prediction_engine group).
"""

import json

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.prediction_result import PredictionResult
from cosa.agents.prediction_engine import config as cfg


class FakeStore:
    """find_similar returns canned cases; add_decision records."""
    def __init__( self, cases=None ):
        self._cases = cases or []
        self.added  = []
    def find_similar( self, **kwargs ):
        return self._cases
    def add_decision( self, **kwargs ):
        self.added.append( kwargs )


class FakeLlmClient:
    def __init__( self, response="" ):
        self._response = response
    def run( self, prompt ):
        return self._response


def _case( pct, **record ):
    return ( pct, record )


@pytest.fixture
def engine():
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    yield eng
    PredictionEngine.reset()


# ---- __new__ double-checked-locking race (74->77) -------------------------

def test_new_double_checked_locking_race( monkeypatch ):
    """Simulate a peer thread winning the race inside the lock → inner check is False."""
    PredictionEngine.reset()

    class Winner:
        _initialized = True            # so __init__ early-returns on it

    sentinel = Winner()

    class RacyLock:
        def __enter__( self ):
            # Another "thread" populated the singleton between the two None-checks.
            PredictionEngine._instance = sentinel
            return self
        def __exit__( self, *exc ):
            return False

    monkeypatch.setattr( PredictionEngine, "_lock", RacyLock() )
    try:
        result = PredictionEngine()
        assert result is sentinel      # __new__ returned the race-winner, took 74->77
    finally:
        PredictionEngine.reset()


# ---- MC single-select winner already valid (line 532) ---------------------

def test_mc_single_select_winner_valid_kept( engine, monkeypatch ):
    """Winner is a valid label → kept verbatim, constrained stays False."""
    cases = [ _case( 90.0, decision_value=json.dumps( { "answers": { "DB": "PostgreSQL" } } ) ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases ) )
    options = { "questions": [
        { "header": "DB", "multi_select": False, "options": [ { "label": "PostgreSQL" } ] },
    ] }
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.predicted_value == { "answers": { "DB": "PostgreSQL" } }
    assert r.metadata[ "constrained" ] is False


# ---- MC multi-select all-valid → no constraint (522->525) -----------------

def test_mc_multi_select_all_valid_no_constraint( engine, monkeypatch ):
    """All predicted labels valid → filtered == prediction → no constraint flag."""
    cases = [ _case( 88.0, decision_value=json.dumps( { "answers": { "Features": [ "Auth", "Caching" ] } } ) ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases ) )
    options = { "questions": [
        { "header": "Features", "multi_select": True,
          "options": [ { "label": "Auth" }, { "label": "Caching" } ] },
    ] }
    r = engine._predict_multiple_choice( "m", "approach", [ 0.1 ], options )
    assert r.predicted_value == { "answers": { "Features": [ "Auth", "Caching" ] } }
    assert r.metadata[ "constrained" ] is False


# ---- OE / OEB deep tiers with debug OFF (687->690, 721->724, 875->878, 912->915) ----

def test_open_ended_exact_match_debug_off( engine, monkeypatch ):
    cases = [ _case( 96.0, question="Q", decision_value="ans" ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases ) )
    r = engine._predict_open_ended( "q", "input", [ 0.1 ] )      # debug False
    assert r.strategy == cfg.STRATEGY_CBR_RETRIEVAL


def test_open_ended_synthesis_debug_off( engine, monkeypatch ):
    cases = [ _case( 90.0, question="other", decision_value="prior" ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases ) )
    monkeypatch.setattr( engine, "_build_synthesis_prompt", lambda m, c: "P" )
    xml = "<open_ended_synthesis_response><predicted_answer>x</predicted_answer>" \
          "<reasoning>r</reasoning><confidence>0.7</confidence></open_ended_synthesis_response>"
    monkeypatch.setattr( engine, "_get_llm_client", lambda: FakeLlmClient( xml ) )
    r = engine._predict_open_ended( "new", "input", [ 0.1 ] )    # debug False
    assert r.strategy == cfg.STRATEGY_LLM_SYNTHESIS


def test_open_ended_batch_exact_match_debug_off( engine, monkeypatch ):
    dv = json.dumps( { "answers": { "T": "x" } } )
    cases = [ _case( 99.0, question="Q", decision_value=dv ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases ) )
    r = engine._predict_open_ended_batch( "q", "input", [ 0.1 ] )    # debug False
    assert r.strategy == cfg.STRATEGY_CBR_RETRIEVAL


def test_open_ended_batch_synthesis_debug_off( engine, monkeypatch ):
    cases = [ _case( 90.0, question="other", decision_value="prior" ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases ) )
    monkeypatch.setattr( engine, "_build_synthesis_prompt", lambda m, c: "P" )
    answer = json.dumps( { "answers": { "T": "ML" } } )
    xml = f"<open_ended_synthesis_response><predicted_answer>{answer}</predicted_answer>" \
          "<reasoning>r</reasoning><confidence>0.6</confidence></open_ended_synthesis_response>"
    monkeypatch.setattr( engine, "_get_llm_client", lambda: FakeLlmClient( xml ) )
    r = engine._predict_open_ended_batch( "new", "input", [ 0.1 ] )  # debug False
    assert r.strategy == cfg.STRATEGY_LLM_SYNTHESIS


# ---- OEB client unavailable → RuntimeError → fallback (line 899) -----------

def test_open_ended_batch_client_none_raises_then_fallback( engine, monkeypatch ):
    dv = json.dumps( { "answers": { "T": "x" } } )
    cases = [ _case( 90.0, question="other", decision_value=dv ) ]
    monkeypatch.setattr( engine, "_get_embedding_store", lambda: FakeStore( cases ) )
    monkeypatch.setattr( engine, "_build_synthesis_prompt", lambda m, c: "P" )
    monkeypatch.setattr( engine, "_get_llm_client", lambda: None )   # → RuntimeError → fallback
    r = engine._predict_open_ended_batch( "new", "input", [ 0.1 ] )
    assert r.strategy == cfg.STRATEGY_CBR_RETRIEVAL
    assert r.metadata[ "tier" ] == "llm_fallback"
    assert "LLM client unavailable" in r.metadata[ "llm_error" ]


# ---- _enrich skip/exit arcs (1047->exit, 1051->exit, 1070->1060, 1073->exit) ----

def test_enrich_open_ended_embedding_none_skips_injection( engine, monkeypatch ):
    """pred_emb None → the AND guard is False → no injection (1047->exit)."""
    monkeypatch.setattr( engine, "_generate_embedding", lambda t: None )
    actual = { "value": "go" }
    pr = PredictionResult( response_type="open_ended", category="c", strategy="x", predicted_value="p" )
    engine._enrich_with_embedding_similarity( actual, pr, cfg.RESPONSE_TYPE_OPEN_ENDED )
    assert "_embedding_similarity" not in actual


def test_enrich_unknown_response_type_is_noop( engine ):
    """A response_type that is neither OE nor OEB falls through both arms (1051->exit)."""
    actual = { "value": "go" }
    pr = PredictionResult( response_type="yes_no", category="c", strategy="x", predicted_value="yes" )
    engine._enrich_with_embedding_similarity( actual, pr, "yes_no" )
    assert "_embedding_similarity" not in actual


def test_enrich_batch_all_headers_skip_no_sims( engine, monkeypatch ):
    """Every header's embedding is None → continue (1070->1060) and no sims (1073->exit)."""
    monkeypatch.setattr( engine, "_generate_embedding", lambda t: None )
    actual = { "answers": { "Topic": "ai" } }
    pr = PredictionResult(
        response_type="open_ended_batch", category="c", strategy="x",
        predicted_value={ "answers": { "Topic": "AI" } },
    )
    engine._enrich_with_embedding_similarity( actual, pr, cfg.RESPONSE_TYPE_OPEN_ENDED_BATCH )
    assert "_embedding_similarity" not in actual


# ---- _generate_embedding: provider returns None → HTTP fallback (1301->1307) ----

def test_generate_embedding_provider_returns_none_uses_http( engine, monkeypatch ):
    class NoneProvider:
        def generate_embedding( self, text, content_type="prose" ):
            return None
    engine._embedding_provider = NoneProvider()
    monkeypatch.setattr( engine, "_generate_embedding_via_http", lambda t: [ 3.0 ] )
    assert engine._generate_embedding( "text" ) == [ 3.0 ]
