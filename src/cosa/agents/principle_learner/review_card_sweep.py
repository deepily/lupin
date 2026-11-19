"""
The review-card sweep: find the contested principles and send Rick a card, within the cap.

The extractor stays silent, so the sweep is a separate job that the queue runs right after an extractor job.
It reads the contested principles from the status function.
It leaves out any already on a recent unanswered card.
It sends one batched card through the dispatcher without waiting for the answer.
The answer door records the ruling when Rick answers, so nothing here waits for it.
A card counts against the cap when it is sent, not when it is answered.
"""

import asyncio
import json
import threading
import uuid

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.agents.prediction_engine.history_derive import derive_answer
from cosa.agents.prediction_engine.principle_retrieval import load_owner_ledger, session_lookup
from cosa.agents.prediction_engine.principle_status import CONTESTED, CONTRADICTING, SOURCE_EXTRACT, SUPPORTING, derive_statuses
from cosa.agents.prediction_engine.review_card import is_review_card
from cosa.agents.principle_learner import extractor_job
from cosa.agents.principle_learner.extractor_prompt import PROMPT_VERSION
from cosa.agents.principle_learner.review_cards import PRINCIPLES_KEY, WINDOW, review_card_cap, review_card_times, send_review_card
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.postgres_models import Notification
from cosa.utils.iso_timestamp import aware_moment
import cosa.utils.util as cu

WAIT_KEY         = "prediction learner review card wait seconds"
SESSION_ID       = "principle-review-sweep"
SAME_SEND_SECONDS = 60
ANSWER_CHARS      = 200

_LOCK  = threading.Lock()
_SENT  = {}


def extractor_version_of( model ):
    """
    Name the extractor version the config currently uses.

    Requires:
        - model is the extractor model id

    Ensures:
        - returns "<model>:<prompt version>", the string the extractor stores on its rows
    """
    return f"{model}:{PROMPT_VERSION}"


class DetachedDispatcher:
    """
    A dispatcher stand-in that sends a card and returns at once.

    Requires:
        - dispatcher has an async present_choices; wait_seconds is how long the ask stays open for an answer

    Ensures:
        - present_choices starts the real call on its own thread and returns None without waiting
        - the thread swallows and prints any failure, because the answer door, not this call, records the ruling
    """

    def __init__( self, dispatcher, wait_seconds ):
        """
        Hold the real dispatcher and the wait.

        Requires:
            - dispatcher has an async present_choices; wait_seconds is a positive integer

        Ensures:
            - threads starts empty; each send appends its thread
        """
        self.dispatcher   = dispatcher
        self.wait_seconds = wait_seconds
        self.threads      = []

    async def present_choices( self, questions, **kwargs ):
        """
        Start the real call on a daemon thread and return at once.

        Requires:
            - questions and kwargs are what the real present_choices takes, without timeout

        Ensures:
            - returns None; the ask stays open for wait_seconds
        """
        thread = threading.Thread( target=self._run, args=( questions, kwargs ), daemon=True )
        self.threads.append( thread )
        thread.start()
        return None

    def _run( self, questions, kwargs ):
        """
        Run the real call to its end on this thread.

        Requires:
            - questions and kwargs as present_choices takes them

        Ensures:
            - a failure, including a timeout with no answer, is printed and not raised
        """
        try:
            asyncio.run( self.dispatcher.present_choices( questions, timeout=self.wait_seconds, **kwargs ) )
        except Exception as error:
            print( f"[REVIEW-CARD] card ended without an answer: {error.__class__.__name__}: {error}" )


def _answer_text( row ):
    """
    Say what the owner answered on one ask, in a short line.

    Requires:
        - row is a Notification or None

    Ensures:
        - returns the stance, the text or the field selections cut to ANSWER_CHARS, or a placeholder when the ask or its answer is missing
    """
    if row is None: return "(the answer could not be found)"
    answer = derive_answer( { "response_type": row.response_type, "response_value": row.response_value } )[ 0 ]
    return json.dumps( { key: value for key, value in answer.items() if key != "kind" }, sort_keys=True, default=str )[ :ANSWER_CHARS ]


