"""
Manual driver: write the missing purpose lines, then rebuild the stored vector set.

Run it on the host against the dev server. It is not a test and it is not scheduled.
    PYTHONPATH=src python3 -m cosa.repo.symindex.candidate_build --root <repo root>
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import time

from cosa.repo.doc_lint import harness_schedule
from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates import purpose_lines as pl
from cosa.repo.symindex.candidates import storage_paths as sp
from cosa.repo.symindex.candidates import vector_build as vb
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.paths import data_dir

WRITER_VERSION = "bounded-cc-1"
JOB_TIMEOUT    = 1800
POLL_SECONDS   = 10


class BoundedJobWriter:
    """
    Write purpose lines through a bounded Claude Code job.

    The job receives a request file of ids and reads the tree itself. It writes its answer to a
    response file, which this writer reads. The job is covered by the Max plan.
    """

    def __init__( self, work_dir, submit, timeout=JOB_TIMEOUT, poll=POLL_SECONDS, sleep=time.sleep, clock=time.monotonic ):
        """
        Hold the hand-off folder and the transport.

        Requires:
            - work_dir is the purpose-lines folder, which the job can write
            - submit is a callable taking the /api/v2/submit payload
        """
        self.work_dir = pathlib.Path( work_dir )
        self.submit   = submit
        self.timeout  = timeout
        self.poll     = poll
        self.sleep    = sleep
        self.clock    = clock

    def __call__( self, ids ):
        """
        Ask the job for the purpose of each id.

        Requires:
            - ids is a non-empty list of entry ids

        Ensures:
            - the job is sent the ids and two file names, never source text
            - returns { id: purpose } for the ids the job answered

        Raises:
            - TimeoutError when no response file appears in time
            - ValueError when the response is not a list of { id, purpose } objects
        """
        key      = hashlib.sha256( "\n".join( ids ).encode( "utf-8" ) ).hexdigest()[ :12 ]
        request  = self.work_dir / f"request-{key}.json"
        response = self.work_dir / f"response-{key}.json"
        self.work_dir.mkdir( parents=True, exist_ok=True )
        if response.exists(): response.unlink()
        request.write_text( json.dumps( { "ids": ids } ), encoding="utf-8" )
        prompt = f"{pl.PROMPT_TEXT} The ids are in {request}. Write the JSON list to {response}, then reply with the word done."
        self.submit( { "command": harness_schedule.COMMAND, "args": { "prompt": prompt, "task_type": "BOUNDED" } } )
        deadline = self.clock() + self.timeout
        while not response.is_file():
            if self.clock() > deadline: raise TimeoutError( f"no response file {response} within {self.timeout} s" )
            self.sleep( self.poll )
        answers = json.loads( response.read_text( encoding="utf-8" ) )
        if not isinstance( answers, list ) or not all( isinstance( a, dict ) and "id" in a and "purpose" in a for a in answers ):
            raise ValueError( f"{response} is not a list of {{id, purpose}} objects" )
        return { a[ "id" ]: a[ "purpose" ] for a in answers }


def run( root, writer, client, screen=None, config=None, environ=None ):
    """
    Write the missing purpose lines and rebuild the vector set.

    Requires:
        - root is a lupin repository root
        - writer takes a list of ids and returns { id: purpose }
        - client has embed( texts, content_type, role ) and info()

    Ensures:
        - the index is ensured, and its public entries are the rows of the set
        - the live vector set is replaced by rename only after the new one is sealed
        - query-cache files made under another set are cleared
        - returns { purposes, manifest_hash, rows, stale_queries_cleared, seconds }
    """
    started   = time.monotonic()
    root      = pathlib.Path( root )
    data      = data_dir( root )
    purpose   = sp.candidate_dir( "purpose", data, config, environ )
    live      = sp.candidate_dir( "vectors", data, config, environ )
    cache     = sp.candidate_dir( "query_cache", data, config, environ )
    entries   = sx_build.read_symbols( sx_build.ensure( root ) )
    report    = pl.write_purpose_lines( entries, writer, purpose / "purpose.jsonl", WRITER_VERSION,
                                        screen if screen is not None else pl.default_screen() )
    new_dir   = live.with_name( live.name + ".new" )
    if new_dir.exists(): shutil.rmtree( new_dir )
    manifest  = vb.build_vectors( entries, pl.load_lines( purpose / "purpose.jsonl" ), client, new_dir )
    vs.swap_in( new_dir, live )
    cleared   = vs.clear_stale_queries( cache, manifest[ "manifest_hash" ] )
    return { "purposes": report, "manifest_hash": manifest[ "manifest_hash" ], "rows": manifest[ "rows" ],
             "stale_queries_cleared": cleared, "seconds": round( time.monotonic() - started, 1 ) }


def main( argv=None, environ=None, writer_factory=None, client=None ):
    """
    Command line entry: build the purpose lines and the vector set for one repository.

    Requires:
        - the INI keys of the candidate storage are set
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD are set, for the job submit

    Ensures:
        - prints the run report as JSON and returns 0
        - returns 2 and prints the code when a CandidateError stops the run
    """
    from cosa.repo.symindex.candidates.errors import CandidateError
    environ = os.environ if environ is None else environ
    parser  = argparse.ArgumentParser( description="Write purpose lines and rebuild the candidate vector set." )
    parser.add_argument( "--root", required=True )
    parser.add_argument( "--base-url", default=environ.get( "LUPIN_APP_SERVER_URL", "http://localhost:7999" ) )
    args    = parser.parse_args( argv )
    try:
        if writer_factory is None:
            email, password = environ[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" ], environ[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ]
            submit  = lambda payload: harness_schedule.submit( payload, args.base_url, email, password )
            work    = sp.candidate_dir( "purpose", data_dir( args.root ), environ=environ )
            writer  = BoundedJobWriter( work, submit )
        else:
            writer = writer_factory( args )
        report = run( args.root, writer, client if client is not None else vb.EndpointClient(), environ=environ )
    except CandidateError as e:
        print( json.dumps( { "error": e.code, "detail": e.detail } ) )
        return 2
    print( json.dumps( report, indent=2 ) )
    return 0


if __name__ == "__main__":    # pragma: no cover -- process entry, main() is tested
    sys.exit( main() )
