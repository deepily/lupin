"""
The ask-time record: what was knowable about one ask at a moment, and nothing later.

``episode_view`` loads a bounded pool of earlier notifications, gives it to ``rebuild_context``
unchanged, and shapes the result as one record for the learner. It builds none of the as-of logic
again: a later answer is withheld by ``rebuild_context``.
Until the remediation's own ask-time record lands, this module is the learner's only door
to ask-time context, so the swap is one change.

The pool is five indexed queries, one per tier of ``rebuild_context``.
Each keeps rows sent to the ask's recipient and created strictly before the ask.
Each but the parent keeps the newest N rows (INI key ``prediction learner episode pool per tier limit``).
A tier that hit the limit is named in the record, so a reader can tell a short history from a cut one.
"""

import re
import uuid

from sqlalchemy import or_

from cosa.agents.prediction_engine.ask_family import PROJECT_PATTERN
from cosa.agents.prediction_engine.history_context_rebuild import SESSION_WINDOW, notification_dict, rebuild_context
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.postgres_models import Notification, PredictionLog
from cosa.utils.iso_timestamp import aware_moment
from cosa.utils.notification_utils import sender_session_suffix

POOL_LIMIT_KEY   = "prediction learner episode pool per tier limit"
QUESTION_CAP     = 3
INFERRED_TIERS   = ( "session", )
LINK_PATTERN     = re.compile( r"\[([^\]]*)\]\(([^)\s]+)\)" )
LINK_KINDS       = ( ( "/app/docs?", "supporting_doc" ), ( "/app/tasks/approve?", "approval" ), ( "/app/tasks/view?", "task_view" ) )
RECOMMENDED_TAG  = "recommended"


def pool_limit():
    """
    Read how many rows each tier of the pool may hold.

    Requires:
        - the INI file carries the key named by POOL_LIMIT_KEY

    Ensures:
        - returns a positive int

    Raises:
        - MissingConfigKeyError if the key is missing or blank, so a missing limit never becomes an unbounded read
        - ValueError if the value is not a positive integer
    """
    limit = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( POOL_LIMIT_KEY, return_type="int" )
    if limit < 1: raise ValueError( f"'{POOL_LIMIT_KEY}' must be a positive integer, got {limit}" )
    return limit


def _tier_queries( session, target, before, limit, session_window ):
    """
    Build the five tier queries for one ask, newest first, each cut to limit + 1 rows.

    Requires:
        - session is an active SQLAlchemy session
        - target is the ask's Notification row and before an aware datetime, the moment the pool is read as of
        - limit is a positive int and session_window a timedelta

    Ensures:
        - returns { tier: query } for the tiers that can match, in tier order
        - every query keeps rows to the ask's recipient created strictly before `before`, never the ask itself
        - a tier with nothing to match on (no reply_to, thread, job or sender) is absent
        - the sender query has no window, because rebuild_context joins a same full sender at any age
        - the sender and session queries skip a row whose own thread or job differs from the ask's, because
          rebuild_context refuses such a row, and it would otherwise fill the newest limit rows to no use
        - the session query keeps a sender ending in the ask's session suffix, or a human_to_ai row whose
          job id is that suffix, created inside the window
        - the parent query is not cut: it holds at most one row
    """
    base = lambda: session.query( Notification ).filter( Notification.recipient_id == target.recipient_id, Notification.created_at < before,
                                          Notification.id != target.id )
    def unconflicted( query ):
        for column, wanted in ( ( Notification.thread_id, target.thread_id ), ( Notification.job_id, target.job_id ) ):
            if wanted: query = query.filter( or_( column.is_( None ), column == "", column == wanted ) )
        return query
    newest = lambda query: query.order_by( Notification.created_at.desc(), Notification.id ).limit( limit + 1 )
    queries = {}
    try:
        parent_id = uuid.UUID( target.reply_to ) if target.reply_to else None
    except ValueError:
        parent_id = None
    if parent_id is not None: queries[ "parent" ] = base().filter( Notification.id == parent_id )
    if target.thread_id: queries[ "thread" ] = newest( base().filter( Notification.thread_id == target.thread_id ) )
    if target.job_id:    queries[ "job" ]    = newest( base().filter( Notification.job_id == target.job_id ) )
    if target.sender_id: queries[ "sender" ] = newest( unconflicted( base().filter( Notification.sender_id == target.sender_id ) ) )
    suffix = sender_session_suffix( target.sender_id )
    if suffix is not None:
        queries[ "session" ] = newest( unconflicted( base().filter( Notification.created_at >= before - session_window,
                                                      ( Notification.sender_id.endswith( "#" + suffix, autoescape=True ) )
                                                      | ( ( Notification.direction == "human_to_ai" ) & ( Notification.job_id == suffix ) ) ) ) )
    return queries


