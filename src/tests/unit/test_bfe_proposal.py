"""
Unit tests for Bug Fix Expediter Phase 3: Proposal + Plan Artifacts.

Tests proposal prompt construction, JSON array parsing, auto-select logic,
voice gate, SDK delegation, plan writer, and proposal abstracts.
"""

import json
import os
import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.bug_fix_expediter.state import (
    BFEPhase,
    DeadJobContext,
    DiagnosisResult,
    ProposedFix,
)
from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig
from cosa.agents.bug_fix_expediter.prompts.proposal import (
    PROPOSAL_SYSTEM_PROMPT,
    build_proposal_prompt,
)
from cosa.agents.bug_fix_expediter.plan_writer import PlanWriter
from cosa.agents.bug_fix_expediter.orchestrator import (
    BFEOrchestrator,
    SDK_AVAILABLE,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def dead_job_context():
    return DeadJobContext(
        id_hash          = "dr-abc12345::user1",
        job_type         = "deep_research",
        user_id          = "user1",
        user_email       = "test@example.com",
        session_id       = "wise-penguin",
        status           = "failed",
        question_text    = "What is quantum computing?",
        error            = "KeyError: 'missing_config_key'",
        stack_trace      = "Traceback:\n  File \"cli.py\", line 42",
        metadata_json    = { "model": "opus" },
    )


@pytest.fixture
def diagnosis():
    return DiagnosisResult(
        root_cause          = "Missing config key 'missing_config_key' in lupin-app.ini",
        error_category      = "config",
        confidence          = 0.85,
        evidence            = [ "KeyError at cli.py:42", "Key not in INI" ],
        affected_components = [ "src/conf/lupin-app.ini", "cli.py" ],
    )


@pytest.fixture
def config():
    return BugFixExpediterConfig()


@pytest.fixture
def orchestrator( dead_job_context, config ):
    return BFEOrchestrator(
        dead_job_context = dead_job_context,
        extra_context    = "Worked yesterday",
        config           = config,
        session_id       = "wise-penguin",
        job_id           = "bfe-test123",
        debug            = True,
    )


@pytest.fixture
def sample_fixes():
    return [
        ProposedFix(
            title="Add missing key to INI",
            description="Add 'missing_config_key = default_value' to lupin-app.ini",
            fix_type="config_change", confidence=0.9, risk_level="low",
            estimated_effort="minimal",
            changes=[ { "file": "src/conf/lupin-app.ini", "action": "modify", "description": "Add missing key" } ],
        ),
        ProposedFix(
            title="Add fallback default in code",
            description="Use config.get() with fallback instead of direct key access",
            fix_type="code_patch", confidence=0.6, risk_level="medium",
            estimated_effort="small",
            changes=[ { "file": "cli.py", "action": "modify", "description": "Add get() fallback" } ],
        ),
    ]


VALID_PROPOSAL_JSON = json.dumps( [ {
    "title"            : "Add missing key",
    "description"      : "Add the missing config key",
    "fix_type"         : "config_change",
    "confidence"       : 0.9,
    "risk_level"       : "low",
    "estimated_effort" : "minimal",
    "changes"          : [ { "file": "config.ini", "action": "modify", "description": "Add key" } ],
} ] )


# =============================================================================
# 1. Proposal Prompt Construction (5 tests)
# =============================================================================

class TestProposalPrompt:

    def test_prompt_includes_diagnosis_root_cause( self, diagnosis, dead_job_context ):
        prompt = build_proposal_prompt( diagnosis, dead_job_context )
        assert "Missing config key" in prompt

    def test_prompt_includes_affected_components( self, diagnosis, dead_job_context ):
        prompt = build_proposal_prompt( diagnosis, dead_job_context )
        assert "src/conf/lupin-app.ini" in prompt

    def test_prompt_includes_dead_job_error( self, diagnosis, dead_job_context ):
        prompt = build_proposal_prompt( diagnosis, dead_job_context )
        assert "KeyError: 'missing_config_key'" in prompt

    def test_prompt_includes_user_feedback( self, diagnosis, dead_job_context ):
        prompt = build_proposal_prompt( diagnosis, dead_job_context, user_feedback="Try a config fix" )
        assert "Try a config fix" in prompt
        assert "rejected" in prompt.lower()

    def test_prompt_includes_extra_context( self, diagnosis, dead_job_context ):
        prompt = build_proposal_prompt( diagnosis, dead_job_context, extra_context="Worked before migration" )
        assert "Worked before migration" in prompt


# =============================================================================
# 2. JSON Array Parsing (6 tests)
# =============================================================================

class TestProposalParsing:

    def test_parse_valid_json_array( self, orchestrator ):
        result = orchestrator._parse_proposal_result( VALID_PROPOSAL_JSON )
        assert len( result ) == 1
        assert result[ 0 ].title == "Add missing key"
        assert result[ 0 ].confidence == 0.9

    def test_parse_with_markdown_fences( self, orchestrator ):
        wrapped = f"Here are my proposals:\n\n```json\n{VALID_PROPOSAL_JSON}\n```\n"
        result = orchestrator._parse_proposal_result( wrapped )
        assert len( result ) == 1
        assert result[ 0 ].title == "Add missing key"

    def test_parse_embedded_in_prose( self, orchestrator ):
        embedded = f"After investigation:\n\n{VALID_PROPOSAL_JSON}\n\nDone."
        result = orchestrator._parse_proposal_result( embedded )
        assert len( result ) == 1

    def test_parse_invalid_json_fallback( self, orchestrator ):
        result = orchestrator._parse_proposal_result( "No JSON here" )
        assert len( result ) == 1
        assert result[ 0 ].fix_type == "manual"
        assert result[ 0 ].confidence == 0.1

    def test_parse_single_element_array( self, orchestrator ):
        single = json.dumps( [ {
            "title": "Single fix", "description": "One fix only",
            "fix_type": "retry", "confidence": 0.7,
        } ] )
        result = orchestrator._parse_proposal_result( single )
        assert len( result ) == 1
        assert result[ 0 ].fix_type == "retry"

    def test_parse_all_fix_types( self, orchestrator ):
        for ft in [ "config_change", "code_patch", "retry", "manual" ]:
            data = json.dumps( [ {
                "title": f"Fix {ft}", "description": f"A {ft} fix",
                "fix_type": ft, "confidence": 0.5,
            } ] )
            result = orchestrator._parse_proposal_result( data )
            assert result[ 0 ].fix_type == ft


# =============================================================================
# 3. Auto-Select Logic (4 tests)
# =============================================================================

class TestAutoSelect:

    def test_single_high_confidence_selected( self ):
        fix = ProposedFix(
            title="Good fix", description="A good fix",
            fix_type="config_change", confidence=0.9,
        )
        result = BFEOrchestrator._auto_select_fix( [ fix ] )
        assert result == fix

    def test_single_low_confidence_not_selected( self ):
        fix = ProposedFix(
            title="Weak fix", description="A weak fix",
            fix_type="manual", confidence=0.5,
        )
        result = BFEOrchestrator._auto_select_fix( [ fix ] )
        assert result is None

    def test_multiple_fixes_not_auto_selected( self, sample_fixes ):
        result = BFEOrchestrator._auto_select_fix( sample_fixes )
        assert result is None

    def test_empty_list_not_selected( self ):
        result = BFEOrchestrator._auto_select_fix( [] )
        assert result is None


# =============================================================================
# 4. Voice Gate — Proposal (5 tests)
# =============================================================================

class TestProposalVoiceGate:

    def test_auto_approve_when_disabled( self, orchestrator, sample_fixes ):
        orchestrator.config.require_user_confirm = False
        result = asyncio.get_event_loop().run_until_complete(
            orchestrator._voice_gate_proposal( sample_fixes, MagicMock(), MagicMock() )
        )
        # Should pick highest confidence
        assert result.title == "Add missing key to INI"

    def test_auto_selected_fix_user_confirms( self, orchestrator ):
        fix = ProposedFix(
            title="Easy fix", description="Simple",
            fix_type="config_change", confidence=0.95,
        )
        mock_cosa = MagicMock()
        mock_cosa.ask_confirmation = AsyncMock( return_value=True )

        result = asyncio.get_event_loop().run_until_complete(
            orchestrator._voice_gate_proposal( [ fix ], MagicMock(), mock_cosa )
        )
        assert result == fix

    def test_multiple_fixes_user_selects( self, orchestrator, sample_fixes ):
        mock_cosa = MagicMock()
        mock_cosa.present_choices = AsyncMock( return_value={
            "answers": { "Fix Selection": "Add missing key to INI" }
        } )

        result = asyncio.get_event_loop().run_until_complete(
            orchestrator._voice_gate_proposal( sample_fixes, MagicMock(), mock_cosa )
        )
        assert result.title == "Add missing key to INI"

    def test_user_rejects_no_feedback( self, orchestrator, sample_fixes ):
        mock_cosa = MagicMock()
        mock_cosa.present_choices = AsyncMock( return_value={
            "answers": { "Fix Selection": "Reject all" }
        } )
        mock_cosa.get_feedback = AsyncMock( return_value=None )

        result = asyncio.get_event_loop().run_until_complete(
            orchestrator._voice_gate_proposal( sample_fixes, MagicMock(), mock_cosa )
        )
        assert result is None

    def test_empty_fixes_returns_none( self, orchestrator ):
        result = asyncio.get_event_loop().run_until_complete(
            orchestrator._voice_gate_proposal( [], MagicMock(), MagicMock() )
        )
        assert result is None


# =============================================================================
# 5. SDK Delegation — Proposal (3 tests)
# =============================================================================

class TestProposalSDKDelegation:

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_run_proposal_happy_path( self, orchestrator, diagnosis ):
        from claude_agent_sdk import AssistantMessage, TextBlock

        async def mock_gen( prompt, options ):
            yield AssistantMessage( content=[ TextBlock( text=VALID_PROPOSAL_JSON ) ], model="opus" )

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=mock_gen ):
            with patch.object( orchestrator, "_voice_gate_proposal", new_callable=AsyncMock ) as mock_gate:
                mock_gate.return_value = ProposedFix(
                    title="Add missing key", description="Add the missing config key",
                    fix_type="config_change", confidence=0.9,
                )
                with patch.object( PlanWriter, "write_plan", return_value="/tmp/test-plan.md" ):
                    fixes, selected, plan_path = asyncio.get_event_loop().run_until_complete(
                        orchestrator.run_proposal( diagnosis )
                    )

        assert len( fixes ) == 1
        assert fixes[ 0 ].title == "Add missing key"
        assert selected.title == "Add missing key"

    def test_run_proposal_sdk_unavailable( self, orchestrator, diagnosis ):
        with patch( "cosa.agents.bug_fix_expediter.orchestrator.SDK_AVAILABLE", False ):
            fixes, selected, plan_path = asyncio.get_event_loop().run_until_complete(
                orchestrator.run_proposal( diagnosis )
            )

        assert len( fixes ) == 1
        assert fixes[ 0 ].fix_type == "manual"
        assert selected is None

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_run_proposal_cancellation( self, orchestrator, diagnosis ):
        orchestrator._stop_requested = True

        fixes, selected, plan_path = asyncio.get_event_loop().run_until_complete(
            orchestrator.run_proposal( diagnosis )
        )

        assert len( fixes ) == 1
        assert fixes[ 0 ].fix_type == "manual"


