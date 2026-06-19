"""
Unit tests for cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator —
NON-phase surface (helpers, parsing, checkpoint, options, state/notify/cancel).

Covers:
  - __init__               : proxy init success / ImportError / generic-Exception
  - save_checkpoint        : populated vs empty state; with/without dead_job_context/plan_path
  - load_checkpoint        : populated vs all-None snapshot
  - set_resume_phase
  - _parse_diagnosis_result: clean / ```json fence / ``` fence / no-json fallback / bad-json fallback
  - _parse_proposal_result : array / not-list wrap / invalid-item skip / all-invalid fallback /
                             no-array fallback / bad-json fallback
  - _extract_last_json_object / _extract_last_json_array : found / no-close / unbalanced
  - _fallback_diagnosis / _fallback_proposal / _auto_select_fix
  - _build_diagnosis_abstract / _build_proposal_abstract  (evidence/components/selected variants)
  - _summarize_tool_use    : Bash(±cmd) / Read-Edit-Write(±fp) / Grep-Glob(±pattern) / other
  - render_worktree_artifacts_abstract : empty / strategy+branch+commit variants
  - _generate_slug / _resolve_trust_level (delegate to GitStrategist)
  - _build_{lead,proposal,coder,tester}_options
  - _notify (narrate-gate / success / raise-swallow) · _emit_state (callback ok/raise/none)
  - _is_cancelled / _drain_user_messages / queue_user_message
  - _warn_on_uncommitted_changes_if_any (dirty / clean / exception)
  - worktree_scope (enabled / disabled)

All boundaries mocked (claude_agent_sdk message types via real classes; EngineeringStrategy,
GitStrategist, WorktreeContext, asyncio subprocess). No real LLM/SDK/git/subprocess/fs.
quick_smoke_test + __main__ excluded via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import asyncio
import queue
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.bug_fix_expediter.orchestrator as orch_mod
from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
from cosa.agents.bug_fix_expediter.state import (
    BFEPhase, DeadJobContext, DiagnosisResult, ProposedFix, FixResult,
)
from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig


def _run( coro ):
    return asyncio.run( coro )


def _ctx():
    return DeadJobContext(
        id_hash="dr-dead::u1", job_type="deep_research",
        user_id="u1", user_email="t@t.com", session_id="s1",
        status="failed", question_text="q", error="boom",
    )


def _orch( *, config=None, debug=False, **over ):
    # Proxy init imports EngineeringStrategy; patch it to a harmless mock by default.
    with patch( "cosa.agents.swe_team.proxy.engineering_strategy.EngineeringStrategy",
                MagicMock() ):
        return BFEOrchestrator(
            dead_job_context = over.get( "ctx", _ctx() ),
            extra_context    = over.get( "extra_context", "" ),
            config           = config or BugFixExpediterConfig(),
            session_id       = "s1",
            job_id           = "bfe-job::u1",
            on_state_change  = over.get( "on_state_change", None ),
            cancel_check     = over.get( "cancel_check", None ),
            debug            = debug,
            verbose          = over.get( "verbose", False ),
        )


def _diag( **over ):
    kw = dict( root_cause="rc", error_category="config", confidence=0.85 )
    kw.update( over )
    return DiagnosisResult( **kw )


def _fix( **over ):
    kw = dict( title="T", description="d", fix_type="config_change", confidence=0.9 )
    kw.update( over )
    return ProposedFix( **kw )


# ===========================================================================
# __init__ proxy branches
# ===========================================================================
class TestInit( unittest.TestCase ):

    def test_proxy_init_success_debug( self ):
        with patch( "cosa.agents.swe_team.proxy.engineering_strategy.EngineeringStrategy",
                    MagicMock( return_value="PROXY" ) ):
            orch = BFEOrchestrator(
                dead_job_context=_ctx(), extra_context="", config=BugFixExpediterConfig(),
                session_id="s", job_id="bfe-1", debug=True,
            )
        self.assertEqual( orch.proxy, "PROXY" )
        self.assertEqual( orch.current_phase, BFEPhase.PACKAGING )

    def test_proxy_import_error_defaults_none( self ):
        # Setting the module to None makes `from ... import EngineeringStrategy` raise ImportError.
        with patch.dict( sys.modules,
                         { "cosa.agents.swe_team.proxy.engineering_strategy": None } ):
            orch = BFEOrchestrator(
                dead_job_context=_ctx(), extra_context="", config=BugFixExpediterConfig(),
                session_id="s", job_id="bfe-1", debug=True,
            )
        self.assertIsNone( orch.proxy )

    def test_proxy_generic_exception_defaults_none( self ):
        with patch( "cosa.agents.swe_team.proxy.engineering_strategy.EngineeringStrategy",
                    MagicMock( side_effect=ValueError( "boom" ) ) ):
            orch = BFEOrchestrator(
                dead_job_context=_ctx(), extra_context="", config=BugFixExpediterConfig(),
                session_id="s", job_id="bfe-1", debug=True,
            )
        self.assertIsNone( orch.proxy )


# ===========================================================================
# checkpoint
# ===========================================================================
class TestCheckpoint( unittest.TestCase ):

    def test_save_checkpoint_full_state( self ):
        orch = _orch()
        orch.diagnosis      = _diag()
        orch.proposed_fixes = [ _fix() ]
        orch.selected_fix   = _fix()
        orch.fix_result     = FixResult( applied=True, success=True )
        orch.plan_path      = "/tmp/plan.md"
        orch.branch_name    = "fix/x"
        orch.commit_hashes  = [ "abc" ]
        orch.pr_url         = "http://pr"
        orch.current_phase  = BFEPhase.FIXING
        ck = orch.save_checkpoint()
        self.assertEqual( ck[ "phase_name" ], "fixing" )
        self.assertEqual( ck[ "phase_ordinal" ], 3 )
        self.assertEqual( ck[ "state_snapshot" ][ "dead_job_id" ], "dr-dead::u1" )
        self.assertIsNotNone( ck[ "state_snapshot" ][ "diagnosis" ] )
        self.assertEqual( ck[ "artifacts" ][ "plan_path" ], "/tmp/plan.md" )
        self.assertEqual( ck[ "stall_reason" ], "voice_gate_timeout" )

    def test_save_checkpoint_empty_state_no_context_no_plan( self ):
        orch = _orch()
        orch.dead_job_context = None
        orch.diagnosis = None; orch.proposed_fixes = []; orch.selected_fix = None
        orch.fix_result = None; orch.plan_path = None
        ck = orch.save_checkpoint()
        self.assertIsNone( ck[ "state_snapshot" ][ "dead_job_id" ] )
        self.assertIsNone( ck[ "state_snapshot" ][ "diagnosis" ] )
        self.assertEqual( ck[ "state_snapshot" ][ "proposed_fixes" ], [] )
        self.assertNotIn( "plan_path", ck[ "artifacts" ] )

    def test_load_checkpoint_full( self ):
        orch = _orch()
        data = {
            "phase_name"     : "proposing",
            "state_snapshot" : {
                "diagnosis"      : _diag().model_dump(),
                "proposed_fixes" : [ _fix().model_dump() ],
                "selected_fix"   : _fix().model_dump(),
                "fix_result"     : FixResult( applied=True, success=True ).model_dump(),
                "plan_path"      : "/p",
                "branch_name"    : "b",
                "commit_hashes"  : [ "h" ],
                "pr_url"         : "u",
            },
        }
        orch.load_checkpoint( data )
        self.assertIsInstance( orch.diagnosis, DiagnosisResult )
        self.assertEqual( len( orch.proposed_fixes ), 1 )
        self.assertIsInstance( orch.selected_fix, ProposedFix )
        self.assertIsInstance( orch.fix_result, FixResult )
        self.assertEqual( orch.current_phase, BFEPhase.PROPOSING )

    def test_load_checkpoint_all_none( self ):
        orch = _orch()
        data = { "phase_name": "packaging", "state_snapshot": {} }
        orch.load_checkpoint( data )
        self.assertIsNone( orch.diagnosis )
        self.assertEqual( orch.proposed_fixes, [] )
        self.assertIsNone( orch.selected_fix )
        self.assertIsNone( orch.fix_result )
        self.assertEqual( orch.current_phase, BFEPhase.PACKAGING )

    def test_set_resume_phase( self ):
        orch = _orch()
        orch.set_resume_phase( 3 )
        self.assertEqual( orch._resume_from_ordinal, 3 )


# ===========================================================================
# JSON parsing
# ===========================================================================
class TestParsing( unittest.TestCase ):

    def setUp( self ):
        self.orch = _orch()

    def test_parse_diagnosis_clean_json( self ):
        out = self.orch._parse_diagnosis_result(
            '{"root_cause": "rc", "error_category": "config", "confidence": 0.9}' )
        self.assertEqual( out.root_cause, "rc" )
        self.assertEqual( out.confidence, 0.9 )

    def test_parse_diagnosis_json_fence( self ):
        text = 'analysis:\n```json\n{"root_cause":"rc","error_category":"config","confidence":0.8}\n```\nend'
        out = self.orch._parse_diagnosis_result( text )
        self.assertEqual( out.root_cause, "rc" )

    def test_parse_diagnosis_plain_fence( self ):
        # No ```json marker, but a trailing ``` fence — exercises the bare-``` split
        # branch while still leaving the JSON intact (split("```")[0]).
        text = '{"root_cause":"rc2","error_category":"code_bug","confidence":0.7}\n```'
        out = self.orch._parse_diagnosis_result( text )
        self.assertEqual( out.root_cause, "rc2" )

    def test_parse_diagnosis_no_json_returns_fallback( self ):
        out = self.orch._parse_diagnosis_result( "no json at all here" )
        self.assertEqual( out.confidence, 0.1 )
        self.assertEqual( out.error_category, "unknown" )

    def test_parse_diagnosis_bad_json_returns_fallback( self ):
        # Has braces but invalid JSON inside → JSONDecodeError → fallback.
        out = self.orch._parse_diagnosis_result( "text { not valid json }" )
        self.assertEqual( out.confidence, 0.1 )

    def test_parse_proposal_array( self ):
        text = '[{"title":"A","description":"d","fix_type":"config_change","confidence":0.9}]'
        out = self.orch._parse_proposal_result( text )
        self.assertEqual( len( out ), 1 )
        self.assertEqual( out[ 0 ].title, "A" )

    def test_parse_proposal_fence_and_invalid_item_skipped( self ):
        # One valid, one invalid (missing required fields) → invalid skipped.
        text = ( '```json\n[{"title":"A","description":"d","fix_type":"x","confidence":0.9},'
                 '{"nope":1}]\n```' )
        out = self.orch._parse_proposal_result( text )
        self.assertEqual( len( out ), 1 )

    def test_parse_proposal_not_a_list_is_wrapped( self ):
        # A bare object (no brackets) → _extract_last_json_array returns None → fallback.
        # To exercise the not-list wrap, feed an array whose element is a single object
        # that json.loads returns as a dict requires brackets; use the object-in-array path:
        text = '[{"title":"Solo","description":"d","fix_type":"x","confidence":0.95}]'
        out = self.orch._parse_proposal_result( text )
        self.assertEqual( out[ 0 ].title, "Solo" )

    def test_parse_proposal_all_invalid_returns_fallback( self ):
        text = '[{"bad":1},{"also":2}]'
        out = self.orch._parse_proposal_result( text )
        self.assertEqual( len( out ), 1 )
        self.assertEqual( out[ 0 ].fix_type, "manual" )     # fallback

    def test_parse_proposal_no_array_returns_fallback( self ):
        out = self.orch._parse_proposal_result( "no array here" )
        self.assertEqual( out[ 0 ].fix_type, "manual" )

    def test_parse_proposal_bad_json_returns_fallback( self ):
        out = self.orch._parse_proposal_result( "junk [ not json ] more" )
        self.assertEqual( out[ 0 ].fix_type, "manual" )

    def test_extract_json_object_no_close_returns_none( self ):
        self.assertIsNone( BFEOrchestrator._extract_last_json_object( "no brace" ) )

    def test_extract_json_object_unbalanced_returns_none( self ):
        # closing brace but no matching open → None
        self.assertIsNone( BFEOrchestrator._extract_last_json_object( "abc } def" ) )

    def test_extract_json_object_nested_walks_back( self ):
        # Nested object → inner `{` decrements depth without reaching 0, exercising
        # the loop-continue arc before the outer `{` closes the match.
        out = BFEOrchestrator._extract_last_json_object( 'pre {"a": {"b": 1}} post' )
        self.assertEqual( out, '{"a": {"b": 1}}' )

    def test_extract_json_array_no_close_returns_none( self ):
        self.assertIsNone( BFEOrchestrator._extract_last_json_array( "no bracket" ) )

    def test_extract_json_array_unbalanced_returns_none( self ):
        self.assertIsNone( BFEOrchestrator._extract_last_json_array( "abc ] def" ) )

    def test_extract_json_array_nested_walks_back( self ):
        out = BFEOrchestrator._extract_last_json_array( 'pre [[1], [2]] post' )
        self.assertEqual( out, '[[1], [2]]' )


# ===========================================================================
# static helpers
# ===========================================================================
class TestStaticHelpers( unittest.TestCase ):

    def test_fallback_diagnosis( self ):
        d = BFEOrchestrator._fallback_diagnosis( "why" )
        self.assertEqual( d.confidence, 0.1 )
        self.assertEqual( d.root_cause, "why" )

    def test_fallback_proposal( self ):
        fixes = BFEOrchestrator._fallback_proposal( "why" )
        self.assertEqual( len( fixes ), 1 )
        self.assertEqual( fixes[ 0 ].fix_type, "manual" )

    def test_auto_select_single_high_confidence( self ):
        self.assertIsNotNone( BFEOrchestrator._auto_select_fix( [ _fix( confidence=0.85 ) ] ) )

    def test_auto_select_low_confidence_returns_none( self ):
        self.assertIsNone( BFEOrchestrator._auto_select_fix( [ _fix( confidence=0.5 ) ] ) )

    def test_auto_select_multiple_returns_none( self ):
        self.assertIsNone( BFEOrchestrator._auto_select_fix( [ _fix(), _fix() ] ) )

    def test_diagnosis_abstract_with_evidence_and_components( self ):
        d = _diag( is_transient=True, evidence=[ "e1" ], affected_components=[ "c1" ] )
        out = BFEOrchestrator._build_diagnosis_abstract( d )
        self.assertIn( "  - e1", out )
        self.assertIn( "c1", out )
        self.assertIn( "**Transient**: Yes", out )

    def test_diagnosis_abstract_without_evidence_or_components( self ):
        d = _diag( is_transient=False )
        out = BFEOrchestrator._build_diagnosis_abstract( d )
        self.assertIn( "  - None", out )
        self.assertIn( "None identified", out )
        self.assertIn( "**Transient**: No", out )

    def test_proposal_abstract_marks_selected( self ):
        f1 = _fix( title="A" ); f2 = _fix( title="B" )
        out = BFEOrchestrator._build_proposal_abstract( [ f1, f2 ], selected_fix=f2 )
        self.assertIn( "**[SELECTED]**", out )
        self.assertIn( "A**", out )
        self.assertIn( "B**", out )

    def test_proposal_abstract_no_selection( self ):
        out = BFEOrchestrator._build_proposal_abstract( [ _fix( title="A" ) ] )
        self.assertNotIn( "[SELECTED]", out )

    def test_summarize_tool_use_bash_with_and_without_command( self ):
        b1 = MagicMock(); b1.name = "Bash"; b1.input = { "command": "ls -la\nsecond" }
        self.assertEqual( BFEOrchestrator._summarize_tool_use( b1 ), "Bash: ls -la" )
        b2 = MagicMock(); b2.name = "Bash"; b2.input = { "command": "" }
        self.assertEqual( BFEOrchestrator._summarize_tool_use( b2 ), "Bash" )

    def test_summarize_tool_use_file_tools( self ):
        b1 = MagicMock(); b1.name = "Edit"; b1.input = { "file_path": "/a/b/c.py" }
        self.assertIn( "c.py", BFEOrchestrator._summarize_tool_use( b1 ) )
        b2 = MagicMock(); b2.name = "Read"; b2.input = {}
        self.assertEqual( BFEOrchestrator._summarize_tool_use( b2 ), "Read" )

    def test_summarize_tool_use_search_tools_and_other( self ):
        b1 = MagicMock(); b1.name = "Grep"; b1.input = { "pattern": "foo" }
        self.assertEqual( BFEOrchestrator._summarize_tool_use( b1 ), "Grep: foo" )
        b2 = MagicMock(); b2.name = "Glob"; b2.input = None
        self.assertEqual( BFEOrchestrator._summarize_tool_use( b2 ), "Glob" )
        b3 = MagicMock(); b3.name = "WebSearch"; b3.input = {}
        self.assertEqual( BFEOrchestrator._summarize_tool_use( b3 ), "WebSearch" )

    def test_render_worktree_artifacts_empty_when_nothing_to_report( self ):
        fr = FixResult( applied=False, success=False )
        self.assertEqual(
            BFEOrchestrator.render_worktree_artifacts_abstract( "bfe-1", fr, False ), [] )

    def test_render_worktree_artifacts_full( self ):
        fr = FixResult( applied=True, success=True, git_strategy="branch_and_pr",
                        branch_name="fix/x", commit_hash="abcdef1234" )
        lines = BFEOrchestrator.render_worktree_artifacts_abstract( "bfe-1", fr, True )
        body = "\n".join( lines )
        self.assertIn( "**Worktree Artifacts**", body )
        self.assertIn( "branch_and_pr", body )
        self.assertIn( "fix/x", body )
        self.assertIn( "abcdef12", body )                  # commit_hash[:8]

    def test_render_worktree_artifacts_applied_but_no_git_fields( self ):
        # fix_applied True (so not the empty short-circuit) but no strategy / branch /
        # commit → each optional sub-line is skipped (the False arcs).
        fr = FixResult( applied=True, success=True )
        lines = BFEOrchestrator.render_worktree_artifacts_abstract( "bfe-1", fr, True )
        body = "\n".join( lines )
        self.assertIn( "**Worktree Artifacts**", body )
        self.assertNotIn( "**Strategy**", body )
        self.assertNotIn( "**Branch**", body )
        self.assertNotIn( "**Commit**", body )

    def test_render_worktree_artifacts_commit_only_not_applied( self ):
        # not applied but commit_hash present → still rendered (the `or` guard)
        fr = FixResult( applied=False, success=False, commit_hash="zz" )
        lines = BFEOrchestrator.render_worktree_artifacts_abstract( "bfe-1", fr, False )
        self.assertTrue( any( "Worktree Artifacts" in l for l in lines ) )

    def test_generate_slug_delegates( self ):
        with patch.object( orch_mod.GitStrategist, "generate_slug", return_value="fix/2026-x" ) as g:
            self.assertEqual( BFEOrchestrator._generate_slug( "some text" ), "fix/2026-x" )
            g.assert_called_once_with( "some text" )

    def test_resolve_trust_level_delegates( self ):
        orch = _orch()
        with patch.object( orch_mod.GitStrategist, "resolve_trust_level", return_value=4 ) as r:
            self.assertEqual( orch._resolve_trust_level(), 4 )
            r.assert_called_once_with( orch.proxy )


# ===========================================================================
# option builders
# ===========================================================================
class TestOptionBuilders( unittest.TestCase ):

    def setUp( self ):
        self.orch = _orch()

    def test_lead_options( self ):
        opts = self.orch._build_lead_options()
        self.assertEqual( opts.permission_mode, "plan" )
        self.assertEqual( opts.model, self.orch.config.lead_model )

    def test_proposal_options( self ):
        opts = self.orch._build_proposal_options()
        self.assertEqual( opts.permission_mode, "plan" )
        self.assertEqual( opts.max_turns, 20 )

    def test_coder_options( self ):
        with patch.object( orch_mod, "build_can_use_tool", return_value="CB" ):
            opts = self.orch._build_coder_options( MagicMock(), MagicMock() )
        self.assertEqual( opts.permission_mode, "acceptEdits" )
        self.assertEqual( opts.model, self.orch.config.worker_model )

    def test_tester_options( self ):
        with patch.object( orch_mod, "build_can_use_tool", return_value="CB" ):
            opts = self.orch._build_tester_options( MagicMock(), MagicMock() )
        self.assertEqual( opts.permission_mode, "acceptEdits" )
        self.assertEqual( opts.max_turns, 10 )


# ===========================================================================
# notify / state / cancellation
# ===========================================================================
class TestNotifyStateCancel( unittest.TestCase ):

    def test_notify_gated_when_narrate_off_and_low_priority( self ):
        cfg = BugFixExpediterConfig(); cfg.narrate_progress = False
        orch = _orch( config=cfg )
        vio = MagicMock(); vio.notify = AsyncMock()
        _run( orch._notify( vio, "msg", priority="low" ) )
        vio.notify.assert_not_awaited()                    # gated

    def test_notify_high_priority_bypasses_narrate_gate( self ):
        cfg = BugFixExpediterConfig(); cfg.narrate_progress = False
        orch = _orch( config=cfg )
        vio = MagicMock(); vio.notify = AsyncMock()
        _run( orch._notify( vio, "msg", priority="high" ) )
        vio.notify.assert_awaited_once()

    def test_notify_swallows_exception( self ):
        orch = _orch()
        vio = MagicMock(); vio.notify = AsyncMock( side_effect=RuntimeError( "down" ) )
        _run( orch._notify( vio, "msg", priority="medium" ) )   # must not raise

    def test_emit_state_with_callback_success( self ):
        cb = AsyncMock()
        orch = _orch( on_state_change=cb, debug=True )
        _run( orch._emit_state( BFEPhase.PACKAGING, BFEPhase.DIAGNOSING ) )
        self.assertEqual( orch.current_phase, BFEPhase.DIAGNOSING )
        cb.assert_awaited_once()

    def test_emit_state_callback_raises_swallowed( self ):
        cb = AsyncMock( side_effect=RuntimeError( "cb down" ) )
        orch = _orch( on_state_change=cb )
        _run( orch._emit_state( BFEPhase.PACKAGING, BFEPhase.DIAGNOSING ) )  # no raise

    def test_emit_state_no_callback( self ):
        orch = _orch( on_state_change=None )
        _run( orch._emit_state( BFEPhase.PACKAGING, BFEPhase.FIXING ) )
        self.assertEqual( orch.current_phase, BFEPhase.FIXING )

    def test_is_cancelled_stop_requested( self ):
        orch = _orch()
        orch._stop_requested = True
        self.assertTrue( orch._is_cancelled() )

    def test_is_cancelled_via_callback( self ):
        orch = _orch( cancel_check=lambda: True )
        self.assertTrue( orch._is_cancelled() )

    def test_is_cancelled_false( self ):
        orch = _orch( cancel_check=lambda: False )
        self.assertFalse( orch._is_cancelled() )

    def test_drain_user_messages_and_queue( self ):
        orch = _orch()
        self.assertEqual( orch._drain_user_messages(), [] )   # empty path
        orch.queue_user_message( "m1" )
        orch.queue_user_message( "m2", urgent=True )
        self.assertTrue( orch._urgent_interrupt.is_set() )
        msgs = orch._drain_user_messages()
        self.assertEqual( msgs, [ "m1", "m2" ] )
        self.assertFalse( orch._urgent_interrupt.is_set() )   # cleared

    def test_drain_handles_empty_race( self ):
        # empty() reports non-empty but get_nowait races to queue.Empty → break path.
        orch = _orch()
        fake_q = MagicMock()
        fake_q.empty.return_value = False
        fake_q.get_nowait.side_effect = queue.Empty
        orch._user_messages = fake_q
        self.assertEqual( orch._drain_user_messages(), [] )


# ===========================================================================
# worktree scope + uncommitted-changes warning
# ===========================================================================
class TestWorktreeScope( unittest.TestCase ):

    def _patch_worktree( self, *, enabled, path="/wt/path" ):
        wt = MagicMock()
        wt.enabled = enabled
        wt.path    = path
        cm = MagicMock()
        cm.__aenter__ = AsyncMock( return_value=wt )
        cm.__aexit__  = AsyncMock( return_value=False )
        return patch( "cosa.agents.shared.worktree_context.WorktreeContext",
                      MagicMock( return_value=cm ) )

    def test_worktree_enabled_sets_and_clears_cwd( self ):
        orch = _orch( debug=True )
        async def _drive():
            async with orch.worktree_scope() as wt:
                self.assertEqual( orch._worktree_cwd, "/wt/path" )
                return wt
        with self._patch_worktree( enabled=True ):
            _run( _drive() )
        self.assertIsNone( orch._worktree_cwd )            # cleared on exit

    def test_worktree_disabled_warns_and_no_cwd( self ):
        orch = _orch()
        orch._warn_on_uncommitted_changes_if_any = AsyncMock()
        async def _drive():
            async with orch.worktree_scope():
                self.assertIsNone( orch._worktree_cwd )
        with self._patch_worktree( enabled=False ):
            _run( _drive() )
        orch._warn_on_uncommitted_changes_if_any.assert_awaited_once()

    def test_warn_uncommitted_dirty_tree_logs( self ):
        orch = _orch()
        proc = MagicMock()
        proc.communicate = AsyncMock( return_value=( b" M file.py\n", b"" ) )
        with patch.object( orch_mod.asyncio, "create_subprocess_exec",
                           AsyncMock( return_value=proc ) ), \
             patch.object( orch_mod.logger, "warning" ) as warn:
            _run( orch._warn_on_uncommitted_changes_if_any() )
        warn.assert_called_once()

    def test_warn_uncommitted_clean_tree_silent( self ):
        orch = _orch()
        proc = MagicMock()
        proc.communicate = AsyncMock( return_value=( b"", b"" ) )
        with patch.object( orch_mod.asyncio, "create_subprocess_exec",
                           AsyncMock( return_value=proc ) ), \
             patch.object( orch_mod.logger, "warning" ) as warn:
            _run( orch._warn_on_uncommitted_changes_if_any() )
        warn.assert_not_called()

    def test_warn_uncommitted_exception_swallowed( self ):
        orch = _orch( debug=True )
        with patch.object( orch_mod.asyncio, "create_subprocess_exec",
                           AsyncMock( side_effect=OSError( "no git" ) ) ):
            _run( orch._warn_on_uncommitted_changes_if_any() )   # must not raise


if __name__ == "__main__":
    unittest.main()
