"""
Compare two duplicate-check judge ledgers on the same pairs.

It gives agreement figures with bootstrap intervals, and recall and precision against human labels.
"""
import argparse
import json
import pathlib
import random

from cosa.repo.duplicate_check.judge import FLAG_VERDICTS as FLAGS
from lupin_mcp.reuse_e2e import mcnemar_exact
from lupin_mcp.reuse_needset.stage_c_score import percentile

LEVELS    = ( "distinct", "related", "near_duplicate", "duplicate" )
KEY_PARTS = 6


def read_ledger( path, model_id=None, slot=None ):
    """
    Read one judge ledger into its rulings.

    Requires:
        - path is a judge-ledger.jsonl: an optional binding line, then lines { key, value: { rulings: [ { candidate, verdict } ] } }
        - a key reads semdup|<a>|<b>|<prompt version>|<model id>|<pass>

    Ensures:
        - returns { ( definition key, candidate ): verdict }, the definition key being the key without its model id and pass
        - model_id and slot, when given, keep only the lines of that model and pass; a line whose value holds no rulings is skipped

    Raises:
        - ValueError if a pair is ruled twice among the kept lines, or a key does not have six parts
    """
    out = {}
    for line in pathlib.Path( path ).read_text( encoding="utf-8" ).splitlines():
        row = json.loads( line )
        if "key" not in row: continue
        parts = row[ "key" ].split( "|" )
        if len( parts ) != KEY_PARTS: raise ValueError( f"ledger key has {len( parts )} parts, not {KEY_PARTS}: {row[ 'key' ]}" )
        if model_id is not None and parts[ 4 ] != model_id: continue
        if slot is not None and parts[ 5 ] != str( slot ): continue
        for r in row[ "value" ].get( "rulings", [] ):
            pair = ( "|".join( parts[ :4 ] ), r[ "candidate" ] )
            if pair in out: raise ValueError( f"pair {pair} is ruled twice; pass model_id and slot to pick one pass" )
            out[ pair ] = r[ "verdict" ]
    return out


def paired( first, second ):
    """Return the sorted pairs ruled in both ledgers, and the count ruled in only one."""
    both = sorted( set( first ) & set( second ) )
    return both, len( set( first ) ^ set( second ) )


def _flag( verdict ):
    """Return 1 when the verdict is a flag, else 0."""
    return 1 if verdict in FLAGS else 0


def flag_table( first, second, pairs ):
    """Return ( both flag, only first, only second, neither ) counts over pairs."""
    a = b = c = d = 0
    for p in pairs:
        x, y = _flag( first[ p ] ), _flag( second[ p ] )
        if x and y: a += 1
        elif x: b += 1
        elif y: c += 1
        else: d += 1
    return a, b, c, d


def kappa( table ):
    """
    Return Cohen's kappa of a 2x2 table.

    Ensures:
        - returns None when chance agreement is 1, where kappa is undefined
    """
    a, b, c, d = table
    n          = a + b + c + d
    po         = ( a + d ) / n
    pe         = ( ( a + b ) * ( a + c ) + ( c + d ) * ( b + d ) ) / ( n * n )
    return None if pe == 1 else ( po - pe ) / ( 1 - pe )


def ac1( table ):
    """
    Return Gwet's first-order agreement coefficient of a 2x2 table.

    Ensures:
        - returns ( po - pe ) / ( 1 - pe ), with pe = 2 * pi * ( 1 - pi ) and pi the mean flag rate
        - is always defined, because pe never exceeds 0.5
    """
    a, b, c, d = table
    n          = a + b + c + d
    po         = ( a + d ) / n
    pi         = ( ( 2 * a + b + c ) / 2 ) / n
    pe         = 2 * pi * ( 1 - pi )
    return ( po - pe ) / ( 1 - pe )


def positive_negative( table ):
    """
    Return ( positive agreement, negative agreement ) of a 2x2 table.

    Ensures:
        - positive is 2a / ( 2a + b + c ) and negative is 2d / ( 2d + b + c )
        - a figure with an empty denominator is None
    """
    a, b, c, d = table
    pos        = 2 * a / ( 2 * a + b + c ) if 2 * a + b + c else None
    neg        = 2 * d / ( 2 * d + b + c ) if 2 * d + b + c else None
    return pos, neg


