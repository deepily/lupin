"""
The full-answer reply: what a forecaster may say about a card, and its parser.

Today a forecast is one answer and one confidence. The full-answer reply is the forecast record of the answer-signal pipeline.
It holds probabilities over yes, no and neither, and the conversational acts as marginals.
It says whether a material condition is likely and which options it changes.
It gives the chosen option ids per field, or a write-in or re-frame.
It also gives the expected text as a gist and the chance the whole card is right.
A reply may instead abstain.

This module holds the reply format, the stable option id, the six named refusals and the parser. ``context_baseline.parse_reply``
calls ``parse_full_reply`` when the switch is on, so every forecaster that parses through ``parse_reply`` reads the new reply.
Each helper below is part of the source ``context_baseline.predictor_version`` hashes while the switch is on.

A refusal raises ``ReplyRefused``, a ``ValueError`` that names its reason. ``principles_forecast.run_arm`` stores that reason on an
abstention row and writes no forecast value, so a refused reply never becomes a forecast.
The switch is ``prediction engine full answer reply enabled``, default off. With it off nothing here is called.
"""

import hashlib

from cosa.agents.io_models.utils.json_object_recovery import recover_json_object
from cosa.config.configuration_manager import ConfigurationManager
from cosa.config.switch_reader import read_switch

SWITCH_KEY                    = "prediction engine full answer reply enabled"
REASON_REPLY_NOT_JSON         = "reply_not_json"
REASON_NOT_NORMALISED         = "probabilities_not_normalised"
REASON_UNKNOWN_OPTION_ID      = "unknown_option_id"
REASON_FIELD_MISSING          = "field_missing"
REASON_STANCE_NOT_IN_VOCAB    = "stance_not_in_vocabulary"
REASON_MODEL_ABSTAINED        = "model_abstained"
REFUSAL_REASONS               = ( REASON_REPLY_NOT_JSON, REASON_NOT_NORMALISED, REASON_UNKNOWN_OPTION_ID, REASON_FIELD_MISSING,
                                  REASON_STANCE_NOT_IN_VOCAB, REASON_MODEL_ABSTAINED )
FULL_ANSWER_TYPES             = ( "yes_no", "multiple_choice", "open_ended", "open_ended_batch" )
STANCES                       = ( "yes", "no", "neither" )
ACTS                          = ( "approve", "decline", "challenge_premise", "request_information", "defer", "propose_alternative" )
NORMALISED_TOLERANCE          = 0.01
SELECTION_KEYS                = ( "option_ids", "write_in", "reframe" )

_COMMON_FORMAT = ( '"acts": {"approve": p, "decline": p, "challenge_premise": p, "request_information": p, "defer": p, "propose_alternative": p}, '
                   '"qualification": {"probability": p, "conditions": [{"text": "<the condition>", "modifies_option_id": "<an option id> or null"}]}, '
                   '"gist": "<the answer you expect, in a sentence>", "whole_card_probability": p' )
# A card with no option ids (yes/no, open-ended, batch) has nothing for a condition to change, so its format says null, not an id.
_NO_ID_FORMAT  = _COMMON_FORMAT.replace( '"<an option id> or null"', "null" )
_NO_ID_NOTE    = " This card has no option ids, so modifies_option_id is always null."
_SCALE         = "Every p is a number from 0 to 1. "
_ABSTAIN       = ' If you cannot forecast this card, reply {"abstain": true, "reason": "<why>"} instead.'
YES_NO_FULL_FORMAT = ( 'Reply: {"probabilities": {"yes": p, "no": p, "neither": p}, ' + _NO_ID_FORMAT + "}. " + _SCALE +
                       "The three probabilities add up to 1; the acts are separate chances and need not." + _NO_ID_NOTE + _ABSTAIN )
