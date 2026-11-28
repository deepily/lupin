"""
The before-and-after report for the regenerated question vectors.

It shows four runs of the checkpoint analysis side by side.

1. Before: the committed baseline, on the stored vectors.
2. The same asks, replayed separately on regenerated vectors.
3. Every ask, on regenerated vectors.
4. Every ask as neighbours, scored only on the final window of column 1.

Change 1 to 2 is the effect of the new vectors alone. Change 2 to 3 is the effect of the added asks.
Change 3 to 4 is the effect of scoring a different population. Each column names its commit, its vector
source and its ask count. This module only lays the columns side by side. It computes no score.

A column is a dict with these keys:

- label, commit, vector_source, ask_count, threshold, top_k
- coverage: the coverage dict of checkpoint_report.render_report, with scores
- calibration: the report half of calibration_fit.fit_and_evaluate
- yes_no_summary: the replay summary of the predictor against always-yes on yes/no asks
- tune_note: optional; when present every tune figure reads this text instead of a number
- ask_ids: the asks the column replayed
- final_ids: the final-window asks the column scored
- produced_by: optional, the replay code commit and run script that made the column
"""

import argparse
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

COLUMN_KEYS = ( "label", "commit", "vector_source", "ask_count", "threshold", "top_k", "coverage", "calibration", "yes_no_summary", "ask_ids", "final_ids" )
WINDOWS     = ( "tune", "final" )


class ReportMismatch( ValueError ):
    """The four columns do not fit the before-and-after design."""


def check_columns( columns: Sequence[Dict[str, Any]] ) -> None:
    """
    Refuse columns that cannot support the four-way comparison.

    Requires:
        - columns is a sequence of dicts shaped as the module docstring says, in the order before, same asks on
          new vectors, all asks on new vectors, all asks scored on before's final window

    Ensures:
        - returns None only when there are exactly four columns, each with every key, columns one and two hold
          the same ask count, columns three and four hold the same ask count, and those two use the same threshold
          and top k
        - columns one and two name the same asks, every ask of column two is in column three, and columns three
          and four name the same asks
        - columns one and four name the same final-window asks, and each holds as many final-window asks in its
          mix as it names

    Raises:
        - ReportMismatch naming the first problem found
    """
    if len( columns ) != 4: raise ReportMismatch( f"expected 4 columns, got {len( columns )}" )
    for column in columns:
        absent = [ key for key in COLUMN_KEYS if key not in column ]
        if absent: raise ReportMismatch( f"column {column.get( 'label', '?' )!r} lacks {absent}" )
    before, same, after, rescored = columns
    if before[ "ask_count" ] != same[ "ask_count" ]:
        raise ReportMismatch( f"columns 1 and 2 must hold the same asks, got {before[ 'ask_count' ]} and {same[ 'ask_count' ]}" )
    if after[ "ask_count" ] != rescored[ "ask_count" ]:
        raise ReportMismatch( f"columns 3 and 4 must hold the same asks, got {after[ 'ask_count' ]} and {rescored[ 'ask_count' ]}" )
    if ( after[ "threshold" ], after[ "top_k" ] ) != ( rescored[ "threshold" ], rescored[ "top_k" ] ):
        raise ReportMismatch( "columns 3 and 4 must use the same frozen threshold and top k" )
    if set( before[ "ask_ids" ] ) != set( same[ "ask_ids" ] ):
        raise ReportMismatch( "columns 1 and 2 name different asks" )
    if not set( same[ "ask_ids" ] ) <= set( after[ "ask_ids" ] ):
        raise ReportMismatch( "column 3 does not contain every ask of column 2" )
    if set( after[ "ask_ids" ] ) != set( rescored[ "ask_ids" ] ):
        raise ReportMismatch( "columns 3 and 4 name different asks" )
    if set( before[ "final_ids" ] ) != set( rescored[ "final_ids" ] ):
        raise ReportMismatch( "columns 1 and 4 do not score the same final-window asks" )
    for column in ( before, rescored ):
        scored = sum( column[ "coverage" ][ "final_mix" ].values() )
        if scored != len( column[ "final_ids" ] ):
            raise ReportMismatch( f"column {column[ 'label' ]!r} scores {scored} final-window asks but names {len( column[ 'final_ids' ] )}" )


