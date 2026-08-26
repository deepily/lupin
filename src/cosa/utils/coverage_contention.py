#!/usr/bin/env python3
"""
Is another test suite running right now? — row `e2099400`, Rick's decision 4.

🔴 WHY THIS EXISTS. Measured 2026-08-26: a `pytest --cov` tier run that shared
the box with a second suite reported **82% / 1320 missing statements**. The
identical tree, run alone minutes later, reported **89% / 853**. Same command,
same isolated `COVERAGE_FILE`, same pass / skip / xfail counts, and **no warning
of any kind** — coverage.py has no "I could not measure that" state, so it
reports a number under conditions where the number means nothing.

The loss concentrated in modules reached through spawned subprocesses
(`cc_notification_listener` 0 → 155 missing, `register_session` 84 → 191,
`hook_common` 34 → 136, `session_end` 12 → 55), while every module that had
tests added that day *improved* in the same run.

**The error is directionally hostile.** It makes coverage look WORSE, so the
reflex is to spend a day writing tests for a hole that does not exist.

**And it now has teeth.** `fail_under` rises per milestone (Rick, same day), so a
floor set from a contended run lands ~7 points too low — and being too low,
nothing ever goes red to say so.

⚠️ THE MECHANISM IS A SUSPECT, NOT A FINDING. Contention is the obvious
difference and subprocess-timed coverage the plausible victim; the causal chain
is unproven. This module does not claim to know why — it refuses the condition
under which the number stopped being trustworthy. Full write-up:
`src/rnd/v0.2.0/2026.08.26-contended-tier-run-fabricates-a-coverage-regression.md`.

## Contract

`find_foreign_pytest( ... )` returns the list of pytest processes that are NOT
this process or one of its ancestors. Ancestors are excluded because the runner
script that invokes this check may itself be named `run-pytest-direct.sh` — a
substring match would otherwise have every run refuse itself.

CLI: `python3 -m cosa.utils.coverage_contention` — exit **0** clear, **1**
contended (offenders printed to stderr), **2** unknown (could not read the
process table). ⚠️ **UNKNOWN IS NOT CLEAR**, and the caller decides what to do
about it; this module does not soften it into a pass.
"""

import os
import sys
from typing import Callable, Iterable, List, Optional, Tuple


EXIT_CLEAR      = 0
EXIT_CONTENDED  = 1
EXIT_UNKNOWN    = 2

ESCAPE_HATCH_ENV = "LUPIN_ALLOW_CONTENDED_COVERAGE"

# ⚠️ SUBSTRING MATCHING WAS TRIED FIRST AND IS WRONG. Markers like "/bin/pytest"
# also match "/usr/bin/pytest-watch" — a watcher that has not started a suite —
# and matching the bare word "pytest" additionally hits this checker's own runner
# scripts (run-pytest-direct.sh), editor buffers, and `grep -rn pytest src/`. Each
# false positive refuses a legitimate coverage run, and a guard that refuses
# legitimate runs is deleted within a day. So the check is TOKEN-shaped: a token
# whose basename is exactly "pytest", in a position where it is the program being
# run rather than a word being passed to one.


def looks_like_pytest( cmdline: str ) -> bool:
    """
    True when `cmdline` looks like a pytest INVOCATION rather than a mention.

    A token counts as an invocation when its basename is exactly "pytest" AND it is
    in a program position: first on the line (a PATH-resolved `pytest -q`), given as
    a path (`/opt/venv/bin/pytest`), or preceded by `-m` (`python3 -m pytest`).

    Requires:
        - cmdline is a string (may be empty)

    Ensures:
        - returns True only for an invocation-shaped command line
        - a path that merely CONTAINS the word pytest (a runner script named
          run-pytest-direct.sh, an open editor buffer, /usr/bin/pytest-watch)
          returns False
        - never raises

    ⚠️ KNOWN GAP, accepted deliberately: a bare `pytest` behind an env prefix
    (`env FOO=1 pytest -q`) is not matched — it is neither first nor a path nor
    after -m. Every sanctioned runner in this tree invokes pytest BY PATH
    (src/scripts/lib/resolve-venv-pytest.sh refuses anything else), so the shape
    does not occur here; widening the rule to cover it re-admits the false
    positives above, which cost more.
    """
    if not cmdline: return False
    tokens = cmdline.split()
    for index, token in enumerate( tokens ):
        if os.path.basename( token ) != "pytest": continue
        if index == 0: return True
        if "/" in token: return True
        if tokens[ index - 1 ] == "-m": return True
    return False


