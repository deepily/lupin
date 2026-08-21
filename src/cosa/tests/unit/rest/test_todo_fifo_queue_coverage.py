#!/usr/bin/env python3
"""
Supplemental unit tests — `cosa.rest.todo_fifo_queue.TodoFifoQueue` coverage closure.

Complements `test_todo_fifo_queue.py` (init + _log_query_with_results). This file
closes the large remaining gap: the routing engine `push_job` (cache-hit /
confirmation / similarity / LLM-routing branches across every agent command),
plus `parse_salutations`, the user-mode methods, `_is_fit`, `_notify_rejection`,
`_dump_code`, `_queue_best_snapshot`, `_get_routing_command`, `_crud_agents_enabled`,
`_confirm_agentic_routing`, `_handle_agentic_command`, `push_job_agentic`, and the
`push` / `delete_by_id_hash` overrides.

Boundary-mock discipline: every heavy constructor dependency (LlmClientFactory,
Gister, GistNormalizer, Normalizer, QueryLogTable, EmbeddingManager,
get_embedding_provider) is patched at import-site; the concrete agent classes,
ConfirmationDialogue, RuntimeArgumentExpeditor, LupinSearch, create_agentic_job,
notify_user_sync, emit_job_state_transition, and the FifoQueue notify path are
all patched per-test. ZERO real LLM/embedding/DB/network/agent execution.

Run: PYTHONPATH=src:src/cosa/tests/unit/infrastructure \
     src/cosa/.venv/bin/python -m pytest \
     src/cosa/tests/unit/rest/test_todo_fifo_queue_coverage.py -v
"""

import sys
import unittest
from dataclasses import replace
from unittest.mock import Mock, MagicMock, patch

import cosa.rest.todo_fifo_queue as tfq
import cosa.rest.v2.registry as reg
from cosa.rest.v2.registry import resolve

# The conversational agents push_job no longer names: since row 10ef4b64 their class
# comes from the REGISTRY, so patching the class in this module's namespace no longer
# intercepts construction. Patch the table entry instead — see _route.
_REGISTRY_BUILT = frozenset( {
    "MathAgent", "CalculatorAgent", "DateAndTimeAgent", "TodoListAgent",
    "CalendaringAgent", "WeatherAgent", "TodoCrudAgent", "CalendarCrudAgent",
} )
from cosa.rest.todo_fifo_queue import TodoFifoQueue, MODE_TO_AGENT, AGENTIC_MODE_MAP
from cosa.agents.runtime_argument_expeditor.expeditor import BATCH_DECLINED, BATCH_UNREACHABLE
from cosa.rest.queue_protocol import QueueableJob


# Default config values used across push_job
_CONFIG = {
    "debug auto"                              : False,
    "debug inject bugs"                       : False,
    "fifo todo queue enable input gisting"    : True,
    "llm spec key for confirmation dialog"    : "spec-confirm",
    "similarity threshold confirmation"       : 90.0,
    "similarity confirmation enabled"         : True,
    "crud for dataframes agents enabled"      : "true",
    "prompt template for agent router"        : "/src/conf/prompts/router.txt",
    "llm spec key for agent router"           : "spec-router",
    "runtime argument expeditor enabled"      : True,
}


def _cfg( overrides=None ):
    """Build a config_mgr mock whose .get returns _CONFIG (with overrides)."""
    data = dict( _CONFIG )
    if overrides:
        data.update( overrides )
    m = Mock()
    m.get.side_effect = lambda key, default=None, return_type=None: data.get( key, default )
    return m


class _TFQBase( unittest.TestCase ):
    """Harness: builds a TodoFifoQueue with all heavy deps boundary-mocked."""

    def setUp( self ):
        self._patchers = []
        for name in ( "LlmClientFactory", "Gister", "GistNormalizer", "Normalizer",
                      "QueryLogTable", "EmbeddingManager", "get_embedding_provider" ):
            p = patch.object( tfq, name )
            p.start()
            self._patchers.append( p )

        self.ws       = Mock()
        self.snap_mgr = Mock()
        self.cfg      = _cfg()
        self.queue = TodoFifoQueue(
            websocket_mgr        = self.ws,
            snapshot_mgr         = self.snap_mgr,
            app                  = Mock(),
            config_mgr           = self.cfg,
            debug                = False,
            verbose              = False,
        )
        # deterministic text processors + embedding provider
        self.queue.gist_normalizer.get_normalized_gist = Mock( return_value="gist" )
        self.queue.normalizer.normalize                = Mock( return_value="normalized" )
        self.queue._embedding_provider.generate_embedding = Mock( return_value=[ 0.1, 0.2 ] )
        self.queue.query_log.log_query                 = Mock()
        # user_job_tracker: echo the id back as the scoped id
        self.queue.user_job_tracker = Mock()
        self.queue.user_job_tracker.register_scoped_job = Mock( side_effect=lambda idh, *a, **k: idh )
        self.queue.user_job_tracker.remove_job          = Mock()

    def tearDown( self ):
        for p in reversed( self._patchers ):
            p.stop()


