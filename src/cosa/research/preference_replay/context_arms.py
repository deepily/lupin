"""
The text behind each vector in the context comparison.

Five arms change only the text embedded for an ask. Q is the question alone. Each other arm adds one input.
Q+A adds the card's abstract and Q+O adds its options.
Q+P adds the project and asking session. Q+H adds the previous answer on the same thread.

Q+A, Q+O and Q+P read fields of the ask itself, which are known at ask time.
Q+H reads the context that ``rebuild_context`` returns. An ask with no rebuilt context is embedded
as the question alone in Q+H, and is counted. An arm whose own input is empty for an ask does the same.
It is counted under its own name, so the two causes stay apart.
"""

import json
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from cosa.agents.prediction_engine.ask_family import PROJECT_PATTERN, UNKNOWN_PROJECT
from cosa.agents.prediction_engine.history_context_rebuild import SESSION_WINDOW, rebuild_context
from cosa.rest.postgres_models import Notification
from cosa.utils.iso_timestamp import aware_moment
from cosa.utils.notification_utils import sender_session_suffix

ARMS            = ( "Q", "Q+A", "Q+O", "Q+P", "Q+H" )
HISTORY_TIERS   = ( "parent", "thread" )
SESSION_TIERS   = ( "sender", "session" )
NO_CONTEXT      = "no_context"
INPUT_ABSENT    = "arm_input_absent"


def question_text( target: Dict[str, Any] ) -> str:
    """
    Give the question text every arm starts from.

    Requires:
        - target is a notification dict with a string message

    Ensures:
        - returns message.strip(), the text the live store path embeds
    """
    return target[ "message" ].strip()


def _abstract_section( target: Dict[str, Any] ) -> Optional[str]:
    """
    Render the card's abstract.

    Requires:
        - target may carry abstract as a string or None

    Ensures:
        - returns "Abstract: <stripped abstract>", or None when it is missing or blank
    """
    abstract = ( target.get( "abstract" ) or "" ).strip()
    return f"Abstract: {abstract}" if abstract else None


def _option_lines( question: Dict[str, Any] ) -> List[str]:
    """
    Render one card question and its options, flagging the recommended one.

    Requires:
        - question is a dict with optional header, question and options (a list of dicts with label)

    Ensures:
        - returns the question line, then one line per option label
        - an option is flagged when its recommended key is true or its label says Recommended,
          and the flag is added only when the label does not already carry it
        - an option without a label is skipped
    """
    head  = ": ".join( part for part in ( str( question.get( "header", "" ) ).strip(), str( question.get( "question", "" ) ).strip() ) if part )
    lines = [ f"- {head}" ] if head else []
    for option in question.get( "options", [] ):
        if not isinstance( option, dict ) or not str( option.get( "label", "" ) ).strip(): continue
        label = str( option[ "label" ] ).strip()
        flag  = option.get( "recommended" ) is True and "recommended" not in label.lower()
        lines.append( f"  * {label}{' (recommended)' if flag else ''}" )
    return lines


def _options_section( target: Dict[str, Any] ) -> Optional[str]:
    """
    Render the card's options.

    Requires:
        - target may carry response_options as a dict with a "questions" list, or None

    Ensures:
        - returns "Options:" and the option lines, or None when the card has no option labels
    """
    options = target.get( "response_options" )
    if not isinstance( options, dict ) or not isinstance( options.get( "questions" ), list ): return None
    lines = []
    for question in options[ "questions" ]:
        if isinstance( question, dict ): lines.extend( _option_lines( question ) )
    return "\n".join( [ "Options:" ] + lines ) if any( line.startswith( "  *" ) for line in lines ) else None


def _project_section( target: Dict[str, Any] ) -> Optional[str]:
    """
    Render the project and the asking session.

    Requires:
        - target may carry sender_id as a string or None

    Ensures:
        - returns "Project: <label>" and, when the sender id has a session part, "Session: <id>"
        - returns None when the sender id names neither
    """
    sender  = target.get( "sender_id" ) or ""
    match   = PROJECT_PATTERN.search( sender )
    project = match.group( 1 ) if match else UNKNOWN_PROJECT
    session = sender_session_suffix( sender )
    lines   = [] if project == UNKNOWN_PROJECT else [ f"Project: {project}" ]
    if session is not None: lines.append( f"Session: {session}" )
    return "\n".join( lines ) if lines else None


