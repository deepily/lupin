#!/usr/bin/env python3
"""
Entry-coverage pins for `TodoFifoQueue.push_job` — the two branches that step 6c
would silently drop when `push_job` is wired to `AskFlow`.

WHY THIS FILE EXISTS (B0(i), brain-integration cascade plan, 2026-08-21). The plan
found that `AskFlow.run()` reads no user mode and that `registry.resolve()` is
CONVERSATIONAL-scoped, so an agentic command resolves to nothing there. Both losses
are invisible to the suites that already exist, because those suites call
`todo_fifo_queue` directly and keep passing after `push_job` stops reaching this code.

WHAT MAKES THESE NON-VACUOUS. The pin is an ABSENCE assertion: the LLM router was
NEVER CALLED. `test_todo_fifo_queue_coverage.py::test_user_mode_direct_routing`
carries the comment "_get_routing_command should NOT have driven it" and then asserts
only that a job came back — which is true whether the router ran or not. Every test
here asserts the absence, and `TestControlsProveTheAbsenceIsReal` proves the absence
assertion can go red at all.

Boundary-mock discipline mirrors `test_todo_fifo_queue_coverage.py`: every heavy
constructor dependency is patched at import site. ZERO real LLM/embedding/DB/network
/agent execution.

Run: PYTHONPATH=src python -m pytest src/cosa/tests/unit/rest/test_push_job_entry_coverage.py -v
"""

import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import cosa.rest.todo_fifo_queue as tfq
import cosa.rest.v2.registry as reg
from cosa.rest.todo_fifo_queue import TodoFifoQueue, MODE_TO_AGENT, AGENTIC_MODE_MAP
from cosa.rest.v2.registry import resolve, resolve_voice


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


def _cfg():
    """Build a config_mgr mock whose .get returns _CONFIG."""
    data = dict( _CONFIG )
    m = Mock()
    m.get.side_effect = lambda key, default=None, return_type=None: data.get( key, default )
    return m


class _PushJobHarness( unittest.TestCase ):
    """Builds a TodoFifoQueue with every heavy dependency boundary-mocked."""

    def setUp( self ):
        self._patchers = []
        for name in ( "LlmClientFactory", "Gister", "GistNormalizer", "Normalizer",
                      "QueryLogTable", "EmbeddingManager", "get_embedding_provider" ):
            p = patch.object( tfq, name )
            p.start()
            self._patchers.append( p )

        self.ws       = Mock()
        self.snap_mgr = Mock()
        self.queue    = TodoFifoQueue(
            websocket_mgr = self.ws, snapshot_mgr = self.snap_mgr, app = Mock(),
            config_mgr    = _cfg(),  debug        = False,         verbose = False,
        )
        self.queue.gist_normalizer.get_normalized_gist    = Mock( return_value="gist" )
        self.queue.normalizer.normalize                   = Mock( return_value="normalized" )
        self.queue._embedding_provider.generate_embedding = Mock( return_value=[ 0.1, 0.2 ] )
        self.queue.query_log.log_query                    = Mock()
        self.queue.user_job_tracker                       = Mock()
        self.queue.user_job_tracker.register_scoped_job   = Mock( side_effect=lambda idh, *a, **k: idh )
        # No cache candidate: every case here must reach the routing block.
        self.snap_mgr.get_snapshots_by_question.return_value = []

    def tearDown( self ):
        for p in reversed( self._patchers ):
            p.stop()

    # ---------------------------------------------------------------- helpers
    def _stub_registry_entry( self, command, agent ):
        """Swap the registry entry for `command` so no real agent is constructed."""
        spec = resolve( command )
        self.assertIsNotNone( spec, f"{command!r} does not resolve — the test's premise is wrong" )
        stub = replace( spec, factory=lambda **kw: agent, crud_factory=lambda **kw: agent )
        return patch.dict( reg.ANSWER_COMMANDS, { spec.command: stub } )


