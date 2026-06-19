"""
Prototype: git_loc_delta branch-summary plotter.

R&D exploration to align on visual design before integrating --plot into
src/cosa/repo/run_git_loc_delta.py.

Reads tidy-long CSVs with columns:
  date, file_type, added, deleted, files_touched, commits

Produces a two-panel PNG:
  Top    — aggregate: positive bars (insertions), negative bars (deletions),
           thick black net line overlay
  Bottom — per-file-type signed net line (one line per file_type),
           ordered by total churn magnitude for legend prominence

Writes to: <repo_root>/src/cosa/io/git-delta-analysis/<csv-stem>-plot.png
"""

import argparse
import csv
import os
from collections import defaultdict
from datetime    import datetime
from pathlib     import Path

import matplotlib.dates  as mdates
import matplotlib.pyplot as plt


def load_csv( csv_path ):
    """
    Load tidy-long git-loc-delta CSV.

    Requires:
        - csv_path exists and has header: date, file_type, added, deleted, files_touched, commits

    Ensures:
        - returns list of dicts with typed fields
    """
    rows = []
    with open( csv_path, "r" ) as f:
        reader = csv.DictReader( f )
        for r in reader:
            rows.append( {
                "date"          : datetime.strptime( r[ "date" ], "%Y-%m-%d" ).date(),
                "file_type"     : r[ "file_type" ],
                "added"         : int( r[ "added"         ] ),
                "deleted"       : int( r[ "deleted"       ] ),
                "files_touched" : int( r[ "files_touched" ] ),
                "commits"       : int( r[ "commits"       ] )
            } )
    return rows


def aggregate_by_day( rows ):
    """
    Roll up by date across all file types.

    Ensures:
        - returns sorted list of (date, added_sum, deleted_sum, net_sum)
    """
    by_day = defaultdict( lambda: { "added": 0, "deleted": 0 } )
    for r in rows:
        by_day[ r[ "date" ] ][ "added"   ] += r[ "added"   ]
        by_day[ r[ "date" ] ][ "deleted" ] += r[ "deleted" ]
    return sorted( [
        ( d, v[ "added" ], v[ "deleted" ], v[ "added" ] - v[ "deleted" ] )
        for d, v in by_day.items()
    ] )


def per_type_series( rows ):
    """
    Build per-file-type net series, zero-filling missing days.

    Ensures:
        - returns dict file_type -> list of (date, net_value) over the
          full set of dates seen in rows, in ascending date order
    """
    all_dates    = sorted( { r[ "date" ] for r in rows } )
    by_type_day  = defaultdict( lambda: defaultdict( int ) )
    for r in rows:
        by_type_day[ r[ "file_type" ] ][ r[ "date" ] ] += r[ "added" ] - r[ "deleted" ]

    out = {}
    for ft, day_map in by_type_day.items():
        out[ ft ] = [ ( d, day_map.get( d, 0 ) ) for d in all_dates ]
    return out


def plot_branch_summary( rows, csv_path, output_path ):
    """
    Produce two-panel branch LoC delta plot.

    Layout:
        Top    — aggregate (bars + net line)
        Bottom — per-file-type net signed lines
    """
    daily      = aggregate_by_day( rows )
    per_type   = per_type_series(  rows )

    dates      = [  d[ 0 ] for d in daily ]
    added_v    = [  d[ 1 ] for d in daily ]
    deleted_v  = [ -d[ 2 ] for d in daily ]   # negate for below-zero bars
    net_v      = [  d[ 3 ] for d in daily ]

    fig, ( ax_top, ax_bot ) = plt.subplots(
        nrows       = 2,
        ncols       = 1,
        figsize     = ( 14, 9 ),
        sharex      = True,
        gridspec_kw = { "height_ratios": [ 1, 1 ], "hspace": 0.18 }
    )

    # ── Top: aggregate
    bar_w = 0.7
    ax_top.bar( dates, added_v,   width=bar_w, color="#4CAF50", alpha=0.55, label="Insertions" )
    ax_top.bar( dates, deleted_v, width=bar_w, color="#E53935", alpha=0.55, label="Deletions"  )
    ax_top.plot( dates, net_v,    color="black", linewidth=2.5, marker="o", markersize=4, label="Net" )
    ax_top.axhline( 0, color="#999", linewidth=0.8 )
    ax_top.set_ylabel( "Lines of code" )
    ax_top.set_title( "Aggregate — insertions / deletions / net", loc="left", fontsize=11, fontweight="bold" )
    ax_top.legend( loc="upper left", framealpha=0.9, fontsize=9 )
    ax_top.grid( axis="y", alpha=0.3 )

    # ── Bottom: per-file-type net
    sorted_types = sorted(
        per_type.keys(),
        key = lambda ft: -sum( abs( v ) for _, v in per_type[ ft ] )
    )

    cmap = plt.get_cmap( "tab10" )
    for i, ft in enumerate( sorted_types ):
        d = [ p[ 0 ] for p in per_type[ ft ] ]
        v = [ p[ 1 ] for p in per_type[ ft ] ]
        ax_bot.plot(
            d, v,
            color      = cmap( i % 10 ),
            marker     = "o",
            markersize = 3.5,
            linewidth  = 1.6,
            label      = ft
        )

    ax_bot.axhline( 0, color="#999", linewidth=0.8 )
    ax_bot.set_ylabel( "Lines of code (signed)" )
    ax_bot.set_title( "Per-file-type net (added − deleted)", loc="left", fontsize=11, fontweight="bold" )
    ax_bot.legend( loc="upper left", framealpha=0.9, fontsize=9, ncol=2 )
    ax_bot.grid( axis="y", alpha=0.3 )

    # x-axis: rotate, sensible tick density
    n_days = len( dates )
    ax_bot.xaxis.set_major_locator( mdates.DayLocator( interval=max( 1, n_days // 14 ) ) )
    ax_bot.xaxis.set_major_formatter( mdates.DateFormatter( "%m-%d" ) )
    fig.autofmt_xdate( rotation=45 )

    fig.suptitle(
        f"git_loc_delta — {Path( csv_path ).stem}",
        fontsize   = 13,
        fontweight = "bold",
        y          = 0.995
    )

    plt.savefig( output_path, dpi=120, bbox_inches="tight" )
    plt.close( fig )
    print( f"Plot written: {output_path}" )


def main():
    parser = argparse.ArgumentParser( description="git_loc_delta plotter prototype" )
    parser.add_argument( "csv_path",                            help="Path to tidy-long CSV" )
    parser.add_argument( "--output-dir", default=None,          help="Override output dir" )
    args = parser.parse_args()

    lupin_root = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
    if args.output_dir:
        out_dir = Path( args.output_dir )
    else:
        out_dir = Path( lupin_root ) / "src" / "cosa" / "io" / "git-delta-analysis"
    out_dir.mkdir( parents=True, exist_ok=True )

    out_path = out_dir / f"{Path( args.csv_path ).stem}-plot.png"

    rows = load_csv( args.csv_path )
    plot_branch_summary( rows, args.csv_path, out_path )


if __name__ == "__main__":
    main()
