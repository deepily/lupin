"""
The read of the four-arm judge run: every figure of plan 17.3 revision 6, from the report.

It reads the report `judge_probe.run_variant` writes (`results[]`, one row per pair, arm and repeat).
When it is given Chloe's cue-list file, a tab-separated file written before any result exists, it also makes the two splits.
It makes no model call, builds no reuse context and writes only the markdown file it is asked for.
It decides nothing beyond the labels the mark defines. It prints the figures, the criteria met and missed, the label, and every pair count it used.
"""
import argparse
import json
import math
import pathlib

from lupin_mcp.reuse_e2e import wilson
from lupin_mcp.reuse_needset import judge_probe as jp

ACCEPT_AT      = 0.30
SIZE_MOVED     = 0.40
MIN_NET_PAIRS  = 2
MAX_SAME_DROP  = 1
NAME_COLUMN    = "name_cue"
NEAR_COLUMN    = "line_near_identical"
YES            = ( "yes", "y", "true", "1" )
NO             = ( "no", "n", "false", "0", "" )
RATING_PLACES  = 6
CRITERIA       = ( "size", "every_repeat", "more_than_one_pair", "not_lower_everywhere", "above_noise" )
MOVED, WORSE, WITHIN, NOISY, NOT_RUN = "moved", "worse", "within noise", "noise-dominated", "not run"
ARM_ORDER      = jp.ARMS
COMPARISONS    = ( ( "N", jp.ARM_PLANT, jp.ARM_SHAPED ), ( "L", jp.ARM_SHAPED, jp.ARM_BOTH ), ( "A", jp.ARM_BASELINE, jp.ARM_PLANT ) )
ORIGINAL_ARMS  = ( jp.ARM_BASELINE, jp.ARM_PLANT, jp.ARM_SHAPED )


def accepted( p ):
    """
    Say whether a plant's p_overlap is accepted.

    Requires:
        - p is a number, the runner's p_overlap, or None for a reading that is missing

    Ensures:
        - returns True when p rounded to six places, as the runner rounds it, is at or above 0.30; a rating of exactly 0.30 is accepted
        - returns False for None
    """
    return p is not None and round( p, RATING_PLACES ) >= ACCEPT_AT


def newcombe( k1, n1, k2, n2 ):
    """
    Give D = k1/n1 - k2/n2 with its Newcombe 95% interval, from the two Wilson intervals.

    Requires:
        - n1 and n2 are positive; k1 and k2 may be fractions, as a mean over repeats is

    Ensures:
        - returns ( D, low, high ), each rounded to six places
    """
    p1, p2         = k1 / n1, k2 / n2
    l1, u1         = wilson( k1, n1 )
    l2, u2         = wilson( k2, n2 )
    d              = p1 - p2
    low, high      = d - math.sqrt( ( p1 - l1 ) ** 2 + ( u2 - p2 ) ** 2 ), d + math.sqrt( ( u1 - p1 ) ** 2 + ( p2 - l2 ) ** 2 )
    return round( d, 6 ), round( low, 6 ), round( high, 6 )


def index_results( results ):
    """
    Lay the report's rows out by arm, repeat and pair.

    Requires:
        - results are rows with pair, label, arm, repeat, request_hash, tokens_in, plant and original, as judge_probe.ask_request writes them

    Ensures:
        - returns { ( arm, repeat ): { pair: row } }
        - a reading that was not answered stays in, with p_overlap None

    Raises:
        - ValueError when a pair appears twice in one arm and repeat, or an arm is not one of the four
    """
    out = {}
    for r in results:
        if r[ "arm" ] not in ARM_ORDER: raise ValueError( f"unknown arm {r[ 'arm' ]!r}" )
        cell = out.setdefault( ( r[ "arm" ], r[ "repeat" ] ), {} )
        if r[ "pair" ] in cell: raise ValueError( f"pair {r[ 'pair' ]} appears twice in {r[ 'arm' ]} repeat {r[ 'repeat' ]}" )
        cell[ r[ "pair" ] ] = r
    return out


