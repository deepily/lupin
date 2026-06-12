"""
SQLAlchemy ORM Models for PostgreSQL Authentication Database.

Maps to the PostgreSQL schema defined in src/scripts/sql/schema.sql.
Uses SQLAlchemy 2.0 declarative syntax with proper relationships and indexes.

Created: 2025-11-17
Database: lupin_auth
"""

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    BigInteger,
    Text,
    Index,
    CheckConstraint,
    func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from datetime import datetime
from typing import Optional, List
import uuid


class Base( DeclarativeBase ):
    """Base class for all ORM models."""
    pass


class User( Base ):
    """
    User account model.

    Requires:
        - email: Valid unique email address
        - password_hash: Hashed password (never store plaintext)

    Ensures:
        - id is automatically generated UUID
        - created_at defaults to current timestamp
        - roles defaults to ["user"]
        - relationships cascade delete to tokens and keys
    """
    __tablename__ = "users"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )

    # User Credentials
    email: Mapped[str] = mapped_column(
        String( 255 ),
        unique=True,
        nullable=False,
        index=True
    )
    password_hash: Mapped[str] = mapped_column(
        String( 255 ),
        nullable=False
    )

    # Account Status
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        index=True
    )
    is_protected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false"
    )

    # User Metadata
    roles: Mapped[dict] = mapped_column(
        JSONB,
        default=["user"],
        server_default='["user"]'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )

    # Relationships (cascade delete to dependent records)
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    api_keys: Mapped[List["ApiKey"]] = relationship(
        "ApiKey",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    email_verification_tokens: Mapped[List["EmailVerificationToken"]] = relationship(
        "EmailVerificationToken",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[List["PasswordResetToken"]] = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification",
        back_populates="recipient",
        cascade="all, delete-orphan"
    )

    # Indexes defined in schema
    __table_args__ = (
        Index( 'idx_users_email', 'email' ),
        Index( 'idx_users_is_active', 'is_active' ),
        Index( 'idx_users_roles', 'roles', postgresql_using='gin' ),
    )

    def __repr__( self ) -> str:
        return f"<User(id={self.id}, email='{self.email}', active={self.is_active})>"


class RefreshToken( Base ):
    """
    Refresh token model for JWT authentication.

    Requires:
        - user_id: Valid user UUID
        - token_hash: SHA-256 hash of refresh token
        - expires_at: Token expiration timestamp

    Ensures:
        - jti (JWT ID) is automatically generated UUID
        - created_at defaults to current timestamp
        - revoked defaults to False
        - cascades delete when user is deleted
    """
    __tablename__ = "refresh_tokens"

    # Primary Key (JWT ID)
    jti: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )

    # Foreign Key to User
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        ForeignKey( "users.id", ondelete="CASCADE" ),
        nullable=False,
        index=True
    )

    # Token Data
    token_hash: Mapped[str] = mapped_column(
        String( 64 ),
        nullable=False,
        index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        index=True
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false"
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        INET,
        nullable=True
    )

    # Relationship to User
    user: Mapped["User"] = relationship(
        "User",
        back_populates="refresh_tokens"
    )

    # Indexes defined in schema
    __table_args__ = (
        Index( 'idx_refresh_tokens_user_id', 'user_id' ),
        Index( 'idx_refresh_tokens_expires_at', 'expires_at' ),
        Index( 'idx_refresh_tokens_token_hash', 'token_hash' ),
        Index(
            'idx_refresh_tokens_revoked',
            'revoked',
            postgresql_where=(Column( 'revoked' ) == False)
        ),
    )

    def __repr__( self ) -> str:
        return f"<RefreshToken(jti={self.jti}, user_id={self.user_id}, revoked={self.revoked})>"


