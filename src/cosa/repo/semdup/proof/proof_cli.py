"""
The proof's command: build proof_run's inputs from a run folder, then check or run.

The spec and the wiring come from the run folder and the tree; --check stops before any model call.
"""
import argparse
import functools
import json
import pathlib
import shutil
import tempfile
import time

import cosa.utils.util as cu
from cosa.repo.doc_lint import harness_runner, model_transport
from cosa.repo.labelling import packets as lb_packets
from cosa.repo.semdup import blind, extract, frozen, judge, structural
from cosa.repo.semdup import config as cfg_mod
from cosa.repo.semdup.proof import label_load, label_prep, proof_run
from cosa.repo.symindex import spec as sp

KEY_DIR          = "key"
PLANTED_FILE     = "planted.json"
KEY_FILE         = "answer-key.json"
PACKETS_DIR      = "packets"
REWRITES_DIR     = "rewrites"
VECTORS_DIR      = "vectors"
TREE_PREFIX      = "tree"
NEW_PREFIX       = "proof-new"
DATA_RELATIVE    = "/io"
LEDGER_NAME      = "judge-ledger.jsonl"
DEFAULT_PARALLEL = 4


def load_run( run_dir ):
    """
    Read the planted pairs and the answer key of a labelling run folder.

    Requires:
        - run_dir holds key/planted.json and key/answer-key.json as label_prep wrote them

    Ensures:
        - returns { planted, items, seed, monolith_blob, config_sha }; planted is the list of { original, rewrite, stratum }
    """
    key_dir = pathlib.Path( run_dir ) / KEY_DIR
    planted = json.loads( ( key_dir / PLANTED_FILE ).read_text( encoding="utf-8" ) )[ "planted" ]
    key     = json.loads( ( key_dir / KEY_FILE ).read_text( encoding="utf-8" ) )
    return { "planted": planted, "items": key[ "items" ], "seed": key[ "seed" ], "monolith_blob": key[ "monolith_blob" ], "config_sha": key[ "config_sha" ] }


def monolith_spec( items, mono_defs ):
    """
    Turn the answer key's monolith items into proof_run's monolith pairs.

    Requires:
        - items is the key's { item id: { a, b, kind, stratum } }; a monolith stratum reads "monolith:<source>"
        - mono_defs are the monolith's definitions as label_prep.monolith_definitions gives them

    Ensures:
        - returns [ { ids, source } ] for every monolith item, sorted by ids

    Raises:
        - ValueError naming the ids the pinned monolith does not define
    """
    pairs   = sorted( ( { "ids": sorted( ( r[ "a" ], r[ "b" ] ) ), "source": r[ "stratum" ].split( ":", 1 )[ 1 ] } for r in items.values() if r[ "kind" ] == "monolith" ),
                      key=lambda p: p[ "ids" ] )
    known   = { d[ "id" ] for d in mono_defs }
    missing = sorted( { i for p in pairs for i in p[ "ids" ] } - known )
    if missing: raise ValueError( f"the pinned monolith does not define {', '.join( missing )}" )
    return pairs


def check_originals( planted, distractors ):
    """
    Refuse a tree whose code moved since the run was planted.

    Requires:
        - distractors are the server-origin definitions of the tree now

    Ensures:
        - returns None when every planted original is still a definition of the tree, byte for byte

    Raises:
        - ValueError naming the originals whose id is no longer in the tree
    """
    now   = { d[ "id" ] for d in distractors }
    stale = sorted( f"{p[ 'original' ][ 'file' ]}#{p[ 'original' ][ 'name' ]}" for p in planted if p[ "original" ][ "id" ] not in now )
    if stale: raise ValueError( f"{len( stale )} planted originals changed since the run was planted: {', '.join( stale )}" )


def plant_failures( planted, first, second ):
    """
    Name the planted pairs both reviewers ruled not the same job.

    Requires:
        - first and second are the two reviewers' { pair key: bool } from label_load.pair_key_labels

    Ensures:
        - returns the sorted pair keys of planted pairs that both reviewers labelled False; a pair either has not labelled is not one
    """
    keys = [ proof_run.label_key( p[ "rewrite" ][ "id" ], p[ "original" ][ "id" ] ) for p in planted ]
    return sorted( k for k in keys if first.get( k ) is False and second.get( k ) is False )


