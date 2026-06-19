"""
CLI entry point for the Daily LoC Delta tool.

Usage:
    python -m cosa.repo.run_git_loc_delta [OPTIONS]

See `--help` for the full flag list. Mirrors the CLI shape of
`run_branch_analyzer.py` (Reuse Map R4).

Exit codes:
    0 — success
    1 — git failure (GitCommandError / DateRangeError)
    2 — argument-parse error (argparse default)
"""

import argparse
import os
import subprocess
import sys
from datetime import date as _date
from typing   import Optional

import cosa.utils.util as cu

from cosa.repo.git_loc_delta.analyzer        import GitLogLocDeltaAnalyzer
from cosa.repo.git_loc_delta.csv_writer      import write_csv, write_sidecar
from cosa.repo.git_loc_delta.exceptions      import DateRangeError, GitCommandError, GitLocDeltaError
from cosa.repo.git_loc_delta.report_formatter import format_console, format_json
from cosa.repo.git_loc_delta.plotter         import plot_summary


def create_parser() -> argparse.ArgumentParser:
    """
    Create the command-line argument parser.

    Ensures:
        - Returns a fully configured argparse.ArgumentParser
        - All flags documented with help text
        - Mutually exclusive group enforces single date-range mode

    Raises:
        - Never raises
    """
    parser = argparse.ArgumentParser(
        prog        = "run_git_loc_delta",
        description = (
            "Per-day breakdown of LoC adds/deletes from `git log --numstat`. "
            "Sister tool to branch_analyzer (which answers 'what did the whole "
            "branch change') — this answers 'what changed when'."
        ),
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n"
            "  python -m cosa.repo.run_git_loc_delta\n"
            "  python -m cosa.repo.run_git_loc_delta --branch\n"
            "  python -m cosa.repo.run_git_loc_delta --branch --output csv\n"
            "  python -m cosa.repo.run_git_loc_delta --branch --plot\n"
            "  python -m cosa.repo.run_git_loc_delta --branch --output csv --plot\n"
            "  python -m cosa.repo.run_git_loc_delta --since 2026-05-01 --until 2026-05-15 --plot\n"
        ),
    )

    parser.add_argument(
        "--repo-path",
        default = ".",
        help    = "Repository to analyze (default: cwd)",
    )

    parser.add_argument(
        "--repo-name",
        metavar = "NAME",
        default = None,
        help    = (
            "Explicit repo identity for the schema v2 `repo` CSV column + sidecar JSON. "
            "Default: basename of the target repo's git-toplevel directory. "
            "Use to disambiguate sub-repos (e.g. `cosa` inside `lupin`)."
        ),
    )

    # Date range mode (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--today",
        action  = "store_true",
        help    = "(Default) Commits since today 00:00 local",
    )
    mode_group.add_argument(
        "--since",
        metavar = "YYYY-MM-DD",
        help    = "Inclusive lower bound for commit date",
    )
    mode_group.add_argument(
        "--branch",
        nargs   = "?",
        const   = "__CURRENT__",
        default = None,
        metavar = "BRANCH",
        help    = "Range = merge-base(BASE, BRANCH)..BRANCH. BRANCH defaults to current branch.",
    )

    parser.add_argument(
        "--until",
        metavar = "YYYY-MM-DD",
        help    = "Inclusive upper bound for commit date (default: today)",
    )
    parser.add_argument(
        "--base",
        default = "main",
        help    = "Base ref for --branch mode (default: main)",
    )

    # Filters
    parser.add_argument(
        "--include-merges",
        action = "store_true",
        help   = "Include merge commits (default: exclude)",
    )
    parser.add_argument(
        "--author",
        metavar = "EMAIL",
        help    = "Filter by commit author email (passed to git log --author; matches as substring/regex per git)",
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
            "Write to file. For --output csv, the default path is mode-aware: "
            "in --branch mode → {project_root}/io/git-loc-delta/{repo}-{branch-slug}-loc-delta.csv "
            "(stable per-branch filename for daily-overwrite workflow); "
            "in --today / --since/--until mode → {project_root}/io/git-loc-delta/{YYYY-MM-DD}-loc-delta.csv "
            "(date-stamped for archival). A sidecar `.meta.json` is written alongside the CSV "
            "with `csv_schema_version: 2` + run metadata (repo, branch, rev_range, since, until, generated_at)."
        ),
    )

    # Plot output (additive — combines with any --output)
    parser.add_argument(
        "--plot",
        action = "store_true",
        help   = (
            "Generate a PNG plot of the daily LoC delta over time. Meaningful "
            "in --branch and --since/--until multi-day modes; --today emits a "
            "warning and skips. Two-panel matplotlib: top aggregate "
            "insertions/deletions bars + net line; bottom signed per-file-type "
            "net lines. Output path is mode-aware (see --plot-output)."
        ),
    )
    parser.add_argument(
        "--plot-output",
        metavar = "PATH",
        help    = (
            "Explicit plot output path. Default: "
            "{target_repo_root}/io/git-delta-analysis/{repo}-{branch-slug}-plot.png "
            "in --branch mode, or "
            "{target_repo_root}/io/git-delta-analysis/{since}_to_{until}-plot.png "
            "in --since/--until mode."
        ),
    )

    parser.add_argument( "-v", "--verbose", action="store_true",  help="Echo git commands + per-commit progress to stderr" )
    parser.add_argument(       "--debug",   action="store_true",  help="Verbose + full tracebacks on failure" )

    return parser


