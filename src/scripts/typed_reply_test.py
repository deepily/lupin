#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Predict the reply typed into a multiple-choice field, and save it for scoring.

It is an offline test. It takes each typed field in a write-in run's sample.
The model sees the card as it was asked and writes the reply it expects. It never sees the answer. Nothing here scores a prediction:
scoring is a separate step, by the answer judge.

Run from a seat tree, pinning all three:

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/typed_reply_test.py \
        --per-ask <write-in run>/full-answer-arm-per-ask.jsonl --archive <write-in run>/archive-copy.sqlite \
        --work-dir <new folder> --model <model id> [--limit N]
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import uuid

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import cosa.research.preference_replay.scratch_db  # noqa: F401  registers the SQLite hooks for JSONB and Vector
from cosa.agents.io_models.utils.json_object_recovery import recover_json_object
from cosa.agents.prediction_engine import context_baseline
from cosa.agents.prediction_engine.accuracy_comparators import offered_labels, schema_questions
from cosa.agents.prediction_engine.config import RESPONSE_TYPE_MULTIPLE_CHOICE
from cosa.agents.prediction_engine.episode_view import episode_view
from cosa.repo.doc_lint import model_transport
from cosa.research.preference_replay.archive_replay import locked_sessions, read_jsonl
from cosa.research.preference_replay.replay_loop import _actual_dict
from cosa.rest.postgres_models import Notification

WORKERS     = 2
OUT_NAME    = "typed-reply-predictions.jsonl"
LEDGER_NAME = "ledger.jsonl"
KINDS       = ( "question", "defer", "pick_with_request", "other" )

SYSTEM_PROMPT = (
    "You predict what one person typed in reply to a question an AI coding assistant put to them. You see only the card as it was shown. "
    "A default or a time limit on the card is not their reply. "
    "Reply with one JSON object and nothing else."
)
ASK = (
    "This person did not pick an offered option for the field \"{field}\". They typed their own words into it. "
    "Write the reply you think they most likely typed, in their own voice, and name its kind: "
    "\"question\" (they ask something back or want more context), \"defer\" (not now, wait), "
    "\"pick_with_request\" (they choose an option in words and add a request or condition), or \"other\".\n\n"
    "Reply: {{\"kind\": one of those four, \"reply\": the words}}."
)


def typed_fields( per_ask, factory ):
    """
    Read every field of the run that holds a typed answer, with the words typed.

    Requires:
        - per_ask holds the rows of a write-in run's per-ask file, each with id and write_in_fields
        - factory is a context-managed session factory over an archive holding those cards

    Ensures:
        - returns one { id, field, actual } per field whose write_in_fields entry says it was typed, in file and field order
        - actual is the picks of that field that are not offered labels, joined by newlines

    Raises:
        - ValueError if a field the run counted as typed holds no pick outside its labels, so the two readings disagree
    """
    found = []
    for row in per_ask:
        headers = [ pair[ "header" ] for pair in row[ "write_in_fields" ] if pair[ "actual" ] ]
        if not headers: continue
        with factory() as session:
            card    = session.get( Notification, uuid.UUID( row[ "id" ] ) )
            answers = _actual_dict( card.response_value[ "value" ], RESPONSE_TYPE_MULTIPLE_CHOICE )[ "answers" ]
            offered = { question[ "header" ]: offered_labels( question ) for question in schema_questions( card.response_options ) }
        for header in headers:
            given = answers[ header ]
            typed = [ pick for pick in ( given if isinstance( given, list ) else [ given ] ) if pick.strip() not in offered[ header ] ]
            if not typed: raise ValueError( f"card {row[ 'id' ]} field {header!r}: the run says typed, but every pick is an offered label" )
            found.append( { "id": row[ "id" ], "field": header, "actual": "\n".join( typed ) } )
    return found


def build_prompt( episode, field, layers ):
    """
    Build the user prompt that asks for the reply typed into one field.

    Requires:
        - episode is episode_view's result for a multiple-choice card; field is one of its field keys
        - layers is a subset of context_baseline.ALL_LAYERS

    Ensures:
        - returns the card as the baseline shows it, with the choice reply format replaced by the request for the field's typed reply
        - holds nothing of the card's answer
    """
    shown = context_baseline.build_user_prompt( episode, layers ).removesuffix( context_baseline.CHOICE_FORMAT )
    return shown + ASK.format( field=field )


