"""
The writer of the daily duplicate check's verdict lines.

The triage seat rules on each finding of a night's run with one fixed line, whose shape is the comment above the pattern below.
The verdict word is one of duplicate, extend or distinct, written in capitals.
The fields are space-separated key=value pairs in that order, with no spaces inside a value.
This verb checks the line and amends it onto the night's triage row. Then it appends it to verdicts.jsonl beside the result files.
The weekly page reads that file (reuse_behaviour.read_verdicts), so the file and the row carry the same lines.
It refuses a malformed line and a run with no result file.
It also refuses a finding id that is not in that run's file, and a finding already ruled on.
Nothing is written when a check fails or when the row cannot be amended.

Exit 0 means the line was written. Exit 3 means it was refused and nothing was written.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys

import cosa.utils.util as cu
from lupin_mcp import duplicate_check_filing as ff
from lupin_mcp import duplicate_check_status as dcs
from lupin_mcp import reuse_behaviour as rb

PREFIX       = "DUPCHECK-VERDICT"
FIELDS       = ( "run", "finding", "verdict", "class", "by", "ts" )
EXIT_REFUSED = 3
# DUPCHECK-VERDICT run=<result file stem> finding=<findings[].id> verdict=<verdict word> class=<kebab-case reason> by=<persona key> ts=<ISO-8601 UTC>
LINE         = re.compile(
    rf"^{PREFIX} run=(?P<run>\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}}-[a-z]+) finding=(?P<finding>[A-Za-z0-9_-]+) verdict=(?P<verdict>{'|'.join( rb.REAL_VERDICTS + rb.NOT_VERDICTS )})"
    r" class=(?P<class_>[a-z0-9]+(?:-[a-z0-9]+)*) by=(?P<by>[^\s=]+) ts=(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00))$" )


class VerdictRefused( ValueError ):
    """A verdict line that was not written, with the reason in the message."""


def seat_actor():
    """
    Name the seat running this command, the way the task_amend tool names its caller.

    Ensures:
        - returns "<persona key> <8-hex session id>" read from the session bridge
    Raises:
        - VerdictRefused when the session id was reached by a fallback (cwd_fallback or generated_fallback), because a guessed id could name another seat
        - VerdictRefused when the bridge holds no voice persona for this session, so the store is never sent a made-up actor
    """
    from lupin_cli.claude_code.hooks.lib import session_bridge as sb
    sid, source = sb.get_claude_session_id_with_source()
    if source in ( sb.SOURCE_CWD_FALLBACK, sb.SOURCE_GENERATED ): raise VerdictRefused( f"the session id {sid[ :8 ]} came from a fallback ({source}), so it may name another seat and the amend has no trustworthy actor" )
    persona = sb.get_voice_persona( sid )
    if not persona or not persona.get( "name" ): raise VerdictRefused( f"session {sid[ :8 ]} has no voice persona in its bridge, so the amend has no actor to carry" )
    return f"{persona[ 'name' ].lower()} {sid[ :8 ]}"


class SeatStore( ff.LiveStore ):
    """The filer's HTTP store, with every amend carrying the calling seat as its actor."""

    def __init__( self, actor, settings=None, api_key=None ):
        super().__init__( settings, api_key )
        self.amend_extra = { **self.amend_extra, "actor": actor }


def parse_line( line ):
    """
    Check one verdict line against the agreed format.

    Requires:
        - line is a string
    Ensures:
        - returns { run, finding, verdict, class, by, ts } as text, ts exactly as written
    Raises:
        - VerdictRefused when the line is not the agreed shape, in the agreed field order, with one value per field, or when ts is not a real UTC time
    """
    m = LINE.match( line )
    if m is None: raise VerdictRefused( f"the line does not match the {PREFIX} shape: {PREFIX} " + " ".join( f"{f}=<{f}>" for f in FIELDS ) + f"; got {line!r}" )
    rec = { k.rstrip( "_" ): v for k, v in m.groupdict().items() }
    try:
        datetime.datetime.fromisoformat( rec[ "ts" ] )
        datetime.date.fromisoformat( rec[ "run" ][ :10 ] )
    except ValueError as e:
        raise VerdictRefused( f"the line has a date or time that does not exist: {e}" ) from e
    return rec


def finding_ids( folder, run ):
    """
    Read the finding ids of one run.

    Ensures:
        - returns the ids in <folder>/<run>.json's findings
    Raises:
        - VerdictRefused when that file is missing or cannot be read as a result file
    """
    path = pathlib.Path( folder ) / f"{run}.json"
    got  = rb.read_check_run( path ) if path.is_file() else None
    if got is None: raise VerdictRefused( f"run {run} has no readable result file at {path}" )
    return [ fid for _verdict, _key, fid in got[ "findings" ] ]


