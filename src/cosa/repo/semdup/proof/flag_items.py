"""
Add the flag pairs an unofficial run owes labels for to the labelling run.

The original items, key rows and packet lines are never rewritten: the new ones are appended, and the result is checked before it replaces anything.
"""
import argparse
import hashlib
import json
import os
import pathlib

import cosa.utils.util as cu
from cosa.repo.labelling import packets as lb_packets
from cosa.repo.labelling import pair_labels as pl
from cosa.repo.semdup import frozen
from cosa.repo.semdup import config as cfg_mod
from cosa.repo.semdup.proof import label_prep, proof_cli, proof_run

FLAG_KIND    = "flag"
FLAG_STRATUM = "flag"
NEW_SUFFIX   = ".flags-new"


def sha_of( data ):
    """Return the sha256 hex digest of bytes."""
    return hashlib.sha256( data ).hexdigest()


def rows_sha( rows ):
    """Ensures: returns one sha256 over the sorted item ids and their rows."""
    return sha_of( json.dumps( [ [ i, rows[ i ] ] for i in sorted( rows ) ], sort_keys=True ).encode( "utf-8" ) )


def label_id_defs( pool ):
    """
    Index a proof pool's definitions by the id the labels use.

    Requires:
        - pool is proof_run.build_pool's result

    Ensures:
        - returns { label id: definition } where a monolith side the pool made over as new carries its original id, so item ids and key rows match the originals' kind
    """
    return { pool[ "canon" ][ d[ "id" ] ]: { **d, "id": pool[ "canon" ][ d[ "id" ] ] } for d in pool[ "defs" ] }


def owed_pairs( record_path ):
    """
    Read the pair keys an unofficial proof record says are owed labels.

    Requires:
        - record_path is a proof record proof_run wrote

    Ensures:
        - returns the sorted owed pair keys

    Raises:
        - ValueError if the record has no owed list or the list is empty
    """
    owed = json.loads( pathlib.Path( record_path ).read_text( encoding="utf-8" ) ).get( "owed" )
    if not owed: raise ValueError( f"{record_path} lists no owed pairs" )
    return sorted( owed )


def build_flag_items( owed, defs, rows, seed ):
    """
    Build the new items and key rows for the owed pairs.

    Requires:
        - owed are pair keys; defs is label_id_defs' map; rows is the key's { item id: row }

    Ensures:
        - returns [ { item, row } ] in owed order, each row carrying kind and stratum "flag"

    Raises:
        - ValueError naming every owed key already in the key, and every id the pool does not define
    """
    held    = { proof_run.label_key( r[ "a" ], r[ "b" ] ) for r in rows.values() }
    already = [ k for k in owed if k in held ]
    absent  = sorted( { i for k in owed for i in k.split( "|" ) } - set( defs ) )
    if already: raise ValueError( f"{len( already )} owed pairs are already in the key: {', '.join( already )}" )
    if absent: raise ValueError( f"{len( absent )} definitions of the owed pairs are not in the pool: {', '.join( absent )}" )
    made = [ label_prep.pair_item( *[ defs[ i ] for i in k.split( "|" ) ], seed ) for k in owed ]
    return [ { "item": m[ "item" ], "row": { **m[ "row" ], "kind": FLAG_KIND, "stratum": FLAG_STRATUM } } for m in made ]


def packet_lines( items, reviewer, seed, taken ):
    """Ensures: returns ( the new items' lines in this reviewer's order, their ids )."""
    order = lb_packets.seeded_order( [ lb_packets.blind_form( i ) for i in items ], f"{seed}|flags|{reviewer}", taken )
    return "".join( json.dumps( i, sort_keys=True ) + "\n" for i in order ), [ i[ "item_id" ] for i in order ]


def tail_state( data, new_ids ):
    """
    Say whether a packet already ends in the new items, left by an interrupted swap.

    Requires:
        - data is a packet's bytes; new_ids is the set of the new items' ids

    Ensures:
        - returns ( True, the bytes before the new items ) when the packet's last len( new_ids ) lines are the new items and nothing else
        - returns ( False, data ) when it holds none of them

    Raises:
        - ValueError if it holds some of them but not all, or all of them but not as its last lines
    """
    lines   = data.splitlines( keepends=True )
    present = { json.loads( line )[ "item_id" ] for line in lines }
    if not new_ids & present: return False, data
    tail = lines[ len( lines ) - len( new_ids ) : ]
    if not new_ids <= present or { json.loads( line )[ "item_id" ] for line in tail } != new_ids: raise ValueError( "a packet holds only some of the new items, or not as its last lines" )
    return True, b"".join( lines[ : len( lines ) - len( new_ids ) ] )


