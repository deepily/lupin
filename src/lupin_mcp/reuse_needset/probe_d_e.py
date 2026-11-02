"""
Replay probes d and e over a saved first-thousand control report, with no model call.

Probe d: where the plant stood in each source list and in the fused list, with its purpose line
and without it. It also gives what each list added to the fused score.
Probe e: whether the need's wording overlaps the plant's purpose line more than the original's.
"""

import argparse
import json
import statistics

from cosa.repo.symindex.candidates import rank_fusion as rf

PRESENCE = ( 10, 32, 128 )
SOURCES  = ( "code", "prose", "vector_concat" )


def drafted_rows( report ):
    """
    Give the drafted pair rows of the control stage in a first-thousand report.

    Requires:
        - report is the parsed stage-reports.json, holding stages.control.report.rows

    Ensures:
        - returns the rows whose drafted flag is true, in report order
    """
    return [ row for row in report[ "stages" ][ "control" ][ "report" ][ "rows" ] if row[ "drafted" ] ]


def passes_agree( report ):
    """Ensures: returns True when every pass of the control report repeats the report rows."""
    control = report[ "stages" ][ "control" ][ "report" ]
    return all( one[ "rows" ] == control[ "rows" ] for one in control[ "passes" ] )


def term( place ):
    """
    Give what a list adds to the fused score of an entry standing at a place in it.

    Ensures:
        - returns None for an entry absent from the list
        - returns 1 / ( FUSION_K + place ) for a place inside FUSION_DEPTH, as rank_fusion.fuse adds it
        - returns 0.0 for a place beyond the depth
    """
    if place is None: return None
    return 1.0 / ( rf.FUSION_K + place ) if place <= rf.FUSION_DEPTH else 0.0


def arm_view( reading ):
    """
    Read one arm of a pair: the ranks saved for an entry, and what each list added.

    Requires:
        - reading is { ranks: { code, prose, vector_concat, fused } } as the control report saves it

    Ensures:
        - returns { ranks, terms, total, shares } over the three source lists
        - total sums the terms of the lists that hold the entry, 0.0 when none does
        - a share is its term over total, None for a list that lacks the entry or when total is 0.0
    """
    ranks  = reading[ "ranks" ]
    terms  = { name: term( ranks[ name ] ) for name in SOURCES }
    total  = sum( t for t in terms.values() if t is not None )
    shares = { name: ( None if terms[ name ] is None or total == 0.0 else terms[ name ] / total ) for name in SOURCES }
    return { "ranks": { name: ranks[ name ] for name in ( *SOURCES, "fused" ) }, "terms": terms, "total": total, "shares": shares }


def inside( place, size ):
    """Ensures: returns True when the entry stands at a place no deeper than size."""
    return place is not None and place <= size


def presence( views ):
    """
    Count the entries inside each cut-off, per source list and in the fused list.

    Requires:
        - views are arm_view results

    Ensures:
        - returns { source or fused: { cut-off: count } } for the three cut-offs 10, 32 and 128
    """
    return { name: { size: sum( 1 for v in views if inside( v[ "ranks" ][ name ], size ) ) for size in PRESENCE } for name in ( *SOURCES, "fused" ) }


def mean_shares( views ):
    """
    Average the share each list gave to the fused score.

    Ensures:
        - returns { list name: mean share over the views whose list holds the entry and whose total is above 0, or None if there are none }
    """
    out = {}
    for name in SOURCES:
        held = [ v[ "shares" ][ name ] for v in views if v[ "shares" ][ name ] is not None ]
        out[ name ] = statistics.mean( held ) if held else None
    return out


def newly_inside( pairs, size ):
    """
    List the pairs whose plant is inside the fused cut-off with the line and not without it.

    Requires:
        - pairs are { rewrite, line, bare } with arm_view values for line and bare

    Ensures:
        - returns [ { rewrite, line_sources, bare_sources } ] in pair order
        - line_sources names the lists holding the plant inside size with the line, bare_sources the same without it
    """
    out = []
    for p in pairs:
        if inside( p[ "line" ][ "ranks" ][ "fused" ], size ) and not inside( p[ "bare" ][ "ranks" ][ "fused" ], size ):
            out.append( { "rewrite": p[ "rewrite" ], "line_sources": [ n for n in SOURCES if inside( p[ "line" ][ "ranks" ][ n ], size ) ],
                          "bare_sources": [ n for n in SOURCES if inside( p[ "bare" ][ "ranks" ][ n ], size ) ] } )
    return out


def probe_d( rows ):
    """
    Replay probe d over the drafted rows.

    Requires:
        - rows are drafted pair rows with plant, plant_bare and original readings

    Ensures:
        - returns { pairs, presence, mean_shares, newly_inside } where pairs hold the line, bare and original views of each row
        - presence and mean_shares are given for the plant with its line, the plant without it, and the original
        - newly_inside is given per cut-off 10, 32 and 128
    """
    pairs = [ { "rewrite": r[ "rewrite" ], "same_job": r[ "same_job" ], "lang": r[ "lang" ], "line": arm_view( r[ "plant" ] ),
                "bare": arm_view( r[ "plant_bare" ] ), "original": arm_view( r[ "original" ] ) } for r in rows ]
    arms  = ( "line", "bare", "original" )
    return { "pairs": pairs,
             "presence": { a: presence( [ p[ a ] for p in pairs ] ) for a in arms },
             "mean_shares": { a: mean_shares( [ p[ a ] for p in pairs ] ) for a in arms },
             "newly_inside": { size: newly_inside( pairs, size ) for size in PRESENCE } }