def repeats_of( cells, arm ):
    """Ensures: returns the repeat numbers present for the arm, sorted."""
    return sorted( n for ( a, n ) in cells if a == arm )


def figures( rows ):
    """
    Count the plants accepted per label for one arm and repeat, and give D.

    Requires:
        - rows are the cell's rows

    Ensures:
        - returns { same, same_n, not_same, not_same_n, d, low, high } where *_n counts answered readings only, so a missing reading shortens the denominator and is not filled
        - d, low and high are None when either class has no answered reading
    """
    got = { jp.SAME_JOB: [ 0, 0 ], jp.NOT_SAME: [ 0, 0 ] }
    for r in rows:
        if r[ "plant" ][ "answered" ]:
            got[ r[ "label" ] ][ 1 ] += 1
            got[ r[ "label" ] ][ 0 ] += accepted( r[ "plant" ][ "p_overlap" ] )
    ( ks, ns ), ( kn, nn ) = got[ jp.SAME_JOB ], got[ jp.NOT_SAME ]
    d = newcombe( ks, ns, kn, nn ) if ns and nn else ( None, None, None )
    return { "same": ks, "same_n": ns, "not_same": kn, "not_same_n": nn, "d": d[ 0 ], "low": d[ 1 ], "high": d[ 2 ] }


def pairing_share( rows ):
    """
    Give the share of pairings where the same-job plant rates higher than the not-same plant.

    Requires:
        - rows are one cell's rows

    Ensures:
        - ties count one half
        - returns { share, pairings } over answered plants, or share None when either class is empty
    """
    same = [ r[ "plant" ][ "p_overlap" ] for r in rows if r[ "label" ] == jp.SAME_JOB and r[ "plant" ][ "answered" ] ]
    nots = [ r[ "plant" ][ "p_overlap" ] for r in rows if r[ "label" ] == jp.NOT_SAME and r[ "plant" ][ "answered" ] ]
    if not same or not nots: return { "share": None, "pairings": 0 }
    score = sum( 1.0 if s > n else 0.5 if s == n else 0.0 for s in same for n in nots )
    return { "share": round( score / ( len( same ) * len( nots ) ), 6 ), "pairings": len( same ) * len( nots ) }


def duplicate_figures( cells, arm, repeat ):
    """
    Give the second reading for one arm and repeat: a plant or original at 0.30 or higher.

    Requires:
        - cells come from index_results

    Ensures:
        - the original's rating counts for arms 0 to 2 only; in arm 3 the original's own line is also the need's purpose, so its rating is a self-match and only the plant is read
        - returns { same, same_n, not_same, not_same_n, originals_used }
    """
    use   = arm in ORIGINAL_ARMS
    got   = { jp.SAME_JOB: [ 0, 0 ], jp.NOT_SAME: [ 0, 0 ] }
    for r in cells[ ( arm, repeat ) ].values():
        mine = r[ "plant" ][ "answered" ] or ( use and r[ "original" ][ "answered" ] )
        if not mine: continue
        got[ r[ "label" ] ][ 1 ] += 1
        got[ r[ "label" ] ][ 0 ] += accepted( r[ "plant" ][ "p_overlap" ] ) or ( use and accepted( r[ "original" ][ "p_overlap" ] ) )
    return { "same": got[ jp.SAME_JOB ][ 0 ], "same_n": got[ jp.SAME_JOB ][ 1 ], "not_same": got[ jp.NOT_SAME ][ 0 ], "not_same_n": got[ jp.NOT_SAME ][ 1 ], "originals_used": use }