def load_pool( session, target, before, limit, session_window=SESSION_WINDOW ):
    """
    Load the bounded pool of earlier notifications that rebuild_context reads.

    Requires:
        - session is an active SQLAlchemy session
        - target is the ask's Notification row and before an aware datetime
        - limit is a positive int

    Ensures:
        - returns ( pool, truncated )
        - pool is a list of notification dicts, de-duplicated by id, the target never in it
        - truncated lists, in tier order, each tier that held more than limit rows and so kept only its newest limit
        - a notification found by two tiers is in the pool once
    """
    pool      = {}
    truncated = []
    for tier, query in _tier_queries( session, target, before, limit, session_window ).items():
        rows = query.all()
        if len( rows ) > limit:
            truncated.append( tier )
            rows = rows[ :limit ]
        for row in rows:
            pool.setdefault( str( row.id ), notification_dict( row ) )
    return list( pool.values() ), truncated


def link_kind( target ):
    """
    Name what a link points to.

    Requires:
        - target is a link address string

    Ensures:
        - returns supporting_doc for a doc-viewer address, approval for a task approval address,
          task_view for a task view address, external for an http(s) address, and other for the rest
    """
    for prefix, kind in LINK_KINDS:
        if target.startswith( prefix ): return kind
    return "external" if target.startswith( ( "http://", "https://" ) ) else "other"


def links_of( abstract ):
    """
    List the links in a card's abstract, in order.

    Requires:
        - abstract is a string or None

    Ensures:
        - returns [ { "kind", "target" } ] for each markdown link, so "an approval link exists" is answerable
        - returns [] for None or a link-free abstract
    """
    return [ { "kind": link_kind( match.group( 2 ) ), "target": match.group( 2 ) } for match in LINK_PATTERN.finditer( abstract or "" ) ]


def _is_recommended( option ):
    """
    Say whether an option is flagged as the recommended one.

    Requires:
        - option is a dict with a label and optionally a recommended key

    Ensures:
        - returns True when recommended is true or the label says Recommended, else False
    """
    return option.get( "recommended" ) is True or RECOMMENDED_TAG in str( option.get( "label", "" ) ).lower()


def fields_of( response_options, response_default ):
    """
    Read the card's fields: prompt, mode, options with descriptions and flags, and default.

    Requires:
        - response_options is a dict with a "questions" list, or None
        - response_default is the card's default string or None

    Ensures:
        - returns [] for a card with no questions
        - each field has key (the header), prompt, mode, options and default
        - mode is "multi" for a multi-select question, "text" for a free-text input, else "single"
        - each option has id (o1, o2, ... per field), label, description (None when absent) and recommended
        - default is the id of the option whose label equals the field's default text; with no option it is the
          default text itself, and None when there is no default. The field's own default_value wins over the card's
    """
    fields = []
    for question in ( response_options or {} ).get( "questions" ) or []:
        options = [ { "id": f"o{number}", "label": option.get( "label" ), "description": option.get( "description" ),
                      "recommended": _is_recommended( option ) } for number, option in enumerate( question.get( "options" ) or [], start=1 ) ]
        default = question.get( "default_value", response_default )
        match   = [ o[ "id" ] for o in options if default is not None and str( o[ "label" ] ).strip() == str( default ).strip() ]
        mode    = "multi" if question.get( "multi_select" ) else ( "text" if question.get( "input_type" ) == "text" else "single" )
        fields.append( { "key": question.get( "header" ), "prompt": question.get( "question" ), "mode": mode, "options": options,
                         "default": match[ 0 ] if match else ( default if not options else None ) } )
    return fields


def _history_entry( attachment ):
    """
    Shape one attachment of rebuild_context as a history entry.

    Requires:
        - attachment comes from rebuild_context

    Ensures:
        - returns notification_id, tier, confidence, evidence, first_known_at, status and, for an answered one,
          answer and answer_known_at
        - an entry joined through the session tier has inferred True, every other False
        - a pending or informational entry carries no answer
    """
    state = attachment[ "answer" ]
    entry = { "notification_id": attachment[ "id" ], "tier": attachment[ "tier" ], "confidence": attachment[ "confidence" ],
              "evidence": attachment[ "evidence" ], "first_known_at": attachment[ "first_known_at" ], "status": state[ "status" ],
              "inferred": attachment[ "tier" ] in INFERRED_TIERS }
    if state[ "status" ] == "answered":
        entry[ "answer" ]          = state[ "value" ]
        entry[ "answer_known_at" ] = state[ "answer_known_at" ]
    return entry


