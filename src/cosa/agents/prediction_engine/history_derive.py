"""
The second history step: keep every original row and derive one example from each.

The originals are written untouched. The derived set decodes each answer through the shared
parsers, names how far its actor can be trusted, and flags retry copies without dropping them.
Both files are written with freeze_corpus.write_snapshot and checked with verify_snapshot.
"""

import json
import os

from cosa.agents.prediction_engine.ask_family import classify_asks
from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows, verify_snapshot, write_snapshot
from cosa.utils.notification_utils import extract_qualifier_comment, parse_field_selections

SCHEMA_VERSION    = 1
BACKFILL_VERSION  = "opl-history-1"
JOIN_METHOD       = "notification_row"
ORIGINALS_NAME    = "originals.jsonl"
DERIVED_NAME      = "derived.jsonl"
MANIFEST_SUFFIX   = ".manifest.json"
FIELD_TYPES       = ( "multiple_choice", "open_ended_batch" )


def attribution_tier( raw ):
    """
    Name how far the actor of an answer can be trusted.

    Requires:
        - raw is a notification row as a dict, with recipient_id and response_value

    Ensures:
        - Returns "none" when the row has no stored answer
        - Returns "timeout_default" when the answer came from the timeout default, not a person
        - Returns "recipient" when the answering user is the recipient
        - Returns "other_account" when a different user answered
        - Returns "unknown_actor" when the answer carries no user, as every answer logged before the actor field
    """
    value = raw.get( "response_value" )
    if not isinstance( value, dict ): return "none"
    if value.get( "source" ) == "timeout_default": return "timeout_default"
    user = ( value.get( "answered_by" ) or {} ).get( "user_id" )
    if user is None: return "unknown_actor"
    return "recipient" if user == raw[ "recipient_id" ] else "other_account"


def derive_answer( raw ):
    """
    Decode the stored answer of one notification.

    Requires:
        - raw is a notification row as a dict, with response_type and response_value

    Ensures:
        - Returns ( answer, failure ); failure is None unless a stored answer could not be read
        - answer is { "kind": "none" } for a row with no stored answer
        - answer is { "kind": "stance", "stance", "qualifier" } for yes/no
        - answer is { "kind": "fields", "fields" } from parse_field_selections for multiple choice and batch
        - answer is { "kind": "text", "text" } for open-ended
        - On a failure the answer keeps kind "unread" and the raw text, never a guess
    """
    value = raw.get( "response_value" )
    if not isinstance( value, dict ): return { "kind": "none" }, None
    text = value.get( "value" )
    kind = raw[ "response_type" ]
    if kind == "yes_no":
        stance, qualifier = extract_qualifier_comment( text if isinstance( text, str ) else None )
        if stance is None: return { "kind": "unread", "text": text }, "stance_not_recognised"
        return { "kind": "stance", "stance": stance, "qualifier": qualifier }, None
    if kind in FIELD_TYPES:
        fields = parse_field_selections( value )
        if fields is None: return { "kind": "unread", "text": text }, "fields_not_readable"
        return { "kind": "fields", "fields": fields }, None
    return { "kind": "text", "text": text }, None


def asks_of( raws ):
    """
    Shape notification rows as the ask dicts classify_asks reads.

    Requires:
        - raws is a list of notification rows as dicts, each with response_type, title, message, sender_id and created_at

    Ensures:
        - Returns one ask dict per row, in order, with category None and asked_at taken from created_at
    """
    return [ { "response_type": r[ "response_type" ], "category": None, "title": r[ "title" ], "message": r[ "message" ],
               "sender_id": r[ "sender_id" ], "asked_at": r[ "created_at" ] } for r in raws ]


def meaning_structure( native_answer, conditions, field_key ):
    """
    Read one field's option ids and linked conditions from a stored meaning record.

    Requires:
        - native_answer is the meaning record's map of field key to entry, each entry holding selected_option_ids,
          write_in_text and referred_option_ids
        - conditions is the record's list of { "text", "modifies_option_id" }, the id None for the whole answer

    Ensures:
        - returns None when the record has no entry for field_key
        - otherwise returns { "option_ids", "write_in_text", "referred_option_ids", "conditions" }
        - a condition belongs to the field when it changes none of the card (id None) or one of this field's selected or referred ids;
          each is returned as { "text", "modifies_option_id" }, so the link to its option reaches the writer as a field, never as joined text
    """
    entry = native_answer.get( field_key )
    if entry is None: return None
    own = set( entry[ "selected_option_ids" ] ) | set( entry[ "referred_option_ids" ] )
    return { "option_ids": list( entry[ "selected_option_ids" ] ), "write_in_text": entry[ "write_in_text" ], "referred_option_ids": list( entry[ "referred_option_ids" ] ),
             "conditions": [ { "text": c[ "text" ], "modifies_option_id": c[ "modifies_option_id" ] } for c in conditions
                             if c[ "modifies_option_id" ] is None or c[ "modifies_option_id" ] in own ] }


