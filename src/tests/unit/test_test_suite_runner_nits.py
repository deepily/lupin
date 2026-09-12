#!/usr/bin/env python3
"""
Runner-infrastructure guards for the three all-suite nits filed off baseline
ts-b51e63c9 (io/test-suite/2026.06.12-at-06:40-EDT-all-results.md):

  1. Unit-leg timeout: the 180s budget killed the grown (~6745-test) unit
     suite at exactly 180.0s (observed full runtime ~185s). The budget must
     carry real headroom over the observed runtime.
  2. Smoke-leg venue routing: run-smoke-tests.sh routes by folder, so the
     DESTRUCTIVE :8000-venue test_proxy_integration.py rode along and blew
     the smoke leg to 3806.9s. The script must --ignore it (the test itself
     is untouched — it keeps its own scheduled invocation).
  3. Integration DB cleaner: clean_test_db's TRUNCATE list predates the
     tables landed 2026-06-12 — task-store (task_items/task_events,
     migration f0a1b2c3d4e5) and FCM (fcm_tokens, migration a1b2c3d4e5f6;
     ruled in by Tiberius, same defect class) — rows written by their
     integration tests would leak across tests.

These are infra surfaces (a constant, a shell script, a fixture's SQL), so
the guards pin source text / module constants rather than runtime behavior.

Venue: :7999-eligible / local — pure reads, sub-second.
"""
import os
import re
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.test_suite.job import ALL_SUITE_COMPONENTS, SUITE_TIMEOUTS_SECONDS

# Observed leg wall-clocks on ts-b51e63c9 (2026-06-12). Budgets must clear
# these with margin, not merely exceed them. The 1.4x floor tracks the house
# margin norm (~1.44-1.48x on the 2026-04-21 smoke/integration bumps); the
# e2e entry pins Tiffany's F1 review finding (2400s was only 1.19x).
_OBSERVED_RUNTIMES_SECONDS = {
    "unit" : 185,
    # 2026-09-11 (row 1657a852): 2020.6 -> 3038.1. The old figure dated from 2026-06-12 and went
    # stale in lockstep with the budget it guards — by 09-10 the suite took longer than its own
    # 3000s cap and a full run was killed at ~87%, while this guard still passed, because it was
    # comparing the new budget against a three-month-old runtime. A guard that vouches for a
    # budget it has never measured against is worse than no guard: it reads as a check.
    # 2026-09-11, SAME DAY, CORRECTED 3038.1 -> 2992.7 — one MEASURED run replacing two added ones.
    # 3038.1 was the sum of two halves (ts-6979205f 1549.0s + ts-0dee4535 1491.1s, less one ~2.0s
    # overhead copy) and it was overstated by ~50s: the halves were a partition over FILES, not
    # over EXECUTIONS. The four src/tests/parity_oracle files are named EXPLICITLY on the runner's
    # command line, and an explicitly-named path SURVIVES --ignore, so half A's --ignore on them was
    # inert and their 25 tests ran in BOTH halves.
    # 🔴 THE UNIT IS JOB DURATION, NOT JUnit testsuite@time. They differ (2992.7 vs 2990.0 on this
    # run) and only one of them is the right comparand: the budget is enforced at job.py:1485 against
    # `time.monotonic() - start_time` wrapped around the runner subprocess, so the guard's `budget >=
    # 1.4 x observed` is only apples-to-apples if observed is that same clock. Putting testsuite@time
    # here would understate the thing being capped by the per-run overhead every time.
    # 2992.7s is ts-cf9f5f85, a single uninterrupted full run through /api/test-suite/submit.
    # JUnit e2e-junit-20260912-002204.xml, 830 distinct tests, 5 locator-timeout reds costing 118.5s.
    # HALVES AND WHOLE AGREE TO WITHIN NOISE — not exactly, and the distinction matters. Corrected
    # halves 3038.1 - 50.0 = 2988.1s vs 2992.7s measured: +4.6s, 0.15%. That is INSIDE the whole-suite
    # run-to-run band, which is 2.05% (+/-61s at this size) measured over five full runs inside ~2
    # days on 08-21/08-22, where suite growth cannot explain the spread. So the honest claim is
    # "indistinguishable at this precision", NOT "equal": +4.6s is a difference this instrument cannot
    # resolve, and a real state-accumulation penalty smaller than ~60s would hide inside it.
    # ⚠️ There are no repeated FULL runs from 2026-09-11, so that band is August's box, not tonight's.
    # What IS settled is that no LARGE once-vs-twice effect exists — that was an open assumption under
    # the 5000s budget, and a bound is what it now has.
    # The BUDGET is unaffected: 1.4 x (2992.7 + 485 growth) = 4868.8, still 5000.
    "e2e"  : 2992.7,
}
_MIN_TIMEOUT_MARGIN = 1.4


def _repo_root():
    return os.environ.get( "LUPIN_ROOT", os.getcwd() )


def _read( rel_path ):
    with open( os.path.join( _repo_root(), rel_path ), encoding="utf-8" ) as f:
        return f.read()


