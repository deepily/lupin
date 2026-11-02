"""
Score the judge-only run against the mark Chloé wrote before any call.

The judge-only run asks the judge about the labelled pairs of the 25 October run, and nothing else.
This module reads that run's stage-c-report.json and prints the figures and levels the mark names.
It makes no model call, no search and no spend-ledger write: it only reads a file and returns numbers.
The mark is io/write-ups/2026.11.02-stage-c-mark-chloe.md; each constant below cites its section.
"""
import argparse
import bisect
import json
import math
import pathlib
import random
import statistics

from lupin_mcp.reuse_e2e import wilson

SAME            = "same_job"
NOT_SAME        = "not_same"
LINE            = 0.30                                    # section 2: the production line; a pair is accepted at this rating or higher
FIXED_LINES     = ( 0.50, 0.70, 0.90 )                    # section 2 item 4: descriptive, fixed, not tuned
SAME_REACH      = 0.80                                    # section 2 item 4: the line where same-job acceptance is this
RESAMPLES       = 10000                                   # section 2 item 1
SEED            = 20261102
REPEATS         = 3                                       # section 1: three judge requests per pair
MIN_PER_CLASS   = 10                                      # section 3: fewer than this in either class gets figures and no level
MAX_LOSS        = 0.15                                    # section 1: drafting may lose at most this share of either class
SIDE_A_SHARE    = 0.95                                    # section 7: share of side-a ratings at the production line or higher
SIDE_A_MEDIAN   = 0.90                                    # section 7: median side-a rating
STRONG          = ( 0.80, 0.70 )                          # section 5: point, lower bound
MODERATE        = ( 0.70, 0.60 )
D_USABLE        = 0.40                                    # section 5: the line level
FALSE_ACCEPT    = 0.50
THRESHOLD_FREE  = ( "inverted", "none shown", "weak", "moderate", "strong" )          # lowest first
LINE_LEVELS     = ( "not usable at the line", "usable" )                              # lowest first
COVERAGE_LIMITED = "coverage-limited"
NO_LEVEL        = "no level"
POPULATIONS     = ( "all_drafted", "without_unsure", "two_agreeing_raters", "without_cue_pairs" )


def mean_ratings( results, side="side_b" ):
    """
    Collect each pair's ratings across its repeats.

    Requires:
        - results are report rows with pair, repeat, stratum, label, unsure, raters, cue and side_b / side_a

    Ensures:
        - returns { pair: { stratum, label, unsure, raters, cue, repeats: { n: p_overlap }, r } } for the side asked
        - r is the mean over the answered repeats, None when no repeat answered
        - a repeat whose side did not answer is left out of repeats
    """
    pairs = { }
    for row in results:
        one = pairs.setdefault( row[ "pair" ], { "stratum": row[ "stratum" ], "label": row[ "label" ], "unsure": row[ "unsure" ], "raters": row[ "raters" ], "cue": row[ "cue" ], "repeats": { } } )
        if row[ side ][ "answered" ]: one[ "repeats" ][ row[ "repeat" ] ] = row[ side ][ "p_overlap" ]
    for one in pairs.values(): one[ "r" ] = statistics.fmean( one[ "repeats" ].values() ) if one[ "repeats" ] else None
    return pairs


def auc_counts( same, other ):
    """
    Count the pairings in which the same-job rating is higher, ties one half.

    Requires:
        - same and other are lists of ratings

    Ensures:
        - returns ( wins, pairings ), wins being a float
    """
    low = sorted( other )
    wins = 0.0
    for r in same: wins += bisect.bisect_left( low, r ) + 0.5 * ( bisect.bisect_right( low, r ) - bisect.bisect_left( low, r ) )
    return wins, len( same ) * len( other )


def split( pairs, key="r" ):
    """
    Group the rated pairs by stratum and class.

    Ensures:
        - returns { stratum: { same_job: [ rating ], not_same: [ rating ] } } over the rated pairs
    """
    out = { }
    for one in pairs:
        if one[ key ] is None: continue
        out.setdefault( one[ "stratum" ], { SAME: [ ], NOT_SAME: [ ] } )[ one[ "label" ] ].append( one[ key ] )
    return out


