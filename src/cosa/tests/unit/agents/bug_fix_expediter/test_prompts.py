"""
Unit tests for the cosa.agents.bug_fix_expediter.prompts package.

Three pure string-builder modules (no I/O, no LLM calls):
  - diagnosis.py : DIAGNOSIS_SYSTEM_PROMPT + build_diagnosis_prompt
                   (iteration-1 initial vs iteration-2+ refinement,
                    metadata-json serializable / unserializable / absent,
                    user-message injection)
  - fix.py       : CODER/TESTER system prompts + build_fix_prompt /
                   build_verification_prompt / build_redelegation_prompt
                   (changes-table present/absent, files-changed present/absent);
                   import-time self-registration into the shared FixExecutor registry
  - proposal.py  : PROPOSAL_SYSTEM_PROMPT + build_proposal_prompt
                   (evidence/components present/absent, extra_context,
                    user_feedback retry path)

All builders are deterministic; tests assert the discriminating *content*
(which branch produced which substring), not just "no exception".
quick_smoke_test + __main__ excluded via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import unittest

from cosa.agents.bug_fix_expediter.state import (
    DeadJobContext, DiagnosisResult, ProposedFix,
)
from cosa.agents.bug_fix_expediter.prompts import diagnosis as diag_mod
from cosa.agents.bug_fix_expediter.prompts import fix as fix_mod
from cosa.agents.bug_fix_expediter.prompts import proposal as prop_mod


def _ctx( **over ):
    base = dict(
        id_hash="dr-test::u1", job_type="deep_research",
        user_id="u1", user_email="t@t.com", session_id="s1",
        status="failed", question_text="What is quantum computing?",
    )
    base.update( over )
    return DeadJobContext( **base )


def _diag( **over ):
    base = dict( root_cause="Missing config key", error_category="config", confidence=0.85 )
    base.update( over )
    return DiagnosisResult( **base )


# ===========================================================================
# diagnosis.py
# ===========================================================================
class TestDiagnosisPrompts( unittest.TestCase ):

    def test_system_prompt_constant( self ):
        self.assertGreater( len( diag_mod.DIAGNOSIS_SYSTEM_PROMPT ), 100 )
        self.assertIn( "forensic analyst", diag_mod.DIAGNOSIS_SYSTEM_PROMPT )

    def test_initial_prompt_includes_all_context_with_serializable_metadata( self ):
        ctx = _ctx( error="KeyError: 'k'", stack_trace="Trace L42",
                    metadata_json={ "model": "opus" }, duration_seconds=12.5,
                    routing_command="agent router go to deep research",
                    created_at="t0", started_at="t1", completed_at="t2" )
        out = diag_mod.build_diagnosis_prompt( ctx, extra_context="worked yesterday" )
        self.assertIn( "deep_research", out )
        self.assertIn( "KeyError", out )
        self.assertIn( "quantum computing", out )
        self.assertIn( "worked yesterday", out )
        self.assertIn( '"model": "opus"', out )       # json.dumps path
        self.assertIn( "12.5", out )
        self.assertIn( "agent router go to deep research", out )

    def test_initial_prompt_unserializable_metadata_falls_back_to_str( self ):
        # A set is not JSON-serializable → TypeError → except → str(metadata).
        unserializable = { "bad": { 1, 2, 3 } }
        ctx = _ctx( metadata_json=unserializable )
        out = diag_mod.build_diagnosis_prompt( ctx )
        # str() of the dict appears (not a clean JSON block).
        self.assertIn( "'bad'", out )

    def test_initial_prompt_none_fields_show_placeholders( self ):
        # No error / stack_trace / metadata / extra_context → placeholder text.
        ctx = _ctx( status="interrupted", question_text="2+2" )
        out = diag_mod.build_diagnosis_prompt( ctx )
        self.assertIn( "No error message available", out )
        self.assertIn( "No stack trace available", out )
        self.assertIn( "None provided", out )
        self.assertIn( "METADATA:\nNone", out )        # metadata_str stayed "None"

    def test_refinement_prompt_for_iteration_two( self ):
        ctx = _ctx()
        prior = _diag( root_cause="Missing config key", confidence=0.4 )
        out = diag_mod.build_diagnosis_prompt( ctx, iteration=2, prior_diagnosis=prior )
        self.assertIn( "40%", out )                    # confidence:.0%
        self.assertIn( "Missing config key", out )
        self.assertIn( "investigate more deeply", out.lower() )
        # Refinement path must NOT include the iteration-1 forensic header.
        self.assertNotIn( "JOB TYPE:", out )

    def test_user_messages_injected( self ):
        ctx = _ctx()
        out = diag_mod.build_diagnosis_prompt(
            ctx, user_messages=[ "Check the config file", "Maybe a typo" ]
        )
        self.assertIn( "ADDITIONAL USER INPUT", out )
        self.assertIn( "Check the config file", out )
        self.assertIn( "Maybe a typo", out )

    def test_no_user_messages_omits_section( self ):
        out = diag_mod.build_diagnosis_prompt( _ctx() )
        self.assertNotIn( "ADDITIONAL USER INPUT", out )


# ===========================================================================
# fix.py
# ===========================================================================
class TestFixPrompts( unittest.TestCase ):

    def _fix( self, **over ):
        base = dict( title="Add missing key", description="Add key to INI",
                     fix_type="config_change", confidence=0.9 )
        base.update( over )
        return ProposedFix( **base )

    def test_system_prompts( self ):
        self.assertIn( "targeted bug fix", fix_mod.CODER_SYSTEM_PROMPT )
        self.assertIn( "validating a bug fix", fix_mod.TESTER_SYSTEM_PROMPT )

    def test_fix_prompt_with_changes_builds_table( self ):
        fix = self._fix( changes=[
            { "file": "lupin-app.ini", "action": "modify", "description": "Add key" },
            { "action": "create" },   # missing file/description → "?" fallbacks
        ] )
        diag = _diag( affected_components=[ "src/conf/lupin-app.ini" ] )
        ctx  = _ctx( error="KeyError: 'k'", stack_trace="trace" )
        out  = fix_mod.build_fix_prompt( fix, diag, ctx )
        self.assertIn( "Add missing key", out )
        self.assertIn( "config_change", out )
        self.assertIn( "| File | Action | Description |", out )   # table header
        self.assertIn( "lupin-app.ini", out )
        self.assertIn( "| ? | create | ? |", out )               # ?-fallbacks
        self.assertIn( "src/conf/lupin-app.ini", out )           # components joined

    def test_fix_prompt_without_changes_says_none_specified( self ):
        fix  = self._fix( changes=[] )
        diag = _diag( affected_components=[] )                    # → "None identified"
        ctx  = _ctx()
        out  = fix_mod.build_fix_prompt( fix, diag, ctx )
        self.assertIn( "None specified", out )
        self.assertIn( "None identified", out )
        self.assertIn( "N/A", out )                              # ctx.error None → N/A

    def test_verification_prompt_with_files( self ):
        fix = self._fix()
        out = fix_mod.build_verification_prompt( fix, "Added key to INI", [ "a.py", "b.py" ] )
        self.assertIn( "Added key to INI", out )
        self.assertIn( "- a.py", out )
        self.assertIn( "- b.py", out )
        self.assertIn( "PASS or FAIL", out )

    def test_verification_prompt_without_files( self ):
        out = fix_mod.build_verification_prompt( self._fix(), "summary", [] )
        self.assertIn( "- None reported", out )

    def test_redelegation_prompt( self ):
        out = fix_mod.build_redelegation_prompt(
            self._fix(), "Prior changes", "Tests failed: KeyError", 2
        )
        self.assertIn( "iteration 2", out )
        self.assertIn( "Prior changes", out )
        self.assertIn( "Tests failed", out )
        self.assertIn( "Do NOT modify test files", out )

    def test_prompts_self_registered_into_shared_registry( self ):
        # Import-time register_fix_prompts( "bfe", ... ) must have populated the
        # shared FixExecutor registry (lines 257-266 run on module import).
        from cosa.agents.shared.fix_executor import FIX_PROMPT_BUILDERS
        self.assertIn( "bfe", FIX_PROMPT_BUILDERS )
        bundle = FIX_PROMPT_BUILDERS[ "bfe" ]
        # The exact builders this module exposes were registered (identity).
        self.assertIs( bundle[ "build_fix_prompt" ],        fix_mod.build_fix_prompt )
        self.assertIs( bundle[ "build_verify_prompt" ],     fix_mod.build_verification_prompt )
        self.assertIs( bundle[ "build_redelegate_prompt" ], fix_mod.build_redelegation_prompt )
        self.assertEqual( bundle[ "coder_system_prompt" ],  fix_mod.CODER_SYSTEM_PROMPT )
        self.assertEqual( bundle[ "tester_system_prompt" ], fix_mod.TESTER_SYSTEM_PROMPT )


# ===========================================================================
# proposal.py
# ===========================================================================
class TestProposalPrompts( unittest.TestCase ):

    def test_system_prompt_constant( self ):
        self.assertGreater( len( prop_mod.PROPOSAL_SYSTEM_PROMPT ), 100 )
        self.assertIn( "proposing fixes", prop_mod.PROPOSAL_SYSTEM_PROMPT )
        self.assertIn( "JSON array", prop_mod.PROPOSAL_SYSTEM_PROMPT )

    def test_full_context_with_evidence_and_components( self ):
        diag = _diag(
            confidence=0.85, is_transient=True,
            evidence=[ "KeyError at cli.py:42" ],
            affected_components=[ "src/conf/lupin-app.ini" ],
        )
        ctx  = _ctx( error="KeyError: 'k'", stack_trace="trace", duration_seconds=3.0 )
        out  = prop_mod.build_proposal_prompt( diag, ctx, extra_context="Worked yesterday" )
        self.assertIn( "Missing config key", out )
        self.assertIn( "85%", out )
        self.assertIn( "Yes", out )                              # is_transient True → "Yes"
        self.assertIn( "- KeyError at cli.py:42", out )          # evidence line
        self.assertIn( "- src/conf/lupin-app.ini", out )        # component line
        self.assertIn( "Worked yesterday", out )                # extra_context branch
        self.assertNotIn( "User Feedback on Previous Proposal", out )

    def test_user_feedback_retry_path( self ):
        diag = _diag()
        ctx  = _ctx()
        out  = prop_mod.build_proposal_prompt(
            diag, ctx, user_feedback="Try a different approach"
        )
        self.assertIn( "Try a different approach", out )
        self.assertIn( "rejected", out.lower() )

    def test_minimal_context_uses_placeholders( self ):
        # No evidence / components / extra_context / feedback → placeholders,
        # is_transient False → "No".
        diag = _diag( root_cause="Unknown failure", error_category="unknown",
                      confidence=0.3, is_transient=False )
        ctx  = _ctx( status="interrupted", question_text="2+2" )
        out  = prop_mod.build_proposal_prompt( diag, ctx )
        self.assertIn( "Unknown failure", out )
        self.assertIn( "No error message available", out )
        self.assertIn( "  - None", out )                        # evidence "  - None"
        self.assertIn( "None identified", out )                 # components placeholder
        self.assertIn( "**Transient**: No", out )


if __name__ == "__main__":
    unittest.main()
