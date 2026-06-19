"""
Unit tests for cosa/agents/tfe_to_cc/prompts/output_contract.py.

Pure JSON/regex parsers + validators — no LLM / network / fs seams, ZERO API spend.
Coverage target: 100% lines + branches + functions on production logic.
quick_smoke_test() / __main__ blocks are excluded by the coverage config.
"""
import pytest

from cosa.agents.tfe_to_cc.prompts.output_contract import (
    parse_diagnosis_block,
    validate_diagnosis_payload,
    parse_result_block,
    validate_result_payload,
    parse_result_from_git_log,
    parse_diagnosis_fallback,
)


# =========================================================================== #
# parse_diagnosis_block
# =========================================================================== #
def _fence_diag( body: str ) -> str:
    return f"prose before\n```tfe-diagnosis\n{body}\n```\nprose after"


def test_parse_diagnosis_block_success():
    out = parse_diagnosis_block( _fence_diag( '{"clusters": {"C1": {"root_cause": "x"}}}' ) )
    assert out == { "clusters": { "C1": { "root_cause": "x" } } }


def test_parse_diagnosis_block_empty_text_returns_none():
    assert parse_diagnosis_block( "" )   is None
    assert parse_diagnosis_block( None ) is None


def test_parse_diagnosis_block_no_fence_returns_none():
    assert parse_diagnosis_block( "no fenced block here" ) is None


def test_parse_diagnosis_block_bad_json_returns_none():
    assert parse_diagnosis_block( _fence_diag( "{not valid json" ) ) is None


def test_parse_diagnosis_block_non_dict_json_returns_none():
    # body parses to an int → not a dict
    assert parse_diagnosis_block( _fence_diag( "123" ) ) is None


def test_parse_diagnosis_block_missing_clusters_key_returns_none():
    assert parse_diagnosis_block( _fence_diag( '{"other": 1}' ) ) is None


def test_parse_diagnosis_block_clusters_not_dict_returns_none():
    assert parse_diagnosis_block( _fence_diag( '{"clusters": [1, 2]}' ) ) is None


# =========================================================================== #
# validate_diagnosis_payload
# =========================================================================== #
def _valid_cluster():
    return { "root_cause": "a clearly long enough root cause", "error_category": "code_bug", "confidence": 0.9 }


def test_validate_diagnosis_payload_none():
    ok, issues = validate_diagnosis_payload( None )
    assert ok is False
    assert "parse failed" in issues[ 0 ]


def test_validate_diagnosis_payload_not_dict():
    ok, issues = validate_diagnosis_payload( [ "not", "a", "dict" ] )
    assert ok is False
    assert "not a dict" in issues[ 0 ]


def test_validate_diagnosis_payload_clusters_not_dict():
    ok, issues = validate_diagnosis_payload( { "clusters": "nope" } )
    assert ok is False
    assert "not a dict" in issues[ 0 ]


def test_validate_diagnosis_payload_empty_clusters():
    ok, issues = validate_diagnosis_payload( { "clusters": {} } )
    assert ok is False
    assert any( "empty" in i for i in issues )


def test_validate_diagnosis_payload_cluster_not_dict():
    ok, issues = validate_diagnosis_payload( { "clusters": { "C1": "not a dict" } } )
    assert ok is False
    assert any( "value is not a dict" in i for i in issues )


def test_validate_diagnosis_payload_missing_required_field():
    ok, issues = validate_diagnosis_payload(
        { "clusters": { "C1": { "root_cause": "long enough root cause text" } } }
    )
    assert ok is False
    assert any( "missing required field" in i for i in issues )


def test_validate_diagnosis_payload_unknown_category():
    cluster = _valid_cluster()
    cluster[ "error_category" ] = "bogus_category"
    ok, issues = validate_diagnosis_payload( { "clusters": { "C1": cluster } } )
    assert ok is False
    assert any( "unknown error_category" in i for i in issues )


def test_validate_diagnosis_payload_confidence_not_a_number():
    cluster = _valid_cluster()
    cluster[ "confidence" ] = "high"
    ok, issues = validate_diagnosis_payload( { "clusters": { "C1": cluster } } )
    assert ok is False
    assert any( "confidence is not a number" in i for i in issues )


def test_validate_diagnosis_payload_confidence_out_of_range():
    cluster = _valid_cluster()
    cluster[ "confidence" ] = 1.5
    ok, issues = validate_diagnosis_payload( { "clusters": { "C1": cluster } } )
    assert ok is False
    assert any( "outside [0.0, 1.0]" in i for i in issues )


