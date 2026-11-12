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

from cosa.utils.lazy_exports import lazy_exports

# name -> submodule the name lives in (single source of truth for the lazy map)
_LAZY_EXPORTS = { "get_db": "database", "engine": "database", "SessionLocal": "database" }

__all__ = list( _LAZY_EXPORTS.keys() )


__getattr__, __dir__ = lazy_exports( __name__, globals(), _LAZY_EXPORTS )
