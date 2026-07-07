"""
Repository pattern implementation for PostgreSQL ORM.

Exports all repository classes for clean imports:
    from cosa.rest.db.repositories import UserRepository, RefreshTokenRepository

Each repository provides CRUD operations for its corresponding model.

LAZY re-exports (PEP 562, bug 1b8ec2b9): the names below resolve on first access
via `__getattr__` instead of being eagerly imported at package load. This keeps
`import cosa.rest.db.repositories` (and a bare `importlib.util.find_spec` on any
SUBMODULE of this package) side-effect-light — it no longer drags in the whole
SQLAlchemy ORM stack. That matters because coverage's `--cov=<dotted.module>`
resolver (coverage.inorout.set_matchers_depending_on_syspath) calls
`find_spec("cosa.rest.db.repositories.task_repository")` INSIDE a
`sys_modules_saved()` block; the old eager `__init__` loaded ~400 modules
(SQLAlchemy included) there, and the block's bulk `del sys.modules[...]` on exit
partially evicted SQLAlchemy, so a later re-import re-ran its declarative +
dialect registration and tripped `AssertionError: Type <class 'object'> is
already registered` at collection. With lazy re-exports the resolver imports only
this lightweight package, nothing gets evicted, and the eager `--cov=<module>`
coverage form collects clean. The public API is UNCHANGED — `from
cosa.rest.db.repositories import UserRepository` still works (IMPORT_FROM falls
through to `__getattr__`), and direct submodule imports
(`from cosa.rest.db.repositories.user_repository import UserRepository`) were
never affected.
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
    PEP 562 lazy attribute resolver — import the owning submodule on first access
    of a re-exported repository class, then bind it on the package so subsequent
    lookups are plain attribute reads.

    Requires:
        - name is the attribute being accessed on this package

    Ensures:
        - a name in _LAZY_EXPORTS -> the class object, imported from its submodule
          and cached as a package attribute (idempotent)
        - any other name -> AttributeError (so a genuine submodule import, e.g.
          `from cosa.rest.db.repositories import vector_store_backend`, still falls
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
