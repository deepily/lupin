"""
Unit tests for cosa.config.cache_registry.

Covers AC1.1, AC1.2, AC1.5 from the doc-viewer-scope-unification design.
"""

import threading

import pytest

from cosa.config import cache_registry


@pytest.fixture( autouse=True )
def _clean_registry():
    """Give each test an EMPTY registry, then RESTORE whatever was there before.

    ⚠️ `cache_registry._REGISTRY` is a PROCESS GLOBAL. Real modules self-register
    invalidators into it at IMPORT time (e.g. judge.py registers
    "dm_length_thresholds"), and an import happens once per process — so anything
    this fixture drops and does not put back stays gone for the REST of the suite.

    The old version cleared in teardown and left the registry empty, which wiped
    those real invalidators; any later suite test asserting one is registered then
    failed purely on ORDERING (row 3b5be159: test_dm_length_thresholds_reload
    passed alone, failed after this file ran). Snapshot before, restore after: this
    file's tests still run against a clean, isolated registry, but the global is
    left exactly as it was found — the fixture no longer pollutes downstream tests.
    """
    saved = dict( cache_registry._REGISTRY )         # the real invalidators, by name→fn
    cache_registry._clear_for_tests()
    yield
    cache_registry._clear_for_tests()                # drop anything this test registered
    for name, fn in saved.items():                   # then put the real ones back
        cache_registry.register_invalidator( name, fn )


# ---------------------------------------------------------------------------
# register_invalidator
# ---------------------------------------------------------------------------

def test_register_invalidator_single():
    """Single registration shows up in _registered_names()."""
    cache_registry.register_invalidator( "foo", lambda: None )
    assert cache_registry._registered_names() == [ "foo" ]


def test_register_invalidator_double_replaces():
    """AC1.1: re-registering the same name REPLACES the prior fn."""
    calls = []
    cache_registry.register_invalidator( "foo", lambda: calls.append( "v1" ) )
    cache_registry.register_invalidator( "foo", lambda: calls.append( "v2" ) )

    assert cache_registry._registered_names() == [ "foo" ]

    cache_registry.invalidate_all()
    assert calls == [ "v2" ], "second registration should have replaced first"


def test_register_invalidator_rejects_empty_name():
    with pytest.raises( ValueError ):
        cache_registry.register_invalidator( "", lambda: None )


def test_register_invalidator_rejects_non_callable():
    with pytest.raises( TypeError ):
        cache_registry.register_invalidator( "foo", "not callable" )  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# invalidate_all — happy path
# ---------------------------------------------------------------------------

def test_invalidate_all_calls_each_fn():
    calls = []
    cache_registry.register_invalidator( "a", lambda: calls.append( "a" ) )
    cache_registry.register_invalidator( "b", lambda: calls.append( "b" ) )
    cache_registry.register_invalidator( "c", lambda: calls.append( "c" ) )

    succeeded = cache_registry.invalidate_all()

    assert sorted( calls ) == [ "a", "b", "c" ]
    assert sorted( succeeded ) == [ "a", "b", "c" ]


def test_invalidate_all_returns_empty_when_no_registrations():
    """Empty registry returns empty list, does NOT raise."""
    assert cache_registry.invalidate_all() == []


# ---------------------------------------------------------------------------
# invalidate_all — exception isolation (AC1.2)
# ---------------------------------------------------------------------------

def test_invalidate_all_isolates_exceptions():
    """AC1.2: exception in one fn does NOT prevent others from running."""
    calls = []

    def boom():
        raise RuntimeError( "intentional test failure" )

    cache_registry.register_invalidator( "a", lambda: calls.append( "a" ) )
    cache_registry.register_invalidator( "boom", boom )
    cache_registry.register_invalidator( "c", lambda: calls.append( "c" ) )

    succeeded = cache_registry.invalidate_all()

    # a + c ran; boom did not contribute to calls list
    assert sorted( calls ) == [ "a", "c" ]
    # succeeded list excludes the failing name
    assert sorted( succeeded ) == [ "a", "c" ]
    assert "boom" not in succeeded

    # failure ledger captured the (name, exception) pair
    failures = cache_registry._last_run_failures()
    assert len( failures ) == 1
    failed_name, failed_exc = failures[ 0 ]
    assert failed_name == "boom"
    assert isinstance( failed_exc, RuntimeError )