def history_of( context ):
    """
    Cut the attachments to the three questions and the informational messages beside them.

    Requires:
        - context is a rebuild_context result

    Ensures:
        - keeps the first three attachments that are questions, in the order rebuild_context returns them
        - a pending question counts toward the three; a candidate in missing is never included
        - an informational message (status not_a_question) is kept and does not count
        - every kept entry stays in rebuild_context's order
    """
    kept      = []
    questions = 0
    for attachment in context[ "attachments" ]:
        if attachment[ "answer" ][ "status" ] == "not_a_question":
            kept.append( _history_entry( attachment ) )
        elif questions < QUESTION_CAP:
            questions += 1
            kept.append( _history_entry( attachment ) )
    return kept


def revealed_at( session, notification_id, cutoff=None ):
    """
    Read when Rick first opened the prediction fold for an ask, as known at a moment.

    Requires:
        - session is an active SQLAlchemy session and notification_id a UUID
        - cutoff is None or an aware datetime

    Ensures:
        - returns the ISO time stored in prediction_log.fold_opened_at, or None when there is no log row or no reveal
        - with a cutoff, a reveal later than the cutoff reads None; a reveal exactly at the cutoff is returned
        - with no cutoff it is the raw stored time, which is the ledger's outcome side and never prompt input
    """
    row = session.query( PredictionLog.fold_opened_at ).filter( PredictionLog.notification_id == notification_id,
                                                                 PredictionLog.fold_opened_at.isnot( None ) ).first()
    if row is None: return None
    moment = aware_moment( row[ 0 ] )
    return None if cutoff is not None and moment > cutoff else moment.isoformat()


def revealed_draft( session, notification_id, cutoff=None ):
    """
    Read the owner's draft from the moment the fold opened, as known at a moment.

    Requires:
        - session is an active SQLAlchemy session and notification_id a UUID
        - cutoff is None or an aware datetime

    Ensures:
        - returns the stored prediction_log.draft_at_reveal, or None when there is no log row, no reveal or no draft
        - the draft is stored by the same call as fold_opened_at, so with a cutoff a reveal later than the cutoff reads None
          and its draft is never returned; a reveal exactly at the cutoff is returned
        - with no cutoff it is the raw stored draft, which is the ledger's outcome side and never prompt input
    """
    row = session.query( PredictionLog.fold_opened_at, PredictionLog.draft_at_reveal ).filter(
        PredictionLog.notification_id == notification_id, PredictionLog.fold_opened_at.isnot( None ) ).first()
    if row is None: return None
    if cutoff is not None and aware_moment( row[ 0 ] ) > cutoff: return None
    return row[ 1 ]


def episode_view( session, notification_id, as_of=None, limit=None ):
    """
    Return what was knowable about one ask at as_of, and nothing later.

    Requires:
        - session is an active SQLAlchemy session
        - notification_id is a notification UUID, as text or UUID
        - as_of is None (the ask's own time), a datetime or an ISO string not before the ask
        - limit is None (read the INI key) or a positive int

    Ensures:
        - returns owner_id, project, asker, asked_at, title, abstract, links, fields, history, exposure and pool
        - asked_at is the ask's own creation time; the history is as of as_of
        - history holds at most three questions plus informational messages, each answered or pending as of as_of;
          an answer given after as_of reads pending
        - exposure is { revealed_at, draft_at_reveal }; revealed_at is None when the reveal came after as_of;
          draft_at_reveal is the stored draft, None when there is none or the reveal came after as_of
        - pool is { limit, truncated }, truncated naming each tier that hit the limit; the history may then lack
          older rows of that tier
        - the ask's own answer is never read

    Raises:
        - LookupError if the notification does not exist
        - ValueError if as_of is before the ask, or limit is not positive
    """
    row = session.get( Notification, uuid.UUID( str( notification_id ) ) )
    if row is None: raise LookupError( f"notification {notification_id} does not exist" )
    asked    = aware_moment( row.created_at )
    cutoff   = asked if as_of is None else aware_moment( as_of )
    if cutoff < asked: raise ValueError( f"as_of {cutoff.isoformat()} is before the ask {asked.isoformat()}" )
    limit    = pool_limit() if limit is None else limit
    if limit < 1: raise ValueError( f"limit must be positive, got {limit}" )
    pool, truncated = load_pool( session, row, cutoff, limit )
    target   = notification_dict( row )
    target[ "created_at" ] = cutoff.isoformat()
    context  = rebuild_context( target, pool )
    match    = PROJECT_PATTERN.search( row.sender_id or "" )
    return { "owner_id": str( row.recipient_id ), "project": match.group( 1 ) if match else None, "asker": row.sender_id,
             "asked_at": asked.isoformat(), "title": row.title, "abstract": row.abstract, "links": links_of( row.abstract ),
             "fields": fields_of( row.response_options, row.response_default ), "history": history_of( context ),
             "exposure": { "revealed_at": revealed_at( session, row.id, cutoff ), "draft_at_reveal": revealed_draft( session, row.id, cutoff ) },
             "pool": { "limit": limit, "truncated": truncated } }
