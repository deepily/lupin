"""
Dry-run smoke test wrapper for the SWE Team Orchestrator.

Delegates to the inline quick_smoke_test() at orchestrator.py:1292 which
tests creation, state management, progress calculation, dry-run execution,
and stop request — all using MockAgentSDKSession (no LLM, no server).

Created: 2026-02-17 (Session 221 — Smoke Test Coverage Audit)
Converted to Pattern A: 2026-02-17 (Session 222 — Consistency Cleanup)
"""

from cosa.agents.swe_team.orchestrator import quick_smoke_test


def test_swe_team_orchestrator_dry_run():
    """Pytest entry point — delegates to source module QST."""
    quick_smoke_test()


if __name__ == "__main__":
    quick_smoke_test()
