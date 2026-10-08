"""
The threshold-fitting script for the labelled-pair run.

It reads the rows of the run and fits four cut-offs of the new question on the fit half only.
It shows the same figures on the check half. It also fits the one cut-off of the old question.

The rate of false reuse it may tolerate is a required argument with no default. Nothing is fitted on a
number nobody chose. No model is called, and nothing is written except the report on the console.
"""
import argparse
import itertools
import json
import pathlib

from cosa.repo.symindex import stage2_split as ss

FORMAT    = "stage2-fit-1"
SHORTLIST = 10                                                # the shortlist size is not fitted
GRID      = { "reuse"     : ( 0.5, 0.6, 0.7, 0.8, 0.9 ),
              "threshold" : ( 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7 ),
              "floor"     : ( 0.1, 0.2, 0.3, 0.4 ),
              "coverage"  : ( 0.3, 0.5, 0.7 ) }
OLD_CUTS  = ( 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7 )
GRID_NOTE = ( "grid note: widened on 2026-10-08. The first fit chose the old question's lowest cut, 0.3, so the old cuts now start at 0.05 "
              "and the new question's threshold at 0.1." )
BINS      = 10
ROW_KEYS  = ( "member", "candidate", "label", "provides", "coverage", "score", "p_overlap", "malformed", "unasked" )


NOT_BINDING = "the false-reuse rate does not bind at any cut; the cut is not determined by it"


class NoFeasiblePolicy( ValueError ):
    """No grid point keeps false reuse within the allowed rate."""


def twin_map_from_manifest( manifest ):
    """
    Map each member to the ids of its twins.

    Requires:
        - manifest holds exact and near lists of records whose members are dicts with an id
    Ensures:
        - returns { id: set of twin ids }, the union over every cluster and pair the id is in
        - an id is never its own twin
    """
    twins = {}
    for kind in ( "exact", "near" ):
        for rec in manifest[ kind ]:
            ids = [ m[ "id" ] for m in rec[ "members" ] ]
            for i in ids: twins.setdefault( i, set() ).update( j for j in ids if j != i )
    return twins


def rows_from_old( old_rows, twin_map ):
    """
    Turn the old run's rows into rows of the labelled-run format.

    Requires:
        - old_rows are dicts with member, candidate, malformed and p_overlap
    Ensures:
        - label is true when the candidate is one of the member's twins
        - provides, coverage and score are None, and unasked is false
    """
    return [ { "member": r[ "member" ], "candidate": r[ "candidate" ], "label": r[ "candidate" ] in twin_map.get( r[ "member" ], () ),
               "provides": None, "coverage": None, "score": None, "p_overlap": r[ "p_overlap" ], "malformed": r[ "malformed" ], "unasked": False }
             for r in old_rows ]


def check_rows( rows ):
    """
    Refuse rows the fit cannot read.

    Ensures:
        - returns None when every row has every key and each number lies from 0 to 1
    Raises:
        - ValueError naming the row's position and the key or field at fault
    """
    for n, r in enumerate( rows ):
        for k in ROW_KEYS:
            if k not in r: raise ValueError( f"row {n}: missing key {k!r}" )
        for k in ( "provides", "coverage", "p_overlap" ):
            v = r[ k ]
            if v is not None and ( type( v ) not in ( int, float ) or not 0 <= v <= 1 ): raise ValueError( f"row {n}: {k} {v!r} is not a number from 0 to 1" )


def split_rows( rows, halves ):
    """
    Cut rows into the fit half and the check half by their member.

    Requires:
        - halves maps each member id to fit or check
    Ensures:
        - returns ( fit rows, check rows ), each in the input order
    Raises:
        - ValueError for a member the split does not know
    """
    fit, check = [], []
    for r in rows:
        if r[ "member" ] not in halves: raise ValueError( f"member {r[ 'member' ]!r} is not in the split" )
        ( fit if halves[ r[ "member" ] ] == "fit" else check ).append( r )
    return fit, check


def usable( row ):
    """Ensures: returns true when the run answered the row's pair and the answer was readable."""
    return row[ "malformed" ] is None and not row[ "unasked" ] and row[ "provides" ] is not None and row[ "coverage" ] is not None


