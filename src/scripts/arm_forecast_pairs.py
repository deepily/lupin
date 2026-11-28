#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Build blinded forecast-and-answer pairs from every forecasting arm, for judge validation.

Plan: src/rnd/v0.2.4/2026.11.17-principle-learner-research/2026.11.23-answer-signal-experiment-plan.md, section 3,
"Gold labels and a validated judge" and "Retrospective re-score".

Yes/no and multiple-choice cards are the run 2 archive's, with the forecasts it stored.
The baseline and principles arms also get full-answer replies on a seeded sample, in a database of its own.
The answer history arm has no stored forecasts, so it is run here. Open-ended and batch cards are the gold sample's.
The baseline, principles and answer history arms are run on them here. Every run is on a scratch copy of the archive. The live database is only read.
There are three stages, forecast, full and pairs. Run each from a tree, pinning all three:

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/arm_forecast_pairs.py forecast --archive <run 2 folder> --work <work folder> ...

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/arm_forecast_pairs.py pairs --archive <run 2 folder> --work <work folder> --out <pairs folder>
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import random
import re
import shutil
import sys
import uuid
from collections import Counter
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import inspect as sql_inspect
from sqlalchemy import text

import cosa.utils.util as cu
import full_answer_arm
from cosa.agents.prediction_engine import answer_history_forecast, context_baseline, principle_retrieval, principles_forecast
from cosa.agents.prediction_engine.accuracy_comparators import compare_yes_no
from cosa.agents.prediction_engine.episode_view import fields_of
from cosa.agents.prediction_engine.history_context_rebuild import answer_known_at_ask
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.prediction_engine.three_way_stance import is_owners_human_answer
from cosa.config.configuration_manager import ConfigurationManager
from cosa.repo.doc_lint import model_transport
from cosa.research.preference_replay import archive_replay
from cosa.research.preference_replay.cohorts import answer_source_of
from cosa.research.preference_replay.extractor_replay import asks_from_session
from cosa.research.preference_replay.replay_loop import _actual_dict
from cosa.research.preference_replay.scratch_db import TABLES, scratch_session
from cosa.research.preference_replay.service_embeddings import CachedServiceEmbedder
from cosa.research.preference_replay.time_sliced_store import RECORD_FIELDS, TimeSlicedDecisionStore
from cosa.rest.postgres_models import AnswerMeaning, Notification, PredictionArmForecast
from cosa.utils.file_hash import file_sha256
from cosa.utils.jsonl_file import read_jsonl
from cosa.utils.notification_utils import parse_field_selections

ARM_HISTORY    = answer_history_forecast.ARM
ARM_BASELINE   = context_baseline.ARM
ARM_PRINCIPLES = principles_forecast.ARM
OPEN_ARMS      = ( ARM_BASELINE, ARM_PRINCIPLES )
CHOICE_TYPES   = ( "yes_no", "multiple_choice" )
OPEN_TYPES     = ( "open_ended", "open_ended_batch" )
MODEL_ARMS     = ( ARM_BASELINE, ARM_PRINCIPLES, ARM_HISTORY )
NO_MODEL_ARMS  = ( archive_replay.ARM_FIXED, "engine" )
PAIRS_NAME     = "pairs.jsonl"
KEY_NAME       = "key.json"
RECEIPT_NAME   = "receipt.json"
MANIFEST_NAME  = "MANIFEST.sha256"
CARDS_NAME     = "cards.jsonl"
HALF_LIFE_KEY  = "prediction engine recency half life days"
BUDGET_SAMPLE  = 200
BUDGET_SEED    = "answer-history-budget"
RULING         = ( "Cheech, 27 Nov 2026 about 21:55 Eastern: for this retrospective development replay only, the answer history arm "
                   "keeps the answered-before-ask rule and drops the meaning-record rule, because the live answer_meaning table is empty. "
                   "The override is in this script; the committed arm is unchanged." )


def eligible_without_meaning( session, cases, owner_id, asked_at ):
    """
    Keep the cases the replay may show for an ask, without asking for a meaning record.

    Requires:
        - the arguments are answer_history_forecast.eligible_cases's; session is not read

    Ensures:
        - keeps a case answered by a human, owned by the ask's owner, not thumbed down and answered at or before the ask
        - the cases keep their order
    """
    return [ case for case in cases if is_owners_human_answer( case, owner_id ) and answer_known_at_ask( case[ "responded_at" ], asked_at ) ]


