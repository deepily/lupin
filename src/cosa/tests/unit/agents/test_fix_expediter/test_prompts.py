#!/usr/bin/env python3
"""
Unit tests for the cosa.agents.test_fix_expediter.prompts subpackage:
  - prompts.cluster    (Phase-0 LLM-refine stub)
  - prompts.diagnosis  (Phase-1 build_diagnosis_prompt + _truncate_traceback)
  - prompts.proposal   (Phase-2 build_proposal_prompt + build_proposal_system_prompt)
  - prompts.fix        (Phase-3 coder/tester/redelegate builders + shared-registry registration)

Pure string-builders — no LLM / SDK / network / disk. Inputs are real state
models where convenient and lightweight duck-typed SimpleNamespace objects where
attribute presence/absence must be controlled (the builders read attrs via
getattr with defaults). Importing prompts.fix self-registers the "tfe" bundle
into shared.fix_executor.FIX_PROMPT_BUILDERS at import time — asserted below.

quick_smoke_test + __main__ are coverage-excluded by repo config.

Created 2026-05-31 by Rachel 🕊️ (CoSA coverage campaign, TFE lane).
"""

from types import SimpleNamespace

import cosa.agents.test_fix_expediter.prompts.cluster as cl_stub
import cosa.agents.test_fix_expediter.prompts.diagnosis as dg
import cosa.agents.test_fix_expediter.prompts.proposal as pr
import cosa.agents.test_fix_expediter.prompts.fix as fx
from cosa.agents.test_fix_expediter.state import (
    FailureCluster, TestDiagnosisResult, TestRemediationContext,
)


def _ctx( failures, **over ):
    base = dict(
        source_test_suite_job_id = "ts-x", snapshot_path="p",
        snapshot                 = { "schema_version": "1.0" },
        suites_run               = [ "unit" ], summary={ "all_passed": False },
        failures                 = failures, original_test_types=[ "unit" ],
        user_id                  = "u", user_email="e@e.com", session_id="s",
    )
    base.update( over )
    return TestRemediationContext( **base )


# ============================================================================
# prompts.cluster (stub)
# ============================================================================
class TestClusterStub:
    def test_system_prompt_stub_present( self ):
        assert "triage analyst" in cl_stub.CLUSTER_SYSTEM_PROMPT_STUB
        assert "STUB" in cl_stub.CLUSTER_SYSTEM_PROMPT_STUB

    def test_build_cluster_prompt_stub_interpolates_counts( self ):
        out = cl_stub.build_cluster_prompt_stub( { "x": 1 }, [ 1, 2, 3 ], max_clusters=5 )
        assert "(STUB)" in out
        assert "3 clusters" in out
        assert "max 5" in out


# ============================================================================
# prompts.diagnosis._truncate_traceback
# ============================================================================
class TestTruncateTraceback:
    def test_empty_returns_placeholder( self ):
        assert dg._truncate_traceback( "" ) == "(no traceback available)"

    def test_short_traceback_returned_whole( self ):
        tb = "line1\nline2\nline3"
        assert dg._truncate_traceback( tb, max_lines=30 ) == tb

    def test_long_traceback_keeps_last_n( self ):
        tb  = "\n".join( f"L{i}" for i in range( 50 ) )
        out = dg._truncate_traceback( tb, max_lines=30 )
        lines = out.splitlines()
        assert len( lines ) == 30
        assert lines[ 0 ] == "L20"      # last 30 of 50
        assert lines[ -1 ] == "L49"