def arm_summary( cells, arm ):
    """
    Summarise one arm over its repeats.

    Requires:
        - the arm has at least one repeat in cells

    Ensures:
        - returns { repeats, by_repeat, d_bar, spread, d_low, d_high, separated }
        - d_bar is the mean D over the repeats that have a D; spread is the largest D minus the smallest
        - d_low and d_high are the Newcombe interval of the mean proportions at the arm's largest class sizes (a reading of the mark: the mark names an interval for the mean and not how it is built)
        - separated is True when d_low and every repeat's low are above 0
    """
    reps   = repeats_of( cells, arm )
    by     = { n: figures( cells[ ( arm, n ) ].values() ) for n in reps }
    ds     = [ f[ "d" ] for f in by.values() if f[ "d" ] is not None ]
    if not ds: return { "repeats": reps, "by_repeat": by, "d_bar": None, "spread": None, "d_low": None, "d_high": None, "separated": False }
    full   = [ f for f in by.values() if f[ "d" ] is not None ]
    ns, nn = max( f[ "same_n" ] for f in full ), max( f[ "not_same_n" ] for f in full )
    ks     = sum( f[ "same" ] / f[ "same_n" ] for f in full ) / len( full ) * ns
    kn     = sum( f[ "not_same" ] / f[ "not_same_n" ] for f in full ) / len( full ) * nn
    _, lo, hi = newcombe( ks, ns, kn, nn )
    return { "repeats": reps, "by_repeat": by, "d_bar": round( sum( ds ) / len( ds ), 6 ), "spread": round( max( ds ) - min( ds ), 6 ), "d_low": lo, "d_high": hi,
             "separated": lo > 0 and all( f[ "low" ] > 0 for f in full ) }


def pair_status( cells, arm, pair ):
    """
    Say whether a pair's plant counts as accepted in an arm.

    Requires:
        - cells come from index_results

    Ensures:
        - returns True when the plant is accepted in a strict majority of the arm's repeats that answered it (2 of 3 with three), False when not, None when no repeat answered it
    """
    seen = [ cells[ ( arm, n ) ][ pair ][ "plant" ][ "p_overlap" ] for n in repeats_of( cells, arm ) if pair in cells[ ( arm, n ) ] and cells[ ( arm, n ) ][ pair ][ "plant" ][ "answered" ] ]
    if not seen: return None
    return sum( accepted( p ) for p in seen ) * 2 > len( seen )


def moves( cells, early, late, pairs ):
    """
    Count the pairs that move toward separation between two arms, by pair status.

    Requires:
        - pairs maps pair id to label

    Ensures:
        - a not-same plant accepted to rejected, or a same-job plant rejected to accepted, is +1; the reverse is -1
        - returns { net, toward, away, same_late, same_early, n } over the pairs that have a status in both arms
    """
    toward = away = same_late = same_early = n = 0
    for pair, label in sorted( pairs.items() ):
        a, b = pair_status( cells, early, pair ), pair_status( cells, late, pair )
        if a is None or b is None: continue
        n += 1
        if label == jp.SAME_JOB:
            same_early += a; same_late += b
            toward += ( not a ) and b; away += a and ( not b )
        else:
            toward += a and ( not b ); away += ( not a ) and b
    return { "net": toward - away, "toward": toward, "away": away, "same_late": same_late, "same_early": same_early, "n": n }


