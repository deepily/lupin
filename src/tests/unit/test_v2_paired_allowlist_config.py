"""Unit test: the paired-eval SAFETY allowlist is CORRECTLY SCOPED in the real INI (bug 080821da).

VENUE: :7999 — pure config reads, no server, no DB.

WHY THIS EXISTS. The SAFETY guard (require_isolated_snapshot_table) is fail-closed on the
`v2 eval permitted snapshot stores` allowlist. Two things must hold, and this test PINS both so
they survive a revert:

  1. SCOPING — the allowlist is populated ONLY in [Lupin: Testing] (the :8000 paired-run block).
     It stays EMPTY in [Lupin: Baseline], so [Lupin: Development] and [Lupin: Production] INHERIT
     the empty default and can never permit a live store. If someone moves the value up into
     Baseline (making dev/prod permissive), the dev/prod assertions here go RED — that is the
     mismatch control Tiberius required.

  2. REFUSE-LIVE — under the real Testing allowlist, the guard PERMITS the two isolated
     measurement stores (lupin_db_test / lupin_db_v1baseline) and REFUSES lupin_db_dev. The
     refuse-live case is pinned so the guard's proof survives: a config change that let
     lupin_db_dev through would fail this test.

The allowlist is read from the REAL src/conf/lupin-app.ini (not a fake config), so these are
config-integration controls: they fail on an INI revert, which a fake-config unit test cannot.
"""

import os

import pytest

# The guard lives under src/scripts, not on the default test path.
import sys
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SCRIPTS = os.path.join( _LUPIN_ROOT, "src", "scripts" )
    if _SCRIPTS not in sys.path:
        sys.path.insert( 0, _SCRIPTS )

import eval_isolation_guard as guard   # noqa: E402
from cosa.config.configuration_manager import ConfigurationManager   # noqa: E402


_CONFIG_PATH   = os.path.join( _LUPIN_ROOT or "", "src", "conf", "lupin-app.ini" )
_SPLAINER_PATH = os.path.join( _LUPIN_ROOT or "", "src", "conf", "lupin-app-splainer.ini" )

_ISOLATED = { "lupin_db_test.solution_snapshots", "lupin_db_v1baseline.solution_snapshots" }


def _load_block( block_id: str ) -> ConfigurationManager:
    """Load the REAL INI for one block, resetting the singleton so each block reads clean."""
    return ConfigurationManager(
        config_path     = _CONFIG_PATH,
        splainer_path   = _SPLAINER_PATH,
        config_block_id = block_id,
        silent          = True,
        mute_splainer   = True,
        _reset_singleton = True,
    )


def _allowlist( config_mgr ) -> set:
    """The parsed allowlist the SAFETY guard would use, from this block's resolved value."""
    return guard.parse_permitted_stores(
        config_mgr.get( guard.PERMITTED_STORES_KEY, default=None, return_type="string" )
    )


@pytest.mark.skipif( not _LUPIN_ROOT, reason="Requires LUPIN_ROOT to locate the real INI" )
@pytest.mark.parametrize( "block_id", [ "Lupin: Baseline", "Lupin: Development", "Lupin: Production" ] )
def test_allowlist_empty_in_baseline_dev_prod( block_id ):
    """SCOPING: the allowlist is EMPTY in Baseline and INHERITED-empty in dev/prod — no live store
    can ever be permitted there. Goes RED if the value is moved up into Baseline (mismatch control)."""
    assert _allowlist( _load_block( block_id ) ) == set()


@pytest.mark.skipif( not _LUPIN_ROOT, reason="Requires LUPIN_ROOT to locate the real INI" )
def test_allowlist_populated_only_in_testing():
    """SCOPING: [Lupin: Testing] overrides the allowlist with EXACTLY the two isolated measurement
    stores — nothing more, nothing less. Goes RED if the override is dropped or widened."""
    assert _allowlist( _load_block( "Lupin: Testing" ) ) == _ISOLATED


@pytest.mark.skipif( not _LUPIN_ROOT, reason="Requires LUPIN_ROOT to locate the real INI" )
def test_testing_guard_permits_isolated_stores():
    """Under the real Testing config, SAFETY PERMITS each isolated store (writeback on + member)."""
    config_mgr = _load_block( "Lupin: Testing" )
    for database in ( "lupin_db_test", "lupin_db_v1baseline" ):
        permitted = guard.require_isolated_snapshot_table(
            config_mgr, write_target="solution_snapshots", write_database=database,
        )
        assert permitted == f"{database}.solution_snapshots"


@pytest.mark.skipif( not _LUPIN_ROOT, reason="Requires LUPIN_ROOT to locate the real INI" )
def test_testing_guard_refuses_live_dev_store():
    """REFUSE-LIVE (pinned): under the real Testing config, SAFETY REFUSES lupin_db_dev — a live
    store is never permitted, even in the block where the allowlist is populated. Goes RED if
    lupin_db_dev.solution_snapshots is ever added to the allowlist."""
    config_mgr = _load_block( "Lupin: Testing" )
    with pytest.raises( guard.IsolationNotConfigured ):
        guard.require_isolated_snapshot_table(
            config_mgr, write_target="solution_snapshots", write_database="lupin_db_dev",
        )


@pytest.mark.skipif( not _LUPIN_ROOT, reason="Requires LUPIN_ROOT to locate the real INI" )
def test_dev_guard_refuses_any_store_empty_allowlist():
    """SCOPING consequence: with the empty inherited allowlist, [Lupin: Development] REFUSES even an
    otherwise-isolated store — fail-closed. Proves dev did not inherit a permissive allowlist."""
    config_mgr = _load_block( "Lupin: Development" )
    with pytest.raises( guard.IsolationNotConfigured ):
        guard.require_isolated_snapshot_table(
            config_mgr, write_target="solution_snapshots", write_database="lupin_db_test",
        )