def _recent_card_principles( session, owner_id, now ):
    """
    List the principles already on an unanswered review card sent inside the window.

    Requires:
        - session is open; owner_id is the owner's user id; now is an aware datetime

    Ensures:
        - returns the set of principle ids, as text, named by marked asks to that owner created inside the window and not yet answered
    """
    rows  = session.query( Notification.response_options, Notification.responded_at ).filter(
        Notification.recipient_id == uuid.UUID( str( owner_id ) ), Notification.created_at > now - WINDOW ).all()
    found = set()
    for options, responded in rows:
        if responded is None and is_review_card( options ):
            found.update( ( json.loads( options ) if isinstance( options, str ) else options ).get( PRINCIPLES_KEY, {} ).values() )
    return found


def contested_items( session, owner_id, now, current_version ):
    """
    Build the card items for the owner's contested principles.

    Requires:
        - session is open; owner_id is the owner's user id; now is an aware datetime
        - current_version is the extractor version the config names

    Ensures:
        - returns items { principle_id, statement, answer_a, answer_b }, one per principle whose derived status is contested
        - answer_a is the owner's earliest supporting answer and answer_b the earliest contradicting one, read at the ask
        - a principle on a recent unanswered card, or sent in this process inside the window, is left out
        - reads only
    """
    principles, evidence = load_owner_ledger( session, str( owner_id ) )
    statuses = derive_statuses( principles, evidence, now, current_version, session_lookup( session, [ e.notification_id for e in evidence ] ) )
    skip     = _recent_card_principles( session, owner_id, now ) | _sent_principles( owner_id, now )
    items    = []
    for principle in sorted( principles, key=lambda p: str( p.id ) ):
        state = statuses.get( principle.id )
        if state is None or state[ "status" ] != CONTESTED or str( principle.id ) in skip: continue
        own = sorted( ( e for e in evidence if e.principle_id == principle.id and e.source == SOURCE_EXTRACT and e.extractor_version == current_version ),
                      key=lambda e: aware_moment( e.answered_at ) )
        support = next( e for e in own if e.relation in SUPPORTING )
        contra  = next( e for e in own if e.relation == CONTRADICTING )
        items.append( { "principle_id": str( principle.id ), "statement": principle.statement,
                        "answer_a": _answer_text( session.get( Notification, support.notification_id ) ),
                        "answer_b": _answer_text( session.get( Notification, contra.notification_id ) ) } )
    return items


def _sent_principles( owner_id, now ):
    """
    List the principles sent on a card by this process inside the window.

    Requires:
        - owner_id is the owner's user id; now is an aware datetime

    Ensures:
        - returns the set of principle ids, as text, from sends recorded after now minus the window
    """
    with _LOCK:
        return { pid for moment, ids in _SENT.get( str( owner_id ), [] ) if now - WINDOW < moment <= now for pid in ids }


def _remember_send( owner_id, now, ids ):
    """
    Record a card when it is sent, so the cap counts it before it is stored or answered.

    Requires:
        - owner_id is the owner's user id; now is an aware datetime; ids are the principle ids on the card

    Ensures:
        - the send is kept in this process, and sends older than the window are dropped
    """
    with _LOCK:
        kept = [ ( moment, held ) for moment, held in _SENT.get( str( owner_id ), [] ) if now - WINDOW < moment ]
        kept.append( ( now, list( ids ) ) )
        _SENT[ str( owner_id ) ] = kept


def forget_sends():
    """
    Clear this process's record of sent cards.

    Requires:
        - nothing

    Ensures:
        - the next sweep counts only cards found in the database
    """
    with _LOCK: _SENT.clear()


def _sent_times( session, owner_id, now ):
    """
    List the times of the owner's cards in the window, stored and in this process.

    Requires:
        - session is open; owner_id is the owner's user id; now is an aware datetime

    Ensures:
        - returns the stored cards' times plus each in-process send not yet stored
        - a send within a minute of a stored card is the same card and counts once
    """
    stored = review_card_times( session, owner_id, now )
    with _LOCK: held = [ moment for moment, _ in _SENT.get( str( owner_id ), [] ) if now - WINDOW < moment <= now ]
    return stored + [ moment for moment in held if all( abs( ( moment - done ).total_seconds() ) > SAME_SEND_SECONDS for done in stored ) ]


