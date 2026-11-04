"""
Choosing the probe entry and composing the six probe packs for the live measurement.

The probe is a boundary entry from the first single run. It is asked about inside a pack of 200.
It goes first, in the middle and last, once among random neighbours and once among its closest by words.
The plan records the seed, the probe and both neighbour lists, and is written once.
Nothing here sends anything.
"""
import json
import os
import random
import re

from lupin_mcp import reuse_tools as rt

BAND           = ( 0.35, 0.65 )
TARGET         = 0.5
PACK_SIZE      = 200
NEIGHBOURS     = PACK_SIZE - 1
POSITIONS      = { "first": 0, "middle": PACK_SIZE // 2, "last": PACK_SIZE - 1 }
SEED_BASE      = 20261007                                       # the random seed of question k is this plus k (ruling R6)
QUESTIONS      = ( 1, 2, 3, 4 )
NEIGHBOUR_RULE = "jaccard-word-tokens-v1"                       # a changed rule needs a new name, so a plan says which one it used
WORD           = re.compile( r"[a-z0-9]+" )


class ProbeNotFound( ValueError ):
    """No clean entry of the first single run lies in the boundary band."""


def overlap_of( probabilities ):
    """Ensures: returns the answer's overlap, reuse plus extend."""
    return probabilities[ "reuse" ] + probabilities[ "extend" ]


def choose_probe( record ):
    """
    Pick the probe from a first single run's results record.

    Requires:
        - record is a results record of the arm single1
    Ensures:
        - returns the id of the clean entry whose overlap is in the band and nearest one half; ties go to the lowest id
        - an entry that is failed, unasked or not reached is never chosen
    Raises:
        - ValueError for a record that is not from single1
        - ProbeNotFound when no clean entry lies in the band
    """
    if record.get( "format" ) != "stage1-arm-1" or record.get( "arm" ) != "single1": raise ValueError( "a probe is chosen from a single1 results record" )
    lost  = set( record[ "failed" ] ) | set( record[ "unasked" ] ) | set( record[ "not_reached" ] )
    found = [ ( round( abs( overlap_of( a[ "probabilities" ] ) - TARGET ), 9 ), a[ "id" ] ) for a in record[ "answers" ]
              if a[ "id" ] not in lost and BAND[ 0 ] <= overlap_of( a[ "probabilities" ] ) <= BAND[ 1 ] ]
    if not found: raise ProbeNotFound( f"no clean entry has an overlap from {BAND[ 0 ]} to {BAND[ 1 ]}" )
    return min( found )[ 1 ]


def _others( entries, probe_id, count ):
    """Ensures: returns the other entries' ids, sorted; ValueError if fewer than `count`."""
    ids = [ e[ "id" ] for e in entries ]
    if len( set( ids ) ) != len( ids ): raise ValueError( "an id is repeated in the catalogue" )
    if probe_id not in ids: raise ValueError( f"probe {probe_id!r} is not in the catalogue" )
    others = sorted( i for i in ids if i != probe_id )
    if len( others ) < count: raise ValueError( f"{len( others )} other entries are too few for {count} neighbours" )
    return others


def random_neighbours( entries, probe_id, seed, count=NEIGHBOURS ):
    """
    Draw the random neighbours.

    Ensures:
        - returns `count` ids from the id-sorted others, by random.Random( seed ).sample, so a seed repeats the draw
    Raises:
        - ValueError for a seed that is not a whole number, a probe not in the catalogue, a repeated id, or too few entries
    """
    if type( seed ) is not int: raise ValueError( f"the seed must be a whole number so it can be recorded, got {seed!r}" )
    return random.Random( seed ).sample( _others( entries, probe_id, count ), count )


def jaccard( a, b ):
    """Ensures: returns the Jaccard score of two texts' lower-case word sets; 0 if both empty."""
    first, second = set( WORD.findall( a.lower() ) ), set( WORD.findall( b.lower() ) )
    return len( first & second ) / len( first | second ) if first | second else 0


def similar_neighbours( entries, probe_id, count=NEIGHBOURS ):
    """
    Pick the neighbours closest to the probe by words.

    Ensures:
        - returns the `count` ids with the highest word-token Jaccard to the probe's entry text, best first
        - ties go to the lowest id, so the set is the same on every run; no model and no seed
    Raises:
        - ValueError for a probe not in the catalogue, a repeated id, or too few entries
    """
    others = _others( entries, probe_id, count )
    by_id  = { e[ "id" ]: e for e in entries }
    mine   = rt.entry_text( by_id[ probe_id ] )
    ranked = sorted( others, key=lambda i: ( -jaccard( mine, rt.entry_text( by_id[ i ] ) ), i ) )
    return ranked[ :count ]


def seed_for( question ):
    """
    Give the random-neighbour seed of a question.

    Ensures:
        - returns 20261007 plus the question number, so no caller chooses a seed
    Raises:
        - ValueError for a question that is not 1 to 4
    """
    if type( question ) is not int or question not in QUESTIONS: raise ValueError( f"question must be one of {QUESTIONS}, got {question!r}" )
    return SEED_BASE + question


def build_probe_plan( entries, record ):
    """
    Compose the six probe packs and the plan that records how they were made.

    Requires:
        - entries are the catalogue the single runs were asked about; record is the first single run's results
    Ensures:
        - returns { plan, arms }; arms maps each probe arm name to { entries, probe } for run_arm
        - the random neighbours are drawn with the question's own seed; the plan takes no seed argument
        - the probe is the same in all six; each neighbour list is fixed across the three places
        - the probe sits at index 0, 100 and 199 of a pack of 200
        - plan holds the question, seed, probe id and overlap, band, target, rule and both neighbour id lists
    Raises:
        - ProbeNotFound, or ValueError from the helpers above
    """
    probe_id  = choose_probe( record )
    seed      = seed_for( record[ "question" ] )
    random_ids, near_ids = random_neighbours( entries, probe_id, seed ), similar_neighbours( entries, probe_id )
    by_id     = { e[ "id" ]: e for e in entries }
    overlap   = next( overlap_of( a[ "probabilities" ] ) for a in record[ "answers" ] if a[ "id" ] == probe_id )
    arms      = {}
    for key, ids, label in ( ( "random", random_ids, "random" ), ( "near", near_ids, "near_duplicate" ) ):
        for place, at in POSITIONS.items():
            pack = ids[ :at ] + [ probe_id ] + ids[ at: ]
            arms[ f"probe-{place}-{key}" ] = { "entries": [ by_id[ i ] for i in pack ], "probe": { "id": probe_id, "placement": place, "neighbours": label } }
    plan = { "question": record[ "question" ], "seed": seed, "probe_id": probe_id, "probe_overlap": overlap, "band": list( BAND ), "target": TARGET,
             "neighbour_rule": NEIGHBOUR_RULE, "random_ids": random_ids, "near_ids": near_ids }
    return { "plan": plan, "arms": arms }


def write_probe_plan( env, plan ):
    """
    Write the plan once, beside the arm files.

    Ensures:
        - writes <results>/s1-q<k>-probe-plan.json whole or not at all; returns its path
    Raises:
        - FileExistsError when the question already has a plan, so a plan is never replaced after the fact
    """
    path = env.results_dir / f"s1-q{plan[ 'plan' ][ 'question' ]}-probe-plan.json"
    path.parent.mkdir( parents=True, exist_ok=True )
    tmp = path.with_name( path.name + ".tmp" )
    tmp.write_text( json.dumps( plan[ "plan" ], sort_keys=True, indent=1 ) + "\n", encoding="utf-8" )
    try: os.link( tmp, path )                                                   # fails if the plan is there: a plan is written once
    finally: tmp.unlink()
    return path
