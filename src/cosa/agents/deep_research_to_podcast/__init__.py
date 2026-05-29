#!/usr/bin/env python3
"""
COSA Deep Research to Podcast Agent Package.

A wrapper agent that orchestrates a chained workflow:
Deep Research → Podcast Generation.

This agent:
1. Runs Deep Research on a given query
2. Extracts the report_path from DR output
3. Passes report_path to Podcast Generator
4. Returns combined result with both artifacts

Usage:
    # CLI
    python -m cosa.agents.deep_research_to_podcast \\
        --query "State of quantum computing in 2026" \\
        --user-email researcher@example.com \\
        --budget 3.00

    # Programmatic
    from cosa.agents.deep_research_to_podcast import DeepResearchToPodcastAgent

    agent = DeepResearchToPodcastAgent(
        query      = "State of quantum computing",
        user_email = "user@example.com",
        budget     = 3.00,
        cli_mode   = False,  # Voice-driven (default)
    )
    result = await agent.run_async()
    print( f"Research: {result.research_path}" )
    print( f"Audio: {result.audio_path}" )
"""

from .agent import DeepResearchToPodcastAgent
from .state import ChainedResult, PipelineState

__all__ = [
    "DeepResearchToPodcastAgent",
    "ChainedResult",
    "PipelineState",
]

__version__ = "0.1.0"
