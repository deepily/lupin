#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Forecast the cards of record with the Haiku baseline under the full-answer reply.

Mr. Radio's manager go of 24 Nov 2026 on the principle-learner re-run row: one real-model arm, Haiku only, bounded Claude Code.
The run works on a copy of run 2's archive, so the archive is never written. Run 2's baseline rows for
the record cards are deleted from the copy only; their old result stays in records.jsonl and is read from it.
Scoring is replay_loop._score with the per-field switch on, the same call run 2 made. Plain scoring reads only
the yes/no stance and the multiple-choice labels, so this arm checks the full-answer reply against the old reply.

Run from a seat tree, pinning all three:

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/full_answer_arm.py \
        --archive <run 2 archive.sqlite> --records <run 2 records.jsonl> --work-dir <new folder> [--limit N]
"""

import argparse
import asyncio
import collections
import json
import os
import random
import shutil
import sys
import uuid

from sqlalchemy import MetaData, create_engine
from sqlalchemy.pool import StaticPool

import cosa.research.preference_replay.scratch_db  # noqa: F401  registers the SQLite hooks for JSONB and Vector
from cosa.agents.prediction_engine import context_baseline, full_answer, write_in_outcome
from cosa.agents.prediction_engine.accuracy_comparators import compare_multiple_choice
from cosa.agents.prediction_engine.config import RESPONSE_TYPE_MULTIPLE_CHOICE
from cosa.agents.prediction_engine.principles_forecast import CapGate
from cosa.repo.doc_lint import model_transport
from cosa.rest.db import schema_drift
from cosa.research.preference_replay.archive_replay import locked_sessions, read_jsonl
from cosa.research.preference_replay.replay_loop import _actual_dict, _score, answer_split, multiple_choice_split, paired_wins
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog

WORKERS         = 2
PROGRESS_EVERY  = 100
STOP_HOOK_TITLE = "Stop hook"
OUT_NAME        = "full-answer-arm-per-ask.jsonl"
COPY_NAME       = "archive-copy.sqlite"
LEDGER_NAME     = "ledger.jsonl"
REFUSALS_NAME   = "refusals.jsonl"
SAMPLE_NAME     = "sample.json"


def add_missing_columns( engine, models=( Notification, PredictionLog, PredictionArmForecast ) ):
    """
    Add to a copied archive the nullable columns its tables gained after the archive was made.

    Requires:
        - engine is an engine over the copy
        - models are the mapped classes whose tables are checked, by default the three the full-answer job uses

    Ensures:
        - the gaps are found by schema_drift.find_missing_columns over the tables of models
        - each column the models hold and the table lacks is added as a nullable column of its SQLite type
        - returns the list of "table.column" names added; a copy that is up to date adds none

    Raises:
        - RuntimeError if a missing column is not nullable or a whole table is missing, because the copy would be unreadable by the job
    """
    scope = MetaData()
    for model in models: model.__table__.to_metadata( scope )
    added = []
    for gap in schema_drift.find_missing_columns( engine, scope ):
        if gap[ "kind" ] == schema_drift.KIND_MISSING_TABLE: raise RuntimeError( f"table {gap[ 'table' ]} is missing from the archive" )
        column = scope.tables[ gap[ "table" ] ].columns[ gap[ "column" ] ]
        if not column.nullable: raise RuntimeError( f"{gap[ 'table' ]}.{column.name} is missing from the archive and is not nullable" )
        with engine.begin() as connection: connection.exec_driver_sql( f"ALTER TABLE {gap[ 'table' ]} ADD COLUMN {column.name} {column.type.compile( dialect=engine.dialect )}" )
        added.append( f"{gap[ 'table' ]}.{column.name}" )
    return added


def prepare_copy( archive, work_dir, ids ):
    """
    Copy the archive into the work folder and clear the baseline rows to redo.

    Requires:
        - archive is the path of run 2's archive; work_dir exists; ids are the card ids to forecast, as text

    Ensures:
        - returns the path of the copy; the archive is only read
        - the copy has no baseline-arm row for any id in ids, so the job writes a fresh one
        - the copy gains the nullable columns the models hold and the archive lacks (run 2's archive has no applicability or three_way_shadow column)
        - a copy already in the work folder is left as it is, so a stopped run resumes and the ledger answers the calls already made

    Raises:
        - FileNotFoundError if the archive does not exist
        - RuntimeError as add_missing_columns does
    """
    target = os.path.join( work_dir, COPY_NAME )
    if os.path.exists( target ): return target
    shutil.copyfile( archive, target )
    engine = create_engine( f"sqlite:///{target}" )
    add_missing_columns( engine )
    with engine.begin() as connection:
        for start in range( 0, len( ids ), 500 ):
            part  = [ uuid.UUID( one ).hex for one in ids[ start:start + 500 ] ]
            holds = ",".join( "?" * len( part ) )
            connection.exec_driver_sql( f"DELETE FROM prediction_arm_forecast WHERE arm = ? AND replace( notification_id, '-', '' ) IN ( {holds} )", ( context_baseline.ARM, *part ) )
    engine.dispose()
    return target


class RefusalKeeper( context_baseline.ContextBaseline ):
    """The full-answer baseline that keeps the raw reply of every reply the parser refuses."""

    def __init__( self, *args, **kwargs ):
        """
        Build the baseline as ContextBaseline does, with an empty list of refusals.

        Ensures:
            - self.kept is an empty list
        """
        super().__init__( *args, **kwargs )
        self.kept = []

    def parse( self, text, episode ):
        """
        Parse a reply as ContextBaseline does, keeping the raw reply when the parser refuses it.

        Ensures:
            - a refused reply adds { title, reason, detail, reply } to self.kept and the refusal is raised again unchanged
        """
        try:
            return super().parse( text, episode )
        except full_answer.ReplyRefused as refusal:
            self.kept.append( { "title": episode[ "title" ], "reason": refusal.reason, "detail": str( refusal ), "reply": text } )
            raise


def draw_sample( records, size, seed ):
    """
    Draw a fixed-seed random sample of cards, split by response type in the cohort's shares.

    Requires:
        - records are the cards of record, each with an id and a response_type; size is from 1 to the number of records; seed is an int

    Ensures:
        - each type gets its share of size by largest remainder, ties going to the type that sorts first, and the shares add to size
        - returns { seed, size, counts, ids } with the ids in record order and counts the cards drawn per type
        - the same records, size and seed always give the same ids

    Raises:
        - ValueError if size is not from 1 to the number of records
    """
    if not 1 <= size <= len( records ): raise ValueError( f"sample size {size} is not from 1 to {len( records )}" )
    by_type = collections.defaultdict( list )
    for record in records: by_type[ record[ "response_type" ] ].append( record[ "id" ] )
    kinds   = sorted( by_type )
    quota   = { kind: size * len( by_type[ kind ] ) / len( records ) for kind in kinds }
    counts  = { kind: int( quota[ kind ] ) for kind in kinds }
    for kind in sorted( kinds, key=lambda one: ( -( quota[ one ] - counts[ one ] ), one ) )[ :size - sum( counts.values() ) ]: counts[ kind ] += 1
    rng     = random.Random( seed )
    chosen  = { one for kind in kinds for one in rng.sample( by_type[ kind ], counts[ kind ] ) }
    return { "seed": seed, "size": size, "counts": counts, "ids": [ record[ "id" ] for record in records if record[ "id" ] in chosen ] }


def refused_ids( per_ask_path ):
    """
    List the card ids a finished run left without an answer.

    Requires:
        - per_ask_path is a per-ask file this driver wrote

    Ensures:
        - returns the ids whose reason is not None, in file order
    """
    return [ row[ "id" ] for row in read_jsonl( per_ask_path ) if row[ "reason" ] is not None ]


async def forecast_all( factory, c0, ids, workers=WORKERS, progress=None ):
    """
    Run the baseline job for every id, at most workers at a time.

    Requires:
        - factory is a locked_sessions factory over the copy; c0 is a baseline with full set; ids are card ids as text
        - progress is None or a function( done, total ) called after each card

    Ensures:
        - returns a Counter of ( status, reason ) over the jobs
        - the job's own cap gate and the semaphore both hold the calls in flight to workers
    """
    gate    = CapGate( workers )
    permit  = asyncio.Semaphore( workers )
    counts  = collections.Counter()
    done    = [ 0 ]

    async def one( ask_id ):
        async with permit:
            result = await context_baseline.run_context_forecast( ask_id, factory, c0, gate, enabled=True )
        counts[ ( result[ "status" ], result[ "reason" ] ) ] += 1
        done[ 0 ] += 1
        if progress is not None: progress( done[ 0 ], len( ids ) )

    await asyncio.gather( *( one( ask_id ) for ask_id in ids ) )
    return counts


def score_rows( factory, records ):
    """
    Read each card's stored baseline row and score it against the card's answer.

    Requires:
        - records are run 2's per-ask lines, each with id, response_type and the baseline arm's correct flag

    Ensures:
        - returns one dict per record, in order: id, response_type, title, forecast, reason, correct, old_correct, scorable, write_in,
          write_in_fields
        - correct is replay_loop._score with per_field True, so an abstention or a missing row reads False
        - scorable and write_in are replay_loop.answer_split's, on the same per-field basis, read from the answer alone
        - old_correct is run 2's own flag for the baseline arm, read from the record
        - write_in_fields is write_in_outcome.field_outcomes over the per-field scoring of a multiple-choice card: one pair per
          answered field the forecast gave a write-in probability, and an empty list for any other card or a forecast without one
    """
    rows = []
    with factory() as session:
        for record in records:
            key    = uuid.UUID( record[ "id" ] )
            card   = session.get( Notification, key )
            arm    = session.query( PredictionArmForecast ).filter( PredictionArmForecast.notification_id == key, PredictionArmForecast.arm == context_baseline.ARM ).first()
            fore   = None if arm is None else arm.forecast
            reason = "no_row" if arm is None else arm.abstention_reason
            right  = _score( card.response_type, fore, card.response_value[ "value" ], card.response_options, per_field=True )
            split  = answer_split( card.response_type, card.response_value[ "value" ], card.response_options, True )
            pairs  = []
            if card.response_type == RESPONSE_TYPE_MULTIPLE_CHOICE:
                _, detail = compare_multiple_choice( fore, _actual_dict( card.response_value[ "value" ], card.response_type ), card.response_options, per_field=True )
                pairs     = write_in_outcome.field_outcomes( fore, detail[ "fields" ] if "fields" in detail else [] )   # an empty answer's detail names only its reason
            rows.append( { "id": record[ "id" ], "response_type": card.response_type, "title": card.title, "forecast": fore, "reason": reason,
                           "correct": right, "old_correct": record[ "arms" ][ context_baseline.ARM ][ "correct" ], **split, "write_in_fields": pairs } )
    return rows


def line_of( label, rows ):
    """
    Count one group of scored rows.

    Requires:
        - rows are score_rows' dicts

    Ensures:
        - returns { label, asks, answered, correct, correct_on_answered, old_correct, abstained, multiple_choice } where abstained maps
          a reason to its count
        - correct and old_correct count over all asks, an abstention being a miss, as run 2 charged it
        - multiple_choice is replay_loop.multiple_choice_split over the group's multiple-choice rows: right over scorable cards,
          the unscored count and the write-in rate, beside the all-cards figure
        - write_in_forecast is write_in_outcome.precision_recall over every write_in_fields pair of the group
    """
    answered = [ row for row in rows if row[ "forecast" ] is not None ]
    reasons  = collections.Counter( row[ "reason" ] for row in rows if row[ "forecast" ] is None )
    return { "label": label, "asks": len( rows ), "answered": len( answered ), "correct": sum( 1 for row in rows if row[ "correct" ] ),
             "correct_on_answered": sum( 1 for row in answered if row[ "correct" ] ), "old_correct": sum( 1 for row in rows if row[ "old_correct" ] ),
             "abstained": dict( reasons ), "multiple_choice": multiple_choice_split( [ row for row in rows if row[ "response_type" ] == RESPONSE_TYPE_MULTIPLE_CHOICE ] ),
             "write_in_forecast": write_in_outcome.precision_recall( [ pair for row in rows for pair in row[ "write_in_fields" ] ] ) }


def summarize( rows ):
    """
    Build the report lines: all cards, each card type and the Stop-hook cards.

    Requires:
        - rows are score_rows' dicts

    Ensures:
        - returns a list of line_of dicts; the Stop-hook line is always present, with 0 asks when no card title starts with STOP_HOOK_TITLE
        - the Stop-hook cards stay in the totals and also get their own line, as Mr. Radio asked
    """
    lines = [ line_of( "all", rows ) ]
    for kind in sorted( { row[ "response_type" ] for row in rows } ): lines.append( line_of( kind, [ row for row in rows if row[ "response_type" ] == kind ] ) )
    lines.append( line_of( "stop-hook cards", [ row for row in rows if ( row[ "title" ] or "" ).startswith( STOP_HOOK_TITLE ) ] ) )
    return lines


def render( lines ):
    """
    Write the report lines as a table.

    Requires:
        - lines are summarize's result

    Ensures:
        - returns the text; every count is printed beside its denominator
        - a group with multiple-choice cards also prints them as right of scorable, unscored and write-in cards, each of all its multiple-choice cards,
          and the unscored cards a forecast still matched; a group with write-in forecasts prints their precision, recall and Brier score;
          the correct column stays the all-cards figure, an unscored card read as a miss, so earlier numbers stay comparable
    """
    out = [ f"{'group':<18}{'asks':>6}{'answered':>10}{'correct':>9}{'old C0':>8}  abstained" ]
    for line in lines:
        out.append( f"{line[ 'label' ]:<18}{line[ 'asks' ]:>6}{line[ 'answered' ]:>10}{line[ 'correct' ]:>9}{line[ 'old_correct' ]:>8}  {line[ 'abstained' ]}" )
        split = line[ "multiple_choice" ]
        if split[ "cards" ]:
            out.append( f"{'':<18}multiple choice: right {split[ 'right' ]} of {split[ 'scorable' ]} scorable, unscored {split[ 'unscored' ]} of {split[ 'cards' ]}, "
                        f"write-in cards {split[ 'write_in_cards' ]} of {split[ 'cards' ]}, unscored right {split[ 'unscored_right' ]}" )
        scores = line[ "write_in_forecast" ]
        if scores[ "fields" ]:
            out.append( f"{'':<18}write-in forecast: {scores[ 'fields' ]} fields, {scores[ 'actual' ]} typed, {scores[ 'predicted' ]} forecast typed, "
                        f"{scores[ 'true_positive' ]} both; precision {_ratio( scores[ 'precision' ] )}, recall {_ratio( scores[ 'recall' ] )}, Brier {_ratio( scores[ 'brier' ] )}" )
    return "\n".join( out )


def _ratio( value ):
    """
    Show a ratio with three decimals, or a dash when there is none.

    Ensures:
        - returns "-" for None, else the value to three decimals
    """
    return "-" if value is None else f"{value:.3f}"


def pair_with( rows, old_rows ):
    """
    Compare this run's multiple-choice cards with an earlier run's, on the cards both scored.

    Requires:
        - rows are score_rows' dicts; old_rows are an earlier per-ask file's rows, each with id and correct

    Ensures:
        - returns { cards, new, old, new_only_right, old_only_right } over the multiple-choice cards both runs hold, in this run's order
        - new and old are replay_loop.multiple_choice_split for each run, both read with this run's scorable and write_in flags,
          because those are facts of the answer and an older file may not carry them
        - new_only_right and old_only_right are replay_loop.paired_wins over the same cards
    """
    old    = { row[ "id" ]: row for row in old_rows }
    shared = [ row for row in rows if row[ "response_type" ] == RESPONSE_TYPE_MULTIPLE_CHOICE and row[ "id" ] in old ]
    flags  = lambda row, correct: { "correct": correct, "scorable": row[ "scorable" ], "write_in": row[ "write_in" ] }
    new    = [ flags( row, row[ "correct" ] ) for row in shared ]
    before = [ flags( row, old[ row[ "id" ] ][ "correct" ] ) for row in shared ]
    wins   = paired_wins( { "records": { "new": [ { "meta": one } for one in new ], "old": [ { "meta": one } for one in before ] } }, "new", "old" )
    return { "cards": len( shared ), "new": multiple_choice_split( new ), "old": multiple_choice_split( before ), "new_only_right": wins[ 0 ], "old_only_right": wins[ 1 ] }


def render_pair( pair ):
    """
    Write pair_with's comparison as two lines.

    Requires:
        - pair is pair_with's result

    Ensures:
        - returns the text: the shared card count, each run's right over scorable and all-cards figure, and the cards only one got right
    """
    new, old = pair[ "new" ], pair[ "old" ]
    return ( f"paired with the earlier run on {pair[ 'cards' ]} multiple-choice cards: this run right {new[ 'right' ]} of {new[ 'scorable' ]} scorable "
             f"({new[ 'correct_all_cards' ]} of {new[ 'cards' ]} all cards), earlier run right {old[ 'right' ]} of {old[ 'scorable' ]} scorable "
             f"({old[ 'correct_all_cards' ]} of {old[ 'cards' ]} all cards)\n"
             f"only this run right {pair[ 'new_only_right' ]}, only the earlier run right {pair[ 'old_only_right' ]}" )


def progress_due( done, total ):
    """
    Say whether a progress line is printed after this many cards.

    Requires:
        - done is the count finished so far and total the count to do, both ints

    Ensures:
        - returns True after every hundredth card and after the last
    """
    return done % PROGRESS_EVERY == 0 or done == total


def main( argv=None, query_fn=None, out=print ):
    """
    Run the arm from the command line.

    Requires:
        - argv is a list of arguments or None; query_fn is None for the live bounded Claude Code call, or a double for a test

    Ensures:
        - the archive is only read; every file is written in the new work folder
        - --limit N cuts the cards to the first N, for a probe in its own work folder
        - writes the per-ask file and the raw replies the parser refused (refusals.jsonl), prints the table; returns 0
        - --only-refused FILE runs only the cards that file left unanswered
        - --sample N --seed S runs a fixed-seed random sample of the cards, split by type, and writes its ids and seed to sample.json before any call
        - --model ID calls that model in place of the INI setting
        - --write-in turns the write-in outcome on for this run only and keeps only the multiple-choice cards, the only ones it changes;
          the INI switch is not read or written
        - --pair-with FILE reads an earlier per-ask file and prints pair_with's comparison after the table
        - the baseline is built with the full-answer reply forced on, so no INI switch changes

    Raises:
        - FileExistsError if the work folder holds a per-ask file already
        - ValueError if only one of --sample and --seed is given, or the sample size is not from 1 to the card count
        - RuntimeError if the full-answer switch reads off, because the cards' option ids exist only with it on and nothing here edits the INI file
    """
    parser = argparse.ArgumentParser( description="Forecast the cards of record with the full-answer reply" )
    parser.add_argument( "--archive", required=True )
    parser.add_argument( "--records", required=True )
    parser.add_argument( "--work-dir", required=True )
    parser.add_argument( "--workers", type=int, default=WORKERS )
    parser.add_argument( "--limit", type=int, default=None )
    parser.add_argument( "--only-refused", default=None, help="a per-ask file; re-run only its cards that got no answer" )
    parser.add_argument( "--sample", type=int, default=None, help="draw this many cards at random, split by response type; needs --seed" )
    parser.add_argument( "--seed", type=int, default=None, help="the seed of the random sample" )
    parser.add_argument( "--model", default=None, help="the model id to call, in place of the INI setting" )
    parser.add_argument( "--write-in", action="store_true", help="ask for the per-field write-in outcome; keeps only the multiple-choice cards" )
    parser.add_argument( "--pair-with", default=None, help="an earlier per-ask file to compare this run's multiple-choice cards with" )
    args    = parser.parse_args( argv )
    if not full_answer.full_answer_enabled(): raise RuntimeError( f"{full_answer.SWITCH_KEY} reads off in this tree; the arm needs it on" )
    records = read_jsonl( args.records )[ :args.limit ]
    if ( args.sample is None ) != ( args.seed is None ): raise ValueError( "--sample and --seed go together" )
    if args.only_refused is not None:
        wanted  = set( refused_ids( args.only_refused ) )
        records = [ record for record in records if record[ "id" ] in wanted ]
    sample  = None if args.sample is None else draw_sample( records, args.sample, args.seed )
    if sample is not None: records = [ record for record in records if record[ "id" ] in set( sample[ "ids" ] ) ]
    if args.write_in: records = [ record for record in records if record[ "response_type" ] == RESPONSE_TYPE_MULTIPLE_CHOICE ]
    ids     = [ record[ "id" ] for record in records ]
    target  = os.path.join( args.work_dir, OUT_NAME )
    if os.path.exists( target ): raise FileExistsError( f"{target} exists; use a new work folder" )
    os.makedirs( args.work_dir, exist_ok=True )
    if sample is not None:
        with open( os.path.join( args.work_dir, SAMPLE_NAME ), "w", encoding="utf-8" ) as handle: json.dump( sample, handle )
    copy    = prepare_copy( args.archive, args.work_dir, ids )
    engine  = create_engine( f"sqlite:///{copy}", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    factory = locked_sessions( engine )
    ledger  = context_baseline.open_ledger( base_path=os.path.join( args.work_dir, LEDGER_NAME ), cli_path=model_transport.CLI_PATH )
    c0      = RefusalKeeper( context_baseline.context_model() if args.model is None else args.model, context_baseline.context_timeout(), context_baseline.context_layers(), ledger, query_fn=query_fn, full=True,
                             write_in=args.write_in )
    counts  = asyncio.run( forecast_all( factory, c0, ids, args.workers, progress=lambda done, total: out( f"[full-answer-arm] {done}/{total}" ) if progress_due( done, total ) else None ) )
    rows    = score_rows( factory, records )
    with open( target, "w", encoding="utf-8" ) as handle:
        for row in rows: handle.write( json.dumps( row, default=str ) + "\n" )
    with open( os.path.join( args.work_dir, REFUSALS_NAME ), "w", encoding="utf-8" ) as handle:
        for kept in c0.kept: handle.write( json.dumps( kept ) + "\n" )
    out( f"refused replies kept: {len( c0.kept )}" )
    out( f"model {c0.model}, full answer {c0.full}, write-in outcome {c0.write_in}, per-field scoring on, jobs {dict( counts )}" )
    out( render( summarize( rows ) ) )
    if args.pair_with is not None: out( render_pair( pair_with( rows, read_jsonl( args.pair_with ) ) ) )
    engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
