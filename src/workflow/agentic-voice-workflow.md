# Agentic Voice Workflow: Building Claude Agent SDK Services

**Version**: 1.0
**Created**: 2026-01-27
**Purpose**: Repeatable process for creating agentic background jobs with voice I/O and queue integration

---

## Overview

This workflow guides the creation of new agentic services in the LUPIN project that:
- Run as background jobs via the `RunningFifoQueue`
- Send progress notifications via `cosa-voice` MCP tools
- Support human-in-the-loop decision points
- Generate artifacts (reports, audio, etc.)
- Follow the established `AgenticJobBase` interface contract

**Pattern Source**: Derived from `deep_research`, `podcast_generator`, and `deep_research_to_podcast` agents.

---

## Phase 0: Interactive Discovery

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

---

## Phase 1-2: Skeletal Agent Foundation

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

### Phase 1-2 Smoke Test Checklist

```
[ ] All files created in src/cosa/agents/{agent_name}/
[ ] python -m cosa.agents.{agent_name}.config  (smoke test passes)
[ ] python -m cosa.agents.{agent_name}.state   (smoke test passes)
[ ] python -m cosa.agents.{agent_name}.orchestrator (smoke test passes)
[ ] python -m cosa.agents.{agent_name} "test" --debug (CLI runs)
```

### Phase 1-2 TodoWrite Template

```
[LUPIN] Create {agent_name} directory structure
[LUPIN] Write {agent_name}/config.py with dataclass
[LUPIN] Write {agent_name}/state.py with Pydantic models and enum
[LUPIN] Write {agent_name}/orchestrator.py skeleton
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

from cosa.cli.notification_models import (
    NotificationRequest,
    NotificationType,
    NotificationPriority,
)
from cosa.cli.notify_user_sync import notify_user_sync as _notify_user_sync
from cosa.cli.notify_user_async import notify_user_async as _notify_user_async

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

## Phase 5+: AgenticJob Queue Wrapper

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

        # Store artifacts
        self.artifacts[ "result" ] = result

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

### Queue Registration

Register the job type in the queue router (typically in `src/cosa/rest/routers/queue_router.py`):

```python
from cosa.agents.{agent_name}.job import {AgentName}Job

# In the job creation endpoint:
if job_type == "{agent_name}":
    job = {AgentName}Job(
        input_value = request.input_value,
        user_id     = current_user.uid,
        user_email  = current_user.email,
        session_id  = request.session_id,
        debug       = request.debug or False
    )
    queue.push( job )
```

### Phase 5+ Smoke Test Checklist

```
[ ] job.py created with AgenticJobBase inheritance
[ ] JOB_TYPE and JOB_PREFIX constants defined
[ ] do_all() -> _execute() bridge pattern implemented
[ ] Dry-run mode with breadcrumb notifications
[ ] python -m cosa.agents.{agent_name}.job (smoke test)
[ ] Job submission via API endpoint works
[ ] Job appears in queue UI correctly
```

### Phase 5+ TodoWrite Template

```
[LUPIN] Create {agent_name}/job.py with AgenticJobBase inheritance
[LUPIN] Implement do_all() -> _execute() bridge pattern
[LUPIN] Add dry-run mode with breadcrumb notifications
[LUPIN] Register job type in queue router
[LUPIN] Run smoke tests for job.py
[LUPIN] Test job submission and queue visualization
```

---

## Reference Implementations

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
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-27 | Initial workflow documentation |
