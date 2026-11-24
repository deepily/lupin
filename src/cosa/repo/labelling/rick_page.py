"""
Rick's offline labelling page: his blind share of cards and a one-file HTML page.

The page embeds its items as JSON and needs no network. It shows no forecast, no reader label and nothing outside
the list it was built from. rick_export reads his answers back.
"""
import argparse
import hashlib
import json
import pathlib
import random
import sys

from cosa.repo.labelling import confirm as cf
from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it
from cosa.repo.labelling import packets as pk
import cosa.utils.util as cu

TEMPLATE_RELATIVE = "/src/cosa/repo/labelling/rick-page-template.html"
KIND_STANCE       = "stance"
KIND_CHOICE       = "choice"
KIND_OPEN         = "open"
STANCE_WORDS      = ( "yes", "no", "neither" )
MEANINGS          = {   # one line each, from plan section 3 and 3b
    "support"                      : "The comment backs the stance or adds a condition, without changing the action.",
    "dissent"                      : "The comment contradicts or reverses the stance, or objects to part of it.",
    "re_frame"                     : "Rejects the question's premise, or asks something else.",
    "no_comment"                   : "The stance alone, with no comment.",
    "agrees"                       : "Picks the recommended option and adds nothing material.",
    "expands_recommendation"       : "Picks the recommended option and adds a condition or detail.",
    "expands_other_option"         : "Picks another listed option and adds a condition.",
    "chose_different_listed_option": "Picks a listed option that is not the recommended one, with no comment.",
    "wrote_own_answer"             : "A typed answer that is tied to no listed option.",
    "no_recommendation_on_card"    : "The card offered no recommendation.",
    "no_answer"                    : "Blank text.",
    "answers"                      : "The text answers what was asked.",
    "declines_or_defers"           : "Refuses, or puts it off.",
}
RELATIONS = {
    KIND_STANCE : ( "support", "dissent", "re_frame", "no_comment" ),
    KIND_CHOICE : ( "agrees", "expands_recommendation", "expands_other_option", "chose_different_listed_option", "wrote_own_answer", "no_recommendation_on_card" ),
    KIND_OPEN   : ( "no_answer", "answers", "declines_or_defers", "re_frame" ),
}


def kind_of( item ):
    """
    Say which kind of card an answer item came from.

    Requires:
        - item is a valid answer_meaning_card item

    Ensures:
        - returns "stance" for a yes, no or neither stance class, "choice" for an item that lists options, "open" for the rest
        - an open-ended or batch-header item and a yes/no card whose answer holds no stance word look alike, and both read as "open"
    """
    p = item[ "payload" ]
    if p[ "stance_class" ] in STANCE_WORDS: return KIND_STANCE
    return KIND_CHOICE if p[ "options" ] else KIND_OPEN


def relations_for( item ):
    """
    List the relations that are valid for one item, in the order the page shows them.

    Requires:
        - item is a valid answer_meaning_card item

    Ensures:
        - returns the labels of its kind; a choice item whose card made no recommendation has no_recommendation_on_card, and one that did has not
        - the three that need a recommendation to compare against are left off a card without one
    """
    labels = RELATIONS[ kind_of( item ) ]
    p      = item[ "payload" ]
    if kind_of( item ) != KIND_CHOICE: return list( labels )
    if p[ "recommendation" ] is None: return [ l for l in labels if l not in ( "agrees", "expands_recommendation", "expands_other_option" ) ]
    return [ l for l in labels if l != "no_recommendation_on_card" ]


def ids_sha256( item_ids ):
    """Ensures: returns the sha256 of the sorted ids joined by newline, with no trailing newline."""
    return hashlib.sha256( "\n".join( sorted( item_ids ) ).encode( "utf-8" ) ).hexdigest()


def page_id( item_ids ):
    """Ensures: returns the first 12 characters of ids_sha256, naming one page."""
    return ids_sha256( item_ids )[ :12 ]


def draw_share( packet, seed, share=cf.BLIND_SHARE ):
    """
    Draw Rick's blind share: a share of the cards, one seeded field from each.

    Requires:
        - packet is { blind, refs } as build_answer_card_sample writes it, every item having a ref with a notification_id
        - seed is non-empty text; share is above 0 and below 1

    Ensures:
        - cards are the distinct notification ids of the packet's items; confirm.blind_sample_ids draws the share of them
        - from each drawn card with more than one item, one item is picked by a draw seeded with the seed and the card id
        - returns { seed, share, cards_total, card_ids, item_ids, item_ids_sha256 }, both id lists sorted
        - the same packet and seed give the same share whatever the order of the items

    Raises:
        - LabellingError BAD_ITEM when the packet holds no items or an item has no ref
    """
    by_card = {}
    for item in packet[ "blind" ]:
        ref = packet[ "refs" ].get( item[ "item_id" ] )
        if ref is None: raise er.LabellingError( er.BAD_ITEM, f"{item[ 'item_id' ]}: no ref in the packet" )
        by_card.setdefault( ref[ "notification_id" ], [] ).append( item[ "item_id" ] )
    if not by_card: raise er.LabellingError( er.BAD_ITEM, "the packet holds no items" )
    cards = cf.blind_sample_ids( list( by_card ), seed, share )
    items = sorted( random.Random( f"{seed}|field|{c}" ).choice( sorted( by_card[ c ] ) ) for c in cards )
    return { "seed": seed, "share": share, "cards_total": len( by_card ), "card_ids": cards, "item_ids": items, "item_ids_sha256": ids_sha256( items ) }


