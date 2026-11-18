"""
The context rebuild, checked on the real 50-target context export (the `local_data` tier).

These tests read Rick's real context records from the main checkout's gitignored
`io/write-ups/online-preference-learning/`. In a worktree the folder is absent and each
test skips by name. Nothing here commits or copies any of that data. The figures were
measured on the export whose sha the first test pins.
"""

import json
from collections import Counter
from datetime import datetime

import pytest

from cosa.agents.prediction_engine.history_context_rebuild import rebuild_context, reconstructable_stage
from cosa.utils.file_hash import file_sha256
from cosa.utils.local_data_tier import MANIFEST_FILE_NAME, require_local_file

CONTEXT_FILE_NAME = "2026.11.17-recent-predictions-sample-50-context.json"

pytestmark = pytest.mark.local_data


def _rebuilt():
    """
    Rebuild the context of every target in the real export from its 323 records.

    Ensures:
        - returns ( export, results ) where results maps target id to the rebuild_context result
        - skips by name when the file is absent
    """
    export  = json.load( open( require_local_file( CONTEXT_FILE_NAME ) ) )
    records = [ r[ "notification" ] for r in export[ "records" ].values() ]
    return export, { t[ "target_notification_id" ]: rebuild_context( t[ "target_notification" ], records ) for t in export[ "targets" ] }


def test_the_context_export_matches_the_manifest_sha():
    recorded = dict( ( line.split( "  " )[ 1 ], line.split( "  " )[ 0 ] )
                     for line in open( require_local_file( MANIFEST_FILE_NAME ) ).read().splitlines() if line.strip() )
    assert recorded[ CONTEXT_FILE_NAME ] == file_sha256( require_local_file( CONTEXT_FILE_NAME ) )


def test_forty_five_of_fifty_targets_are_rebuilt_and_every_other_one_has_a_named_reason():
    export, results = _rebuilt()
    stage = reconstructable_stage( list( results.values() ) )
    assert ( stage[ "count" ], stage[ "dropped" ] ) == ( 45, { "no_context": 4, "ambiguous_only": 1 } )
    for target in export[ "targets" ]:
        if results[ target[ "target_notification_id" ] ][ "context_state" ] == "no_context":
            assert target[ "context_ids_oldest_first" ] == [], "the export also holds no context for it"


def test_every_record_the_export_chose_is_attached_except_the_five_on_a_bare_sender():
    export, results = _rebuilt()
    attached = missed = 0
    for target in export[ "targets" ]:
        got = { a[ "id" ] for a in results[ target[ "target_notification_id" ] ][ "attachments" ] }
        chosen = set( target[ "context_ids_oldest_first" ] )
        attached += len( chosen & got )
        if chosen - got:
            missed += len( chosen - got )
            assert target[ "conversation" ][ "key_kind" ] == "sender"
            assert "#" not in target[ "target_notification" ][ "sender_id" ]
            assert { m[ "reason" ] for m in results[ target[ "target_notification_id" ] ][ "missing" ] } == { "bare_sender_only" }
    assert ( attached, missed ) == ( 327, 5 )


def test_the_tier_follows_the_export_conversation_key():
    export, results = _rebuilt()
    tiers = Counter()
    for target in export[ "targets" ]:
        by_id = { a[ "id" ]: a[ "tier" ] for a in results[ target[ "target_notification_id" ] ][ "attachments" ] }
        for record_id in target[ "context_ids_oldest_first" ]:
            if record_id in by_id: tiers[ ( target[ "conversation" ][ "key_kind" ], by_id[ record_id ] ) ] += 1
    assert dict( tiers ) == { ( "job", "job" ): 5, ( "session", "sender" ): 314, ( "session", "session" ): 8 }


def test_the_answer_as_of_the_ask_agrees_with_the_export_on_every_link_it_can_compare():
    export, results = _rebuilt()
    agreement = Counter()
    for target in export[ "targets" ]:
        by_id = { a[ "id" ]: a[ "answer" ][ "status" ] for a in results[ target[ "target_notification_id" ] ][ "attachments" ] }
        for record_id in target[ "context_ids_oldest_first" ]:
            for link in export[ "records" ][ record_id ][ "linked_targets" ]:
                if link[ "target_notification_id" ] == target[ "target_notification_id" ] and record_id in by_id:
                    agreement[ ( link[ "answer_status_at_this_target" ], by_id[ record_id ] ) ] += 1
    assert dict( agreement ) == { ( "answered", "answered" ): 77, ( "pending", "pending" ): 28, ( "not_a_question", "not_a_question" ): 222 }


def test_nothing_created_at_or_after_the_ask_is_attached_to_any_target():
    export, results = _rebuilt()
    created = { rid: datetime.fromisoformat( r[ "notification" ][ "created_at" ] ) for rid, r in export[ "records" ].items() }
    for target in export[ "targets" ]:
        asked = datetime.fromisoformat( target[ "asked_at" ] )
        for attachment in results[ target[ "target_notification_id" ] ][ "attachments" ]:
            assert created[ attachment[ "id" ] ] < asked
