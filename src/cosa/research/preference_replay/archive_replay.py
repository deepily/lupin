"""
Replay the archive of asks through the forecasting arms and the Opus twins.

The run uses replay_loop.replay as its one harness, and no second one.
Every ask outside the fixture is predicted by the case-based engine and by the fixed rules.
The baseline Haiku forecast and the principles forecast run through their own jobs, over a scratch copy of the tables.
Principles are extracted from each answer as time reaches it, so each ask sees only what was known then.
The Opus twins run in a second stage that trails the first, so they never set its pace.
Every stage writes into a work folder and can be stopped and started again from its last checkpoint.
The report pairs the arms with replay_loop.summarize at a floor stated before the run.
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from sqlalchemy.orm import Session

from cosa.agents.prediction_engine import context_baseline, opus_twins, principle_retrieval, principles_forecast
from cosa.agents.prediction_engine.episode_view import fields_of
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.principle_learner import opus_call, principles_call
from cosa.agents.principle_learner.extractor_prompt import PROMPT_VERSION
from cosa.repo.doc_lint import model_transport
from cosa.research.preference_replay.extractor_replay import ExtractorReplay, asks_from_session, check_no_leakage, make_recorder
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, _score, replay, summarize
from cosa.research.preference_replay.scratch_db import load_export, scratch_session
from cosa.research.preference_replay.service_embeddings import CachedServiceEmbedder
from cosa.rest.repair_attempt_tracker import cosine_similarity
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PreferenceEvidence, PreferencePrinciple
from cosa.utils.iso_timestamp import aware_moment

ARM_FIXED       = "A0"
ARM_BASELINE    = context_baseline.ARM
ARM_PRINCIPLES  = principles_forecast.ARM
HAIKU_ARMS      = ( ARM_BASELINE, ARM_PRINCIPLES )
TWIN_ARMS       = ( opus_twins.ARM_BASELINE_OPUS, opus_twins.ARM_PRINCIPLES_OPUS )
RECORDED_ARMS   = ( ENGINE_ARM, ARM_FIXED ) + HAIKU_ARMS
ELIGIBLE_TYPES  = ( "yes_no", "multiple_choice" )
OPERATIONAL_FLOOR = 10
REPLAY_LAG      = timedelta( seconds=0 )
CHUNK_SIZE      = 250
EXTRACTOR_MODEL = "claude-sonnet-5-5"
RECORDER_ARM    = "recorder"
STAND_IN_PRIORITY = "medium"
FLUSH_EVERY     = 500
LABELS          = { ENGINE_ARM: "A1", ARM_FIXED: "A0" }
PAIRINGS        = ( ( ARM_PRINCIPLES, ARM_BASELINE ), ( ARM_PRINCIPLES, ENGINE_ARM ), ( ARM_PRINCIPLES, ARM_FIXED ), ( ARM_BASELINE, ENGINE_ARM ),
                    ( TWIN_ARMS[ 0 ], ARM_BASELINE ), ( TWIN_ARMS[ 1 ], ARM_PRINCIPLES ) )

_DB_LOCK = threading.RLock()


def read_jsonl( path ):
    """
    Read a JSON-lines file.

    Requires:
        - path names a readable file with one JSON object per line

    Ensures:
        - returns the objects in file order, skipping blank lines
    """
    with open( path, encoding="utf-8" ) as handle: return [ json.loads( line ) for line in handle if line.strip() ]


class PeriodicFlush:
    """
    An embedder that writes its side file as it goes.

    Requires:
        - embedder is a CachedServiceEmbedder or a double with encoder, calls, flush and a call that takes a text
        - every is a positive number of service calls between writes

    Ensures:
        - calling it returns the embedder's vector for the text
        - the side file is written after every `every` service calls, and on flush
        - a text answered from the cache makes no call and no write
    """

    def __init__( self, embedder, every=FLUSH_EVERY ):
        self.embedder = embedder
        self.every    = every
        self.written  = embedder.calls
        self.encoder  = embedder.encoder

    def __call__( self, text ):
        vector = self.embedder( text )
        if self.embedder.calls - self.written >= self.every: self.flush()
        return vector

    def flush( self ):
        """
        Write the side file now.

        Ensures:
            - the embedder's file holds every vector made so far
        """
        self.embedder.flush()
        self.written = self.embedder.calls


def load_archive( session, asks_path, nonasks_path ):
    """
    Load every archived notification, asks and the rest, into the scratch copy.

    Requires:
        - session is an active session over the scratch tables
        - both paths are JSON-lines files of notification rows

    Ensures:
        - returns the number of notifications inserted
        - a row with no priority, as the archive's rows have none, gets STAND_IN_PRIORITY, which no forecast reads, because the column cannot be empty
        - a copy that already holds notifications is left as it is and 0 is returned, so a resumed run never loads twice
    """
    if session.query( Notification ).count() > 0: return 0
    rows = [ { "priority": STAND_IN_PRIORITY, **raw } for raw in read_jsonl( asks_path ) + read_jsonl( nonasks_path ) ]
    return load_export( session, { "targets": [], "records": { raw[ "id" ]: { "notification": raw } for raw in rows } } )


def fixture_ids( export_path ):
    """
    Name the asks of the development fixture.

    Requires:
        - export_path is a context export with a targets list

    Ensures:
        - returns the set of target notification ids
    """
    with open( export_path, encoding="utf-8" ) as handle: export = json.load( handle )
    return { target[ "target_notification" ][ "id" ] for target in export[ "targets" ] }


def evaluation_ids( asks, fixture ):
    """
    List the asks the evaluation predicts, in the order the replay predicts them.

    Requires:
        - asks are the replay's ask dicts; fixture is a set of ask ids

    Ensures:
        - returns the ids of yes/no and multiple-choice asks outside the fixture, ordered by ask time and then by position
        - an ask in the fixture is left out of the list and still serves as a case
    """
    order = sorted( range( len( asks ) ), key=lambda i: ( aware_moment( asks[ i ][ "asked_at" ] ), i ) )
    return [ asks[ i ][ "id" ] for i in order if asks[ i ][ "response_type" ] in ELIGIBLE_TYPES and asks[ i ][ "id" ] not in fixture ]


def _pick( field ):
    """
    Choose the label the fixed rules pick for one option field.

    Requires:
        - field is one of fields_of's fields with at least one option

    Ensures:
        - returns the one recommended label when exactly one option is recommended, else the first label
        - a multi-select field returns that label as a one-item list
    """
    recommended = [ option[ "label" ] for option in field[ "options" ] if option[ "recommended" ] ]
    label       = recommended[ 0 ] if len( recommended ) == 1 else field[ "options" ][ 0 ][ "label" ]
    return [ label ] if field[ "mode" ] == "multi" else label


def fixed_rules_arm( ask, visible_rows ):
    """
    Forecast with the fixed rules: yes, or the recommended or first option.

    Requires:
        - ask is an ask dict with response_type and response_options

    Ensures:
        - returns { "value": "yes" } for a yes/no ask
        - returns { "answers": { header: pick } } for a multiple-choice ask, one entry per field that offers options
        - returns None for a card with no option to pick, and for any other type
    """
    if ask[ "response_type" ] == "yes_no": return { "value": "yes" }
    if ask[ "response_type" ] != "multiple_choice": return None
    answers = { field[ "key" ]: _pick( field ) for field in fields_of( ask[ "response_options" ], None ) if field[ "options" ] }
    return { "answers": answers } if answers else None


def scratch_topk( session, model, vector_column, query_embedding, limit, exclude_filter=None, threshold_pct=None, clamp=False, metric="dot" ):
    """
    Search the scratch copy for the nearest rows by cosine, in Python.

    The live search runs in the database with a vector operator that SQLite does not have.
    This takes the live search's arguments and returns what it returns for the cosine metric.

    Requires:
        - session is an active session; exclude_filter keeps the rows to search, as the live search's does
        - each row's vector is a list of floats the width of query_embedding

    Ensures:
        - returns at most limit pairs of ( cosine times 100, row ), best first
    """
    pairs = [ ( cosine_similarity( list( row.embedding ), list( query_embedding ) ) * 100.0, row ) for row in session.query( model ).filter( exclude_filter ).all() ]
    return sorted( pairs, key=lambda pair: -pair[ 0 ] )[ :limit ]


def locked_sessions( bind ):
    """
    Make the session factory the arms' jobs use over the one scratch connection.

    Requires:
        - bind is the scratch engine

    Ensures:
        - returns a function that gives a context-managed session, one new session per call
        - the connection is held for the whole block, so two jobs on two threads never use it together
    """
    @contextlib.contextmanager
    def factory():
        with _DB_LOCK:
            with Session( bind ) as session: yield session
    return factory


class ModelArms:
    """
    The four model arms as the jobs run them, with each ask's rows read back for the harness.

    Requires:
        - factory is a locked_sessions factory; c0 is the baseline contract
        - embed maps a text to a vector; encoder and extractor name the principle versions in use
        - gates maps each arm in HAIKU_ARMS and TWIN_ARMS to its CapGate

    Ensures:
        - an arm runs through its own job with its switch forced on, so no INI switch changes
        - a result row is read back as ( forecast, reason ); a missing row reads as ( None, "no_row" )
    """

    def __init__( self, factory, c0, embed, encoder, extractor, gates ):
        self.factory   = factory
        self.c0        = c0
        self.embedder  = SimpleNamespace( encode=embed )
        self.encoder   = encoder
        self.extractor = extractor
        self.gates     = gates
        self.rows      = {}

    def _job( self, arm, ask_id ):
        """
        Start one arm's job for one ask.

        Requires:
            - arm is in HAIKU_ARMS or TWIN_ARMS

        Ensures:
            - returns the job's awaitable; the job is the one the live service runs for that arm
        """
        gate = self.gates[ arm ]
        if arm == ARM_BASELINE: return context_baseline.run_context_forecast( ask_id, self.factory, self.c0, gate, enabled=True )
        if arm == ARM_PRINCIPLES: return principles_forecast.run_b1( self.factory, ask_id, self.c0, self.embedder, self.encoder, self.extractor, gate, enabled=True )
        if arm == TWIN_ARMS[ 0 ]: return opus_twins.run_baseline_opus( self.factory, ask_id, self.c0, gate, enabled=True )
        return opus_twins.run_principles_opus( self.factory, ask_id, self.c0, self.embedder, self.encoder, self.extractor, gate, enabled=True )

    async def _gather( self, arms, ask_id ):
        """
        Run several arms for one ask at once.

        Ensures:
            - returns each job's { status, reason } in the order of arms
        """
        return await asyncio.gather( *( self._job( arm, ask_id ) for arm in arms ) )

    def run( self, ask_id, arms ):
        """
        Run the arms for one ask, then read their rows.

        Requires:
            - ask_id names a loaded notification

        Ensures:
            - returns a Counter of ( arm, status, reason ) for the jobs just run
            - self.rows holds ( forecast, reason ) for each arm of this ask
        """
        with mock.patch.object( principle_retrieval, "dot_topk", scratch_topk ): results = asyncio.run( self._gather( arms, ask_id ) )
        with self.factory() as session:
            for arm in arms:
                row = session.query( PredictionArmForecast ).filter( PredictionArmForecast.notification_id == uuid.UUID( ask_id ), PredictionArmForecast.arm == arm ).first()
                self.rows[ ( ask_id, arm ) ] = ( None, "no_row" ) if row is None else ( row.forecast, row.abstention_reason )
        return Counter( ( arm, result[ "status" ], result[ "reason" ] ) for arm, result in zip( arms, results ) )

    def reader( self, arm ):
        """
        Make the baseline function that hands the harness an arm's stored forecast.

        Requires:
            - run was called for the ask, for this arm, before the harness calls the function

        Ensures:
            - returns a function that gives the arm's forecast, or None for an abstention
        """
        return lambda ask_at_ask, visible_rows, episode_view=None, principles=None: self.rows[ ( ask_at_ask[ "id" ], arm ) ][ 0 ]


def default_models( session, embed, encoder, extractor, work ):
    """
    Build the model arms from the INI settings.

    Requires:
        - session is the scratch session; work is the work folder paths

    Ensures:
        - the baseline is made from the INI model, timeout and layers, with its ledger in the work folder
        - the caps come from the INI keys the live jobs read
    """
    c0    = context_baseline.ContextBaseline( context_baseline.context_model(), context_baseline.context_timeout(), context_baseline.context_layers(),
                                             context_baseline.open_ledger( base_path=work.ledger, cli_path=model_transport.CLI_PATH ) )
    gates = { ARM_BASELINE: context_baseline.context_gate(), ARM_PRINCIPLES: principles_call.get_gate(),
              TWIN_ARMS[ 0 ]: opus_call.get_gate( TWIN_ARMS[ 0 ] ), TWIN_ARMS[ 1 ]: opus_call.get_gate( TWIN_ARMS[ 1 ] ) }
    return ModelArms( locked_sessions( session.get_bind() ), c0, embed, encoder, extractor, gates )


class WorkFolder:
    """
    The files one archive run keeps, named from a folder.

    Requires:
        - root is a folder path that exists
    """

    def __init__( self, root ):
        self.database = os.path.join( root, "archive.sqlite" )
        self.state    = os.path.join( root, "state.json" )
        self.records  = os.path.join( root, "records.jsonl" )
        self.twins    = os.path.join( root, "twin-records.jsonl" )
        self.log      = os.path.join( root, "checkpoints.log" )
        self.cache    = os.path.join( root, "embeddings.json" )
        self.ledger   = os.path.join( root, "ledger.jsonl" )
        self.report   = os.path.join( root, "report.json" )


def load_state( path ):
    """
    Read the checkpoint of the first stage.

    Ensures:
        - returns { extracted_ids, done_ids, not_replayable, unrebuildable, context_asks }, empty when the file is absent
    """
    if not os.path.exists( path ): return { "extracted_ids": [], "done_ids": [], "not_replayable": 0, "unrebuildable": 0, "context_asks": 0 }
    with open( path, encoding="utf-8" ) as handle: return json.load( handle )


def save_state( path, state ):
    """
    Write the checkpoint without ever leaving a half-written file.

    Ensures:
        - the file holds the whole state, or keeps the old one if the write is cut short
    """
    temporary = f"{path}.tmp"
    with open( temporary, "w", encoding="utf-8" ) as handle: json.dump( state, handle )
    os.replace( temporary, path )


def append_lines( path, objects ):
    """
    Add one JSON line per object to a file.

    Ensures:
        - each object is one line; the file is created when absent
    """
    with open( path, "a", encoding="utf-8" ) as handle:
        for item in objects: handle.write( json.dumps( item ) + "\n" )


def extracted_in_db( session, version ):
    """
    Name the answers whose evidence the database already holds.

    Requires:
        - version is the extractor version the run writes under

    Ensures:
        - returns the set of notification ids with an evidence row of that version
    """
    return { str( row.notification_id ) for row in session.query( PreferenceEvidence ).filter( PreferenceEvidence.extractor_version == version ) }


def checkpoint_line( done, total, state, session, counts, context_in_chunk ):
    """
    Describe one checkpoint in a line.

    Requires:
        - done and total are ask counts; counts is a Counter of job results for the chunk

    Ensures:
        - returns a line with the asks done, the principles and evidence held, the asks with an episode history, and the job results by reason
    """
    results = ", ".join( f"{arm} {status}/{reason}={n}" for ( arm, status, reason ), n in sorted( counts.items(), key=str ) )
    return ( f"[checkpoint] {done}/{total} asks, principles {session.query( PreferencePrinciple ).count()}, evidence {session.query( PreferenceEvidence ).count()}, "
             f"asks with an episode history {context_in_chunk} in this chunk and {state[ 'context_asks' ]} so far; {results}" )


def run_first_stage( session, asks, ids, engine, embed, models, work, model=EXTRACTOR_MODEL, timeout_seconds=30, query_fn=None, chunk=CHUNK_SIZE, out=print ):
    """
    Predict the evaluation asks in time order with every arm but the twins.

    Requires:
        - asks are the replay's ask dicts and ids the evaluation ids in replay order
        - models is a ModelArms; work is a WorkFolder; the scratch tables hold the archive

    Ensures:
        - principles are extracted from every answer once time reaches it, so no arm sees a later answer
        - each chunk of asks is replayed by replay_loop.replay, checked for leakage, then written to records.jsonl and the checkpoint
        - a chunk already done in the checkpoint is skipped, and an answer already extracted is not extracted again
        - returns the number of asks predicted in this call

    Raises:
        - LeakageError if any arm was handed evidence from after its ask
    """
    state     = load_state( work.state )
    version   = f"{model}:{PROMPT_VERSION}"
    extracted = set( state[ "extracted_ids" ] ) | extracted_in_db( session, version )
    runner    = ExtractorReplay( session, asks, REPLAY_LAG, query_fn=query_fn, embed_fn=embed, model=model, encoder=embed.encoder, timeout_seconds=timeout_seconds )
    runner.pending = [ ask for ask in runner.pending if ask[ "id" ] not in extracted ]
    seen      = []
    chunk_context = [ 0 ]

    def episode_provider( ask_at_ask, visible_rows ):
        view = runner.episode_provider( ask_at_ask, visible_rows )
        if view[ "history" ]: chunk_context[ 0 ] += 1
        return view

    counts = Counter()

    def principles_provider( ask_at_ask, asked_at ):
        found = runner.principles_provider( ask_at_ask, asked_at )
        counts.update( models.run( ask_at_ask[ "id" ], HAIKU_ARMS ) )
        return found

    done_ids = set( state[ "done_ids" ] )
    todo     = [ ask_id for ask_id in ids if ask_id not in done_ids ]
    baselines = { ARM_FIXED: fixed_rules_arm, ARM_BASELINE: models.reader( ARM_BASELINE ), ARM_PRINCIPLES: models.reader( ARM_PRINCIPLES ), RECORDER_ARM: make_recorder( seen ) }
    sha       = hashlib.sha256( "\n".join( ids ).encode( "utf-8" ) ).hexdigest()
    for start in range( 0, len( todo ), chunk ):
        part = todo[ start:start + chunk ]
        chunk_context[ 0 ] = 0
        counts.clear()
        run = replay( asks, engine, sha, baselines=baselines, target_types=ELIGIBLE_TYPES, context_arms=( ARM_BASELINE, ARM_PRINCIPLES, RECORDER_ARM ),
                      episode_view_provider=episode_provider, principles_provider=principles_provider, target_ids=set( part ) )
        check_no_leakage( seen )
        seen.clear()
        append_lines( work.records, _record_lines( run, models ) )
        state[ "done_ids" ]      = state[ "done_ids" ] + [ r[ "meta" ][ "notification_id" ] for r in run[ "records" ][ ENGINE_ARM ] ]
        state[ "extracted_ids" ] = sorted( extracted | { item[ "notification_id" ] for item in runner.summaries } | { a for a in state[ "extracted_ids" ] } )
        state[ "not_replayable" ] += run[ "not_replayable" ]
        state[ "unrebuildable" ]  += run[ "unrebuildable_cases" ]
        state[ "context_asks" ]   += chunk_context[ 0 ]
        session.commit()
        embed.flush()
        save_state( work.state, state )
        line = checkpoint_line( len( state[ "done_ids" ] ), len( ids ), state, session, counts, chunk_context[ 0 ] )
        append_lines( work.log, [ { "line": line } ] )
        out( line )
        models.rows.clear()
    return len( todo )


def _record_lines( run, models ):
    """
    Turn one replayed chunk into one line per ask.

    Requires:
        - run is replay_loop.replay's result holding the arms in RECORDED_ARMS
        - models.rows holds the Haiku arms' rows for each ask of the chunk

    Ensures:
        - returns one dict per ask, in ask order, with its id, type, family and, per arm, correct, forecast and the reason for an abstention
    """
    lines = []
    for index, head in enumerate( run[ "records" ][ ENGINE_ARM ] ):
        arms = {}
        for name in RECORDED_ARMS:
            meta = run[ "records" ][ name ][ index ][ "meta" ]
            arms[ name ] = { "correct": meta[ "correct" ], "forecast": meta[ "forecast" ], "reason": models.rows.get( ( meta[ "notification_id" ], name ), ( None, None ) )[ 1 ] }
        lines.append( { "id": head[ "meta" ][ "notification_id" ], "response_type": head[ "meta" ][ "response_type" ], "family": head[ "meta" ][ "family" ], "arms": arms } )
    return lines


def run_twin_stage( session, asks, ids, models, work, follow=False, poll_seconds=60, sleep=time.sleep, chunk=CHUNK_SIZE, out=print ):
    """
    Run the Opus twins over the evaluation asks, trailing the first stage.

    Requires:
        - asks are the replay's ask dicts; ids the evaluation ids in replay order
        - the first stage writes records.jsonl in the same work folder

    Ensures:
        - only an ask the first stage has recorded is run, so the twins never get ahead of it
        - each ask runs both twins at once, scores each row as the harness scores a forecast, and appends one line to twin-records.jsonl
        - an ask already in twin-records.jsonl is skipped
        - with follow True the stage waits for the first stage to record more asks; otherwise it stops when none is ready
        - returns the number of asks the twins ran in this call
    """
    by_id = { ask[ "id" ]: ask for ask in asks }
    ran   = 0
    while True:
        recorded = { line[ "id" ] for line in read_jsonl( work.records ) } if os.path.exists( work.records ) else set()
        finished = { line[ "id" ] for line in read_jsonl( work.twins ) } if os.path.exists( work.twins ) else set()
        ready    = [ ask_id for ask_id in ids if ask_id in recorded and ask_id not in finished ]
        if not ready:
            if follow and len( recorded ) < len( ids ):
                sleep( poll_seconds )
                continue
            return ran
        counts = Counter()
        for position, ask_id in enumerate( ready, start=1 ):
            counts.update( models.run( ask_id, TWIN_ARMS ) )
            ask = by_id[ ask_id ]
            arms = { arm: { "correct": _score( ask[ "response_type" ], models.rows[ ( ask_id, arm ) ][ 0 ], ask[ "actual_value" ], ask[ "response_options" ] ),
                            "forecast": models.rows[ ( ask_id, arm ) ][ 0 ], "reason": models.rows[ ( ask_id, arm ) ][ 1 ] } for arm in TWIN_ARMS }
            append_lines( work.twins, [ { "id": ask_id, "arms": arms } ] )
            ran += 1
            models.rows.clear()
            if ( len( finished ) + position ) % chunk == 0:
                line = f"[twin checkpoint] {len( finished ) + position} asks run; " + ", ".join( f"{arm} {status}/{reason}={n}" for ( arm, status, reason ), n in sorted( counts.items(), key=str ) )
                append_lines( work.log, [ { "line": line } ] )
                out( line )
                counts.clear()


def _coverage( records, arm ):
    """
    Measure how much of the asks an arm forecast and how often it was right when it did.

    Requires:
        - records are the per-ask lines holding the arm

    Ensures:
        - returns { asks, answered, coverage, correct, accuracy_on_answered }; accuracy is None when nothing was answered
    """
    answered = [ r for r in records if r[ "arms" ][ arm ][ "forecast" ] is not None ]
    correct  = sum( 1 for r in answered if r[ "arms" ][ arm ][ "correct" ] )
    return { "asks": len( records ), "answered": len( answered ), "coverage": len( answered ) / len( records ) if records else None,
             "correct": correct, "accuracy_on_answered": correct / len( answered ) if answered else None }


def _arm_view( line, twin_by_id, arm ):
    """
    Pick one arm's correct flag and forecast for one ask.

    Requires:
        - line is a first-stage line; twin_by_id maps an ask id to its twin-stage line

    Ensures:
        - an Opus twin's view comes from the twin stage's line, any other arm's from the first stage's
    """
    return twin_by_id[ line[ "id" ] ][ "arms" ][ arm ] if arm in TWIN_ARMS else line[ "arms" ][ arm ]


def build_report( records, twin_records, state, floor=OPERATIONAL_FLOOR ):
    """
    Pair the arms and say how much each forecast.

    Requires:
        - records are the first stage's lines in ask order; twin_records are the twin stage's lines
        - state is the first stage's checkpoint; floor is the discordant-pair floor stated before the run

    Ensures:
        - returns { asks, floor, pairings, context_asks, not_replayable, unrebuildable_cases_chunk_sum, twin_stretch }
        - each pairing is replay_loop.summarize over the two arms on the same asks, with coverage and accuracy on the asks answered beside it
        - an Opus pairing covers only the asks both twins have a line for, and its Haiku twin is cut to the same asks
        - a pairing whose arm has no line at all is reported as not run, with no verdict
    """
    twin_by_id = { line[ "id" ]: line for line in twin_records }
    stretch    = [ line for line in records if line[ "id" ] in twin_by_id ]
    pairings   = []
    for arm, baseline in PAIRINGS:
        twin   = arm in TWIN_ARMS
        rows   = stretch if twin else records
        if not rows:
            pairings.append( { "arm": LABELS.get( arm, arm ), "baseline": LABELS.get( baseline, baseline ), "status": "not run, blocked by no recorded asks for this pairing" } )
            continue
        views  = { name: [ _arm_view( line, twin_by_id, name ) for line in rows ] for name in ( arm, baseline ) }
        run    = { "records": { name: [ { "meta": { "correct": view[ "correct" ] } } for view in series ] for name, series in views.items() },
                   "not_replayable": state[ "not_replayable" ], "unrebuildable_cases": state[ "unrebuildable" ], "families": len( { json.dumps( line[ "family" ], sort_keys=True ) for line in rows } ) }
        shaped = [ { "arms": { name: views[ name ][ index ] for name in views } } for index in range( len( rows ) ) ]
        result = summarize( run, baseline, floor, arm=arm )
        pairings.append( { "arm": LABELS.get( arm, arm ), "baseline": LABELS.get( baseline, baseline ), "summary": result,
                           "arm_coverage": _coverage( shaped, arm ), "baseline_coverage": _coverage( shaped, baseline ) } )
    return { "asks": len( records ), "floor": floor, "pairings": pairings, "context_asks": state[ "context_asks" ], "not_replayable": state[ "not_replayable" ],
             "unrebuildable_cases_chunk_sum": state[ "unrebuildable" ], "twin_stretch": len( stretch ) }


def render_report( report ):
    """
    Write the report as a table, with no reading of the verdicts.

    Requires:
        - report is build_report's result

    Ensures:
        - returns markdown with one row per pairing: asks, discordant pairs both ways, floor met, the verdict word, and coverage and accuracy on answered per arm
    """
    lines = [ f"Evaluation asks: {report[ 'asks' ]}; discordant-pair floor {report[ 'floor' ]}; asks with an episode history {report[ 'context_asks' ]}; "
              f"twin stretch {report[ 'twin_stretch' ]} asks.", "",
              "| arm | against | asks | arm only right | other only right | floor met | verdict | arm coverage | arm accuracy answered | other coverage | other accuracy answered |",
              "|---|---|---|---|---|---|---|---|---|---|---|" ]
    for item in report[ "pairings" ]:
        if "summary" not in item:
            lines.append( f"| {item[ 'arm' ]} | {item[ 'baseline' ]} | {item[ 'status' ]} | | | | | | | | |" )
            continue
        s, a, b = item[ "summary" ], item[ "arm_coverage" ], item[ "baseline_coverage" ]
        lines.append( f"| {item[ 'arm' ]} | {item[ 'baseline' ]} | {s[ 'asks_replayed' ]} | {s[ 'engine_only_right' ]} | {s[ 'baseline_only_right' ]} | {s[ 'floor_met' ]} | {s[ 'verdict' ]} | "
                      f"{_pct( a[ 'coverage' ] )} | {_pct( a[ 'accuracy_on_answered' ] )} | {_pct( b[ 'coverage' ] )} | {_pct( b[ 'accuracy_on_answered' ] )} |" )
    return "\n".join( lines )


def _pct( value ):
    """
    Show a share as a percent, or a dash when there is none.

    Ensures:
        - returns "-" for None, else the share with one decimal and a percent sign
    """
    return "-" if value is None else f"{value * 100:.1f}%"


def main( argv=None, query_fn=None, embed=None, make_models=None, out=print ):
    """
    Run one stage of the archive replay from the command line.

    Requires:
        - argv is a list of arguments or None for sys.argv
        - query_fn and embed are None for the live services, or doubles for a test; make_models is None or a function( session, embed ) giving the model arms

    Ensures:
        - stage first predicts the evaluation asks with the engine, the fixed rules and the two Haiku arms, and stops with the work saved at each chunk
        - stage twins runs the Opus twins over the asks the first stage has recorded; --follow keeps waiting for more until all are recorded
        - stage report writes report.json and prints the pairing table
        - --limit N cuts the evaluation asks to the first N, so a trial never reaches a real run's work folder
        - returns 0
    """
    parser = argparse.ArgumentParser( description="Replay the archive of asks through the forecasting arms" )
    parser.add_argument( "stage", choices=( "first", "twins", "report" ) )
    parser.add_argument( "--work", required=True, help="the work folder; it must exist" )
    parser.add_argument( "--asks", help="the archive asks, JSON lines" )
    parser.add_argument( "--non-asks", help="the other archived notifications, JSON lines" )
    parser.add_argument( "--fixture", help="the development fixture's context export" )
    parser.add_argument( "--follow", action="store_true" )
    parser.add_argument( "--poll-seconds", type=int, default=60 )
    parser.add_argument( "--chunk", type=int, default=CHUNK_SIZE )
    parser.add_argument( "--limit", type=int, default=None, help="predict only the first N evaluation asks, for a short trial in its own work folder" )
    args = parser.parse_args( argv )
    work = WorkFolder( args.work )
    if args.stage == "report":
        records = read_jsonl( work.records )
        twins   = read_jsonl( work.twins ) if os.path.exists( work.twins ) else []
        report  = build_report( records, twins, load_state( work.state ) )
        with open( work.report, "w", encoding="utf-8" ) as handle: json.dump( report, handle, indent=1, default=str )
        out( render_report( report ) )
        return 0
    with scratch_session( work.database ) as session:
        embed = PeriodicFlush( CachedServiceEmbedder( work.cache ) ) if embed is None else embed
        load_archive( session, args.asks, args.non_asks )
        PredictionEngine.reset()
        engine = PredictionEngine( debug=False )
        asks   = asks_from_session( session, engine, embed )
        embed.flush()
        ids    = evaluation_ids( asks, fixture_ids( args.fixture ) )[ :args.limit ]
        models = default_models( session, embed, embed.encoder, f"{EXTRACTOR_MODEL}:{PROMPT_VERSION}", work ) if make_models is None else make_models( session, embed )
        if args.stage == "first": run_first_stage( session, asks, ids, engine, embed, models, work, query_fn=query_fn, chunk=args.chunk, out=out )
        else: run_twin_stage( session, asks, ids, models, work, follow=args.follow, poll_seconds=args.poll_seconds, chunk=args.chunk, out=out )
        embed.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
