"""
The principles forecast: the baseline job plus a block of applicable principles.

It runs the same model and the same prompts as the baseline arm.
The one difference is a block of principles, retrieved as of the ask, added to the user prompt.
Its result goes to the sibling table ``prediction_arm_forecast`` under its own arm name, never to ``prediction_log``.

The baseline job is the remediation's background forecast job, ``context_baseline.ContextBaseline``.
This module takes it as an argument, the ``c0`` contract below, and without it reads "blocked" and writes nothing.
The learner's ``principles_call.run_principles_forecast`` supplies the process's own baseline, gate and embedder.
It has its own switch (``prediction learner principles forecast enabled``, default off).
It has its own concurrency cap (``prediction learner principles forecast max concurrent``).
So it cannot take a slot from the baseline job.
A card beyond the cap gets a row with the capped reason at once, not a queue.
The per-arm summary (``arm_summary.per_arm_summary``) reads those rows and reports timeliness, capped and no_row.

The ``c0`` contract, an object with:

- ``model``                         the model id the baseline calls
- ``timeout_seconds``               the call's timeout
- ``errors``                        the exception classes a failed call raises, as a tuple
- ``build_prompts( episode )``      returns ( system prompt, user prompt ), the baseline's own
- ``complete( model, system, user, timeout_seconds=... )``  an async call returning the reply text
- ``parse( text, episode )``        returns the typed forecast dict, or raises ValueError for an unreadable reply
- ``predictor_version``             the baseline's version string
"""

import asyncio
import inspect
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from cosa.agents.prediction_engine.full_answer import ReplyRefused
from cosa.agents.prediction_engine.episode_view import card_text, episode_view
from cosa.agents.prediction_engine.card_stage import card_stage_of
from cosa.agents.prediction_engine.principle_retrieval import APPLICABILITY_KEY, CAVEATS_KEY, DEFAULT_K, principle_block, retrieval_limits, retrieve_principles
from cosa.agents.shared.config_loader import required_positive_int
from cosa.config.configuration_manager import ConfigurationManager
from cosa.config.switch_reader import read_switch
from cosa.rest.db.repositories.arm_forecast_repository import CAPPED_ARM_REASON
from cosa.rest.postgres_models import Notification, PredictionArmForecast
from cosa.utils.iso_timestamp import aware_moment

ARM              = "B1"
SWITCH_KEY       = "prediction learner principles forecast enabled"
CAP_KEY          = "prediction learner principles forecast max concurrent"
STATUS_RAN       = "ran"
STATUS_NOT_RUN   = "not_run"
STATUS_CAPACITY  = "capacity"
STATUS_FAILED    = "failed"
REASON_BLOCKED   = "blocked by phase 6"
REASON_SWITCH    = "switch off"
REASON_STORED    = "already stored"
REASON_UNREADABLE = "unreadable_forecast"
BLOCK_HEADING    = "Principles that apply to this card, learned from earlier answers:"
VERSION_SUFFIX   = "+principles"
REASON_INPUT     = "input_error"

CONTRACT_VALUES  = ( "model", "timeout_seconds", "predictor_version" )
CONTRACT_ERRORS  = "errors"
CONTRACT_SYNC    = { "build_prompts": 1, "parse": 2 }
CONTRACT_ASYNC   = "complete"


def switch_enabled( key ):
    """
    Say whether one learner switch is on.

    Requires:
        - key names a boolean INI setting; an unreadable setting reads as off

    Ensures:
        - returns True only when the INI key is true
        - never raises, so a settings failure cannot stop an ask
    """
    return read_switch( lambda env_var_name: ConfigurationManager( env_var_name=env_var_name ), key, False,
                        lambda settings_error: f"[PRINCIPLES] ⚠️ Switch '{key}' unreadable, treated as off: {settings_error}" )


