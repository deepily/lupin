# Agentic Voice Workflow: Complete Lifecycle Guide

**Version**: 2.1
**Created**: 2026-01-27
**Updated**: 2026-02-07
**Purpose**: Complete lifecycle guide — CONCEPT → BUILD → VALIDATE — for creating CJ Flow agentic background jobs with voice I/O and queue integration

**Pattern Source**: Derived from `deep_research`, `podcast_generator`, and `deep_research_to_podcast` agents.

---

## Table of Contents

- [Part I: CONCEPT](#part-i-concept)
  - [Why Agentic Jobs Exist](#why-agentic-jobs-exist)
  - [Architecture Overview](#architecture-overview)
  - [The Runtime Argument Expeditor](#the-runtime-argument-expeditor)
  - [Agentic Jobs vs Traditional Agents](#agentic-jobs-vs-traditional-agents)
  - [When to Use Agentic Jobs](#when-to-use-agentic-jobs)
  - [Decision Checklist](#decision-checklist)
- [Part II: BUILD](#part-ii-build)
  - [Phase 0: Interactive Discovery + Pre-Flight Checks](#phase-0-interactive-discovery--pre-flight-checks)
  - [Phase 1-2: Skeletal Agent Foundation + Mock Clients](#phase-1-2-skeletal-agent-foundation--mock-clients)
  - [Phase 3-4: Notification Integration](#phase-3-4-notification-integration)
  - [Phase 5: AgenticJob Queue Wrapper](#phase-5-agenticjob-queue-wrapper)
  - [Phase 5b: Dedicated FastAPI Router](#phase-5b-dedicated-fastapi-router)
  - [Phase 6: LLM Client Integration](#phase-6-llm-client-integration)
  - [Phase 7: Cost Tracking](#phase-7-cost-tracking)
  - [Phase 8: Rate Limiting](#phase-8-rate-limiting)
  - [Phase 9: External Service Integration](#phase-9-external-service-integration-patterns)
  - [Phase 10: Advanced Orchestration Patterns](#phase-10-advanced-orchestration-patterns)
- [Part III: VALIDATE — The Testing Ladder](#part-iii-validate--the-testing-ladder)
  - [Surface 1: Unit Tests + Inline Smoke Tests](#surface-1-unit-tests--inline-smoke-tests-free-1s)
  - [Surface 2: Mock Job Endpoint](#surface-2-mock-job-endpoint-free-1s-server-required)
  - [Surface 3: Notification UI Submission Cards](#surface-3-notification-ui-submission-cards-0001query-1-3s)
  - [Surface 4: PEFT Training + XML Data Generation](#surface-4-peft-training--xml-data-generation-5-50-gpu-hrs)
  - [Surface 5: Voice Routing — ASR → LORA → Queue](#surface-5-voice-routing--asr--lora--queue-001query-2-5s)
  - [Recommended Iteration Strategy](#recommended-iteration-strategy)
  - [Adding a New Agentic Agent — Complete Checklist](#adding-a-new-agentic-agent--complete-checklist)
- [Part IV: Reference Implementations](#part-iv-reference-implementations)
- [Version History](#version-history)

---

# Part I: CONCEPT

## Why Agentic Jobs Exist

Traditional request-response APIs work well for operations that complete in milliseconds — fetch a
record, validate a token, return a JSON payload. But many valuable tasks take **minutes or hours**:
generating a research report, producing a podcast episode, training a model. These long-running
tasks need a fundamentally different execution model.

**The Agentic Job pattern** solves this by combining three ideas:

1. **Queue-Based Execution**: Jobs are submitted to a FIFO queue and executed by a background
   runner thread. The HTTP request returns immediately with a job ID. The client polls for
   completion or receives WebSocket notifications.

2. **Voice-First Notifications**: Because these jobs run while the user is away from the terminal,
   progress updates are delivered as **audio notifications** via the `cosa-voice` MCP server.
   Critical decision points use blocking voice prompts that wait for the user's spoken response.

3. **Human-in-the-Loop Checkpoints**: Unlike fully autonomous pipelines, agentic jobs can **pause**
   at defined states to ask the user for approval, clarification, or selection between options.
   This keeps humans in control of expensive or irreversible operations.

## CJ Flow Architecture Overview

```
                          ┌─────────────────────────────────────────────────┐
                          │                  LUPIN Server                   │
                          │                                                 │
  ┌──────────┐   HTTP     │  ┌──────────┐   ┌───────────────┐              │
  │  Browser  │──────────►│  │  FastAPI  │──►│  Expeditor    │              │
  │  or CLI   │   POST    │  │  Router   │   │  (parse args) │              │
  └──────────┘            │  └──────────┘   └───────┬───────┘              │
       ▲                  │                         │                       │
       │ WebSocket        │                         ▼                       │
       │ Notifications    │  ┌───────────────────────────────────┐         │
       │                  │  │       AgenticJobFactory            │         │
       │                  │  │  command → Job class dispatch      │         │
       │                  │  └───────────────┬───────────────────┘         │
       │                  │                  │                              │
       │                  │                  ▼                              │
       │                  │  ┌───────────────────────────────────┐         │
       │                  │  │     RunningFifoQueue              │         │
       │                  │  │  ┌──────┐ ┌──────┐ ┌──────┐      │         │
       │                  │  │  │ todo │►│ run  │►│ done │      │         │
       │                  │  │  └──────┘ └──┬───┘ └──────┘      │         │
       │                  │  └──────────────┼───────────────────┘         │
       │                  │                 │                              │
       │                  │                 ▼                              │
       │                  │  ┌──────────────────────────────┐             │
       │                  │  │   AgenticJobBase.do_all()    │             │
       │                  │  │                              │             │
       │                  │  │  ┌────────────────────────┐  │  cosa-voice │
       │                  │  │  │  Orchestrator           │  │────────────►
       │                  │  │  │  • LLM calls            │  │  Audio TTS │
       │                  │  │  │  • Web search           │  │            │
       │                  │  │  │  • Cost tracking         │  │            │
       │                  │  │  │  • Rate limiting         │  │            │
       │                  │  │  │  • Human-in-the-loop    │  │            │
       │                  │  │  └────────────────────────┘  │             │
       │                  │  └──────────────────────────────┘             │
       │                  └─────────────────────────────────────────────────┘
       │                                    │
       └────────────────────────────────────┘
                    Poll /api/get-queue/done
```

**Key flow**: User submits via browser or CLI → FastAPI router receives request → Expeditor
parses arguments → Factory creates the right Job subclass → Queue manages lifecycle (todo → run →
done) → Job's `do_all()` runs the Orchestrator → Voice notifications keep user informed throughout.

## The Runtime Argument Expeditor

The **Runtime Argument Expeditor** bridges the gap between a natural-language voice command and the structured arguments an agentic job needs to start.

When a user says *"make me a podcast about quantum computing"*, the voice pipeline (ASR → LORA router) identifies the command (`agent router go to podcast generator`) and extracts raw arguments. But the job constructor may need additional parameters — research file path, target audience, languages. The Expeditor's role is to:

1. **Gap Analysis**: Compare extracted args against the agent's required + optional arg list (defined in `agent_registry.py`)
2. **Collection**: For each missing arg, prompt the user via voice — either one-by-one or as a batch form
3. **Confirmation**: Present the full arg set for user review, allowing tweaks or approval
4. **Injection**: Add system-provided args (user_email, session_id) that the user never sees

Without Expeditor registration, an agent **cannot be invoked via voice commands** — only via direct REST API calls. This makes it a mandatory integration step for any agent that participates in the voice-first UX.

**Key files**:
- `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` — Agent registry with arg specs
- `src/cosa/agents/runtime_argument_expeditor/expeditor.py` — Gap analysis + collection logic
- `src/cosa/rest/agentic_job_factory.py` — `args_dict` → Job constructor mapping

See [Expeditor Registration](#expeditor-registration-agent_registrypy) in Part II for the how-to.

## Agentic Jobs vs Traditional Agents

| Dimension | Traditional Agent | Agentic Job |
|-----------|------------------|-------------|
| **Execution** | Synchronous, inline | Async, background queue |
| **Lifetime** | Seconds | Minutes to hours |
| **User feedback** | Terminal stdout | Voice notifications + WebSocket |
| **Human-in-the-loop** | Not supported | Built-in checkpoint states |
| **Cost tracking** | None | Per-call with budget limits |
| **Rate limiting** | None | Sliding window with proactive delays |
| **Artifacts** | Return value | Files on disk + queue metadata |
| **Error handling** | Exception propagation | Graceful failure with notification |
| **Testability** | Unit tests only | 5-surface validation ladder |
| **Voice routing** | N/A | LORA classifier → queue dispatch |
| **Examples** | Math agent, calendar | Deep Research, Podcast Generator |

## When to Use Agentic Jobs

**Good fit** — use an agentic job when:
- Task takes more than 30 seconds to complete
- Task makes multiple LLM API calls (cost tracking needed)
- Task produces file artifacts (reports, audio, images)
- User needs progress updates while task runs
- Human approval is needed at intermediate steps
- Task can benefit from voice-driven submission ("research quantum computing")

**Bad fit** — use a traditional agent or direct API call when:
- Task completes in under 5 seconds
- Task is purely deterministic (no LLM calls)
- No user interaction needed during execution
- Output is a simple JSON response, not a file artifact
- Task is called programmatically without a user session

## Decision Checklist

Before starting, confirm your agent needs the agentic job pattern:

```
Pre-Build Decision Checklist:

[ ] Task takes >30 seconds (otherwise use traditional agent)
[ ] Task requires LLM API calls (otherwise use utility function)
[ ] Task produces user-visible artifacts (reports, audio, etc.)
[ ] You have a clear state machine (≥3 states)
[ ] You know the primary input type (text, file, URL, etc.)
[ ] You know the primary output type (markdown, audio, JSON, etc.)
[ ] You have identified external dependencies (APIs, DBs, etc.)
[ ] You have identified human-in-the-loop checkpoints (if any)

If fewer than 4 boxes are checked, consider a simpler pattern.
```

---

# Part II: BUILD

## Phase 0: Interactive Discovery + Pre-Flight Checks

Before creating any files, answer these questions to establish the agent's characteristics:

### Required Information

```
1. Agent Name (snake_case): ____________________
   Example: notification_agent, pdf_summarizer, code_reviewer

2. Job Prefix (2-3 letters): ____
   Example: na, ps, cr
   Used in job IDs: {prefix}-a1b2c3d4

3. Primary Input Type:
   [ ] User query (text string)
   [ ] File path (document, image, etc.)
   [ ] URL (web resource)
   [ ] Structured data (JSON, API response)
   [ ] Other: ____________________

4. Primary Output Type:
   [ ] Text report (markdown)
   [ ] Audio file (mp3, wav)
   [ ] Structured data (JSON)
   [ ] Multiple artifacts
   [ ] Other: ____________________

5. External Dependencies:
   [ ] Web search API
   [ ] LLM API (Claude, OpenAI)
   [ ] TTS API (ElevenLabs, etc.)
   [ ] Database access
   [ ] File system operations
   [ ] None
   [ ] Other: ____________________

6. Human-in-the-Loop Checkpoints:
   [ ] None (fully autonomous)
   [ ] Input clarification
   [ ] Plan approval
   [ ] Draft review
   [ ] Final confirmation
   [ ] Custom: ____________________

7. Estimated Execution Time:
   [ ] Seconds (< 1 min)
   [ ] Minutes (1-10 min)
   [ ] Long-running (10+ min)

8. Is this a chained workflow?
   [ ] No - standalone agent
   [ ] Yes - depends on output from: ____________________
```

### State Machine States

Define the orchestrator states for your agent:

```python
# Example state progression (customize for your agent):
class OrchestratorState( Enum ):
    # Active states
    INITIALIZING = "initializing"
    PROCESSING   = "processing"
    GENERATING   = "generating"

    # Waiting states (human-in-the-loop)
    WAITING_APPROVAL = "waiting_approval"

    # Terminal states
    COMPLETED = "completed"
    FAILED    = "failed"
```

### Pre-Flight Check: API Key Firewall

**Critical**: Use a separate API key from Claude Code's own key to prevent billing conflicts
and enable independent rate limiting.

```python
# Pattern from deep_research/api_client.py
# Three-tier priority: explicit param → env var → local file

ENV_VAR_NAME  = "ANTHROPIC_API_KEY_FIREWALLED"
KEY_FILE_NAME = "anthropic-api-key-firewalled"

def _load_api_key( self, api_key=None ):
    """
    Load API key with three-tier priority.

    Requires:
        - At least one key source is available

    Ensures:
        - Returns a valid API key string
        - Never uses Claude Code's own ANTHROPIC_API_KEY

    Raises:
        - ValueError if no key found in any source
    """
    # Priority 1: Explicit parameter (testing, overrides)
    if api_key:
        return api_key

    # Priority 2: Dedicated env var (production)
    env_key = os.environ.get( ENV_VAR_NAME )
    if env_key:
        if self.debug: print( f"Using API key from {ENV_VAR_NAME}" )
        return env_key

    # Priority 3: Local file (development)
    try:
        file_key = cu.get_api_key( KEY_FILE_NAME )
        if file_key:
            if self.debug: print( f"Using API key from local file" )
            return file_key
    except FileNotFoundError:
        pass

    raise ValueError(
        f"No API key found. Set {ENV_VAR_NAME} or create "
        f"src/conf/keys/{KEY_FILE_NAME}"
    )
```

**Pre-flight checklist**:
```
[ ] Firewalled API key created (separate from Claude Code's key)
[ ] Key stored in ONE of: env var, src/conf/keys/ file, or parameter
[ ] Key is NOT the same as ANTHROPIC_API_KEY (Claude Code's key)
```

### Pre-Flight Check: Configuration Manager Integration

Register your agent's config keys in `lupin-app.ini` so they can be tuned without code changes:

```ini
# In src/conf/lupin-app.ini under [Lupin: Baseline]
{agent_name} model           = claude-sonnet-4-20250514
{agent_name} max iterations  = 10
{agent_name} timeout seconds = 300
{agent_name} budget usd      = 5.00
```

```ini
# In src/conf/lupin-app-splainer.ini (ALWAYS add matching explanation)
{agent_name} model           = LLM model for {agent_name} inference
{agent_name} max iterations  = Maximum processing iterations before forced stop
{agent_name} timeout seconds = Maximum wall-clock time before timeout
{agent_name} budget usd      = Maximum API cost before BudgetExceededError
```

```python
# Loading config values in your agent
import cosa.utils.util as cu
from cosa.app.configuration_manager import ConfigurationManager

config_mgr = ConfigurationManager( cu.get_project_root() + "/src/conf/lupin-app.ini" )
model      = config_mgr.get( "{agent_name} model" )
budget     = float( config_mgr.get( "{agent_name} budget usd", default="5.00" ) )
```

### Pre-Flight Check: Dependency Verification

Verify required packages are available before the user invests time in scaffolding:

```python
def verify_dependencies( agent_name, required_packages ):
    """
    Check that all required packages are importable.

    Requires:
        - required_packages is a list of (import_name, pip_name) tuples

    Ensures:
        - Prints clear error messages for missing packages
        - Returns True only if ALL dependencies are available
    """
    missing = []
    for import_name, pip_name in required_packages:
        try:
            __import__( import_name )
        except ImportError:
            missing.append( pip_name )

    if missing:
        print( f"Missing dependencies for {agent_name}:" )
        for pkg in missing:
            print( f"  pip install {pkg}" )
        return False

    return True

# Example usage:
REQUIRED = [
    ( "anthropic", "anthropic" ),
    ( "pydantic",  "pydantic" ),
]
# Optional (only if your agent needs them):
# ( "pydub",      "pydub" ),         # Audio processing
# ( "websockets", "websockets" ),    # TTS streaming
# ( "elevenlabs", "elevenlabs" ),    # ElevenLabs TTS
```

---

## Phase 1-2: Skeletal Agent Foundation + Mock Clients

### Directory Structure

Create the agent directory with this structure:

```
src/cosa/agents/{agent_name}/
├── __init__.py          # Package exports
├── config.py            # Configuration dataclass
├── state.py             # Pydantic models + state enum
├── orchestrator.py      # Core business logic
├── __main__.py          # CLI entry point
└── prompts/             # LLM prompt templates (optional)
    └── __init__.py
```

### File Templates

#### `__init__.py`

```python
"""
{Agent Display Name} - {brief description}.

Example:
    from cosa.agents.{agent_name} import {AgentName}Orchestrator

    orchestrator = {AgentName}Orchestrator( query="...", debug=True )
    result = await orchestrator.run()
"""

from .orchestrator import {AgentName}Orchestrator
from .config import {AgentName}Config
from .state import OrchestratorState

__all__ = [
    "{AgentName}Orchestrator",
    "{AgentName}Config",
    "OrchestratorState",
]
```

#### `config.py`

```python
#!/usr/bin/env python3
"""
Configuration for {Agent Display Name}.

Design decisions:
- {document key architectural choices}
- {explain model selection rationale}
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class {AgentName}Config:
    """
    Configuration for the {agent_name} agent.

    Requires:
        - All numeric values must be positive

    Ensures:
        - Provides sensible defaults for all parameters
    """

    # === Model Selection ===
    model: str = "claude-sonnet-4-20250514"

    # === Execution Limits ===
    max_iterations: int = 10
    timeout_seconds: int = 300

    # === COSA Integration ===
    feedback_timeout_seconds: int = 300
    narrate_progress: bool = True

    # === Output Configuration ===
    # Add agent-specific output settings here


def quick_smoke_test():
    """Quick smoke test for {AgentName}Config."""
    import cosa.utils.util as cu

    cu.print_banner( "{AgentName}Config Smoke Test", prepend_nl=True )

    try:
        print( "Testing default config..." )
        config = {AgentName}Config()
        assert config.model == "claude-sonnet-4-20250514"
        print( "✓ Default config created" )

        print( "\\n✓ {AgentName}Config smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

#### `state.py`

```python
#!/usr/bin/env python3
"""
State Schemas for {Agent Display Name}.

Uses Pydantic for structured outputs and Enum for state machine.
"""

from enum import Enum
from typing import TypedDict, Optional, Any
from pydantic import BaseModel, Field


class OrchestratorState( Enum ):
    """
    State machine for the {Agent Display Name}.

    Active states represent work being done.
    Waiting states are yield points for human-in-the-loop.
    Terminal states indicate completion or failure.
    """
    # Active states
    INITIALIZING = "initializing"
    PROCESSING   = "processing"
    GENERATING   = "generating"

    # Waiting states (yield control via await)
    WAITING_APPROVAL = "waiting_approval"

    # Terminal states
    COMPLETED = "completed"
    FAILED    = "failed"


# =============================================================================
# Pydantic Models for Structured Outputs
# =============================================================================

class {AgentName}Result( BaseModel ):
    """
    Result model for {agent_name} output.
    """
    success: bool
    output: str
    metadata: dict = Field( default_factory=dict )


# =============================================================================
# TypedDict State (for workflow tracking)
# =============================================================================

class {AgentName}State( TypedDict ):
    """
    Main state for the {agent_name} workflow.
    """
    # Input
    original_input: str

    # Processing
    current_state: str
    iterations: int

    # Output
    result: Optional[str]
    error: Optional[str]


def create_initial_state( input_value: str ) -> {AgentName}State:
    """
    Create the initial state for a {agent_name} task.

    Args:
        input_value: The user's input

    Returns:
        {AgentName}State: Initialized state dictionary
    """
    return {AgentName}State(
        original_input = input_value,
        current_state  = OrchestratorState.INITIALIZING.value,
        iterations     = 0,
        result         = None,
        error          = None,
    )


def quick_smoke_test():
    """Quick smoke test for state schemas."""
    import cosa.utils.util as cu

    cu.print_banner( "{Agent Display Name} State Smoke Test", prepend_nl=True )

    try:
        print( "Testing OrchestratorState enum..." )
        assert OrchestratorState.COMPLETED.value == "completed"
        print( f"✓ OrchestratorState enum valid ({len( OrchestratorState )} states)" )

        print( "Testing create_initial_state..." )
        state = create_initial_state( "test input" )
        assert state[ "original_input" ] == "test input"
        print( "✓ create_initial_state works" )

        print( "\\n✓ State smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

#### `orchestrator.py` (skeleton)

```python
#!/usr/bin/env python3
"""
{Agent Display Name} Orchestrator.

Core business logic for {brief description}.
"""

import asyncio
from typing import Optional

from .config import {AgentName}Config
from .state import OrchestratorState, create_initial_state


class {AgentName}Orchestrator:
    """
    Orchestrates the {agent_name} workflow.

    Manages state transitions, LLM interactions, and human-in-the-loop
    decision points.
    """

    def __init__(
        self,
        input_value: str,
        config: Optional[ {AgentName}Config ] = None,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the orchestrator.

        Args:
            input_value: Primary input for processing
            config: Configuration options (uses defaults if None)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.input_value = input_value
        self.config      = config or {AgentName}Config()
        self.debug       = debug
        self.verbose     = verbose

        # Initialize state
        self._state = create_initial_state( input_value )
        self._current_state = OrchestratorState.INITIALIZING

    async def run( self ) -> Optional[ str ]:
        """
        Execute the full workflow.

        Returns:
            str: Result of the workflow, or None if cancelled
        """
        try:
            # Phase 1: Initialize
            self._current_state = OrchestratorState.PROCESSING

            # Phase 2: Process (implement your logic here)
            result = await self._process()

            # Phase 3: Generate output
            self._current_state = OrchestratorState.GENERATING
            output = await self._generate_output( result )

            self._current_state = OrchestratorState.COMPLETED
            return output

        except Exception as e:
            self._current_state = OrchestratorState.FAILED
            self._state[ "error" ] = str( e )
            raise

    async def _process( self ) -> str:
        """Process the input. Override with actual logic."""
        # Placeholder - implement your processing logic
        return self.input_value

    async def _generate_output( self, processed: str ) -> str:
        """Generate final output. Override with actual logic."""
        # Placeholder - implement your output generation
        return f"Processed: {processed}"


def quick_smoke_test():
    """Quick smoke test for {AgentName}Orchestrator."""
    import cosa.utils.util as cu

    cu.print_banner( "{AgentName}Orchestrator Smoke Test", prepend_nl=True )

    try:
        print( "Testing orchestrator instantiation..." )
        orchestrator = {AgentName}Orchestrator(
            input_value = "test input",
            debug       = True
        )
        assert orchestrator._current_state == OrchestratorState.INITIALIZING
        print( "✓ Orchestrator created" )

        print( "\\n✓ Orchestrator smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

#### `__main__.py`

```python
#!/usr/bin/env python3
"""
CLI entry point for {Agent Display Name}.

Usage:
    python -m cosa.agents.{agent_name} "your input here"
    python -m cosa.agents.{agent_name} --help
"""

import argparse
import asyncio
import sys

from .orchestrator import {AgentName}Orchestrator
from .config import {AgentName}Config


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="{Agent Display Name} - {brief description}"
    )

    parser.add_argument(
        "input",
        help="Input to process"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()

    config = {AgentName}Config()

    orchestrator = {AgentName}Orchestrator(
        input_value = args.input,
        config      = config,
        debug       = args.debug,
        verbose     = args.verbose
    )

    result = await orchestrator.run()

    if result:
        print( f"\\nResult: {result}" )
    else:
        print( "\\nOperation cancelled." )
        sys.exit( 1 )


if __name__ == "__main__":
    asyncio.run( main() )
```

#### `mock_clients.py` (optional but recommended)

Mock clients enable testing without real API calls. Create one mock class per external dependency.

```python
#!/usr/bin/env python3
"""
Mock clients for {Agent Display Name} testing.

Provides canned responses that match real API response structure.
Used by dry-run mode and unit tests.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MockCostEstimate:
    """Mock cost tracking that always reports $0.00."""
    total_cost_usd : float = 0.0
    total_input    : int   = 0
    total_output   : int   = 0
    api_calls      : int   = 0


# =============================================================================
# Canned Responses — Match real API response structure exactly
# =============================================================================

MOCK_RESULT = {
    "title"   : "Mock Result: Dry Run Test",
    "content" : "This is a simulated result for testing purposes.",
    "metadata": {
        "model"       : "mock",
        "input_tokens": 0,
        "output_tokens": 0,
    }
}


class Mock{AgentName}APIClient:
    """
    Mock API client for {agent_name}.

    Mirrors the real client interface but returns canned responses.

    Requires:
        - Same method signatures as real API client

    Ensures:
        - Never makes real API calls
        - Returns structurally valid mock responses
        - Tracks call count for test assertions
    """

    def __init__( self, config=None, debug=False, verbose=False ):
        self.config       = config
        self.debug        = debug
        self.verbose      = verbose
        self.call_count   = 0
        self.cost_estimate = MockCostEstimate()

    async def process( self, input_value, **kwargs ):
        """
        Mock processing — returns canned result after simulated delay.

        Args:
            input_value: The input to "process"

        Returns:
            dict: Mock result matching real API response structure
        """
        self.call_count += 1
        await asyncio.sleep( 0.5 )  # Simulate latency

        if self.debug: print( f"[Mock] Call #{self.call_count}: {input_value[ :50 ]}" )

        return MOCK_RESULT.copy()

    def get_cost_summary( self ):
        """Return zero-cost summary."""
        return self.cost_estimate


def quick_smoke_test():
    """Quick smoke test for mock clients."""
    import cosa.utils.util as cu

    cu.print_banner( "{Agent Display Name} Mock Clients Smoke Test", prepend_nl=True )

    try:
        print( "1. Testing MockCostEstimate..." )
        cost = MockCostEstimate()
        assert cost.total_cost_usd == 0.0
        print( "   ✓ MockCostEstimate: $0.00" )

        print( "2. Testing Mock{AgentName}APIClient..." )
        client = Mock{AgentName}APIClient( debug=True )
        result = asyncio.run( client.process( "test input" ) )
        assert result[ "title" ] == "Mock Result: Dry Run Test"
        assert client.call_count == 1
        print( f"   ✓ Mock client returned: {result[ 'title' ]}" )

        print( "\\n✓ Mock clients smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

**Updated directory structure** with mock clients:

```
src/cosa/agents/{agent_name}/
├── __init__.py          # Package exports
├── config.py            # Configuration dataclass
├── state.py             # Pydantic models + state enum
├── orchestrator.py      # Core business logic
├── mock_clients.py      # Mock clients for testing (optional)
├── __main__.py          # CLI entry point
└── prompts/             # LLM prompt templates (optional)
    └── __init__.py
```

### Phase 1-2 Smoke Test Checklist

```
[ ] All files created in src/cosa/agents/{agent_name}/
[ ] python -m cosa.agents.{agent_name}.config  (smoke test passes)
[ ] python -m cosa.agents.{agent_name}.state   (smoke test passes)
[ ] python -m cosa.agents.{agent_name}.orchestrator (smoke test passes)
[ ] python -m cosa.agents.{agent_name}.mock_clients (smoke test passes)
[ ] python -m cosa.agents.{agent_name} "test" --debug (CLI runs)
[ ] (Optional) Scaffold live pipeline test file: src/tests/smoke/test_{agent_name}_live_pipeline.py
```

### Phase 1-2 TodoWrite Template

```
[LUPIN] Create {agent_name} directory structure
[LUPIN] Write {agent_name}/config.py with dataclass
[LUPIN] Write {agent_name}/state.py with Pydantic models and enum
[LUPIN] Write {agent_name}/orchestrator.py skeleton
[LUPIN] Write {agent_name}/mock_clients.py with canned responses
[LUPIN] Write {agent_name}/__main__.py CLI entry point
[LUPIN] Run smoke tests for Phase 1-2 files
```

---

## Phase 3-4: Notification Integration

### cosa_interface.py

```python
#!/usr/bin/env python3
"""
COSA Voice Interface Integration Layer for {Agent Display Name}.

Provides async wrappers for cosa-voice notification tools.
"""

import asyncio
import logging
import os
from typing import Optional

from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    NotificationType,
    NotificationPriority,
)
from lupin_cli.notifications.notify_user_sync import notify_user_sync as _notify_user_sync
from lupin_cli.notifications.notify_user_async import notify_user_async as _notify_user_async

logger = logging.getLogger( __name__ )


def _get_sender_id() -> str:
    """
    Get sender_id for {Agent Display Name} notifications.

    Returns:
        str: Sender ID in format: {agent_name}@{project}.deepily.ai
    """
    cwd = os.getcwd()

    if "/lupin" in cwd.lower():
        project = "lupin"
    elif "/cosa" in cwd.lower():
        project = "cosa"
    else:
        project = os.path.basename( cwd ).lower()

    return f"{agent_name}@{project}.deepily.ai"


# Cache sender_id at module load
SENDER_ID = _get_sender_id()

# Session name for UI display
SESSION_NAME: Optional[str] = None


async def notify_progress(
    message: str,
    priority: str = "medium",
    abstract: Optional[str] = None,
    job_id: Optional[str] = None
) -> None:
    """
    Send fire-and-forget progress notification.

    Args:
        message: The message to announce
        priority: "low", "medium", "high", or "urgent"
        abstract: Optional supplementary context (markdown)
        job_id: Optional job ID for routing (e.g., "xx-a1b2c3d4")
    """
    try:
        request = NotificationRequest(
            message           = message,
            sender_id         = SENDER_ID,
            notification_type = NotificationType.PROGRESS,
            priority          = NotificationPriority( priority ),
            abstract          = abstract,
            job_id            = job_id,
        )
        await asyncio.to_thread( _notify_user_async, request )
    except Exception as e:
        logger.warning( f"Notification failed: {e}" )


async def ask_yes_no(
    question: str,
    default: str = "no",
    timeout: int = 300,
    abstract: Optional[str] = None
) -> bool:
    """
    Ask a yes/no question and wait for response.

    Args:
        question: The yes/no question to ask
        default: Default answer if timeout ("yes" or "no")
        timeout: Seconds to wait for response
        abstract: Optional supplementary context

    Returns:
        bool: True if user said yes, False otherwise
    """
    # Implementation follows cosa.agents.utils.voice_io pattern
    pass  # See deep_research/cosa_interface.py for full implementation


def quick_smoke_test():
    """Quick smoke test for cosa_interface."""
    import cosa.utils.util as cu

    cu.print_banner( "{Agent Display Name} COSA Interface Smoke Test", prepend_nl=True )

    try:
        print( "Testing sender_id generation..." )
        sender_id = _get_sender_id()
        assert "@" in sender_id
        assert "deepily.ai" in sender_id
        print( f"✓ Sender ID: {sender_id}" )

        print( "\\n✓ COSA interface smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

### voice_io.py

```python
#!/usr/bin/env python3
"""
Voice-First I/O Layer for {Agent Display Name}.

Thin wrapper around cosa.agents.utils.voice_io configured with
this agent's cosa_interface for proper sender identity.
"""

import asyncio
from typing import Optional, List, Union

from cosa.agents.utils import voice_io as _core_voice_io
from . import cosa_interface as _cosa_interface

# Configure core voice_io with our cosa_interface
_core_voice_io.configure( _cosa_interface )


# Re-export functions
def set_cli_mode( enabled: bool ) -> None:
    """Enable or disable forced CLI mode."""
    _core_voice_io.set_cli_mode( enabled )


async def notify(
    message: str,
    priority: str = "medium",
    abstract: Optional[str] = None,
    session_name: Optional[str] = None,
    job_id: Optional[str] = None
) -> None:
    """Send a progress notification (voice-first)."""
    await _core_voice_io.notify( message, priority, abstract, session_name, job_id )


async def ask_yes_no(
    question: str,
    default: str = "no",
    timeout: int = 60,
    abstract: Optional[str] = None
) -> bool:
    """Ask a yes/no question (voice-first)."""
    return await _core_voice_io.ask_yes_no( question, default, timeout, abstract )


async def get_input(
    prompt: str,
    allow_empty: bool = True,
    timeout: int = 300
) -> Optional[str]:
    """Get open-ended input from user (voice-first)."""
    return await _core_voice_io.get_input( prompt, allow_empty, timeout )


async def choose(
    question: str,
    options: Union[ List[str], List[dict] ],
    timeout: int = 120,
    allow_custom: bool = False
) -> str:
    """Present multiple-choice options (voice-first)."""
    return await _core_voice_io.choose( question, options, timeout, allow_custom )


def quick_smoke_test():
    """Quick smoke test for voice_io wrapper."""
    import cosa.utils.util as cu

    cu.print_banner( "{Agent Display Name} Voice I/O Smoke Test", prepend_nl=True )

    try:
        print( "Testing module configuration..." )
        assert _core_voice_io._cosa_interface is not None
        print( "✓ Core voice_io configured" )

        print( "Testing async function signatures..." )
        import inspect
        assert inspect.iscoroutinefunction( notify )
        assert inspect.iscoroutinefunction( ask_yes_no )
        print( "✓ Async functions have correct signatures" )

        print( "\\n✓ Voice I/O smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

### Notification Placement Guidelines

Add notifications at these key points:

```python
# 1. Workflow start
await voice_io.notify( f"Starting {agent_name}: {input_summary}", priority="medium" )

# 2. Phase transitions
await voice_io.notify( "Processing complete, generating output...", priority="low" )

# 3. Human-in-the-loop prompts
approved = await voice_io.ask_yes_no( "Proceed with generation?", default="yes" )

# 4. Completion
await voice_io.notify(
    "Task complete!",
    priority="medium",
    abstract=f"**Result**: {summary}\\n**Duration**: {duration}s"
)

# 5. Errors
await voice_io.notify( f"Error: {error_msg}", priority="urgent" )
```

### Phase 3-4 Smoke Test Checklist

```
[ ] cosa_interface.py created with sender_id generation
[ ] voice_io.py created as wrapper
[ ] Notifications fire when orchestrator runs
[ ] Human-in-the-loop prompts work (if applicable)
[ ] python -m cosa.agents.{agent_name}.cosa_interface (smoke test)
[ ] python -m cosa.agents.{agent_name}.voice_io (smoke test)
[ ] (If live pipeline test exists) Verify notifications appear in test output
```

### Phase 3-4 TodoWrite Template

```
[LUPIN] Create {agent_name}/cosa_interface.py with notification wrappers
[LUPIN] Create {agent_name}/voice_io.py as thin wrapper
[LUPIN] Add progress notifications to orchestrator phases
[LUPIN] Add human-in-the-loop prompts (if applicable)
[LUPIN] Run smoke tests for Phase 3-4 files
[LUPIN] Test end-to-end notification flow
```

---

## Phase 5: AgenticJob Queue Wrapper

### job.py

```python
"""
{Agent Display Name} background job for queue-based execution.

Wraps the {AgentName}Orchestrator for execution within the COSA queue system.

Example:
    job = {AgentName}Job(
        input_value = "your input here",
        user_id     = "user123",
        user_email  = "user@example.com",
        session_id  = "wise-penguin",
        debug       = True
    )
    result = job.do_all()
"""

import asyncio
from datetime import datetime
from typing import Optional

from cosa.agents.agentic_job_base import AgenticJobBase


class {AgentName}Job( AgenticJobBase ):
    """
    Background job for {Agent Display Name} execution.

    Attributes:
        input_value: The primary input to process
        result_path: Path to generated output (set after completion)
    """

    JOB_TYPE   = "{agent_name}"
    JOB_PREFIX = "{prefix}"  # e.g., "na" for notification_agent

    def __init__(
        self,
        input_value: str,
        user_id: str,
        user_email: str,
        session_id: str,
        dry_run: bool = False,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a {Agent Display Name} job.

        Args:
            input_value: The primary input to process
            user_id: System ID of the job owner
            user_email: Email address for output storage
            session_id: WebSocket session for notifications
            dry_run: Simulate execution without API calls
            debug: Enable debug output
            verbose: Enable verbose output
        """
        super().__init__(
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id,
            debug      = debug,
            verbose    = verbose
        )

        # Job-specific parameters
        self.input_value = input_value
        self.dry_run     = dry_run

        # Results (populated after execution)
        self.result_path = None

    @property
    def last_question_asked( self ) -> str:
        """Display string for queue UI."""
        truncated = self.input_value[ :50 ] + "..." if len( self.input_value ) > 50 else self.input_value
        return f"[{Agent Display Name}] {truncated}"

    def do_all( self ) -> str:
        """
        Execute job and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        """
        if self.debug:
            print( f"[{AgentName}Job] Starting do_all()..." )

        self.status     = "running"
        self.started_at = datetime.now().isoformat()

        try:
            result = asyncio.run( self._execute() )

            self.status       = "completed"
            self.completed_at = datetime.now().isoformat()
            self.result       = result
            self.answer_conversational = result

            return result

        except Exception as e:
            self.status       = "failed"
            self.completed_at = datetime.now().isoformat()
            self.error        = str( e )

            self.answer_conversational = f"Job failed: {str( e )}"
            return self.answer_conversational

    async def _execute( self ) -> str:
        """
        Internal async execution.

        Returns:
            str: Conversational summary of results
        """
        from cosa.agents.{agent_name} import voice_io, cosa_interface

        # Handle dry-run mode
        if self.dry_run:
            return await self._execute_dry_run( voice_io, cosa_interface )

        # Import orchestrator
        from cosa.agents.{agent_name}.orchestrator import {AgentName}Orchestrator
        from cosa.agents.{agent_name}.config import {AgentName}Config

        # Set sender_id for notifications
        cosa_interface.SENDER_ID = cosa_interface._get_sender_id() + f"#{self.id_hash}"

        # Notify start
        await voice_io.notify(
            f"Starting {agent_name}: {self.input_value[ :80 ]}",
            priority="medium"
        )

        # Create and run orchestrator
        config = {AgentName}Config()
        orchestrator = {AgentName}Orchestrator(
            input_value = self.input_value,
            config      = config,
            debug       = self.debug,
            verbose     = self.verbose
        )

        result = await orchestrator.run()

        if result is None:
            await voice_io.notify( "Operation was cancelled.", priority="medium" )
            return "Operation was cancelled by the user."

        # ── Artifact Storage ──────────────────────────────────
        # Store output files and metadata in self.artifacts for UI access.
        # The queue runner includes artifacts in job_state_transition events.
        #
        # Config key pattern: "{agent_name} output directory = /io/{agent_name}"
        # Path construction:
        #   output_dir = config_mgr.get( "{agent_name} output directory" )
        #   full_path  = cu.get_project_root() + output_dir + f"/{user_email}/{timestamp}_{sanitized}.md"
        #
        self.artifacts[ "result" ] = result
        # Real agents also store: "report_path", "audio_path", "cost_summary", etc.

        # Notify completion
        await voice_io.notify(
            "Task complete!",
            priority="medium",
            abstract=f"**Result**: {result[ :200 ]}..."
        )

        return f"Task complete. {result}"

    async def _execute_dry_run( self, voice_io, cosa_interface ) -> str:
        """Execute dry-run mode with breadcrumb notifications."""
        import asyncio

        cosa_interface.SENDER_ID = cosa_interface._get_sender_id() + f"#{self.id_hash}"

        await voice_io.notify( "Dry run: Starting simulation", priority="low" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: Skipping processing", priority="low" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run complete!", priority="medium" )

        return "Dry run complete. No actual processing performed."


def quick_smoke_test():
    """Quick smoke test for {AgentName}Job."""
    import cosa.utils.util as cu

    cu.print_banner( "{AgentName}Job Smoke Test", prepend_nl=True )

    try:
        print( "Testing module import..." )
        from cosa.agents.{agent_name}.job import {AgentName}Job
        print( "✓ Module imported" )

        print( "Testing job instantiation..." )
        job = {AgentName}Job(
            input_value = "test input",
            user_id     = "user123",
            user_email  = "test@test.com",
            session_id  = "session456",
            debug       = True
        )
        print( f"✓ Job created: {job.id_hash}" )

        print( "Testing ID format..." )
        assert job.id_hash.startswith( "{prefix}-" )
        print( f"✓ ID format correct: {job.id_hash}" )

        print( "Testing class constants..." )
        assert {AgentName}Job.JOB_TYPE == "{agent_name}"
        assert {AgentName}Job.JOB_PREFIX == "{prefix}"
        print( "✓ Class constants correct" )

        print( "\\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

### Expeditor Registration (agent_registry.py)

**CRITICAL**: New agents MUST be registered in the Expeditor's agent registry for argument
parsing and fallback question prompting. Without this, the voice path cannot discover your agent.

**File**: `src/cosa/agents/runtime_argument_expeditor/agent_registry.py`

Add an entry to the `AGENTIC_AGENTS` dictionary:

```python
AGENTIC_AGENTS = {
    # ... existing agents ...

    "agent router go to {agent_name}" : {
        "cli_module"         : "cosa.agents.{agent_name}.cli",
        "job_class_path"     : "cosa.agents.{agent_name}.job.{AgentName}Job",
        "required_user_args" : [ "query" ],           # Args the user MUST provide
        "system_provided"    : [ "user_email", "session_id", "user_id", "no_confirm" ],
        "arg_mapping"        : {
            # Maps natural-language arg names → CLI arg names
            "topic"  : "query",
            "query"  : "query",
            "budget" : "budget",
        },
        "fallback_questions" : {
            # If arg is missing, Expeditor asks the user via voice
            "query"  : "What would you like me to process?",
            "budget" : "Would you like to set a budget limit? Say a dollar amount, or 'no limit'.",
        },
    },
}
```

**Key fields explained**:

| Field | Purpose |
|-------|---------|
| `cli_module` | Python module path for `--help` capture |
| `job_class_path` | Fully qualified class path for import |
| `required_user_args` | Args the Expeditor will extract or prompt for |
| `system_provided` | Args injected by the system (user never provides these) |
| `arg_mapping` | Maps synonyms to canonical arg names (e.g., "topic" → "query") |
| `fallback_questions` | Voice prompts for missing required args |

**Optional field**: `special_handlers` — for advanced input resolution (e.g., `"research": "fuzzy_file_match"` in the podcast generator).

### Factory Registration (agentic_job_factory.py)

Add an `elif` branch to `create_agentic_job()` in `src/cosa/rest/agentic_job_factory.py`:

```python
def create_agentic_job( command, args_dict, user_id, user_email, session_id, debug=False, verbose=False ):

    from cosa.agents.deep_research.job import DeepResearchJob
    from cosa.agents.podcast_generator.job import PodcastGeneratorJob
    from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
    from cosa.agents.{agent_name}.job import {AgentName}Job     # <-- ADD IMPORT

    if command == "agent router go to deep research":
        # ... existing ...

    elif command == "agent router go to podcast generator":
        # ... existing ...

    elif command == "agent router go to research to podcast":
        # ... existing ...

    elif command == "agent router go to {agent_name}":           # <-- ADD BRANCH
        return {AgentName}Job(
            input_value = args_dict.get( "query", "" ),
            user_id     = user_id,
            user_email  = user_email,
            session_id  = session_id,
            dry_run     = args_dict.get( "dry_run", False ),
            debug       = debug,
            verbose     = verbose
        )

    else:
        print( f"[agentic_job_factory] Unknown command: {command}" )
        return None
```

This factory is shared by both the voice path (Expeditor → TodoFifoQueue) and the REST path
(dedicated router endpoints). Adding your branch here means both paths work automatically.

### Phase 5 Smoke Test Checklist

```
[ ] job.py created with AgenticJobBase inheritance
[ ] JOB_TYPE and JOB_PREFIX constants defined
[ ] do_all() -> _execute() bridge pattern implemented
[ ] Dry-run mode with breadcrumb notifications
[ ] python -m cosa.agents.{agent_name}.job (smoke test)
[ ] Job submission via API endpoint works
[ ] Job appears in queue UI correctly
[ ] Live pipeline test created: src/tests/smoke/test_{agent_name}_live_pipeline.py
[ ] Live pipeline test passes with submit-and-poll validation
```

### WebSocket Job State Transitions

You do **not** need to emit WebSocket events manually. The `RunningFifoQueue` handles this
automatically via `emit_job_state_transition()` (defined in `src/cosa/rest/queue_util.py`).

Your job just needs to set these fields — the queue runner reads them at transition time:

| Field | When to Set | Purpose |
|-------|------------|---------|
| `self.status` | In `do_all()` | "running", "completed", "failed" |
| `self.artifacts` | In `_execute()` | File paths, cost summaries, metadata |
| `self.answer_conversational` | In `do_all()` | Human-readable result for UI display |

**Automatic transitions emitted by the queue**:
- `todo → run` — when the consumer thread picks up your job
- `run → done` — when `do_all()` returns successfully
- `run → dead` — when `do_all()` raises an exception

Each transition includes metadata (response_text, agent_type, duration_seconds, etc.) and is
targeted to the correct user via `user_job_tracker`. The browser receives these as
`job_state_transition` WebSocket events and updates the UI automatically.

### Phase 5 TodoWrite Template

```
[LUPIN] Create {agent_name}/job.py with AgenticJobBase inheritance
[LUPIN] Implement do_all() -> _execute() bridge pattern
[LUPIN] Add dry-run mode with breadcrumb notifications
[LUPIN] Register agent in agent_registry.py (AGENTIC_AGENTS dict)
[LUPIN] Add factory elif branch in agentic_job_factory.py
[LUPIN] Create dedicated FastAPI router (Phase 5b)
[LUPIN] Register router in main.py
[LUPIN] Run smoke tests for job.py
[LUPIN] Test job submission and queue visualization
```

---

## Phase 5b: Dedicated FastAPI Router

Each agentic job gets a **dedicated REST endpoint** for direct submission from the browser UI.
This is how the notification submission cards (Surface 3) submit jobs — separate from the voice
routing path.

**Reference implementations**:
- `src/cosa/rest/routers/deep_research.py`
- `src/cosa/rest/routers/podcast_generator.py`

### Router Template

Create `src/cosa/rest/routers/{agent_name}.py`:

```python
"""
{Agent Display Name} REST router for direct job submission.

Provides the endpoint used by the notification UI submission card.

Endpoints:
    POST /api/{agent-name}/submit - Submit {agent_name} job
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

import cosa.utils.util as cu
from cosa.rest.auth import get_current_user
from cosa.rest.queue_extensions import user_job_tracker
from cosa.rest.agentic_job_factory import create_agentic_job


router = APIRouter( tags=[ "{agent-name}" ] )


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════════

class {AgentName}SubmitRequest( BaseModel ):
    """Request body for submitting a {agent_name} job."""
    query   : str            = Field( ..., min_length=1, description="Primary input" )
    budget  : Optional[float] = Field( None, ge=0, description="Max budget in USD" )
    dry_run : bool           = Field( False, description="Simulate without API calls" )


class {AgentName}SubmitResponse( BaseModel ):
    """Response body for {agent_name} job submission."""
    status         : str = Field( ..., description="Job status (queued)" )
    job_id         : str = Field( ..., description="Unique job identifier" )
    queue_position : int = Field( ..., description="Position in the todo queue" )
    message        : str = Field( ..., description="Human-readable confirmation" )


# ═══════════════════════════════════════════════════════════════════════════════
# Dependencies
# ═══════════════════════════════════════════════════════════════════════════════

def get_todo_queue():
    """Dependency to get todo queue from main module."""
    import fastapi_app.main as main_module
    return main_module.jobs_todo_queue


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@router.post( "/api/{agent-name}/submit", response_model={AgentName}SubmitResponse )
async def submit_{agent_name}(
    request_body: {AgentName}SubmitRequest,
    current_user: dict = Depends( get_current_user ),
    todo_queue = Depends( get_todo_queue )
):
    """
    Submit a {agent_name} job to the background queue.

    Requires:
        - Authenticated user (Bearer token)
        - Valid input in request_body

    Ensures:
        - Job created and pushed to queue
        - User-job association tracked for WebSocket notifications
        - Returns job_id for polling
    """
    user_id    = current_user.get( "uid" )
    user_email = current_user.get( "email" )

    if not user_id or not user_email:
        raise HTTPException( status_code=400, detail="User ID or email not found in token" )

    session_id = f"api-{user_id[ :8 ]}"

    try:
        args_dict = { "query": request_body.query }
        if request_body.budget is not None:
            args_dict[ "budget" ] = str( request_body.budget )
        if request_body.dry_run:
            args_dict[ "dry_run" ] = True

        job = create_agentic_job(
            command    = "agent router go to {agent_name}",
            args_dict  = args_dict,
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id
        )

        if job is None:
            raise HTTPException( status_code=500, detail="Failed to create job" )

        # Associate BEFORE push to prevent race condition
        user_job_tracker.associate_job_with_user( job.id_hash, user_id )
        user_job_tracker.associate_job_with_session( job.id_hash, session_id )

        # Push to todo queue
        todo_queue.push( job )

        return {AgentName}SubmitResponse(
            status         = "queued",
            job_id         = job.id_hash,
            queue_position = todo_queue.size(),
            message        = f"{Agent Display Name} job queued: {job.last_question_asked}"
        )

    except Exception as e:
        raise HTTPException( status_code=500, detail=f"Failed to submit job: {str( e )}" )
```

### Register Router in main.py

Add the import and registration in `src/fastapi_app/main.py`:

```python
# At the top with other router imports:
from cosa.rest.routers import {agent_name}

# In the router registration block:
app.include_router( {agent_name}.router )
```

### Critical Pattern: Associate BEFORE Push

The `user_job_tracker.associate_job_with_user()` and `associate_job_with_session()` calls MUST
happen **before** `todo_queue.push()`. The queue's consumer thread may grab the job immediately
after push, and if the user mapping doesn't exist yet, WebSocket notifications can't be routed
to the correct user.

```python
# ✅ CORRECT — associate first, push second
user_job_tracker.associate_job_with_user( job.id_hash, user_id )
user_job_tracker.associate_job_with_session( job.id_hash, session_id )
todo_queue.push( job )

# ❌ WRONG — race condition if consumer grabs job before association
todo_queue.push( job )
user_job_tracker.associate_job_with_user( job.id_hash, user_id )
```

---

## Phase 5b: Dedicated Router + Automated Testing

### Overview

After queue integration is working (Phase 5), create a dedicated FastAPI router for your agent
and an automated live pipeline test. This ensures every new agent has repeatable, automated
validation from day one.

**CRITICAL**: Prefer automated pipeline tests over manual curl/UI submission. The test
infrastructure (`LivePipelineTestBase`, `InteractiveSmokeTest`) already handles auth,
session resolution, submit-and-poll, validation, and reporting.

### Phase 5b Smoke Test Checklist

```
[ ] Router created at src/cosa/rest/routers/{agent_name}.py
[ ] Router registered in main.py via app.include_router()
[ ] POST /api/{agent-name}/submit returns 200 with valid job_id
[ ] Job appears in todo queue after submission
[ ] Live pipeline test created: src/tests/smoke/test_{agent_name}_live_pipeline.py
[ ] Live pipeline test passes
[ ] Q&A script created (if interactive): src/conf/notification-proxy-scripts/{agent-name}.json
[ ] Proxy integration passes (if interactive)
```

### Phase 5b TodoWrite Template

```
[LUPIN] Create dedicated FastAPI router for {agent_name}
[LUPIN] Register router in main.py
[LUPIN] Verify POST endpoint returns job_id
[LUPIN] Create live pipeline test (test_{agent_name}_live_pipeline.py)
[LUPIN] Run live pipeline test (all scenarios pass)
[LUPIN] Create Q&A script (if interactive)
[LUPIN] Run proxy integration test (if interactive)
```

### Reference

For inline test templates and the `LivePipelineTestBase` / `InteractiveSmokeTest` API, see
the **agentic-voice-workflow** SKILL.md or the test infrastructure files:

- `src/tests/smoke/utilities/live_pipeline_base.py` — Base class
- `src/tests/smoke/utilities/interactive_smoke_test.py` — Interactive variant
- `src/tests/smoke/test_calculator_live_pipeline.py` — Non-interactive reference (6 scenarios)
- `src/tests/smoke/test_proxy_integration.py` — Interactive reference (12 scenarios)
- `src/docs/automated-interactive-testing.md` — Comprehensive guide

---

## Phase 6: LLM Client Integration

### Overview

The LLM client is the bridge between your orchestrator and the Claude API. It handles model
routing, retry logic, web search tool integration, and per-call cost tracking.

**Reference**: `src/cosa/agents/deep_research/api_client.py` (685 lines)

### api_client.py

```python
#!/usr/bin/env python3
"""
LLM API Client for {Agent Display Name}.

Handles model routing, retry logic, and cost tracking integration.
"""

import asyncio
import os
from typing import Optional, Any

import anthropic

import cosa.utils.util as cu

from .config import {AgentName}Config


# =============================================================================
# API Key Firewall Constants
# =============================================================================

ENV_VAR_NAME  = "ANTHROPIC_API_KEY_FIREWALLED"
KEY_FILE_NAME = "anthropic-api-key-firewalled"


class {AgentName}APIClient:
    """
    LLM API client for {agent_name}.

    Requires:
        - Valid API key available via env var or local file
        - anthropic package installed

    Ensures:
        - All API calls use the firewalled key (not Claude Code's key)
        - Cost tracking is updated after every call
        - Rate limits are respected with proactive delays
    """

    def __init__(
        self,
        config: Optional[ {AgentName}Config ] = None,
        cost_tracker = None,
        rate_limiter = None,
        api_key: Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ):
        self.config       = config or {AgentName}Config()
        self.cost_tracker = cost_tracker
        self.rate_limiter = rate_limiter
        self.debug        = debug
        self.verbose      = verbose

        # Load API key with firewall pattern
        self.api_key = self._load_api_key( api_key )
        self._client = anthropic.AsyncAnthropic( api_key=self.api_key )

    def _load_api_key( self, api_key=None ):
        """Load API key with three-tier priority (see Phase 0)."""
        if api_key:
            return api_key

        env_key = os.environ.get( ENV_VAR_NAME )
        if env_key:
            if self.debug: print( f"Using API key from {ENV_VAR_NAME}" )
            return env_key

        try:
            file_key = cu.get_api_key( KEY_FILE_NAME )
            if file_key:
                if self.debug: print( "Using API key from local file" )
                return file_key
        except FileNotFoundError:
            pass

        raise ValueError(
            f"No API key found. Set {ENV_VAR_NAME} or create "
            f"src/conf/keys/{KEY_FILE_NAME}"
        )

    # =================================================================
    # Model Routing — Lead Agent vs Subagent
    # =================================================================

    async def call_lead_agent(
        self,
        system_prompt: str,
        user_message: str,
        call_type: str = "lead",
        use_web_search: bool = False
    ) -> dict:
        """
        Call the lead model (typically Opus) for primary reasoning.

        Args:
            system_prompt: System-level instructions
            user_message: The user's query or task
            call_type: Label for cost tracking
            use_web_search: Enable web search tool

        Returns:
            dict with keys: content, input_tokens, output_tokens, model
        """
        return await self._call_api(
            model          = self.config.lead_model,
            system_prompt  = system_prompt,
            user_message   = user_message,
            call_type      = call_type,
            use_web_search = use_web_search
        )

    async def call_subagent(
        self,
        system_prompt: str,
        user_message: str,
        call_type: str = "subagent",
        use_web_search: bool = False
    ) -> dict:
        """
        Call the subagent model (typically Sonnet) for supporting tasks.

        Args:
            system_prompt: System-level instructions
            user_message: The task for the subagent
            call_type: Label for cost tracking
            use_web_search: Enable web search tool

        Returns:
            dict with keys: content, input_tokens, output_tokens, model
        """
        return await self._call_api(
            model          = self.config.subagent_model,
            system_prompt  = system_prompt,
            user_message   = user_message,
            call_type      = call_type,
            use_web_search = use_web_search
        )

    # =================================================================
    # Core API Call with Retry and Cost Tracking
    # =================================================================

    async def _call_api(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        call_type: str = "general",
        use_web_search: bool = False,
        max_tokens: int = 16000
    ) -> dict:
        """
        Core API call with retry, rate limiting, and cost tracking.

        Requires:
            - self._client is initialized
            - model is a valid Claude model string

        Ensures:
            - Rate limiter consulted before call
            - Cost tracker updated after call
            - Retries with exponential backoff on transient errors
        """
        # Rate limit check (proactive delay BEFORE call)
        if self.rate_limiter:
            delay = await self.rate_limiter.wait_if_needed()
            if delay > 0 and self.debug:
                print( f"Rate limiter: waited {delay:.1f}s" )

        # Build request kwargs
        kwargs = {
            "model"      : model,
            "max_tokens" : max_tokens,
            "system"     : system_prompt,
            "messages"   : [ { "role": "user", "content": user_message } ],
        }

        # Add web search tool if requested
        if use_web_search:
            kwargs[ "tools" ] = [ { "type": "web_search_20250305" } ]

        # Execute with retry
        response = await self._call_with_retry(
            kwargs         = kwargs,
            use_web_search = use_web_search
        )

        # Extract response content
        content       = self._extract_content( response )
        input_tokens  = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        # Record cost
        if self.cost_tracker:
            self.cost_tracker.record_call(
                model         = model,
                input_tokens  = input_tokens,
                output_tokens = output_tokens,
                call_type     = call_type
            )

        # Record rate limit usage
        if self.rate_limiter:
            self.rate_limiter.record_usage(
                tokens    = input_tokens + output_tokens,
                call_type = call_type
            )

        return {
            "content"       : content,
            "input_tokens"  : input_tokens,
            "output_tokens" : output_tokens,
            "model"         : model,
        }

    async def _call_with_retry(
        self,
        kwargs: dict,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        use_web_search: bool = False
    ):
        """
        Retry API call with exponential backoff.

        Web search calls use longer delays (30s initial, 8 retries)
        because search rate limits are more aggressive.
        """
        if use_web_search:
            max_retries   = 8
            initial_delay = 30.0
            max_delay     = 300.0
        else:
            max_delay = 60.0

        delay = initial_delay

        for attempt in range( max_retries + 1 ):
            try:
                return await self._client.messages.create( **kwargs )

            except anthropic.RateLimitError as e:
                if attempt == max_retries:
                    raise
                if self.debug: print( f"Rate limited, retrying in {delay:.0f}s (attempt {attempt + 1})" )
                await asyncio.sleep( delay )
                delay = min( delay * 2, max_delay )

            except anthropic.APIStatusError as e:
                if e.status_code >= 500 and attempt < max_retries:
                    if self.debug: print( f"Server error {e.status_code}, retrying in {delay:.0f}s" )
                    await asyncio.sleep( delay )
                    delay = min( delay * 2, max_delay )
                else:
                    raise

    def _extract_content( self, response ) -> str:
        """Extract text content from API response, handling tool results."""
        parts = []
        for block in response.content:
            if hasattr( block, "text" ):
                parts.append( block.text )
        return "\n".join( parts )


def quick_smoke_test():
    """Quick smoke test for {AgentName}APIClient."""
    import cosa.utils.util as cu

    cu.print_banner( "{AgentName}APIClient Smoke Test", prepend_nl=True )

    try:
        print( "1. Testing API key loading..." )
        # This will fail if no key is available — that's expected in CI
        try:
            client = {AgentName}APIClient( debug=True )
            print( f"   ✓ API key loaded ({ENV_VAR_NAME} or local file)" )
        except ValueError as e:
            print( f"   ⚠ No API key available (expected in CI): {e}" )
            print( "   ✓ Key loading logic works correctly" )

        print( "2. Testing model routing methods exist..." )
        assert hasattr( {AgentName}APIClient, "call_lead_agent" )
        assert hasattr( {AgentName}APIClient, "call_subagent" )
        print( "   ✓ Lead and subagent methods available" )

        print( "\\n✓ API client smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

### Config Additions for Phase 6

Add these fields to your `config.py`:

```python
@dataclass
class {AgentName}Config:
    # ... existing fields ...

    # === Model Routing (Phase 6) ===
    lead_model    : str = "claude-opus-4-20250514"      # Primary reasoning
    subagent_model: str = "claude-sonnet-4-20250514"    # Supporting tasks
    max_tokens    : int = 16000
```

> **Note on model strings**: The hardcoded model names above are **examples only**. In the
> actual codebase, model names are loaded from `lupin-app.ini` via `ConfigurationManager` (see
> Phase 0). The config supports multiple providers and uses a `Provider/model-name` format.
> Always load model names from config rather than hardcoding them in production code.

### Phase 6 Smoke Test Checklist

```
[ ] api_client.py created with API key firewall
[ ] Lead agent and subagent model routing works
[ ] Retry logic handles RateLimitError and 5xx errors
[ ] Cost tracker integration records calls (if cost_tracker provided)
[ ] python -m cosa.agents.{agent_name}.api_client (smoke test)
```

### Phase 6 TodoWrite Template

```
[LUPIN] Create {agent_name}/api_client.py with firewalled key loading
[LUPIN] Add lead_model and subagent_model to config.py
[LUPIN] Implement retry logic with exponential backoff
[LUPIN] Wire cost tracker and rate limiter integration
[LUPIN] Run smoke tests for api_client.py
```

---

## Phase 7: Cost Tracking

### Overview

Cost tracking prevents runaway API bills by recording per-call costs and enforcing budget limits.
Thread-safe for parallel subagent execution.

**Reference**: `src/cosa/agents/deep_research/cost_tracker.py` (473 lines)

### cost_tracker.py

```python
#!/usr/bin/env python3
"""
Cost Tracker for {Agent Display Name}.

Tracks per-call API costs with budget enforcement.
Thread-safe for parallel subagent execution.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


# =============================================================================
# Model Pricing (per 1M tokens, as of 2026-02)
# =============================================================================

class ModelTier( Enum ):
    """Supported model tiers with pricing."""
    OPUS_4   = "opus-4"
    SONNET_4 = "sonnet-4"
    HAIKU_4  = "haiku-4"


# Pricing per 1M tokens (input, output)
MODEL_PRICING = {
    ModelTier.OPUS_4   : { "input": 15.00, "output": 75.00 },
    ModelTier.SONNET_4 : { "input":  3.00, "output": 15.00 },
    ModelTier.HAIKU_4  : { "input":  0.80, "output":  4.00 },
}

# Cache token multipliers
CACHE_CREATION_MULTIPLIER = 1.25   # 25% more than base input
CACHE_READ_MULTIPLIER     = 0.10   # 90% discount on cached reads

# Model string → tier mapping
MODEL_TO_TIER = {
    "claude-opus-4-20250514"   : ModelTier.OPUS_4,
    "claude-sonnet-4-20250514" : ModelTier.SONNET_4,
    "claude-haiku-4-20250514"  : ModelTier.HAIKU_4,
}


@dataclass
class CostRecord:
    """Single API call cost record."""
    timestamp     : str
    model         : str
    tier          : ModelTier
    input_tokens  : int
    output_tokens : int
    cost_usd      : float
    call_type     : str


class BudgetExceededError( Exception ):
    """Raised when a call would exceed the configured budget limit."""
    pass


class {AgentName}CostTracker:
    """
    Track API costs with optional budget enforcement.

    Requires:
        - Model strings must be in MODEL_TO_TIER mapping

    Ensures:
        - All cost mutations are thread-safe
        - BudgetExceededError raised BEFORE the call that would exceed budget
        - Cost summary available at any time
    """

    def __init__( self, budget_limit_usd: Optional[ float ] = None, debug: bool = False ):
        self.budget_limit_usd = budget_limit_usd
        self.debug            = debug
        self._records: List[ CostRecord ] = []
        self._lock = threading.Lock()

    def record_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        call_type: str = "general",
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0
    ) -> float:
        """
        Record an API call and return its cost.

        Requires:
            - model is a recognized model string
            - token counts are non-negative

        Ensures:
            - Cost is calculated and recorded atomically
            - BudgetExceededError raised if budget would be exceeded

        Raises:
            - BudgetExceededError if adding this call exceeds budget
            - KeyError if model string is not recognized
        """
        tier    = MODEL_TO_TIER[ model ]
        pricing = MODEL_PRICING[ tier ]

        # Calculate cost
        input_cost  = ( input_tokens / 1_000_000 ) * pricing[ "input" ]
        output_cost = ( output_tokens / 1_000_000 ) * pricing[ "output" ]
        cache_cost  = (
            ( cache_creation_tokens / 1_000_000 ) * pricing[ "input" ] * CACHE_CREATION_MULTIPLIER +
            ( cache_read_tokens / 1_000_000 ) * pricing[ "input" ] * CACHE_READ_MULTIPLIER
        )
        total_cost = input_cost + output_cost + cache_cost

        record = CostRecord(
            timestamp     = datetime.now().isoformat(),
            model         = model,
            tier          = tier,
            input_tokens  = input_tokens,
            output_tokens = output_tokens,
            cost_usd      = total_cost,
            call_type     = call_type,
        )

        with self._lock:
            # Budget check BEFORE recording
            if self.budget_limit_usd is not None:
                current_total = sum( r.cost_usd for r in self._records )
                if current_total + total_cost > self.budget_limit_usd:
                    raise BudgetExceededError(
                        f"Budget limit ${self.budget_limit_usd:.2f} would be exceeded. "
                        f"Current: ${current_total:.4f}, This call: ${total_cost:.4f}"
                    )
            self._records.append( record )

        if self.debug:
            print( f"[Cost] {call_type}: ${total_cost:.4f} ({input_tokens}in/{output_tokens}out)" )

        return total_cost

    @property
    def total_cost_usd( self ) -> float:
        """Current total cost across all recorded calls."""
        with self._lock:
            return sum( r.cost_usd for r in self._records )

    @property
    def total_calls( self ) -> int:
        """Total number of API calls recorded."""
        with self._lock:
            return len( self._records )

    def get_summary( self ) -> dict:
        """
        Get a breakdown of costs by call type.

        Returns:
            dict with keys: total_cost_usd, total_calls, by_call_type, by_model
        """
        with self._lock:
            by_type  = {}
            by_model = {}

            for r in self._records:
                # Group by call type
                if r.call_type not in by_type:
                    by_type[ r.call_type ] = { "calls": 0, "cost_usd": 0.0 }
                by_type[ r.call_type ][ "calls" ]    += 1
                by_type[ r.call_type ][ "cost_usd" ] += r.cost_usd

                # Group by model tier
                tier_name = r.tier.value
                if tier_name not in by_model:
                    by_model[ tier_name ] = { "calls": 0, "cost_usd": 0.0 }
                by_model[ tier_name ][ "calls" ]    += 1
                by_model[ tier_name ][ "cost_usd" ] += r.cost_usd

            return {
                "total_cost_usd" : sum( r.cost_usd for r in self._records ),
                "total_calls"    : len( self._records ),
                "by_call_type"   : by_type,
                "by_model"       : by_model,
            }

    def format_summary( self ) -> str:
        """Format cost summary as human-readable string."""
        summary = self.get_summary()
        lines   = [ f"Total: ${summary[ 'total_cost_usd' ]:.4f} ({summary[ 'total_calls' ]} calls)" ]

        for call_type, data in summary[ "by_call_type" ].items():
            lines.append( f"  {call_type}: ${data[ 'cost_usd' ]:.4f} ({data[ 'calls' ]} calls)" )

        return "\n".join( lines )


def quick_smoke_test():
    """Quick smoke test for {AgentName}CostTracker."""
    import cosa.utils.util as cu

    cu.print_banner( "{AgentName}CostTracker Smoke Test", prepend_nl=True )

    try:
        print( "1. Testing cost calculation..." )
        tracker = {AgentName}CostTracker( budget_limit_usd=1.00, debug=True )
        cost = tracker.record_call(
            model         = "claude-sonnet-4-20250514",
            input_tokens  = 1000,
            output_tokens = 500,
            call_type     = "test"
        )
        assert cost > 0
        print( f"   ✓ Cost recorded: ${cost:.6f}" )

        print( "2. Testing budget enforcement..." )
        try:
            # Try to record a massive call that exceeds budget
            tracker.record_call(
                model         = "claude-opus-4-20250514",
                input_tokens  = 1_000_000,
                output_tokens = 1_000_000,
                call_type     = "budget_test"
            )
            print( "   ✗ Should have raised BudgetExceededError" )
        except BudgetExceededError:
            print( "   ✓ BudgetExceededError raised correctly" )

        print( "3. Testing summary..." )
        summary = tracker.get_summary()
        assert summary[ "total_calls" ] == 1  # Only the first call succeeded
        print( f"   ✓ Summary: {tracker.format_summary()}" )

        print( "\\n✓ CostTracker smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

### Phase 7 Smoke Test Checklist

```
[ ] cost_tracker.py created with ModelTier and pricing
[ ] Budget enforcement raises BudgetExceededError before exceeding limit
[ ] Thread-safe with threading.Lock
[ ] Summary reports by call type and model tier
[ ] python -m cosa.agents.{agent_name}.cost_tracker (smoke test)
```

### Phase 7 TodoWrite Template

```
[LUPIN] Create {agent_name}/cost_tracker.py with model pricing
[LUPIN] Add budget_limit_usd to config.py
[LUPIN] Wire cost tracker into api_client.py
[LUPIN] Verify thread safety with parallel call simulation
[LUPIN] Run smoke tests for cost_tracker.py
```

---

## Phase 8: Rate Limiting

### Overview

Rate limiting prevents API throttling by tracking token usage in a sliding window and inserting
proactive delays **before** calls, not after. This keeps throughput high while avoiding 429 errors.

**Reference**: `src/cosa/agents/deep_research/rate_limiter.py` (468 lines)

### rate_limiter.py

```python
#!/usr/bin/env python3
"""
Rate Limiter for {Agent Display Name}.

Sliding-window token tracking with proactive delay calculation.
Notifies user when delays are needed so they know the job hasn't stalled.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable


@dataclass
class TokenRecord:
    """Single token usage record within the sliding window."""
    timestamp : float
    tokens    : int
    call_type : str


class {AgentName}RateLimiter:
    """
    Sliding-window rate limiter with proactive delays.

    Requires:
        - tokens_per_minute > 0
        - window_seconds > 0

    Ensures:
        - wait_if_needed() delays BEFORE the call (not after)
        - User is notified when delay exceeds notify_threshold
        - Old records are cleaned up automatically
    """

    def __init__(
        self,
        tokens_per_minute: int = 80_000,
        window_seconds: float = 60.0,
        notify_threshold: float = 5.0,
        notify_callback: Optional[ Callable[ [ str ], Awaitable[ None ] ] ] = None,
        debug: bool = False
    ):
        self.tokens_per_minute = tokens_per_minute
        self.window_seconds    = window_seconds
        self.notify_threshold  = notify_threshold
        self.notify_callback   = notify_callback
        self.debug             = debug

        self._records: deque[ TokenRecord ] = deque()

    async def wait_if_needed( self ) -> float:
        """
        Check current usage and wait if approaching the limit.

        Returns:
            float: Number of seconds waited (0.0 if no wait needed)
        """
        now = time.monotonic()
        self._cleanup_old_records( now )

        tokens_in_window = sum( r.tokens for r in self._records )
        utilization      = tokens_in_window / self.tokens_per_minute

        if utilization < 0.8:
            return 0.0

        # Calculate delay: how long until enough tokens expire
        delay = self._calculate_delay( now, tokens_in_window )

        if delay > 0:
            if self.debug:
                print( f"[RateLimiter] {tokens_in_window:,} tokens in window, waiting {delay:.1f}s" )

            # Notify user if delay is significant
            if self.notify_callback and delay > self.notify_threshold:
                await self.notify_callback(
                    f"Rate limit pause: {tokens_in_window:,} tokens used in last "
                    f"{self.window_seconds:.0f}s. Waiting {delay:.0f}s..."
                )

            await asyncio.sleep( delay )

        return delay

    def record_usage( self, tokens: int, call_type: str = "general" ) -> None:
        """Record token usage after an API call."""
        self._records.append( TokenRecord(
            timestamp = time.monotonic(),
            tokens    = tokens,
            call_type = call_type
        ) )

    def get_tokens_in_window( self ) -> int:
        """Get current token count in the sliding window."""
        self._cleanup_old_records( time.monotonic() )
        return sum( r.tokens for r in self._records )

    def _calculate_delay( self, now: float, tokens_in_window: int ) -> float:
        """Calculate how long to wait for tokens to expire from window."""
        if tokens_in_window < self.tokens_per_minute:
            return 0.0

        # Find oldest record and calculate when it expires
        if self._records:
            oldest      = self._records[ 0 ].timestamp
            time_to_expire = ( oldest + self.window_seconds ) - now
            return max( 0.0, time_to_expire + 1.0 )  # +1s safety margin

        return 0.0

    def _cleanup_old_records( self, now: float ) -> None:
        """Remove records older than the sliding window."""
        cutoff = now - self.window_seconds
        while self._records and self._records[ 0 ].timestamp < cutoff:
            self._records.popleft()

    def get_status( self ) -> dict:
        """Get current rate limiter status for monitoring."""
        now = time.monotonic()
        self._cleanup_old_records( now )
        tokens = sum( r.tokens for r in self._records )
        return {
            "tokens_in_window"  : tokens,
            "tokens_per_minute" : self.tokens_per_minute,
            "utilization_pct"   : ( tokens / self.tokens_per_minute ) * 100,
            "records_count"     : len( self._records ),
        }


def quick_smoke_test():
    """Quick smoke test for {AgentName}RateLimiter."""
    import cosa.utils.util as cu

    cu.print_banner( "{AgentName}RateLimiter Smoke Test", prepend_nl=True )

    try:
        print( "1. Testing instantiation..." )
        limiter = {AgentName}RateLimiter( tokens_per_minute=1000, debug=True )
        print( "   ✓ Rate limiter created" )

        print( "2. Testing record_usage..." )
        limiter.record_usage( 500, "test" )
        assert limiter.get_tokens_in_window() == 500
        print( f"   ✓ Recorded 500 tokens, window: {limiter.get_tokens_in_window()}" )

        print( "3. Testing status..." )
        status = limiter.get_status()
        assert status[ "utilization_pct" ] == 50.0
        print( f"   ✓ Utilization: {status[ 'utilization_pct' ]:.0f}%" )

        print( "4. Testing wait_if_needed (no delay expected)..." )
        delay = asyncio.run( limiter.wait_if_needed() )
        print( f"   ✓ Delay: {delay:.1f}s (expected 0.0)" )

        print( "\\n✓ RateLimiter smoke test completed successfully" )

    except Exception as e:
        print( f"\\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
```

### Phase 8 TodoWrite Template

```
[LUPIN] Create {agent_name}/rate_limiter.py with sliding window
[LUPIN] Wire rate limiter into api_client.py
[LUPIN] Add voice notification callback for long delays
[LUPIN] Run smoke tests for rate_limiter.py
```

---

## Phase 9: External Service Integration Patterns

### Overview

Many agentic jobs interact with external services beyond the Claude API: TTS providers, audio
processing libraries, file storage, databases. This phase documents common integration patterns.

**Reference**: `src/cosa/agents/podcast_generator/tts_client.py` (754 lines),
`src/cosa/agents/podcast_generator/audio_stitcher.py` (405 lines)

### Pattern: WebSocket Streaming Client

For services that use WebSocket streaming (e.g., ElevenLabs TTS):

```python
class StreamingServiceClient:
    """
    WebSocket-based streaming client pattern.

    Requires:
        - websockets package installed
        - Valid API credentials for the service

    Ensures:
        - Connection established with timeout
        - Data streamed in chunks with progress callbacks
        - Clean connection teardown on error
    """

    def __init__(
        self,
        api_key: str,
        endpoint_url: str,
        progress_callback = None,
        debug: bool = False
    ):
        self.api_key           = api_key
        self.endpoint_url      = endpoint_url
        self.progress_callback = progress_callback
        self.debug             = debug

    async def stream( self, input_data: str ) -> bytes:
        """
        Stream data through the WebSocket connection.

        Args:
            input_data: The data to send to the service

        Returns:
            bytes: Collected response data
        """
        import websockets

        collected = bytearray()

        async with websockets.connect(
            self.endpoint_url,
            extra_headers={ "xi-api-key": self.api_key },
            ping_interval=30
        ) as ws:

            # Send input
            await ws.send( input_data )

            # Collect streamed response
            async for message in ws:
                if isinstance( message, bytes ):
                    collected.extend( message )
                    if self.progress_callback:
                        await self.progress_callback( len( collected ) )

        return bytes( collected )
```

### Pattern: Audio Processing Pipeline

For agents that produce audio output:

```python
class AudioPipeline:
    """
    Audio processing pipeline for combining segments.

    Pattern from podcast_generator/audio_stitcher.py:
    PCM chunks → AudioSegment → concatenate with silence → export MP3
    """

    def __init__( self, output_format="mp3", bitrate="192k" ):
        self.output_format = output_format
        self.bitrate       = bitrate

    def stitch_segments(
        self,
        audio_segments: list,
        silence_ms: int = 500,
        output_path: str = "output.mp3"
    ) -> str:
        """
        Concatenate audio segments with silence gaps.

        Args:
            audio_segments: List of AudioSegment objects
            silence_ms: Milliseconds of silence between segments
            output_path: Where to write the final file

        Returns:
            str: Path to the output file
        """
        from pydub import AudioSegment

        silence  = AudioSegment.silent( duration=silence_ms )
        combined = AudioSegment.empty()

        for i, segment in enumerate( audio_segments ):
            combined += segment
            if i < len( audio_segments ) - 1:
                combined += silence

        combined.export( output_path, format=self.output_format, bitrate=self.bitrate )
        return output_path
```

### Pattern: Service Response Caching

For expensive external calls that may be repeated:

```python
import hashlib
import json
import os

import cosa.utils.util as cu


class ServiceCache:
    """
    File-based cache for expensive external service responses.

    Requires:
        - cache_dir exists or can be created

    Ensures:
        - Cache key is deterministic hash of input
        - Cache hits avoid redundant API calls
        - Cache can be cleared without side effects
    """

    def __init__( self, cache_dir: str, debug: bool = False ):
        self.cache_dir = cu.get_project_root() + cache_dir
        self.debug     = debug
        os.makedirs( self.cache_dir, exist_ok=True )

    def _make_key( self, input_data: str ) -> str:
        """Generate cache key from input data."""
        return hashlib.sha256( input_data.encode() ).hexdigest()[ :16 ]

    def get( self, input_data: str ):
        """Return cached result or None."""
        key  = self._make_key( input_data )
        path = os.path.join( self.cache_dir, f"{key}.json" )

        if os.path.exists( path ):
            if self.debug: print( f"[Cache] HIT: {key}" )
            with open( path, "r" ) as f:
                return json.load( f )

        if self.debug: print( f"[Cache] MISS: {key}" )
        return None

    def put( self, input_data: str, result: dict ) -> None:
        """Store result in cache."""
        key  = self._make_key( input_data )
        path = os.path.join( self.cache_dir, f"{key}.json" )

        with open( path, "w" ) as f:
            json.dump( result, f, indent=2 )

        if self.debug: print( f"[Cache] STORED: {key}" )
```

### Phase 9 TodoWrite Template

```
[LUPIN] Identify external services needed by agent
[LUPIN] Create service client(s) following streaming/caching patterns
[LUPIN] Add mock versions of service clients for testing
[LUPIN] Wire service clients into orchestrator
[LUPIN] Run smoke tests for service integrations
```

---

## Phase 10: Advanced Orchestration Patterns

### Overview

Once individual agents work, you may want to compose them into multi-stage pipelines or add
sophisticated narrowing/refinement loops. This phase covers patterns beyond single-agent execution.

**Reference**: `src/cosa/agents/deep_research_to_podcast/agent.py` (529 lines),
`src/cosa/agents/deep_research/narrowing_harness.py` (696 lines)

### Pattern: Chained Agents (Pipeline)

Compose two or more existing agents into a sequential pipeline:

```python
from enum import Enum
from typing import Optional


class PipelineState( Enum ):
    """State machine for chained agent execution."""
    INITIALIZED            = "initialized"
    RUNNING_STAGE_1        = "running_stage_1"
    STAGE_1_DONE           = "stage_1_done"
    RUNNING_STAGE_2        = "running_stage_2"
    COMPLETED              = "completed"
    CANCELLED              = "cancelled"
    FAILED                 = "failed"


class ChainedAgent:
    """
    Sequential pipeline composing multiple agents.

    Pattern from deep_research_to_podcast/agent.py:
    1. Run Agent A → produce intermediate artifact
    2. Feed artifact to Agent B → produce final output
    3. Track combined costs and state across both agents

    Requires:
        - Both sub-agents are independently functional
        - Intermediate artifact format is compatible

    Ensures:
        - State machine tracks pipeline progress
        - Combined cost is sum of both agents
        - Cancellation at any stage is clean
    """

    def __init__(
        self,
        input_value: str,
        agent_a_config = None,
        agent_b_config = None,
        cli_mode: bool = False,
        debug: bool = False
    ):
        self.input_value    = input_value
        self.agent_a_config = agent_a_config
        self.agent_b_config = agent_b_config
        self.cli_mode       = cli_mode
        self.debug          = debug
        self.state          = PipelineState.INITIALIZED

    async def run( self ) -> dict:
        """Execute the full pipeline."""
        try:
            # Stage 1
            self.state    = PipelineState.RUNNING_STAGE_1
            stage_1_result = await self._run_stage_1()

            if stage_1_result.get( "cancelled" ):
                self.state = PipelineState.CANCELLED
                return { "state": self.state.value, "cancelled": True }

            self.state = PipelineState.STAGE_1_DONE

            # Stage 2 — feed Stage 1 output as input
            self.state    = PipelineState.RUNNING_STAGE_2
            stage_2_result = await self._run_stage_2( stage_1_result )

            self.state = PipelineState.COMPLETED
            return {
                "state"          : self.state.value,
                "stage_1_result" : stage_1_result,
                "stage_2_result" : stage_2_result,
            }

        except Exception as e:
            self.state = PipelineState.FAILED
            raise

    async def _run_stage_1( self ) -> dict:
        """Override with Agent A execution."""
        raise NotImplementedError( "Implement _run_stage_1()" )

    async def _run_stage_2( self, stage_1_output: dict ) -> dict:
        """Override with Agent B execution."""
        raise NotImplementedError( "Implement _run_stage_2()" )
```

### Pattern: Progressive Narrowing (Interactive Refinement)

For agents that iteratively refine results with user feedback:

```python
class NarrowingHarness:
    """
    Progressive narrowing with voice-first interaction.

    Pattern from deep_research/narrowing_harness.py:
    1. Generate broad set of candidates (e.g., themes, topics)
    2. Present to user for selection (voice or CLI)
    3. Refine based on selection
    4. Repeat until focused enough

    Stages: Broad → Clustered → Selected → Refined → Final
    """

    def __init__( self, voice_io, auto_approve: bool = False, debug: bool = False ):
        self.voice_io     = voice_io
        self.auto_approve = auto_approve
        self.debug        = debug

    async def narrow( self, candidates: list, stages: int = 3 ) -> list:
        """
        Iteratively narrow candidates through user interaction.

        Args:
            candidates: Initial broad set of options
            stages: Number of narrowing iterations

        Returns:
            list: Final narrowed selection
        """
        current = candidates

        for stage in range( stages ):
            if self.debug: print( f"[Narrowing] Stage {stage + 1}: {len( current )} candidates" )

            if self.auto_approve:
                # Auto-select top half
                current = current[ :len( current ) // 2 ] or current[ :1 ]
            else:
                # Present to user for selection
                selection = await self.voice_io.choose(
                    f"Stage {stage + 1}: Select options to keep",
                    [ { "label": c, "description": "" } for c in current ],
                    timeout=120
                )
                current = [ c for c in current if c in selection ]

        return current
```

### Pattern: Parallel Subagent Execution

For agents that can run multiple LLM calls concurrently:

```python
async def run_parallel_subagents(
    api_client,
    tasks: list,
    max_concurrent: int = 3,
    voice_io = None
) -> list:
    """
    Execute multiple subagent calls in parallel with concurrency limit.

    Args:
        api_client: The LLM API client (must be thread-safe)
        tasks: List of (system_prompt, user_message, call_type) tuples
        max_concurrent: Maximum concurrent API calls
        voice_io: Optional notification interface

    Returns:
        list: Results in same order as input tasks
    """
    semaphore = asyncio.Semaphore( max_concurrent )

    async def _run_one( index, system_prompt, user_message, call_type ):
        async with semaphore:
            result = await api_client.call_subagent(
                system_prompt = system_prompt,
                user_message  = user_message,
                call_type     = call_type
            )
            if voice_io:
                await voice_io.notify(
                    f"Subagent {index + 1}/{len( tasks )} complete",
                    priority="low"
                )
            return result

    coros   = [ _run_one( i, sp, um, ct ) for i, ( sp, um, ct ) in enumerate( tasks ) ]
    results = await asyncio.gather( *coros, return_exceptions=True )

    # Re-raise first exception if any
    for r in results:
        if isinstance( r, Exception ):
            raise r

    return results
```

### Phase 10 TodoWrite Template

```
[LUPIN] Determine orchestration pattern needed (single, chained, narrowing, parallel)
[LUPIN] Implement chosen pattern following reference templates
[LUPIN] Add state machine tracking for multi-stage workflows
[LUPIN] Wire voice notifications into each stage transition
[LUPIN] Run smoke tests for orchestration logic
```

---

# Part III: VALIDATE — The Testing Ladder

## Overview: Fail Fast, Fail Cheap

The process of wiring up an agentic job from concept to voice-driven production is **long**.
Each testing surface catches different categories of bugs at different costs. The key insight:
**iterate on the cheapest surfaces first** before escalating to more expensive ones.

```
Surface 1: Unit + Smoke     FREE, <1s      ──► Logic bugs, import errors
Surface 2: Mock Endpoint    FREE, <1s      ──► API contracts, factory routing
Surface 3: UI Cards + LLM   $0.001, 1-3s  ──► LLM routing, prompt bugs
Surface 4: PEFT Training    $5-50, hours   ──► Model accuracy, data balance
Surface 5: Voice Pipeline   $0.01, 2-5s    ──► ASR quality, LORA classification
```

**The rule**: Don't move to Surface N+1 until Surface N passes. A bug caught at Surface 1
costs nothing. The same bug caught at Surface 4 costs GPU hours. The same bug caught at
Surface 5 (in production) costs user trust.

### Comparison Matrix

| Surface | Cost | Time | What's Exercised | What's Caught |
|---------|------|------|-----------------|---------------|
| 1: Unit + Smoke | FREE | <1s | Individual functions, imports | Logic bugs, schema errors, ID format |
| 2: Mock Endpoint | FREE | <1s | HTTP → expeditor → factory → queue | API contracts, routing errors |
| 3: UI Cards + LLM | ~$0.001/query | 1-3s | Full routing stack with real LLM | Prompt bugs, snapshot issues |
| 4: PEFT Training | $5-50 | GPU-hours | LORA model accuracy | Data imbalance, command confusion |
| 5: Voice Pipeline | ~$0.01/query | 2-5s | ASR → LORA → dispatch | Transcription errors, homophones |

---

## Surface 1: Unit Tests + Inline Smoke Tests (FREE, <1s)

The cheapest and fastest testing surface. Run on **every code change**.

### Inline Smoke Tests

Every module in your agent should have a `quick_smoke_test()` function:

```python
def quick_smoke_test():
    """Quick smoke test for {module_name}."""
    import cosa.utils.util as cu

    cu.print_banner( "{Module Name} Smoke Test", prepend_nl=True )

    try:
        # Test 1: Module imports work
        print( "1. Testing imports..." )
        from cosa.agents.{agent_name}.config import {AgentName}Config
        print( "   ✓ Imports successful" )

        # Test 2: Instantiation works
        print( "2. Testing instantiation..." )
        config = {AgentName}Config()
        assert config.model is not None
        print( f"   ✓ Config created: model={config.model}" )

        # Test 3: ID format validation
        print( "3. Testing ID format..." )
        from cosa.agents.{agent_name}.job import {AgentName}Job
        job = {AgentName}Job(
            input_value = "test",
            user_id     = "u1",
            user_email  = "t@t.com",
            session_id  = "s1"
        )
        assert job.id_hash.startswith( "{prefix}-" )
        print( f"   ✓ ID format correct: {job.id_hash}" )

        print( "\n✓ All smoke tests passed" )
        return True

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


# Dual entry point: pytest discovers test_smoke(), CLI runs quick_smoke_test()
def test_smoke():
    """Pytest wrapper for smoke test."""
    assert quick_smoke_test()


if __name__ == "__main__":
    import sys
    sys.exit( 0 if quick_smoke_test() else 1 )
```

**Catches**: Import errors, instantiation failures, ID format bugs, missing dependencies.

**Run**:
```bash
# Individual module
python -m cosa.agents.{agent_name}.config
python -m cosa.agents.{agent_name}.state
python -m cosa.agents.{agent_name}.orchestrator
python -m cosa.agents.{agent_name}.job

# All smoke tests via pytest
pytest src/tests/smoke/ -v
```

### Unit Tests

Unit tests use `pytest` with full mocking — no server, no API calls, no network.

**Location**: `src/tests/unit/test_{agent_name}.py`

```python
"""
Unit tests for {agent_name}.

Tests individual components with mocked dependencies.
No server, no API calls, no network access.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from cosa.agents.{agent_name}.config import {AgentName}Config
from cosa.agents.{agent_name}.state import OrchestratorState, create_initial_state
from cosa.agents.{agent_name}.job import {AgentName}Job


class Test{AgentName}Config:
    """Tests for {AgentName}Config dataclass."""

    def test_default_values( self ):
        config = {AgentName}Config()
        assert config.model == "claude-sonnet-4-20250514"
        assert config.max_iterations > 0
        assert config.timeout_seconds > 0

    def test_custom_values( self ):
        config = {AgentName}Config( model="claude-opus-4-20250514", max_iterations=5 )
        assert config.model == "claude-opus-4-20250514"
        assert config.max_iterations == 5


class Test{AgentName}State:
    """Tests for state machine and state creation."""

    def test_state_enum_values( self ):
        assert OrchestratorState.COMPLETED.value == "completed"
        assert OrchestratorState.FAILED.value == "failed"

    def test_create_initial_state( self ):
        state = create_initial_state( "test input" )
        assert state[ "original_input" ] == "test input"
        assert state[ "current_state" ] == "initializing"
        assert state[ "iterations" ] == 0

    def test_all_states_have_values( self ):
        for state in OrchestratorState:
            assert isinstance( state.value, str )
            assert len( state.value ) > 0


class Test{AgentName}Job:
    """Tests for {AgentName}Job queue wrapper."""

    def _make_job( self, **kwargs ):
        defaults = {
            "input_value" : "test query",
            "user_id"     : "user123",
            "user_email"  : "test@test.com",
            "session_id"  : "session456",
            "debug"       : True,
        }
        defaults.update( kwargs )
        return {AgentName}Job( **defaults )

    def test_job_creation( self ):
        job = self._make_job()
        assert job.input_value == "test query"
        assert job.status is not None

    def test_job_id_prefix( self ):
        job = self._make_job()
        assert job.id_hash.startswith( "{prefix}-" )

    def test_job_type_constant( self ):
        assert {AgentName}Job.JOB_TYPE == "{agent_name}"
        assert {AgentName}Job.JOB_PREFIX == "{prefix}"

    def test_last_question_asked_truncation( self ):
        long_input = "x" * 100
        job = self._make_job( input_value=long_input )
        assert len( job.last_question_asked ) < 100
        assert "..." in job.last_question_asked

    @patch( "cosa.agents.{agent_name}.job.asyncio.run" )
    def test_dry_run_mode( self, mock_asyncio_run ):
        mock_asyncio_run.return_value = "Dry run complete."
        job = self._make_job( dry_run=True )
        result = job.do_all()
        assert "dry run" in result.lower() or "Dry run" in result
```

**Catches**: Logic bugs, XML schema mismatches, factory routing errors, state machine issues.

**Run**:
```bash
pytest src/tests/unit/test_{agent_name}.py -v
```

### Surface 1 Checklist

```
[ ] Every module has quick_smoke_test() with dual entry point
[ ] Unit test file exists at src/tests/unit/test_{agent_name}.py
[ ] ≥1 test per public class/function
[ ] All tests pass: pytest src/tests/unit/test_{agent_name}.py -v
[ ] All smoke tests pass: python -m cosa.agents.{agent_name}.{module}
```

### Automated Notification Proxy Responses

If your agent uses the Runtime Argument Expediter (which sends notification questions to gather missing arguments), you will need a **Q&A script** for the Notification Proxy to auto-answer those questions during automated testing.

**See**: `src/conf/notification-proxy-scripts/README.md` for:
- Q&A script JSON format specification
- Step-by-step guide to create a script for your agent
- How to derive entries from your agent's `fallback_questions` in the agent registry
- Template file (`_template.json`) to copy and modify

---

## Surface 2: Mock Job Endpoint (FREE, <1s, server required)

Test the full HTTP → expeditor → factory → queue pipeline **without LLM calls**.

### What's Exercised

```
POST /api/mock-job/submit
  └── voice_command field triggers expeditor test mode
        └── Expeditor parses command → extracts args
              └── AgenticJobFactory creates job instance
                    └── Job pushed to RunningFifoQueue
                          └── Job executes in dry_run mode
```

### How to Test

```bash
# 1. Login and get token
TOKEN=$(curl -s -X POST http://localhost:7999/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "'$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL'", "password": "'$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD'"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['tokens']['access_token'])")

# 2. Submit mock job with voice command
curl -s -X POST http://localhost:7999/api/mock-job/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"voice_command": "research quantum computing"}' | python3 -m json.tool

# Expected response:
# {
#   "status": "queued",
#   "job_id": "dr-a1b2c3d4",
#   "queue_position": 1
# }

# 3. Poll for completion
curl -s http://localhost:7999/api/get-queue/done \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### Mock Job Endpoint Pattern

The mock job endpoint (`src/cosa/rest/routers/mock_job.py`) has two modes:

1. **Randomized mock**: Random iterations and sleep — tests queue mechanics
2. **Expeditor test**: `voice_command` field → tests the full routing pipeline

```python
# In your router, the voice_command branch:
if request_body.voice_command:
    return await _handle_expeditor_test(
        voice_command = request_body.voice_command,
        current_user  = current_user,
        todo_queue    = todo_queue
    )
```

**Catches**: API contract errors, expeditor parsing gaps, factory routing bugs, queue integration issues.

**Key difference from Surface 1**: Exercises the HTTP layer, authentication, and inter-module wiring.
Still FREE because `dry_run=True` prevents any LLM API calls.

### Surface 2 Checklist

```
[ ] Server running on localhost:7999
[ ] Mock job endpoint accepts voice_command field
[ ] Expeditor correctly parses your agent's commands
[ ] Factory creates correct job type for your command
[ ] Job appears in todo queue → runs → moves to done queue
[ ] Dry-run breadcrumb notifications fire
[ ] Job completes with $0.00 cost
```

---

## Surface 3: Notification UI Submission Cards ($0.001/query, 1-3s)

This surface tests **real LLM inference** through the production routing stack.

### What's New vs Surface 2

| Aspect | Surface 2 (Mock) | Surface 3 (UI Cards) |
|--------|------------------|----------------------|
| LLM calls | None (dry_run) | Real inference |
| Routing | Keyword matching | LLM-based router |
| Cost | $0.00 | ~$0.001 per query |
| Input method | curl + voice_command | Browser UI card or /api/push |
| Confirmation | None | UI confirmation dialog |

### Submission Card Pattern

Each agentic process gets its own **dedicated submission card** in the notification UI:

- **Deep Research card**: Query input + budget slider + language selector
- **Podcast Generator card**: Topic input + voice selection + duration
- **Research→Podcast card**: Combined flow — one card triggers both agents

These cards are also testable via the `/api/push` endpoint:

```bash
# Submit via /api/push — full production routing stack
curl -s -X POST http://localhost:7999/api/push \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "raw_text": "research quantum computing for beginners",
    "push_type": "agentic"
  }' | python3 -m json.tool
```

### What's Exercised

```
User input (text or voice transcription)
  └── Gist normalization (clean up input)
        └── Solution snapshot search (find matching agent)
              └── LLM router (classify intent → agent type)
                    └── Confirmation dialog (user approves)
                          └── Expeditor (extract arguments)
                                └── Factory → Queue → Execute
```

**Catches**: LLM routing failures, prompt template bugs, snapshot cache mismatches,
confirmation dialog issues, argument extraction errors.

### Creating a Submission Card

Each agent needs an HTML card in the notification UI and a JavaScript handler to submit jobs.

**1. HTML Card** — Add to `src/fastapi_app/static/html/notifications.html`:

```html
<div class="job-submit-card" id="{agent-name}-submit-card">
    <h4>🔧 {Agent Display Name}</h4>
    <div class="form-group" style="margin-bottom: 12px;">
        <label for="{agent-name}-input" style="display: block; font-size: 12px; margin-bottom: 4px; color: #666;">
            Input:
        </label>
        <div style="display: flex; gap: 8px; align-items: center;">
            <button type="button" id="{agent-name}-stt-button" class="stt-button"
                    title="Click to record (30s max, ESC to cancel)">🎤</button>
            <input type="text" id="{agent-name}-input"
                   placeholder="Enter your request..."
                   style="flex: 1; padding: 8px; border: 1px solid #ced4da; border-radius: 4px;" />
        </div>
    </div>
    <div style="margin-bottom: 12px;">
        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
            <input type="checkbox" id="{agent-name}-dry-run" checked />
            <span style="font-size: 13px;">🧪 Dry run (simulate only)</span>
        </label>
    </div>
    <button id="submit-{agent-name}-job" type="button"
            style="padding: 10px 20px; background: #28a745; color: white; border: none;
                   border-radius: 4px; cursor: pointer; font-weight: 500;">
        🚀 Submit Job
        <span id="{agent-name}-loading" class="loading" style="display: none;">
            <span class="spinner"></span>
        </span>
    </button>
    <div id="{agent-name}-submit-status"
         style="margin-top: 8px; font-size: 12px; color: #666;"></div>
</div>
```

**2. JavaScript Handler** — Add to `src/fastapi_app/static/js/notifications.js`:

Wire the submit button in `setupJobSubmitEventListeners()`:

```javascript
const submit{AgentName}Btn = document.getElementById( 'submit-{agent-name}-job' );
if ( submit{AgentName}Btn ) {
    submit{AgentName}Btn.addEventListener( 'click', () => {
        this.submit{AgentName}Job();
    });
}
```

Then add the submission method (follows the established fetch pattern):

```javascript
async submit{AgentName}Job() {
    const input      = document.getElementById( '{agent-name}-input' );
    const dryRun     = document.getElementById( '{agent-name}-dry-run' );
    const submitBtn  = document.getElementById( 'submit-{agent-name}-job' );
    const loading    = document.getElementById( '{agent-name}-loading' );
    const statusDiv  = document.getElementById( '{agent-name}-submit-status' );

    const query = input.value.trim();
    if ( !query ) {
        statusDiv.textContent = '⚠️ Please enter input.';
        statusDiv.style.color = '#dc3545';
        return;
    }

    try {
        submitBtn.disabled = true;
        loading.style.display = 'inline-block';
        statusDiv.textContent = 'Submitting...';

        await this.ensureValidToken();

        const response = await fetch( '/api/{agent-name}/submit', {
            method  : 'POST',
            headers : {
                'Authorization' : this.getAuthHeader(),
                'X-Session-ID'  : this.queueSessionId,
                'Content-Type'  : 'application/json'
            },
            body: JSON.stringify({ query: query, dry_run: dryRun.checked })
        });

        if ( !response.ok ) {
            const err = await response.json().catch( () => ({ detail: response.statusText }) );
            throw new Error( err.detail || `HTTP ${response.status}` );
        }

        const result = await response.json();
        statusDiv.textContent = `✓ Job submitted! ID: ${result.job_id}, Position: ${result.queue_position}`;
        statusDiv.style.color = '#28a745';
        input.value = '';

    } catch ( error ) {
        statusDiv.textContent = `✗ Error: ${error.message}`;
        statusDiv.style.color = '#dc3545';
    } finally {
        submitBtn.disabled = false;
        loading.style.display = 'none';
    }
}
```

**Key patterns**: Bearer token auth via `this.getAuthHeader()`, session ID header, loading
spinner toggle, color-coded status feedback (#28a745 = green success, #dc3545 = red error).

### Surface 3 Checklist

```
[ ] Submission card added to notifications.html
[ ] JS handler added to notifications.js (setupJobSubmitEventListeners + submit method)
[ ] Agent's submission card renders in notification UI
[ ] Text input correctly routes to your agent via LLM
[ ] /api/push endpoint correctly classifies your agent's commands
[ ] Confirmation dialog shows correct agent name and parameters
[ ] Full execution completes with expected artifacts
[ ] Cost is reasonable (~$0.001-$0.01 per test query)
```

---

## Surface 4: PEFT Training + XML Data Generation ($5-50, GPU-hrs)

**CRITICAL**: This surface MUST come before Surface 5 (voice routing). The LORA classifier
can't route to an agent it hasn't been trained on.

### Why This Surface Exists

The voice pipeline uses a **fine-tuned LORA model** to classify spoken commands into agent
types. When you add a new agentic job, you need to:

1. Create training templates for your agent's commands
2. Generate synthetic training data from those templates
3. Retrain the LORA model to recognize your new commands
4. Validate that the retrained model doesn't regress on existing agents

### Training Data Pipeline

```
Templates (human-written)
  └── Placeholder substitution (automated)
        └── Train/test split (automated)
              └── PEFT training (GPU)
                    └── Evaluation (automated)
```

### Step 1: Add to Agent Router Commands

Register your agent in `src/conf/training/agent-router-agentic-commands.json`:

```json
{
    "agent router go to {agent_name}": "/src/ephemera/prompts/data/synthetic-data-agent-routing-{agent_name}.txt"
}
```

The JSON structure maps each routing command directly to its template file path (relative to
project root). No metadata object — just command → template path.

**Actual file contents** (for reference):
```json
{
    "agent router go to deep research"      : "/src/ephemera/prompts/data/synthetic-data-agent-routing-deep-research.txt",
    "agent router go to podcast generator"   : "/src/ephemera/prompts/data/synthetic-data-agent-routing-podcast-generator.txt",
    "agent router go to research to podcast" : "/src/ephemera/prompts/data/synthetic-data-agent-routing-research-to-podcast.txt"
}
```

### Step 2: Create Training Templates

Create `src/ephemera/prompts/data/synthetic-data-agent-routing-{agent_name}.txt`:

```
# Templates for {agent_name} — one per line
# Use PLACEHOLDER_NAME for substitution points
# Aim for 65+ diverse templates

research SEARCH_TERMS
look up SEARCH_TERMS for me
do a deep dive on SEARCH_TERMS
investigate SEARCH_TERMS
find out about SEARCH_TERMS
can you research SEARCH_TERMS
I need research on SEARCH_TERMS
please look into SEARCH_TERMS
tell me about SEARCH_TERMS
give me a report on SEARCH_TERMS
# ... aim for 65+ templates with natural variation
```

**Template guidelines**:
- Write commands as a user would **speak** them (conversational, not formal)
- Include variations: polite ("please research"), direct ("research"), question ("can you research")
- Include filler words people actually say: "um", "hey", "so like"
- Avoid templates that could match other agents (test for confusion)
- Minimum 65 templates for reliable LORA classification

### Step 3: Generate Training Data

The XML coordinator generates training examples by substituting placeholders:

```bash
# Generate training data for all agents (including yours)
python -m cosa.training.xml_coordinator \
    --config src/conf/lupin-app.ini \
    --sample-size 2000 \
    --output-dir src/conf/training-data/generated/
```

**Reference**: `src/cosa/training/xml_coordinator.py` — `build_compound_vox_cmd_training_prompts()`

### Step 4: Train the LORA Model

```bash
# Run PEFT training
./src/scripts/run-agentic-intent-training.sh \
    --data-dir src/conf/training-data/generated/ \
    --output-dir src/conf/models/agentic-intent/ \
    --epochs 3 \
    --batch-size 8
```

**Reference**: `src/cosa/training/peft_trainer.py`, `src/scripts/run-agentic-intent-training.sh`

### Step 5: Evaluate

After training, verify:

```
[ ] New agent commands classified correctly (>95% accuracy)
[ ] Existing agent commands still classified correctly (no regression)
[ ] Confusion matrix shows clean separation between agent types
[ ] Edge cases tested: similar commands, ambiguous phrasing
```

### Surface 4 Checklist

```
[ ] Agent registered in agent-router-agentic-commands.json
[ ] 65+ training templates created
[ ] Training data generated via xml_coordinator
[ ] LORA model retrained with new agent's data
[ ] Accuracy >95% on new agent commands
[ ] No regression on existing agent commands (±1% tolerance)
[ ] Confusion matrix reviewed for overlap with similar agents
```

---

## Surface 5: Voice Routing — ASR → LORA → Queue ($0.01/query, 2-5s)

The full end-to-end voice pipeline. **Requires Surface 4** (LORA must be trained first).

### What's Exercised

```
Microphone input (user speaks)
  └── Whisper ASR (speech → text)
        └── LORA classifier (text → agent type)
              └── Expeditor (extract arguments)
                    └── Factory → Queue → Execute
                          └── Voice notifications back to user
```

### Voice-Specific Failure Modes

| Failure Mode | Example | Mitigation |
|-------------|---------|------------|
| ASR garbling | "research" → "re search" | Add garbled variants to templates |
| Homophones | "their/there/they're" | Test with spoken audio, not typed text |
| Filler words | "um, like, research stuff" | Include filler words in templates |
| Accent variation | Regional pronunciation | Train with diverse speakers |
| Background noise | Partial transcription | Test in realistic environments |
| Command confusion | "podcast about research" vs "research about podcasts" | Confusion matrix at Surface 4 |

### Testing Voice Routing

```bash
# Option A: Use the browser microphone button
# Navigate to the Lupin UI → click the microphone icon → speak your command

# Option B: Use a pre-recorded audio file
# (Requires whisper CLI or API endpoint for file-based ASR)

# Option C: Simulate ASR output by submitting transcription text
curl -s -X POST http://localhost:7999/api/push \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "raw_text": "um research quantum computing please",
    "push_type": "voice"
  }' | python3 -m json.tool
```

### Current Status

> **Note**: Full LORA runtime integration is pending. Voice commands currently fall back to
> Surface 3 (LLM-based routing via `/api/push`). Once LORA runtime is integrated, this
> surface becomes the true end-to-end voice test.

### Surface 5 Checklist

```
[ ] LORA model trained with your agent's templates (Surface 4 complete)
[ ] Spoken commands correctly transcribed by Whisper ASR
[ ] LORA classifier routes to correct agent type
[ ] Expeditor extracts arguments from transcribed text
[ ] Full pipeline: speak → transcribe → classify → execute → notify
[ ] Tested with 5+ different phrasings of the same intent
[ ] Tested with background noise and casual speech patterns
```

---

### Automated Pipeline Testing (Cross-Surface)

Lupin provides two base classes for automated live pipeline testing. Use these instead of
manual curl/UI submission for all new agents.

#### Class Hierarchy

| Class | Use When | Proxy Required |
|-------|----------|----------------|
| `LivePipelineTestBase` | Agent has no interactive questions | No |
| `InteractiveSmokeTest` | Agent asks expediter/CRUD questions | Yes (auto-launched) |

Both classes handle: authentication, session resolution, mode switching, submit-and-poll,
keyword validation, and tabular reporting.

#### Key Files

| File | Purpose |
|------|---------|
| `src/tests/smoke/utilities/live_pipeline_base.py` | Base class for submit-and-poll tests |
| `src/tests/smoke/utilities/interactive_smoke_test.py` | Adds proxy auto-launch for interactive agents |
| `src/tests/smoke/test_calculator_live_pipeline.py` | Reference: non-interactive (6 scenarios) |
| `src/tests/smoke/test_proxy_integration.py` | Reference: interactive (12 scenarios, 3 agent groups) |
| `src/conf/notification-proxy-scripts/_template.json` | Q&A script template for new agents |

#### Non-Interactive Template

For agents that do **not** ask interactive questions:

```python
from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase

SCENARIOS = [
    {
        "id"               : "SCENARIO_1",
        "query"            : "Your test query here",
        "expected_keywords" : [ "expected", "words" ],
    },
]

class MyAgentPipelineTest( LivePipelineTestBase ):
    TEST_NAME       = "My Agent Live Pipeline"
    SCENARIOS       = SCENARIOS
    DEFAULT_TIMEOUT = 120

    def get_mode_for_scenario( self, scenario ):
        return "my_agent"  # Or None for auto-route testing

if __name__ == "__main__":
    test    = MyAgentPipelineTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
```

#### Interactive Template

For agents that ask interactive questions via the Runtime Argument Expediter:

```python
from tests.smoke.utilities.interactive_smoke_test import InteractiveSmokeTest

class MyAgentInteractiveTest( InteractiveSmokeTest ):
    TEST_NAME      = "My Agent Interactive"
    SCENARIOS      = SCENARIOS
    PROXY_PROFILE  = "my_agent"
    DEFAULT_TIMEOUT = 180
```

Run with: `python src/tests/smoke/test_my_agent_live_pipeline.py --auto-proxy --no-confirm`

#### Running Commands

```bash
# Non-interactive agent — all scenarios
python src/tests/smoke/test_{agent_name}_live_pipeline.py

# Non-interactive — specific scenarios only
python src/tests/smoke/test_{agent_name}_live_pipeline.py -q 0,2,4

# Interactive agent — auto-launch proxy, disable similarity confirmation
python src/tests/smoke/test_{agent_name}_live_pipeline.py --auto-proxy --no-confirm

# Interactive — specific group only
python src/tests/smoke/test_proxy_integration.py --group {agent_name} --auto-proxy --no-confirm
```

#### Comprehensive Guide

See [`src/docs/automated-interactive-testing.md`](../docs/automated-interactive-testing.md)
for the full guide covering proxy architecture, Q&A scripts, strategy chain,
test profiles, and scenario authoring.

---

## Recommended Iteration Strategy

### Development Flow

```
On every code change:
  → Run Surface 1 (unit + smoke) .............. FREE, <1s
  → Run Surface 2 (mock endpoint) ............. FREE, <1s

After queue integration works:
  → Run Surface 3 (UI cards + LLM) ........... ~$0.01

When adding new agent to voice pipeline:
  → Run Surface 4 (PEFT training) ............ $5-50

Before branch merge to main:
  → Run Surface 5 (voice routing) ............ ~$0.10 total
```

### Cost Budget per Agent Development

| Phase | Estimated Cost | When |
|-------|---------------|------|
| Development (Surfaces 1-2) | $0 | Every code change |
| Routing validation (Surface 3) | $0.05-0.50 | 50-500 test queries |
| LORA training (Surface 4) | $5-50 | Once per new agent |
| Voice testing (Surface 5) | $0.10-1.00 | 10-100 spoken tests |
| **Total per new agent** | **$5-52** | |

---

## Adding a New Agentic Agent — Complete Checklist

This is the master checklist for taking a new agent from concept to voice-driven production.
Complete each step in order. Do not skip ahead.

```
═══════════════════════════════════════════════════════════════
  CONCEPT
═══════════════════════════════════════════════════════════════

[ ] Decision checklist passed (≥4 boxes checked)
[ ] Agent name, prefix, input/output types defined
[ ] State machine states identified
[ ] External dependencies cataloged

═══════════════════════════════════════════════════════════════
  BUILD
═══════════════════════════════════════════════════════════════

Phase 0: Pre-Flight
[ ] API key firewall configured
[ ] Config keys added to lupin-app.ini + splainer
[ ] Dependencies verified

Phase 1-2: Foundation
[ ] Directory structure created
[ ] config.py, state.py, orchestrator.py, __main__.py written
[ ] mock_clients.py written (if external services used)

Phase 3-4: Notifications
[ ] cosa_interface.py created
[ ] voice_io.py wrapper created
[ ] Notifications wired into orchestrator

Phase 5: Queue Integration
[ ] job.py with AgenticJobBase inheritance
[ ] do_all() → _execute() bridge pattern
[ ] Dry-run mode with breadcrumb notifications
[ ] Agent registered in agent_registry.py (AGENTIC_AGENTS dict)
[ ] Factory elif branch added in agentic_job_factory.py
[ ] Dedicated FastAPI router created and registered in main.py

Phase 5b: Router + Automated Testing
[ ] Dedicated FastAPI router created and registered in main.py
[ ] Live pipeline test created: test_{agent_name}_live_pipeline.py
[ ] Live pipeline test passes (all scenarios)
[ ] Q&A script created (if interactive)
[ ] Proxy integration test passes (if interactive)

Phase 6-10: Advanced (as needed)
[ ] LLM client with model routing (Phase 6)
[ ] Cost tracking with budget enforcement (Phase 7)
[ ] Rate limiting with proactive delays (Phase 8)
[ ] External service integrations (Phase 9)
[ ] Advanced orchestration patterns (Phase 10)

═══════════════════════════════════════════════════════════════
  VALIDATE — The Testing Ladder
═══════════════════════════════════════════════════════════════

Surface 1: Unit + Smoke (FREE)
[ ] Every module has quick_smoke_test()
[ ] Unit test file at src/tests/unit/test_{agent_name}.py
[ ] All tests pass

Surface 2: Mock Endpoint (FREE)
[ ] Mock endpoint creates job correctly
[ ] Dry-run executes with $0.00 cost
[ ] Job lifecycle: todo → run → done
[ ] Live pipeline test (submit-and-poll): test_{agent_name}_live_pipeline.py passes

Surface 3: UI Cards + LLM (~$0.001/query)
[ ] Submission card added to notifications.html + notifications.js
[ ] Text input routes to agent via LLM
[ ] Submission card works in notification UI
[ ] /api/push endpoint classifies correctly
[ ] Automated proxy test passes (if interactive): --auto-proxy --no-confirm

Surface 4: PEFT Training ($5-50)
[ ] Added to agent-router-agentic-commands.json
[ ] 65+ training templates created
[ ] Training data generated
[ ] LORA retrained, accuracy >95%, no regression

Surface 5: Voice Routing (~$0.01/query)
[ ] Spoken commands transcribed correctly
[ ] LORA routes to correct agent type
[ ] End-to-end voice pipeline works

═══════════════════════════════════════════════════════════════
  FINAL VERIFICATION
═══════════════════════════════════════════════════════════════

[ ] Automated verification: live pipeline test passes (all scenarios)
[ ] Manual verification (visual only): submit via UI, visually verify artifacts
[ ] (v0.1.6) Playwright E2E: submit via UI, verify job card + notification rendering
[ ] Notifications: start, progress, completion all fire
[ ] Error handling: simulate failure, verify urgent notification
[ ] Documentation: agent added to Reference Implementations table
[ ] Branch merged to main after all surfaces pass
```

---

# Part IV: Reference Implementations

For complete working examples, see:

| Agent | Location | Key Features |
|-------|----------|--------------|
| deep_research | `src/cosa/agents/deep_research/` | Web search, report synthesis, human-in-the-loop |
| podcast_generator | `src/cosa/agents/podcast_generator/` | File input, TTS generation, audio stitching |
| deep_research_to_podcast | `src/cosa/agents/deep_research_to_podcast/` | Chained workflow pattern |

### Key Files to Reference

```
# Interface contract
src/cosa/agents/agentic_job_base.py

# Notification utilities
src/cosa/agents/utils/voice_io.py

# Configuration patterns
src/cosa/agents/deep_research/config.py

# State machine patterns
src/cosa/agents/deep_research/state.py

# Job wrapper pattern
src/cosa/agents/deep_research/job.py

# LLM client (Phase 6)
src/cosa/agents/deep_research/api_client.py

# Cost tracking (Phase 7)
src/cosa/agents/deep_research/cost_tracker.py

# Rate limiting (Phase 8)
src/cosa/agents/deep_research/rate_limiter.py

# Mock clients (Phase 1-2)
src/cosa/agents/podcast_generator/mock_clients.py

# TTS integration (Phase 9)
src/cosa/agents/podcast_generator/tts_client.py

# Chained agent (Phase 10)
src/cosa/agents/deep_research_to_podcast/agent.py

# Job factory + agent registry (Phase 5)
src/cosa/rest/agentic_job_factory.py
src/cosa/agents/runtime_argument_expeditor/agent_registry.py

# Dedicated routers (Phase 5b)
src/cosa/rest/routers/deep_research.py
src/cosa/rest/routers/podcast_generator.py

# Queue utilities (WebSocket state transitions)
src/cosa/rest/queue_util.py
src/cosa/rest/queue_extensions.py

# Mock job endpoint (Surface 2)
src/cosa/rest/routers/mock_job.py

# Training coordinator (Surface 4)
src/cosa/training/xml_coordinator.py

# PEFT trainer (Surface 4)
src/cosa/training/peft_trainer.py

# Smoke test example (Surface 1)
src/tests/smoke/test_deep_research_dry_run_smoke.py

# Unit test example (Surface 1)
src/tests/unit/test_runtime_argument_expeditor.py
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.1 | 2026-02-07 | Completeness review: fixed training template naming + JSON path (Surface 4), added agent_registry.py + agentic_job_factory.py registration (Phase 5), added FastAPI router template (Phase 5b), added notification UI submission card guide (Surface 3), added artifact storage pattern + WebSocket state transition notes (Phase 5), added model string convention note (Phase 6), expanded final checklist |
| 2.0 | 2026-02-06 | Complete lifecycle guide: Part I CONCEPT, Part II BUILD expanded (Phases 6-10), Part III VALIDATE Testing Ladder (5 surfaces), Part IV Reference Implementations |
| 1.0 | 2026-01-27 | Initial workflow documentation (BUILD phases 0-5 only) |
