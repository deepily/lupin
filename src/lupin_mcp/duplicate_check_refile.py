"""
File again the findings a saved result file of the daily check holds.

A filing error leaves the day's findings in the result file and no rows in the store.
The error may be a store that is down, a missing key file or a broken client.
This command reads the file and files the findings.
The run's one triage row lists the findings; its store key is made of the findings' keys, with no date.
So a finding already on a triage row is not listed again, and a finding already in the spool is not spooled twice.
It asks the store before the create, as the daily check does.
Each run adds a record of its answer to the result file under "refilings".

Exit 0 means every finding is filed or was already. Exit 1 means some are still queued or were refused.
Exit 3 means it could not finish. The file cannot be read, it holds no findings, or the filing raised.
It also means the rows were filed and the record could not be written; the answer is printed first.
"""
import argparse
import datetime
import json
import pathlib
import sys

from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import duplicate_check_filing as filing

REFILINGS  = "refilings"
NEEDED     = ( "id", "name", "file", "line", "others", "window", "correlation_key" )     # what triage_payload reads of a finding that has no text
EXIT_LEFT  = 1
EXIT_NONE  = 3


class RefileError( Exception ):
    """A result file that cannot be refiled, with the reason."""


class FilingFailed( RefileError ):
    """The filer raised; the file is unchanged."""


class RecordNotWritten( RefileError ):
    """The rows were filed, the record was not written; the answer is kept here."""

    def __init__( self, message, answer ):
        super().__init__( message )
        self.answer = answer


def read_result( path ):
    """
    Read a result file and check that it can be refiled.

    Requires:
        - path names a result file written by the daily check
    Ensures:
        - returns the parsed document
    Raises:
        - OSError when the file cannot be read, ValueError when it is not JSON
        - RefileError when it is not a result document, holds no findings list (a file written before findings were kept on every run), or a finding lacks a field the row needs
    """
    doc = json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )
    if not isinstance( doc, dict ) or not isinstance( doc.get( "findings" ), list ):
        raise RefileError( f"{path} holds no findings list: it was written before the findings were kept on every run" )
    for i, found in enumerate( doc[ "findings" ] ):
        missing = [ k for k in NEEDED if not isinstance( found, dict ) or k not in found ]
        if missing: raise RefileError( f"finding {i} of {path} lacks {', '.join( missing )}" )
    return doc


def refile( path, filer=None, now=None ):
    """
    File the findings of a result file and record the answer in it.

    Requires:
        - filer takes ( findings, folder ) like the daily check's filer; None means daily.live_filer
        - now is a timezone-aware time, or None for the present
    Ensures:
        - the filer is given the file's findings and the folder the file lives in, which is where the spool is
        - each finding carries day, the date of the run that made the file, so the row's title names that day and not the day of the refile
        - each finding carries run_file, the file's name, so a row that lists only part of them says where the rest are
        - the file gains one entry in "refilings", { at, answer }, written only after the filer has returned
        - returns the filer's answer
    Raises:
        - what read_result raises
        - FilingFailed when the filer raises, naming what it raised; the file is left as it was
        - RecordNotWritten when the filing returned and the file could not be rewritten; it carries the answer
    """
    doc = read_result( path )
    dated = [ { **f, "day": f[ "day" ] if "day" in f else doc[ "date" ], "run_file": f[ "run_file" ] if "run_file" in f else pathlib.Path( path ).name } for f in doc[ "findings" ] ]
    try: answer = ( filer if filer is not None else daily.live_filer )( dated, pathlib.Path( path ).parent )
    except Exception as e:                  # a store client or config that raises: the daily check records the same and goes on
        raise FilingFailed( f"the filing raised {type( e ).__name__}: {e}. The file is unchanged." ) from e
    doc.setdefault( REFILINGS, [] ).append( { "at": ( now if now is not None else datetime.datetime.now().astimezone() ).isoformat(), "answer": answer } )
    try: daily.write_json( path, doc )
    except OSError as e: raise RecordNotWritten( f"the rows were filed, and the record could not be written: {type( e ).__name__}: {e}", answer ) from e
    return answer


def main( argv=None, out=None, filer=None, now=None ):
    """
    Command line: a result file path.

    Ensures:
        - prints the filing's answer as JSON
        - returns 0 when nothing is left queued or refused, 1 when something is, 3 with the reason printed when nothing could be done
    """
    ap = argparse.ArgumentParser( description="File again the findings of a saved daily-check result file." )
    ap.add_argument( "result", help="a result file under <data dir>/duplicate-check-daily/" )
    args = ap.parse_args( argv )
    out  = out if out is not None else sys.stdout
    try: answer = refile( args.result, filer, now )
    except RecordNotWritten as e:
        print( json.dumps( e.answer, indent=2, sort_keys=True ), file=out )
        print( f"WARNING: {e}.", file=out )
        return EXIT_NONE
    except FilingFailed as e:
        print( f"REFUSING: {e}", file=out )
        return EXIT_NONE
    except ( OSError, ValueError, RefileError ) as e:
        print( f"REFUSING: {type( e ).__name__}: {e}. Nothing was filed.", file=out )
        return EXIT_NONE
    print( json.dumps( answer, indent=2, sort_keys=True ), file=out )
    return EXIT_LEFT if answer[ filing.QUEUED ] or answer[ filing.REFUSED ] else 0


if __name__ == "__main__":  # pragma: no cover - the entry only calls main
    sys.exit( main() )
