#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Score the saved typed-reply predictions by kind, with a keyword rule and no model.

Each predicted text and each typed text is sorted into question, defer or other by one rule.
The control names the commonest kind of the typed texts every time. The pairs where both are
questions are saved apart, because only a judge can say whether the same thing is asked.

    cd <tree> && PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/typed_reply_score.py \
        --predictions <typed-reply-predictions.jsonl> --pairs-out <new file>
"""

import argparse
import collections
import json
import re
import sys

from cosa.research.phi4_flash_lite_study.statistics import mcnemar_exact
from cosa.research.preference_replay.archive_replay import read_jsonl
from lupin_mcp.reuse_needset.report_rollup import share

KINDS = ( "question", "defer", "other" )
DEFER = re.compile( r"\b(wait|later|busy|re-?ask|ask (me )?(again|later|tomorrow)|minutes?|tomorrow|hold|not now|in the middle|check back|after)\b", re.I )
QUEST = re.compile( r"\?|\b(why|what|how|which|explain|tell me|don't understand|confus)", re.I )


def kind_of( text ):
    """
    Sort one reply by the keyword rule of the write-in study's addendum.

    Requires:
        - text is a string

    Ensures:
        - returns "defer" when a defer word occurs, else "question" for a question mark or a question word, else "other"
    """
    if DEFER.search( text ): return "defer"
    return "question" if QUEST.search( text ) else "other"


def score_kinds( rows ):
    """
    Compare the kind of each prediction with the kind of the words typed, beside the control.

    Requires:
        - rows is a non-empty list of prediction rows, each with actual and predicted; predicted is None for a field with no prediction

    Ensures:
        - returns { fields, typed, predicted, control, by_kind, model_only, control_only, question_pairs }
        - typed and predicted count the kinds of each side; a missing prediction is counted under no kind and never matches
        - control is the commonest typed kind, ties going to the first of question, defer and other
        - by_kind maps each typed kind to { fields, model, control }, the matches of each
        - model_only and control_only count the fields only one of the two got right
        - question_pairs holds the rows whose typed words and prediction are both questions, in order
    """
    pairs   = [ ( row, kind_of( row[ "actual" ] ), None if row[ "predicted" ] is None else kind_of( row[ "predicted" ] ) ) for row in rows ]
    typed   = collections.Counter( actual for _, actual, _ in pairs )
    control = max( KINDS, key=lambda kind: typed[ kind ] )
    by_kind = { kind: { "fields": typed[ kind ], "model": sum( 1 for _, a, p in pairs if a == kind and p == kind ),
                        "control": typed[ kind ] if kind == control else 0 } for kind in KINDS }
    return { "fields": len( rows ), "typed": dict( typed ), "predicted": dict( collections.Counter( p for _, _, p in pairs if p is not None ) ),
             "control": control, "by_kind": by_kind,
             "model_only"     : sum( 1 for _, a, p in pairs if p == a and a != control ),
             "control_only"   : sum( 1 for _, a, p in pairs if p != a and a == control ),
             "question_pairs" : [ row for row, a, p in pairs if a == p == "question" ] }


def main( argv=None, out=print ):
    """
    Score a predictions file from the command line.

    Requires:
        - argv holds --predictions and --pairs-out, or None to read the process arguments

    Ensures:
        - prints the kind counts, the match rate overall and by typed kind for the model and the control with 95% Wilson
          intervals, and the exact McNemar p of the fields only one of them got right
        - writes the question-to-question rows to --pairs-out, one per line, for a judge; returns 0

    Raises:
        - FileExistsError if --pairs-out already exists
    """
    parser = argparse.ArgumentParser( description="Score typed-reply predictions by kind" )
    for name in ( "--predictions", "--pairs-out" ): parser.add_argument( name, required=True )
    args  = parser.parse_args( argv )
    score = score_kinds( read_jsonl( args.predictions ) )
    with open( args.pairs_out, "x", encoding="utf-8" ) as handle:
        for row in score[ "question_pairs" ]: handle.write( json.dumps( row ) + "\n" )
    total   = score[ "fields" ]
    model   = sum( cell[ "model" ] for cell in score[ "by_kind" ].values() )
    control = score[ "typed" ][ score[ "control" ] ]
    out( f"fields {total}; kinds typed {score[ 'typed' ]}; kinds predicted {score[ 'predicted' ]}; control always says {score[ 'control' ]}" )
    out( "| typed kind | model matches | control matches |" )
    out( "|---|---|---|" )
    out( f"| all | {share( model, total )} | {share( control, total )} |" )
    for kind, cell in score[ "by_kind" ].items(): out( f"| {kind} | {share( cell[ 'model' ], cell[ 'fields' ] )} | {share( cell[ 'control' ], cell[ 'fields' ] )} |" )
    test = mcnemar_exact( score[ "model_only" ], score[ "control_only" ] )
    out( f"only the model right {score[ 'model_only' ]}, only the control right {score[ 'control_only' ]}, exact McNemar p {test[ 'p_value' ]:.4f}" )
    out( f"question-to-question pairs saved for a judge: {len( score[ 'question_pairs' ] )}" )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
