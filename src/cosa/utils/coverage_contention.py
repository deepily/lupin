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

An offender must pass BOTH tests: its command line must be invocation-SHAPED
(`looks_like_pytest`) AND the kernel must agree the process IS a python or pytest
binary (`comm_could_be_pytest`, read from /proc/<pid>/comm). The two answer
different questions — the command line says what somebody WROTE, comm says what
the process IS — and only the pair is sufficient. See the docstring on
`comm_could_be_pytest` for the measurements that forced this.

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
    an ABSOLUTE path (`/opt/venv/bin/pytest`), or preceded by `-m` (`python3 -m pytest`).

    Requires:
        - cmdline is a string (may be empty)

    Ensures:
        - returns True only for an invocation-shaped command line
        - a path that merely CONTAINS the word pytest (a runner script named
          run-pytest-direct.sh, an open editor buffer, /usr/bin/pytest-watch)
          returns False
        - a RELATIVE path ending in pytest returns False — it is overwhelmingly a
          quoted `pgrep -f "bin/pytest ..."` search pattern rather than a program
        - never raises

    ⚠️ TWO KNOWN GAPS, both accepted deliberately, and for the same reason: every
    sanctioned runner in this tree invokes pytest by an ABSOLUTE path
    (src/scripts/lib/resolve-venv-pytest.sh resolves under $LUPIN_ROOT and refuses to
    fall back to a bare `python3 -m pytest`), so neither shape occurs here, and
    widening the rule to cover either one re-admits the false positives above — which
    cost more, because a false positive refuses EVERY coverage run in the tree.
        1. a bare `pytest` behind an env prefix (`env FOO=1 pytest -q`) — neither
           first, nor absolute, nor after -m.
        2. a RELATIVE path (`.venv/bin/pytest -q`, typed by hand from the repo root).
           This is the one gap opened on 2026-08-26 to close the quoted-pattern false
           positive, and it is the cheaper trade: a hand-typed relative invocation is
           rare and visible, while the false positive was silent and total.
    """
    if not cmdline: return False
    tokens = cmdline.split()
    for index, token in enumerate( tokens ):
        if os.path.basename( token ) != "pytest": continue
        if index == 0: return True
        # ⚠️ ABSOLUTE paths only. This read `if "/" in token` until 2026-08-26 and that
        # matched the QUOTED SEARCH PATTERN inside a peer's wait-for-the-box loop —
        # `pgrep -f "bin/pytest src/"` splits to a token whose basename is "pytest" and
        # which contains a slash, so an IDLE session waiting for the box read as a running
        # suite and every coverage run in the tree was refused (row e2099400, measured
        # against the live command line, twice). Every sanctioned runner invokes pytest by
        # an ABSOLUTE path — src/scripts/lib/resolve-venv-pytest.sh resolves under
        # $LUPIN_ROOT and refuses a bare fallback — so requiring the leading slash costs
        # nothing real and drops the whole quoted-pattern class.
        if token.startswith( "/" ): return True
        if tokens[ index - 1 ] == "-m": return True
    return False


# ⚠️ THE COMMAND LINE ALONE IS NOT ENOUGH, AND THIS COST A GATE RUN ON 2026-08-30.
# The shape test above was already tightened once (absolute paths only, so a quoted
# `pgrep -f "bin/pytest src/"` no longer matches). The hole that survived is the `-m`
# clause: a peer Claude seat whose SPAWN BRIEFING quoted the command
#     LUPIN_ROOT="$PWD" .venv/bin/python -m pytest src/tests/unit/test_x.py -q
# has that text in its own /proc/<pid>/cmdline, because a seat's briefing IS its command
# line. So it read as a running suite and the coverage gate refused both tiers on a box
# where the comm-based count of real pytest processes was ZERO (measured: pid 22130,
# comm=claude). The sanctioned way out is the escape hatch, which stamps the number "not
# comparable" — so the false positive does not merely annoy, it degrades the receipt.
#
# ⇒ ASK THE KERNEL WHAT THE PROCESS IS, not what its command line says about it. A
# briefing that TALKS about running pytest has comm="claude"; a suite that IS running has
# comm="pytest" or "python3.13". This is CLAUDE.md §"IS ANOTHER SUITE RUNNING?" — the
# pgrep-over-a-fleet-of-agents trap — and it gets MORE likely the more the fleet
# coordinates about the box, because a briefing about testing is the text most likely to
# contain the command.
#
# ⚠️ THIS IS ADDED TO THE SHAPE TEST, NEVER SUBSTITUTED FOR IT. comm alone would flag every
# `python3 -c ...` on the box. The shape test also still earns the pytest-watch exclusion
# documented above. Both, or neither works.
#
# ⚠️ AND IT MEANS A SPOOFED argv NO LONGER FOOLS THE GUARD — which is the point, but it
# also retired the old end-to-end fixture. `exec -a "/usr/bin/pytest x" sleep 20` has
# comm="sleep" (verified), so it was never a real foreign suite, only a real foreign
# COMMAND LINE. The end-to-end test now spawns an actual `-m pytest`.
# 🔴 THERE IS EXACTLY ONE comm PREDICATE, AND IT LIVES AT comm_could_be_pytest BELOW.
# Two of them existed for about an hour on 2026-08-30: this row's fix and row 9078a035's
# landed independently on the same function and were merged together, leaving one predicate
# per author with OPPOSITE answers for an unreadable comm — one kept the process (fail
# closed), one dropped it (fail open). The composition silently took the fail-OPEN answer,
# which is the direction this module's whole doctrine forbids, and it contradicted the
# commit message that introduced it. A guard with two sources of truth for one question is
# the "frame in two places" hazard that pyproject's coverage comments warn about, one
# mechanism over. If you are about to add a second one, do not.


def _default_comm_of( pid: int ) -> Optional[str]:
    """
    The kernel's name for a process, or None when it cannot be determined.

    Ensures:
        - returns the stripped contents of /proc/<pid>/comm when readable
        - returns None when the process has EXITED (its /proc entry is gone) — the
          same race `_default_process_table` already absorbs, one step later
        - returns "" when /proc/<pid> still exists but comm could not be read, which
          keeps the caller FAIL-CLOSED: an unreadable live process stays an offender
          rather than being waved through on a technicality
    """
    try:
        with open( f"/proc/{pid}/comm" ) as handle:
            return handle.read().strip()
    except OSError:
        return "" if os.path.exists( f"/proc/{pid}" ) else None


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


def comm_could_be_pytest( comm: str ) -> bool:
    """
    True when a process's `comm` is one a pytest run could actually have.

    ⚠️ THIS IS THE HALF THE COMMAND LINE CANNOT ANSWER, and it is why the guard reads
    /proc/<pid>/comm at all. `comm` says what a process IS; the command line says what
    somebody WROTE about it. A Claude seat carries its entire spawn brief in argv, so a
    brief that merely QUOTES a command — `.venv/bin/python -B -m pytest src/tests/unit/`
    — is indistinguishable from a running suite to any argv-only check.

    MEASURED 2026-08-30 (row 9078a035, while taking a coverage measurement that could not
    start). The guard refused a --cov run naming two processes as live suites:

        pid  22130  comm=claude   argv contains "-m pytest"   (spawn brief for row a8222a71)
        pid 124554  comm=claude   argv contains "-m pytest"   (spawn brief for row c89cec9b)

    Neither was running anything. Both are long-lived seats, so the guard would not have
    opened again for as long as they lived — the "gate never opens on an idle box" failure,
    which is worse than the contention it guards against because it has no timeout. The
    real suite on the box at that moment appeared in NEITHER of the guard's two named rows.

    This is the same family as the quoted-search-pattern case fixed above on 2026-08-26,
    one vector over: that one was a peer's `pgrep -f "bin/pytest src/"`, this one is a
    peer's spawn brief. Requiring an absolute path closed the first and cannot close the
    second, because "-m pytest" is exactly the shape a brief quotes.

    ⇒ The positive form is the one CLAUDE.md § "IS ANOTHER SUITE RUNNING?" already
    prescribes: match `comm`, never the command line.

    Requires:
        - comm is a string (may be empty)

    Ensures:
        - True for "pytest" and for any interpreter name beginning "python"
          (python, python3, python3.13 — a real pytest runs under one of these)
        - False for "claude", and for anything else that is not interpreter-shaped
        - an EMPTY comm returns True, so an unreadable comm can never turn a real
          suite invisible — unknown stays a refusal, never a pass
    """
    if not comm: return True
    return comm == "pytest" or comm.startswith( "python" )


def _default_process_table() -> List[ Tuple[ int, str ] ]:
    """
    Every readable (pid, cmdline) from /proc, EXCLUDING processes whose `comm` says they
    cannot be a pytest run. See comm_could_be_pytest for why the cmdline alone is not
    enough and what it measured.

    Raises OSError if /proc is unusable.
    """
    rows = []
    for entry in os.listdir( "/proc" ):
        if not entry.isdigit(): continue
        try:
            with open( f"/proc/{entry}/cmdline", "rb" ) as handle:
                raw = handle.read()
        except OSError:
            continue                      # the process exited between listdir and open
        try:
            with open( f"/proc/{entry}/comm" ) as handle:
                comm = handle.read().strip()
        except OSError:
            comm = ""                     # unreadable -> treated as could-be, never skipped
        if not comm_could_be_pytest( comm ): continue
        rows.append( ( int( entry ), raw.replace( b"\0", b" " ).decode( "utf-8", "replace" ).strip() ) )
    return rows


def _comm_admits_a_suite( comm: Optional[str] ) -> bool:
    """
    Whether a pid's comm leaves open the possibility that it is running a suite.

    The pid-level companion to comm_could_be_pytest, which takes a string. The ONLY thing
    added here is the None case, and the two are deliberately different:

        None  the process EXITED between the table read and this read. A dead process
              cannot contend for the box, so it is dropped.
        ""    the process is ALIVE and its comm could not be read. Unknown is never
              cleared in this module (see main()'s exit 2), so it is KEPT.

    Requires:
        - comm is a comm string, "" for live-but-unreadable, or None for gone

    Ensures:
        - returns False for None
        - otherwise defers entirely to comm_could_be_pytest, so there is one answer
    """
    if comm is None: return False
    return comm_could_be_pytest( comm )


def find_foreign_pytest(
    process_table : Optional[ Callable[ [], Iterable[ Tuple[ int, str ] ] ] ]=None,
    ancestors     : Optional[ Iterable[int] ]=None,
    comm_of       : Optional[ Callable[ [int], Optional[str] ] ]=None,
) -> List[ Tuple[ int, str ] ]:
    """
    Pytest processes that are neither this process nor one of its ancestors.

    Requires:
        - process_table, when supplied, is a callable returning (pid, cmdline) pairs
        - ancestors, when supplied, is an iterable of pids to exclude
        - comm_of, when supplied, maps a pid to its kernel name (or None if gone)

    Ensures:
        - returns [] when the only pytest processes belong to our own tree
        - excludes ancestors, so a runner script whose own name contains
          "pytest" never causes a run to refuse itself
        - excludes any process whose command line is invocation-SHAPED but whose
          comm is not an interpreter — a peer agent seat quoting `-m pytest` in
          its briefing is not a running suite
        - excludes a process that exited between the table read and the comm read
        - the result is sorted by pid, so two callers see the same order

    Raises:
        - OSError if the process table cannot be read at all
    """
    table   = ( process_table or _default_process_table )()
    ours    = set( _default_ancestors() if ancestors is None else ancestors )
    name_of = comm_of or _default_comm_of
    found   = [ ( pid, cmd ) for pid, cmd in table
                if pid not in ours
                and looks_like_pytest( cmd )
                and _comm_admits_a_suite( name_of( pid ) ) ]
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
        "REMEDY: wait for it to finish, then re-run. Check with:",
        "  ps -eo comm,args --no-headers | awk '$1==\"pytest\" || ($1 ~ /^python/ && $0 ~ / -m pytest/)'",
        "  (A pgrep over command lines is NOT equivalent: it also finds every agent seat",
        "   whose briefing merely TALKS about running pytest. comm is what the process IS.)",
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