def _default_ancestors( pid: Optional[int]=None ) -> List[int]:
    """This process and every ancestor, walking /proc/<pid>/stat's ppid field."""
    chain = []
    current = os.getpid() if pid is None else pid
    seen = set()
    while current and current not in seen:
        seen.add( current )
        chain.append( current )
        try:
            with open( f"/proc/{current}/stat" ) as handle:
                # comm can contain spaces AND parentheses; ppid is the field
                # after the last ')' — index 1 of the remainder.
                fields = handle.read().rsplit( ")", 1 )[ 1 ].split()
            current = int( fields[ 1 ] )
        except ( OSError, ValueError, IndexError ):
            break
        if current <= 1: break
    return chain


def _default_process_table() -> List[ Tuple[ int, str ] ]:
    """Every readable (pid, cmdline) from /proc. Raises OSError if /proc is unusable."""
    rows = []
    for entry in os.listdir( "/proc" ):
        if not entry.isdigit(): continue
        try:
            with open( f"/proc/{entry}/cmdline", "rb" ) as handle:
                raw = handle.read()
        except OSError:
            continue                      # the process exited between listdir and open
        rows.append( ( int( entry ), raw.replace( b"\0", b" " ).decode( "utf-8", "replace" ).strip() ) )
    return rows


def find_foreign_pytest(
    process_table : Optional[ Callable[ [], Iterable[ Tuple[ int, str ] ] ] ]=None,
    ancestors     : Optional[ Iterable[int] ]=None,
) -> List[ Tuple[ int, str ] ]:
    """
    Pytest processes that are neither this process nor one of its ancestors.

    Requires:
        - process_table, when supplied, is a callable returning (pid, cmdline) pairs
        - ancestors, when supplied, is an iterable of pids to exclude

    Ensures:
        - returns [] when the only pytest processes belong to our own tree
        - excludes ancestors, so a runner script whose own name contains
          "pytest" never causes a run to refuse itself
        - the result is sorted by pid, so two callers see the same order

    Raises:
        - OSError if the process table cannot be read at all
    """
    table  = ( process_table or _default_process_table )()
    ours   = set( _default_ancestors() if ancestors is None else ancestors )
    found  = [ ( pid, cmd ) for pid, cmd in table
               if pid not in ours and looks_like_pytest( cmd ) ]
    return sorted( found, key=lambda row: row[ 0 ] )


def escape_hatch_engaged( environ=None ) -> bool:
    """
    True when the operator has deliberately allowed a contended coverage run.

    Ensures:
        - only an explicit truthy value engages it; "0", "false", "" and absent
          all read as NOT engaged, so a leftover `=0` in a shell profile cannot
          silently disable the guard
    """
    raw = ( environ if environ is not None else os.environ ).get( ESCAPE_HATCH_ENV, "" )
    return raw.strip().lower() in ( "1", "true", "yes", "on" )


def render_refusal( offenders: List[ Tuple[ int, str ] ] ) -> str:
    """The message a refused run prints. Names the offender AND the remedy."""
    lines = [
        "REFUSING a --cov run: another test suite is already running on this box.",
        "",
        "WHY: a coverage run sharing the box with another suite reports a number that is",
        "     silently wrong. Measured 2026-08-26 — a contended tier run read 82% / 1320",
        "     missing where the identical tree run alone read 89% / 853, with no warning",
        "     and identical pass counts. It reads LOW, so the reflex is to go write tests",
        "     for a hole that is not there.",
        "",
        "WHAT IS RUNNING:",
    ]
    for pid, cmd in offenders:
        lines.append( f"  pid {pid}  {cmd[ :160 ]}" )
    lines += [
        "",
        "REMEDY: wait for it to finish, then re-run. Check with:  pgrep -af pytest",
        f"DELIBERATE?  {ESCAPE_HATCH_ENV}=1 <your command>   (the number will not be comparable)",
    ]
    return "\n".join( lines )


def main( argv=None ) -> int:
    """
    Exit 0 clear · 1 contended · 2 unknown. UNKNOWN IS NOT CLEAR.
    """
    if escape_hatch_engaged():
        print( f"[coverage-contention] {ESCAPE_HATCH_ENV} set — check skipped.", file=sys.stderr )
        return EXIT_CLEAR
    try:
        offenders = find_foreign_pytest()
    except OSError as failure:
        print( f"[coverage-contention] UNKNOWN — could not read the process table: {failure}",
               file=sys.stderr )
        return EXIT_UNKNOWN
    if offenders:
        print( render_refusal( offenders ), file=sys.stderr )
        return EXIT_CONTENDED
    return EXIT_CLEAR


if __name__ == "__main__":   # pragma: no cover - CLI entrypoint; main() is tested directly
    sys.exit( main() )
