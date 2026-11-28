"""
The meaning labeller's plain-code rules: read one stored answer, field by field, no model.

Plain code decides the stance word, the selected option ids and the match with the recommended option.
It also decides whether a comment exists, an empty selection and the answer's source.
The rules are in plan sections 3, 3b and 5. What plain code cannot decide has no relation, and the model layer labels it.
The result is a plain dict, so no database row or session reaches the model.

A draft holds response_type, card_text, unknowns, fields and plain.
The field key is "answer" on a single-field card, else the question header.
Each of fields has kind, prompt, options, answer, stance, comment, selected_ids, write_in_text and relation.
A relation of None means the model decides.
plain maps a field key to a finished entry with no relation, which is an empty selection.
"""
import json

from cosa.agents.prediction_engine.episode_view import fields_of
from cosa.utils.notification_utils import extract_qualifier_comment, parse_field_selections

SINGLE_KEY     = "answer"
HUMAN_SOURCE   = "ui"
TIMEOUT_SOURCE = "timeout_default"
CANCELLED_TEXT = "[cancelled]"
TEXT_TYPES     = ( "yes_no", "open_ended" )
FIELD_TYPES    = ( "multiple_choice", "open_ended_batch" )


def card_text_of( notification ):
    """
    Join a card's title, message and abstract.

    Requires:
        - notification has title, message and abstract, each a string or None

    Ensures:
        - returns the non-blank parts on separate lines
        - the title is left out when the message opens with it
    """
    title, message = notification.title or "", notification.message or ""
    head = "" if message.startswith( title ) else title
    return "\n".join( part for part in ( head, message, notification.abstract ) if part and part.strip() )


def _field( kind, answer, prompt=None, options=(), stance=None, comment=None, selected_ids=(), write_in_text=None, relation=None ):
    """Ensures: returns one draft field with every key present."""
    return { "kind": kind, "prompt": prompt, "options": list( options ), "answer": answer, "stance": stance, "comment": comment,
             "selected_ids": list( selected_ids ), "write_in_text": write_in_text, "relation": relation }


def entry_of( field ):
    """
    Build the stored native-answer entry of one draft field.

    Requires:
        - field is a draft field

    Ensures:
        - returns kind, selected_option_ids, empty_selection, write_in_text, referred_option_ids and text
        - text is the stance of a yes or no field that has one, the answer of any other text field, and None on a card field
        - "comment" and "relation" are present only when the field has them
    """
    if field[ "kind" ] == "yes_no_stance": text = field[ "stance" ] or field[ "answer" ]
    elif field[ "kind" ] in ( "open_ended_text", "batch_field_text" ): text = field[ "answer" ]
    else: text = None
    entry = { "kind": field[ "kind" ], "selected_option_ids": list( field[ "selected_ids" ] ), "empty_selection": False,
              "write_in_text": field[ "write_in_text" ], "referred_option_ids": [], "text": text }
    if field[ "comment" ] is not None: entry[ "comment" ] = field[ "comment" ]
    if field[ "relation" ] is not None: entry[ "relation" ] = field[ "relation" ]
    return entry


def pending_keys( draft ):
    """Ensures: returns the field keys the model still has to label, in card order."""
    return [ key for key, field in draft[ "fields" ].items() if field[ "relation" ] is None ]


def _is_cancelled( value ):
    """Ensures: returns True for the cancelled marker, as text or as a json cancelled flag."""
    if value.strip() == CANCELLED_TEXT: return True
    try:
        parsed = json.loads( value )
    except ValueError:
        return False
    return isinstance( parsed, dict ) and parsed.get( "cancelled" ) is True


def _yes_no( draft, value ):
    """
    Read a yes, no or neither answer.

    Ensures:
        - a bare stance is no_comment; a stance with a comment has no relation
        - a string with no recognised stance has neither, and unknowns holds no_explicit_stance
        - a neither is also named in unknowns
    """
    answer          = value.strip()
    stance, comment = extract_qualifier_comment( answer )
    if stance is None: draft[ "unknowns" ].append( "no_explicit_stance" )
    if stance == "neither": draft[ "unknowns" ].append( "neither" )
    relation = "no_comment" if stance is not None and comment is None else None
    draft[ "fields" ][ SINGLE_KEY ] = _field( "yes_no_stance", answer, stance=stance, comment=comment, relation=relation )


def _text_field( kind, text, prompt, silent ):
    """Ensures: returns a text field, no_answer when the text is blank or nobody typed it."""
    answer = text.strip()
    return _field( kind, answer, prompt=prompt, relation="no_answer" if silent or not answer else None )