def _answer_text( value: Any ) -> str:
    """
    Render a stored answer as text.

    Requires:
        - value is a string or JSON-serialisable

    Ensures:
        - returns a string as it is, anything else as sorted JSON
    """
    return value if isinstance( value, str ) else json.dumps( value, sort_keys=True )


def _latest_answered( attachments: List[Dict[str, Any]], tiers: Tuple[str, ...] ) -> Optional[Dict[str, Any]]:
    """
    Pick the attachment answered last among the given tiers.

    Requires:
        - attachments come from rebuild_context

    Ensures:
        - returns the attachment of a given tier with status answered whose answer became known last
        - ties go to the lower id; returns None when there is none
    """
    answered = [ a for a in attachments if a[ "tier" ] in tiers and a[ "answer" ][ "status" ] == "answered" ]
    if not answered: return None
    return min( answered, key=lambda a: ( -aware_moment( a[ "answer" ][ "answer_known_at" ] ).timestamp(), a[ "id" ] ) )


def _history_section( target: Dict[str, Any], context: Dict[str, Any], notes_by_id: Dict[str, Dict[str, Any]] ) -> Optional[str]:
    """
    Render the latest answer known at the ask, from its thread or its sender session.

    Requires:
        - context comes from rebuild_context for this target
        - notes_by_id maps notification id to its dict, and holds every attachment of the context

    Ensures:
        - an answered parent or thread attachment wins; the one answered last is chosen
        - otherwise an answered sender or session attachment created within SESSION_WINDOW of the ask is chosen the same way
        - returns "Previous answer on this thread: ..." or "Previous answer in this session: ..." with the earlier question
          and its answer, or None when there is none

    Raises:
        - ValueError if a chosen answer became known after the ask, which rebuild_context never returns
    """
    asked_at = aware_moment( target[ "created_at" ] )
    chosen   = _latest_answered( context[ "attachments" ], HISTORY_TIERS )
    where    = "on this thread"
    if chosen is None:
        near   = [ a for a in context[ "attachments" ] if asked_at - aware_moment( a[ "first_known_at" ] ) <= SESSION_WINDOW ]
        chosen = _latest_answered( near, SESSION_TIERS )
        where  = "in this session"
    if chosen is None: return None
    if aware_moment( chosen[ "answer" ][ "answer_known_at" ] ) > asked_at:
        raise ValueError( f"answer to {chosen[ 'id' ]} became known after the ask {target[ 'id' ]}" )
    return f"Previous answer {where}: {question_text( notes_by_id[ chosen[ 'id' ] ] )} -> {_answer_text( chosen[ 'answer' ][ 'value' ] )}"


def arm_text( arm: str, target: Dict[str, Any], context: Dict[str, Any], notes_by_id: Dict[str, Dict[str, Any]] ) -> Tuple[str, Optional[str]]:
    """
    Build the text to embed for one ask in one arm.

    Requires:
        - arm is a name in the module's arm tuple
        - target is a notification dict with id, created_at and message
        - context is the rebuild_context result for the target
        - notes_by_id maps notification id to its dict, and holds every attachment of the context

    Ensures:
        - returns ( text, reason )
        - the arm Q returns the question and reason None, whatever the context
        - Q+H returns the question alone with reason "no_context" when context_state is not reconstructed
        - the arms Q+A, Q+O and Q+P never read the context
        - an arm whose input is empty returns the question alone with reason "arm_input_absent"
        - otherwise returns the question, a blank line, then the arm's section, with reason None

    Raises:
        - ValueError if arm is not a name in the arm tuple
    """
    if arm not in ARMS: raise ValueError( f"arm must be one of {ARMS}, got {arm!r}" )
    question = question_text( target )
    if arm == "Q": return question, None
    if arm == "Q+H" and context[ "context_state" ] != "reconstructed": return question, NO_CONTEXT
    builders = { "Q+A": lambda: _abstract_section( target ), "Q+O": lambda: _options_section( target ),
                 "Q+P": lambda: _project_section( target ), "Q+H": lambda: _history_section( target, context, notes_by_id ) }
    section  = builders[ arm ]()
    if section is None: return question, INPUT_ABSENT
    return f"{question}\n\n{section}", None