class TestModeBranchNeverCallsTheRouter( _PushJobHarness ):
    """A user in a mode has already chosen; the LLM router must not be consulted."""

    def test_direct_mode_bypasses_the_router( self ):
        # "todo" is in MODE_TO_AGENT only — the f-string synthesis arm (todo_fifo_queue.py:726).
        agent = Mock(); agent.id_hash = "ag"
        self.queue.set_user_mode( "u1", "todo" )
        with self._stub_registry_entry( "agent router go to todo", agent ), \
             patch.object( self.queue, "_get_routing_command" ) as router, \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), \
             patch( "builtins.print" ):
            result = self.queue.push_job( "add milk to my list", "ws1", "u1", "u@x.com" )
        router.assert_not_called()                       # THE pin — an absence, not an outcome
        self.assertEqual( result[ "job_id" ], "ag" )

    def test_agentic_mode_bypasses_the_router( self ):
        # An agentic mode takes its command straight from AGENTIC_MODE_MAP (:719).
        mode    = "deep_research"
        command = AGENTIC_MODE_MAP[ mode ]
        self.assertIn( command, tfq.JOB_ARG_CONTRACTS,
                       "premise broken: the mapped command must be an agentic contract" )
        self.queue.set_user_mode( "u1", mode )
        with patch.object( self.queue, "_get_routing_command" ) as router, \
             patch.object( self.queue, "_handle_agentic_command", return_value="ok" ) as handle, \
             patch( "builtins.print" ):
            self.queue.push_job( "look into pgvector tuning", "ws1", "u1", "u@x.com" )
        router.assert_not_called()                       # THE pin
        handle.assert_called_once()
        self.assertEqual( handle.call_args[ 0 ][ 0 ], command )

    def test_receptionist_mode_runs_the_receptionist_and_still_skips_the_router( self ):
        """
        The one MODE_TO_AGENT key that takes a different branch from the other six.

        "receptionist" synthesises "agent router go to receptionist", which resolve()
        returns None for by design (CommandClass.NONE, registry.py:234), so push_job
        falls past the conversational arm to its own receptionist branch at
        todo_fifo_queue.py:791 and builds the agent there. That is correct today and it
        is audit row 13 — after 6c the same None sends AskFlow to _receptionist under
        route_reason "unknown_command", the right agent under a reason that says the
        router failed when it did not.

        Covered here, not fixed here: the mode still has to skip the router.
        """
        agent = Mock(); agent.id_hash = "ag"
        self.queue.set_user_mode( "u1", "receptionist" )
        self.assertIsNone( resolve( "agent router go to receptionist" ),
                           "premise broken: resolve() now returns a spec for the receptionist" )
        with patch.object( self.queue, "_get_routing_command" ) as router, \
             patch.object( tfq, "ReceptionistAgent", return_value=agent ) as receptionist, \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), \
             patch( "builtins.print" ):
            result = self.queue.push_job( "who are you", "ws1", "u1", "u@x.com" )
        router.assert_not_called()                       # THE pin
        receptionist.assert_called_once()                # and it really was the receptionist
        self.assertEqual( result[ "job_id" ], "ag" )

    def test_every_mode_key_reaches_one_of_the_two_bypasses( self ):
        """
        No mode key falls through to the router — every key DRIVEN THROUGH push_job.

        The first version of this test only asserted that set_user_mode accepted the
        key, which is true whether or not push_job then consults the router — the exact
        vacuous shape this file exists to replace. Pocholo caught it on review. Each key
        now runs the real method and the assertion is the absence.
        """
        agent = Mock(); agent.id_hash = "ag"
        for mode in list( AGENTIC_MODE_MAP ) + list( MODE_TO_AGENT ):
            with self.subTest( mode=mode ):
                self.queue.set_user_mode( "u1", mode )
                self.assertIsNotNone( self.queue.get_user_mode( "u1" ),
                                      f"set_user_mode rejected {mode!r} — it is in a routing map" )
                with patch.object( self.queue, "_get_routing_command" ) as router, \
                     patch.object( self.queue, "_handle_agentic_command", return_value="ok" ), \
                     patch.object( self.queue, "_confirm_agentic_routing", return_value=None ), \
                     patch.object( tfq, "ReceptionistAgent", return_value=agent ), \
                     patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), \
                     patch( "builtins.print" ):
                    # The conversational modes build a real agent from the registry;
                    # stub whichever command this mode synthesises so nothing heavy runs.
                    # "receptionist" is the one mode whose command resolve() returns None
                    # for (it is CommandClass.NONE), so push_job builds the agent itself
                    # from this module's namespace — hence the ReceptionistAgent patch
                    # above. Without it this test opens a real outbound connection and
                    # the unit tier's network guard fails the whole run.
                    command = AGENTIC_MODE_MAP.get( mode ) or f"agent router go to {mode}"
                    spec    = resolve( command )
                    if spec is not None:
                        with self._stub_registry_entry( command, agent ):
                            self.queue.push_job( "do the thing", "ws1", "u1", "u@x.com" )
                    else:
                        self.queue.push_job( "do the thing", "ws1", "u1", "u@x.com" )
                    router.assert_not_called()


