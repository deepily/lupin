"""
Scrub credential values out of files that already have them on disk (row dba8195c).

THE SURFACE. Claude Code transcripts under ~/.claude/projects/ and the hook logs under
io/claude_code_hooks/logs/ are written by the harness, not by pytest, so the report
hookwrapper that closed row b0e97156 cannot reach them. A shell probe that echoes a
credential variable lands the live value in both. Six files carried the current test
password on 2026-08-19; Rick ruled on 2026-08-21 that they are scrubbed IN PLACE —
not rotated, not deleted, because a transcript is a diagnostic record.

THE VOCABULARY IS NOT REDEFINED HERE. Both rules come from
`cosa.utils.secret_redaction` — the same helper the pytest hookwrapper uses. A second
regex would drift from the first, and the point of that module is that there is one.

TWO THINGS THIS MODULE ADDS, neither of which belongs in the redaction vocabulary:

  1. FIND THE FILES BY VALUE, at run time. A file list written two days ago names
     sessions that have since ended and misses every file written since. So the list is
     re-derived on every run by grepping the roots for the CURRENT values, with those
     values handed to grep on STDIN — never in argv, which is row 4996e41c's exact
     defect (argv is readable through `ps` and `/proc`).

  2. REWRITE IN PLACE, SAFELY. The rewrite goes to a temp file in the same directory,
     is fsync'd, and is then renamed over the original, so neither a crash mid-write
     nor a power loss can leave a truncated transcript. File mode is carried across, and a file modified in the last few
     minutes is SKIPPED and REPORTED rather than rewritten — a live session appends to
     its transcript, and a rename underneath it would drop whatever it wrote next.

⚠️ NOTHING HERE EVER PRINTS A VALUE. Counts, paths and key names only. A tool that
reports what it found by showing it would write the leak into the transcript of the run
that fixed the leak.
"""

import os
import subprocess
import tempfile
import time

from cosa.utils.secret_redaction import credential_env_values, redact_text


# A file touched more recently than this may belong to a session that is still
# appending to it. Rewriting one is how a fix for an unreadable file corrupts a
# readable one.
DEFAULT_ACTIVE_WINDOW_SECONDS = 300


def scan_for_values( roots, values ):
    """
    Every file under `roots` that contains one of `values` verbatim, plus what could
    not be read.

    ⚠️ THE APERTURE IS PART OF THE RESULT. grep exits 2 when it hits a single unreadable
    file, and an earlier version of this treated that as a failure and threw the
    matches away — one permission-denied file in a scratch directory killed a scan of
    8 GB. The matches it DID find are still findings, and the files it could not open
    are still a hole in the count. Both come back; the caller reports both.

    Requires:
        - roots is an iterable of directory or file paths (missing paths are skipped)
        - values is a non-empty iterable of non-empty strings

    Ensures:
        - returns {"paths": sorted matches, "unreadable": sorted paths grep could not
          open}, never None
        - the values are passed to grep on STDIN — never in argv, never to disk
        - a grep exit status of 1 (no matches) and 2 (some file unreadable) are both
          results, not failures

    Raises:
        - ValueError if values is empty or holds an empty string
        - subprocess.CalledProcessError only when grep did not run at all (status > 2)
    """
    values = list( values )
    if not values or any( not value for value in values ):
        raise ValueError( "values must be a non-empty iterable of non-empty strings" )

    existing = [ root for root in roots if os.path.exists( root ) ]
    if not existing:
        return { "paths": [], "unreadable": [] }

    # -r recurse, -l names only, -F fixed strings, -f - patterns from stdin, -a treat
    # binary as text (a transcript with one odd byte would otherwise be skipped whole).
    completed = subprocess.run(
        [ "grep", "-rlFa", "-f", "-" ] + existing,
        input="\n".join( values ),
        capture_output=True,
        text=True,
    )
    if completed.returncode > 2:
        raise subprocess.CalledProcessError(
            completed.returncode, "grep", output=completed.stdout, stderr=completed.stderr
        )
    unreadable = sorted(
        line.split( ": ", 1 )[ 1 ].rsplit( ": ", 1 )[ 0 ]
        for line in completed.stderr.splitlines() if ": " in line
    )
    return {
        "paths"      : sorted( line for line in completed.stdout.splitlines() if line ),
        "unreadable" : unreadable,
    }