def weighted_kappa( first, second, pairs ):
    """
    Return linearly weighted kappa over the four levels.

    Ensures:
        - returns None when the expected disagreement is zero
    """
    k       = len( LEVELS ) - 1
    index   = { v: i for i, v in enumerate( LEVELS ) }
    n       = len( pairs )
    rows    = [ 0 ] * len( LEVELS )
    cols    = [ 0 ] * len( LEVELS )
    observed = 0.0
    for p in pairs:
        i, j      = index[ first[ p ] ], index[ second[ p ] ]
        rows[ i ] += 1
        cols[ j ] += 1
        observed  += abs( i - j ) / k
    expected = sum( rows[ i ] * cols[ j ] * abs( i - j ) / k for i in range( len( LEVELS ) ) for j in range( len( LEVELS ) ) ) / n
    return None if expected == 0 else 1 - observed / expected


def exact( first, second, pairs ):
    """Return how many pairs have the same verdict word in both ledgers."""
    return sum( 1 for p in pairs if first[ p ] == second[ p ] )


def statistics( first, second, pairs ):
    """Return every agreement figure over pairs as one dict."""
    table    = flag_table( first, second, pairs )
    pos, neg = positive_negative( table )
    return { "kappa": kappa( table ), "ac1": ac1( table ), "positive_agreement": pos, "negative_agreement": neg,
             "weighted_kappa": weighted_kappa( first, second, pairs ), "exact": exact( first, second, pairs ) / len( pairs ),
             "flag_rate_first": ( table[ 0 ] + table[ 1 ] ) / len( pairs ), "flag_rate_second": ( table[ 0 ] + table[ 2 ] ) / len( pairs ) }


def bootstrap( first, second, pairs, draws=2000, seed=0 ):
    """
    Bootstrap every agreement figure, resampling whole definitions.

    Requires:
        - pairs is non-empty; each pair is ( definition key, candidate ); draws >= 1

    Ensures:
        - returns { figure: [ low, high ] }, the 2.5% and 97.5% points of the draws; a draw where a figure is undefined is left out of that figure
        - a figure undefined in every draw reports None
        - the same seed gives the same intervals
    """
    groups = {}
    for p in pairs: groups.setdefault( p[ 0 ], [] ).append( p )
    names  = sorted( groups )
    rng    = random.Random( seed )
    draws_by = {}
    for _ in range( draws ):
        sample = [ p for name in ( rng.choice( names ) for _ in names ) for p in groups[ name ] ]
        for k, v in statistics( first, second, sample ).items():
            if v is not None: draws_by.setdefault( k, [] ).append( v )
    out = {}
    for k in statistics( first, second, pairs ):
        vals   = sorted( draws_by.get( k, [] ) )
        out[ k ] = [ percentile( vals, 0.025 ), percentile( vals, 0.975 ) ] if vals else None
    return out


