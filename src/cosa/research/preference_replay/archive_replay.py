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
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from sqlalchemy.orm import Session

from cosa.agents.prediction_engine import context_baseline, opus_twins, principle_retrieval, principles_forecast
from cosa.agents.prediction_engine.episode_view import fields_of
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.agents.principle_learner import extractor_job, opus_call, principles_call
from cosa.agents.principle_learner.extractor_store import NEIGHBOURS
from cosa.agents.principle_learner.extractor_prompt import PROMPT_VERSION
import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager
from cosa.repo.doc_lint import model_transport
from cosa.research.preference_replay.checkpoint_report import FIRST_NAME, checkpoint_name
from cosa.research.preference_replay.extractor_replay import ExtractorReplay, asks_from_session, check_no_leakage, make_recorder
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, _score, replay, summarize
from cosa.research.preference_replay.scratch_db import load_export, scratch_session
from cosa.research.preference_replay.service_embeddings import CachedServiceEmbedder
from cosa.rest.repair_attempt_tracker import cosine_similarity
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PreferenceEvidence, PreferencePrinciple
from cosa.utils.iso_timestamp import aware_moment
from cosa.utils.jsonl_file import read_jsonl

ARM_FIXED       = "A0"
ARM_BASELINE    = context_baseline.ARM
ARM_PRINCIPLES  = principles_forecast.ARM
HAIKU_ARMS      = ( ARM_BASELINE, ARM_PRINCIPLES )
TWIN_ARMS       = ( opus_twins.ARM_BASELINE_OPUS, opus_twins.ARM_PRINCIPLES_OPUS )
RECORDED_ARMS   = ( ENGINE_ARM, ARM_FIXED ) + HAIKU_ARMS
ELIGIBLE_TYPES  = ( "yes_no", "multiple_choice" )
OPERATIONAL_FLOOR = 10
REPLAY_LAG      = timedelta( seconds=0 )
WINDOW_START    = datetime( 2026, 9, 10, tzinfo=timezone.utc )
CHUNK_SIZE      = 250
RECORDER_ARM    = "recorder"
STAND_IN_PRIORITY = "medium"
WARN_FRACTION   = 0.8
BOUND_REASON    = f"{principles_forecast.REASON_INPUT}: {principle_retrieval.PrincipleBoundExceeded.__name__}"
LEGACY_FREEZE   = { "fetch_multiplier": 0, "scored_against": FIRST_NAME }
STOP_EXIT       = 3
CHECKPOINT_PATH = "/src/conf/prediction-checkpoint.json"
CODE_KEYS       = ( "code_sha", "code_dirty" )
FLUSH_EVERY     = 500
LABELS          = { ENGINE_ARM: "A1", ARM_FIXED: "A0" }
PAIRINGS        = ( ( ARM_PRINCIPLES, ARM_BASELINE ), ( ARM_PRINCIPLES, ENGINE_ARM ), ( ARM_PRINCIPLES, ARM_FIXED ), ( ARM_BASELINE, ENGINE_ARM ),
                    ( TWIN_ARMS[ 0 ], ARM_BASELINE ), ( TWIN_ARMS[ 1 ], ARM_PRINCIPLES ) )

_DB_LOCK = threading.RLock()


class FreezeMismatch( RuntimeError ):
    """Raised when a run is asked to continue under other settings than it started with."""


class BoundStop( RuntimeError ):
    """
    Raised when a principles forecast fails on the limit and the stage stops.

    Carries ask_id, principles (the count held when it stopped) and bound (the limit read); the message names all three and the fix.
    """

    def __init__( self, ask_id, principles, bound ):
        self.ask_id     = ask_id
        self.principles = principles
        self.bound      = bound
        super().__init__( f"STOPPED AT THE PRINCIPLE LIMIT: ask {ask_id} could not be forecast, {principles} principles held against a limit of {bound}. "
                          f"Raise 'prediction learner principle limit' in the INI file and start the same stage again; finished work is kept." )


