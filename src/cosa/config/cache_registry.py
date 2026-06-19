"""
Generic cache-invalidation registry.

Modules that hold process-lifetime caches (lazy-init singletons, cached
configuration-derived data, etc.) self-register an invalidator function
here at import time. The `/api/init` hot-reload handler calls
`invalidate_all()` after `config_mgr.init()` to flush every registered
cache uniformly.

Design contract:
    - Module-level self-registration via `register_invalidator(name, fn)`
      called at import time (mirrors FastAPI router self-registration
      pattern)
    - `invalidate_all()` snapshots the registry under a `threading.RLock`,
      RELEASES the lock, then calls each invalidator outside the lock
      (avoids deadlock if an invalidator re-enters the registry)
    - Per-fn try/except: exceptions in one invalidator do NOT prevent
      others from running; failed names are tracked internally + logged
      at WARN level
    - Re-registration with the same name REPLACES the prior fn (idempotent
      for hot-reload safety; satisfies AC1.1)

Anchors:
    - Design doc: src/rnd/v0.1.7/2026.05.15-doc-viewer-scope-unification.md §7 Phase 1
    - Pattern source: PredictionEngine.reset() classmethod (the original
      lazy-singleton-reset shape this generalizes)
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, List, Tuple


_REGISTRY     : Dict[ str, Callable[ [], None ] ] = {}
_REGISTRY_LOCK: threading.RLock                   = threading.RLock()

# Names of invalidators whose last call raised; populated by invalidate_all()
# for test inspection. NOT exposed via /api/init payload (per Q5-A: payload
# is List[str] of SUCCEEDED names only).
_LAST_RUN_FAILURES: List[ Tuple[ str, BaseException ] ] = []


def register_invalidator( name: str, fn: Callable[ [], None ] ) -> None:
    """
    Register `fn` as the invalidator callable for the cache named `name`.

    Requires:
        - name is a non-empty string
        - fn is callable taking no arguments
        - safe to call from any thread (RLock-protected)

    Ensures:
        - subsequent `invalidate_all()` calls fn() after config_mgr reload
        - re-registration with the same name REPLACES the previous fn (AC1.1)
        - registration is idempotent in the hot-reload sense: same module
          re-imported (e.g., reload-on-edit during dev) does not duplicate
          the entry
    """
    if not name:
        raise ValueError( "register_invalidator: name must be a non-empty string" )
    if not callable( fn ):
        raise TypeError( f"register_invalidator: fn must be callable, got {type( fn ).__name__}" )

    with _REGISTRY_LOCK:
        _REGISTRY[ name ] = fn


def invalidate_all() -> List[ str ]:
    """
    Call every registered invalidator. Return list of names that succeeded.

    Requires:
        - safe to call from any thread (RLock-protected during snapshot only)

    Ensures:
        - returns List[str] of names whose invalidator returned cleanly
        - exceptions in one invalidator do NOT prevent others from running
          (AC1.2)
        - failed (name, exception) pairs stored in _LAST_RUN_FAILURES for
          test inspection; also printed at WARN level
        - registry snapshot is taken under lock; fns are called OUTSIDE the
          lock to avoid deadlock if an invalidator re-enters the registry
          (AC1.5)
    """
    global _LAST_RUN_FAILURES

    with _REGISTRY_LOCK:
        snapshot = list( _REGISTRY.items() )

    succeeded: List[ str ]                              = []
    failed   : List[ Tuple[ str, BaseException ] ]      = []

    for name, fn in snapshot:
        try:
            fn()
            succeeded.append( name )
        except BaseException as e:
            failed.append( ( name, e ) )
            print( f"[cache_registry] WARN: invalidator {name!r} raised {type( e ).__name__}: {e}" )

    _LAST_RUN_FAILURES = failed
    return succeeded


def _registered_names() -> List[ str ]:
    """Test-only: return registered cache names (snapshot)."""
    with _REGISTRY_LOCK:
        return list( _REGISTRY.keys() )


def _clear_for_tests() -> None:
    """Test-only: drop every registered invalidator and the failure ledger.

    Tests should call this in a fixture teardown to prevent cross-test
    pollution. NOT for production use.
    """
    global _LAST_RUN_FAILURES
    with _REGISTRY_LOCK:
        _REGISTRY.clear()
    _LAST_RUN_FAILURES = []


def _last_run_failures() -> List[ Tuple[ str, BaseException ] ]:
    """Test-only: return the failure ledger from the most recent invalidate_all() call."""
    return list( _LAST_RUN_FAILURES )
