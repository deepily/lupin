"""
Prompt templates for COSA Deep Research Agent.

This module provides system prompts and user message generators for:
- Query clarification analysis
- Research planning and decomposition
- Subagent research execution
- Report synthesis and revision

All prompts are designed to produce structured JSON output
for reliable parsing by the orchestrator.
"""

from .clarification import (
    CLARIFICATION_SYSTEM_PROMPT,
    get_clarification_prompt,
    parse_clarification_response,
)

from .planning import (
    PLANNING_SYSTEM_PROMPT,
    get_planning_prompt,
    parse_planning_response,
    THEME_CLUSTERING_PROMPT,
    get_theme_clustering_prompt,
)

from .subagent import (
    SUBAGENT_SYSTEM_PROMPT,
    get_subagent_prompt,
    get_system_prompt_with_params,
    parse_subagent_response,
)

from .synthesis import (
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_WITH_FEEDBACK_PROMPT,
    get_synthesis_prompt,
    get_revision_prompt,
    get_revision_system_prompt,
)

__all__ = [
    # Clarification
    "CLARIFICATION_SYSTEM_PROMPT",
    "get_clarification_prompt",
    "parse_clarification_response",

    # Planning
    "PLANNING_SYSTEM_PROMPT",
    "get_planning_prompt",
    "parse_planning_response",
    "THEME_CLUSTERING_PROMPT",
    "get_theme_clustering_prompt",

    # Subagent
    "SUBAGENT_SYSTEM_PROMPT",
    "get_subagent_prompt",
    "get_system_prompt_with_params",
    "parse_subagent_response",

    # Synthesis
    "SYNTHESIS_SYSTEM_PROMPT",
    "SYNTHESIS_WITH_FEEDBACK_PROMPT",
    "get_synthesis_prompt",
    "get_revision_prompt",
    "get_revision_system_prompt",
]