def _resolve_mode( args ) -> str:
    """
    Resolve which mode the user selected based on flag combinations.

    Ensures:
        - Returns one of: "today", "explicit", "branch"
        - "today" is the default when no range flags are set
    """
    if args.branch is not None: return "branch"
    if args.since is not None or args.until is not None: return "explicit"
    return "today"


def _resolve_target_root( repo_path: str ) -> str:
    """
    Resolve the target repo's filesystem root.

    Uses `git rev-parse --show-toplevel` so the resolved root always points
    at the repo containing `repo_path`, regardless of which subdir the user
    invoked from. Falls back to `os.path.abspath(repo_path)` if the path is
    not a git repository (or if `git` is missing).

    Requires:
        - repo_path is a string pointing at a directory (relative or absolute)

    Ensures:
        - Returns an absolute path
        - Never raises (subprocess failures fall back to abspath)
    """
    target_path = os.path.abspath( repo_path )
    try:
        result = subprocess.run(
            [ "git", "rev-parse", "--show-toplevel" ],
            capture_output = True,
            text           = True,
            timeout        = 5,
            cwd            = target_path,
        )
        if result.returncode == 0:
            resolved = result.stdout.strip()
            if resolved:
                return resolved
    except Exception:
        pass
    return target_path


def _resolve_repo_name( override: Optional[str], target_root: str ) -> str:
    """
    Resolve the schema-v2 `repo` identity for CSV + sidecar + plot title.

    Ensures:
        - If `override` is non-empty, returns it verbatim
        - Else returns `basename(target_root)` if non-empty
        - Else returns "repo" (defensive default — never empty)
    """
    if override: return override
    base = os.path.basename( target_root )
    return base or "repo"