def add_missing_columns( engine ):
    """
    Bring an older scratch copy up to the models' columns.

    Requires:
        - engine is a SQLite engine over a copy that holds every scratch table

    Ensures:
        - the answer meaning table is created when absent, so a query on it finds no rows
        - every column the scratch tables' models hold and the copy lacks is added by full_answer_arm.add_missing_columns
        - returns the added columns as "table.column", sorted

    Raises:
        - RuntimeError as full_answer_arm.add_missing_columns does
    """
    AnswerMeaning.__table__.create( engine, checkfirst=True )
    return sorted( full_answer_arm.add_missing_columns( engine, TABLES ) )


def import_live( session, live_session ):
    """
    Copy the live database's answered notifications the scratch copy lacks.

    Requires:
        - session is the scratch session; live_session is a session on the live database, used for reading only

    Ensures:
        - every live notification with an answer, of the four card types, not already in the copy, is inserted into the copy
        - the live read runs in a read-only transaction that is rolled back
        - returns the number inserted
    """
    columns = [ attribute.key for attribute in sql_inspect( Notification ).column_attrs ]
    have    = { row[ 0 ] for row in session.query( Notification.id ) }
    live_session.execute( text( "SET TRANSACTION READ ONLY" ) )
    try:
        found = live_session.query( Notification ).filter( Notification.responded_at.isnot( None ), Notification.response_type.in_( CHOICE_TYPES + OPEN_TYPES ) )
        new   = [ { name: getattr( row, name ) for name in columns } for row in found if row.id not in have ]
    finally: live_session.rollback()
    session.add_all( [ Notification( **values ) for values in new ] )
    session.commit()
    return len( new )


def sample_open_ids( types_path ):
    """
    Name the gold sample's open-ended and batch cards.

    Requires:
        - types_path is a JSON object of "<notification id>:<number>" to card type

    Ensures:
        - returns the notification ids of the open-ended and batch items, each once, sorted
    """
    with open( types_path, encoding="utf-8" ) as handle: types = json.load( handle )
    return sorted( { item.rsplit( ":", 1 )[ 0 ] for item, kind in types.items() if kind in OPEN_TYPES } )


def archive_ids( records_path ):
    """
    Name the run 2 evaluation cards.

    Requires:
        - records_path is run 2's records.jsonl

    Ensures:
        - returns the card ids, yes/no cards first and then the rest, each group in file order
    """
    lines = sorted( read_jsonl( records_path ), key=lambda line: line[ "response_type" ] != "yes_no" )
    return [ line[ "id" ] for line in lines ]


def store_of( session, engine, embed ):
    """
    Build the as-of case store the answer history arm retrieves from.

    Requires:
        - session is the scratch session; engine has a classifier; embed maps a text to a vector

    Ensures:
        - returns a TimeSlicedDecisionStore over every answered notification of the copy
    """
    asks = asks_from_session( session, engine, embed )
    return TimeSlicedDecisionStore( [ { field: ask[ field ] for field in RECORD_FIELDS + ( "responded_at", ) } for ask in asks ] )


