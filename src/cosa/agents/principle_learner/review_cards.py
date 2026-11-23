"""
The review card: how a contested principle goes to Rick and his answer becomes a ruling.

When two sets of supporting answers disagree, the split step looks for a card feature that tells them apart.
If one exists, both sides gain a condition and nothing is asked. If none does, the principle is contested.
Contested principles go to Rick on a batched multiple-choice card, sent through the dispatcher's present_choices.
The card carries the review-card marker, so it is never forecast, never read by the extractor and never stored as a case.
At most the capped number of cards go to one owner in any rolling 24 hours.
His answer becomes one ruling row per principle, with source review_card, which the status function reads.
"""

import json
import uuid
from datetime import timedelta

from cosa.agents.heartbeat_arbiter.ping_throttle import prune_window
from cosa.agents.prediction_engine.history_derive import attribution_tier
from cosa.agents.prediction_engine.review_card import REVIEW_CARD_KEY, REVIEW_CARD_SOURCE, is_review_card
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.postgres_models import Notification, PreferenceEvidence
from cosa.utils.iso_timestamp import aware_moment

CAP_KEY        = "prediction learner review card cap per day"
WINDOW         = timedelta( hours=24 )
BATCH_MAX      = 5
PRINCIPLES_KEY = "principle_ids"
RULING_VERSION = "review_card"
OWNER_SOURCE   = "ui"

OPTION_ONE     = "One: keep the principle"
OPTION_OTHER   = "Other: drop the principle"
OPTION_BOTH    = "Both, under a condition"
OPTION_RETRACT = "Retract it"

SPLIT      = "split"
CONTESTED  = "contested"


def review_card_cap():
    """
    Read the number of review cards one owner may be sent in a rolling 24 hours.

    Requires:
        - the INI file holds the cap key

    Ensures:
        - returns the configured integer

    Raises:
        - MissingConfigKeyError if the key is absent
    """
    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get_required( CAP_KEY, return_type="int" )


def split_step( side_a, side_b ):
    """
    Look for a card feature that tells two sets of supporting episodes apart.

    Requires:
        - side_a and side_b are lists of dicts, one per episode, mapping a card feature name to its value

    Ensures:
        - a feature separates the sets when every episode of both has it and no value occurs on both sides
        - returns { feature, condition_a, condition_b } for the first separating feature in name order
        - a condition reads "<feature> is <value>", values joined by " or " in sorted order
        - returns None when either set is empty or no feature separates them
    """
    if not side_a or not side_b: return None
    names = set.intersection( *( set( episode ) for episode in side_a + side_b ) )
    for feature in sorted( names ):
        values_a = { str( episode[ feature ] ) for episode in side_a }
        values_b = { str( episode[ feature ] ) for episode in side_b }
        if values_a & values_b: continue
        return { "feature": feature, "condition_a": f"{feature} is {' or '.join( sorted( values_a ) )}",
                 "condition_b": f"{feature} is {' or '.join( sorted( values_b ) )}" }
    return None


def resolve_conflict( side_a, side_b ):
    """
    Decide what a contradiction between two sets of supporting episodes becomes.

    Requires:
        - side_a and side_b are as split_step takes them

    Ensures:
        - returns { outcome: "split", feature, condition_a, condition_b } when a feature separates the sets
        - returns { outcome: "contested" } otherwise; the principle is then put to Rick, and nothing is written here
    """
    found = split_step( side_a, side_b )
    return { "outcome": SPLIT, **found } if found is not None else { "outcome": CONTESTED }


def cards_in_window( sent_times, now ):
    """
    Count the cards sent inside the rolling 24 hours that end at now.

    Requires:
        - sent_times is a list of aware datetimes; now is an aware datetime

    Ensures:
        - counts a time after now minus 24 hours and at or before now; a card sent exactly 24 hours ago no longer counts
    """
    return len( prune_window( sent_times, now, WINDOW.total_seconds(), strict=True, drop_future=True ) )


