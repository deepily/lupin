"""
Unit tests for cosa.agents.prediction_engine.accuracy_comparators.

The comparators measure prediction accuracy per response-type, each returning
(match, detail). Tests cover the real public surface + every branch:

    - compare_yes_no: match / mismatch / None / actual-qualifier / predicted+actual
      qualifier, plus _extract_binary and _extract_qualifier edge arcs,
    - compare_multiple_choice_single: full match / partial (mismatches list) / None /
      empty_answers,
    - compare_multiple_choice_multi: Jaccard below+above threshold / None / empty_answers /
      scalar-option normalization / empty-union (len(union)==0 else arm),
    - compare_open_ended: embedding-similarity path (match+below) / exact-match fallback /
      None,
    - compare_open_ended_batch: embedding per-header / exact fallback / partial-embedding
      (header missing from sims) / None / empty_answers,
    - get_comparator: yes_no / multiple_choice single default / data-driven multi-select
      detection / no-actual backward-compat / open_ended_batch / unknown→open_ended.

`quick_smoke_test` is coverage-excluded (house style); its 14 cases are harvested here.

Authored by Rachel 🕊️ for the CoSA 100% coverage campaign (prediction_engine group).
"""

from cosa.agents.prediction_engine.accuracy_comparators import (
    compare_yes_no,
    compare_multiple_choice_single,
    compare_multiple_choice_multi,
    compare_open_ended,
    compare_open_ended_batch,
    get_comparator,
    _extract_binary,
    _extract_qualifier,
)
from cosa.agents.prediction_engine.config import (
    RESPONSE_TYPE_YES_NO,
    RESPONSE_TYPE_MULTIPLE_CHOICE,
    RESPONSE_TYPE_OPEN_ENDED,
    RESPONSE_TYPE_OPEN_ENDED_BATCH,
)


# ---- compare_yes_no -------------------------------------------------------

def test_yes_no_match():
    match, detail = compare_yes_no( { "value": "yes" }, { "value": "yes" } )
    assert match is True
    assert detail[ "predicted_binary" ] == "yes" and detail[ "actual_binary" ] == "yes"


def test_yes_no_mismatch():
    match, _ = compare_yes_no( { "value": "yes" }, { "value": "no" } )
    assert match is False


def test_yes_no_none_returns_missing_data():
    match, detail = compare_yes_no( None, { "value": "yes" } )
    assert match is None and detail == { "reason": "missing_data" }


def test_yes_no_actual_qualifier_extracted():
    match, detail = compare_yes_no( { "value": "yes" }, { "value": "yes [comment: only the old ones]" } )
    assert match is True
    assert detail[ "actual_qualifier" ] == "only the old ones"
    assert "predicted_qualifier" not in detail


def test_yes_no_predicted_and_actual_qualifiers():
    match, detail = compare_yes_no(
        { "value": "yes", "qualifier": "only the March ones" },
        { "value": "yes [comment: only the old ones]" },
    )
    assert match is True
    assert detail[ "predicted_qualifier" ] == "only the March ones"
    assert detail[ "actual_qualifier" ] == "only the old ones"


# ---- _extract_binary / _extract_qualifier edge arcs -----------------------

def test_extract_binary_arcs():
    assert _extract_binary( "" ) == ""                       # empty guard
    assert _extract_binary( "YES please" ) == "yes"          # startswith yes
    assert _extract_binary( "Nope" ) == "no"                 # startswith no
    assert _extract_binary( "maybe later" ) == "maybe later" # neither → lowered passthrough


def test_extract_qualifier_arcs():
    assert _extract_qualifier( "" ) is None                          # empty guard
    assert _extract_qualifier( "yes, sure" ) is None                 # no marker
    assert _extract_qualifier( "yes [comment: only March]" ) == "only March"   # closed marker
    assert _extract_qualifier( "yes [comment: unterminated" ) == "unterminated"  # no closing ]


