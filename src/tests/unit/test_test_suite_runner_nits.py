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
    "e2e"  : 2020.6,
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