def plan_card( contested, sent_times, now, cap, batch_max=BATCH_MAX ):
    """
    Decide which contested principles go on the next card, and which wait.

    Requires:
        - contested is a list of items { principle_id, statement, answer_a, answer_b }
        - sent_times and now are as cards_in_window takes them; cap is a non-negative integer; batch_max is positive

    Ensures:
        - returns { send, deferred, sent_in_window }
        - one batched card is planned per call: send holds at most batch_max items, in order
        - send is empty and every item is deferred when the window already holds cap cards or more
    """
    sent = cards_in_window( sent_times, now )
    if sent >= cap or not contested: return { "send": [], "deferred": list( contested ), "sent_in_window": sent }
    return { "send": list( contested[ :batch_max ] ), "deferred": list( contested[ batch_max: ] ), "sent_in_window": sent }


def build_card( items ):
    """
    Build the questions and the marker keys for one batched card.

    Requires:
        - items is a non-empty list of items { principle_id, statement, answer_a, answer_b }

    Ensures:
        - returns ( questions, extras ); questions are multiple-choice dicts with the four options, one per item
        - the header of the n-th question is "P<n>", counting from 1
        - extras is { "review_card": True, "principle_ids": { header: principle_id } }
    """
    questions = []
    ids       = {}
    for number, item in enumerate( items, start=1 ):
        header = f"P{number}"
        ids[ header ] = str( item[ "principle_id" ] )
        questions.append( {
            "question"    : f"{item[ 'statement' ]}\nYou said: {item[ 'answer_a' ]}\nYou also said: {item[ 'answer_b' ]}",
            "header"      : header,
            "multiSelect" : False,
            "options"     : [
                { "label": OPTION_ONE,     "description": "The principle stands as stated." },
                { "label": OPTION_OTHER,   "description": "The other answer wins; the principle is dropped." },
                { "label": OPTION_BOTH,    "description": f"Both hold. Type: {OPTION_BOTH}: your condition. A click alone records nothing." },
                { "label": OPTION_RETRACT, "description": "Drop the principle altogether." },
            ],
        } )
    return questions, { REVIEW_CARD_KEY: True, PRINCIPLES_KEY: ids }


async def send_review_card( dispatcher, contested, sent_times, now, cap, title="Which of your answers should win?", batch_max=BATCH_MAX ):
    """
    Send one batched review card through the dispatcher, unless the cap is reached.

    Requires:
        - dispatcher has an async present_choices taking questions, title and response_options_extra
        - the other arguments are as plan_card takes them

    Ensures:
        - returns { sent, deferred, sent_in_window, answers }; answers is the dispatcher's reply, or None when nothing was sent
        - nothing is sent when plan_card plans no card, so the dispatcher is not called
        - the marker and the header-to-principle map travel in the ask's response_options
    """
    plan = plan_card( contested, sent_times, now, cap, batch_max )
    if not plan[ "send" ]: return { "sent": False, "deferred": plan[ "deferred" ], "sent_in_window": plan[ "sent_in_window" ], "answers": None }
    questions, extras = build_card( plan[ "send" ] )
    answers = await dispatcher.present_choices( questions, title=title, response_options_extra=extras )
    return { "sent": True, "deferred": plan[ "deferred" ], "sent_in_window": plan[ "sent_in_window" ], "answers": answers }


def review_card_times( session, owner_id, now ):
    """
    List when review cards were last sent to an owner.

    Requires:
        - session is an open session; owner_id is the recipient's user id; now is an aware datetime

    Ensures:
        - returns the created_at, as an aware time, of every marked ask to that owner inside the 24 hours that end at now
    """
    rows = session.query( Notification.created_at, Notification.response_options ).filter(
        Notification.recipient_id == uuid.UUID( str( owner_id ) ), Notification.created_at > now - WINDOW ).all()
    return [ aware_moment( created ) for created, options in rows if is_review_card( options ) ]


