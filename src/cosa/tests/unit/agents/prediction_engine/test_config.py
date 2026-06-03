"""
Unit tests for cosa.agents.prediction_engine.config.

config.py is a pure constants module (no functions, no branches). The tests lock
the *contract* the rest of the package — and, for the RESPONSE_TYPE_* identifiers,
the cosa-voice MCP server — depends on:

    - the five STRATEGY_* names are distinct non-empty strings (used as enum-like
      discriminators in PredictionResult.strategy + engine dispatch),
    - the four RESPONSE_TYPE_* identifiers equal the exact protocol strings the
      cosa-voice MCP server emits (a cross-process contract, NOT a tautology —
      a drift here silently breaks comparator dispatch),
    - every threshold/top-k default sits in its documented numeric range.

These are change-detectors *by design* for protocol-coupled values: the literal
IS the contract.

Authored by Rachel 🕊️ for the CoSA 100% coverage campaign (prediction_engine group).
"""

from cosa.agents.prediction_engine import config


def test_strategy_constants_are_distinct_nonempty_strings():
    """STRATEGY_* are enum-like discriminators → must be unique, non-empty strings."""
    strategies = [
        config.STRATEGY_CBR_MAJORITY,
        config.STRATEGY_CBR_RETRIEVAL,
        config.STRATEGY_LLM_SYNTHESIS,
        config.STRATEGY_OPTION_SCORING,
        config.STRATEGY_COLD_START,
    ]
    assert all( isinstance( s, str ) and s for s in strategies )
    assert len( set( strategies ) ) == len( strategies )


def test_response_type_identifiers_match_cosa_voice_protocol():
    """RESPONSE_TYPE_* are a cross-process contract with the cosa-voice MCP server."""
    assert config.RESPONSE_TYPE_YES_NO           == "yes_no"
    assert config.RESPONSE_TYPE_MULTIPLE_CHOICE  == "multiple_choice"
    assert config.RESPONSE_TYPE_OPEN_ENDED       == "open_ended"
    assert config.RESPONSE_TYPE_OPEN_ENDED_BATCH == "open_ended_batch"
    # The four identifiers are distinct.
    assert len( {
        config.RESPONSE_TYPE_YES_NO, config.RESPONSE_TYPE_MULTIPLE_CHOICE,
        config.RESPONSE_TYPE_OPEN_ENDED, config.RESPONSE_TYPE_OPEN_ENDED_BATCH,
    } ) == 4


def test_thresholds_are_floats_in_unit_interval():
    """Similarity/confidence thresholds are probabilities → 0.0 <= t <= 1.0."""
    for t in (
        config.DEFAULT_CBR_SIMILARITY_THRESHOLD,
        config.DEFAULT_CONFIDENCE_THRESHOLD,
        config.DEFAULT_OPEN_ENDED_CBR_THRESHOLD,
        config.OPEN_ENDED_SIMILARITY_THRESHOLD,
        config.MULTI_SELECT_JACCARD_THRESHOLD,
    ):
        assert isinstance( t, float )
        assert 0.0 <= t <= 1.0


def test_top_k_defaults_are_positive_ints():
    """CBR top-k values index a retrieval window → positive integers."""
    assert isinstance( config.DEFAULT_CBR_TOP_K, int ) and config.DEFAULT_CBR_TOP_K > 0
    assert isinstance( config.DEFAULT_OPEN_ENDED_CBR_TOP_K, int ) and config.DEFAULT_OPEN_ENDED_CBR_TOP_K > 0


def test_feature_toggle_and_port_and_table_defaults():
    """Misc scalar defaults carry the documented types/shapes."""
    assert config.DEFAULT_ENABLED is True
    assert config.DEFAULT_DEBUG is False
    assert isinstance( config.DEFAULT_EMBEDDING_FALLBACK_PORT, int )
    assert config.DEFAULT_EMBEDDING_FALLBACK_PORT == 7999
    assert isinstance( config.DEFAULT_LANCEDB_TABLE, str ) and config.DEFAULT_LANCEDB_TABLE
    assert isinstance( config.DEFAULT_OPEN_ENDED_LLM_SPEC_KEY, str ) and config.DEFAULT_OPEN_ENDED_LLM_SPEC_KEY