def extractor_settings():
    """
    Read the extractor's model id and timeout from the INI file, as the live job does.

    Ensures:
        - returns ( model id, timeout seconds ) from the keys the extractor job reads

    Raises:
        - MissingConfigKeyError if either key is absent
    """
    config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    return config.get_required( extractor_job.MODEL_KEY ), config.get_required( extractor_job.TIMEOUT_KEY, return_type="int" )


def tree_state( folder ):
    """
    Name the git commit of a folder's tree, and whether tracked files differ from it.

    Requires:
        - folder is inside a git working tree

    Ensures:
        - returns { sha, dirty }; dirty is True when a tracked file has an uncommitted change
    """
    sha   = subprocess.run( [ "git", "-C", folder, "rev-parse", "HEAD" ], capture_output=True, text=True, check=True ).stdout.strip()
    state = subprocess.run( [ "git", "-C", folder, "status", "--porcelain", "--untracked-files=no" ], capture_output=True, text=True, check=True ).stdout.strip()
    return { "sha": sha, "dirty": bool( state ) }


def current_freeze( models, code, scored_against=FIRST_NAME ):
    """
    List every setting that must not change inside one evaluation window.

    Requires:
        - models is a ModelArms; code is tree_state's result
        - scored_against is the name of the checkpoint the run is scored against, as checkpoint_report.checkpoint_name gives it

    Ensures:
        - the dict names scored_against, so a work folder started against one checkpoint is refused by check_freeze under the other; a freeze written before the key existed reads FIRST_NAME
        - returns a dict of the code commit, the vocabulary and extractor versions, the extractor timeout, the encoder, neighbours, k,
          the principle limit and fetch multiplier as read from the INI file, lag seconds, window start, floor and the baseline and Opus model ids
    """
    limits = principle_retrieval.retrieval_limits()
    return { "code_sha": code[ "sha" ], "code_dirty": code[ "dirty" ], "vocabulary_version": PROMPT_VERSION, "extractor_version": models.extractor,
             "extractor_timeout_seconds": extractor_settings()[ 1 ], "encoder": models.encoder, "neighbours": NEIGHBOURS, "k": principle_retrieval.DEFAULT_K,
             "bound": limits[ "bound" ], "fetch_multiplier": limits[ "multiplier" ], "lag_seconds": REPLAY_LAG.total_seconds(), "window_start": WINDOW_START.isoformat(), "floor": OPERATIONAL_FLOOR,
             "baseline_model": models.c0.model, "twin_model": opus_twins.opus_model(), "scored_against": scored_against }


def check_freeze( state, current, accept_code_change=None, now=None ):
    """
    Record the freeze on the first start and refuse a later start that differs.

    Requires:
        - state is the checkpoint dict; current is current_freeze's result
        - accept_code_change is None or "<old sha>:<new sha>", the caller's word that the code change does not alter what the run measures
        - now is None or an aware datetime stamped on the history entry

    Ensures:
        - with no freeze in the state, stores current there and returns True so the caller saves it
        - with a freeze that equals current, returns False and changes nothing
        - a freeze written before a key existed reads that key as its shipped default (LEGACY_FREEZE): a run frozen before the fetch multiplier existed ran with 0
        - a higher principle limit is allowed when the old multiplier was 0 and the multiplier is unchanged, because below the old limit both limits fetch the same principles
        - a code change is allowed only when accept_code_change names the frozen sha and the current sha as written, and the current tree is clean
        - an allowed change replaces the freeze with current and appends { at, changed, accepted_code_change } to state["freeze_history"]; returns True
        - nothing is written to the state on a refusal

    Raises:
        - FreezeMismatch naming each setting that differs, when any difference is not one of the two allowed changes
    """
    if "freeze" not in state:
        state[ "freeze" ] = current
        return True
    old       = { **LEGACY_FREEZE, **state[ "freeze" ] }
    differing = sorted( key for key in set( old ) | set( current ) if old.get( key ) != current.get( key ) )
    if not differing: return False
    refused   = [ key for key in differing if key not in ( "bound", *CODE_KEYS ) ]
    if "bound" in differing and not ( current[ "bound" ] > old[ "bound" ] and old[ "fetch_multiplier" ] == 0 ): refused.append( "bound" )
    if any( key in differing for key in CODE_KEYS ):
        named = f"{old[ 'code_sha' ]}:{current[ 'code_sha' ]}"
        if accept_code_change != named or old[ "code_sha" ] == current[ "code_sha" ] or current[ "code_dirty" ]: refused.extend( key for key in CODE_KEYS if key in differing )
    if refused: raise FreezeMismatch( f"this work folder was started under other settings; differing: {', '.join( sorted( set( refused ) ) )}" )
    stamp = ( datetime.now( timezone.utc ) if now is None else now ).isoformat()
    state.setdefault( "freeze_history", [] ).append( { "at": stamp, "changed": { key: [ old.get( key ), current.get( key ) ] for key in differing },
                                                       "accepted_code_change": accept_code_change if any( key in differing for key in CODE_KEYS ) else None } )
    state[ "freeze" ] = current
    return True


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