def put_back( path, existed, before ):
    """
    Put verdicts.jsonl back to what it was before this call appended to it.

    Requires:
        - existed says whether the file was there before; before is its size in bytes then
    Ensures:
        - cuts the file back to before bytes, or removes it when it did not exist
        - returns None when that worked, or the OSError's text when it did not; never raises it
    """
    try:
        if existed:
            with path.open( "r+b" ) as f: f.truncate( before )
        else: path.unlink()
    except OSError as e:
        return f"{type( e ).__name__}: {e}"
    return None


def write_verdict( line, folder, row_id, amender ):
    """
    Check a verdict line, append it to verdicts.jsonl, then amend it onto the triage row.

    Requires:
        - folder is the check's result folder; row_id is the triage row's uuid, or None for a file-only back-fill
        - amender has amend( row_id, note ) returning ( ok, status, body ), and is read only when row_id is given
    Ensures:
        - returns the record written: { run, finding, verdict, class, by, ts }
        - the file is written first and the row amended second; if the amend fails, the file is put back to what it was
        - so a failed append leaves the row unamended, and a failed amend leaves the file as it was
        - the file's line is the record as JSON, one per line, the folder made if absent
        - any exception from the amend, not only a refusal, puts the file back before it is raised on
    Raises:
        - VerdictRefused for a malformed line, a missing run file, a finding id not in that run, a finding that already has a line, an amend the store did not accept, or a file that cannot be written
        - the message says what was and was not written
    """
    rec = parse_line( line )
    if rec[ "finding" ] not in finding_ids( folder, rec[ "run" ] ): raise VerdictRefused( f"finding {rec[ 'finding' ]} is not in run {rec[ 'run' ]}" )
    if ( rec[ "run" ], rec[ "finding" ] ) in rb.read_verdicts( folder ): raise VerdictRefused( f"finding {rec[ 'finding' ]} of run {rec[ 'run' ]} already has a verdict line" )
    folder  = pathlib.Path( folder )
    path    = folder / rb.VERDICTS_FILE
    existed = path.exists()
    before  = path.stat().st_size if existed else 0
    try:
        folder.mkdir( parents=True, exist_ok=True )
        with path.open( "a", encoding="utf-8" ) as f: f.write( json.dumps( rec ) + "\n" )
    except OSError as e:
        raise VerdictRefused( f"could not append to {path} ({type( e ).__name__}: {e}); the row was not amended and the file holds what it held before" ) from e
    if row_id is not None:
        try: ok, status, body = amender.amend( row_id, line )
        except BaseException:
            put_back( path, existed, before )
            raise
        if not ok:
            failed = f"the store refused the amend onto row {row_id} (HTTP {status}): {body}"
            stuck  = put_back( path, existed, before )
            raise VerdictRefused( f"{failed}; the file was put back as it was" if stuck is None else f"{failed}; the line is still in {path} and could not be taken out ({stuck})" )
    return rec


def main( argv=None, out=None, amender=None ):
    """
    Write one verdict line from the command line.

    Ensures:
        - takes the line as its one argument; --row names the triage row to amend, or --file-only writes the file alone, one of the two being needed
        - --data-dir holds the check's folder, as reuse_behaviour's flag does
        - the live row amend carries the seat's actor, as task_amend does; the store refuses one with none
        - returns 0 with the written line printed; 3 with the reason printed and nothing written
    """
    ap = argparse.ArgumentParser( description="Write one daily duplicate check verdict line." )
    ap.add_argument( "line" )
    ap.add_argument( "--row", default=None, help="the triage row's uuid, amended with the line" )
    ap.add_argument( "--file-only", action="store_true", help="write verdicts.jsonl without amending a row, for a back-fill" )
    ap.add_argument( "--data-dir", default=None )
    a   = ap.parse_args( argv )
    if ( a.row is None ) == ( not a.file_only ): ap.error( "give --row <uuid> or --file-only, not both and not neither" )
    out = out if out is not None else sys.stdout
    folder = pathlib.Path( a.data_dir ) / rb.CHECK_FOLDER if a.data_dir else dcs.folder_of( cu.get_project_root() )
    try:
        rec = write_verdict( a.line, folder, a.row, amender if amender is not None or a.row is None else SeatStore( seat_actor() ) )
    except ValueError as e:
        print( f"REFUSING: {e}. Nothing was written.", file=out )
        return EXIT_REFUSED
    print( f"WROTE: {json.dumps( rec )}", file=out )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
