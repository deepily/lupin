#!/usr/bin/env python3
"""
COSA Podcast Generator Agent.

Transforms Deep Research documents into conversational "Dynamic Duo" podcasts
with two AI hosts discussing the content in an accessible format.

Key Features:
- Customizable host personalities (A/B comparison of same content)
- Minimalist markdown script format with prosody annotations; one MP3 output
- Voice I/O CLI interface (like Deep Research Agent)
- COSA Router integration for voice-spawned execution

Architecture:
- PodcastOrchestratorAgent: Async state machine managing the full workflow
- PodcastConfig: Configuration dataclass; state models: Pydantic script and metadata

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

Bounded-CC script generation
----------------------------
Script generation (`PodcastAPIClient`'s four LLM methods) runs on the in-process
Claude Agent SDK (`claude_agent_sdk.query`), matching the BFE/TFE bounded-CC
pattern. It is a cost-shift to the already-paid Max plan, not "free": the SDK
reports `total_cost_usd` telemetry, but the firewalled Anthropic balance does
not move. The audio (TTS / ElevenLabs) phase uses its own path.
Cost model: src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md
"""

__version__ = "0.2.0"   # 0.2.0: bounded-CC script-phase migration (in-process sdk_query)

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
