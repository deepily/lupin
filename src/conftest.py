"""
Root pytest config shared by BOTH test trees under `src/`:
  - the Lupin `src/tests/` tree, and
  - the in-tree CoSA `src/cosa/tests/` tree.

This file exists for ONE cross-tree test-isolation guard (see the fixture below).
Keep it minimal — tree-specific fixtures belong in `src/tests/conftest.py` /
`src/cosa/tests/...conftest.py`, not here.
"""

import sys

import pytest


@pytest.fixture( autouse=True )
def _evict_real_fastapi_main_after_test():
    """
    Cross-file test-isolation guard (2026-06-03 Gate-Zero finding).

    Many router / auth tests import the REAL `fastapi_app.main` at module load (to
    build a TestClient against the live app). That import persists in `sys.modules`
    AND sets `main` as an attribute on the `fastapi_app` package object. The PARENT
    ATTRIBUTE is the trap: `import fastapi_app.main as m` resolves it (not the
    `sys.modules['fastapi_app.main']` entry), so a later test's
    `patch.dict(sys.modules, {"fastapi_app.main": <fake>})` is silently defeated —
    the code under test gets the real, un-started module whose `config_mgr` /
    `jobs_todo_queue` are None, and fails depending ONLY on suite run-order.

    Evicting after every test makes each test start able to mock `fastapi_app.main`
    cleanly, regardless of which earlier test imported the real app. Tests that
    legitimately use the real app hold their own module-level `app` reference, which
    is a live object unaffected by this `sys.modules` eviction.

    Ensures:
        - after each test, `sys.modules['fastapi_app.main']` is removed (if present)
        - after each test, the `fastapi_app.main` parent-package attribute is removed
          (if present), so it cannot shadow a future `sys.modules` patch
    """
    yield
    sys.modules.pop( "fastapi_app.main", None )
    pkg = sys.modules.get( "fastapi_app" )
    if pkg is not None and hasattr( pkg, "main" ):
        delattr( pkg, "main" )