def aucs( groups ):
    """
    Compute the within-stratum AUC per stratum, the stratum-weighted mean and the pooled AUC.

    Requires:
        - groups is split's result

    Ensures:
        - returns { by_stratum: { stratum: auc or None }, primary, pooled }, each None when no pairing exists
        - primary weights each stratum by its number of pairings, so it equals total wins over total pairings
        - pooled ignores strata: every same-job rating against every not-same rating
    """
    by, wins, total = { }, 0.0, 0
    for name, g in groups.items():
        w, n = auc_counts( g[ SAME ], g[ NOT_SAME ] )
        by[ name ] = w / n if n else None
        wins, total = wins + w, total + n
    every = { SAME: [ r for g in groups.values() for r in g[ SAME ] ], NOT_SAME: [ r for g in groups.values() for r in g[ NOT_SAME ] ] }
    w, n  = auc_counts( every[ SAME ], every[ NOT_SAME ] )
    return { "by_stratum": by, "primary": wins / total if total else None, "pooled": w / n if n else None }


def percentile( values, q ):
    """Ensures: returns the q-th percentile ( 0 to 1 ) of values by interpolation, None for none."""
    if not values: return None
    ordered = sorted( values )
    place   = q * ( len( ordered ) - 1 )
    low     = math.floor( place )
    return ordered[ low ] + ( place - low ) * ( ordered[ min( low + 1, len( ordered ) - 1 ) ] - ordered[ low ] )


def bootstrap( groups, resamples=RESAMPLES, seed=SEED ):
    """
    Give the 95% percentile interval of the primary, pooled and per-stratum AUC.

    Requires:
        - groups is split's result

    Ensures:
        - pairs are resampled with replacement within class and stratum, resamples times, from random.Random( seed )
        - returns { primary, pooled, by_stratum: { stratum: ( low, high ) } }; a figure with no pairing gives ( None, None )
    """
    rng, draws = random.Random( seed ), { "primary": [ ], "pooled": [ ], "by": { s: [ ] for s in groups } }
    for _ in range( resamples ):
        sample = { s: { c: [ rng.choice( g[ c ] ) for _ in g[ c ] ] if g[ c ] else [ ] for c in ( SAME, NOT_SAME ) } for s, g in groups.items() }
        got    = aucs( sample )
        if got[ "primary" ] is not None: draws[ "primary" ].append( got[ "primary" ] )
        if got[ "pooled" ] is not None: draws[ "pooled" ].append( got[ "pooled" ] )
        for s, v in got[ "by_stratum" ].items():
            if v is not None: draws[ "by" ][ s ].append( v )
    span = lambda d: ( percentile( d, 0.025 ), percentile( d, 0.975 ) )
    return { "primary": span( draws[ "primary" ] ), "pooled": span( draws[ "pooled" ] ), "by_stratum": { s: span( d ) for s, d in draws[ "by" ].items() } }


def newcombe( k1, n1, k2, n2 ):
    """
    Give the difference of two proportions with Newcombe's 95% interval.

    Requires:
        - n1 and n2 are above 0

    Ensures:
        - returns { d, low, high } for k1 / n1 minus k2 / n2, from the Wilson intervals of each
    """
    p1, p2     = k1 / n1, k2 / n2
    l1, u1     = wilson( k1, n1 )
    l2, u2     = wilson( k2, n2 )
    d          = p1 - p2
    return { "d": d, "low": d - math.sqrt( ( p1 - l1 ) ** 2 + ( u2 - p2 ) ** 2 ), "high": d + math.sqrt( ( u1 - p1 ) ** 2 + ( p2 - l2 ) ** 2 ) }


def acceptance( same, other, line=LINE ):
    """
    Count the pairs accepted at a line in each class.

    Ensures:
        - returns { same: { k, n, rate, interval }, not_same: { ... }, diff } where accepted means r >= line
        - diff is newcombe's result, None when either class is empty
    """
    side = lambda xs: { "k": sum( 1 for r in xs if r >= line ), "n": len( xs ), "rate": ( sum( 1 for r in xs if r >= line ) / len( xs ) ) if xs else None, "interval": wilson( sum( 1 for r in xs if r >= line ), len( xs ) ) }
    a, b = side( same ), side( other )
    return { "same": a, "not_same": b, "diff": newcombe( a[ "k" ], a[ "n" ], b[ "k" ], b[ "n" ] ) if a[ "n" ] and b[ "n" ] else None }


