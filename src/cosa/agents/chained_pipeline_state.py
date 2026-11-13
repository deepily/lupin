#!/usr/bin/env python3
"""
Shared result predicate for the chained Deep Research pipelines.

The Deep Research to Podcast and Deep Research to Presentation pipelines each keep their own
PipelineState enum and ChainedResult dataclass. They share one rule for a half-finished run,
which lives here as a mixin so the two result classes agree on it.
The two chained agents also share the whole Deep Research stage, which lives here as a base class.
The same class finalizes a run: the end time, the duration and the combined cost.
"""

import time
from datetime import datetime


class ChainedResultMixin:
    """
    Predicate shared by the chained pipelines' result dataclasses.

    A subclass sets two class attributes.
    PARTIAL_STATES lists the states under which a run can count as partial.
    PRIMARY_ARTIFACT names the field that stays None when the second stage made nothing.
    """

    PARTIAL_STATES   = ()
    PRIMARY_ARTIFACT = ""

    def is_partial( self ) -> bool:
        """
        Check if the research stage finished but the second stage produced nothing.

        Requires:
            - the subclass sets PARTIAL_STATES and PRIMARY_ARTIFACT
            - self has state and research_path fields, and a field named by PRIMARY_ARTIFACT

        Ensures:
            - Returns True only when state is in PARTIAL_STATES, research_path is set and
              the PRIMARY_ARTIFACT field is None
        """
        return (
            self.state in self.PARTIAL_STATES
            and self.research_path is not None
            and getattr( self, self.PRIMARY_ARTIFACT ) is None
        )


