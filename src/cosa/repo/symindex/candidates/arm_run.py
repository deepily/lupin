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
import pathlib
import types

from cosa.repo.symindex import verdict as vd
from cosa.repo.symindex.candidates import arm_metrics as am
from cosa.repo.symindex.candidates import arm_report as ar
from cosa.repo.symindex.candidates import arms
from cosa.repo.symindex.candidates import rank_fusion as rf
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError

QUERY_VECTOR_MISSING = "QUERY_VECTOR_MISSING"
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


def lists_for( available, text ):
    """
    Resolve the extra lists for one query.

    Requires:
        - available is a mapping of source name to ranked ids, or a callable taking the query text and returning one

    Ensures:
        - returns the mapping, so an arm whose vectors depend on the query text and an arm with fixed lists run the same code
    """
    return available( text ) if callable( available ) else available


def measure_arm( arm, needs, stages, available, answers, ks=arms.KS ):
    """
    Measure one arm on the in-sample needs, by recall and by verdict replay.

    Requires:
        - available holds every list the arm fuses, or is a callable that takes a need's text and returns them
        - answers is load_answers's mapping

    Ensures:
        - returns { t1_first, t1_union, empty, t2 } with t1 tables from arm_metrics.t1_table
        - empty lists the needs whose repeat-1 reference is empty; they are left out of both t1 tables
        - t2 maps "control" and "K=<k>" for each of REPLAY_KS to the t2_replay result
        - the control replays the whole answered set, so its agreement is 1.0 whatever the arm
    """
    first, union = references( answers, needs )
    short = { k: { n: arms.run_arm( arm, needs[ n ][ "need" ], stages, lists_for( available, needs[ n ][ "need" ] ), k )[ "shortlist" ] for n in needs } for k in sorted( set( ks ) | set( REPLAY_KS ) ) }
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
        - available is a mapping of lists, or a callable that takes the query text and returns one

    Ensures:
        - returns ( ranks_by_language, absent ): the best twin rank per member grouped by file suffix, and the members not in the index
        - the member is left out of the ranking before a rank is read, and None marks a member whose twins are not ranked
    """
    by_id  = { e[ "id" ]: e for e in entries }
    absent = sorted( m for m in twins if m not in by_id )
    ranks  = collections.defaultdict( list )
    for member in sorted( twins ):
        if member not in by_id: continue
        text    = query_text( by_id[ member ] )
        ranking = [ d for d in arms.full_ranking( arm, text, stages, lists_for( available, text ) ) if d != member ]
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


FUSION_GRID    = tuple( ( k, depth, head ) for k in ( 10, 30, 60, 100 ) for depth in ( 128, 256, 512 ) for head in ( 5, 10 ) )
SELECTION_ARM  = "B2"
SELECTION_K    = 128
VECTOR_NAMES   = ( "concat", "prose", "code" )


def vector_source( entry_ids, vset, query_for ):
    """
    Build the callable that gives an arm its vector lists for one query text.

    Requires:
        - entry_ids is the list of entry ids the arms rank, and vset is a loaded VectorSet
        - query_for takes a text and returns { concat, prose, code } query vectors

    Ensures:
        - returns a callable text -> { vector_concat, vector_prose, vector_code } ranked ids
        - only entries that the vector set holds are ranked; the rest are absent from every vector list
        - the matrices are cut to those rows once, not for every query
    """
    row   = { i: n for n, i in enumerate( vset.ids ) }
    held  = [ i for i in entry_ids if i in row ]
    index = [ row[ i ] for i in held ]
    cut   = { name: vset.matrices[ name ][ index ] for name in VECTOR_NAMES }
    return lambda text: arms.cosine_sources( held, cut, query_for( text ) )


def select_fusion_constants( needs, entries, purposes, answers, available, grid=FUSION_GRID ):
    """
    Pick the fusion constants on the in-sample needs.

    Requires:
        - the arguments are those of measure_arm and arms.build_arm_stages
        - grid is a collection of ( k, depth, head ) triples

    Ensures:
        - returns ( chosen, recall_by_params ); chosen is arms.select_fusion's pick
        - recall is the mean repeat-1 recall of arm SELECTION_ARM at K=SELECTION_K, so one measure picks for every arm
    """
    first, _ = references( answers, needs )
    recall   = {}
    for params in grid:
        stages = arms.build_arm_stages( entries, purposes, *params )
        cut    = { n: arms.run_arm( SELECTION_ARM, needs[ n ][ "need" ], stages, lists_for( available, needs[ n ][ "need" ] ), SELECTION_K )[ "shortlist" ] for n in needs }
        recall[ params ] = am.t1_table( { SELECTION_ARM: { SELECTION_K: cut } }, first )[ SELECTION_ARM ][ SELECTION_K ][ "mean" ] or 0.0
    return arms.select_fusion( recall ), recall


def run_all_arms( env, snapshot_paths, needs_path, fresh_sha, manifest_path, vset, purposes, pages, query_for, redactor, code_sha, grid=FUSION_GRID, arm_names=arms.ARMS ):
    """
    Measure all five arms on one index, one needs file and one vector set.

    Requires:
        - env, snapshot_paths, needs_path, fresh_sha and manifest_path are as for run_arm_report
        - vset is a loaded VectorSet, purposes maps pin to purpose line, pages is page_candidates' list
        - query_for takes a text and returns { concat, prose, code } query vectors, redactor takes a text and returns its ranking text
        - arm_names lists the arms to measure; with only arms that fuse no vector list, vset and query_for may be None

    Ensures:
        - returns { meta, fusion, recall_by_params, measured, t3, absent, vectors_choice, misses, snapshot, needs, pages, twin_manifest_sha,
          empty_purpose_entries, empty_purpose_in_references, vector_entries, snapshot_entries }
        - pages is the number of capability pages offered to the wiki list; redactable is not in the result, the caller counts it
        - every arm ranks the same entries for the same ranking text, and the fusion constants come from select_fusion_constants
        - the page builder reads this dict and measures nothing
        - when no measured arm fuses a vector list, nothing is embedded, the fusion constants are the module defaults, and
          vectors_choice and the selection table are None and empty, so a page cannot claim a choice that was not made

    Raises:
        - CandidateError FRESH_NEEDS_REFUSED from load_needs
    """
    from cosa.repo.symindex.candidates import wiki_list
    needs  = load_needs( needs_path, fresh_sha )
    probe  = needs[ sorted( needs )[ 0 ] ]
    def hits_for( path ):
        held = snapshot_entries( path, env.sendable )
        return sum( 1 for e in held if env.cache.get( env.pair_key( probe[ "need" ], env.entry_text( e ), env.model, 1 ) ) is not None )
    hits, path = pick_snapshot( snapshot_paths, hits_for )
    entries    = snapshot_entries( path, env.sendable )
    answers, misses = load_answers( needs, entries, env )
    ranked_needs = { n: dict( rec, need=redactor( rec[ "need" ] ) ) for n, rec in needs.items() }
    entry_ids  = sorted( e[ "id" ] for e in entries )
    with_vectors = any( arms.ARM_SOURCES[ a ] for a in arm_names )
    source     = vector_source( entry_ids, vset, query_for ) if with_vectors else None
    wiki_for   = lambda text: wiki_list.wiki_ranked_ids( text, pages )
    def available( text ): return { **source( text ), "wiki": wiki_for( text ) }
    if with_vectors: fusion, recall = select_fusion_constants( ranked_needs, entries, purposes, answers, available, grid )
    else: available, fusion, recall = ( lambda text: {} ), ( rf.FUSION_K, rf.FUSION_DEPTH, rf.FUSION_HEAD ), {}
    stages   = arms.build_arm_stages( entries, purposes, *fusion )
    manifest = json.load( open( manifest_path ) )
    twins    = twin_map( manifest )
    measured, t3 = {}, {}
    for arm in arm_names:
        measured[ arm ] = measure_arm( arm, ranked_needs, stages, available, answers )
        ranks, absent   = measure_twins( arm, entries, twins, stages, available )
        t3[ arm ]       = am.t3_summary( dict( ranks, all=[ r for held in ranks.values() for r in held ] ) )
    held_ids = set( entry_ids ) & set( vset.ids ) if vset is not None else set()
    b1, b2 = [ { "recall_128": measured[ a ][ "t1_first" ][ 128 ][ "mean" ], "median_rank": t3[ a ][ "all" ][ "median_all" ] } if a in measured else None for a in ( "B1", "B2" ) ]
    empty_pins = { e[ "id" ] for e in entries if e.get( "pin" ) in purposes and not purposes[ e[ "pin" ] ] }
    first, union = references( answers, needs )
    used = sorted( empty_pins & ( set().union( *first.values() ) | set().union( *union.values() ) ) )
    meta = { "run_id": f"all-{hash_answers( answers )[ :8 ]}", "code_sha": code_sha, "index_sha": os.path.basename( path ).split( "." )[ 0 ],
             "manifest_hash": vset.manifest_hash if vset is not None else "none", "needs_sha": sha256_of( needs_path ), "cache_sha": hash_answers( answers ) }
    return { "meta": meta, "fusion": fusion, "recall_by_params": recall, "measured": measured, "t3": t3, "absent": absent,
             "vectors_choice": am.choose_vectors( b1, b2 ) if b1 and b2 else None, "misses": misses, "snapshot": path,
             "empty_purpose_entries": len( empty_pins ), "empty_purpose_in_references": used,
             "vector_entries": len( held_ids ), "snapshot_entries": len( entry_ids ), "twin_manifest_sha": sha256_of( manifest_path ), "pages": len( pages ),
             "needs": len( needs ) }


def cached_query_vectors( cache_dir, manifest_hash ):
    """
    Build a read-only source of query vectors from a cache another process filled.

    Requires:
        - cache_dir holds files named <sha256 of the text>.json, as vector_store.query_vectors writes them
        - manifest_hash is the hash of the vector set the vectors must have been made under

    Ensures:
        - returns a callable text -> { concat, prose, code } that never embeds and never writes
        - a text with no file, an unreadable file, or a file made under another set is a named error, not a recomputation

    Raises:
        - CandidateError QUERY_VECTOR_MISSING from the returned callable
    """
    def read( text ):
        path = pathlib.Path( cache_dir ) / f"{vs.query_key( text )}.json"
        try:
            stored = json.loads( path.read_text( encoding="utf-8" ) )
            made_under, vectors = stored[ "manifest_hash" ], stored[ "vectors" ]
        except ( OSError, ValueError, KeyError ) as e:
            raise CandidateError( QUERY_VECTOR_MISSING, f"no readable cached query vector for {vs.query_key( text )[ :12 ]}: {type( e ).__name__}" )
        if made_under != manifest_hash:
            raise CandidateError( QUERY_VECTOR_MISSING, f"the cached vector for {vs.query_key( text )[ :12 ]} was made under another set" )
        return vectors
    return read


def render_all_arms_page( result, redactable ):
    """
    Build the results page for a run_all_arms result.

    Requires:
        - result is run_all_arms's dict, with every arm measured for the page to be complete
        - redactable is arm_report.count_redactable's result

    Ensures:
        - returns the page text: the shared report, then the fusion selection, the entry counts and the empty-purpose finding
        - the replay column is the verdict replay at K=128, and the page says so
        - a run that fused no vector list says the vector choice and the fusion selection were not made

    Raises:
        - CandidateError REPORT_META_MISSING from arm_report.render_report
    """
    measured = result[ "measured" ]
    t1 = { arm: measured[ arm ][ "t1_first" ] for arm in measured }
    t2 = { arm: measured[ arm ][ "t2" ][ "K=128" ] for arm in measured }
    page = ar.render_report( result[ "meta" ], t1, result[ "t3" ], t2, ( f"{result[ 'vectors_choice' ]} by the rule, which keeps B1 unless B2 beats it on recall at K=128 or on median twin rank, so a tie is B1" if result[ "vectors_choice" ] else "not decided: no vector arm was measured" ),
                             result[ "fusion" ], redactable )
    lines = [ "", "## Fusion constants chosen on the in-sample needs", "" ]
    if result[ "recall_by_params" ]:
        lines += [ f"Chosen by arms.select_fusion on {SELECTION_ARM} recall at K={SELECTION_K}, repeat-1 reference. Ties go to the smaller k, then depth, then head.", "",
                   "| k | depth | head | recall |", "|---|---|---|---|" ]
        lines += [ f"| {k[ 0 ]} | {k[ 1 ]} | {k[ 2 ]} | {ar.percent( v )} |" for k, v in sorted( result[ "recall_by_params" ].items() ) ]
    else:
        lines += [ "Not selected: no vector arm was measured, so the module defaults were used for every arm." ]
    lines += [ "", "## Entries and purpose lines", "",
               f"- The snapshot holds {result[ 'snapshot_entries' ]} sendable entries; the vector set holds rows for {result[ 'vector_entries' ]} of them.",
               f"- {result[ 'empty_purpose_entries' ]} snapshot entries carry an empty purpose line; {len( result[ 'empty_purpose_in_references' ] )} of them are in any need's reference.",
               f"- Capability pages offered to the wiki list: {result[ 'pages' ]}.",
               f"- Cached judge answers missing for the snapshot: {result[ 'misses' ]}.",
               "- The replay column is the verdict replay at K=128; the control row of each arm is in the run's JSON." ]
    return page + "\n".join( lines ) + "\n"


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
