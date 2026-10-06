#!/usr/bin/env python3
"""
Detect another running test suite, so a coverage run can refuse to share the box.

A `pytest --cov` tier run that shared the box with a second suite reported 82%
with 1320 missing statements. The identical tree run alone reported 89% with 853.
The command, the isolated `COVERAGE_FILE` and the pass, skip and xfail counts were
the same, and nothing warned. Coverage.py has no "could not measure" state, so it
reports a number under conditions where the number means nothing.

The loss concentrated in modules reached through spawned subprocesses. The error
is hostile in direction: it makes coverage look worse, so the reflex is to write
tests for a hole that does not exist. It also has teeth. `fail_under` rises per
milestone, so a floor set from a contended run lands about 7 points too low, and
nothing goes red to say so.

The mechanism is a suspect, not a finding. Contention is the obvious difference and
subprocess-timed coverage the plausible victim, but the causal chain is unproven.
This module refuses the condition under which the number stopped being trustworthy.

`find_foreign_pytest( ... )` returns the pytest processes that are not this process
or one of its ancestors. Ancestors are excluded because the runner script that
invokes this check may be named `run-pytest-direct.sh`, and a substring match would
make every run refuse itself.

An offender must pass both tests. Its command line must be suite-shaped
(`looks_like_a_running_suite`), and its kernel `comm` must be a python or pytest
binary (`comm_could_be_pytest`). The command line says what somebody wrote. The
comm says what the process is. Only the pair is sufficient.

The shape half has two independent clauses, kept apart:
  1. `looks_like_pytest`: a `pytest` token in a program position.
  2. `looks_like_a_direct_test_file_run`: an interpreter running a `test_*.py` path
     directly, with no pytest token at all. Many unit test files run a real suite as
     `python <file>.py`, because their `__main__` calls `pytest.main(...)`.
Clause 2 is separate because widening clause 1's token rule would re-admit the
quoted-search-pattern and spawn-brief false positives it was tightened to close.

CLI: `python3 -m cosa.utils.coverage_contention`. Exit 0 is clear, 1 is contended
(offenders on stderr), 2 is unknown (the process table could not be read). Unknown
is not clear: the caller decides what to do, and this module never softens it.
"""

import os
import re
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
    Return True when `cmdline` looks like a pytest invocation rather than a mention.

    A token counts as an invocation when its basename is exactly "pytest" and it is in
    a program position. That means first on the line (a PATH-resolved `pytest -q`),
    an absolute path (`/opt/venv/bin/pytest`), or preceded by `-m` (`python3 -m pytest`).

    Requires:
        - cmdline is a string (may be empty)

    Ensures:
        - returns True only for an invocation-shaped command line
        - a path that merely contains the word pytest (a runner script named
          run-pytest-direct.sh, an open editor buffer, /usr/bin/pytest-watch)
          returns False
        - a relative path ending in pytest returns False unless it leads the line. `.venv/bin/pytest -q` is True (index 0). The same path in any later position is overwhelmingly a quoted `pgrep -f "bin/pytest ..."` search pattern rather than a program
        - never raises

    Two known gaps are accepted for one reason. Every sanctioned runner in this tree
    resolves pytest through src/scripts/lib/resolve-venv-pytest.sh, which resolves under
    $LUPIN_ROOT and refuses a bare `python3 -m pytest` fallback. The code leans on that
    resolver, not on one spelling. Widening the rule re-admits the false positives
    above, and a false positive refuses every coverage run in the tree.
        1. a bare `pytest` behind an env prefix (`env FOO=1 pytest -q`): not first,
           not absolute, not after -m.
        2. a relative path in a non-leading position, for example
           `.venv/bin/python3 .venv/bin/pytest src/tests/unit/ -q` -> False. This is
           the script form `run-*-tests.sh` uses. It is the cheaper trade, because the
           quoted-pattern false positive it closes was silent and total.
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


# ⚠️ A SECOND SHAPE CLAUSE, NOT A WIDENING OF THE FIRST — row from 2026-08-30 (found by
# Rachel 🕊️, measured by Tiberius 👑). The token rule above can only see a command line that
# CONTAINS the word pytest. A test file invoked directly does not contain it anywhere:
#
#     .venv/bin/python src/tests/unit/test_outreach_ledger.py     -> 12 passed in 0.17s
#
# **181 of the 699 files under src/tests/unit/ run a real suite this way**, because their
# `__main__` calls pytest.main(...) or unittest.main(...). Every one of them was invisible to
# this module: looks_like_pytest returned False, so the process never reached the comm gate —
# which would have admitted it (comm=python3.13). The shape test was the sole thing hiding it.
#
# ⇒ THE FIX IS A SEPARATE CLAUSE BECAUSE THE TOKEN RULE MUST NOT MOVE. That rule has been
# tightened twice — absolute-paths-only (2026-08-26, the quoted `pgrep -f "bin/pytest src/"`
# pattern) and the comm gate (2026-08-30, a peer seat whose spawn brief quotes `-m pytest`).
# Loosening it to catch a no-pytest-token command line would have to match on something other
# than the token, i.e. re-open both. A clause keyed on the SCRIPT BEING RUN shares no
# machinery with it and therefore cannot.
#
# ⚠️ AND IT IS NOT A LICENCE TO BE LOOSE. This clause is deliberately narrow in three ways,
# each closing a false positive the token rule already paid for:
#   - the interpreter must LEAD the line, so `vim .../test_x.py` and `grep -rn test_x.py src/`
#     never match;
#   - `-c` and `-m` ABORT it, so `python3 -c "... test_x.py ..."` (this row's own repro
#     command, and every seat brief that quotes one) does not match — under -c the following
#     token is code, and under -m it is a module name, neither of which is a script;
#   - only the FIRST non-option token is examined — the script — never a later argument.
# The comm gate still applies on top, exactly as it does to the token rule.


