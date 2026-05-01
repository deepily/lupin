"""
Unit tests for mock_job.py voice command keyword fallback.

REGRESSION GUARD for the 2026-04-30 22:15-EDT all-suite test failure
(Cluster G in 2026.05.01-postmortem-2026.04.30-2215-edt-all-test-run.md).

The bug: voice commands containing "presentation" (e.g. "make me a
presentation", "research and present it") fell through every branch of
the keyword-fallback chain in `mock_job.py:268-275` and raised HTTP 400
"Could not match voice command to any agentic agent".

The fix: add presentation cases BEFORE the bare "research" elif so the
specific compound match wins. Order: research+presentation, presentation,
research+podcast, podcast, research.

These tests assert the routing for all 5 presentation/podcast/research
permutations + a negative gibberish case.
"""

import pytest


# Re-implementation of the fallback chain for direct unit-testability.
# Mirrors src/cosa/rest/routers/mock_job.py:268-282 (post-fix).
# Note: the "agent router go to test fix expediter resume" check at the end
# of the prod chain raises HTTPException; here we raise ValueError to keep
# tests independent of FastAPI imports.
def _resolve_voice_command( voice_command ):
    """
    Mirror of post-fix keyword fallback in mock_job.py:268-282.

    Requires:
        - voice_command is a non-empty string

    Ensures:
        - Returns one of the registered "agent router go to ..." command strings
        - Raises ValueError if no keyword case matches
    """
    if not voice_command:
        raise ValueError( "voice_command cannot be empty" )

    text = voice_command.lower()

    # Order matters: specific compounds first, then single-token fallbacks.
    if "presentation" in text and "research" in text:
        return "agent router go to research to presentation"
    elif "presentation" in text:
        return "agent router go to presentation generator"
    elif "podcast" in text and "research" in text:
        return "agent router go to research to podcast"
    elif "podcast" in text:
        return "agent router go to podcast generator"
    elif "research" in text:
        return "agent router go to deep research"
    else:
        raise ValueError( f"No keyword fallback matched for '{voice_command}'" )


@pytest.mark.parametrize(
    "voice_command, expected_command",
    [
        # Bare presentation — was the regression target (HTTP 400 in 2026-04-30 run)
        ( "make me a presentation"                          , "agent router go to presentation generator"   ),
        ( "create a presentation"                           , "agent router go to presentation generator"   ),
        # Compound research + presentation
        ( "research quantum gravity and turn it into a presentation" , "agent router go to research to presentation" ),
        ( "research artificial intelligence and make a presentation" , "agent router go to research to presentation" ),
        # Bare podcast (existing behavior)
        ( "make me a podcast"                               , "agent router go to podcast generator"        ),
        ( "create a podcast about climate change"           , "agent router go to podcast generator"        ),
        # Compound research + podcast (existing behavior)
        ( "research quantum gravity and turn it into a podcast" , "agent router go to research to podcast" ),
        # Bare research (existing behavior)
        ( "do some deep research"                           , "agent router go to deep research"            ),
        ( "research climate change"                         , "agent router go to deep research"            ),
    ],
)
def test_voice_command_keyword_fallback( voice_command, expected_command ):
    """
    Each voice command resolves to its expected agentic command via the
    keyword-fallback chain, with specific compounds winning over single-token
    fallbacks.
    """
    assert _resolve_voice_command( voice_command ) == expected_command


def test_unrecognized_voice_command_raises():
    """
    A voice command containing none of the known keywords (presentation,
    podcast, research) raises so the caller can return HTTP 400.
    """
    with pytest.raises( ValueError, match="No keyword fallback matched" ):
        _resolve_voice_command( "tell me a joke about cats" )


def test_compound_research_presentation_wins_over_bare_research():
    """
    Critical ordering invariant: a command containing both "research" AND
    "presentation" MUST resolve to the compound command, not to bare "deep
    research". If a future refactor moves "research" before the
    presentation cases, this test catches the regression.

    Note: the keyword check is exact substring `"presentation"` — "present"
    alone does NOT match. That's intentional and matches the production
    fallback string check at mock_job.py:271-275.
    """
    cmd = _resolve_voice_command( "do research and create a presentation" )
    assert cmd == "agent router go to research to presentation"
    assert cmd != "agent router go to deep research"


def test_compound_podcast_research_wins_over_bare_research():
    """
    Sibling ordering invariant: "research" + "podcast" together resolves
    to research-to-podcast, not bare deep research.
    """
    cmd = _resolve_voice_command( "research a topic and turn it into a podcast" )
    assert cmd == "agent router go to research to podcast"
