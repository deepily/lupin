"""
Unit tests for TFE-to-CC output_contract parsers.

Exercises:
- `parse_diagnosis_block` — primary fenced-block extractor
- `validate_diagnosis_payload` — schema check
- `parse_diagnosis_fallback` — markdown-regex recovery when fence missing

Filed 2026-04-19 Session be57a252.
"""

import pytest

from cosa.agents.tfe_to_cc.prompts.output_contract import (
    parse_diagnosis_block,
    parse_diagnosis_fallback,
    validate_diagnosis_payload,
)


# ═══════════════════════════════════════════════════════════════════════════
# parse_diagnosis_block — primary parser
# ═══════════════════════════════════════════════════════════════════════════

class TestParseDiagnosisBlock:

    def test_empty_input_returns_none( self ):
        assert parse_diagnosis_block( "" ) is None
        assert parse_diagnosis_block( None ) is None

    def test_no_fence_returns_none( self ):
        text = "I looked at the code and it's broken. Root cause: X."
        assert parse_diagnosis_block( text ) is None

    def test_simple_fenced_block_parses( self ):
        text = '''
Some prose explaining the analysis.

```tfe-diagnosis
{"clusters": {"C1": {"root_cause": "stale assertion", "error_category": "test_bug", "confidence": 0.95}}}
```
'''
        result = parse_diagnosis_block( text )
        assert result is not None
        assert "clusters" in result
        assert result[ "clusters" ][ "C1" ][ "error_category" ] == "test_bug"
        assert result[ "clusters" ][ "C1" ][ "confidence" ] == 0.95

    def test_multi_cluster_block_parses( self ):
        text = '''
```tfe-diagnosis
{
  "clusters": {
    "C1": {"root_cause": "a", "error_category": "test_bug", "confidence": 0.9},
    "C2": {"root_cause": "b", "error_category": "code_bug", "confidence": 0.7}
  }
}
```
'''
        result = parse_diagnosis_block( text )
        assert result is not None
        assert set( result[ "clusters" ].keys() ) == { "C1", "C2" }

    def test_malformed_json_returns_none( self ):
        text = '''
```tfe-diagnosis
{"clusters": {"C1": { incomplete
```
'''
        assert parse_diagnosis_block( text ) is None

    def test_wrong_top_level_type_returns_none( self ):
        text = '''
```tfe-diagnosis
["not", "a", "dict"]
```
'''
        assert parse_diagnosis_block( text ) is None

    def test_missing_clusters_key_returns_none( self ):
        text = '''
```tfe-diagnosis
{"summary": "2 clusters fixed"}
```
'''
        assert parse_diagnosis_block( text ) is None

    def test_block_among_other_content_extracts_correctly( self ):
        # Simulates realistic CC output where prose + block + trailing prose.
        text = '''
## My analysis

Here's what I found...

```python
# irrelevant code block
print("hello")
```

The root cause spans multiple files.

```tfe-diagnosis
{"clusters": {"C1": {"root_cause": "x", "error_category": "code_bug", "confidence": 0.8}}}
```

Thanks for reading!
'''
        result = parse_diagnosis_block( text )
        assert result is not None
        assert result[ "clusters" ][ "C1" ][ "error_category" ] == "code_bug"

    def test_first_tfe_diagnosis_fence_wins_when_multiple( self ):
        # Shouldn't happen in practice but be deterministic if it does.
        text = '''
```tfe-diagnosis
{"clusters": {"C1": {"root_cause": "first", "error_category": "test_bug", "confidence": 0.9}}}
```

Then later:

```tfe-diagnosis
{"clusters": {"C1": {"root_cause": "second", "error_category": "code_bug", "confidence": 0.5}}}
```
'''
        result = parse_diagnosis_block( text )
        assert result is not None
        assert result[ "clusters" ][ "C1" ][ "root_cause" ] == "first"


# ═══════════════════════════════════════════════════════════════════════════
# validate_diagnosis_payload
# ═══════════════════════════════════════════════════════════════════════════

