#!/usr/bin/env python3
"""
POST-MERGE LIVE CHECK for the v2 voice path: a todo, a math and a weather question.

WHAT THIS PROVES, and why it is not covered by anything else in the pyramid.
    The unit and cosa tiers prove the flow's pieces. The through-path tests prove the
    switch and the tombstones against an in-process app. NONE of them proves a spoken
    question reaches a running server, gets routed to the agent it should, and comes
    back with an answer. That is what this file does, against the real API.

    Plan §Verification, "Live check": *"speak a todo, a math and a weather request;
    confirm the job card appears, the answer arrives over the websocket, and the CRUD
    agent handled the todo."*

VENUE: `:8000`, EVERY VARIANT. NOT `:7999`.
    🔴 CORRECTED 2026-08-21 — my first version of this file claimed the read-shaped todo
    kept the run `:7999`-legal. That was WRONG, and the reason is worth stating because
    it defeats the obvious reasoning: **EVERY ask writes a snapshot row, whatever the
    question was.** `flow._maybe_write_back` (`flow.py:287-300`) writes when
    `snapshotable and outcome.status == "done"`, and `snapshotable` defaults to **True**
    on the registry entry (`registry.py:82`). So the math question writes. The weather
    question writes. A "read-shaped" todo writes. Shaping the QUESTION to avoid a
    mutation cannot work when the mutation belongs to the FLOW, not to the agent.
    (Found by Pocholo 📣 on review; verified here at `flow.py:291` / `registry.py:82`.)

    ⇒ CLAUDE.md routes by what a run MUTATES, so this file is `:8000` work, full stop.
    It runs on the gate rig post-merge, which is where it was always going to run.

    ⚠️ AND NOT BY DISABLING WRITE-BACK. `writeback_enabled` would make the run
    `:7999`-legal and worthless: it would exercise a configuration production does not
    run, which is a different system from the one the gate is meant to clear.
    (Cheech's ruling, 2026-08-21.)

WHEN IT MEANS ANYTHING — read this before running it.
    ⚠️ Neither server serves the integration branch by default: `:7999` mounts the MAIN
    CHECKOUT, and so does `:8000` (`./src` in `docker-compose.yml`). Running this against
    either as they stand tests the OLD code and proves nothing about this work. Run it
    on the GATE RIG — `:8000` recreated against a worktree checked out at the gate sha —
    or after the final merge to the working branch AND a bounce. A saved file is not a
    served file; auto-reload is off.

USAGE — on `:8000`, once the gate rig is up
    python src/tests/smoke/test_v2_ask_voice_path_live.py                # read-shaped todo
    python src/tests/smoke/test_v2_ask_voice_path_live.py --insert-todo  # writing todo
    python src/tests/smoke/test_v2_ask_voice_path_live.py -q 1           # math only

    The flag changes the SHAPE of the todo question, not the venue — both write snapshot
    rows, and both are `:8000`.

Requires:
    - a server carrying the code under test (see WHEN IT MEANS ANYTHING above)
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD in the environment

No curl anywhere: submission and polling go through requests via LivePipelineTestBase,
per CLAUDE.md's testing anti-patterns.

Created: 2026-08-21 (maya 🌻, tester, brain-integration build)
"""

import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase


# ═══════════════════════════════════════════════════════════════════════════════
# The three questions the plan names, one per agent family
# ═══════════════════════════════════════════════════════════════════════════════

READ_SHAPED_TODO = {
    "id"                : "TODO_CRUD",
    "query"             : "what is on my todo list",
    "expected_agent"    : "CRUD",          # substring — the CRUD family, not one class name
    "expected_keywords" : [],              # an empty list is checked below, never skipped
}

WRITING_TODO = {
    "id"                : "TODO_CRUD_WRITE",
    "query"             : "add buy milk to my todo list",
    "expected_agent"    : "CRUD",
    "expected_keywords" : [],
}

VOICE_PATH_SCENARIOS = [
    READ_SHAPED_TODO,
    {
        "id"                : "MATH",
        "query"             : "what is seventeen times twenty three",
        "expected_agent"    : "Math",
        "expected_keywords" : [ "391" ],
    },
    {
        "id"                : "WEATHER",
        "query"             : "what is the weather today",
        "expected_agent"    : "Weather",
        "expected_keywords" : [],
    },
]


