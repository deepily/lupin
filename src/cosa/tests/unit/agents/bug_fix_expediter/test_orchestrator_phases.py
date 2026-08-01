"""
Unit tests for cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator —
the ASYNC PHASE methods (SDK delegation + pipeline control flow).

Covers:
  - run_diagnosis        : SDK-unavailable · happy break · cancel-in-loop ·
                           low-confidence refine · all-None→fallback ·
                           voice-gate-timeout→StalledException · cancel-before-gate ·
                           user-messages+debug
  - _delegate_to_lead    : assistant text/tool-use · top-level TextBlock · ResultMessage ·
                           RateLimitEvent · empty→None · exception→None
  - run_proposal         : SDK-unavailable · cancelled · delegate-None→fallback ·
                           plan-write-exception · voice-gate-timeout→Stalled ·
                           selected→plan-rewrite (ok + exception)
  - _voice_gate_diagnosis: auto-approve · approved · timeout-reraise · other-exc-autoapprove ·
                           rejected→feedback(exc / none / refine-higher / refine-not-higher)
  - _voice_gate_proposal : no-fixes · auto-select(confirm/timeout/other-exc) ·
                           multiple→choices(found / exception) · feedback(exc/none/revise±diag) ·
                           require_user_confirm=False auto-best
  - run_fix              : SDK-unavailable · success · failure · plan-update-exception
  - run_git_strategy     : skip(not-success / no-files) · success+field-apply · finalize
  - _finalize_git_strategy: plan ok / exception
  - _delegate_to_coder   : edit/write tracking · cancel-break · ResultMessage · RateLimit ·
                           SafetyLimitError-reraise · generic-exc→("",[])
  - _verify_fix          : pass/fail self-report · pytest override · SafetyLimitError · exception

sdk_query + all collaborators (FixExecutor, GitStrategist, PlanWriter, GitOps, run_pytest,
post_tool_hook, voice_io, cosa_interface) mocked at the boundary — no real LLM/SDK/git/fs.
quick_smoke_test + __main__ excluded via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.bug_fix_expediter.orchestrator as orch_mod
import cosa.agents.bug_fix_expediter.voice_io as vio_mod
from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
from cosa.agents.bug_fix_expediter.state import (
    BFEPhase, DeadJobContext, DiagnosisResult, ProposedFix, FixResult,
)
from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig
from cosa.agents.test_fix_expediter.state import (
    VoiceGateTimeoutError, VoiceGateUnreachableError, StalledException,
)

from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock


def _run( coro ):
    return asyncio.run( coro )


def _ctx():
    return DeadJobContext(
        id_hash="dr-dead::u1", job_type="deep_research",
        user_id="u1", user_email="t@t.com", session_id="s1",
        status="failed", question_text="q", error="boom",
    )


def _orch( *, config=None, debug=False, **over ):
    with patch( "cosa.agents.swe_team.proxy.engineering_strategy.EngineeringStrategy",
                MagicMock() ):
        return BFEOrchestrator(
            dead_job_context = over.get( "ctx", _ctx() ),
            extra_context    = over.get( "extra_context", "" ),
            config           = config or BugFixExpediterConfig(),
            session_id       = "s1",
            job_id           = "bfe-job::u1",
            cancel_check     = over.get( "cancel_check", None ),
            debug            = debug,
        )


def _diag_json( confidence ):
    return ( '{"root_cause":"rc","error_category":"config","confidence":' + str( confidence ) + '}' )


def _diag( **over ):
    kw = dict( root_cause="rc", error_category="config", confidence=0.85 )
    kw.update( over )
    return DiagnosisResult( **kw )


def _fix( **over ):
    kw = dict( title="T", description="d", fix_type="config_change", confidence=0.9 )
    kw.update( over )
    return ProposedFix( **kw )


def _sdk_stream( *messages ):
    async def _gen( prompt=None, options=None ):
        for m in messages:
            yield m
    return _gen


def _sdk_raise( exc ):
    async def _gen( prompt=None, options=None ):
        raise exc
        yield  # pragma: no cover - unreachable; makes this an async generator
    return _gen


def _result_msg():
    return MagicMock( spec=orch_mod.ResultMessage )


def _rate_limit():
    return MagicMock( spec=orch_mod.RateLimitEvent )


def _guard():
    g = MagicMock()
    g.check_timeout   = MagicMock()
    g.check_iteration = MagicMock()
    return g


# ===========================================================================
# run_diagnosis
# ===========================================================================
class TestRunDiagnosis( unittest.TestCase ):

    def setUp( self ):
        self.notify = AsyncMock()
        self._p = patch.object( vio_mod, "notify", self.notify )
        self._p.start()

    def tearDown( self ):
        self._p.stop()

    def test_sdk_unavailable_returns_fallback( self ):
        orch = _orch()
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            out = _run( orch.run_diagnosis() )
        self.assertEqual( out.confidence, 0.1 )
        self.assertIn( "SDK not installed", out.root_cause )

    def test_happy_break_on_confidence( self ):
        orch = _orch()
        orch._delegate_to_lead     = AsyncMock( return_value=_diag_json( 0.9 ) )
        orch._voice_gate_diagnosis = AsyncMock( side_effect=lambda d, *a: d )
        out = _run( orch.run_diagnosis() )
        self.assertEqual( out.confidence, 0.9 )
        orch._voice_gate_diagnosis.assert_awaited_once()

    def test_cancelled_in_loop_returns_fallback( self ):
        orch = _orch()
        orch._stop_requested   = True
        orch._delegate_to_lead = AsyncMock()
        out = _run( orch.run_diagnosis() )
        self.assertIn( "Cancelled by user", out.root_cause )
        orch._delegate_to_lead.assert_not_awaited()

    def test_low_confidence_refines_then_keeps_best( self ):
        cfg = BugFixExpediterConfig(); cfg.max_diagnosis_iterations = 2; cfg.min_diagnosis_confidence = 0.7
        orch = _orch( config=cfg, debug=True )
        orch._delegate_to_lead     = AsyncMock( side_effect=[ _diag_json( 0.3 ), _diag_json( 0.5 ) ] )
        orch._voice_gate_diagnosis = AsyncMock( side_effect=lambda d, *a: d )
        out = _run( orch.run_diagnosis() )
        self.assertEqual( out.confidence, 0.5 )         # best kept
        self.assertEqual( orch._delegate_to_lead.await_count, 2 )

    def test_second_iteration_lower_confidence_not_adopted( self ):
        # iter1=0.5 (best), iter2=0.3 (NOT higher) → best stays 0.5 (332->336 false arc).
        cfg = BugFixExpediterConfig(); cfg.max_diagnosis_iterations = 2; cfg.min_diagnosis_confidence = 0.7
        orch = _orch( config=cfg )
        orch._delegate_to_lead     = AsyncMock( side_effect=[ _diag_json( 0.5 ), _diag_json( 0.3 ) ] )
        orch._voice_gate_diagnosis = AsyncMock( side_effect=lambda d, *a: d )
        out = _run( orch.run_diagnosis() )
        self.assertEqual( out.confidence, 0.5 )

    def test_all_delegations_none_returns_fallback( self ):
        cfg = BugFixExpediterConfig(); cfg.max_diagnosis_iterations = 1
        orch = _orch( config=cfg )
        orch._delegate_to_lead     = AsyncMock( return_value=None )
        orch._voice_gate_diagnosis = AsyncMock( side_effect=lambda d, *a: d )
        out = _run( orch.run_diagnosis() )
        self.assertEqual( out.confidence, 0.1 )         # fallback "no result"

    def test_voice_gate_timeout_raises_stalled( self ):
        orch = _orch()
        orch._delegate_to_lead     = AsyncMock( return_value=_diag_json( 0.9 ) )
        orch._voice_gate_diagnosis = AsyncMock( side_effect=VoiceGateTimeoutError( "diagnosing" ) )
        with self.assertRaises( StalledException ) as cm:
            _run( orch.run_diagnosis() )
        self.assertEqual( cm.exception.phase, BFEPhase.DIAGNOSING.value )
        self.assertIsNotNone( orch.diagnosis )          # populated for checkpoint

    def test_voice_gate_unreachable_also_raises_stalled( self ):
        # The caller wiring, not the gate: an unreachable gate must reach the
        # SAME clean yield point as a timeout — checkpoint + stall — rather than
        # escaping as an unhandled error and failing the job (row 421b9498).
        orch = _orch()
        orch._delegate_to_lead     = AsyncMock( return_value=_diag_json( 0.9 ) )
        orch._voice_gate_diagnosis = AsyncMock(
            side_effect=VoiceGateUnreachableError( "diagnosing", RuntimeError( "ws down" ) )
        )
        with self.assertRaises( StalledException ) as cm:
            _run( orch.run_diagnosis() )
        self.assertEqual( cm.exception.phase, BFEPhase.DIAGNOSING.value )
        self.assertIsNotNone( orch.diagnosis )          # populated for checkpoint

    def test_stall_message_says_which_no_answer_it_was( self ):
        # Timeout and unreachable both stall, so the stall alone cannot tell them
        # apart — the message is the only place the distinction survives.
        orch = _orch()
        orch._delegate_to_lead     = AsyncMock( return_value=_diag_json( 0.9 ) )
        orch._voice_gate_diagnosis = AsyncMock(
            side_effect=VoiceGateUnreachableError( "diagnosing", RuntimeError( "ws down" ) )
        )
        with self.assertRaises( StalledException ) as cm:
            _run( orch.run_diagnosis() )
        self.assertIn( "unreachable", str( cm.exception ) )

        orch2 = _orch()
        orch2._delegate_to_lead     = AsyncMock( return_value=_diag_json( 0.9 ) )
        orch2._voice_gate_diagnosis = AsyncMock( side_effect=VoiceGateTimeoutError( "diagnosing" ) )
        with self.assertRaises( StalledException ) as cm2:
            _run( orch2.run_diagnosis() )
        self.assertIn( "timeout", str( cm2.exception ) )

    def test_cancel_before_voice_gate_skips_gate( self ):
        cfg = BugFixExpediterConfig(); cfg.max_diagnosis_iterations = 1
        # cancel_check: False during the loop, True at the post-loop gate guard.
        orch = _orch( config=cfg, cancel_check=MagicMock( side_effect=[ False, True ] ) )
        orch._delegate_to_lead     = AsyncMock( return_value=_diag_json( 0.9 ) )
        orch._voice_gate_diagnosis = AsyncMock()
        out = _run( orch.run_diagnosis() )
        self.assertEqual( out.confidence, 0.9 )
        orch._voice_gate_diagnosis.assert_not_awaited()  # gate skipped

    def test_user_messages_incorporated_with_debug( self ):
        cfg = BugFixExpediterConfig(); cfg.max_diagnosis_iterations = 1
        orch = _orch( config=cfg, debug=True )
        orch.queue_user_message( "look at the config" )
        orch._delegate_to_lead     = AsyncMock( return_value=_diag_json( 0.9 ) )
        orch._voice_gate_diagnosis = AsyncMock( side_effect=lambda d, *a: d )
        out = _run( orch.run_diagnosis() )
        self.assertEqual( out.confidence, 0.9 )


# ===========================================================================
# _delegate_to_lead
# ===========================================================================
class TestDelegateToLead( unittest.TestCase ):

    def setUp( self ):
        self._p = patch.object( vio_mod, "notify", AsyncMock() )
        self._p.start()

    def tearDown( self ):
        self._p.stop()

    def test_collects_text_and_handles_all_message_types( self ):
        orch = _orch()
        am = AssistantMessage(
            content=[ TextBlock( text="hello " ),
                      ToolUseBlock( id="t1", name="Grep", input={ "pattern": "x" } ),
                      object() ],                                    # neither block type → loop-back arc
            model="m",
        )
        top = TextBlock( text="world" )
        # object() trailing message matches none of the isinstance checks → fall-through loop-back.
        with patch.object( orch_mod, "sdk_query",
                           _sdk_stream( am, top, _result_msg(), _rate_limit(), object() ) ):
            out = _run( orch._delegate_to_lead( vio_mod, "prompt" ) )   # options=None → build
        self.assertEqual( out, "hello world" )

    def test_empty_response_returns_none( self ):
        orch = _orch()
        am = AssistantMessage( content=[ TextBlock( text="   " ) ], model="m" )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( am ) ):
            out = _run( orch._delegate_to_lead( vio_mod, "p", options="opts" ) )
        self.assertIsNone( out )

    def test_exception_returns_none_with_debug( self ):
        orch = _orch( debug=True )
        with patch.object( orch_mod, "sdk_query", _sdk_raise( RuntimeError( "sdk down" ) ) ):
            out = _run( orch._delegate_to_lead( vio_mod, "p", options="opts" ) )
        self.assertIsNone( out )

    def test_exception_returns_none_debug_off( self ):
        orch = _orch( debug=False )
        with patch.object( orch_mod, "sdk_query", _sdk_raise( RuntimeError( "sdk down" ) ) ):
            out = _run( orch._delegate_to_lead( vio_mod, "p", options="opts" ) )
        self.assertIsNone( out )


# ===========================================================================
# run_proposal
# ===========================================================================
class TestRunProposal( unittest.TestCase ):

    def setUp( self ):
        self._p = patch.object( vio_mod, "notify", AsyncMock() )
        self._p.start()
        # PlanWriter mocked so no real plan files are written.
        self.writer = MagicMock()
        self.writer.write_plan = MagicMock( return_value="/tmp/plan.md" )
        self._pw = patch.object( orch_mod, "PlanWriter", MagicMock( return_value=self.writer ) )
        self._pw.start()

    def tearDown( self ):
        self._p.stop(); self._pw.stop()

    def test_sdk_unavailable_returns_fallback_tuple( self ):
        orch = _orch()
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            fixes, selected, plan = _run( orch.run_proposal( _diag() ) )
        self.assertEqual( len( fixes ), 1 )
        self.assertIsNone( selected )
        self.assertEqual( plan, "" )

    def test_cancelled_returns_fallback_tuple( self ):
        orch = _orch()
        orch._stop_requested = True
        fixes, selected, plan = _run( orch.run_proposal( _diag() ) )
        self.assertEqual( fixes[ 0 ].fix_type, "manual" )
        self.assertIsNone( selected )

    def test_delegate_none_uses_fallback_and_writes_plan( self ):
        orch = _orch()
        orch._delegate_to_lead   = AsyncMock( return_value=None )
        orch._voice_gate_proposal = AsyncMock( return_value=None )
        fixes, selected, plan = _run( orch.run_proposal( _diag() ) )
        self.assertEqual( fixes[ 0 ].fix_type, "manual" )
        self.assertEqual( plan, "/tmp/plan.md" )
        self.writer.write_plan.assert_called()

    def test_delegate_response_is_parsed( self ):
        orch = _orch()
        orch._delegate_to_lead    = AsyncMock(
            return_value='[{"title":"Parsed","description":"d","fix_type":"x","confidence":0.9}]' )
        orch._voice_gate_proposal = AsyncMock( return_value=None )
        fixes, selected, plan = _run( orch.run_proposal( _diag() ) )
        self.assertEqual( fixes[ 0 ].title, "Parsed" )   # parsed, not fallback

    def test_cancelled_before_voice_gate_skips_gate( self ):
        # _is_cancelled: False at the early guard, True at the voice-gate guard.
        orch = _orch( cancel_check=MagicMock( side_effect=[ False, True ] ) )
        orch._delegate_to_lead    = AsyncMock( return_value=None )
        orch._voice_gate_proposal = AsyncMock()
        fixes, selected, plan = _run( orch.run_proposal( _diag() ) )
        self.assertIsNone( selected )
        orch._voice_gate_proposal.assert_not_awaited()

    def test_plan_write_exception_is_swallowed( self ):
        orch = _orch()
        orch._delegate_to_lead    = AsyncMock( return_value=None )
        orch._voice_gate_proposal = AsyncMock( return_value=None )
        self.writer.write_plan.side_effect = RuntimeError( "disk full" )
        fixes, selected, plan = _run( orch.run_proposal( _diag() ) )
        self.assertEqual( plan, "" )                     # write failed → plan_path stays ""

    def test_voice_gate_timeout_raises_stalled( self ):
        orch = _orch()
        orch._delegate_to_lead    = AsyncMock( return_value=None )
        orch._voice_gate_proposal = AsyncMock( side_effect=VoiceGateTimeoutError( "proposing" ) )
        with self.assertRaises( StalledException ) as cm:
            _run( orch.run_proposal( _diag() ) )
        self.assertEqual( cm.exception.phase, BFEPhase.PROPOSING.value )

    def test_voice_gate_unreachable_raises_stalled_and_selects_nothing( self ):
        # Caller wiring for the fix-application gate. The load-bearing assertion
        # is the second one: no fix is carried forward for application when the
        # gate broke (row 421b9498).
        orch = _orch()
        orch._delegate_to_lead    = AsyncMock( return_value=None )
        orch._voice_gate_proposal = AsyncMock(
            side_effect=VoiceGateUnreachableError( "proposing", RuntimeError( "ws down" ) )
        )
        with self.assertRaises( StalledException ) as cm:
            _run( orch.run_proposal( _diag() ) )
        self.assertEqual( cm.exception.phase, BFEPhase.PROPOSING.value )
        self.assertIn( "unreachable", str( cm.exception ) )
        # Krishna 🦚 flagged the assertion that used to sit here —
        #   assertIsNone( getattr( orch, "selected_fix", None ) )
        # — as vacuous, and it was worse than he thought: __init__ sets
        # self.selected_fix = None (orchestrator.py:135) and run_proposal only
        # ever binds a LOCAL, so that line could not fail under any behaviour.
        # It asserted nothing while reading like the load-bearing check.
        # What actually matters is that no SELECTION reaches the writer — the
        # step that would carry an unapproved fix forward. (write_plan IS called
        # once for the initial plan, so assert_not_called would be wrong here;
        # the invariant is that no call ever names a selected_fix.)
        selected_args = [
            c.kwargs.get( "selected_fix" ) for c in self.writer.write_plan.call_args_list
        ]
        self.assertTrue( selected_args, "writer was never called at all — test is not exercising the path" )
        self.assertTrue( all( s is None for s in selected_args ), f"a fix was carried to the writer: {selected_args}" )

    def test_selected_fix_triggers_plan_rewrite( self ):
        orch = _orch()
        sel = _fix( title="Chosen" )
        orch._delegate_to_lead    = AsyncMock( return_value=None )
        orch._voice_gate_proposal = AsyncMock( return_value=sel )
        fixes, selected, plan = _run( orch.run_proposal( _diag() ) )
        self.assertEqual( selected.title, "Chosen" )
        # write_plan called twice: once initial, once with selection.
        self.assertGreaterEqual( self.writer.write_plan.call_count, 2 )

    def test_selected_fix_plan_rewrite_exception_swallowed( self ):
        orch = _orch()
        sel = _fix( title="Chosen" )
        orch._delegate_to_lead    = AsyncMock( return_value=None )
        orch._voice_gate_proposal = AsyncMock( return_value=sel )
        # First write_plan ok, the rewrite (2nd call) raises → swallowed.
        self.writer.write_plan.side_effect = [ "/tmp/plan.md", RuntimeError( "rewrite boom" ) ]
        fixes, selected, plan = _run( orch.run_proposal( _diag() ) )
        self.assertEqual( selected.title, "Chosen" )


# ===========================================================================
# _voice_gate_diagnosis
# ===========================================================================
class TestVoiceGateDiagnosis( unittest.TestCase ):

    def setUp( self ):
        self._p = patch.object( vio_mod, "notify", AsyncMock() )
        self._p.start()
        self.ci = MagicMock()
        self.ci.ask_confirmation = AsyncMock()
        self.ci.get_feedback     = AsyncMock()

    def tearDown( self ):
        self._p.stop()

    def test_auto_approve_when_confirm_disabled( self ):
        cfg = BugFixExpediterConfig(); cfg.require_user_confirm = False
        orch = _orch( config=cfg, debug=True )
        d = _diag()
        out = _run( orch._voice_gate_diagnosis( d, vio_mod, self.ci ) )
        self.assertIs( out, d )

    def test_approved_returns_diagnosis( self ):
        orch = _orch( debug=True )
        self.ci.ask_confirmation.return_value = True
        d = _diag()
        out = _run( orch._voice_gate_diagnosis( d, vio_mod, self.ci ) )
        self.assertIs( out, d )

    def test_timeout_reraised( self ):
        orch = _orch()
        self.ci.ask_confirmation.side_effect = VoiceGateTimeoutError( "diagnosing" )
        with self.assertRaises( VoiceGateTimeoutError ):
            _run( orch._voice_gate_diagnosis( _diag(), vio_mod, self.ci ) )

    def test_other_confirmation_exception_refuses_to_approve( self ):
        # Was test_other_confirmation_exception_auto_approves — it pinned the defect.
        # A gate that cannot reach a human must not answer for them (row 421b9498).
        orch = _orch()
        self.ci.ask_confirmation.side_effect = RuntimeError( "ws down" )
        with self.assertRaises( VoiceGateUnreachableError ) as ctx:
            _run( orch._voice_gate_diagnosis( _diag(), vio_mod, self.ci ) )
        self.assertEqual( ctx.exception.phase, BFEPhase.DIAGNOSING.value )
        self.assertIsInstance( ctx.exception.cause, RuntimeError )

    def test_unreachable_is_not_reported_as_a_timeout( self ):
        # The two are distinct events and the record must be able to say which.
        # Collapsing them is the same "cannot distinguish" defect the gate had.
        orch = _orch()
        self.ci.ask_confirmation.side_effect = RuntimeError( "ws down" )
        with self.assertRaises( VoiceGateUnreachableError ):
            _run( orch._voice_gate_diagnosis( _diag(), vio_mod, self.ci ) )
        self.assertFalse( issubclass( VoiceGateUnreachableError, VoiceGateTimeoutError ) )
        self.assertFalse( issubclass( VoiceGateTimeoutError, VoiceGateUnreachableError ) )

    def test_rejected_then_feedback_exception_does_not_convert_no_into_yes( self ):
        # Was test_rejected_feedback_exception_returns_as_is. The user ALREADY
        # said no; returning the diagnosis turned an explicit rejection into an
        # acceptance because a *second* call failed. The only site in this sweep
        # that overrode a human who spoke, rather than one who was absent.
        orch = _orch( debug=True )
        self.ci.ask_confirmation.return_value = False          # explicit NO
        self.ci.get_feedback.side_effect = RuntimeError( "fb down" )
        with self.assertRaises( VoiceGateUnreachableError ) as ctx:
            _run( orch._voice_gate_diagnosis( _diag(), vio_mod, self.ci ) )
        self.assertIsInstance( ctx.exception.cause, RuntimeError )

    def test_feedback_timeout_stays_a_timeout_and_is_not_relabelled( self ):
        # Krishna 🦚, pre-commit review: the feedback handler wrapped EVERY
        # exception as unreachable, including a genuine VoiceGateTimeoutError
        # that get_feedback raises in its own right. Both branches stall, so
        # nothing leaked — but a handler that cannot tell the two states apart
        # is the exact defect this change exists to remove, sitting inside the
        # fix for it.
        orch = _orch()
        self.ci.ask_confirmation.return_value = False          # user rejects
        self.ci.get_feedback.side_effect = VoiceGateTimeoutError( "diagnosing" )
        with self.assertRaises( VoiceGateTimeoutError ):
            _run( orch._voice_gate_diagnosis( _diag(), vio_mod, self.ci ) )

    # NOTE: a second "end-to-end" test was written here and DELETED. It mocked
    # _voice_gate_diagnosis wholesale, so it never entered the feedback handler
    # at all — with Krishna's fix reverted it still passed. It would have sat in
    # the suite looking like coverage of exactly the defect it could not see.
    # The caller-side label is already proven by
    # test_stall_message_says_which_no_answer_it_was, which does go red.

    def test_control_a_working_gate_still_returns_the_approved_diagnosis( self ):
        # Control for the two refusal tests above: if they passed because the
        # gate refuses EVERYTHING, this one goes red. A refusal test whose green
        # is indistinguishable from a gate that never approves proves nothing.
        orch = _orch()
        self.ci.ask_confirmation.return_value = True
        self.ci.ask_confirmation.side_effect = None
        d = _diag()
        out = _run( orch._voice_gate_diagnosis( d, vio_mod, self.ci ) )
        self.assertIs( out, d )

    def test_rejected_no_feedback_returns_as_is( self ):
        orch = _orch( debug=True )
        self.ci.ask_confirmation.return_value = False
        self.ci.get_feedback.return_value = ""
        d = _diag()
        out = _run( orch._voice_gate_diagnosis( d, vio_mod, self.ci ) )
        self.assertIs( out, d )

    def test_rejected_feedback_refines_to_higher_confidence( self ):
        orch = _orch()
        self.ci.ask_confirmation.return_value = False
        self.ci.get_feedback.return_value = "fix the category"
        orch._delegate_to_lead = AsyncMock( return_value=_diag_json( 0.95 ) )
        d = _diag( confidence=0.4 )
        out = _run( orch._voice_gate_diagnosis( d, vio_mod, self.ci ) )
        self.assertAlmostEqual( out.confidence, 0.95 )   # refined adopted

    def test_rejected_feedback_not_higher_keeps_original( self ):
        orch = _orch()
        self.ci.ask_confirmation.return_value = False
        self.ci.get_feedback.return_value = "meh"
        orch._delegate_to_lead = AsyncMock( return_value=_diag_json( 0.2 ) )
        d = _diag( confidence=0.6 )
        out = _run( orch._voice_gate_diagnosis( d, vio_mod, self.ci ) )
        self.assertIs( out, d )                          # refine not higher → original

    def test_rejected_feedback_delegate_none_keeps_original( self ):
        # Refinement delegation returns None → raw_response falsy → keep original.
        orch = _orch()
        self.ci.ask_confirmation.return_value = False
        self.ci.get_feedback.return_value = "please retry"
        orch._delegate_to_lead = AsyncMock( return_value=None )
        d = _diag( confidence=0.6 )
        out = _run( orch._voice_gate_diagnosis( d, vio_mod, self.ci ) )
        self.assertIs( out, d )


# ===========================================================================
# _voice_gate_proposal
# ===========================================================================
class TestVoiceGateProposal( unittest.TestCase ):

    def setUp( self ):
        self._p = patch.object( vio_mod, "notify", AsyncMock() )
        self._p.start()
        self.ci = MagicMock()
        self.ci.ask_confirmation = AsyncMock()
        self.ci.present_choices  = AsyncMock()
        self.ci.get_feedback     = AsyncMock()

    def tearDown( self ):
        self._p.stop()

    def test_no_fixes_returns_none( self ):
        orch = _orch()
        self.assertIsNone( _run( orch._voice_gate_proposal( [], vio_mod, self.ci ) ) )

    def test_confirm_disabled_auto_best( self ):
        cfg = BugFixExpediterConfig(); cfg.require_user_confirm = False
        orch = _orch( config=cfg, debug=True )
        best = _fix( title="Best", confidence=0.99 )
        out = _run( orch._voice_gate_proposal( [ _fix( confidence=0.4 ), best ], vio_mod, self.ci ) )
        self.assertEqual( out.title, "Best" )

    def test_auto_select_single_high_conf_approved( self ):
        orch = _orch()
        self.ci.ask_confirmation.return_value = True
        f = _fix( confidence=0.9 )
        out = _run( orch._voice_gate_proposal( [ f ], vio_mod, self.ci ) )
        self.assertIs( out, f )

    def test_auto_select_timeout_reraised( self ):
        orch = _orch()
        self.ci.ask_confirmation.side_effect = VoiceGateTimeoutError( "proposing" )
        with self.assertRaises( VoiceGateTimeoutError ):
            _run( orch._voice_gate_proposal( [ _fix( confidence=0.9 ) ], vio_mod, self.ci ) )

    def test_auto_select_other_exception_refuses_to_apply( self ):
        # Was test_auto_select_other_exception_auto_approves. This gate asks
        # "Apply this fix?" — a broken gate returning the fix meant BFE applied
        # a code change nobody approved (row 421b9498).
        orch = _orch()
        self.ci.ask_confirmation.side_effect = RuntimeError( "ws down" )
        with self.assertRaises( VoiceGateUnreachableError ) as ctx:
            _run( orch._voice_gate_proposal( [ _fix( confidence=0.9 ) ], vio_mod, self.ci ) )
        self.assertEqual( ctx.exception.phase, BFEPhase.PROPOSING.value )

    def test_control_a_working_gate_still_returns_the_approved_fix( self ):
        # Control: if the refusal test above passed because the gate refuses
        # everything, this goes red.
        orch = _orch()
        self.ci.ask_confirmation.side_effect = None
        self.ci.ask_confirmation.return_value = True
        f = _fix( confidence=0.9 )
        out = _run( orch._voice_gate_proposal( [ f ], vio_mod, self.ci ) )
        self.assertIs( out, f )

    def test_auto_select_not_approved_falls_to_feedback( self ):
        # Single high-conf fix, user does NOT approve → drops to the feedback path.
        orch = _orch()
        self.ci.ask_confirmation.return_value = False
        self.ci.get_feedback.return_value = ""           # no feedback → None
        out = _run( orch._voice_gate_proposal( [ _fix( confidence=0.9 ) ], vio_mod, self.ci ) )
        self.assertIsNone( out )

    def test_multiple_fixes_choice_found( self ):
        orch = _orch()
        f1 = _fix( title="A", confidence=0.5 ); f2 = _fix( title="B", confidence=0.5 )
        self.ci.present_choices.return_value = { "answers": { "Fix Selection": "B" } }
        out = _run( orch._voice_gate_proposal( [ f1, f2 ], vio_mod, self.ci ) )
        self.assertEqual( out.title, "B" )

    def test_multiple_fixes_choices_exception_then_feedback_none( self ):
        orch = _orch( debug=True )
        f1 = _fix( title="A", confidence=0.5 ); f2 = _fix( title="B", confidence=0.5 )
        self.ci.present_choices.side_effect = RuntimeError( "choices down" )
        self.ci.get_feedback.return_value = ""           # no feedback → None
        out = _run( orch._voice_gate_proposal( [ f1, f2 ], vio_mod, self.ci ) )
        self.assertIsNone( out )

    def test_multiple_fixes_choices_timeout_reraised( self ):
        orch = _orch()
        f1 = _fix( title="A", confidence=0.5 ); f2 = _fix( title="B", confidence=0.5 )
        self.ci.present_choices.side_effect = VoiceGateTimeoutError( "proposing" )
        with self.assertRaises( VoiceGateTimeoutError ):
            _run( orch._voice_gate_proposal( [ f1, f2 ], vio_mod, self.ci ) )

    def test_rejected_feedback_exception_returns_none( self ):
        orch = _orch()
        f1 = _fix( title="A", confidence=0.5 ); f2 = _fix( title="B", confidence=0.5 )
        self.ci.present_choices.return_value = { "answers": { "Fix Selection": "none" } }
        self.ci.get_feedback.side_effect = RuntimeError( "fb down" )
        out = _run( orch._voice_gate_proposal( [ f1, f2 ], vio_mod, self.ci ) )
        self.assertIsNone( out )

    def test_rejected_feedback_revises_with_diagnosis( self ):
        orch = _orch()
        orch._last_diagnosis = _diag()
        f1 = _fix( title="A", confidence=0.5 ); f2 = _fix( title="B", confidence=0.5 )
        self.ci.present_choices.return_value = { "answers": { "Fix Selection": "none" } }
        self.ci.get_feedback.return_value = "try harder"
        # Revised proposal returns a high-confidence fix → auto-selected.
        orch._delegate_to_lead = AsyncMock(
            return_value='[{"title":"Revised","description":"d","fix_type":"x","confidence":0.9}]' )
        out = _run( orch._voice_gate_proposal( [ f1, f2 ], vio_mod, self.ci ) )
        self.assertEqual( out.title, "Revised" )

    def test_rejected_feedback_revise_without_diagnosis_returns_none( self ):
        orch = _orch()                                    # no _last_diagnosis attribute
        f1 = _fix( title="A", confidence=0.5 ); f2 = _fix( title="B", confidence=0.5 )
        self.ci.present_choices.return_value = { "answers": { "Fix Selection": "none" } }
        self.ci.get_feedback.return_value = "try harder"
        out = _run( orch._voice_gate_proposal( [ f1, f2 ], vio_mod, self.ci ) )
        self.assertIsNone( out )                          # prompt None → no revise → None

    def test_rejected_feedback_revise_delegate_none_returns_none( self ):
        orch = _orch()
        orch._last_diagnosis = _diag()
        f1 = _fix( title="A", confidence=0.5 ); f2 = _fix( title="B", confidence=0.5 )
        self.ci.present_choices.return_value = { "answers": { "Fix Selection": "none" } }
        self.ci.get_feedback.return_value = "try harder"
        orch._delegate_to_lead = AsyncMock( return_value=None )   # raw_response falsy
        out = _run( orch._voice_gate_proposal( [ f1, f2 ], vio_mod, self.ci ) )
        self.assertIsNone( out )

    def test_rejected_feedback_revise_low_confidence_returns_none( self ):
        orch = _orch()
        orch._last_diagnosis = _diag()
        f1 = _fix( title="A", confidence=0.5 ); f2 = _fix( title="B", confidence=0.5 )
        self.ci.present_choices.return_value = { "answers": { "Fix Selection": "none" } }
        self.ci.get_feedback.return_value = "try harder"
        # Revised fixes parse to the fallback (confidence 0.1) → not > 0.1 → None.
        orch._delegate_to_lead = AsyncMock( return_value="no json array here" )
        out = _run( orch._voice_gate_proposal( [ f1, f2 ], vio_mod, self.ci ) )
        self.assertIsNone( out )


# ===========================================================================
# run_fix
# ===========================================================================
class TestRunFix( unittest.TestCase ):

    def setUp( self ):
        self._p = patch.object( vio_mod, "notify", AsyncMock() )
        self._p.start()
        self.writer = MagicMock()
        self._pw = patch.object( orch_mod, "PlanWriter", MagicMock( return_value=self.writer ) )
        self._pw.start()

    def tearDown( self ):
        self._p.stop(); self._pw.stop()

    def _patch_executor( self, fix_result, files, coder_output="coder summary" ):
        ex = MagicMock()
        ex.execute_fix       = AsyncMock( return_value=( fix_result, files ) )
        ex.last_coder_output = coder_output
        return patch.object( orch_mod, "FixExecutor", MagicMock( return_value=ex ) )

    def test_sdk_unavailable_returns_failed_fixresult( self ):
        orch = _orch()
        with patch.object( orch_mod, "SDK_AVAILABLE", False ):
            fr = _run( orch.run_fix( _diag(), _fix(), "/tmp/plan.md" ) )
        self.assertFalse( fr.applied ); self.assertFalse( fr.success )

    def test_success_updates_plan_and_files( self ):
        orch = _orch()
        fr = FixResult( applied=True, success=True, details="done" )
        with self._patch_executor( fr, [ "a.py", "b.py" ] ):
            out = _run( orch.run_fix( _diag(), _fix(), "/tmp/plan.md" ) )
        self.assertTrue( out.success )
        self.assertEqual( orch.last_files_changed, [ "a.py", "b.py" ] )
        self.writer.update_implementation_log.assert_called_once()

    def test_failure_high_priority_notify( self ):
        orch = _orch()
        fr = FixResult( applied=True, success=False, details="nope" )
        with self._patch_executor( fr, [] ):
            out = _run( orch.run_fix( _diag(), _fix(), "/tmp/plan.md" ) )
        self.assertFalse( out.success )

    def test_plan_update_exception_swallowed( self ):
        orch = _orch()
        fr = FixResult( applied=True, success=True )
        self.writer.update_implementation_log.side_effect = RuntimeError( "log boom" )
        with self._patch_executor( fr, [ "a.py" ] ):
            out = _run( orch.run_fix( _diag(), _fix(), "/tmp/plan.md" ) )
        self.assertTrue( out.success )                    # exception did not propagate


# ===========================================================================
# run_git_strategy + _finalize_git_strategy
# ===========================================================================
class TestRunGitStrategy( unittest.TestCase ):

    def setUp( self ):
        self._p = patch.object( vio_mod, "notify", AsyncMock() )
        self._p.start()
        self.writer = MagicMock()
        self._pw = patch.object( orch_mod, "PlanWriter", MagicMock( return_value=self.writer ) )
        self._pw.start()
        # GitOps constructed inside run_git_strategy (imported from bfe.git_ops)
        self._go = patch( "cosa.agents.bug_fix_expediter.git_ops.GitOps", MagicMock() )
        self._go.start()

    def tearDown( self ):
        self._p.stop(); self._pw.stop(); self._go.stop()

    def test_skip_when_not_successful( self ):
        orch = _orch( debug=True )
        fr = FixResult( applied=True, success=False )
        out = _run( orch.run_git_strategy( fr, [ "a.py" ], "/tmp/plan.md" ) )
        self.assertIs( out, fr )

    def test_skip_when_no_files( self ):
        orch = _orch()
        fr = FixResult( applied=True, success=True )
        out = _run( orch.run_git_strategy( fr, [], "/tmp/plan.md" ) )
        self.assertIs( out, fr )

    def test_success_applies_git_fields( self ):
        orch = _orch()
        fr = FixResult( applied=True, success=True, details="the fix" )
        git_result = {
            "git_strategy" : "branch_and_pr", "commit_hash": "abc1234",
            "branch_name"  : "fix/x", "pr_url": "http://pr",
        }
        strat = MagicMock()
        async def _commit( *, notify_fn, **kw ):
            await notify_fn( "committing...", priority="low" )   # exercises the inner _notify_fn
            return git_result
        strat.commit_and_pr_single = AsyncMock( side_effect=_commit )
        with patch.object( orch_mod, "GitStrategist",
                           MagicMock( return_value=strat,
                                      resolve_trust_level=MagicMock( return_value=3 ) ) ):
            out = _run( orch.run_git_strategy( fr, [ "a.py" ], "/tmp/plan.md" ) )
        self.assertEqual( out.git_strategy, "branch_and_pr" )
        self.assertEqual( out.commit_hash, "abc1234" )
        self.assertEqual( out.branch_name, "fix/x" )
        self.assertEqual( out.pr_url, "http://pr" )
        self.writer.update_git_references.assert_called_once()

    def test_success_with_none_git_fields_and_no_details( self ):
        orch = _orch()
        fr = FixResult( applied=True, success=True, details="" )     # no details → default messages
        git_result = { "git_strategy": None, "commit_hash": None,
                       "branch_name": None, "pr_url": None }
        strat = MagicMock()
        strat.commit_and_pr_single = AsyncMock( return_value=git_result )
        with patch.object( orch_mod, "GitStrategist",
                           MagicMock( return_value=strat,
                                      resolve_trust_level=MagicMock( return_value=1 ) ) ):
            out = _run( orch.run_git_strategy( fr, [ "a.py" ], "/tmp/plan.md" ) )
        self.assertIsNone( out.git_strategy )            # None field not applied

    def test_finalize_plan_update_exception_swallowed( self ):
        orch = _orch()
        fr = FixResult( applied=True, success=True )
        self.writer.update_git_references.side_effect = RuntimeError( "git ref boom" )
        out = orch._finalize_git_strategy( fr, "/tmp/plan.md", MagicMock() )
        self.assertIs( out, fr )


# ===========================================================================
# _delegate_to_coder
# ===========================================================================
class TestDelegateToCoder( unittest.TestCase ):

    def setUp( self ):
        self._p = patch.object( vio_mod, "notify", AsyncMock() )
        self._p.start()
        self._wp = patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p )
        self._wp.start()
        self._pth = patch.object( orch_mod, "post_tool_hook", AsyncMock() )
        self._pth.start()

    def tearDown( self ):
        self._p.stop(); self._wp.stop(); self._pth.stop()

    def test_tracks_files_and_handles_messages( self ):
        orch = _orch( debug=True )
        orch._build_coder_options = MagicMock( return_value="opts" )
        am = AssistantMessage(
            content=[ TextBlock( text="patching " ),
                      ToolUseBlock( id="t1", name="Edit", input={ "file_path": "/x/a.py" } ),
                      ToolUseBlock( id="t2", name="Edit", input={ "file_path": "/x/a.py" } ),  # dup → skip
                      ToolUseBlock( id="t3", name="Write", input={ "file_path": "" } ),         # empty path
                      ToolUseBlock( id="t4", name="Read", input={ "file_path": "/x/r.py" } ),   # non-edit tool
                      object() ],                                                               # neither block type
            model="m",
        )
        top = TextBlock( text="done" )
        with patch.object( orch_mod, "sdk_query",
                           _sdk_stream( am, top, _result_msg(), _rate_limit(), object() ) ):
            output, files = _run( orch._delegate_to_coder( vio_mod, "p", _guard(), MagicMock() ) )
        self.assertEqual( output, "patching done" )
        self.assertEqual( files, [ "/x/a.py" ] )         # dup + empty + Read filtered

    def test_cancellation_breaks_loop( self ):
        orch = _orch()
        orch._build_coder_options = MagicMock( return_value="opts" )
        orch._stop_requested = True
        am = AssistantMessage( content=[ TextBlock( text="x" ) ], model="m" )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( am ) ):
            output, files = _run( orch._delegate_to_coder( vio_mod, "p", _guard(), MagicMock() ) )
        self.assertEqual( output, "" )                    # broke before collecting

    def test_safety_limit_error_reraised( self ):
        orch = _orch()
        orch._build_coder_options = MagicMock( return_value="opts" )
        g = _guard()
        g.check_timeout.side_effect = orch_mod.SafetyLimitError( "budget" )
        am = AssistantMessage( content=[ TextBlock( text="x" ) ], model="m" )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( am ) ):
            with self.assertRaises( orch_mod.SafetyLimitError ):
                _run( orch._delegate_to_coder( vio_mod, "p", g, MagicMock() ) )

    def test_generic_exception_returns_empty( self ):
        orch = _orch()
        orch._build_coder_options = MagicMock( return_value="opts" )
        with patch.object( orch_mod, "sdk_query", _sdk_raise( RuntimeError( "down" ) ) ):
            output, files = _run( orch._delegate_to_coder( vio_mod, "p", _guard(), MagicMock() ) )
        self.assertEqual( ( output, files ), ( "", [] ) )


# ===========================================================================
# _verify_fix
# ===========================================================================
class TestVerifyFix( unittest.TestCase ):

    def setUp( self ):
        self._p = patch.object( vio_mod, "notify", AsyncMock() )
        self._p.start()
        self._wp = patch.object( orch_mod, "wrap_prompt_for_streaming", lambda p: p )
        self._wp.start()
        self._pth = patch.object( orch_mod, "post_tool_hook", AsyncMock() )
        self._pth.start()

    def tearDown( self ):
        self._p.stop(); self._wp.stop(); self._pth.stop()

    def _orch_tester( self, debug=False ):
        orch = _orch( debug=debug )
        orch._build_tester_options = MagicMock( return_value="opts" )
        return orch

    def test_self_report_pass_handles_all_block_types( self ):
        # Exercises block-level arcs: non-edit tool (Read), empty-path Write,
        # neither-type block, top-level TextBlock, and a junk trailing message.
        orch = self._orch_tester()
        am = AssistantMessage(
            content=[ TextBlock( text="All tests pass cleanly. " ),
                      ToolUseBlock( id="t1", name="Read", input={ "file_path": "/x/a.py" } ),
                      ToolUseBlock( id="t2", name="Write", input={ "file_path": "" } ),
                      object() ],
            model="m",
        )
        top = TextBlock( text="" )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( am, top, _rate_limit(), object() ) ):
            passed, out = _run( orch._verify_fix(
                vio_mod, _fix(), "coder out", [ "a.py" ], _guard(), MagicMock() ) )
        self.assertTrue( passed )

    def test_pytest_override_forces_fail_skips_non_test_file( self ):
        orch = self._orch_tester( debug=True )
        am = AssistantMessage(
            content=[ TextBlock( text="pass" ),
                      ToolUseBlock( id="t1", name="Write", input={ "file_path": "notes.txt" } ),   # not a .py test → skipped
                      ToolUseBlock( id="t2", name="Write", input={ "file_path": "test_x.py" } ) ],
            model="m",
        )
        run_result = MagicMock( passed=False, passed_count=0, total_tests=3 )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( am ) ), \
             patch.object( orch_mod, "run_pytest", AsyncMock( return_value=run_result ) ):
            passed, out = _run( orch._verify_fix(
                vio_mod, _fix(), "coder", [], _guard(), MagicMock() ) )
        self.assertFalse( passed )                        # pytest overrides self-report

    def test_pytest_passes_keeps_self_report_debug_off( self ):
        orch = self._orch_tester( debug=False )
        am = AssistantMessage(
            content=[ TextBlock( text="pass" ),
                      ToolUseBlock( id="t1", name="Write", input={ "file_path": "test_y.py" } ) ],
            model="m",
        )
        run_result = MagicMock( passed=True, passed_count=2, total_tests=2 )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( am ) ), \
             patch.object( orch_mod, "run_pytest", AsyncMock( return_value=run_result ) ):
            passed, out = _run( orch._verify_fix(
                vio_mod, _fix(), "coder", [], _guard(), MagicMock() ) )
        self.assertTrue( passed )                         # pytest passed → self-report kept

    def test_safety_limit_error_reraised( self ):
        orch = self._orch_tester()
        g = _guard()
        g.check_timeout.side_effect = orch_mod.SafetyLimitError( "budget" )
        am = AssistantMessage( content=[ TextBlock( text="x" ) ], model="m" )
        with patch.object( orch_mod, "sdk_query", _sdk_stream( am ) ):
            with self.assertRaises( orch_mod.SafetyLimitError ):
                _run( orch._verify_fix( vio_mod, _fix(), "c", [], g, MagicMock() ) )

    def test_generic_exception_returns_false( self ):
        orch = self._orch_tester()
        with patch.object( orch_mod, "sdk_query", _sdk_raise( RuntimeError( "down" ) ) ):
            passed, out = _run( orch._verify_fix( vio_mod, _fix(), "c", [], _guard(), MagicMock() ) )
        self.assertFalse( passed )
        self.assertIn( "Verification error", out )


if __name__ == "__main__":
    unittest.main()
