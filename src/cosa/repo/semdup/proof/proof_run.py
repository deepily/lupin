"""The proof run: judge the pool twice, compare with the labels and the bar, keep the record."""
import json
import os
import pathlib
import random

from cosa.repo.semdup import cluster, errors as err, extract, pipeline
from cosa.repo.semdup import config as cfg_mod
from cosa.repo.semdup.proof import proof_bar

PROOF_FOLDER = ( "semdup", "proof" )
LEDGER_FILE  = "proof-ledger.jsonl"
SLOTS        = ( 0, 1 )


def pair_key( a, b ):
    """Return the key of an unordered pair of definition ids."""
    return "|".join( sorted( ( a, b ) ) )


def resolve_label( first, second, ruling=None ):
    """
    Settle one pair's label from the two reviewers.

    Requires:
        - first and second are the reviewers' booleans, True for a true duplicate
        - ruling is None, or the boolean call made on a disagreement

    Ensures:
        - returns True only when both say true; returns False when both say false
        - on a disagreement returns the ruling

    Raises:
        - ValueError if the reviewers disagree and no ruling was given
    """
    if first == second: return first
    if ruling is None: raise ValueError( "the two reviewers disagree and no ruling was given" )
    return ruling


def _as_new( d ):
    """Return a definition made over as a new one, with the id that origin gives."""
    return { **d, "origin": "new", "id": extract.definition_id( "new", d[ "file" ], d[ "name" ], d[ "text" ] ) }


def build_pool( spec, seed ):
    """
    Assemble the closed pool the proof judges.

    Requires:
        - spec holds planted ( { original, rewrite, stratum } ), monolith_defs, monolith_pairs ( { ids, source } ) and distractors
        - originals, monolith definitions and distractors are server-origin; rewrites are new-origin

    Ensures:
        - returns { defs, new, canon, sizes }: every definition once, the new ones (the rewrites and one side of each monolith pair, drawn by seed),
          and canon, which maps a pool id back to the id the labels use
        - everything that is not a rewrite or a chosen monolith side is server-origin
        - the same seed and spec give the same pool whatever order the lists arrive in
    """
    rng       = random.Random( seed )
    chosen    = { rng.choice( sorted( p[ "ids" ] ) ) for p in sorted( spec[ "monolith_pairs" ], key=lambda p: sorted( p[ "ids" ] ) ) }
    server    = { d[ "id" ]: d for d in [ *( p[ "original" ] for p in spec[ "planted" ] ), *spec[ "monolith_defs" ], *spec[ "distractors" ] ] }
    canon, new = {}, []
    for p in spec[ "planted" ]:
        new.append( p[ "rewrite" ] )
        canon[ p[ "rewrite" ][ "id" ] ] = p[ "rewrite" ][ "id" ]
    for old_id in sorted( chosen ):
        made = _as_new( server.pop( old_id ) )
        new.append( made )
        canon[ made[ "id" ] ] = old_id
    for i in server: canon[ i ] = i
    defs = sorted( [ *new, *server.values() ], key=lambda d: d[ "id" ] )
    return { "defs": defs, "new": sorted( new, key=lambda d: d[ "id" ] ), "canon": canon,
             "sizes": { "size": len( defs ), "new": len( new ), "server": len( server ), "distractors": len( spec[ "distractors" ] ) } }


def next_number( folder ):
    """Return the number of the next proof record in the folder, counting from 1."""
    taken = [ int( p.stem ) for p in pathlib.Path( folder ).glob( "*.json" ) if p.stem.isdigit() ]
    return max( taken, default=0 ) + 1


def append_ledger( path, entry ):
    """
    Add one line to the proof ledger without touching what is there.

    Requires:
        - entry is a JSON-serialisable dict

    Ensures:
        - the file is opened for append only and the line is on disk before this returns
    """
    with open( path, "a", encoding="utf-8" ) as f:
        f.write( json.dumps( entry, sort_keys=True ) + "\n" )
        f.flush()
        os.fsync( f.fileno() )


def _flags( outcome, canon ):
    """Return the set of pair keys one pass flagged, in the ids the labels use."""
    return { pair_key( canon[ a ], canon[ b ] ) for a, b in cluster.join_pairs( outcome[ "verdicts" ] ) }