class TestSuiteTimeoutHeadroom:

    @pytest.mark.parametrize( "suite", sorted( _OBSERVED_RUNTIMES_SECONDS ) )
    def test_timeout_has_headroom_over_observed_runtime( self, suite ):
        """Nit (a) + review F1: a budget below the observed runtime kills the
        leg mid-run (unit died at exactly 180.0s); every leg with an observed
        baseline runtime must carry >= 1.4x margin over it."""
        observed = _OBSERVED_RUNTIMES_SECONDS[ suite ]
        budget   = SUITE_TIMEOUTS_SECONDS[ suite ]
        assert budget >= observed * _MIN_TIMEOUT_MARGIN, (
            f"'{suite}' budget {budget}s is under {_MIN_TIMEOUT_MARGIN}x the "
            f"observed {observed}s (ts-b51e63c9)"
        )

    def test_every_all_suite_component_has_explicit_timeout( self ):
        """Each leg of the expanded all-suite must have its own budget — a
        missing entry silently falls back to the 600s default."""
        missing = [ s for s in ALL_SUITE_COMPONENTS if s not in SUITE_TIMEOUTS_SECONDS ]
        assert missing == [ ], f"ALL_SUITE_COMPONENTS without explicit timeout: {missing}"


class TestSmokeLegExcludesDestructiveProxyTest:

    def test_run_smoke_tests_sh_ignores_proxy_integration( self ):
        """Nit (b): the smoke leg's pytest invocation must deselect the destructive
        :8000-venue proxy suite BEFORE caller args (folder is not a venue
        marker — CLAUDE.md § TESTING VENUES).

        ⚠️ The pattern used to be anchored on `^exec `, which pinned it to HOW the script
        launches pytest rather than to the deselection it is guarding. Row 73c6819d had to
        drop the exec — an exec'd shell cannot read pytest's exit code, and on a conftest
        collection error that code is the only signal that exists. The ordering assertion
        (`--ignore` ahead of `"$@"`, so a caller cannot re-select the destructive suite by
        accident) is unchanged, which is the part that was ever load-bearing.
        """
        script     = _read( "src/tests/run-smoke-tests.sh" )
        invocation = re.search(
            r"^(?!#).*src/tests/smoke/ "
            r"--ignore=src/tests/smoke/test_proxy_integration\.py "
            r'"\$@"',
            script,
            flags=re.MULTILINE
        )
        assert invocation is not None, (
            "run-smoke-tests.sh must invoke pytest with "
            "--ignore=src/tests/smoke/test_proxy_integration.py ahead of \"$@\""
        )

    def test_proxy_integration_test_itself_untouched( self ):
        """The exclusion is routing-only: the destructive suite stays in place
        for its own scheduled :8000 invocation."""
        assert os.path.isfile(
            os.path.join( _repo_root(), "src/tests/smoke/test_proxy_integration.py" )
        )


class TestCleanTestDbTruncatesNewTables:

    def test_truncate_list_includes_2026_06_12_tables( self ):
        """Nit (c) + Tiberius's fcm_tokens ruling: the clean_test_db TRUNCATE
        statement must name every table landed on 2026-06-12 — task-store
        (migration f0a1b2c3d4e5) and FCM (migration a1b2c3d4e5f6)."""
        conftest = _read( "src/tests/integration/conftest.py" )
        truncate = re.search( r"TRUNCATE TABLE[\s\S]*?\)", conftest )
        assert truncate is not None, "clean_test_db TRUNCATE statement not found"
        for table in ( "task_items", "task_events", "fcm_tokens" ):
            assert table in truncate.group( 0 ), \
                f"clean_test_db TRUNCATE list missing {table}"

    def test_every_table_with_a_foreign_key_to_task_items_is_truncated_with_it( self ):
        """
        Postgres refuses to TRUNCATE a table another table references unless both are
        named. task_promotion_tickets gained an FK to task_items and was never added,
        so clean_test_db errored at SETUP for every test that used it — 15 errors in
        one :8000 run on 2026-09-11 (María, row 2d786391). Derived from the models,
        not a hand list, so the next such table reddens this instead of the suite.
        """
        from cosa.rest.postgres_models import Base
        referencing = sorted(
            table.name for table in Base.metadata.tables.values()
            if table.name != "task_items"
            and any( fk.column.table.name == "task_items" for fk in table.foreign_keys )
        )
        assert referencing, "found no table referencing task_items — the scan is blind"
        truncate = re.search( r"TRUNCATE TABLE[\s\S]*?\)", _read( "src/tests/integration/conftest.py" ) ).group( 0 )
        missing  = [ name for name in referencing if name not in truncate ]
        assert not missing, f"clean_test_db TRUNCATE names task_items but not its dependents: {missing}"


class TestCleanTestDbTruncatesRefreshTokens:
    """Bug 8bd20375 (row-level layer): refresh_tokens must be in the
    clean_test_db TRUNCATE list in BOTH conftests. It is absent today, so
    companion refresh tokens accumulate unbounded across tests + suites; a
    residual duplicate-jti row collides with 'Token already exists' (500) when
    it survives the e2e→integration seam on the shared :8000 DB. Truncating it
    per-test closes the residue path at the finest grain — intra- AND
    cross-suite — independent of the runner-level between-suites reset."""

    @pytest.mark.parametrize( "conftest_rel", [
        "src/tests/integration/conftest.py",
        "src/tests/e2e_ui/conftest.py",
    ] )
    def test_truncate_list_includes_refresh_tokens( self, conftest_rel ):
        conftest = _read( conftest_rel )
        truncate = re.search( r"TRUNCATE TABLE[\s\S]*?\)", conftest )
        assert truncate is not None, \
            f"{conftest_rel}: clean_test_db TRUNCATE statement not found"
        assert "refresh_tokens" in truncate.group( 0 ), \
            f"{conftest_rel}: TRUNCATE list missing refresh_tokens (bug 8bd20375)"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