def _default_csv_path( mode: str, target_root: str, repo_name: str, branch: Optional[str] ) -> str:
    """
    Return the default CSV save path under `{target_root}/io/git-loc-delta/`.

    - **branch mode** → `{target_root}/io/git-loc-delta/{repo_name}-{branch-slug}-loc-delta.csv`
      (stable per-branch filename; daily reruns overwrite in place until merge)
    - **today / explicit mode** → `{target_root}/io/git-loc-delta/{YYYY-MM-DD}-loc-delta.csv`
      (date-stamped; daily reruns produce a dated history)

    Requires:
        - mode is one of: "today", "explicit", "branch"
        - target_root is an absolute path (already resolved by _resolve_target_root)
        - repo_name is a non-empty string (already resolved by _resolve_repo_name)
        - branch is the resolved branch name (only required for branch mode)

    Ensures:
        - Returns an absolute path under `{target_root}/io/git-loc-delta/`
        - Branch names containing `/` are slugified (`/` → `-`) for filename safety
        - Never raises
    """
    base_dir = os.path.join( target_root, "io", "git-loc-delta" )

    if mode == "branch" and branch:
        branch_slug = branch.replace( "/", "-" )
        return os.path.join( base_dir, f"{repo_name}-{branch_slug}-loc-delta.csv" )

    today = _date.today().isoformat()
    return os.path.join( base_dir, f"{today}-loc-delta.csv" )


def _default_plot_path( mode: str, target_root: str, repo_name: str, branch: Optional[str], since: Optional[str], until: Optional[str] ) -> str:
    """
    Return the default PNG plot path under `{target_root}/io/git-delta-analysis/`.

    Sister directory to `git-loc-delta/` — keeps raw CSV data separate from
    derived plot artifacts per Rick's directive.

    - **branch mode** → `{target_root}/io/git-delta-analysis/{repo_name}-{branch-slug}-plot.png`
    - **explicit (--since/--until)** → `{target_root}/io/git-delta-analysis/{since}_to_{until_or_today}-plot.png`

    Requires:
        - mode is "branch" or "explicit" (never called for "today")
        - target_root is absolute
        - repo_name is non-empty
    """
    base_dir = os.path.join( target_root, "io", "git-delta-analysis" )

    if mode == "branch" and branch:
        branch_slug = branch.replace( "/", "-" )
        return os.path.join( base_dir, f"{repo_name}-{branch_slug}-plot.png" )

    # explicit mode
    since_str = since or "start"
    until_str = until or _date.today().isoformat()
    return os.path.join( base_dir, f"{since_str}_to_{until_str}-plot.png" )


def _emit_plot( args, result: dict, mode: str, target_root: str, repo_name: str ) -> int:
    """
    Render the PNG plot from analyzer result. Called only when args.plot is set.

    Ensures:
        - Returns 0 on success, 1 on failure
        - --today mode emits a stderr warning and returns 0 (non-fatal skip)
        - Output path resolved via --plot-output override or _default_plot_path

    Failure modes (returns 1):
        - daily has < 2 dates after analysis (multi-day required for plotting)
        - matplotlib rendering raises (defensive; should not normally happen)
    """
    if mode == "today":
        print(
            "Warning: --plot has no effect in --today mode (single-day data). "
            "Use --branch or --since/--until for multi-day plots.",
            file = sys.stderr,
        )
        return 0

    daily = result.get( "daily", {} )
    if len( daily ) < 2:
        print(
            f"Warning: --plot skipped — only {len(daily)} day(s) of data, "
            "need at least 2 dates for a time-series plot.",
            file = sys.stderr,
        )
        return 0

    plot_path = args.plot_output or _default_plot_path(
        mode        = mode,
        target_root = target_root,
        repo_name   = repo_name,
        branch      = result[ "branch" ],
        since       = result[ "since" ],
        until       = result[ "until" ],
    )

    title_meta = {
        "scope":  "branch",
        "repo":   repo_name,
        "branch": result[ "branch" ] or "(date-range)",
        "since":  result[ "since" ] or sorted( daily.keys() )[ 0 ],
        "until":  result[ "until" ] or sorted( daily.keys() )[ -1 ],
    }

    try:
        plot_summary(
            daily       = daily,
            summary     = result[ "summary" ],
            output_path = plot_path,
            group_by    = "file_type",
            title_meta  = title_meta,
            debug       = args.debug,
        )
    except Exception as e:
        print( f"Plot generation failed: {e}", file=sys.stderr )
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1

    print( f"Plot written to {plot_path}" )
    return 0


