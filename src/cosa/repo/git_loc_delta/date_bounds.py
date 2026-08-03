"""
Date-bound normalization for the git selection flags (row d0b3cd84).

THE DEFECT THIS EXISTS TO KILL
------------------------------
Git resolves a BARE ISO date to a time-of-day that is not midnight. Measured on
a repo with 35 commits on 2026-08-02, asked at 21:37 that same day:

    git log --no-merges --since=2026-08-02          ->  0 commits
    git log --no-merges --since="2026-08-02 00:00"  -> 35 commits
    git log --no-merges --since=2026-08-01          -> 35 commits

So `--since=<today>` selects nothing, while `--since=<yesterday>` correctly
selects today. `--today` mode built exactly the bare form, which meant the
DEFAULT mode of the LoC tool reported zero on a busy day — and reported it as a
successful empty result, not an error.

That zero is indistinguishable from "this repo did no work today". It reached a
fleet-wide roll-up twice on 2026-08-02: once per-repo (35 commits read as 0) and
once at discovery scope (43 commits read as 0 ACTIVE REPOS).

WHY THE COVERAGE GUARD DID NOT CATCH IT
---------------------------------------
`coverage_guard` cross-checks the numstat walk against an independent
`git rev-list`, and deliberately mirrors the selection flags EXACTLY so that any
difference is a real coverage gap rather than flag skew. That design catches a
walk/parse divergence — but both sides were handed the SAME wrong predicate, so
both returned 0 and agreed. A guard that mirrors the flags cannot audit the
flags. Normalizing HERE, in one place both call, is what makes their agreement
meaningful again.

`--until` needs no such fix: a bare ISO date lands at the END of that day, which
is already the inclusive upper bound the CLI documents. Verified — bare
`--until=2026-08-01` and explicit `--until="2026-08-01 23:59:59"` both return 61.

Created: 2026-08-02 (Cheech 🌿) · row d0b3cd84
"""
import re


# A date with no time component: exactly YYYY-MM-DD and nothing else.
_BARE_ISO_DATE = re.compile( r"^\d{4}-\d{2}-\d{2}$" )

# What a bare lower-bound date is SUPPOSED to mean: the start of that day.
_DAY_START = " 00:00:00"


def normalize_since( value ):
    """
    Pin a lower-bound date to the START of its day so git cannot drift it.

    Requires:
        - value is a date/datetime string git accepts, or None

    Ensures:
        - returns None unchanged
        - returns a BARE ISO date (YYYY-MM-DD) with " 00:00:00" appended, which
          is the bound the caller meant and the one git would otherwise miss
        - returns anything else verbatim — a value that already carries a time,
          or a relative expression like "1 day ago", is already unambiguous and
          must not be second-guessed
    """
    if value is None:
        return None
    if _BARE_ISO_DATE.match( value ):
        return f"{value}{_DAY_START}"
    return value


def normalize_until( value ):
    """
    Return an upper-bound date unchanged, with the reason recorded.

    A bare ISO date already resolves to the END of that day, which matches the
    inclusive upper bound the CLI advertises. This function exists so the two
    bounds are handled symmetrically at every call site — a future reader who
    "fixes" the asymmetry by adding a time here would silently make `--until`
    exclusive and lop a day off every range.

    Requires:
        - value is a date/datetime string git accepts, or None

    Ensures:
        - returns value unchanged, always
    """
    return value