# ============================================================================
# prompts.diagnosis.build_diagnosis_prompt
# ============================================================================
class TestBuildDiagnosisPrompt:
    def test_iteration1_full_fields( self ):
        ctx = _ctx(
            failures=[ {
                "classname": "src.tests.unit.test_auth.TestLogin",
                "name": "test_ok", "type": "FAILED", "message": "assert 401 == 200",
                "traceback": 'File "src/cosa/auth/tokens.py", line 42, in refresh',
            } ],
            suites_run=[ "unit" ], original_pytest_args=[ "-k", "auth" ],
        )
        cluster = FailureCluster(
            cluster_id="C1", failure_indices=[ 0 ],
            shared_error_signature="sig", hypothesis="token race",
            affected_files_guess=[ "src/cosa/auth/tokens.py" ],
        )
        out = dg.build_diagnosis_prompt( cluster, ctx, iteration=1 )
        assert "Failure cluster: C1" in out
        assert "Suite: unit" in out                          # suites_run present
        assert "Heuristic hypothesis: token race" in out     # hypothesis present
        assert "Affected files (guess): src/cosa/auth/tokens.py" in out
        assert "test_ok" in out
        assert "Iteration: 1 of 4" in out
        assert "pytest args: ['-k', 'auth']" in out          # original_pytest_args present
        assert "Previous attempts" not in out                # iteration 1 -> skipped

    def test_iteration2_empty_optionals_and_previous_attempts( self ):
        # suites_run empty -> "unknown"; hypothesis "" -> else branch;
        # affected_files_guess empty -> skipped; failure missing fields -> .get defaults;
        # original_pytest_args empty -> skipped; long traceback -> truncated loop.
        long_tb = "\n".join( f"frame{i}" for i in range( 40 ) )
        ctx = _ctx(
            failures=[ { "traceback": long_tb } ],   # no classname/name/type/message
            suites_run=[], original_pytest_args=[],
        )
        cluster = FailureCluster(
            cluster_id="C2", failure_indices=[ 0 ],
            shared_error_signature="sig", hypothesis="",
            affected_files_guess=[],
        )
        priors = [
            { "root_cause": "rc-with-evidence", "error_category": "code_bug",
              "confidence": 0.55, "evidence": [ "e1", "e2" ] },
            { "root_cause": "rc-no-evidence", "error_category": "test_bug",
              "confidence": 0.4 },                       # no evidence key -> [] -> skip
        ]
        out = dg.build_diagnosis_prompt( cluster, ctx, iteration=2, previous_attempts=priors )
        assert "Suite: unknown" in out                       # suites_run empty fallback
        assert "Heuristic hypothesis: (none" in out          # else branch
        assert "Affected files (guess):" not in out          # empty -> skipped
        assert "<unknown>::<unknown>" in out                 # classname/name defaults
        assert "Type: FAILED" in out                         # type default
        assert "Message: (none)" in out                      # message default
        assert "pytest args:" not in out                     # empty args -> skipped
        assert "Previous attempts" in out                    # iteration>1 + priors
        assert "rc-with-evidence" in out
        assert "evidence: ['e1', 'e2']" in out               # evidence present arm
        assert "rc-no-evidence" in out                       # second prior, evidence skipped
        # the long traceback was truncated to its last 30 lines inside the prompt
        assert "frame39" in out
        assert "frame9" not in out

    def test_iteration2_without_previous_attempts_skips_block( self ):
        # iteration > 1 but previous_attempts is None -> `and` short-circuits -> block skipped
        ctx = _ctx( failures=[ { "classname": "A", "name": "t", "traceback": "" } ] )
        cluster = FailureCluster( cluster_id="C3", failure_indices=[ 0 ], shared_error_signature="s" )
        out = dg.build_diagnosis_prompt( cluster, ctx, iteration=2, previous_attempts=None )
        assert "Iteration: 2 of 4" in out
        assert "Previous attempts" not in out

    def test_system_prompt_teaching_points( self ):
        assert len( dg.DIAGNOSIS_SYSTEM_PROMPT ) > 1000
        assert "code_bug" in dg.DIAGNOSIS_SYSTEM_PROMPT
        assert "Output contract" in dg.DIAGNOSIS_SYSTEM_PROMPT


# ============================================================================
# prompts.proposal
# ============================================================================
class TestBuildProposalSystemPrompt:
    def test_cap_interpolated( self ):
        assert "1 to 1 alternative" in pr.build_proposal_system_prompt( 1 )
        s3 = pr.build_proposal_system_prompt( 3 )
        assert "1 to 3 alternative" in s3
        assert "code_patch" in s3
        assert "Guardrails" in s3


class TestBuildProposalPrompt:
    def _diag( self, **over ):
        base = dict(
            cluster_id="C1", root_cause="rc", error_category="code_bug",
            confidence=0.82, evidence=[], affected_components=[], test_symptoms=[],
        )
        base.update( over )
        return TestDiagnosisResult( **base )

    def test_full_optionals_present( self ):
        ctx = _ctx(
            failures=[ {
                "classname": "src.tests.unit.test_auth.TestLogin", "name": "test_ok",
                "message": "assert 401 == 200",
            } ],
            original_pytest_args=[ "-k", "auth" ],
        )
        cluster = FailureCluster( cluster_id="C1", failure_indices=[ 0 ], shared_error_signature="s" )
        diag = self._diag( evidence=[ "tokens.py:42" ],
                           affected_components=[ "src/cosa/auth/tokens.py" ],
                           test_symptoms=[ "assert 401 == 200" ] )
        out = pr.build_proposal_prompt( cluster, diag, ctx, max_proposals=3 )
        assert "Propose fixes for cluster C1" in out
        assert "Root cause: rc" in out
        assert "Confidence: 82%" in out
        assert "Evidence: ['tokens.py:42']" in out            # evidence present
        assert "Affected components:" in out                  # present
        assert "Test symptoms:" in out                        # present
        assert "src.tests.unit.test_auth.TestLogin::test_ok" in out
        assert "pytest args: ['-k', 'auth']" in out           # present
        assert "Propose 1 to 3 alternative" in out

    def test_empty_optionals_skipped( self ):
        ctx = _ctx( failures=[ {} ], original_pytest_args=[] )   # failure missing all fields
        cluster = FailureCluster( cluster_id="C9", failure_indices=[ 0 ], shared_error_signature="s" )
        diag = self._diag()   # evidence/affected_components/test_symptoms all empty
        out = pr.build_proposal_prompt( cluster, diag, ctx, max_proposals=1 )
        assert "Evidence:" not in out
        assert "Affected components:" not in out
        assert "Test symptoms:" not in out
        assert "`<unknown>::<unknown>`" in out                 # classname/name defaults
        assert "pytest args:" not in out                       # empty -> skipped
        assert "Propose 1 to 1 alternative" in out


