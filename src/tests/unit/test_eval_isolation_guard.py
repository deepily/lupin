"""Unit tests for the paired-eval snapshot-table isolation guard.

Proves the guard BOTH fires (refuses an unisolated run) AND lets through (a run
rebound to a dedicated table) — a guard that only ever says no is the same as no
guard. The passes-when-isolated arm uses a synthetic table name that cannot
plausibly be the real one, so the test can never accidentally match production.

A live control (test_resolve_write_target_reads_the_real_orm_table) reads the
ORM's actual __tablename__ so a rename of the shared table is caught here instead
of silently defeating the guard.
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


# A name that cannot plausibly become the real production table.
_SYNTHETIC_ISOLATED = "v2_paired_eval_isolated_DO_NOT_USE_IN_PROD"
_SHARED             = "solution_snapshots"


class _FakeConfig:
    """Minimal ConfigurationManager stand-in: .get( key, default, return_type )."""
    def __init__( self, values ):
        self.values = values
    def get( self, key, default=None, return_type=None ):
        return self.values.get( key, default )


def test_writeback_off_needs_no_isolation():
    cfg = _FakeConfig( { "v2 snapshot writeback enabled": False } )
    # No write happens, so the guard returns None without inspecting the table.
    assert guard.require_isolated_snapshot_table( cfg, write_target=_SHARED ) is None


def test_refuses_when_writeback_on_and_no_isolated_table_configured():
    cfg = _FakeConfig( { "v2 snapshot writeback enabled": True } )   # 'v2 snapshot table' absent — today's state
    with pytest.raises( guard.IsolationNotConfigured ) as exc:
        guard.require_isolated_snapshot_table( cfg, write_target=_SHARED )
    assert "no 'v2 snapshot table'" in str( exc.value )
    assert _SHARED in str( exc.value )


def test_refuses_when_config_set_but_app_still_writes_shared():
    # The false-isolation case: the INI key is set, but the ORM still writes the
    # shared table because the wiring (bug 080821da) does not exist. MUST refuse.
    cfg = _FakeConfig( {
        "v2 snapshot writeback enabled": True,
        "v2 snapshot table"            : _SYNTHETIC_ISOLATED,
    } )
    with pytest.raises( guard.IsolationNotConfigured ) as exc:
        guard.require_isolated_snapshot_table( cfg, write_target=_SHARED )
    assert "isolation is NOT wired" in str( exc.value )


def test_refuses_when_resolving_write_target_live_and_it_is_shared():
    # write_target omitted -> resolved live via resolve_write_target(); today that is
    # the shared table, so an on-writeback run with an isolated cfg still refuses.
    cfg = _FakeConfig( {
        "v2 snapshot writeback enabled": True,
        "v2 snapshot table"            : _SYNTHETIC_ISOLATED,
    } )
    with pytest.raises( guard.IsolationNotConfigured ):
        guard.require_isolated_snapshot_table( cfg )   # live resolve of __tablename__


def test_passes_when_app_write_target_matches_configured_isolated_table():
    # The only path that lets a paired run proceed: the app's live write target IS
    # the configured, synthetic, dedicated isolated table.
    cfg = _FakeConfig( {
        "v2 snapshot writeback enabled": True,
        "v2 snapshot table"            : _SYNTHETIC_ISOLATED,
    } )
    result = guard.require_isolated_snapshot_table( cfg, write_target=_SYNTHETIC_ISOLATED )
    assert result == _SYNTHETIC_ISOLATED


def test_resolve_write_target_reads_the_real_orm_table():
    # Live control: the guard's shared-side source is the ORM attribute the app
    # actually writes through. If the shared table is renamed, this catches it.
    assert guard.resolve_write_target() == _SHARED