def evaluation_ids( asks, fixture, window_start=WINDOW_START ):
    """
    List the asks the evaluation predicts, in the order the replay predicts them.

    Requires:
        - asks are the replay's ask dicts; fixture is a set of ask ids; window_start is an aware datetime

    Ensures:
        - returns the ids of yes/no and multiple-choice asks outside the fixture, asked at or after window_start, ordered by ask time and then by position
        - an ask in the fixture or before the window is left out of the list and still serves as a case and as an extractor input
    """
    order = sorted( range( len( asks ) ), key=lambda i: ( aware_moment( asks[ i ][ "asked_at" ] ), i ) )
    return [ asks[ i ][ "id" ] for i in order if asks[ i ][ "response_type" ] in ELIGIBLE_TYPES and asks[ i ][ "id" ] not in fixture
             and aware_moment( asks[ i ][ "asked_at" ] ) >= window_start ]


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
        - limits is None, or { bound, multiplier } handed to every principles forecast in place of a read of the INI file; a stage sets it from the freeze

    Ensures:
        - an arm runs through its own job with its switch forced on, so no INI switch changes
        - a result row is read back as ( forecast, reason ); a missing row reads as ( None, "no_row" )
    """

    def __init__( self, factory, c0, embed, encoder, extractor, gates, limits=None ):
        self.limits    = limits
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
        if arm == ARM_PRINCIPLES: return principles_forecast.run_b1( self.factory, ask_id, self.c0, self.embedder, self.encoder, self.extractor, gate, enabled=True, limits=self.limits )
        if arm == TWIN_ARMS[ 0 ]: return opus_twins.run_baseline_opus( self.factory, ask_id, self.c0, gate, enabled=True )
        return opus_twins.run_principles_opus( self.factory, ask_id, self.c0, self.embedder, self.encoder, self.extractor, gate, enabled=True, limits=self.limits )

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

    def discard_bound_failures( self, ask_id, arms ):
        """
        Delete an ask's stored limit failures so the arm can be forecast again.

        Requires:
            - ask_id names a loaded notification; arms are in HAIKU_ARMS or TWIN_ARMS

        Ensures:
            - only a row whose reason is BOUND_REASON is deleted; a forecast, or a failure of another kind, is never touched
            - returns the number of rows deleted
        """
        with self.factory() as session:
            deleted = session.query( PredictionArmForecast ).filter( PredictionArmForecast.notification_id == uuid.UUID( ask_id ), PredictionArmForecast.arm.in_( arms ),
                                                                     PredictionArmForecast.abstention_reason == BOUND_REASON ).delete( synchronize_session=False )
            session.commit()
        return deleted

    def discard_unrecorded_limit_failures( self, arms, recorded_ids ):
        """
        Delete limit failures stored for asks that no record file holds.

        Requires:
            - arms are in HAIKU_ARMS or TWIN_ARMS; recorded_ids are the ask ids the stage's record file already holds

        Ensures:
            - a limit failure row of those arms for an ask not in recorded_ids is deleted, so that ask is forecast fresh
            - rows for recorded asks, other failures and forecasts are never touched
            - returns the number of rows deleted
        """
        with self.factory() as session:
            rows    = session.query( PredictionArmForecast ).filter( PredictionArmForecast.arm.in_( arms ), PredictionArmForecast.abstention_reason == BOUND_REASON ).all()
            orphans = [ row for row in rows if str( row.notification_id ) not in recorded_ids ]
            for row in orphans: session.delete( row )
            session.commit()
        return len( orphans )

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
        - returns { extracted_ids, done_ids, skipped_ids, not_replayable, unrebuildable, context_asks }, plus freeze once one was written; empty when the file is absent
    """
    if not os.path.exists( path ): return { "extracted_ids": [], "done_ids": [], "skipped_ids": [], "not_replayable": 0, "unrebuildable": 0, "context_asks": 0 }
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


