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


# Generous on purpose. These children take ~1-6s unloaded; the cap exists to convert a
# HANG into a message, not to police latency. Tight enough that a wedged child cannot
# stall the suite, loose enough that a merely-busy box never trips it.
_CHILD_TIMEOUT_SECONDS = 300


def _run_child( argv, env, cwd=None, what="child process" ):
    """
    Run a child and return its CompletedProcess — or fail with a message that says
    TIMED OUT and nothing else.

    WHY THIS EXISTS (bug 4938a829, Rachel 2026-07-21). Every test in this file shells out
    to a fresh interpreter or a nested pytest, and none of them used to pass a `timeout=`
    — `pytest-timeout` is not installed either, so there was no ambient backstop. A child
    starved, OOM-killed or wedged under box load surfaced as a bare non-zero returncode
    with possibly-empty output, through the SAME assertion a real regression trips.

    That is fatal for `test_eager_cov_module_form_collects_clean` specifically, because
    that test's entire job is to be the regression oracle for bug 1b8ec2b9 ("RED on the
    pre-fix tree; GREEN after"). An oracle that also goes RED because the box was busy
    cannot answer the only question it is asked. Row 1ec38d18 caught it doing exactly
    that: RED in one of two SIMULTANEOUS full-suite runs, green in three solo runs of the
    same tree, same commit.

    So the two outcomes are made distinguishable IN THE FAILURE TEXT, which is all a
    future reader gets: a timeout says TIMED OUT and names the load hypothesis; a real
    regression says what it always said. Never fold the two into one message again.
    """
    try:
        return subprocess.run( argv, env=env, cwd=cwd, capture_output=True, text=True,
                               timeout=_CHILD_TIMEOUT_SECONDS )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"TIMED OUT after {_CHILD_TIMEOUT_SECONDS}s waiting for {what} — this is a LOAD "
            f"symptom, NOT evidence of the regression this test guards. Re-run on a quiet box "
            f"before filing anything. (Concurrent full suites on one machine: rows 1ec38d18, "
            f"84db12a0, 4ae91da3.)"
        )


# ---------------------------------------------------------------------------
# The timeout path, FIRED ON PURPOSE (bug 4938a829)
# ---------------------------------------------------------------------------

def test_run_child_reports_a_timeout_as_a_timeout_not_as_a_regression( monkeypatch ):
    """
    A hard-fail that has never fired once is a hard-fail nobody knows works.

    This is the whole point of the row: the failure TEXT must distinguish "the box was
    busy" from "the regression came back", because that text is all a future reader gets.
    So the timeout is provoked against a deliberately-slow child and the message asserted
    — both that it SAYS timed out, and that it does NOT wear the vocabulary of the real
    regression it sits next to.
    """
    monkeypatch.setattr( sys.modules[ __name__ ], "_CHILD_TIMEOUT_SECONDS", 1 )
    _root, env = _clean_env()

    # `pytest.fail` raises `Failed`, which derives from BaseException — NOT Exception. A
    # `pytest.raises( Exception )` here does not catch it, and the timeout then propagates
    # as this test's own failure: the mechanism fires correctly and the test reports RED
    # anyway. Caught on the first run of this very test, which is the argument for firing
    # a hard-fail on purpose rather than trusting that it would have worked.
    with pytest.raises( pytest.fail.Exception ) as exc:
        _run_child( [ sys.executable, "-c", "import time; time.sleep(30)" ], env,
                    what="deliberately slow child" )

    message = str( exc.value )
    assert "TIMED OUT"                in message
    assert "deliberately slow child"  in message, "the message must name WHICH child hung"
    assert "LOAD symptom"             in message
    assert "already registered"   not in message, "a timeout must not borrow the regression's vocabulary"


def test_run_child_returns_the_completed_process_when_the_child_behaves( ):
    """The negative control: the wrapper is a pass-through on the happy path, not a filter."""
    _root, env = _clean_env()
    out = _run_child( [ sys.executable, "-c", "print('ok')" ], env, what="fast child" )
    assert out.returncode == 0
    assert out.stdout.strip() == "ok"


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
    out = _run_child( [ sys.executable, "-c", code ], env, what="find_spec probe interpreter" )
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
    out = _run_child( [ sys.executable, "-c", code ], env, what="package-import probe interpreter" )
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
    out = _run_child(
        [ sys.executable, "-m", "pytest",
          "src/tests/unit/test_task_repository.py",
          "--cov=cosa.rest.db.repositories.task_repository",
          "--collect-only", "-q", "-p", "no:cacheprovider" ],
        env, cwd=root, what="nested pytest --collect-only child",
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
