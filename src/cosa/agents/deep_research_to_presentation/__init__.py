#!/usr/bin/env python3
"""
COSA Deep Research to Presentation Agent Package.

A wrapper agent that orchestrates a chained workflow:
Deep Research → Presentation Generation.

This agent:
1. Runs Deep Research on a given query
2. Extracts the report_path from DR output
3. Passes report_path to Presentation Generator as source_path
4. Returns combined result with both artifacts

Usage:
    # CLI
    python -m cosa.agents.deep_research_to_presentation \\
        --query "State of quantum computing in 2026" \\
        --user-email researcher@example.com \\
        --budget 3.00

    # Programmatic
    from cosa.agents.deep_research_to_presentation import DeepResearchToPresentationAgent

    agent = DeepResearchToPresentationAgent(
        query      = "State of quantum computing",
        user_email = "user@example.com",
        budget     = 3.00,
        cli_mode   = False,  # Voice-driven (default)
    )
    result = await agent.run_async()
    print( f"Research: {result.research_path}" )
    print( f"Presentation: {result.marp_path}" )
"""

from .agent import DeepResearchToPresentationAgent
from .state import ChainedResult, PipelineState

__all__ = [
    "DeepResearchToPresentationAgent",
    "ChainedResult",
    "PipelineState",
]

__version__ = "0.1.0"
