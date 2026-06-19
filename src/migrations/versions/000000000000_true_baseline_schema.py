"""true_baseline_schema

Revision ID: 000000000000
Revises:
Create Date: 2026-06-17

TRUE baseline migration ZERO (D7 hybrid ruling — TODO.md "Alembic TRUE baseline
migration"). This migration ENCODES THE ORIGIN of ``src/scripts/sql/schema.sql``
as the first link in the chain, so a fresh / empty database is brought fully up
to head with ``alembic upgrade head`` ALONE — retiring the former bootstrap
workaround (``schema.sql`` if empty  ->  ``alembic stamp e9f0a1b2c3d4``  ->
``alembic upgrade head``).

WHY this migration exists
-------------------------
Before this baseline the chain's true base was ``210acf4d54dd`` whose
``upgrade()`` is a NO-OP (``pass``); the nine base tables were seeded entirely
by ``schema.sql`` out-of-band. The intermediate migrations between that no-op
base and ``e9f0a1b2c3d4`` are NOT runnable from an empty DB (e.g.
``62ec6f256d27`` references ``notifications`` columns — ``is_hidden`` /
``abstract`` — that no migration in the chain ever creates), which is precisely
why the stamp-then-upgrade workaround was required. The OFFICIAL bootstrap
(verified 13 tables on fresh Cloud-SQL, TODO.md) stamps at ``e9f0a1b2c3d4`` —
which SKIPS that entire pre-baseline span — then runs ``upgrade head``.

This baseline reproduces that proven behavior: its ``upgrade()`` emits the exact
DDL of ``schema.sql`` (the nine tables the stamp recipe leaves in place), and the
post-baseline chain (``f0a1b2c3d4e5`` -> ... -> head) is rebased directly onto it.
Net result is BEHAVIORALLY EQUIVALENT to the documented recipe, with no stamp
step. The eight absorbed pre-baseline revisions (``210acf4d54dd`` ..
``e9f0a1b2c3d4``) are retired into this single baseline.

The DDL below is a verbatim copy of ``src/scripts/sql/schema.sql`` as of this
revision (kept inline so the migration is self-contained and never depends on a
file path being present in the deployment image's bind-mount).

Stamp-compatibility (one-time reconciliation)
---------------------------------------------
A steady-state alembic-managed DB is at the head (``d4e5f6a7b8c9``) — its
``alembic_version`` is unchanged by this rebase, so ``upgrade head`` is a no-op
and NOTHING needs to be done. The only DB that needs attention is one frozen
EXACTLY at a now-removed revision (most plausibly ``e9f0a1b2c3d4`` — i.e. it was
stamped but ``upgrade head`` was never run). For that rare transient case, run
ONCE before upgrading:

    UPDATE alembic_version SET version_num = '000000000000'
        WHERE version_num IN (
            '210acf4d54dd','275fb8d9c75c','62ec6f256d27','a3b4c5d6e7f8',
            'b5c6d7e8f9a0','c7d8e9f0a1b2','d8e9f0a1b2c3','e9f0a1b2c3d4'
        );

Such a DB already carries the ``schema.sql`` tables, so mapping it to this
baseline (whose ``upgrade()`` is a no-op against it thanks to ``IF NOT EXISTS``)
and then running ``upgrade head`` applies only the genuine post-baseline deltas.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '000000000000'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Verbatim copy of src/scripts/sql/schema.sql (PostgreSQL). Every CREATE uses
# IF NOT EXISTS, so this baseline is a safe no-op against a DB that already
# carries the schema.sql tables (the one-time reconciliation case above).
_SCHEMA_SQL = """
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table: users
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    email_verified BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    roles JSONB DEFAULT '["user"]'::jsonb,
    last_login_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_users_roles ON users USING GIN (roles);