def rewrite_sources( run_dir, planted ):
    """
    Find the file each rewrite was written to.

    Requires:
        - label_prep wrote the i-th planted rewrite under key/rewrites/<i as three digits>/<the rewrite's file>

    Ensures:
        - returns { rewrite id: ( folder name, absolute path ) }

    Raises:
        - FileNotFoundError naming a rewrite whose file is missing
    """
    out = {}
    for i, p in enumerate( planted ):
        folder = f"{i:03d}"
        path   = ( pathlib.Path( run_dir ) / KEY_DIR / REWRITES_DIR / folder / p[ "rewrite" ][ "file" ] ).resolve()
        if not path.is_file(): raise FileNotFoundError( f"rewrite {p[ 'rewrite' ][ 'id' ]} has no file at {path}" )
        out[ p[ "rewrite" ][ "id" ] ] = ( folder, path )
    return out


def staged_name( d, rewrites ):
    """
    Return where a definition's file sits in the staged tree.

    Ensures:
        - a rewrite sits under proof-new/<folder>/, everything else under tree/
    """
    if d[ "id" ] in rewrites: return f"{NEW_PREFIX}/{rewrites[ d[ 'id' ] ][ 0 ]}/{d[ 'file' ]}"
    return f"{TREE_PREFIX}/{d[ 'file' ]}"


def stage_pool( root, defs, rewrites ):
    """
    Copy the file of every definition of the pool into one temporary tree.

    Requires:
        - root is the repository root the server and monolith definitions are relative to; rewrites is as rewrite_sources gives it

    Ensures:
        - returns ( TemporaryDirectory, { ( staged file, line, end_line ): pool id } )
        - the key leaves the name out: a class-member rewrite is recorded by its member name, and extraction names it Class.member
        - a rewrite and its original keep apart, because the rewrite is staged under proof-new/ and the original under tree/
        - the staged root holds no src/ folder of its own, so symindex treats it as a plain tree and names modules from it
    """
    tmp, where = tempfile.TemporaryDirectory(), {}
    for d in defs:
        rel = staged_name( d, rewrites )
        dst = pathlib.Path( tmp.name ) / rel
        if not dst.exists():
            dst.parent.mkdir( parents=True, exist_ok=True )
            shutil.copyfile( rewrites[ d[ "id" ] ][ 1 ] if d[ "id" ] in rewrites else pathlib.Path( root ) / d[ "file" ], dst )
        where[ ( rel, d[ "line" ], d[ "end_line" ] ) ] = d[ "id" ]
    return tmp, where


def check_found( where, found, defs, min_nodes ):
    """
    Refuse a staged tree that lost a pool definition.

    Requires:
        - where is stage_pool's map; found is the set of ( file, line, end_line ) the staged extraction returned

    Ensures:
        - returns None when every pool definition of min_nodes nodes or more was found

    Raises:
        - ValueError naming the pool definitions of min_nodes nodes or more the staged extraction did not find, since their clones would be lost unseen
    """
    big  = { d[ "id" ] for d in defs if d[ "nodes" ] >= min_nodes }
    lost = sorted( pid for k, pid in where.items() if k not in found and pid in big )
    if lost: raise ValueError( f"{len( lost )} pool definitions were not found in the staged tree: {', '.join( lost )}" )


