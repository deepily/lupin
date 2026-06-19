#!/usr/bin/env python3
"""
Decision Responder for the Decision Proxy Agent.

Extends BaseResponder with trust-aware decision routing. Receives
notification events, classifies decisions by category, checks trust
levels, and either acts autonomously, queues for ratification, or
shadows for training data.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

import json
from typing import Optional

from cosa.agents.utils.proxy_agents.base_responder import BaseResponder
from cosa.agents.decision_proxy.config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    DEFAULT_TRUST_MODE,
)
from cosa.agents.decision_proxy.smart_router import SmartRouter


class DecisionResponder( BaseResponder ):
    """
    Trust-aware decision responder for the Decision Proxy.

    Routes response-required notifications through a domain-specific
    decision strategy that classifies, gates, and decides based on
    earned trust levels.

    Requires:
        - A domain strategy is loaded (via --profile flag)
        - Trust mode is one of: shadow, suggest, active

    Ensures:
        - Decisions at L1 are logged but never acted on
        - Decisions at L2 are queued as provisional
        - Decisions at L3+ are committed with audit trail
        - All decisions are logged regardless of action
    """

    LOG_PREFIX = "[DecisionResponder]"

    def __init__(
        self,
        trust_mode          = DEFAULT_TRUST_MODE,
        accepted_senders    = None,
        embedding_provider  = None,
        host                = DEFAULT_SERVER_HOST,
        port                = DEFAULT_SERVER_PORT,
        dry_run             = False,
        debug               = False,
        verbose             = False
    ):
        """
        Initialize the decision responder.

        Args:
            trust_mode: Operating mode ("shadow", "suggest", "active")
            accepted_senders: List of sender IDs this proxy will respond to
            embedding_provider: Optional EmbeddingProvider for generating question embeddings
            host: Server hostname for REST API
            port: Server port for REST API
            dry_run: Display decisions without acting
            debug: Enable debug output
            verbose: Enable verbose output
        """
        super().__init__(
            host    = host,
            port    = port,
            dry_run = dry_run,
            debug   = debug,
            verbose = verbose
        )

        self.trust_mode         = trust_mode
        self.accepted_senders   = accepted_senders or []
        self.smart_router       = SmartRouter( debug=debug )
        self.domain_strategy    = None  # Set by profile loader
        self.embedding_provider = embedding_provider
        self._embedding_store   = None  # Lazy-init on first use

        # Extend base stats with decision-specific counters
        self.stats.update( {
            "decisions_classified" : 0,
            "decisions_shadowed"   : 0,
            "decisions_suggested"  : 0,
            "decisions_acted"      : 0,
            "decisions_deferred"   : 0,
            "sender_rejected"      : 0,
        } )

    def set_domain_strategy( self, strategy ):
        """
        Set the domain-specific decision strategy.

        Requires:
            - strategy implements BaseDecisionStrategy interface

        Ensures:
            - Strategy is stored and used for all subsequent decisions

        Args:
            strategy: Domain-specific strategy instance
        """
        self.domain_strategy = strategy

    async def handle_event( self, event_type, event_data ):
        """
        Handle a WebSocket event.

        Routes notification_queue_update events to the decision pipeline.
        Logs job_state_transition events if verbose.

        Args:
            event_type: WebSocket event type string
            event_data: Event payload dict
        """
        self.stats[ "events_received" ] += 1

        if event_type == "notification_queue_update":
            await self._handle_decision_event( event_data )

        elif event_type == "job_state_transition":
            if self.verbose:
                job_id     = event_data.get( "job_id", "?" )
                from_queue = event_data.get( "from_queue", "?" )
                to_queue   = event_data.get( "to_queue", "?" )
                print( f"{self.LOG_PREFIX} Job state: {job_id} {from_queue} -> {to_queue}" )

        elif self.verbose:
            print( f"{self.LOG_PREFIX} Event: {event_type}" )

    async def _handle_decision_event( self, event_data ):
        """
        Process a notification_queue_update event through the decision pipeline.

        Steps:
            1. Extract notification fields
            2. Check sender ID against accepted list
            3. Skip non-response-requested notifications
            4. Classify decision category
            5. Check trust level and gate action
            6. Act, suggest, shadow, or defer

        Args:
            event_data: notification_queue_update event payload
        """
        # Extract notification from the event
        notification = event_data.get( "notification", event_data )

        notification_id    = notification.get( "id_hash" ) or notification.get( "notification_id" ) or notification.get( "id" )
        response_requested = notification.get( "response_requested", False )
        message            = notification.get( "message", "" )
        sender_id          = notification.get( "sender_id", "" )
        response_type      = notification.get( "response_type", "" )
        title              = notification.get( "title", "" )

        # Debug display
        if self.debug:
            print( f"\n{self.LOG_PREFIX} {'=' * 50}" )
            print( f"{self.LOG_PREFIX} Notification: {notification_id}" )
            print( f"{self.LOG_PREFIX} sender_id: {sender_id}" )
            print( f"{self.LOG_PREFIX} response_type: {response_type}" )
            print( f"{self.LOG_PREFIX} response_requested: {response_requested}" )
            print( f"{self.LOG_PREFIX} message: {message[ :120 ]}" )

        # Skip non-response-requested notifications
        if not response_requested:
            self.stats[ "skipped" ] += 1
            return

        if not notification_id:
            self.stats[ "errors" ] += 1
            print( f"{self.LOG_PREFIX} ERROR: No notification_id in event" )
            return

        # Check sender ID against accepted list
        if self.accepted_senders and sender_id not in self.accepted_senders:
            self.stats[ "sender_rejected" ] += 1
            if self.debug: print( f"{self.LOG_PREFIX} Sender rejected: {sender_id}" )
            return

        # Dry run: log and cancel
        if self.dry_run:
            cancel_value = "no" if response_type == "yes_no" else "cancel"
            self.submit_response( notification_id, cancel_value )
            self.stats[ "skipped" ] += 1
            print( f"{self.LOG_PREFIX} DRY RUN — Declined ({cancel_value} sent)" )
            return

        # No domain strategy loaded — shadow everything
        if self.domain_strategy is None:
            self.stats[ "decisions_shadowed" ] += 1
            if self.debug: print( f"{self.LOG_PREFIX} No strategy loaded — shadow log only" )
            return

        # Run the decision pipeline
        result = self.domain_strategy.evaluate( message, sender_id, context=notification )
        self.stats[ "decisions_classified" ] += 1

        if result.action == "shadow":
            self.stats[ "decisions_shadowed" ] += 1
            self._persist_decision( notification_id, result, message )
            if self.debug:
                print( f"{self.LOG_PREFIX} SHADOW: {result.category} (L{result.trust_level}, {result.confidence:.2f})" )

        elif result.action == "suggest":
            self.stats[ "decisions_suggested" ] += 1
            self._persist_decision( notification_id, result, message, requires_ratification=True )
            if self.debug:
                print( f"{self.LOG_PREFIX} SUGGEST: {result.category} -> {result.value}" )

        elif result.action == "act":
            self.stats[ "decisions_acted" ] += 1
            self._persist_decision( notification_id, result, message, requires_ratification=False )
            if result.value is not None:
                success = self.submit_response( notification_id, result.value )
                if success:
                    self.stats[ "responses_sent" ] += 1
                    print( f"{self.LOG_PREFIX} ACT: {result.category} -> {result.value}" )
                else:
                    self.stats[ "errors" ] += 1

        elif result.action == "defer":
            self.stats[ "decisions_deferred" ] += 1
            self._persist_decision( notification_id, result, message )
            if self.debug:
                print( f"{self.LOG_PREFIX} DEFER: {result.category} — {result.reason}" )

    def _get_embedding_store( self ):
        """
        Lazily initialize the LanceDB embedding store.

        Ensures:
            - Returns ProxyDecisionEmbeddings instance or None
            - Only initializes once per responder lifetime
        """
        if self._embedding_store is not None:
            return self._embedding_store

        if self.embedding_provider is None:
            return None

        try:
            from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
            from cosa.agents.decision_proxy.config import DEFAULT_PROXY_LANCEDB_TABLE

            import cosa.utils.util as cu
            from cosa.config.configuration_manager import ConfigurationManager

            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            db_path    = cu.get_project_root() + config_mgr.get( "solution snapshots lancedb path" )
            table_name = config_mgr.get( "swe team trust proxy lancedb table", default=DEFAULT_PROXY_LANCEDB_TABLE )

            self._embedding_store = ProxyDecisionEmbeddings(
                db_path    = db_path,
                table_name = table_name,
                debug      = self.debug,
            )

            if self.debug: print( f"{self.LOG_PREFIX} Initialized embedding store: {table_name}" )
            return self._embedding_store

        except Exception as e:
            if self.debug: print( f"{self.LOG_PREFIX} Embedding store init failed (non-fatal): {e}" )
            return None

    def _persist_decision( self, notification_id, result, question, requires_ratification=None ):
        """
        Persist a decision to the database (non-fatal).

        Wraps DB writes in try/except so the in-memory tracker remains
        source of truth. DB persistence is best-effort. After PostgreSQL
        write, generates an embedding and writes to LanceDB (also best-effort).

        Requires:
            - notification_id is a string
            - result is a DecisionResult with category, action, confidence, trust_level, reason

        Ensures:
            - Decision logged to proxy_decisions table on success
            - Embedding written to LanceDB on success (best-effort)
            - Failure logged but never propagates

        Args:
            notification_id: UUID string of original notification
            result: DecisionResult from domain strategy
            question: Original question text
            requires_ratification: Override for ratification state (None = infer from action)
        """
        try:
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository

            with get_db() as session:
                repo = ProxyDecisionRepository( session )

                if result.action == "shadow":
                    repo.log_shadow(
                        notification_id = notification_id,
                        domain          = getattr( self.domain_strategy, "name", "unknown" ),
                        category        = result.category,
                        question        = question[ :500 ],
                        sender_id       = "",
                        confidence      = result.confidence,
                        trust_level     = result.trust_level,
                        reason          = result.reason or "shadow mode",
                    )
                else:
                    repo.log_decision(
                        notification_id      = notification_id,
                        domain               = getattr( self.domain_strategy, "name", "unknown" ),
                        category             = result.category,
                        question             = question[ :500 ],
                        action               = result.action,
                        decision_value       = result.value,
                        confidence           = result.confidence,
                        trust_level          = result.trust_level,
                        reason               = result.reason or "",
                        requires_ratification = requires_ratification if requires_ratification is not None else ( result.action == "suggest" ),
                    )

        except Exception as e:
            if self.debug:
                print( f"{self.LOG_PREFIX} DB persistence failed (non-fatal): {e}" )

        # Best-effort: generate embedding and write to LanceDB
        self._persist_embedding( notification_id, result, question, requires_ratification )

    def _persist_embedding( self, notification_id, result, question, requires_ratification ):
        """
        Generate a question embedding and write to LanceDB (best-effort).

        Called after PostgreSQL write succeeds. Both embedding generation
        and LanceDB write are wrapped in try/except — failures are logged
        but never propagate.

        Args:
            notification_id: Decision identifier
            result: DecisionResult from domain strategy
            question: Original question text
            requires_ratification: Ratification state flag
        """
        try:
            store = self._get_embedding_store()
            if store is None:
                return

            from datetime import datetime, timezone

            embedding = self.embedding_provider.generate_embedding( question[ :500 ], content_type="prose" )

            ratification_state = "shadow"
            if requires_ratification is True:
                ratification_state = "pending"
            elif requires_ratification is False:
                ratification_state = "autonomous"

            store.add_decision(
                id                  = notification_id,
                question            = question[ :500 ],
                category            = result.category,
                decision_value      = result.value or "",
                ratification_state  = ratification_state,
                question_embedding  = embedding,
                created_at          = datetime.now( timezone.utc ).isoformat(),
            )

        except Exception as e:
            if self.debug:
                print( f"{self.LOG_PREFIX} Embedding persistence failed (non-fatal): {e}" )

    def get_decision_diagnostics( self ):
        """
        Return combined decision diagnostics.

        Ensures:
            - Returns dict with stats and optional Thompson Sampling diagnostics
            - Safe to call regardless of strategy configuration

        Returns:
            Dict with "stats" and optional "thompson_sampling" keys
        """
        result = { "stats": dict( self.stats ) }

        if self.domain_strategy and hasattr( self.domain_strategy, "get_thompson_diagnostics" ):
            result[ "thompson_sampling" ] = self.domain_strategy.get_thompson_diagnostics()

        if self.domain_strategy and hasattr( self.domain_strategy, "_conformal_wrapper" ):
            wrapper = self.domain_strategy._conformal_wrapper
            if wrapper is not None:
                result[ "conformal" ] = wrapper.get_status()

        return result

    def print_stats( self ):
        """Print decision proxy statistics."""
        print( f"\n{'=' * 50}" )
        print( "Decision Proxy Statistics" )
        print( f"{'=' * 50}" )
        for key, value in self.stats.items():
            label = key.replace( "_", " " ).title()
            print( f"  {label:30s} : {value}" )
        print( f"{'=' * 50}" )