def reach_line( same, other, reach=SAME_REACH ):
    """
    Give the not-same acceptance at the line where same-job acceptance reaches `reach`.

    Ensures:
        - returns { line, not_same_rate } read from the ratings themselves, so it is fitted on this set
        - returns { line: None, not_same_rate: None } when either class is empty
    """
    if not same or not other: return { "line": None, "not_same_rate": None }
    line = sorted( same, reverse=True )[ math.ceil( reach * len( same ) ) - 1 ]
    return { "line": line, "not_same_rate": sum( 1 for r in other if r >= line ) / len( other ) }


def spread( xs ):
    """Ensures: returns { n, min, q1, median, q3, max, mean } of xs, or { n: 0 } for none."""
    if not xs: return { "n": 0 }
    return { "n": len( xs ), "min": min( xs ), "q1": percentile( xs, 0.25 ), "median": percentile( xs, 0.5 ), "q3": percentile( xs, 0.75 ), "max": max( xs ), "mean": statistics.fmean( xs ) }


def threshold_free_level( point, interval ):
    """
    Name the level of an AUC from the rows of section 5, the first that holds.

    Requires:
        - point is the AUC and interval its ( low, high ) bounds, or point is None

    Ensures:
        - returns one of THRESHOLD_FREE
        - none shown for an AUC that does not exist
    """
    if point is None or interval[ 0 ] is None: return "none shown"
    low, high = interval
    if high < 0.50: return "inverted"
    if point >= STRONG[ 0 ] and low >= STRONG[ 1 ]: return "strong"
    if point >= MODERATE[ 0 ] and low > MODERATE[ 1 ]: return "moderate"
    return "weak" if low > 0.50 else "none shown"


def line_level( accept ):
    """
    Name the level at the production line.

    Requires:
        - accept is acceptance's result

    Ensures:
        - returns usable when D is at least D_USABLE, its Newcombe lower bound is above 0 and the not-same acceptance is at most FALSE_ACCEPT
        - returns not usable at the line otherwise, including when a class is empty
    """
    diff = accept[ "diff" ]
    if diff is None: return LINE_LEVELS[ 0 ]
    return LINE_LEVELS[ 1 ] if diff[ "d" ] >= D_USABLE and diff[ "low" ] > 0 and accept[ "not_same" ][ "rate" ] <= FALSE_ACCEPT else LINE_LEVELS[ 0 ]


def repeat_floor( pairs_by_repeat ):
    """
    Measure the judge's noise from the repeats.

    Requires:
        - pairs_by_repeat is { n: list of { stratum, label, r } } for each repeat, r being that repeat's rating

    Ensures:
        - returns { primary: [ per repeat ], pooled: [ ... ], d: [ ... ], by_stratum: { stratum: [ per repeat ] }, floor_primary, floor_d, floor_by_stratum }
        - a floor is the largest minus the smallest of the repeats' figures, None when a repeat has none
        - a stratum's floor comes from that stratum's own AUC in each repeat
    """
    prim, pool, ds, per = [ ], [ ], [ ], { }
    for n in sorted( pairs_by_repeat ):
        g   = split( pairs_by_repeat[ n ] )
        got = aucs( g )
        for name, value in got[ "by_stratum" ].items(): per.setdefault( name, [ ] ).append( value )
        acc = acceptance( [ r for s in g.values() for r in s[ SAME ] ], [ r for s in g.values() for r in s[ NOT_SAME ] ] )
        prim.append( got[ "primary" ] ); pool.append( got[ "pooled" ] ); ds.append( None if acc[ "diff" ] is None else acc[ "diff" ][ "d" ] )
    gap = lambda xs: ( max( xs ) - min( xs ) ) if xs and None not in xs else None
    return { "primary": prim, "pooled": pool, "d": ds, "by_stratum": per, "floor_primary": gap( prim ), "floor_d": gap( ds ), "floor_by_stratum": { name: gap( v ) for name, v in per.items() } }


def cap_level( level, point, floor ):
    """
    Cap an AUC level by the repeat floor, the same way in both directions.

    Requires:
        - level is one of THRESHOLD_FREE; point is the AUC; floor is the repeat floor or None

    Ensures:
        - a weak, moderate or strong level stands only if ( point - 0.50 ) exceeds the floor, else none shown
        - inverted stands only if ( 0.50 - point ) exceeds the floor, else none shown
        - an unavailable floor ( None ) caps every level but none shown
    """
    margin = point - 0.50 if level in ( "weak", "moderate", "strong" ) else 0.50 - point if level == "inverted" else None
    if margin is None: return level
    return level if floor is not None and margin > floor else "none shown"