class ChainedDeepResearchAgent:
    """
    Base class for the chained agents whose first stage is Deep Research.

    A subclass sets four class attributes.
    PIPELINE_STATE is its own PipelineState enum, and RESULT_CLASS is its own ChainedResult.
    STAGE_LABEL names the second stage in notifications, for example "Podcast Generation".
    A subclass also defines three methods.
    The first returns the second stage's voice_io module, and it is named _stage_voice_io.
    The second runs the stage, and it is named _run_second_stage.
    The third keeps what the stage made, and it is named _store_second_stage_result.
    """

    PIPELINE_STATE = None
    RESULT_CLASS   = None
    STAGE_LABEL    = ""

    def __init__(
        self,
        query: str,
        user_email: str,
        budget=None,
        lead_model=None,
        no_confirm: bool = False,
        audience=None,
        audience_context=None,
        source_document=None,
        cli_mode: bool = False,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Keep the options both chained agents share and start an empty result.

        Requires:
            - the subclass sets RESULT_CLASS
            - query is a non-empty string and user_email is an email address

        Ensures:
            - every argument is kept under its own name, and source_document is [] when None
            - self.result is a new RESULT_CLASS and self._start_time is None
            - with debug it prints the query, the user and the mode
        """
        self.query            = query
        self.user_email       = user_email
        self.budget           = budget
        self.lead_model       = lead_model
        self.no_confirm       = no_confirm
        self.audience         = audience
        self.audience_context = audience_context
        self.source_document  = source_document or [ ]
        self.cli_mode         = cli_mode
        self.debug            = debug
        self.verbose          = verbose
        self.result           = self.RESULT_CLASS()
        self._start_time      = None

        if self.debug:
            print( f"[{type( self ).__name__}] Initialized" )
            print( f"  Query: {query[ :50 ]}..." )
            print( f"  User: {user_email}" )
            print( f"  Mode: {'CLI' if cli_mode else 'Voice-driven'}" )

    def _set_modality( self ) -> None:
        """
        Set voice or CLI mode on Deep Research and on the second stage.

        Requires:
            - _stage_voice_io returns a voice_io module with set_cli_mode

        Ensures:
            - both voice_io modules carry self.cli_mode
            - Deep Research is the default binding for the pipeline's notifications
        """
        from cosa.agents.deep_research import voice_io as dr_voice_io

        dr_voice_io.set_cli_mode( self.cli_mode )
        self._stage_voice_io().set_cli_mode( self.cli_mode )

        # Re-establish DR binding as the default for pipeline notifications
        dr_voice_io.reconfigure()

        if self.debug:
            mode = "CLI" if self.cli_mode else "Voice-driven"
            print( f"[{type( self ).__name__}] Set modality to: {mode}" )

    async def run_async( self ):
        """
        Execute the full chain: Deep Research, then the second stage.

        Ensures:
            - returns self.result, finalized, whether the run completed, was cancelled or failed
            - the state is completed only when both stages made a result
            - a stage's cancellation or a missing report path sets the cancelled or failed state and an error
            - an exception sets the failed state, notifies at urgent priority and does not escape
        """
        self._start_time = time.time()
        self.result.started_at = datetime.now().isoformat()
        self.result.state = self.PIPELINE_STATE.INITIALIZED

        # Set modality before running either agent
        self._set_modality()

        try:
            # Step 1: Run Deep Research
            await self._notify( "Starting Deep Research pipeline...", priority="medium" )
            dr_result = await self._run_deep_research()

            if dr_result.get( "cancelled" ):
                self.result.state = self.PIPELINE_STATE.CANCELLED
                self.result.error = "Deep Research was cancelled by user"
                return self._finalize_result()

            # Extract report path
            report_path = dr_result.get( "report_path" )
            if not report_path:
                self.result.state = self.PIPELINE_STATE.FAILED
                self.result.error = "Deep Research completed but no report_path returned"
                return self._finalize_result()

            # Store DR results
            self.result.research_path = report_path
            self.result.research_abstract = dr_result.get( "abstract" )
            self.result.dr_cost = dr_result.get( "cost", 0.0 )
            self.result.dr_artifacts = dr_result.get( "artifacts", {} )
            self.result.state = self.PIPELINE_STATE.DEEP_RESEARCH_DONE

            # Checkpoint: Confirm DR artifacts before the second-stage handoff
            dr_artifacts = self.result.dr_artifacts
            checkpoint_abstract = (
                f"**Research Report**: {report_path}\n\n"
                f"**Abstract**: {self.result.research_abstract[ :200 ] if self.result.research_abstract else 'N/A'}...\n\n"
                f"**Cost**: ${self.result.dr_cost:.4f} | "
                f"**Tokens**: {dr_artifacts.get( 'tokens_used', 'N/A' ):,} | "
                f"**Duration**: {dr_artifacts.get( 'duration_seconds', 0 ):.0f}s"
            )

            skipped_names = self._skipped_topic_names( dr_artifacts )
            if skipped_names:
                checkpoint_abstract += f"\n\n**Skipped topics ({len( skipped_names )})**: " + "; ".join( skipped_names )

            await self._notify(
                f"Deep Research complete! Cost: ${self.result.dr_cost:.4f}" + ( f" ({len( skipped_names )} topics skipped)" if skipped_names else "" ),
                priority="medium",
                abstract=checkpoint_abstract
            )

            # Step 2: Run the second stage
            await self._notify( f"Starting {self.STAGE_LABEL}...", priority="medium" )
            pg_result = await self._run_second_stage( report_path )

            if pg_result.get( "cancelled" ):
                self.result.state = self.PIPELINE_STATE.CANCELLED
                self.result.error = f"{self.STAGE_LABEL} was cancelled by user"
                return self._finalize_result()

            # Store second-stage results
            self._store_second_stage_result( pg_result )
            self.result.pg_cost = pg_result.get( "cost", 0.0 )
            self.result.pg_artifacts = pg_result.get( "artifacts", {} )
            self.result.state = self.PIPELINE_STATE.COMPLETED

            await self._notify(
                f"Pipeline complete! Total cost: ${self.result.total_cost:.4f}",
                priority="medium"
            )

            return self._finalize_result()

        except Exception as e:
            self.result.state = self.PIPELINE_STATE.FAILED
            self.result.error = str( e )

            await self._notify(
                f"Pipeline failed: {str( e )[ :100 ]}",
                priority="urgent"
            )

            if self.debug:
                import traceback
                traceback.print_exc()

            return self._finalize_result()

    def _skipped_topic_names( self, dr_artifacts: dict ) -> list:
        """
        Name the research topics Deep Research skipped, for the checkpoint notice.

        Requires:
            - dr_artifacts is the artifacts dict Deep Research returned

        Ensures:
            - returns a list of topic names, empty when the stage reports none or does not use them
        """
        return [ ]

    async def _notify( self, message: str, priority: str = "medium", **kwargs ) -> None:
        """
        Send a notification using the Deep Research voice_io, which is already configured.

        Ensures:
            - the message is sent at the given priority with any extra keyword arguments
        """
        from cosa.agents.deep_research import voice_io

        await voice_io.notify( message, priority=priority, **kwargs )

    def get_state( self ):
        """
        Get the current pipeline state.

        Ensures:
            - returns self.result.state
        """
        return self.result.state

    async def _run_deep_research( self ) -> dict:
        """
        Run the Deep Research stage and return its results.

        Requires:
            - self.PIPELINE_STATE is the subclass's PipelineState enum
            - self carries query, user_email, budget, lead_model, audience, audience_context,
              source_document, no_confirm, debug, verbose and a result with a settable state

        Ensures:
            - result.state is RUNNING_DEEP_RESEARCH
            - the per-task dispatch context names self.user_email as target_user
            - returns {"cancelled": True} when the research made no report
            - otherwise returns a dict with report_path, abstract, cost, artifacts and cancelled False

        Raises:
            - Exception when the cost budget is exceeded
        """
        self.result.state = self.PIPELINE_STATE.RUNNING_DEEP_RESEARCH

        # Re-establish DR voice_io binding before DR phase
        from cosa.agents.utils.agent_notification_dispatcher import set_dispatch_context
        from cosa.agents.deep_research import voice_io as dr_voice_io
        from cosa.agents.deep_research import cosa_interface as dr_cosa_interface
        dr_voice_io.reconfigure()
        dr_cosa_interface.TARGET_USER = self.user_email
        set_dispatch_context( target_user=self.user_email )

        # Import Deep Research components
        from cosa.agents.deep_research.config import ResearchConfig
        from cosa.agents.deep_research.cost_tracker import CostTracker, BudgetExceededError
        from cosa.agents.deep_research.seed_context import query_with_seed_context
        from cosa.agents.deep_research.cli import run_research
        from cosa.agents.deep_research.job import abstract_and_save_report, derive_session_name, resolve_output_settings
        from cosa.config.configuration_manager import ConfigurationManager

        # Initialize configuration
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Get storage configuration and the full output path
        output_settings = resolve_output_settings( config_mgr )
        storage_backend = output_settings[ 0 ]

        # Generate session_name from query using Gister, and derive semantic_topic from it
        session_name, semantic_topic = derive_session_name( self.query, debug=self.debug )

        if self.debug:
            print( f"[DR] Session name: {session_name}" )
            print( f"[DR] Semantic topic: {semantic_topic}" )
            print( f"[DR] Storage backend: {storage_backend}" )

        # Create research configuration
        config = ResearchConfig(
            lead_model     = self.lead_model if self.lead_model else config_mgr.get_required( "deep research lead model" ),
            subagent_model = config_mgr.get_required( "deep research subagent model" ),
            audience = self.audience or config_mgr.get(
                "deep research audience",
                default="academic"
            ),
            audience_context = self.audience_context or config_mgr.get(
                "deep research audience context",
                default=None
            ) or None,
        )

        # Generate unique session ID for this pipeline (needed by CostTracker)
        import uuid
        session_id = f"chain-{uuid.uuid4().hex[ :8 ]}"

        # Create cost tracker
        cost_tracker = CostTracker( session_id=session_id, budget_limit_usd=self.budget )

        try:
            # Run the research.
            #
            # The seed document enters here and nowhere else (row 5726e3c5). It is kept
            # out of `self.query`, which also feeds the session-name gist above, the
            # pipeline notifications and the saved report's frontmatter, where a whole
            # file would be unreadable. One call site, one enrichment.
            skipped_topics = []
            report = await run_research(
                query        = query_with_seed_context( self.query, self.source_document ),
                config       = config,
                cost_tracker = cost_tracker,
                user_email   = self.user_email,
                no_confirm   = self.no_confirm,
                debug        = self.debug,
                verbose      = self.verbose,
                skipped_topics = skipped_topics
            )

            if report is None:
                return { "cancelled": True }

            # Generate abstract, then save the report with frontmatter
            abstract, report_path = await abstract_and_save_report(
                report, self.query, config, cost_tracker, session_id, semantic_topic, output_settings, self.user_email, debug=self.debug
            )

            # Get cost summary
            summary = cost_tracker.get_summary()

            return {
                "report_path" : report_path,
                "abstract"    : abstract,
                "cost"        : summary.total_cost_usd,
                "artifacts"   : {
                    "report"          : report,
                    "skipped_topics"  : skipped_topics,
                    "session_name"    : session_name,
                    "semantic_topic"  : semantic_topic,
                    "tokens_used"     : summary.total_input_tokens + summary.total_output_tokens,
                    "duration_seconds": summary.duration_seconds,
                },
                "cancelled"   : False,
            }

        except BudgetExceededError as e:
            raise Exception( f"Deep Research budget exceeded: ${e.current_cost:.2f} of ${e.budget_limit:.2f}" )

    def _finalize_result( self ):
        """
        Stamp the finished run with its end time, duration and combined cost, and return it.

        Requires:
            - self.result has completed_at, duration_seconds, total_cost, dr_cost and pg_cost
            - self._start_time is None or the time.time() value taken when the run began

        Ensures:
            - result.completed_at is the current local time as ISO text
            - result.duration_seconds is set only when _start_time is truthy
            - result.total_cost is dr_cost plus pg_cost
            - returns self.result
        """
        self.result.completed_at = datetime.now().isoformat()
        if self._start_time:
            self.result.duration_seconds = time.time() - self._start_time
        self.result.total_cost = self.result.dr_cost + self.result.pg_cost
        return self.result
