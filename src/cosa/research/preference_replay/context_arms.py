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
from cosa.agents.prediction_engine.history_context_rebuild import _session_of
from cosa.utils.iso_timestamp import aware_moment

ARMS            = ( "Q", "Q+A", "Q+O", "Q+P", "Q+H" )
HISTORY_TIERS   = ( "parent", "thread" )
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
    session = _session_of( sender )
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


def _history_section( target: Dict[str, Any], context: Dict[str, Any], notes_by_id: Dict[str, Dict[str, Any]] ) -> Optional[str]:
    """
    Render the latest answer known at the ask from the target's own thread.

    Requires:
        - context comes from rebuild_context for this target
        - notes_by_id maps notification id to its dict, and holds every attachment of the context

    Ensures:
        - only attachments of the parent and thread tiers with status answered are considered
        - the one answered last is chosen; ties go to the lower id
        - returns "Previous answer on this thread: <its question> -> <its answer>", or None when there is none

    Raises:
        - ValueError if a chosen answer became known after the ask, which rebuild_context never returns
    """
    asked_at = aware_moment( target[ "created_at" ] )
    answered = [ a for a in context[ "attachments" ] if a[ "tier" ] in HISTORY_TIERS and a[ "answer" ][ "status" ] == "answered" ]
    if not answered: return None
    chosen = min( answered, key=lambda a: ( -aware_moment( a[ "answer" ][ "answer_known_at" ] ).timestamp(), a[ "id" ] ) )
    if aware_moment( chosen[ "answer" ][ "answer_known_at" ] ) > asked_at:
        raise ValueError( f"answer to {chosen[ 'id' ]} became known after the ask {target[ 'id' ]}" )
    return f"Previous answer on this thread: {question_text( notes_by_id[ chosen[ 'id' ] ] )} -> {_answer_text( chosen[ 'answer' ][ 'value' ] )}"


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