def compare( name, early, late, cells, floor, pairs ):
    """
    Score one comparison against the five conditions of the mark.

    Requires:
        - floor is { spread, valid } for arm 0: its spread in D, and whether the proof allows it to stand as a floor

    Ensures:
        - returns { name, early, late, delta, criteria, met, label, n_pairs, moves }
        - the label is one of worse, moved, within noise, noise-dominated, not run, in that order of test: not run when the floor is not valid or an arm has no D; worse when delta is at most -0.40 and every later D is below every earlier D; noise-dominated when the floor is 0.40 or more; moved when all five hold; else within noise
        - the five conditions are size (delta >= 0.40), every repeat agrees (the lowest later D above the highest earlier D), more than one pair (net >= 2 by status), not lower everywhere (same-job accepted by status at most 1 below), and above the noise floor (delta larger than arm 0's spread)
    """
    a, b = arm_summary( cells, early ), arm_summary( cells, late )
    base = { "name": name, "early": early, "late": late }
    if a[ "d_bar" ] is None or b[ "d_bar" ] is None or not floor[ "valid" ]:
        return { **base, "delta": None, "criteria": {}, "met": [], "label": NOT_RUN, "n_pairs": 0, "moves": None }
    delta = round( b[ "d_bar" ] - a[ "d_bar" ], 6 )
    ds_a  = [ f[ "d" ] for f in a[ "by_repeat" ].values() if f[ "d" ] is not None ]
    ds_b  = [ f[ "d" ] for f in b[ "by_repeat" ].values() if f[ "d" ] is not None ]
    mv    = moves( cells, early, late, pairs )
    crit  = { "size": delta >= SIZE_MOVED, "every_repeat": min( ds_b ) > max( ds_a ), "more_than_one_pair": mv[ "net" ] >= MIN_NET_PAIRS,
              "not_lower_everywhere": mv[ "same_late" ] >= mv[ "same_early" ] - MAX_SAME_DROP, "above_noise": delta > floor[ "spread" ] }
    met   = [ c for c in CRITERIA if crit[ c ] ]
    if delta <= -SIZE_MOVED and max( ds_b ) < min( ds_a ): label = WORSE
    elif floor[ "spread" ] >= SIZE_MOVED: label = NOISY
    elif len( met ) == len( CRITERIA ): label = MOVED
    else: label = WITHIN
    return { **base, "delta": delta, "criteria": crit, "met": met, "label": label, "n_pairs": mv[ "n" ], "moves": mv }


def flips( cells, early, late ):
    """
    List, per repeat number, the plants that flip between two arms.

    Requires:
        - cells come from index_results; repeat numbers carry no meaning, so a flip pairs the same repeat number only for display

    Ensures:
        - returns { repeat: { accept_to_reject, reject_to_accept, rows } } per class counts and rows { pair, label, early_p, late_p, flip }
    """
    out = {}
    for n in sorted( set( repeats_of( cells, early ) ) & set( repeats_of( cells, late ) ) ):
        rows, count = [], { jp.SAME_JOB: [ 0, 0 ], jp.NOT_SAME: [ 0, 0 ] }
        for pair, r in sorted( cells[ ( early, n ) ].items() ):
            other = cells[ ( late, n ) ].get( pair )
            if other is None or not r[ "plant" ][ "answered" ] or not other[ "plant" ][ "answered" ]: continue
            was, now = accepted( r[ "plant" ][ "p_overlap" ] ), accepted( other[ "plant" ][ "p_overlap" ] )
            flip = "accept_to_reject" if was and not now else "reject_to_accept" if now and not was else None
            if flip: count[ r[ "label" ] ][ 0 if flip == "accept_to_reject" else 1 ] += 1
            rows.append( { "pair": pair, "label": r[ "label" ], "early_p": r[ "plant" ][ "p_overlap" ], "late_p": other[ "plant" ][ "p_overlap" ], "flip": flip } )
        out[ n ] = { "accept_to_reject": { k: v[ 0 ] for k, v in count.items() }, "reject_to_accept": { k: v[ 1 ] for k, v in count.items() }, "rows": rows }
    return out