def check_control( committed_final_correct: int, rerun_final_correct: int ) -> None:
    """
    Refuse to trust new figures until the control run reproduces the committed one.

    Requires:
        - both arguments are final-window correct counts at the frozen settings, the second from today's code on stored vectors

    Ensures:
        - returns None when they are equal

    Raises:
        - ReportMismatch naming both counts when they differ
    """
    if committed_final_correct != rerun_final_correct:
        raise ReportMismatch( f"control run gave {rerun_final_correct} final-window correct, the committed report has {committed_final_correct}" )


def column_rows( column: Dict[str, Any] ) -> Dict[str, Any]:
    """
    Flatten one column into labelled figures, in report order.

    Requires:
        - column passed check_columns; its coverage holds tune_mix, final_mix and scores for every type

    Ensures:
        - returns label to figure, a number or a string, never recomputed from another figure here
        - holds the ask count, the frozen threshold and top k, each window's mix, each window's correct count
          and correct per 100 by answer type (n/a for a type with no asks), and beside it the scorable count and correct per 100
          over scorable asks (correct_scorable over scorable) ("not recorded" when the column has no scorable count, n/a for none scorable), the yes/no comparison against always-yes
          (counts, discordant pairs, McNemar p and verdict), and each calibration cell
        - with a tune_note, every figure whose label starts with "tune " reads that note
        - a calibration cell that was not fitted shows its status in place of Brier scores
    """
    coverage = column[ "coverage" ]
    rows: Dict[str, Any] = { "asks": column[ "ask_count" ], "threshold": column[ "threshold" ], "top k": column[ "top_k" ] }
    kinds = sorted( set( coverage[ "tune_mix" ] ) | set( coverage[ "final_mix" ] ) )
    for window in WINDOWS:
        for kind in kinds: rows[ f"{window} asks: {kind}" ] = coverage[ f"{window}_mix" ].get( kind, 0 )
    for window in WINDOWS:
        for kind in kinds:
            score = coverage[ "scores" ][ window ][ kind ]
            rows[ f"{window} correct: {kind}" ]         = score[ "correct" ]
            rows[ f"{window} correct per 100: {kind}" ] = 100.0 * score[ "correct" ] / score[ "asks" ] if score[ "asks" ] > 0 else "n/a"
            if "scorable" not in score or score[ "scorable" ] is None:
                rows[ f"{window} scorable: {kind}" ]                 = "not recorded"
                rows[ f"{window} correct per 100 scorable: {kind}" ] = "not recorded"
                continue
            rows[ f"{window} scorable: {kind}" ]                 = score[ "scorable" ]
            rows[ f"{window} correct per 100 scorable: {kind}" ] = 100.0 * score[ "correct_scorable" ] / score[ "scorable" ] if score[ "scorable" ] > 0 else "n/a"
    summary = column[ "yes_no_summary" ]
    rows[ "yes_no vs always-yes: predictor correct" ]      = summary[ "engine_correct" ]
    rows[ "yes_no vs always-yes: baseline correct" ]       = summary[ "baseline_correct" ]
    rows[ "yes_no vs always-yes: predictor only right" ]   = summary[ "engine_only_right" ]
    rows[ "yes_no vs always-yes: baseline only right" ]    = summary[ "baseline_only_right" ]
    rows[ "yes_no vs always-yes: McNemar exact p" ]        = summary[ "mcnemar" ][ "p_value" ]
    rows[ "yes_no vs always-yes: verdict" ]                = summary[ "verdict" ]
    for key, cell in sorted( column[ "calibration" ][ "cells" ].items() ):
        if cell[ "status" ] == "evaluated":
            rows[ f"calibration {key}: Brier raw" ]        = cell[ "brier_raw" ]
            rows[ f"calibration {key}: Brier calibrated" ] = cell[ "brier_calibrated" ]
        else:
            rows[ f"calibration {key}" ] = cell[ "status" ]
    if "tune_note" in column:
        rows = { name: ( column[ "tune_note" ] if name.startswith( "tune " ) else value ) for name, value in rows.items() }
    return rows


