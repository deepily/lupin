#!/usr/bin/env python3
"""
Import-hygiene guard for the DB packages (bug 1b8ec2b9).

The pre-existing failure: `pytest --cov=cosa.rest.db.repositories.task_repository`
(the obvious per-module coverage-gate invocation) tripped a collection ERROR —
`AssertionError: Type <class 'object'> is already registered` — because coverage's
source resolver (coverage.inorout.set_matchers_depending_on_syspath) calls
`importlib.util.find_spec(<dotted module>)` INSIDE a `sys_modules_saved()` block.
find_spec imports the target's PARENT packages; the old eager `__init__` files
(`cosa.rest.db` re-exporting database.get_db/engine/SessionLocal, and
`cosa.rest.db.repositories` re-exporting all 8 repo classes) dragged the whole
SQLAlchemy ORM stack (~400 modules) into that block. The block's bulk
`del sys.modules[...]` on exit then partially evicted SQLAlchemy, so a later
re-import re-ran its declarative + dialect registration and crashed at collection.

The fix made both package `__init__`s lazy (PEP 562 `__getattr__`) so a spec lookup
imports only the lightweight package, never the ORM. These tests pin that invariant
(RED-first: they fail on the pre-fix eager tree) AND that the public re-export API
is preserved (regression-guard: those passed pre-fix too, they prove the lazy
refactor didn't break `from cosa.rest.db... import Name`).

Venue :7999 (subprocess spawns a clean interpreter / a scoped pytest; no shared
state mutated). 100% of the changed __init__ lines are exercised here.
"""
import os
import subprocess
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


def _clean_env():
    """A child-process env with LUPIN_ROOT + src on PYTHONPATH (mirrors the harness)."""
    root = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    env  = dict( os.environ )
    env[ "LUPIN_ROOT" ] = root
    env[ "PYTHONPATH" ] = os.path.join( root, "src" ) + os.pathsep + env.get( "PYTHONPATH", "" )
    return root, env


# ---------------------------------------------------------------------------
# RED-first: the spec-lookup invariant (the actual bug mechanism)
# ---------------------------------------------------------------------------

def test_find_spec_on_repository_module_imports_no_sqlalchemy():
    """
    find_spec on a repositories SUBMODULE must NOT import SQLAlchemy — a spec
    lookup imports parent packages, and those must stay side-effect-light. RED on
    the pre-fix eager __init__ tree (find_spec pulled ~140 sqlalchemy modules).
    Runs in a FRESH interpreter so the ambient (already-imported) sqlalchemy of the
    test process can't mask the regression.
    """
    _root, env = _clean_env()
    code = (
        "import sys, importlib.util;"
        "importlib.util.find_spec('cosa.rest.db.repositories.task_repository');"
        "print(len([m for m in sys.modules if m.startswith('sqlalchemy')]))"
    )
    out = subprocess.run( [ sys.executable, "-c", code ], env=env, capture_output=True, text=True )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "0", f"find_spec imported sqlalchemy: {out.stdout!r}"


def test_importing_db_packages_imports_no_sqlalchemy():
    """
    A bare `import cosa.rest.db` / `import cosa.rest.db.repositories` must not pull
    SQLAlchemy either (the package __init__s are lazy). Fresh interpreter. RED on
    the pre-fix eager tree.
    """
    _root, env = _clean_env()
    code = (
        "import sys, cosa.rest.db, cosa.rest.db.repositories;"
        "print(len([m for m in sys.modules if m.startswith('sqlalchemy')]))"
    )
    out = subprocess.run( [ sys.executable, "-c", code ], env=env, capture_output=True, text=True )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "0", f"package import pulled sqlalchemy: {out.stdout!r}"


def test_eager_cov_module_form_collects_clean():
    """
    The end-to-end regression: the exact invocation that reproduced bug 1b8ec2b9 —
    `--cov=<dotted.module>` — must now COLLECT without the SQLAlchemy
    double-registration error. `--collect-only` is enough (the crash was at
    collection) and keeps this fast. RED on the pre-fix tree (1 error during
    collection); GREEN after.
    """
    root, env = _clean_env()
    out = subprocess.run(
        [ sys.executable, "-m", "pytest",
          "src/tests/unit/test_task_repository.py",
          "--cov=cosa.rest.db.repositories.task_repository",
          "--collect-only", "-q", "-p", "no:cacheprovider" ],
        cwd=root, env=env, capture_output=True, text=True,
    )
    combined = out.stdout + out.stderr
    assert "already registered" not in combined, combined
    assert "error during collection" not in combined, combined
    assert out.returncode == 0, combined


# ---------------------------------------------------------------------------
# Regression-guard: the lazy refactor preserves the public re-export API
# (these passed pre-fix too — they prove __getattr__ didn't break consumers)
# ---------------------------------------------------------------------------

def test_db_package_reexports_resolve():
    import cosa.rest.db as db
    from cosa.rest.db.database import get_db as direct_get_db
    assert db.get_db is direct_get_db                        # lazy __getattr__ returns the real object
    assert db.engine is not None and db.SessionLocal is not None
    assert set( db.__all__ ) == { "get_db", "engine", "SessionLocal" }


def test_db_package_unknown_attr_raises_attributeerror():
    import cosa.rest.db as db
    with pytest.raises( AttributeError ):
        _ = db.does_not_exist                                # __getattr__ falls through cleanly


def test_repositories_package_reexports_resolve():
    from cosa.rest.db.repositories import UserRepository, TrustStateRepository, ProxyDecisionRepository
    from cosa.rest.db.repositories.user_repository import UserRepository as DirectUserRepo
    assert UserRepository is DirectUserRepo
    # Two names sourced from the SAME submodule both resolve (proxy_decision_repository)
    assert TrustStateRepository.__name__ == "TrustStateRepository"
    assert ProxyDecisionRepository.__name__ == "ProxyDecisionRepository"


def test_repositories_package_unknown_attr_raises_attributeerror():
    import cosa.rest.db.repositories as repos
    with pytest.raises( AttributeError ):
        _ = repos.NotARepository


def test_repositories_package_dir_lists_lazy_names():
    import cosa.rest.db.repositories as repos
    assert "UserRepository" in dir( repos ) and "BaseRepository" in dir( repos )


def test_db_package_dir_lists_lazy_names():
    import cosa.rest.db as db
    assert "get_db" in dir( db ) and "SessionLocal" in dir( db )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
