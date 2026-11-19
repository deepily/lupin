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
- ask_ids: optional, the asks the column replayed
- final_ids: optional, the final-window asks the column scored
- produced_by: optional, the replay code commit and run script that made the column
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

COLUMN_KEYS = ( "label", "commit", "vector_source", "ask_count", "threshold", "top_k", "coverage", "calibration" )
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
          the same ask count, and columns three and four hold the same ask count
        - when both give ask_ids, columns one and two name the same asks, and every ask of column two is in
          column three; when both give final_ids, columns one and four score the same final-window asks

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
    if _both( before, same, "ask_ids" ) and set( before[ "ask_ids" ] ) != set( same[ "ask_ids" ] ):
        raise ReportMismatch( "columns 1 and 2 name different asks" )
    if _both( same, after, "ask_ids" ) and not set( same[ "ask_ids" ] ) <= set( after[ "ask_ids" ] ):
        raise ReportMismatch( "column 3 does not contain every ask of column 2" )
    if _both( before, rescored, "final_ids" ) and set( before[ "final_ids" ] ) != set( rescored[ "final_ids" ] ):
        raise ReportMismatch( "columns 1 and 4 do not score the same final-window asks" )


def _both( one: Dict[str, Any], two: Dict[str, Any], key: str ) -> bool:
    """
    Say whether two columns both carry an optional key.

    Requires:
        - one and two are column dicts

    Ensures:
        - returns True only when neither value is missing or None
    """
    return one.get( key ) is not None and two.get( key ) is not None


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
          and correct per 100 by answer type, and each calibration cell
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
            rows[ f"{window} correct: {kind}" ]        = score[ "correct" ]
            rows[ f"{window} correct per 100: {kind}" ] = 100.0 * score[ "correct" ] / score[ "asks" ]
    for key, cell in sorted( column[ "calibration" ][ "cells" ].items() ):
        if cell[ "status" ] == "evaluated":
            rows[ f"calibration {key}: Brier raw" ]        = cell[ "brier_raw" ]
            rows[ f"calibration {key}: Brier calibrated" ] = cell[ "brier_calibrated" ]
        else:
            rows[ f"calibration {key}" ] = cell[ "status" ]
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


def render_before_after( columns: Sequence[Dict[str, Any]], title: str = "Before and after: regenerated question vectors" ) -> str:
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
        - the same columns give the same text
    """
    check_columns( columns )
    flat = [ column_rows( column ) for column in columns ]
    names: List[str] = []
    for rows in flat:
        names += [ name for name in rows if name not in names ]
    labels = [ column[ "label" ] for column in columns ]
    lines  = [ f"# {title}", "",
               "Change 1 to 2 is the effect of the regenerated vectors alone. Change 2 to 3 is the effect of the added asks."
               " Change 3 to 4 is the effect of scoring only before's final window.", "",
               "| column | label | commit | vector source | asks | scored | produced by |", "|---|---|---|---|---|---|---|" ]
    for number, column in enumerate( columns, start=1 ):
        scored = sum( column[ "coverage" ][ "tune_mix" ].values() ) + sum( column[ "coverage" ][ "final_mix" ].values() )
        lines.append( f"| {number} | {column[ 'label' ]} | `{column[ 'commit' ]}` | {_vector_source( column[ 'vector_source' ] )} | {column[ 'ask_count' ]} | {scored} | {column.get( 'produced_by', 'not stated' )} |" )
    lines += [ "", "| figure | " + " | ".join( labels ) + " | change 1 to 2 | change 2 to 3 | change 3 to 4 |", "|---|---|---|---|---|---|---|---|" ]
    for name in names:
        figures = [ rows.get( name ) for rows in flat ]
        changes = [ _change( figures[ i ], figures[ i + 1 ] ) for i in range( 3 ) ]
        lines.append( f"| {name} | " + " | ".join( _shown( figure ) for figure in figures ) + " | " + " | ".join( changes ) + " |" )
    lines.append( "" )
    return "\n".join( lines )