-- Table: refresh_tokens
CREATE TABLE IF NOT EXISTS refresh_tokens (
    jti UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMP WITH TIME ZONE,
    user_agent TEXT,
    ip_address INET,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_revoked ON refresh_tokens(revoked) WHERE revoked = FALSE;

-- Table: api_keys
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    key_hash VARCHAR(64) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_is_active ON api_keys(is_active);

-- Table: email_verification_tokens
CREATE TABLE IF NOT EXISTS email_verification_tokens (
    token VARCHAR(255) PRIMARY KEY,
    user_id UUID NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_email_verification_user_id ON email_verification_tokens(user_id);

-- Table: password_reset_tokens
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token VARCHAR(255) PRIMARY KEY,
    user_id UUID NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_password_reset_user_id ON password_reset_tokens(user_id);

-- Table: failed_login_attempts
CREATE TABLE IF NOT EXISTS failed_login_attempts (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    ip_address INET NOT NULL,
    attempt_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_failed_login_email ON failed_login_attempts(email);
CREATE INDEX IF NOT EXISTS idx_failed_login_attempt_time ON failed_login_attempts(attempt_time);

-- Table: notifications (sender-aware notification system)
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_id VARCHAR(255) NOT NULL,
    recipient_id UUID NOT NULL,
    title VARCHAR(255),
    message TEXT NOT NULL,
    type VARCHAR(50) NOT NULL,
    priority VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMP WITH TIME ZONE,
    responded_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    response_requested BOOLEAN DEFAULT FALSE,
    response_type VARCHAR(50),
    response_value JSONB,
    response_default VARCHAR(255),
    timeout_seconds BIGINT,
    state VARCHAR(50) NOT NULL DEFAULT 'created',
    FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notifications_sender_id ON notifications(sender_id);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient_id ON notifications(recipient_id);
CREATE INDEX IF NOT EXISTS idx_notifications_state ON notifications(state);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_sender_recipient ON notifications(sender_id, recipient_id);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);

-- Table: auth_audit_log
CREATE TABLE IF NOT EXISTS auth_audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    user_id UUID,
    email VARCHAR(255),
    ip_address INET,
    details JSONB,
    success BOOLEAN DEFAULT TRUE,
    event_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_event_type ON auth_audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_auth_audit_user_id ON auth_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_audit_event_time ON auth_audit_log(event_time);

-- Table: job_history (CJ Flow Persistence)
CREATE TABLE IF NOT EXISTS job_history (
    id_hash             VARCHAR(255)    PRIMARY KEY,
    job_type            VARCHAR(100)    NOT NULL,
    user_id             VARCHAR(255)    NOT NULL,
    user_email          VARCHAR(255),
    session_id          VARCHAR(255),
    routing_command     VARCHAR(255),
    status              VARCHAR(50)     NOT NULL DEFAULT 'pending',
    question_text       TEXT,
    error               TEXT,
    is_cache_hit        BOOLEAN         DEFAULT FALSE,
    duration_seconds    FLOAT,
    metadata_json       JSONB,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMP WITH TIME ZONE,
    completed_at        TIMESTAMP WITH TIME ZONE,
    updated_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_history_user_id ON job_history(user_id);
CREATE INDEX IF NOT EXISTS idx_job_history_status ON job_history(status);
CREATE INDEX IF NOT EXISTS idx_job_history_job_type ON job_history(job_type);
CREATE INDEX IF NOT EXISTS idx_job_history_created_at ON job_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_history_user_status ON job_history(user_id, status);
"""


# Tables created by _SCHEMA_SQL, listed in reverse foreign-key dependency order
# for a clean downgrade (every dependent dropped before its parent `users`).
_BASELINE_TABLES = [
    "notifications",
    "refresh_tokens",
    "api_keys",
    "email_verification_tokens",
    "password_reset_tokens",
    "failed_login_attempts",
    "auth_audit_log",
    "job_history",
    "users",
]


def upgrade() -> None:
    """Build the baseline schema (verbatim schema.sql DDL).

    Ensures:
        - the nine base tables (users, refresh_tokens, api_keys,
          email_verification_tokens, password_reset_tokens,
          failed_login_attempts, notifications, auth_audit_log, job_history)
          and their indexes exist
        - idempotent: every statement uses IF NOT EXISTS, so re-running against
          a DB that already carries these tables is a safe no-op
    """
    op.execute( _SCHEMA_SQL )


def downgrade() -> None:
    """Drop the baseline schema.

    Ensures:
        - all nine baseline tables are removed (CASCADE clears FK-dependent
          objects); dropped in reverse FK order for clarity
        - the chain can be walked back to ``base`` cleanly
    """
    for table in _BASELINE_TABLES:
        op.execute( f"DROP TABLE IF EXISTS {table} CASCADE;" )
