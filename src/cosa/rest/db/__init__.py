"""
Database package for PostgreSQL ORM and repository pattern.

Exports:
    - get_db: Context manager for database sessions
    - engine: SQLAlchemy engine with connection pooling
    - SessionLocal: Session factory
    - Base: Declarative base from postgres_models

LAZY re-exports (PEP 562, bug 1b8ec2b9): get_db / engine / SessionLocal resolve on
first access via `__getattr__` instead of being eagerly imported at package load,
so `import cosa.rest.db` (and coverage's `find_spec` on ANY submodule of this
package, e.g. `cosa.rest.db.repositories.task_repository`) no longer drags in
`cosa.rest.db.database` and the whole SQLAlchemy stack. That eager import was one
of the two parent-package side effects that made coverage's `--cov=<dotted.module>`
resolver load + partially-evict SQLAlchemy inside its `sys_modules_saved()` block,
tripping `AssertionError: Type <class 'object'> is already registered` at
collection (see cosa/rest/db/repositories/__init__.py for the full mechanism). The
package-level re-export has ZERO current consumers (all 107 call sites import
straight from `cosa.rest.db.database`), so this is behavior-preserving; the lazy
form keeps the documented API working for any future `from cosa.rest.db import
get_db` caller.
"""

import importlib

# name -> submodule the name lives in (single source of truth for the lazy map)
_LAZY_EXPORTS = { "get_db": "database", "engine": "database", "SessionLocal": "database" }

__all__ = list( _LAZY_EXPORTS.keys() )


def __getattr__( name ):
    """
    PEP 562 lazy attribute resolver — import `database` on first access of a
    re-exported name, then cache it as a package attribute.

    Requires:
        - name is the attribute being accessed on this package

    Ensures:
        - a name in _LAZY_EXPORTS -> the object imported from cosa.rest.db.database,
          cached on the package (idempotent; engine/SessionLocal stay singletons —
          database.py is imported at most once)
        - any other name -> AttributeError (a genuine submodule import such as
          `from cosa.rest.db import vector_store_models` still resolves normally)
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
