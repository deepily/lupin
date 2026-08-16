"""Unit tests for the paired-eval snapshot-store isolation guard (two checks).

VENUE: :7999 — pure, injected sources, no server, no DB.

Two must-fail CONTROLS carry the SAFETY check, one per direction the old table-name-only
predicate got wrong:
  · test_safety_refuses_a_shared_db_write — the old guard ALLOWED a shared-db write (it
    only compared table names); the new one refuses the fully-qualified dev.solution_snapshots.
  · test_safety_allows_same_table_in_an_isolated_db — the old guard BLOCKED a genuinely
    isolated different-database write with the same table name; the new one allows it.
Each goes red on the old predicate, for the right reason (the database half of the identity).
"""

import os
import sys

import pytest

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SCRIPTS = os.path.join( _LUPIN_ROOT, "src", "scripts" )
    if _SCRIPTS not in sys.path:
        sys.path.insert( 0, _SCRIPTS )

import eval_isolation_guard as guard   # noqa: E402


_SHARED_TABLE = "solution_snapshots"                     # the ORM shipped default table
_SHARED_DEV   = "lupin_db_dev.solution_snapshots"        # the LIVE shared store (never permitted)
_ISO_DEDICATED = "lupin_db_test.v2_paired_snapshots"     # a dedicated isolated store
_ISO_SAME_TABLE = "lupin_db_test.solution_snapshots"     # same table name, ISOLATED by database


class _FakeConfig:
    """Minimal ConfigurationManager stand-in: .get( key, default, return_type )."""
    def __init__( self, values ):
        self.values = values
    def get( self, key, default=None, return_type=None ):
        return self.values.get( key, default )


def _cfg( *, writeback=True, allowlist=None ):
    values = { "v2 snapshot writeback enabled": writeback }
    if allowlist is not None:
        values[ guard.PERMITTED_STORES_KEY ] = allowlist
    return _FakeConfig( values )


# ---------------------------------------------------------------------------
# helpers: parse / db-name / fully-qualified
# ---------------------------------------------------------------------------
def test_parse_permitted_stores_variants():
    assert guard.parse_permitted_stores( None ) == set()
    assert guard.parse_permitted_stores( "   " ) == set()
    assert guard.parse_permitted_stores( "a.b" ) == { "a.b" }
    assert guard.parse_permitted_stores( " a.b , c.d ,, " ) == { "a.b", "c.d" }


def test_db_name_strips_leading_slash_and_ignores_query_fragment():
    assert guard._db_name( "postgresql://u:p@h/lupin_db_test?sslmode=require" ) == "lupin_db_test"
    assert guard._db_name( "postgresql://u:p@h/lupin_db_dev#/lupin_db_test" ) == "lupin_db_dev"


def test_fully_qualified_joins_db_and_table():
    assert guard.fully_qualified( "lupin_db_test", "solution_snapshots" ) == "lupin_db_test.solution_snapshots"


# ---------------------------------------------------------------------------
# SAFETY — require_isolated_snapshot_table
# ---------------------------------------------------------------------------
def test_writeback_off_needs_no_isolation():
    cfg = _cfg( writeback=False )
    # No write happens, so the guard returns None without inspecting the destination.
    assert guard.require_isolated_snapshot_table( cfg, write_target=_SHARED_TABLE, write_database="lupin_db_dev" ) is None


def test_fail_closed_when_allowlist_is_empty_or_absent():
    # Writeback ON, no allowlist configured -> the destination cannot be PROVEN non-live.
    cfg = _cfg( allowlist=None )
    with pytest.raises( guard.IsolationNotConfigured ) as exc:
        guard.require_isolated_snapshot_table( cfg, write_target=_SHARED_TABLE, write_database="lupin_db_test" )
    assert "allowlist is empty" in str( exc.value )
    # An explicitly blank allowlist is the same fail-closed refusal.
    cfg_blank = _cfg( allowlist="   " )
    with pytest.raises( guard.IsolationNotConfigured ):
        guard.require_isolated_snapshot_table( cfg_blank, write_target=_SHARED_TABLE, write_database="lupin_db_test" )


def test_safety_refuses_a_shared_db_write():
    """MUST-FAIL CONTROL (direction 1). The app would write dev.solution_snapshots — a LIVE
    store. The OLD table-name-only guard, with its isolated cfg set to 'solution_snapshots',
    passed this (table == table). The new guard refuses the fully-qualified destination."""
    cfg = _cfg( allowlist=_ISO_DEDICATED )
    with pytest.raises( guard.IsolationNotConfigured ) as exc:
        guard.require_isolated_snapshot_table( cfg, write_target=_SHARED_TABLE, write_database="lupin_db_dev" )
    assert "NOT in the permitted" in str( exc.value ) and _SHARED_DEV in str( exc.value )


def test_safety_allows_same_table_in_an_isolated_db():
    """MUST-FAIL CONTROL (direction 2). Same table name 'solution_snapshots' but in the
    ISOLATED lupin_db_test database. The OLD table-name-only guard BLOCKED this (table ==
    shared name, != a synthetic isolated cfg). The new guard ALLOWS it — the db isolates."""
    cfg = _cfg( allowlist=_ISO_SAME_TABLE )
    result = guard.require_isolated_snapshot_table( cfg, write_target=_SHARED_TABLE, write_database="lupin_db_test" )
    assert result == _ISO_SAME_TABLE


def test_safety_allows_a_dedicated_isolated_store():
    cfg = _cfg( allowlist=f"{_ISO_DEDICATED}, {_ISO_SAME_TABLE}" )
    result = guard.require_isolated_snapshot_table( cfg, write_target="v2_paired_snapshots", write_database="lupin_db_test" )
    assert result == _ISO_DEDICATED


def test_resolve_write_target_reads_the_real_orm_table():
    # Live control: the guard's table source is the ORM attribute the app writes through.
    # A rename of the shared table is caught here instead of silently defeating the guard.
    assert guard.resolve_write_target() == _SHARED_TABLE


# ---------------------------------------------------------------------------
# VALIDITY — require_arms_distinct_and_clean
# ---------------------------------------------------------------------------
def test_validity_passes_when_arms_are_distinct_and_clean():
    result = guard.require_arms_distinct_and_clean(
        "lupin_db_v1baseline.solution_snapshots", "lupin_db_test.solution_snapshots",
        v1_rowcount=0, v2_rowcount=0,
    )
    assert result == ( "lupin_db_v1baseline.solution_snapshots", "lupin_db_test.solution_snapshots" )


def test_validity_refuses_when_arms_share_a_destination():
    with pytest.raises( guard.PairedTargetsNotIsolated ) as exc:
        guard.require_arms_distinct_and_clean( _ISO_SAME_TABLE, _ISO_SAME_TABLE, v1_rowcount=0, v2_rowcount=0 )
    assert "SAME destination" in str( exc.value )


def test_validity_refuses_when_a_destination_is_dirty():
    with pytest.raises( guard.PairedTargetsNotIsolated ) as exc:
        guard.require_arms_distinct_and_clean( "db1.t", "db2.t", v1_rowcount=5, v2_rowcount=0 )
    assert "START CLEAN" in str( exc.value ) and "db1.t" in str( exc.value )


def test_validity_names_both_dirty_arms():
    with pytest.raises( guard.PairedTargetsNotIsolated ) as exc:
        guard.require_arms_distinct_and_clean( "db1.t", "db2.t", v1_rowcount=3, v2_rowcount=7 )
    msg = str( exc.value )
    assert "db1.t" in msg and "db2.t" in msg
