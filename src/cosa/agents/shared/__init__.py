"""
COSA Shared Agent Primitives.

Reusable modules extracted from agent-specific packages, so BugFixExpediter, TestFixExpediter and future repair agents
can share fix-application, git-strategy and plan-writing machinery. Their agent-specific code paths stay separate.

This package sits beside the agent packages. It does not import from any specific agent (for example, no `cosa.agents.bug_fix_expediter.*` imports).
Agent packages import from here, not the other way around.

Modules:
    `plan_writer`: structured markdown plan document writer (agent-agnostic).
    `git_strategist`: trust-level to git action mapping (the git phase of BFE/TFE).
    `fix_executor`: coder+tester loop with polymorphic prompt registry (the fix phase of BFE/TFE).

Future modules (pending extraction):
    meta_repair_guard - Shared recursion-guard helpers for meta-repair agents
"""

from .plan_writer import PlanWriter
from .git_strategist import GitStrategist
from .fix_executor import FixExecutor, FIX_PROMPT_BUILDERS, register_fix_prompts

__all__ = [
    "PlanWriter",
    "GitStrategist",
    "FixExecutor",
    "FIX_PROMPT_BUILDERS",
    "register_fix_prompts",
]

__version__ = "0.1.0"