class TestValidateDiagnosisPayload:

    def test_none_fails( self ):
        ok, issues = validate_diagnosis_payload( None )
        assert not ok
        assert any( "None" in i or "parse" in i.lower() for i in issues )

    def test_valid_minimal_passes( self ):
        payload = {
            "clusters": {
                "C1": {
                    "root_cause": "The test asserts the wrong count because JOB_ARG_CONTRACTS now has 10 entries, not 5.",
                    "error_category": "test_bug",
                    "confidence": 0.95,
                }
            }
        }
        ok, issues = validate_diagnosis_payload( payload )
        assert ok, f"Expected valid, got issues: {issues}"
        assert issues == []

    def test_missing_clusters_key_fails( self ):
        ok, issues = validate_diagnosis_payload( { "summary": "x" } )
        assert not ok
        assert any( "clusters" in i for i in issues )

    def test_empty_clusters_produces_issue( self ):
        ok, issues = validate_diagnosis_payload( { "clusters": {} } )
        assert not ok
        assert any( "empty" in i.lower() for i in issues )

    def test_missing_required_field_flagged( self ):
        payload = {
            "clusters": {
                "C1": {
                    "root_cause": "Detailed explanation of the root cause here.",
                    # missing error_category and confidence
                }
            }
        }
        ok, issues = validate_diagnosis_payload( payload )
        assert not ok
        assert any( "error_category" in i for i in issues )
        assert any( "confidence" in i for i in issues )

    def test_unknown_category_flagged( self ):
        payload = {
            "clusters": {
                "C1": {
                    "root_cause": "Detailed explanation of the root cause here.",
                    "error_category": "mystery_bug",
                    "confidence": 0.8,
                }
            }
        }
        ok, issues = validate_diagnosis_payload( payload )
        assert not ok
        assert any( "mystery_bug" in i for i in issues )

    def test_out_of_range_confidence_flagged( self ):
        payload = {
            "clusters": {
                "C1": {
                    "root_cause": "Detailed explanation of the root cause here.",
                    "error_category": "test_bug",
                    "confidence": 1.5,
                }
            }
        }
        ok, issues = validate_diagnosis_payload( payload )
        assert not ok
        assert any( "1.5" in i or "outside" in i for i in issues )

    def test_non_numeric_confidence_flagged( self ):
        payload = {
            "clusters": {
                "C1": {
                    "root_cause": "Detailed explanation of the root cause here.",
                    "error_category": "test_bug",
                    "confidence": "high",
                }
            }
        }
        ok, issues = validate_diagnosis_payload( payload )
        assert not ok
        assert any( "confidence" in i for i in issues )

    def test_short_root_cause_flagged( self ):
        payload = {
            "clusters": {
                "C1": {
                    "root_cause": "idk",  # too short to be useful
                    "error_category": "test_bug",
                    "confidence": 0.5,
                }
            }
        }
        ok, issues = validate_diagnosis_payload( payload )
        assert not ok
        assert any( "short" in i.lower() for i in issues )

    def test_multi_cluster_accumulates_issues_independently( self ):
        payload = {
            "clusters": {
                "C1": {
                    "root_cause": "Valid cluster root cause text here.",
                    "error_category": "test_bug",
                    "confidence": 0.9,
                },
                "C2": {
                    "root_cause": "Another valid one with enough text.",
                    "error_category": "bogus",
                    "confidence": 0.5,
                },
            }
        }
        ok, issues = validate_diagnosis_payload( payload )
        assert not ok
        # C2 issue should be isolated to C2
        assert any( "C2" in i and "bogus" in i for i in issues )
        # C1 should not surface issues
        assert not any( "C1" in i for i in issues )


# ═══════════════════════════════════════════════════════════════════════════
# parse_diagnosis_fallback — regex recovery
# ═══════════════════════════════════════════════════════════════════════════

class TestParseDiagnosisFallback:

    def test_empty_returns_none( self ):
        assert parse_diagnosis_fallback( "" ) is None
        assert parse_diagnosis_fallback( None ) is None

    def test_no_cluster_headers_returns_none( self ):
        text = "I couldn't figure it out. Sorry."
        assert parse_diagnosis_fallback( text ) is None

    def test_recovers_single_cluster_with_root_cause( self ):
        text = '''
## Cluster C1

**Root cause**: The test asserts len(X) == 5 but X now has 10 entries.
**Category**: test_bug
'''
        result = parse_diagnosis_fallback( text )
        assert result is not None
        assert "C1" in result[ "clusters" ]
        assert "len(X) == 5" in result[ "clusters" ][ "C1" ][ "root_cause" ]
        assert result[ "clusters" ][ "C1" ][ "error_category" ] == "test_bug"
        assert result[ "clusters" ][ "C1" ][ "confidence" ] == 0.5  # fallback default

    def test_recovers_multi_cluster( self ):
        text = '''
### Cluster C1
Root cause: first cause here
Category: code_bug

### Cluster C2
Diagnosis: second one is about fixtures
Error_category: fixture_bug
'''
        result = parse_diagnosis_fallback( text )
        assert result is not None
        assert set( result[ "clusters" ].keys() ) == { "C1", "C2" }
        assert result[ "clusters" ][ "C1" ][ "error_category" ] == "code_bug"
        assert result[ "clusters" ][ "C2" ][ "error_category" ] == "fixture_bug"

    def test_missing_category_defaults_to_unknown( self ):
        text = '''
## Cluster C1

Root cause: explanation without a category line.
'''
        result = parse_diagnosis_fallback( text )
        assert result is not None
        assert result[ "clusters" ][ "C1" ][ "error_category" ] == "unknown"

    def test_cluster_without_root_cause_skipped( self ):
        text = '''
## Cluster C1
Just a header, no cause extracted.
'''
        result = parse_diagnosis_fallback( text )
        # No root_cause → cluster skipped → no clusters → returns None
        assert result is None

    def test_case_insensitive_headers_and_labels( self ):
        text = '''
## CLUSTER c1

ROOT CAUSE: upper-case everything works too
'''
        result = parse_diagnosis_fallback( text )
        assert result is not None
        assert "C1" in result[ "clusters" ]  # normalized to uppercase

    def test_fallback_notes_field_flags_fallback_origin( self ):
        text = '''
## Cluster C1
Root cause: testing fallback notes
'''
        result = parse_diagnosis_fallback( text )
        assert result is not None
        assert "fallback parser" in result[ "clusters" ][ "C1" ][ "notes" ].lower()


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