async def sweep_review_cards( session, owner_id, now, cap, dispatcher, current_version, wait_seconds ):
    """
    Send the owner one review card for their contested principles, unless the cap is reached.

    Requires:
        - session is open; owner_id is the owner's user id; now is an aware datetime
        - cap is the number of cards allowed in a rolling 24 hours
        - dispatcher has an async present_choices taking questions, title and response_options_extra
        - current_version is the extractor version; wait_seconds is how long the ask stays open

    Ensures:
        - returns { contested, sent, deferred, sent_in_window }
        - the card goes out through the dispatcher on its own thread, and this call does not wait for the answer
        - a card sent is counted against the cap at once, so a sweep that runs again before it is answered, or stored, sees it
        - with no contested principle, or at the cap, nothing is sent
    """
    items  = contested_items( session, owner_id, now, current_version )
    result = await send_review_card( DetachedDispatcher( dispatcher, wait_seconds ), items, _sent_times( session, owner_id, now ), now, cap )
    if result[ "sent" ]:
        sent_ids = { item[ "principle_id" ] for item in items } - { item[ "principle_id" ] for item in result[ "deferred" ] }
        _remember_send( owner_id, now, sent_ids )
    return { "contested": len( items ), "sent": result[ "sent" ], "deferred": len( result[ "deferred" ] ), "sent_in_window": result[ "sent_in_window" ] }


class ReviewCardSweepJob( AgenticJobBase ):
    """
    Send the owner's review card after an extractor job, as a job of its own.

    Requires:
        - user_id is the owner's user id and user_email their address

    Ensures:
        - the extractor job stays silent; only this job may send a card
        - the job reads the cap, the extractor model and the wait from the INI file when it runs
    """

    JOB_TYPE   = "principle_review_sweep"
    JOB_PREFIX = "pr"

    def __init__( self, user_id, user_email, dispatcher=None, session_factory=None, clock=None, cap=None, debug=False, verbose=False ):
        """
        Build the job.

        Requires:
            - dispatcher, session_factory, clock and cap are None or test stand-ins

        Ensures:
            - the job id has the "pr" prefix and the session id is "principle-review-sweep"
        """
        super().__init__( user_id=user_id, user_email=user_email, session_id=SESSION_ID, debug=debug, verbose=verbose )
        self.dispatcher      = dispatcher
        self.session_factory = session_factory
        self.clock           = clock
        self.cap             = cap

    @property
    def last_question_asked( self ):
        """
        Display string for the queue listing.

        Ensures:
            - returns "[Review card sweep] " and the owner's id
        """
        return f"[Review card sweep] {self.user_id}"

    def do_all( self ):
        """
        Run the sweep to completion.

        Ensures:
            - returns the JSON summary of _execute; raises what it raises, after the state is marked failed
        """
        return self._run_execute( "ReviewCardSweepJob", str( self.user_id ), "Review card sweep failed" )

    async def _execute( self ):
        """
        Sweep once for this owner.

        Ensures:
            - returns the sweep's report as a JSON string
            - a dispatcher is built for the owner's address when none was given
        """
        config     = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        version    = extractor_version_of( config.get_required( extractor_job.MODEL_KEY ) )
        wait       = config.get_required( WAIT_KEY, return_type="int" )
        cap        = self.cap if self.cap is not None else review_card_cap()
        now        = self.clock() if self.clock is not None else aware_moment( cu.get_current_datetime_iso() )
        dispatcher = self.dispatcher if self.dispatcher is not None else self._dispatcher()
        with ( self.session_factory if self.session_factory is not None else extractor_job.default_session )() as session:
            report = await sweep_review_cards( session, self.user_id, now, cap, dispatcher, version, wait )
        return json.dumps( report, sort_keys=True )

    def _dispatcher( self ):
        """
        Build the dispatcher that addresses the owner.

        Ensures:
            - returns an AgentNotificationDispatcher whose target user is the owner's address
        """
        from cosa.agents.utils.agent_notification_dispatcher import AgentNotificationDispatcher
        dispatcher             = AgentNotificationDispatcher( agent_type="principle.learner" )
        dispatcher.target_user = self.user_email
        return dispatcher


def sweep_job_after( extractor ):
    """
    Build the sweep job to queue right after an extractor job.

    Requires:
        - extractor is a PrincipleExtractorJob

    Ensures:
        - returns a ReviewCardSweepJob for the same owner
    """
    return ReviewCardSweepJob( extractor.user_id, extractor.user_email )
