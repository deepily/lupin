"""
Backwards-compatibility shim — PlanWriter moved to cosa.agents.shared.plan_writer.

Session 1cfcdf73 (2026-04-10) extracted PlanWriter into the shared/ package
so BugFixExpediter and TestFixExpediter can both use it without contaminating
each other's agent-specific code paths. This shim preserves the old import
path for backwards compatibility with existing test files and any external
code that imports from cosa.agents.bug_fix_expediter.plan_writer.

See: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/02-fix-executor-extraction-plan.md
"""

from cosa.agents.shared.plan_writer import PlanWriter, quick_smoke_test

__all__ = [ "PlanWriter", "quick_smoke_test" ]


if __name__ == "__main__":
    quick_smoke_test()
