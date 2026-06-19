"""
COSA Bug Fix Expediter Agent Package.

An agentic job that takes a dead (failed/interrupted) job's context,
runs a three-phase forensic pipeline (diagnose -> propose -> fix),
and optionally retries the original job.
"""

from .config import BugFixExpediterConfig

from .state import (
    BFEPhase,
    DeadJobContext,
    DiagnosisResult,
    ProposedFix,
    FixResult,
    BFEState,
    create_initial_state
)

from .cosa_interface import (
    notify_progress,
    ask_confirmation,
    get_feedback,
    present_choices,
)

from .voice_io import (
    set_cli_mode,
    reset_voice_check,
    is_voice_available,
    get_mode_description,
    notify as voice_notify,
    ask_yes_no as voice_ask_yes_no,
    get_input as voice_get_input,
    choose as voice_choose,
)

from .dead_job_packager import package_dead_job
from .orchestrator import BFEOrchestrator
from .plan_writer import PlanWriter

__all__ = [
    "BugFixExpediterConfig",
    "BFEPhase", "DeadJobContext", "DiagnosisResult", "ProposedFix",
    "FixResult", "BFEState", "create_initial_state",
    "notify_progress", "ask_confirmation", "get_feedback", "present_choices",
    "set_cli_mode", "reset_voice_check", "is_voice_available", "get_mode_description",
    "voice_notify", "voice_ask_yes_no", "voice_get_input", "voice_choose",
    "package_dead_job",
    "BFEOrchestrator",
    "PlanWriter",
]

__version__ = "0.1.0"