_TEST_FILE_BASENAME = re.compile( r"^(test_.+|.+_test)\.py$" )


def looks_like_a_direct_test_file_run( cmdline: str ) -> bool:
    """
    Return True when `cmdline` is an interpreter running a test file directly.

    The shape is `<python> [options] <path/to/test_something.py> [args]`, with no
    pytest token anywhere. That is why `looks_like_pytest` cannot see it.

    Requires:
        - cmdline is a string (may be empty)

    Ensures:
        - True for an interpreter leading the line whose first non-option argument has a
          basename matching `test_*.py` or `*_test.py`, by absolute or relative path
        - False when the leading token is not an interpreter: an editor, a grep, a
          `pytest` invocation (that one is clause 1's job)
        - False when `-c` or `-m` appears before the script. Under `-c` the next token
          is code and under `-m` it is a module name, so neither is a file being run
          and both are shapes a peer's command line quotes verbatim
        - False when the first non-option token is an ordinary script (`manage.py`)
        - never raises

    One narrowing is accepted. An option that takes a separate value before the script
    (`python -X importtime test_x.py`) is read as `-X` then `importtime`, which is not
    test-shaped, so the line returns False. It fails toward a miss rather than a false
    refusal. A false refusal blocks every coverage run in the tree; a miss blocks none.
    A table of value-taking options would be one more thing to keep in sync with CPython.
    """
    if not cmdline: return False
    tokens = cmdline.split()
    if not tokens: return False
    if not _PYTHON_COMM.match( os.path.basename( tokens[ 0 ] ) ): return False
    for token in tokens[ 1: ]:
        if token.startswith( "-" ):
            if token in ( "-c", "-m" ): return False
            continue
        return bool( _TEST_FILE_BASENAME.match( os.path.basename( token ) ) )
    return False


def looks_like_a_running_suite( cmdline: str ) -> bool:
    """
    Return True when either shape clause matches: the whole shape half of the gate.

    There is one shape predicate, and this is it. When two callers each compose the
    clauses themselves they drift, and a guard with two sources of truth answers
    differently depending on the door. `find_foreign_pytest` calls this and nothing else.

    Requires:
        - cmdline is a string (may be empty)

    Ensures:
        - True when either a pytest token is in a program position (clause 1) or an
          interpreter is running a test file directly (clause 2)
        - the two clauses are disjoint in practice, since clause 2 requires no pytest
          token, so neither can mask a regression in the other
        - never raises
    """
    return looks_like_pytest( cmdline ) or looks_like_a_direct_test_file_run( cmdline )


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
# 🔴 THERE IS EXACTLY ONE comm PREDICATE, AND IT IS comm_could_be_pytest BELOW.
# Two existed for a few hours on 2026-08-30: this row's fix and row 9078a035's landed
# independently on the same function and merged together, leaving one predicate per author
# with OPPOSITE answers for an unreadable comm. The composition silently took the fail-OPEN
# one, contradicting this module's doctrine AND the commit message that introduced it. A
# guard with two sources of truth for one question is the "one truth in two places" hazard
# pyproject's coverage comments warn about, one mechanism over. Do not add a second.


