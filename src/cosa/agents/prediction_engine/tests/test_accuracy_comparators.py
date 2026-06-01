"""
Unit tests for prediction_engine/accuracy_comparators.py.

Coverage target: 100% lines + branches + functions on production logic.
quick_smoke_test() + __main__ guard are excluded by pyproject.toml
[tool.coverage.report].exclude_also.

All comparators are pure functions over dicts — no LLM / network / API to mock.
Embedding similarity is supplied as an injected float/dict (as production does),
so no embedding engine is touched. Assertions harvested from the in-module
quick_smoke_test (D2 pipeline) + edge cases for full branch coverage.
"""
import pytest

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
    OPEN_ENDED_SIMILARITY_THRESHOLD,
    MULTI_SELECT_JACCARD_THRESHOLD,
)


# =========================================================================== #
# compare_yes_no
# =========================================================================== #
def test_yes_no_match():
    match, detail = compare_yes_no( { "value": "yes" }, { "value": "yes" } )
    assert match is True
    assert detail[ "predicted_binary" ] == "yes"
    assert detail[ "actual_binary" ]    == "yes"


def test_yes_no_mismatch():
    match, detail = compare_yes_no( { "value": "yes" }, { "value": "no" } )
    assert match is False


def test_yes_no_predicted_none():
    # first operand of `predicted is None or actual is None` True
    match, detail = compare_yes_no( None, { "value": "yes" } )
    assert match is None
    assert detail == { "reason": "missing_data" }


def test_yes_no_actual_none():
    # first operand False, second True
    match, detail = compare_yes_no( { "value": "yes" }, None )
    assert match is None


def test_yes_no_actual_qualifier_only():
    match, detail = compare_yes_no(
        { "value": "yes" },
        { "value": "yes [comment: only the old ones]" },
    )
    assert match is True
    assert detail[ "actual_qualifier" ] == "only the old ones"
    assert "predicted_qualifier" not in detail


def test_yes_no_both_qualifiers():
    match, detail = compare_yes_no(
        { "value": "yes", "qualifier": "only the March ones" },
        { "value": "yes [comment: only the old ones]" },
    )
    assert match is True
    assert detail[ "predicted_qualifier" ] == "only the March ones"
    assert detail[ "actual_qualifier" ]    == "only the old ones"


def test_yes_no_no_qualifiers():
    # actual_qualifier falsy AND predicted_qualifier falsy → neither detail key added
    match, detail = compare_yes_no( { "value": "yes" }, { "value": "yes" } )
    assert "actual_qualifier"    not in detail
    assert "predicted_qualifier" not in detail


# =========================================================================== #
# compare_multiple_choice_single
# =========================================================================== #
def test_mc_single_match():
    match, detail = compare_multiple_choice_single(
        { "answers": { "Database": "PostgreSQL" } },
        { "answers": { "Database": "PostgreSQL" } },
    )
    assert match is True
    assert detail[ "matches" ] == 1
    assert detail[ "total" ]   == 1
    assert detail[ "mismatches" ] == []


def test_mc_single_mismatch():
    match, detail = compare_multiple_choice_single(
        { "answers": { "Database": "PostgreSQL" } },
        { "answers": { "Database": "MySQL" } },
    )
    assert match is False
    assert detail[ "matches" ] == 0
    assert detail[ "mismatches" ][ 0 ] == { "header": "Database", "predicted": "PostgreSQL", "actual": "MySQL" }


def test_mc_single_predicted_none():
    match, detail = compare_multiple_choice_single( None, { "answers": { "a": "b" } } )
    assert match is None
    assert detail == { "reason": "missing_data" }


def test_mc_single_actual_none():
    match, detail = compare_multiple_choice_single( { "answers": { "a": "b" } }, None )
    assert match is None


def test_mc_single_empty_predicted_answers():
    # `not predicted_answers` True
    match, detail = compare_multiple_choice_single( { "answers": {} }, { "answers": { "a": "b" } } )
    assert match is None
    assert detail == { "reason": "empty_answers" }