def read_cues( path ):
    """
    Read the cue-list file, one row per pair.

    A row says whether the plant's name carries a cue and whether the two purpose lines are near-identical.

    Requires:
        - path is a tab-separated file; the first column is the pair id; an optional header row names the columns
        - with a header, the columns are the ones named exactly name_cue and line_near_identical; without one, columns 2 and 3
        - a value is yes, y, true or 1 for a cue, and no, n, false, 0 or empty for none, in any case

    Ensures:
        - returns { pair: { name_cue, near_identical } } with booleans; other columns are ignored

    Raises:
        - ValueError naming the line for a row with too few columns or a value that is neither a yes nor a no, or the header when it lacks a column
    """
    lines = [ ln for ln in pathlib.Path( path ).read_text( encoding="utf-8" ).splitlines() if ln.strip() ]
    cols  = [ 1, 2 ]
    if lines and lines[ 0 ].split( "\t" )[ 0 ].strip().lower() in ( "pair", "pair_id", "id" ):
        head = [ h.strip().lower() for h in lines.pop( 0 ).split( "\t" ) ]
        if NAME_COLUMN not in head or NEAR_COLUMN not in head: raise ValueError( f"the header {head!r} lacks a {NAME_COLUMN} column or a {NEAR_COLUMN} column" )
        cols = [ head.index( NAME_COLUMN ), head.index( NEAR_COLUMN ) ]
    out = {}
    for n, ln in enumerate( lines, 1 ):
        cells = [ c.strip() for c in ln.split( "\t" ) ]
        if len( cells ) <= max( cols ): raise ValueError( f"line {n} of the cue file has {len( cells )} columns: {ln!r}" )
        got = []
        for c in cols:
            v = cells[ c ].lower()
            if v not in YES + NO: raise ValueError( f"line {n} of the cue file has {cells[ c ]!r}, which is neither yes nor no" )
            got.append( v in YES )
        out[ cells[ 0 ] ] = { "name_cue": got[ 0 ], "near_identical": got[ 1 ] }
    return out


def proof_of( results ):
    """
    Give the proof that the posts were fresh and separate.

    Ensures:
        - returns { posts, distinct_hashes, every_hash_distinct, with_tokens, without_tokens, arm0_all_fresh, missing_readings }
        - arm0_all_fresh is True when there is an arm 0 row and none of them was answered with no tokens, which is what a cache read looks like
        - an arm 0 row that failed and was not answered does not void the floor; it stays in missing_readings, and the spread is then over fewer repeats
        - missing_readings lists { pair, arm, repeat } for a plant or original that was not answered
    """
    hashes = [ r[ "request_hash" ] for r in results ]
    arm0   = [ r for r in results if r[ "arm" ] == jp.ARM_BASELINE ]
    return { "posts": len( results ), "distinct_hashes": len( set( hashes ) ), "every_hash_distinct": len( set( hashes ) ) == len( results ),
             "with_tokens": sum( 1 for r in results if r[ "tokens_in" ] ), "without_tokens": sum( 1 for r in results if not r[ "tokens_in" ] ),
             "arm0_all_fresh": bool( arm0 ) and not any( ( r[ "plant" ][ "answered" ] or r[ "original" ][ "answered" ] ) and not r[ "tokens_in" ] for r in arm0 ),
             "missing_readings": [ { "pair": r[ "pair" ], "arm": r[ "arm" ], "repeat": r[ "repeat" ], "side": s } for r in results for s in ( "plant", "original" ) if not r[ s ][ "answered" ] ] }


def analyze( report, cues=None ):
    """
    Compute every figure of the mark from a report.

    Requires:
        - report is a judge_probe variant report with results; cues is None or read_cues' result

    Ensures:
        - returns { proof, floor, arms, comparisons, pairing, second_reading, flips, splits }
        - floor is { spread, valid }: arm 0's spread, valid only when every arm 0 post was fresh and every post had its own body
        - comparisons holds N, L and A each once, scored alone, with no joint label
        - splits holds, when cues are given, the name-cue and near-identical-line lists as written and the N and L comparisons recomputed without those pairs; they decide no label
        - a run with no results returns arms, comparisons and the rest empty, never an error
    """
    results = report[ "results" ]
    cells   = index_results( results )
    pairs   = { r[ "pair" ]: r[ "label" ] for r in results }
    proof   = proof_of( results )
    arms    = { a: arm_summary( cells, a ) for a in ARM_ORDER if repeats_of( cells, a ) }
    zero    = arms.get( jp.ARM_BASELINE )
    floor   = { "spread": zero[ "spread" ] if zero and zero[ "spread" ] is not None else 0.0, "valid": bool( zero and zero[ "spread" ] is not None ) and proof[ "arm0_all_fresh" ] and proof[ "every_hash_distinct" ] }
    comps   = [ compare( n, e, l, cells, floor, pairs ) for n, e, l in COMPARISONS if e in arms and l in arms ]
    out     = { "proof": proof, "floor": floor, "arms": arms, "comparisons": comps, "pairs": len( pairs ),
                "pairing": { f"{a}/{n}": pairing_share( cells[ ( a, n ) ].values() ) for ( a, n ) in sorted( cells ) },
                "second_reading": { f"{a}/{n}": duplicate_figures( cells, a, n ) for ( a, n ) in sorted( cells ) },
                "flips": { name: flips( cells, e, l ) for name, e, l in COMPARISONS if e in arms and l in arms }, "splits": None }
    if cues is not None: out[ "splits" ] = splits_of( cells, cues, floor, pairs, arms )
    return out