def test_validate_diagnosis_payload_root_cause_not_string():
    cluster = _valid_cluster()
    cluster[ "root_cause" ] = 12345
    ok, issues = validate_diagnosis_payload( { "clusters": { "C1": cluster } } )
    assert ok is False
    assert any( "root_cause is not a string" in i for i in issues )


def test_validate_diagnosis_payload_root_cause_too_short():
    cluster = _valid_cluster()
    cluster[ "root_cause" ] = "short"
    ok, issues = validate_diagnosis_payload( { "clusters": { "C1": cluster } } )
    assert ok is False
    assert any( "suspiciously short" in i for i in issues )


def test_validate_diagnosis_payload_valid_optional_fields_none():
    # error_category None + confidence None → those guards skip; root_cause long → valid
    cluster = { "root_cause": "a clearly long enough root cause", "error_category": None, "confidence": None }
    ok, issues = validate_diagnosis_payload( { "clusters": { "C1": cluster } } )
    assert ok is True
    assert issues == []


def test_validate_diagnosis_payload_fully_valid():
    ok, issues = validate_diagnosis_payload( { "clusters": { "C1": _valid_cluster() } } )
    assert ok is True
    assert issues == []


# =========================================================================== #
# parse_result_block
# =========================================================================== #
def _fence_result( body: str ) -> str:
    return f"```tfe-result\n{body}\n```"


def test_parse_result_block_success():
    out = parse_result_block( _fence_result( '{"clusters": {"C1": {"verdict": "fixed"}}}' ) )
    assert out == { "clusters": { "C1": { "verdict": "fixed" } } }


def test_parse_result_block_empty_text_returns_none():
    assert parse_result_block( None ) is None


def test_parse_result_block_no_fence_returns_none():
    assert parse_result_block( "nothing fenced" ) is None


def test_parse_result_block_bad_json_returns_none():
    assert parse_result_block( _fence_result( "}{" ) ) is None


def test_parse_result_block_non_dict_json_returns_none():
    assert parse_result_block( _fence_result( '"a string"' ) ) is None


def test_parse_result_block_missing_clusters_returns_none():
    assert parse_result_block( _fence_result( '{"x": 1}' ) ) is None


def test_parse_result_block_clusters_not_dict_returns_none():
    assert parse_result_block( _fence_result( '{"clusters": 5}' ) ) is None


# =========================================================================== #
# validate_result_payload
# =========================================================================== #
def test_validate_result_payload_none():
    ok, issues = validate_result_payload( None )
    assert ok is False
    assert "parse failed" in issues[ 0 ]


def test_validate_result_payload_not_dict():
    ok, issues = validate_result_payload( 42 )
    assert ok is False
    assert "not a dict" in issues[ 0 ]


def test_validate_result_payload_clusters_not_dict():
    ok, issues = validate_result_payload( { "clusters": None } )
    assert ok is False
    assert "not a dict" in issues[ 0 ]


def test_validate_result_payload_empty_clusters():
    ok, issues = validate_result_payload( { "clusters": {} } )
    assert ok is False
    assert any( "empty" in i for i in issues )


def test_validate_result_payload_cluster_not_dict():
    ok, issues = validate_result_payload( { "clusters": { "C1": 7 } } )
    assert ok is False
    assert any( "value is not a dict" in i for i in issues )


def test_validate_result_payload_missing_verdict():
    ok, issues = validate_result_payload( { "clusters": { "C1": {} } } )
    assert ok is False
    assert any( "missing required field 'verdict'" in i for i in issues )


def test_validate_result_payload_unknown_verdict():
    ok, issues = validate_result_payload( { "clusters": { "C1": { "verdict": "maybe" } } } )
    assert ok is False
    assert any( "unknown verdict" in i for i in issues )


def test_validate_result_payload_fixed_missing_commit_sha():
    ok, issues = validate_result_payload( { "clusters": { "C1": { "verdict": "fixed" } } } )
    assert ok is False
    assert any( "commit_sha is missing" in i for i in issues )


def test_validate_result_payload_fixed_commit_sha_not_string():
    ok, issues = validate_result_payload(
        { "clusters": { "C1": { "verdict": "fixed", "commit_sha": 123 } } }
    )
    assert ok is False
    assert any( "commit_sha is missing or not a string" in i for i in issues )


def test_validate_result_payload_pytest_passed_not_bool():
    ok, issues = validate_result_payload(
        { "clusters": { "C1": { "verdict": "failed", "pytest_passed": "yes" } } }
    )
    assert ok is False
    assert any( "pytest_passed is not a bool" in i for i in issues )


