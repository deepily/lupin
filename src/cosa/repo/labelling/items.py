"""
The item a reviewer is shown: a need with its proposed key, or a pair of definitions.

One format serves the need-set labelling and the duplicate checker's labelling.
"""
from cosa.repo.labelling import errors as er

ITEM_FORMAT    = "labelling-item-1"
NEED_KEY       = "need_key"
DUPLICATE_PAIR = "semdup_pair"   # the value stays: packets already written carry it
ANSWER_CARD    = "answer_meaning_card"
TYPES          = ( NEED_KEY, DUPLICATE_PAIR, ANSWER_CARD )
STANCE_CLASSES = ( "yes", "no", "neither", "none" )   # none: a card with no stance, such as multiple choice or open-ended
TOP_KEYS       = ( "item_id", "type", "payload" )
MAX_CALL_SITES = 5
ALLOWED     = { NEED_KEY: frozenset( { "need", "key_sources", "nothing_exists", "hits", "call_sites" } ), DUPLICATE_PAIR: frozenset( { "a", "b" } ), ANSWER_CARD: frozenset( { "card_text", "options", "recommendation", "answer", "stance_class" } ) }


def _fail( item, why ):
    """Raises: LabellingError BAD_ITEM naming the item and the reason."""
    name = item.get( "item_id", "?" ) if isinstance( item, dict ) else "?"
    raise er.LabellingError( er.BAD_ITEM, f"{name}: {why}" )


def _text( value ):
    """Ensures: returns True for a non-empty string."""
    return isinstance( value, str ) and value.strip() != ""


def _check_answer_card( item, p ):
    """
    Check the payload of an answer_meaning_card item.

    Ensures:
        - returns None when the payload holds card_text and answer as non-empty text, options as a list of non-empty text,
          recommendation as None or non-empty text, and stance_class as one of STANCE_CLASSES
        - fields beyond these are left for blind_form to refuse as PACKET_LEAK, so a forecast or a label never rides along

    Raises:
        - LabellingError BAD_ITEM naming the first violation
    """
    for k in ( "card_text", "answer" ):
        if not _text( p.get( k ) ): _fail( item, f"an answer_meaning_card needs {k} as non-empty text" )
    options = p.get( "options" )
    if not isinstance( options, list ) or not all( _text( o ) for o in options ): _fail( item, "options must be a list of non-empty lines, empty when the card has none" )
    rec = p.get( "recommendation" )
    if "recommendation" not in p or ( rec is not None and not _text( rec ) ): _fail( item, "recommendation must be present, as None or non-empty text" )
    if p.get( "stance_class" ) not in STANCE_CLASSES: _fail( item, f"stance_class must be one of {STANCE_CLASSES}" )


def validate_item( item ):
    """
    Check one item against the labelling-item-1 format.

    Requires:
        - item is any object

    Ensures:
        - returns None when valid
        - a need_key item holds a need and either a non-empty list of key sources or nothing_exists true with up to ten hits
        - a matched need_key item may also hold call_sites, a list of up to five non-empty lines; a nothing-exists item may not
        - a semdup_pair item holds two definitions, a and b
        - an answer_meaning_card item holds the card text, options, recommendation, answer and stance class (see _check_answer_card)
        - extra payload fields are left for export_packets to refuse

    Raises:
        - LabellingError BAD_ITEM naming the first violation
    """
    if not isinstance( item, dict ): _fail( item, "not a dict" )
    for k in TOP_KEYS:
        if k not in item: _fail( item, f"missing key {k!r}" )
    if not _text( item[ "item_id" ] ): _fail( item, "item_id must be a non-empty string" )
    if item[ "type" ] not in TYPES: _fail( item, f"unknown type {item[ 'type' ]!r}" )
    p = item[ "payload" ]
    if not isinstance( p, dict ): _fail( item, "payload must be a dict" )
    if item[ "type" ] == ANSWER_CARD:
        _check_answer_card( item, p )
        return
    if item[ "type" ] == DUPLICATE_PAIR:
        if not ( _text( p.get( "a" ) ) and _text( p.get( "b" ) ) ): _fail( item, "a semdup_pair needs two definitions, a and b" )
        return
    if not _text( p.get( "need" ) ): _fail( item, "a need_key item needs the need text" )
    sources = p.get( "key_sources" )
    if p.get( "nothing_exists" ) is True:
        if sources is not None: _fail( item, "a nothing-exists item has no key sources" )
        hits = p.get( "hits" )
        if not isinstance( hits, list ) or len( hits ) > 10 or not all( _text( h ) for h in hits ): _fail( item, "a nothing-exists item needs a list of up to ten hit lines" )
        if "call_sites" in p: _fail( item, "a nothing-exists item has no call sites" )
    else:
        if not isinstance( sources, list ) or not sources or not all( _text( s ) for s in sources ): _fail( item, "a matched item needs a non-empty list of key sources" )
        if "hits" in p or "nothing_exists" in p: _fail( item, "a matched item has no hits and no nothing_exists" )
        sites = p.get( "call_sites", [] )
        if not isinstance( sites, list ) or len( sites ) > MAX_CALL_SITES or not all( _text( c ) for c in sites ): _fail( item, "call_sites must be a list of up to five non-empty lines" )


def make_item( kind, id, payload ):
    """
    Build and validate an item.

    Requires:
        - kind is one of the item types; payload is the dict that kind needs

    Ensures:
        - returns { item_id, type, payload }

    Raises:
        - LabellingError BAD_ITEM when the item is invalid
    """
    item = { "item_id": id, "type": kind, "payload": payload }
    validate_item( item )
    return item
