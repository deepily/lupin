"""
The ten-need drafting smoke: a small live run that measures and sets no pass bar.

It takes a test-only kind split and a named commit as arguments and marks every need smoke.
It writes the date, host, commit, seconds per call and failure rate beside the drafts.
A live run is refused outside 10 a.m. to 1 p.m. Eastern, the window the Max plan allows.
"""
import argparse
import datetime
import json
import pathlib
import socket
import sys
import threading
import time
import zoneinfo

from cosa.repo.symindex import build, dups, spec as sp
from cosa.repo.symindex.candidates import candidate_stage, vector_build, vector_store
from lupin_mcp.reuse_needset import draft, keys, pool, quota, run, strip
from lupin_mcp.reuse_needset import errors as er

EASTERN      = zoneinfo.ZoneInfo( "America/New_York" )
WINDOW_START = 10
WINDOW_END   = 13
TOTAL        = 10
MATCHED      = 8
NONE         = 2
SECOND_MODEL = "claude-opus-5-5"
SECOND_SYSTEM = "You answer with one JSON object and nothing else."
SMOKE_FILE   = "needset-smoke.json"
SMOKE_FORMAT = "needset-smoke-1"


def in_window( now ):
    """
    Say whether a moment falls in the hours a live model run is allowed.

    Requires:
        - now is a timezone-aware datetime

    Ensures:
        - True from 10:00 up to, not including, 13:00 Eastern time, on any day

    Raises:
        - ValueError when now has no timezone
    """
    if now.tzinfo is None: raise ValueError( "now must carry a timezone" )
    return WINDOW_START <= now.astimezone( EASTERN ).hour < WINDOW_END