def main( argv: Optional[list] = None ) -> int:
    """
    CLI entry point. Returns an exit code.

    Ensures:
        - Returns 0 on success, 1 on GitLocDeltaError or plot failure,
          2 on argparse error
        - In --debug mode, full tracebacks are printed for failures
    """
    parser = create_parser()
    args   = parser.parse_args( argv )

    mode = _resolve_mode( args )

    branch_arg = None
    if mode == "branch":
        # __CURRENT__ sentinel means "use current branch" (--branch with no value)
        branch_arg = None if args.branch == "__CURRENT__" else args.branch

    # Resolve repo identity ONCE up front — shared by analyzer + CSV + sidecar + plot
    target_root = _resolve_target_root( args.repo_path )
    repo_name   = _resolve_repo_name( args.repo_name, target_root )

    try:
        analyzer = GitLogLocDeltaAnalyzer(
            repo_path      = args.repo_path,
            mode           = mode,
            branch         = branch_arg,
            base           = args.base,
            since          = args.since,
            until          = args.until,
            include_merges = args.include_merges,
            author         = args.author,
            repo_name      = repo_name,
            debug          = args.debug,
            verbose        = args.verbose,
        )
        result = analyzer.analyze()
    except DateRangeError as e:
        # Graceful empty output for empty ranges (AC17): print the banner and exit 0
        # only for the "no commits / merge-base == HEAD" subcase. Other invalid
        # ranges (e.g. since > until) are still errors.
        if e.branch is not None and "Empty rev-range" in str( e ):
            print( "No commits in range." )
            return 0
        print( f"Error: {e}", file=sys.stderr )
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1
    except GitCommandError as e:
        print( f"Git error: {e}", file=sys.stderr )
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1
    except GitLocDeltaError as e:
        print( f"Error: {e}", file=sys.stderr )
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1

    # ── Output emission per --output choice
    if args.output == "console":
        text = format_console(
            daily     = result["daily"],
            summary   = result["summary"],
            since     = result["since"],
            until     = result["until"],
            branch    = result["branch"],
            rev_range = result["rev_range"],
        )
        if args.save_output:
            with open( args.save_output, "w" ) as f:
                f.write( text )
            if args.verbose: print( f"Saved console output to {args.save_output}", file=sys.stderr )
        else:
            print( text )

    elif args.output == "json":
        js = format_json(
            daily     = result["daily"],
            summary   = result["summary"],
            since     = result["since"],
            until     = result["until"],
            branch    = result["branch"],
            rev_range = result["rev_range"],
            repo_path = result["repo_path"],
        )
        if args.save_output:
            with open( args.save_output, "w" ) as f:
                f.write( js )
            if args.verbose: print( f"Saved JSON output to {args.save_output}", file=sys.stderr )
        else:
            print( js )

    elif args.output == "csv":
        csv_path = args.save_output or _default_csv_path(
            mode        = mode,
            target_root = target_root,
            repo_name   = repo_name,
            branch      = result["branch"],
        )
        rows = write_csv(
            by_type = result["by_type"],
            path    = csv_path,
            repo    = repo_name,
            branch  = result["branch"],
            debug   = args.debug,
        )
        sidecar_path = write_sidecar(
            csv_path  = csv_path,
            repo      = repo_name,
            branch    = result["branch"],
            rev_range = result["rev_range"],
            since     = result["since"],
            until     = result["until"],
            debug     = args.debug,
        )
        print( f"Wrote {rows} rows to {csv_path}" )
        if args.verbose: print( f"Wrote sidecar to {sidecar_path}", file=sys.stderr )

    else:
        # Shouldn't reach — argparse validates --output choices
        print( f"Unknown --output value: {args.output!r}", file=sys.stderr )
        return 1

    # ── Optional plot generation (additive, independent of --output)
    if args.plot:
        plot_exit = _emit_plot( args, result, mode, target_root, repo_name )
        if plot_exit != 0:
            return plot_exit

    return 0


if __name__ == "__main__":
    sys.exit( main() )
