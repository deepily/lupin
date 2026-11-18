"""
The four leak classes on the real 50-target context export (local_data tier).

These tests read Rick's real context records from the main checkout's gitignored
`io/write-ups/online-preference-learning/`. In a worktree the folder is absent and each
test skips by name. Nothing here commits or copies any of that data, and every figure
below was measured on the export whose sha the first test pins.
"""

import json
from datetime import datetime

import pytest

from cosa.utils.file_hash import file_sha256
from cosa.utils.local_data_tier import MANIFEST_FILE_NAME, require_local_file

CONTEXT_FILE_NAME = "2026.11.17-recent-predictions-sample-50-context.json"

pytestmark = pytest.mark.local_data


def _export():
    """
    Load the real context export.

    Ensures:
        - returns ( targets_by_id, records ) from the export
        - skips by name when the file is absent
    """
    export = json.load( open( require_local_file( CONTEXT_FILE_NAME ) ) )
    return { t[ "target_notification_id" ]: t for t in export[ "targets" ] }, export[ "records" ]


def _links( targets, records ):
    """
    Walk every ( record, target, link ) triple in the export.

    Requires:
        - targets and records come from _export

    Ensures:
        - yields ( notification, target, answer_status_at_this_target ) once per link
    """
    for record in records.values():
        for link in record[ "linked_targets" ]:
            yield record[ "notification" ], targets[ link[ "target_notification_id" ] ], link[ "answer_status_at_this_target" ]


def _when( text ):
    """
    Parse an ISO time with offset, None for a missing one.

    Requires:
        - text is an ISO-8601 string or None

    Ensures:
        - returns an aware datetime or None
    """
    return datetime.fromisoformat( text ) if text else None


def test_the_context_export_matches_the_manifest_sha_and_the_measured_counts():
    recorded = dict( ( line.split( "  " )[ 1 ], line.split( "  " )[ 0 ] )
                     for line in open( require_local_file( MANIFEST_FILE_NAME ) ).read().splitlines() if line.strip() )
    assert recorded[ CONTEXT_FILE_NAME ] == file_sha256( require_local_file( CONTEXT_FILE_NAME ) )
    targets, records = _export()
    assert ( len( targets ), len( records ), len( list( _links( targets, records ) ) ) ) == ( 50, 323, 332 )


def test_eventual_answer_an_answered_link_was_answered_by_the_ask_and_a_pending_one_carries_no_answer():
    targets, records = _export()
    answered = pending = 0
    for notification, target, status in _links( targets, records ):
        asked = _when( target[ "asked_at" ] )
        if status == "answered":
            answered += 1
            assert _when( notification[ "responded_at" ] ) <= asked
            assert notification[ "response_value" ] is not None
        elif status == "pending":
            pending += 1
            assert notification[ "responded_at" ] is None and notification[ "response_value" ] is None
    assert ( answered, pending ) == ( 82, 28 )


def test_later_status_one_pending_link_sits_on_a_record_whose_final_state_is_responded():
    targets, records = _export()
    final_but_pending = [ notification[ "state" ] for notification, _, status in _links( targets, records )
                          if status == "pending" and notification[ "state" ] in ( "responded", "expired" ) ]
    assert sorted( final_but_pending ) == [ "expired" ] * 27 + [ "responded" ]
    one_answered_later = [ n for n, _, status in _links( targets, records ) if status == "pending" and n[ "state" ] == "responded" ]
    assert len( one_answered_later ) == 1
    assert one_answered_later[ 0 ][ "response_value" ] is None, "the export hides the answer its final state would reveal"


def test_final_notification_state_never_decides_the_ask_time_status():
    targets, records = _export()
    for notification, _, status in _links( targets, records ):
        if status == "answered": assert notification[ "state" ] == "responded"
    by_state = {}
    for notification, _, status in _links( targets, records ):
        by_state.setdefault( notification[ "state" ], set() ).add( status )
    assert "pending" in by_state[ "expired" ] and "pending" in by_state[ "responded" ], "the same final state carries different ask-time statuses"


def test_own_stored_case_no_target_is_in_its_own_context_and_every_record_precedes_its_ask():
    targets, records = _export()
    assert not [ t for t in targets.values() if t[ "target_notification_id" ] in t[ "context_ids_oldest_first" ] ]
    assert all( _when( n[ "created_at" ] ) < _when( t[ "asked_at" ] ) for n, t, _ in _links( targets, records ) )
