"""
The voice-card bridge: batches out to Rick, spoken answers back as labels.

Code cannot call the voice tools. This module builds what a seat passes to ask_open_ended_batch and to task_create, and reads
back what ask_open_ended_batch returns. The plan is 2026.11.24-meaning-labeller-plan.md.
"""
import argparse
import hashlib
import json
import pathlib
import random
import re
import sys
from datetime import datetime, timedelta, timezone

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import gold_store as gs
from cosa.repo.labelling import items as it
from cosa.repo.labelling import packets as pk
from cosa.utils.notification_utils import format_open_ended_batch_for_tts

BATCH_SIZE      = 20
KIND_BLIND      = "blind"
KIND_DISPUTE    = "dispute"
CORRELATION_KEY = "epic:answer-signal-pipeline"
MIN_ID_LENGTH   = 4
MAX_SPOKEN      = 400
CHASE_DAYS      = 1
ALIASES         = {   # what Rick may say, normalised, for the relations whose name is not how a person says it
    "expands on the recommendation" : "expands_recommendation",
    "expands on the other option"   : "expands_other_option",
    "expands on another option"     : "expands_other_option",
    "chose a different option"      : "chose_different_listed_option",
    "chose a different listed option": "chose_different_listed_option",
    "wrote his own answer"          : "wrote_own_answer",
    "wrote their own answer"        : "wrote_own_answer",
    "reframe"                       : "re_frame",
    "no recommendation"             : "no_recommendation_on_card",
    "declines"                      : "declines_or_defers",
    "defers"                        : "declines_or_defers",
}


def _normal( text ):
    """
    Normalise a spoken phrase for matching.

    Ensures:
        - returns the text lowercased, with _ and - read as spaces, other punctuation dropped and runs of space collapsed
    """
    return " ".join( re.sub( r"[^a-z0-9 ]", "", text.lower().replace( "_", " " ).replace( "-", " " ) ).split() )


SPOKEN = { **{ _normal( label ): label for label in pk.ANSWER_LABELS }, **ALIASES }


def short_ids( item_ids ):
    """
    Give each item of one batch a short id, the header its answer comes back under.

    Requires:
        - item_ids are distinct strings

    Ensures:
        - returns { item_id: short id } where a short id is a prefix of the item id's sha256 hex digest
        - the prefixes are as short as they can be, but at least MIN_ID_LENGTH, while still all different
    """
    n = MIN_ID_LENGTH
    digests = { i: hashlib.sha256( i.encode( "utf-8" ) ).hexdigest() for i in item_ids }
    while len( { d[ :n ] for d in digests.values() } ) < len( digests ): n += 1
    return { i: d[ :n ] for i, d in digests.items() }


def batch_id( name, seed, index ):
    """
    Name one batch.

    Ensures:
        - returns the first 12 hex characters of a sha256 over the packet's name, the seed and the batch's index
    """
    return hashlib.sha256( f"{name}|{seed}|{index}".encode( "utf-8" ) ).hexdigest()[ :12 ]


def _card_lines( item, header ):
    """
    Write one card's lines of the batch abstract.

    Ensures:
        - returns markdown lines; only the fields an answer_meaning_card may hold are read
    """
    p = item[ "payload" ]
    lines = [ f"**{header}** ({p[ 'stance_class' ]}): {p[ 'card_text' ]}" ]
    if p[ "options" ]: lines.append( "  - options: " + "; ".join( p[ "options" ] ) )
    lines.append( f"  - recommended: {p[ 'recommendation' ]}" if p[ "recommendation" ] is not None else "  - recommended: none" )
    lines.append( f"  - answer: {p[ 'answer' ]}" )
    return lines


