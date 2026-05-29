"""
Cross-repo daily LoC delta roll-up CLI.

Sister tool to `cosa.repo.run_git_loc_delta`. Where the per-branch tool answers
"what did I do on each day of THIS branch in THIS repo," this tool answers
"what did I do across N repos on each day in a date window."

Reads per-repo CSVs from `{repo_path}/io/git-loc-delta/*-loc-delta.csv`,
concatenates them, aggregates by date, and emits console / JSON / CSV /
optional PNG plot.

Backward-compat with schema v1 CSVs (no `repo` / `branch` columns): if the
sidecar JSON is present, repo identity comes from there; otherwise from the
filename's first segment before `-loc-delta.csv`.

Author: Rachel 🕊️ (CoSA session `e13fed4f`, 2026-05-21) — implementing the
Phase 1 design ratified in Maria's PIP R&D doc
`planning-is-prompting/src/rnd/2026.05.21-cross-repo-loc-delta-rollup.md`.
"""

import argparse
import json
import os
import sys
from datetime import date as _date, datetime
from glob     import glob
from typing   import List, Optional

import pandas as pd

import cosa.utils.util as cu

from cosa.repo.git_loc_delta.plotter import plot_summary


# Exit codes
EXIT_OK            = 0
EXIT_ERROR         = 1
EXIT_NO_DATA       = 0   # graceful — same as per-repo tool's empty-range behavior


