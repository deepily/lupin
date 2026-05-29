#!/usr/bin/env python3
"""
COSA Podcast Generator Agent.

Transforms Deep Research documents into conversational "Dynamic Duo" podcasts
with two AI hosts discussing the content in an engaging, accessible format.

Key Features:
- Customizable host personalities (for A/B comparison of same content)
- Minimalist markdown script format with prosody annotations
- Single consolidated MP3 audio output
- Voice I/O CLI interface (like Deep Research Agent)
- COSA Router integration for voice-spawned execution

Architecture:
- PodcastOrchestratorAgent: Async state machine managing the full workflow
- PodcastConfig: Configuration dataclass for all settings
- State models: Pydantic models for script segments and podcast metadata

Usage:
    from cosa.agents.podcast_generator import (
        PodcastOrchestratorAgent,
        PodcastConfig,
        OrchestratorState,
    )

    # Create agent
    agent = PodcastOrchestratorAgent(
        research_doc_path = "path/to/deep-research.md",
        user_id           = "user@example.com",
        config            = PodcastConfig(),
    )

    # Run async workflow
    script = await agent.do_all_async()
"""

__version__ = "0.1.0"

from .config import PodcastConfig, HostPersonality, VoiceProfile
from .state import (
    OrchestratorState,
    ScriptSegment,
    PodcastScript,
    PodcastMetadata,
    ProsodyAnnotation,
    create_initial_state,
)

from .orchestrator import PodcastOrchestratorAgent
from .api_client import PodcastAPIClient, APIResponse, CostEstimate
from . import cosa_interface

__all__ = [
    # Version
    "__version__",
    # Config
    "PodcastConfig",
    "HostPersonality",
    "VoiceProfile",
    # State
    "OrchestratorState",
    "ScriptSegment",
    "PodcastScript",
    "PodcastMetadata",
    "ProsodyAnnotation",
    "create_initial_state",
    # Orchestrator
    "PodcastOrchestratorAgent",
    # API Client
    "PodcastAPIClient",
    "APIResponse",
    "CostEstimate",
    # COSA Interface
    "cosa_interface",
]
