"""
The item a reviewer is shown: a need with its proposed key, or a pair of definitions.

One format serves the need-set labelling and the duplicate checker's labelling.
"""
from cosa.repo.labelling import errors as er

ITEM_FORMAT = "labelling-item-1"
NEED_KEY    = "need_key"
SEMDUP_PAIR = "semdup_pair"
TYPES       = ( NEED_KEY, SEMDUP_PAIR )
TOP_KEYS    = ( "item_id", "type", "payload" )
ALLOWED     = { NEED_KEY: frozenset( { "need", "key_sources", "nothing_exists", "hits" } ), SEMDUP_PAIR: frozenset( { "a", "b" } ) }


def _fail( item, why ):
    """Raises: LabellingError BAD_ITEM naming the item and the reason."""
    name = item.get( "item_id", "?" ) if isinstance( item, dict ) else "?"
    raise er.LabellingError( er.BAD_ITEM, f"{name}: {why}" )


def _text( value ):
    """Ensures: returns True for a non-empty string."""
    return isinstance( value, str ) and value.strip() != ""


def validate_item( item ):
    """
    Check one item against the labelling-item-1 format.

    Requires:
        - item is any object

    Ensures:
        - returns None when valid
        - a need_key item holds a need and either a non-empty list of key sources or nothing_exists true with up to ten hits
        - a semdup_pair item holds two definitions, a and b
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
    if item[ "type" ] == SEMDUP_PAIR:
        if not ( _text( p.get( "a" ) ) and _text( p.get( "b" ) ) ): _fail( item, "a semdup_pair needs two definitions, a and b" )
        return
    if not _text( p.get( "need" ) ): _fail( item, "a need_key item needs the need text" )
    sources = p.get( "key_sources" )
    if p.get( "nothing_exists" ) is True:
        if sources is not None: _fail( item, "a nothing-exists item has no key sources" )
        hits = p.get( "hits" )
        if not isinstance( hits, list ) or len( hits ) > 10 or not all( _text( h ) for h in hits ): _fail( item, "a nothing-exists item needs a list of up to ten hit lines" )
    else:
        if not isinstance( sources, list ) or not sources or not all( _text( s ) for s in sources ): _fail( item, "a matched item needs a non-empty list of key sources" )
        if "hits" in p or "nothing_exists" in p: _fail( item, "a matched item has no hits and no nothing_exists" )


def make_item( kind, id, payload ):
    """
    Build and validate an item.

    Requires:
        - kind is need_key or semdup_pair; payload is the dict that kind needs

    Ensures:
        - returns { item_id, type, payload }

    Raises:
        - LabellingError BAD_ITEM when the item is invalid
    """
    item = { "item_id": id, "type": kind, "payload": payload }
    validate_item( item )
    return item