def _default_comm_of( pid: int ) -> Optional[str]:
    """
    Return the kernel's name for a process, or None when it cannot be determined.

    Ensures:
        - returns the stripped contents of /proc/<pid>/comm when readable
        - returns None when the process has exited (its /proc entry is gone), the
          same race `_default_process_table` already absorbs, one step later
        - returns "" when /proc/<pid> still exists but comm could not be read, which
          keeps the caller fail-closed: an unreadable live process stays an offender
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


_PYTHON_COMM = re.compile( r"^python[0-9.]*$" )


def comm_could_be_pytest( comm: str ) -> bool:
    """
    Return True when a process's `comm` is one a pytest run could actually have.

    Requires:
        - comm is a string (may be empty)

    Ensures:
        - True for "pytest" and for a whole interpreter name (python, python3,
          python3.13), since a real pytest runs under one of these
        - False for "claude", and for anything else that is not interpreter-shaped
        - False for "python3-config" and "python3.10-config", which a
          startswith("python") test called interpreters. Their shebang is #!/bin/sh,
          so a real invocation's comm is "sh"; the predicate should still answer its
          own question correctly
        - an empty comm returns True, so an unreadable comm can never turn a real
          suite invisible: unknown stays a refusal, never a pass

    Why comm matters: it says what a process is, while the command line says what
    somebody wrote about it. A Claude seat carries its entire spawn brief in argv, so
    a brief that merely quotes a command such as `.venv/bin/python -B -m pytest
    src/tests/unit/` looks like a running suite to any argv-only check. Such seats are
    long-lived, so the guard would stay shut for as long as they live. That failure is
    worse than the contention it guards against, because it has no timeout. The same
    family as the quoted `pgrep -f "bin/pytest src/"` pattern, one vector over:
    requiring an absolute path closed the first and cannot close the second. The
    positive form is to match `comm`, never the command line.

    The whole-name match is a narrowing. A tighter test risks missing a real suite,
    which takes somebody's box away. It does not here, because the excluded names
    provably cannot run pytest. "Looser is safer under fail-closed doctrine" holds only
    when the excluded thing could be an interpreter. These cannot.
    """
    if not comm: return True
    return comm == "pytest" or bool( _PYTHON_COMM.match( comm ) )


def _default_process_table() -> List[ Tuple[ int, str ] ]:
    """
    Return every readable (pid, cmdline) from /proc; raise OSError if /proc is unusable.

    The comm filter lives in find_foreign_pytest, not here. With the
    filter in both places, the real path was filtered twice and an injected
    process_table only once. A test could then pass against a shape production never
    sees. One gate, one code path, so every caller gets the same answer.
    """
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


def _comm_admits_a_running_suite( comm: Optional[str] ) -> bool:
    """
    Return whether a comm value leaves a pytest-shaped command line an offender.

    Requires:
        - comm is a real name, "" for a live process whose comm could not be read, or
          None for a process that has exited

    Ensures:
        - returns False only for None, or for a real name that is not an interpreter
        - returns True for "", keeping an unreadable live process an offender

    The three values are three different facts, and collapsing any two breaks the
    guard in one direction or the other:

        real name ("python3", "bash")  ->  ask the predicate. A named non-interpreter
                                           is a seat quoting a command, not a suite.
        "" (alive, unreadable)         ->  offender. "Could not look" is not "nothing
                                           there". Refusing costs a wait; passing costs
                                           a silently wrong coverage number.
        None (exited)                  ->  not an offender. There is nothing to contend with.

    _default_comm_of already makes this distinction and promises fail-closed on "".
    The caller once passed "" straight to the predicate, whose own contract said False,
    and the process was dropped. Neither function was wrong alone; the two contracts
    did not meet. A test must supply all three values: with only a readable
    interpreter name, the old and new code answer identically.
    """
    if comm is None:  return False
    # ⚠️ DELIBERATELY REDUNDANT with comm_could_be_pytest's own `if not comm: return True`
    # (Rachel spotted the duplication 2026-08-30; keeping it is the considered answer).
    # This line is the FAIL-CLOSED contract boundary. Folding it would make the gate's
    # answer for "" depend on the predicate continuing to agree — and "two contracts that
    # did not meet" is the exact defect this module was written to fix.
    #
    # 🔴 AND THIS LINE IS **MASKED**: NO TEST CAN FAIL ON IT WHILE THE DELEGATE AGREES.
    # I first wrote here that both sites were "pinned independently, so the duplication is
    # checked, not merely asserted". That was WRONG, and Rachel's mutation proved it —
    # confirmed independently: DELETE THIS LINE and the suites stay green (127 passed),
    # because `test_all_three_comm_values_are_distinguished` and this function's own `""`
    # case both observe the OUTPUT, which comm_could_be_pytest still supplies. Mutating the
    # DELEGATE is caught (rc=1); mutating THIS site is not caught by anything.
    #
    # That is the price of the belt, and it is stated rather than hidden: the redundancy is
    # deliberate AND unfalsifiable, so it is defended by this comment and by review, not by
    # the harness. Catalogued as `masked-invariant`
    # (io/post-games/2026.08.30-instruments-that-cannot-fail-post-game.md §6). ⚠️ Do NOT
    # "fix" the masking by deleting this line — the redundancy is the point; the missing
    # proof is the cost.
    if comm == "":    return True
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
                and looks_like_a_running_suite( cmd )
                and _comm_admits_a_running_suite( name_of( pid ) ) ]
    return sorted( found, key=lambda row: row[ 0 ] )


def escape_hatch_engaged( environ=None ) -> bool:
    """
    Return True when the operator has chosen to allow a contended coverage run.

    Ensures:
        - only an explicit truthy value engages it; "0", "false", "" and absent
          all read as not engaged, so a leftover `=0` in a shell profile cannot
          silently disable the guard
    """
    raw = ( environ if environ is not None else os.environ ).get( ESCAPE_HATCH_ENV, "" )
    return raw.strip().lower() in ( "1", "true", "yes", "on" )


def render_refusal( offenders: List[ Tuple[ int, str ] ] ) -> str:
    """
    Build the message a refused run prints, naming the offenders and the remedy.
    """
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
    Run the check and return an exit code: 0 clear, 1 contended, 2 unknown.

    Unknown is not clear. The environment escape hatch skips the check and returns 0.
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
