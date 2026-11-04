"""
Date-bound normalization for the git selection flags.

What this module prevents
-------------------------
Git resolves a bare ISO date to a time of day that is not midnight. Measured on a
repo with 35 commits on one day, asked at 21:37 that same day:

```
git log --no-merges --since=2026-08-02          ->  0 commits
git log --no-merges --since="2026-08-02 00:00"  -> 35 commits
git log --no-merges --since=2026-08-01          -> 35 commits
```

So `--since=<today>` selects nothing, while `--since=<yesterday>` correctly selects
today. `--today` mode builds the bare form, so without this fix the default mode of
the LoC tool reports zero on a busy day. It reports that zero as a successful empty
result, not as an error.

That zero cannot be told apart from "this repo did no work today". It reached a fleet-wide
roll-up twice. Once per repo, 35 commits read as 0. Once at discovery scope, 43
commits read as 0 active repos.

Why the coverage guard cannot catch it
--------------------------------------
`coverage_guard` cross-checks the numstat walk against an independent `git rev-list`.
It mirrors the selection flags exactly, so that any difference is a real coverage gap
and not flag skew. That design catches a walk or parse divergence. It cannot catch a
wrong bound, because both sides receive the same wrong predicate, both return 0 and
they agree. A guard that mirrors the flags cannot audit the flags. Normalizing here,
in one place that both call, keeps their agreement meaningful.

`--until` needs no such fix. A bare ISO date lands at the end of that day, which is
already the inclusive upper bound the CLI documents. Bare `--until=2026-08-01` and
explicit `--until="2026-08-01 23:59:59"` both return 61 commits on the measured repo.
"""
import re


# A date with no time component: exactly YYYY-MM-DD and nothing else.
_BARE_ISO_DATE = re.compile( r"^\d{4}-\d{2}-\d{2}$" )

# What a bare lower-bound date is SUPPOSED to mean: the start of that day.
_DAY_START = " 00:00:00"


def normalize_since( value ):
    """
    Pin a lower-bound date to the start of its day so git cannot drift it.

    Requires:
        - value is a date/datetime string git accepts, or None

    Ensures:
        - returns None unchanged
        - returns a bare ISO date (YYYY-MM-DD) with " 00:00:00" appended, which
          is the bound the caller meant and the one git would otherwise miss
        - returns anything else verbatim. A value that already carries a time,
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

    A bare ISO date already resolves to the end of that day, which is the inclusive
    upper bound the CLI advertises. Both bounds go through one call at every call
    site. Adding a time here would silently make `--until` exclusive.

    Requires:
        - value is a date/datetime string git accepts, or None

    Ensures:
        - returns value unchanged, always
    """
    return value