def matched_budget( factory, ids, c0, embedder, encoder, extractor, limits, size=BUDGET_SAMPLE ):
    """
    Measure the evidence-token budget the learned principles arm uses on development data.

    Requires:
        - ids are archive card ids; the other arguments are as principles_forecast._prepare takes them

    Ensures:
        - returns the ceiling of the mean approx_tokens of the principle block over a seeded sample of at most size cards
        - no model is called and nothing is written

    Raises:
        - ValueError when ids is empty
    """
    if not ids: raise ValueError( "no card to measure the budget on" )
    chosen = random.Random( BUDGET_SEED ).sample( sorted( ids ), min( size, len( ids ) ) )
    total  = 0
    with mock.patch.object( principle_retrieval, "dot_topk", archive_replay.scratch_topk ):
        for one in chosen:
            block  = principles_forecast._prepare( factory, one, c0, embedder, encoder, extractor, principle_retrieval.DEFAULT_K, True, limits, None )[ 2 ]
            total += answer_history_forecast.approx_tokens( block[ "text" ] )
    return -( -total // len( chosen ) )


# The baseline and principles arms with full-answer replies on archive cards, under their own codes so run 2's rows stay.
FULL_BASELINE    = ARM_BASELINE + "-full"
FULL_PRINCIPLES  = ARM_PRINCIPLES + "-full"
FULL_ARMS        = ( FULL_BASELINE, FULL_PRINCIPLES )
FULL_SAMPLE_SEED = "full-reply-archive"
SAMPLE_NAME      = "sample.json"


def full_sample( records_path, per_type ):
    """
    Draw the archive cards the baseline and principles arms are run on again.

    Requires:
        - records_path is run 2's records.jsonl; per_type is a non-negative int

    Ensures:
        - returns at most per_type card ids of each response type, a seeded draw, the same on every call
    """
    lines, drawn = read_jsonl( records_path ), []
    for kind in CHOICE_TYPES:
        ids    = sorted( line[ "id" ] for line in lines if line[ "response_type" ] == kind )
        drawn += sorted( random.Random( f"{FULL_SAMPLE_SEED}|{kind}" ).sample( ids, min( per_type, len( ids ) ) ) )
    return drawn


async def forecast_all( work, factory, c0, embedder, encoder, extractor, store, budget, half_life_days, limits, concurrency, out=print ):
    """
    Run the missing forecasts, several cards at a time.

    Requires:
        - work is a list of ( card id, arm ), each arm one of MODEL_ARMS or FULL_ARMS
        - concurrency is a positive int; the other arguments are as the arms' jobs take them

    Ensures:
        - each pair runs through its arm's own job with the switch passed on, so no INI switch changes
        - a card that already has its row is left alone by the job itself
        - returns a Counter of ( arm, status, reason ); a progress line is printed every 100 jobs and at the end
    """
    gates    = { arm: principles_forecast.CapGate( concurrency ) for arm in MODEL_ARMS + FULL_ARMS }
    places   = asyncio.Semaphore( concurrency )
    counts   = Counter()
    finished = 0

    async def one( card, arm ):
        """Run one arm for one card."""
        nonlocal finished
        async with places:
            if arm == ARM_BASELINE: result = await context_baseline.run_context_forecast( card, factory, c0, gates[ arm ], enabled=True )
            elif arm == ARM_PRINCIPLES: result = await principles_forecast.run_b1( factory, card, c0, embedder, encoder, extractor, gates[ arm ], enabled=True, limits=limits )
            elif arm == FULL_BASELINE: result = await principles_forecast.run_arm( arm, context_baseline.SWITCH_KEY, "", False, factory, card, c0, None, "", "", gates[ arm ], enabled=True )
            elif arm == FULL_PRINCIPLES: result = await principles_forecast.run_arm( arm, principles_forecast.SWITCH_KEY, principles_forecast.VERSION_SUFFIX, True, factory, card, c0,
                                                                                    embedder, encoder, extractor, gates[ arm ], enabled=True, limits=limits )
            else: result = await answer_history_forecast.run_answer_history( factory, card, c0, store, embedder, budget, half_life_days, gates[ arm ], enabled=True )
        counts[ ( arm, result[ "status" ], result[ "reason" ] ) ] += 1
        finished += 1
        if finished % 100 == 0 or finished == len( work ): out( f"[forecast] {finished}/{len( work )} " + json.dumps( sorted( [ list( map( str, k ) ) + [ n ] for k, n in counts.items() ] ) ) )

    with mock.patch.object( principle_retrieval, "dot_topk", archive_replay.scratch_topk ), \
         mock.patch.object( answer_history_forecast, "eligible_cases", eligible_without_meaning ):
        await asyncio.gather( *( one( card, arm ) for card, arm in work ) )
    return counts


def _joined( value ):
    """
    Write a pick, a list of picks or free text as one string.

    Requires:
        - value is None, a string, a list or any other value

    Ensures:
        - a list is its members joined by "; "; None stays None; anything else is its string
    """
    if value is None: return None
    if isinstance( value, ( list, tuple ) ): return "; ".join( str( member ) for member in value )
    return str( value )


# Chloé's wider review pattern, 27 Nov. A diagnostic only: it misses some references and catches some ordinary words.
EARLIER_ANSWER = re.compile( r"\bearlier\b|\bpreviously\b|\bconsistently\b|\balready (chose|ruled|said|asked)|(their|the) (usual |earlier |past |prior )?pattern|\bprecedent|"
                             r"\bprinciples?\b|past (answers?|choices|decisions)|previous(ly)? (answer|chose|said|picked|ruled)", re.IGNORECASE )


def refers_to_earlier( predicted ):
    """
    Say whether a forecast text points at earlier answers.

    Requires:
        - predicted is a string or None

    Ensures:
        - returns True when the text holds one of EARLIER_ANSWER's phrases; it is a word match, a diagnostic that nothing is excluded on
    """
    return bool( predicted and EARLIER_ANSWER.search( predicted ) )


def _with_conditions( said, forecast ):
    """
    Put a full record's conditions after what it forecast.

    Requires:
        - said is a non-empty string; forecast is a forecast dict

    Ensures:
        - returns said, then "; " and the record's qualifier when it has one
    """
    return "; ".join( part for part in ( said, forecast.get( "qualifier" ) ) if part )


def _choice_predicted( forecast, header ):
    """
    Read what a forecast says for one multiple-choice field.

    Requires:
        - forecast is a stored forecast dict; header is a field of the card

    Ensures:
        - returns the picked label or labels, else the full record's write-in or re-frame text, else None
        - a full record's conditions are added after the pick
    """
    given = ( forecast.get( "answers" ) or {} ).get( header )
    if given is None:
        field = ( forecast.get( "fields" ) or {} ).get( header ) or {}
        given = field.get( "write_in" ) or field.get( "reframe" )
    if given is None: return None
    return _with_conditions( _joined( given ), forecast )


def texts_of( response_type, forecast, actual_value ):
    """
    Give the ( field key, predicted text, actual text ) rows one forecast of one card makes.

    Requires:
        - response_type is one of the four card types; actual_value is the stored answer string
        - forecast is a stored forecast dict, or None for an abstention

    Ensures:
        - an abstention makes no row
        - yes/no: one row with field key "" when the forecast's stance is the answer's; the texts are the two conditions as the complete-action comparator reads them, None for none
        - multiple choice: one row per answered field the forecast speaks to, field key the header
        - open-ended: one row, the predicted text the forecast's gist with its conditions after it
        - batch: one row per answered field the forecast gives a gist for, field key the header; the card's conditions follow each field's gist
        - no forecast text drops a condition the record holds
    """
    if not forecast: return []
    if response_type == "yes_no":
        match, detail = compare_yes_no( forecast, _actual_dict( actual_value, response_type ) )
        return [ ( "", detail.get( "predicted_qualifier" ), detail.get( "actual_qualifier" ) ) ] if match else []
    if response_type == "open_ended":
        predicted = forecast.get( "gist" )
        return [ ( "", _with_conditions( predicted, forecast ), actual_value ) ] if predicted else []
    fields = parse_field_selections( actual_value ) or {}
    rows   = []
    for header, record in fields.items():
        answered  = record[ "text" ] if record[ "text" ] is not None else _joined( record[ "selected" ] )
        if response_type == "multiple_choice": predicted = _choice_predicted( forecast, header )
        else:
            gist      = ( ( forecast.get( "fields" ) or {} ).get( header ) or {} ).get( "gist" )
            predicted = _with_conditions( gist, forecast ) if gist else None
        if predicted is not None and answered: rows.append( ( header, predicted, answered ) )
    return rows


def option_mismatch( card, field_key, forecast ):
    """
    Say whether a forecast chose otherwise than the person did, conditions left out.

    Requires:
        - card is one of human_cards' entries, of type yes_no or multiple_choice
        - field_key and forecast are those of a row texts_of made for the card

    Ensures:
        - yes/no: True when the forecast's stance is not the answer's
        - multiple choice, a forecast that picked options: True when its set of labels is not the answered set
        - multiple choice, a write-in or re-frame forecast: True when the answer holds a label the card offered, so two typed answers do not differ here
    """
    if card[ "response_type" ] == "yes_no": return not compare_yes_no( forecast, _actual_dict( card[ "actual_value" ], "yes_no" ) )[ 0 ]
    answered = set( parse_field_selections( card[ "actual_value" ] )[ field_key ][ "selected" ] )
    picked   = ( forecast.get( "answers" ) or {} ).get( field_key )
    if picked is None:
        offered = { option[ "label" ] for field in fields_of( card[ "options" ], None ) if field[ "key" ] == field_key for option in field[ "options" ] }
        return bool( answered & offered )
    return { str( one ).strip() for one in ( picked if isinstance( picked, list ) else [ picked ] ) } != answered


def pair_id_of( notification_id, field_key, arm ):
    """
    Name a pair without naming its arm.

    Requires:
        - the three are strings

    Ensures:
        - returns the first 16 hex digits of the sha256 of "notification_id|field_key|arm"
    """
    return hashlib.sha256( f"{notification_id}|{field_key}|{arm}".encode( "utf-8" ) ).hexdigest()[ :16 ]


def make_pairs( cards, forecasts, models ):
    """
    Turn every arm's forecasts into blinded pairs and their sealed key.

    Requires:
        - cards maps a card id to { response_type, actual_value, options }; actual_value is the person's own stored answer
        - forecasts is an iterable of ( card id, arm, forecast or None )
        - models maps each arm to its model's id

    Ensures:
        - returns ( pairs, key ); pairs are sorted by pair id and never name an arm or a model
        - literal_mismatch is True when the two texts differ after stripping and lower-casing, None counting as empty
        - refers_to_earlier is refers_to_earlier of the predicted text, reported and never used to exclude a pair
        - a yes/no or multiple-choice pair also carries option_mismatch; the other types have no options and no such key
        - key maps each pair id to { arm, model }
        - a forecast of a card not in cards makes nothing
    """
    pairs, key = {}, {}
    for card_id, arm, forecast in forecasts:
        card = cards.get( card_id )
        if card is None: continue
        for field_key, predicted, actual in texts_of( card[ "response_type" ], forecast, card[ "actual_value" ] ):
            pair_id          = pair_id_of( card_id, field_key, arm )
            pairs[ pair_id ] = { "pair_id": pair_id, "notification_id": card_id, "response_type": card[ "response_type" ], "field_key": field_key,
                                 "predicted_text": predicted, "actual_text": actual,
                                 "literal_mismatch": ( predicted or "" ).strip().lower() != ( actual or "" ).strip().lower(),
                                 "refers_to_earlier": refers_to_earlier( predicted ) }
            if card[ "response_type" ] in CHOICE_TYPES: pairs[ pair_id ][ "option_mismatch" ] = option_mismatch( card, field_key, forecast )
            key[ pair_id ]   = { "arm": arm, "model": models[ arm ] }
    return [ pairs[ one ] for one in sorted( pairs ) ], key


def human_cards( session, ids ):
    """
    Read the cards that a person answered.

    Requires:
        - session is the scratch session; ids are card ids

    Ensures:
        - returns { card id: { response_type, actual_value, options } } for the ids whose stored answer is a person's own and a string
    """
    cards = {}
    for row in session.query( Notification ).filter( Notification.id.in_( [ uuid.UUID( one ) for one in ids ] ) ):
        if answer_source_of( row.response_value, row.response_options ) != "human": continue
        value = row.response_value.get( "value" )
        if isinstance( value, str ): cards[ str( row.id ) ] = { "response_type": row.response_type, "actual_value": value, "options": row.response_options }
    return cards


def stored_forecasts( session, records_path, twins_path ):
    """
    Read every arm's forecasts: the run 2 record files and the scratch copy's rows.

    Requires:
        - session is the scratch session; the paths are run 2's record files

    Ensures:
        - returns { ( card id, arm ): forecast or None }; the copy's rows win over a record file for the same card and arm
    """
    found = {}
    for path in ( records_path, twins_path ):
        for line in read_jsonl( path ):
            for arm, entry in line[ "arms" ].items(): found[ ( line[ "id" ], arm ) ] = entry[ "forecast" ]
    for row in session.query( PredictionArmForecast ): found[ ( str( row.notification_id ), row.arm ) ] = row.forecast
    return found


def count_table( pairs, key, forecasts, cards ):
    """
    Count, per arm and card type, the forecasts, abstentions, pairs and mismatches.

    Requires:
        - pairs and key are make_pairs's; forecasts is stored_forecasts's; cards is human_cards's

    Ensures:
        - returns { arm: { card type: { cards, abstained, pairs, literal_mismatch, option_mismatch, refers_to_earlier } } }; a type without options counts 0
    """
    table = {}
    def cell( arm, kind ):
        """Give the counts of one arm and card type."""
        return table.setdefault( arm, {} ).setdefault( kind, { "cards": 0, "abstained": 0, "pairs": 0, "literal_mismatch": 0, "option_mismatch": 0, "refers_to_earlier": 0 } )
    for ( card_id, arm ), forecast in forecasts.items():
        if card_id not in cards: continue
        counts = cell( arm, cards[ card_id ][ "response_type" ] )
        counts[ "cards" ]     += 1
        counts[ "abstained" ] += not forecast
    for pair in pairs:
        counts = cell( key[ pair[ "pair_id" ] ][ "arm" ], pair[ "response_type" ] )
        counts[ "pairs" ]            += 1
        counts[ "literal_mismatch" ] += pair[ "literal_mismatch" ]
        counts[ "option_mismatch" ]  += pair.get( "option_mismatch", False )
        counts[ "refers_to_earlier" ] += pair[ "refers_to_earlier" ]
    return table


def card_rows( session, ids ):
    """
    Give each paired card as it was shown, with the stored answer.

    Requires:
        - session is the scratch session; ids are card ids

    Ensures:
        - returns one { notification_id, response_type, message, abstract, options, answer } per id, sorted by id
        - notification_id is the string the pairs carry; answer is the stored response's "value" only, so no answerer is named
    """
    rows = session.query( Notification ).filter( Notification.id.in_( [ uuid.UUID( one ) for one in set( ids ) ] ) )
    return sorted( ( { "notification_id": str( row.id ), "response_type": row.response_type, "message": row.message, "abstract": row.abstract,
                       "options": row.response_options, "answer": row.response_value[ "value" ] } for row in rows ), key=lambda row: row[ "notification_id" ] )


def write_outputs( out, pairs, key, receipt, cards ):
    """
    Write the pairs, the sealed key, the receipt, the cards and their sha256 manifest.

    Requires:
        - out is a folder path; pairs and key are make_pairs's; receipt is JSON data; cards is card_rows's

    Ensures:
        - the folder holds PAIRS_NAME, KEY_NAME, RECEIPT_NAME, CARDS_NAME and MANIFEST_NAME
        - the manifest has one "<sha256>  <name>" line per other file, in sha256sum's format

    Raises:
        - FileExistsError when the folder already holds pairs, so a drawn set is never overwritten
    """
    os.makedirs( out, exist_ok=True )
    with open( os.path.join( out, PAIRS_NAME ), "x", encoding="utf-8" ) as handle:
        for pair in pairs: handle.write( json.dumps( pair, sort_keys=True ) + "\n" )
    with open( os.path.join( out, CARDS_NAME ), "w", encoding="utf-8" ) as handle:
        for card in cards: handle.write( json.dumps( card, sort_keys=True ) + "\n" )
    for name, data in ( ( KEY_NAME, key ), ( RECEIPT_NAME, receipt ) ):
        with open( os.path.join( out, name ), "w", encoding="utf-8" ) as handle: json.dump( data, handle, indent=1, sort_keys=True )
    with open( os.path.join( out, MANIFEST_NAME ), "w", encoding="utf-8" ) as handle:
        for name in ( PAIRS_NAME, KEY_NAME, RECEIPT_NAME, CARDS_NAME ): handle.write( f"{file_sha256( os.path.join( out, name ) )}  {name}\n" )


def history_rows( session ):
    """
    Count the answer history rows, and those that showed no earlier answer.

    Requires:
        - session is the scratch session

    Ensures:
        - returns { rows, showed_nothing } over the arm's rows; showed_nothing counts empty evidence ids
    """
    shown = [ row.evidence_ids for row in session.query( PredictionArmForecast ).filter( PredictionArmForecast.arm == ARM_HISTORY ) ]
    return { "rows": len( shown ), "showed_nothing": sum( 1 for ids in shown if not ids ) }


def run_forecast( args, session, live_scope, embed, out=print ):
    """
    Fill the scratch copy with every missing forecast.

    Requires:
        - args carries archive, types, work, limit, concurrency and budget; session is the scratch session
        - live_scope is None or a context-managed session factory on the live database; embed is a CachedServiceEmbedder or a double

    Ensures:
        - the copy gains the live answers it lacks, then one row per ( card, arm ) wanted
        - writes forecast-receipt.json in the work folder and returns it
    """
    add_missing_columns( session.get_bind() )
    imported = 0
    if live_scope is not None:
        with live_scope() as live: imported = import_live( session, live )
    records = os.path.join( args.archive, "records.jsonl" )
    with open( os.path.join( args.archive, "report.json" ), encoding="utf-8" ) as handle: freeze = json.load( handle )[ "freeze" ]
    PredictionEngine.reset()
    store    = store_of( session, PredictionEngine( debug=False ), embed )
    embed.flush()
    config   = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    c0       = context_baseline.ContextBaseline( context_baseline.context_model(), context_baseline.context_timeout(), context_baseline.context_layers(),
                                                 context_baseline.open_ledger( base_path=os.path.join( args.work, "ledger.jsonl" ), cli_path=model_transport.CLI_PATH ), full=True )
    factory  = archive_replay.locked_sessions( session.get_bind() )
    embedder = SimpleNamespace( encode=embed )
    limits   = { "bound": freeze[ "bound" ], "multiplier": freeze[ "fetch_multiplier" ] }
    cards    = archive_ids( records )
    budget   = args.budget
    if budget is None: budget = matched_budget( factory, cards, c0, embedder, embed.encoder, freeze[ "extractor_version" ], limits )
    held     = human_cards( session, sample_open_ids( args.types ) )
    opened   = sorted( held )
    work     = [ ( card, ARM_HISTORY ) for card in cards[ :args.limit ] ]
    work    += [ ( card, arm ) for card in opened[ :args.limit ] for arm in MODEL_ARMS ]
    counts   = asyncio.run( forecast_all( work, factory, c0, embedder, embed.encoder, freeze[ "extractor_version" ], store, budget,
                                          config.get_required( HALF_LIFE_KEY, return_type="float" ), limits, args.concurrency, out ) )
    embed.flush()
    with mock.patch.object( answer_history_forecast, "eligible_cases", eligible_without_meaning ): suffix = answer_history_forecast.version_suffix()
    receipt  = { "ruling": RULING, "imported_live_rows": imported, "budget_tokens": budget, "model": c0.model, "full_answer_reply": True,
                 "history_rows": history_rows( session ),
                 "predictor_version": c0.predictor_version, "answer_history_suffix": suffix,
                 "archive_cards": len( cards ), "open_cards": len( opened ), "jobs": sorted( [ str( k[ 0 ] ), k[ 1 ], str( k[ 2 ] ), n ] for k, n in counts.items() ) }
    with open( os.path.join( args.work, "forecast-receipt.json" ), "w", encoding="utf-8" ) as handle: json.dump( receipt, handle, indent=1 )
    return receipt


def record_sample( work, ids, per_type ):
    """
    Write down which cards the full stage will run, before it calls a model.

    Requires:
        - work is a folder; ids are full_sample's for per_type

    Ensures:
        - work holds sample.json: the seed, per_type, the ids and the sha256 of the ids, one per line
        - a file already there is kept when it names the same ids

    Raises:
        - ValueError when a file already there names other ids
    """
    record = { "seed": FULL_SAMPLE_SEED, "per_type": per_type, "ids_sha256": hashlib.sha256( "".join( f"{one}\n" for one in ids ).encode( "utf-8" ) ).hexdigest(), "ids": ids }
    path   = os.path.join( work, SAMPLE_NAME )
    if not os.path.exists( path ):
        with open( path, "x", encoding="utf-8" ) as handle: json.dump( record, handle, indent=1 )
        return record
    with open( path, encoding="utf-8" ) as handle: held = json.load( handle )
    if held[ "ids_sha256" ] != record[ "ids_sha256" ]: raise ValueError( f"{path} records another sample; use another work folder" )
    return held


def run_full( args, session, embed, out=print ):
    """
    Run the full-reply baseline and principles arms on a seeded sample of archive cards.

    Requires:
        - args carries archive, full_work, per_type and concurrency; session is over the full stage's own database
        - embed is a CachedServiceEmbedder or a double

    Ensures:
        - the sample is written by record_sample before any model is called
        - each sampled card gains one row per arm of FULL_ARMS, under that code, so run 2's rows are left as they are
        - writes full-receipt.json in the full work folder and returns it
    """
    add_missing_columns( session.get_bind() )
    records = os.path.join( args.archive, "records.jsonl" )
    sample  = record_sample( args.full_work, full_sample( records, args.per_type ), args.per_type )
    with open( os.path.join( args.archive, "report.json" ), encoding="utf-8" ) as handle: freeze = json.load( handle )[ "freeze" ]
    c0      = context_baseline.ContextBaseline( context_baseline.context_model(), context_baseline.context_timeout(), context_baseline.context_layers(),
                                                context_baseline.open_ledger( base_path=os.path.join( args.full_work, "ledger.jsonl" ), cli_path=model_transport.CLI_PATH ), full=True )
    counts  = asyncio.run( forecast_all( [ ( card, arm ) for card in sample[ "ids" ] for arm in FULL_ARMS ], archive_replay.locked_sessions( session.get_bind() ), c0,
                                         SimpleNamespace( encode=embed ), embed.encoder, freeze[ "extractor_version" ], None, None, None,
                                         { "bound": freeze[ "bound" ], "multiplier": freeze[ "fetch_multiplier" ] }, args.concurrency, out ) )
    embed.flush()
    receipt = { "model": c0.model, "predictor_version": c0.predictor_version, "seed": sample[ "seed" ], "per_type": sample[ "per_type" ], "cards": len( sample[ "ids" ] ),
                "ids_sha256": sample[ "ids_sha256" ], "jobs": sorted( [ str( k[ 0 ] ), k[ 1 ], str( k[ 2 ] ), n ] for k, n in counts.items() ) }
    with open( os.path.join( args.full_work, "full-receipt.json" ), "w", encoding="utf-8" ) as handle: json.dump( receipt, handle, indent=1 )
    return receipt


def full_stage_forecasts( full_work ):
    """
    Read the full stage's forecasts and receipt.

    Requires:
        - full_work is the full stage's work folder after it ran

    Ensures:
        - returns ( { ( card id, arm ): forecast or None } for the arms of FULL_ARMS only, the receipt )
    """
    with scratch_session( os.path.join( full_work, "archive.sqlite" ) ) as session:
        found = { ( str( row.notification_id ), row.arm ): row.forecast for row in session.query( PredictionArmForecast ).filter( PredictionArmForecast.arm.in_( FULL_ARMS ) ) }
    with open( os.path.join( full_work, "full-receipt.json" ), encoding="utf-8" ) as handle: return found, json.load( handle )


def run_pairs( args, session, models ):
    """
    Write the blinded pairs from the forecasts held.

    Requires:
        - args carries archive, types, work, full_work and out; session is the scratch session after run_forecast
        - the full stage has run in args.full_work
        - models maps every arm held to its model id

    Ensures:
        - writes the pairs folder and returns the receipt: counts per arm and card type, and both runs' receipts
    """
    records   = os.path.join( args.archive, "records.jsonl" )
    forecasts = stored_forecasts( session, records, os.path.join( args.archive, "twin-records.jsonl" ) )
    extra, full_ran = full_stage_forecasts( args.full_work )
    forecasts.update( extra )
    cards     = human_cards( session, archive_ids( records ) + sample_open_ids( args.types ) )
    pairs, key = make_pairs( cards, ( ( card, arm, forecast ) for ( card, arm ), forecast in forecasts.items() ), models )
    with open( os.path.join( args.work, "forecast-receipt.json" ), encoding="utf-8" ) as handle: ran = json.load( handle )
    receipt = { "pairs": len( pairs ), "cards": dict( Counter( card[ "response_type" ] for card in cards.values() ) ),
                "counts": count_table( pairs, key, forecasts, cards ), "forecast_run": ran, "full_run": full_ran }
    write_outputs( args.out, pairs, key, receipt, card_rows( session, [ pair[ "notification_id" ] for pair in pairs ] ) )
    return receipt


def arm_models( haiku, opus ):
    """
    Name each arm's model.

    Requires:
        - haiku and opus are model ids

    Ensures:
        - the baseline, principles and answer history arms map to haiku, the two twins to opus, the fixed rules and the engine to "none"
    """
    return { **{ arm: haiku for arm in MODEL_ARMS + FULL_ARMS }, **{ arm: opus for arm in archive_replay.TWIN_ARMS }, **{ arm: "none" for arm in NO_MODEL_ARMS } }


def prepare_work( archive, work ):
    """
    Make the work folder from copies of the run 2 database and vector cache.

    Requires:
        - archive holds archive.sqlite and embeddings.json

    Ensures:
        - work holds a copy of each; a copy already there is left as it is, so a run resumes
        - returns ( database path, cache path )
    """
    os.makedirs( work, exist_ok=True )
    made = []
    for name in ( "archive.sqlite", "embeddings.json" ):
        target = os.path.join( work, name )
        if not os.path.exists( target ): shutil.copyfile( os.path.join( archive, name ), target )
        made.append( target )
    return tuple( made )


def main( argv=None, live_scope=None, make_embed=CachedServiceEmbedder, out=print ):
    """
    Run one of the three stages.

    Requires:
        - the environment names the configuration; for forecast, the embedding service and, unless live_scope is given, the live database are reachable

    Ensures:
        - forecast fills the work folder's copy; full fills the full work folder's own copy; pairs writes the pairs folder; each prints its receipt and returns 0
    """
    root   = cu.get_project_root()
    parser = argparse.ArgumentParser( description="Blinded forecast-and-answer pairs from every arm." )
    parser.add_argument( "stage", choices=( "forecast", "full", "pairs" ) )
    parser.add_argument( "--archive", default=root + "/io/phase4-archive-run-2" )
    parser.add_argument( "--types", default=root + "/io/gold-labels/item-card-types.json" )
    parser.add_argument( "--work", default=root + "/io/judge-validation/work" )
    parser.add_argument( "--out", default=root + "/io/judge-validation/pairs" )
    parser.add_argument( "--limit", type=int, default=None, help="first N cards of each group, for a trial" )
    parser.add_argument( "--concurrency", type=int, default=6 )
    parser.add_argument( "--full-work", default=root + "/io/judge-validation/full", help="work folder of the full stage, with its own database" )
    parser.add_argument( "--per-type", type=int, default=300, help="archive cards of each type the full stage runs" )
    parser.add_argument( "--budget", type=int, default=None, help="history token budget; measured from the principle blocks when absent" )
    args = parser.parse_args( argv )
    database, cache = prepare_work( args.archive, args.full_work if args.stage == "full" else args.work )
    with contextlib.ExitStack() as stack:
        session = stack.enter_context( scratch_session( database ) )
        if args.stage == "forecast":
            if live_scope is None:
                from cosa.rest.db.database import get_db as live_scope
            receipt = run_forecast( args, session, live_scope, make_embed( cache ), out )
        elif args.stage == "full": receipt = run_full( args, session, make_embed( cache ), out )
        else:
            add_missing_columns( session.get_bind() )
            with open( os.path.join( args.archive, "report.json" ), encoding="utf-8" ) as handle: freeze = json.load( handle )[ "freeze" ]
            receipt = run_pairs( args, session, arm_models( freeze[ "baseline_model" ], freeze[ "twin_model" ] ) )
    out( json.dumps( receipt, indent=1, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit( main() )