def pair_sd_median( pairs ):
    """Ensures: returns the median over pairs of the spread of a pair's ratings, None for none."""
    sds = [ statistics.stdev( p[ "repeats" ].values() ) for p in pairs if len( p[ "repeats" ] ) >= 2 ]
    return statistics.median( sds ) if sds else None


def figures( pairs, by_repeat, resamples=RESAMPLES ):
    """
    Compute every figure of sections 2 to 5 for one population.

    Requires:
        - pairs are mean_ratings' values for side b; by_repeat is { n: [ { stratum, label, r } ] } over the same pairs

    Ensures:
        - returns { counts, auc, interval, accept, descriptive, floor, strata, levels } with per-stratum figures and levels beside the overall ones
        - a stratum with fewer than MIN_PER_CLASS pairs in either class gets figures and level NO_LEVEL
        - the threshold-free level is capped by cap_level with the primary floor; a stratum is capped with its own floor, never the overall one
    """
    groups = split( pairs )
    got    = aucs( groups )
    ci     = bootstrap( groups, resamples )
    every  = { c: [ r for g in groups.values() for r in g[ c ] ] for c in ( SAME, NOT_SAME ) }
    accept = acceptance( every[ SAME ], every[ NOT_SAME ] )
    floor  = repeat_floor( by_repeat )
    level  = cap_level( threshold_free_level( got[ "primary" ], ci[ "primary" ] ), got[ "primary" ], floor[ "floor_primary" ] )
    strata = { }
    for name, g in sorted( groups.items() ):
        a    = acceptance( g[ SAME ], g[ NOT_SAME ] )
        full = len( g[ SAME ] ) >= MIN_PER_CLASS and len( g[ NOT_SAME ] ) >= MIN_PER_CLASS
        own  = floor[ "floor_by_stratum" ][ name ]
        tf   = cap_level( threshold_free_level( got[ "by_stratum" ][ name ], ci[ "by_stratum" ][ name ] ), got[ "by_stratum" ][ name ], own ) if got[ "by_stratum" ][ name ] is not None else "none shown"
        strata[ name ] = { "n": { SAME: len( g[ SAME ] ), NOT_SAME: len( g[ NOT_SAME ] ) }, "auc": got[ "by_stratum" ][ name ], "interval": ci[ "by_stratum" ][ name ], "accept": a, "floor": own,
                           "levels": { "threshold_free": tf, "line": line_level( a ) } if full else { "threshold_free": NO_LEVEL, "line": NO_LEVEL } }
    return { "counts": { SAME: len( every[ SAME ] ), NOT_SAME: len( every[ NOT_SAME ] ) }, "auc": got, "interval": ci, "accept": accept,
             "descriptive": { "fixed_lines": { str( x ): acceptance( every[ SAME ], every[ NOT_SAME ], x ) for x in FIXED_LINES }, "at_same_80": reach_line( every[ SAME ], every[ NOT_SAME ] ),
                              "spread": { SAME: spread( every[ SAME ] ), NOT_SAME: spread( every[ NOT_SAME ] ) } },
             "floor": { **floor, "pair_sd_median": pair_sd_median( pairs ) }, "strata": strata,
             "levels": { "threshold_free": level, "line": line_level( accept ) },
             "consistent": { s: ( strata[ s ][ "auc" ] is not None and strata[ s ][ "auc" ] > 0.50 ) for s in ( "flag", "monolith:structural" ) if s in strata } }


def pearson( xs, ys ):
    """Ensures: returns Pearson's r of two equal lists, None for under two points or no spread."""
    if len( xs ) < 2 or len( set( xs ) ) < 2 or len( set( ys ) ) < 2: return None
    return statistics.correlation( xs, ys )