def _shown( value: Any ) -> str:
    """
    Format one figure.

    Requires:
        - value is an int, a float or a string, or None for an absent figure

    Ensures:
        - an int prints whole; a float prints with four decimals when its size is under 1, else one decimal
        - None prints as n/a
    """
    if value is None: return "n/a"
    if isinstance( value, float ): return f"{value:.4f}" if abs( value ) < 1 else f"{value:.1f}"
    return str( value )


def _change( earlier: Any, later: Any ) -> str:
    """
    Show the change from one column's figure to the next.

    Requires:
        - earlier and later are numbers, strings or None

    Ensures:
        - two numbers give a signed difference, in the earlier figure's precision
        - two equal strings give "same", two different strings "changed"
        - a missing figure, or a number against a string, gives n/a
    """
    if earlier is None or later is None: return "n/a"
    numbers = ( int, float )
    if isinstance( earlier, numbers ) and isinstance( later, numbers ):
        delta = later - earlier
        if isinstance( delta, int ): return f"{delta:+d}"
        return f"{delta:+.4f}" if abs( earlier ) < 1 and abs( later ) < 1 else f"{delta:+.1f}"
    if isinstance( earlier, str ) and isinstance( later, str ): return "same" if earlier == later else "changed"
    return "n/a"


def _vector_source( source: Any ) -> str:
    """
    Name a column's vector source on one line.

    Requires:
        - source is a string, or a dict with model and revision

    Ensures:
        - a string is returned as it is; a dict reads "<model> @ <revision>"
    """
    return source if isinstance( source, str ) else f"{source[ 'model' ]} @ {source[ 'revision' ]}"


def render_before_after( columns: Sequence[Dict[str, Any]], title: str = "Before and after: regenerated question vectors", notes: Sequence[str] = () ) -> str:
    """
    Render the four-column report as Markdown.

    Requires:
        - columns passes check_columns: before, same asks on new vectors, all asks on new vectors, all asks
          scored on before's final window

    Ensures:
        - a provenance table gives each column's label, commit, vector source, ask count, scored count (the asks in
          its two windows, read from its mix) and produced_by, or "not stated" when the column has none
        - one comparison table gives every figure in all four columns, then the change between each adjacent pair
        - a figure one column lacks reads n/a, and its changes read n/a
        - a pipe inside a figure name is escaped so the table keeps its columns
        - each note is printed as a bullet under the introduction
        - the same columns and notes give the same text
    """
    check_columns( columns )
    flat = [ column_rows( column ) for column in columns ]
    names: List[str] = []
    for rows in flat:
        names += [ name for name in rows if name not in names ]
    labels = [ column[ "label" ] for column in columns ]
    lines  = [ f"# {title}", "",
               "Change 1 to 2 is the effect of the regenerated vectors alone. Change 2 to 3 is the effect of the added asks."
               " Change 3 to 4 is the effect of scoring only before's final window.", "" ] + [ f"- {note}" for note in notes ] + ( [ "" ] if notes else [] ) + [
               "| column | label | commit | vector source | asks | scored | produced by |", "|---|---|---|---|---|---|---|" ]
    for number, column in enumerate( columns, start=1 ):
        scored = sum( column[ "coverage" ][ "tune_mix" ].values() ) + sum( column[ "coverage" ][ "final_mix" ].values() )
        lines.append( f"| {number} | {column[ 'label' ]} | `{column[ 'commit' ]}` | {_vector_source( column[ 'vector_source' ] )} | {column[ 'ask_count' ]} | {scored} | {column.get( 'produced_by', 'not stated' )} |" )
    lines += [ "", "| figure | " + " | ".join( labels ) + " | change 1 to 2 | change 2 to 3 | change 3 to 4 |", "|---|---|---|---|---|---|---|---|" ]
    for name in names:
        figures = [ rows.get( name ) for rows in flat ]
        changes = [ _change( figures[ i ], figures[ i + 1 ] ) for i in range( 3 ) ]
        lines.append( f"| {name.replace( '|', chr( 92 ) + '|' )} | " + " | ".join( _shown( figure ) for figure in figures ) + " | " + " | ".join( changes ) + " |" )
    lines.append( "" )
    return "\n".join( lines )


