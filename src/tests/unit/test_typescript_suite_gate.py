"""
The TypeScript suite is wired to a gate, and its threshold is enforced (row 36e479ed).

WHY THIS FILE EXISTS: CLAUDE.md's 100% COVERAGE MANDATE names TypeScript
explicitly — "100% coverage, lines AND branches AND functions … TypeScript via
`c8 --100`". Until 2026-07-21 nothing invoked it: zero runner scripts, zero
test-types, zero hooks, no CI. The mandate's Python half had real teeth via
`--cov-fail-under=100`; reading the mandate, both halves looked equally
enforced.

These tests assert the WIRING, which is the thing that was missing. They are
deliberately cheap and run on the `unit` gate; the TS suite itself is a
`:8000` job (2,245 tests, 8m19s measured uninstrumented on 2026-07-21).

WHAT THIS FILE DOES NOT ASSERT: that the TS suite currently passes, or what its
coverage number is. Those are the suite's job. A wiring test that claimed a
green it never observed would be the same defect one layer up.
"""

import re
import stat

from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.agents.test_suite.job import (
    ALL_SUITE_COMPONENTS,
    SUITE_SCRIPTS,
    SUITE_TIMEOUTS_SECONDS,
    SUITES_SUPPORTING_JUNIT_XML,
    TestSuiteJob,
)


RUNNER_REL = "src/tests/run-typescript-tests.sh"


@pytest.fixture( scope="module" )
def runner_source():
    """The TypeScript runner's text, read once."""
    return ( Path( cu.get_project_root() ) / RUNNER_REL ).read_text( encoding="utf-8" )


# ---------------------------------------------------------------------------
# Wiring — the part whose absence WAS the defect
# ---------------------------------------------------------------------------

def test_typescript_is_an_invocable_test_type():
    """Without a SUITE_SCRIPTS entry, no test-type can schedule the suite at all."""
    assert SUITE_SCRIPTS[ "typescript" ] == RUNNER_REL


def test_the_runner_exists_and_is_executable():
    runner = Path( cu.get_project_root() ) / RUNNER_REL

    assert runner.is_file()
    assert runner.stat().st_mode & stat.S_IXUSR, "runner is not executable — SUITE_SCRIPTS would fail to launch it"


def test_typescript_is_held_out_of_the_all_pyramid_pending_a_ruling():
    """
    HELD OUT ON PURPOSE, and this test is the marker that keeps it visible.

    Measured 2026-07-21: the TS suite passes 2245/2245 but scores 93.19%
    statements against the mandate's 100%. The entire gap is three
    exempt-shaped categories — `boot.ts` entry points, `types.ts` type-only
    modules, `index.ts` barrels. Whether those are legitimately excluded from
    the denominator changes what "100%" means, so it is a ruling (row
    36e479ed), not a default I get to pick.

    Wiring it into `all` before that ruling would make every `all` run red for
    a known reason, and a gate that always fails for a known reason gets
    ignored — which is how the original gap survived in the first place.

    WHEN THE RULING LANDS: flip this assertion to `in`, and delete the
    hold-out comments in job.py and run-all-tests.sh. The test failing after
    that flip is the point — it will not let the hold-out be forgotten.
    """
    assert "typescript" not in ALL_SUITE_COMPONENTS
    assert "typescript" in SUITE_SCRIPTS, "held out of `all`, but it MUST stay schedulable on demand"


def test_run_all_tests_script_agrees_with_all_suite_components():
    """
    The shell pyramid and the Python pyramid must name the same suites.

    They are two independent lists that must not drift — a suite present in one
    and absent from the other runs or skips depending on which door you came
    through, which is indistinguishable from coverage.
    """
    source = ( Path( cu.get_project_root() ) / "src/tests/run-all-tests.sh" ).read_text( encoding="utf-8" )
    declared = re.search( r"^SUITES=\(([^)]*)\)", source, re.MULTILINE ).group( 1 )
    # NOTE the digit class: `e2e` has one, and a `[a-z_]+` pattern silently drops
    # it — which would have made this drift check pass while comparing a SHORTER
    # list than the file actually declares.
    shell_suites = re.findall( r"\"([a-z0-9_]+)\"", declared )

    assert shell_suites == ALL_SUITE_COMPONENTS


def test_typescript_has_an_explicit_timeout():
    """A suite falling back to the 600s default would be killed mid-run."""
    assert SUITE_TIMEOUTS_SECONDS[ "typescript" ] > 8 * 60, (
        "the TS suite measured 8m19s uninstrumented on 2026-07-21; c8 adds overhead on top"
    )


def test_typescript_has_a_canonical_log_symlink():
    assert TestSuiteJob._LOG_SYMLINKS[ "typescript" ] == "/tmp/typescript-latest.log"