class ApiKey( Base ):
    """
    API key model for service account authentication.

    Requires:
        - user_id: Valid user UUID
        - key_hash: SHA-256 hash of API key

    Ensures:
        - id is automatically generated UUID
        - created_at defaults to current timestamp
        - is_active defaults to True
        - cascades delete when user is deleted
    """
    __tablename__ = "api_keys"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )

    # Foreign Key to User
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        ForeignKey( "users.id", ondelete="CASCADE" ),
        nullable=False,
        index=True
    )

    # Key Data
    key_hash: Mapped[str] = mapped_column(
        String( 64 ),
        nullable=False,
        index=True
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        index=True
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )

    # Relationship to User
    user: Mapped["User"] = relationship(
        "User",
        back_populates="api_keys"
    )

    # Indexes defined in schema
    __table_args__ = (
        Index( 'idx_api_keys_key_hash', 'key_hash' ),
        Index( 'idx_api_keys_user_id', 'user_id' ),
        Index( 'idx_api_keys_is_active', 'is_active' ),
    )

    def __repr__( self ) -> str:
        return f"<ApiKey(id={self.id}, user_id={self.user_id}, active={self.is_active})>"


class EmailVerificationToken( Base ):
    """
    Email verification token model.

    Requires:
        - token: Unique verification token string
        - user_id: Valid user UUID
        - expires_at: Token expiration timestamp

    Ensures:
        - created_at defaults to current timestamp
        - used defaults to False
        - cascades delete when user is deleted
    """
    __tablename__ = "email_verification_tokens"

    # Primary Key
    token: Mapped[str] = mapped_column(
        String( 255 ),
        primary_key=True
    )

    # Foreign Key to User
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        ForeignKey( "users.id", ondelete="CASCADE" ),
        nullable=False,
        index=True
    )

    # Token Data
    expires_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False
    )
    used: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )

    # Relationship to User
    user: Mapped["User"] = relationship(
        "User",
        back_populates="email_verification_tokens"
    )

    # Indexes defined in schema
    __table_args__ = (
        Index( 'idx_email_verification_user_id', 'user_id' ),
    )

    def __repr__( self ) -> str:
        return f"<EmailVerificationToken(token={self.token[:8]}..., user_id={self.user_id}, used={self.used})>"


class PasswordResetToken( Base ):
    """
    Password reset token model.

    Requires:
        - token: Unique reset token string
        - user_id: Valid user UUID
        - expires_at: Token expiration timestamp

    Ensures:
        - created_at defaults to current timestamp
        - used defaults to False
        - cascades delete when user is deleted
    """
    __tablename__ = "password_reset_tokens"

    # Primary Key
    token: Mapped[str] = mapped_column(
        String( 255 ),
        primary_key=True
    )

    # Foreign Key to User
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        ForeignKey( "users.id", ondelete="CASCADE" ),
        nullable=False,
        index=True
    )

    # Token Data
    expires_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False
    )
    used: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )

    # Relationship to User
    user: Mapped["User"] = relationship(
        "User",
        back_populates="password_reset_tokens"
    )

    # Indexes defined in schema
    __table_args__ = (
        Index( 'idx_password_reset_user_id', 'user_id' ),
    )

    def __repr__( self ) -> str:
        return f"<PasswordResetToken(token={self.token[:8]}..., user_id={self.user_id}, used={self.used})>"


class FailedLoginAttempt( Base ):
    """
    Failed login attempt model for security monitoring.

    Requires:
        - email: Email address used in login attempt
        - ip_address: IP address of login attempt

    Ensures:
        - id is automatically generated BIGSERIAL
        - attempt_time defaults to current timestamp
        - no foreign key (tracks attempts for non-existent users too)
    """
    __tablename__ = "failed_login_attempts"

    # Primary Key (BIGSERIAL auto-increment)
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )

    # Attempt Data
    email: Mapped[str] = mapped_column(
        String( 255 ),
        nullable=False,
        index=True
    )
    ip_address: Mapped[str] = mapped_column(
        INET,
        nullable=False
    )
    attempt_time: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        index=True
    )

    # Indexes defined in schema
    __table_args__ = (
        Index( 'idx_failed_login_email', 'email' ),
        Index( 'idx_failed_login_attempt_time', 'attempt_time' ),
    )

    def __repr__( self ) -> str:
        return f"<FailedLoginAttempt(id={self.id}, email='{self.email}', ip={self.ip_address})>"