# ───────────────────── parse_salutations / modes / _is_fit ─────────────────────
class TestSalutationsAndModes( _TFQBase ):
    """Exercises parse_salutations, user-mode methods, get_available_modes, _is_fit."""

    def test_parse_salutations_with_prefix( self ):
        sal, rest = self.queue.parse_salutations( "hey buddy what time is it" )
        self.assertEqual( sal, "hey buddy" )
        self.assertEqual( rest, "what time is it" )

    def test_parse_salutations_none( self ):
        sal, rest = self.queue.parse_salutations( "what time is it" )
        self.assertEqual( sal, "" )
        self.assertEqual( rest, "what time is it" )

    def test_get_set_clear_user_mode( self ):
        self.assertIsNone( self.queue.get_user_mode( "u1" ) )
        self.assertIsNone( self.queue.set_user_mode( "u1", "math" ) )
        self.assertEqual( self.queue.get_user_mode( "u1" ), "math" )
        self.assertEqual( self.queue.set_user_mode( "u1", None ), "math" )   # None → pop
        self.assertIsNone( self.queue.get_user_mode( "u1" ) )

    def test_set_user_mode_debug_branch( self ):
        self.queue.debug = True
        with patch( "builtins.print" ):
            self.queue.set_user_mode( "u1", "calendar" )
            self.queue.clear_user_mode( "u1" )

    def test_set_user_mode_invalid_raises( self ):
        with self.assertRaises( ValueError ):
            self.queue.set_user_mode( "u1", "bogus_mode" )

    def test_clear_user_mode_returns_previous( self ):
        self.queue.set_user_mode( "u1", "weather" )
        self.assertEqual( self.queue.clear_user_mode( "u1" ), "weather" )

    def test_get_available_modes( self ):
        modes = self.queue.get_available_modes()
        self.assertTrue( any( m[ "key" ] == "system" for m in modes ) )
        self.assertTrue( all( { "key", "display_name", "description" } <= set( m ) for m in modes ) )

    def test_is_fit( self ):
        self.assertFalse( self.queue._is_fit( "" ) )
        self.assertFalse( self.queue._is_fit( "   " ) )
        self.assertFalse( self.queue._is_fit( "x" * 1001 ) )
        self.assertFalse( self.queue._is_fit( "invalid request" ) )
        self.assertTrue( self.queue._is_fit( "what time is it" ) )

    def test_crud_agents_enabled( self ):
        self.assertTrue( self.queue._crud_agents_enabled() )
        self.queue.config_mgr = _cfg( { "crud for dataframes agents enabled": "false" } )
        self.assertFalse( self.queue._crud_agents_enabled() )


# ───────────────────── _notify_rejection / _dump_code ─────────────────────
class TestNotifyRejectionAndDumpCode( _TFQBase ):
    """Exercises _notify_rejection emit paths + exception, and _dump_code."""

    def test_rejection_emit_to_session( self ):
        self.queue.websocket_mgr.emit_to_session_sync = Mock()
        self.queue._notify_rejection( "q", "ws1", "bad" )
        self.queue.websocket_mgr.emit_to_session_sync.assert_called_once()

    def test_rejection_fallback_emit( self ):
        # no emit_to_session_sync attribute → fallback to .emit
        ws = Mock( spec=[ "emit" ] )
        self.queue.websocket_mgr = ws
        self.queue._notify_rejection( "q", "ws1", "bad" )
        ws.emit.assert_called_once()

    def test_rejection_exception_swallowed( self ):
        self.queue.debug = True
        ws = Mock( spec=[ "emit_to_session_sync" ] )
        ws.emit_to_session_sync.side_effect = Exception( "boom" )
        self.queue.websocket_mgr = ws
        with patch( "builtins.print" ):
            self.queue._notify_rejection( "q", "ws1", "bad" )   # must not raise

    def test_rejection_no_websocket_mgr( self ):
        self.queue.websocket_mgr = None
        self.queue._notify_rejection( "q", "ws1", "bad" )       # no-op, no raise

    def test_dump_code_debug_verbose( self ):
        self.queue.debug = True
        self.queue.verbose = True
        snap = Mock()
        snap.code = [ "line1", "line2" ]
        snap.question = "q"
        with patch( "builtins.print" ):
            self.queue._dump_code( snap )

    def test_dump_code_empty( self ):
        self.queue.debug = True
        self.queue.verbose = True
        snap = Mock()
        snap.code = []
        with patch( "builtins.print" ):
            self.queue._dump_code( snap )


# ───────────────────── push_job: rejection + cache-hit paths ─────────────────────

def _registry_stub( testcase, command, agent, expect, crud_enabled ):
    """
    Context manager: assert the registry binds `command` to `expect`, then swap that
    entry's factories for a stub returning `agent`.

    The injection point for the six conversational agents moved in row 10ef4b64 — they
    are built from the registry table now, so `patch.object( tfq, "MathAgent", ... )`
    misses and a REAL agent is constructed, violating this file's ZERO-real-agent
    contract. Patch the table entry instead.

    Requires:
        - command resolves to a conversational AgentSpec
        - expect is the class NAME the caller expects for this command

    Ensures:
        - fails the test if the registry binds command to some other class
        - yields a patch.dict context in which push_job builds `agent`
    """
    # One resolver now (step 2b): the same call answers what the fork produces AND
    # what gets patched, so the check and the patch can no longer drift apart.
    forked = resolve( command, crud_enabled )
    testcase.assertEqual(
        forked.factory.__name__, expect,
        f"registry bound {command!r} to {forked.factory.__name__}, expected {expect}"
    )
    spec = resolve( command, crud_enabled=False )
    stub = replace( spec, factory=lambda **kw: agent, crud_factory=lambda **kw: agent )
    return patch.dict( reg.ANSWER_COMMANDS, { spec.command: stub } )


