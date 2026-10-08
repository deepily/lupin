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
FLOOR                           = 0.3                         # the page floor of the policy
CONFIDENCE_BAR                  = 0.9                         # an answer is confident from this largest probability

INVALID_STOPS = ( "ceiling", "ledger", "consecutive_422" )
PROBE_PLAN_SUFFIX = "-probe-plan.json"                        # the driver writes one of these beside the arms of a question
LOST_ONE_IN   = 200                                           # an arm may lose one entry in this many and still be judged
REQUIRED_ARMS = ( "single1", "canary", "single2", "pack10", "pack50", "pack200", "page-single1", "page-single2", "page-pack",
                  "probe-first-random", "probe-first-near", "probe-middle-random", "probe-middle-near", "probe-last-random", "probe-last-near" )


def lost_limit( n ):
    """
    Give the number of entries an arm of n entries may lose and still be judged.

    Requires:
        - n is a non-negative integer
    Ensures:
        - returns n divided by the lost-entry ratio, rounded down
    """
    return n // LOST_ONE_IN


def read_arm( record ):
    """
    Read one arm record into the facts the rules use.

    Requires:
        - record is a dict in the stage1-arm-1 format
    Ensures:
        - returns the record's identity, its totals, rows and transport calls, plus overlaps, confidences,
          the valid probabilities, malformed, and status
        - overlaps maps each validly answered id to reuse plus extend rounded to six places
        - malformed maps an answered id whose probabilities are not valid to the reason
        - status is "invalid" when the arm was stopped by the ceiling, the ledger or refusals, or errored
        - lost lists, sorted, the asked ids without a valid answer plus every id named failed, unasked or not reached
        - lost_limit is the number of entries the arm may lose and still be judged
        - status is "inconclusive" when it asked nothing, or has any other stop reason, whatever it lost
        - status is "inconclusive" when it is not complete and lost nothing, since the record contradicts itself
        - status is "clean" when the lost entries number at most the limit, and "inconclusive" otherwise
        - an arm that tried every entry and has no stop reason is judged by its lost entries, complete or not
    Raises:
        - ValueError for another format, an answer for an id the arm did not ask about, or an id answered twice
    """
    if record.get( "format" ) != FORMAT: raise ValueError( f"expected format {FORMAT!r}, got {record.get( 'format' )!r}" )
    asked = set( record[ "entry_ids" ] )
    overlaps, confidences, probabilities, malformed, seen = {}, {}, {}, {}, set()
    for a in record[ "answers" ]:
        i = a[ "id" ]
        if i not in asked: raise ValueError( f"answer for {i!r} which the arm did not ask about" )
        if i in seen: raise ValueError( f"{i!r} answered twice" )
        seen.add( i )
        reason = vd.malformed_reason( a[ "probabilities" ] )
        if reason is not None: malformed[ i ] = reason; continue
        p, conf, _ = vd.call_facts( a[ "probabilities" ] )
        overlaps[ i ], confidences[ i ], probabilities[ i ] = round( p, 6 ), round( conf, 6 ), a[ "probabilities" ]
    stop = record[ "stop_reason" ]
    lost = sorted( ( asked - set( overlaps ) ) | set( record[ "failed" ] ) | set( record[ "unasked" ] ) | set( record[ "not_reached" ] ) )
    limit = lost_limit( len( asked ) )
    if record[ "state" ] == "error" or stop in INVALID_STOPS or ( stop is not None and stop.startswith( "error" ) ): status = "invalid"
    elif not asked or stop is not None or ( record[ "state" ] != "complete" and not lost ): status = "inconclusive"
    else: status = "clean" if len( lost ) <= limit else "inconclusive"
    return { "question": record[ "question" ], "arm": record[ "arm" ], "run_name": record[ "run_name" ], "size": record[ "size" ],
             "attempt": record.get( "attempt" ) or 1, "retry_reason": record.get( "retry_reason" ),
             "state": record[ "state" ], "stop_reason": stop, "entry_ids": list( record[ "entry_ids" ] ),
             "overlaps": overlaps, "confidences": confidences, "probabilities": probabilities, "malformed": malformed,
             "lost": lost, "lost_limit": limit,
             "failed": list( record[ "failed" ] ), "not_reached": list( record[ "not_reached" ] ), "unasked": list( record[ "unasked" ] ),
             "cache_hits": record[ "cache_hits" ], "totals": record[ "totals" ], "rows": record[ "rows" ],
             "transport_calls": record[ "transport_calls" ], "probe": record.get( "probe" ), "status": status }


