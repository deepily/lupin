"""
Run one arm of the offline comparison against the cached sweep and the known twins.

The functions read the in-sample needs, the cached judge answers and the baseline twin manifest.
Every reader is passed in, so a unit test feeds hand-built cases and the run feeds the real ones.
"""
import argparse
import collections
import gzip
import hashlib
import json
import os
import types

from cosa.repo.symindex import verdict as vd
from cosa.repo.symindex.candidates import arm_metrics as am
from cosa.repo.symindex.candidates import arm_report as ar
from cosa.repo.symindex.candidates import arms
from cosa.repo.symindex.candidates.errors import CandidateError

REPEATS          = ( 1, 2, 3, 4, 5 )
REPLAY_KS        = ( 128, 512 )
TWIN_SOURCE_KEYS = ( "exact", "near" )


def real_env( data_dir ):
    """
    Build the readers of the real index and the real answer cache.

    Requires:
        - data_dir is the folder that holds the jev-cache

    Ensures:
        - returns a namespace with sendable, entry_text, pair_key, model and cache
    """
    from lupin_mcp import reuse_pack as rp
    from lupin_mcp import reuse_tools as rt
    return types.SimpleNamespace( sendable=rt.sendable, entry_text=rt.entry_text, pair_key=rp.pair_key, model=rt.JEV_MODEL, cache=rt.JevCache( data_dir ) )


def sha256_of( path ):
    """Return the sha256 hex digest of a file's bytes."""
    return hashlib.sha256( open( path, "rb" ).read() ).hexdigest()


def load_needs( path, fresh_sha ):
    """
    Read the in-sample needs and refuse the reserved file.

    Requires:
        - path is a needs file holding { "needs": [ { id, need, exclude } ] }
        - fresh_sha is the content hash of the reserved needs file

    Ensures:
        - returns { need id: need record }
        - the reserved ids and the reserved file are refused, by arms.refuse_fresh_needs

    Raises:
        - CandidateError FRESH_NEEDS_REFUSED from the guard
    """
    needs = { n[ "id" ]: n for n in json.load( open( path ) )[ "needs" ] }
    arms.refuse_fresh_needs( list( needs ), sha256_of( path ), fresh_sha )
    return needs


def snapshot_entries( path, sendable ):
    """
    Read the index entries of one stored snapshot.

    Requires:
        - path is a gzip file holding { "symbols_jsonl": <one JSON entry per line> }
        - sendable takes ( entries, excluded prefixes ) and returns ( kept, dropped )

    Ensures:
        - returns the entries the sweep would send
    """
    snap    = json.loads( gzip.decompress( open( path, "rb" ).read() ).decode( "utf-8" ) )
    entries = [ json.loads( line ) for line in snap[ "symbols_jsonl" ].splitlines() if line ]
    return sendable( entries, () )[ 0 ]


def pick_snapshot( paths, hits_for ):
    """
    Choose the snapshot the cache answers best.

    Requires:
        - paths is a non-empty list of snapshot paths
        - hits_for takes a path and returns how many probe answers the cache holds for it

    Ensures:
        - returns ( hits, path ) for the most hits, the first path winning a tie
    """
    return max( ( ( hits_for( p ), p ) for p in sorted( paths ) ), key=lambda pair: pair[ 0 ] )


def load_answers( needs, entries, env, repeats=REPEATS ):
    """
    Read the cached judge answers of the new question for every need and repeat.

    Requires:
        - needs maps need id to a record with need and exclude
        - entries is the snapshot's entries
        - env holds pair_key, entry_text, model and a cache with get

    Ensures:
        - returns ( answers, misses ); answers maps ( need id, repeat ) to { entry id: { provides, coverage } }
        - the entry a need excludes is not asked, and an entry with no cached answer counts as a miss
    """
    answers, misses = {}, 0
    for need_id, record in needs.items():
        for repeat in repeats:
            held = {}
            for entry in entries:
                if entry[ "id" ] == record[ "exclude" ]: continue
                hit = env.cache.get( env.pair_key( record[ "need" ], env.entry_text( entry ), env.model, repeat ) )
                if hit is None: misses += 1; continue
                fit = hit[ "answers" ][ "fit" ]
                held[ entry[ "id" ] ] = { "provides": fit[ "provides" ], "coverage": fit[ "probabilities" ] }
            answers[ ( need_id, repeat ) ] = held
    return answers, misses