def count_value_occurrences( path, values ):
    """
    How many times the values appear in one file, verbatim.

    Requires:
        - path names a readable file
        - values is an iterable of non-empty strings

    Ensures:
        - returns a non-negative int, the sum over every value
        - reads with surrogateescape so an undecodable byte cannot raise
        - never returns or logs the value itself

    Raises:
        - OSError if the file cannot be read
    """
    with open( path, "r", encoding="utf-8", errors="surrogateescape" ) as handle:
        text = handle.read()
    return sum( text.count( value ) for value in values )


def scrub_file( path, values ):
    """
    Rewrite one file with its credentials redacted, in place.

    Requires:
        - path names a readable, writable file
        - values is the by-value list from credential_env_values

    Ensures:
        - returns {"path", "before", "after", "changed"} — counts of verbatim value
          occurrences before and after; `changed` is True iff the text differs
        - the rewrite is atomic: a temp file in the same directory, fsync'd and then
          renamed over the original, so neither a process crash nor a power loss can
          leave a truncated file
        - the original file mode is preserved
        - the file is left untouched when redaction changes nothing
        - both rules of cosa.utils.secret_redaction apply — by value AND by
          credential-shaped key

    Raises:
        - OSError if the file cannot be read or replaced
    """
    with open( path, "r", encoding="utf-8", errors="surrogateescape" ) as handle:
        original = handle.read()

    # Line by line: a transcript is JSONL, so this bounds each regex pass to one record
    # instead of running the alternation across a hundred megabytes in a single string.
    scrubbed = "".join(
        redact_text( line, values ) for line in original.splitlines( keepends=True )
    )

    before = sum( original.count( value ) for value in values )
    after  = sum( scrubbed.count( value ) for value in values )

    if scrubbed == original:
        return { "path": path, "before": before, "after": after, "changed": False }

    mode      = os.stat( path ).st_mode & 0o7777
    directory = os.path.dirname( os.path.abspath( path ) )
    handle_fd, temp_path = tempfile.mkstemp( dir=directory, prefix=".scrub-" )
    try:
        with os.fdopen( handle_fd, "w", encoding="utf-8", errors="surrogateescape" ) as temp_handle:
            temp_handle.write( scrubbed )
            temp_handle.flush()
            # fsync BEFORE the rename, or the atomicity is only against a process
            # crash: the rename can reach disk while the temp file's contents are
            # still in the page cache, and a power loss then leaves the original
            # replaced by an empty file. Flagged by María on review.
            os.fsync( temp_handle.fileno() )
        os.chmod( temp_path, mode )
        os.replace( temp_path, path )
    except BaseException:
        if os.path.exists( temp_path ):
            os.unlink( temp_path )
        raise

    return { "path": path, "before": before, "after": after, "changed": True }


def is_recently_modified( path, window_seconds=DEFAULT_ACTIVE_WINDOW_SECONDS, now=None ):
    """
    Whether a file was written recently enough that a session may still hold it open.

    Requires:
        - path names an existing file
        - window_seconds is a non-negative number
        - now is a POSIX timestamp, or None to read the clock

    Ensures:
        - returns True iff mtime is within window_seconds of `now`

    Raises:
        - OSError if the file cannot be stat'd
    """
    if now is None:
        now = time.time()
    return ( now - os.stat( path ).st_mtime ) < window_seconds


