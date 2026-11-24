#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Build the development sample of answer cards for Rick's gold labels.

Plan: src/rnd/v0.2.4/2026.11.17-online-preference-learning-upgrades/2026.11.24-meaning-labeller-plan.md, section 11.
The database is read in a read-only transaction. The packet file is written once, never overwritten.

Run from the main checkout, pinning all three:

    cd <tree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/build_answer_card_sample.py --seed <seed>
"""

import argparse
import json
import os
import random
import sys
import uuid

from sqlalchemy import text

import cosa.utils.util as cu
import filter_stop_hook_cards as fsh
from cosa.agents.prediction_engine.episode_view import fields_of
from cosa.repo.labelling import items as it
from cosa.repo.labelling import voice_batches as vb
from cosa.research.preference_replay.cohorts import answer_source_of
from cosa.research.preference_replay.retune_run import read_id_list
from cosa.rest.postgres_models import Notification
from cosa.utils.notification_utils import extract_qualifier_comment, parse_field_selections

QUOTAS      = { "yes_no": 200, "multiple_choice": 180, "open_ended": 100, "open_ended_batch": 96 }
COHORT_TYPES = ( "yes_no", "multiple_choice" )
OPEN_TYPES   = ( "open_ended", "open_ended_batch" )
SINGLE_KEY   = "answer"
OUT          = "/io/gold-labels/answer-card-sample-packet.json"
CHASE_START  = "2026-01-01T00:00:00+00:00"


def counts_as_answer( notification ):
    """
    Say whether a stored answer is a person's own, never a default or a review card.

    Requires:
        - notification is a Notification row

    Ensures:
        - True only when answer_source_of says "human": the stored source is "ui", which a timeout default never is
    """
    return answer_source_of( notification.response_value, notification.response_options ) == "human"


def population( session, cohort_path ):
    """
    List the card ids each type may be drawn from.

    Requires:
        - session is an active session on the database that holds the notifications
        - cohort_path is the checkpoint cohort file

    Ensures:
        - yes/no and multiple-choice ids are the cohort's, less the Stop-hook cards (filter_stop_hook_cards), that count as answers
        - open-ended and batch ids are every answered card of that type that counts as an answer
        - each list is sorted; the reads run in a read-only transaction that is rolled back
        - returns { "population": { type: [ids] }, "stop_hook_dropped": int, "rows": { id: Notification } }
    """
    kept, dropped = fsh.split_cohort( read_id_list( cohort_path ), fsh.stop_hook_ids( session ) )
    session.execute( text( "SET TRANSACTION READ ONLY" ) )
    try:
        rows = { str( n.id ): n for n in session.query( Notification ).filter( Notification.state == "responded", Notification.response_type.in_( OPEN_TYPES ) ) }
        rows.update( { str( n.id ): n for n in session.query( Notification ).filter( Notification.id.in_( [ uuid.UUID( i ) for i in kept ] ) ) } )
    finally: session.rollback()
    people = { i: n for i, n in rows.items() if counts_as_answer( n ) }
    return { "population": { t: sorted( i for i, n in people.items() if n.response_type == t ) for t in QUOTAS },
             "stop_hook_dropped": len( dropped ), "rows": people }


def draw( ids, quota, seed, response_type ):
    """
    Draw a seeded uniform sample of one type.

    Requires:
        - ids is a sorted list of card ids; quota is a non-negative integer

    Ensures:
        - returns quota ids, the same for the same seed and type, whatever order ids arrives in

    Raises:
        - ValueError when the type has fewer cards than its quota
    """
    if len( ids ) < quota: raise ValueError( f"{response_type} has {len( ids )} cards, fewer than the quota of {quota}" )
    return sorted( random.Random( f"{seed}|{response_type}" ).sample( sorted( ids ), quota ) )


def card_items( notification ):
    """
    Turn one stored card into its answer items, one per answered field.

    Requires:
        - notification is a Notification row of one of the four types, answered by a person

    Ensures:
        - returns ( items, blanks ): items are ( item, ref ) pairs, ref being { notification_id, field_key }
        - a yes/no or open-ended card gives one item with field key "answer"; a multiple-choice or batch card one per header with an answer
        - stance_class is the stance extract_qualifier_comment reads on a yes/no card, "none" on every other
        - a field with no answer text is counted in blanks and gives no item
        - an item carries no forecast and no label

    Raises:
        - LabellingError BAD_ITEM when an item fails its validator
    """
    nid    = str( notification.id )
    value  = notification.response_value
    title  = notification.title or ""
    head   = [ notification.message, notification.abstract ] if title and notification.message.startswith( title ) else [ title, notification.message, notification.abstract ]
    found  = []
    if notification.response_type in ( "yes_no", "open_ended" ):
        answer = ( value.get( "value" ) or "" ).strip()
        stance = extract_qualifier_comment( answer )[ 0 ] if notification.response_type == "yes_no" else None
        found.append( ( SINGLE_KEY, head, [], None, answer, stance or "none" ) )
    else:
        picks = parse_field_selections( value ) or {}
        for field in fields_of( notification.response_options, notification.response_default ):
            key    = field[ "key" ] or SINGLE_KEY
            chosen = picks.get( field[ "key" ], { "selected": [] } )[ "selected" ]
            labels = [ o[ "label" ] for o in field[ "options" ] if o[ "label" ] ]
            marked = [ o[ "label" ] for o in field[ "options" ] if o[ "recommended" ] and o[ "label" ] ]
            found.append( ( key, head + [ field[ "prompt" ] ], labels, marked[ 0 ] if marked else None, ", ".join( chosen ), "none" ) )
    made, blanks = [], 0
    for number, ( key, parts, options, recommendation, answer, stance ) in enumerate( found ):
        if not answer.strip():
            blanks += 1
            continue
        payload = { "card_text": "\n".join( p for p in parts if p and p.strip() ), "options": options, "recommendation": recommendation,
                    "answer": answer.strip(), "stance_class": stance }
        made.append( ( it.make_item( it.ANSWER_CARD, f"{nid}:{number}", payload ), { "notification_id": nid, "field_key": key } ) )
    return made, blanks


def build( session, cohort_path, seed, name, quotas=None ):
    """
    Draw the sample and turn it into a packet for the voice-batch bridge.

    Requires:
        - session and cohort_path are as population takes them; seed and name are non-empty text

    Ensures:
        - returns ( packet, receipt ); packet is { name, blind, disputes, refs } with every item in blind and disputes empty
        - voice_batches accepts the packet, so no spoken text is over its limit and no item leaks a field
        - receipt names, per type, the population, the cards drawn and the items made, plus the blanks left out,
          the Stop-hook cards the filter dropped, the seed and the number of batches

    Raises:
        - ValueError when a type has fewer cards than its quota
    """
    quotas = QUOTAS if quotas is None else quotas
    pool   = population( session, cohort_path )
    packet = { "name": name, "blind": [], "disputes": [], "refs": {} }
    stats  = { t: { "population": len( pool[ "population" ][ t ] ), "cards": 0, "items": 0 } for t in quotas }
    blanks = 0
    for response_type, quota in quotas.items():
        for card in draw( pool[ "population" ][ response_type ], quota, seed, response_type ):
            made, empty = card_items( pool[ "rows" ][ card ] )
            blanks += empty
            stats[ response_type ][ "cards" ] += 1
            stats[ response_type ][ "items" ] += len( made )
            for item, ref in made:
                packet[ "blind" ].append( item )
                packet[ "refs" ][ item[ "item_id" ] ] = ref
    batches = vb.voice_batches( packet, seed, CHASE_START )
    return packet, { "seed": seed, "types": stats, "blank_fields_left_out": blanks, "stop_hook_dropped": pool[ "stop_hook_dropped" ], "batches": len( batches ) }


def main( argv=None, session_scope=None ):
    """
    Write the sample packet and print its receipt.

    Requires:
        - the database named by the configuration is reachable, unless session_scope is given
        - the packet file does not exist yet

    Ensures:
        - writes the packet once and prints the receipt as sorted-key json; returns 0
        - returns 2, writing nothing, when the packet file exists

    Raises:
        - ValueError when a type has fewer cards than its quota
    """
    root   = cu.get_project_root()
    parser = argparse.ArgumentParser( description="Build the development sample of answer cards (read only)." )
    parser.add_argument( "--seed", required=True )
    parser.add_argument( "--name", default="dev-sample" )
    parser.add_argument( "--cohort", default=root + fsh.COHORT )
    parser.add_argument( "--out", default=root + OUT )
    args = parser.parse_args( argv )
    if session_scope is None:
        from cosa.rest.db.database import get_db as session_scope
    if os.path.exists( args.out ):
        print( f"refused: {args.out} exists, and a packet is never overwritten", file=sys.stderr )
        return 2
    with session_scope() as session: packet, receipt = build( session, args.cohort, args.seed, args.name )
    with open( args.out, "x", encoding="utf-8" ) as handle: json.dump( packet, handle )
    print( json.dumps( receipt, indent=1, sort_keys=True ) )
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit( main() )