def _rank( row ): return ( -row[ "provides" ], row[ "candidate" ] )


def shortlist( rows, policy, cap=SHORTLIST ):
    """
    Give the shortlist of one member under a policy.

    Requires:
        - rows are the member's rows; policy has reuse, threshold, floor and coverage
    Ensures:
        - the causal rows are the reuse rows, or else the extend rows, and none when any row was unusable
        - the pool is the causal rows plus every usable row at or above the threshold
        - returns at most cap rows ranked by provides, high to low, then candidate id
        - the causal rows keep their place first, and the best of the others fill what is left
    """
    good   = [ r for r in rows if usable( r ) ]
    reuse  = [ r for r in good if r[ "provides" ] >= policy[ "reuse" ] ]
    extend = [ r for r in good if policy[ "floor" ] <= r[ "provides" ] < policy[ "reuse" ] and r[ "coverage" ] >= policy[ "coverage" ] ]
    causal = [] if len( good ) != len( rows ) else ( reuse or extend )
    ids    = { r[ "candidate" ] for r in causal }
    rest   = sorted( ( r for r in good if r[ "provides" ] >= policy[ "threshold" ] and r[ "candidate" ] not in ids ), key=_rank )
    causal = sorted( causal, key=_rank )
    keep   = causal[ :cap ] + rest[ :max( 0, cap - len( causal ) ) ]
    return sorted( keep, key=_rank )


def evaluate( rows, policy, cap=SHORTLIST ):
    """
    Measure a policy on a set of rows.

    Ensures:
        - returns { members, twins, twins_on_shortlist, hit_at_10, twin_recall, non_twin_rows, false_reuse, false_reuse_rate, unusable }
        - members counts the members with a twin row; an unusable twin row counts as a twin and as a miss
        - false_reuse counts usable non-twin rows at or above the reuse cut; the rate is over all non-twin rows
        - a ratio with nothing to divide by is None
    """
    by_member = {}
    for r in rows: by_member.setdefault( r[ "member" ], [] ).append( r )
    members = twins = found = hits = 0
    for m in sorted( by_member ):
        mine = by_member[ m ]
        n    = sum( 1 for r in mine if r[ "label" ] )
        if not n: continue
        got = sum( 1 for r in shortlist( mine, policy, cap ) if r[ "label" ] )
        members, twins, found, hits = members + 1, twins + n, found + got, hits + ( 1 if got else 0 )
    non_twin = [ r for r in rows if not r[ "label" ] ]
    false    = sum( 1 for r in non_twin if usable( r ) and r[ "provides" ] >= policy[ "reuse" ] )
    return { "members": members, "twins": twins, "twins_on_shortlist": found,
             "hit_at_10": round( hits / members, 6 ) if members else None, "twin_recall": round( found / twins, 6 ) if twins else None,
             "non_twin_rows": len( non_twin ), "false_reuse": false, "false_reuse_rate": round( false / len( non_twin ), 6 ) if non_twin else None,
             "unusable": sum( 1 for r in rows if not usable( r ) ) }


def edges( chosen, grid ):
    """
    Name the chosen values that sit on the edge of their grid.

    Requires:
        - chosen and grid have the same keys, and each grid value is a tuple of numbers
    Ensures:
        - returns [ { key, value, edge } ] in the key order of chosen, edge being lowest or highest
        - a key whose grid has one value is never an edge
    """
    out = []
    for k, v in chosen.items():
        vals = sorted( grid[ k ] )
        if len( vals ) > 1 and v in ( vals[ 0 ], vals[ -1 ] ): out.append( { "key": k, "value": v, "edge": "lowest" if v == vals[ 0 ] else "highest" } )
    return out


def _check_rate( rate ):
    """Raises: ValueError unless rate is a number from 0 to 1."""
    if type( rate ) not in ( int, float ) or not 0 <= rate <= 1: raise ValueError( f"rate must be a number from 0 to 1, got {rate!r}" )