def principles_forecast_enabled():
    """
    Say whether the principles forecast is switched on.

    Requires:
        - nothing; an unreadable setting reads as off

    Ensures:
        - returns True only when the INI key named by SWITCH_KEY is true
        - never raises, so a settings failure cannot stop an ask
    """
    return switch_enabled( SWITCH_KEY )


def read_cap( key ):
    """
    Read how many calls of one arm may run at once.

    Requires:
        - the INI file carries the key

    Ensures:
        - returns a positive int

    Raises:
        - MissingConfigKeyError if the key is missing or blank, so a missing cap never becomes unbounded
        - ValueError if the value is not a positive integer
    """
    return required_positive_int( key, ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ) )


def concurrency_cap():
    """
    Read how many principles forecasts may run at once.

    Requires:
        - the INI file carries the key named by CAP_KEY

    Ensures:
        - returns a positive int

    Raises:
        - MissingConfigKeyError if the key is missing or blank, so a missing cap never becomes unbounded
        - ValueError if the value is not a positive integer
    """
    return read_cap( CAP_KEY )


class CapGate:
    """A count of calls in flight that refuses at once past its limit, never queues."""

    def __init__( self, limit ):
        """
        Make a gate that lets at most limit calls in.

        Requires:
            - limit is a positive int

        Raises:
            - ValueError if limit is not a positive int
        """
        if not isinstance( limit, int ) or limit < 1: raise ValueError( f"limit must be a positive int, got {limit!r}" )
        self.limit    = limit
        self.inflight = 0
        self._lock    = threading.Lock()

    def try_enter( self ):
        """
        Take a place if one is free.

        Ensures:
            - returns True and counts the call when fewer than limit are in flight, else False and changes nothing
        """
        with self._lock:
            entered = self.inflight < self.limit
            if entered: self.inflight += 1
        return entered

    def leave( self ):
        """
        Give a place back.

        Requires:
            - the caller got True from try_enter

        Ensures:
            - one fewer call is counted
        """
        with self._lock: self.inflight -= 1


def check_baseline( c0 ):
    """
    Check that an object meets the baseline contract this module depends on.

    Requires:
        - c0 is any object; the contract is the list in the module docstring

    Ensures:
        - returns None when c0 carries a model id, a positive timeout and a version string, a non-empty tuple of
          exception classes as errors, build_prompts and parse taking one and two arguments, and an async complete
          that accepts timeout_seconds
        - the module docstring lists the same names this function checks, which a test reads

    Raises:
        - TypeError naming every member that is missing or has the wrong shape, all at once
    """
    problems = []
    for name in CONTRACT_VALUES + ( CONTRACT_ERRORS, ) + tuple( CONTRACT_SYNC ) + ( CONTRACT_ASYNC, ):
        if not hasattr( c0, name ): problems.append( f"{name} is missing" )
    if not problems:
        if not ( isinstance( c0.model, str ) and c0.model ): problems.append( "model must be a non-empty string" )
        if not ( isinstance( c0.timeout_seconds, ( int, float ) ) and not isinstance( c0.timeout_seconds, bool ) and c0.timeout_seconds > 0 ): problems.append( "timeout_seconds must be a positive number" )
        if not ( isinstance( c0.predictor_version, str ) and c0.predictor_version ): problems.append( "predictor_version must be a non-empty string" )
        if not ( isinstance( c0.errors, tuple ) and c0.errors and all( isinstance( e, type ) and issubclass( e, BaseException ) for e in c0.errors ) ):
            problems.append( "errors must be a non-empty tuple of exception classes" )
        for name, count in CONTRACT_SYNC.items():
            member = getattr( c0, name )
            if not callable( member ) or inspect.iscoroutinefunction( member ): problems.append( f"{name} must be a plain function" )
            elif len( inspect.signature( member ).parameters ) != count: problems.append( f"{name} must take {count} argument(s)" )
        complete = getattr( c0, CONTRACT_ASYNC )
        if not inspect.iscoroutinefunction( complete ): problems.append( "complete must be an async function" )
        elif "timeout_seconds" not in inspect.signature( complete ).parameters: problems.append( "complete must accept timeout_seconds" )
    if problems: raise TypeError( "the baseline does not meet the contract: " + "; ".join( problems ) )