class Notification( Base ):
    """
    Notification model for sender-aware notification system.

    Requires:
        - sender_id: Sender identifier (e.g., claude.code@lupin.deepily.ai)
        - recipient_id: Valid user UUID
        - message: Notification message text

    Ensures:
        - id is automatically generated UUID
        - created_at defaults to current timestamp
        - state defaults to 'created'
        - cascades delete when recipient user is deleted
    """
    __tablename__ = "notifications"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )

    # Routing - sender_id is the key field for multi-project grouping
    sender_id: Mapped[str] = mapped_column(
        String( 255 ),
        nullable=False,
        index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        ForeignKey( "users.id", ondelete="CASCADE" ),
        nullable=False,
        index=True
    )
    job_id: Mapped[Optional[str]] = mapped_column(
        String( 256 ),
        nullable=True,
        index=True
    )  # Agentic job ID for routing - compound IDs: SHA256(64) + '::' + UUID(36) = 102+ chars
    progress_group_id: Mapped[Optional[str]] = mapped_column(
        String( 24 ),
        nullable=True,
        index=True
    )  # Progress group ID for in-place DOM updates (format: pg-{hex} or pr-{hex}-{batch})

    # Content
    title: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    abstract: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    type: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        index=True
    )
    priority: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )
    responded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )

    # Response handling
    response_requested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false"
    )
    response_type: Mapped[Optional[str]] = mapped_column(
        String( 50 ),
        nullable=True
    )
    response_value: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )
    response_default: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True
    )
    response_options: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )
    timeout_seconds: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True
    )

    # State machine (created, queued, delivered, responded, expired, error)
    state: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        default="created",
        server_default="created",
        index=True
    )

    # Soft delete / archive flag for hiding notifications without deletion
    is_hidden: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        index=True
    )

    # Relationship to User
    recipient: Mapped["User"] = relationship(
        "User",
        back_populates="notifications"
    )

    # Indexes
    __table_args__ = (
        Index( 'idx_notifications_sender_id', 'sender_id' ),
        Index( 'idx_notifications_recipient_id', 'recipient_id' ),
        Index( 'idx_notifications_state', 'state' ),
        Index( 'idx_notifications_created_at', 'created_at' ),
        Index( 'idx_notifications_sender_recipient', 'sender_id', 'recipient_id' ),
    )

    def __repr__( self ) -> str:
        return f"<Notification(id={self.id}, sender='{self.sender_id}', state='{self.state}')>"


class AuthAuditLog( Base ):
    """
    Authentication audit log model for security tracking.

    Requires:
        - event_type: Type of authentication event

    Ensures:
        - id is automatically generated BIGSERIAL
        - event_time defaults to current timestamp
        - success defaults to True
        - user_id is optional (tracks events for non-authenticated users)
    """
    __tablename__ = "auth_audit_log"

    # Primary Key (BIGSERIAL auto-increment)
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )

    # Event Data
    event_type: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID( as_uuid=True ),
        nullable=True,
        index=True
    )
    email: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        INET,
        nullable=True
    )
    details: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )
    success: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true"
    )
    event_time: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        index=True
    )

    # Indexes defined in schema
    __table_args__ = (
        Index( 'idx_auth_audit_event_type', 'event_type' ),
        Index( 'idx_auth_audit_user_id', 'user_id' ),
        Index( 'idx_auth_audit_event_time', 'event_time' ),
    )

    def __repr__( self ) -> str:
        return f"<AuthAuditLog(id={self.id}, event_type='{self.event_type}', user_id={self.user_id}, success={self.success})>"


