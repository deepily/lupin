"""
Unit tests for the tfe_to_cc Phase 1 + Phase 3 bundle-prompt builders.

Pure string builders — no LLM / network / fs seams, ZERO API spend.
Coverage target: 100% lines + branches + functions on production logic.
quick_smoke_test() / __main__ blocks are excluded by the coverage config.
"""
import pytest

from cosa.agents.tfe_to_cc.prompts.bundle_phase1 import build_diagnosis_bundle_prompt
from cosa.agents.tfe_to_cc.prompts.bundle_phase3 import build_fix_bundle_prompt


# =========================================================================== #
# build_diagnosis_bundle_prompt  ( Phase 1 )
# =========================================================================== #
def test_phase1_empty_clusters_raises():
    with pytest.raises( ValueError, match="clusters must be non-empty" ):
        build_diagnosis_bundle_prompt( [] )


def test_phase1_full_cluster_all_fields_and_source_suite():
    # source_suite present ( 56 True ); sig present ( 91 ); affected present ( 95 );
    # test with error_type + error_message + traceback ( 107/110/113 True arcs )
    clusters = [ {
        "cluster_id"             : "C1",
        "failure_count"          : 2,
        "shared_error_signature" : "AssertionError: 1 != 2",
        "affected_files_guess"   : [ "src/foo.py", "src/bar.py" ],
        "failing_tests"          : [ {
            "test_name"         : "test_alpha",
            "error_type"        : "AssertionError",
            "error_message"     : "1 != 2",
            "traceback_excerpt" : "line one\nline two",
        } ],
    } ]
    prompt = build_diagnosis_bundle_prompt( clusters, failure_context={ "source_suite": "unit" } )
    assert "Phase 1: Diagnose" in prompt
    assert "Source suite: `unit`" in prompt
    assert "### Cluster C1 — 2 failing test(s)" in prompt
    assert "**Shared error signature**: `AssertionError: 1 != 2`" in prompt
    assert "- `src/foo.py`" in prompt
    assert "- `test_alpha`" in prompt
    assert "Error type: `AssertionError`" in prompt
    assert "Error message: `1 != 2`" in prompt
    assert "Traceback excerpt:" in prompt
    assert "    line one" in prompt          # traceback line indented
    assert "```tfe-diagnosis" in prompt      # output contract present


def test_phase1_minimal_cluster_defaults_and_no_source():
    # failure_context None ( 41 → {} ); source absent ( 56 False );
    # failing_tests missing → [] ( 83 'or []' falsy arc ); affected missing ( 95 False );
    # sig absent ( 91 False ); failure_count absent → len(failing)=0 ( 84 );
    # a test with only test_name → err_type/err_msg/tb all absent ( False arcs )
    clusters = [
        { "cluster_id": "C2" },  # no failing_tests, no sig, no affected
        { "cluster_id": "C3", "failing_tests": [ { "test_name": "test_bare" } ] },
    ]
    prompt = build_diagnosis_bundle_prompt( clusters )
    assert "Source suite:" not in prompt
    assert "### Cluster C2 — 0 failing test(s)" in prompt
    assert "**Shared error signature**" not in prompt
    assert "Candidate affected files" not in prompt
    assert "- `test_bare`" in prompt
    assert "Error type:" not in prompt
    assert "Error message:" not in prompt
    assert "Traceback excerpt:" not in prompt


def test_phase1_failing_tests_none_coerced_to_empty():
    # failing_tests explicitly None → 'or []' falsy arc, affected_files_guess None too
    clusters = [ { "cluster_id": "C9", "failing_tests": None, "affected_files_guess": None } ]
    prompt = build_diagnosis_bundle_prompt( clusters )
    assert "### Cluster C9 — 0 failing test(s)" in prompt


# =========================================================================== #
# build_fix_bundle_prompt  ( Phase 3 )
# =========================================================================== #
def test_phase3_empty_fixes_raises():
    with pytest.raises( ValueError, match="selected_fixes must be non-empty" ):
        build_fix_bundle_prompt( [], {}, "/var/lupin/wt" )