# =============================================================================
# 6. Plan Writer (7 tests)
# =============================================================================

class TestPlanWriter:

    def test_slug_generation( self ):
        assert PlanWriter._generate_slug( "Missing config key in lupin-app.ini" ) == "missing-config-key-in-lupinappini"

    def test_slug_truncated_to_5_words( self ):
        slug = PlanWriter._generate_slug( "a b c d e f g h i j" )
        assert slug == "a-b-c-d-e"

    def test_slug_empty_string( self ):
        assert PlanWriter._generate_slug( "" ) == "unknown-fix"

    def test_plan_file_created( self, dead_job_context, diagnosis, sample_fixes ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch( "cosa.utils.util.get_project_root", return_value=tmpdir ):
                writer = PlanWriter( user_email="test@test.com" )
                plan_path = writer.write_plan( dead_job_context, diagnosis, sample_fixes )

                assert os.path.exists( plan_path )
                assert "test@test.com" in plan_path

    def test_plan_contains_diagnosis( self, dead_job_context, diagnosis, sample_fixes ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch( "cosa.utils.util.get_project_root", return_value=tmpdir ):
                writer = PlanWriter( user_email="test@test.com" )
                plan_path = writer.write_plan( dead_job_context, diagnosis, sample_fixes )

                content = open( plan_path ).read()
                assert "Missing config key" in content
                assert "KeyError" in content

    def test_plan_contains_fixes( self, dead_job_context, diagnosis, sample_fixes ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch( "cosa.utils.util.get_project_root", return_value=tmpdir ):
                writer = PlanWriter( user_email="test@test.com" )
                plan_path = writer.write_plan( dead_job_context, diagnosis, sample_fixes )

                content = open( plan_path ).read()
                assert "Add missing key to INI" in content
                assert "Add fallback default in code" in content

    def test_selected_fix_marked( self, dead_job_context, diagnosis, sample_fixes ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch( "cosa.utils.util.get_project_root", return_value=tmpdir ):
                writer = PlanWriter( user_email="test@test.com" )
                plan_path = writer.write_plan(
                    dead_job_context, diagnosis, sample_fixes,
                    selected_fix=sample_fixes[ 0 ]
                )

                content = open( plan_path ).read()
                assert "[SELECTED]" in content


# =============================================================================
# 7. Proposal Abstract (2 tests)
# =============================================================================

class TestProposalAbstract:

    def test_single_fix_abstract( self ):
        fixes = [ ProposedFix(
            title="Quick fix", description="Simple fix",
            fix_type="config_change", confidence=0.9,
        ) ]
        abstract = BFEOrchestrator._build_proposal_abstract( fixes )
        assert "Quick fix" in abstract
        assert "config_change" in abstract

    def test_multiple_fix_abstract_with_selection( self, sample_fixes ):
        abstract = BFEOrchestrator._build_proposal_abstract( sample_fixes, selected_fix=sample_fixes[ 0 ] )
        assert "[SELECTED]" in abstract
        assert "2 Fix(es)" in abstract


# =============================================================================
# 8. JSON Array Extraction (3 tests)
# =============================================================================

class TestJSONArrayExtraction:

    def test_extract_last_array( self ):
        text = 'Some text [1, 2] more text [3, 4]'
        result = BFEOrchestrator._extract_last_json_array( text )
        assert result == "[3, 4]"

    def test_no_array_returns_none( self ):
        result = BFEOrchestrator._extract_last_json_array( "No arrays here" )
        assert result is None

    def test_nested_array_handled( self ):
        text = 'text [{"a": [1, 2]}, {"b": 3}] end'
        result = BFEOrchestrator._extract_last_json_array( text )
        assert result is not None
        data = json.loads( result )
        assert len( data ) == 2
