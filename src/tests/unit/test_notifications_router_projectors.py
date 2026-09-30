"""
Unit tests for the row-to-envelope projectors in `cosa.rest.routers.notifications`.

🔴 EVERY FIELD IN THE FIXTURES CARRIES A DISTINCT VALUE. A projector is exactly the
shape where interchangeable data hides a defect: if `title` and `message` both read
"x", swapping them changes nothing observable and the test passes a projector that
crosses them. So each field gets a value naming itself, and the assertions check
identity rather than presence.

The same rule governs `from_earlier_session`: it is driven by a three-way condition,
so all four corners are posed. Two of them return False for DIFFERENT reasons, and a
test that only covered one would accept a projector that ignored the other.
"""

import sys
import os

import pytest

# Bootstrap imports
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

import cosa.rest.routers.notifications as notif


class _Row:
    """A stand-in Notification ORM row: whatever attributes the test names."""

    def __init__( self, **fields ):
        for key, value in fields.items():
            setattr( self, key, value )


class _Stamp:
    """A datetime stand-in whose isoformat() is unmistakable."""

    def __init__( self, text ):
        self._text = text

    def isoformat( self ):
        return self._text


# ──────────────────────────────────────────────────────────────────────────────
# _project_undelivered_notification
# ──────────────────────────────────────────────────────────────────────────────

def _undelivered_row( **overrides ):
    fields = {
        "id"         : "ID-VALUE",
        "sender_id"  : "SENDER-VALUE",
        "title"      : "TITLE-VALUE",
        "message"    : "MESSAGE-VALUE",
        "abstract"   : "ABSTRACT-VALUE",
        "type"       : "TYPE-VALUE",
        "priority"   : "PRIORITY-VALUE",
        "state"      : "STATE-VALUE",
        "job_id"     : "JOB-VALUE",
        "payload"    : { "PAYLOAD-KEY": "PAYLOAD-VALUE" },
        "created_at" : _Stamp( "CREATED-VALUE" ),
    }
    fields.update( overrides )
    return _Row( **fields )


class TestProjectUndeliveredNotification:
    """
    Project a Notification row to the undelivered-inbox envelope.

    Ensures:
        - every key carries ITS OWN field, so a crossed pair is visible
        - id is stringified
        - created_at is isoformat()-ed, and None survives as None
    """

    def test_every_field_lands_under_its_own_key( self ):
        # 🔴 THE VALUES ARE ALL DIFFERENT ON PURPOSE. With a shared "x" this assertion
        # would pass a projector that put `message` under "title".
        out = notif._project_undelivered_notification( _undelivered_row() )
        assert out == {
            "id"         : "ID-VALUE",
            "sender_id"  : "SENDER-VALUE",
            "title"      : "TITLE-VALUE",
            "message"    : "MESSAGE-VALUE",
            "abstract"   : "ABSTRACT-VALUE",
            "type"       : "TYPE-VALUE",
            "priority"   : "PRIORITY-VALUE",
            "state"      : "STATE-VALUE",
            "job_id"     : "JOB-VALUE",
            "payload"    : { "PAYLOAD-KEY": "PAYLOAD-VALUE" },
            "created_at" : "CREATED-VALUE",
        }

    def test_the_payload_passes_through_as_a_dict_rather_than_being_stringified( self ):
        """
        Row 4f320c27 S2. The payload is structured data a consumer folds on — a
        JSON string here would still serialise and still look like a payload, and
        every reader would have to parse it back.
        """
        out = notif._project_undelivered_notification( _undelivered_row() )
        assert out[ "payload" ] == { "PAYLOAD-KEY": "PAYLOAD-VALUE" }
        assert isinstance( out[ "payload" ], dict )

    def test_a_row_with_no_payload_projects_None_rather_than_raising( self ):
        """Every row written before migration 9184990becdf carries NULL here."""
        assert notif._project_undelivered_notification( _undelivered_row( payload=None ) )[ "payload" ] is None

    def test_the_id_is_stringified_not_passed_through( self ):
        """
        🔴 A UUID IS NOT JSON-SAFE. The fixture uses a non-str id whose str() differs
        from the object, so passing it through unconverted is detectable.
        """
        class _Uuid:
            def __str__( self ):
                return "the-stringified-form"
        out = notif._project_undelivered_notification( _undelivered_row( id=_Uuid() ) )
        assert out[ "id" ] == "the-stringified-form"
        assert isinstance( out[ "id" ], str )

    def test_a_missing_created_at_becomes_none_rather_than_raising( self ):
        out = notif._project_undelivered_notification( _undelivered_row( created_at=None ) )
        assert out[ "created_at" ] is None

    def test_created_at_is_isoformatted_not_str_ed( self ):
        """
        🔴 str() AND isoformat() MUST DISAGREE HERE, or the test cannot tell them
        apart. This stamp's str() is the default object repr, so only isoformat()
        yields the expected value.
        """
        row = _undelivered_row( created_at=_Stamp( "2026-08-30T21:00:00+00:00" ) )
        out = notif._project_undelivered_notification( row )
        assert out[ "created_at" ] == "2026-08-30T21:00:00+00:00"
        assert out[ "created_at" ] != str( row.created_at )


# ──────────────────────────────────────────────────────────────────────────────
# _project_owed_answer
# ──────────────────────────────────────────────────────────────────────────────

