-- PostgreSQL schema for Lupin database
-- Created: 2025-11-17
-- Database: lupin_db

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
    response_options JSONB,
    timeout_seconds BIGINT,
    state VARCHAR(50) NOT NULL DEFAULT 'created',
    -- Routing / content / soft-delete columns added by migration e5f6a7b8c9d0
    -- (migration<->ORM drift fix). The companion direction/sender_persona/
    -- sender_icon/reply_to/thread_id columns are added by migration
    -- c3d4e5f6a7b8 (NOT redeclared here).
    job_id VARCHAR(256),
    progress_group_id VARCHAR(24),
    abstract TEXT,
    is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notifications_sender_id ON notifications(sender_id);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient_id ON notifications(recipient_id);
CREATE INDEX IF NOT EXISTS idx_notifications_state ON notifications(state);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_sender_recipient ON notifications(sender_id, recipient_id);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);
CREATE INDEX IF NOT EXISTS idx_notifications_job_id ON notifications(job_id);
CREATE INDEX IF NOT EXISTS idx_notifications_progress_group_id ON notifications(progress_group_id);
CREATE INDEX IF NOT EXISTS idx_notifications_is_hidden ON notifications(is_hidden);

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

-- ============================================================================
-- Decision-proxy + prediction + server-lifecycle tables.
-- Added by migration e5f6a7b8c9d0 (migration<->ORM drift fix). These four
-- tables previously existed in deployed DBs only because the app-boot
-- auto-migrator bootstraps via Base.metadata.create_all; the migration chain
-- now creates them so a pure `alembic upgrade head` reaches ORM parity.
-- Maps to ProxyDecision / TrustState / PredictionLog / ServerLifecycle in
-- src/cosa/rest/postgres_models.py.
-- ============================================================================

-- Table: proxy_decisions
CREATE TABLE IF NOT EXISTS proxy_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id VARCHAR(255) NOT NULL,
    domain VARCHAR(50) NOT NULL,
    category VARCHAR(100) NOT NULL,
    question TEXT NOT NULL,
    sender_id VARCHAR(255),
    action VARCHAR(50) NOT NULL,
    decision_value TEXT,
    confidence FLOAT,
    trust_level INTEGER NOT NULL,
    reason TEXT,
    ratification_state VARCHAR(50) NOT NULL DEFAULT 'not_required',
    ratified_by VARCHAR(255),
    ratified_at TIMESTAMP WITH TIME ZONE,
    ratification_feedback TEXT,
    metadata_json JSONB,
    data_origin VARCHAR(50) NOT NULL DEFAULT 'organic',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proxy_decisions_domain ON proxy_decisions(domain);
CREATE INDEX IF NOT EXISTS idx_proxy_decisions_category ON proxy_decisions(category);
CREATE INDEX IF NOT EXISTS idx_proxy_decisions_action ON proxy_decisions(action);
CREATE INDEX IF NOT EXISTS idx_proxy_decisions_ratification ON proxy_decisions(ratification_state);
CREATE INDEX IF NOT EXISTS idx_proxy_decisions_created_at ON proxy_decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_proxy_decisions_domain_category ON proxy_decisions(domain, category);
CREATE INDEX IF NOT EXISTS idx_proxy_decisions_data_origin ON proxy_decisions(data_origin);

-- Table: trust_states
CREATE TABLE IF NOT EXISTS trust_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email VARCHAR(255) NOT NULL,
    domain VARCHAR(50) NOT NULL,
    category VARCHAR(100) NOT NULL,
    trust_level INTEGER NOT NULL,
    total_decisions INTEGER NOT NULL,
    successful_decisions INTEGER NOT NULL,
    rejected_decisions INTEGER NOT NULL,
    circuit_breaker_state JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trust_states_user_domain ON trust_states(user_email, domain);
CREATE INDEX IF NOT EXISTS idx_trust_states_category ON trust_states(category);
CREATE UNIQUE INDEX IF NOT EXISTS idx_trust_states_user_domain_category ON trust_states(user_email, domain, category);

-- Table: prediction_log
CREATE TABLE IF NOT EXISTS prediction_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID NOT NULL,
    response_type VARCHAR(50) NOT NULL,
    category VARCHAR(100) NOT NULL,
    predicted_value JSONB,
    prediction_confidence FLOAT NOT NULL,
    prediction_strategy VARCHAR(50) NOT NULL,
    similar_case_count INTEGER NOT NULL,
    actual_value JSONB,
    accuracy_match BOOLEAN,
    accuracy_detail JSONB,
    predicted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    responded_at TIMESTAMP WITH TIME ZONE,
    sender_id VARCHAR(255),
    FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_prediction_log_response_type_category ON prediction_log(response_type, category);
CREATE INDEX IF NOT EXISTS idx_prediction_log_predicted_at ON prediction_log(predicted_at);

-- Table: server_lifecycle (single-row downtime marker)
CREATE TABLE IF NOT EXISTS server_lifecycle (
    key VARCHAR(32) PRIMARY KEY,
    last_available_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_job_history_user_status ON job_history(user_id, status);