CHOICE_FULL_FORMAT = ( 'Reply: {"fields": {"<field name>": {"option_ids": ["<option id>"]} or {"write_in": "<text>"} or {"reframe": "<text>"}}, ' +
                       _COMMON_FORMAT + "}. " + _SCALE + "Give option ids exactly as listed in brackets, never labels. "
                       "A field that allows several options takes a list of ids; any other takes one." + _ABSTAIN )
OPEN_FULL_FORMAT   = ( 'Reply: {' + _NO_ID_FORMAT + "}. " + _SCALE + "The gist is the text you expect them to write." + _NO_ID_NOTE + _ABSTAIN )
BATCH_FULL_FORMAT  = ( 'Reply: {"fields": {"<field name>": {"gist": "<the text you expect for that field>"}}, ' + _NO_ID_FORMAT + "}. " + _SCALE + _NO_ID_NOTE.lstrip() + _ABSTAIN )
FULL_FORMATS       = { "yes_no": YES_NO_FULL_FORMAT, "multiple_choice": CHOICE_FULL_FORMAT, "open_ended": OPEN_FULL_FORMAT, "open_ended_batch": BATCH_FULL_FORMAT }


class ReplyRefused( ValueError ):
    """A reply the full-answer parser refuses; reason is one of REFUSAL_REASONS."""

    def __init__( self, reason, detail ):
        """
        Name the refusal.

        Requires:
            - reason is one of REFUSAL_REASONS; detail says what in the reply was wrong

        Ensures:
            - str( error ) is "reason: detail" and error.reason is the reason alone
        """
        super().__init__( f"{reason}: {detail}" )
        self.reason = reason


def full_answer_enabled():
    """
    Say whether the full-answer reply is switched on.

    Ensures:
        - returns True only when the INI key named by SWITCH_KEY is true; an unreadable setting reads as off and never raises
    """
    return read_switch( lambda env_var_name: ConfigurationManager( env_var_name=env_var_name ), SWITCH_KEY, False,
                        lambda settings_error: f"[FULL-ANSWER] ⚠️ Switch '{SWITCH_KEY}' unreadable, treated as off: {settings_error}" )


def stable_option_id( position_id, label ):
    """
    Name an option so its id survives a reordering of the card.

    Requires:
        - position_id is the field's position id ("o1", "o2", ...); label is the option's label or None

    Ensures:
        - returns the position id, a dash and the first six hex digits of the sha-256 of the stripped label
        - the same position and label always give the same id, and a changed label gives a new one
    """
    return f"{position_id}-{hashlib.sha256( str( label ).strip().encode( 'utf-8' ) ).hexdigest()[ :6 ]}"


def option_ids_of( field ):
    """
    List the stable option ids of one episode field, in the card's order.

    Requires:
        - field is one of episode_view's fields

    Ensures:
        - returns one stable_option_id per option
    """
    return [ stable_option_id( option[ "id" ], option[ "label" ] ) for option in field[ "options" ] ]


def _probability( value, where ):
    """
    Read one probability.

    Requires:
        - value is any parsed JSON value; where names it for the message

    Ensures:
        - returns a float from 0 to 1

    Raises:
        - ReplyRefused( probabilities_not_normalised ) when it is not a number from 0 to 1
    """
    if isinstance( value, bool ) or not isinstance( value, ( int, float ) ) or not 0 <= value <= 1:
        raise ReplyRefused( REASON_NOT_NORMALISED, f"{where} must be a number from 0 to 1, got {value!r}" )
    return float( value )


def _object( value, key, where ):
    """
    Take a required object out of a reply.

    Requires:
        - value is a dict; key is the member's name

    Ensures:
        - returns the member when it is a dict

    Raises:
        - ReplyRefused( field_missing ) when it is absent or not an object
    """
    member = value.get( key )
    if not isinstance( member, dict ): raise ReplyRefused( REASON_FIELD_MISSING, f"{where} must be an object" )
    return member


