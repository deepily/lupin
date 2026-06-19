"""
Proxy decision repository for CRUD operations on ProxyDecision and TrustState models.

Provides decision-specific methods beyond base repository functionality,
including shadow logging, ratification, and trust state persistence.

Dependency Rule:
    This module NEVER imports from notification_proxy or swe_team.
"""

from typing import Optional, List, Dict
from datetime import datetime, timezone
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from cosa.rest.postgres_models import ProxyDecision, TrustState
from cosa.rest.db.repositories.base import BaseRepository


class ProxyDecisionRepository( BaseRepository[ProxyDecision] ):
    """
    Repository for ProxyDecision model with trust-aware operations.

    Extends BaseRepository with decision-specific methods:
        - Shadow logging (L1 decisions — observe only)
        - Decision logging (L2+ — suggest/act/defer)
        - Pending decision retrieval for ratification
        - Ratification (approve/reject)
        - Similar decision lookup

    Requires:
        - session: Active SQLAlchemy session (from get_db())

    Ensures:
        - All decisions are logged regardless of trust level
        - Ratification updates decision state and trust metrics
        - Pending decisions are retrievable by domain/category
    """

    def __init__( self, session: Session ):
        """
        Initialize ProxyDecisionRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())
        """
        super().__init__( ProxyDecision, session )

    def log_shadow( self, notification_id, domain, category, question,
                    sender_id="", confidence=0.0, trust_level=1, reason="",
                    metadata_json=None, data_origin="organic" ):
        """
        Log a shadow decision (L1 — observe only, no action taken).

        Requires:
            - notification_id: UUID string of the original notification
            - domain: Domain identifier (e.g., "swe")
            - category: Decision category
            - question: Original question text

        Ensures:
            - ProxyDecision created with action="shadow"
            - ratification_state set to "not_required"
            - Returns created ProxyDecision instance

        Args:
            notification_id: Original notification UUID string
            domain: Domain identifier
            category: Decision category
            question: Original question text
            sender_id: Requesting agent sender ID
            confidence: Classification confidence (0.0-1.0)
            trust_level: Trust level at decision time
            reason: Human-readable reason
            metadata_json: Optional JSONB metadata
            data_origin: Provenance tag (organic, synthetic_seed, synthetic_generated)

        Returns:
            Created ProxyDecision instance
        """
        return self.create(
            notification_id      = notification_id,
            domain               = domain,
            category             = category,
            question             = question,
            sender_id            = sender_id,
            action               = "shadow",
            decision_value       = None,
            confidence           = confidence,
            trust_level          = trust_level,
            reason               = reason or "L1 shadow mode — log only",
            ratification_state   = "not_required",
            metadata_json        = metadata_json,
            data_origin          = data_origin,
        )

    def log_decision( self, notification_id, domain, category, question,
                      action, decision_value=None, sender_id="",
                      confidence=0.0, trust_level=1, reason="",
                      requires_ratification=False, metadata_json=None,
                      data_origin="organic" ):
        """
        Log a decision with specified action (suggest, act, defer).

        Requires:
            - notification_id: UUID string of the original notification
            - domain: Domain identifier
            - category: Decision category
            - question: Original question text
            - action: One of "suggest", "act", "defer"

        Ensures:
            - ProxyDecision created with given action
            - ratification_state set based on requires_ratification
            - Returns created ProxyDecision instance

        Args:
            notification_id: Original notification UUID string
            domain: Domain identifier
            category: Decision category
            question: Original question text
            action: Action taken (suggest, act, defer)
            decision_value: Decision value if acted
            sender_id: Requesting agent sender ID
            confidence: Classification confidence (0.0-1.0)
            trust_level: Trust level at decision time
            reason: Human-readable reason
            requires_ratification: Whether decision needs human approval
            metadata_json: Optional JSONB metadata
            data_origin: Provenance tag (organic, synthetic_seed, synthetic_generated)

        Returns:
            Created ProxyDecision instance
        """
        ratification_state = "pending" if requires_ratification else "not_required"

        return self.create(
            notification_id      = notification_id,
            domain               = domain,
            category             = category,
            question             = question,
            sender_id            = sender_id,
            action               = action,
            decision_value       = decision_value,
            confidence           = confidence,
            trust_level          = trust_level,
            reason               = reason,
            ratification_state   = ratification_state,
            metadata_json        = metadata_json,
            data_origin          = data_origin,
        )

    def get_pending( self, domain=None, category=None, limit=100 ):
        """
        Get decisions pending ratification.

        Requires:
            - Optional domain/category filters

        Ensures:
            - Returns decisions with ratification_state="pending"
            - Ordered by created_at ascending (oldest first)
            - Applies optional domain and category filters

        Args:
            domain: Optional domain filter
            category: Optional category filter
            limit: Maximum results (default: 100)

        Returns:
            List of ProxyDecision instances pending ratification
        """
        query = self.session.query( ProxyDecision ).filter(
            ProxyDecision.ratification_state == "pending"
        )

        if domain:
            query = query.filter( ProxyDecision.domain == domain )
        if category:
            query = query.filter( ProxyDecision.category == category )

        return query.order_by(
            ProxyDecision.created_at.asc()
        ).limit( limit ).all()

    def ratify( self, decision_id, approved, ratified_by, feedback="" ):
        """
        Ratify (approve or reject) a pending decision.

        Requires:
            - decision_id: UUID of the decision to ratify
            - approved: True to approve, False to reject
            - ratified_by: Email of the ratifying user

        Ensures:
            - ratification_state updated to "approved" or "rejected"
            - ratified_at timestamp set
            - ratified_by and feedback recorded
            - Returns updated ProxyDecision or None if not found

        Args:
            decision_id: UUID of the decision
            approved: True to approve, False to reject
            ratified_by: User email
            feedback: Optional feedback text

        Returns:
            Updated ProxyDecision instance or None
        """
        decision = self.get_by_id( decision_id )
        if not decision:
            return None

        decision.ratification_state   = "approved" if approved else "rejected"
        decision.ratified_by          = ratified_by
        decision.ratified_at          = datetime.now( timezone.utc )
        decision.ratification_feedback = feedback

        self.session.flush()
        return decision

    def delete_pending( self, decision_id ):
        """
        Delete a pending decision permanently.

        Only decisions with ratification_state="pending" can be deleted.
        Approved/rejected decisions are protected from deletion.

        Requires:
            - decision_id: UUID of the decision to delete

        Ensures:
            - Decision is hard-deleted from the database if pending
            - Returns True on success, False if not found
            - Does NOT modify trust state counters

        Raises:
            - ValueError if decision exists but is not in "pending" state

        Args:
            decision_id: UUID of the decision

        Returns:
            True if deleted, False if not found
        """
        decision = self.get_by_id( decision_id )
        if not decision:
            return False

        if decision.ratification_state != "pending":
            raise ValueError(
                f"Cannot delete decision with state '{decision.ratification_state}' — only pending decisions can be deleted"
            )

        self.session.delete( decision )
        self.session.flush()
        return True

    def get_by_domain_category( self, domain, category, limit=50 ):
        """
        Get decisions for a specific domain and category.

        Requires:
            - domain: Domain identifier
            - category: Decision category

        Ensures:
            - Returns decisions matching domain+category
            - Ordered by created_at descending (newest first)

        Args:
            domain: Domain identifier
            category: Decision category
            limit: Maximum results (default: 50)

        Returns:
            List of ProxyDecision instances
        """
        return self.session.query( ProxyDecision ).filter(
            ProxyDecision.domain == domain,
            ProxyDecision.category == category
        ).order_by(
            desc( ProxyDecision.created_at )
        ).limit( limit ).all()

    def find_similar( self, question, domain, category, limit=5 ):
        """
        Find similar past decisions for a given question.

        Uses simple substring matching for now. Can be enhanced with
        vector similarity search later.

        Requires:
            - question: Question text to match against
            - domain: Domain filter
            - category: Category filter

        Ensures:
            - Returns decisions with similar questions in same domain/category
            - Ordered by created_at descending (most recent first)

        Args:
            question: Question text
            domain: Domain identifier
            category: Decision category
            limit: Maximum results (default: 5)

        Returns:
            List of ProxyDecision instances with similar questions
        """
        # Extract key words (>3 chars) for ILIKE matching
        words = [ w for w in question.split() if len( w ) > 3 ]
        if not words:
            return []

        query = self.session.query( ProxyDecision ).filter(
            ProxyDecision.domain == domain,
            ProxyDecision.category == category
        )

        # Match any keyword (OR logic)
        for word in words[ :3 ]:  # Use first 3 keywords to avoid over-filtering
            query = query.filter(
                ProxyDecision.question.ilike( f"%{word}%" )
            )

        return query.order_by(
            desc( ProxyDecision.created_at )
        ).limit( limit ).all()

    def get_pending_summary( self, domain=None ):
        """
        Get summary of pending decisions for ratification UI.

        Requires:
            - Optional domain filter

        Ensures:
            - Returns dict with total_pending, by_category, by_trust_level, oldest_pending

        Args:
            domain: Optional domain filter

        Returns:
            Dict with summary statistics
        """
        query = self.session.query( ProxyDecision ).filter(
            ProxyDecision.ratification_state == "pending"
        )

        if domain:
            query = query.filter( ProxyDecision.domain == domain )

        decisions = query.all()

        by_category    = {}
        by_trust_level = {}
        oldest_pending = None

        for d in decisions:
            by_category[ d.category ] = by_category.get( d.category, 0 ) + 1
            level_key = f"L{d.trust_level}"
            by_trust_level[ level_key ] = by_trust_level.get( level_key, 0 ) + 1

            if oldest_pending is None or d.created_at < oldest_pending:
                oldest_pending = d.created_at

        return {
            "total_pending"  : len( decisions ),
            "by_category"    : by_category,
            "by_trust_level" : by_trust_level,
            "oldest_pending" : oldest_pending.isoformat() if oldest_pending else None,
        }


