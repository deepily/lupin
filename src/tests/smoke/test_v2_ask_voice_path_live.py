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

WHEN IT MEANS ANYTHING — read this before running it.
    ⚠️ `:7999` serves the MAIN CHECKOUT, not the integration branch (Cheech,
    2026-08-21). Running this before the build merges to the working branch and the
    server is bounced tests the OLD code and proves nothing about this work. Run it
    AFTER the final merge AND after `src/scripts/bounce-dev-server.sh` — a saved file
    is not a served file, and auto-reload is off.

VENUE, AND THE ONE JUDGEMENT CALL IN THIS FILE.
    CLAUDE.md routes by what a run MUTATES. Two of the three questions are read-only,
    but a todo that INSERTS leaves a row behind, which by the rubric forces `:8000`.
    The plan puts this check on `:7999` after the bounce.

    ⇒ The todo scenario is READ-SHAPED by default ("what is on my todo list"), which
    still proves the CRUD agent handled it — the assertion is on WHICH AGENT RAN, not
    on a row appearing. `--insert-todo` switches to a writing todo for anyone who wants
    the stronger check, and that variant belongs on `:8000` because it mutates.
    Named here rather than decided silently.

USAGE
    python src/tests/smoke/test_v2_ask_voice_path_live.py                # read-shaped todo, :7999
    python src/tests/smoke/test_v2_ask_voice_path_live.py --insert-todo  # writes a row -> :8000
    python src/tests/smoke/test_v2_ask_voice_path_live.py -q 1           # math only

Requires:
    - a server on :7999 carrying the merged code (see WHEN IT MEANS ANYTHING above)
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
        - a bounced server carrying the merged build
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
                             help="Use a WRITING todo instead of a reading one. Mutates state -> run on :8000." )
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