def test_mc_single_empty_actual_answers():
    # `not predicted_answers` False, `not actual_answers` True
    match, detail = compare_multiple_choice_single( { "answers": { "a": "b" } }, { "answers": {} } )
    assert match is None
    assert detail == { "reason": "empty_answers" }


def test_mc_single_partial_match_is_false():
    match, detail = compare_multiple_choice_single(
        { "answers": { "DB": "PG", "Cache": "Redis" } },
        { "answers": { "DB": "PG", "Cache": "Memcached" } },
    )
    assert match is False
    assert detail[ "matches" ] == 1
    assert detail[ "total" ]   == 2


# =========================================================================== #
# compare_multiple_choice_multi  ( Jaccard )
# =========================================================================== #
def test_mc_multi_partial_overlap_below_threshold():
    match, detail = compare_multiple_choice_multi(
        { "answers": { "Features": [ "Auth", "Caching" ] } },
        { "answers": { "Features": [ "Auth", "Logging" ] } },
    )
    # Jaccard = 1/3 ≈ 0.333 < 0.5
    assert match is False
    assert detail[ "avg_jaccard" ] < MULTI_SELECT_JACCARD_THRESHOLD


def test_mc_multi_identical_above_threshold():
    match, detail = compare_multiple_choice_multi(
        { "answers": { "Features": [ "Auth", "Caching" ] } },
        { "answers": { "Features": [ "Auth", "Caching" ] } },
    )
    assert match is True
    assert detail[ "avg_jaccard" ] == 1.0


def test_mc_multi_predicted_none():
    match, detail = compare_multiple_choice_multi( None, { "answers": { "F": [ "A" ] } } )
    assert match is None


def test_mc_multi_actual_none():
    match, detail = compare_multiple_choice_multi( { "answers": { "F": [ "A" ] } }, None )
    assert match is None


def test_mc_multi_empty_predicted():
    match, detail = compare_multiple_choice_multi( { "answers": {} }, { "answers": { "F": [ "A" ] } } )
    assert match is None
    assert detail == { "reason": "empty_answers" }


def test_mc_multi_empty_actual():
    match, detail = compare_multiple_choice_multi( { "answers": { "F": [ "A" ] } }, { "answers": {} } )
    assert match is None


def test_mc_multi_non_list_values_normalized_to_singleton_sets():
    # actual_options non-list ( str ) and predicted_options non-list ( str )
    match, detail = compare_multiple_choice_multi(
        { "answers": { "Pick": "A" } },
        { "answers": { "Pick": "A" } },
    )
    assert match is True
    assert detail[ "header_scores" ][ "Pick" ][ "jaccard" ] == 1.0


def test_mc_multi_empty_union_yields_zero_jaccard():
    # both sides empty list for the header → union empty → jaccard 0.0 ( ternary else arc )
    match, detail = compare_multiple_choice_multi(
        { "answers": { "F": [] } },
        { "answers": { "F": [] } },
    )
    assert detail[ "header_scores" ][ "F" ][ "jaccard" ] == 0.0
    assert match is False


def test_mc_multi_predicted_missing_header_defaults_empty():
    # predicted_answers.get(header, []) → [] when header absent
    match, detail = compare_multiple_choice_multi(
        { "answers": { "Other": [ "X" ] } },
        { "answers": { "Features": [ "A", "B" ] } },
    )
    assert match is False
    assert detail[ "header_scores" ][ "Features" ][ "jaccard" ] == 0.0


# =========================================================================== #
# compare_open_ended
# =========================================================================== #
def test_open_ended_embedding_above_threshold():
    match, detail = compare_open_ended(
        { "value": "proceed with deployment" },
        { "value": "go ahead with deployment", "_embedding_similarity": 0.92 },
    )
    assert match is True
    assert detail[ "method" ]     == "embedding_similarity"
    assert detail[ "similarity" ] == 0.92
    assert detail[ "threshold" ]  == OPEN_ENDED_SIMILARITY_THRESHOLD


def test_open_ended_embedding_below_threshold():
    match, detail = compare_open_ended(
        { "value": "proceed" },
        { "value": "abort", "_embedding_similarity": 0.10 },
    )
    assert match is False
    assert detail[ "method" ] == "embedding_similarity"


