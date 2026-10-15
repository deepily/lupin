"""
Manual driver: write the missing purpose lines, then rebuild the stored vector set.

Run it on the host against the dev server. It is not a test. The daily scheduled run is
cosa.repo.symindex.vector_refresh, which calls run() below.
    PYTHONPATH=src python3 -m cosa.repo.symindex.candidate_build --root <repo root>
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

from cosa.repo.doc_lint import harness_schedule
from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates import freshness as fr
from cosa.repo.symindex.candidates import purpose_lines as pl
from cosa.repo.symindex.candidates import storage_paths as sp
from cosa.repo.symindex.candidates import vector_build as vb
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError, DEPENDENCY_MISSING
from cosa.repo.symindex.paths import data_dir, default_out_dir

WRITER_VERSION = "bounded-cc-1"
JOB_TIMEOUT    = 1800
POLL_SECONDS   = 10


class BoundedJobWriter:
    """
    Write purpose lines through a bounded Claude Code job.

    The job receives a request file of ids and reads the tree itself. It writes its answer to a
    response file, which this writer reads. The job is covered by the Max plan.
    """

    def __init__( self, work_dir, submit, to_container=None, index_path=None, timeout=JOB_TIMEOUT, poll=POLL_SECONDS, sleep=time.sleep, clock=time.monotonic ):
        """
        Hold the hand-off folder and the transport.

        Requires:
            - work_dir is a folder the job can read and write, under the checkout the container mounts
            - submit is a callable taking the /api/v2/submit payload
            - to_container turns a host path into the path the job sees, or is None for the same path
            - index_path is the container path of the index's symbols file, or None to name none
        """
        self.work_dir     = pathlib.Path( work_dir )
        self.submit       = submit
        self.to_container = to_container if to_container is not None else str
        self.index_path   = index_path
        self.timeout      = timeout
        self.poll         = poll
        self.sleep        = sleep
        self.clock        = clock

    def __call__( self, ids ):
        """
        Ask the job for the purpose of each id.

        Requires:
            - ids is a non-empty list of entry ids

        Ensures:
            - the job is sent the ids and file names as the container sees them, never source text
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
        where  = f" Each id is the id field of one line of {self.index_path}, which names its file and line." if self.index_path else ""
        prompt = ( f"{pl.PROMPT_TEXT} The ids are in {self.to_container( request )}.{where} "
                   f"Write the JSON list to {self.to_container( response )}, then reply with the word done." )
        self.submit( { "command": harness_schedule.COMMAND, "args": { "prompt": prompt, "task_type": "BOUNDED" } } )
        deadline = self.clock() + self.timeout
        while not response.is_file():
            if self.clock() > deadline: raise TimeoutError( f"no response file {response} within {self.timeout} s" )
            self.sleep( self.poll )
        answers = json.loads( response.read_text( encoding="utf-8" ) )
        if not isinstance( answers, list ) or not all( isinstance( a, dict ) and "id" in a and "purpose" in a for a in answers ):
            raise ValueError( f"{response} is not a list of {{id, purpose}} objects" )
        return { a[ "id" ]: a[ "purpose" ] for a in answers }


def tree_path_refusal( index, out_dir, main_tree ):
    """
    Name why a tree-local build may not write to out_dir, or return None when it may.

    Requires:
        - index is the host path of a symbols.jsonl file, read and never written
        - out_dir is the host folder the build would write to
        - main_tree is the main checkout of the repository

    Ensures:
        - returns a sentence naming --out-dir when it is, holds, or sits inside the index's folder
        - returns a sentence naming --out-dir when it is outside main_tree, which the container mounts
        - returns a sentence naming --out-dir when it is inside main_tree and git does not ignore it
        - returns None otherwise; when git cannot answer the path is refused
    """
    out, gen, main = pathlib.Path( out_dir ).resolve(), pathlib.Path( index ).resolve().parent, pathlib.Path( main_tree ).resolve()
    if out == gen or gen in out.parents or out in gen.parents:
        return f"--out-dir {out_dir} overlaps the index folder {gen}; the index is read only"
    if out != main and main not in out.parents:
        return f"--out-dir {out_dir} is outside the main checkout {main}, which is what the job container mounts"
    rc = subprocess.run( [ "git", "-C", str( main ), "check-ignore", "-q", str( out ) ], capture_output=True ).returncode
    if rc != 0: return f"--out-dir {out_dir} is inside the tracked tree of the main checkout {main}; choose a gitignored folder under it"
    return None