def test_phase3_full_breadcrumbs_escalation_and_source():
    # source_suite present ( 70 ); emit_breadcrumbs True ( 84/144 ); allow_mcp_escalation True ( 106 );
    # confidence float → ':.0%' arc ( 196 True ); target_files + failing_tests present ( 203/204 truthy );
    # diagnoses has the cluster → 'or {}' truthy arc ( 192 )
    fixes = [ {
        "cluster_id"    : "C1",
        "title"         : "repair stale assertion",
        "fix_type"      : "test_patch",
        "confidence"    : 0.92,
        "description"   : "update the expected value",
        "target_files"  : [ "src/foo_test.py" ],
        "failing_tests" : [ "test_alpha" ],
    } ]
    diagnoses = { "C1": { "root_cause": "stale expected value", "error_category": "test_bug" } }
    prompt = build_fix_bundle_prompt(
        fixes, diagnoses, "/var/lupin/wt",
        source_suite="unit", emit_breadcrumbs=True, allow_mcp_escalation=True,
    )
    assert "Apply 1 fixes in parallel" in prompt
    assert "Working directory (CWD): `/var/lupin/wt`" in prompt
    assert "Source test suite: `unit`" in prompt
    assert "Emit progress breadcrumbs" in prompt        # emit_breadcrumbs True (coordinator)
    assert "Progress breadcrumbs (optional" in prompt   # emit_breadcrumbs True (subagent brief)
    assert "ask_yes_no" in prompt                        # allow_mcp_escalation True
    assert "### Fix 1: `C1` — repair stale assertion" in prompt
    assert "**confidence**: 92%" in prompt               # float formatted
    assert "**error_category**: test_bug" in prompt
    assert "src/foo_test.py" in prompt
    assert "test_alpha" in prompt
    assert "stale expected value" in prompt              # root_cause from diagnoses
    assert "```tfe-result" in prompt


def test_phase3_minimal_flags_false_and_defaults():
    # source_suite absent ( 70 False ); emit_breadcrumbs False ( 90/144 else ); allow_mcp_escalation False ( 106 False );
    # confidence missing → '?' default → str(conf) arc ( 196 False ); target_files / failing_tests missing → ternary else;
    # diagnoses empty → diag={} → root_cause + error_category defaults ( 192 'or {}' falsy arc )
    fixes = [ { "cluster_id": "C2", "title": "bare fix" } ]
    prompt = build_fix_bundle_prompt(
        fixes, {}, "/var/lupin/wt2",
        emit_breadcrumbs=False, allow_mcp_escalation=False,
    )
    assert "Source test suite:" not in prompt
    assert "Progress notifications not required" in prompt   # emit_breadcrumbs False branch
    assert "Progress breadcrumbs (optional" not in prompt
    assert "ask_yes_no" not in prompt                        # escalation off
    assert "**fix_type**: code_patch" in prompt              # fix_type default
    assert "**confidence**: ?" in prompt                     # str(conf) default arc
    assert "**error_category**: unknown" in prompt           # diag default
    assert "(no Phase 1 diagnosis" in prompt                 # root_cause default
    assert "(none named — subagent may discover" in prompt   # target_files empty ternary
    assert "(none captured — subagent may omit" in prompt    # failing_tests empty ternary


def test_phase3_confidence_int_formats_as_percent():
    # confidence int is also isinstance(...,(float,int)) → ':.0%' arc
    fixes = [ { "cluster_id": "C5", "title": "t", "confidence": 1 } ]
    prompt = build_fix_bundle_prompt( fixes, {}, "/wt" )
    assert "**confidence**: 100%" in prompt


def test_phase3_target_files_and_tests_none_use_ternary_else():
    fixes = [ { "cluster_id": "C7", "title": "t", "target_files": None, "failing_tests": None } ]
    prompt = build_fix_bundle_prompt( fixes, {}, "/wt" )
    assert "(none named — subagent may discover" in prompt
    assert "(none captured — subagent may omit" in prompt


def test_phase3_custom_commit_identity_rendered():
    fixes = [ { "cluster_id": "C1", "title": "t" } ]
    prompt = build_fix_bundle_prompt(
        fixes, {}, "/wt",
        commit_author_email="me@x.com", commit_author_name="Me",
    )
    assert 'user.email="me@x.com"' in prompt
    assert 'user.name="Me"' in prompt