# ---- compare_multiple_choice_single ---------------------------------------

def test_mc_single_match():
    match, _ = compare_multiple_choice_single(
        { "answers": { "Database": "PostgreSQL" } }, { "answers": { "Database": "PostgreSQL" } },
    )
    assert match is True


def test_mc_single_partial_records_mismatches():
    match, detail = compare_multiple_choice_single(
        { "answers": { "DB": "MySQL", "Cache": "Redis" } },
        { "answers": { "DB": "PostgreSQL", "Cache": "Redis" } },
    )
    assert match is False
    assert detail[ "matches" ] == 1 and detail[ "total" ] == 2
    assert detail[ "mismatches" ][ 0 ][ "header" ] == "DB"


def test_mc_single_none():
    match, detail = compare_multiple_choice_single( None, { "answers": {} } )
    assert match is None and detail == { "reason": "missing_data" }


def test_mc_single_empty_answers():
    match, detail = compare_multiple_choice_single( { "answers": {} }, { "answers": { "DB": "PG" } } )
    assert match is None and detail == { "reason": "empty_answers" }


# ---- compare_multiple_choice_multi (Jaccard) ------------------------------

def test_mc_multi_below_threshold():
    match, detail = compare_multiple_choice_multi(
        { "answers": { "Features": [ "Auth", "Caching" ] } },
        { "answers": { "Features": [ "Auth", "Logging" ] } },
    )
    assert match is False                    # Jaccard 1/3 < 0.5
    assert detail[ "avg_jaccard" ] < 0.5


def test_mc_multi_above_threshold():
    match, detail = compare_multiple_choice_multi(
        { "answers": { "Features": [ "Auth", "Caching" ] } },
        { "answers": { "Features": [ "Auth", "Caching" ] } },
    )
    assert match is True                     # Jaccard 1.0 >= 0.5
    assert detail[ "avg_jaccard" ] == 1.0


def test_mc_multi_none():
    match, detail = compare_multiple_choice_multi( None, None )
    assert match is None and detail == { "reason": "missing_data" }


def test_mc_multi_empty_answers():
    match, detail = compare_multiple_choice_multi( { "answers": {} }, { "answers": { "F": [ "A" ] } } )
    assert match is None and detail == { "reason": "empty_answers" }


def test_mc_multi_scalar_option_normalized_to_set():
    """A non-list option value is normalized to a singleton set (the isinstance else arms)."""
    match, detail = compare_multiple_choice_multi(
        { "answers": { "DB": "PG" } }, { "answers": { "DB": "PG" } },
    )
    assert match is True
    assert detail[ "header_scores" ][ "DB" ][ "jaccard" ] == 1.0


def test_mc_multi_empty_union_yields_zero_jaccard():
    """Both header option-sets empty → len(union)==0 → jaccard 0.0 (the else arm)."""
    match, detail = compare_multiple_choice_multi(
        { "answers": { "F": [] } }, { "answers": { "F": [] } },
    )
    assert match is False
    assert detail[ "header_scores" ][ "F" ][ "jaccard" ] == 0.0


# ---- compare_open_ended ---------------------------------------------------

def test_open_ended_embedding_match():
    match, detail = compare_open_ended(
        { "value": "proceed with deployment" },
        { "value": "go ahead with deployment", "_embedding_similarity": 0.92 },
    )
    assert match is True
    assert detail[ "method" ] == "embedding_similarity" and detail[ "similarity" ] == 0.92


def test_open_ended_embedding_below_threshold():
    match, detail = compare_open_ended(
        { "value": "proceed" }, { "value": "cancel", "_embedding_similarity": 0.30 },
    )
    assert match is False
    assert detail[ "method" ] == "embedding_similarity"


def test_open_ended_exact_match_fallback():
    match, detail = compare_open_ended( { "value": "Proceed" }, { "value": "proceed" } )
    assert match is True
    assert detail[ "method" ] == "exact_match"