def with_principles( system_prompt, user_prompt, block ):
    """
    Add the principle block to the baseline's user prompt and change nothing else.

    Requires:
        - system_prompt and user_prompt are the baseline's own prompts for this card
        - block is principle_block's result

    Ensures:
        - returns ( system_prompt, user prompt ); the system prompt is returned as given
        - with no principles the user prompt is returned as given, so the call then equals the baseline's
        - otherwise the user prompt is followed by a blank line, BLOCK_HEADING and the block text
    """
    if not block[ "text" ]: return system_prompt, user_prompt
    return system_prompt, f"{user_prompt}\n\n{BLOCK_HEADING}\n{block[ 'text' ]}"


def _row_present( session, key, arm=ARM ):
    """
    Say whether a card already has its principles row on this session.

    Requires:
        - session is an active session; key is the card's notification UUID

    Ensures:
        - returns True when a prediction_arm_forecast row for the card and the arm exists
    """
    return session.query( PredictionArmForecast ).filter( PredictionArmForecast.notification_id == key, PredictionArmForecast.arm == arm ).first() is not None


def _has_row( session_factory, notification_id, arm=ARM ):
    """
    Say whether a card already has its principles row.

    Requires:
        - session_factory returns a context-managed session

    Ensures:
        - returns True when a prediction_arm_forecast row for this card and the principles arm exists
    """
    with session_factory() as session:
        found = _row_present( session, uuid.UUID( str( notification_id ) ), arm )
    return found


def _write_row( session_factory, notification_id, asked_at, ready_at, forecast, version, principle_ids, reason, arm=ARM, applicability=None ):
    """
    Store the one principles row for a card, unless it already has one.

    Requires:
        - session_factory returns a context-managed session; ready_at is None for a card with no forecast

    Ensures:
        - adds one prediction_arm_forecast row, for the arm given, displayed false, and commits
        - applicability is stored as given: None (the checks did not run) or the list of dropped principles
        - writes nothing when the card already has its principles row
        - a row that arrives between the check and the insert breaks the unique key; that is read as already stored,
          the session is closed with its failed commit rolled back, and nothing is raised
        - returns True when a row was written
    """
    with session_factory() as session:
        key     = uuid.UUID( str( notification_id ) )
        written = not _row_present( session, key, arm )
        if written:
            session.add( PredictionArmForecast( notification_id=key, arm=arm, predictor_version=version, forecast=forecast, input_cutoff=asked_at,
                                                evidence_ids=principle_ids, forecast_ready_at=ready_at, abstention_reason=reason, displayed=False,
                                                applicability=applicability ) )
            try: session.commit()
            except IntegrityError: written = False
    return written