def hash_answers( answers ):
    """Return a hash of the answers that were read, so a page names exactly what it replayed."""
    flat = [ [ n, r, sorted( held.items() ) ] for ( n, r ), held in sorted( answers.items() ) ]
    return hashlib.sha256( json.dumps( flat, sort_keys=True ).encode( "utf-8" ) ).hexdigest()


def references( answers, needs ):
    """
    Take the full sweep's shortlist for every need.

    Requires:
        - answers is load_answers's mapping and holds every repeat in the module's repeat list for each need

    Ensures:
        - returns ( first, union ): the shortlist ids of repeat 1, and the ids any repeat shortlisted, per need
    """
    def shortlist( need_id, repeat ):
        held = answers[ ( need_id, repeat ) ]
        rows = [ { "id": i, **a } for i, a in held.items() ]
        return am.reference_ids( vd.decide_provides( rows, sorted( held ), [], set() ) )
    first = { n: shortlist( n, 1 ) for n in needs }
    union = { n: sorted( set().union( *[ set( shortlist( n, r ) ) for r in REPEATS ] ) ) for n in needs }
    return first, union


def measure_arm( arm, needs, stages, available, answers, ks=arms.KS ):
    """
    Measure one arm on the in-sample needs, by recall and by verdict replay.

    Requires:
        - available holds every list the arm fuses
        - answers is load_answers's mapping

    Ensures:
        - returns { t1_first, t1_union, empty, t2 } with t1 tables from arm_metrics.t1_table
        - empty lists the needs whose repeat-1 reference is empty; they are left out of both t1 tables
        - t2 maps "control" and "K=<k>" for each of REPLAY_KS to the t2_replay result
        - the control replays the whole answered set, so its agreement is 1.0 whatever the arm
    """
    first, union = references( answers, needs )
    short = { k: { n: arms.run_arm( arm, needs[ n ][ "need" ], stages, available, k )[ "shortlist" ] for n in needs } for k in sorted( set( ks ) | set( REPLAY_KS ) ) }
    cuts  = { k: short[ k ] for k in ks }
    t2    = { "control": am.t2_replay( { n: sorted( answers[ ( n, 1 ) ] ) for n in needs }, answers ) }
    for k in REPLAY_KS: t2[ f"K={k}" ] = am.t2_replay( short[ k ], answers )
    return { "t1_first" : am.t1_table( { arm: cuts }, first )[ arm ],
             "t1_union" : am.t1_table( { arm: cuts }, union )[ arm ],
             "empty"    : sorted( n for n, ids in first.items() if not ids ),
             "t2"       : t2 }


def twin_map( manifest ):
    """
    Map every known-twin member to the other members of its cluster.

    Requires:
        - manifest holds exact and near clusters, each with members that carry an id

    Ensures:
        - returns { member id: set of twin ids }, never holding the member itself
    """
    twins = collections.defaultdict( set )
    for key in TWIN_SOURCE_KEYS:
        for cluster in manifest[ key ]:
            ids = [ m[ "id" ] for m in cluster[ "members" ] ]
            for member in ids: twins[ member ].update( i for i in ids if i != member )
    return dict( twins )


def query_text( entry ):
    """
    Build the query for a known-twin member from its own entry text.

    Ensures:
        - returns the name, the signature and the first docstring line, joined by single spaces
        - the purpose line joins the query once the index carries one
    """
    first = ( entry.get( "doc" ) or "" ).strip().splitlines()[ 0:1 ]
    return " ".join( [ entry[ "name" ], entry.get( "sig" ) or "" ] + first ).strip()