def test_validate_result_payload_fully_valid():
    payload = { "clusters": { "C1": {
        "verdict": "fixed", "commit_sha": "abc1234", "pytest_passed": True
    } } }
    ok, issues = validate_result_payload( payload )
    assert ok is True
    assert issues == []


def test_validate_result_payload_valid_non_fixed_no_commit_needed():
    # verdict != fixed → commit_sha guard skipped; pytest_passed None → guard skipped
    payload = { "clusters": { "C1": { "verdict": "unclear" } } }
    ok, issues = validate_result_payload( payload )
    assert ok is True
    assert issues == []


# =========================================================================== #
# parse_result_from_git_log
# =========================================================================== #
def test_git_log_empty_with_expected_ids_builds_unclear():
    out = parse_result_from_git_log( "", expected_cluster_ids=[ "C1", "C2" ] )
    assert out[ "summary" ] == "0/2 fixed"
    assert out[ "clusters" ][ "C1" ][ "verdict" ] == "unclear"
    assert out[ "clusters" ][ "C2" ][ "commit_sha" ] is None


def test_git_log_empty_no_expected_returns_none():
    assert parse_result_from_git_log( "   " ) is None
    assert parse_result_from_git_log( None ) is None


def test_git_log_with_matching_commits():
    log = (
        "deadbeef fix(tfe): C1 repair stale assertion\n"
        "cafe1234 fix(tfe): C2 patch fixture\n"
        "0000000 chore: unrelated commit\n"
    )
    out = parse_result_from_git_log( log )
    assert out[ "summary" ] == "2/2 fixed"
    assert out[ "clusters" ][ "C1" ][ "commit_sha" ] == "deadbeef"
    assert out[ "clusters" ][ "C1" ][ "verdict" ]    == "fixed"


def test_git_log_first_occurrence_wins_for_duplicate_cluster():
    # newest-first: the first C1 line wins; the second is ignored ( 'if cid not in found' False arc )
    log = (
        "newsha11 fix(tfe): C1 newer fix\n"
        "oldsha22 fix(tfe): C1 older fix\n"
    )
    out = parse_result_from_git_log( log )
    assert out[ "clusters" ][ "C1" ][ "commit_sha" ] == "newsha11"
    assert len( out[ "clusters" ] ) == 1


def test_git_log_only_non_matching_lines_returns_none():
    # lines present but none match the pattern, no expected_ids → found empty → None
    assert parse_result_from_git_log( "abc chore: nothing\nxyz docs: readme\n" ) is None


def test_git_log_matches_plus_expected_adds_unclear():
    log = "deadbeef fix(tfe): C1 done\n"
    out = parse_result_from_git_log( log, expected_cluster_ids=[ "C1", "C2", "C3" ] )
    assert out[ "clusters" ][ "C1" ][ "verdict" ] == "fixed"
    assert out[ "clusters" ][ "C2" ][ "verdict" ] == "unclear"
    assert out[ "clusters" ][ "C3" ][ "verdict" ] == "unclear"
    assert out[ "summary" ] == "1/3 fixed"


# =========================================================================== #
# parse_diagnosis_fallback
# =========================================================================== #
def test_diagnosis_fallback_empty_text_returns_none():
    assert parse_diagnosis_fallback( "" )   is None
    assert parse_diagnosis_fallback( None ) is None


def test_diagnosis_fallback_no_cluster_headers_returns_none():
    assert parse_diagnosis_fallback( "just some prose with no cluster headers" ) is None


def test_diagnosis_fallback_recovers_cluster_with_category():
    text = (
        "## Cluster C1 — analysis\n"
        "Root cause: the assertion compares against a stale expected value\n"
        "Category: test_bug\n"
        "### C2\n"
        "Diagnosis: the production function returns the wrong type\n"
        "error_category: code_bug\n"
    )
    out = parse_diagnosis_fallback( text )
    assert out[ "clusters" ][ "C1" ][ "error_category" ] == "test_bug"
    assert out[ "clusters" ][ "C2" ][ "error_category" ] == "code_bug"
    assert out[ "clusters" ][ "C1" ][ "confidence" ] == 0.5


def test_diagnosis_fallback_root_cause_without_category_defaults_unknown():
    # cat_m absent → ternary False arc → "unknown"
    text = "### C1\nRoot cause: something went wrong in the loop bounds\n"
    out = parse_diagnosis_fallback( text )
    assert out[ "clusters" ][ "C1" ][ "error_category" ] == "unknown"


def test_diagnosis_fallback_header_without_root_cause_skipped_returns_none():
    # header present but no root_cause line → cluster skipped ( continue ) → clusters empty → None
    text = "### C1\nsome notes but no root cause line here\n"
    assert parse_diagnosis_fallback( text ) is None