# ============================================================================
# Decision Proxy Models (Phase 4)
# ============================================================================

class ProxyDecision( Base ):
    """
    Decision proxy decision log — every decision classified and acted on (or shadowed).

    Requires:
        - notification_id: UUID of the original notification
        - domain: Domain identifier (e.g., "swe", "devops")
        - category: Decision category within the domain
        - question: Original question text
        - action: Action taken (shadow, suggest, act, defer)

    Ensures:
        - id is automatically generated UUID
        - created_at defaults to current timestamp
        - ratification_state defaults to "not_required"
        - metadata stored as JSONB for extensibility
    """
    __tablename__ = "proxy_decisions"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )

    # Decision context
    notification_id: Mapped[str] = mapped_column(
        String( 255 ),
        nullable=False,
        index=True
    )
    domain: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        index=True
    )
    category: Mapped[str] = mapped_column(
        String( 100 ),
        nullable=False,
        index=True
    )
    question: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    sender_id: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True,
        index=True
    )

    # Decision outcome
    action: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        index=True
    )
    decision_value: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    confidence: Mapped[Optional[float]] = mapped_column(
        nullable=True
    )
    trust_level: Mapped[int] = mapped_column(
        nullable=False,
        default=1
    )
    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Ratification
    ratification_state: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        default="not_required",
        server_default="not_required",
        index=True
    )
    ratified_by: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True
    )
    ratified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )
    ratification_feedback: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Extensible metadata
    metadata_json: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )

    # Data provenance (organic, synthetic_seed, synthetic_generated)
    data_origin: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        default="organic",
        server_default="organic",
        index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )

    # Indexes
    __table_args__ = (
        Index( 'idx_proxy_decisions_domain', 'domain' ),
        Index( 'idx_proxy_decisions_category', 'category' ),
        Index( 'idx_proxy_decisions_action', 'action' ),
        Index( 'idx_proxy_decisions_ratification', 'ratification_state' ),
        Index( 'idx_proxy_decisions_created_at', 'created_at' ),
        Index( 'idx_proxy_decisions_domain_category', 'domain', 'category' ),
        Index( 'idx_proxy_decisions_data_origin', 'data_origin' ),
    )

    def __repr__( self ) -> str:
        return f"<ProxyDecision(id={self.id}, domain='{self.domain}', category='{self.category}', action='{self.action}')>"


class TrustState( Base ):
    """
    Trust state snapshot — per-user, per-domain, per-category trust tracking.

    Stores the current trust level and aggregate decision statistics for
    a specific domain+category combination. Updated after each ratification.

    Requires:
        - user_email: User email for multi-user trust isolation
        - domain: Domain identifier
        - category: Decision category

    Ensures:
        - id is automatically generated UUID
        - updated_at tracks last modification
        - circuit_breaker_state stored as JSONB
    """
    __tablename__ = "trust_states"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )

    # Trust context
    user_email: Mapped[str] = mapped_column(
        String( 255 ),
        nullable=False,
        index=True
    )
    domain: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        index=True
    )
    category: Mapped[str] = mapped_column(
        String( 100 ),
        nullable=False,
        index=True
    )

    # Trust metrics
    trust_level: Mapped[int] = mapped_column(
        nullable=False,
        default=1
    )
    total_decisions: Mapped[int] = mapped_column(
        nullable=False,
        default=0
    )
    successful_decisions: Mapped[int] = mapped_column(
        nullable=False,
        default=0
    )
    rejected_decisions: Mapped[int] = mapped_column(
        nullable=False,
        default=0
    )

    # Circuit breaker
    circuit_breaker_state: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )

    # Indexes
    __table_args__ = (
        Index( 'idx_trust_states_user_domain', 'user_email', 'domain' ),
        Index( 'idx_trust_states_category', 'category' ),
        Index( 'idx_trust_states_user_domain_category', 'user_email', 'domain', 'category', unique=True ),
    )

    def __repr__( self ) -> str:
        return f"<TrustState(user={self.user_email}, domain='{self.domain}', category='{self.category}', level={self.trust_level})>"