def side_a_check( a_pairs, b_pairs ):
    """
    Run the side-a sanity check and print the a-to-b correlation.

    Requires:
        - a_pairs and b_pairs are mean_ratings' values for side a and side b, keyed by pair

    Ensures:
        - returns { share_at_line, median, passed, by_stratum, by_class, failing, correlation }
        - passed needs at least 95% of the pairs at the production line or higher and a median of at least 0.90
        - failing lists the pair ids below the production line
        - correlation is the Pearson r between a's and b's ratings per class; it decides nothing
    """
    rated = { k: v for k, v in a_pairs.items() if v[ "r" ] is not None }
    rs    = [ v[ "r" ] for v in rated.values() ]
    share = ( sum( 1 for r in rs if r >= LINE ) / len( rs ) ) if rs else 0.0
    med   = statistics.median( rs ) if rs else None
    cut   = lambda key: { name: spread( [ v[ "r" ] for v in rated.values() if v[ key ] == name ] ) | { "below_line": sum( 1 for v in rated.values() if v[ key ] == name and v[ "r" ] < LINE ) } for name in sorted( { v[ key ] for v in rated.values() } ) }
    both  = { c: [ ( v[ "r" ], b_pairs[ k ][ "r" ] ) for k, v in rated.items() if v[ "label" ] == c and b_pairs[ k ][ "r" ] is not None ] for c in ( SAME, NOT_SAME ) }
    return { "share_at_line": share, "median": med, "passed": bool( rs ) and share >= SIDE_A_SHARE and med >= SIDE_A_MEDIAN, "by_stratum": cut( "stratum" ), "by_class": cut( "label" ),
             "failing": sorted( k for k, v in rated.items() if v[ "r" ] < LINE ), "correlation": { c: pearson( [ x for x, _ in pts ], [ y for _, y in pts ] ) for c, pts in both.items() } }


def refused_row( refused, rated, undrafted ):
    """
    Print the pairs the runner refused as a fixed row, outside the population.

    Requires:
        - refused are { pair, stratum, label, reasons } rows; rated and undrafted give the classes and strata of the judged population

    Ensures:
        - returns { total, by_class_stratum, by_class, by_stratum, by_reason } with a cell for every class and stratum named anywhere, zero where nothing was refused
        - a by_class_stratum cell is { n, reasons: { reason: count } }; a pair with several reasons counts once under each
        - refused pairs are never rated, imputed or counted as misses
    """
    names  = lambda key: sorted( { r[ key ] for r in [ *rated, *undrafted, *refused ] } )
    cells  = { f"{c}/{st}": { "n": 0, "reasons": { } } for c in names( "label" ) for st in names( "stratum" ) }
    reason = { }
    for r in refused:
        cell = cells[ f"{r[ 'label' ]}/{r[ 'stratum' ]}" ]
        cell[ "n" ] += 1
        for why in r[ "reasons" ]:
            cell[ "reasons" ][ why ] = cell[ "reasons" ].get( why, 0 ) + 1
            reason[ why ] = reason.get( why, 0 ) + 1
    return { "total": len( refused ), "by_class_stratum": cells, "by_class": { c: sum( 1 for r in refused if r[ "label" ] == c ) for c in names( "label" ) },
             "by_stratum": { st: sum( 1 for r in refused if r[ "stratum" ] == st ) for st in names( "stratum" ) }, "by_reason": reason }


def coverage( rated, undrafted, refused=() ):
    """
    Report the drafting losses and, beside them, the pairs refused outside the population.

    Requires:
        - rated are the drafted pairs ( mean_ratings' values ); undrafted and refused are { pair, stratum, label } rows
        - refused are pairs the runner would not post at all, such as a side that is not a real record; refused rows carry reasons

    Ensures:
        - returns { by_class, by_stratum, limited, population, refused }
        - each cell of by_class and by_stratum is { drafted, undrafted, lost }; lost is undrafted over drafted plus undrafted, so refused pairs are not in it
        - limited is true when drafting lost more than MAX_LOSS of either class of the judged population
        - population is { judged, of }: the drafted and undrafted pairs, and those plus the refused
        - refused is refused_row's fixed row
    """
    cells = lambda key: { name: { "drafted": sum( 1 for r in rated if r[ key ] == name ), "undrafted": sum( 1 for r in undrafted if r[ key ] == name ) }
                          for name in sorted( { r[ key ] for r in [ *rated, *undrafted ] } ) }
    by_c, by_s = cells( "label" ), cells( "stratum" )
    for table in ( by_c, by_s ):
        for cell in table.values(): cell[ "lost" ] = cell[ "undrafted" ] / ( cell[ "drafted" ] + cell[ "undrafted" ] )
    return { "by_class": by_c, "by_stratum": by_s, "limited": any( c[ "lost" ] > MAX_LOSS for c in by_c.values() ),
             "population": { "judged": len( rated ) + len( undrafted ), "of": len( rated ) + len( undrafted ) + len( refused ) }, "refused": refused_row( refused, rated, undrafted ) }