def page_items( packet, item_ids ):
    """
    Turn a list of item ids into what the page embeds.

    Requires:
        - packet is { blind, disputes, refs }; item_ids is a non-empty list of distinct ids of items in blind or disputes

    Ensures:
        - returns one dict per id, in sorted order: item_id, card_text, options, recommendation, answer, stance_class and relations ( label, meaning )
        - nothing else rides along: each item passes blind_form, which refuses a forecast, a label or any other field, and the refs are never read

    Raises:
        - LabellingError BAD_ITEM for no ids, a repeated id or an id the packet does not hold
        - LabellingError PACKET_LEAK from blind_form
    """
    if not item_ids or len( set( item_ids ) ) != len( item_ids ): raise er.LabellingError( er.BAD_ITEM, "the page needs a non-empty list of distinct item ids" )
    known  = { i[ "item_id" ]: i for i in packet[ "blind" ] + packet[ "disputes" ] }
    absent = sorted( set( item_ids ) - set( known ) )
    if absent: raise er.LabellingError( er.BAD_ITEM, f"item ids the packet does not hold: {absent[ :5 ]}" )
    out = []
    for item_id in sorted( item_ids ):
        item = pk.blind_form( known[ item_id ] )
        out.append( { "item_id": item_id, **item[ "payload" ], "relations": [ { "label": l, "meaning": MEANINGS[ l ] } for l in relations_for( item ) ] } )
    return out


def embed_json( value ):
    """Ensures: returns ASCII JSON text, with < > and & escaped, safe inside a script element."""
    return json.dumps( value, ensure_ascii=True, sort_keys=True ).replace( "<", "\\u003c" ).replace( ">", "\\u003e" ).replace( "&", "\\u0026" )


def render_page( items, title ):
    """
    Build the one-file page.

    Requires:
        - items is page_items' result; title is non-empty text

    Ensures:
        - returns the HTML text of a page with the items embedded and no reference to any outside script, style, font or address
        - the title is written as escaped text; the page id is the one page_id gives for the item ids

    Raises:
        - LabellingError BAD_ITEM for no items or a blank title
    """
    if not items or not title.strip(): raise er.LabellingError( er.BAD_ITEM, "a page needs items and a title" )
    template = pathlib.Path( cu.get_project_root() + TEMPLATE_RELATIVE ).read_text( encoding="utf-8" )
    safe     = title.replace( "&", "&amp;" ).replace( "<", "&lt;" ).replace( ">", "&gt;" )
    ids      = [ i[ "item_id" ] for i in items ]
    return template.replace( "__TITLE__", safe ).replace( "__PAGE_ID__", page_id( ids ) ).replace( "__ITEMS_JSON__", embed_json( items ) )


def _fail( message, code ):
    """Ensures: prints the message to stderr and returns the exit code."""
    print( message, file=sys.stderr )
    return code


def main( argv=None ):
    """
    Build Rick's page from the draw or from a list of item ids.

    Requires:
        - argv is --packet FILE, then one of --draw SEED or --ids FILE (one id per line), with optional --out, --title, --share and --receipt-only

    Ensures:
        - prints the receipt as sorted-key json: for a draw, its seed, card ids, item ids and the sha256 of the sorted item ids; always the page id and item count
        - unless --receipt-only, writes the page to --out and the sorted ids beside it as <out>.ids.txt, and adds the page's sha256 to the receipt; returns 0
        - returns 2, writing nothing, when the packet or ids cannot be read, the ids are not valid, or either output file exists
    """
    ap = argparse.ArgumentParser( description="Build Rick's offline labelling page." )
    ap.add_argument( "--packet", required=True )
    src = ap.add_mutually_exclusive_group( required=True )
    src.add_argument( "--draw", metavar="SEED" )
    src.add_argument( "--ids", metavar="FILE" )
    ap.add_argument( "--share", type=float, default=cf.BLIND_SHARE )
    ap.add_argument( "--out", default=cu.get_project_root() + "/io/gold-labels/rick-blind-share.html" )
    ap.add_argument( "--title", default="Rick's gold labels" )
    ap.add_argument( "--receipt-only", action="store_true" )
    args = ap.parse_args( argv )
    try:
        packet  = json.loads( pathlib.Path( args.packet ).read_text( encoding="utf-8" ) )
        receipt = draw_share( packet, args.draw, args.share ) if args.draw is not None else {}
        ids     = receipt[ "item_ids" ] if args.draw is not None else pathlib.Path( args.ids ).read_text( encoding="utf-8" ).split()
        items   = page_items( packet, ids )
        html    = render_page( items, args.title )
    except ( OSError, ValueError, KeyError, TypeError, er.LabellingError ) as e:
        return _fail( f"cannot build the page: {e!r}", 2 )
    receipt.update( { "page_id": page_id( ids ), "items": len( items ) } )
    out, ids_path = pathlib.Path( args.out ), pathlib.Path( args.out + ".ids.txt" )
    if not args.receipt_only:
        if out.exists() or ids_path.exists(): return _fail( f"refused: {out} or {ids_path} exists, and a page is never overwritten", 2 )
        out.write_text( html, encoding="utf-8" )
        ids_path.write_text( "".join( f"{i}\n" for i in sorted( ids ) ), encoding="utf-8" )
        receipt[ "page_sha256" ] = hashlib.sha256( html.encode( "utf-8" ) ).hexdigest()
    print( json.dumps( receipt, indent=1, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit( main() )