def _prepare( session_factory, notification_id, c0, embedder, encoder_version, extractor_version, k, use_principles=True, limits=None ):
    """
    Gather the inputs as of the ask: the episode, the principles and the two prompts.

    Requires:
        - session_factory returns a context-managed session; c0 and embedder as run_arm takes them
        - use_principles is False for an arm that adds no principle block; its embedder is then not called

    Ensures:
        - returns ( episode, selected, block, system prompt, user prompt ), everything as of the ask and nothing later
        - block is principle_block's result plus applicability: None when the applicability switch is off or no principles are used, else the list of { principle_id (text), rule } dropped, [] when none
        - without principles the selection is empty, the block is principle_block of none, and the prompts are the baseline's own
        - with principles and the applicability switch (APPLICABILITY_KEY) on, retrieval also drops each principle failing the antecedent rule and prints the dropped ones; the card's stage is read from its own question by card_stage_of, so the stage rule runs for a card whose stage that names
        - with principles, the block carries each stored caveat only when the caveats switch (CAVEATS_KEY) is on
        - with principles, the limit and fetch multiplier are the `limits` given ({ bound, multiplier }); with None they are read from the INI file for this ask (retrieval_limits)
    """
    with session_factory() as session:
        episode  = episode_view( session, notification_id )
        selected = []
        caveats  = False
        dropped  = None
        if use_principles:
            limits   = retrieval_limits() if limits is None else limits
            vector   = embedder.encode( card_text( episode ) )
            caveats  = switch_enabled( CAVEATS_KEY )
            check    = { "card": card_text( episode ), "card_stage": card_stage_of( episode ) } if switch_enabled( APPLICABILITY_KEY ) else None
            found    = retrieve_principles( session, episode[ "owner_id" ], episode[ "project" ], vector, aware_moment( episode[ "asked_at" ] ),
                                            encoder_version, extractor_version, k=k, bound=limits[ "bound" ], multiplier=limits[ "multiplier" ], applicability=check, caveats=caveats )
            selected = found[ "principles" ]
            if check is not None:
                dropped = [ { "principle_id": str( d[ "principle_id" ] ), "rule": d[ "rule" ] } for d in found[ "applicability" ] ]
                if dropped: print( f"[PRINCIPLES] applicability dropped: {dropped}" )
    block            = { **principle_block( selected, caveats=caveats ), "applicability": dropped }
    system, user     = with_principles( *c0.build_prompts( episode ), block )
    return episode, selected, block, system, user


