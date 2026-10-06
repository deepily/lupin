"""
Repository pattern implementation for PostgreSQL ORM.

Exports all repository classes for clean imports:
    from cosa.rest.db.repositories import UserRepository, RefreshTokenRepository

Each repository provides CRUD operations for its corresponding model.

The re-exports are lazy (`PEP 562`): each name resolves on first access via `__getattr__`, not at package load.
So `import cosa.rest.db.repositories`, and `find_spec` on any submodule, stays light and does not import the
SQLAlchemy ORM stack. That matters because coverage's `--cov=<dotted.module>` resolver calls `find_spec` inside
a `sys_modules_saved()` block, which on exit deletes modules from `sys.modules`. An eager `__init__` loaded about
400 modules there. The partial eviction of SQLAlchemy made a later re-import fail at collection with
`AssertionError: Type <class 'object'> is already registered`. With lazy exports nothing gets evicted.
The public API is unchanged: `from cosa.rest.db.repositories import UserRepository` still works, and direct
submodule imports were never affected.
"""

import importlib

# name -> submodule the name lives in (the single source of truth for the lazy map)
_LAZY_EXPORTS = {
    "BaseRepository"                   : "base",
    "UserRepository"                   : "user_repository",
    "RefreshTokenRepository"           : "refresh_token_repository",
    "ApiKeyRepository"                 : "api_key_repository",
    "EmailVerificationTokenRepository" : "email_verification_token_repository",
    "PasswordResetTokenRepository"     : "password_reset_token_repository",
    "FailedLoginAttemptRepository"     : "failed_login_attempt_repository",
    "AuthAuditLogRepository"           : "auth_audit_log_repository",
    "ProxyDecisionRepository"          : "proxy_decision_repository",
    "TrustStateRepository"             : "proxy_decision_repository",
}

__all__ = list( _LAZY_EXPORTS.keys() )


def __getattr__( name ):
    """
    Resolve a re-exported repository class on first access (`PEP 562` lazy attribute).

    Requires:
        - name is the attribute being accessed on this package

    Ensures:
        - a name in _LAZY_EXPORTS -> the class object, imported from its submodule
          and cached as a package attribute (idempotent)
        - any other name -> AttributeError (so a genuine submodule import, e.g.
          `from cosa.rest.db.repositories import vector_search`, still falls
          through to the normal submodule-import machinery)
    """
    submodule = _LAZY_EXPORTS.get( name )
    if submodule is None:
        raise AttributeError( f"module {__name__!r} has no attribute {name!r}" )
    value = getattr( importlib.import_module( f".{submodule}", __name__ ), name )
    globals()[ name ] = value                                # cache — next access skips __getattr__
    return value


def __dir__():
    """Expose the lazy names to dir()/autocomplete alongside the real attributes."""
    return sorted( set( globals() ) | set( _LAZY_EXPORTS ) )
