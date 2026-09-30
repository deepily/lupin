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

import os
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


def test_typescript_rides_the_all_pyramid():
    """
    The TS suite is IN `all` — the ruling landed and the hold-out is over.

    Rick ratified the denominator exclusions on gate 07a5460d (2026-07-21,
    answered live; the timeout default was NO). Before that this assertion ran
    inverted, as a tripwire on a deliberate interim.

    `all` silently skipping the TS suite is how the gap survived: 113 test
    files reachable by no runner, no test-type, no hook, and no CI, under a
    CLAUDE.md mandate that reads as enforced.
    """
    assert "typescript" in ALL_SUITE_COMPONENTS
    assert "typescript" in SUITE_SCRIPTS, "in `all`, so it MUST also be schedulable on demand"


# The exclusions are the load-bearing half now. A 100% threshold over a
# denominator anyone can quietly narrow is decorative, so these assertions
# guard the RATIFIED set — not that exclusions exist, but that these three and
# only these three do, each with its ruling recorded.

RATIFIED_EXCLUSIONS = ( "**/boot.ts", "**/types.ts", "**/index.ts" )


def _command_exclusions( source ):
    """
    The `--exclude` patterns c8 actually RECEIVES — comment lines excluded.

    This distinction is load-bearing and was nearly missed. The runner
    documents each exclusion in a comment block that repeats the flag verbatim,
    so a naive scan of the whole file sees every pattern twice: once where it
    takes effect and once where it is merely described. Set semantics hid the
    duplication, and the test passed for the wrong reason.

    The failure that would have slipped through: DELETE a real `--exclude` and
    leave its comment behind. The denominator silently widens or narrows, the
    documentation still asserts the ruling, and a whole-file scan still finds
    the pattern — a green from evidence that is only prose.

    Requires:
        - source is the runner script's full text

    Ensures:
        - returns patterns from executable lines only
        - a pattern appearing solely in a comment is NOT returned
    """
    executable = [ ln for ln in source.splitlines() if not ln.lstrip().startswith( "#" ) ]
    return set( re.findall( r"--exclude='([^']+)'", "\n".join( executable ) ) )


@pytest.mark.parametrize( "pattern", RATIFIED_EXCLUSIONS )
def test_each_ratified_exclusion_is_present( runner_source, pattern ):
    """Present on an EXECUTABLE line — a comment describing it is not the thing."""
    assert pattern in _command_exclusions( runner_source )


def test_comment_only_exclusions_do_not_count( runner_source ):
    """
    The comment block must not be able to satisfy the equality check alone.

    Positive control for `_command_exclusions`: strip every executable line and
    the set must collapse to empty, proving the parser reads the command and
    not the prose that documents it. Without this, the helper could silently
    devolve into a whole-file scan and nothing would notice.
    """
    comments_only = "\n".join(
        ln for ln in runner_source.splitlines() if ln.lstrip().startswith( "#" )
    )

    assert "--exclude=" in comments_only, "the runner should document its exclusions in comments"
    assert _command_exclusions( comments_only ) == set()


def test_no_exclusion_beyond_the_ratified_set( runner_source ):
    """
    A FOURTH exclusion must fail here until someone widens this literal.

    This is the whitelist-EQUALITY shape rather than a name-list: it asserts
    the exclusion set EQUALS the ratified set, so a new `--exclude` cannot be
    slipped in and quietly shrink the denominator. A test that merely
    enumerated the three would pass while a fourth rode along beside them —
    that is the exact failure this fleet hit today, where a refusal test named
    three flags, a fourth was added, and it passed.
    """
    found = _command_exclusions( runner_source )
    expected = set( RATIFIED_EXCLUSIONS ) | { "**/*.test.ts" }   # test files are never a denominator

    assert found == expected, (
        "the c8 exclusion set drifted from the ratified set.\n"
        f"  unexpected (narrows the denominator without a ruling): {sorted( found - expected )}\n"
        f"  missing (ruled but absent): {sorted( expected - found )}\n"
        "Every exclusion needs a dated ruling in run-typescript-tests.sh."
    )


def test_the_ruling_and_its_cost_are_recorded_in_the_runner( runner_source ):
    """
    The measured numbers must travel WITH the exclusion that was bought by them.

    Without this, a future reader sees three excludes and no way to judge them
    short of re-running a nine-minute suite.
    """
    assert "07a5460d" in runner_source, "the ratifying gate id is not recorded"
    assert "93.19" in runner_source, "the measured pre-exclusion coverage is not recorded"
    for pattern in RATIFIED_EXCLUSIONS:
        stem = pattern.replace( "**/", "" )
        assert re.search( rf"{re.escape( stem )}.*2026-07-21", runner_source ), (
            f"exclusion {stem} carries no dated reason"
        )


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


