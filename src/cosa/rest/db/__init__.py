"""
Database package for PostgreSQL ORM and repository pattern.

Exports:
    - get_db: Context manager for database sessions
    - engine: SQLAlchemy engine with connection pooling
    - SessionLocal: Session factory
    - Base: Declarative base from postgres_models

The three names are re-exported lazily through the module `__getattr__` hook: get_db, engine and
SessionLocal resolve on first access, not at package load. So `import cosa.rest.db`,
and coverage's `find_spec` on any submodule such as
`cosa.rest.db.repositories.task_repository`, never imports `cosa.rest.db.database`
or SQLAlchemy. An eager import made coverage's `--cov=<dotted.module>` resolver load
and partly evict SQLAlchemy, which raised `AssertionError: Type <class 'object'> is
already registered` at collection (see cosa/rest/db/repositories/__init__.py).
No code imports the names from the package today; all call sites import from
`cosa.rest.db.database`. The lazy form keeps `from cosa.rest.db import get_db` working.
"""

import importlib

# name -> submodule the name lives in (single source of truth for the lazy map)
_LAZY_EXPORTS = { "get_db": "database", "engine": "database", "SessionLocal": "database" }

__all__ = list( _LAZY_EXPORTS.keys() )


def __getattr__( name ):
    """
    Import `database` on first access of a re-exported name and cache the name.

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
