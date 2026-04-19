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


# ──────────────────────────────────────────────────────────────────
# 2026-04-19 fix: when proposed.changes is empty, fall back to
# cluster.affected_files_guess. Validated via tfe-a1c6e15a post-game
# where every TFE proposal had empty `changes` → everything fell
# through to `medium` instead of matching the correct tier.
# ──────────────────────────────────────────────────────────────────


def _cluster( files: list ) -> SimpleNamespace:
    return SimpleNamespace( affected_files_guess=files )


def test_cluster_fallback_single_file_test_patch_is_small():
    # Proposed with empty changes, but cluster says 1 file → small
    assert TFEOrchestrator._derive_budget_tier(
        _fix( "test_patch", 0 ),
        cluster=_cluster( [ "src/tests/unit/test_x.py" ] ),
    ) == "small"


def test_cluster_fallback_five_files_is_large():
    # Proposed with empty changes, cluster says 5 files → large
    assert TFEOrchestrator._derive_budget_tier(
        _fix( "test_patch", 0 ),
        cluster=_cluster( [ f"f{i}.py" for i in range( 5 ) ] ),
    ) == "large"


def test_cluster_fallback_two_files_is_medium():
    assert TFEOrchestrator._derive_budget_tier(
        _fix( "code_patch", 0 ),
        cluster=_cluster( [ "a.py", "b.py" ] ),
    ) == "medium"


def test_proposed_changes_preferred_over_cluster():
    # When proposed.changes is populated, it wins even if cluster disagrees
    assert TFEOrchestrator._derive_budget_tier(
        _fix( "test_patch", 1 ),
        cluster=_cluster( [ f"f{i}.py" for i in range( 5 ) ] ),
    ) == "small"


def test_cluster_none_defaults_to_medium_when_changes_empty():
    # No cluster passed, empty changes → medium (original behavior)
    assert TFEOrchestrator._derive_budget_tier(
        SimpleNamespace( fix_type="code_patch", changes=[] ),
        cluster=None,
    ) == "medium"


def test_cluster_with_no_affected_files_guess_attribute_is_medium():
    # Defensive: cluster exists but missing the attribute
    cluster = SimpleNamespace()  # no affected_files_guess
    assert TFEOrchestrator._derive_budget_tier(
        _fix( "test_patch", 0 ),
        cluster=cluster,
    ) == "medium"


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