def test_claude_md_merge_pyramid_agrees_with_all_suite_components():
    """
    CLAUDE.md's merge pyramid and the code's suite list must name the same suites.

    THE FAILURE THIS PREVENTS, measured 2026-08-25: CLAUDE.md § PR MERGE REQUIREMENTS
    listed six steps and omitted BOTH `typescript` and `smoke`, while
    ALL_SUITE_COMPONENTS and run-all-tests.sh's SUITES=(...) both carried seven
    suites. A reader following the documented pyramid merged without ever running
    two tiers, and nothing failed — a gate absent from the doc is a gate nobody
    runs, which is indistinguishable from a gate that passed.

    Two independent lists already guard each other (shell SUITES vs Python
    ALL_SUITE_COMPONENTS, above). The DOC was the third list nobody checked.

    Requires:
        - CLAUDE.md carries a `<!-- merge-pyramid-suites: ... -->` marker line
        - the prose paragraph beneath it names each suite

    Ensures:
        - the marker's suite SET equals ALL_SUITE_COMPONENTS
        - every marker name also appears in the human-readable prose

    SET, not sequence, and deliberately so: the shell array runs `integration`
    before `e2e`, while the documented pyramid runs `e2e` first and holds
    `integration` back as the FINAL GATE. That ordering difference is a ruling,
    not drift. Membership is what must never differ.
    """
    claude_md = ( Path( cu.get_project_root() ) / "CLAUDE.md" ).read_text( encoding="utf-8" )

    marker = re.search( r"<!--\s*merge-pyramid-suites:([^>]*?)-->", claude_md )
    assert marker is not None, (
        "CLAUDE.md carries no `<!-- merge-pyramid-suites: ... -->` marker — the merge "
        "pyramid became unparseable, so this drift check cannot run. Restore the marker "
        "immediately above § PR MERGE REQUIREMENTS' order sentence."
    )
    documented = marker.group( 1 ).split()

    assert sorted( documented ) == sorted( ALL_SUITE_COMPONENTS ), (
        f"CLAUDE.md merge pyramid names {sorted( documented )} but the code runs "
        f"{sorted( ALL_SUITE_COMPONENTS )}. Missing from the doc: "
        f"{sorted( set( ALL_SUITE_COMPONENTS ) - set( documented ) )}; "
        f"extra in the doc: {sorted( set( documented ) - set( ALL_SUITE_COMPONENTS ) )}."
    )

    # The marker is machine-readable and therefore invisible to a human reader.
    # A marker that is correct while the prose beneath it omits a tier is the exact
    # defect this test exists to catch, one level down — so check the prose too.
    prose = claude_md[ marker.end() : ].split( "\n\n", 1 )[ 0 ].lower()
    for suite in documented:
        assert suite in prose, (
            f"`{suite}` is in CLAUDE.md's merge-pyramid marker but not in the prose "
            f"sentence a human actually reads. The marker is not the documentation."
        )


# ─── The numbered gate table in CLAUDE.md ────────────────────────────────────
#
# Rows in that table which are NOT members of ALL_SUITE_COMPONENTS. Named here, with the
# reason, so that a NEW unexplained row fails instead of silently widening the table.
_NON_SUITE_GATE_ROWS = {
    "serial bridge guard": (
        "a whole-directory contact check, not a submittable suite: it has no SUITE_SCRIPTS "
        "entry, cannot be submitted to :7999 as a test type, and the concurrent unit run "
        "deselects it on purpose. It is a merge gate without being a suite."
    ),
}