class V2AskVoicePathLiveTest( LivePipelineTestBase ):
    """
    Three questions through /api/v2/ask on a running server, checked by AGENT and ANSWER.

    Requires:
        - a :8000 server carrying the code under test (gate rig, or post-merge + bounce)
        - test credentials in the environment

    Ensures:
        - each question returns a terminal job with a non-empty answer
        - the todo question was handled by a CRUD agent, not the receptionist
        - a scenario with expected_keywords is checked against them
    """

    TEST_NAME       = "v2 /ask voice path — todo, math, weather"
    SCENARIOS       = VOICE_PATH_SCENARIOS
    DEFAULT_TIMEOUT = 180

    def build_argparser( self ):
        """Add the venue-relevant flags."""
        parser = super().build_argparser()
        parser.add_argument( "--queries", "-q", type=str, default=None,
                             help="Comma-separated scenario indices (e.g. '0,2'). Default: all." )
        parser.add_argument( "--insert-todo", action="store_true", default=False,
                             help="Use a WRITING todo instead of a reading one. Venue is :8000 either way — "
                                  "every ask writes a snapshot row (flow.py:291, registry.py:82)." )
        return parser

    def get_scenario_indices( self, args ):
        """Honour --queries, and swap in the writing todo when asked.

        Ensures:
            - returns valid indices into SCENARIOS
            - replaces scenario 0 with the writing variant under --insert-todo
        """
        if getattr( args, "insert_todo", False ):
            self.SCENARIOS = [ WRITING_TODO ] + VOICE_PATH_SCENARIOS[ 1: ]
        if getattr( args, "queries", None ):
            return [ int( x.strip() ) for x in args.queries.split( "," )
                     if int( x.strip() ) < len( self.SCENARIOS ) ]
        return list( range( len( self.SCENARIOS ) ) )

    def get_mode_for_scenario( self, scenario ):
        """No mode is ever set.

        ⚠️ THIS IS THE POINT OF THE FILE. Forcing a mode would bypass the router and
        prove only that a named agent runs when told to. The check is that a BARE
        SPOKEN QUESTION reaches the right agent on its own.
        """
        return None

    def validate_result( self, scenario, job_data ):
        """Check the agent that ran FIRST, then the answer.

        Ensures:
            - fails when the receptionist answered (routing did not happen)
            - fails when the agent family is not the expected one
            - fails on an empty answer even when no keywords are expected
        """
        # ⚠️ ONE answer string, resolved ONCE, used for BOTH the emptiness check and the
        # keyword check. The base class reads `response_text`; a v2 job may carry the
        # text under `answer_conversational` or `answer` instead. Delegating the keyword
        # half to the base while checking emptiness here would compare two DIFFERENT
        # fields — a routed job with a correct answer would pass the first check and
        # fail the second, reporting "no keyword match" for a field that was never
        # populated. Caught on 2026-08-21 by probing the validator with a job dict that
        # carried `answer` and no `response_text`.
        agent_type = job_data.get( "agent_type", "" ) or ""
        answer     = ( job_data.get( "response_text" )
                       or job_data.get( "answer_conversational" )
                       or job_data.get( "answer" ) or "" )

        if scenario[ "expected_agent" ] not in agent_type:
            return {
                "status"         : "fail",
                "answer_preview" : answer[ :80 ],
                "details"        : ( f"{scenario[ 'id' ]} was handled by {agent_type!r}, expected an agent "
                                     f"whose name contains {scenario[ 'expected_agent' ]!r}. A receptionist "
                                     f"answer here means the question never routed." ),
            }

        # An empty answer is a failure even with no keywords to match — otherwise a
        # scenario with an empty keyword list passes on silence.
        if not answer.strip():
            return {
                "status"         : "fail",
                "answer_preview" : "",
                "details"        : f"{scenario[ 'id' ]} routed to {agent_type} but returned an EMPTY answer",
            }

        if not scenario[ "expected_keywords" ]:
            return {
                "status"         : "pass",
                "answer_preview" : answer[ :80 ],
                "details"        : f"routed to {agent_type}, non-empty answer",
            }

        matched, keyword = self._check_answer( answer, scenario[ "expected_keywords" ] )
        if matched:
            return {
                "status"         : "pass",
                "answer_preview" : answer[ :80 ],
                "details"        : f"matched '{keyword}' (agent: {agent_type})",
            }
        return {
            "status"         : "fail",
            "answer_preview" : answer[ :80 ],
            "details"        : ( f"{scenario[ 'id' ]} routed to {agent_type} and answered, but none of "
                                 f"{scenario[ 'expected_keywords' ]} appears in the answer" ),
        }


if __name__ == "__main__":  # pragma: no cover - live smoke entry point
    sys.exit( V2AskVoicePathLiveTest().run() )