def leak_split( rows ):
    """
    Compare the need's overlap with the plant's line against the original's line.

    Ensures:
        - returns { pairs, plant_higher, tied, original_higher, median_difference, mean_difference }
        - a pair counts only when both overlaps are saved, and its difference is the plant's minus the original's
        - the medians and means are None when no pair counts
    """
    diffs = [ round( r[ "leak" ][ "plant" ] - r[ "leak" ][ "original" ], 3 ) for r in rows if r[ "leak" ][ "plant" ] is not None and r[ "leak" ][ "original" ] is not None ]
    return { "pairs": len( diffs ), "plant_higher": sum( 1 for d in diffs if d > 0 ), "tied": sum( 1 for d in diffs if d == 0 ),
             "original_higher": sum( 1 for d in diffs if d < 0 ),
             "median_difference": statistics.median( diffs ) if diffs else None, "mean_difference": round( statistics.mean( diffs ), 3 ) if diffs else None }


def probe_e( rows ):
    """
    Replay probe e over the drafted rows from the overlaps the report saved.

    Requires:
        - rows are drafted pair rows carrying leak { plant, original }, each a number or None

    Ensures:
        - returns { all, same_job, not_same, pairs } where the first three are leak_split results
        - pairs hold { rewrite, same_job, plant, original } per row, the overlaps as saved
    """
    return { "all": leak_split( rows ), "same_job": leak_split( [ r for r in rows if r[ "same_job" ] ] ),
             "not_same": leak_split( [ r for r in rows if not r[ "same_job" ] ] ),
             "pairs": [ { "rewrite": r[ "rewrite" ], "same_job": r[ "same_job" ], "plant": r[ "leak" ][ "plant" ], "original": r[ "leak" ][ "original" ] } for r in rows ] }


def replay( report ):
    """
    Run both probes over one saved report.

    Ensures:
        - returns { drafted, undrafted, passes_agree, d, e } with the probe results
    """
    rows = drafted_rows( report )
    return { "drafted": len( rows ), "undrafted": len( report[ "stages" ][ "control" ][ "report" ][ "rows" ] ) - len( rows ),
             "passes_agree": passes_agree( report ), "d": probe_d( rows ), "e": probe_e( rows ) }


def cell( value ):
    """Ensures: returns the text of a rank or a number, a dash for None."""
    return "-" if value is None else ( f"{value:.3f}" if isinstance( value, float ) else str( value ) )


def render( result ):
    """
    Write the result as markdown tables.

    Ensures:
        - returns text holding the per-pair ranks, the presence counts, the mean shares, the newly inside pairs and the overlap table
    """
    lines = [ f"{result[ 'drafted' ]} drafted pairs, {result[ 'undrafted' ]} undrafted; the two passes hold identical rows: {result[ 'passes_agree' ]}", "",
              "| pair | same job | line c/p/v/fused | bare c/p/v/fused | original c/p/v/fused |", "|---|---|---|---|---|" ]
    for p in result[ "d" ][ "pairs" ]:
        lines.append( f"| {p[ 'rewrite' ]} | {p[ 'same_job' ]} | " + " | ".join( "/".join( cell( p[ a ][ 'ranks' ][ n ] ) for n in ( *SOURCES, "fused" ) ) for a in ( "line", "bare", "original" ) ) + " |" )
    lines += [ "", "| arm | source | " + " | ".join( f"inside {s}" for s in PRESENCE ) + " |", "|---|---|" + "---|" * len( PRESENCE ) ]
    for arm, table in result[ "d" ][ "presence" ].items():
        for name, counts in table.items(): lines.append( f"| {arm} | {name} | " + " | ".join( str( counts[ s ] ) for s in PRESENCE ) + " |" )
    lines += [ "", "| arm | " + " | ".join( SOURCES ) + " |", "|---|" + "---|" * len( SOURCES ) ]
    for arm, shares in result[ "d" ][ "mean_shares" ].items(): lines.append( f"| {arm} | " + " | ".join( cell( shares[ n ] ) for n in SOURCES ) + " |" )
    for size, entries in result[ "d" ][ "newly_inside" ].items():
        lines += [ "", f"Inside {size} fused with the line and not without it: {len( entries )}" ]
        lines += [ f"- {e[ 'rewrite' ]}: with line {e[ 'line_sources' ]}, without {e[ 'bare_sources' ]}" for e in entries ]
    lines += [ "", "| population | pairs | plant higher | tied | original higher | median difference | mean difference |", "|---|---|---|---|---|---|---|" ]
    for name in ( "all", "same_job", "not_same" ):
        s = result[ "e" ][ name ]
        lines.append( f"| {name} | {s[ 'pairs' ]} | {s[ 'plant_higher' ]} | {s[ 'tied' ]} | {s[ 'original_higher' ]} | {cell( s[ 'median_difference' ] )} | {cell( s[ 'mean_difference' ] )} |" )
    return "\n".join( lines ) + "\n"


def main( argv=None ):
    """
    Read a saved report, replay both probes, write the JSON and print the tables.

    Requires:
        - argv holds --report, a stage-reports.json path, and optionally --out, a JSON path

    Ensures:
        - returns 0 after printing the markdown tables, and writing the result to --out when given
    """
    parser = argparse.ArgumentParser( description="Replay probes d and e over a saved control report." )
    parser.add_argument( "--report", required=True )
    parser.add_argument( "--out" )
    args   = parser.parse_args( argv )
    with open( args.report ) as f: result = replay( json.load( f ) )
    if args.out:
        with open( args.out, "w" ) as f: json.dump( result, f, indent=2, sort_keys=True )
    print( render( result ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point only calls main
    raise SystemExit( main() )