def final_correct( column: Dict[str, Any] ) -> int:
    """
    Sum a column's final-window correct forecasts over its answer types.

    Requires:
        - column holds coverage with final-window scores for each type

    Ensures:
        - returns the total correct count
    """
    return sum( score[ "correct" ] for score in column[ "coverage" ][ "scores" ][ "final" ].values() )


def assemble_report( columns: Sequence[Dict[str, Any]], expected_final_correct: Sequence[int], control_final_correct: int, before: Dict[str, Any],
                     notes: Sequence[str] = (), title: str = "Before and after: regenerated question vectors" ) -> str:
    """
    Check the control, set the Before column's provenance and render the report.

    Requires:
        - columns are the four column dicts; before holds the commit and produced_by of the committed baseline
        - expected_final_correct holds the final-window correct count each of columns 1 to 3 must reproduce
        - control_final_correct is the count from the control run on stored vectors; it must equal the first expected count

    Ensures:
        - the control run and each of columns 1 to 3 reproduce their counts, or nothing is rendered
        - column 1 carries the commit and produced_by that before names
        - returns the render of the four columns

    Raises:
        - ReportMismatch naming the column when a count differs, or when the columns do not fit the design
    """
    check_control( expected_final_correct[ 0 ], control_final_correct )
    for number, expected in enumerate( expected_final_correct ):
        if final_correct( columns[ number ] ) != expected:
            raise ReportMismatch( f"column {number + 1} has {final_correct( columns[ number ] )} final-window correct, the expected count is {expected}" )
    return render_before_after( [ dict( columns[ 0 ], **before ) ] + list( columns[ 1: ] ), title, notes )


def main( argv: Optional[Sequence[str]] = None ) -> int:
    """
    Build the committed before-and-after report from the four column files.

    Requires:
        - argv names the four column files in order, the three counts columns 1 to 3 must reproduce, the control report and the output path
        - the control report is a retune report with a grid point at threshold 0.5 and top k 10

    Ensures:
        - writes the Markdown report and returns 0

    Raises:
        - ReportMismatch when the control or a column fails to reproduce its count
    """
    parser = argparse.ArgumentParser( description="Build the before-and-after report from four column files." )
    parser.add_argument( "--columns", nargs=4, required=True )
    parser.add_argument( "--control-report", required=True )
    parser.add_argument( "--expect-final-correct", nargs=3, type=int, required=True, metavar="N", help="the final-window correct count columns 1, 2 and 3 must reproduce" )
    parser.add_argument( "--before-commit", required=True )
    parser.add_argument( "--before-produced-by", required=True )
    parser.add_argument( "--note", action="append", default=[] )
    parser.add_argument( "--out", required=True )
    args = parser.parse_args( argv )
    with open( args.control_report, encoding="utf-8" ) as handle: control = json.load( handle )
    control_correct = next( point for point in control[ "grid_points" ] if point[ "threshold" ] == 0.5 and point[ "top_k" ] == 10 )[ "final_correct" ]
    columns = []
    for path in args.columns:
        with open( path, encoding="utf-8" ) as handle: columns.append( json.load( handle ) )
    text = assemble_report( columns, args.expect_final_correct, control_correct,
                            { "commit": args.before_commit, "produced_by": args.before_produced_by }, args.note )
    with open( args.out, "w", encoding="utf-8" ) as handle: handle.write( text )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    import sys
    sys.exit( main( sys.argv[ 1: ] ) )
