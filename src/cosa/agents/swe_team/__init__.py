"""
COSA SWE Team Agent Package.

A multi-agent engineering team powered by Claude Agent SDK,
integrated with Lupin's notification system and CJ Flow queue.

Phase 1: Foundation
- config.py: SweTeamConfig dataclass
- state.py: Pydantic state schemas, OrchestratorState/JobSubState enums
- safety_limits.py: SAFETY_LIMITS dict, SafetyGuard, DANGEROUS_COMMANDS
- agent_definitions.py: 6 role definitions (lead + coder active)
- orchestrator.py: SweTeamOrchestrator (dry-run + live delegation)
- cosa_interface.py: Role-aware async notification wrappers
- voice_io.py: Voice-first I/O layer (thin wrapper)
- mock_clients.py: MockAgentSDKSession for dry-run mode
- __main__.py: CLI entry point

Phase 2: Lead + Coder delegation loop
- hooks.py: SDK hook functions (notification, pre-tool, post-tool)
- state_files.py: FeatureList + ProgressLog for cross-session persistence

Phase 3 (Current): Tester verification loop
- test_runner.py: Orchestrator-level pytest validation helper
- VerificationResult model in state.py
- Coder-tester retry cycle in orchestrator.py

Phase 4 (Planned): Trust-aware decision proxy
Phase 5 (Planned): Full team + CJ Flow integration

Usage:
    # CLI (dry-run)
    python -m cosa.agents.swe_team "Implement health check endpoint" --dry-run

    # CLI (live - Phase 3 delegation + verification)
    python -m cosa.agents.swe_team "Add JWT auth"

    # Programmatic
    from cosa.agents.swe_team import (
        SweTeamOrchestrator,
        SweTeamConfig,
        OrchestratorState,
    )

    config = SweTeamConfig( dry_run=True )
    orch = SweTeamOrchestrator( "Implement feature X", config=config )
    result = asyncio.run( orch.run() )
"""

from .config import SweTeamConfig

from .state import (
    OrchestratorState,
    JobSubState,
    SweTeamState,
    TaskSpec,
    DelegationResult,
    ReviewFinding,
    VerificationResult,
    create_initial_state,
)

from .safety_limits import (
    SAFETY_LIMITS,
    DANGEROUS_COMMANDS,
    SafetyGuard,
    SafetyLimitError,
    is_dangerous_command,
)

from .agent_definitions import (
    AgentRole,
    get_agent_roles,
    get_active_roles,
    get_model_for_role,
    get_sender_id,
    SWE_TEAM_SENDERS,
)

from .orchestrator import SweTeamOrchestrator

from .cosa_interface import (
    notify_progress,
    ask_confirmation,
    request_decision,
    get_feedback,
    is_approval,
    is_rejection,
)

from .mock_clients import (
    MockAgentSDKSession,
    MockAgentMessage,
)

# Phase 3: Test Runner
from .test_runner import (
    TestRunResult,
    run_pytest,
)

# Phase 2: SDK Hooks and State Persistence
from .hooks import (
    notification_hook,
    pre_tool_hook,
    post_tool_hook,
    build_can_use_tool,
    wrap_prompt_for_streaming,
)

from .state_files import (
    FeatureList,
    ProgressLog,
)

# Phase 1: Voice-First I/O Layer
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

__all__ = [
    # Config
    "SweTeamConfig",

    # State Enums
    "OrchestratorState",
    "JobSubState",

    # State TypedDict
    "SweTeamState",

    # Pydantic Models
    "TaskSpec",
    "DelegationResult",
    "ReviewFinding",
    "VerificationResult",

    # State Factory
    "create_initial_state",

    # Safety
    "SAFETY_LIMITS",
    "DANGEROUS_COMMANDS",
    "SafetyGuard",
    "SafetyLimitError",
    "is_dangerous_command",

    # Agent Definitions
    "AgentRole",
    "get_agent_roles",
    "get_active_roles",
    "get_model_for_role",
    "get_sender_id",
    "SWE_TEAM_SENDERS",

    # Orchestrator
    "SweTeamOrchestrator",

    # COSA Interface Functions
    "notify_progress",
    "ask_confirmation",
    "request_decision",
    "get_feedback",

    # Feedback Analysis
    "is_approval",
    "is_rejection",

    # Mock Clients
    "MockAgentSDKSession",
    "MockAgentMessage",

    # SDK Hooks (Phase 2)
    "notification_hook",
    "pre_tool_hook",
    "post_tool_hook",
    "build_can_use_tool",
    "wrap_prompt_for_streaming",

    # Test Runner (Phase 3)
    "TestRunResult",
    "run_pytest",

    # State Files (Phase 2)
    "FeatureList",
    "ProgressLog",

    # Voice-First I/O Layer
    "set_cli_mode",
    "reset_voice_check",
    "is_voice_available",
    "get_mode_description",
    "voice_notify",
    "voice_ask_yes_no",
    "voice_get_input",
    "voice_choose",
]

__version__ = "0.3.0"  # Phase 3: Tester Verification Loop