def measure_twins( arm, entries, twins, stages, available ):
    """
    Find where each known-twin member's best twin lands.

    Requires:
        - entries is the snapshot's entries
        - twins is twin_map's result

    Ensures:
        - returns ( ranks_by_language, absent ): the best twin rank per member grouped by file suffix, and the members not in the index
        - the member is left out of the ranking before a rank is read, and None marks a member whose twins are not ranked
    """
    by_id  = { e[ "id" ]: e for e in entries }
    absent = sorted( m for m in twins if m not in by_id )
    ranks  = collections.defaultdict( list )
    for member in sorted( twins ):
        if member not in by_id: continue
        ranking = [ d for d in arms.full_ranking( arm, query_text( by_id[ member ] ), stages, available ) if d != member ]
        found   = [ r for r in ( am.twin_rank( ranking, t ) for t in sorted( twins[ member ] ) if t in by_id ) if r is not None ]
        suffix  = os.path.splitext( by_id[ member ][ "file" ] )[ 1 ].lstrip( "." ) or "other"
        ranks[ suffix ].append( min( found ) if found else None )
    return dict( ranks ), absent


def render_partial_page( meta, arm, measured, t3, absent, pending, ruling ):
    """
    Build the results page for the arms measured so far.

    Requires:
        - meta holds every key of arm_report.META_KEYS
        - measured is measure_arm's result, t3 is am.t3_summary of measure_twins's ranks with a first count per language
        - pending lists the arms not measured yet, each as ( arm, what it waits on )
        - ruling is the sentence that defines the twin query

    Ensures:
        - returns the page text
        - states that every figure is in-sample, and that none is a flip rate
        - lists the pending arms and what each waits on

    Raises:
        - CandidateError REPORT_META_MISSING naming the absent keys
    """
    absent_keys = [ key for key in ar.META_KEYS if not meta.get( key ) ]
    if absent_keys: raise CandidateError( ar.REPORT_META_MISSING, ", ".join( absent_keys ) )
    ks    = sorted( measured[ "t1_first" ] )
    lines = [ f"# Offline comparison: arm {arm}", "",
              "All figures are in-sample, so they rank arms against each other. They are not a flip rate.", "",
              "| key | value |", "|---|---|" ] + [ f"| {key} | {meta[ key ]} |" for key in ar.META_KEYS ]
    lines += [ "", "## Recall of the cached full-sweep shortlist", "",
               f"Counted over the needs whose reference is not empty. {len( measured[ 'empty' ] )} needs have an empty reference and are left out: "
               + ", ".join( measured[ "empty" ] ) + ".", "",
               "| K | repeat-1 reference | union of repeats | mean shortlist size |", "|---|---|---|---|" ]
    for k in ks:
        row = measured[ "t1_first" ][ k ]
        lines.append( f"| {k} | {ar.percent( row[ 'mean' ] )} | {ar.percent( measured[ 't1_union' ][ k ][ 'mean' ] )} | {ar.size( row[ 'mean_size' ] )} |" )
    lines += [ "", "## Where the known twin lands", "", ruling, "",
               "| language | members | unranked | median | median counting unranked as worst | rank 1 | top 10 | top 50 | top 128 |", "|---|---|---|---|---|---|---|---|---|" ]
    for language in sorted( t3 ):
        row = t3[ language ]
        lines.append( f"| {language} | {row[ 'members' ]} | {row[ 'unranked' ]} | {row[ 'median' ]} | {row[ 'median_all' ]} "
                      f"| {row[ 'first' ]} | {row[ 'within' ][ 10 ]} | {row[ 'within' ][ 50 ]} | {row[ 'within' ][ 128 ]} |" )
    lines += [ "", f"{len( absent )} known-twin members are not in the snapshot.", "",
               "## Verdict replay of cached answers", "",
               "A flip here is a verdict difference across repeats. The strict rule also counts a shortlist difference.", "",
               "| run | needs | verdict flip rate | agreement | shortlisted entries with no cached answer |", "|---|---|---|---|---|" ]
    for label in sorted( measured[ "t2" ] ):
        row = measured[ "t2" ][ label ]
        lines.append( f"| {label} | {row[ 'needs' ]} | {ar.percent( row[ 'flip_rate' ] )} | {ar.percent( row[ 'agreement' ] )} | {row[ 'uncached' ]} |" )
    lines += [ "", "## Arms not measured yet", "", "| arm | waits on |", "|---|---|" ] + [ f"| {a} | {why} |" for a, why in pending ]
    return "\n".join( lines ) + "\n"


