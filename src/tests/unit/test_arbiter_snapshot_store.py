#!/usr/bin/env python3
"""
Unit tests for arbiter_snapshot_store — the server-side fleet-snapshot cache
behind GET /api/arbiter/fleet-snapshot (arbiter design `03` §10.4, C2).
100% line+branch+function coverage.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.arbiter_snapshot_store as store


@pytest.fixture( autouse=True )
def _clean():
    store.clear_snapshot()
    yield
    store.clear_snapshot()


def test_get_is_none_before_any_push():
    assert store.get_snapshot() is None


def test_set_then_get():
    store.set_snapshot( { "session_count": 2, "sessions": [ ] } )
    assert store.get_snapshot()[ "session_count" ] == 2


def test_last_writer_wins():
    store.set_snapshot( { "session_count": 2 } )
    store.set_snapshot( { "session_count": 9 } )
    assert store.get_snapshot()[ "session_count" ] == 9


def test_clear_resets_to_none():
    store.set_snapshot( { "session_count": 1 } )
    store.clear_snapshot()
    assert store.get_snapshot() is None


def test_set_none_is_allowed():
    store.set_snapshot( { "x": 1 } )
    store.set_snapshot( None )
    assert store.get_snapshot() is None


def test_quick_smoke_test():
    assert store.quick_smoke_test() is True


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
