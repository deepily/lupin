#!/usr/bin/env python3
"""
Row predicates in task_store_owed that the unit tier never drove.

Every function here is pure, so each test pins an input and asserts the rule's answer.
A holding row with an unreadable chase stays visible. A parked row with a malformed chase surfaces as owed.
A blocker is terminal only on the evidence the contract names.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cosa.rest.task_store_owed import (
    OWED_BASE_STATUSES,
    blocker_is_terminal,
    holding_is_active,
    is_canonical_uuid,
    is_owed,
    item_blocker_ids,
    owed_status_row,
    park_is_active,
)
from cosa.rest.task_store_rules import BLOCKED_STATUS, NOT_APPROVED_STATUS, PARK_STATUS

NOW          = datetime( 2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc )
FUTURE_AWARE = NOW + timedelta( hours = 1 )
PAST_AWARE   = NOW - timedelta( hours = 1 )
CANON_ID     = "123e4567-e89b-42d3-a456-426614174000"


# ── _is_active_until, reached through park_is_active / holding_is_active ──────────────────────────────────

class TestChaseCoercion:

    def test_datetime_chase_in_future_is_active( self ):
        assert park_is_active( PARK_STATUS, FUTURE_AWARE, NOW ) is True

    def test_datetime_chase_in_past_is_not_active( self ):
        assert park_is_active( PARK_STATUS, PAST_AWARE, NOW ) is False

    def test_naive_datetime_chase_is_read_as_utc( self ):
        naive_future = ( NOW + timedelta( minutes = 5 ) ).replace( tzinfo=None )
        naive_past   = ( NOW - timedelta( minutes = 5 ) ).replace( tzinfo=None )
        assert park_is_active( PARK_STATUS, naive_future, NOW ) is True
        assert park_is_active( PARK_STATUS, naive_past, NOW )   is False

    def test_naive_now_is_read_as_utc( self ):
        assert park_is_active( PARK_STATUS, FUTURE_AWARE, NOW.replace( tzinfo=None ) ) is True
        assert park_is_active( PARK_STATUS, PAST_AWARE, NOW.replace( tzinfo=None ) )   is False

    def test_string_chase_with_z_suffix_and_padding_is_parsed( self ):
        assert park_is_active( PARK_STATUS, "  2026-10-26T13:00:00Z ", NOW ) is True
        assert park_is_active( PARK_STATUS, "2026-10-26T11:00:00Z", NOW )     is False

    def test_unparseable_string_chase_is_not_active( self ):
        assert park_is_active( PARK_STATUS, "next tuesday", NOW ) is False

    @pytest.mark.parametrize( "chase", [ None, 12345, [ ] ] )
    def test_non_string_non_datetime_chase_is_not_active( self, chase ):
        assert park_is_active( PARK_STATUS, chase, NOW ) is False

    def test_wrong_status_is_not_active_even_with_a_future_chase( self ):
        assert park_is_active( "queued", FUTURE_AWARE, NOW ) is False


class TestHoldingIsActive:

    def test_not_approved_with_future_chase_is_active( self ):
        assert holding_is_active( NOT_APPROVED_STATUS, FUTURE_AWARE, NOW ) is True

    def test_not_approved_with_past_chase_has_expired( self ):
        assert holding_is_active( NOT_APPROVED_STATUS, PAST_AWARE, NOW ) is False

    def test_not_approved_with_unreadable_chase_is_not_hidden( self ):
        assert holding_is_active( NOT_APPROVED_STATUS, None, NOW )  is False
        assert holding_is_active( NOT_APPROVED_STATUS, "junk", NOW ) is False

    def test_a_parked_row_is_not_in_the_holding_area( self ):
        assert holding_is_active( PARK_STATUS, FUTURE_AWARE, NOW ) is False


# ── is_owed ────────────────────────────────────────────────────────────────────────────────────────────────

class TestIsOwed:

    @pytest.mark.parametrize( "status", [ "done", "dropped", "wont_fix" ] )
    def test_terminal_status_is_never_owed( self, status ):
        assert is_owed( status, None, NOW ) is False
        assert is_owed( status, PAST_AWARE, NOW ) is False

    def test_parked_with_future_chase_is_not_owed( self ):
        assert is_owed( PARK_STATUS, FUTURE_AWARE, NOW ) is False

    def test_parked_with_expired_chase_is_owed( self ):
        assert is_owed( PARK_STATUS, PAST_AWARE, NOW ) is True

    def test_queued_is_owed( self ):
        assert is_owed( "queued", None, NOW ) is True


# ── item_blocker_ids ───────────────────────────────────────────────────────────────────────────────────────

class TestItemBlockerIds:

    def test_non_list_gives_empty( self ):
        assert item_blocker_ids( None )            == [ ]
        assert item_blocker_ids( { "kind": "item", "id": "a" } ) == [ ]

    def test_only_well_formed_item_refs_survive_in_order_with_duplicates( self ):
        blocked_by = [
            "not-a-dict",
            { "kind": "user", "id": "rick" },        # wrong kind
            { "kind": "item" },                      # no id
            { "kind": "item", "id": 7 },             # id not a string
            { "kind": "item", "id": "" },            # empty id
            { "kind": "item", "id": "b" },
            { "kind": "item", "id": "a" },
            { "kind": "item", "id": "b" },
        ]
        assert item_blocker_ids( blocked_by ) == [ "b", "a", "b" ]


# ── is_canonical_uuid ──────────────────────────────────────────────────────────────────────────────────────

class TestIsCanonicalUuid:

    def test_dashed_lowercase_uuid_is_canonical( self ):
        assert is_canonical_uuid( CANON_ID ) is True

    def test_uppercase_dashed_uuid_is_canonical( self ):
        assert is_canonical_uuid( CANON_ID.upper() ) is True

    @pytest.mark.parametrize( "value", [
        "123e4567",                                  # 8-hex prefix
        CANON_ID.replace( "-", "" ),                 # compact 32-char form
        None, 42,                                    # not strings
    ] )
    def test_other_shapes_are_not_canonical( self, value ):
        assert is_canonical_uuid( value ) is False

    def test_36_chars_that_are_not_a_uuid_are_not_canonical( self ):
        # Right length, so the UUID parser is reached and refuses it.
        assert is_canonical_uuid( "z" * 36 ) is False

    def test_a_36_char_string_that_parses_but_is_not_the_canonical_form_is_rejected( self ):
        # Braces + no dashes parse as a UUID but str( UUID ) differs from the input.
        assert is_canonical_uuid( "{" + CANON_ID.replace( "-", "" ) + "}" ) is False


# ── blocker_is_terminal ────────────────────────────────────────────────────────────────────────────────────

class TestBlockerIsTerminal:

    def _refs( self, *ids ):
        return [ { "kind": "item", "id": i } for i in ids ]

    def test_a_status_other_than_blocked_is_never_flagged( self ):
        assert blocker_is_terminal( "queued", self._refs( "a" ), { "a": "done" } ) is False

    def test_blocker_in_a_terminal_status_is_flagged( self ):
        assert blocker_is_terminal( BLOCKED_STATUS, self._refs( "a" ), { "a": "dropped" } ) is True

    def test_blocker_still_live_is_not_flagged( self ):
        assert blocker_is_terminal( BLOCKED_STATUS, self._refs( "a" ), { "a": "in_progress" } ) is False

    def test_blocker_missing_from_the_lookup_is_skipped( self ):
        assert blocker_is_terminal( BLOCKED_STATUS, self._refs( "gone" ), { } ) is False

    def test_unresolved_canonical_id_is_condemned( self ):
        assert blocker_is_terminal( BLOCKED_STATUS, self._refs( CANON_ID ), { CANON_ID: None } ) is True

    def test_unresolved_non_canonical_id_is_not_condemned( self ):
        # "I cannot tell" lies toward not-flagged: an 8-hex prefix that failed to resolve proves nothing.
        assert blocker_is_terminal( BLOCKED_STATUS, self._refs( "123e4567" ), { "123e4567": None } ) is False

    def test_a_later_terminal_blocker_is_found_after_a_live_one( self ):
        refs   = self._refs( "live", "dead" )
        lookup = { "live": "queued", "dead": "wont_fix" }
        assert blocker_is_terminal( BLOCKED_STATUS, refs, lookup ) is True


# ── owed_status_row ────────────────────────────────────────────────────────────────────────────────────────

class TestOwedStatusRow:

    @pytest.mark.parametrize( "status", OWED_BASE_STATUSES )
    def test_base_statuses_are_owed_whatever_the_chase( self, status ):
        assert owed_status_row( status, "junk", NOW ) is True

    @pytest.mark.parametrize( "status", [ "blocked", "claimed", "review", "done", "dropped", "not_approved" ] )
    def test_other_statuses_are_not_in_the_owed_only_set( self, status ):
        assert owed_status_row( status, PAST_AWARE, NOW ) is False

    def test_parked_with_a_future_chase_is_not_owed( self ):
        assert owed_status_row( PARK_STATUS, FUTURE_AWARE, NOW ) is False

    def test_parked_with_a_due_chase_is_owed( self ):
        assert owed_status_row( PARK_STATUS, PAST_AWARE, NOW ) is True

    def test_parked_chase_due_exactly_now_is_owed( self ):
        assert owed_status_row( PARK_STATUS, NOW, NOW ) is True        # not ( chase > now )

    def test_parked_string_chase_is_parsed( self ):
        assert owed_status_row( PARK_STATUS, "2026-10-26T13:00:00Z", NOW ) is False
        assert owed_status_row( PARK_STATUS, "2026-10-26T11:00:00Z", NOW ) is True

    def test_parked_naive_chase_and_naive_now_are_read_as_utc( self ):
        naive_future = ( NOW + timedelta( hours = 1 ) ).replace( tzinfo=None )
        assert owed_status_row( PARK_STATUS, naive_future, NOW.replace( tzinfo=None ) ) is False

    def test_parked_unparseable_string_surfaces_as_owed( self ):
        assert owed_status_row( PARK_STATUS, "not a date", NOW ) is True

    @pytest.mark.parametrize( "chase", [ None, 5, [ ] ] )
    def test_parked_with_no_readable_chase_surfaces_as_owed( self, chase ):
        assert owed_status_row( PARK_STATUS, chase, NOW ) is True