def _check_grid( grid ):
    """Raises: ValueError unless grid has the four keys, each a non-empty tuple in 0 to 1."""
    if set( grid ) != set( GRID ): raise ValueError( f"grid must have exactly the keys {sorted( GRID )}, got {sorted( grid )}" )
    for k, vals in grid.items():
        if not vals or any( type( v ) not in ( int, float ) or not 0 <= v <= 1 for v in vals ): raise ValueError( f"grid {k} must be a non-empty tuple of numbers from 0 to 1, got {vals!r}" )


def _check_fit_rows( rows, halves ):
    """Raises: ValueError for no rows, an unknown member, or a row of the check half."""
    if not rows: raise ValueError( "no rows to fit" )
    check_rows( rows )
    for r in rows:
        if r[ "member" ] not in halves: raise ValueError( f"member {r[ 'member' ]!r} is not in the split" )
        if halves[ r[ "member" ] ] != "fit": raise ValueError( f"member {r[ 'member' ]!r} is in the check half; the fit reads the fit half only" )


def _best( policies, rows, rate ):
    """
    Pick the policy with the most twins on the shortlist among those within the rate.

    Requires:
        - policies come in the order that settles ties: the first of the best wins
    Raises:
        - NoFeasiblePolicy naming the lowest false-reuse rate any policy reached
    """
    table = []
    for p in policies:
        f = evaluate( rows, p )
        table.append( { "policy": p, "figures": f, "feasible": ( f[ "false_reuse_rate" ] or 0 ) <= rate } )
    ok = [ t for t in table if t[ "feasible" ] ]
    if not ok:
        lowest = min( ( t[ "figures" ][ "false_reuse_rate" ] for t in table ), default=None )
        raise NoFeasiblePolicy( f"no grid point keeps false reuse within {rate}; the lowest reachable rate is {lowest}" )
    best = ok[ 0 ]
    for t in ok[ 1: ]:
        if t[ "figures" ][ "twins_on_shortlist" ] > best[ "figures" ][ "twins_on_shortlist" ]: best = t
    return { "chosen": best[ "policy" ], "table": table, "feasible": len( ok ) }


def fit_policy( rows, halves, rate, grid=GRID ):
    """
    Fit the four cut-offs of the new question on the fit half.

    Requires:
        - rate is the false-reuse rate allowed, a number from 0 to 1 that a person chose
        - rows hold only members of the fit half
    Ensures:
        - returns { chosen, table, feasible }; the table lists every point tried, ordered by threshold, reuse, floor, coverage
        - the chosen point has the most twins on the shortlist among those within the rate; ties go to the first in the table order
        - a point whose floor is above its reuse cut is never tried
    Raises:
        - ValueError for a bad rate or grid, no rows, an unknown member, or a row of the check half
        - NoFeasiblePolicy when no point keeps false reuse within the rate
    """
    _check_rate( rate )
    _check_grid( grid )
    _check_fit_rows( rows, halves )
    points = [ { "reuse": r, "threshold": t, "floor": f, "coverage": c }
               for t, r, f, c in itertools.product( sorted( grid[ "threshold" ] ), sorted( grid[ "reuse" ] ), sorted( grid[ "floor" ] ), sorted( grid[ "coverage" ] ) ) if f <= r ]
    return _best( points, rows, rate )


def _old_view( rows ):
    """Ensures: returns the rows with the old overlap standing as provides and coverage zero."""
    return [ { **r, "provides": r[ "p_overlap" ], "coverage": None if r[ "p_overlap" ] is None else 0.0 } for r in rows ]


def _old_policy( cut ): return { "reuse": cut, "threshold": cut, "floor": cut, "coverage": 1.0 }


def fit_old( rows, halves, rate, cuts=OLD_CUTS ):
    """
    Fit the one cut-off of the old question on the fit half.

    Requires:
        - rate and rows as for the new question; rows carry the old overlap
    Ensures:
        - returns { chosen: { cut }, table, feasible }; the cut serves as reuse cut and shortlist threshold alike
        - ties go to the lowest cut
    Raises:
        - the errors of the new question's fit
    """
    _check_rate( rate )
    _check_fit_rows( rows, halves )
    best = _best( [ _old_policy( c ) for c in sorted( cuts ) ], _old_view( rows ), rate )
    return { "chosen": { "cut": best[ "chosen" ][ "reuse" ] }, "feasible": best[ "feasible" ],
             "table": [ { **t, "policy": { "cut": t[ "policy" ][ "reuse" ] } } for t in best[ "table" ] ] }