def stage( run_dir, owed, defs, reviewers, seed ):
    """
    Write the extended key and packets beside the originals and check them.

    Requires:
        - run_dir is a labelling run folder; reviewers are the two packet names

    Ensures:
        - writes <file>.flags-new beside the key and each packet that lacks the new items, leaving the originals as they were
        - a packet that already ends in the new items, left by a swap that was interrupted, is not staged again; the key is
        - returns { added, swaps, packets, key_new, recovered, before, after }; swaps is [ ( new path, old path ) ] with the key last; recovered lists the reviewers whose packet was already done; before and after hold the shas of the original rows and packet bytes
        - the new packet bytes begin with the old packet bytes, every original key row is the same row, and every packet line is in blind form

    Raises:
        - ValueError from build_flag_items, tail_state, for a packet that does not end in a newline, a labels file of the second reviewer, or a staged file that fails its check
    """
    run_dir, key_path = pathlib.Path( run_dir ), pathlib.Path( run_dir ) / proof_cli.KEY_DIR / proof_cli.KEY_FILE
    packets           = { r: lb_packets.packet_path( run_dir / proof_cli.PACKETS_DIR, r ) for r in reviewers }
    if pl.labels_path( packets[ reviewers[ 1 ] ] ).exists(): raise ValueError( f"{pl.labels_path( packets[ reviewers[ 1 ] ] )} exists; the second reviewer has started, so the items cannot be added" )
    key_text = key_path.read_text( encoding="utf-8" )
    key      = json.loads( key_text )
    if json.dumps( key, indent=2, sort_keys=True ) != key_text: raise ValueError( f"{key_path} is not in the form label_prep wrote; its rows cannot be proved unchanged" )
    built    = build_flag_items( owed, defs, key[ "items" ], key[ "seed" ] )
    items    = [ b[ "item" ] for b in built ]
    new_ids  = { i[ "item_id" ] for i in items }
    old, done = {}, set()
    for r, path in packets.items():
        data = path.read_bytes()
        if data and not data.endswith( b"\n" ): raise ValueError( f"{path} does not end in a newline" )
        finished, old[ r ] = tail_state( data, new_ids )
        if finished: done.add( r )
    taken, swaps, files = [], [], {}
    for r in reviewers:
        if r in done:
            files[ r ] = packets[ r ]
            taken.append( [ json.loads( line )[ "item_id" ] for line in packets[ r ].read_text( encoding="utf-8" ).splitlines() ][ -len( new_ids ) : ] )
            continue
        text, order = packet_lines( items, r, key[ "seed" ], taken )
        taken.append( order )
        files[ r ] = packets[ r ].with_name( packets[ r ].name + NEW_SUFFIX )
        files[ r ].write_bytes( old[ r ] + text.encode( "utf-8" ) )
        swaps.append( ( files[ r ], packets[ r ] ) )
    rows    = { **key[ "items" ], **{ b[ "item" ][ "item_id" ]: b[ "row" ] for b in built } }
    key_new = key_path.with_name( key_path.name + NEW_SUFFIX )
    key_new.write_text( json.dumps( { **key, "items": rows }, indent=2, sort_keys=True ), encoding="utf-8" )
    swaps.append( ( key_new, key_path ) )
    try:
        verify( files, key_new, old, key, len( built ) )
    except ValueError:
        discard( swaps )
        raise
    staged = json.loads( key_new.read_text( encoding="utf-8" ) )[ "items" ]
    return { "added": len( built ), "swaps": swaps, "packets": files, "key_new": key_new, "recovered": sorted( done ),
             "before": { "rows": rows_sha( key[ "items" ] ), **{ r: sha_of( d ) for r, d in old.items() } },
             "after": { "rows": rows_sha( { i: staged[ i ] for i in key[ "items" ] } ), **{ r: sha_of( files[ r ].read_bytes()[ : len( old[ r ] ) ] ) for r in reviewers } } }


