"""
The analysis of the live packing measurement: the rules that read its result.

Pure functions on the arm records the driver writes (format stage1-arm-1). Nothing here calls a
model, reads the cache or writes a file, except the command line at the end. Every threshold is a
constant taken from the plan and pinned by a test to the plan's literal. They were fixed before any
live number existed, and a change to one is a change to the pre-registration.

An arm is clean, inconclusive or invalid. Only a clean arm can contribute to a pass.
"""
import math

from cosa.repo.symindex import verdict as vd

FORMAT                          = "stage1-arm-1"
BAND                            = ( 0.35, 0.65 )              # a boundary entry's single-run overlap lies in this band, ends included
MIN_BOUNDARY_POOLED             = 90                          # fewer pooled boundary entries reads inconclusive, never pass
STOP_BOUNDARY_AFTER_QUESTION_2  = 50                          # fewer pooled after question 2 stops the stage
STOP_SPEND_AFTER_QUESTION_1     = 15_000_000                  # tokens; more than this after question 1 stops the stage
STAGE_TOKENS                    = 71_000_000
NOISE_FLOOR_MIN                 = 0.02
PERCENTILE                      = 0.99
FLIP_ALLOWANCE                  = 1                           # a pack size may flip this many more entries than the noise floor
THRESHOLD                       = 0.5                         # the policy threshold the flips are counted at
OUTPUT_PER_ENTRY_STOP           = 60
PACK_SIZES                      = ( 10, 50, 200 )
PRICE_PER_MILLION               = 0.042
PROBE_PLACEMENTS                = ( "first", "middle", "last" )
PROBE_NEIGHBOURS                = ( "random", "near_duplicate" )

INVALID_STOPS = ( "ceiling", "ledger", "consecutive_422" )


def read_arm( record ):
    """
    Read one arm record into the facts the rules use.

    Requires:
        - record is a dict in the stage1-arm-1 format
    Ensures:
        - returns the record's identity, its totals, rows and transport calls, plus overlaps, confidences,
          malformed, and status
        - overlaps maps each validly answered id to reuse plus extend rounded to six places
        - malformed maps an answered id whose probabilities are not valid to the reason
        - status is "invalid" when the arm was stopped by the ceiling, the ledger or refusals, or errored
        - status is "inconclusive" when it ran out of attempts, is not complete, or has any failed, unasked,
          unreached entry, or has an entry without a valid answer (a malformed one included), or asked nothing
        - status is "clean" otherwise
    Raises:
        - ValueError for another format, an answer for an id the arm did not ask about, or an id answered twice
    """
    if record.get( "format" ) != FORMAT: raise ValueError( f"expected format {FORMAT!r}, got {record.get( 'format' )!r}" )
    asked = set( record[ "entry_ids" ] )
    overlaps, confidences, malformed, seen = {}, {}, {}, set()
    for a in record[ "answers" ]:
        i = a[ "id" ]
        if i not in asked: raise ValueError( f"answer for {i!r} which the arm did not ask about" )
        if i in seen: raise ValueError( f"{i!r} answered twice" )
        seen.add( i )
        reason = vd.malformed_reason( a[ "probabilities" ] )
        if reason is not None: malformed[ i ] = reason; continue
        p, conf, _ = vd.call_facts( a[ "probabilities" ] )
        overlaps[ i ], confidences[ i ] = round( p, 6 ), round( conf, 6 )
    stop = record[ "stop_reason" ]
    if record[ "state" ] == "error" or stop in INVALID_STOPS or ( stop is not None and stop.startswith( "error" ) ): status = "invalid"
    elif ( stop == "attempts" or record[ "state" ] != "complete" or record[ "failed" ] or record[ "unasked" ] or record[ "not_reached" ]
           or set( overlaps ) != asked or not asked ): status = "inconclusive"
    else: status = "clean"
    return { "question": record[ "question" ], "arm": record[ "arm" ], "run_name": record[ "run_name" ], "size": record[ "size" ],
             "state": record[ "state" ], "stop_reason": stop, "entry_ids": list( record[ "entry_ids" ] ),
             "overlaps": overlaps, "confidences": confidences, "malformed": malformed,
             "failed": list( record[ "failed" ] ), "not_reached": list( record[ "not_reached" ] ), "unasked": list( record[ "unasked" ] ),
             "cache_hits": record[ "cache_hits" ], "totals": record[ "totals" ], "rows": record[ "rows" ],
             "transport_calls": record[ "transport_calls" ], "probe": record.get( "probe" ), "status": status }


def read_stage( records ):
    """
    Read every arm record of the stage and group them.

    Ensures:
        - returns { question: { arm name: arm } }
    Raises:
        - ValueError for a run name used twice, or an arm name twice in one question
    """
    stage, names = {}, set()
    for rec in records:
        arm = read_arm( rec )
        if arm[ "run_name" ] is not None:
            if arm[ "run_name" ] in names: raise ValueError( f"run name {arm[ 'run_name' ]!r} used twice" )
            names.add( arm[ "run_name" ] )
        by_name = stage.setdefault( arm[ "question" ], {} )
        if arm[ "arm" ] in by_name: raise ValueError( f"arm {arm[ 'arm' ]!r} given twice for question {arm[ 'question' ]}" )
        by_name[ arm[ "arm" ] ] = arm
    return stage


def percentile( values, q=PERCENTILE ):
    """
    Take the nearest-rank percentile.

    Ensures:
        - returns the ceil( q * n )-th smallest value, or None for no values
    """
    if not values: return None
    ordered = sorted( values )
    return ordered[ math.ceil( round( q * len( ordered ), 9 ) ) - 1 ]


def differences( a, b ):
    """
    Take the per-entry overlap differences between two arms.

    Ensures:
        - returns { id: absolute difference, six places } over the ids validly answered in both arms
    """
    return { i: round( abs( a[ "overlaps" ][ i ] - b[ "overlaps" ][ i ] ), 6 ) for i in a[ "overlaps" ] if i in b[ "overlaps" ] }


def boundary_ids( arm ):
    """
    List the boundary entries of an arm.

    Ensures:
        - returns the sorted ids whose overlap lies from the band's low end to its high end, both included
    """
    return sorted( i for i, o in arm[ "overlaps" ].items() if BAND[ 0 ] <= o <= BAND[ 1 ] )


def flips( ref, other, ids, cut ):
    """
    List the entries that cross a cut between two arms.

    Ensures:
        - returns the sorted ids, among ids answered in both arms, on opposite sides of cut
        - an overlap equal to the cut counts as above it
    """
    return sorted( i for i in ids if i in ref[ "overlaps" ] and i in other[ "overlaps" ] and ( ref[ "overlaps" ][ i ] >= cut ) != ( other[ "overlaps" ][ i ] >= cut ) )