class TestPushJobRejectionAndCache( _TFQBase ):
    """Exercises push_job rejection arms and the snapshot cache-hit branches."""

    def test_reject_empty( self ):
        with patch.object( self.queue, "_notify_rejection" ) as mk:
            r = self.queue.push_job( "", "ws1", "u1", "u@x.com" )
        self.assertIsNone( r[ "job_id" ] )
        self.assertIn( "empty", r[ "message" ].lower() )
        mk.assert_called_once()

    def test_reject_too_long( self ):
        with patch.object( self.queue, "_notify_rejection" ):
            r = self.queue.push_job( "x" * 1001, "ws1", "u1", "u@x.com" )
        self.assertIn( "too long", r[ "message" ].lower() )

    def test_reject_invalid_content( self ):
        with patch.object( self.queue, "_notify_rejection" ):
            r = self.queue.push_job( "invalid thing", "ws1", "u1", "u@x.com" )
        self.assertIn( "invalid content", r[ "message" ].lower() )

    def test_perfect_match_auto_accept( self ):
        snap = Mock(); snap.id_hash = "snap1"; snap.question = "q?"
        self.snap_mgr.get_snapshots_by_question.return_value = [ ( 100.0, snap ) ]
        with patch.object( self.queue, "_queue_best_snapshot", return_value={ "message": "queued", "job_id": "j1" } ) as mk, \
             patch.object( self.queue, "_dump_code" ), patch( "builtins.print" ):
            r = self.queue.push_job( "what time is it", "ws1", "u1", "u@x.com" )
        self.assertEqual( r[ "job_id" ], "j1" )
        mk.assert_called_once()

    def test_similarity_confirm_user_yes( self ):
        snap = Mock(); snap.id_hash = "snap1"; snap.question = "q?"
        self.snap_mgr.get_snapshots_by_question.return_value = [ ( 95.0, snap ) ]
        resp = Mock(); resp.status = "responded"; resp.response_value = "yes"
        with patch.object( tfq, "notify_user_sync", return_value=resp ), \
             patch.object( self.queue, "_queue_best_snapshot", return_value={ "message": "q", "job_id": "j2" } ) as mk, \
             patch.object( self.queue, "_dump_code" ), patch( "builtins.print" ):
            r = self.queue.push_job( "what time is it", "ws1", "u1", "u@x.com" )
        self.assertEqual( r[ "job_id" ], "j2" )
        mk.assert_called_once()

    def test_similarity_confirm_user_no_routes_to_llm( self ):
        snap = Mock(); snap.id_hash = "snap1"; snap.question = "q?"
        self.snap_mgr.get_snapshots_by_question.return_value = [ ( 95.0, snap ) ]
        resp = Mock(); resp.status = "responded"; resp.response_value = "no"
        agent = Mock(); agent.id_hash = "ag1"
        with patch.object( tfq, "notify_user_sync", return_value=resp ), \
             patch.object( self.queue, "_get_routing_command", return_value=( "agent router go to math", "" ) ), \
             _registry_stub( self, "agent router go to math", agent, "MathAgent",
                             self.queue._crud_agents_enabled() ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), \
             patch.object( self.queue, "_dump_code" ), patch( "builtins.print" ):
            r = self.queue.push_job( "what time is it", "ws1", "u1", "u@x.com" )
        self.assertEqual( r[ "job_id" ], "ag1" )

    def test_similarity_confirmation_disabled_auto_accept( self ):
        snap = Mock(); snap.id_hash = "snap1"; snap.question = "q?"
        self.snap_mgr.get_snapshots_by_question.return_value = [ ( 95.0, snap ) ]
        self.queue.config_mgr = _cfg( { "similarity confirmation enabled": False } )
        with patch.object( self.queue, "_queue_best_snapshot", return_value={ "message": "q", "job_id": "j3" } ) as mk, \
             patch.object( self.queue, "_dump_code" ), patch( "builtins.print" ):
            r = self.queue.push_job( "what time is it", "ws1", "u1", "u@x.com" )
        self.assertEqual( r[ "job_id" ], "j3" )

    def test_low_similarity_routes_to_llm( self ):
        snap = Mock(); snap.id_hash = "snap1"; snap.question = "q?"
        self.snap_mgr.get_snapshots_by_question.return_value = [ ( 50.0, snap ) ]
        agent = Mock(); agent.id_hash = "ag2"
        with patch.object( self.queue, "_get_routing_command", return_value=( "agent router go to weather", "" ) ), \
             _registry_stub( self, "agent router go to weather", agent, "WeatherAgent",
                             self.queue._crud_agents_enabled() ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            r = self.queue.push_job( "what is the weather", "ws1", "u1", "u@x.com" )
        self.assertEqual( r[ "job_id" ], "ag2" )

    def test_not_accepting_jobs_confirmation_runs_snapshot( self ):
        # queue not accepting → ConfirmationDialogue confirms → run previous best
        snap = Mock(); snap.id_hash = "snap1"
        self.queue.push_blocking_object( { "best_snapshot": snap, "question": "orig q" } )
        conf = Mock(); conf.confirmed.return_value = True
        with patch.object( tfq, "ConfirmationDialogue", return_value=conf ), \
             patch.object( self.queue, "_queue_best_snapshot", return_value={ "message": "q", "job_id": "j4" } ) as mk, \
             patch.object( self.queue, "_dump_code" ), patch( "builtins.print" ):
            r = self.queue.push_job( "yes please", "ws1", "u1", "u@x.com" )
        self.assertEqual( r[ "job_id" ], "j4" )
        mk.assert_called_once()

    def test_refactor_skips_snapshot_search( self ):
        agent = Mock(); agent.id_hash = "ag3"
        with patch.object( self.queue, "_get_routing_command", return_value=( "agent router go to math", "" ) ), \
             _registry_stub( self, "agent router go to math", agent, "MathAgent",
                             self.queue._crud_agents_enabled() ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            r = self.queue.push_job( "refactor this code", "ws1", "u1", "u@x.com" )
        self.assertEqual( r[ "job_id" ], "ag3" )
        self.snap_mgr.get_snapshots_by_question.assert_not_called()


# ───────────────────── push_job: LLM routing per-command ─────────────────────
class TestPushJobRouting( _TFQBase ):
    """Exercises the LLM-routing command dispatch arms (no similar snapshots)."""

    def setUp( self ):
        super().setUp()
        self.snap_mgr.get_snapshots_by_question.return_value = []   # no cache → LLM routing

    def _route( self, command, question="do something", user_mode=None, agent_cls=None, agent_attr=None ):
        """
        Drive one push_job routing branch with a stub agent, and return its result.

        ⚠️ TWO INJECTION POINTS, and which one applies moved in row 10ef4b64. push_job used
        to name every agent class itself, so patching this module's namespace intercepted
        construction. The six conversational agents now come from the REGISTRY, so that
        patch no longer bites — it silently misses and a REAL agent gets built, breaking
        this file's own "ZERO real agent execution" contract. That is exactly how these
        twelve tests caught the change, and the right fix is to patch where the object is
        looked up now, not to relax the assertion.

        For a registry-built agent this is STRICTLY STRONGER than the old form: it first
        asserts the table hands back the class the caller named, THEN swaps that entry's
        factory for the stub. The old version only proved something got pushed; this also
        proves the right binding was chosen, including the CRUD fork.

        Requires:
            - command is a routing string push_job can reach
            - agent_attr, when given, names the agent class expected for this command

        Ensures:
            - returns push_job's result dict
            - no real agent, push, or notify happens
        """
        agent = Mock(); agent.id_hash = "ag"
        if user_mode:
            self.queue.set_user_mode( "u1", user_mode )
        with patch.object( self.queue, "_get_routing_command", return_value=( command, "" ) ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), \
             patch( "builtins.print" ):
            if agent_attr in _REGISTRY_BUILT:
                # ⚠️ THE EFFECTIVE COMMAND, not the one passed in. A user_mode BYPASSES the
                #    router and push_job synthesises "agent router go to <mode>" itself, so
                #    test_user_mode_direct_routing passes "ignored" as the command. Resolving
                #    that would return None and the unpack below would raise — a test failing
                #    for a reason that has nothing to do with what it checks.
                effective = f"agent router go to {user_mode}" if user_mode else command
                with _registry_stub( self, effective, agent, agent_attr,
                                     self.queue._crud_agents_enabled() ):
                    return self.queue.push_job( question, "ws1", "u1", "u@x.com" )
            if agent_attr:
                # Still built by push_job itself (ReceptionistAgent) — namespace patch holds.
                with patch.object( tfq, agent_attr, return_value=agent ):
                    return self.queue.push_job( question, "ws1", "u1", "u@x.com" )
            return self.queue.push_job( question, "ws1", "u1", "u@x.com" )

    def test_calendar_crud( self ):
        r = self._route( "agent router go to calendar", agent_attr="CalendarCrudAgent" )
        self.assertEqual( r[ "job_id" ], "ag" )

    def test_calendar_non_crud( self ):
        self.queue.config_mgr = _cfg( { "crud for dataframes agents enabled": "false" } )
        r = self._route( "agent router go to calendar", agent_attr="CalendaringAgent" )
        self.assertEqual( r[ "job_id" ], "ag" )

    def test_calculator( self ):
        self.assertEqual( self._route( "agent router go to calculator", agent_attr="CalculatorAgent" )[ "job_id" ], "ag" )

    def test_math( self ):
        self.assertEqual( self._route( "agent router go to math", agent_attr="MathAgent" )[ "job_id" ], "ag" )

    def test_todo_crud( self ):
        self.assertEqual( self._route( "agent router go to todo", agent_attr="TodoCrudAgent" )[ "job_id" ], "ag" )

    def test_todo_non_crud( self ):
        self.queue.config_mgr = _cfg( { "crud for dataframes agents enabled": "false" } )
        self.assertEqual( self._route( "agent router go to todo list", agent_attr="TodoListAgent" )[ "job_id" ], "ag" )

    def test_datetime( self ):
        self.assertEqual( self._route( "agent router go to datetime", agent_attr="DateAndTimeAgent" )[ "job_id" ], "ag" )

    def test_weather( self ):
        self.assertEqual( self._route( "agent router go to weather", agent_attr="WeatherAgent" )[ "job_id" ], "ag" )

    def test_receptionist( self ):
        self.assertEqual( self._route( "agent router go to receptionist", agent_attr="ReceptionistAgent" )[ "job_id" ], "ag" )

    def test_none_command_to_receptionist( self ):
        self.assertEqual( self._route( "none", agent_attr="ReceptionistAgent" )[ "job_id" ], "ag" )

    def test_automatic_routing_already_active( self ):
        with patch.object( self.queue, "_get_routing_command",
                           return_value=( "agent router go to automatic routing mode", "" ) ), \
             patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            r = self.queue.push_job( "go automatic", "ws1", "u1", "u@x.com" )
        self.assertIn( "already", r[ "message" ].lower() )

    def test_search_and_summarize( self ):
        search = Mock(); search.get_results.return_value = "summary text"
        with patch.object( self.queue, "_get_routing_command", return_value=( "anything", "" ) ), \
             patch.object( tfq, "LupinSearch", return_value=search ), \
             patch.object( self.queue, "_notify" ), patch.object( self.queue, "push" ), \
             patch( "builtins.print" ):
            r = self.queue.push_job( "search and summarize quantum computing", "ws1", "u1", "u@x.com" )
        search.search_and_summarize_the_web.assert_called_once()

    def test_unknown_command_hands_off_to_receptionist( self ):
        # 720ce725 branch 1 — a GENUINE non-resolution: _get_routing_command returns
        # ("unknown","") on any XML parse failure / gibberish. Behavior must be a
        # receptionist hand-off, NOT a silent web-search of the user's question.
        agent = Mock(); agent.id_hash = "ag"
        with patch.object( self.queue, "_get_routing_command", return_value=( "unknown", "" ) ), \
             patch.object( tfq, "ReceptionistAgent", return_value=agent ) as mk_rec, \
             patch.object( self.queue, "_search_and_summarize_safely" ) as mk_search, \
             patch.object( self.queue, "push" ) as mk_push, \
             patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            r = self.queue.push_job( "what time is it", "ws1", "u1", "u@x.com" )
        # observable behavior: receptionist constructed + job pushed, no web-search
        mk_rec.assert_called_once()
        mk_search.assert_not_called()
        mk_push.assert_called_once()
        self.assertEqual( r[ "job_id" ], "ag" )

    def test_unwired_command_fails_loudly( self ):
        # 720ce725 branch 2 — the router EMITTED a command string that resolves
        # nowhere (not conversational, not receptionist/none, not in JOB_ARG_CONTRACTS).
        # Behavior must be a LOUD error-return: no web-search, no receptionist
        # smoothing the routing bug into a friendly non-answer, no job pushed.
        with patch.object( self.queue, "_get_routing_command",
                           return_value=( "agent router go to nonexistent", "" ) ), \
             patch.object( tfq, "ReceptionistAgent" ) as mk_rec, \
             patch.object( self.queue, "_search_and_summarize_safely" ) as mk_search, \
             patch.object( self.queue, "push" ) as mk_push, \
             patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            r = self.queue.push_job( "route me nowhere", "ws1", "u1", "u@x.com" )
        mk_search.assert_not_called()        # NOT web-searched (the old defect)
        mk_rec.assert_not_called()           # NOT smoothed over by the receptionist
        mk_push.assert_not_called()          # no job created
        self.assertIn( "unroutable command (no wiring)", r[ "message" ].lower() )
        self.assertIsNone( r[ "job_id" ] )

    def test_user_mode_direct_routing( self ):
        # user in 'math' mode → bypass LLM, command synthesized
        r = self._route( "ignored", user_mode="math", agent_attr="MathAgent" )
        # _get_routing_command should NOT have driven it; mode synthesized "agent router go to math"
        self.assertEqual( r[ "job_id" ], "ag" )

    def test_ding_for_new_job_emits_sound( self ):
        agent = Mock(); agent.id_hash = "ag"
        with patch.object( self.queue, "_get_routing_command", return_value=( "agent router go to math", "" ) ), \
             _registry_stub( self, "agent router go to math", agent, "MathAgent",
                             self.queue._crud_agents_enabled() ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            self.queue.push_job( "add two numbers", "ws1", "u1", "u@x.com" )
        # math sets ding_for_new_job=True → websocket emits the sound update
        self.ws.emit.assert_any_call( 'notification_sound_update', { 'soundFile': '/static/gentle-gong.mp3' } )

    def test_agentic_command_via_llm_disambiguation( self ):
        cmd = next( iter( tfq.JOB_ARG_CONTRACTS ) )
        with patch.object( self.queue, "_get_routing_command", return_value=( cmd, "args" ) ), \
             patch.object( self.queue, "_confirm_agentic_routing", return_value=cmd ), \
             patch.object( self.queue, "_handle_agentic_command", return_value="submitted" ) as mk, \
             patch( "builtins.print" ):
            r = self.queue.push_job( "investigate something", "ws1", "u1", "u@x.com" )
        self.assertIsNone( r[ "job_id" ] )
        mk.assert_called_once()

    def test_agentic_command_user_cancels( self ):
        cmd = next( iter( tfq.JOB_ARG_CONTRACTS ) )
        with patch.object( self.queue, "_get_routing_command", return_value=( cmd, "args" ) ), \
             patch.object( self.queue, "_confirm_agentic_routing", return_value=None ), \
             patch( "builtins.print" ):
            r = self.queue.push_job( "investigate", "ws1", "u1", "u@x.com" )
        self.assertIn( "cancelled", r[ "message" ].lower() )

    def test_agentic_command_explicit_mode_skips_disambiguation( self ):
        # find an agentic mode whose mapped command is in JOB_ARG_CONTRACTS
        mode = next( iter( AGENTIC_MODE_MAP ) )
        cmd  = AGENTIC_MODE_MAP[ mode ]
        if cmd not in tfq.JOB_ARG_CONTRACTS:
            self.skipTest( "mapped command not in JOB_ARG_CONTRACTS registry" )
        self.queue.set_user_mode( "u1", mode )
        with patch.object( self.queue, "_handle_agentic_command", return_value="ok" ) as mk, \
             patch( "builtins.print" ):
            r = self.queue.push_job( "do agentic", "ws1", "u1", "u@x.com" )
        mk.assert_called_once()


# ───────────────────── _queue_best_snapshot / _get_routing_command ─────────────────────
class TestQueueBestSnapshotAndRouting( _TFQBase ):
    """Exercises _queue_best_snapshot (jobs-ahead + empty) and _get_routing_command."""

    def _snap( self ):
        job = Mock(); job.id_hash = "copy1"
        snap = Mock(); snap.id_hash = "orig1"; snap.last_question_asked = "q?"
        snap.get_copy.return_value = job
        return snap, job

    def test_queue_best_snapshot_jobs_ahead( self ):
        snap, job = self._snap()
        with patch.object( self.queue, "size", return_value=2 ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ) as mk, \
             patch( "builtins.print" ):
            r = self.queue._queue_best_snapshot( snap, 95.0, "u1", "u@x.com" )
        # job.id_hash = register_scoped_job( best_snapshot.id_hash ) → echoes "orig1"
        self.assertEqual( r[ "job_id" ], "orig1" )
        mk.assert_called_once()     # "N jobs ahead" notify

    def test_queue_best_snapshot_empty( self ):
        snap, job = self._snap()
        with patch.object( self.queue, "size", return_value=0 ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ) as mk, \
             patch( "builtins.print" ):
            r = self.queue._queue_best_snapshot( snap, 95.0, "u1", "u@x.com" )
        mk.assert_not_called()      # no jobs-ahead notify

    def test_get_routing_command_success( self ):
        llm = Mock(); llm.run.return_value = "<response><command>x</command></response>"
        self.queue.llm_factory.get_client = Mock( return_value=llm )
        parsed = Mock(); parsed.command = "agent router go to math"; parsed.args = "a"
        with patch( "cosa.rest.todo_fifo_queue.du.get_file_as_string", return_value="{voice_command}" ), \
             patch( "cosa.rest.todo_fifo_queue.du.get_project_root", return_value="/p" ), \
             patch.object( tfq.CommandResponse, "from_xml", return_value=parsed ), \
             patch( "builtins.print" ):
            cmd, args = self.queue._get_routing_command( "what is 2+2" )
        self.assertEqual( cmd, "agent router go to math" )
        self.assertEqual( args, "a" )

    def test_get_routing_command_xml_parse_error( self ):
        llm = Mock(); llm.run.return_value = "garbage"
        self.queue.llm_factory.get_client = Mock( return_value=llm )
        with patch( "cosa.rest.todo_fifo_queue.du.get_file_as_string", return_value="{voice_command}" ), \
             patch( "cosa.rest.todo_fifo_queue.du.get_project_root", return_value="/p" ), \
             patch.object( tfq.CommandResponse, "from_xml", side_effect=tfq.XMLParsingError( "bad" ) ), \
             patch( "builtins.print" ):
            cmd, args = self.queue._get_routing_command( "q" )
        self.assertEqual( cmd, "unknown" )

    def test_get_routing_command_generic_error( self ):
        llm = Mock(); llm.run.return_value = "x"
        self.queue.llm_factory.get_client = Mock( return_value=llm )
        with patch( "cosa.rest.todo_fifo_queue.du.get_file_as_string", return_value="{voice_command}" ), \
             patch( "cosa.rest.todo_fifo_queue.du.get_project_root", return_value="/p" ), \
             patch.object( tfq.CommandResponse, "from_xml", side_effect=RuntimeError( "boom" ) ), \
             patch( "builtins.print" ):
            cmd, args = self.queue._get_routing_command( "q" )
        self.assertEqual( cmd, "unknown" )


# ───────────────────── _confirm_agentic_routing ─────────────────────
class TestConfirmAgenticRouting( _TFQBase ):
    """Exercises _confirm_agentic_routing timeout/cancel/parse/reverse-lookup arms."""

    def _cmd( self ):
        return next( iter( self.queue.CARD_LABELS ) )

    def test_timeout_aborts_none( self ):
        # Row cad45cf1: a silent timeout must NOT masquerade as a confirmation of
        # the detected command — it aborts (returns None) instead of auto-running.
        cmd = self._cmd()
        resp = Mock(); resp.is_timeout = True; resp.is_error = False
        with patch.object( tfq, "notify_user_sync", return_value=resp ), patch( "builtins.print" ):
            self.assertIsNone( self.queue._confirm_agentic_routing( cmd, "", "u1", "u@x.com", "q" ) )

    def test_error_aborts_none( self ):
        # Row cad45cf1: a notification-system error is also not a confirmation → abort.
        cmd = self._cmd()
        resp = Mock(); resp.is_timeout = False; resp.is_error = True
        with patch.object( tfq, "notify_user_sync", return_value=resp ), patch( "builtins.print" ):
            self.assertIsNone( self.queue._confirm_agentic_routing( cmd, "", "u1", "u@x.com", "q" ) )

    def test_timeout_seconds_read_from_config_not_literal( self ):
        # Row cad45cf1: the wait window comes from the config key, not a hardcoded 30.
        cmd = self._cmd()
        self.queue.config_mgr = _cfg( { "agentic routing confirm timeout seconds": 47 } )
        resp = Mock(); resp.is_timeout = False; resp.is_error = False; resp.response_value = "Cancel"
        with patch.object( tfq, "notify_user_sync", return_value=resp ) as m_notify, patch( "builtins.print" ):
            self.queue._confirm_agentic_routing( cmd, "", "u1", "u@x.com", "q" )
        sent_request = m_notify.call_args[ 0 ][ 0 ]
        self.assertEqual( sent_request.timeout_seconds, 47 )

    def test_cancel_returns_none( self ):
        cmd = self._cmd()
        resp = Mock(); resp.is_timeout = False; resp.is_error = False; resp.response_value = "Cancel"
        with patch.object( tfq, "notify_user_sync", return_value=resp ), patch( "builtins.print" ):
            self.assertIsNone( self.queue._confirm_agentic_routing( cmd, "", "u1", "u@x.com", "q" ) )

    def test_json_answer_reverse_lookup( self ):
        cmd  = self._cmd()
        name = self.queue.CARD_LABELS[ cmd ]
        resp = Mock(); resp.is_timeout = False; resp.is_error = False
        resp.response_value = '{"answers": {"Command": "' + name + '"}}'
        with patch.object( tfq, "notify_user_sync", return_value=resp ), patch( "builtins.print" ):
            self.assertEqual( self.queue._confirm_agentic_routing( cmd, "", "u1", "u@x.com", "q" ), cmd )

    def test_bad_json_falls_back( self ):
        cmd = self._cmd()
        resp = Mock(); resp.is_timeout = False; resp.is_error = False
        resp.response_value = "{not valid json"
        with patch.object( tfq, "notify_user_sync", return_value=resp ), patch( "builtins.print" ):
            # unparseable → kept as-is → no reverse-lookup match → fallback to command
            self.assertEqual( self.queue._confirm_agentic_routing( cmd, "", "u1", "u@x.com", "q" ), cmd )


# ───────────────────── _handle_agentic_command ─────────────────────
class TestHandleAgenticCommand( _TFQBase ):
    """Exercises _handle_agentic_command disabled/cancel/job-None/success arms."""

    def _cmd( self ):
        return next( iter( tfq.JOB_ARG_CONTRACTS ) )

    def test_disabled( self ):
        self.queue.config_mgr = _cfg( { "runtime argument expeditor enabled": False } )
        msg = self.queue._handle_agentic_command( self._cmd(), "", "u1", "u@x.com", "ws1", "q" )
        self.assertIn( "disabled", msg.lower() )

    def _run_expeditor_failure( self, reason ):
        exp = Mock(); exp.expedite.return_value = None; exp._last_expedite_reason = reason
        with patch.object( tfq, "RuntimeArgumentExpeditor", return_value=exp ), \
             patch.object( tfq, "emit_job_state_transition" ), \
             patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            return self.queue._handle_agentic_command( self._cmd(), "", "u1", "u@x.com", "ws1", "q" )

    def test_expeditor_declined_says_cancelled( self ):
        # A real user "no" is the ONE outcome that may be reported as a cancellation.
        msg = self._run_expeditor_failure( BATCH_DECLINED )
        self.assertIn( "cancelled", msg.lower() )

    def test_expeditor_undeliverable_never_says_cancelled( self ):
        # Bug 68198c9f: a prompt that never reached the user must NOT blame them.
        msg = self._run_expeditor_failure( BATCH_UNREACHABLE )
        self.assertNotIn( "cancel", msg.lower() )
        self.assertNotIn( "declined", msg.lower() )

    def test_job_none( self ):
        exp = Mock(); exp.expedite.return_value = { "some": "args" }
        with patch.object( tfq, "RuntimeArgumentExpeditor", return_value=exp ), \
             patch.object( tfq, "create_agentic_job", return_value=None ), \
             patch.object( tfq, "emit_job_state_transition" ), \
             patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            msg = self.queue._handle_agentic_command( self._cmd(), "", "u1", "u@x.com", "ws1", "q" )
        self.assertIn( "failed", msg.lower() )

    def test_success_with_scheduling( self ):
        exp = Mock()
        exp.expedite.return_value = { "scheduled_at": "2026-06-02T02:00:00", "monopolize": "yes", "query": "q" }
        job = Mock(); job.JOB_TYPE = "deep_research"; job.id_hash = "x"
        with patch.object( tfq, "RuntimeArgumentExpeditor", return_value=exp ), \
             patch.object( tfq, "create_agentic_job", return_value=job ), \
             patch.object( tfq, "emit_job_state_transition" ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            msg = self.queue._handle_agentic_command( self._cmd(), "", "u1", "u@x.com", "ws1", "q" )
        self.assertIn( "submitted", msg.lower() )
        self.assertEqual( job.scheduled_at, "2026-06-02T02:00:00" )
        self.assertTrue( job.monopolize )

    def test_success_immediately_normalized( self ):
        exp = Mock()
        exp.expedite.return_value = { "scheduled_at": "immediately", "monopolize": "no" }
        job = Mock(); job.JOB_TYPE = "podcast"; job.id_hash = "x"
        with patch.object( tfq, "RuntimeArgumentExpeditor", return_value=exp ), \
             patch.object( tfq, "create_agentic_job", return_value=job ), \
             patch.object( tfq, "emit_job_state_transition" ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            msg = self.queue._handle_agentic_command( self._cmd(), "", "u1", "u@x.com", "ws1", "q" )
        self.assertIn( "submitted", msg.lower() )


# ───────────────────── push_job_agentic ─────────────────────
class TestPushJobAgentic( _TFQBase ):
    """Exercises push_job_agentic success / unknown-command / construction-exception arms."""

    def _cmd( self ):
        return next( iter( tfq.JOB_ARG_CONTRACTS ) )

    def test_success( self ):
        job = Mock(); job.JOB_TYPE = "deep_research"; job.id_hash = "x"
        with patch.object( tfq, "create_agentic_job", return_value=job ), \
             patch.object( tfq, "emit_job_state_transition" ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            r = self.queue.push_job_agentic( self._cmd(), { "query": "q" }, "ws1", "u1", "u@x.com",
                                             question="q", scheduled_at="2026-06-02T02:00:00", monopolize=True )
        self.assertIsNotNone( r[ "job_id" ] )
        self.assertEqual( job.scheduled_at, "2026-06-02T02:00:00" )
        self.assertTrue( job.monopolize )

    def test_unknown_command( self ):
        with patch.object( tfq, "create_agentic_job", return_value=None ), \
             patch.object( tfq, "emit_job_state_transition" ), \
             patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            r = self.queue.push_job_agentic( "bogus command", {}, "ws1", "u1", "u@x.com" )
        self.assertIsNone( r[ "job_id" ] )
        self.assertIn( "unknown", r[ "message" ].lower() )

    def test_construction_exception( self ):
        with patch.object( tfq, "create_agentic_job", side_effect=Exception( "ctor boom" ) ), \
             patch.object( tfq, "emit_job_state_transition" ), \
             patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            r = self.queue.push_job_agentic( self._cmd(), {}, "ws1", "u1", "u@x.com" )
        self.assertIsNone( r[ "job_id" ] )
        self.assertIn( "construction failed", r[ "message" ].lower() )


# ───────────────────── push / delete_by_id_hash overrides ─────────────────────
class TestQueueOverrides( _TFQBase ):
    """Exercises the push() coordination override + delete_by_id_hash notify override."""

    def _job( self ):
        from cosa.rest.job_state import JobState
        # spec=QueueableJob so the double satisfies push()'s hardened
        # is_queueable_job() guard (bare Mock() fails the runtime_checkable
        # data-member check under py3.12+); all attrs below are SET (not access-set),
        # incl. the non-protocol original_args, which remains settable under spec.
        j = Mock( spec=QueueableJob )
        j.id_hash            = "j1"
        j.user_id            = "u1"
        j.last_question_asked = "q?"
        j.job_type           = "MathAgent"
        j.created_date       = "2026-06-01"
        j.scheduled_at       = None
        j.monopolize         = False
        j.state              = JobState.QUEUED
        j.user_email         = "u@x.com"
        j.session_id         = "ws1"
        j.routing_command    = "agent router go to math"
        j.original_args      = {}
        return j

    def test_push_emits_transition_and_notifies_consumer( self ):
        job = self._job()
        with patch.object( tfq, "emit_job_state_transition" ) as mk_emit, patch( "builtins.print" ):
            self.queue.push( job )
        self.assertEqual( self.queue.size(), 1 )
        mk_emit.assert_called_once()

    def test_push_debug_branch( self ):
        self.queue.debug = True
        job = self._job()
        with patch.object( tfq, "emit_job_state_transition" ), patch( "builtins.print" ):
            self.queue.push( job )

    def test_delete_by_id_hash_found_notifies( self ):
        job = self._job()
        with patch.object( tfq, "emit_job_state_transition" ), patch( "builtins.print" ):
            self.queue.push( job )
        self.assertTrue( self.queue.delete_by_id_hash( "j1" ) )

    def test_delete_by_id_hash_absent( self ):
        with patch( "builtins.print" ):
            self.assertFalse( self.queue.delete_by_id_hash( "missing" ) )


class TestBranchFills( _TFQBase ):
    """Targeted fills for debug-gated and edge branches across the module."""

    def test_parse_salutations_all_salutations( self ):
        # every token is a salutation → the for-loop exhausts WITHOUT break (201->209)
        sal, rest = self.queue.parse_salutations( "hey buddy" )
        self.assertEqual( sal, "hey buddy" )
        self.assertEqual( rest, "" )

    def test_rejection_success_debug_print( self ):
        self.queue.debug = True
        self.queue.websocket_mgr.emit_to_session_sync = Mock()
        with patch( "builtins.print" ):
            self.queue._notify_rejection( "q", "ws1", "bad" )      # 363-364

    def test_rejection_exception_debug_off( self ):
        self.queue.debug = False
        ws = Mock( spec=[ "emit_to_session_sync" ] )
        ws.emit_to_session_sync.side_effect = Exception( "boom" )
        self.queue.websocket_mgr = ws
        self.queue._notify_rejection( "q", "ws1", "bad" )          # 365 except, 366 false arm

    def test_dump_code_debug_off( self ):
        self.queue.debug = False
        self.queue._dump_code( Mock() )                            # 836 false arm → exit

    def test_log_query_error_debug_off( self ):
        self.queue.debug = False
        self.queue.query_log.log_query.side_effect = Exception( "db down" )
        # must not raise; 817 except, 818 false arm (no print)
        self.queue._log_query_with_results( "v", "n", "g", "u1", "ws1", {}, {}, {} )

    def test_gisting_disabled_uses_normalizer( self ):
        self.queue.config_mgr = _cfg( { "fifo todo queue enable input gisting": False } )
        self.snap_mgr.get_snapshots_by_question.return_value = []
        agent = Mock(); agent.id_hash = "ag"
        with patch.object( self.queue, "_get_routing_command", return_value=( "agent router go to math", "" ) ), \
             _registry_stub( self, "agent router go to math", agent, "MathAgent",
                             self.queue._crud_agents_enabled() ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            self.queue.push_job( "add numbers", "ws1", "u1", "u@x.com" )   # 418 else arm

    def test_push_job_debug_verbose_block( self ):
        self.queue.debug = True
        self.queue.verbose = True
        self.snap_mgr.get_snapshots_by_question.return_value = []
        agent = Mock(); agent.id_hash = "ag"
        with patch.object( self.queue, "_get_routing_command", return_value=( "agent router go to math", "" ) ), \
             _registry_stub( self, "agent router go to math", agent, "MathAgent",
                             self.queue._crud_agents_enabled() ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), \
             patch.object( self.queue, "_dump_code" ), patch( "builtins.print" ):
            self.queue.push_job( "add numbers", "ws1", "u1", "u@x.com" )   # 439-443 + 664 router debug

    def test_direct_mode_bypass_debug( self ):
        self.queue.debug = True
        self.queue.set_user_mode( "u1", "math" )                   # MODE_TO_AGENT key
        self.snap_mgr.get_snapshots_by_question.return_value = []
        agent = Mock(); agent.id_hash = "ag"
        with patch.object( tfq, "MathAgent", return_value=agent ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            self.queue.push_job( "compute", "ws1", "u1", "u@x.com" )       # 656-657 direct-mode debug

    def test_agentic_mode_bypass_debug( self ):
        self.queue.debug = True
        mode = next( iter( AGENTIC_MODE_MAP ) )
        cmd  = AGENTIC_MODE_MAP[ mode ]
        if cmd not in tfq.JOB_ARG_CONTRACTS:
            self.skipTest( "mapped command not in JOB_ARG_CONTRACTS registry" )
        self.queue.set_user_mode( "u1", mode )
        self.snap_mgr.get_snapshots_by_question.return_value = []
        with patch.object( self.queue, "_handle_agentic_command", return_value="ok" ), patch( "builtins.print" ):
            self.queue.push_job( "do agentic", "ws1", "u1", "u@x.com" )    # 648-649 agentic-mode debug

    def test_handle_agentic_command_debug( self ):
        self.queue.debug = True
        cmd = next( iter( tfq.JOB_ARG_CONTRACTS ) )
        exp = Mock(); exp.expedite.return_value = { "query": "q" }
        job = Mock(); job.JOB_TYPE = "deep_research"; job.id_hash = "x"
        with patch.object( tfq, "RuntimeArgumentExpeditor", return_value=exp ), \
             patch.object( tfq, "create_agentic_job", return_value=job ), \
             patch.object( tfq, "emit_job_state_transition" ), \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), patch( "builtins.print" ):
            self.queue._handle_agentic_command( cmd, "", "u1", "u@x.com", "ws1", "q" )   # 1097 debug print


def isolated_unit_test():
    """
    Run this module's tests in isolation.

    Ensures:
        - returns True when all tests pass, False otherwise
    """
    suite  = unittest.TestLoader().loadTestsFromModule( sys.modules[ __name__ ] )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    return result.wasSuccessful()


if __name__ == "__main__":
    isolated_unit_test()
