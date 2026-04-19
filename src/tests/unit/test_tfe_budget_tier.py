"""
Unit tests for TFE Coder turn-budget tier derivation (Option A, 2026-04-18).

Exercises the pure `_derive_budget_tier` staticmethod on TFEOrchestrator.
Mirrors the rules documented in
`src/rnd/v0.1.6/2026.04.18-tfe-coder-turn-budget-option-a.md`.

Tier rule:
    small   — single-file test_patch or config_change
    large   — 4+ affected files
    medium  — everything else (defensive fallback included)

No SDK imports are required for this test module — we exercise the
staticmethod via its fully qualified path and pass plain namespace
objects (not full TFEProposedFix pydantic models) so the tests stay
fast and side-effect-free.
"""

from types import SimpleNamespace

from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator


def _fix( fix_type: str, n_files: int ) -> SimpleNamespace:
    """Build a minimal proposal-like object for tier derivation tests."""
    return SimpleNamespace(
        fix_type = fix_type,
        changes  = [ { "file": f"f{i}.py" } for i in range( n_files ) ],
    )


def test_single_file_test_patch_is_small():
    assert TFEOrchestrator._derive_budget_tier( _fix( "test_patch", 1 ) ) == "small"


def test_single_file_config_change_is_small():
    assert TFEOrchestrator._derive_budget_tier( _fix( "config_change", 1 ) ) == "small"


def test_single_file_code_patch_is_medium():
    assert TFEOrchestrator._derive_budget_tier( _fix( "code_patch", 1 ) ) == "medium"


def test_three_file_test_patch_is_medium():
    assert TFEOrchestrator._derive_budget_tier( _fix( "test_patch", 3 ) ) == "medium"


def test_five_file_test_patch_is_large():
    assert TFEOrchestrator._derive_budget_tier( _fix( "test_patch", 5 ) ) == "large"


def test_four_file_code_patch_is_large():
    assert TFEOrchestrator._derive_budget_tier( _fix( "code_patch", 4 ) ) == "large"


def test_empty_changes_is_medium():
    assert TFEOrchestrator._derive_budget_tier(
        SimpleNamespace( fix_type="code_patch", changes=[] )
    ) == "medium"


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