def _make_batch( name, seed, index, total, kind, cards, chase ):
    """
    Build one batch: the arguments of ask_open_ended_batch and the spec of the store row.

    Requires:
        - cards are valid answer_meaning_card items in their blind form, 1 to BATCH_SIZE of them, with distinct ids
        - chase is an aware datetime

    Raises:
        - LabellingError BAD_ITEM when the spoken text is MAX_SPOKEN characters or more
    """
    ids       = short_ids( [ c[ "item_id" ] for c in cards ] )
    questions = [ { "header": ids[ c[ "item_id" ] ], "question": f"Card {ids[ c[ 'item_id' ] ]}: how does the answer relate to the card?" } for c in cards ]
    spoken    = format_open_ended_batch_for_tts( questions )
    if len( spoken ) >= MAX_SPOKEN: raise er.LabellingError( er.BAD_ITEM, f"batch {index}: the spoken text is {len( spoken )} characters" )
    abstract  = "\n".join(
        [ f"Say one word or phrase per card, from: {', '.join( pk.ANSWER_LABELS )}.", "" ] + [ line for c in cards for line in _card_lines( c, ids[ c[ 'item_id' ] ] ) ] )
    bid = batch_id( name, seed, index )
    return {
        "batch_id"  : bid,
        "kind"      : kind,
        "index"     : index,
        "item_ids"  : [ c[ "item_id" ] for c in cards ],
        "headers"   : { ids[ c[ "item_id" ] ]: c[ "item_id" ] for c in cards },
        "questions" : questions,
        "spoken"    : spoken,
        "abstract"  : abstract,
        "row_spec"  : {
            "title"           : f"[LUPIN] Label voice batch {index + 1} of {total} ({kind}, {len( cards )} cards) for the meaning labeller's gold set, batch {bid}",
            "correlation_key" : CORRELATION_KEY,
            "next_chase_ts"   : chase.isoformat(),
            "batch_id"        : bid,
        },
    }


def voice_batches( packet, seed, chase_start, size=BATCH_SIZE, chase_days=CHASE_DAYS ):
    """
    Split a gold-label packet into batches of voice cards.

    Requires:
        - packet is { "name": str, "blind": [items], "disputes": [items] }: Rick's blind share (blind_sample_ids, plain random) and the items the two readers disagreed on
        - every item is an answer_meaning_card; ids are distinct across both lists
        - chase_start is an ISO-8601 time, with or without a zone (none means UTC); size is a positive integer; chase_days is a non-negative integer

    Ensures:
        - returns the batches, the blind ones first, in a seeded order that does not depend on the order the items arrive in
        - every batch holds size items except the last of each kind; no item is in two batches
        - a batch mixes no blind item with a dispute item
        - an item's fields beyond the answer_meaning_card payload (a forecast, a reader label, a labeller label) are refused, not passed on
        - batch i is chased chase_days * i days after chase_start
        - the same packet, seed and chase_start always give the same batches and ids

    Raises:
        - LabellingError BAD_ITEM for a wrong item type, a repeated id, a bad size or time, or a spoken text of 400 characters or more
        - LabellingError PACKET_LEAK for a field a reviewer may not see
    """
    if not isinstance( size, int ) or isinstance( size, bool ) or size < 1: raise er.LabellingError( er.BAD_ITEM, f"size must be a positive integer, got {size!r}" )
    start = pk.moment( chase_start )
    if start is None: raise er.LabellingError( er.BAD_ITEM, f"chase_start is not an ISO-8601 time: {chase_start!r}" )
    groups = []
    for kind, key in ( ( KIND_BLIND, "blind" ), ( KIND_DISPUTE, "disputes" ) ):
        clean = [ pk.blind_form( i ) for i in packet[ key ] ]
        for i in clean:
            if i[ "type" ] != it.ANSWER_CARD: raise er.LabellingError( er.BAD_ITEM, f"{i[ 'item_id' ]}: a voice batch holds answer_meaning_card items only" )
        groups.append( ( kind, sorted( clean, key=lambda i: i[ "item_id" ] ) ) )
    every = [ i[ "item_id" ] for _, cards in groups for i in cards ]
    if len( set( every ) ) != len( every ): raise er.LabellingError( er.BAD_ITEM, "item ids repeat" )
    chunks = []
    for kind, cards in groups:
        random.Random( f"{seed}|{packet[ 'name' ]}|{kind}" ).shuffle( cards )
        chunks += [ ( kind, cards[ n:n + size ] ) for n in range( 0, len( cards ), size ) ]
    return [ _make_batch( packet[ "name" ], seed, k, len( chunks ), kind, cards, start + timedelta( days=chase_days * k ) ) for k, ( kind, cards ) in enumerate( chunks ) ]