def checkpoint_line( done, total, state, session, counts, context_in_chunk, bound ):
    """
    Describe one checkpoint in a line.

    Requires:
        - done and total are ask counts; counts is a Counter of job results for the chunk; bound is the frozen principle limit

    Ensures:
        - returns a line with the asks done, the principles held against the frozen limit, the evidence held, the asks with an episode history, and the job results by reason
        - the line ends with a warning once the principles reach WARN_FRACTION of the limit
    """
    results = ", ".join( f"{arm} {status}/{reason}={n}" for ( arm, status, reason ), n in sorted( counts.items(), key=str ) )
    return ( f"[checkpoint] {done}/{total} asks, principles {principle_progress( session, bound )}, evidence {session.query( PreferenceEvidence ).count()}, "
             f"asks with an episode history {context_in_chunk} in this chunk and {state[ 'context_asks' ]} so far; {results}" ) + warning_text( session, bound )


def principle_progress( session, bound ):
    """
    Show the principle count against the limit.

    Requires:
        - bound is the frozen limit

    Ensures:
        - returns "<count>/<limit> (<percent>%)"
    """
    count = session.query( PreferencePrinciple ).count()
    return f"{count}/{bound} ({count * 100 / bound:.0f}%)"


def warning_text( session, bound ):
    """
    Warn when the principle count nears the limit.

    Requires:
        - bound is the frozen limit

    Ensures:
        - returns "" below WARN_FRACTION of the limit, else a warning naming the setting to raise
    """
    count = session.query( PreferencePrinciple ).count()
    if count < bound * WARN_FRACTION: return ""
    return f" WARNING: principles are at {count * 100 / bound:.0f}% of the limit {bound}; above it the principles forecasts fail and the stage stops (raise 'prediction learner principle limit')"


def freeze_limits( models, state ):
    """
    Hand the frozen limit and multiplier to the model arms.

    No forecast then rereads the INI file.

    Requires:
        - state holds a freeze, as check_freeze leaves it; models is a ModelArms

    Ensures:
        - models.limits is { bound, multiplier } from the freeze
        - returns the frozen bound
    """
    models.limits = { "bound": state[ "freeze" ][ "bound" ], "multiplier": state[ "freeze" ][ "fetch_multiplier" ] }
    return models.limits[ "bound" ]


def bound_failed( counts ):
    """
    Say whether any job result in a Counter is a failure on the principle limit.

    Requires:
        - counts is a Counter of ( arm, status, reason )

    Ensures:
        - returns True when any key carries BOUND_REASON
    """
    return any( reason == BOUND_REASON for ( _arm, _status, reason ) in counts )