class TrustStateRepository( BaseRepository[TrustState] ):
    """
    Repository for TrustState model — persists per-user trust snapshots.

    Provides trust state CRUD with upsert semantics for the unique
    (user_email, domain, category) composite key.

    Requires:
        - session: Active SQLAlchemy session (from get_db())

    Ensures:
        - Trust states are upserted (create or update)
        - get_or_create returns existing or creates new
    """

    def __init__( self, session: Session ):
        """
        Initialize TrustStateRepository with session.

        Requires:
            - session: Active SQLAlchemy session (from get_db())
        """
        super().__init__( TrustState, session )

    def get_by_user_domain_category( self, user_email, domain, category ):
        """
        Get trust state for a specific user+domain+category combo.

        Requires:
            - user_email: User email address
            - domain: Domain identifier
            - category: Decision category

        Ensures:
            - Returns TrustState if found, None otherwise

        Args:
            user_email: User email
            domain: Domain identifier
            category: Decision category

        Returns:
            TrustState instance or None
        """
        return self.session.query( TrustState ).filter(
            TrustState.user_email == user_email,
            TrustState.domain == domain,
            TrustState.category == category
        ).first()

    def get_or_create( self, user_email, domain, category ):
        """
        Get existing trust state or create a new one.

        Requires:
            - user_email: User email address
            - domain: Domain identifier
            - category: Decision category

        Ensures:
            - Returns existing TrustState if found
            - Creates new TrustState with defaults if not found
            - New trust states start at level 1

        Args:
            user_email: User email
            domain: Domain identifier
            category: Decision category

        Returns:
            TrustState instance (existing or newly created)
        """
        existing = self.get_by_user_domain_category( user_email, domain, category )
        if existing:
            return existing

        return self.create(
            user_email           = user_email,
            domain               = domain,
            category             = category,
            trust_level          = 1,
            total_decisions      = 0,
            successful_decisions = 0,
            rejected_decisions   = 0
        )

    def update_after_ratification( self, user_email, domain, category, approved ):
        """
        Update trust state after a ratification event.

        Requires:
            - user_email: User email address
            - domain: Domain identifier
            - category: Decision category
            - approved: True if ratified (success), False if rejected

        Ensures:
            - Trust state counters updated
            - updated_at timestamp refreshed
            - Returns updated TrustState

        Args:
            user_email: User email
            domain: Domain identifier
            category: Decision category
            approved: True if approved, False if rejected

        Returns:
            Updated TrustState instance
        """
        state = self.get_or_create( user_email, domain, category )

        state.total_decisions += 1
        if approved:
            state.successful_decisions += 1
        else:
            state.rejected_decisions += 1

        state.updated_at = datetime.now( timezone.utc )

        self.session.flush()
        return state

    def get_all_for_user( self, user_email, domain=None ):
        """
        Get all trust states for a user, optionally filtered by domain.

        Requires:
            - user_email: User email address
            - domain: Optional domain filter

        Ensures:
            - Returns list of TrustState instances
            - Ordered by domain, then category

        Args:
            user_email: User email
            domain: Optional domain filter

        Returns:
            List of TrustState instances
        """
        query = self.session.query( TrustState ).filter(
            TrustState.user_email == user_email
        )

        if domain:
            query = query.filter( TrustState.domain == domain )

        return query.order_by(
            TrustState.domain,
            TrustState.category
        ).all()

    def update_trust_level( self, user_email, domain, category, new_level ):
        """
        Update the stored trust level for a category.

        Requires:
            - user_email: User email address
            - domain: Domain identifier
            - category: Decision category
            - new_level: New trust level (1-5)

        Ensures:
            - Trust level updated
            - updated_at refreshed

        Args:
            user_email: User email
            domain: Domain identifier
            category: Decision category
            new_level: New trust level

        Returns:
            Updated TrustState instance
        """
        state = self.get_or_create( user_email, domain, category )
        state.trust_level = new_level
        state.updated_at  = datetime.now( timezone.utc )
        self.session.flush()
        return state

    def update_circuit_breaker_state( self, user_email, domain, category, cb_state ):
        """
        Update the circuit breaker state for a category.

        Requires:
            - user_email: User email address
            - domain: Domain identifier
            - category: Decision category
            - cb_state: Dict with circuit breaker state

        Ensures:
            - circuit_breaker_state JSONB updated
            - updated_at refreshed

        Args:
            user_email: User email
            domain: Domain identifier
            category: Decision category
            cb_state: Circuit breaker state dict

        Returns:
            Updated TrustState instance
        """
        state = self.get_or_create( user_email, domain, category )
        state.circuit_breaker_state = cb_state
        state.updated_at = datetime.now( timezone.utc )
        self.session.flush()
        return state
