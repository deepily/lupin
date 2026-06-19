#!/usr/bin/env python3
"""
Prompts module for COSA Podcast Generator Agent.

Contains system prompts and prompt templates for:
- Script generation (dialogue creation)
- Personality configuration (host customization)
- Prosody annotation (expressive speech markers)
"""

from .script_generation import (
    SCRIPT_GENERATION_SYSTEM_PROMPT,
    CONTENT_ANALYSIS_SYSTEM_PROMPT,
    get_script_generation_prompt,
    get_content_analysis_prompt,
    get_script_revision_prompt,
    parse_script_response,
    parse_analysis_response,
)

from .personality import (
    get_personality_prompt_section,
    get_dynamic_duo_description,
    CURIOUS_HOST_PROMPT_SECTION,
    EXPERT_HOST_PROMPT_SECTION,
)

__all__ = [
    # Script generation
    "SCRIPT_GENERATION_SYSTEM_PROMPT",
    "CONTENT_ANALYSIS_SYSTEM_PROMPT",
    "get_script_generation_prompt",
    "get_content_analysis_prompt",
    "get_script_revision_prompt",
    "parse_script_response",
    "parse_analysis_response",
    # Personality
    "get_personality_prompt_section",
    "get_dynamic_duo_description",
    "CURIOUS_HOST_PROMPT_SECTION",
    "EXPERT_HOST_PROMPT_SECTION",
]