def parse_args( argv ):
    """
    Read the command line.

    Ensures:
        - the root, out dir, source commit, seed, vector folders and the three matched-kind counts are required
        - the kind split is whatever is passed; no default stands in for the real split
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "--root",             required=True )
    ap.add_argument( "--out-dir",          required=True )
    ap.add_argument( "--source-commit",    required=True )
    ap.add_argument( "--seed",             required=True, type=int )
    ap.add_argument( "--vectors-dir",      required=True )
    ap.add_argument( "--query-cache-dir",  required=True )
    ap.add_argument( "--near-copy",        required=True, type=int )
    ap.add_argument( "--work-alike",       required=True, type=int )
    ap.add_argument( "--cross-language",   required=True, type=int )
    ap.add_argument( "--ts-share",         type=float, default=0.6 )
    ap.add_argument( "--parallel",         type=int, default=3 )
    ap.add_argument( "--server",           default="max-plan" )
    ap.add_argument( "--set-by",           default="smoke" )
    ap.add_argument( "--cli-path",         default=None )
    ap.add_argument( "--second-model",     default=SECOND_MODEL )
    return ap.parse_args( argv )


def kind_split( args ):
    """Return the matched-kind split the arguments name."""
    return { "near_copy": args.near_copy, "work_alike": args.work_alike, "cross_language": args.cross_language }


class Timed:
    """A drafter call that times every call and counts the ones that raise."""

    def __init__( self, ask, clock ):
        """Wrap ask( system, user ) and read the time from clock()."""
        self.ask, self.clock, self.seconds, self.errors, self.lock = ask, clock, [], 0, threading.Lock()

    def __call__( self, system, prompt ):
        """Forward the call, recording its duration and any failure."""
        start = self.clock()
        try:
            return self.ask( system, prompt )
        except Exception:
            with self.lock: self.errors += 1
            raise
        finally:
            with self.lock: self.seconds.append( self.clock() - start )


def index_parts( root, index_dir ):
    """
    Build the index of a tree and everything the run reads from it.

    Requires:
        - root is a repository root and index_dir a folder to publish the index in

    Ensures:
        - returns ( by_id, kept, measures, twins, bodies ) with by_id holding every searchable record
        - twin ids carry the same prefix the index gives, so they match the index's ids
    """
    root    = pathlib.Path( root )
    built   = build.build( root, index_dir )
    records, _reader = pool.read_pool_symbols( built[ "gen_dir" ] )
    measures = pool.measure( root, records )
    kept, _dropped = pool.eligible( records, measures )
    spec    = sp.spec_for( root )
    found   = dups.find_duplicates( spec, sp.iter_files( spec, spec.py_roots, { ".py" } ), js_files=sp.iter_files( spec, spec.js_roots, set( sp.SCRIPT_SUFFIXES ) ) )
    twins   = pool.twin_map( found, prefix="" if build.is_lupin_tree( spec.root ) else f"{spec.name}:" )
    return { r[ "id" ]: r for r in records }, kept, measures, twins, strip.bodies_for( kept, root )


def candidate_parts( vectors_dir, cache_dir, client, records ):
    """
    Load the live vector set and build the word stage and the query embedder.

    Requires:
        - vectors_dir holds a sealed vector set; client has embed( texts, content_type, role ) and info()

    Ensures:
        - returns ( vectors, stage, embed ) where embed( text ) is the concat query vector of that text
    """
    vectors = vector_store.load_vectors( vectors_dir )
    stage   = candidate_stage.build_stage( records )
    embed   = lambda text: vector_store.query_vectors( text, client, cache_dir, vectors.manifest )[ "concat" ]
    return vectors, stage, embed


def assemble_env( args, ask, second_ask, client, set_at ):
    """
    Put the index, the candidate parts and the model calls into a run.Env.

    Requires:
        - ask( system, user ) and second_ask( system, user ) return reply text; client is an embeddings client

    Ensures:
        - the env is a smoke env, with its two ledgers under args.out_dir
        - the seed pool is the eligible symbols that have a row in the vector set, and the counts are kept in env.extras
        - a symbol newer than the vector set is left out, so the smoke measures; the real draw needs a fresh vector set
    """
    root, out = pathlib.Path( args.root ), pathlib.Path( args.out_dir )
    by_id, kept, measures, twins, bodies = index_parts( root, out / "index" )
    vectors, stage, embed = candidate_parts( args.vectors_dir, args.query_cache_dir, client, list( by_id.values() ) )
    rows    = set( vectors.ids )
    pooled  = [ r for r in kept if r[ "id" ] in rows ]
    extras  = { "vector_coverage": { "eligible": len( kept ), "with_a_vector_row": len( pooled ), "vector_set_ids": len( rows ) } }
    book    = draft.SharedLedger( draft.make_ledger( out / "ledger-draft.jsonl", args.cli_path, args.server ) )
    second  = draft.SharedLedger( draft.make_ledger( out / "ledger-second.jsonl", args.cli_path, args.server ) )
    describe = lambda i: f"{by_id[ i ][ 'sig' ]} — {by_id[ i ][ 'doc' ]}"
    none_fn = draft.make_none_drafter( stage, vectors, embed, describe, lambda prompt: second_ask( SECOND_SYSTEM, prompt ), second, args.second_model )
    ctx     = keys.KeyContext( pooled, measures, bodies, args.seed, vectors )
    return run.Env( by_id, pooled, ctx, twins, lambda rec: strip.strip_member( rec, root ), ask, book, draft.DRAFTER_MODEL, args.server, args.source_commit,
                    args.seed, kind_split( args ), args.set_by, set_at, none_draft_fn=none_fn, parallel=args.parallel, smoke=True, extras=extras )


def live_build_env( args, set_at ):
    """Build the env with the real drafter, the real second model and the real embeddings client."""
    return assemble_env( args, draft.drafter_call(), draft.drafter_call( args.second_model ), vector_build.EndpointClient(), set_at )


def smoke_report( args, timed, result, started, finished, host, extras ):
    """
    Summarise one smoke run as measurements.

    Ensures:
        - returns the date, host, source commit, split, seed, call count, seconds per call (mean, min, max, or None with no call) and the env's extras
        - failure_rate is the failed seeds over the seeds tried, with failed seeds listed by reason
        - says in a note that it is a measurement and not a pass bar
    """
    cells  = result[ "cells" ]
    failed = [ f for c in cells for f in c[ "failed" ] ]
    tried  = sum( len( c[ "accepted" ] ) for c in cells ) + len( failed )
    secs   = timed.seconds
    reasons = {}
    for f in failed: reasons[ f[ "reason" ] ] = reasons.get( f[ "reason" ], 0 ) + 1
    return { "format": SMOKE_FORMAT, "smoke": True, "date": finished.isoformat(), "host": host, "source_commit": args.source_commit, "seed": args.seed,
             "kind_split": kind_split( args ), "ts_share": args.ts_share, "needs": len( result[ "needs" ] ), "model_calls": len( secs ), "call_errors": timed.errors,
             "seconds_per_call": { "mean": sum( secs ) / len( secs ), "min": min( secs ), "max": max( secs ) } if secs else None,
             "seeds_tried": tried, "seeds_failed": len( failed ), "failure_rate": len( failed ) / tried if tried else None, "failed_by_reason": reasons,
             "elapsed_seconds": ( finished - started ).total_seconds(), "extras": extras, "note": "a measurement, not a pass bar" }


def main( argv=None, build_env=None, now=None, clock=time.monotonic, host=None ):
    """
    Run the smoke: refuse a live run outside the window, then draft ten needs and measure.

    Requires:
        - build_env( args, set_at ) returns a run.Env; None means the live env with real models
        - now is a function returning an aware datetime, None for the system clock

    Ensures:
        - returns the smoke report, also written as needset-smoke.json beside the plan, drafts and draft report
        - every need carries smoke true, and the drafter's calls are timed
        - the window is checked before anything is built or called, and only for the live env

    Raises:
        - NeedsetError OUTSIDE_WINDOW for a live run at another time
        - NeedsetError KIND_SPLIT_UNSET or QUOTA_INVALID from the split the arguments name
    """
    args  = parse_args( argv )
    now   = ( lambda: datetime.datetime.now( datetime.timezone.utc ) ) if now is None else now
    live  = build_env is None
    start = now()
    if live and not in_window( start ): raise er.NeedsetError( er.OUTSIDE_WINDOW, start.astimezone( EASTERN ).isoformat() )
    table = quota.plan_quota( TOTAL, MATCHED, NONE, args.ts_share, kind_split( args ) )
    pathlib.Path( args.out_dir ).mkdir( parents=True, exist_ok=True )
    env   = ( live_build_env if live else build_env )( args, start.isoformat() )
    timed = Timed( env.ask, clock )
    env.ask, env.smoke = timed, True
    result = run.run_needset( env, table, args.out_dir )
    report = smoke_report( args, timed, result, start, now(), socket.gethostname() if host is None else host, env.extras )
    ( pathlib.Path( args.out_dir ) / SMOKE_FILE ).write_text( json.dumps( report, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    return report


if __name__ == "__main__":
    print( json.dumps( main(), indent=4 ) )
    sys.exit( 0 )