def run_arm_report( env, snapshot_paths, needs_path, fresh_sha, manifest_path, out_path, code_sha, arm="C0" ):
    """
    Measure an arm that needs no extra list and write its results page.

    Requires:
        - arm is one that fuses no vector or wiki list, so it needs only the index
        - the other arguments are as for the functions this one calls

    Ensures:
        - returns { page_sha, misses, snapshot, needs, members }
        - the page carries the run, the code sha and the hashes of what was read
        - the arms that need lists are named as pending

    Raises:
        - CandidateError FRESH_NEEDS_REFUSED from load_needs
    """
    needs  = load_needs( needs_path, fresh_sha )
    probe  = needs[ sorted( needs )[ 0 ] ]
    def hits_for( path ):
        held = snapshot_entries( path, env.sendable )
        return sum( 1 for e in held if env.cache.get( env.pair_key( probe[ "need" ], env.entry_text( e ), env.model, 1 ) ) is not None )
    hits, path = pick_snapshot( snapshot_paths, hits_for )
    entries    = snapshot_entries( path, env.sendable )
    answers, misses = load_answers( needs, entries, env )
    stages   = arms.build_arm_stages( entries, {} )
    measured = measure_arm( arm, needs, stages, {}, answers )
    manifest = json.load( open( manifest_path ) )
    ranks, absent = measure_twins( arm, entries, twin_map( manifest ), stages, {} )
    t3 = am.t3_summary( dict( ranks, all=[ r for held in ranks.values() for r in held ] ) )
    for language, held in dict( ranks, all=[ r for h in ranks.values() for r in h ] ).items(): t3[ language ][ "first" ] = sum( 1 for r in held if r == 1 )
    meta = { "run_id": f"{arm}-{hash_answers( answers )[ :8 ]}", "code_sha": code_sha, "index_sha": os.path.basename( path ).split( "." )[ 0 ],
             "manifest_hash": sha256_of( manifest_path ), "needs_sha": sha256_of( needs_path ), "cache_sha": hash_answers( answers ) }
    pending = [ ( "C1", "purpose lines for the whole index; only samples exist" ), ( "B1", "the concatenated vector matrix" ),
                ( "B2", "the prose and code vector matrices" ), ( "B2w", "the vector matrices and the wiki page list" ) ]
    ruling  = ( "Query ruling (Cheech, 2026-10-15): a known-twin member's query is its own entry text, the name, the signature and the first docstring line, "
                "with the purpose line added once it exists. The member is left out of the ranking, and the rank is where its best twin lands. "
                "Every arm uses the same query." )
    page = render_partial_page( meta, arm, measured, t3, absent, pending, ruling )
    return { "page_sha": ar.write_report( out_path, page ), "misses": misses, "snapshot": path, "needs": len( needs ), "members": len( twin_map( manifest ) ) }


def main( argv=None ):
    """
    Run the measurement from the command line.

    Requires:
        - argv holds --data, --needs, --fresh-sha, --manifest, --out and --code-sha

    Ensures:
        - prints the result of run_arm_report and returns 0
    """
    parser = argparse.ArgumentParser( description="Measure arm C0 against the cached sweep and the known twins" )
    for name in ( "data", "needs", "fresh-sha", "manifest", "out", "code-sha" ): parser.add_argument( f"--{name}", required=True )
    args  = parser.parse_args( argv )
    env   = real_env( args.data )
    snaps = sorted( os.path.join( args.data, "snapshots", p ) for p in os.listdir( os.path.join( args.data, "snapshots" ) ) )
    out   = run_arm_report( env, snaps, args.needs, args.fresh_sha, args.manifest, args.out, args.code_sha )
    print( json.dumps( out, indent=2 ) )
    return 0


if __name__ == "__main__":  # pragma: no cover -- the guard line only; main() has its own test
    raise SystemExit( main() )
