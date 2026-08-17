"""
Unit tests for row d7691334 — LUPIN_PAIRED_N and the integration suite timeout
must stay COUPLED, and the compose comment must state the pair it was checked at.

THE DEFECT THIS CLOSES
    Two numbers in two files decide one fact — whether the v2 paired-eval run
    finishes or is SIGTERM'd mid-flight:

        docker-compose.yml   LUPIN_PAIRED_N        how many samples the run takes
        job.py:84            SUITE_TIMEOUTS_       how long the runner lets the
                             SECONDS["integration"] integration suite live

    Nothing compared them. On 2026-08-17 the compose comment argued carefully for
    n=10 against a 2000s timeout while the line itself carried 60 and the timeout
    had already been raised to 30000s — three claims, no two of which agreed, and
    a green suite the whole time. job.py:84 still says "REVERT to 2000 at close",
    so the pair is scheduled to break again the moment somebody does exactly that
    and leaves n at 60.

WHAT THE COMMENT HAS TO CARRY
    A prose comment cannot be checked, so the compose block carries one machine-
    readable receipt line:

        # CONFIRMED <date>: n=<n> fits integration timeout <t>s

    Both numbers are bound to reality here — `n` against the value on the very
    next line, `t` against the live constant in job.py. Stale prose passes a
    "does the comment mention 60" test; it cannot pass this one.

WHY A COMPARATOR AND NOT A HARDCODED PAIR
    Asserting "n == 60 and timeout == 30000" would go red on every legitimate
    change and teach people to edit the test. `_paired_run_fits` states the
    RELATION instead, anchored on job.py's own measurement, so any pair that
    actually fits is allowed and any pair that does not is refused.

    It is a NECESSARY condition, not a sufficient one: the integration suite runs
    ~43 other tests inside the same budget, so a pair that passes here can still
    be tight. It refuses the pairs that cannot possibly finish.

Venue: :7999 / AI-discretionary. Pure file reads + one in-process import. No
Docker, no network, no persistent state.
"""
import os
import re

import pytest

import cosa.utils.util as cu
from cosa.agents.test_suite.job import SUITE_TIMEOUTS_SECONDS

PROJECT_ROOT = cu.get_project_root()
COMPOSE_PATH = os.path.join( PROJECT_ROOT, "docker-compose.yml" )

# job.py:84's OWN measurement of the closing run: n=60 ≈ 4.8h ⇒ 17280 / 60.
# One "unit of n" is n_per_command, which drives ~20 real calls across both arms
# and both passes (v1 ~6.7s/push + v2 ~22s/call ≈ 1200 calls at n=60).
SECONDS_PER_N_MEASURED = 288

RE_PAIRED_N  = re.compile( r'^\s*LUPIN_PAIRED_N:\s*"?(\d+)"?\s*$' )
RE_CONFIRMED = re.compile(
    r"^\s*#\s*CONFIRMED\s+\d{4}-\d{2}-\d{2}:\s*n=(\d+)\s+fits\s+integration\s+timeout\s+(\d+)s\s*$"
)


def _compose_lines():
    with open( COMPOSE_PATH, "r", encoding="utf-8" ) as handle:
        return handle.read().splitlines()


def _sole_match( pattern, lines, what ):
    """
    Return the sole regex match for `pattern` across `lines`.

    Ensures:
        - fails loudly on ZERO matches — an empty scan must never read as a clean
          one, which is how a renamed key would silently retire this whole file
        - fails loudly on MORE THAN ONE match — two declarations mean two answers,
          and this test would otherwise check whichever it happened to see first
    """
    hits = [ m for m in ( pattern.match( line ) for line in lines ) if m ]
    assert len( hits ) == 1, f"expected exactly 1 {what} in docker-compose.yml, found {len( hits )}"
    return hits[ 0 ]


def _paired_run_fits( n, timeout_seconds ):
    """
    Return True iff a paired-eval run of sample size `n` can finish inside
    `timeout_seconds`, at the cost per unit of n that job.py:84 measured.

    Requires:
        - n and timeout_seconds are non-negative ints

    Ensures:
        - True iff n * SECONDS_PER_N_MEASURED <= timeout_seconds
        - necessary, not sufficient: the rest of the integration suite shares the
          same budget, so a True here is "not scheduled to die", not "comfortable"
    """
    return n * SECONDS_PER_N_MEASURED <= timeout_seconds


def test_compose_declares_exactly_one_paired_n():
    n = int( _sole_match( RE_PAIRED_N, _compose_lines(), "LUPIN_PAIRED_N declaration" ).group( 1 ) )
    assert n > 0


def test_confirmed_receipt_names_the_value_on_the_next_line():
    lines     = _compose_lines()
    confirmed = _sole_match( RE_CONFIRMED, lines, "CONFIRMED receipt line" )
    declared  = int( _sole_match( RE_PAIRED_N, lines, "LUPIN_PAIRED_N declaration" ).group( 1 ) )
    assert int( confirmed.group( 1 ) ) == declared, (
        "the CONFIRMED line argues one sample size while LUPIN_PAIRED_N carries another — "
        "that exact disagreement is row d7691334"
    )


def test_confirmed_receipt_names_the_live_integration_timeout():
    confirmed = _sole_match( RE_CONFIRMED, _compose_lines(), "CONFIRMED receipt line" )
    assert int( confirmed.group( 2 ) ) == SUITE_TIMEOUTS_SECONDS[ "integration" ], (
        "the CONFIRMED line cites a timeout job.py no longer carries — re-check the pair and "
        "restate it, do not just edit the number"
    )


def test_the_shipped_pair_actually_fits():
    n = int( _sole_match( RE_PAIRED_N, _compose_lines(), "LUPIN_PAIRED_N declaration" ).group( 1 ) )
    timeout = SUITE_TIMEOUTS_SECONDS[ "integration" ]
    assert _paired_run_fits( n, timeout ), (
        f"n={n} needs ~{n * SECONDS_PER_N_MEASURED}s but the integration budget is {timeout}s — "
        "the run would be SIGTERM'd mid-flight"
    )


@pytest.mark.parametrize(
    "n,timeout,fits",
    [
        ( 60, 30000, True  ),   # the shipped pair
        ( 60,  2000, False ),   # job.py's own "REVERT to 2000 at close" against n=60
        ( 10,  2000, False ),   # the n=10 argument the stale comment made — also did not fit
        ( 10,  3000, True  ),   # n=10 does fit, given a budget that matches the measurement
        ( 60, 17280, True  ),   # exact boundary: n * 288
        ( 61, 17280, False ),   # one sample past it
        (  0,     0, True  ),   # degenerate: no samples, no time needed
    ],
)
def test_comparator_fires_and_passes( n, timeout, fits ):
    """The guard is only worth having if it can go red — these are the pairs it must refuse."""
    assert _paired_run_fits( n, timeout ) is fits