def read_stage( records ):
    """
    Read every arm record of the stage and group them.

    Ensures:
        - returns { question: { arm name: arm } }; a retry is keyed by its name and attempt, such as canary-a2
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
        key     = arm[ "arm" ] if arm[ "attempt" ] == 1 else f"{arm[ 'arm' ]}-a{arm[ 'attempt' ]}"
        if key in by_name: raise ValueError( f"arm {key!r} given twice for question {arm[ 'question' ]}" )
        by_name[ key ] = arm
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


PASS_THREE_SIZE = 200                                         # the probe placements are run in a pack of this size, so they gate only this size
CANARY_TRIPS    = ( "output_per_entry_over_60", "usage_over_reserve", "refusal", "usage_missing", "incomplete", "nothing_measured" )


def _spent( arm ):
    """
    Take the tokens an arm spent.

    Ensures:
        - returns the settled figure, or the reported input plus output when none was settled
    """
    t = arm[ "totals" ]
    return t[ "spent_tokens" ] if t.get( "spent_tokens" ) is not None else ( t.get( "tokens_in" ) or 0 ) + ( t.get( "tokens_out" ) or 0 )


def _arms_state( arms ):
    """
    Judge a set of arms together.

    Ensures:
        - returns "invalid" if any arm is invalid
        - otherwise "inconclusive" if any is absent or not clean
        - otherwise None
    """
    if any( a is not None and a[ "status" ] == "invalid" for a in arms ): return "invalid"
    if not arms or any( a is None or a[ "status" ] != "clean" for a in arms ): return "inconclusive"
    return None


def _combine( states ):
    """
    Take the strongest of several states.

    Ensures:
        - returns the first present of invalid, fail, inconclusive, and otherwise pass
    """
    for s in ( "invalid", "fail", "inconclusive" ):
        if s in states: return s
    return "pass"


def noise_floor( stage ):
    """
    Measure the noise floor: single run 1 against single run 2, pooled over the questions run.

    Ensures:
        - returns { measured, floor, max, n, state }
        - state is "invalid" if any single run was stopped, "inconclusive" if any is absent or not clean,
          else "ok"
        - measured is the 99th percentile of the pooled differences, and floor is the larger of it and the minimum
        - measured, floor and max are None unless state is "ok"
    """
    arms = [ a for q in sorted( stage ) for a in ( stage[ q ].get( "single1" ), stage[ q ].get( "single2" ) ) ]
    bad  = _arms_state( arms )
    if bad is not None: return { "measured": None, "floor": None, "max": None, "n": 0, "state": bad }
    diffs = [ d for q in sorted( stage ) for d in differences( stage[ q ][ "single1" ], stage[ q ][ "single2" ] ).values() ]
    measured = percentile( diffs )
    return { "measured": measured, "floor": max( measured, NOISE_FLOOR_MIN ), "max": max( diffs ), "n": len( diffs ), "state": "ok" }


def pass_one( stage, size, floor ):
    """
    Pass 1: the 99th percentile of the per-entry difference stays within the floor.

    Ensures:
        - returns { state, p99, max, n } pooled over the questions run
        - state is "pass" when p99 is at most floor, "fail" above it, "invalid" or "inconclusive" with its arms
        - state is "inconclusive" when floor is None
    """
    arms = [ a for q in sorted( stage ) for a in ( stage[ q ].get( "single1" ), stage[ q ].get( f"pack{size}" ) ) ]
    bad  = _arms_state( arms )
    if bad is not None or floor is None: return { "state": bad or "inconclusive", "p99": None, "max": None, "n": 0 }
    diffs = [ d for q in sorted( stage ) for d in differences( stage[ q ][ "single1" ], stage[ q ][ f"pack{size}" ] ).values() ]
    p99   = percentile( diffs )
    return { "state": "pass" if p99 <= floor else "fail", "p99": p99, "max": max( diffs ), "n": len( diffs ) }


def pass_two( stage, size ):
    """
    Pass 2: flips at the threshold on boundary entries, pack arm against single run 1.

    Ensures:
        - returns { state, pack_flips, noise_flips, boundary } pooled over the questions run
        - state is "pass" when pack_flips is at most noise_flips plus the allowance, "fail" above it
        - state is "invalid" or "inconclusive" with its arms
    """
    arms = [ a for q in sorted( stage ) for a in ( stage[ q ].get( "single1" ), stage[ q ].get( "single2" ), stage[ q ].get( f"pack{size}" ) ) ]
    bad  = _arms_state( arms )
    if bad is not None: return { "state": bad, "pack_flips": None, "noise_flips": None, "boundary": 0 }
    pack_flips = noise_flips = boundary = 0
    for q in sorted( stage ):
        s1, s2, pack = stage[ q ][ "single1" ], stage[ q ][ "single2" ], stage[ q ][ f"pack{size}" ]
        ids = boundary_ids( s1 )
        boundary    += len( ids )
        pack_flips  += len( flips( s1, pack, ids, THRESHOLD ) )
        noise_flips += len( flips( s1, s2, ids, THRESHOLD ) )
    return { "state": "pass" if pack_flips <= noise_flips + FLIP_ALLOWANCE else "fail", "pack_flips": pack_flips, "noise_flips": noise_flips, "boundary": boundary }


def pass_three( stage, floor ):
    """
    Pass 3: the probe entry stays within the floor of its single value in six placements.

    Requires:
        - a question with probe arms has all six placements, each once
    Ensures:
        - returns { state, placements, worst, not_probed } pooled over the questions that have probe arms
        - not_probed lists, in order, the questions with no probe arm; they add no evidence
        - state is "pass" when every placement is within floor of single run 1, "fail" when one is not
        - state is "inconclusive" while any probed question has fewer than all six placements
        - state is "invalid" when a probe arm was stopped, and "inconclusive" when no question has probes, a
          question lacks a placement, single run 1 is not clean or lacks the probe, or the arm has no probe answer
    Raises:
        - ValueError when one placement is given twice for a question
    """
    placements, diffs, states, not_probed = 0, [], [], []
    for q in sorted( stage ):
        probes = [ a for a in stage[ q ].values() if a[ "probe" ] ]
        if not probes: not_probed.append( q ); continue
        seen = {}
        for a in probes:
            key = ( a[ "probe" ][ "placement" ], a[ "probe" ][ "neighbours" ] )
            if key in seen: raise ValueError( f"placement {key} given twice for question {q}" )
            seen[ key ] = a
        s1 = stage[ q ].get( "single1" )
        if _arms_state( [ s1 ] + probes ) == "invalid": states.append( "invalid" ); continue
        if s1 is None or s1[ "status" ] != "clean" or len( seen ) != len( PROBE_PLACEMENTS ) * len( PROBE_NEIGHBOURS ): states.append( "inconclusive" ); continue
        for a in probes:
            pid = a[ "probe" ][ "id" ]
            if pid not in a[ "overlaps" ] or pid not in s1[ "overlaps" ]: states.append( "inconclusive" ); continue
            placements += 1
            diffs.append( round( abs( a[ "overlaps" ][ pid ] - s1[ "overlaps" ][ pid ] ), 6 ) )
    if not states and not diffs: return { "state": "inconclusive", "placements": 0, "worst": None, "not_probed": not_probed }
    if floor is None: states.append( "inconclusive" )
    else: states.append( "pass" if all( d <= floor for d in diffs ) else "fail" )
    return { "state": _combine( states ), "placements": placements, "worst": max( diffs ) if diffs else None, "not_probed": not_probed }


def evaluate( stage ):
    """
    Apply the three passes to each pack size and name the default.

    Ensures:
        - returns { noise_floor, boundary_by_question, boundary_pooled, sizes, default_size, unresolved_larger, decision }
        - sizes maps each pack size to { state, pass_one, pass_two, pass_three }; pass 3 gates only the size it was run at
        - a size that would pass reads inconclusive while fewer than the minimum pooled boundary entries were seen
        - default_size is the largest size that passes, and unresolved_larger lists larger sizes still inconclusive
        - decision is "stop and ask: an arm is invalid" if any size is invalid, else the default size, else
          "inconclusive" if any size is, else "stop and ask: no pack size passes"
    """
    nf     = noise_floor( stage )
    by_q   = { q: len( boundary_ids( stage[ q ][ "single1" ] ) ) for q in sorted( stage ) if stage[ q ].get( "single1" ) and stage[ q ][ "single1" ][ "status" ] == "clean" }
    pooled = sum( by_q.values() )
    sizes  = {}
    for size in PACK_SIZES:
        p1, p2 = pass_one( stage, size, nf[ "floor" ] ), pass_two( stage, size )
        p3     = pass_three( stage, nf[ "floor" ] ) if size == PASS_THREE_SIZE else None
        state  = _combine( [ p1[ "state" ], p2[ "state" ] ] + ( [ p3[ "state" ] ] if p3 else [] ) )
        if state == "pass" and pooled < MIN_BOUNDARY_POOLED: state = "inconclusive"
        sizes[ size ] = { "state": state, "pass_one": p1, "pass_two": p2, "pass_three": p3 }
    passing = [ s for s in PACK_SIZES if sizes[ s ][ "state" ] == "pass" ]
    default = max( passing ) if passing else None
    states  = [ sizes[ s ][ "state" ] for s in PACK_SIZES ]
    if "invalid" in states: decision = "stop and ask: an arm is invalid"
    elif default is not None: decision = f"default pack size {default}"
    elif "inconclusive" in states: decision = "inconclusive"
    else: decision = "stop and ask: no pack size passes"
    return { "noise_floor": nf, "boundary_by_question": by_q, "boundary_pooled": pooled, "sizes": sizes, "default_size": default,
             "unresolved_larger": [ s for s in PACK_SIZES if default is not None and s > default and sizes[ s ][ "state" ] == "inconclusive" ],
             "decision": decision }


def stop_rules( stage, check_arms=True ):
    """
    Read the rules that stop the stage between questions.

    Ensures:
        - returns { stop, next_step, findings, pooled_boundary, spent_by_question, spent_total }
        - a finding is { rule, stop, detail }; the rules are the stage ceiling, spend after question 1,
          and a single run 1 that is absent or not clean
        - with check_arms, the first question that lacks a required arm names its remaining arms as the next step
        - the arms are checked after the stop findings and an unclean single run 1, and before the rules below
        - a retry such as canary-a2 never stands in for a required arm
        - after question 2, fewer than the minimum pooled boundary entries stops before question 3
        - after question 3, fewer than the pooled minimum asks for the reserve question
        - after the reserve question, fewer than the pooled minimum reads inconclusive
    """
    spent = { q: sum( _spent( a ) for a in stage[ q ].values() ) for q in sorted( stage ) }
    total = sum( spent.values() )
    findings = []
    if total > STAGE_TOKENS: findings.append( { "rule": "stage_ceiling", "stop": True, "detail": f"stage tokens above {STAGE_TOKENS:,}" } )
    if spent.get( 1, 0 ) > STOP_SPEND_AFTER_QUESTION_1: findings.append( { "rule": "spend_after_question_1", "stop": True, "detail": f"spend after question 1 above {STOP_SPEND_AFTER_QUESTION_1:,} tokens" } )
    unclean = [ q for q in sorted( stage ) if stage[ q ].get( "single1" ) is None or stage[ q ][ "single1" ][ "status" ] != "clean" ]
    pooled  = sum( len( boundary_ids( stage[ q ][ "single1" ] ) ) for q in sorted( stage ) if q not in unclean )
    last    = max( stage ) if stage else 0
    stops   = [ f for f in findings if f[ "stop" ] ]
    if stops: stop, step = True, f"stop and ask: {stops[ 0 ][ 'detail' ]}"
    elif unclean: stop, step = True, f"stop and ask: question {unclean[ 0 ]}'s single run 1 is not clean"
    elif check_arms and any( n not in stage[ q ] for q in sorted( stage ) for n in REQUIRED_ARMS ):
        q = next( q for q in sorted( stage ) if any( n not in stage[ q ] for n in REQUIRED_ARMS ) )
        stop, step = False, f"run question {q}'s remaining arms: " + ", ".join( n for n in REQUIRED_ARMS if n not in stage[ q ] )
    elif last <= 1: stop, step = False, "run question 2"
    elif last == 2 and pooled < STOP_BOUNDARY_AFTER_QUESTION_2: stop, step = True, f"stop and ask: under {STOP_BOUNDARY_AFTER_QUESTION_2} pooled boundary entries after question 2"
    elif last == 2: stop, step = False, "run question 3"
    elif last == 3 and pooled < MIN_BOUNDARY_POOLED: stop, step = False, "run the reserve question"
    elif last >= 4 and pooled < MIN_BOUNDARY_POOLED: stop, step = False, f"evaluate: inconclusive, under {MIN_BOUNDARY_POOLED} pooled boundary entries"
    else: stop, step = False, "evaluate"
    return { "stop": stop, "next_step": step, "findings": findings, "pooled_boundary": pooled, "spent_by_question": spent, "spent_total": total }


def check_canary( arm, canary ):
    """
    Recompute the canary's stop conditions from the arm's own rows.

    Requires:
        - arm is the canary arm record and canary the driver's canary file, both as dicts
    Ensures:
        - returns { tripped, output_per_entry, unverifiable, agrees, analysis_only, driver_only, failed, unasked, not_reached }
        - tripped lists, in the order of CANARY_TRIPS: output tokens per entry above the stop figure, usage above
          a row's reserve, any refusal (a refused row, an HTTP 422, or a refused total), an answered row with no
          usage, an unfinished arm, and an arm that sent no request
        - unverifiable counts answered rows that reported no usage, which only a person can read
        - agrees compares tripped with the driver's own list, and the two other lists name the differences
    """
    rows, out_per, over_reserve, refused = arm[ "rows" ], [], False, bool( arm[ "totals" ].get( "refused_422" ) )
    for r in rows:
        if r[ "status" ] == "refused" or r.get( "http_status" ) == 422: refused = True
        if r[ "tokens_out" ] is None or r[ "tokens_in" ] is None: continue
        out_per.append( round( r[ "tokens_out" ] / r[ "size" ], 6 ) )
        if r[ "reserve_tokens" ] is not None and r[ "tokens_in" ] + r[ "tokens_out" ] > r[ "reserve_tokens" ]: over_reserve = True
    unverifiable = sum( 1 for r in rows if r[ "status" ] == "answered" and ( r[ "tokens_in" ] is None or r[ "tokens_out" ] is None ) )
    flags = { "output_per_entry_over_60": any( x > OUTPUT_PER_ENTRY_STOP for x in out_per ), "usage_over_reserve": over_reserve, "refusal": refused,
              "usage_missing": unverifiable > 0, "incomplete": arm[ "state" ] != "complete" or bool( arm[ "failed" ] or arm[ "unasked" ] or arm[ "not_reached" ] ),
              "nothing_measured": not any( r[ "attempts" ] > 0 for r in rows ) }
    tripped = [ t for t in CANARY_TRIPS if flags[ t ] ]
    driver  = list( canary[ "tripped" ] )
    return { "tripped": tripped, "output_per_entry": out_per, "unverifiable": unverifiable,
             "agrees": sorted( tripped ) == sorted( driver ), "analysis_only": [ t for t in tripped if t not in driver ], "driver_only": [ t for t in driver if t not in tripped ],
             "failed": len( arm[ "failed" ] ), "unasked": len( arm[ "unasked" ] ), "not_reached": len( arm[ "not_reached" ] ) }


def analyze_pages( stage ):
    """
    Read the page arm of each question.

    Ensures:
        - returns { question: { state, chosen_single1, chosen_single2, chosen_pack, set_changed_by_packing,
          set_changed_by_noise, pack_p99, pack_max, noise_p99, noise_max } } for each question with any page arm
        - the chosen pages are those the tool itself chooses at the policy floor, capped as the tool caps them
        - only the pages answered in all three arms are read, so an entry lost within the limit never raises
        - state is "fail" when packing changes the set of chosen pages, "pass" when it does not, and "invalid"
          or "inconclusive" with its arms; a change between the two single runs is reported as noise only
    """
    from lupin_mcp import reuse_tools as rt
    out = {}
    for q in sorted( stage ):
        names = ( "page-single1", "page-single2", "page-pack" )
        if not any( n in stage[ q ] for n in names ): continue
        s1, s2, pack = ( stage[ q ].get( n ) for n in names )
        bad = _arms_state( [ s1, s2, pack ] )
        if bad is not None: out[ q ] = { "state": bad }; continue
        common = [ i for i in s1[ "entry_ids" ] if all( i in a[ "probabilities" ] for a in ( s1, s2, pack ) ) ]
        chosen = [ [ c[ "slug" ] for c in rt._choose_pages( [ { "id": i, "probabilities": a[ "probabilities" ][ i ] } for i in common ], vd.POLICY ) ] for a in ( s1, s2, pack ) ]
        pk, nz = list( differences( s1, pack ).values() ), list( differences( s1, s2 ).values() )
        changed = set( chosen[ 0 ] ) != set( chosen[ 2 ] )
        out[ q ] = { "state": "fail" if changed else "pass", "chosen_single1": chosen[ 0 ], "chosen_single2": chosen[ 1 ], "chosen_pack": chosen[ 2 ],
                     "set_changed_by_packing": changed, "set_changed_by_noise": set( chosen[ 0 ] ) != set( chosen[ 1 ] ),
                     "pack_p99": percentile( pk ), "pack_max": max( pk ), "noise_p99": percentile( nz ), "noise_max": max( nz ) }
    return out


def _confidence_flips( ref, other ):
    """Ensures: returns the ids answered in both arms on opposite sides of the confidence bar."""
    return [ i for i in ref[ "confidences" ] if i in other[ "confidences" ] and ( ref[ "confidences" ][ i ] >= CONFIDENCE_BAR ) != ( other[ "confidences" ][ i ] >= CONFIDENCE_BAR ) ]


def other_boundaries( stage, size ):
    """
    Count the flips at the policy's other boundaries, recorded with no pass or fail.

    Ensures:
        - returns { question: { floor: { pack, noise }, confidence: { pack, noise } } } over every entry answered in both arms
        - the pack count compares the pack arm with single run 1, and the noise count single run 2 with single run 1
        - a question is None when its single runs or its pack arm are absent or not clean
    """
    out = {}
    for q in sorted( stage ):
        s1, s2, pack = stage[ q ].get( "single1" ), stage[ q ].get( "single2" ), stage[ q ].get( f"pack{size}" )
        if _arms_state( [ s1, s2, pack ] ) is not None: out[ q ] = None; continue
        ids = list( s1[ "overlaps" ] )
        out[ q ] = { "floor"     : { "pack": len( flips( s1, pack, ids, FLOOR ) ), "noise": len( flips( s1, s2, ids, FLOOR ) ) },
                     "confidence": { "pack": len( _confidence_flips( s1, pack ) ), "noise": len( _confidence_flips( s1, s2 ) ) } }
    return out


def _mean( values ): return round( sum( values ) / len( values ), 3 ) if values else None


def request_stats( stage ):
    """
    Summarise the requests each arm sent.

    Ensures:
        - returns { question: { arm: { requests_sent, tokens_in_per_request, tokens_out_per_request, tokens_out_per_entry,
          retried_calls, extra_attempts, usage_missing, retry_statuses } } }
        - only rows with an attempt count as sent; a sent row without usage counts as missing and stays out of the means
        - retries are reported as 429 or 529 together, because the transport does not say which
    """
    out = {}
    for q in sorted( stage ):
        for name, arm in stage[ q ].items():
            sent  = [ r for r in arm[ "rows" ] if r[ "attempts" ] > 0 ]
            known = [ r for r in sent if r[ "tokens_in" ] is not None and r[ "tokens_out" ] is not None ]
            calls = arm[ "transport_calls" ]
            out.setdefault( q, {} )[ name ] = { "requests_sent": len( sent ), "tokens_in_per_request": _mean( [ r[ "tokens_in" ] for r in known ] ),
                "tokens_out_per_request": _mean( [ r[ "tokens_out" ] for r in known ] ), "tokens_out_per_entry": _mean( [ r[ "tokens_out" ] / r[ "size" ] for r in known ] ),
                "retried_calls": sum( 1 for c in calls if c[ "attempts" ] > 1 ), "extra_attempts": sum( c[ "attempts" ] - 1 for c in calls ),
                "usage_missing": len( sent ) - len( known ), "retry_statuses": "429 or 529, not told apart" }
    return out


def cost_per_search( stage, default_size ):
    """
    Price one search at the default pack size.

    Ensures:
        - the search is the entries asked in packs of that size, plus the page asks packed
        - returns None when default_size is None
        - otherwise { question: { entry_tokens, page_tokens, dollars }, mean_dollars } for each question with that pack arm
        - dollars are tokens over a million at the pinned price, input and output counted at the same rate
        - page_tokens is zero for a question with no page-pack arm; mean_dollars is None with no such question
    """
    if default_size is None: return None
    out = {}
    for q in sorted( stage ):
        pack = stage[ q ].get( f"pack{default_size}" )
        if pack is None: continue
        entry, page = _spent( pack ), _spent( stage[ q ][ "page-pack" ] ) if "page-pack" in stage[ q ] else 0
        out[ q ] = { "entry_tokens": entry, "page_tokens": page, "dollars": round( ( entry + page ) / 1_000_000 * PRICE_PER_MILLION, 6 ) }
    out[ "mean_dollars" ] = round( sum( v[ "dollars" ] for v in out.values() ) / len( out ), 6 ) if out else None
    return out


def old_shape_report( stage ):
    """
    Compare the old-shape arm with single run 1. Reported only.

    Ensures:
        - compares only the entries that were cache hits
        - returns { question: { hits, p99, max, boundary_flips, note } } for each question with an old arm
        - boundary_flips counts the hits among single run 1's boundary entries that cross the threshold
        - a question is None when its single run 1 is absent or not clean
    """
    out = {}
    for q in sorted( stage ):
        old = stage[ q ].get( "old" )
        if old is None: continue
        s1 = stage[ q ].get( "single1" )
        if _arms_state( [ s1 ] ) is not None: out[ q ] = None; continue
        diffs = list( differences( s1, old ).values() )
        out[ q ] = { "hits": len( old[ "overlaps" ] ), "p99": percentile( diffs ), "max": max( diffs ) if diffs else None,
                     "boundary_flips": len( flips( s1, old, boundary_ids( s1 ), THRESHOLD ) ), "note": "reported only, no pass or fail" }
    return out


def old_shape_arm( question, data_dir, need, entries ):
    """
    Read the old three-way answers for entries from the cache, as an arm record.

    Requires:
        - entries are symbol dicts with id, sig and doc; data_dir holds the cache the old runs wrote
    Ensures:
        - returns a stage1-arm-1 record named "old" with no run name, one entry per request, and no live call
        - answers hold the cached entries, in order; entries with no cache hit are listed as not reached
        - state is "complete" only when every entry was a hit
    """
    from lupin_mcp import reuse_tools as rt
    cache, answers, missing = rt.JevCache( data_dir ), [], []
    for rec in entries:
        resp = cache.get( rt.request_hash( rt.build_request( need, rt.entry_text( rec ) ) ) )
        if resp is None: missing.append( rec[ "id" ] )
        else: answers.append( { "id": rec[ "id" ], "probabilities": rt.parse_answer( resp ) } )
    zero = { "requests": 0, "calls": 0, "attempts_answered": 0, "attempts_failed": 0, "tokens_in": 0, "tokens_out": 0, "usage_missing": 0,
             "refused_422": 0, "stopped_by": None, "spent_tokens": 0, "reserved_tokens": 0, "ceiling_refusals": 0 }
    return { "format": FORMAT, "question": question, "need": need, "arm": "old", "run_name": None, "run_index": None, "size": 1, "model": rt.JEV_MODEL,
             "template_hash": None, "state": "complete" if not missing else "incomplete", "stop_reason": None, "entry_ids": [ e[ "id" ] for e in entries ],
             "answers": answers, "failed": [], "not_reached": missing, "unasked": [], "cache_hits": len( answers ), "rows": [], "totals": zero, "transport_calls": [] }


def build_report( records, canaries ):
    """
    Run every part of the analysis on the arm records.

    Requires:
        - records are stage1-arm-1 dicts; canaries is a list of ( canary arm record, canary file ) pairs
    Ensures:
        - returns { decision, next_step, evaluate, stop_rules, pages, other_boundaries, request_stats, cost, old_shape,
          canaries, unclean_arms, lost_by_arm }
        - lost_by_arm gives every arm's lost count beside its limit
        - decision comes from the passes and next_step from the stop rules
        - unclean_arms lists every arm that is not clean, with its status and stop reason
    """
    stage = read_stage( records )
    ev    = evaluate( stage )
    stop  = stop_rules( stage )
    unclean = [ { "run_name": a[ "run_name" ], "question": a[ "question" ], "arm": a[ "arm" ], "status": a[ "status" ], "stop_reason": a[ "stop_reason" ] }
                for q in sorted( stage ) for a in stage[ q ].values() if a[ "status" ] != "clean" ]
    return { "decision": ev[ "decision" ], "next_step": stop[ "next_step" ], "evaluate": ev, "stop_rules": stop, "pages": analyze_pages( stage ),
             "other_boundaries": { s: other_boundaries( stage, s ) for s in PACK_SIZES }, "request_stats": request_stats( stage ),
             "cost": cost_per_search( stage, ev[ "default_size" ] ), "old_shape": old_shape_report( stage ),
             "canaries": [ dict( check_canary( arm, can ), run_name=can[ "run_name" ] ) for arm, can in canaries ], "unclean_arms": unclean,
             "lost_by_arm": [ { "run_name": a[ "run_name" ], "question": a[ "question" ], "arm": a[ "arm" ], "lost": len( a[ "lost" ] ), "lost_limit": a[ "lost_limit" ] }
                              for q in sorted( stage ) for a in stage[ q ].values() ] }


def render( report ):
    """
    Write the report as plain text.

    Ensures:
        - returns a string with the decision, the next step, the boundary count, the noise floor, one block per
          pack size, every arm's lost count and limit, the questions not probed, each arm that is not clean, each canary, the page arms and the cost
    """
    ev, nf = report[ "evaluate" ], report[ "evaluate" ][ "noise_floor" ]
    lines  = [ "Live packing measurement: analysis", "", f"Decision: {report[ 'decision' ]}", f"Next step: {report[ 'next_step' ]}", "",
               f"boundary entries pooled: {ev[ 'boundary_pooled' ]} (minimum {MIN_BOUNDARY_POOLED}); by question {ev[ 'boundary_by_question' ]}",
               f"noise floor: {nf[ 'state' ]}, measured {nf[ 'measured' ]}, used {nf[ 'floor' ]} over {nf[ 'n' ]} entries" ]
    for size in PACK_SIZES:
        s = ev[ "sizes" ][ size ]
        p3 = s[ "pass_three" ]
        lines.append( f"pack {size}: {s[ 'state' ]}; pass 1 {s[ 'pass_one' ][ 'state' ]} (p99 {s[ 'pass_one' ][ 'p99' ]}, max {s[ 'pass_one' ][ 'max' ]}); "
                      f"pass 2 {s[ 'pass_two' ][ 'state' ]} (flips {s[ 'pass_two' ][ 'pack_flips' ]} against noise {s[ 'pass_two' ][ 'noise_flips' ]})"
                      + ( f"; pass 3 {p3[ 'state' ]} ({p3[ 'placements' ]} placements, worst {p3[ 'worst' ]})" if p3 else "" ) )
    for a in report[ "lost_by_arm" ]: lines.append( f"{a[ 'run_name' ] or 'question ' + str( a[ 'question' ] ) + ' ' + a[ 'arm' ]}: lost {a[ 'lost' ]} of limit {a[ 'lost_limit' ]}" )
    p3 = ev[ "sizes" ][ PASS_THREE_SIZE ][ "pass_three" ]
    for q in p3[ "not_probed" ]: lines.append( f"not probed: question {q}" )
    if ev[ "default_size" ] is not None:
        lines.append( f"pass 3 was run at size {PASS_THREE_SIZE} only; sizes 10 and 50 carry no position evidence" )
    for a in report[ "unclean_arms" ]: lines.append( f"not clean: {a[ 'run_name' ]} is {a[ 'status' ]} (stop reason {a[ 'stop_reason' ]})" )
    for c in report[ "canaries" ]:
        lines.append( f"canary {c[ 'run_name' ]}: tripped {c[ 'tripped' ]}; driver agrees {c[ 'agrees' ]}; only here {c[ 'analysis_only' ]}; only driver {c[ 'driver_only' ]}" )
    for q, p in report[ "pages" ].items(): lines.append( f"pages, question {q}: {p[ 'state' ]}" )
    if report[ "cost" ] is not None: lines.append( f"cost per search: mean ${report[ 'cost' ][ 'mean_dollars' ]}" )
    return "\n".join( lines )


def main( argv=None ):
    """
    Read a folder of arm and canary files and print the report.

    Ensures:
        - probe plan files, which end in the plan suffix, are not read as arm files
        - returns 0 after printing, and 2 when the folder holds no arm file
    Raises:
        - ValueError when a canary file has no arm file beside it
    """
    import argparse, json, pathlib
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "folder" )
    folder = pathlib.Path( ap.parse_args( argv ).folder )
    arm_files    = sorted( p for p in folder.glob( "*.json" ) if not p.name.endswith( ( ".canary.json", PROBE_PLAN_SUFFIX ) ) )
    canary_files = sorted( folder.glob( "*.canary.json" ) )
    if not arm_files: print( f"no arm files in {folder}" ); return 2
    pairs = []
    for c in canary_files:
        arm_file = folder / ( c.name[ :-len( ".canary.json" ) ] + ".json" )
        if not arm_file.exists(): raise ValueError( f"{c.name} has no arm file {arm_file.name} beside it" )
        pairs.append( ( json.loads( arm_file.read_text() ), json.loads( c.read_text() ) ) )
    print( render( build_report( [ json.loads( p.read_text() ) for p in arm_files ], pairs ) ) )
    return 0


if __name__ == "__main__":
    raise SystemExit( main() )