def staged_pairs( root, defs, rewrites, cfg, jscpd=structural.run_jscpd ):
    """
    Find the structural clone pairs of a whole pool by staging it as one tree.

    Requires:
        - defs are the pool's definitions, as judge_all hands them to structural_pairs; cfg is the frozen configuration
        - jscpd is structural.run_jscpd unless a test stands in for it

    Ensures:
        - runs jscpd over the staged script files, and dups over the staged Python and script files, once each, and merges them with clone_pairs
        - dups gets every staged definition, not only those of min_nodes nodes or more, because it numbers a repeated name ~2 before its own cut
        - returns those pairs with each id mapped back to its pool id; a pair touching a staged definition the pool does not hold is left out

    Raises:
        - ValueError naming the pool definitions of min_nodes nodes or more the staged extraction did not find, since their clones would be lost unseen
    """
    tmp, where = stage_pool( root, defs, rewrites )
    with tmp:
        base   = pathlib.Path( tmp.name )
        files  = sorted( { rel for rel, _, _ in where } )
        paths  = [ base / f for f in files ]
        every  = extract.extract_tree( tmp.name, paths, "server" )[ "definitions" ]
        staged = [ d for d in every if d[ "nodes" ] >= cfg[ "min_nodes" ] ]
        found  = { ( d[ "file" ], d[ "line" ], d[ "end_line" ] ) for d in staged }
        check_found( where, found, defs, cfg[ "min_nodes" ] )
        spec   = sp.spec_for( tmp.name )
        py     = [ d for d in every if d[ "file" ].endswith( ".py" ) ]
        js     = [ d for d in staged if d[ "file" ].endswith( extract.SCRIPT_SUFFIXES ) ]
        js_all = [ d for d in every if d[ "file" ].endswith( extract.SCRIPT_SUFFIXES ) ]
        py_at  = [ p for p in paths if p.name.endswith( ".py" ) ]
        js_at  = [ p for p in paths if p.name.endswith( extract.SCRIPT_SUFFIXES ) ]
        merged = structural.clone_pairs( structural.parse_jscpd( jscpd( tmp.name, [ TREE_PREFIX, NEW_PREFIX ], cfg ), js, cfg[ "clone_cover" ] ),
                                         structural.python_clones( spec, py_at, py, cfg[ "min_nodes" ] ),
                                         structural.script_clones( spec, js_at, js_all, cfg[ "min_nodes" ] ) )
    to_pool = { d[ "id" ]: where.get( ( d[ "file" ], d[ "line" ], d[ "end_line" ] ) ) for d in every }
    out     = []
    for p in merged:
        ids = [ to_pool[ i ] for i in p[ "ids" ] ]
        if None not in ids: out.append( { **p, "ids": sorted( ids ) } )
    return out


def structural_source( root, rewrites, cfg, jscpd=structural.run_jscpd ):
    """
    Give judge_all its structural_pairs callable for the proof pool.

    Ensures:
        - returns a callable taking the pool's definitions and returning staged_pairs for them
        - a second call with the same definition ids, as the second slot makes, returns the first answer without staging again
    """
    cache = {}
    def pairs( defs ):
        """Return the staged clone pairs of these definitions, computed once per set of ids."""
        key = tuple( sorted( d[ "id" ] for d in defs ) )
        if key not in cache: cache[ key ] = staged_pairs( root, defs, rewrites, cfg, jscpd )
        return cache[ key ]
    return pairs


def build_spec( run, mono_defs, distractors, labels, failures ):
    """
    Assemble the spec proof_run takes.

    Requires:
        - run is load_run's result; labels is { pair key: bool }; failures is plant_failures' list

    Ensures:
        - returns { planted, monolith_defs, monolith_pairs, distractors, seed, labels, plant_failures }, the seed being the key's

    Raises:
        - ValueError from monolith_spec or check_originals
    """
    check_originals( run[ "planted" ], distractors )
    return { "planted": run[ "planted" ], "monolith_defs": mono_defs, "monolith_pairs": monolith_spec( run[ "items" ], mono_defs ),
             "distractors": distractors, "seed": run[ "seed" ], "labels": labels, "plant_failures": failures }


def label_state( labels_paths, key_path, rulings, third_path=None ):
    """
    Read the reviewers' labels and say whether the proof can use them.

    Requires:
        - labels_paths is a list of zero, one or two labels files; rulings is None or { pair key: bool }
        - third_path is None or the third rater's labels file, read only when there are two files

    Ensures:
        - returns { counts, labels, failures, owed }: counts per file; labels is resolved_labels' dict, or None with the reason in owed
        - failures is plant_failures' list when there are two files, else []
    """
    run      = load_run( pathlib.Path( key_path ).parent.parent )
    each     = [ label_load.pair_key_labels( p, key_path ) for p in labels_paths ]
    counts   = { str( p ): len( e ) for p, e in zip( labels_paths, each ) }
    if len( each ) != 2: return { "counts": counts, "labels": None, "failures": [], "owed": f"two reviewers' labels files are needed, {len( each )} given" }
    failures = plant_failures( run[ "planted" ], each[ 0 ], each[ 1 ] )
    try:
        labels = label_load.resolved_labels( labels_paths[ 0 ], labels_paths[ 1 ], key_path, rulings, third_path )
    except ValueError as e:
        return { "counts": counts, "labels": None, "failures": failures, "owed": str( e ) }
    return { "counts": counts, "labels": labels, "failures": failures, "owed": None }


