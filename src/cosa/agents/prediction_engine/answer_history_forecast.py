"""
The answer history arm: the baseline job plus Rick's earlier answers, retrieved whole.

It runs the same model and the same prompts as the baseline arm. The one difference is a block of his earlier
answers to similar questions, as of the ask, added to the user prompt.
Each answer is shown as it was given.
It carries the card's question, the options as shown with their ids, the recommendation, and his raw final response.
The raw response is the stance, comment, typed text and picks.
The labeller's reading is never shown, so the arm never inherits the labeller's errors.

It is the yardstick the learned principles arm has to beat (experiment plan, section 3, "The answer history arm").
It shares ``principles_forecast.run_arm`` through a block provider, so it inherits that function's switch, cap, failure
handling and row writing. The reply goes through the baseline's own ``parse``, the same reader every forecaster arm uses.

Retrieval follows the plan's rule. ``three_way_stance.neighbours_of`` ranks earlier cards by question similarity with its
independence weight, over ``time_sliced_store.TimeSlicedDecisionStore``, which makes an answer visible only as of the ask.
A card is eligible only if its human answer and its meaning record both existed at or before the ask.

The budget is a parameter. Its value is fixed at the freeze, not here.
"""

import inspect
import json
import math
import uuid

from cosa.agents.prediction_engine import principles_forecast
from cosa.agents.prediction_engine.episode_view import card_text, fields_of
from cosa.agents.prediction_engine.exposure import observation_view
from cosa.agents.prediction_engine.history_context_rebuild import answer_known_at_ask
from cosa.agents.prediction_engine.three_way_stance import is_owners_human_answer, neighbours_of
from cosa.repo.doc_lint import model_transport
from cosa.rest.postgres_models import AnswerMeaning, Notification
from cosa.utils.iso_timestamp import aware_moment

ARM              = "answer_history"
SWITCH_KEY       = "principle learner answer history arm enabled"
BLOCK_HEADING    = "Your owner's earlier answers to similar questions, shown whole as they were given:"
VERSION_PREFIX   = "+answer-history-"
HASH_LENGTH      = 10
CHARACTERS_PER_TOKEN = 4


def answer_history_enabled():
    """
    Say whether the answer history arm is switched on.

    Requires:
        - nothing; an unreadable setting reads as off

    Ensures:
        - returns True only when the INI key named by SWITCH_KEY is true
        - never raises, so a settings failure cannot stop an ask
    """
    return principles_forecast.switch_enabled( SWITCH_KEY )


def approx_tokens( text ):
    """
    Estimate how many model tokens a text takes.

    Requires:
        - text is a string

    Ensures:
        - returns ceil( characters / 4 ), a whole number, 0 for the empty text
        - it is an estimate, not a tokenizer's count; a caller that has a tokenizer passes its own counter
    """
    return math.ceil( len( text ) / CHARACTERS_PER_TOKEN )


def _plain( value ):
    """
    Turn a read-only mapping from observation_view into a dict, so json can write it.

    Requires:
        - value is a mapping that json does not know how to write

    Ensures:
        - returns dict( value )
    """
    return dict( value )


def render_answer( message, view ):
    """
    Show one earlier answer whole, as it was given.

    Requires:
        - message is the earlier card's question text
        - view is exposure.observation_view's result for that card

    Ensures:
        - returns the question, one line per field with each option's id and label (the asker's recommendation marked), and the owner's raw response
        - the raw response is the stored value as it was, in JSON with sorted keys, so the same answer always reads the same
        - nothing from the meaning record, the forecast or the labeller is shown
        - a card with no fields and no response still returns the question and a response of null
    """
    lines = [ f"Question: {message}" ]
    ids   = view[ "option_ids" ]
    for field in fields_of( view[ "card" ], None ):
        shown = "; ".join( f"[{one}] \"{option[ 'label' ]}\"" + ( " (recommended by the asker)" if option[ "recommended" ] else "" )
                           for one, option in zip( ids.get( field[ "key" ], () ), field[ "options" ] ) )
        lines.append( f"- {field[ 'key' ] or 'field'}: {field[ 'prompt' ] or ''}".rstrip() + ( f" options: {shown}" if shown else " (free text)" ) )
    lines.append( "Answer given: " + json.dumps( view[ "raw_response" ], sort_keys=True, default=_plain, ensure_ascii=False ) )
    return "\n".join( lines )


def render_history( entries, budget, count_tokens=approx_tokens ):
    """
    Lay out as many whole answers as the budget allows, strongest first.

    Requires:
        - entries is a list of ( notification id, rendered answer ), strongest first
        - budget is a non-negative int, in the unit count_tokens counts
        - count_tokens maps a text to a whole number

    Ensures:
        - returns { text, ids } where ids are the notification ids shown, in order
        - an answer is shown whole or not at all; none is cut short
        - it stops at the first answer that does not fit, so a weaker answer never takes the place of a stronger one
        - count_tokens( text ) is never more than budget; with nothing that fits, text is "" and ids is []
    """
    shown, used, text = [], [], ""
    for notification_id, rendered in entries:
        candidate = "\n\n".join( shown + [ f"Earlier answer {len( shown ) + 1}:\n{rendered}" ] )
        if count_tokens( candidate ) > budget: break
        shown.append( f"Earlier answer {len( shown ) + 1}:\n{rendered}" )
        used.append( notification_id )
        text = candidate
    return { "text": text, "ids": used }


