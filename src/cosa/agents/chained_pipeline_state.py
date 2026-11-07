#!/usr/bin/env python3
"""
Shared result predicate for the chained Deep Research pipelines.

The Deep Research to Podcast and Deep Research to Presentation pipelines each keep their own
PipelineState enum and ChainedResult dataclass. They share one rule for a half-finished run,
which lives here as a mixin so the two result classes agree on it.
The two chained agents also share the whole Deep Research stage, which lives here as a base class.
"""


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

    A subclass sets PIPELINE_STATE to its own PipelineState enum.
    The second stage stays in the subclass, because the artifacts it makes differ.
    """

    PIPELINE_STATE = None

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
        from cosa.agents.deep_research.cli import (
            run_research,
            generate_abstract_for_cli,
            save_report_with_frontmatter,
        )
        from cosa.config.configuration_manager import ConfigurationManager
        from cosa.memory.gister import Gister
        import cosa.utils.util as cu

        # Initialize configuration
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Get storage configuration
        storage_backend = config_mgr.get( "deep research storage backend", default="local" )
        gcs_bucket = config_mgr.get( "deep research gcs bucket", default=None )
        output_dir = config_mgr.get( "deep research output directory", default="/io/deep-research" )

        # Build full output path
        if not output_dir.startswith( "/" ):
            output_dir = cu.get_project_root() + "/" + output_dir
        elif not output_dir.startswith( cu.get_project_root() ):
            output_dir = cu.get_project_root() + output_dir

        # Generate session_name from query using Gister
        gister = Gister( debug=self.debug )
        session_name = gister.get_gist(
            self.query,
            prompt_key="prompt template for deep research session name"
        )
        session_name = session_name.lower().strip() if session_name else "general research query"

        # Derive semantic_topic from session_name
        semantic_topic = session_name.replace( " ", "-" )

        if self.debug:
            print( f"[DR] Session name: {session_name}" )
            print( f"[DR] Semantic topic: {semantic_topic}" )
            print( f"[DR] Storage backend: {storage_backend}" )

        # Create research configuration
        config = ResearchConfig(
            lead_model = self.lead_model if self.lead_model else config_mgr.get(
                "deep research lead model",
                default="claude-opus-4-6"
            ),
            subagent_model = config_mgr.get(
                "deep research subagent model",
                default="claude-sonnet-4-6"
            ),
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

            # Generate abstract
            abstract = await generate_abstract_for_cli(
                report       = report,
                config       = config,
                cost_tracker = cost_tracker,
                debug        = self.debug
            )

            # Save report with frontmatter
            report_path = save_report_with_frontmatter(
                report          = report,
                query           = self.query,
                abstract        = abstract,
                semantic_topic  = semantic_topic,
                session_id      = session_id,
                cost_tracker    = cost_tracker,
                config          = config,
                output_dir      = output_dir,
                user_email      = self.user_email,
                storage_backend = storage_backend,
                gcs_bucket      = gcs_bucket,
                debug           = self.debug
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