# ============================================================================
# prompts.fix
# ============================================================================
class TestBuildFixPrompt:
    def _diag( self, affected=None ):
        return SimpleNamespace(
            root_cause="Token refresh returns None",
            error_category="code_bug",
            affected_components=affected if affected is not None else [],
        )

    def test_full_with_cluster_id_and_changes( self ):
        selected = SimpleNamespace(
            cluster_id="C1", title="Fix it", fix_type="code_patch",
            risk_level="medium", confidence=0.9, description="do the thing",
            changes=[
                { "file": "a.py", "action": "modify", "description": "line 42" },
                {},   # missing keys -> defaults "<unknown>"/"modify"/""
            ],
        )
        out = fx.build_fix_prompt( selected, self._diag( [ "a.py" ] ), SimpleNamespace( cluster_id="CX" ) )
        assert "Apply this fix for cluster C1." in out         # first-arm cluster_id
        assert "## Fix: Fix it" in out
        assert "**Type**: code_patch" in out
        assert "**Risk**: medium" in out                       # risk_level present
        assert "**Confidence**: 90%" in out
        assert "Root cause: Token refresh returns None" in out
        assert "Affected components: ['a.py']" in out          # present
        assert "1. **a.py** (modify): line 42" in out          # change with fields
        assert "2. **<unknown>** (modify): " in out            # change defaults

    def test_empty_cluster_id_falls_back_to_fix_context( self ):
        selected = SimpleNamespace(
            cluster_id="", title="T", fix_type="retry", confidence=0.5,
            description="d", changes=[],
        )   # risk_level absent -> getattr default 'low'
        out = fx.build_fix_prompt( selected, self._diag(), SimpleNamespace( cluster_id="C9" ) )
        assert "Apply this fix for cluster C9." in out         # second OR arm
        assert "**Risk**: low" in out                          # getattr default
        assert "Affected components:" not in out               # empty -> skipped
        assert "## Proposed changes: (none" in out             # changes empty -> else

    def test_missing_cluster_id_everywhere_defaults_question_mark( self ):
        selected = SimpleNamespace(
            title="T", fix_type="manual", confidence=0.3, description="d", changes=[],
        )   # no cluster_id attr at all
        out = fx.build_fix_prompt( selected, self._diag(), SimpleNamespace() )
        assert "Apply this fix for cluster C?." in out         # both missing -> "C?"


class TestBuildVerificationPrompt:
    def test_with_coder_output_and_files( self ):
        out = fx.build_verification_prompt(
            SimpleNamespace( cluster_id="C1", title="T" ),
            coder_output="Modified line 42", files_changed=[ "a.py", "b.py" ],
        )
        assert "Verify the fix for cluster C1: T" in out
        assert "Modified line 42" in out
        assert "- `a.py`" in out and "- `b.py`" in out
        assert "PASS or FAIL" in out

    def test_empty_coder_output_and_no_files( self ):
        out = fx.build_verification_prompt(
            SimpleNamespace( cluster_id="C2", title="T" ),
            coder_output="", files_changed=[],
        )
        assert "(Coder produced no summary)" in out            # empty coder_output
        assert "## Files modified" not in out                  # no files -> block skipped

    def test_missing_cluster_id_defaults( self ):
        out = fx.build_verification_prompt( SimpleNamespace( title="T" ), "x", [ "a.py" ] )
        assert "Verify the fix for cluster C?: T" in out       # getattr default


class TestBuildRedelegationPrompt:
    def test_with_outputs( self ):
        out = fx.build_redelegation_prompt(
            SimpleNamespace( cluster_id="C1" ),
            coder_output="prior changes", tester_output="tests failing", iteration=2,
        )
        assert "iteration 2" in out
        assert "prior changes" in out
        assert "tests failing" in out

    def test_empty_outputs_use_placeholders( self ):
        out = fx.build_redelegation_prompt(
            SimpleNamespace( cluster_id="C3" ),
            coder_output="", tester_output="", iteration=3,
        )
        assert "(no summary)" in out                           # empty coder_output
        assert "(no feedback)" in out                          # empty tester_output

    def test_missing_cluster_id_defaults( self ):
        out = fx.build_redelegation_prompt( SimpleNamespace(), "c", "t", iteration=2 )
        assert "cluster C?" in out


class TestFixRegistration:
    def test_tfe_bundle_registered_in_shared_registry( self ):
        from cosa.agents.shared.fix_executor import FIX_PROMPT_BUILDERS
        assert "tfe" in FIX_PROMPT_BUILDERS
        bundle = FIX_PROMPT_BUILDERS[ "tfe" ]
        assert bundle[ "coder_system_prompt" ] == fx.CODER_SYSTEM_PROMPT
        assert bundle[ "tester_system_prompt" ] == fx.TESTER_SYSTEM_PROMPT
        assert bundle[ "build_fix_prompt" ] is fx.build_fix_prompt

    def test_system_prompts_nonempty( self ):
        assert len( fx.CODER_SYSTEM_PROMPT ) > 200
        assert "pytest -k" in fx.TESTER_SYSTEM_PROMPT