def replace_arms( path, replacements ):
    """
    Replace arm entries inside a JSON-lines file without ever leaving a half-written file.

    Requires:
        - replacements maps an ask id to { arm: entry }; every id is a line of the file

    Ensures:
        - each named arm of each named line holds the new entry; every other line and arm is byte-for-byte as read, in the same order
        - the line count is unchanged, so no ask is doubled or lost
    """
    lines = read_jsonl( path )
    for line in lines:
        if line[ "id" ] in replacements: line[ "arms" ].update( replacements[ line[ "id" ] ] )
    temporary = f"{path}.tmp"
    with open( temporary, "w", encoding="utf-8" ) as handle:
        for line in lines: handle.write( json.dumps( line ) + "\n" )
    os.replace( temporary, path )


def rerun_bound_failures( session, asks, models, work, arm, path, bound, per_field, out=print, chunk=CHUNK_SIZE ):
    """
    Forecast again every ask whose arm failed on the limit, and replace its entry.

    Requires:
        - arm is ARM_PRINCIPLES with path work.records, or TWIN_ARMS[ 1 ] with path work.twins; bound is the frozen limit, which models hands to the forecast
        - per_field is the engine's per-field multiple-choice switch, so the new entry is scored on the engine arms' basis
        - the scratch database holds the principles and evidence extracted so far, which are kept and never extracted again

    Ensures:
        - only a line whose arm reason is BOUND_REASON is run again; the arm's stored failure row is deleted first, then the arm alone runs, so no other arm is called
        - the new entry is scored as the harness scores a forecast; a new failure of another kind is recorded as that failure
        - the file is rewritten after every `chunk` asks and at the end, so a stop keeps what finished and the next start reruns only what still shows the limit failure
        - a failure on the limit again stops the stage at that ask: its row is deleted, the finished entries are written, and BoundStop is raised
        - returns the number of asks run again

    Raises:
        - BoundStop when the limit fails again
    """
    if not os.path.exists( path ): return 0
    by_id    = { ask[ "id" ]: ask for ask in asks }
    todo     = [ line[ "id" ] for line in read_jsonl( path ) if line[ "arms" ][ arm ][ "reason" ] == BOUND_REASON ]
    replaced = {}
    for position, ask_id in enumerate( todo, start=1 ):
        models.discard_bound_failures( ask_id, ( arm, ) )
        if bound_failed( models.run( ask_id, ( arm, ) ) ):
            models.discard_bound_failures( ask_id, ( arm, ) )
            if replaced: replace_arms( path, replaced )
            raise BoundStop( ask_id, session.query( PreferencePrinciple ).count(), bound )
        forecast, reason = models.rows[ ( ask_id, arm ) ]
        ask              = by_id[ ask_id ]
        replaced[ ask_id ] = { arm: { "correct": _score( ask[ "response_type" ], forecast, ask[ "actual_value" ], ask[ "response_options" ], per_field ), "forecast": forecast, "reason": reason } }
        models.rows.clear()
        if position % chunk == 0 or position == len( todo ):
            replace_arms( path, replaced )
            replaced.clear()
            line = f"[rerun {arm}] {position}/{len( todo )} failed forecasts run again under the frozen limit, principles {principle_progress( session, bound )}"
            append_lines( work.log, [ { "line": line } ] )
            out( line )
    return len( todo )