def build_arm_texts( arm: str, targets: List[Dict[str, Any]], contexts: Dict[str, Dict[str, Any]],
                     notes_by_id: Dict[str, Dict[str, Any]] ) -> Dict[str, Any]:
    """
    Build one arm's text for every ask, counting the asks that fell back to the question.

    Requires:
        - arm is a name in the module's arm tuple
        - targets is a list of notification dicts with distinct ids
        - contexts maps each target id to its rebuild_context result
        - notes_by_id is as for arm_text

    Ensures:
        - returns { arm, texts, counts }
        - texts maps every target id to its text, and the order follows targets
        - counts holds asks, with_section, no_context and arm_input_absent; the last three add up to asks

    Raises:
        - ValueError as arm_text does
        - KeyError if a target has no context
    """
    texts   = {}
    reasons = Counter()
    for target in targets:
        text, reason = arm_text( arm, target, contexts[ target[ "id" ] ], notes_by_id )
        texts[ target[ "id" ] ] = text
        reasons[ reason ] += 1
    counts = { "asks": len( targets ), "with_section": reasons[ None ], NO_CONTEXT: reasons[ NO_CONTEXT ], INPUT_ABSENT: reasons[ INPUT_ABSENT ] }
    return { "arm": arm, "texts": texts, "counts": counts }


def notification_dict( row: Any ) -> Dict[str, Any]:
    """
    Turn a Notification row into the dict that rebuild_context and the arm builders read.

    Requires:
        - row has the Notification columns listed below

    Ensures:
        - returns id (as text), created_at (ISO text), message, abstract, response_options, sender_id, reply_to,
          thread_id, job_id, direction, response_requested, responded_at (ISO text or None) and response_value
        - created_at is the notification's own creation time, never a case row's time
    """
    return { "id": str( row.id ), "created_at": row.created_at.isoformat(), "message": row.message, "abstract": row.abstract,
             "response_options": row.response_options, "sender_id": row.sender_id, "reply_to": row.reply_to, "thread_id": row.thread_id,
             "job_id": row.job_id, "direction": row.direction, "response_requested": row.response_requested,
             "responded_at": row.responded_at.isoformat() if row.responded_at is not None else None,
             "response_value": row.response_value }


def read_arm_inputs( session: Any, asks: List[Dict[str, Any]] ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Read each cohort ask's notification, and the pool of question notifications.

    Requires:
        - session is an active SQLAlchemy session
        - asks are cohort_asks dicts, whose id is the notification id

    Ensures:
        - returns ( targets, notes_by_id )
        - targets hold one notification dict per ask, in the asks' order
        - notes_by_id holds the targets and every notification with response_requested true, keyed by id
        - the pool holds question notifications only, because only a question carries an answer
        - the context state of a target is read over that pool, so it can differ from a rebuild over every notification

    Raises:
        - LookupError if an ask has no notification row
    """
    targets = []
    for ask in asks:
        row = session.get( Notification, ask[ "id" ] )
        if row is None: raise LookupError( f"ask {ask[ 'id' ]} has no notification row" )
        targets.append( notification_dict( row ) )
    pool = { str( row.id ): notification_dict( row ) for row in session.query( Notification ).filter( Notification.response_requested.is_( True ) ).all() }
    notes_by_id = dict( pool )
    notes_by_id.update( { target[ "id" ]: target for target in targets } )
    return targets, notes_by_id


def build_cohort_arms( session: Any, asks: List[Dict[str, Any]], arms: Tuple[str, ...] = ARMS ) -> Dict[str, Dict[str, Any]]:
    """
    Build the text of every arm for every ask of a cohort.

    Requires:
        - session is an active SQLAlchemy session
        - asks are cohort_asks dicts
        - arms are names in the arm tuple

    Ensures:
        - returns { arm: build_arm_texts result } for each arm
        - each context is rebuilt once, from the pool read_arm_inputs returns, and shared by all arms

    Raises:
        - LookupError as read_arm_inputs does
        - ValueError as build_arm_texts does
    """
    targets, notes_by_id = read_arm_inputs( session, asks )
    pool     = list( notes_by_id.values() )
    contexts = { target[ "id" ]: rebuild_context( target, pool ) for target in targets }
    return { arm: build_arm_texts( arm, targets, contexts, notes_by_id ) for arm in arms }