def _ruling_of( label ):
    """
    Map one chosen option to a ruling.

    Requires:
        - label is the option text Rick chose, plus ": <condition>" for the both-under-a-condition option

    Ensures:
        - returns ( relation, condition ): supports for the first option, contradicts for the second and the fourth,
          refines with the written condition for the third
        - returns None for text that is no option, and for the third option with no condition written
    """
    if label == OPTION_ONE: return "supports", None
    if label in ( OPTION_OTHER, OPTION_RETRACT ): return "contradicts", None
    if label.startswith( OPTION_BOTH ):
        condition = label[ len( OPTION_BOTH ): ].lstrip( ": " ).strip()
        return ( "refines", condition ) if condition else None
    return None


def _owners_own_answer( row ):
    """
    Say whether the stored answer is the owner's own word, from their own screen.

    Requires:
        - row is an answered Notification

    Ensures:
        - returns True only when the answering user is the recipient and the source is the screen, the test the extractor applies
        - a timeout default, a proxy answer, an answer with no user and another account's answer are all False
    """
    value = row.response_value
    raw   = { "recipient_id": str( row.recipient_id ), "response_value": value }
    return attribution_tier( raw ) == "recipient" and isinstance( value, dict ) and value.get( "source" ) == OWNER_SOURCE


def record_card_answer( session, notification_id, now ):
    """
    Turn the answer to a review card into ruling rows.

    Requires:
        - session is an open session; notification_id names an answered ask
        - now is an aware datetime, written as the rows' extracted_at

    Ensures:
        - returns { rulings_written, existing, rejected }; rejected lists { header, reason }
        - an ask without the marker, an unanswered ask, or an answer with no choices writes nothing
        - an answer that is not the owner's own from their screen (a timeout default, a proxy, another account) writes nothing and is
          rejected with header None and reason not_the_owners_answer
        - each answered header writes one evidence row with source review_card, field key the header, answered_at the ask's response time
        - a header the card does not name, or an answer that is no option, is rejected and writes nothing
        - an answer recorded twice writes nothing the second time
        - no extractor-input row and no case is written, and the notification is not changed
    """
    report = { "rulings_written": 0, "existing": 0, "rejected": [] }
    row    = session.get( Notification, uuid.UUID( str( notification_id ) ) )
    if row is None or row.responded_at is None or not is_review_card( row.response_options ): return report
    if not _owners_own_answer( row ):
        report[ "rejected" ].append( { "header": None, "reason": "not_the_owners_answer" } )
        return report
    options = json.loads( row.response_options ) if isinstance( row.response_options, str ) else row.response_options
    ids     = options.get( PRINCIPLES_KEY, {} )
    value   = row.response_value[ "value" ] if isinstance( row.response_value, dict ) and "value" in row.response_value else row.response_value
    answers = ( json.loads( value ) if isinstance( value, str ) else value ).get( "answers", {} )
    for header, chosen in answers.items():
        label = chosen[ 0 ] if isinstance( chosen, list ) and chosen else chosen
        if header not in ids:
            report[ "rejected" ].append( { "header": header, "reason": "header_not_on_card" } )
            continue
        ruling = _ruling_of( label ) if isinstance( label, str ) else None
        if ruling is None:
            report[ "rejected" ].append( { "header": header, "reason": "answer_is_not_an_option_or_has_no_condition" } )
            continue
        key = dict( principle_id=uuid.UUID( ids[ header ] ), notification_id=row.id, field_key=header, extractor_version=RULING_VERSION, source=REVIEW_CARD_SOURCE )
        if session.query( PreferenceEvidence ).filter_by( **key ).first() is not None:
            report[ "existing" ] += 1
            continue
        session.add( PreferenceEvidence( id=uuid.uuid4(), relation=ruling[ 0 ], condition=ruling[ 1 ], answered_at=row.responded_at, extracted_at=now, **key ) )
        report[ "rulings_written" ] += 1
    return report