def create_parser() -> argparse.ArgumentParser:
    """
    Build the CLI parser for the global aggregator.

    Mirrors per-repo `run_git_loc_delta`'s flag shape where flags carry through
    (--output, --save-output, --plot, --plot-output, --since, --until, --debug,
    --verbose). Adds `--repos` (required for Phase 1; INI auto-discovery is a
    Phase 1.x follow-on per Maria's open Q §7.1).
    """
    parser = argparse.ArgumentParser(
        prog        = "run_git_loc_delta_global",
        description = (
            "Cross-repo daily LoC delta roll-up. Aggregates per-branch CSVs "
            "from N repos into a single global view. Sister CLI to "
            "`run_git_loc_delta`. Phase 1: explicit --repos list. "
            "Phase 1.x: hybrid INI auto-discovery (deferred — see Maria's "
            "PIP R&D doc §7.1)."
        ),
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n"
            "  python -m cosa.repo.run_git_loc_delta_global \\\n"
            "      --repos /path/to/lupin /path/to/cosa /path/to/planning-is-prompting\n"
            "  python -m cosa.repo.run_git_loc_delta_global \\\n"
            "      --repos . src/cosa --since 2026-05-15 --plot\n"
        ),
    )

    parser.add_argument(
        "--repos",
        nargs    = "+",
        required = True,
        metavar  = "PATH",
        help     = "Repo paths to aggregate. One or more. Each path's io/git-loc-delta/ is scanned for branch CSVs.",
    )
    parser.add_argument(
        "--since",
        metavar = "YYYY-MM-DD",
        help    = "Inclusive lower bound (filters the aggregated DataFrame by date)",
    )
    parser.add_argument(
        "--until",
        metavar = "YYYY-MM-DD",
        help    = "Inclusive upper bound (filters the aggregated DataFrame by date)",
    )

    # CSV selection within a repo
    parser.add_argument(
        "--prefer-branch-csv",
        action  = "store_true",
        default = True,
        help    = (
            "When multiple CSVs exist in a repo's io/git-loc-delta/, prefer the "
            "branch-mode CSV (filename starts with the repo name, not a date). "
            "Default: enabled."
        ),
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

    parser.add_argument( "-v", "--verbose", action="store_true",  help="Echo discovery + concat progress to stderr" )
    parser.add_argument(       "--debug",   action="store_true",  help="Verbose + full tracebacks on failure" )

    return parser


def _find_csv_in_repo( repo_path: str, prefer_branch: bool, verbose: bool ) -> Optional[str]:
    """
    Discover the CSV to aggregate from a given repo's io/git-loc-delta/.

    Strategy:
        1. Glob `{repo_path}/io/git-loc-delta/*-loc-delta.csv`
        2. If `prefer_branch=True`, prefer CSVs whose basename does NOT start
           with `YYYY-` (branch-mode files start with `{repo}-{branch-slug}-`)
        3. If multiple candidates remain, pick the most recently modified
        4. Return None if no CSV found (caller reports stale repo)

    Ensures:
        - Returns absolute path to a single CSV, or None
        - Skips `.meta.json` sidecars (the glob doesn't match them — they end in `.json`)
    """
    csv_dir = os.path.join( repo_path, "io", "git-loc-delta" )
    if not os.path.isdir( csv_dir ):
        if verbose: print( f"[discover] {repo_path}: io/git-loc-delta/ missing", file=sys.stderr )
        return None

    candidates = sorted( glob( os.path.join( csv_dir, "*-loc-delta.csv" ) ) )
    if not candidates:
        if verbose: print( f"[discover] {repo_path}: no CSVs found", file=sys.stderr )
        return None

    if prefer_branch:
        non_date_starting = [
            c for c in candidates
            if not os.path.basename( c )[ :5 ].replace( "-", "" ).isdigit()
        ]
        if non_date_starting:
            candidates = non_date_starting

    # Most recently modified wins (stable, deterministic single pick)
    chosen = max( candidates, key=lambda p: os.path.getmtime( p ) )
    if verbose: print( f"[discover] {repo_path}: chose {os.path.basename(chosen)}", file=sys.stderr )
    return chosen


def _load_csv_with_identity( csv_path: str, verbose: bool ) -> pd.DataFrame:
    """
    Load a per-repo CSV + sidecar JSON, returning a DataFrame with `repo`
    + `branch` columns guaranteed present.

    Handles schema v1 (no `repo`/`branch` columns) by injecting them from
    the sidecar JSON if present, or from the filename otherwise.

    Ensures:
        - Returned DataFrame has columns: date, repo, branch, file_type, added,
          deleted, files_touched, commits
        - Empty CSV (header only) returns an empty DataFrame with the same columns
    """
    df = pd.read_csv( csv_path )

    sidecar_path = f"{csv_path}.meta.json"
    sidecar_repo:   Optional[str] = None
    sidecar_branch: Optional[str] = None
    if os.path.isfile( sidecar_path ):
        try:
            with open( sidecar_path, "r" ) as f:
                meta = json.load( f )
            sidecar_repo   = meta.get( "repo" )
            sidecar_branch = meta.get( "branch" )
            if verbose: print( f"[load] {os.path.basename(csv_path)}: sidecar repo={sidecar_repo} branch={sidecar_branch}", file=sys.stderr )
        except Exception as e:
            if verbose: print( f"[load] sidecar parse failed for {sidecar_path}: {e}", file=sys.stderr )

    # Inject repo / branch columns if missing (schema v1)
    if "repo" not in df.columns:
        repo_value = sidecar_repo or _repo_from_filename( csv_path )
        df[ "repo" ] = repo_value
        if verbose: print( f"[load] injected repo={repo_value!r} (schema v1 CSV)", file=sys.stderr )

    if "branch" not in df.columns:
        branch_value = sidecar_branch or _branch_from_filename( csv_path )
        df[ "branch" ] = branch_value
        if verbose: print( f"[load] injected branch={branch_value!r} (schema v1 CSV)", file=sys.stderr )

    # Reorder columns to canonical schema v2 form
    return df[ [ "date", "repo", "branch", "file_type", "added", "deleted", "files_touched", "commits" ] ]


def _repo_from_filename( csv_path: str ) -> str:
    """
    Derive repo identity from filename when sidecar absent.

    Filename pattern: `{repo}-{branch-slug}-loc-delta.csv` (branch mode).
    Returns the first segment before the first `-wip-` or `-loc-delta`.

    Defensive: returns "unknown" if pattern doesn't match.
    """
    stem = os.path.basename( csv_path ).removesuffix( "-loc-delta.csv" )
    # Branch mode: stem is `{repo}-{branch-slug}`. Date mode: stem is `YYYY-MM-DD`.
    # Heuristic: if stem starts with 4 digits, treat as date-mode (no repo embedded → use parent dir's parent)
    if stem[ :4 ].isdigit():
        # `{repo_path}/io/git-loc-delta/{date}-loc-delta.csv`
        # repo path → 3 dirs up from the CSV
        return os.path.basename( os.path.dirname( os.path.dirname( os.path.dirname( csv_path ) ) ) ) or "unknown"
    # Branch mode: split on first `-wip-` or `-` and take leftmost
    if "-wip-" in stem:
        return stem.split( "-wip-" )[ 0 ]
    return stem.split( "-" )[ 0 ]


def _branch_from_filename( csv_path: str ) -> str:
    """
    Derive branch identity from filename when sidecar absent.

    Filename: `{repo}-{branch-slug}-loc-delta.csv`. Returns `{branch-slug}`.
    Returns empty string if no branch can be derived (date-mode CSV).
    """
    stem = os.path.basename( csv_path ).removesuffix( "-loc-delta.csv" )
    if stem[ :4 ].isdigit():
        return ""   # date-mode — no branch info
    if "-wip-" in stem:
        return "wip-" + stem.split( "-wip-", 1 )[ 1 ]
    return ""


def _build_aggregated_daily( df: pd.DataFrame ) -> dict:
    """
    Build the `daily` dict expected by plot_summary().

    Ensures:
        - Returns dict[date_str -> {added, deleted, files_touched, commits,
                                   by_repo: [...], by_file_type: [...]}]
        - by_repo / by_file_type lists are sorted by `added` descending
        - files_touched / commits at the date level use sum (rows already
          contain bucket-level uniques; we cannot deduplicate across CSVs
          without commit SHAs, so this approximates)
    """
    out = {}
    for date_str, group in df.groupby( "date" ):
        # Per-repo rollup
        by_repo_rows = []
        for repo_name, repo_group in group.groupby( "repo" ):
            by_repo_rows.append({
                "repo":          repo_name,
                "added":         int( repo_group[ "added"         ].sum() ),
                "deleted":       int( repo_group[ "deleted"       ].sum() ),
                "files_touched": int( repo_group[ "files_touched" ].sum() ),
                "commits":       int( repo_group[ "commits"       ].sum() ),
            })
        by_repo_rows.sort( key=lambda r: -r[ "added" ] )

        # Per-file-type rollup (across repos)
        by_type_rows = []
        for file_type, type_group in group.groupby( "file_type" ):
            by_type_rows.append({
                "file_type":     file_type,
                "added":         int( type_group[ "added"         ].sum() ),
                "deleted":       int( type_group[ "deleted"       ].sum() ),
                "files_touched": int( type_group[ "files_touched" ].sum() ),
                "commits":       int( type_group[ "commits"       ].sum() ),
            })
        by_type_rows.sort( key=lambda r: -r[ "added" ] )

        out[ date_str ] = {
            "added":         int( group[ "added"         ].sum() ),
            "deleted":       int( group[ "deleted"       ].sum() ),
            "files_touched": int( group[ "files_touched" ].sum() ),
            "commits":       int( group[ "commits"       ].sum() ),
            "by_repo":       by_repo_rows,
            "by_file_type":  by_type_rows,
        }
    return out


def _build_summary( df: pd.DataFrame ) -> dict:
    """
    Build the overall summary dict expected by plot_summary().

    Ensures:
        - Returns {total_added, total_deleted, total_files, total_commits,
                   total_days, net, repos}
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
        "total_commits": int( df[ "commits"       ].sum() ),
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
        return "No data in range across the requested repos."

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
        d = daily[ date_str ]
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
        - Returns a JSON string matching the shape in Maria's PIP R&D doc §4.1
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

    # ── Today-default fallback (Maria's §7.4 ratification 2026-05-21).
    # When neither --since nor --until is supplied, default both to today.
    # When exactly one is supplied, leave the other as an open bound (any
    # date passes that side of the filter). This matches the natural mental
    # model for `/plan-loc-delta-global` ad-hoc invocations: bare command =
    # "what did I do today across all repos?"
    if not args.since and not args.until:
        today      = _date.today().isoformat()
        args.since = today
        args.until = today
        if args.verbose: print( f"[main] Today-default applied: since={today} until={today}", file=sys.stderr )

    # ── Phase 1: discover per-repo CSVs from explicit --repos paths
    found_csvs: List[str] = []
    stale_repos: List[str] = []

    for repo_path in args.repos:
        abs_path = os.path.abspath( repo_path )
        csv_path = _find_csv_in_repo( abs_path, args.prefer_branch_csv, args.verbose )
        if csv_path is None:
            stale_repos.append( abs_path )
            print(
                f"Warning: no CSV found for {abs_path} (stale — no session-end ran here yet? "
                f"Run /plan-session-end in that repo to enable rollup coverage)",
                file = sys.stderr,
            )
        else:
            found_csvs.append( csv_path )

    if not found_csvs:
        print( "Error: no CSVs found across the requested repos. Run --output csv on per-repo branches first.", file=sys.stderr )
        return EXIT_ERROR

    # ── Load + identity-stamp each DataFrame
    dfs = []
    for csv_path in found_csvs:
        try:
            df = _load_csv_with_identity( csv_path, args.verbose )
            dfs.append( df )
            if args.verbose: print( f"[load] {os.path.basename(csv_path)}: {len(df)} rows", file=sys.stderr )
        except Exception as e:
            print( f"Failed to load {csv_path}: {e}", file=sys.stderr )
            if args.debug:
                import traceback
                traceback.print_exc()
            return EXIT_ERROR

    # ── Concat + date filter
    combined = pd.concat( dfs, ignore_index=True ) if dfs else pd.DataFrame()

    if args.since:
        combined = combined[ combined[ "date" ] >= args.since ]
    if args.until:
        combined = combined[ combined[ "date" ] <= args.until ]

    if args.verbose: print( f"[concat] {len(combined)} rows post-filter across {combined['repo'].nunique() if not combined.empty else 0} repos", file=sys.stderr )

    # ── Build aggregated structures
    daily   = _build_aggregated_daily( combined )
    summary = _build_summary( combined )

    if stale_repos:
        summary[ "stale_repos" ] = [ os.path.basename( p ) for p in stale_repos ]

    # ── Output emission
    cwd = os.getcwd()

    if args.output == "console":
        text = _format_console( daily, summary, args.since, args.until )
        if stale_repos:
            text += "\n\nStale repos (no CSV found):\n" + "\n".join( f"  - {os.path.basename(p)}" for p in stale_repos )
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
        parent = os.path.dirname( csv_path )
        if parent and not os.path.isdir( parent ):
            os.makedirs( parent, exist_ok=True )
        combined.to_csv( csv_path, index=False )
        print( f"Wrote {len(combined)} rows to {csv_path}" )

    # ── Optional plot (additive)
    if args.plot:
        if len( daily ) < 2:
            print( f"Warning: --plot skipped — only {len(daily)} day(s) of data, need ≥ 2 dates.", file=sys.stderr )
        else:
            plot_path = args.plot_output or _default_path( cwd, "png", args.since, args.until )
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

    Synthesizes 3 tempfile CSVs simulating 3 repos:
      - tempdir_a: schema v2 (with sidecar JSON), 2 days of activity
      - tempdir_b: schema v2 (with sidecar JSON), 1 day of activity
      - tempdir_c: schema v1 (NO sidecar — exercises filename-derived identity)
      - tempdir_d: EMPTY (no io/git-loc-delta/ — exercises stale-repo path)

    Exercises:
      1. _find_csv_in_repo discovery
      2. _load_csv_with_identity (both v2 and v1 paths)
      3. _build_aggregated_daily + _build_summary
      4. _format_console output
      5. _format_json output (JSON-parsable; expected shape)
      6. plot_summary(group_by="repo") emission
      7. Stale-repo handling

    Ensures:
        - Tests complete with ✓ or ✗ indicators
        - Uses cu.print_banner formatting
        - Does NOT raise (catches all exceptions)
        - Cleans up tempfiles on exit
    """
    import shutil
    import tempfile

    cu.print_banner( "Global Aggregator Smoke Test", prepend_nl=True )

    workdir = tempfile.mkdtemp( prefix="git_loc_delta_global_smoke_" )
    try:
        # ── Set up 4 fake repos in workdir
        repo_a = os.path.join( workdir, "alpha" )
        repo_b = os.path.join( workdir, "beta"  )
        repo_c = os.path.join( workdir, "gamma" )
        repo_d = os.path.join( workdir, "delta" )
        for r in ( repo_a, repo_b, repo_c ):
            os.makedirs( os.path.join( r, "io", "git-loc-delta" ), exist_ok=True )
        os.makedirs( repo_d, exist_ok=True )   # repo_d has NO io/git-loc-delta/ — stale

        # repo_a: schema v2 (2 days, branch CSV)
        a_csv = os.path.join( repo_a, "io", "git-loc-delta", "alpha-wip-test-loc-delta.csv" )
        with open( a_csv, "w" ) as f:
            f.write( "date,repo,branch,file_type,added,deleted,files_touched,commits\n" )
            f.write( "2026-05-20,alpha,wip-test,python,100,10,2,1\n" )
            f.write( "2026-05-20,alpha,wip-test,markdown,50,5,1,1\n" )
            f.write( "2026-05-21,alpha,wip-test,python,200,20,3,2\n" )
        with open( a_csv + ".meta.json", "w" ) as f:
            json.dump({
                "csv_schema_version": 2,
                "repo":               "alpha",
                "branch":             "wip-test",
                "rev_range":          "main..wip-test",
                "since":              None,
                "until":              None,
                "generated_at":       "2026-05-21T22:00:00Z",
            }, f )

        # repo_b: schema v2 (1 day, branch CSV)
        b_csv = os.path.join( repo_b, "io", "git-loc-delta", "beta-wip-test-loc-delta.csv" )
        with open( b_csv, "w" ) as f:
            f.write( "date,repo,branch,file_type,added,deleted,files_touched,commits\n" )
            f.write( "2026-05-21,beta,wip-test,typescript,300,30,4,3\n" )
        with open( b_csv + ".meta.json", "w" ) as f:
            json.dump({
                "csv_schema_version": 2,
                "repo":               "beta",
                "branch":             "wip-test",
                "rev_range":          "main..wip-test",
                "since":              None,
                "until":              None,
                "generated_at":       "2026-05-21T22:00:00Z",
            }, f )

        # repo_c: schema v1 (1 day, branch CSV) — no sidecar, no repo/branch columns
        c_csv = os.path.join( repo_c, "io", "git-loc-delta", "gamma-wip-legacy-loc-delta.csv" )
        with open( c_csv, "w" ) as f:
            f.write( "date,file_type,added,deleted,files_touched,commits\n" )   # v1 header
            f.write( "2026-05-21,javascript,75,7,1,1\n" )

        repos_active = [ repo_a, repo_b, repo_c ]
        repos_all    = repos_active + [ repo_d ]

        try:
            # Test 1: Discovery on the 3 active repos
            print( "Test 1: discovery on 3 active repos..." )
            csvs_found = [ _find_csv_in_repo( r, True, False ) for r in repos_active ]
            assert all( c is not None for c in csvs_found ), f"Expected 3 CSVs, got {csvs_found}"
            print( "✓ 3 CSVs discovered" )

            # Test 2: Stale-repo path returns None
            print( "Test 2: stale-repo discovery returns None..." )
            stale_result = _find_csv_in_repo( repo_d, True, False )
            assert stale_result is None
            print( "✓ stale repo returns None" )

            # Test 3: Load v2 CSV with sidecar
            print( "Test 3: load v2 CSV with sidecar..." )
            df_a = _load_csv_with_identity( a_csv, False )
            assert list( df_a.columns ) == [ "date", "repo", "branch", "file_type", "added", "deleted", "files_touched", "commits" ]
            assert ( df_a[ "repo" ] == "alpha" ).all()
            assert ( df_a[ "branch" ] == "wip-test" ).all()
            assert len( df_a ) == 3
            print( "✓ v2 CSV loaded with correct identity" )

            # Test 4: Load v1 CSV (no sidecar, no repo/branch columns)
            print( "Test 4: load v1 CSV with filename-derived identity..." )
            df_c = _load_csv_with_identity( c_csv, False )
            assert list( df_c.columns ) == [ "date", "repo", "branch", "file_type", "added", "deleted", "files_touched", "commits" ]
            assert ( df_c[ "repo" ] == "gamma" ).all(), f"Expected repo=gamma, got {df_c[ 'repo' ].unique()}"
            assert df_c[ "branch" ].iloc[ 0 ] == "wip-legacy", f"Expected branch=wip-legacy, got {df_c[ 'branch' ].iloc[ 0 ]!r}"
            print( "✓ v1 CSV identity injected from filename" )

            # Test 5: Aggregation
            print( "Test 5: build_aggregated_daily + build_summary..." )
            df_b = _load_csv_with_identity( b_csv, False )
            combined = pd.concat( [ df_a, df_b, df_c ], ignore_index=True )
            daily    = _build_aggregated_daily( combined )
            summary  = _build_summary( combined )
            assert set( daily.keys() ) == { "2026-05-20", "2026-05-21" }
            # 2026-05-21 should have all 3 repos contributing
            assert len( daily[ "2026-05-21" ][ "by_repo" ] ) == 3
            assert summary[ "total_added"   ] == 100 + 50 + 200 + 300 + 75   # 725
            assert summary[ "total_deleted" ] == 10 + 5 + 20 + 30 + 7        # 72
            assert summary[ "net"           ] == 725 - 72                    # 653
            assert summary[ "total_days"    ] == 2
            assert sorted( summary[ "repos" ] ) == [ "alpha", "beta", "gamma" ]
            print( f"✓ aggregation correct: net={summary['net']}, days={summary['total_days']}, repos={summary['repos']}" )

            # Test 6: Console output
            print( "Test 6: console output formatting..." )
            text = _format_console( daily, summary, since=None, until=None )
            assert "Cross-Repo Daily LoC Delta" in text
            assert "alpha" in text and "beta" in text and "gamma" in text
            assert "+653" in text or "net +653" in text   # net headline
            print( "✓ console output contains expected markers" )

            # Test 7: JSON output shape (validate against Maria's PIP doc §4.1)
            print( "Test 7: JSON output shape..." )
            js = _format_json( daily, summary, since=None, until=None )
            parsed = json.loads( js )
            assert "summary" in parsed and "days" in parsed and "repos" in parsed
            assert parsed[ "summary" ][ "net" ] == 653
            assert len( parsed[ "days" ] ) == 2
            day_21 = next( d for d in parsed[ "days" ] if d[ "date" ] == "2026-05-21" )
            assert "by_repo" in day_21 and "by_file_type" in day_21
            assert len( day_21[ "by_repo" ] ) == 3
            print( "✓ JSON output shape matches PIP doc §4.1" )

            # Test 8: Plot emission
            print( "Test 8: plot emission via plot_summary(group_by='repo')..." )
            plot_path = os.path.join( workdir, "test-plot.png" )
            plot_summary(
                daily       = daily,
                summary     = summary,
                output_path = plot_path,
                group_by    = "repo",
                title_meta  = {
                    "scope":      "global",
                    "repos":      summary[ "repos" ],
                    "rev_window": "2026-05-20..2026-05-21",
                },
            )
            assert os.path.isfile( plot_path )
            assert os.path.getsize( plot_path ) > 1000
            print( f"✓ plot rendered ({os.path.getsize(plot_path)} bytes)" )

            # Test 9: End-to-end via main(argv=...)
            print( "Test 9: end-to-end main() with --output json..." )
            json_out = os.path.join( workdir, "out.json" )
            exit_code = main( argv=[
                "--repos", repo_a, repo_b, repo_c,
                "--since", "2026-05-20",
                "--until", "2026-05-21",
                "--output", "json",
                "--save-output", json_out,
            ] )
            assert exit_code == 0
            assert os.path.isfile( json_out )
            with open( json_out, "r" ) as f:
                parsed = json.load( f )
            assert parsed[ "summary" ][ "net" ] == 653
            print( "✓ end-to-end main() ran clean and produced valid JSON" )

            # Test 10: End-to-end CSV output
            print( "Test 10: end-to-end main() with --output csv..." )
            csv_out = os.path.join( workdir, "out.csv" )
            exit_code = main( argv=[
                "--repos", repo_a, repo_b, repo_c,
                "--since", "2026-05-20",
                "--until", "2026-05-21",
                "--output", "csv",
                "--save-output", csv_out,
            ] )
            assert exit_code == 0
            assert os.path.isfile( csv_out )
            verify_df = pd.read_csv( csv_out )
            assert "repo" in verify_df.columns and "branch" in verify_df.columns
            assert len( verify_df ) == 5   # 3 (alpha day 20) + 1 (alpha day 21 python) + 1 (beta day 21) + 1 (gamma day 21) — wait
            # Actually: alpha=3 rows (2 on 05-20 + 1 on 05-21) + beta=1 + gamma=1 = 5 rows total
            assert sorted( verify_df[ "repo" ].unique().tolist() ) == [ "alpha", "beta", "gamma" ]
            print( f"✓ CSV output: {len(verify_df)} rows across {verify_df['repo'].nunique()} repos" )

            # Test 11: Today-default fallback (Maria's §7.4)
            print( "Test 11: today-default fallback when no --since/--until..." )
            # Mock argv with no date flags — args.since/until will default to today
            # We don't actually run this since today's data isn't in our fixtures, but we verify the logic
            from datetime import date as date_today
            today_str = date_today.today().isoformat()
            # Empty result expected when no fixture matches today
            tmp_out = os.path.join( workdir, "today.json" )
            exit_code = main( argv=[
                "--repos", repo_a, repo_b, repo_c,
                "--output", "json",
                "--save-output", tmp_out,
            ] )
            assert exit_code == 0
            with open( tmp_out, "r" ) as f:
                today_parsed = json.load( f )
            # since/until should be today
            assert today_parsed[ "since" ] == today_str and today_parsed[ "until" ] == today_str
            print( f"✓ today-default applied: since=until={today_str}" )

            # Test 12: Stale-repo summary handling
            print( "Test 12: stale-repo path through main()..." )
            stale_out = os.path.join( workdir, "stale.json" )
            exit_code = main( argv=[
                "--repos", repo_a, repo_b, repo_d,           # repo_d has no io/git-loc-delta/
                "--since", "2026-05-20",
                "--until", "2026-05-21",
                "--output", "json",
                "--save-output", stale_out,
            ] )
            assert exit_code == 0
            with open( stale_out, "r" ) as f:
                stale_parsed = json.load( f )
            # Only alpha + beta should appear in repos
            assert sorted( stale_parsed[ "repos" ] ) == [ "alpha", "beta" ]
            print( "✓ stale repo silently skipped in aggregation (logged to stderr)" )

            print( "\n✓ All 12 aggregator smoke tests passed successfully!" )

        except AssertionError as e:
            print( f"\n✗ Smoke test assertion failed: {e}" )
            import traceback
            traceback.print_exc()
        except Exception as e:
            print( f"\n✗ Smoke test failed with exception: {e}" )
            import traceback
            traceback.print_exc()

    finally:
        # Cleanup tempfiles
        shutil.rmtree( workdir, ignore_errors=True )


if __name__ == "__main__":
    # If invoked as `python -m cosa.repo.run_git_loc_delta_global --smoke-test`,
    # run the smoke test instead of the normal CLI. Otherwise run the CLI.
    if len( sys.argv ) > 1 and sys.argv[ 1 ] == "--smoke-test":
        quick_smoke_test()
    else:
        sys.exit( main() )