def _text( member, key, where ):
    """
    Take a required non-blank string out of a dict.

    Requires:
        - member is a dict

    Ensures:
        - returns the stripped string

    Raises:
        - ReplyRefused( field_missing ) when it is absent, not a string or blank
    """
    text = member.get( key )
    if not isinstance( text, str ) or not text.strip(): raise ReplyRefused( REASON_FIELD_MISSING, f"{where} must be a non-blank string" )
    return text.strip()


def _named_probabilities( value, key, vocabulary, label ):
    """
    Read one object of probabilities, one for every name in a vocabulary.

    Requires:
        - value is the parsed reply; key is the member's name; vocabulary is the tuple of names it may hold
        - label is the words that precede a name in a message, such as "act"

    Ensures:
        - returns { name: probability } in the vocabulary's order, each a float from 0 to 1; the values need not add up to anything

    Raises:
        - ReplyRefused( field_missing ) if the member is absent or not an object, or leaves a name out
        - ReplyRefused( stance_not_in_vocabulary ) if it holds a name outside the vocabulary
        - ReplyRefused( probabilities_not_normalised ) if a value is not a number from 0 to 1
    """
    given   = _object( value, key, key )
    unknown = [ name for name in given if name not in vocabulary ]
    if unknown: raise ReplyRefused( REASON_STANCE_NOT_IN_VOCAB, f"{unknown} are not among {vocabulary}" )
    absent  = [ name for name in vocabulary if name not in given ]
    if absent: raise ReplyRefused( REASON_FIELD_MISSING, f"{key} leaves out {absent}" )
    return { name: _probability( given[ name ], f"{label} {name}" ) for name in vocabulary }


def _stance_probabilities( value ):
    """
    Read the yes, no and neither probabilities.

    Requires:
        - value is the parsed reply

    Ensures:
        - returns { yes, no, neither } as floats that add up to 1 within NORMALISED_TOLERANCE

    Raises:
        - ReplyRefused( field_missing ) if probabilities or one of the three is absent
        - ReplyRefused( stance_not_in_vocabulary ) if it names a stance other than the three
        - ReplyRefused( probabilities_not_normalised ) if one is not from 0 to 1 or they do not add up to 1
    """
    read    = _named_probabilities( value, "probabilities", STANCES, "probability of" )
    if abs( sum( read.values() ) - 1 ) > NORMALISED_TOLERANCE: raise ReplyRefused( REASON_NOT_NORMALISED, f"the stances add up to {sum( read.values() )}, not 1" )
    return read


def _acts( value ):
    """
    Read the six act marginals.

    Requires:
        - value is the parsed reply

    Ensures:
        - returns { act: probability } for every act in the act vocabulary; the marginals need not add up to 1

    Raises:
        - ReplyRefused( field_missing ) if acts or one act is absent
        - ReplyRefused( stance_not_in_vocabulary ) if it names an act outside the act vocabulary
        - ReplyRefused( probabilities_not_normalised ) if one is not from 0 to 1
    """
    return _named_probabilities( value, "acts", ACTS, "act" )


def _qualification( value, known_ids ):
    """
    Read the chance of a material condition and the conditions asserted.

    Requires:
        - value is the parsed reply; known_ids holds every stable option id on the card, empty for a card with none (yes/no, open-ended, batch)

    Ensures:
        - returns { probability, conditions }, each condition { text, modifies_option_id }, the id None for a condition on the whole answer
          and for every condition on a card with no option ids, whatever id the model wrote

    Raises:
        - ReplyRefused( field_missing ) if qualification, its probability, its conditions list or a condition's text is absent
        - ReplyRefused( probabilities_not_normalised ) if the probability is not from 0 to 1
        - ReplyRefused( unknown_option_id ) if a condition changes an option the card does not have
    """
    given = _object( value, "qualification", "qualification" )
    if "probability" not in given: raise ReplyRefused( REASON_FIELD_MISSING, "qualification leaves out its probability" )
    probability = _probability( given[ "probability" ], "qualification probability" )
    listed      = given.get( "conditions" )
    if not isinstance( listed, list ): raise ReplyRefused( REASON_FIELD_MISSING, "qualification conditions must be a list" )
    conditions  = []
    for condition in listed:
        if not isinstance( condition, dict ): raise ReplyRefused( REASON_FIELD_MISSING, "a condition must be an object" )
        target = condition.get( "modifies_option_id" ) if known_ids else None
        if target is not None and target not in known_ids: raise ReplyRefused( REASON_UNKNOWN_OPTION_ID, f"a condition changes {target!r}, which is not an option of the card" )
        conditions.append( { "text": _text( condition, "text", "a condition's text" ), "modifies_option_id": target } )
    return { "probability": probability, "conditions": conditions }


