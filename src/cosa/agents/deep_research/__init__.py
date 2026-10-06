"""
COSA Deep Research Agent Package.

A voice-driven deep research agent integrating COSA voice I/O,
async orchestration, and Claude for multi-agent research.

Research calls run through the in-process Claude Agent SDK (`claude_agent_sdk.query`),
not the direct firewalled Anthropic SDK, matching the BFE, TFE, Podcast and Presentation pattern.
They use the Max-subscription OAuth path. This shifts cost rather than removing it:
SDK `total_cost_usd` telemetry is still reported but is covered by the fixed Max plan.
Web search uses Claude Code WebSearch and WebFetch (lead agent `tools=[]`, research
subagents `tools=[WebSearch, WebFetch]`). Parsing is strict: unrecoverable JSON fails loudly,
never silently defaulting. See `src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md`.

Modules:
- config.py, state.py: `ResearchConfig` dataclass; Pydantic state schemas and enums
- orchestrator.py: `ResearchOrchestratorAgent` skeleton (async `do_all_async`)
- cosa_interface.py: Async wrappers for cosa.cli notification functions
- api_client.py: Bounded-CC `sdk_query` client; cost_tracker.py: cost tracking and budgets
- prompts/: Clarification, planning, subagent, synthesis prompts
- cli.py: Command-line interface for testing; nodes/: LangGraph node implementations

The client reads no API key: `ENV_VAR_NAME` and `KEY_FILE_NAME` remain only for export
compatibility. Never use `ANTHROPIC_API_KEY`, which is reserved for the Claude Code CLI's OAuth.

Usage:
    # CLI Usage (bounded-CC — OAuth via the Claude Code session, no API key)
    python -m cosa.agents.deep_research.cli --query "Your research question"

    # Programmatic Usage
    from cosa.agents.deep_research import (
        ResearchOrchestratorAgent,
        ResearchConfig,
        ResearchAPIClient,
        CostTracker,
    )

    config = ResearchConfig( max_subagents_complex=5 )
    cost_tracker = CostTracker( session_id="my-session" )
    api_client = ResearchAPIClient( config=config, cost_tracker=cost_tracker )
    # Then use api_client.call_lead_agent(), call_subagent(), etc.
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

__version__ = "0.3.0"  # Phase 3 bounded-CC migration (AsyncAnthropic → in-process sdk_query)