class PredictionLog( Base ):
    """
    Prediction log — tracks prediction engine predictions alongside actual human responses.

    Each row represents one prediction attempt for a notification. The predicted_value
    is filled at prediction time; actual_value and accuracy fields are filled when
    the human responds.

    Requires:
        - notification_id references a valid notifications row
        - response_type is a valid response type string
        - category is a non-empty string

    Ensures:
        - id is automatically generated UUID
        - predicted_at defaults to current timestamp
        - accuracy_match is null until outcome is recorded
    """
    __tablename__ = "prediction_log"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )

    # Link to notification
    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        ForeignKey( "notifications.id", ondelete="CASCADE" ),
        nullable=False,
        index=True
    )

    # Classification context
    response_type: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        index=True
    )
    category: Mapped[str] = mapped_column(
        String( 100 ),
        nullable=False,
        index=True
    )

    # Prediction output
    predicted_value: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )
    prediction_confidence: Mapped[float] = mapped_column(
        nullable=False,
        default=0.0
    )
    prediction_strategy: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False
    )
    similar_case_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0
    )

    # Actual outcome (filled on response)
    actual_value: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )
    accuracy_match: Mapped[Optional[bool]] = mapped_column(
        nullable=True,
        index=True
    )
    accuracy_detail: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )

    # Timestamps
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )
    responded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )

    # Sender context
    sender_id: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True,
        index=True
    )

    # Indexes
    __table_args__ = (
        Index( 'idx_prediction_log_response_type_category', 'response_type', 'category' ),
        Index( 'idx_prediction_log_predicted_at', 'predicted_at' ),
    )

    def __repr__( self ) -> str:
        return f"<PredictionLog(id={self.id}, type='{self.response_type}', category='{self.category}', match={self.accuracy_match})>"


# ============================================================================
# CJ Flow Persistence Models
# ============================================================================

class JobHistory( Base ):
    """
    Job history model for CJ Flow persistence.

    Tracks the lifecycle of AgenticJobBase jobs (deep_research, podcast,
    claude_code, swe_team, research_to_podcast) through state transitions.

    Requires:
        - id_hash: Scoped job identifier ("{hash}::{user_id}" string from CJ Flow)
        - job_type: Agentic job type identifier
        - user_id: User identifier (VARCHAR, not UUID — matches CJ Flow string-based user IDs)

    Ensures:
        - id_hash is VARCHAR(255) primary key (unique among models — not UUID)
        - status tracks job lifecycle: pending, running, completed, failed, interrupted
        - metadata_json stores rich output: response_text, abstract, report_link, cost_summary, artifacts
        - created_at and updated_at default to current timestamp
        - No foreign key relationships (user_id is a CJ Flow string, not a users.id UUID)
    """
    __tablename__ = "job_history"

    # Primary Key — scoped "{hash}::{user_id}" string from CJ Flow
    id_hash: Mapped[str] = mapped_column(
        String( 255 ),
        primary_key=True
    )

    # Job classification
    job_type: Mapped[str] = mapped_column(
        String( 100 ),
        nullable=False,
        index=True
    )

    # User context (VARCHAR, not UUID FK — matches CJ Flow string-based user IDs)
    user_id: Mapped[str] = mapped_column(
        String( 255 ),
        nullable=False,
        index=True
    )
    user_email: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True
    )
    routing_command: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True
    )

    # Job state
    status: Mapped[str] = mapped_column(
        String( 50 ),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True
    )
    question_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    is_cache_hit: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false"
    )
    duration_seconds: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True
    )

    # Rich metadata (response_text, abstract, report_link, cost_summary, artifacts)
    metadata_json: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )

    # Indexes
    __table_args__ = (
        Index( 'idx_job_history_user_id', 'user_id' ),
        Index( 'idx_job_history_status', 'status' ),
        Index( 'idx_job_history_job_type', 'job_type' ),
        Index( 'idx_job_history_created_at', 'created_at' ),
        Index( 'idx_job_history_user_status', 'user_id', 'status' ),
    )

    def __repr__( self ) -> str:
        return f"<JobHistory(id_hash='{self.id_hash[:20]}...', job_type='{self.job_type}', status='{self.status}')>"