def test_open_ended_none():
    match, detail = compare_open_ended( None, { "value": "x" } )
    assert match is None and detail == { "reason": "missing_data" }


# ---- compare_open_ended_batch ---------------------------------------------

def test_open_ended_batch_embedding_match():
    match, detail = compare_open_ended_batch(
        { "answers": { "Topic": "quantum computing", "Budget": "no limit" } },
        { "answers": { "Topic": "quantum computing", "Budget": "no limit" },
          "_embedding_similarity": { "Topic": 0.95, "Budget": 0.90 } },
    )
    assert match is True
    assert detail[ "avg_similarity" ] >= 0.85


def test_open_ended_batch_exact_fallback():
    """No _embedding_similarity → per-header exact match (use_embedding False arm)."""
    match, detail = compare_open_ended_batch(
        { "answers": { "Topic": "AI" } }, { "answers": { "Topic": "ai" } },
    )
    assert match is True
    assert detail[ "header_details" ][ "Topic" ][ "method" ] == "exact_match"


def test_open_ended_batch_partial_embedding_falls_back_per_header():
    """A header absent from the sims dict falls back to exact match for THAT header."""
    match, detail = compare_open_ended_batch(
        { "answers": { "A": "alpha", "B": "beta" } },
        { "answers": { "A": "alpha", "B": "beta" }, "_embedding_similarity": { "A": 0.99 } },
    )
    assert detail[ "header_details" ][ "A" ][ "method" ] == "embedding_similarity"
    assert detail[ "header_details" ][ "B" ][ "method" ] == "exact_match"
    assert match is True


def test_open_ended_batch_none():
    match, detail = compare_open_ended_batch( None, {} )
    assert match is None and detail == { "reason": "missing_data" }


def test_open_ended_batch_empty_answers():
    match, detail = compare_open_ended_batch( { "answers": {} }, { "answers": { "A": "x" } } )
    assert match is None and detail == { "reason": "empty_answers" }


# ---- get_comparator dispatch ----------------------------------------------

def test_get_comparator_yes_no():
    assert get_comparator( RESPONSE_TYPE_YES_NO ) is compare_yes_no


def test_get_comparator_unknown_falls_back_to_open_ended():
    assert get_comparator( "totally_unknown" ) is compare_open_ended


def test_get_comparator_open_ended_batch():
    assert get_comparator( RESPONSE_TYPE_OPEN_ENDED_BATCH ) is compare_open_ended_batch


def test_get_comparator_open_ended():
    assert get_comparator( RESPONSE_TYPE_OPEN_ENDED ) is compare_open_ended


def test_get_comparator_multiple_choice_single_default():
    """multiple_choice with no actual_value → single-select comparator (backward compat)."""
    assert get_comparator( RESPONSE_TYPE_MULTIPLE_CHOICE ) is compare_multiple_choice_single


def test_get_comparator_multiple_choice_detects_multi_select():
    """A list-valued answer in actual_value routes to the multi-select comparator."""
    comp = get_comparator( RESPONSE_TYPE_MULTIPLE_CHOICE, actual_value={ "answers": { "F": [ "A", "B" ] } } )
    assert comp is compare_multiple_choice_multi


def test_get_comparator_multiple_choice_single_value_actual():
    """A scalar-valued answer in actual_value keeps the single-select comparator."""
    comp = get_comparator( RESPONSE_TYPE_MULTIPLE_CHOICE, actual_value={ "answers": { "DB": "PG" } } )
    assert comp is compare_multiple_choice_single


def test_get_comparator_multiple_choice_non_dict_actual():
    """A non-dict actual_value can't carry multi-select hints → single-select."""
    comp = get_comparator( RESPONSE_TYPE_MULTIPLE_CHOICE, actual_value="not-a-dict" )
    assert comp is compare_multiple_choice_single