def reliability( rows, key="provides", bins=BINS ):
    """
    Bin a score against the share of rows that are twins.

    Ensures:
        - returns { bins, unusable }; bins lists every bin from 0 up to 1, an empty bin with n zero and a share of None
        - the top bin includes 1.0
        - a row with no readable score is counted in unusable and in no bin
    """
    out = [ { "low": round( k / bins, 6 ), "high": round( ( k + 1 ) / bins, 6 ), "n": 0, "twins": 0, "share": None } for k in range( bins ) ]
    unusable = 0
    for r in rows:
        if r[ "malformed" ] is not None or r[ "unasked" ] or r[ key ] is None: unusable += 1; continue
        b = out[ min( int( round( r[ key ] * bins, 9 ) ), bins - 1 ) ]
        b[ "n" ] += 1; b[ "twins" ] += 1 if r[ "label" ] else 0
    for b in out:
        if b[ "n" ]: b[ "share" ] = round( b[ "twins" ] / b[ "n" ], 6 )
    return { "bins": out, "unusable": unusable }


def _counts( rows, split, halves ):
    """Ensures: returns, for each half, its groups, members, rows and twin rows."""
    return { h: { "groups": len( split[ h ] ), "members": sum( len( g[ "members" ] ) for g in split[ h ] ),
                  "rows": sum( 1 for r in rows if halves[ r[ "member" ] ] == h ), "twin_rows": sum( 1 for r in rows if halves[ r[ "member" ] ] == h and r[ "label" ] ) }
             for h in ( "fit", "check" ) }


def report( rows, split, rate, grid=GRID, placeholder=False ):
    """
    Fit the new question and read the chosen policy on both halves.

    Requires:
        - split is the record the split module writes; rate is the allowed false-reuse rate
    Ensures:
        - returns { format, rate, placeholder, grid, edges, rate_binds, counts, fit, chosen, on_fit, on_check, reliability }
        - rate_binds is false when every grid point keeps false reuse within the rate
        - edges names each chosen value that sits on the edge of its grid
        - on_check is the chosen policy read on the check half, which the fit never saw
    """
    halves = ss.half_by_member( split )
    check_rows( rows )
    fit_rows, other = split_rows( rows, halves )
    fit = fit_policy( fit_rows, halves, rate, grid )
    return { "format": FORMAT, "rate": rate, "placeholder": placeholder, "grid": grid, "edges": edges( fit[ "chosen" ], grid ), "rate_binds": fit[ "feasible" ] < len( fit[ "table" ] ),
             "counts": _counts( rows, split, halves ), "fit": fit, "chosen": fit[ "chosen" ],
             "on_fit": evaluate( fit_rows, fit[ "chosen" ] ), "on_check": evaluate( other, fit[ "chosen" ] ),
             "reliability": { "fit": reliability( fit_rows ), "check": reliability( other ) } }


def old_report( rows, split, rate, cuts=OLD_CUTS, placeholder=False ):
    """
    Fit the old question and read the chosen cut on both halves.

    Requires:
        - rows carry the old overlap; split and rate as for the new question
    Ensures:
        - returns the same keys as the new question's report, with a cut in place of the four cut-offs
    """
    halves = ss.half_by_member( split )
    check_rows( rows )
    fit_rows, other = split_rows( rows, halves )
    fit    = fit_old( fit_rows, halves, rate, cuts )
    policy = _old_policy( fit[ "chosen" ][ "cut" ] )
    return { "format": FORMAT, "rate": rate, "placeholder": placeholder, "grid": { "cut": tuple( sorted( cuts ) ) }, "edges": edges( fit[ "chosen" ], { "cut": cuts } ), "rate_binds": fit[ "feasible" ] < len( fit[ "table" ] ),
             "counts": _counts( rows, split, halves ), "fit": fit, "chosen": fit[ "chosen" ],
             "on_fit": evaluate( _old_view( fit_rows ), policy ), "on_check": evaluate( _old_view( other ), policy ),
             "reliability": { "fit": reliability( fit_rows, "p_overlap" ), "check": reliability( other, "p_overlap" ) } }


