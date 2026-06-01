"""
Unit tests for prediction_engine/config.py.

config.py is a flat module of default constants ( no logic, no branches ).
These tests pin the documented public contract — the exact default values
that the engine falls back to when an INI key is missing — so a silent
default-drift is caught.

Coverage target: 100% lines + branches + functions ( trivially, the module
is constant assignments only ).
"""
import cosa.agents.prediction_engine.config as cfg


def test_feature_toggle_defaults():
    assert cfg.DEFAULT_ENABLED is True
    assert cfg.DEFAULT_DEBUG   is False


def test_cbr_parameter_defaults():
    assert cfg.DEFAULT_CBR_TOP_K              == 5
    assert cfg.DEFAULT_CBR_SIMILARITY_THRESHOLD == 0.75
    assert cfg.DEFAULT_CONFIDENCE_THRESHOLD   == 0.60


def test_embedding_and_lancedb_defaults():
    assert cfg.DEFAULT_EMBEDDING_FALLBACK_PORT == 7999
    assert cfg.DEFAULT_LANCEDB_TABLE           == "prediction_decisions"


def test_open_ended_llm_defaults():
    assert cfg.DEFAULT_OPEN_ENDED_CBR_TOP_K     == 5
    assert cfg.DEFAULT_OPEN_ENDED_CBR_THRESHOLD == 0.85
    assert cfg.DEFAULT_OPEN_ENDED_LLM_SPEC_KEY  == "kaitchup/phi_4_14b"


def test_strategy_constants_are_distinct():
    strategies = {
        cfg.STRATEGY_CBR_MAJORITY,
        cfg.STRATEGY_CBR_RETRIEVAL,
        cfg.STRATEGY_LLM_SYNTHESIS,
        cfg.STRATEGY_OPTION_SCORING,
        cfg.STRATEGY_COLD_START,
    }
    # five distinct strategy identifiers
    assert len( strategies ) == 5
    assert cfg.STRATEGY_CBR_MAJORITY == "cbr_majority_vote"
    assert cfg.STRATEGY_COLD_START   == "cold_start"


def test_accuracy_thresholds():
    assert cfg.OPEN_ENDED_SIMILARITY_THRESHOLD == 0.85
    assert cfg.MULTI_SELECT_JACCARD_THRESHOLD  == 0.50


def test_response_type_identifiers():
    assert cfg.RESPONSE_TYPE_YES_NO           == "yes_no"
    assert cfg.RESPONSE_TYPE_MULTIPLE_CHOICE  == "multiple_choice"
    assert cfg.RESPONSE_TYPE_OPEN_ENDED       == "open_ended"
    assert cfg.RESPONSE_TYPE_OPEN_ENDED_BATCH == "open_ended_batch"
