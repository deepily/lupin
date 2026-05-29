"""
Report Formatter — console + JSON output for the Daily LoC Delta tool.

Console output uses two tables (daily totals + by date×file_type) with
`du.print_banner` for headers (matches COSA idiom).

JSON output is a single nested dict:
    {
        "since":      "2026-05-15",
        "until":      "2026-05-16",
        "repo_path":  ".",
        "rev_range":  "main..HEAD" or null,
        "branch":     "wip-foo" or null,
        "summary":    { total_added, total_deleted, total_files, total_commits, total_days, net },
        "days":       [ { date, added, deleted, files_touched, commits, by_file_type: [...] }, ... ],
    }

CSV output is delegated to `csv_writer.write_csv()`.
"""

import json
from typing import Dict, Optional

import cosa.utils.util as du


def format_console(
    daily:     Dict[str, Dict],
    summary:   Dict[str, int],
    since:     Optional[str] = None,
    until:     Optional[str] = None,
    branch:    Optional[str] = None,
    rev_range: Optional[str] = None,
) -> str:
    """
    Render a two-table console report and return it as a string.

    Requires:
        - daily is the dict returned by DailyAggregator.daily()
        - summary is the dict returned by DailyAggregator.summary()

    Ensures:
        - Returns a non-empty string suitable for stdout
        - Empty input produces a single "No commits in range" line plus the
          range banner (no traceback)
    """
    lines = []

    # Header banner (built manually so the function returns a string instead
    # of printing — easier to capture for save-output and smoke tests).
    title_parts = []
    if since and until:
        title_parts.append( f"{since} .. {until}" )
    elif since:
        title_parts.append( f"since {since}" )
    elif until:
        title_parts.append( f"until {until}" )
    title = "Daily LoC Delta"
    if title_parts: title += " — " + " ".join( title_parts )

    bar = "─" * 65
    lines.append( bar )
    lines.append( f"  {title}" )
    if branch:    lines.append( f"  Branch: {branch}" )
    if rev_range: lines.append( f"  Range: {rev_range}" )
    lines.append( bar )
    lines.append( "" )

    if not daily:
        lines.append( "No commits in range." )
        lines.append( "" )
        return "\n".join( lines )

    # Table 1: Daily totals
    lines.append( "Daily Totals" )
    lines.append( f"  {'Date':<12} {'Added':>8} {'Deleted':>9} {'Net':>8} {'Files':>7} {'Commits':>9}" )
    for date in sorted( daily.keys() ):
        d = daily[date]
        net = d["added"] - d["deleted"]
        sign = "+" if net >= 0 else ""
        lines.append(
            f"  {date:<12} {d['added']:>8} {d['deleted']:>9} {sign}{net:>7} {d['files_touched']:>7} {d['commits']:>9}"
        )
    lines.append(
        f"  {'TOTAL':<12} {summary['total_added']:>8} {summary['total_deleted']:>9} "
        f"{('+' if summary['net']>=0 else '')}{summary['net']:>7} {summary['total_files']:>7} {summary['total_commits']:>9}"
    )
    lines.append( "" )

    # Table 2: By Date × File Type
    lines.append( "By Date × File Type" )
    lines.append( f"  {'Date':<12} {'File Type':<14} {'Added':>8} {'Deleted':>9} {'Files':>7} {'Commits':>9}" )
    for date in sorted( daily.keys() ):
        for row in daily[date]["by_file_type"]:
            lines.append(
                f"  {date:<12} {row['file_type']:<14} {row['added']:>8} {row['deleted']:>9} "
                f"{row['files_touched']:>7} {row['commits']:>9}"
            )
    lines.append( "" )
    return "\n".join( lines )


def format_json(
    daily:     Dict[str, Dict],
    summary:   Dict[str, int],
    since:     Optional[str] = None,
    until:     Optional[str] = None,
    branch:    Optional[str] = None,
    rev_range: Optional[str] = None,
    repo_path: Optional[str] = None,
) -> str:
    """
    Render the analysis as JSON and return it as a string.

    Requires:
        - daily and summary are the dicts from DailyAggregator

    Ensures:
        - Returns valid JSON (indent=2) with stable key ordering
        - "days" is a list ordered by date ascending
    """
    days_list = []
    for date in sorted( daily.keys() ):
        d = daily[date]
        days_list.append({
            "date":          date,
            "added":         d["added"],
            "deleted":       d["deleted"],
            "files_touched": d["files_touched"],
            "commits":       d["commits"],
            "by_file_type":  d["by_file_type"],
        })

    payload = {
        "since":     since,
        "until":     until,
        "branch":    branch,
        "rev_range": rev_range,
        "repo_path": repo_path,
        "summary":   summary,
        "days":      days_list,
    }
    return json.dumps( payload, indent=2 )


def print_console_banner( title: str ) -> None:
    """
    Convenience wrapper around `du.print_banner` for callers that want the
    banner printed directly to stdout (e.g. the CLI in --debug mode).

    Ensures:
        - Delegates to cosa.utils.util.print_banner with prepend_nl=True
    """
    du.print_banner( title, prepend_nl=True )
