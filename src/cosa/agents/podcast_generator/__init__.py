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

Bounded-CC migration (Phase 1 — 2026-06-18, D9 banner)
------------------------------------------------------
The script-generation phase (`PodcastAPIClient`'s four LLM methods) was
migrated from the direct firewalled Anthropic SDK
(`AsyncAnthropic.messages.create`) to the in-process Claude Agent SDK
(`claude_agent_sdk.query`), matching the shipped BFE/TFE bounded-CC pattern
(ratified D-DR1 Option X). This is a COST-SHIFT to the already-paid Max plan,
NOT "free": the SDK reports `total_cost_usd` telemetry, but the firewalled
Anthropic console balance does not move. The firewalled-key prose elsewhere in
this package is HISTORICAL for the script phase. The audio (TTS / ElevenLabs)
phase is unchanged.
  - Scope:        src/rnd/v0.1.8/2026.06.18-podcast-phase1-bounded-cc-scope.md
  - Ratification: src/rnd/v0.1.8/2026.06.18-bounded-cc-d1d9-ratification-package.md
  - Cost model:   src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md
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