def run( root, writer, client, screen=None, config=None, environ=None, batch_size=pl.BATCH_SIZE, built_at=None, index=None, out_dir=None ):
    """
    Write the missing purpose lines and rebuild the vector set.

    Requires:
        - root is a lupin repository root
        - writer takes a list of ids and returns { id: purpose }
        - client has embed( texts, content_type, role ) and info()

    Ensures:
        - the index is ensured, and its public entries that pass screen.sendable are the rows of the set,
          which is the list the lookup uploads as the stage, so the stage refuses no vector id as unknown
        - purpose lines are written from every public entry, and the screen's drops are reported there
        - the whole run holds the build lock, so a manual build and the scheduled one cannot overlap
        - the new set carries its build info: the index manifest it was built from, built_at
          (the current UTC time when built_at is None), and the pins the writer left without a line
        - a live set that loads and carries the row-texts sidecar lends its vectors for every row whose text is
          unchanged and whose engines and roles still match; a set that does not load is rebuilt in full
        - vectors reports, per matrix, how many rows were reused and how many embedded
        - the live vector set is replaced by rename only after the new one is sealed
        - query-cache files made under another set are cleared
        - returns { purposes, manifest_hash, rows, stale_queries_cleared, seconds, index_manifest, built_at, unwritten_pins, vectors }

        - index, when given, is the symbols.jsonl read instead of the ensured index; nothing is built or written there
        - out_dir, when given, holds the purpose, vector, query-cache and lock files, and the storage environment overrides are ignored

    Raises:
        - CandidateError BUILD_LOCK_HELD when another build holds the lock; nothing is written
    """
    started   = time.monotonic()
    root      = pathlib.Path( root )
    data      = data_dir( root ) if out_dir is None else pathlib.Path( out_dir )
    dir_env   = environ if out_dir is None else {}
    purpose   = sp.candidate_dir( "purpose", data, config, dir_env )
    live      = sp.candidate_dir( "vectors", data, config, dir_env )
    cache     = sp.candidate_dir( "query_cache", data, config, dir_env )
    gen       = sx_build.ensure( root ) if index is None else pathlib.Path( index ).parent
    header    = sx_build.read_header( gen )
    entries   = sx_build.read_symbols( gen )
    with fr.refresh_lock( data / fr.LOCK_FILE ):
        screen    = screen if screen is not None else pl.default_screen()
        report    = pl.write_purpose_lines( entries, writer, purpose / "purpose.jsonl", WRITER_VERSION, screen, batch_size=batch_size )
        new_dir   = live.with_name( live.name + ".new" )
        if new_dir.exists(): shutil.rmtree( new_dir )
        stored    = pl.load_lines( purpose / "purpose.jsonl" )
        try:
            reuse = vs.load_vectors( live )
        except CandidateError:
            reuse = None
        used      = {}
        staged    = screen.sendable( entries )[ 0 ]                          # the rows are the entries the stage will hold, so no vector id is a ghost to it
        manifest  = vb.build_vectors( staged, stored, client, new_dir, reuse=reuse, stats=used )
        reuse     = None
        unwritten = { e[ "pin" ] for e in staged if e[ "pin" ] not in stored }
        info      = fr.write_build_info( new_dir, header, built_at if built_at is not None else fr.utc_now(), unwritten )
        vs.swap_in( new_dir, live )
        cleared   = vs.clear_stale_queries( cache, manifest[ "manifest_hash" ] )
    return { "purposes": report, "manifest_hash": manifest[ "manifest_hash" ], "rows": manifest[ "rows" ],
             "stale_queries_cleared": cleared, "seconds": round( time.monotonic() - started, 1 ),
             "index_manifest": info[ "index_manifest" ], "built_at": info[ "built_at" ],
             "unwritten_pins": info[ "unwritten_pins" ], "vectors": used }