def _owed_row( **overrides ):
    fields = {
        "id"             : "OWED-ID",
        "sender_id"      : "claude.code@lupin.deepily.ai#aaaa1111",
        "sender_persona" : "PERSONA-VALUE",
        "message"        : "QUESTION-VALUE",
        "title"          : "TITLE-VALUE",
        "abstract"       : "ABSTRACT-VALUE",
        "response_value" : "ANSWER-VALUE",
        "responded_at"   : _Stamp( "RESPONDED-VALUE" ),
        "created_at"     : _Stamp( "CREATED-VALUE" ),
        "job_id"         : "JOB-VALUE",
    }
    fields.update( overrides )
    return _Row( **fields )


class TestProjectOwedAnswer:

    def test_the_question_is_the_asks_message_not_its_title( self ):
        """
        🔴 THE FIELD THIS ENVELOPE EXISTS FOR. A replayed answer with no question
        attached is worse than nothing, and `title` is the plausible wrong source —
        so the two fixtures differ and the assertion names both.
        """
        out = notif._project_owed_answer( _owed_row() )
        assert out[ "question" ] == "QUESTION-VALUE"
        assert out[ "title" ]    == "TITLE-VALUE"

    def test_every_other_field_lands_under_its_own_key( self ):
        out = notif._project_owed_answer( _owed_row() )
        assert out[ "id" ]             == "OWED-ID"
        assert out[ "sender_persona" ] == "PERSONA-VALUE"
        assert out[ "abstract" ]       == "ABSTRACT-VALUE"
        assert out[ "response_value" ] == "ANSWER-VALUE"
        assert out[ "job_id" ]         == "JOB-VALUE"
        # 🔴 the two stamps carry DIFFERENT text, so a projector that read
        # created_at into responded_at is visible.
        assert out[ "responded_at" ]   == "RESPONDED-VALUE"
        assert out[ "created_at" ]     == "CREATED-VALUE"

    def test_the_session_hash_is_the_suffix_after_the_hash_mark( self ):
        out = notif._project_owed_answer( _owed_row() )
        assert out[ "session_hash8" ] == "aaaa1111"

    @pytest.mark.parametrize( "sender_id", [ None, "", "no-hash-mark-here" ] )
    def test_a_sender_id_with_no_suffix_yields_no_session_hash( self, sender_id ):
        out = notif._project_owed_answer( _owed_row( sender_id=sender_id ) )
        assert out[ "session_hash8" ] is None

    def test_missing_stamps_become_none_rather_than_raising( self ):
        out = notif._project_owed_answer( _owed_row( responded_at=None, created_at=None ) )
        assert out[ "responded_at" ] is None
        assert out[ "created_at" ]   is None

    # ── from_earlier_session: all four corners ────────────────────────────────

    def test_a_different_asking_session_is_flagged_as_earlier( self ):
        out = notif._project_owed_answer( _owed_row(), requesting_session_hash8="bbbb2222" )
        assert out[ "from_earlier_session" ] is True

    def test_the_same_session_is_not_flagged( self ):
        """
        🔴 THE ONE THAT MAKES THE FLAG MEAN SOMETHING. Without it a projector
        hard-coded to True passes every other case here.
        """
        out = notif._project_owed_answer( _owed_row(), requesting_session_hash8="aaaa1111" )
        assert out[ "from_earlier_session" ] is False

    def test_no_requesting_session_is_not_flagged( self ):
        # False for a DIFFERENT reason than the case above — the comparison cannot
        # be made at all, rather than being made and matching.
        out = notif._project_owed_answer( _owed_row() )
        assert out[ "from_earlier_session" ] is False

    def test_an_asker_with_no_hash_is_not_flagged_even_against_a_requester( self ):
        # The third corner: requester known, asker unknown. A projector comparing
        # None != "bbbb2222" naively would call this True.
        out = notif._project_owed_answer( _owed_row( sender_id="no-hash-mark-here" ),
                                          requesting_session_hash8="bbbb2222" )
        assert out[ "from_earlier_session" ] is False

    def test_the_flag_is_a_bool_not_a_truthy_string( self ):
        """
        🔴 IT CROSSES A JSON BOUNDARY. `"aaaa1111"` is truthy and would serialise as
        a string, so identity against True/False is asserted, not truthiness.
        """
        out = notif._project_owed_answer( _owed_row(), requesting_session_hash8="bbbb2222" )
        assert out[ "from_earlier_session" ] is True
        assert isinstance( out[ "from_earlier_session" ], bool )


# ──────────────────────────────────────────────────────────────────────────────
# _undelivered_max_age_hours
# ──────────────────────────────────────────────────────────────────────────────

class TestUndeliveredMaxAgeHours:
    """
    Resolve the undelivered-drain age cap from config.

    🔴 THE FIXTURE VALUE IS NOT THE DEFAULT. If the test asked for 24 it could not
    tell "read the config" from "returned the hard-coded default", which is the only
    thing this helper does.
    """

    def test_it_returns_the_configured_cap( self, monkeypatch ):
        import lupin_app.main as main_module

        class _Cfg:
            def get( self, key, default=None, return_type=None ):
                assert key == "notification undelivered max age hours"
                return 72

        monkeypatch.setattr( main_module, "config_mgr", _Cfg() )
        assert notif._undelivered_max_age_hours() == 72

    def test_it_asks_for_24_as_the_default( self, monkeypatch ):
        """
        The storm guard's fallback. Asserted by capturing the DEFAULT the helper
        passes down, because a config that answers cannot reveal what it would have
        fallen back to.
        """
        import lupin_app.main as main_module
        seen = {}

        class _Cfg:
            def get( self, key, default=None, return_type=None ):
                seen[ "default" ] = default
                return default

        monkeypatch.setattr( main_module, "config_mgr", _Cfg() )
        assert notif._undelivered_max_age_hours() == 24
        assert seen[ "default" ] == 24