def run_first_stage( session, asks, ids, engine, embed, models, work, query_fn=None, chunk=CHUNK_SIZE, out=print, code=None, accept_code_change=None, scored_against=FIRST_NAME ):
    """
    Predict the evaluation asks in time order with every arm but the twins.

    Requires:
        - asks are the replay's ask dicts and ids the evaluation ids in replay order
        - models is a ModelArms; work is a WorkFolder; the scratch tables hold the archive

    Ensures:
        - principles are extracted from every answer once time reaches it, so no arm sees a later answer
        - each chunk of asks is replayed by replay_loop.replay, checked for leakage, then written to records.jsonl and the checkpoint
        - a chunk already done in the checkpoint is skipped, and an answer already extracted is not extracted again
        - the extractor's model and timeout come from the INI file, as the live job reads them
        - an ask with no vector is counted once, kept in the checkpoint as skipped, and left out of every later chunk
        - a line already in records.jsonl is not written again, so a stop between the write and the checkpoint never doubles an ask
        - check_freeze refuses a work folder frozen against the checkpoint other than scored_against
        - the first start stores the freeze in the checkpoint, and a later start under other settings is refused, except a higher principle limit
          (old multiplier 0) and a code change named by accept_code_change; both are recorded in the freeze history
        - before the first chunk, limit failures stored for asks with no record (a stopped chunk's) are deleted, then every recorded ask whose principles forecast failed on the limit is forecast again under the frozen limit
        - on the first failure on the limit the stage saves its checkpoint, writes a named stop line and raises BoundStop; that ask and every later one
          has no failed forecast recorded, and the asks before it in the chunk keep their stored rows, so a restart does not call their models again
        - returns the number of asks predicted in this call

    Raises:
        - LeakageError if any arm was handed evidence from after its ask
        - FreezeMismatch if the work folder was started under other settings
        - BoundStop when the principle limit stops a forecast
    """
    state     = load_state( work.state )
    if check_freeze( state, current_freeze( models, tree_state( os.path.dirname( __file__ ) ) if code is None else code, scored_against ), accept_code_change ): save_state( work.state, state )
    frozen_bound = freeze_limits( models, state )
    models.discard_unrecorded_limit_failures( HAIKU_ARMS, { line[ "id" ] for line in read_jsonl( work.records ) } if os.path.exists( work.records ) else set() )
    rerun_bound_failures( session, asks, models, work, ARM_PRINCIPLES, work.records, frozen_bound, engine.per_field_mc_enabled, out=out, chunk=chunk )
    model, timeout_seconds = extractor_settings()
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
        ran   = models.run( ask_at_ask[ "id" ], HAIKU_ARMS )
        if bound_failed( ran ):
            models.discard_bound_failures( ask_at_ask[ "id" ], HAIKU_ARMS )
            raise BoundStop( ask_at_ask[ "id" ], session.query( PreferencePrinciple ).count(), frozen_bound )
        counts.update( ran )
        return found

    settled  = set( state[ "done_ids" ] ) | set( state[ "skipped_ids" ] )
    todo     = [ ask_id for ask_id in ids if ask_id not in settled ]
    baselines = { ARM_FIXED: fixed_rules_arm, ARM_BASELINE: models.reader( ARM_BASELINE ), ARM_PRINCIPLES: models.reader( ARM_PRINCIPLES ), RECORDER_ARM: make_recorder( seen ) }
    sha       = hashlib.sha256( "\n".join( ids ).encode( "utf-8" ) ).hexdigest()
    for start in range( 0, len( todo ), chunk ):
        part = todo[ start:start + chunk ]
        chunk_context[ 0 ] = 0
        counts.clear()
        try:
            run = replay( asks, engine, sha, baselines=baselines, target_types=ELIGIBLE_TYPES, context_arms=( ARM_BASELINE, ARM_PRINCIPLES, RECORDER_ARM ),
                          episode_view_provider=episode_provider, principles_provider=principles_provider, target_ids=set( part ) )
        except BoundStop as stop:
            state[ "extracted_ids" ] = sorted( extracted | { item[ "notification_id" ] for item in runner.summaries } | { a for a in state[ "extracted_ids" ] } )
            session.commit()
            embed.flush()
            save_state( work.state, state )
            line = f"[stopped] {len( state[ 'done_ids' ] ) + len( state[ 'skipped_ids' ] )}/{len( ids )} asks recorded; {stop}"
            append_lines( work.log, [ { "line": line } ] )
            out( line )
            raise
        check_no_leakage( seen )
        seen.clear()
        recorded = { line[ "id" ] for line in read_jsonl( work.records ) } if os.path.exists( work.records ) else set()
        append_lines( work.records, [ line for line in _record_lines( run, models ) if line[ "id" ] not in recorded ] )
        state[ "done_ids" ]      = state[ "done_ids" ] + [ r[ "meta" ][ "notification_id" ] for r in run[ "records" ][ ENGINE_ARM ] ]
        state[ "extracted_ids" ] = sorted( extracted | { item[ "notification_id" ] for item in runner.summaries } | { a for a in state[ "extracted_ids" ] } )
        state[ "skipped_ids" ]    = sorted( set( state[ "skipped_ids" ] ) | set( run[ "not_replayable_ids" ] ) )
        state[ "not_replayable" ] = len( state[ "skipped_ids" ] )
        state[ "unrebuildable" ]  += run[ "unrebuildable_cases" ]
        state[ "context_asks" ]   += chunk_context[ 0 ]
        session.commit()
        embed.flush()
        save_state( work.state, state )
        line = checkpoint_line( len( state[ "done_ids" ] ) + len( state[ "skipped_ids" ] ), len( ids ), state, session, counts, chunk_context[ 0 ], frozen_bound )
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