def _selection( field, given ):
    """
    Read one multiple-choice field's forecast: option ids, a write-in or a re-frame.

    Requires:
        - field is an episode field with options; given is the reply's value for it

    Ensures:
        - returns { "option_ids": [ ids ] } with ids in the field's own set, one for a single-choice field and at least one for a multi
        - or { "write_in": text } or { "reframe": text }

    Raises:
        - ReplyRefused( field_missing ) if given is not an object holding exactly one of the three, or the id list is empty, repeats or is the wrong size for the mode
        - ReplyRefused( unknown_option_id ) if an id is not one of the field's stable ids
    """
    present = [ key for key in SELECTION_KEYS if key in given ] if isinstance( given, dict ) else []
    if len( present ) != 1: raise ReplyRefused( REASON_FIELD_MISSING, f"field {field[ 'key' ]!r} needs exactly one of {SELECTION_KEYS}" )
    key = present[ 0 ]
    if key != "option_ids": return { key: _text( given, key, f"field {field[ 'key' ]!r} {key}" ) }
    ids   = given[ "option_ids" ]
    known = option_ids_of( field )
    if not isinstance( ids, list ): raise ReplyRefused( REASON_FIELD_MISSING, f"field {field[ 'key' ]!r} option_ids must be a list" )
    unknown = [ one for one in ids if one not in known ]
    if unknown: raise ReplyRefused( REASON_UNKNOWN_OPTION_ID, f"field {field[ 'key' ]!r}: {unknown} are not among {known}" )
    if not ids or len( set( ids ) ) != len( ids ) or ( field[ "mode" ] != "multi" and len( ids ) != 1 ):
        raise ReplyRefused( REASON_FIELD_MISSING, f"field {field[ 'key' ]!r} ({field[ 'mode' ]}) cannot take {ids!r}" )
    return { "option_ids": ids }


def _fields( value, episode ):
    """
    Read the per-field part of a multiple-choice or batch reply.

    Requires:
        - value is the parsed reply; episode is episode_view's result of a multiple_choice or open_ended_batch card

    Ensures:
        - a multiple-choice card returns { field key: selection } for every option field, and a field the card leaves as free text is not forecast
        - a batch card returns { field key: { "gist": text } } for every field

    Raises:
        - ReplyRefused( field_missing ) if fields or any card field's entry is absent or unreadable
        - ReplyRefused( unknown_option_id ) as _selection does
    """
    given  = _object( value, "fields", "fields" )
    batch  = episode[ "response_type" ] == "open_ended_batch"
    chosen = {}
    for field in episode[ "fields" ]:
        if field[ "mode" ] == "text" and not batch: continue
        if field[ "key" ] not in given: raise ReplyRefused( REASON_FIELD_MISSING, f"the reply leaves out field {field[ 'key' ]!r}" )
        entry = given[ field[ "key" ] ]
        if batch:
            if not isinstance( entry, dict ): raise ReplyRefused( REASON_FIELD_MISSING, f"field {field[ 'key' ]!r} must be an object holding a gist" )
            chosen[ field[ "key" ] ] = { "gist": _text( entry, "gist", f"field {field[ 'key' ]!r} gist" ) }
        else: chosen[ field[ "key" ] ] = _selection( field, entry )
    if not chosen: raise ReplyRefused( REASON_FIELD_MISSING, "the card has no field to forecast" )
    return chosen