def read_answers( batch, answers ):
    """
    Turn the answer that ask_open_ended_batch returned for one batch into labels.

    Strict: a phrase counts only when it is, after lowercasing and dropping punctuation, one of the ANSWER_LABELS or a known spoken form of one.
    Anything else is left unlabelled, never guessed.

    Requires:
        - batch is one element of voice_batches' result
        - answers is the "answers" dict the tool returned, keyed by header

    Ensures:
        - returns { "labels": [ { item_id, header, relation } ], "unlabelled": [ { item_id, header, text } ], "unmatched": [ header ] }
        - a card the reply did not answer, or answered blankly or unclearly, is in unlabelled, text being what was said or None
        - a header that matches no card of the batch is in unmatched, in sorted order, and labels nothing
        - labels and unlabelled follow the batch's card order and together hold every card once
    """
    labels, unlabelled = [], []
    for header, item_id in batch[ "headers" ].items():
        text     = answers.get( header )
        relation = SPOKEN.get( _normal( text ) ) if isinstance( text, str ) else None
        if relation is None: unlabelled.append( { "item_id": item_id, "header": header, "text": text } )
        else: labels.append( { "item_id": item_id, "header": header, "relation": relation } )
    return { "labels": labels, "unlabelled": unlabelled, "unmatched": sorted( set( answers ) - set( batch[ "headers" ] ) ) }


def main( argv=None, clock=lambda: datetime.now( timezone.utc ) ):
    """
    Read a returned batch answer into the gold store.

    Requires:
        - argv is [ "read", "--batch", id, "--packet", file, "--seed", seed, "--answers", file ], with optional --store, --source and --reader
        - the packet file holds { name, blind, disputes, refs }, refs mapping each item id to { notification_id, field_key }
        - the answers file holds the dict ask_open_ended_batch returned, or just its "answers" dict

    Ensures:
        - returns 0 after writing one gold line per labelled card and printing a JSON summary of the labelled, unlabelled and unmatched cards and Rick's labelled cards by stance class
        - returns 2, writing nothing, for an unknown batch id, a missing ref, or a file that cannot be read
        - returns 3, writing nothing, when the store is locked or damaged
    """
    ap = argparse.ArgumentParser( prog="voice_batches" )
    sub = ap.add_subparsers( dest="verb", required=True )
    rd = sub.add_parser( "read" )
    rd.add_argument( "--batch", required=True )
    rd.add_argument( "--packet", required=True )
    rd.add_argument( "--seed", required=True )
    rd.add_argument( "--answers", required=True )
    rd.add_argument( "--store", default=None )
    rd.add_argument( "--source", choices=gs.SOURCES, default=gs.SOURCE_HUMAN )
    rd.add_argument( "--reader", default="rick" )
    args = ap.parse_args( argv )
    try:
        packet  = json.loads( pathlib.Path( args.packet ).read_text( encoding="utf-8" ) )
        answers = json.loads( pathlib.Path( args.answers ).read_text( encoding="utf-8" ) )
        batches = voice_batches( packet, args.seed, "2026-01-01T00:00:00+00:00" )
    except ( OSError, ValueError, KeyError, TypeError, er.LabellingError ) as e:
        return er.fail( f"cannot read the packet or the answers: {e!r}", 2 )
    batch = next( ( b for b in batches if b[ "batch_id" ] == args.batch ), None )
    if batch is None: return er.fail( f"unknown batch id {args.batch}", 2 )
    if isinstance( answers, dict ) and isinstance( answers.get( "answers" ), dict ): answers = answers[ "answers" ]
    if not isinstance( answers, dict ): return er.fail( "the answers file holds no dict of answers", 2 )
    refs = packet.get( "refs", {} )
    absent = [ i for i in batch[ "item_ids" ] if not isinstance( refs.get( i ), dict ) or set( refs[ i ] ) != { "notification_id", "field_key" } ]
    if absent: return er.fail( f"the packet's refs lack notification_id and field_key for: {absent[ :5 ]}", 2 )
    result = read_answers( batch, answers )
    cards  = { i[ "item_id" ]: i for i in packet[ "blind" ] + packet[ "disputes" ] }
    ts     = clock().isoformat()
    lines  = [ { "item_id": x[ "item_id" ], "notification_id": refs[ x[ "item_id" ] ][ "notification_id" ], "field_key": refs[ x[ "item_id" ] ][ "field_key" ],
                 "relation": x[ "relation" ], "card_stance": cards[ x[ "item_id" ] ][ "payload" ][ "stance_class" ], "source": args.source,
                 "reader": args.reader, "batch_id": batch[ "batch_id" ], "ts": ts } for x in result[ "labels" ] ]
    path = pathlib.Path( args.store ) if args.store else gs.default_path()
    try:
        gs.append_gold( path, lines )
        counts = gs.human_card_counts( gs.read_gold( path ) )
    except er.LabellingError as e:
        return er.fail( f"the gold store refused the write: {e}", 3 )
    print( json.dumps( { "batch_id": batch[ "batch_id" ], "written": len( lines ), "unlabelled": result[ "unlabelled" ], "unmatched": result[ "unmatched" ], "human_labelled_by_stance": counts }, sort_keys=True ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
