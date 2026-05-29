"""
COSA Deep Research Agent Package.

A voice-driven deep research agent integrating COSA voice I/O,
async orchestration, and Claude API for multi-agent research.

Phase 1 (Complete): Foundation
- config.py: ResearchConfig dataclass
- state.py: Pydantic state schemas, OrchestratorState/JobSubState enums
- orchestrator.py: ResearchOrchestratorAgent skeleton (async do_all_async)
- cosa_interface.py: Async wrappers for cosa.cli notification functions

Phase 2 (Complete): API Client and Prompts
- api_client.py: Direct Anthropic API wrapper with web search
- cost_tracker.py: Per-request cost tracking and budget limits
- prompts/: Clarification, planning, subagent, synthesis prompts
- cli.py: Command-line interface for testing

Phase 3 (Future): LangGraph Integration
- graph.py: Optional StateGraph orchestration
- nodes/: LangGraph node implementations

Phase 4 (Future): Queue Integration
- Async queue consumer evolution for non-blocking job execution

API Key Configuration (Firewalled Pattern):
    IMPORTANT: NEVER use ANTHROPIC_API_KEY - that is reserved for Claude Code CLI.

    For development (local key file):
        # Create/use: src/conf/keys/anthropic-api-key-firewalled
        # The API client will automatically find and use this file

    For testing/production (environment variable):
        export ANTHROPIC_API_KEY_FIREWALLED=your-api-key
        python -m cosa.agents.deep_research.cli --query "..."

Usage:
    # CLI Usage (development - uses local key file)
    python -m cosa.agents.deep_research.cli --query "Your research question"

    # CLI Usage (testing/production - uses env var)
    export ANTHROPIC_API_KEY_FIREWALLED=your-key
    python -m cosa.agents.deep_research.cli --query "Your research question"

    # Programmatic Usage
    from cosa.agents.deep_research import (
        ResearchOrchestratorAgent,
        ResearchConfig,
        ResearchAPIClient,
        CostTracker,
        ENV_VAR_NAME,      # "ANTHROPIC_API_KEY_FIREWALLED"
        KEY_FILE_NAME,     # "anthropic-api-key-firewalled"
    )

    config = ResearchConfig( max_subagents_complex=5 )
    cost_tracker = CostTracker( session_id="my-session" )
    api_client = ResearchAPIClient( config=config, cost_tracker=cost_tracker )

    # Use api_client.call_lead_agent(), call_subagent(), etc.
"""

from .config import ResearchConfig

from .state import (
    OrchestratorState,
    JobSubState,
    ResearchState,
    SubQuery,
    ResearchPlan,
    SourceReference,
    SubagentFinding,
    ClarificationDecision,
    Citation,
    create_initial_state
)

from .orchestrator import ResearchOrchestratorAgent

from .cosa_interface import (
    notify_progress,
    ask_confirmation,
    get_feedback,
    present_choices,
    is_approval,
    is_rejection,
    extract_feedback_intent
)

# Phase 2 additions
from .cost_tracker import (
    CostTracker,
    UsageRecord,
    SessionSummary,
    BudgetExceededError,
    ModelTier,
    MODEL_PRICING,
)

from .api_client import (
    ResearchAPIClient,
    APIResponse,
    ANTHROPIC_AVAILABLE,
    ENV_VAR_NAME,
    KEY_FILE_NAME,
)

# Phase 2: Voice-First I/O Layer
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

# Phase 2: Progressive Narrowing Test Harness
from .narrowing_harness import (
    NarrowingHarness,
    NarrowingResult,
)

from .narrowing_mocks import (
    MockResearchAPIClient,
    get_mock_theme_response,
    get_mock_subqueries,
    MOCK_THEMES_3,
    MOCK_THEMES_4,
    SAMPLE_SUBQUERIES_5,
    SAMPLE_SUBQUERIES_8,
)

__all__ = [
    # Config
    "ResearchConfig",

    # State Enums
    "OrchestratorState",
    "JobSubState",

    # State TypedDict
    "ResearchState",

    # Pydantic Models
    "SubQuery",
    "ResearchPlan",
    "SourceReference",
    "SubagentFinding",
    "ClarificationDecision",
    "Citation",

    # State Factory
    "create_initial_state",

    # Orchestrator
    "ResearchOrchestratorAgent",

    # COSA Interface Functions
    "notify_progress",
    "ask_confirmation",
    "get_feedback",
    "present_choices",

    # Feedback Analysis Utilities
    "is_approval",
    "is_rejection",
    "extract_feedback_intent",

    # Phase 2: Cost Tracking
    "CostTracker",
    "UsageRecord",
    "SessionSummary",
    "BudgetExceededError",
    "ModelTier",
    "MODEL_PRICING",

    # Phase 2: API Client
    "ResearchAPIClient",
    "APIResponse",
    "ANTHROPIC_AVAILABLE",

    # Phase 2: API Key Configuration (Firewalled Pattern)
    "ENV_VAR_NAME",      # "ANTHROPIC_API_KEY_FIREWALLED"
    "KEY_FILE_NAME",     # "anthropic-api-key-firewalled"

    # Phase 2: Voice-First I/O Layer
    "set_cli_mode",
    "reset_voice_check",
    "is_voice_available",
    "get_mode_description",
    "voice_notify",
    "voice_ask_yes_no",
    "voice_get_input",
    "voice_choose",

    # Phase 2: Progressive Narrowing Test Harness
    "NarrowingHarness",
    "NarrowingResult",
    "MockResearchAPIClient",
    "get_mock_theme_response",
    "get_mock_subqueries",
    "MOCK_THEMES_3",
    "MOCK_THEMES_4",
    "SAMPLE_SUBQUERIES_5",
    "SAMPLE_SUBQUERIES_8",
]

__version__ = "0.2.2"  # Updated for Progressive Narrowing Harness
