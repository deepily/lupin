"""
COSA TestFixExpediter Agent Package.

An agentic job that takes a failed TestSuiteJob's remediation snapshot,
clusters the failures into K root causes, runs a four-phase forensic
pipeline (diagnose → propose → fix → validate), and commits fixes via
the shared GitStrategist.

Session 1cfcdf73 (2026-04-10): Phase 0 package scaffolding. Full pipeline
lands incrementally in steps 7-12 of the approved plan.

Canonical plan: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md
"""

from .config import TestFixExpediterConfig

from .state import (
    TFEPhase,
    TestRemediationContext,
    FailureCluster,
    TestDiagnosisResult,
    TFEProposedFix,
    TFEState,
    create_initial_state,
)

from .cosa_interface import (
    SENDER_ID,
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

from .snapshot_loader import (
    load_from_path,
    load_from_artifacts,
    SnapshotLoadError,
)

from .cluster import heuristic_seed, llm_refine
from .orchestrator import TFEOrchestrator
from .job import TestFixExpediterJob

__all__ = [
    "TestFixExpediterConfig",
    "TFEPhase", "TestRemediationContext", "FailureCluster",
    "TestDiagnosisResult", "TFEProposedFix", "TFEState", "create_initial_state",
    "SENDER_ID",
    "notify_progress", "ask_confirmation", "get_feedback", "present_choices",
    "set_cli_mode", "reset_voice_check", "is_voice_available", "get_mode_description",
    "voice_notify", "voice_ask_yes_no", "voice_get_input", "voice_choose",
    "load_from_path", "load_from_artifacts", "SnapshotLoadError",
    "heuristic_seed", "llm_refine",
    "TFEOrchestrator",
    "TestFixExpediterJob",
]

__version__ = "0.1.0"