async def run_arm( arm, switch_key, version_suffix, use_principles, session_factory, notification_id, c0, embedder, encoder_version, extractor_version, gate,
                   enabled=None, k=DEFAULT_K, clock=None, limits=None ):
    """
    Make one arm's forecast for one ask, and store its row.

    The principles forecast and the Opus twins share this one path. They differ only in the arm name, the switch, the version suffix,
    whether a principle block is added, and the model the baseline object names.

    Requires:
        - arm names the row's arm; switch_key is the INI switch that gates it; version_suffix is added to the baseline's version
        - use_principles is True to add the principle block and False to send the baseline's prompts unchanged
        - session_factory returns a context-managed session; notification_id names an ask
        - c0 is the baseline contract in the module docstring, or None while the background forecast job has not landed
        - embedder has encode( text ) returning a vector from the encoder named encoder_version
        - gate is a CapGate; enabled is None (read the INI switch named by switch_key) or a bool; clock is None or a function returning an aware datetime
        - limits is None (read the principle limit and fetch multiplier from the INI file for this ask) or { bound, multiplier }, which a replay passes so a frozen run never rereads the file

    Ensures:
        - returns { status, reason }; status is ran, not_run, capacity or failed
        - only a failure gathering the inputs adds a third key, stored, True when its row was saved; no other result has it
        - with the switch off, or with c0 None (reason REASON_BLOCKED), nothing is read, called or written
        - a card that already has its row is left alone, with no call (reason "already stored")
        - past the cap, one row with forecast None and the capped reason (CAPPED_ARM_REASON) is written and no model is called
        - a baseline that does not meet the contract raises TypeError before anything is read or written
        - a failure gathering the inputs stores one row with the reason "input_error: <exception class>", the cutoff and no
          forecast, and returns failed with stored True; only a card that does not exist raises, since it has no cutoff to store
        - when the database is down, so the row cannot be stored either, it still returns failed, with stored False
        - otherwise the baseline's prompts plus the principle block go to the baseline's model, once, with no retry
        - a row written after the inputs were gathered also stores applicability: the dropped-principle list with the applicability switch on, else NULL
        - a block with no applicability key, as another provider's block may be, stores NULL and raises nothing
        - a ready forecast is stored with the principle ids it was given and its ready time; an unreadable reply or a
          failed call stores one row with the reason and no forecast
        - a full-answer reply the parser refuses stores that refusal's own reason (full_answer.REFUSAL_REASONS) and no forecast value
        - the cap place is always given back
    """
    if not ( switch_enabled( switch_key ) if enabled is None else enabled ): return { "status": STATUS_NOT_RUN, "reason": REASON_SWITCH }
    if c0 is None: return { "status": STATUS_NOT_RUN, "reason": REASON_BLOCKED }
    check_baseline( c0 )
    if await asyncio.to_thread( _has_row, session_factory, notification_id, arm ): return { "status": STATUS_NOT_RUN, "reason": REASON_STORED }
    now = clock if clock is not None else ( lambda: datetime.now( timezone.utc ) )
    if not gate.try_enter():
        asked = await asyncio.to_thread( _asked_at, session_factory, notification_id )
        await asyncio.to_thread( _write_row, session_factory, notification_id, asked, None, None, c0.predictor_version + version_suffix, [], CAPPED_ARM_REASON, arm )
        return { "status": STATUS_CAPACITY, "reason": CAPPED_ARM_REASON }
    try:
        version = c0.predictor_version + version_suffix
        try:
            episode, selected, block, system, user = await asyncio.to_thread( _prepare, session_factory, notification_id, c0, embedder, encoder_version, extractor_version, k, use_principles, limits )
        except Exception as input_error:  # any failure gathering inputs (database, embedder, bound) must still leave a row
            reason = f"{REASON_INPUT}: {type( input_error ).__name__}"
            try:
                asked = await asyncio.to_thread( _asked_at, session_factory, notification_id )
                await asyncio.to_thread( _write_row, session_factory, notification_id, asked, None, None, version, [], reason, arm )
            except SQLAlchemyError: return { "status": STATUS_FAILED, "reason": reason, "stored": False }  # the database that failed the read cannot take the row
            return { "status": STATUS_FAILED, "reason": reason, "stored": True }
        asked   = aware_moment( episode[ "asked_at" ] )
        ids     = block[ "principle_ids" ]
        # a block from another provider (the answer history arm) may carry no applicability key: that means no check ran, so NULL
        checked = block[ "applicability" ] if "applicability" in block else None
        try:
            text     = await c0.complete( c0.model, system, user, timeout_seconds=c0.timeout_seconds )
            forecast = c0.parse( text, episode )
        except c0.errors as call_error:
            reason = f"model_error: {type( call_error ).__name__}"
        except ReplyRefused as refusal:
            reason = refusal.reason
        except ValueError:
            reason = REASON_UNREADABLE
        else:
            await asyncio.to_thread( _write_row, session_factory, notification_id, asked, now(), forecast, version, [ str( i ) for i in ids ], None, arm, checked )
            return { "status": STATUS_RAN, "reason": None }
        await asyncio.to_thread( _write_row, session_factory, notification_id, asked, None, None, version, [ str( i ) for i in ids ], reason, arm, checked )
        return { "status": STATUS_FAILED, "reason": reason }
    finally:
        gate.leave()


async def run_b1( session_factory, notification_id, c0, embedder, encoder_version, extractor_version, gate, enabled=None, k=DEFAULT_K, clock=None, limits=None ):
    """
    Make the principles forecast for one ask, and store its row.

    Requires:
        - the same as run_arm, with the arm, switch and version suffix fixed to the principles forecast's

    Ensures:
        - is run_arm for the principles forecast with the principle block on, so everything run_arm ensures holds
    """
    return await run_arm( ARM, SWITCH_KEY, VERSION_SUFFIX, True, session_factory, notification_id, c0, embedder, encoder_version, extractor_version, gate,
                          enabled=enabled, k=k, clock=clock, limits=limits )


def _asked_at( session_factory, notification_id ):
    """
    Read the moment an ask was made.

    Requires:
        - session_factory returns a context-managed session; notification_id names an ask

    Ensures:
        - returns the notification's creation time as an aware datetime

    Raises:
        - LookupError if the notification does not exist
    """
    with session_factory() as session:
        row     = session.get( Notification, uuid.UUID( str( notification_id ) ) )
        created = None if row is None else row.created_at
    if row is None: raise LookupError( f"notification {notification_id} does not exist" )
    return aware_moment( created )