def unofficial_state( labels_paths, key_path ):
    """
    Read one reviewer's labels for an unofficial run.

    Requires:
        - labels_paths is a list of labels files; key_path is the run's answer key

    Ensures:
        - returns label_state's shape; with exactly one file, labels is that reviewer's { pair key: bool } and failures the planted pairs it labels False
        - with any other number of files, labels is None and owed says one is needed
    """
    if len( labels_paths ) != 1:
        return { "counts": {}, "labels": None, "failures": [], "owed": f"an unofficial run takes exactly one labels file, {len( labels_paths )} given" }
    labels = label_load.pair_key_labels( labels_paths[ 0 ], key_path )
    run    = load_run( pathlib.Path( key_path ).parent.parent )
    return { "counts": { str( labels_paths[ 0 ] ): len( labels ) }, "labels": labels, "failures": plant_failures( run[ "planted" ], labels, labels ), "owed": None }


def live_parts( root, run_dir, cfg, parallel, prep_wiring=label_prep.live_wiring, monolith=label_prep.monolith_definitions, jscpd=structural.run_jscpd ):
    """
    Build everything the proof needs from the real tree, short of the labels.

    Requires:
        - root is the repository root; run_dir the labelling run folder; cfg the verified frozen configuration
        - prep_wiring, monolith and jscpd are label_prep's and structural's own unless a test stands in for them

    Ensures:
        - returns { run, mono_defs, distractors, wiring }; wiring holds every key judge_all and proof_run read except labels, which live in the spec, and ledger, which proof_ledger makes on a real run
        - the distractors are label_prep's server and client definitions
        - writes nothing: no folder, no ledger
    """
    run       = load_run( run_dir )
    prep      = prep_wiring( root, pathlib.Path( run_dir ) / VECTORS_DIR )
    tmp, mono = monolith( root, cfg[ "min_nodes" ] )
    tmp.cleanup()
    data_dir  = cu.get_project_root() + DATA_RELATIVE
    wiring    = { "client": prep[ "client" ], "cache_dir": pathlib.Path( run_dir ) / VECTORS_DIR, "scrub": blind.scrub_tokens( frozen.ARM_LABELS ),
                  "structural_pairs": structural_source( root, rewrite_sources( run_dir, run[ "planted" ] ), cfg, jscpd ), "backend": judge.MaxPlanBackend(),
                  "parallel": parallel, "frozen_path": frozen.frozen_path(),
                  "live": frozen.live_config(), "data_dir": data_dir, "clock": lambda: time.strftime( "%Y-%m-%dT%H:%M:%S%z" ) }
    return { "run": run, "mono_defs": mono, "distractors": [ *prep[ "server_defs" ], *prep[ "client_defs" ] ], "wiring": wiring }


def proof_ledger( data_dir, cli_path, backend, folder=proof_run.PROOF_FOLDER ):
    """
    Make the proof's judge ledger, bound to the Claude Code binary.

    Requires:
        - data_dir is the data root the proof records live under; cli_path is the Claude Code binary; backend is the judge backend
        - folder is the record folder under data_dir, the proof's own unless an unofficial run names its own

    Ensures:
        - creates the proof folder if it is missing, which is why only a real run calls this
        - returns the ledger at <proof folder>/judge-ledger.jsonl, bound as judge.ledger_binding binds it: binary, version, backend and server
    """
    folder = pathlib.Path( data_dir ).joinpath( *folder )
    folder.mkdir( parents=True, exist_ok=True )
    return harness_runner.Ledger( folder / LEDGER_NAME, binding=judge.ledger_binding( f"claude_cli={cli_path}|version={model_transport.cli_version( cli_path )}", backend ) )


