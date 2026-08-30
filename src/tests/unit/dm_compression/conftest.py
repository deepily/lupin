"""
Make a missing corpus snapshot LOUD instead of silent.

THE DEFECT THIS CLOSES (working-tree-artifact gate audit, 2026-08-30, Mode 2).
`test_freeze.py`'s corpus fixture reads a snapshot under `src/tmp/`, which is
gitignored at `.gitignore:5`. When the file is present the module reports
`494 passed`; when it is absent it reports `488 passed, 6 skipped`. BOTH read
as success, and `git status` cannot tell you which run you got, because a
gitignored path is suppressed from it entirely. Two machines "both pass" while
measuring different things and nothing in the output says so.

WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT DO. It makes the silence
visible: a header line before the run and a summary line after it, each naming
the absent artifact and how many tests it cost. It does NOT decide whether the
corpus should be tracked, nor whether those tests should FAIL rather than skip
when it is missing. That question is open and is not this file's to answer —
and making the loss visible does not prejudge either answer.

THE COUNT IS MEASURED, NEVER DECLARED. `pytest_terminal_summary` counts the
reports actually skipped for this reason in the run that just happened. A
hardcoded 6 would be one more instrument certifying itself: it would keep
saying 6 after someone adds a seventh corpus test, and the number nobody
re-derives is the number that goes stale.
"""

import os

import cosa.utils.util as cu


SNAPSHOT = cu.get_project_root() + "/src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"

# The fixture's skip reason. Matched, not re-typed, so the two cannot drift apart.
SKIP_REASON_PREFIX = "corpus snapshot not present: "


def corpus_snapshot_is_present():
    """
    Report whether the pinned DM-traffic corpus is readable.

    Requires:
        - nothing; safe to call when the path does not exist

    Ensures:
        - returns True iff SNAPSHOT exists on this host
        - never raises, so a header hook cannot take down collection
    """
    return os.path.exists( SNAPSHOT )


# ─────────────────────────────────────────────────────────────────────────────
# THERE IS DELIBERATELY NO `pytest_report_header` HERE. DO NOT ADD ONE.
#
# The first cut of this file had one, announcing the absent corpus BEFORE the
# run. Measured, it fired almost never:
#
#     pytest <this dir>          -q   ->  header ABSENT   (-q suppresses headers)
#     pytest <this dir>               ->  header present
#     pytest src/tests/unit/          ->  header ABSENT   (subdir conftest, loaded too late)
#
# Every command this repo documents passes `-q`, and the tier is normally run
# whole — so in practice it would have fired in neither of the two cases that
# matter. A warning that is usually silent is worse than none at all: a reader
# who sees no header concludes the corpus is PRESENT, which is the exact
# false-green this file was written to close, moved one level up.
#
# The summary hook below has no such hole — it is measured firing under `-q`,
# without it, scoped to this directory, and in a mixed multi-directory run.
# ─────────────────────────────────────────────────────────────────────────────


def pytest_terminal_summary( terminalreporter, exitstatus, config ):
    """
    State, after the run, how many tests the absent corpus actually cost.

    Requires:
        - terminalreporter carries this run's collected reports

    Ensures:
        - writes a line naming the MEASURED count when any test skipped for
          the missing corpus
        - stays silent when none did, so a complete run reads clean
        - the count comes from the run, never from a constant in this file
    """
    skipped = terminalreporter.stats.get( "skipped", [] )
    ours    = [ report for report in skipped if _skipped_for_missing_corpus( report ) ]

    if not ours: return

    terminalreporter.write_sep( "=", "dm-compression: tests that did NOT run", red=True )
    terminalreporter.write_line(
        f"{len( ours )} test(s) skipped because the pinned corpus is absent: {SNAPSHOT}" )
    terminalreporter.write_line(
        "This run measured LESS than a run on a host that has it. The pass count above is "
        "not comparable to one taken elsewhere." )
    for report in ours:
        terminalreporter.write_line( f"    {report.nodeid}" )


def _skipped_for_missing_corpus( report ):
    """
    Decide whether one skip report is ours.

    Requires:
        - report is a pytest TestReport with a `longrepr`

    Ensures:
        - returns True only for skips carrying the fixture's own reason prefix
        - tolerates every longrepr shape pytest uses, returning False rather
          than raising on one it does not recognise
    """
    longrepr = getattr( report, "longrepr", None )
    if longrepr is None: return False

    # pytest reports a fixture skip as (path, lineno, reason); other shapes exist.
    if isinstance( longrepr, tuple ) and len( longrepr ) == 3:
        return SKIP_REASON_PREFIX in str( longrepr[ 2 ] )

    return SKIP_REASON_PREFIX in str( longrepr )