def test_open_ended_embedding_int_accepted():
    # isinstance(embedding_sim, (int, float)) True for int as well
    match, detail = compare_open_ended(
        { "value": "x" },
        { "value": "y", "_embedding_similarity": 1 },
    )
    assert match is True
    assert detail[ "similarity" ] == 1.0


def test_open_ended_exact_match_fallback():
    # no _embedding_similarity → Strategy 2 exact match
    match, detail = compare_open_ended( { "value": "Proceed" }, { "value": "  proceed  " } )
    assert match is True
    assert detail[ "method" ] == "exact_match"


def test_open_ended_exact_mismatch_fallback():
    match, detail = compare_open_ended( { "value": "proceed" }, { "value": "abort" } )
    assert match is False
    assert detail[ "method" ] == "exact_match"


def test_open_ended_predicted_none():
    match, detail = compare_open_ended( None, { "value": "x" } )
    assert match is None


def test_open_ended_actual_none():
    match, detail = compare_open_ended( { "value": "x" }, None )
    assert match is None


def test_open_ended_non_numeric_embedding_falls_through_to_exact():
    # _embedding_similarity present but not int/float → isinstance False → exact match path
    match, detail = compare_open_ended(
        { "value": "proceed" },
        { "value": "proceed", "_embedding_similarity": "not a number" },
    )
    assert match is True
    assert detail[ "method" ] == "exact_match"


# =========================================================================== #
# compare_open_ended_batch
# =========================================================================== #
def test_open_ended_batch_embedding_match():
    match, detail = compare_open_ended_batch(
        { "answers": { "Topic": "quantum computing", "Budget": "no limit" } },
        { "answers": { "Topic": "quantum computing", "Budget": "no limit" },
          "_embedding_similarity": { "Topic": 0.95, "Budget": 0.90 } },
    )
    assert match is True
    assert detail[ "avg_similarity" ] >= OPEN_ENDED_SIMILARITY_THRESHOLD
    assert detail[ "header_details" ][ "Topic" ][ "method" ] == "embedding_similarity"


def test_open_ended_batch_exact_fallback_no_embedding():
    # use_embedding False ( no _embedding_similarity ) → exact-match per header
    match, detail = compare_open_ended_batch(
        { "answers": { "Topic": "quantum", "Budget": "none" } },
        { "answers": { "Topic": "quantum", "Budget": "none" } },
    )
    assert match is True
    assert detail[ "header_details" ][ "Topic" ][ "method" ] == "exact_match"
    assert detail[ "header_details" ][ "Topic" ][ "similarity" ] == 1.0


def test_open_ended_batch_exact_mismatch():
    match, detail = compare_open_ended_batch(
        { "answers": { "Topic": "quantum" } },
        { "answers": { "Topic": "classical" } },
    )
    assert match is False
    assert detail[ "header_details" ][ "Topic" ][ "similarity" ] == 0.0


def test_open_ended_batch_embedding_present_but_header_missing_uses_exact():
    # use_embedding True ( dict non-empty ) but this header absent from sims →
    # `use_embedding and header in embedding_sims` False → exact path for that header
    match, detail = compare_open_ended_batch(
        { "answers": { "Topic": "quantum", "Extra": "same" } },
        { "answers": { "Topic": "quantum", "Extra": "same" },
          "_embedding_similarity": { "Topic": 0.99 } },
    )
    assert detail[ "header_details" ][ "Topic" ][ "method" ] == "embedding_similarity"
    assert detail[ "header_details" ][ "Extra" ][ "method" ] == "exact_match"


def test_open_ended_batch_predicted_none():
    match, detail = compare_open_ended_batch( None, { "answers": { "a": "b" } } )
    assert match is None


def test_open_ended_batch_actual_none():
    match, detail = compare_open_ended_batch( { "answers": { "a": "b" } }, None )
    assert match is None


def test_open_ended_batch_empty_predicted():
    match, detail = compare_open_ended_batch( { "answers": {} }, { "answers": { "a": "b" } } )
    assert match is None
    assert detail == { "reason": "empty_answers" }