def splits_of( cells, cues, floor, pairs, arms ):
    """
    Recompute N without the name-cue pairs and L without the near-identical-line pairs.

    Requires:
        - cues come from read_cues and hold a row for every pair in the report

    Ensures:
        - returns { name_cue, near_identical, N_without, L_without } with the two pair lists as Chloe wrote them
        - a split decides no label; the pairs left out are named, and the comparison's own pair count is stated in n_pairs
        - a comparison whose arms are not both present is None

    Raises:
        - ValueError naming the pairs of the report that the cue file has no row for
    """
    absent = sorted( set( pairs ) - set( cues ) )
    if absent: raise ValueError( f"the cue file has no row for {len( absent )} pairs of the report: {absent}" )
    cued = sorted( p for p in pairs if cues[ p ][ "name_cue" ] )
    near = sorted( p for p in pairs if cues[ p ][ "near_identical" ] )
    keep = lambda dropped: { p: lab for p, lab in pairs.items() if p not in dropped }
    wo   = lambda name, early, late, dropped: compare( name, early, late, filtered( cells, dropped ), floor, keep( dropped ) ) if early in arms and late in arms else None
    return { "name_cue": cued, "near_identical": near, "N_without": wo( "N", jp.ARM_PLANT, jp.ARM_SHAPED, cued ), "L_without": wo( "L", jp.ARM_SHAPED, jp.ARM_BOTH, near ) }


def filtered( cells, dropped ):
    """Ensures: returns cells without the dropped pairs, the argument unchanged."""
    return { k: { p: r for p, r in v.items() if p not in dropped } for k, v in cells.items() }