def parse_prediction( text ):
    """
    Read the predicted kind and words out of a reply.

    Requires:
        - text is the model's reply

    Ensures:
        - returns { kind, reply } with kind one of the four listed kinds and reply a non-blank string

    Raises:
        - ValueError if the reply holds no JSON object, names another kind or has no words
    """
    value = recover_json_object( text )
    if not isinstance( value, dict ): raise ValueError( "the reply holds no JSON object" )
    kind, words = value.get( "kind" ), value.get( "reply" )
    if kind not in KINDS: raise ValueError( f"kind must be one of {KINDS}, got {kind!r}" )
    if not isinstance( words, str ) or not words.strip(): raise ValueError( "the reply has no words" )
    return { "kind": kind, "reply": words }


async def predict_all( fields, factory, baseline, workers=WORKERS ):
    """
    Make one prediction for every typed field, at most workers calls at a time.

    Requires:
        - fields is typed_fields' result; factory opens the archive; baseline is a ContextBaseline, used for its cached bounded call

    Ensures:
        - returns one row per field, in order: id, field, actual, kind, predicted, reason, raw
        - a prediction that was read has reason None and raw None
        - a failed call has reason "call_failed" and the error text in raw; an unreadable reply has reason "unreadable" and the reply in raw
        - the typed answer is never put in a prompt
    """
    permit = asyncio.Semaphore( workers )

    async def one( item ):
        with factory() as session: episode = episode_view( session, item[ "id" ] )
        row = { **item, "kind": None, "predicted": None, "reason": None, "raw": None }
        async with permit:
            try:
                text = await baseline.complete( baseline.model, SYSTEM_PROMPT, build_prompt( episode, item[ "field" ], baseline.layers ) )
            except baseline.errors as error:
                return { **row, "reason": "call_failed", "raw": str( error ) }
        try:
            read = parse_prediction( text )
        except ValueError:
            return { **row, "reason": "unreadable", "raw": text }
        return { **row, "kind": read[ "kind" ], "predicted": read[ "reply" ] }

    return await asyncio.gather( *( one( item ) for item in fields ) )


def main( argv=None, query_fn=None, out=print ):
    """
    Predict the typed replies of one write-in run from the command line.

    Requires:
        - argv is a list of arguments or None; query_fn is None for the live bounded Claude Code call, or a double for a test

    Ensures:
        - --model names the model to call; the code holds no model id
        - the archive is opened read-only; every file is written in the work folder
        - --limit N cuts the typed fields to the first N, for a probe in its own work folder
        - writes OUT_NAME, one line per field with predict_all's row plus the model and the prompt version, and prints the counts; returns 0

    Raises:
        - FileExistsError if the work folder holds a predictions file already
        - ValueError as typed_fields does
    """
    parser = argparse.ArgumentParser( description="Predict the replies typed into multiple-choice fields" )
    for name in ( "--per-ask", "--archive", "--work-dir" ): parser.add_argument( name, required=True )
    parser.add_argument( "--model", required=True )
    parser.add_argument( "--limit", type=int, default=None )
    parser.add_argument( "--workers", type=int, default=WORKERS )
    args   = parser.parse_args( argv )
    target = os.path.join( args.work_dir, OUT_NAME )
    if os.path.exists( target ): raise FileExistsError( f"{target} exists; use a new work folder" )
    engine  = create_engine( "sqlite://", creator=lambda: sqlite3.connect( f"file:{os.path.abspath( args.archive )}?mode=ro", uri=True, check_same_thread=False ), poolclass=StaticPool )
    factory = locked_sessions( engine )
    fields  = typed_fields( read_jsonl( args.per_ask ), factory )[ :args.limit ]
    os.makedirs( args.work_dir, exist_ok=True )
    ledger   = context_baseline.open_ledger( base_path=os.path.join( args.work_dir, LEDGER_NAME ), cli_path=model_transport.CLI_PATH )
    baseline = context_baseline.ContextBaseline( args.model, context_baseline.context_timeout(), context_baseline.context_layers(), ledger, query_fn=query_fn, full=False )
    rows     = asyncio.run( predict_all( fields, factory, baseline, args.workers ) )
    version  = model_transport.prompt_version( "typed-reply", SYSTEM_PROMPT, ASK, ",".join( baseline.layers ), baseline.predictor_version )
    with open( target, "w", encoding="utf-8" ) as handle:
        for row in rows: handle.write( json.dumps( { **row, "model": args.model, "prompt_version": version } ) + "\n" )
    refused = sum( 1 for row in rows if row[ "reason" ] is not None )
    out( f"model {args.model}: {len( rows )} typed fields on {len( { row[ 'id' ] for row in rows } )} cards, {len( rows ) - refused} predicted, {refused} without a prediction" )
    engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