def _pick_field( card_field, record ):
    """
    Read one multiple-choice answer against its question's options.

    Requires:
        - card_field is a fields_of entry; record is a parse_field_selections entry with at least one pick

    Ensures:
        - picks that equal an option's label are selected ids ("<header>#o<n>"); any other pick is typed text
        - with typed text the field has no relation
        - else no_recommendation_on_card when no option is recommended, agrees when every pick is recommended,
          and chose_different_listed_option otherwise
    """
    key     = card_field[ "key" ]
    by_name = { str( o[ "label" ] ).strip(): o for o in card_field[ "options" ] }
    picks   = [ str( pick ) for pick in record[ "selected" ] ]
    chosen  = [ by_name[ pick ] for pick in picks if pick in by_name ]
    typed   = [ pick for pick in picks if pick not in by_name ]
    options = [ dict( o, id=f"{key}#{o[ 'id' ]}" ) for o in card_field[ "options" ] ]
    if record[ "mode" ] == "multi": kind = "multi_selected_options" if chosen else "write_in_text"
    else: kind = "selected_options" if chosen else "write_in_text"
    relation = None
    if not typed:
        if not any( o[ "recommended" ] for o in options ): relation = "no_recommendation_on_card"
        elif all( o[ "recommended" ] for o in chosen ): relation = "agrees"
        else: relation = "chose_different_listed_option"
    return _field( kind, "; ".join( picks ), prompt=card_field[ "prompt" ], options=options, selected_ids=[ f"{key}#{o[ 'id' ]}" for o in chosen ],
                   write_in_text="; ".join( typed ) or None, relation=relation )


def _answers_of( value, card_fields ):
    """
    Read a card answer as one record per header.

    Ensures:
        - returns parse_field_selections of the value when it is an answers map
        - a plain string, the older stored form, is the one pick of a card with exactly one question
        - returns None otherwise
    """
    parsed = parse_field_selections( value )
    if parsed is not None: return parsed
    if value.lstrip().startswith( "{" ) or len( card_fields ) != 1: return None
    return { card_fields[ 0 ][ "key" ]: { "mode": "single", "selected": [ value.strip() ], "text": value } }


def _multiple_choice( draft, value, card_fields ):
    """
    Read a multiple-choice answer, one entry per question.

    Ensures:
        - a question with no answer entry adds absent_field and no field
        - an empty selection is a finished plain entry
        - an unplaceable answer adds unreadable_payload
    """
    answers = _answers_of( value, card_fields )
    if answers is None:
        draft[ "unknowns" ].append( "unreadable_payload" )
        return
    for card_field in card_fields:
        key    = card_field[ "key" ]
        record = answers.get( key )
        if record is None:
            draft[ "unknowns" ].append( "absent_field" )
        elif not record[ "selected" ]:
            draft[ "plain" ][ key ] = { "kind": "empty_selection", "selected_option_ids": [], "empty_selection": True,
                                        "write_in_text": None, "referred_option_ids": [], "text": None }
        else:
            draft[ "fields" ][ key ] = _pick_field( card_field, record )


def _batch( draft, value, card_fields, silent ):
    """
    Split a batch answer into one text entry per header.

    Ensures:
        - the headers are the card's questions, then any further header the answer holds
        - a blank or missing header, and every header of a timed-out card, is no_answer
        - an unreadable answer adds unreadable_payload
    """
    answers = parse_field_selections( value )
    if answers is None:
        draft[ "unknowns" ].append( "unreadable_payload" )
        return
    prompts = { f[ "key" ]: f[ "prompt" ] for f in card_fields }
    for key in list( prompts ) + [ k for k in answers if k not in prompts ]:
        text = ( answers.get( key ) or {} ).get( "text" ) or ""
        draft[ "fields" ][ key ] = _text_field( "batch_field_text", text, prompts.get( key ), silent )


def draft_of( notification ):
    """
    Read one stored answer with plain code.

    Requires:
        - notification has response_type, response_value, response_options, response_default, title, message and abstract
        - response_type is yes_no, multiple_choice, open_ended or open_ended_batch

    Ensures:
        - returns the draft the module docstring describes
        - a response_value without text or with a source other than ui or timeout_default adds unreadable_payload and no field,
          so an answer nobody can be shown to have given is never read as a stance
        - a timeout default or a cancelled card adds cancellation; a yes or no or multiple-choice card then has no field,
          and an open-ended or batch card has no_answer fields

    Raises:
        - ValueError for any other response type
    """
    response_type = notification.response_type
    if response_type not in TEXT_TYPES + FIELD_TYPES: raise ValueError( f"unknown response type {response_type!r}" )
    draft  = { "response_type": response_type, "card_text": card_text_of( notification ), "unknowns": [], "fields": {}, "plain": {} }
    stored = notification.response_value
    value  = stored.get( "value" ) if isinstance( stored, dict ) else None
    source = stored.get( "source" ) if isinstance( stored, dict ) else None
    if not isinstance( value, str ) or source not in ( HUMAN_SOURCE, TIMEOUT_SOURCE ):
        draft[ "unknowns" ].append( "unreadable_payload" )
        return draft
    silent = source == TIMEOUT_SOURCE or _is_cancelled( value )
    if silent: draft[ "unknowns" ].append( "cancellation" )
    card_fields = fields_of( notification.response_options, notification.response_default )
    if response_type == "yes_no":
        if not silent: _yes_no( draft, value )
    elif response_type == "open_ended":
        draft[ "fields" ][ SINGLE_KEY ] = _text_field( "open_ended_text", value, None, silent )
    elif response_type == "multiple_choice":
        if not silent: _multiple_choice( draft, value, card_fields )
    else:
        # a cancelled batch carries no answers, so the card's questions stand alone
        _batch( draft, '{"answers":{}}' if silent and parse_field_selections( value ) is None else value, card_fields, silent )
    return draft