def parse_full_reply( text, episode ):
    """
    Turn a full-answer reply into the forecast record.

    Requires:
        - text is the model's reply; episode is episode_view's result for a card of a type in FULL_ANSWER_TYPES

    Ensures:
        - returns { confidence, acts, qualification, qualifier, gist, whole_card_probability } and, by card type:
          yes_no adds value (the likeliest stance, a tie going to yes, then no, then neither) and probabilities, and its confidence is the probability of value;
          multiple_choice adds fields ( option ids, write-in or re-frame ) and answers ( the labels of the chosen options, for a field with option ids );
          open_ended_batch adds fields ( a gist per field );
          every other type's confidence is whole_card_probability
        - qualifier is the conditions' texts joined by "; ", or None when there are none, as three_way_stance's qualifier is a string or None
        - nothing is written; a refused reply returns nothing

    Raises:
        - ReplyRefused, with the reason that names what is wrong, for every reply it cannot read as a forecast, and for a reply that abstains
    """
    value = recover_json_object( text )
    if not isinstance( value, dict ): raise ReplyRefused( REASON_REPLY_NOT_JSON, "the reply holds no JSON object" )
    if value.get( "abstain" ) is True: raise ReplyRefused( REASON_MODEL_ABSTAINED, str( value.get( "reason" ) or "no reason given" ) )
    kind   = episode[ "response_type" ]
    known  = { one for field in episode[ "fields" ] for one in option_ids_of( field ) }
    record = {}
    if kind == "yes_no":
        probabilities           = _stance_probabilities( value )
        record[ "value" ]       = max( STANCES, key=lambda stance: ( probabilities[ stance ], -STANCES.index( stance ) ) )
        record[ "probabilities" ] = probabilities
    record[ "acts" ]            = _acts( value )
    record[ "qualification" ]   = _qualification( value, known )
    if kind in ( "multiple_choice", "open_ended_batch" ): record[ "fields" ] = _fields( value, episode )
    if kind == "multiple_choice": record[ "answers" ] = _labels_of( episode, record[ "fields" ] )
    record[ "gist" ]                   = _text( value, "gist", "gist" )
    if "whole_card_probability" not in value: raise ReplyRefused( REASON_FIELD_MISSING, "the reply leaves out whole_card_probability" )
    record[ "whole_card_probability" ] = _probability( value[ "whole_card_probability" ], "whole_card_probability" )
    texts                              = [ condition[ "text" ] for condition in record[ "qualification" ][ "conditions" ] ]
    record[ "qualifier" ]              = "; ".join( texts ) if texts else None
    record[ "confidence" ]             = record[ "probabilities" ][ record[ "value" ] ] if kind == "yes_no" else record[ "whole_card_probability" ]
    return record


def _labels_of( episode, chosen ):
    """
    Turn chosen option ids back into the card's labels.

    Requires:
        - episode is episode_view's result; chosen is _fields' result for it

    Ensures:
        - returns { field key: label } for a single-choice field and { field key: [ labels ] } for a multi-select one
        - a field answered by a write-in or a re-frame is left out
    """
    answers = {}
    for field in episode[ "fields" ]:
        pick = chosen.get( field[ "key" ] )
        if pick is None or "option_ids" not in pick: continue
        by_id = dict( zip( option_ids_of( field ), [ option[ "label" ] for option in field[ "options" ] ] ) )
        names = [ by_id[ one ] for one in pick[ "option_ids" ] ]
        answers[ field[ "key" ] ] = names if field[ "mode" ] == "multi" else names[ 0 ]
    return answers