def render( a ):
    """
    Write the analysis as markdown.

    Requires:
        - a comes from analyze

    Ensures:
        - returns the text: the proof, the floor, D per arm and repeat, the three comparisons with their criteria, the second reading, the pairing share, the flips and the splits
        - no joint label and no pass flag is printed
    """
    f, L = a[ "floor" ], []
    p    = a[ "proof" ]
    L += [ "# Four-arm judge run: the read (plan 17.3 revision 6)", "", f"Pairs: {a[ 'pairs' ]}. Posts: {p[ 'posts' ]}, distinct hashes: {p[ 'distinct_hashes' ]}, with tokens: {p[ 'with_tokens' ]}, without: {p[ 'without_tokens' ]}.",
           f"Arm 0 all fresh: {p[ 'arm0_all_fresh' ]}. Missing readings: {len( p[ 'missing_readings' ] )}. Noise floor (arm 0 spread in D): {f[ 'spread' ]}; valid: {f[ 'valid' ]}.", "",
           "## D per arm and repeat", "", "| arm | repeat | same accepted | not-same accepted | D | Newcombe 95% |", "|---|---|---|---|---|---|" ]
    for arm, s in a[ "arms" ].items():
        for n, g in s[ "by_repeat" ].items(): L.append( f"| {arm} | {n} | {g[ 'same' ]} of {g[ 'same_n' ]} | {g[ 'not_same' ]} of {g[ 'not_same_n' ]} | {g[ 'd' ]} | {g[ 'low' ]} to {g[ 'high' ]} |" )
        L.append( f"| **{arm}** | mean | | | **{s[ 'd_bar' ]}** | {s[ 'd_low' ]} to {s[ 'd_high' ]}; spread {s[ 'spread' ]}; separated: {s[ 'separated' ]} |" )
    L += [ "", "## Comparisons, each read alone", "", "| comparison | later minus earlier | delta | met | label |", "|---|---|---|---|---|" ]
    for c in a[ "comparisons" ]: L.append( f"| {c[ 'name' ]} | {c[ 'late' ]} - {c[ 'early' ]} | {c[ 'delta' ]} | {', '.join( c[ 'met' ] ) or 'none'} | **{c[ 'label' ]}** (n pairs {c[ 'n_pairs' ]}) |" )
    L += [ "", "## Second reading (plant or original at 0.30 or more; originals from arms 0 to 2 only; arm 3 is the plant only, so do not compare it with arms 0 to 2)", "", "| arm/repeat | same | not-same | originals used |", "|---|---|---|---|" ]
    for k, g in a[ "second_reading" ].items(): L.append( f"| {k} | {g[ 'same' ]} of {g[ 'same_n' ]} | {g[ 'not_same' ]} of {g[ 'not_same_n' ]} | {g[ 'originals_used' ]} |" )
    L += [ "", "## Threshold-free share (same-job plant rates higher; not a mark figure)", "", "| arm/repeat | share | pairings |", "|---|---|---|" ]
    for k, g in a[ "pairing" ].items(): L.append( f"| {k} | {g[ 'share' ]} | {g[ 'pairings' ]} |" )
    L += [ "", "## Flips per comparison and repeat", "" ]
    for name, by in a[ "flips" ].items():
        for n, g in by.items():
            L += [ f"**{name}, repeat {n}:** accept to reject {g[ 'accept_to_reject' ]}, reject to accept {g[ 'reject_to_accept' ]}", "", "| pair | label | earlier p | later p | flip |", "|---|---|---|---|---|" ]
            L += [ f"| {r[ 'pair' ]} | {r[ 'label' ]} | {r[ 'early_p' ]} | {r[ 'late_p' ]} | {r[ 'flip' ] or ''} |" for r in g[ "rows" ] ] + [ "" ]
    s = a[ "splits" ]
    if s is not None:
        L += [ "## Splits (decide no label)", "", f"Name-cue pairs (Chloe's list): {s[ 'name_cue' ]}", f"Near-identical purpose-line pairs (Chloe's list): {s[ 'near_identical' ]}" ]
        for key in ( "N_without", "L_without" ):
            c = s[ key ]
            L.append( f"- {key}: " + ( "arm missing" if c is None else f"delta {c[ 'delta' ]}, label {c[ 'label' ]}, n pairs {c[ 'n_pairs' ]}" ) )
    return "\n".join( L ) + "\n"


def parse_args( argv ):
    """Ensures: returns the namespace with report (required), cues (optional) and out (optional)."""
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "--report", required=True )
    ap.add_argument( "--cues", default=None )
    ap.add_argument( "--out", default=None )
    return ap.parse_args( argv )


def main( argv=None, out=print ):
    """
    Read a report and print or write the read.

    Ensures:
        - makes no model call and reads only the report and the optional cue file
        - writes the markdown to --out when given, else prints it; returns 0
    """
    args   = parse_args( argv )
    report = json.loads( pathlib.Path( args.report ).read_text( encoding="utf-8" ) )
    cues   = read_cues( args.cues ) if args.cues else None
    text   = render( analyze( report, cues ) )
    if args.out: pathlib.Path( args.out ).write_text( text, encoding="utf-8" )
    else: out( text )
    return 0


if __name__ == "__main__":  # pragma: no cover  reason: the command line entry; main is tested
    import sys
    sys.exit( main( sys.argv[ 1: ] ) )