def test_typescript_is_excluded_from_junit_xml_injection():
    """`node --test` is not pytest; appending --junit-xml would error at arg-parse."""
    assert "typescript" not in SUITES_SUPPORTING_JUNIT_XML


# ---------------------------------------------------------------------------
# The threshold — the part that turns a report into a gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "flag", [ "--lines", "--branches", "--functions", "--statements" ] )
def test_runner_enforces_one_hundred_on_every_dimension( runner_source, flag ):
    """
    The mandate says lines AND branches AND functions. A runner that measured
    without a threshold would print a number nobody acts on.
    """
    assert re.search( rf"{re.escape( flag )}\s+\"?\$?\{{?THRESHOLD", runner_source ), (
        f"{flag} is not wired to a threshold variable"
    )


def test_every_threshold_is_one_hundred( runner_source ):
    thresholds = dict( re.findall( r"^THRESHOLD_([A-Z]+)=(\d+)$", runner_source, re.MULTILINE ) )

    assert thresholds == {
        "LINES"      : "100",
        "BRANCHES"   : "100",
        "FUNCTIONS"  : "100",
        "STATEMENTS" : "100",
    }


def test_runner_checks_coverage_by_default( runner_source ):
    """Without --check-coverage, c8 exits 0 no matter how low the number is."""
    assert 'CHECK_COVERAGE="--check-coverage"' in runner_source


def test_runner_counts_files_with_no_tests( runner_source ):
    """
    `--all` is what makes an entirely untested module visible.

    Without it c8 reports only files the tests happened to load, so a module
    with zero tests contributes zero to the denominator and the percentage
    stays flattering — the same silence this whole row is about.
    """
    assert re.search( r"^\s*--all\s*\\?$", runner_source, re.MULTILINE )


def test_runner_instruments_every_typescript_entry_tree( runner_source ):
    """All three tsconfig roots must be measured, or one tree is silently exempt."""
    for tree in ( "multiplexer", "nav", "diagnostic" ):
        assert f"--include='src/lupin_app/static/js/{tree}/**/*.ts'" in runner_source


def test_runner_excludes_test_files_from_the_denominator( runner_source ):
    assert "--exclude='**/*.test.ts'" in runner_source


# ---------------------------------------------------------------------------
# Result parsing — a green run must not report 0/0/0/0
# ---------------------------------------------------------------------------

def test_tap_summary_parses_a_passing_run():
    stdout = "ok 1 - a\n# tests 2245\n# pass 2245\n# fail 0\n# skipped 0\n# todo 0\n"

    assert TestSuiteJob._parse_non_pytest_stdout( "typescript", stdout ) == {
        "passed": 2245, "failed": 0, "skipped": 0, "errors": 0,
    }


def test_tap_summary_parses_failures_and_skips():
    stdout = "# tests 10\n# pass 7\n# fail 2\n# skipped 1\n"

    assert TestSuiteJob._parse_non_pytest_stdout( "typescript", stdout ) == {
        "passed": 7, "failed": 2, "skipped": 1, "errors": 0,
    }


def test_tap_summary_takes_the_last_trailer_not_a_nested_one():
    """
    A test whose own output contains `# pass 1` must not shadow the run total.

    This suite's TS tests assert on rendered markup and log lines, so a nested
    TAP-shaped string is a live possibility, not a hypothetical.
    """
    stdout = "# pass 1\n# fail 0\nok 1 - renders a summary\n# tests 2245\n# pass 2245\n# fail 3\n"

    assert TestSuiteJob._parse_non_pytest_stdout( "typescript", stdout ) == {
        "passed": 2245, "failed": 3, "skipped": 0, "errors": 0,
    }


def test_tap_summary_returns_none_without_a_trailer():
    """Unrecognized output must preserve the caller's zero-count default, not invent one."""
    assert TestSuiteJob._parse_non_pytest_stdout( "typescript", "ok 1 - a test\n" ) is None


def test_tap_summary_returns_none_on_empty_stdout():
    assert TestSuiteJob._parse_non_pytest_stdout( "typescript", "" ) is None


def test_websocket_parser_is_untouched_by_the_typescript_branch():
    """The pre-existing websocket path must keep its exact prior behaviour."""
    stdout = "Total Tests: 50\nPassed: 50\nFailed: 0\nALL SMOKE TESTS PASSED!\n"

    assert TestSuiteJob._parse_non_pytest_stdout( "websocket", stdout ) == {
        "passed": 50, "failed": 0, "skipped": 0, "errors": 0,
    }


def test_unknown_suite_types_still_return_none():
    assert TestSuiteJob._parse_non_pytest_stdout( "unit", "# pass 5\n" ) is None