class TestAgenticEarlyReturn( _PushJobHarness ):
    """The agentic branch pushes and notifies inside its helper, then returns early."""

    def test_agentic_branch_returns_no_job_id_and_never_pushes( self ):
        command = next( iter( tfq.JOB_ARG_CONTRACTS ) )
        with patch.object( self.queue, "_get_routing_command", return_value=( command, "args" ) ), \
             patch.object( self.queue, "_confirm_agentic_routing", return_value=command ), \
             patch.object( self.queue, "_handle_agentic_command", return_value="submitted" ) as handle, \
             patch.object( self.queue, "push" ) as push, \
             patch( "builtins.print" ):
            result = self.queue.push_job( "run the thing", "ws1", "u1", "u@x.com" )
        handle.assert_called_once()
        push.assert_not_called()                         # the helper owns the push
        self.assertIsNone( result[ "job_id" ] )
        self.assertEqual( result[ "message" ], "submitted" )

    def test_llm_routed_agentic_command_asks_before_running( self ):
        command = next( iter( tfq.JOB_ARG_CONTRACTS ) )
        with patch.object( self.queue, "_get_routing_command", return_value=( command, "args" ) ), \
             patch.object( self.queue, "_confirm_agentic_routing", return_value=None ) as confirm, \
             patch( "builtins.print" ):
            result = self.queue.push_job( "run the thing", "ws1", "u1", "u@x.com" )
        confirm.assert_called_once()
        self.assertIn( "cancelled", result[ "message" ].lower() )
        self.assertIsNone( result[ "job_id" ] )


class TestControlsProveTheAbsenceIsReal( _PushJobHarness ):
    """Must-fail controls: an `assert_not_called` that can never fail proves nothing."""

    def test_without_a_mode_the_router_IS_called( self ):
        agent = Mock(); agent.id_hash = "ag"
        with self._stub_registry_entry( "agent router go to todo", agent ), \
             patch.object( self.queue, "_get_routing_command",
                           return_value=( "agent router go to todo", "" ) ) as router, \
             patch.object( self.queue, "push" ), patch.object( self.queue, "_notify" ), \
             patch( "builtins.print" ):
            self.queue.push_job( "add milk to my list", "ws1", "u1", "u@x.com" )
        router.assert_called_once()

    def test_without_a_mode_the_agentic_command_is_confirmed_first( self ):
        command = AGENTIC_MODE_MAP[ "deep_research" ]
        with patch.object( self.queue, "_get_routing_command", return_value=( command, "" ) ), \
             patch.object( self.queue, "_confirm_agentic_routing", return_value=command ) as confirm, \
             patch.object( self.queue, "_handle_agentic_command", return_value="ok" ), \
             patch( "builtins.print" ):
            self.queue.push_job( "look into pgvector tuning", "ws1", "u1", "u@x.com" )
        confirm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