def main( argv=None, make_parts=live_parts, run_proof=proof_run.proof_run ):
    """
    Check the proof's inputs, or run the proof once.

    Requires:
        - argv holds --run-dir, up to two --labels files, optionally --rulings (a JSON file of { pair key: bool }), --third-labels,
          --export-third, --unofficial, --parallel, --claude-cli-path and --check

    Ensures:
        - verifies the frozen configuration first and refuses a run folder planted under another config_sha
        - with --export-third <reviewer>: needs two --labels files; writes that reviewer's blind packet of the disputed items beside the others,
          prints its path and size as JSON and returns 0; makes no model call
        - with --unofficial: takes exactly one --labels file and runs proof_run unofficially, with its own judge ledger in the unofficial folder;
          refuses --rulings and --third-labels
        - with --check: builds the spec and the wiring, computes the structural pairs of the pool once, prints the sizes and the label state as JSON,
          makes no model call and writes nothing, not even the proof folder or the ledger; returns 0
        - without --check: refuses (returns 2, after printing why) unless both reviewers' labels resolve and --claude-cli-path is given; otherwise runs proof_run once,
          prints its record and returns 0

    Raises:
        - SemdupError CONFIG_DRIFT if the live configuration is not the frozen one
        - ValueError if the run folder was planted under another configuration, from build_spec, or for --unofficial with --rulings or --third-labels
    """
    parser = argparse.ArgumentParser( description="Check or run the Phase 2 semantic duplicate proof." )
    parser.add_argument( "--run-dir", required=True )
    parser.add_argument( "--labels", action="append", default=[] )
    parser.add_argument( "--rulings", default=None )
    parser.add_argument( "--third-labels", default=None )
    parser.add_argument( "--export-third", default=None )
    parser.add_argument( "--parallel", type=int, default=DEFAULT_PARALLEL )
    parser.add_argument( "--claude-cli-path", default=None )
    parser.add_argument( "--check", action="store_true" )
    parser.add_argument( "--unofficial", action="store_true" )
    args    = parser.parse_args( argv )
    model_transport.configure( args.claude_cli_path )
    cfg     = cfg_mod.verify_frozen( frozen.frozen_path(), frozen.live_config() )
    run_dir = pathlib.Path( args.run_dir )
    key_sha = load_run( run_dir )[ "config_sha" ]
    if key_sha != cfg[ "config_sha" ]: raise ValueError( f"the run was planted under config {key_sha}, the frozen one is {cfg[ 'config_sha' ]}" )
    if args.export_third is not None:
        if len( args.labels ) != 2: raise ValueError( "--export-third needs both reviewers' --labels files" )
        items = label_load.disputed_items( *args.labels )
        path  = lb_packets.export_subset_packet( run_dir / PACKETS_DIR, items, args.export_third, load_run( run_dir )[ "seed" ] )
        print( json.dumps( { "status": "exported", "packet": str( path ), "items": len( items ) }, indent=2, sort_keys=True ) )
        return 0
    if args.unofficial and ( args.rulings is not None or args.third_labels is not None ):
        raise ValueError( "--unofficial takes one reviewer's labels only, so --rulings and --third-labels do not apply" )
    rulings = json.loads( pathlib.Path( args.rulings ).read_text( encoding="utf-8" ) ) if args.rulings is not None else None
    key     = run_dir / KEY_DIR / KEY_FILE
    state   = unofficial_state( args.labels, key ) if args.unofficial else label_state( args.labels, key, rulings, args.third_labels )
    if not args.check and state[ "labels" ] is None:
        print( json.dumps( { "status": "refused", "owed": state[ "owed" ], "counts": state[ "counts" ] }, indent=2, sort_keys=True ) )
        return 2
    if not args.check and args.claude_cli_path is None:
        print( json.dumps( { "status": "refused", "owed": "a real run needs --claude-cli-path, because the ledger is bound to that binary", "counts": state[ "counts" ] }, indent=2, sort_keys=True ) )
        return 2
    parts   = make_parts( cu.get_project_root(), run_dir, cfg, args.parallel )
    spec    = build_spec( parts[ "run" ], parts[ "mono_defs" ], parts[ "distractors" ], state[ "labels" ] or {}, state[ "failures" ] )
    if args.check:
        pool  = proof_run.build_pool( spec, spec[ "seed" ] )
        pairs = parts[ "wiring" ][ "structural_pairs" ]( pool[ "defs" ] )
        print( json.dumps( { "status": "checked", "pool": pool[ "sizes" ], "planted": len( spec[ "planted" ] ), "monolith_pairs": len( spec[ "monolith_pairs" ] ),
                             "structural_pairs": len( pairs ), "labels": state[ "counts" ], "owed": state[ "owed" ], "plant_failures": len( state[ "failures" ] ),
                             "config_sha": cfg[ "config_sha" ] }, indent=2, sort_keys=True ) )
        return 0
    folder = proof_run.UNOFFICIAL_FOLDER if args.unofficial else proof_run.PROOF_FOLDER
    run    = functools.partial( run_proof, unofficial=True ) if args.unofficial else run_proof
    record = run( spec, { **parts[ "wiring" ], "ledger": proof_ledger( parts[ "wiring" ][ "data_dir" ], args.claude_cli_path, parts[ "wiring" ][ "backend" ], folder ) } )
    print( json.dumps( record, indent=2, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - the command's entry; main is tested directly
    raise SystemExit( main() )