class ServerLifecycle( Base ):
    """
    Single-row server-lifecycle marker for downtime-aware scheduled-job catch-up.

    Records when this server was last known to be available — stamped periodically
    by the clock-loop heartbeat (survives hard kills / OOM) and once more in the
    clean-shutdown ritual (exact final stamp). On startup, mark_interrupted_jobs()
    reads last_available_at to compute the exact downtime window [last_available_at,
    now] and CATCH UP scheduled jobs whose fire time fell inside it, instead of
    dropping them as interrupted (the missed-window bug).

    Requires:
        - key is the fixed singleton string "singleton" (exactly one row per database)

    Ensures:
        - last_available_at is timezone-aware UTC
        - dev (lupin_db_dev) and test (lupin_db_test) are SEPARATE databases, so the
          single row is naturally per-server with no cross-contamination
    """
    __tablename__ = "server_lifecycle"

    key: Mapped[str] = mapped_column(
        String( 32 ),
        primary_key=True
    )
    last_available_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        default=func.now(),
        server_default=func.now()
    )

    def __repr__( self ) -> str:
        return f"<ServerLifecycle(key='{self.key}', last_available_at='{self.last_available_at}')>"


# ============================================================================
# Unified Task Store Models (Phase 1)
# ============================================================================

class TaskItem( Base ):
    """
    Task-store item — one row per obligation (unified task store, Phase 1).

    The single source of truth for fleet owed-work state: arbiter, managers,
    workers, and Rick all read the same rows (design R1/R4). Structural rules
    (receipts on done, chase-ts on blocked) are enforced by task_store_rules
    at the API layer; this model carries the belt-and-suspenders CHECK.

    Canonical design: planning-is-prompting ->
    src/rnd/2026.06.11-unified-task-store-design.md (v0.4) §2.1.

    Requires:
        - item_class: one of task|decision|review_request|bug|gate
          (named item_class at EVERY layer — `class` is a Python reserved
          word; one-name rule, gate-ruled by Tiberius qid c8c73fde)
        - title: non-empty item title
        - project: repo scope (lupin, planning-is-prompting, ...)
        - created_by: persona + session id of the creator

    Ensures:
        - id is automatically generated UUID
        - status defaults to 'queued' (creation event stamps "->queued")
        - blocked_by is a JSONB list of TYPED refs [{kind: item|persona|user, id}]
        - next_chase_ts is non-null whenever status='blocked' (I3, CHECK-enforced)
        - correlation_key is indexed (C1 — poured Phase 1, writer arrives Phase 2)
        - events cascade-delete with the item
    """
    __tablename__ = "task_items"

    # Primary Key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid()
    )

    # Classification
    item_class: Mapped[str] = mapped_column(
        String( 32 ),
        nullable=False,
        index=True
    )
    title: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    body: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )  # decision items carry the framing payload (options, pros/cons, recommendation) here
    project: Mapped[str] = mapped_column(
        String( 255 ),
        nullable=False,
        index=True
    )

    # Ownership (design T1 — real fields, not prose-and-emoji)
    owner_persona: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True,
        index=True
    )
    accountable_manager: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True,
        index=True
    )
    created_by: Mapped[str] = mapped_column(
        String( 255 ),
        nullable=False
    )

    # State
    status: Mapped[str] = mapped_column(
        String( 32 ),
        nullable=False,
        default="queued",
        server_default="queued",
        index=True
    )
    blocked_by: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]"
    )  # typed refs [{kind: item|persona|user, id}] — {kind:user} => oracle treats as NOT-owed
    next_chase_ts: Mapped[Optional[datetime]] = mapped_column(
        DateTime( timezone=True ),
        nullable=True
    )
    gate_class: Mapped[str] = mapped_column(
        String( 32 ),
        nullable=False,
        default="none",
        server_default="none",
        index=True
    )  # Rick's court becomes SELECT ... WHERE gate_class='ricks_court'
    priority: Mapped[str] = mapped_column(
        String( 2 ),
        nullable=False,
        default="P2",
        server_default="P2"
    )

    # Provenance + correlation
    source_qid: Mapped[Optional[str]] = mapped_column(
        String( 64 ),
        nullable=True
    )  # DM question id that spawned the item, if any (T4)
    correlation_key: Mapped[Optional[str]] = mapped_column(
        String( 255 ),
        nullable=True
    )  # harness TodoWrite/TaskList <-> store uuid correlation (C1 upsert key); indexed via __table_args__

    # Timestamps (design names: _ts, not _at)
    created_ts: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )
    updated_ts: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now()
    )  # onupdate is ORM-CLIENT-SIDE only — no DB trigger; a raw-SQL UPDATE
       # will NOT bump this (cold-review N6). Freshness holds only while every
       # writer rides TaskRepository; a future non-ORM writer must bump it
       # explicitly (Phase-2 backlog carries this constraint).

    # Relationships
    events: Mapped[List["TaskEvent"]] = relationship(
        "TaskEvent",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="TaskEvent.id"
    )

    # Indexes + structural CHECK
    __table_args__ = (
        Index( 'idx_task_items_owner_status', 'owner_persona', 'status' ),  # the oracle query shape
        Index( 'idx_task_items_correlation_key', 'correlation_key' ),
        CheckConstraint(
            "status != 'blocked' OR next_chase_ts IS NOT NULL",
            name="ck_task_items_blocked_requires_chase_ts"
        ),
    )

    def __repr__( self ) -> str:
        return f"<TaskItem(id={self.id}, item_class='{self.item_class}', status='{self.status}', owner='{self.owner_persona}')>"


