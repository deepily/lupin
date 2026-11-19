"""
Write the per-arm summary of the live database as a Markdown report file.

This is the command that runs cosa.research.preference_replay.arm_summary against a database and saves the table.
It reads the database only. The file sits beside the replay harness's own reports.
Its header names the code sha, the start of the window, the time and the exact command line.
Two lines under the table give the totals of orphaned forecasts and of answered cards with no forecast row.
Both should read zero on a healthy database, so the live check is one run and a look at those two lines.
"""

import argparse
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import cosa.utils.util as cu
from cosa.repo.doc_lint.pool_builder import resolve_commit
from cosa.research.preference_replay.arm_summary import per_arm_summary, render_summary
from cosa.rest.db.database import get_db
from cosa.utils.iso_timestamp import parse_iso


def render_report( summaries: List[ Dict[ str, Any ] ], provenance: Dict[ str, str ] ) -> str:
    """
    Lay out the report: a title, the provenance lines, the summary table and the two totals.

    Requires:
        - summaries is what per_arm_summary returns
        - provenance maps a label to its text

    Ensures:
        - returns Markdown ending in a newline
        - the table is render_summary's, unchanged
        - the totals are the sums of orphaned and of no_row over every arm, with an empty database reading zero
    """
    lines  = [ "# Per-arm summary", "" ]
    lines += [ f"- {label}: {value}" for label, value in provenance.items() ]
    lines += [ "", render_summary( summaries ), "" ]
    lines += [ f"- orphaned forecasts, all arms: {sum( s[ 'orphaned' ] for s in summaries )}",
               f"- answered cards with no forecast row, all arms: {sum( s[ 'no_row' ] for s in summaries )}" ]
    return "\n".join( lines ) + "\n"


def main( argv: Optional[ Sequence[ str ] ] = None, session_factory: Optional[ Callable ] = None, code_sha: Optional[ str ] = None,
          clock: Optional[ Callable ] = None ) -> int:
    """
    Summarize every arm from the database and write the report file.

    Requires:
        - argv holds --out, the report path, and optionally --since, an ISO-8601 time; a stamp with no zone reads as UTC
        - session_factory, code_sha and clock are injected by tests and default to the real ones

    Ensures:
        - reads the database only, then writes the report to --out
        - the header names the code sha, the window start ("none" when --since is absent), the time and the exact command
        - returns 0

    Raises:
        - ValueError when --since is not a readable time
    """
    parser = argparse.ArgumentParser( description="Write the per-arm summary of the live database." )
    parser.add_argument( "--out", required=True )
    parser.add_argument( "--since", help="only cards predicted at or after this ISO-8601 time are summarized" )
    args  = parser.parse_args( argv )
    since = None
    if args.since is not None:
        since = parse_iso( args.since )
        if since is None: raise ValueError( f"--since is not an ISO-8601 time: {args.since!r}" )
    command = "python -m cosa.research.preference_replay.arm_summary_report " + " ".join( list( argv ) if argv is not None else sys.argv[ 1: ] )
    with ( session_factory or get_db )() as session:
        summaries = per_arm_summary( session, since )
    provenance = { "code sha of this report": code_sha if code_sha is not None else resolve_commit( cu.get_project_root(), "HEAD" ),
                   "window starts": "none" if since is None else since.isoformat(),
                   "generated": ( clock or ( lambda: datetime.now( timezone.utc ) ) )().isoformat(), "command": f"`{command}`" }
    with open( args.out, "w", encoding="utf-8" ) as handle: handle.write( render_report( summaries, provenance ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
