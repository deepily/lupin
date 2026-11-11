#!/usr/bin/env python3
"""
Records the prompts the podcast orchestrator sends at its four call sites.

The sites are analysis, script, revision and translation. Inputs are fixed and
the client is a recorder, so nothing is spent and nothing is written. The golden
file under the unit fixtures came from main, captured with this module before
any script-type code existed. A test replays the module against the current code.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from cosa.agents.podcast_generator.config import PodcastConfig
from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
from cosa.agents.podcast_generator.state import PodcastScript, ScriptSegment

SOURCE_TEXT = (
    "# Fixed Source\n\nThe cache layer was rewritten and now serves reads in 3 ms.\n"
    "Two items remain: the migration script and the rollback test.\n"
)

CALL_SITES = ( "analysis", "script", "revision", "translation" )


class _Response:
    """Stand-in for APIResponse; content is never parsed by the capture run."""
    def __init__( self, content ):
        self.content       = content
        self.model         = "recorder"
        self.input_tokens  = 0
        self.output_tokens = 0
        self.stop_reason   = "end_turn"
        self.sdk_cost_usd  = 0.0


class RecordingClient:
    """
    Records every call_for_* as ( system_prompt, user_message ) under its site.

    Requires:
        - replies maps a site name to the text the call should return
    Ensures:
        - self.calls[ site ] holds the last system and user strings sent
    """

    def __init__( self, replies ):
        self.replies = replies
        self.calls   = {}

    async def _record( self, site, system_prompt, user_message ):
        self.calls[ site ] = { "system": system_prompt, "user": user_message }
        return _Response( self.replies[ site ] )

    async def call_for_analysis( self, system_prompt, user_message, **kw ):
        return await self._record( "analysis", system_prompt, user_message )

    async def call_for_script( self, system_prompt, user_message, **kw ):
        # the script site and the translation site both use call_for_script
        site = "translation" if user_message.startswith( "Generate a " ) else "script"
        return await self._record( site, system_prompt, user_message )

    async def call_for_revision( self, system_prompt, user_message, **kw ):
        return await self._record( "revision", system_prompt, user_message )


def _fixed_script():
    return PodcastScript(
        title                      = "Fixed Title",
        generated_at               = "2026-01-01T00:00:00",
        research_source            = "/io/fixed/report.md",
        host_a_name                = "Maria",
        host_b_name                = "Mr. Radio",
        segments                   = [
            ScriptSegment( speaker="Maria", role="curious", text="Where are we today?", prosody=[] ),
            ScriptSegment( speaker="Mr. Radio", role="expert", text="The cache is done.", prosody=[] ),
        ],
        estimated_duration_minutes = 5.0,
        key_topics                 = [ "cache" ],
    )


def _replies():
    analysis = json.dumps( { "main_topic": "Cache", "key_subtopics": [ "reads" ] } )
    script   = json.dumps( { "title": "T", "segments": [
        { "speaker": "Maria", "role": "curious", "text": "Hi", "prosody": [] } ],
        "key_topics": [], "estimated_duration_minutes": 1.0 } )
    return { "analysis": analysis, "script": script, "revision": script, "translation": script }


def capture_prompts( config=None, **agent_kw ):
    """
    Drive the four real call sites and return { site: { system, user } }.

    Requires:
        - config is a PodcastConfig or None (None means PodcastConfig())
    Ensures:
        - returns a dict keyed by every name in CALL_SITES
    """
    agent               = PodcastOrchestratorAgent(
        research_doc_path = "/io/fixed/report.md",
        user_id           = "fixed@test.com",
        config            = config or PodcastConfig(),
        target_languages  = [ "en" ],
        **agent_kw,
    )
    client              = RecordingClient( _replies() )
    agent._api_client   = client
    agent._podcast_state[ "revision_count" ] = 1

    async def _run():
        analysis = await agent._analyze_content_async( SOURCE_TEXT )
        await agent._generate_script_async( SOURCE_TEXT, analysis )
        await agent._revise_script_async( _fixed_script(), "Shorten the intro." )
        await agent._generate_translated_script_async( _fixed_script(), "es-MX" )

    with patch( "cosa.agents.podcast_generator.orchestrator.voice_io.notify", new=AsyncMock() ):
        asyncio.run( _run() )

    missing = [ s for s in CALL_SITES if s not in client.calls ]
    if missing: raise RuntimeError( f"call sites not reached: {missing}" )
    return client.calls


if __name__ == "__main__":
    import sys
    json.dump( capture_prompts(), sys.stdout, indent=2, sort_keys=True, ensure_ascii=False )
    sys.stdout.write( "\n" )
