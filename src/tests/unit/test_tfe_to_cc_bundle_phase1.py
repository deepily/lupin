"""
Unit tests for TFE-to-CC Phase 1 bundle-prompt builder.

Exercises `build_diagnosis_bundle_prompt`:
- Required sections are present
- Cluster data renders into readable markdown
- Tool-guardrail lines name the right tools
- Output contract mentions the fenced `tfe-diagnosis` block
- Confidence + category guidance present

Filed 2026-04-19 Session be57a252. Paired design doc:
    src/rnd/v0.1.6/2026.04.10-test-fix-expediter/20-tfe-to-cc-phase1-live-test.md
"""

import pytest

from cosa.agents.tfe_to_cc.prompts.bundle_phase1 import build_diagnosis_bundle_prompt


def _cluster( cid: str, tests: list, **extras ) -> dict:
    return {
        "cluster_id"             : cid,
        "failing_tests"          : tests,
        "shared_error_signature" : extras.get( "signature" ),
        "affected_files_guess"   : extras.get( "affected" ),
        "failure_count"          : extras.get( "failure_count" ),
    }


def _test( name: str, msg: str = "", err_type: str = "", tb: str = "" ) -> dict:
    return {
        "test_name"         : name,
        "error_message"     : msg,
        "error_type"        : err_type,
        "traceback_excerpt" : tb,
    }


def test_empty_clusters_raises():
    with pytest.raises( ValueError, match="non-empty" ):
        build_diagnosis_bundle_prompt( clusters=[] )


def test_minimal_single_cluster_renders():
    prompt = build_diagnosis_bundle_prompt(
        clusters=[ _cluster(
            "C1",
            [ _test( "src/tests/unit/test_x.py::test_foo", "assert 1 == 2" ) ],
        ) ],
    )
    # Core structural elements
    assert "# Test Fix Expediter — Phase 1: Diagnose" in prompt
    assert "## Your context" in prompt
    assert "## Available tools + guardrails" in prompt
    assert "## Clusters to diagnose" in prompt
    assert "## Output contract" in prompt
    # Cluster specifics
    assert "### Cluster C1" in prompt
    assert "test_foo" in prompt
    assert "assert 1 == 2" in prompt


def test_multi_cluster_renders_each():
    prompt = build_diagnosis_bundle_prompt(
        clusters=[
            _cluster( "C1", [ _test( "a::test_one" ) ] ),
            _cluster( "C2", [ _test( "b::test_two" ) ] ),
            _cluster( "C3", [ _test( "c::test_three" ) ] ),
        ],
    )
    assert "### Cluster C1" in prompt
    assert "### Cluster C2" in prompt
    assert "### Cluster C3" in prompt
    assert "test_one" in prompt
    assert "test_two" in prompt
    assert "test_three" in prompt


def test_tool_guardrails_are_strict():
    # The strict tool allowlist is the whole point of Phase 1 (read-only).
    prompt = build_diagnosis_bundle_prompt(
        clusters=[ _cluster( "C1", [ _test( "x", "y" ) ] ) ],
    )
    # Allowed
    assert "✅ Read" in prompt
    assert "✅ Grep" in prompt
    assert "✅ Glob" in prompt
    # Disallowed
    assert "❌ Edit" in prompt
    assert "❌ Bash" in prompt
    assert "do NOT modify" in prompt
    assert "do NOT run" in prompt
    # Blocking MCP tools should be called out as off-limits for Phase 1
    assert "cosa-voice blocking tools" in prompt
    assert "do NOT block on operator input" in prompt


def test_output_contract_mentions_fenced_block_and_schema():
    prompt = build_diagnosis_bundle_prompt(
        clusters=[ _cluster( "C1", [ _test( "x", "y" ) ] ) ],
    )
    # Fence tag operator will grep for
    assert "```tfe-diagnosis" in prompt
    # Schema fields
    for field in ( "root_cause", "error_category", "confidence", "affected_components" ):
        assert field in prompt, f"Missing schema field: {field}"
    # Categories enumerated
    for cat in ( "code_bug", "test_bug", "fixture_bug", "environment_bug" ):
        assert cat in prompt