def test_open_ended_batch_empty_actual():
    match, detail = compare_open_ended_batch( { "answers": { "a": "b" } }, { "answers": {} } )
    assert match is None


def test_open_ended_batch_empty_embedding_dict_uses_exact():
    # _embedding_similarity present but empty dict → use_embedding False ( len == 0 )
    match, detail = compare_open_ended_batch(
        { "answers": { "Topic": "x" } },
        { "answers": { "Topic": "x" }, "_embedding_similarity": {} },
    )
    assert detail[ "header_details" ][ "Topic" ][ "method" ] == "exact_match"


def test_open_ended_batch_predicted_missing_header_defaults_empty_string():
    match, detail = compare_open_ended_batch(
        { "answers": { "Other": "x" } },
        { "answers": { "Topic": "" } },
    )
    # predicted missing "Topic" → "" ; actual "" → exact match True
    assert detail[ "header_details" ][ "Topic" ][ "similarity" ] == 1.0


# =========================================================================== #
# get_comparator  ( dispatch )
# =========================================================================== #
def test_get_comparator_yes_no():
    assert get_comparator( "yes_no" ) is compare_yes_no


def test_get_comparator_unknown_falls_back_to_open_ended():
    assert get_comparator( "unknown_type" ) is compare_open_ended


def test_get_comparator_open_ended_batch():
    assert get_comparator( "open_ended_batch" ) is compare_open_ended_batch


def test_get_comparator_open_ended():
    assert get_comparator( "open_ended" ) is compare_open_ended


def test_get_comparator_mc_no_actual_value_is_single():
    # actual_value is None → skip data-driven dispatch → single
    assert get_comparator( "multiple_choice" ) is compare_multiple_choice_single


def test_get_comparator_mc_multi_select_detected():
    # actual has a list value → multi
    comp = get_comparator( "multiple_choice", actual_value={ "answers": { "Features": [ "A", "B" ] } } )
    assert comp is compare_multiple_choice_multi


def test_get_comparator_mc_single_select_detected():
    # actual answers all scalar → loop exhausts without a list → single
    comp = get_comparator( "multiple_choice", actual_value={ "answers": { "DB": "PG" } } )
    assert comp is compare_multiple_choice_single


def test_get_comparator_mc_non_dict_actual_value():
    # actual_value not None but not a dict → isinstance() else → answers {} → single
    comp = get_comparator( "multiple_choice", actual_value="not a dict" )
    assert comp is compare_multiple_choice_single


def test_get_comparator_non_mc_with_actual_value_skips_dispatch():
    # response_type != multiple_choice → the `and` short-circuits → normal table lookup
    comp = get_comparator( "yes_no", actual_value={ "answers": { "F": [ "A" ] } } )
    assert comp is compare_yes_no


# =========================================================================== #
# _extract_binary
# =========================================================================== #
def test_extract_binary_empty_returns_empty():
    assert _extract_binary( "" ) == ""


def test_extract_binary_yes():
    assert _extract_binary( "yes" ) == "yes"
    assert _extract_binary( "  YES [comment: x]" ) == "yes"


def test_extract_binary_no():
    assert _extract_binary( "no" ) == "no"
    assert _extract_binary( "No way" ) == "no"


def test_extract_binary_neither_returns_lowered_value():
    assert _extract_binary( "Maybe" ) == "maybe"


# =========================================================================== #
# _extract_qualifier
# =========================================================================== #
def test_extract_qualifier_empty_returns_none():
    assert _extract_qualifier( "" ) is None


def test_extract_qualifier_no_marker_returns_none():
    assert _extract_qualifier( "yes" ) is None


def test_extract_qualifier_with_closing_bracket():
    assert _extract_qualifier( "yes [comment: only the March ones]" ) == "only the March ones"


def test_extract_qualifier_unclosed_marker_returns_rest():
    # marker present, no closing "]" → returns text from start to end of string
    assert _extract_qualifier( "yes [comment: unclosed tail" ) == "unclosed tail"