def run_twin_stage( session, asks, ids, models, work, per_field, follow=False, poll_seconds=60, sleep=time.sleep, chunk=CHUNK_SIZE, out=print, code=None, accept_code_change=None, scored_against=FIRST_NAME ):
    """
    Run the Opus twins over the evaluation asks, trailing the first stage.

    Requires:
        - asks are the replay's ask dicts; ids the evaluation ids in replay order
        - per_field is the engine's per-field multiple-choice switch, the basis the first stage scored the engine arms on
        - the first stage writes records.jsonl in the same work folder

    Ensures:
        - only an ask the first stage has recorded is run, so the twins never get ahead of it
        - each ask runs both twins at once, scores each row as the harness scores a forecast, and appends one line to twin-records.jsonl
        - an ask already in twin-records.jsonl is skipped
        - with follow True the stage waits for the first stage to record more asks; otherwise it stops when none is ready
        - returns the number of asks the twins ran in this call
        - check_freeze refuses a work folder frozen against the checkpoint other than scored_against
        - a work folder started under other settings is refused, as in the first stage, with the same two allowed changes; this stage saves the state only
          when it wrote the first freeze, so it never overwrites the first stage's progress
        - before it runs a new ask, every twin line whose principles twin failed on the limit is forecast again under the limit now read
        - on the first failure on the limit it deletes that ask's failed rows, writes a named stop line and raises BoundStop; no failed twin line is written for it

    Raises:
        - FreezeMismatch if the settings differ from the ones the first stage froze
        - BoundStop when the principle limit stops a twin
    """
    state = load_state( work.state )
    fresh = "freeze" not in state
    if check_freeze( state, current_freeze( models, tree_state( os.path.dirname( __file__ ) ) if code is None else code, scored_against ), accept_code_change ) and fresh: save_state( work.state, state )
    frozen_bound = freeze_limits( models, state )
    models.discard_unrecorded_limit_failures( TWIN_ARMS, { line[ "id" ] for line in read_jsonl( work.twins ) } if os.path.exists( work.twins ) else set() )
    rerun_bound_failures( session, asks, models, work, TWIN_ARMS[ 1 ], work.twins, frozen_bound, per_field, out=out, chunk=chunk )
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
            outcome = models.run( ask_id, TWIN_ARMS )
            if bound_failed( outcome ):
                models.discard_bound_failures( ask_id, TWIN_ARMS )
                stop = BoundStop( ask_id, session.query( PreferencePrinciple ).count(), frozen_bound )
                line = f"[twin stopped] {len( finished ) + position - 1} asks run; {stop}"
                append_lines( work.log, [ { "line": line } ] )
                out( line )
                raise stop
            counts.update( outcome )
            ask = by_id[ ask_id ]
            arms = { arm: { "correct": _score( ask[ "response_type" ], models.rows[ ( ask_id, arm ) ][ 0 ], ask[ "actual_value" ], ask[ "response_options" ], per_field ),
                            "forecast": models.rows[ ( ask_id, arm ) ][ 0 ], "reason": models.rows[ ( ask_id, arm ) ][ 1 ] } for arm in TWIN_ARMS }
            append_lines( work.twins, [ { "id": ask_id, "arms": arms } ] )
            ran += 1
            models.rows.clear()
            if ( len( finished ) + position ) % chunk == 0:
                line = f"[twin checkpoint] {len( finished ) + position} asks run, principles {principle_progress( session, frozen_bound )}; " + ", ".join( f"{arm} {status}/{reason}={n}" for ( arm, status, reason ), n in sorted( counts.items(), key=str ) )
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
        - returns { asks, floor, freeze, pairings, context_asks, not_replayable, unrebuildable_cases_chunk_sum, twin_stretch }, the freeze as the run stored it
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
    return { "asks": len( records ), "floor": floor, "freeze": state.get( "freeze" ), "pairings": pairings, "context_asks": state[ "context_asks" ], "not_replayable": state[ "not_replayable" ],
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
        lines.append( f"| {item[ 'arm' ]} | {item[ 'baseline' ]} | {s[ 'asks_replayed' ]} | {s[ 'engine_only_right' ]} | {s[ 'baseline_only_right' ]} | {s[ 'floor_met' ]} | {_named_verdict( s[ 'verdict' ], item[ 'arm' ], item[ 'baseline' ] )} | "
                      f"{_pct( a[ 'coverage' ] )} | {_pct( a[ 'accuracy_on_answered' ] )} | {_pct( b[ 'coverage' ] )} | {_pct( b[ 'accuracy_on_answered' ] )} |" )
    return "\n".join( lines )


def _named_verdict( verdict, arm, baseline ):
    """
    Name the arm that came out ahead, in place of summarize's engine and baseline words.

    Requires:
        - verdict is a word summarize returns: "engine better", "baseline better", "no difference" or "not decisive"
        - arm and baseline are the labels of the pairing's first and second arm

    Ensures:
        - "engine better" reads as the first arm's label plus " better", and "baseline better" as the second arm's
        - "no difference" and "not decisive" come back unchanged
        - no arm called "engine" is claimed unless a label says so
    """
    if verdict == "engine better": return f"{arm} better"
    if verdict == "baseline better": return f"{baseline} better"
    return verdict


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
        - a stop on the principle limit prints its named message and returns STOP_EXIT (3) with the work saved; any other return is 0
        - --accept-code-change <old sha>:<new sha> names the one code change a resume may carry
        - --limit N cuts the evaluation asks to the first N, so a trial never reaches a real run's work folder
        - --checkpoint names the freeze file the run is scored against; every run of every stage first prints which one, through out
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
    parser.add_argument( "--accept-code-change", default=None, help="<old sha>:<new sha>, the caller's word that the code change does not alter what the run measures; recorded in the freeze history" )
    parser.add_argument( "--checkpoint", default=None, help="the freeze file the run is scored against; default is the 18 Nov checkpoint, src/conf/prediction-checkpoint.json" )
    parser.add_argument( "--limit", type=int, default=None, help="predict only the first N evaluation asks, for a short trial in its own work folder" )
    args = parser.parse_args( argv )
    work = WorkFolder( args.work )
    scored_against = checkpoint_name( cu.get_project_root() + CHECKPOINT_PATH if args.checkpoint is None else args.checkpoint )
    out( f"[checkpoint] scored against: {scored_against}" )
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
        models = default_models( session, embed, embed.encoder, f"{extractor_settings()[ 0 ]}:{PROMPT_VERSION}", work ) if make_models is None else make_models( session, embed )
        try:
            if args.stage == "first": run_first_stage( session, asks, ids, engine, embed, models, work, query_fn=query_fn, chunk=args.chunk, out=out, accept_code_change=args.accept_code_change, scored_against=scored_against )
            else: run_twin_stage( session, asks, ids, models, work, engine.per_field_mc_enabled, follow=args.follow, poll_seconds=args.poll_seconds, chunk=args.chunk, out=out, accept_code_change=args.accept_code_change, scored_against=scored_against )
        except BoundStop as stop:
            embed.flush()
            out( str( stop ) )
            return STOP_EXIT
        embed.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is what the tests drive
    sys.exit( main() )