def test_confidence_guidance_present():
    prompt = build_diagnosis_bundle_prompt(
        clusters=[ _cluster( "C1", [ _test( "x", "y" ) ] ) ],
    )
    assert "Confidence guidance" in prompt
    # Numeric ranges should be called out
    assert "0.85" in prompt


def test_shared_error_signature_renders():
    prompt = build_diagnosis_bundle_prompt(
        clusters=[ _cluster(
            "C1",
            [ _test( "x::t", "AssertionError" ) ],
            signature="AssertionError: assert 5 == 10",
        ) ],
    )
    assert "AssertionError: assert 5 == 10" in prompt
    assert "Shared error signature" in prompt


def test_affected_files_guess_renders_all_paths():
    prompt = build_diagnosis_bundle_prompt(
        clusters=[ _cluster(
            "C1",
            [ _test( "x::t" ) ],
            affected=[ "src/a.py", "src/b.py", "src/c.py" ],
        ) ],
    )
    for p in ( "src/a.py", "src/b.py", "src/c.py" ):
        assert p in prompt
    assert "Candidate affected files" in prompt


def test_traceback_excerpt_renders_in_code_fence():
    prompt = build_diagnosis_bundle_prompt(
        clusters=[ _cluster(
            "C1",
            [ _test(
                "x::t", "AssertionError",
                err_type="AssertionError",
                tb="  File \"test.py\", line 42\n    assert 5 == 10\nE   AssertionError",
            ) ],
        ) ],
    )
    assert "assert 5 == 10" in prompt
    assert "line 42" in prompt
    # Should be wrapped in a code fence
    assert "    ```" in prompt


def test_source_suite_context_renders_when_provided():
    prompt = build_diagnosis_bundle_prompt(
        clusters=[ _cluster( "C1", [ _test( "x", "y" ) ] ) ],
        failure_context={ "source_suite": "ts-d3df4d87 (smoke data)" },
    )
    assert "ts-d3df4d87" in prompt
    assert "Source suite" in prompt


def test_source_suite_context_omitted_when_absent():
    prompt = build_diagnosis_bundle_prompt(
        clusters=[ _cluster( "C1", [ _test( "x", "y" ) ] ) ],
    )
    # No Source suite line when context missing
    assert "Source suite" not in prompt


def test_prompt_is_bounded_in_size():
    # Sanity: a realistic multi-cluster prompt shouldn't blow past ~50KB.
    # This protects against accidental exponential growth if cluster data
    # gets large.
    clusters = [
        _cluster(
            f"C{i}",
            [ _test( f"src/tests/unit/test_x.py::test_{i}_{j}", "err" ) for j in range( 5 ) ],
            signature=f"Error in C{i}",
            affected=[ f"src/file_{i}_{j}.py" for j in range( 5 ) ],
        )
        for i in range( 1, 9 )
    ]
    prompt = build_diagnosis_bundle_prompt( clusters=clusters )
    # 8 clusters × 5 tests × 5 files is a worst-case realistic input. ~50KB cap.
    assert len( prompt ) < 50_000, (
        f"Prompt grew larger than expected: {len( prompt )} chars"
    )
    # Still contains the key markers
    assert prompt.count( "### Cluster" ) == 8


def test_prompt_is_deterministic():
    # Same input → same output (important for diffability + caching)
    clusters = [ _cluster(
        "C1",
        [ _test( "x::t", "err" ) ],
        signature="S",
        affected=[ "f.py" ],
    ) ]
    p1 = build_diagnosis_bundle_prompt( clusters=clusters )
    p2 = build_diagnosis_bundle_prompt( clusters=clusters )
    assert p1 == p2


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
