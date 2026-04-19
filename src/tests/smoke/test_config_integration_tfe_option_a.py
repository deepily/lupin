"""
Smoke test: TFE Option A config integration.

Verifies that the new INI keys added for Option A (auto-tiered Coder turn
budget) actually propagate from lupin-app.ini → ConfigurationManager →
TestFixExpediterConfig. Catches the silent-fallback-to-dataclass-default
class of misconfig (e.g., typo in key_map that would silently use the
built-in 30/50/80 defaults even if the INI said otherwise).

Also verifies the 2026-04-18 `cosa worktree auto cleanup = false` flip
is actually applied.

Filed 2026-04-18 Session be57a252.
"""

import os

import pytest


@pytest.fixture( scope="module" )
def config_mgr():
    """Fresh ConfigurationManager pointed at the real project INI."""
    os.environ[ "LUPIN_CONFIG_MGR_CLI_ARGS" ] = (
        "config_path=/src/conf/lupin-app.ini "
        "splainer_path=/src/conf/lupin-app-splainer.ini "
        "config_block_id=Lupin:+Baseline"
    )
    from cosa.config.configuration_manager import ConfigurationManager
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


@pytest.fixture( scope="module" )
def tfe_config( config_mgr ):
    from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
    return TestFixExpediterConfig.from_config( config_mgr )


class TestTFEOptionAConfig:

    def test_coder_budget_small_turns_matches_ini( self, tfe_config ):
        # INI: `test fix expediter coder budget small turns = 50`
        # Bumped 2026-04-19 from 30 after tfe-a1c6e15a ran short.
        # If this breaks, the key_map wiring in config.py is wrong.
        assert tfe_config.coder_budget_small_turns == 50, (
            f"Expected 50 from INI; got {tfe_config.coder_budget_small_turns} "
            f"(likely silent fallback to dataclass default — check key_map)"
        )

    def test_coder_budget_medium_turns_matches_ini( self, tfe_config ):
        # Bumped 2026-04-19 from 50 → 80.
        assert tfe_config.coder_budget_medium_turns == 80

    def test_coder_budget_large_turns_matches_ini( self, tfe_config ):
        # Bumped 2026-04-19 from 80 → 150.
        assert tfe_config.coder_budget_large_turns == 150

    def test_all_three_tiers_strictly_ascending( self, tfe_config ):
        # Sanity: small < medium < large. A flipped pair would be a silent
        # misconfig that confuses budget selection.
        assert tfe_config.coder_budget_small_turns < tfe_config.coder_budget_medium_turns
        assert tfe_config.coder_budget_medium_turns < tfe_config.coder_budget_large_turns


class TestCosaWorktreeConfig:

    def test_worktree_enabled( self, config_mgr ):
        assert config_mgr.get( "cosa worktree enabled", return_type="boolean" ) is True

    def test_worktree_auto_cleanup_is_false( self, config_mgr ):
        # This key was flipped to False on 2026-04-18 per user directive
        # ("There's no point in doing the work just to throw it away").
        # If this regresses to True, preserved worktrees will silently
        # vanish at Phase 5 exit again.
        assert config_mgr.get( "cosa worktree auto cleanup", return_type="boolean" ) is False, (
            "cosa worktree auto cleanup must be False (preserve). "
            "If this regresses to True, preserved worktrees vanish at Phase 5 exit."
        )


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