def proof_run( spec, wiring ):
    """
    Run the proof once and keep its record, whatever the result.

    Requires:
        - spec is as build_pool needs, plus seed, labels ( { pair key: bool } ) and plant_failures ( pair keys both reviewers ruled not equivalent )
        - wiring is as pipeline.judge_all needs, plus frozen_path, live, data_dir and clock ( a callable giving the time as text )

    Ensures:
        - verifies the frozen configuration, judges the pool in slot 0 and slot 1 with the same configuration, and writes <data>/semdup/proof/<n>.json once
        - appends one line to proof-ledger.jsonl with the config_sha and the status, for a pass and for every other result alike
        - status is "complete" with the bar figures, "incomplete" when a definition is unjudged, "labels_pending" with the pairs the reviewers still owe,
          or "no_flags" when the checker raised none
        - found, correct and the strata come from slot 0; agreement compares the two slots; slot 1's found count is reported beside slot 0's
        - a planted pair in plant_failures is left out of every denominator and counted, with its rate
        - the record carries the pool size

    Raises:
        - SemdupError CONFIG_DRIFT if the live configuration is not the frozen one
    """
    cfg      = cfg_mod.verify_frozen( wiring[ "frozen_path" ], wiring[ "live" ] )
    pool     = build_pool( spec, spec[ "seed" ] )
    passes   = [ pipeline.judge_all( pool[ "new" ], pool[ "defs" ], cfg, wiring, slot ) for slot in SLOTS ]
    folder   = pathlib.Path( wiring[ "data_dir" ] ).joinpath( *PROOF_FOLDER )
    folder.mkdir( parents=True, exist_ok=True )
    failures = set( spec[ "plant_failures" ] )
    known    = {}
    for p in spec[ "planted" ]:
        key = pair_key( p[ "rewrite" ][ "id" ], p[ "original" ][ "id" ] )
        if key not in failures: known[ key ] = p[ "stratum" ]
    for p in spec[ "monolith_pairs" ]: known[ pair_key( *p[ "ids" ] ) ] = f"monolith:{p[ 'source' ]}"
    flags    = [ _flags( outcome, pool[ "canon" ] ) - failures for outcome in passes ]
    labels   = spec[ "labels" ]
    record   = { "config_sha": cfg[ "config_sha" ], "pool": pool[ "sizes" ], "plant_failures": { "count": len( failures ), "of": len( spec[ "planted" ] ),
                 "rate": len( failures ) / len( spec[ "planted" ] ) if spec[ "planted" ] else None, "pairs": sorted( failures ) },
                 "unjudged": [ outcome[ "unjudged" ] for outcome in passes ] }
    owed     = sorted( ( set( known ) | flags[ 0 ] ) - set( labels ) )
    true     = sorted( k for k in known if labels.get( k ) is True )
    record[ "agreement" ] = proof_bar.agreement( passes[ 0 ][ "verdicts" ], passes[ 1 ][ "verdicts" ] )
    if any( record[ "unjudged" ] ):
        record[ "status" ] = "incomplete"
    elif owed:
        record.update( status="labels_pending", owed=owed )
    else:
        counts = { "true_pairs": len( true ), "found": len( set( true ) & flags[ 0 ] ), "flags": len( flags[ 0 ] ), "correct": sum( 1 for k in flags[ 0 ] if labels[ k ] ),
                   "both": record[ "agreement" ][ "pairs_in_both" ], "agree": record[ "agreement" ][ "flag_agree" ] }
        record.update( counts=counts, found_in_slot_1=len( set( true ) & flags[ 1 ] ),
                       strata=proof_bar.stratum_rates( [ { "stratum": known[ k ], "found": k in flags[ 0 ] } for k in true ] ) )
        try:
            record.update( status="complete", bar=proof_bar.evaluate_bar( counts ) )
        except err.SemdupError as e:
            if e.code != err.NO_FLAGS: raise
            record.update( status="no_flags", bar=None, detail=e.detail )
    number = next_number( folder )
    record[ "proof" ] = number
    with open( folder / f"{number}.json", "x", encoding="utf-8" ) as f: json.dump( record, f, indent=2, sort_keys=True )
    passed = record[ "bar" ][ "passed" ] if record[ "status" ] == "complete" else None
    append_ledger( folder / LEDGER_FILE, { "proof": number, "config_sha": cfg[ "config_sha" ], "status": record[ "status" ], "passed": passed, "time": wiring[ "clock" ]() } )
    return record
