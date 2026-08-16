"""
Unit tests for `parse_result_block`, `validate_result_payload`, and
`parse_result_from_git_log` in `output_contract.py`.
"""

import pytest

from cosa.agents.tfe_to_cc.prompts.output_contract import (
    parse_result_block,
    validate_result_payload,
    parse_result_from_git_log,
)


# ═════════════════════════════════════════════════════════════════════════
# parse_result_block
# ═════════════════════════════════════════════════════════════════════════

class TestParseResultBlock:

    def test_empty_returns_none( self ):
        assert parse_result_block( "" ) is None
        assert parse_result_block( None ) is None

    def test_no_fence_returns_none( self ):
        assert parse_result_block( "I did the fixes." ) is None

    def test_simple_result_parses( self ):
        text = '''
Summary prose here.

```tfe-result
{
  "clusters": {
    "C1": {"verdict": "fixed", "commit_sha": "abc1234", "files": ["src/a.py"], "pytest_passed": true, "notes": "ok"}
  },
  "summary": "1/1 fixed"
}
```
'''
        r = parse_result_block( text )
        assert r is not None
        assert r[ "clusters" ][ "C1" ][ "verdict" ] == "fixed"
        assert r[ "clusters" ][ "C1" ][ "commit_sha" ] == "abc1234"
        assert r[ "summary" ] == "1/1 fixed"

    def test_malformed_json_returns_none( self ):
        text = '```tfe-result\n{"clusters": {broken\n```'
        assert parse_result_block( text ) is None

    def test_missing_clusters_key_returns_none( self ):
        text = '```tfe-result\n{"summary": "nope"}\n```'
        assert parse_result_block( text ) is None

    def test_wrong_top_type_returns_none( self ):
        text = '```tfe-result\n[]\n```'
        assert parse_result_block( text ) is None

    def test_result_block_does_not_match_diagnosis_fence( self ):
        # Make sure the result parser isn't accidentally catching tfe-diagnosis blocks
        text = '''
```tfe-diagnosis
{"clusters": {"C1": {"root_cause": "x", "error_category": "test_bug", "confidence": 0.9}}}
```
'''
        assert parse_result_block( text ) is None


# ═════════════════════════════════════════════════════════════════════════
# validate_result_payload
# ═════════════════════════════════════════════════════════════════════════

class TestValidateResultPayload:

    def test_none_fails( self ):
        ok, issues = validate_result_payload( None )
        assert not ok
        assert issues

    def test_valid_fixed_passes( self ):
        payload = {
            "clusters": {
                "C1": {
                    "verdict": "fixed",
                    "commit_sha": "abc1234",
                    "files": [ "src/a.py" ],
                    "pytest_passed": True,
                    "notes": "ok",
                }
            }
        }
        ok, issues = validate_result_payload( payload )
        assert ok, f"Expected valid, got: {issues}"

    def test_valid_failed_without_commit_passes( self ):
        payload = {
            "clusters": {
                "C1": {
                    "verdict": "failed",
                    "commit_sha": None,
                    "pytest_passed": False,
                    "notes": "tests still failing",
                }
            }
        }
        ok, issues = validate_result_payload( payload )
        assert ok, f"Expected valid, got: {issues}"

    def test_fixed_without_commit_sha_flagged( self ):
        payload = {
            "clusters": {
                "C1": {
                    "verdict": "fixed",
                    "commit_sha": None,  # MISSING for a fixed verdict
                }
            }
        }
        ok, issues = validate_result_payload( payload )
        assert not ok
        assert any( "commit_sha" in i for i in issues )

    def test_unknown_verdict_flagged( self ):
        payload = {
            "clusters": {
                "C1": { "verdict": "yolo" }
            }
        }
        ok, issues = validate_result_payload( payload )
        assert not ok
        assert any( "yolo" in i for i in issues )

    def test_missing_verdict_flagged( self ):
        payload = {
            "clusters": {
                "C1": { "commit_sha": "x" }
            }
        }
        ok, issues = validate_result_payload( payload )
        assert not ok
        assert any( "verdict" in i for i in issues )

    def test_pytest_passed_non_bool_flagged( self ):
        payload = {
            "clusters": {
                "C1": { "verdict": "fixed", "commit_sha": "x", "pytest_passed": "yes" }
            }
        }
        ok, issues = validate_result_payload( payload )
        assert not ok
        assert any( "pytest_passed" in i for i in issues )

    def test_empty_clusters_produces_issue( self ):
        ok, issues = validate_result_payload( { "clusters": {} } )
        assert not ok
        assert any( "empty" in i.lower() for i in issues )

    def test_multi_cluster_mixed( self ):
        payload = {
            "clusters": {
                "C1": { "verdict": "fixed", "commit_sha": "abc123" },
                "C2": { "verdict": "failed", "commit_sha": None },
                "C3": { "verdict": "unclear", "commit_sha": None },
            }
        }
        ok, issues = validate_result_payload( payload )
        assert ok, f"Expected valid, got: {issues}"


