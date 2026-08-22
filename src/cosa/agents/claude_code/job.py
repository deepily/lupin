"""
Claude Code background job for queue-based execution.

Wraps the existing ClaudeCodeDispatcher functionality for execution
within the CJ Flow (COSA Job Flow) queue system. Enables users to submit
Claude Code tasks via the API and receive results asynchronously.

Supports both task types:
    - BOUNDED: Fire-and-forget, runs to completion
    - INTERACTIVE: Bidirectional via notification service

Example:
    job = ClaudeCodeJob(
        prompt      = "Run the tests and fix any failures",
        project     = "lupin",
        user_id     = "user123",
        user_email  = "user@example.com",
        session_id  = "wise-penguin",
        task_type   = "BOUNDED",
        max_turns   = 50,
        debug       = True
    )
    result = job.do_all()  # Runs task and returns conversational answer
"""

import asyncio
from datetime import datetime
from typing import Optional

import cosa.utils.util as cu
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


class ClaudeCodeJob( AgenticJobBase ):
    """
    Background job for Claude Code execution via CJ Flow.

    Wraps ClaudeCodeDispatcher for queue-based execution with full
    notification support via cosa-voice MCP tools.

    Attributes:
        prompt: The task prompt for Claude Code
        project: Target project name (e.g., "lupin", "cosa")
        task_type: "BOUNDED" or "INTERACTIVE"
        max_turns: Maximum agentic turns (default 50)
        cost_usd: Execution cost (set after completion)
        output_text: Task output (set after completion)
    """

    JOB_TYPE   = "claude_code"
    JOB_PREFIX = "cc"

    # Phase labels for dry-run simulation loops
    DRY_RUN_BOUNDED_LABELS = [
        "Initializing Claude Code session",
        "Parsing task prompt",
        "Preparing project environment",
        "Simulating bounded execution",
        "Generating completion report",
    ]

    DRY_RUN_INTERACTIVE_LABELS = [
        "Initializing interactive session",
        "Streaming initial response",
        "Pausing for user input",
        "Processing injected message",
        "Resuming with context awareness",
        "Second interaction cycle",
        "Graceful session shutdown",
    ]

    # Config-driven defaults (loaded once at class level, overridden per-instance)
    _config_defaults_loaded = False
    _default_max_turns      = 50
    _default_timeout        = 3600

    @classmethod
    def _load_config_defaults( cls ):
        """Load defaults from ConfigurationManager (once per process)."""
        if cls._config_defaults_loaded:
            return
        try:
            from cosa.config.configuration_manager import ConfigurationManager
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            cls._default_max_turns = config_mgr.get( "claude code job max turns default", default=50, return_type="int" )
            cls._default_timeout   = config_mgr.get( "claude code job timeout seconds default", default=3600, return_type="int" )
        except Exception:
            pass  # Fall back to hardcoded defaults if config unavailable
        cls._config_defaults_loaded = True

    def __init__(
        self,
        prompt: str,
        project: str,
        user_id: str,
        user_email: str,
        session_id: str,
        task_type: str = "BOUNDED",
        max_turns: int = None,
        timeout_seconds: int = None,
        dry_run: bool = False,
        dry_run_phases: int = None,
        dry_run_delay: float = None,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a Claude Code job.

        Requires:
            - prompt is a non-empty string
            - project is a valid project name
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID
            - task_type is "BOUNDED" or "INTERACTIVE" (case-insensitive)

        Ensures:
            - Job ID generated with "cc-" prefix
            - All parameters stored for execution
            - Defaults loaded from ConfigurationManager when params are None
            - task_type is stored upper-cased, and is one of the two legal values

        Raises:
            - ValueError if task_type is neither BOUNDED nor INTERACTIVE

        Args:
            prompt: The task prompt for Claude Code
            project: Target project name (e.g., "lupin", "cosa")
            user_id: System ID of the job owner
            user_email: Email address for user association
            session_id: WebSocket session for notifications
            task_type: "BOUNDED" (default) or "INTERACTIVE"
            max_turns: Maximum agentic turns (None = load from config, default 50)
            timeout_seconds: Task timeout (None = load from config, default 3600)
            dry_run: If True, simulate execution without running Claude Code
            dry_run_phases: Number of simulation phases (None = use class-level defaults per task_type)
            dry_run_delay: Seconds to sleep per phase (None = 1.0 for bounded, 1.0 for interactive)
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

        # Load config defaults if not yet loaded
        self._load_config_defaults()

        # Claude Code task parameters (use config defaults when not explicitly provided)
        self.prompt          = prompt
        self.project         = project
        # THE TWO LEGAL VALUES, CHECKED HERE RATHER THAN AT A DOOR. The Requires above has
        # always said BOUNDED or INTERACTIVE, and nothing enforced it: an unknown value was
        # stored and then tested with `== "BOUNDED"` at every branch below (dispatch, the
        # notification prefix, the run fork), so a typo did not fail — it silently ran the
        # task INTERACTIVE, waiting for a human who is not there.
        #
        # `/api/claude-code/submit` held this guard as a 400 and is now a tombstone;
        # `/api/v2/submit` is generic and validates `args` against the command's argument
        # contract, which says nothing about which VALUES an argument may take. So the check
        # moves to the job, where it also covers the voice path and the in-process callers.
        self.task_type       = task_type.upper()
        if self.task_type not in ( "BOUNDED", "INTERACTIVE" ):
            raise ValueError(
                f"Invalid task_type [{task_type}] — must be BOUNDED or INTERACTIVE."
            )
        self.max_turns       = max_turns if max_turns is not None else self._default_max_turns
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else self._default_timeout
        self.dry_run         = dry_run
        self.dry_run_phases  = dry_run_phases
        self.dry_run_delay   = dry_run_delay

        # Results (populated after execution)
        self.task_result  = None
        self.cost_usd     = None
        self.output_text  = None
        self.cost_summary = None  # Required by queues.py for unified job interface

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns truncated prompt with task type prefix.

        Returns:
            str: Human-readable job description
        """
        prefix = "Bounded" if self.task_type == "BOUNDED" else "Interactive"
        truncated = self.prompt[ :50 ] + "..." if len( self.prompt ) > 50 else self.prompt
        return f"[Claude Code - {prefix}] {truncated}"

    def do_all( self ) -> str:
        """
        Execute Claude Code task and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing results
        """
        if self.debug:
            print( f"[ClaudeCodeJob] Starting do_all() for: {self.prompt[ :50 ]}..." )

        self.state      = JobState.RUNNING
        self.started_at = cu.get_current_datetime_iso()

        try:
            result = asyncio.run( self._execute() )

            self.state        = JobState.COMPLETED
            self.completed_at = cu.get_current_datetime_iso()
            self.result       = result
            self.answer_conversational = result

            if self.debug:
                duration = self.get_execution_duration_seconds()
                print( f"[ClaudeCodeJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = str( e )
            self.answer_conversational = f"Claude Code task failed: {str( e )}"

            if self.debug:
                print( f"[ClaudeCodeJob] Failed: {e}" )
                import traceback
                traceback.print_exc()

            # Re-raise so the agentic-pool Future captures the exception.
            # Backlog item 5 (2026-04-29): canonical Future contract.
            raise

    async def _execute( self ) -> str:
        """
        Internal async task execution.

        Uses ClaudeCodeDispatcher to run the task with MCP voice tools.
        Notifications route through the notification service with job_id
        for proper job card association.

        Returns:
            str: Conversational summary of task results
        """
        # Check for dry-run mode first
        if self.dry_run:
            return await self._execute_dry_run()

        from cosa.orchestration.claude_code import ClaudeCodeDispatcher, Task, TaskType

        # Import cosa_interface for notifications (uses notification API directly)
        from cosa.agents.claude_code import cosa_interface

        # Notify start
        await cosa_interface.notify_progress(
            f"Starting Claude Code task: {self.prompt[ :60 ]}...",
            priority="low",
            job_id=self.id_hash,
            queue_name="run"
        )

        if self.debug:
            print( f"[ClaudeCodeJob] Dispatching {self.task_type} task" )
            print( f"[ClaudeCodeJob] Project: {self.project}" )
            print( f"[ClaudeCodeJob] Max turns: {self.max_turns}" )

        # Create dispatcher
        dispatcher = ClaudeCodeDispatcher(
            on_message=self._on_message_callback
        )

        # Create task
        task_type_enum = TaskType.BOUNDED if self.task_type == "BOUNDED" else TaskType.INTERACTIVE

        task = Task(
            id              = self.id_hash,
            project         = self.project,
            prompt          = self.prompt,
            type            = task_type_enum,
            max_turns       = self.max_turns,
            timeout_seconds = self.timeout_seconds
        )

        # Dispatch and collect result
        result = await dispatcher.dispatch( task )

        # Store task result
        self.task_result = result

        if result.success:
            # Store artifacts
            self.cost_usd     = result.cost_usd or 0.0
            self.output_text  = result.result or ""
            self.cost_summary = {
                "total_cost_usd" : self.cost_usd
            }

            self.artifacts = {
                "cost_usd"     : self.cost_usd,
                "cost_summary" : self.cost_summary,
                "output_text"  : self.output_text[ :500 ] if self.output_text else "",
                "task_type"    : self.task_type,
                "project"      : self.project,
                "session_id"   : result.session_id,
                "duration_ms"  : result.duration_ms
            }

            # Format completion message
            cost_str = f"${self.cost_usd:.4f}" if self.cost_usd else "$0.00"
            duration_str = f"{result.duration_ms / 1000:.1f}s" if result.duration_ms else "N/A"

            completion_abstract = f"""**Claude Code Task Complete!**

**Task**: {self.prompt[ :100 ]}...

**Stats**: {cost_str} | {duration_str}

**Output**: {self.output_text[ :200 ] if self.output_text else "No output"}..."""

            # Store the abstract in artifacts so it rides the running→done transition (bug 9b481811 sweep)
            self.artifacts[ "abstract" ] = completion_abstract

            # Notify completion
            await cosa_interface.notify_progress(
                f"Claude Code task complete. Cost: {cost_str}",
                priority="medium",
                abstract=completion_abstract,
                job_id=self.id_hash,
                queue_name="run"
            )

            return f"Claude Code task completed. Cost: {cost_str}. {self.output_text[ :200 ] if self.output_text else ''}"

        else:
            # Task failed
            error_msg = result.error or "Unknown error"
            self.artifacts = {
                "error"     : error_msg,
                "task_type" : self.task_type,
                "project"   : self.project,
                "exit_code" : result.exit_code
            }

            await cosa_interface.notify_progress(
                f"Claude Code task failed: {error_msg[ :80 ]}",
                priority="urgent",
                job_id=self.id_hash,
                queue_name="run"
            )

            raise RuntimeError( f"Claude Code task failed: {error_msg}" )

    async def _execute_dry_run( self ) -> str:
        """
        Dispatch dry-run execution to mode-specific handler.

        Routes to _execute_dry_run_interactive() for INTERACTIVE tasks,
        _execute_dry_run_bounded() for everything else.

        Returns:
            str: Mock completion message
        """
        if self.task_type == "INTERACTIVE":
            return await self._execute_dry_run_interactive()
        return await self._execute_dry_run_bounded()

    async def _execute_dry_run_bounded( self ) -> str:
        """
        Simulate BOUNDED ClaudeCodeJob execution for testing queue flow.

        Loops through DRY_RUN_BOUNDED_LABELS with configurable phase count
        and delay, sending low-priority notifications at each phase.

        Requires:
            - self.dry_run is True
            - self.task_type is "BOUNDED" (or any non-INTERACTIVE type)

        Ensures:
            - Runs min( dry_run_phases, len( DRY_RUN_BOUNDED_LABELS ) ) phases
            - Each phase sleeps for dry_run_delay seconds
            - Sets cost_summary dict and artifacts for queue parity
            - Returns mock completion message

        Returns:
            str: Mock completion message
        """
        from cosa.agents.claude_code import cosa_interface
        import asyncio

        # Resolve configurable phase count and delay
        num_phases = self.dry_run_phases if self.dry_run_phases is not None else len( self.DRY_RUN_BOUNDED_LABELS )
        delay      = self.dry_run_delay if self.dry_run_delay is not None else 1.0
        num_phases = min( num_phases, len( self.DRY_RUN_BOUNDED_LABELS ) )

        if self.debug:
            print( f"[ClaudeCodeJob] DRY RUN BOUNDED for: {self.prompt[ :50 ]}..." )
            print( f"[ClaudeCodeJob] Phases: {num_phases}, delay: {delay}s" )

        # Loop through simulation phases
        for i in range( num_phases ):
            label = self.DRY_RUN_BOUNDED_LABELS[ i ]
            await cosa_interface.notify_progress(
                f"Dry run: {label}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( delay )

        # Mock cost summary with actual simulated duration
        total_duration = num_phases * delay
        self.output_text  = f"Mock Bounded execution completed for: {self.prompt[ :100 ]}..."
        self.cost_usd     = 0.0
        self.cost_summary = {
            "duration_seconds"    : total_duration,
            "total_cost_usd"      : 0.0,
            "total_input_tokens"  : 0,
            "total_output_tokens" : 0,
        }
        self.artifacts = {
            "cost_usd"     : 0.0,
            "output_text"  : self.output_text,
            "task_type"    : self.task_type,
            "project"      : self.project,
            "dry_run"      : True,
            "cost_summary" : self.cost_summary,
        }

        # Completion notification with abstract
        completion_abstract = f"""**Mock Claude Code Job Complete**

- **Job ID**: {self.id_hash}
- **Type**: Bounded
- **Project**: {self.project}
- **Cost**: $0.00 (dry-run)
- **Duration**: ~{total_duration:.0f}s (simulated)

This was a dry-run simulation. No actual Claude Code execution occurred."""

        # Store the abstract in artifacts so it rides the running→done transition (bug 9b481811 sweep)
        self.artifacts[ "abstract" ] = completion_abstract

        await cosa_interface.notify_progress(
            f"Dry run complete: {self.id_hash}",
            priority="medium",
            abstract=completion_abstract,
            job_id=self.id_hash,
            queue_name="run"
        )

        return self.output_text

    async def _execute_dry_run_interactive( self ) -> str:
        """
        Simulate INTERACTIVE ClaudeCodeJob execution for testing queue flow.

        Exercises MessageHistory and multi-turn conversation simulation,
        validating the bidirectional flow that the real dispatcher uses
        (dispatcher.py:388-509) without touching the dispatcher.

        Phases:
            1. Session init — create MessageHistory, set original prompt
            2. Initial response — add_assistant_text with mock analysis
            3. Pause for input — notification: "waiting for user"
            4. Injected message — add_user_message + get_context_prompt
            5. Resume with context — add_assistant_text showing context awareness
            6. Second cycle — another user+assistant turn
            7. Session end — final notification + stats

        Requires:
            - self.dry_run is True
            - self.task_type is "INTERACTIVE"

        Ensures:
            - MessageHistory tracks 5 messages (2 assistant, 2 user, 1 assistant)
            - get_context_prompt() returns non-empty string
            - Sets cost_summary dict and artifacts with conversation stats
            - Returns mock completion message with conversation turn count

        Returns:
            str: Mock completion message including conversation stats
        """
        from cosa.agents.claude_code import cosa_interface
        from cosa.orchestration.claude_code.message_history import MessageHistory
        import asyncio

        # Resolve configurable phase count and delay
        num_phases = self.dry_run_phases if self.dry_run_phases is not None else len( self.DRY_RUN_INTERACTIVE_LABELS )
        delay      = self.dry_run_delay if self.dry_run_delay is not None else 1.0
        num_phases = min( num_phases, len( self.DRY_RUN_INTERACTIVE_LABELS ) )

        if self.debug:
            print( f"[ClaudeCodeJob] DRY RUN INTERACTIVE for: {self.prompt[ :50 ]}..." )
            print( f"[ClaudeCodeJob] Phases: {num_phases}, delay: {delay}s" )

        # ─── Phase 1: Session init ────────────────────────────────────────
        history = MessageHistory()
        history.set_original_prompt( self.prompt )

        if num_phases >= 1:
            await cosa_interface.notify_progress(
                f"Dry run: {self.DRY_RUN_INTERACTIVE_LABELS[ 0 ]}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( delay )

        # ─── Phase 2: Initial response ────────────────────────────────────
        mock_analysis = (
            f"I'll analyze the task: '{self.prompt[ :80 ]}'. "
            "Let me start by examining the relevant code and identifying "
            "the key areas that need attention."
        )
        history.add_assistant_text( mock_analysis )

        if num_phases >= 2:
            await cosa_interface.notify_progress(
                f"Dry run: {self.DRY_RUN_INTERACTIVE_LABELS[ 1 ]}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( delay )

        # ─── Phase 3: Pause for user input ─────────────────────────────────
        if num_phases >= 3:
            await cosa_interface.notify_progress(
                f"Dry run: {self.DRY_RUN_INTERACTIVE_LABELS[ 2 ]}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( delay )

        # ─── Phase 4: Injected message + context prompt ────────────────────
        mock_user_message = "Focus on the error handling paths first, then address the main logic."
        history.add_user_message( mock_user_message )

        # Validate context prompt generation (the key piece!)
        context_prompt = history.get_context_prompt()
        if self.debug:
            print( f"[ClaudeCodeJob] Context prompt length: {len( context_prompt )} chars" )
            print( f"[ClaudeCodeJob] Messages in history: {len( history )}" )

        if num_phases >= 4:
            await cosa_interface.notify_progress(
                f"Dry run: {self.DRY_RUN_INTERACTIVE_LABELS[ 3 ]}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( delay )

        # ─── Phase 5: Resume with context awareness ────────────────────────
        mock_context_response = (
            "Understood. I'll prioritize the error handling paths as requested. "
            "Based on our conversation context, I can see the original task and "
            "your refinement. Proceeding with error handling first."
        )
        history.add_assistant_text( mock_context_response )

        if num_phases >= 5:
            await cosa_interface.notify_progress(
                f"Dry run: {self.DRY_RUN_INTERACTIVE_LABELS[ 4 ]}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( delay )

        # ─── Phase 6: Second interaction cycle ─────────────────────────────
        mock_user_followup = "Looks good, please continue with the main logic now."
        history.add_user_message( mock_user_followup )

        mock_final_response = (
            "Moving on to the main logic now. All error handling paths have been "
            "addressed. The implementation is complete."
        )
        history.add_assistant_text( mock_final_response )

        if num_phases >= 6:
            await cosa_interface.notify_progress(
                f"Dry run: {self.DRY_RUN_INTERACTIVE_LABELS[ 5 ]}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( delay )

        # ─── Phase 7: Session end ──────────────────────────────────────────
        conversation_turns = len( history )
        context_prompt_len = len( history.get_context_prompt() )

        # Verify conversation state
        if self.debug:
            print( f"[ClaudeCodeJob] Final conversation turns: {conversation_turns}" )
            print( f"[ClaudeCodeJob] Final context prompt length: {context_prompt_len}" )
            assert conversation_turns == 5, f"Expected 5 messages, got {conversation_turns}"
            assert context_prompt_len > 0, "Context prompt should be non-empty"

        total_duration = num_phases * delay
        self.output_text  = (
            f"Mock Interactive session completed for: {self.prompt[ :100 ]}... "
            f"({conversation_turns} conversation turns, "
            f"context prompt: {context_prompt_len} chars)"
        )
        self.cost_usd     = 0.0
        self.cost_summary = {
            "duration_seconds"    : total_duration,
            "total_cost_usd"      : 0.0,
            "total_input_tokens"  : 0,
            "total_output_tokens" : 0,
        }
        self.artifacts = {
            "cost_usd"           : 0.0,
            "output_text"        : self.output_text,
            "task_type"          : self.task_type,
            "project"            : self.project,
            "dry_run"            : True,
            "cost_summary"       : self.cost_summary,
            "conversation_turns" : conversation_turns,
            "context_prompt_len" : context_prompt_len,
        }

        if num_phases >= 7:
            await cosa_interface.notify_progress(
                f"Dry run: {self.DRY_RUN_INTERACTIVE_LABELS[ 6 ]}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( delay )

        # Completion notification with abstract
        completion_abstract = f"""**Mock Interactive Claude Code Job Complete**

- **Job ID**: {self.id_hash}
- **Type**: Interactive
- **Project**: {self.project}
- **Cost**: $0.00 (dry-run)
- **Duration**: ~{total_duration:.0f}s (simulated)
- **Conversation turns**: {conversation_turns}
- **Context prompt**: {context_prompt_len} chars

This was a dry-run simulation exercising MessageHistory and multi-turn context."""

        # Store the abstract in artifacts so it rides the running→done transition (bug 9b481811 sweep)
        self.artifacts[ "abstract" ] = completion_abstract

        await cosa_interface.notify_progress(
            f"Dry run complete: {self.id_hash}",
            priority="medium",
            abstract=completion_abstract,
            job_id=self.id_hash,
            queue_name="run"
        )

        return self.output_text

    def _on_message_callback( self, task_id: str, message ) -> None:
        """
        Callback for streaming messages from dispatcher.

        Logs messages in debug mode. Messages are primarily for
        WebSocket streaming in direct mode; in queue mode, notifications
        use the cosa-voice MCP tools instead.

        Args:
            task_id: The task ID
            message: Message object (dict or SDK type)
        """
        if self.debug:
            msg_type = message.get( "type", "unknown" ) if isinstance( message, dict ) else type( message ).__name__
            print( f"[ClaudeCodeJob] Message: {msg_type}" )


def quick_smoke_test():
    """
    Quick smoke test for ClaudeCodeJob.
    """
    import cosa.utils.util as cu

    cu.print_banner( "ClaudeCodeJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.claude_code.job import ClaudeCodeJob
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing job instantiation..." )
        job = ClaudeCodeJob(
            prompt     = "Run the tests",
            project    = "lupin",
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
            task_type  = "BOUNDED",
            debug      = True
        )
        print( f"✓ Job created with id: {job.id_hash}" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "cc-" ), "ID should start with cc-"
        assert len( job.id_hash ) == 11, f"ID should be 11 chars, got {len( job.id_hash )}"
        print( f"✓ ID format correct: {job.id_hash}" )

        # Test 4: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = job.last_question_asked
        assert "[Claude Code - Bounded]" in lqa
        print( f"✓ last_question_asked: {lqa}" )

        # Test 5: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable == False
        print( "✓ is_cacheable correctly returns False" )

        # Test 6: Check attributes
        print( "Testing job attributes..." )
        assert job.prompt == "Run the tests"
        assert job.project == "lupin"
        assert job.task_type == "BOUNDED"
        assert job.max_turns == 50
        assert job.state == JobState.PENDING
        print( "✓ All attributes set correctly" )

        # Test 7: Check JOB_TYPE and JOB_PREFIX
        print( "Testing class constants..." )
        assert ClaudeCodeJob.JOB_TYPE == "claude_code"
        assert ClaudeCodeJob.JOB_PREFIX == "cc"
        print( "✓ Class constants correct" )

        # Test 8: Test INTERACTIVE mode
        print( "Testing INTERACTIVE mode..." )
        job_interactive = ClaudeCodeJob(
            prompt     = "Let's work on the auth refactor",
            project    = "cosa",
            user_id    = "user456",
            user_email = "user@test.com",
            session_id = "session789",
            task_type  = "INTERACTIVE",
            max_turns  = 200,
            debug      = False
        )
        assert job_interactive.task_type == "INTERACTIVE"
        assert job_interactive.max_turns == 200
        assert "[Claude Code - Interactive]" in job_interactive.last_question_asked
        print( f"✓ INTERACTIVE job created: {job_interactive.id_hash}" )

        # Test 9: Test unified interface properties
        print( "Testing unified interface properties..." )
        assert job.question == job.last_question_asked, "question should equal last_question_asked"
        assert job.job_type == "claude_code", "job_type should equal JOB_TYPE"
        assert job.created_date == job.run_date, "created_date should equal run_date"
        print( "✓ Unified interface properties work correctly" )

        # Test 10: Test dry_run flag
        print( "Testing dry_run flag..." )
        assert job.dry_run == False, "Default dry_run should be False"
        job_dry = ClaudeCodeJob(
            prompt     = "Test dry run",
            project    = "lupin",
            user_id    = "user789",
            user_email = "dry@test.com",
            session_id = "session_dry",
            dry_run    = True
        )
        assert job_dry.dry_run == True, "dry_run should be True when set"
        print( "✓ dry_run flag works correctly" )

        # Test 11: Test cost_summary attribute
        print( "Testing cost_summary attribute..." )
        assert hasattr( job, 'cost_summary' ), "Job should have cost_summary attribute"
        assert job.cost_summary is None, "cost_summary should be None initially"
        print( "✓ cost_summary attribute exists and is None by default" )

        # Test 12: Test dry_run_phases and dry_run_delay defaults
        print( "Testing dry_run_phases and dry_run_delay defaults..." )
        assert job.dry_run_phases is None, "dry_run_phases should be None by default"
        assert job.dry_run_delay is None, "dry_run_delay should be None by default"
        print( "✓ dry_run_phases and dry_run_delay are None by default" )

        # Test 13: Test dry_run_phases and dry_run_delay with explicit values
        print( "Testing dry_run_phases and dry_run_delay with explicit values..." )
        job_custom_dry = ClaudeCodeJob(
            prompt          = "Test custom dry run params",
            project         = "lupin",
            user_id         = "user_custom",
            user_email      = "custom@test.com",
            session_id      = "session_custom",
            dry_run         = True,
            dry_run_phases  = 3,
            dry_run_delay   = 0.5
        )
        assert job_custom_dry.dry_run_phases == 3, f"Expected 3, got {job_custom_dry.dry_run_phases}"
        assert job_custom_dry.dry_run_delay == 0.5, f"Expected 0.5, got {job_custom_dry.dry_run_delay}"
        print( "✓ dry_run_phases=3 and dry_run_delay=0.5 set correctly" )

        # Test 14: Test class-level phase labels
        print( "Testing class-level DRY_RUN labels..." )
        assert len( ClaudeCodeJob.DRY_RUN_BOUNDED_LABELS ) == 5, "Bounded should have 5 labels"
        assert len( ClaudeCodeJob.DRY_RUN_INTERACTIVE_LABELS ) == 7, "Interactive should have 7 labels"
        print( f"✓ Bounded: {len( ClaudeCodeJob.DRY_RUN_BOUNDED_LABELS )} labels, Interactive: {len( ClaudeCodeJob.DRY_RUN_INTERACTIVE_LABELS )} labels" )

        # Note: We don't test do_all() here as it requires Claude Code CLI
        print( "\n* Note: do_all() not tested (requires Claude Code CLI)" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