def sample_purposes( root, writer, store_path, count, batch_size=pl.BATCH_SIZE, screen=None, index=None ):
    """
    Write purpose lines for an evenly spaced sample of the index into a separate store.

    Requires:
        - root is a lupin repository root
        - count is a positive integer
        - store_path is a purpose.jsonl path that is not the live store

    Ensures:
        - the entries are the public symbols sorted by id, taking every k-th, so two runs pick the same ones
        - returns the write report with the sampled ids added as "ids"
    """
    gen     = sx_build.ensure( pathlib.Path( root ) ) if index is None else pathlib.Path( index ).parent
    entries = sorted( sx_build.read_symbols( gen ), key=lambda e: e[ "id" ] )
    step    = max( 1, len( entries ) // count )
    chosen  = entries[ ::step ][ :count ]
    report  = pl.write_purpose_lines( chosen, writer, store_path, WRITER_VERSION,
                                      screen if screen is not None else pl.default_screen(), batch_size=batch_size )
    report[ "ids" ] = [ e[ "id" ] for e in chosen ]
    return report


def make_job_writer( root, base_url, environ, index=None, out_dir=None ):
    """
    Build the bounded-job writer the live runs use.

    Requires:
        - root is the main checkout, never a worktree: the job reads the index of the main checkout,
          unless index and out_dir name a tree-local build
        - environ holds LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD

    Ensures:
        - returns a BoundedJobWriter whose submit logs in to base_url and posts to /api/v2/submit
        - the hand-off folder and the index path are the ones the container sees
        - with index and out_dir, the index path is the named file and the hand-off folder is out_dir/handoff

    Raises:
        - ValueError naming the main checkout when root is a worktree
        - CandidateError DEPENDENCY_MISSING when a credential variable is absent
    """
    main_tree = sp.main_checkout( root )
    if index is None and pathlib.Path( root ).resolve() != pathlib.Path( main_tree ).resolve():
        raise ValueError( f"--root {root} is a worktree; the job reads the index of the main checkout {main_tree}. Pass --root {main_tree}" )
    try:
        email, password = environ[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" ], environ[ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ]
    except KeyError as e:
        raise CandidateError( DEPENDENCY_MISSING, f"the job credential variable {e.args[ 0 ]} is not set" )
    submit = lambda payload: harness_schedule.submit( payload, base_url, email, password )
    to_c   = lambda path: sp.container_path( path, root, environ=environ )
    if index is None:
        return BoundedJobWriter( sp.handoff_dir( root, environ=environ ), submit, to_container=to_c,
                                 index_path=to_c( default_out_dir( main_tree ) / "current" / "symbols.jsonl" ) )
    return BoundedJobWriter( pathlib.Path( out_dir ) / "handoff", submit, to_container=to_c, index_path=to_c( index ) )


def main( argv=None, environ=None, writer_factory=None, client=None ):
    """
    Command line entry: build the purpose lines and the vector set for one repository.

    Requires:
        - the INI keys of the candidate storage are set
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD are set, for the job submit

    Ensures:
        - prints the run report as JSON and returns 0
        - returns 2 and prints the code when a CandidateError stops the run
        - exits with the argparse usage error, naming the option, for a batch size or sample below 1,
          a --sample without --store, --index without --out-dir or the reverse, an --out-dir that
          overlaps the index, is outside the main checkout or sits in its tracked tree, or a
          worktree --root without --index
    """
    environ = os.environ if environ is None else environ
    parser  = argparse.ArgumentParser( description="Write purpose lines and rebuild the candidate vector set." )
    parser.add_argument( "--root", required=True )
    parser.add_argument( "--base-url", default=environ.get( "LUPIN_APP_SERVER_URL", "http://localhost:7999" ) )
    parser.add_argument( "--batch-size", type=int, default=pl.BATCH_SIZE )
    parser.add_argument( "--sample", type=int, default=0, help="write lines for this many entries into --store and build nothing" )
    parser.add_argument( "--store", default=None, help="the purpose.jsonl path for --sample" )
    parser.add_argument( "--index", default=None, help="symbols.jsonl to read, read only; needs --out-dir; lets --root be a worktree" )
    parser.add_argument( "--out-dir", default=None, help="folder for the purpose, vector and query-cache output; needs --index" )
    args    = parser.parse_args( argv )
    if args.batch_size < 1: parser.error( f"--batch-size must be 1 or more, got {args.batch_size}" )
    if args.sample < 0:     parser.error( f"--sample must be 1 or more, or left out, got {args.sample}" )
    if args.sample and args.store is None: parser.error( "--sample needs --store, the purpose.jsonl path to write" )
    if ( args.index is None ) != ( args.out_dir is None ): parser.error( "--index and --out-dir are given together or not at all" )
    if args.index is not None:
        why = tree_path_refusal( args.index, args.out_dir, sp.main_checkout( args.root ) )
        if why: parser.error( why )
    try:
        if writer_factory is None:
            try:
                writer = make_job_writer( args.root, args.base_url, environ, index=args.index, out_dir=args.out_dir )
            except ValueError as e:
                parser.error( str( e ) )
        else:
            writer = writer_factory( args )
        if args.sample:
            report = sample_purposes( args.root, writer, args.store, args.sample, batch_size=args.batch_size, index=args.index )
        else:
            report = run( args.root, writer, client if client is not None else vb.EndpointClient(), environ=environ, batch_size=args.batch_size,
                         index=args.index, out_dir=args.out_dir )
    except CandidateError as e:
        print( json.dumps( { "error": e.code, "detail": e.detail } ) )
        return 2
    print( json.dumps( report, indent=2 ) )
    return 0


if __name__ == "__main__":    # pragma: no cover -- process entry, main() is tested
    sys.exit( main() )
