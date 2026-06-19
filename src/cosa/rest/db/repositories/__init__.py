"""
Repository pattern implementation for PostgreSQL ORM.

Exports all repository classes for clean imports:
    from cosa.rest.db.repositories import UserRepository, RefreshTokenRepository

Each repository provides CRUD operations for its corresponding model.
"""

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.db.repositories.user_repository import UserRepository
from cosa.rest.db.repositories.refresh_token_repository import RefreshTokenRepository
from cosa.rest.db.repositories.api_key_repository import ApiKeyRepository
from cosa.rest.db.repositories.email_verification_token_repository import EmailVerificationTokenRepository
from cosa.rest.db.repositories.password_reset_token_repository import PasswordResetTokenRepository
from cosa.rest.db.repositories.failed_login_attempt_repository import FailedLoginAttemptRepository
from cosa.rest.db.repositories.auth_audit_log_repository import AuthAuditLogRepository
from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository, TrustStateRepository

__all__ = [
    "BaseRepository",
    "UserRepository",
    "RefreshTokenRepository",
    "ApiKeyRepository",
    "EmailVerificationTokenRepository",
    "PasswordResetTokenRepository",
    "FailedLoginAttemptRepository",
    "AuthAuditLogRepository",
    "ProxyDecisionRepository",
    "TrustStateRepository",
]
