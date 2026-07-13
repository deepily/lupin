"""
Coverage Guard — reconcile counted commits against an independent git oracle.

Born from bugs `bbff93a3` + `37a8beeb` (2026-07-13). The roll-up had been reporting
numbers that were **self-consistent and confidently wrong** for weeks: a whole commit
on `main` was structurally uncountable, and nothing complained — because every internal
cross-check agreed with every other internal cross-check.

The lesson generalizes past this bug: *an aggregate that only ever checks itself cannot
discover that it is blind.* So after each repo is analyzed, we ask git a SECOND,
INDEPENDENT question — "how many commits are in this window?" — and assert that the
number of commits we actually counted matches.

The project workflow already mandates "never silently swallow" for **errors**. This
extends that rule to **coverage**, which is the failure class that actually bit us.

Usage:
    from cosa.repo.git_loc_delta.coverage_guard import reconcile_coverage

    report = reconcile_coverage(
        repo_path    = "/path/to/repo",
        counted_shas = agg.all_shas(),
        since        = "2026-07-08",
        until        = "2026-07-14",
        all_branches = True,
    )
    if not report[ "reconciled" ]:
        print( report[ "warning" ], file=sys.stderr )
"""

import subprocess
from typing import List, Optional, Set

from .exceptions import GitCommandError


def _rev_list_shas(
    repo_path:      str,
    since:          Optional[str],
    until:          Optional[str],
    rev_range:      Optional[str],
    all_branches:   bool,
    include_merges: bool,
    timeout:        int,
) -> Set[str]:
    """
    Ask git, independently of the numstat walk, which SHAs are in the window.

    Deliberately uses `git rev-list` rather than re-parsing `git log --numstat`
    output: the guard is worthless if it shares a code path (and therefore a bug)
    with the thing it is auditing. Different porcelain, same question.

    Requires:
        - repo_path is a valid git repository
        - since / until are ISO date strings or None
        - timeout is a positive integer

    Ensures:
        - Returns the set of commit SHAs git reports for the window
        - Selection flags mirror GitLogParser._build_command EXACTLY, so any
          difference in the result is a real coverage gap and not a flag skew

    Raises:
        - GitCommandError if the underlying git invocation fails
    """
    cmd = [ "git", "rev-list" ]
    if not include_merges:
        cmd.append( "--no-merges" )
    if since: cmd.append( f"--since={since}" )
    if until: cmd.append( f"--until={until}" )
    if all_branches:
        cmd.append( "--branches" )
    if rev_range:
        cmd.append( rev_range )
    elif not all_branches:
        # rev-list, unlike log, has no implicit HEAD default — name it explicitly.
        cmd.append( "HEAD" )

    try:
        result = subprocess.run(
            cmd,
            capture_output = True,
            text           = True,
            timeout        = timeout,
            cwd            = repo_path,
        )
    except subprocess.TimeoutExpired:
        raise GitCommandError(
            message     = f"git rev-list timed out after {timeout} seconds",
            command     = cmd,
            return_code = -1,
        )
    except FileNotFoundError:
        raise GitCommandError(
            message = "Git command not found. Is git installed?",
            command = cmd,
        )

    if result.returncode != 0:
        raise GitCommandError(
            message     = f"git rev-list failed with return code {result.returncode}",
            command     = cmd,
            return_code = result.returncode,
            stderr      = result.stderr,
            stdout      = result.stdout,
        )

    return { line.strip() for line in result.stdout.splitlines() if line.strip() }


def reconcile_coverage(
    repo_path:      str,
    counted_shas:   Set[str],
    since:          Optional[str] = None,
    until:          Optional[str] = None,
    rev_range:      Optional[str] = None,
    all_branches:   bool          = False,
    include_merges: bool          = False,
    repo_name:      Optional[str] = None,
    timeout:        int           = 60,
    debug:          bool          = False,
) -> dict:
    """
    Reconcile the commits we COUNTED against the commits git says are IN the window.

    Requires:
        - counted_shas is the set of unique SHAs the aggregator actually recorded
          (i.e. DailyAggregator.all_shas())
        - The selection arguments are the SAME ones handed to GitLogParser — a guard
          run against a different window audits nothing

    Ensures:
        - Returns a report dict:
            {
              "repo":         str,
              "reconciled":   bool,          # True iff nothing is missing
              "expected":     int,           # commits git reports in the window
              "counted":      int,           # commits we recorded a change row for
              "uncounted":    [ sha, ... ],  # in git's set, absent from ours
              "unexpected":   [ sha, ... ],  # in ours, absent from git's — a real alarm
              "warning":      str | None,    # rendered, ready to print to stderr
            }
        - `uncounted` is NOT automatically a bug: a commit whose only changes are
          binary files, or an empty commit, legitimately produces zero countable
          rows. It IS, however, always the operator's business — so we name the SHAs
          and let a human judge, rather than inferring benignity and staying quiet.
        - `unexpected` (we counted a commit git says is out of window) is never benign:
          it means the walk and the filter disagree — the author-date/committer-date
          class of bug. Surfaced with its own line.

    Raises:
        - GitCommandError if the git oracle invocation fails
    """
    expected_shas = _rev_list_shas(
        repo_path      = repo_path,
        since          = since,
        until          = until,
        rev_range      = rev_range,
        all_branches   = all_branches,
        include_merges = include_merges,
        timeout        = timeout,
    )

    uncounted  = sorted( expected_shas - counted_shas )
    unexpected = sorted( counted_shas - expected_shas )
    reconciled = not uncounted and not unexpected
    label      = repo_name or repo_path

    warning: Optional[str] = None
    if not reconciled:
        lines: List[str] = [
            f"⚠️  COVERAGE MISMATCH — {label}: git reports {len(expected_shas)} commit(s) "
            f"in this window; we counted changes for {len(counted_shas)}."
        ]
        if uncounted:
            lines.append(
                f"    {len(uncounted)} commit(s) in the window produced NO counted rows: "
                + ", ".join( s[ :8 ] for s in uncounted[ :10 ] )
                + ( f" (+{len(uncounted) - 10} more)" if len( uncounted ) > 10 else "" )
            )
            lines.append(
                "    Benign if those commits are binary-only or empty. NOT benign if the "
                "range is excluding real work — that is bug bbff93a3's signature."
            )
        if unexpected:
            lines.append(
                f"    {len(unexpected)} counted commit(s) are OUTSIDE git's window: "
                + ", ".join( s[ :8 ] for s in unexpected[ :10 ] )
                + ( f" (+{len(unexpected) - 10} more)" if len( unexpected ) > 10 else "" )
            )
            lines.append(
                "    The walk and the date filter disagree — check the date basis "
                "(committer vs author date). This is never benign."
            )
        warning = "\n".join( lines )

    if debug:
        print( f"[coverage_guard] {label}: expected={len(expected_shas)} counted={len(counted_shas)} reconciled={reconciled}" )

    return {
        "repo":       label,
        "reconciled": reconciled,
        "expected":   len( expected_shas ),
        "counted":    len( counted_shas ),
        "uncounted":  uncounted,
        "unexpected": unexpected,
        "warning":    warning,
    }