# ═════════════════════════════════════════════════════════════════════════
# parse_result_from_git_log — fallback
# ═════════════════════════════════════════════════════════════════════════

class TestGitLogFallback:

    def test_empty_no_expected_returns_none( self ):
        assert parse_result_from_git_log( "" ) is None
        assert parse_result_from_git_log( None ) is None

    def test_empty_with_expected_cluster_ids_returns_all_unclear( self ):
        r = parse_result_from_git_log( "", expected_cluster_ids=[ "C1", "C2" ] )
        assert r is not None
        assert set( r[ "clusters" ].keys() ) == { "C1", "C2" }
        for cid in ( "C1", "C2" ):
            assert r[ "clusters" ][ cid ][ "verdict" ] == "unclear"
        assert r[ "summary" ] == "0/2 fixed"

    def test_single_commit_parsed( self ):
        git_log = "abc1234 fix(tfe): C1 Add missing CARD_LABELS entry"
        r = parse_result_from_git_log( git_log )
        assert r is not None
        assert r[ "clusters" ][ "C1" ][ "verdict" ] == "fixed"
        assert r[ "clusters" ][ "C1" ][ "commit_sha" ] == "abc1234"
        assert "fallback" in r[ "clusters" ][ "C1" ][ "notes" ].lower()

    def test_multiple_commits_parsed( self ):
        git_log = "\n".join( [
            "abc1234 fix(tfe): C1 First",
            "def5678 fix(tfe): C3 Third",
            "9876543 Some unrelated commit",
            "ffeeaa1 fix(tfe): C6 Sixth",
        ] )
        r = parse_result_from_git_log( git_log )
        assert r is not None
        assert set( r[ "clusters" ].keys() ) == { "C1", "C3", "C6" }
        assert r[ "clusters" ][ "C1" ][ "commit_sha" ] == "abc1234"
        assert r[ "clusters" ][ "C3" ][ "commit_sha" ] == "def5678"
        assert r[ "clusters" ][ "C6" ][ "commit_sha" ] == "ffeeaa1"
        assert "3/3 fixed" == r[ "summary" ]

    def test_expected_ids_fills_in_unclear_for_missing( self ):
        git_log = "abc1234 fix(tfe): C1 One"
        r = parse_result_from_git_log( git_log, expected_cluster_ids=[ "C1", "C2", "C3" ] )
        assert r is not None
        assert r[ "clusters" ][ "C1" ][ "verdict" ] == "fixed"
        assert r[ "clusters" ][ "C2" ][ "verdict" ] == "unclear"
        assert r[ "clusters" ][ "C3" ][ "verdict" ] == "unclear"
        assert r[ "summary" ] == "1/3 fixed"

    def test_same_cluster_twice_newer_wins( self ):
        # Git log is newest-first
        git_log = "\n".join( [
            "newer11 fix(tfe): C1 Retry attempt",
            "older00 fix(tfe): C1 First attempt",
        ] )
        r = parse_result_from_git_log( git_log )
        assert r is not None
        assert r[ "clusters" ][ "C1" ][ "commit_sha" ] == "newer11"

    def test_non_tfe_commits_ignored( self ):
        git_log = "\n".join( [
            "abc1234 chore: random commit",
            "def5678 feat: new feature",
            "ffeeaa1 fix: generic fix without (tfe)",
        ] )
        r = parse_result_from_git_log( git_log )
        assert r is None  # no tfe commits, no expected ids → nothing

    def test_pattern_matches_uppercase_or_lowercase_tfe( self ):
        # Our commit convention is lowercase fix(tfe): but be tolerant
        git_log = "abc1234 Fix(TFE): C1 title"
        r = parse_result_from_git_log( git_log )
        assert r is not None
        assert "C1" in r[ "clusters" ]


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