def derive_dataset( raws ):
    """
    Derive one example per original row, and count what could not be read.

    Requires:
        - raws is a list of notification rows as dicts, each with id, recipient_id, sender_id,
          title, message, response_type, state, created_at and response_value

    Ensures:
        - Returns ( derived, counts ), derived in the order of raws, one example per row
        - Each example has the notification id, sender, thread, job and parent ids, schema and backfill versions, source pointer, join
          method, offered-schema flag, answer, attribution tier, failure, retry flag and retry group
        - A retry copy stays in the set, flagged; no row is dropped
        - counts holds rows, answered, unread_by_reason and tiers, so a parse failure is visible
    """
    groups  = classify_asks( asks_of( raws ) )
    derived = []
    counts  = { "rows": len( raws ), "answered": 0, "unread_by_reason": {}, "tiers": {} }
    for raw, group in zip( raws, groups ):
        answer, failure = derive_answer( raw )
        tier            = attribution_tier( raw )
        if answer[ "kind" ] != "none": counts[ "answered" ] += 1
        if failure is not None: counts[ "unread_by_reason" ][ failure ] = counts[ "unread_by_reason" ].get( failure, 0 ) + 1
        counts[ "tiers" ][ tier ] = counts[ "tiers" ].get( tier, 0 ) + 1
        derived.append( {
            "notification_id"    : raw[ "id" ],
            "schema_version"     : SCHEMA_VERSION,
            "backfill_version"   : BACKFILL_VERSION,
            "source_pointer"     : f"notifications:{raw[ 'id' ]}",
            "join_method"        : JOIN_METHOD,
            "response_type"      : raw[ "response_type" ],
            "state"              : raw[ "state" ],
            "asked_at"           : raw[ "created_at" ],
            "sender_id"          : raw[ "sender_id" ],
            "thread_id"          : raw.get( "thread_id" ),
            "job_id"             : raw.get( "job_id" ),
            "reply_to"           : raw.get( "reply_to" ),
            "has_offered_schema" : bool( ( raw.get( "response_options" ) or {} ).get( "questions" ) ),
            "answer"             : answer,
            "attribution_tier"   : tier,
            "failure"            : failure,
            "is_retry_copy"      : group[ "is_retry_copy" ],
            "retry_group"        : group[ "retry_group" ],
        } )
    return derived, counts


def write_dataset( raws, out_dir ):
    """
    Write the originals and the derived set, each with a manifest, and check both.

    Requires:
        - raws is a non-empty list of notification rows as dicts
        - out_dir is a directory path that may not exist yet

    Ensures:
        - Writes originals.jsonl exactly as given and derived.jsonl, each beside its manifest
        - Returns { "counts", "originals_sha256", "derived_sha256" }
        - Both files pass verify_snapshot

    Raises:
        - ValueError if raws is empty, or if either file fails its check, naming the file and the detail
    """
    if not raws: raise ValueError( "no original rows to preserve" )
    derived, counts = derive_dataset( raws )
    os.makedirs( out_dir, exist_ok=True )
    shas = {}
    for name, rows in ( ( ORIGINALS_NAME, raws ), ( DERIVED_NAME, derived ) ):
        path     = os.path.join( out_dir, name )
        manifest = path + MANIFEST_SUFFIX
        write_snapshot( rows, path )
        shas[ name ] = sha256_of_rows( rows )
        with open( manifest, "w", encoding="utf-8" ) as handle:
            json.dump( { "snapshot_sha256": shas[ name ], "snapshot_row_count": len( rows ), "schema_version": SCHEMA_VERSION,
                         "backfill_version": BACKFILL_VERSION }, handle, sort_keys=True )
        ok, detail = verify_snapshot( path, manifest )
        if not ok: raise ValueError( f"{name} failed its check: {detail}" )
    return { "counts": counts, "originals_sha256": shas[ ORIGINALS_NAME ], "derived_sha256": shas[ DERIVED_NAME ] }