def valid_run( results ):
    """
    Check the conditions of a valid run.

    Requires:
        - results are the report's rows

    Ensures:
        - returns { valid, posts, distinct_hashes, without_tokens, short_pairs, reasons }
        - valid needs every post to have its own request hash, every post to report tokens ( so none was served from the cache ), every pair to have three repeats, and every status to be answered
    """
    hashes  = [ r[ "request_hash" ] for r in results ]
    per     = { }
    for r in results: per.setdefault( r[ "pair" ], set() ).add( r[ "repeat" ] )
    short   = sorted( p for p, reps in per.items() if len( reps ) < REPEATS )
    bad     = sorted( { r[ "pair" ] for r in results if r[ "status" ] != "answered" or not r[ "side_b" ][ "answered" ] or not r[ "side_a" ][ "answered" ] } )
    notoken = sum( 1 for r in results if not r[ "tokens_in" ] )
    reasons = [ text for text, hit in ( ( "a post shares its request hash with another", len( set( hashes ) ) != len( hashes ) ), ( f"{notoken} posts reported no tokens, so they may be cache reads", notoken > 0 ),
                                        ( f"{len( short )} pairs lack a repeat", bool( short ) ), ( f"{len( bad )} pairs have a post that was not answered", bool( bad ) ), ( "the report has no results", not results ) ) if hit ]
    return { "valid": not reasons, "posts": len( results ), "distinct_hashes": len( set( hashes ) ), "without_tokens": notoken, "short_pairs": short, "unanswered_pairs": bad, "reasons": reasons }


def lowest( levels, order ):
    """Ensures: returns the level of `levels` that comes first in `order`, the lowest."""
    return min( levels, key=order.index )


def population_pairs( pairs, name ):
    """
    Pick the pairs of one population.

    Ensures:
        - all_drafted is every pair; without_unsure drops pairs with an unsure mark; two_agreeing_raters keeps pairs with two raters ( no third rater ); without_cue_pairs drops pairs whose need shares words with the candidate's name
    """
    keep = { "all_drafted": lambda p: True, "without_unsure": lambda p: not p[ "unsure" ], "two_agreeing_raters": lambda p: p[ "raters" ] == 2, "without_cue_pairs": lambda p: not p[ "cue" ] }[ name ]
    return [ p for p in pairs if keep( p ) ]


def score( report, resamples=RESAMPLES ):
    """
    Score a judge-only report against the pre-registered mark.

    Requires:
        - report is the parsed stage-c-report.json: results ( one row per pair and repeat ), undrafted ( pairs with no need ) and, when the runner refused pairs before drafting, refused

    Ensures:
        - returns { coverage, valid_run, side_a, populations, headline }; the headline says how many of the whole set were judged, as covers
        - coverage comes first and, when drafting lost more than 15% of either class of the judged population, no level is awarded
        - refused pairs are printed as a fixed row and kept out of the loss count: they were removed before drafting by a stated rule, so they say nothing about drafting
        - a run that is not valid, or whose side-a check fails, awards no level
        - a report with no refused key is not valid, so a refused list that was never written cannot read as no refusals
        - the headline level is the lowest of the populations' levels; the without_cue_pairs population counts only when some pair carries the cue
        - repeats that the run lacks make the repeat floor, and so any threshold-free level above none shown, unavailable

    Readings where the mark is silent, each open to Chloé's correction ( the floor cap is symmetric, and each stratum has its own floor, by her ruling of 12:25 ):
        - the spread of a pair's ratings is the sample standard deviation, and the side-a to side-b correlation is Pearson's
        - the without-cue population is the fourth population in the lowest-of rule, as the cue check says the headline is also read without those pairs
        - the sanity check and the valid-run conditions block both levels; a pair with no answered side-b rating is left out of the figures
    """
    results = report[ "results" ]
    b, a    = mean_ratings( results, "side_b" ), mean_ratings( results, "side_a" )
    pairs   = [ dict( v, pair=k ) for k, v in b.items() ]
    cover   = coverage( pairs, report[ "undrafted" ], report[ "refused" ] if "refused" in report else [ ] )
    valid   = valid_run( results )
    if "refused" not in report: valid = { **valid, "valid": False, "reasons": [ *valid[ "reasons" ], "the report has no refused list, so a forgotten write would read as no refusals" ] }
    side    = side_a_check( a, b )
    pops    = { }
    for name in POPULATIONS:
        chosen = population_pairs( pairs, name )
        if name == "without_cue_pairs" and len( chosen ) == len( pairs ): continue
        names  = { p[ "pair" ] for p in chosen }
        rep    = { n: [ { "stratum": p[ "stratum" ], "label": p[ "label" ], "r": p[ "repeats" ].get( n ) } for p in chosen ] for n in range( 1, REPEATS + 1 ) }
        pops[ name ] = figures( chosen, rep, resamples ) | { "pairs": len( names ) }
    blocked = [ text for text, hit in ( ( COVERAGE_LIMITED, cover[ "limited" ] ), ( "the run is not valid: " + "; ".join( valid[ "reasons" ] ), not valid[ "valid" ] ),
                                        ( "the judge did not recognise a need's own source", not side[ "passed" ] ) ) if hit ]
    head    = { "covers": f"{cover[ 'population' ][ 'judged' ]} of {cover[ 'population' ][ 'of' ]} pairs judged", "blocked_by": blocked, "threshold_free": NO_LEVEL if blocked else lowest( [ p[ "levels" ][ "threshold_free" ] for p in pops.values() ], THRESHOLD_FREE ),
                "line": NO_LEVEL if blocked else lowest( [ p[ "levels" ][ "line" ] for p in pops.values() ], LINE_LEVELS ) }
    return { "coverage": cover, "valid_run": valid, "side_a": side, "populations": pops, "headline": head }


