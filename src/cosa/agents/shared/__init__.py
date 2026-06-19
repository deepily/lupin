"""
COSA Shared Agent Primitives.

Reusable modules extracted from agent-specific packages so multiple agent
implementations (BugFixExpediter, TestFixExpediter, and future repair agents)
can share the same fix-application, git-strategy, and plan-writing machinery
without contaminating each other's agent-specific code paths.

This package is a PEER of the agent packages — it does not import from any
specific agent (e.g., no `cosa.agents.bug_fix_expediter.*` imports). Agent
packages import from here, not the other way around.

Modules:
    plan_writer      — Structured markdown plan document writer (agent-agnostic)
    git_strategist   — Trust-level → git action mapping (Phase 5 of BFE/TFE)
    fix_executor     — Coder+tester loop with polymorphic prompt registry (Phase 3)

Future modules (pending extraction):
    meta_repair_guard — Shared recursion-guard helpers for meta-repair agents
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