def test_invalidate_all_resets_failure_ledger_on_each_run():
    def boom():
        raise RuntimeError( "boom" )

    cache_registry.register_invalidator( "boom", boom )
    cache_registry.invalidate_all()
    assert len( cache_registry._last_run_failures() ) == 1

    # Re-register with a passing fn at same name
    cache_registry.register_invalidator( "boom", lambda: None )
    cache_registry.invalidate_all()
    assert cache_registry._last_run_failures() == []


# ---------------------------------------------------------------------------
# invalidate_all — concurrency (AC1.5)
# ---------------------------------------------------------------------------

def test_invalidate_all_no_deadlock_on_reentrant_registration():
    """
    AC1.5: an invalidator that re-registers another invalidator during its
    own run does NOT deadlock. The RLock is reentrant and `invalidate_all`
    releases it before calling fns.
    """
    nested_called = []

    def nested_invalidator():
        nested_called.append( "nested" )

    def reentrant_invalidator():
        # Re-register a different name DURING invalidation. This would
        # deadlock if invalidate_all held the lock while calling fns.
        cache_registry.register_invalidator( "nested", nested_invalidator )

    cache_registry.register_invalidator( "reentrant", reentrant_invalidator )
    succeeded = cache_registry.invalidate_all()

    assert "reentrant" in succeeded
    # nested registration happened during the first run, so it's NOT in
    # this run's snapshot. A subsequent run picks it up.
    assert "nested" not in succeeded

    succeeded_second = cache_registry.invalidate_all()
    assert "nested" in succeeded_second
    assert nested_called == [ "nested" ]


def test_invalidate_all_concurrent_threads():
    """
    AC1.5: concurrent invalidate_all() calls from multiple threads complete
    without deadlock. Tests with 10 threads each calling invalidate_all
    20 times on a registry with 5 invalidators.
    """
    call_count = { "n": 0 }
    count_lock = threading.Lock()

    def counting_invalidator():
        with count_lock:
            call_count[ "n" ] += 1

    for i in range( 5 ):
        cache_registry.register_invalidator( f"cache_{i}", counting_invalidator )

    errors = []

    def worker():
        try:
            for _ in range( 20 ):
                cache_registry.invalidate_all()
        except BaseException as e:
            errors.append( e )

    threads = [ threading.Thread( target=worker ) for _ in range( 10 ) ]
    for t in threads:
        t.start()
    for t in threads:
        t.join( timeout=10.0 )
        assert not t.is_alive(), "Thread did not finish — possible deadlock"

    assert not errors, f"Errors raised in concurrent invalidate_all: {errors}"
    # 10 threads * 20 iters * 5 invalidators = 1000 total calls
    assert call_count[ "n" ] == 10 * 20 * 5


# ---------------------------------------------------------------------------
# Test-helper hygiene
# ---------------------------------------------------------------------------

def test_clear_for_tests_drops_registrations_and_failures():
    cache_registry.register_invalidator( "foo", lambda: None )
    cache_registry.register_invalidator( "bar", lambda: ( _ for _ in () ).throw( RuntimeError( "bang" ) ) )
    cache_registry.invalidate_all()

    assert cache_registry._registered_names() == [ "foo", "bar" ] or \
        cache_registry._registered_names() == [ "bar", "foo" ]
    assert len( cache_registry._last_run_failures() ) == 1

    cache_registry._clear_for_tests()
    assert cache_registry._registered_names() == []
    assert cache_registry._last_run_failures() == []
