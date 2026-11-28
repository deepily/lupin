"""
Rick's offline labelling page: his blind share of cards and a one-file HTML page.

The page embeds its items as JSON and needs no network. It shows no forecast, no reader label and nothing outside
the list it was built from. rick_export reads his answers back.
"""
import argparse
import hashlib
import json
import os
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
DRAW_SECTION      = "blind share"
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
CARD_TYPE_LABELS  = {   # the card types item-card-types.json holds, as Rick reads them
    "yes_no"          : "Yes / No / Neither",
    "multiple_choice" : "Multiple choice",
    "open_ended"      : "Open-ended",
    "open_ended_batch": "Batch (open-ended)",
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


def merge_sections( sections ):
    """
    Put the sections in one order and drop an item that an earlier section already holds.

    Requires:
        - sections is a dict from a section name to a list of item ids; a name is non-empty text

    Ensures:
        - returns ( kept, dropped ): kept maps each name to its ids, sorted, without those of an earlier section; dropped lists the removed ids, sorted
        - the sections keep the order they came in

    Raises:
        - LabellingError BAD_ITEM for a blank name or an id repeated inside one section
    """
    kept, dropped, seen = {}, [], set()
    for name, ids in sections.items():
        if not name.strip() or len( set( ids ) ) != len( ids ): raise er.LabellingError( er.BAD_ITEM, f"section {name!r}: needs a name and distinct item ids" )
        kept[ name ] = sorted( i for i in ids if i not in seen )
        dropped += [ i for i in ids if i in seen ]
        seen |= set( ids )
    return kept, sorted( dropped )


def questions_of( packet ):
    """
    Name the one question each item of a multi-question card labels.

    A multiple-choice or batch card gives one item per answered question. Each item's card text is the card's shared
    text followed by that question's own wording. The page shows one of those items. Without a name, the reader sees
    every question of the card above a single answer and cannot tell which one it answers.

    Requires:
        - packet is { blind, disputes, refs }, refs mapping an item id to { notification_id, field_key }

    Ensures:
        - returns { item_id: question } for every item whose card has two or more items in the packet
        - question is { header, prompt, answered }: header is the item's field_key, answered the card's item count, and
          prompt the item's card text after the longest prefix its card's texts share, cut back to a line start, or None
          when that remainder is blank
        - an item with no ref, or the only item of its card, has no entry
        - only notification_id and field_key are read from a ref, and only the header reaches the page
    """
    refs, cards = packet[ "refs" ], {}
    for item in packet[ "blind" ] + packet[ "disputes" ]:
        ref = refs.get( item[ "item_id" ] )
        if ref is not None: cards.setdefault( ref[ "notification_id" ], [] ).append( item )
    out = {}
    for group in cards.values():
        if len( group ) < 2: continue
        texts  = [ i[ "payload" ][ "card_text" ] for i in group ]
        shared = os.path.commonprefix( texts )
        shared = shared[ :shared.rfind( "\n" ) + 1 ]
        for item in group:
            prompt = item[ "payload" ][ "card_text" ][ len( shared ): ].strip()
            out[ item[ "item_id" ] ] = { "header": refs[ item[ "item_id" ] ][ "field_key" ], "prompt": prompt or None, "answered": len( group ) }
    return out


def page_items( packet, sections, card_types ):
    """
    Turn the sections of item ids into what the page embeds.

    Requires:
        - packet is { blind, disputes, refs }; sections is merge_sections' kept dict, with at least one id in all, each id in blind or disputes
        - card_types is a dict from item id to a key of CARD_TYPE_LABELS, as item-card-types.json holds it, with an entry for every id

    Ensures:
        - returns one dict per id, the first section first and each section in sorted order: item_id, section, card_type (the label Rick reads), card_text, options, recommendation, answer, stance_class, question and relations ( label, meaning )
        - question is questions_of's entry for an item of a multi-question card, else None
        - nothing else rides along: each item passes blind_form, which refuses a forecast, a label or any other field, and from the refs only what questions_of reads is used

    Raises:
        - LabellingError BAD_ITEM for no ids, an id the packet does not hold, or an id with no card type or one that is not a key of CARD_TYPE_LABELS
        - LabellingError PACKET_LEAK from blind_form
    """
    ids = [ i for group in sections.values() for i in group ]
    if not ids: raise er.LabellingError( er.BAD_ITEM, "the page needs at least one item id" )
    known  = { i[ "item_id" ]: i for i in packet[ "blind" ] + packet[ "disputes" ] }
    absent = sorted( set( ids ) - set( known ) )
    if absent: raise er.LabellingError( er.BAD_ITEM, f"item ids the packet does not hold: {absent[ :5 ]}" )
    untyped = sorted( i for i in ids if card_types.get( i ) not in CARD_TYPE_LABELS )
    if untyped: raise er.LabellingError( er.BAD_ITEM, f"item ids with no known card type: {untyped[ :5 ]}" )
    out       = []
    questions = questions_of( packet )
    for name, group in sections.items():
        for item_id in group:
            item = pk.blind_form( known[ item_id ] )
            out.append( { "item_id": item_id, "section": name, "card_type": CARD_TYPE_LABELS[ card_types[ item_id ] ], **item[ "payload" ], "question": questions.get( item_id ),
                          "relations": [ { "label": l, "meaning": MEANINGS[ l ] } for l in relations_for( item ) ] } )
    return out


def read_ids( path ):
    """
    Read a list of item ids from a file.

    Ensures:
        - returns the ids of a JSON list of text, or else of the whitespace-separated words of the file
    """
    text = pathlib.Path( path ).read_text( encoding="utf-8" )
    try:
        data = json.loads( text )
    except ValueError:
        return text.split()
    return data if isinstance( data, list ) else text.split()


def embed_json( value ):
    """Ensures: returns ASCII JSON text, with < > and & escaped, safe inside a script element."""
    return json.dumps( value, ensure_ascii=True, sort_keys=True ).replace( "<", "\\u003c" ).replace( ">", "\\u003e" ).replace( "&", "\\u0026" )


def fill_page( template_relative, items, title, ids, extra=None ):
    """
    Fill a one-file page template with a title, a page id and the embedded items.

    Requires:
        - template_relative is a path under the project root, starting /src/; title is non-empty text
        - items is a non-empty list the template reads; ids names its entries; extra maps further placeholders to their text

    Ensures:
        - __TITLE__ holds the title as escaped text, and __PAGE_ID__ the id page_id gives for ids
        - each placeholder of extra is filled, and __ITEMS_JSON__ last, so item text that quotes a placeholder reaches the page unchanged

    Raises:
        - LabellingError BAD_ITEM for no items or a blank title
        - OSError when the template cannot be read
    """
    if not items or not title.strip(): raise er.LabellingError( er.BAD_ITEM, "a page needs items and a title" )
    page = pathlib.Path( cu.get_project_root() + template_relative ).read_text( encoding="utf-8" )
    safe = title.replace( "&", "&amp;" ).replace( "<", "&lt;" ).replace( ">", "&gt;" )
    page = page.replace( "__TITLE__", safe ).replace( "__PAGE_ID__", page_id( ids ) )
    for placeholder, text in ( extra or {} ).items(): page = page.replace( placeholder, text )
    return page.replace( "__ITEMS_JSON__", embed_json( items ) )


def render_page( items, title ):
    """
    Build the one-file page.

    Requires:
        - items is page_items' result; title is non-empty text

    Ensures:
        - returns the HTML text of a page with the items embedded and no reference to any outside script, style, font or address
        - the title is written as escaped text; the page id is the one page_id gives for the item ids
        - the page's grouped view orders card types as CARD_TYPE_LABELS does
        - the items are embedded last, so card text that quotes a placeholder reaches the page unchanged

    Raises:
        - LabellingError BAD_ITEM for no items or a blank title
    """
    return fill_page( TEMPLATE_RELATIVE, items, title, [ i.get( "item_id" ) for i in items ], { "__TYPE_ORDER_JSON__": embed_json( list( CARD_TYPE_LABELS.values() ) ) } )


def main( argv=None ):
    """
    Build Rick's page from the draw and from lists of item ids.

    Requires:
        - argv is --packet with a file, then --draw with a seed and/or --section name=file (one or more; the file holds a JSON list or ids separated by space), with optional --out, --title, --share, --card-types (a JSON dict from item id to card type; default io/gold-labels/item-card-types.json), --receipt-only

    Ensures:
        - the draw, when given, is the first section, named "blind share"; the sections follow in the order given, and an id already in an earlier section is dropped from a later one
        - prints the receipt as sorted-key json: the draw (seed, card ids, item ids, sha256), each section's count, the dropped ids, the page id and the item count
        - unless --receipt-only, writes the page to --out, all item ids to <out>.ids.txt and the sections to <out>.sections.json, and adds the page's sha256 to the receipt; returns 0
        - returns 2, writing nothing, when the packet or an ids file cannot be read, the ids are not valid, the card types file cannot be read or lacks an id, or an output file exists
    """
    ap = argparse.ArgumentParser( description="Build Rick's offline labelling page." )
    ap.add_argument( "--packet", required=True )
    ap.add_argument( "--draw", metavar="SEED" )
    ap.add_argument( "--section", action="append", default=[], metavar="NAME=FILE" )
    ap.add_argument( "--card-types", default=cu.get_project_root() + "/io/gold-labels/item-card-types.json" )
    ap.add_argument( "--share", type=float, default=cf.BLIND_SHARE )
    ap.add_argument( "--out", default=cu.get_project_root() + "/io/gold-labels/rick-blind-share.html" )
    ap.add_argument( "--title", default="Rick's gold labels" )
    ap.add_argument( "--receipt-only", action="store_true" )
    args = ap.parse_args( argv )
    try:
        packet   = json.loads( pathlib.Path( args.packet ).read_text( encoding="utf-8" ) )
        receipt  = draw_share( packet, args.draw, args.share ) if args.draw is not None else {}
        sections = { DRAW_SECTION: receipt[ "item_ids" ] } if args.draw is not None else {}
        for spec in args.section:
            name, _, path = spec.partition( "=" )
            sections[ name ] = read_ids( path )
        kept, dropped = merge_sections( sections )
        card_types    = json.loads( pathlib.Path( args.card_types ).read_text( encoding="utf-8" ) )
        items         = page_items( packet, kept, card_types )
        html          = render_page( items, args.title )
    except ( OSError, ValueError, KeyError, TypeError, AttributeError, er.LabellingError ) as e:
        return er.fail( f"cannot build the page: {e!r}", 2 )
    ids = [ i[ "item_id" ] for i in items ]
    receipt.update( { "page_id": page_id( ids ), "items": len( items ), "sections": { n: len( g ) for n, g in kept.items() }, "dropped_as_already_listed": dropped } )
    out, ids_path, sec_path = pathlib.Path( args.out ), pathlib.Path( args.out + ".ids.txt" ), pathlib.Path( args.out + ".sections.json" )
    if not args.receipt_only:
        if any( f.exists() for f in ( out, ids_path, sec_path ) ): return er.fail( f"refused: {out} or a file beside it exists, and a page is never overwritten", 2 )
        out.write_text( html, encoding="utf-8" )
        ids_path.write_text( "".join( f"{i}\n" for i in sorted( ids ) ), encoding="utf-8" )
        sec_path.write_text( json.dumps( kept, indent=1 ) + "\n", encoding="utf-8" )
        receipt[ "page_sha256" ] = hashlib.sha256( html.encode( "utf-8" ) ).hexdigest()
    print( json.dumps( receipt, indent=1, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit( main() )