def test_claude_md_numbered_gate_table_carries_every_suite():
    """
    CLAUDE.md's NUMBERED gate table must name every suite the code actually runs.

    🔴 THE FAILURE THIS PREVENTS, MEASURED 2026-09-09 (row 7bc67019). Adding `typecheck`
    to the merge pyramid touched EIGHT consumers. Seven of them reddened a test that named
    its own fix. The eighth — this table — is a SECOND, numbered list further down the same
    file, and nothing read it. So the marker test above reddened, the marker was fixed, and
    the table sat one gate short with the whole suite green. Mr. Radio found it by reading
    the diff; no instrument would have.

    ⇒ A DOC THAT IS HALF MACHINE-CHECKED IS THE WORST OF BOTH: the checked half earns a
    trust the unchecked half then spends. The marker being green said nothing whatsoever
    about the table forty lines below it, and it read exactly as if it did.

    THE CONSUMER CENSUS, verified 2026-09-09 by making the change and observing which
    guards fired — not by reading the code and inferring:

        # consumer                                   watched by
        1 SUITE_SCRIPTS                              test_every_runnable_suite_can_write_a_stdout_log
        2 SUITE_TIMEOUTS_SECONDS                     test_every_all_suite_component_has_explicit_timeout
        3 ALL_SUITE_COMPONENTS                       test_all_components_order  (the source of truth)
        4 _parse_non_pytest_stdout whitelist         nothing — but only non-pytest runners need it
        5 _LOG_BASENAMES                             test_every_runnable_suite_can_write_a_stdout_log
        6 run-all-tests.sh SUITES + SCRIPTS          test_run_all_tests_script_agrees_with_all_suite_components
        7 CLAUDE.md merge-pyramid-suites marker      test_claude_md_merge_pyramid_agrees_with_all_suite_components
        8 CLAUDE.md numbered gate table              THIS TEST  (was: nothing)

    ⇒ 8 consumers, 7 watched, 1 blind. This closes the eighth.

    ⚠️ #4 IS STILL NOT WATCHED FOR MEMBERSHIP and is deliberately left so: a pytest suite
    does not belong in that tuple at all, so a general "every component is present" assertion
    would be WRONG rather than merely absent. If a future non-pytest runner is added and
    omitted from it, its counts silently read as zero — which `_classify_suite_status` then
    reports as NOT EXECUTED rather than PASSED, so it fails loud rather than green. That is
    why it is tolerable, and the reasoning is recorded rather than the gap simply left.

    🔴 THIS TEST DERIVES ITS EXPECTATION — it does not hardcode a second ordered list.
    Mr. Radio's constraint when he ruled the test in, and it is the whole point: a test that
    pinned its own copy of the pyramid would become a NINTH consumer to drift, guarding
    against the very failure it had just re-created one level up.

    Requires:
        - CLAUDE.md carries a `| # | gate | venue |` table under § PR MERGE REQUIREMENTS

    Ensures:
        - the table's numbering is contiguous from 1, with no gaps or repeats
        - every ALL_SUITE_COMPONENTS member is named in at least one row
        - the row count equals the suites plus the explicitly-named non-suite rows,
          so BOTH a missing row and an unexplained new one fail
    """
    claude_md = ( Path( cu.get_project_root() ) / "CLAUDE.md" ).read_text( encoding="utf-8" )

    header = claude_md.find( "| # | gate | venue |" )
    assert header != -1, (
        "CLAUDE.md carries no `| # | gate | venue |` table — the numbered merge pyramid "
        "became unparseable, so this drift check cannot run. It lives under "
        "§ PR MERGE REQUIREMENTS, beneath the merge-pyramid-suites marker."
    )

    rows = []
    for line in claude_md[ header : ].splitlines()[ 2 : ]:   # skip header + |---| separator
        if not line.startswith( "|" ): break
        cells = [ c.strip() for c in line.strip( "|" ).split( "|" ) ]
        if len( cells ) < 2 or not cells[ 0 ].isdigit(): break
        rows.append( ( int( cells[ 0 ] ), cells[ 1 ].lower() ) )

    assert rows, "the numbered gate table parsed to zero rows — check its formatting"

    # 1. Contiguous numbering. Catches a renumber that skipped or repeated an index.
    assert [ n for n, _ in rows ] == list( range( 1, len( rows ) + 1 ) ), (
        f"the gate table's numbering is {[ n for n, _ in rows ]}, which is not 1..{len( rows )}. "
        f"Renumber the rows — a reader following a gap will skip a gate."
    )

    # 2. Membership, DERIVED from the code's own list. This is the assertion that would
    #    have caught 2026-09-09: typecheck was in ALL_SUITE_COMPONENTS and in no row.
    table_text = " ".join( text for _, text in rows )
    missing    = [ s for s in ALL_SUITE_COMPONENTS if s.lower() not in table_text ]
    assert missing == [ ], (
        f"these suites run in the merge pyramid but appear in NO row of CLAUDE.md's numbered "
        f"gate table: {missing}. A gate absent from the table a human reads is a gate nobody "
        f"runs, which is indistinguishable from a gate that passed. Add a row and renumber."
    )

    # 3. Width, so an unexplained EXTRA row fails too. Anything in the table that is not a
    #    suite must be named in _NON_SUITE_GATE_ROWS with the reason it belongs.
    expected_rows = len( ALL_SUITE_COMPONENTS ) + len( _NON_SUITE_GATE_ROWS )
    assert len( rows ) == expected_rows, (
        f"the gate table has {len( rows )} rows; {len( ALL_SUITE_COMPONENTS )} suites plus "
        f"{len( _NON_SUITE_GATE_ROWS )} named non-suite rows makes {expected_rows}.\n"
        f"  · a row SHORT means a suite is undocumented — add it and renumber.\n"
        f"  · a row LONG means a gate was added that is not a submittable suite. Name it in "
        f"_NON_SUITE_GATE_ROWS with WHY it is a gate without being a suite, rather than "
        f"loosening this count."
    )

    for name, why in _NON_SUITE_GATE_ROWS.items():
        assert name in table_text, (
            f"'{name}' is listed in _NON_SUITE_GATE_ROWS as a non-suite merge gate ({why}), "
            f"but no longer appears in the table. If it was retired, drop it from that dict "
            f"in the same commit — a stale exemption inflates the expected row count and "
            f"would then hide a genuinely missing suite."
        )