class TaskEvent( Base ):
    """
    Task-store event — append-only per-item audit trail (design R3/T2).

    Every state change writes exactly one event row in the same transaction
    that updates the item. Receipts are first-class: a ->done transition's
    receipt_refs must pass task_store_rules.validate_receipt_refs (T3 — the
    mechanical no-confabulation enforcement).

    Requires:
        - item_id: valid task_items UUID
        - actor: persona + session id performing the transition
        - transition: "from->to" string (creation stamps "->queued")
        - authority: standing|user_direct|manager_relay (blast-radius model)

    Ensures:
        - id is an append-only BIGSERIAL (insertion order == audit order)
        - ts defaults to current timestamp
        - cascades delete when the item is deleted
    """
    __tablename__ = "task_events"

    # Primary Key (append-only BIGSERIAL)
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )

    # Foreign Key to TaskItem
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID( as_uuid=True ),
        ForeignKey( "task_items.id", ondelete="CASCADE" ),
        nullable=False
    )  # indexed via __table_args__ (idx_task_events_item_id)

    # Event Data
    ts: Mapped[datetime] = mapped_column(
        DateTime( timezone=True ),
        nullable=False,
        default=func.now(),
        server_default=func.now()
    )
    actor: Mapped[str] = mapped_column(
        String( 255 ),
        nullable=False
    )
    transition: Mapped[str] = mapped_column(
        String( 64 ),
        nullable=False
    )
    receipt_refs: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True
    )  # {commit, test_run, qid, doc_path, log_line} — non-empty REQUIRED for ->done (T3)
    authority: Mapped[str] = mapped_column(
        String( 32 ),
        nullable=False,
        default="standing",
        server_default="standing"
    )

    # Relationship to TaskItem
    item: Mapped["TaskItem"] = relationship(
        "TaskItem",
        back_populates="events"
    )

    # Indexes
    __table_args__ = (
        Index( 'idx_task_events_item_id', 'item_id' ),
    )

    def __repr__( self ) -> str:
        return f"<TaskEvent(id={self.id}, item_id={self.item_id}, transition='{self.transition}', actor='{self.actor}')>"