def render( rep ):
    """
    Write a report as plain text.

    Ensures:
        - returns a string with the allowed rate, the grid and its note, the group counts, the chosen policy on both halves and both reliability tables
        - a chosen value on the edge of its grid gets a warning line
        - a rate that binds at no cut gets a warning line with the condition text
    """
    lines = [ f"Threshold fit ({rep[ 'format' ]})", "", f"false-reuse rate allowed: {rep[ 'rate' ]}" + ( " (placeholder)" if rep[ "placeholder" ] else "" ),
              "grid: " + "; ".join( f"{k} {min( v )} to {max( v )} ({len( v )} values)" for k, v in rep[ "grid" ].items() ), GRID_NOTE,
              f"groups: fit {rep[ 'counts' ][ 'fit' ][ 'groups' ]}, check {rep[ 'counts' ][ 'check' ][ 'groups' ]}",
              f"rows: fit {rep[ 'counts' ][ 'fit' ][ 'rows' ]}, check {rep[ 'counts' ][ 'check' ][ 'rows' ]}; points within the rate: {rep[ 'fit' ][ 'feasible' ]} of {len( rep[ 'fit' ][ 'table' ] )}",
              f"chosen on the fit half: {rep[ 'chosen' ]}", f"  {rep[ 'on_fit' ]}", f"same policy on the check half: {rep[ 'chosen' ]}", f"  {rep[ 'on_check' ]}" ]
    if not rep[ "rate_binds" ]: lines.append( f"warning: {NOT_BINDING}" )
    for e in rep[ "edges" ]: lines.append( f"warning: the chosen {e[ 'key' ]} {e[ 'value' ]} is the {e[ 'edge' ]} value of its grid; widen the grid before reading it" )
    for half in ( "fit", "check" ):
        rel = rep[ "reliability" ][ half ]
        lines.append( f"reliability, {half} half ({rel[ 'unusable' ]} rows with no readable score):" )
        for b in rel[ "bins" ]: lines.append( f"  bin {b[ 'low' ]:.1f} to {b[ 'high' ]:.1f}: n {b[ 'n' ]}, twins {b[ 'twins' ]}, share {b[ 'share' ]}" )
    return "\n".join( lines )


def main( argv=None ):
    """
    Fit from a rows file or from the old run's results, and print the report.

    Ensures:
        - returns 0 after printing
        - exactly one of the new rows file and the old results file is given, and the rate is always given
    Raises:
        - SystemExit with code 2 for a missing or conflicting argument
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "--rows" ); ap.add_argument( "--old-results" ); ap.add_argument( "--manifest" ); ap.add_argument( "--split", required=True )
    ap.add_argument( "--rate", type=float, required=True, help="the false-reuse rate allowed; there is no default" )
    ap.add_argument( "--placeholder", action="store_true", help="say in the report that the rate is a placeholder" )
    a = ap.parse_args( argv )
    if ( a.rows is None ) == ( a.old_results is None ): ap.error( "give exactly one of --rows and --old-results" )
    if a.old_results is not None and a.manifest is None: ap.error( "--old-results needs --manifest" )
    split = json.loads( pathlib.Path( a.split ).read_text() )
    if a.rows is not None:
        data = json.loads( pathlib.Path( a.rows ).read_text() )
        rep  = report( data[ "rows" ] if isinstance( data, dict ) else data, split, a.rate, placeholder=a.placeholder )
    else:
        old = json.loads( pathlib.Path( a.old_results ).read_text() )
        rep = old_report( rows_from_old( old[ "rows" ], twin_map_from_manifest( json.loads( pathlib.Path( a.manifest ).read_text() ) ) ), split, a.rate, placeholder=a.placeholder )
    print( render( rep ) )
    return 0


if __name__ == "__main__":
    raise SystemExit( main() )