def test_typescript_has_an_explicit_timeout():
    """A suite falling back to the 600s default would be killed mid-run."""
    assert SUITE_TIMEOUTS_SECONDS[ "typescript" ] > 8 * 60, (
        "the TS suite measured 8m19s uninstrumented on 2026-07-21; c8 adds overhead on top"
    )


def test_typescript_has_a_canonical_log_symlink( tmp_path, monkeypatch ):
    # Derived from _ARTIFACT_DIR now (row fd0cd863) so the symlink cannot be relocated
    # independently of the log file and the junit XML.
    #
    # The root MUST be pinned here. Left unpinned, `_log_symlink_path` resolves through
    # attestation.artifact_root(), which fails closed under pytest (c29beb07) — and that
    # refusal is correct: this test has no business resolving the real artifact root just
    # to check a basename. Asserted against the computed path rather than a literal, so
    # it follows a future artifact-root move instead of pinning the tree to /tmp.
    monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )
    assert TestSuiteJob._log_symlink_path( "typescript" ) == os.path.join(
        str( tmp_path ), "typescript-latest.log"
    )


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
        # not_executed joined the parser output at c37443f5 (89bfcc8f D2, 2026-08-13);
        # this expected dict predated it (test last touched 2026-08-03) → the stale red.
        "not_executed": 0,
    }


def test_unknown_suite_types_still_return_none():
    assert TestSuiteJob._parse_non_pytest_stdout( "unit", "# pass 5\n" ) is None


def test_the_runner_injects_its_own_job_id_for_artifact_provenance():
    """
    `written_by` was "unknown-caller" on EVERY artifact ever written (row 224fbb68).

    test_v2_paired_live.py reads `LUPIN_TEST_SUITE_JOB_ID` and stamps it into the
    paired-run artifact, calling "unknown-caller" the tell that nothing identified
    itself as a real run. Krishna measured that nothing in the tree ever SET that
    variable — so the tell could never fire, and a previous session nearly read a
    scaffold artifact as a real result.

    Ensures:
        - the runner injects the variable at all
        - it carries the job's own id
        - it is placed so a caller's env_vars CANNOT overwrite it — provenance that
          a run can relabel is not provenance
    """
    source = ( Path( cu.get_project_root() ) / "src/cosa/agents/test_suite/job.py" ).read_text( encoding="utf-8" )

    assert '"LUPIN_TEST_SUITE_JOB_ID" : self.id_hash' in source, (
        "the runner must inject its own job id, or every artifact keeps stamping "
        "'unknown-caller' and the backstop stays dead"
    )

    # Order is the whole guarantee: **self.env_vars must come BEFORE the injection.
    env_spread = source.index( "**self.env_vars" )
    injection  = source.index( '"LUPIN_TEST_SUITE_JOB_ID"' )
    assert env_spread < injection, (
        "LUPIN_TEST_SUITE_JOB_ID is spread-over by **self.env_vars — a caller could "
        "relabel whose run wrote an artifact. Move the injection after the spread."
    )