def verify( packets, key_new, old, key, added ):
    """
    Check the staged files against the originals before any swap.

    Requires:
        - packets is { reviewer: the file holding that reviewer's extended packet }, staged or already swapped; key_new is the staged key; old is { reviewer: original packet bytes }; key is the original key

    Ensures:
        - returns None when each packet begins with its original bytes and adds the new items alone, in blind form, and the key keeps every original row and adds the new ones

    Raises:
        - ValueError naming the first check that fails
    """
    for r, data in old.items():
        got = packets[ r ].read_bytes()
        if not got.startswith( data ): raise ValueError( f"{packets[ r ]} does not begin with the original packet bytes" )
        added_lines = got[ len( data ) : ].decode( "utf-8" ).splitlines()
        if len( added_lines ) != added: raise ValueError( f"{packets[ r ]} adds {len( added_lines )} items, not {added}" )
        for line in added_lines: lb_packets.blind_form( json.loads( line ) )
    staged = json.loads( key_new.read_text( encoding="utf-8" ) )
    if any( staged[ "items" ].get( i ) != row for i, row in key[ "items" ].items() ): raise ValueError( "the staged key changed an original row" )
    if len( staged[ "items" ] ) != len( key[ "items" ] ) + added: raise ValueError( "the staged key does not hold the original rows plus the new ones" )
    if { k: v for k, v in staged.items() if k != "items" } != { k: v for k, v in key.items() if k != "items" }: raise ValueError( "the staged key changed a field outside its items" )


def swap( swaps ):
    """
    Replace each old file with its new one, in the order given.

    Requires:
        - swaps is [ ( new path, old path ) ] with the packets first and the key last

    Ensures:
        - the key is replaced only after every packet is, so a crash leaves packets that hold the new items and a key that does not, which a re-run finishes
    """
    for new, old in swaps: os.replace( new, old )


def discard( swaps ):
    """Ensures: the staged files are removed, so a refusal leaves the folder unchanged."""
    for new, _ in swaps: new.unlink( missing_ok=True )


def main( argv=None, make_parts=proof_cli.live_parts ):
    """
    Add the owed flag pairs of an unofficial proof record to the labelling run as new items.

    Requires:
        - argv holds --run-dir, --record (the unofficial proof record whose owed list names the pairs), optionally --parallel and --check

    Ensures:
        - stdout holds one JSON record; banners go to stderr
        - builds the pool as the proof builds it, so each definition is the one the proof judged
        - stages the extended key and both packets beside the originals, checks them, then swaps them in; --check stages and checks, then removes the staged files
        - the record carries the sha of the original key rows and of each original packet's bytes, before and after
        - returns 0

    Raises:
        - ValueError if the second reviewer has labels, an owed pair is already in the key, a definition is not in the pool, or a staged file fails its check
    """
    return proof_cli.json_stdout( lambda out: _main( argv, make_parts, out ) )


def _main( argv, make_parts, out ):
    """Do main's work, printing the JSON record to out."""
    parser = argparse.ArgumentParser( description="Add the owed flag pairs of an unofficial proof record to the labelling run." )
    parser.add_argument( "--run-dir", required=True )
    parser.add_argument( "--record", required=True )
    parser.add_argument( "--parallel", type=int, default=proof_cli.DEFAULT_PARALLEL )
    parser.add_argument( "--check", action="store_true" )
    args   = parser.parse_args( argv )
    cfg    = cfg_mod.verify_frozen( frozen.frozen_path(), frozen.live_config() )
    run    = proof_cli.load_run( args.run_dir )
    if run[ "config_sha" ] != cfg[ "config_sha" ]: raise ValueError( f"the run was planted under config {run[ 'config_sha' ]}, the frozen one is {cfg[ 'config_sha' ]}" )
    parts  = make_parts( cu.get_project_root(), pathlib.Path( args.run_dir ), cfg, args.parallel )
    spec   = proof_cli.build_spec( parts[ "run" ], parts[ "mono_defs" ], parts[ "distractors" ], {}, [] )
    owed   = owed_pairs( args.record )
    staged = stage( args.run_dir, owed, label_id_defs( proof_run.build_pool( spec, spec[ "seed" ] ) ), label_prep.REVIEWERS, run[ "seed" ] )
    ( discard if args.check else swap )( staged[ "swaps" ] )
    print( json.dumps( { "status": "checked" if args.check else "added", "added": staged[ "added" ], "recovered": staged[ "recovered" ], "reviewers": list( label_prep.REVIEWERS ),
                         "original_bytes_sha_before": staged[ "before" ], "original_bytes_sha_after": staged[ "after" ] }, indent=2, sort_keys=True ), file=out )
    return 0


if __name__ == "__main__":  # pragma: no cover - the command's entry; main is tested directly
    raise SystemExit( main() )