def quick_smoke_test():
    """
    Quick smoke test for postgres_models module - validates PostgreSQL ORM model definitions.
    """
    import cosa.utils.util as cu

    cu.print_banner( "PostgreSQL SQLAlchemy ORM Models Smoke Test", prepend_nl=True )

    try:
        # Test 1: Module imports
        print( "Testing module imports..." )
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        print( "✓ SQLAlchemy imports successful" )

        # Test 2: Model classes exist
        print( "Testing model class definitions..." )
        models = [User, RefreshToken, ApiKey, EmailVerificationToken,
                  PasswordResetToken, FailedLoginAttempt, Notification, AuthAuditLog,
                  ProxyDecision, TrustState, PredictionLog, JobHistory, ServerLifecycle,
                  TaskItem, TaskEvent]
        for model in models:
            assert hasattr( model, '__tablename__' ), f"{model.__name__} missing __tablename__"
        print( f"✓ All {len( models )} models defined: {', '.join( [m.__name__ for m in models] )}" )

        # Test 3: Base metadata exists
        print( "Testing Base metadata..." )
        assert hasattr( Base, 'metadata' ), "Base missing metadata"
        table_names = list( Base.metadata.tables.keys() )
        expected_tables = ['users', 'refresh_tokens', 'api_keys', 'email_verification_tokens',
                          'password_reset_tokens', 'failed_login_attempts', 'notifications', 'auth_audit_log',
                          'proxy_decisions', 'trust_states', 'prediction_log', 'job_history',
                          'server_lifecycle', 'task_items', 'task_events']
        assert set( table_names ) == set( expected_tables ), f"Table mismatch: {table_names}"
        print( f"✓ Base metadata contains {len( table_names )} tables" )

        # Test 4: Relationships defined
        print( "Testing ORM relationships..." )
        assert hasattr( User, 'refresh_tokens' ), "User missing refresh_tokens relationship"
        assert hasattr( User, 'api_keys' ), "User missing api_keys relationship"
        assert hasattr( User, 'notifications' ), "User missing notifications relationship"
        assert hasattr( RefreshToken, 'user' ), "RefreshToken missing user relationship"
        assert hasattr( Notification, 'recipient' ), "Notification missing recipient relationship"
        print( "✓ ORM relationships defined correctly" )

        # Test 5: Test PostgreSQL connection and schema validation
        print( "Testing PostgreSQL connection and schema validation..." )
        import os
        from sqlalchemy import text
        db_url = os.environ.get( 'DATABASE_URL', 'postgresql://lupin_dev:dev_password@localhost:5432/lupin_auth' )
        try:
            engine = create_engine( db_url )
            # Test connection
            with engine.connect() as conn:
                result = conn.execute( text( "SELECT 1" ) )
                result.close()
            print( f"✓ PostgreSQL connection successful" )

            # Compare ORM metadata with actual database schema
            from sqlalchemy import inspect
            inspector = inspect( engine )
            db_tables = inspector.get_table_names()
            expected = set( expected_tables )
            actual = set( db_tables )

            if expected.issubset( actual ):
                print( f"✓ All {len( expected_tables )} ORM tables exist in database" )
            else:
                missing = expected - actual
                print( f"⚠ Warning: Tables missing from database: {missing}" )

        except Exception as db_error:
            print( f"⚠ PostgreSQL connection skipped: {db_error}" )
            print( "  (This is OK if database is not running)" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
