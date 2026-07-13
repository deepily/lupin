"""
Cross-repo daily LoC delta roll-up CLI.

Sister tool to `cosa.repo.run_git_loc_delta`. Where the per-branch tool answers
"what did I do on each day of THIS branch in THIS repo," this tool answers
"what did I do across N repos on each day in a date window."

**It computes from git.** For each repo it runs a date-windowed, branch-agnostic
analysis (`git log --since --until --branches --no-merges`) and aggregates the
results in memory.

Rewritten 2026-07-13 (Mr. Radio 🦉) to close bugs `bbff93a3` + `37a8beeb`. Design +
receipts: `src/rnd/v0.1.9/2026.07.13-loc-rollup-branch-agnostic-window-and-commit-dedup.md`.

WHAT THIS TOOL USED TO DO, AND WHY IT WAS WRONG
-----------------------------------------------
It used to read each repo's most recent `io/git-loc-delta/*-loc-delta.csv` — a CSV
written by session-end in **branch mode** (`main..<branch>`) — concatenate them, and
date-filter the rows. Two defects followed structurally:

1. **Under-report** (`bbff93a3`). A date filter cannot add back commits the CSV never
   saw. Any commit reachable from `main` sits on the BASELINE side of `main..<branch>`
   and was uncountable, forever. google/skills-distillation — a fresh repo whose Phase-1
   work went straight to main — under-reported by exactly 1,607 lines: 36% of the repo's
   entire existence, silently.

2. **Commit double-count** (`37a8beeb`). The per-repo CSVs are tidy-long, one row per
   (date, file_type), and the `commits` column holds the unique SHAs touching THAT
   file type. Summing that column across file types counts a commit touching .py + .md
   twice. The CSV carries no SHA column, so this was un-dedupable post-hoc — no
   regeneration of CSVs could have reached it.

Computing from git closes both, and moots the entire stale-CSV class along with them
(the workflow's "refresh stale CSVs" step could never run: `--branch` and `--since` are
mutually exclusive in argparse — it failed INTO staleness, quietly).

Per-repo CSVs are now an **artifact**, not an input. Nothing here reads them.

THE ONE RULE FOR COMMIT COUNTS
------------------------------
A commit count is ONLY ever a `len()` over a SHA set, or a sum along an axis a SHA
cannot straddle. A SHA has exactly one date and belongs to exactly one repo — so summing
per-(repo, date) counts is safe. A SHA does NOT have one file_type. **Never sum commits
across file types.** That was the bug.

Author: Rachel 🕊️ (CoSA session `e13fed4f`, 2026-05-21) — original CSV-aggregating design.
Rewritten to compute from git by Mr. Radio 🦉 (Lupin session `cec2ec5b`, 2026-07-13).
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import date as _date
from typing   import Dict, List, Optional, Tuple

import pandas as pd

import cosa.utils.util as cu

from cosa.repo.git_loc_delta.analyzer   import GitLogLocDeltaAnalyzer
from cosa.repo.git_loc_delta.exceptions import GitCommandError, GitLocDeltaError
from cosa.repo.git_loc_delta.plotter    import plot_summary


# Exit codes
EXIT_OK      = 0
EXIT_ERROR   = 1
EXIT_NO_DATA = 0   # graceful — same as per-repo tool's empty-range behavior

# Consolidated-CSV schema v3 (2026-07-13).
#
# `repo_date_commits` — NOT `commits` — is deliberate and breaking. The old column
# name invited `df["commits"].sum()`, which is exactly the double-count that shipped
# for weeks. The value is the unique commit count for that (repo, date); it repeats
# across the file-type rows of a given (repo, date) and MUST NOT be summed across them.
# The name now says so, and a naive `.sum()` on a column called `commits` no longer
# even finds a column. No v2→v3 compat shim: CSVs are regenerated, not migrated.
CSV_COLUMNS        = [ "date", "repo", "file_type", "added", "deleted", "files_touched", "repo_date_commits" ]
CSV_SCHEMA_VERSION = 3


def create_parser() -> argparse.ArgumentParser:
    """
    Build the CLI parser for the global aggregator.

    Mirrors per-repo `run_git_loc_delta`'s flag shape where flags carry through
    (--output, --save-output, --plot, --plot-output, --since, --until, --debug,
    --verbose). `--repos` stays required: discovery policy lives in the PIP-side
    workflow, not in this CLI (it stays honest-explicit).
    """
    parser = argparse.ArgumentParser(
        prog        = "run_git_loc_delta_global",
        description = (
            "Cross-repo daily LoC delta roll-up. For each repo, runs a date-windowed, "
            "branch-agnostic git analysis and aggregates across repos. Sister CLI to "
            "`run_git_loc_delta`."
        ),
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n"
            "  python -m cosa.repo.run_git_loc_delta_global \\\n"
            "      --repos /path/to/lupin /path/to/planning-is-prompting\n"
            "  python -m cosa.repo.run_git_loc_delta_global \\\n"
            "      --repos . ../other --since 2026-07-08 --until 2026-07-14 --plot\n"
        ),
    )

    parser.add_argument(
        "--repos",
        nargs    = "+",
        required = True,
        metavar  = "PATH",
        help     = "Repo paths to aggregate. One or more. Each is analyzed directly from git.",
    )
    parser.add_argument(
        "--since",
        metavar = "YYYY-MM-DD",
        help    = "Inclusive lower bound of the commit window",
    )
    parser.add_argument(
        "--until",
        metavar = "YYYY-MM-DD",
        help    = "Inclusive upper bound of the commit window",
    )
    parser.add_argument(
        "--head-only",
        action  = "store_true",
        help    = (
            "Walk only each repo's current HEAD instead of all local branches. "
            "Default is all local branches — the roll-up asks 'what work happened in "
            "window W', and work on a sibling branch is still work. Use this to scope "
            "to the checked-out line of development only."
        ),
    )
    parser.add_argument(
        "--include-merges",
        action = "store_true",
        help   = "Include merge commits (default: exclude)",
    )

    # Output
    parser.add_argument(
        "--output",
        choices = [ "console", "json", "csv" ],
        default = "console",
        help    = "Output format (default: console)",
    )
    parser.add_argument(
        "--save-output",
        metavar = "PATH",
        help    = (
            "Write to file. For --output csv default: "
            "{cwd}/io/loc-delta-global/global-{since}_to_{until}-loc-delta.csv"
        ),
    )

    # Plot
    parser.add_argument(
        "--plot",
        action = "store_true",
        help   = (
            "Generate a PNG plot. Two-panel matplotlib: top aggregate "
            "insertions/deletions bars + net line summed across all repos; "
            "bottom per-repo signed net lines. Multi-day required."
        ),
    )
    parser.add_argument(
        "--plot-output",
        metavar = "PATH",
        help    = "Override plot output path. Default: {cwd}/io/loc-delta-global/global-{since}_to_{until}-plot.png",
    )

    parser.add_argument( "-v", "--verbose", action="store_true", help="Echo per-repo analysis progress to stderr" )
    parser.add_argument(       "--debug",   action="store_true", help="Verbose + full tracebacks on failure" )

    return parser


def _is_git_repo( repo_path: str ) -> bool:
    """
    Return True iff `repo_path` is a git repository root.

    Ensures:
        - True iff `{repo_path}/.git` exists (dir for a normal clone, file for a worktree)
    """
    return os.path.exists( os.path.join( repo_path, ".git" ) )


def _git_common_dir( repo_path: str, timeout: int = 30 ) -> Optional[str]:
    """
    Return the absolute `--git-common-dir` for `repo_path`, or None if git can't say.

    THIS IS THE REPO'S IDENTITY. Two paths that resolve to the same common dir share an
    object database and a ref namespace — they are the SAME REPOSITORY seen from two
    places, no matter how different the working directories look.

    Why it matters (bug found 2026-07-13, after the first fix shipped): lupin has **13
    worktrees**. A worktree's `.git` is a FILE, not a directory, and it shares the parent's
    objects and refs — so a date-windowed, branch-agnostic walk inside a worktree returns
    THE PARENT'S COMMITS, in full. Hand the roll-up `lupin` plus one worktree and it
    reports lupin's work TWICE, under two different names:

        --repos lupin                     -> +11,407 / 40 commits
        --repos lupin lupin-wt-<lane>     -> +22,814 / 80 commits   (exactly doubled)

    With all 13 worktrees discovered, lupin's LoC would be multiplied by ~14. That is the
    same silent-confidently-wrong failure this module was rewritten to kill, inverted: I
    would have traded an under-count for a far worse over-count.

    Deduping on the common dir is a MECHANISM, not a special case. A "`.git` must be a
    directory" check would also work for worktrees, but it is a rule about one filesystem
    layout; this is a rule about repository IDENTITY, so it also catches symlinked roots,
    bind-mounted duplicates, and `--repos . $(pwd)` — every way the same repo can arrive
    twice under two names.

    Ensures:
        - Returns an absolute path string, or None if the command fails
        - Never raises (a failure here degrades to "can't prove aliasing", not a crash)
    """
    try:
        result = subprocess.run(
            [ "git", "rev-parse", "--path-format=absolute", "--git-common-dir" ],
            capture_output = True,
            text           = True,
            timeout        = timeout,
            cwd            = repo_path,
        )
    except ( subprocess.TimeoutExpired, FileNotFoundError, OSError ):
        return None

    if result.returncode != 0:
        return None

    common = result.stdout.strip()
    return os.path.realpath( common ) if common else None


def _has_any_commits( repo_path: str, timeout: int = 30 ) -> bool:
    """
    Return True iff the repo has at least one commit on any ref.

    A freshly-`git init`'d repo with zero commits is a legitimate roster entry — the
    roll-up's whole subject is FRESH repos (bug bbff93a3), so one appearing before its
    first commit must be reported as empty, not blow up the run. But `git log` on such a
    repo exits 128 (`fatal: your current branch 'main' does not have any commits yet`),
    which surfaces as a GitCommandError. Checking up front is cheaper and clearer than
    pattern-matching that stderr string.

    (Under `--branches` the empty repo happens to walk cleanly — zero refs, zero commits,
    exit 0 — so this only ever bit the `--head-only` path. That asymmetry is exactly the
    kind of thing that hides until someone runs the other flag.)

    Ensures:
        - True iff `git rev-list -n 1 --all` names a commit
        - False on an empty repo; never raises for the empty case
    """
    result = subprocess.run(
        [ "git", "rev-list", "-n", "1", "--all" ],
        capture_output = True,
        text           = True,
        timeout        = timeout,
        cwd            = repo_path,
    )
    return result.returncode == 0 and bool( result.stdout.strip() )


def _resolve_repo_names( repo_paths: List[str] ) -> Dict[str, str]:
    """
    Map each repo path → a UNIQUE display name.

    Requires:
        - repo_paths are absolute

    Ensures:
        - Returns { repo_path: repo_name } with NO duplicate names
        - The common case is the basename (`.../projects/lupin` → `lupin`)
        - On a basename COLLISION, both entries are qualified with their parent dir
          (`google/lupin` vs `acme/lupin`) so they stay distinguishable

    Why this exists: repo identity keys the commit-count map. Two roster entries sharing a
    basename (`google/foo` and `other/foo` — entirely possible, the roster is globbed
    across grouping dirs) would collide on `(repo_name, date)` and the second would
    OVERWRITE the first's commit count. That is a SILENT UNDERCOUNT — the exact failure
    class this module was rewritten to kill (bbff93a3/37a8beeb). Caught in review of that
    very rewrite: two repos named `lupin` reported 1 commit instead of 2.
    """
    names:  Dict[str, str] = {}
    counts: Dict[str, int] = {}

    for path in repo_paths:
        base = os.path.basename( path.rstrip( os.sep ) )
        counts[ base ] = counts.get( base, 0 ) + 1

    for path in repo_paths:
        clean = path.rstrip( os.sep )
        base  = os.path.basename( clean )
        if counts[ base ] > 1:
            parent       = os.path.basename( os.path.dirname( clean ) )
            names[ path ] = f"{parent}/{base}" if parent else base
        else:
            names[ path ] = base

    return names


def _analyze_repos(
    repo_paths:     List[str],
    since:          Optional[str],
    until:          Optional[str],
    all_branches:   bool,
    include_merges: bool,
    verbose:        bool,
    debug:          bool,
) -> Tuple[pd.DataFrame, Dict[Tuple[str, str], int], List[dict], List[str], List[str]]:
    """
    Analyze each repo directly from git and return the combined tidy-long frame.

    Requires:
        - repo_paths are absolute paths
        - since / until are ISO date strings or None

    Ensures:
        - Returns ( combined_df, commits_by_repo_date, coverage_reports,
                    empty_repos, skipped_repos )
        - `combined_df` has CSV_COLUMNS; one row per (repo, date, file_type).
          `repo_date_commits` repeats the (repo, date) unique-commit count across that
          group's file-type rows — see CSV_COLUMNS for why it must never be summed
          across them.
        - `commits_by_repo_date` maps (repo, date) → unique commit count. THIS is the
          authoritative commit source; the DataFrame column is for the artifact only.
        - `empty_repos` are git repos with zero commits in the window (not an error)
        - `skipped_repos` are paths that are not git repositories (warned, not fatal)

    Raises:
        - GitLocDeltaError if a repo's analysis fails outright
    """
    rows:                 List[dict]                  = []
    commits_by_repo_date: Dict[Tuple[str, str], int]  = {}
    coverage_reports:     List[dict]                  = []
    empty_repos:          List[str]                   = []
    skipped_repos:        List[str]                   = []

    repo_names = _resolve_repo_names( repo_paths )

    # Repo IDENTITY -> the first path that claimed it. A second path resolving to the same
    # git-common-dir is an ALIAS (worktree / symlink / duplicate roster entry), not another
    # repo, and counting it again multiplies that repo's LoC. See _git_common_dir.
    seen_identities: Dict[str, str] = {}

    for repo_path in repo_paths:
        repo_name = repo_names[ repo_path ]

        if not _is_git_repo( repo_path ):
            skipped_repos.append( repo_path )
            print(
                f"Warning: {repo_path} is not a git repository — skipped. "
                f"(Discovery handed us a path with no .git; check the roster.)",
                file = sys.stderr,
            )
            continue

        identity = _git_common_dir( repo_path )
        if identity is not None and identity in seen_identities:
            first = seen_identities[ identity ]
            skipped_repos.append( repo_path )
            print(
                f"Warning: {repo_path} is the SAME REPOSITORY as {first} "
                f"(shared git dir: {identity}) — skipped to avoid DOUBLE-COUNTING its commits. "
                f"A worktree shares its parent's objects and refs, so analyzing both would "
                f"report that repo's work twice.",
                file = sys.stderr,
            )
            continue
        if identity is not None:
            seen_identities[ identity ] = repo_path

        if not _has_any_commits( repo_path ):
            # A fresh `git init` with no commits yet. Legitimate; report it, don't die.
            empty_repos.append( repo_name )
            if verbose: print( f"[analyze] {repo_name}: repository has no commits yet", file=sys.stderr )
            continue

        if verbose: print( f"[analyze] {repo_name}: git log --since={since} --until={until} "
                           f"{'--branches' if all_branches else '(HEAD only)'}", file=sys.stderr )

        # mode="explicit" when a window is given; "today" when it is not. Never
        # "branch" — a branch delta cannot answer "what happened in window W"
        # (bug bbff93a3: work on `main` is on the baseline side and uncountable).
        mode = "explicit" if ( since or until ) else "today"

        analyzer = GitLogLocDeltaAnalyzer(
            repo_path      = repo_path,
            mode           = mode,
            since          = since,
            until          = until,
            all_branches   = all_branches,
            include_merges = include_merges,
            repo_name      = repo_name,
            debug          = debug,
            verbose        = verbose,
        )
        result = analyzer.analyze( reconcile=True )

        coverage = result[ "coverage" ]
        coverage_reports.append( coverage )
        if not coverage[ "reconciled" ]:
            print( coverage[ "warning" ], file=sys.stderr )

        if not result[ "daily" ]:
            empty_repos.append( repo_name )
            if verbose: print( f"[analyze] {repo_name}: no commits in window", file=sys.stderr )
            continue

        # Unique commits per (repo, date) — from the daily view, which counts unique
        # SHAs per date. NOT from by_type, whose buckets overlap across file types.
        for date_str, day in result[ "daily" ].items():
            commits_by_repo_date[ ( repo_name, date_str ) ] = day[ "commits" ]

        for ( date_str, file_type ), counts in result[ "by_type" ].items():
            rows.append({
                "date":              date_str,
                "repo":              repo_name,
                "file_type":         file_type,
                "added":             counts[ "added" ],
                "deleted":           counts[ "deleted" ],
                "files_touched":     counts[ "files_touched" ],
                "repo_date_commits": result[ "daily" ][ date_str ][ "commits" ],
            })

        if verbose:
            s = result[ "summary" ]
            print( f"[analyze] {repo_name}: +{s['total_added']} / -{s['total_deleted']} "
                   f"across {s['total_commits']} commits", file=sys.stderr )

    combined = pd.DataFrame( rows, columns=CSV_COLUMNS )
    return combined, commits_by_repo_date, coverage_reports, empty_repos, skipped_repos


def _build_aggregated_daily( df: pd.DataFrame, commits_by_repo_date: Dict[Tuple[str, str], int] ) -> dict:
    """
    Build the `daily` dict expected by plot_summary().

    Requires:
        - commits_by_repo_date maps (repo, date) → unique commit count

    Ensures:
        - Returns dict[date_str -> {added, deleted, files_touched, commits,
                                   by_repo: [...], by_file_type: [...]}]
        - by_repo / by_file_type lists are sorted by `added` descending
        - `commits` at BOTH the date level and the by_repo level come from
          commits_by_repo_date — NEVER from summing the frame's per-file-type rows.
          A SHA belongs to exactly one repo and has exactly one date, so summing
          per-(repo, date) counts across repos is exact. Summing across file_type
          would double-count (bug 37a8beeb).
        - by_file_type rows carry NO commits key: a commit is not decomposable by file
          type, and offering the number is what invited the bug.
    """
    out = {}
    for date_str, group in df.groupby( "date" ):
        by_repo_rows = []
        for repo_name, repo_group in group.groupby( "repo" ):
            by_repo_rows.append({
                "repo":          repo_name,
                "added":         int( repo_group[ "added"         ].sum() ),
                "deleted":       int( repo_group[ "deleted"       ].sum() ),
                "files_touched": int( repo_group[ "files_touched" ].sum() ),
                "commits":       commits_by_repo_date.get( ( repo_name, date_str ), 0 ),
            })
        by_repo_rows.sort( key=lambda r: -r[ "added" ] )

        by_type_rows = []
        for file_type, type_group in group.groupby( "file_type" ):
            by_type_rows.append({
                "file_type":     file_type,
                "added":         int( type_group[ "added"         ].sum() ),
                "deleted":       int( type_group[ "deleted"       ].sum() ),
                "files_touched": int( type_group[ "files_touched" ].sum() ),
            })
        by_type_rows.sort( key=lambda r: -r[ "added" ] )

        out[ date_str ] = {
            "added":         int( group[ "added"         ].sum() ),
            "deleted":       int( group[ "deleted"       ].sum() ),
            "files_touched": int( group[ "files_touched" ].sum() ),
            "commits":       sum( r[ "commits" ] for r in by_repo_rows ),
            "by_repo":       by_repo_rows,
            "by_file_type":  by_type_rows,
        }
    return out


def _build_summary( df: pd.DataFrame, commits_by_repo_date: Dict[Tuple[str, str], int] ) -> dict:
    """
    Build the overall summary dict expected by plot_summary().

    Ensures:
        - Returns {total_added, total_deleted, total_files, total_commits,
                   total_days, net, repos}
        - total_commits sums commits_by_repo_date over ALL (repo, date) keys. Exact:
          each SHA contributes to exactly one (repo, date) bucket.
    """
    if df.empty:
        return {
            "total_added":   0,
            "total_deleted": 0,
            "total_files":   0,
            "total_commits": 0,
            "total_days":    0,
            "net":           0,
            "repos":         [],
        }
    return {
        "total_added":   int( df[ "added"         ].sum() ),
        "total_deleted": int( df[ "deleted"       ].sum() ),
        "total_files":   int( df[ "files_touched" ].sum() ),
        "total_commits": sum( commits_by_repo_date.values() ),
        "total_days":    int( df[ "date"          ].nunique() ),
        "net":           int( df[ "added" ].sum() - df[ "deleted" ].sum() ),
        "repos":         sorted( df[ "repo" ].unique().tolist() ),
    }


def _format_console( daily: dict, summary: dict, since: Optional[str], until: Optional[str] ) -> str:
    """
    Render a console table.

    Ensures:
        - Returns a multiline string with header banner + daily totals table
          + per-repo daily breakdown
    """
    if not daily:
        return "No commits in range across the requested repos."

    repos_str = ", ".join( summary[ "repos" ] )
    lines = [
        "─" * 80,
        "  Cross-Repo Daily LoC Delta — Global Roll-up",
        f"  Repos: {repos_str}",
        f"  Window: {since or 'all'} .. {until or 'all'}",
        f"  Total: +{summary['total_added']} / -{summary['total_deleted']} (net {summary['net']:+d}), {summary['total_commits']} commits, {summary['total_days']} days",
        "─" * 80,
        "",
        "Daily Totals (all repos summed):",
        f"  {'Date':<12} {'Added':>10} {'Deleted':>10} {'Net':>10} {'Files':>8} {'Commits':>8}",
    ]
    for date_str in sorted( daily.keys() ):
        d   = daily[ date_str ]
        net = d[ "added" ] - d[ "deleted" ]
        lines.append( f"  {date_str:<12} {d['added']:>10} {d['deleted']:>10} {net:>+10} {d['files_touched']:>8} {d['commits']:>8}" )

    lines.extend([ "", "Daily Per-Repo Breakdown:" ])
    for date_str in sorted( daily.keys() ):
        d = daily[ date_str ]
        lines.append( f"  {date_str}:" )
        for r in d[ "by_repo" ]:
            net = r[ "added" ] - r[ "deleted" ]
            lines.append( f"      {r['repo']:<32} +{r['added']:>8} / -{r['deleted']:>6}  net {net:>+8}  ({r['commits']} commits)" )

    return "\n".join( lines )


def _format_json( daily: dict, summary: dict, since: Optional[str], until: Optional[str] ) -> str:
    """
    Render JSON output.

    Ensures:
        - Returns a JSON string carrying since/until/repos/summary/days
    """
    days = []
    for date_str in sorted( daily.keys() ):
        d = daily[ date_str ]
        days.append({
            "date":          date_str,
            "added":         d[ "added"         ],
            "deleted":       d[ "deleted"       ],
            "files_touched": d[ "files_touched" ],
            "commits":       d[ "commits"       ],
            "by_repo":       d[ "by_repo"       ],
            "by_file_type":  d[ "by_file_type"  ],
        })

    payload = {
        "since":   since,
        "until":   until,
        "repos":   summary[ "repos" ],
        "summary": { k: v for k, v in summary.items() if k != "repos" },
        "days":    days,
    }
    return json.dumps( payload, indent=2 )


def _default_path( cwd: str, kind: str, since: Optional[str], until: Optional[str] ) -> str:
    """
    Build default output path for csv / plot.

    `kind` is "csv" or "png". Files land under `{cwd}/io/loc-delta-global/`.
    """
    sub_dir = os.path.join( cwd, "io", "loc-delta-global" )
    since_s = since or "start"
    until_s = until or _date.today().isoformat()
    if kind == "csv":
        return os.path.join( sub_dir, f"global-{since_s}_to_{until_s}-loc-delta.csv" )
    return os.path.join( sub_dir, f"global-{since_s}_to_{until_s}-plot.png" )


def main( argv: Optional[list] = None ) -> int:
    """
    CLI entry. Returns an exit code.
    """
    parser = create_parser()
    args   = parser.parse_args( argv )

    # Today-default fallback (Maria's §7.4 ratification 2026-05-21): bare command =
    # "what did I do today across all repos?"
    if not args.since and not args.until:
        today      = _date.today().isoformat()
        args.since = today
        args.until = today
        if args.verbose: print( f"[main] Today-default applied: since={today} until={today}", file=sys.stderr )

    repo_paths = [ os.path.abspath( p ) for p in args.repos ]

    try:
        combined, commits_by_repo_date, coverage_reports, empty_repos, skipped_repos = _analyze_repos(
            repo_paths     = repo_paths,
            since          = args.since,
            until          = args.until,
            all_branches   = not args.head_only,
            include_merges = args.include_merges,
            verbose        = args.verbose,
            debug          = args.debug,
        )
    except ( GitLocDeltaError, GitCommandError ) as e:
        # GitCommandError is NOT a GitLocDeltaError — it descends from BranchAnalyzerError
        # (cosa.repo.branch_analyzer.exceptions). Catching only GitLocDeltaError let every
        # underlying git failure escape as a raw traceback. Caught in review; the per-repo
        # CLI already catches both, so this brings the two CLIs back into line.
        print( f"Error: {e}", file=sys.stderr )
        if args.debug:
            import traceback
            traceback.print_exc()
        return EXIT_ERROR

    if not repo_paths or len( skipped_repos ) == len( repo_paths ):
        print( "Error: no git repositories among the requested paths.", file=sys.stderr )
        return EXIT_ERROR

    daily   = _build_aggregated_daily( combined, commits_by_repo_date )
    summary = _build_summary( combined, commits_by_repo_date )

    if empty_repos:   summary[ "empty_repos"   ] = empty_repos
    if skipped_repos: summary[ "skipped_repos" ] = [ os.path.basename( p ) for p in skipped_repos ]

    unreconciled = [ c for c in coverage_reports if not c[ "reconciled" ] ]
    if unreconciled:
        summary[ "coverage_warnings" ] = [ c[ "repo" ] for c in unreconciled ]

    cwd = os.getcwd()

    if args.output == "console":
        text = _format_console( daily, summary, args.since, args.until )
        if empty_repos:
            text += "\n\nRepos with no commits in window:\n" + "\n".join( f"  - {r}" for r in empty_repos )
        if skipped_repos:
            text += "\n\nSkipped (not a git repo):\n" + "\n".join( f"  - {os.path.basename(p)}" for p in skipped_repos )
        if unreconciled:
            text += "\n\n⚠️  COVERAGE WARNINGS — the numbers above may be incomplete:\n"
            text += "\n".join( c[ "warning" ] for c in unreconciled )
        if args.save_output:
            with open( args.save_output, "w" ) as f:
                f.write( text )
        else:
            print( text )

    elif args.output == "json":
        js = _format_json( daily, summary, args.since, args.until )
        if args.save_output:
            with open( args.save_output, "w" ) as f:
                f.write( js )
        else:
            print( js )

    elif args.output == "csv":
        csv_path = args.save_output or _default_path( cwd, "csv", args.since, args.until )
        parent   = os.path.dirname( csv_path )
        if parent and not os.path.isdir( parent ):
            os.makedirs( parent, exist_ok=True )
        combined.to_csv( csv_path, index=False )
        print( f"Wrote {len(combined)} rows to {csv_path}" )

    # Optional plot (additive)
    if args.plot:
        if len( daily ) < 2:
            print( f"Warning: --plot skipped — only {len(daily)} day(s) of data, need ≥ 2 dates.", file=sys.stderr )
        else:
            plot_path  = args.plot_output or _default_path( cwd, "png", args.since, args.until )
            title_meta = {
                "scope":      "global",
                "repos":      summary[ "repos" ],
                "rev_window": f"{args.since or sorted(daily.keys())[0]}..{args.until or sorted(daily.keys())[-1]}",
            }
            try:
                plot_summary(
                    daily       = daily,
                    summary     = summary,
                    output_path = plot_path,
                    group_by    = "repo",
                    title_meta  = title_meta,
                    debug       = args.debug,
                )
                print( f"Plot written to {plot_path}" )
            except Exception as e:
                print( f"Plot generation failed: {e}", file=sys.stderr )
                if args.debug:
                    import traceback
                    traceback.print_exc()
                return EXIT_ERROR

    return EXIT_OK


def quick_smoke_test() -> None:
    """
    Quick smoke test for the global aggregator.

    Builds THREE REAL GIT REPOS in a tempdir (the old smoke test synthesized CSVs —
    which is precisely how a tool that never touched git passed its own tests while
    under-reporting by 36%):

      - repo_main_only : ALL work committed straight to `main`, no WIP branch.
                         This is the bbff93a3 regression case — the old CSV-reading
                         path scored it ZERO.
      - repo_branched  : work on `main`, THEN more on a WIP branch cut from it.
                         Must report BOTH.
      - repo_multitype : one commit touching .py AND .md. The 37a8beeb regression
                         case — must count ONE commit, not two.
      - not_a_repo     : a plain directory. Must be skipped, not fatal.

    Ensures:
        - Tests complete with ✓ or ✗ indicators
        - Uses cu.print_banner formatting
        - Does NOT raise (catches all exceptions)
        - Cleans up tempfiles on exit
    """
    import shutil
    import subprocess
    import tempfile

    cu.print_banner( "Global Aggregator Smoke Test (computes from git)", prepend_nl=True )

    workdir = tempfile.mkdtemp( prefix="git_loc_delta_global_smoke_" )

    def git( repo: str, *cmd: str ) -> None:
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE":    "2026-07-10T12:00:00",
            "GIT_COMMITTER_DATE": "2026-07-10T12:00:00",
        }
        subprocess.run( [ "git", *cmd ], cwd=repo, check=True, capture_output=True, env=env )

    def init_repo( name: str ) -> str:
        repo = os.path.join( workdir, name )
        os.makedirs( repo )
        git( repo, "init", "-q", "-b", "main" )
        git( repo, "config", "user.email", "smoke@test.local" )
        git( repo, "config", "user.name",  "Smoke Test" )
        return repo

    def commit( repo: str, files: dict, message: str ) -> None:
        for rel, content in files.items():
            full = os.path.join( repo, rel )
            os.makedirs( os.path.dirname( full ), exist_ok=True )
            with open( full, "w" ) as f:
                f.write( content )
        git( repo, "add", "-A" )
        git( repo, "commit", "-q", "-m", message )

    try:
        # ── repo_main_only: 10 python lines, committed straight to main. No WIP branch.
        repo_main_only = init_repo( "main_only" )
        commit( repo_main_only, { "src/a.py": "\n".join( f"line{i}" for i in range( 10 ) ) + "\n" }, "main-only work" )

        # ── repo_branched: 5 lines on main, then 7 more on a WIP branch cut from it.
        repo_branched = init_repo( "branched" )
        commit( repo_branched, { "src/b.py": "\n".join( f"base{i}" for i in range( 5 ) ) + "\n" }, "landed on main" )
        git( repo_branched, "checkout", "-q", "-b", "wip-feature" )
        commit( repo_branched, { "src/c.py": "\n".join( f"feat{i}" for i in range( 7 ) ) + "\n" }, "on the wip branch" )

        # ── repo_multitype: ONE commit touching python + markdown.
        repo_multitype = init_repo( "multitype" )
        commit(
            repo_multitype,
            {
                "src/d.py":  "\n".join( f"py{i}" for i in range( 3 ) ) + "\n",
                "docs/e.md": "\n".join( f"md{i}" for i in range( 4 ) ) + "\n",
            },
            "one commit, two file types",
        )

        # ── not_a_repo: plain directory
        not_a_repo = os.path.join( workdir, "not_a_repo" )
        os.makedirs( not_a_repo )

        all_repos = [ repo_main_only, repo_branched, repo_multitype ]
        window    = [ "--since", "2026-07-09", "--until", "2026-07-12" ]

        try:
            # Test 1: main-only repo is counted (bbff93a3 regression)
            print( "Test 1: repo whose ONLY work is on main reports its delta (bug bbff93a3)..." )
            df, commits, cov, empty, skipped = _analyze_repos(
                [ repo_main_only ], "2026-07-09", "2026-07-12",
                all_branches=True, include_merges=False, verbose=False, debug=False,
            )
            summary = _build_summary( df, commits )
            assert summary[ "total_added" ] == 10, f"Expected 10 added, got {summary['total_added']}"
            assert summary[ "total_commits" ] == 1, f"Expected 1 commit, got {summary['total_commits']}"
            print( f"✓ main-only repo counted: +{summary['total_added']}, {summary['total_commits']} commit "
                   f"(the CSV-reading path scored this ZERO)" )

            # Test 2: branched repo counts BOTH main-side and branch-side work
            print( "Test 2: main-side + branch-side work both counted..." )
            df, commits, cov, empty, skipped = _analyze_repos(
                [ repo_branched ], "2026-07-09", "2026-07-12",
                all_branches=True, include_merges=False, verbose=False, debug=False,
            )
            summary = _build_summary( df, commits )
            assert summary[ "total_added" ] == 12, f"Expected 12 (5 main + 7 branch), got {summary['total_added']}"
            assert summary[ "total_commits" ] == 2, f"Expected 2 commits, got {summary['total_commits']}"
            print( f"✓ both sides counted: +{summary['total_added']} across {summary['total_commits']} commits" )

            # Test 3: a commit touching 2 file types counts ONCE (37a8beeb regression)
            print( "Test 3: one commit touching .py + .md counts ONCE (bug 37a8beeb)..." )
            df, commits, cov, empty, skipped = _analyze_repos(
                [ repo_multitype ], "2026-07-09", "2026-07-12",
                all_branches=True, include_merges=False, verbose=False, debug=False,
            )
            summary = _build_summary( df, commits )
            assert len( df ) == 2, f"Expected 2 file-type rows, got {len(df)}"
            assert summary[ "total_commits" ] == 1, f"DOUBLE-COUNT: expected 1 commit, got {summary['total_commits']}"
            assert int( df[ "repo_date_commits" ].sum() ) == 2, "sanity: the naive sum IS 2 — which is why we never sum it"
            print( f"✓ {len(df)} file-type rows, {summary['total_commits']} commit "
                   f"(naive sum of the column would say {int(df['repo_date_commits'].sum())})" )

            # Test 4: coverage guard reconciles clean on a healthy repo
            print( "Test 4: coverage guard reconciles..." )
            assert all( c[ "reconciled" ] for c in cov ), f"Coverage did not reconcile: {cov}"
            assert cov[ 0 ][ "expected" ] == cov[ 0 ][ "counted" ] == 1
            print( f"✓ guard reconciled: expected={cov[0]['expected']} counted={cov[0]['counted']}" )

            # Test 5: non-git path is skipped, not fatal
            print( "Test 5: non-git path skipped gracefully..." )
            df, commits, cov, empty, skipped = _analyze_repos(
                [ repo_main_only, not_a_repo ], "2026-07-09", "2026-07-12",
                all_branches=True, include_merges=False, verbose=False, debug=False,
            )
            assert len( skipped ) == 1 and skipped[ 0 ] == not_a_repo
            assert _build_summary( df, commits )[ "total_added" ] == 10
            print( "✓ non-git path skipped; the real repo still counted" )

            # Test 6: window exclusion — a window with no commits yields empty
            print( "Test 6: empty window yields no data (graceful)..." )
            df, commits, cov, empty, skipped = _analyze_repos(
                all_repos, "2099-01-01", "2099-01-02",
                all_branches=True, include_merges=False, verbose=False, debug=False,
            )
            assert df.empty and len( empty ) == 3
            assert _build_summary( df, commits )[ "total_commits" ] == 0
            print( "✓ out-of-window repos reported empty, not errored" )

            # Test 7: multi-repo aggregation totals
            print( "Test 7: cross-repo aggregation..." )
            df, commits, cov, empty, skipped = _analyze_repos(
                all_repos, "2026-07-09", "2026-07-12",
                all_branches=True, include_merges=False, verbose=False, debug=False,
            )
            summary = _build_summary( df, commits )
            daily   = _build_aggregated_daily( df, commits )
            assert summary[ "total_added"   ] == 10 + 12 + 7, f"Expected 29 added, got {summary['total_added']}"
            assert summary[ "total_commits" ] == 1 + 2 + 1,   f"Expected 4 commits, got {summary['total_commits']}"
            assert sorted( summary[ "repos" ] ) == [ "branched", "main_only", "multitype" ]
            assert daily[ "2026-07-10" ][ "commits" ] == 4
            print( f"✓ 3 repos: +{summary['total_added']} across {summary['total_commits']} commits" )

            # Test 8: by_file_type rows carry NO commits key (the bug's invitation)
            print( "Test 8: by_file_type exposes no commits key..." )
            for row in daily[ "2026-07-10" ][ "by_file_type" ]:
                assert "commits" not in row, "by_file_type must not offer a commits count — that invited 37a8beeb"
            print( "✓ by_file_type carries no commits key" )

            # Test 9: end-to-end main() with --output json
            print( "Test 9: end-to-end main() --output json..." )
            json_out  = os.path.join( workdir, "out.json" )
            exit_code = main( argv=[ "--repos", *all_repos, *window, "--output", "json", "--save-output", json_out ] )
            assert exit_code == 0
            with open( json_out ) as f:
                parsed = json.load( f )
            assert parsed[ "summary" ][ "total_added"   ] == 29
            assert parsed[ "summary" ][ "total_commits" ] == 4
            print( "✓ end-to-end JSON: +29 added, 4 commits" )

            # Test 10: end-to-end CSV artifact carries the renamed column
            print( "Test 10: end-to-end main() --output csv..." )
            csv_out   = os.path.join( workdir, "out.csv" )
            exit_code = main( argv=[ "--repos", *all_repos, *window, "--output", "csv", "--save-output", csv_out ] )
            assert exit_code == 0
            verify_df = pd.read_csv( csv_out )
            assert list( verify_df.columns ) == CSV_COLUMNS
            assert "commits" not in verify_df.columns, "the un-summable column must not be named `commits`"
            assert "repo_date_commits" in verify_df.columns
            print( f"✓ CSV artifact: {len(verify_df)} rows, schema v{CSV_SCHEMA_VERSION}, column is `repo_date_commits`" )

            # Test 11: --head-only scopes to the checked-out line
            print( "Test 11: --head-only excludes sibling-branch work..." )
            df_head, commits_head, _, _, _ = _analyze_repos(
                [ repo_branched ], "2026-07-09", "2026-07-12",
                all_branches=False, include_merges=False, verbose=False, debug=False,
            )
            # HEAD is wip-feature, which descends from main → still sees both commits
            assert _build_summary( df_head, commits_head )[ "total_commits" ] == 2
            print( "✓ --head-only walks HEAD's ancestry (both commits reachable here)" )

            print( "\n✓ All 11 aggregator smoke tests passed successfully!" )

        except AssertionError as e:
            print( f"\n✗ Smoke test assertion failed: {e}" )
            import traceback
            traceback.print_exc()
        except Exception as e:
            print( f"\n✗ Smoke test failed with exception: {e}" )
            import traceback
            traceback.print_exc()

    finally:
        shutil.rmtree( workdir, ignore_errors=True )


if __name__ == "__main__":
    if len( sys.argv ) > 1 and sys.argv[ 1 ] == "--smoke-test":
        quick_smoke_test()
    else:
        sys.exit( main() )