def scrub_roots( roots, values=None, window_seconds=DEFAULT_ACTIVE_WINDOW_SECONDS,
                 exclude=(), dry_run=False ):
    """
    Find and scrub every file under `roots` that carries a live credential value.

    Requires:
        - roots is an iterable of paths
        - values is the by-value list, or None to read the environment now
        - exclude is an iterable of paths to leave alone regardless

    Ensures:
        - returns {"found", "unreadable", "scrubbed", "would_scrub",
          "skipped_active", "skipped_excluded", "total_before", "total_after"} holding
          PATHS and COUNTS only
        - a file modified inside window_seconds is skipped, not rewritten, and appears
          under skipped_active so the omission is visible
        - files grep could not open come back under "unreadable" — the hole in the
          count is reported, not swallowed
        - dry_run counts without writing anything and names each file it WOULD have
          rewritten — a dry run that reports a number and no paths cannot be checked
        - total_after is 0 once every found file has been scrubbed

    Raises:
        - ValueError if the environment holds no credential values to hunt for
    """
    if values is None:
        values = credential_env_values()
    if not values:
        raise ValueError(
            "no credential-named environment values to hunt for — the by-value arm is blind"
        )

    excluded = { os.path.abspath( path ) for path in exclude }
    scan     = scan_for_values( roots, values )
    found    = scan[ "paths" ]

    result = {
        "found"            : found,
        "unreadable"       : scan[ "unreadable" ],
        "scrubbed"         : [],
        "would_scrub"      : [],
        "skipped_active"   : [],
        "skipped_excluded" : [],
        "total_before"     : 0,
        "total_after"      : 0,
    }

    for path in found:
        if os.path.abspath( path ) in excluded:
            count = count_value_occurrences( path, values )
            result[ "skipped_excluded" ].append( path )
            result[ "total_before" ] += count
            result[ "total_after"  ] += count
            continue
        if is_recently_modified( path, window_seconds ):
            count = count_value_occurrences( path, values )
            result[ "skipped_active" ].append( path )
            result[ "total_before" ] += count
            result[ "total_after"  ] += count
            continue
        if dry_run:
            count = count_value_occurrences( path, values )
            result[ "would_scrub" ].append( path )
            result[ "total_before" ] += count
            result[ "total_after"  ] += count
            continue
        outcome = scrub_file( path, values )
        result[ "total_before" ] += outcome[ "before" ]
        result[ "total_after"  ] += outcome[ "after" ]
        result[ "scrubbed" ].append( path )

    return result


def format_report( result ):
    """
    Render a run's result as text safe to paste anywhere.

    Requires:
        - result is the dict returned by scrub_roots

    Ensures:
        - returns a string carrying counts and paths only — never a credential value
        - names every skipped file, because a silent omission reads as coverage

    Raises:
        - nothing
    """
    lines = [
        f"files carrying a live credential value : {len( result[ 'found' ] )}",
        f"occurrences before                     : {result[ 'total_before' ]}",
        f"occurrences after                      : {result[ 'total_after' ]}",
        f"scrubbed                               : {len( result[ 'scrubbed' ] )}",
        f"files grep could not read (blind spot) : {len( result[ 'unreadable' ] )}",
    ]
    for path in result[ "scrubbed" ]:
        lines.append( f"  scrubbed  {path}" )
    for path in result[ "would_scrub" ]:
        lines.append( f"  would scrub  {path}" )
    for path in result[ "skipped_active" ]:
        lines.append( f"  SKIPPED (recently written) {path}" )
    for path in result[ "skipped_excluded" ]:
        lines.append( f"  SKIPPED (excluded) {path}" )
    return "\n".join( lines )


def main( argv=None ):
    """
    Command-line entry point.

    Requires:
        - argv is a list of arguments, or None for sys.argv[1:]

    Ensures:
        - prints the report and returns 0 when no occurrence survives the run
        - returns 1 when occurrences survive (skipped or excluded files)

    Raises:
        - nothing beyond what scrub_roots raises
    """
    import argparse

    parser = argparse.ArgumentParser( description="Scrub credential values out of files on disk." )
    parser.add_argument( "roots", nargs="+", help="directories or files to scan" )
    parser.add_argument( "--dry-run", action="store_true", help="find and count only" )
    parser.add_argument( "--window-seconds", type=int, default=DEFAULT_ACTIVE_WINDOW_SECONDS,
                         help="skip files written more recently than this" )
    parser.add_argument( "--exclude", action="append", default=[],
                         help="a path to leave alone (repeatable)" )
    args = parser.parse_args( argv )

    result = scrub_roots(
        args.roots, window_seconds=args.window_seconds, exclude=args.exclude,
        dry_run=args.dry_run,
    )
    print( format_report( result ) )
    return 0 if result[ "total_after" ] == 0 else 1


if __name__ == "__main__":
    import sys

    sys.exit( main() )