def history_code_hash():
    """
    Hash the code and text that decide how the history is shown.

    Requires:
        - nothing

    Ensures:
        - returns model_transport.prompt_version's hex digits, HASH_LENGTH of them, over the heading and the source of render_answer, render_history, eligible_cases, the provider, observation_view and fields_of
        - a change to any of them changes the value, so a new way of showing the history starts a new ledger
    """
    parts = ( BLOCK_HEADING, inspect.getsource( render_answer ), inspect.getsource( render_history ), inspect.getsource( eligible_cases ), inspect.getsource( history_provider ),
              inspect.getsource( observation_view ), inspect.getsource( fields_of ) )
    return model_transport.prompt_version( "answer-history", *parts ).rsplit( "-", 1 )[ 1 ]


def version_suffix():
    """
    Name the arm's version suffix, added to the baseline's predictor version.

    Requires:
        - nothing

    Ensures:
        - returns VERSION_PREFIX followed by history_code_hash()
    """
    return VERSION_PREFIX + history_code_hash()


def eligible_cases( session, cases, owner_id, asked_at ):
    """
    Keep the cases that may be shown for this ask.

    Requires:
        - session is an active session; cases are TimeSlicedDecisionStore.visible_cases, each with an id that is a notification id
        - owner_id is the ask's owner as text; asked_at is an aware datetime

    Ensures:
        - keeps a case answered by a human, owned by the ask's owner, not thumbed down, answered at or before the ask
          and with a meaning record annotated at or before the ask
        - the answer's own time is checked here by history_context_rebuild.answer_known_at_ask, the one as-of rule, as well as by the store
        - the cases keep their order
    """
    kept = [ case for case in cases if is_owners_human_answer( case, owner_id ) and answer_known_at_ask( case[ "responded_at" ], asked_at ) ]
    if not kept: return []
    known = { str( row[ 0 ] ) for row in session.query( AnswerMeaning.notification_id )
              .filter( AnswerMeaning.notification_id.in_( [ uuid.UUID( case[ "id" ] ) for case in kept ] ), AnswerMeaning.annotated_at <= asked_at ).distinct() }
    return [ case for case in kept if case[ "id" ] in known ]


def history_provider( store, embedder, budget, half_life_days, count_tokens=approx_tokens ):
    """
    Make the block provider that run_arm calls for this arm.

    Requires:
        - store is a TimeSlicedDecisionStore over the cases the arm may ever retrieve
        - embedder has encode( text ) returning a vector from the encoder the store's vectors came from
        - budget is a non-negative int, in the unit count_tokens counts; half_life_days is positive
        - count_tokens maps a text to a whole number

    Ensures:
        - returns provider( session, episode ) giving { text, principle_ids, heading }
        - the store is advanced to the ask, so an answer given after the ask is never retrieved
        - the neighbours are neighbours_of the eligible cases, strongest first, each shown whole by render_answer from its notification's observation view
        - a neighbour whose notification no longer exists is skipped
        - the heading line and the text together, as run_arm's prompt carries them, never take more than budget by count_tokens
        - principle_ids holds the shown notification ids, in order, as the row's evidence ids; with nothing shown text is ""
    """
    def provider( session, episode ):
        """Give the block for one ask."""
        asked_at = aware_moment( episode[ "asked_at" ] )
        store.advance_to( asked_at )
        cases    = eligible_cases( session, store.visible_cases(), episode[ "owner_id" ], asked_at )
        found    = neighbours_of( { "question_embedding": embedder.encode( card_text( episode ) ), "asked_at": asked_at }, cases, half_life_days )
        entries  = []
        for neighbour in found:
            row = session.get( Notification, uuid.UUID( neighbour[ "case" ][ "id" ] ) )
            if row is None: continue
            entries.append( ( neighbour[ "case" ][ "id" ], render_answer( row.message, observation_view( row.response_type, row.response_options, row.response_value, row.responded_at, None, None ) ) ) )
        laid = render_history( entries, max( budget - count_tokens( f"\n\n{BLOCK_HEADING}\n" ), 0 ), count_tokens )
        return { "text": laid[ "text" ], "principle_ids": laid[ "ids" ], "heading": BLOCK_HEADING }
    return provider


async def run_answer_history( session_factory, notification_id, c0, store, embedder, budget, half_life_days, gate, enabled=None, clock=None, count_tokens=approx_tokens ):
    """
    Make the answer history forecast for one ask, and store its row.

    Requires:
        - session_factory, notification_id, c0, gate, enabled and clock as run_arm takes them
        - store, embedder, budget, half_life_days and count_tokens as history_provider takes them

    Ensures:
        - is run_arm for this arm, with no principle block and the history block from history_provider, so everything run_arm ensures holds
        - with the switch off, nothing is read, called or written
        - the row's arm is the answer history arm's and its version is the baseline's plus version_suffix()
    """
    return await principles_forecast.run_arm( ARM, SWITCH_KEY, version_suffix(), False, session_factory, notification_id, c0, embedder, None, None, gate,
                                              enabled=enabled, clock=clock, block_provider=history_provider( store, embedder, budget, half_life_days, count_tokens ) )