def parse_args( argv=None ):
    """Ensures: returns the command line: --report, --out, --resamples."""
    ap = argparse.ArgumentParser( description="Score a Stage C report against the pre-registered mark." )
    ap.add_argument( "--report", required=True, help="the run's stage-c-report.json" )
    ap.add_argument( "--out", default=None, help="write the scored JSON here" )
    ap.add_argument( "--resamples", type=int, default=RESAMPLES )
    return ap.parse_args( argv )


def render( scored ):
    """
    Render the refused row, the coverage, the headline and the per-population levels as text.

    Ensures:
        - returns lines that open with the population line and the refused row per class and stratum, with reasons, before any figure
        - then the drafting loss, the blocks, the headline and one row per population
    """
    head, cover = scored[ "headline" ], scored[ "coverage" ]
    gone        = cover[ "refused" ]
    out         = [ f"population {cover[ 'population' ][ 'judged' ]} of {cover[ 'population' ][ 'of' ]}; {gone[ 'total' ]} pairs refused, not judged, outside the population" ]
    for name, cell in gone[ "by_class_stratum" ].items():
        out.append( f"refused {name}: {cell[ 'n' ]}" + ( " " + ", ".join( f"{why} {n}" for why, n in sorted( cell[ "reasons" ].items() ) ) if cell[ "reasons" ] else "" ) )
    out += [ "drafting lost: " + ", ".join( f"{k} {v['undrafted']}/{v['drafted'] + v['undrafted']}" for k, v in cover[ "by_class" ].items() ),
             f"blocked by: {head[ 'blocked_by' ] or 'nothing'}", f"headline: {head[ 'threshold_free' ]} / {head[ 'line' ]} ( {head[ 'covers' ]}; the refused row above is not judged )" ]
    for name, p in scored[ "populations" ].items():
        auc = p[ "auc" ][ "primary" ]
        out.append( f"{name:22} pairs {p[ 'pairs' ]:4} primary AUC {'n/a' if auc is None else f'{auc:.3f}'} levels {p[ 'levels' ][ 'threshold_free' ]} / {p[ 'levels' ][ 'line' ]}" )
    return out


def main( argv=None ):
    """
    Score the report named on the command line and print a summary.

    Ensures:
        - reads the report, prints render's lines, writes the scored JSON when --out is given
        - returns 0
    """
    args   = parse_args( argv )
    scored = score( json.loads( pathlib.Path( args.report ).read_text( encoding="utf-8" ) ), args.resamples )
    for line in render( scored ): print( line )
    if args.out: pathlib.Path( args.out ).write_text( json.dumps( scored, sort_keys=True, indent=4, default=list ) + "\n", encoding="utf-8" )
    return 0


if __name__ == "__main__":
    raise SystemExit( main() )