def against_labels( first, second, pair_map, labels, strata, exclude=() ):
    """
    Score both ledgers against the human labels, as the proof scores them.

    Requires:
        - pair_map is { "<definition key>|<candidate>": label pair key }, the label key written as proof_run.label_key writes it
        - labels is { label pair key: bool }
        - strata is { label pair key: stratum name } for the planted and monolith pairs labelled true; these are the recall denominator
        - exclude is the label pair keys left out of every count, the plant failures

    Ensures:
        - a labelled pair counts as flagged by a ledger when any of its ruled pairs is a flag there; only pairs ruled in both ledgers count
        - a true pair that no ruled pair maps to counts as not found, as in the proof
        - returns { all: block, <stratum>: block }; a block holds for each ledger the true pairs found and recall
        - the all block also holds the flags on labelled pairs, how many are true, and precision
        - every block holds McNemar's test on the pairs where the two flags differ, over that block's pairs, and again over its true pairs alone
        - the first test is biased toward the ledger whose flags chose the labelled pairs, so the true-pairs test is the fair one
        - the all block counts the flagged pairs that carry no label, for each ledger
    """
    skip    = set( exclude )
    flagged = [ {}, {} ]
    unlabelled = [ set(), set() ]
    for text, label_key in pair_map.items():
        defkey, cand = text.rsplit( "|", 1 )
        p            = ( defkey, cand )
        if p not in first or p not in second or label_key in skip: continue
        for i, ledger in enumerate( ( first, second ) ):
            if label_key not in labels:
                if ledger[ p ] in FLAGS: unlabelled[ i ].add( label_key )
                continue
            flagged[ i ][ label_key ] = flagged[ i ].get( label_key, False ) or ledger[ p ] in FLAGS
    out = {}
    for name in [ "all", *sorted( set( strata.values() ) ) ]:
        true  = sorted( k for k, v in strata.items() if name == "all" or v == name )
        pool  = sorted( set( true ) | set( flagged[ 0 ] ) | set( flagged[ 1 ] ) ) if name == "all" else true
        block = { "true_pairs": len( true ) }
        for i, label in enumerate( ( "first", "second" ) ):
            hits = sum( 1 for k in true if flagged[ i ].get( k, False ) )
            block[ label ] = { "found": hits, "recall": hits / len( true ) }
            if name == "all":
                flags = [ k for k in flagged[ i ] if flagged[ i ][ k ] ]
                good  = sum( 1 for k in flags if labels[ k ] )
                block[ label ].update( flags=len( flags ), correct=good, precision=good / len( flags ) if flags else None, unlabelled_flags=len( unlabelled[ i ] ) )
        b = sum( 1 for k in pool if flagged[ 0 ].get( k, False ) and not flagged[ 1 ].get( k, False ) )
        c = sum( 1 for k in pool if flagged[ 1 ].get( k, False ) and not flagged[ 0 ].get( k, False ) )
        block[ "mcnemar" ] = { "pairs": len( pool ), "only_first": b, "only_second": c, "p": mcnemar_exact( b, c ) }
        tb = sum( 1 for k in true if flagged[ 0 ].get( k, False ) and not flagged[ 1 ].get( k, False ) )
        tc = sum( 1 for k in true if flagged[ 1 ].get( k, False ) and not flagged[ 0 ].get( k, False ) )
        block[ "mcnemar_true_pairs" ] = { "pairs": len( true ), "only_first": tb, "only_second": tc, "p": mcnemar_exact( tb, tc ) }
        out[ name ] = block
    return out


def compare( first, second, labels=None, pair_map=None, strata=None, exclude=(), draws=2000, seed=0 ):
    """
    Return the agreement figures with intervals.

    Ensures:
        - adds the label scores when labels, a pair map and strata are all given
    """
    pairs, one_side = paired( first, second )
    if not pairs: raise ValueError( "the two ledgers share no ruled pair" )
    out = { "pairs": len( pairs ), "pairs_in_one_ledger_only": one_side, "definitions": len( { p[ 0 ] for p in pairs } ),
            "figures": statistics( first, second, pairs ), "intervals": bootstrap( first, second, pairs, draws, seed ),
            "flag_table": dict( zip( ( "both", "first_only", "second_only", "neither" ), flag_table( first, second, pairs ) ) ),
            "exact_count": exact( first, second, pairs ) }
    if labels is not None and pair_map is not None and strata is not None: out[ "labels" ] = against_labels( first, second, pair_map, labels, strata, exclude )
    return out


def main( argv=None ):
    """
    Compare two judge ledgers and print the result as JSON.

    Requires:
        - argv holds --first and --second ledger paths, each with an optional --*-model and --*-slot to pick one pass,
          and optionally --labels ( { label pair key: bool } ), --pair-map, --strata and --exclude ( a list of label pair keys ), all JSON files, --draws and --seed

    Ensures:
        - prints one JSON document and returns 0
    """
    ap = argparse.ArgumentParser( description="Compare two duplicate-check judge ledgers." )
    for side in ( "first", "second" ):
        ap.add_argument( f"--{side}", required=True )
        ap.add_argument( f"--{side}-model", default=None )
        ap.add_argument( f"--{side}-slot", default=None )
    for name in ( "labels", "pair-map", "strata", "exclude" ): ap.add_argument( f"--{name}", default=None )
    ap.add_argument( "--draws", type=int, default=2000 )
    ap.add_argument( "--seed", type=int, default=0 )
    a        = ap.parse_args( argv )
    load     = lambda p: None if p is None else json.loads( pathlib.Path( p ).read_text( encoding="utf-8" ) )
    first    = read_ledger( a.first, a.first_model, a.first_slot )
    second   = read_ledger( a.second, a.second_model, a.second_slot )
    print( json.dumps( compare( first, second, load( a.labels ), load( a.pair_map ), load( a.strata ), load( a.exclude ) or (), a.draws, a.seed ), indent=2, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - the command's entry; main is tested directly
    raise SystemExit( main() )
