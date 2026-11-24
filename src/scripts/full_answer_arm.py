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
import shutil
import sys
import uuid

from sqlalchemy import MetaData, create_engine
from sqlalchemy.pool import StaticPool

import cosa.research.preference_replay.scratch_db  # noqa: F401  registers the SQLite hooks for JSONB and Vector
from cosa.agents.prediction_engine import context_baseline, full_answer
from cosa.agents.prediction_engine.principles_forecast import CapGate
from cosa.repo.doc_lint import model_transport
from cosa.rest.db import schema_drift
from cosa.research.preference_replay.archive_replay import locked_sessions, read_jsonl
from cosa.research.preference_replay.replay_loop import _score
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PredictionLog

WORKERS         = 2
PROGRESS_EVERY  = 100
STOP_HOOK_TITLE = "Stop hook"
OUT_NAME        = "full-answer-arm-per-ask.jsonl"
COPY_NAME       = "archive-copy.sqlite"
LEDGER_NAME     = "ledger.jsonl"


def add_missing_columns( engine ):
    """
    Add to a copied archive the nullable columns its tables gained after the archive was made.

    Requires:
        - engine is an engine over the copy

    Ensures:
        - the gaps are found by schema_drift.find_missing_columns over the three tables the job reads or writes
        - each column the models hold and the table lacks is added as a nullable column of its SQLite type
        - returns the list of "table.column" names added; a copy that is up to date adds none

    Raises:
        - RuntimeError if a missing column is not nullable or a whole table is missing, because the copy would be unreadable by the job
    """
    scope = MetaData()
    for model in ( Notification, PredictionLog, PredictionArmForecast ): model.__table__.to_metadata( scope )
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
        - returns one dict per record, in order: id, response_type, title, forecast, reason, correct, old_correct
        - correct is replay_loop._score with per_field True, so an abstention or a missing row reads False
        - old_correct is run 2's own flag for the baseline arm, read from the record
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
            rows.append( { "id": record[ "id" ], "response_type": card.response_type, "title": card.title, "forecast": fore, "reason": reason,
                           "correct": right, "old_correct": record[ "arms" ][ context_baseline.ARM ][ "correct" ] } )
    return rows


def line_of( label, rows ):
    """
    Count one group of scored rows.

    Requires:
        - rows are score_rows' dicts

    Ensures:
        - returns { label, asks, answered, correct, old_correct, abstained } where abstained maps a reason to its count
        - correct and old_correct count over all asks, an abstention being a miss, as run 2 charged it
    """
    answered = [ row for row in rows if row[ "forecast" ] is not None ]
    reasons  = collections.Counter( row[ "reason" ] for row in rows if row[ "forecast" ] is None )
    return { "label": label, "asks": len( rows ), "answered": len( answered ), "correct": sum( 1 for row in rows if row[ "correct" ] ),
             "correct_on_answered": sum( 1 for row in answered if row[ "correct" ] ), "old_correct": sum( 1 for row in rows if row[ "old_correct" ] ),
             "abstained": dict( reasons ) }


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
    """
    out = [ f"{'group':<18}{'asks':>6}{'answered':>10}{'correct':>9}{'old C0':>8}  abstained" ]
    for line in lines: out.append( f"{line[ 'label' ]:<18}{line[ 'asks' ]:>6}{line[ 'answered' ]:>10}{line[ 'correct' ]:>9}{line[ 'old_correct' ]:>8}  {line[ 'abstained' ]}" )
    return "\n".join( out )


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
        - writes the per-ask file and prints the table; returns 0
        - the baseline is built with the full-answer reply forced on, so no INI switch changes

    Raises:
        - FileExistsError if the work folder holds a per-ask file already
        - RuntimeError if the full-answer switch reads off, because the cards' option ids exist only with it on and nothing here edits the INI file
    """
    parser = argparse.ArgumentParser( description="Forecast the cards of record with the full-answer reply" )
    parser.add_argument( "--archive", required=True )
    parser.add_argument( "--records", required=True )
    parser.add_argument( "--work-dir", required=True )
    parser.add_argument( "--workers", type=int, default=WORKERS )
    parser.add_argument( "--limit", type=int, default=None )
    args    = parser.parse_args( argv )
    if not full_answer.full_answer_enabled(): raise RuntimeError( f"{full_answer.SWITCH_KEY} reads off in this tree; the arm needs it on" )
    records = read_jsonl( args.records )[ :args.limit ]
    ids     = [ record[ "id" ] for record in records ]
    target  = os.path.join( args.work_dir, OUT_NAME )
    if os.path.exists( target ): raise FileExistsError( f"{target} exists; use a new work folder" )
    os.makedirs( args.work_dir, exist_ok=True )
    copy    = prepare_copy( args.archive, args.work_dir, ids )
    engine  = create_engine( f"sqlite:///{copy}", connect_args={ "check_same_thread": False }, poolclass=StaticPool )
    factory = locked_sessions( engine )
    ledger  = context_baseline.open_ledger( base_path=os.path.join( args.work_dir, LEDGER_NAME ), cli_path=model_transport.CLI_PATH )
    c0      = context_baseline.ContextBaseline( context_baseline.context_model(), context_baseline.context_timeout(), context_baseline.context_layers(), ledger, query_fn=query_fn, full=True )
    counts  = asyncio.run( forecast_all( factory, c0, ids, args.workers, progress=lambda done, total: out( f"[full-answer-arm] {done}/{total}" ) if progress_due( done, total ) else None ) )
    rows    = score_rows( factory, records )
    with open( target, "w", encoding="utf-8" ) as handle:
        for row in rows: handle.write( json.dumps( row, default=str ) + "\n" )
    out( f"model {c0.model}, full answer {c0.full}, per-field scoring on, jobs {dict( counts )}" )
    out( render( summarize( rows ) ) )
    engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
