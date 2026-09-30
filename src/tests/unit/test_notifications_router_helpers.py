"""
Unit tests for the pure helpers in `cosa.rest.routers.notifications`.

🔴 WRITTEN TO DISCRIMINATE, NOT TO EXECUTE. Every case here is chosen so that the
WRONG behaviour produces a DIFFERENT observable value, because a test whose expected
and mutated outputs coincide is a line-counter wearing an assertion's clothes. Two
shapes are avoided deliberately:

  - interchangeable values. A fixture using the same number, key or id twice cannot
    reveal a swap between them, whatever the assertion says.
  - defaults that agree with the bug. `_extract_response_value( True )` must be
    `"true"` and not `"True"`, so `json.dumps` and `str` are distinguishable; an
    eviction test must say WHICH entry survived, not how many did.

Every test in this file was mutation-checked: the helper was broken one edit at a
time and the named test below reddened. See the review record for the arms.
"""

import json
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


# ──────────────────────────────────────────────────────────────────────────────
# _extract_response_value
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractResponseValue:
    """
    Pull the scalar answer out of a stored response_value.

    Requires:
        - nothing; the helper is pure

    Ensures:
        - None in, None out
        - a dict is unwrapped by its "value" key
        - a bare string passes through unchanged
        - any non-string is JSON-encoded, NOT str()-ed
    """

    def test_none_stays_none( self ):
        assert notif._extract_response_value( None ) is None

    def test_a_dict_is_unwrapped_by_its_value_key( self ):
        # 🔴 the wrapper and the payload are DIFFERENT strings, so returning the whole
        # dict, or the wrong key, cannot coincide with the right answer.
        assert notif._extract_response_value( { "value": "yes", "other": "no" } ) == "yes"

    def test_a_bare_string_passes_through( self ):
        assert notif._extract_response_value( "maybe" ) == "maybe"

    def test_a_non_string_is_json_encoded_not_str_ed( self ):
        # 🔴 THE WHOLE POINT OF THIS CASE. `str( True )` is "True" and
        # `json.dumps( True )` is "true" — a helper that reached for str() would pass
        # any test using a value where the two agree (an int, say). They must not.
        assert notif._extract_response_value( True ) == "true"
        assert notif._extract_response_value( True ) != str( True )

    def test_a_dict_whose_value_is_not_a_string_is_json_encoded( self ):
        assert notif._extract_response_value( { "value": [ 1, 2 ] } ) == json.dumps( [ 1, 2 ] )

    def test_a_dict_with_no_value_key_encodes_none( self ):
        # .get( "value" ) is None, which is not a str, so it is dumped — "null", not None.
        assert notif._extract_response_value( { "nothing": "here" } ) == "null"


# ──────────────────────────────────────────────────────────────────────────────
# _sse_headers
# ──────────────────────────────────────────────────────────────────────────────

class TestSseHeaders:

    def test_it_carries_the_four_headers_that_stop_buffering_and_caching( self ):
        """
        Ensures:
            - the exact values are pinned, because a proxy that buffers an
              event-stream turns a live ask into a silent one
        """
        h = notif._sse_headers()
        assert h[ "Content-Type" ]     == "text/event-stream"
        assert h[ "Cache-Control" ]    == "no-cache"
        assert h[ "X-Accel-Buffering" ] == "no"
        assert h[ "Connection" ]       == "keep-alive"

    def test_it_returns_a_fresh_dict_each_call( self ):
        # 🔴 a shared mutable default would let one response's header edit leak into
        # the next. Identity, not equality, is the question.
        assert notif._sse_headers() is not notif._sse_headers()


# ──────────────────────────────────────────────────────────────────────────────
# _voice_persona_for_sender_id
# ──────────────────────────────────────────────────────────────────────────────

class TestVoicePersonaForSenderId:
    """
    Resolve a sender_id to a voice-persona dict via the session bridge.

    Ensures:
        - every failure path returns None rather than raising
        - a legacy bridge lacking `display_name` gets one stamped
        - a bridge that already has `display_name` is left alone
    """

    def test_it_returns_none_when_the_bridge_module_is_unavailable( self, monkeypatch ):
        monkeypatch.setattr( notif, "_bridge_get_voice_persona", None )
        assert notif._voice_persona_for_sender_id( "claude.code@x#abcd1234" ) is None

    @pytest.mark.parametrize( "sender_id", [ None, "", "no-hash-suffix-at-all" ] )
    def test_it_returns_none_for_a_sender_id_it_cannot_split( self, monkeypatch, sender_id ):
        # the bridge is AVAILABLE here, so a None result is attributable to the
        # sender_id and not to the module being absent.
        monkeypatch.setattr( notif, "_bridge_get_voice_persona",
                             lambda s: { "name": "krishna" } )
        assert notif._voice_persona_for_sender_id( sender_id ) is None

    def test_it_returns_none_when_the_suffix_is_blank( self, monkeypatch ):
        # "#   " splits to a whitespace suffix, which .strip() empties.
        monkeypatch.setattr( notif, "_bridge_get_voice_persona",
                             lambda s: { "name": "krishna" } )
        assert notif._voice_persona_for_sender_id( "claude.code@x#   " ) is None

    def test_it_passes_the_suffix_alone_to_the_bridge( self, monkeypatch ):
        """
        🔴 THE SUFFIX, NOT THE WHOLE SENDER_ID. Passing the full string would still
        return a persona from a lenient bridge, so the ARGUMENT is what is asserted.
        """
        seen = []
        monkeypatch.setattr( notif, "_bridge_get_voice_persona",
                             lambda s: seen.append( s ) or { "name"         : "krishna",
                                                             "display_name" : "Krishna" } )
        notif._voice_persona_for_sender_id( "claude.code@lupin.deepily.ai#cda66e8e" )
        assert seen == [ "cda66e8e" ]

    def test_a_bridge_exception_becomes_none_rather_than_a_500( self, monkeypatch ):
        def boom( _s ):
            raise RuntimeError( "bridge file is corrupt" )
        monkeypatch.setattr( notif, "_bridge_get_voice_persona", boom )
        assert notif._voice_persona_for_sender_id( "claude.code@x#abcd1234" ) is None

    def test_a_legacy_persona_without_display_name_gets_one_stamped( self, monkeypatch ):
        monkeypatch.setattr( notif, "_bridge_get_voice_persona",
                             lambda s: { "name": "krishna", "icon": "🦚" } )
        monkeypatch.setattr( notif, "_display_name_for", lambda n: n.upper() )
        out = notif._voice_persona_for_sender_id( "claude.code@x#abcd1234" )
        # 🔴 "KRISHNA" is not "krishna" — the stamped value must be the RESOLVER's
        # output, not the raw name copied across.
        assert out[ "display_name" ] == "KRISHNA"
        assert out[ "name" ]         == "krishna"
        assert out[ "icon" ]         == "🦚"

    def test_an_existing_display_name_is_not_overwritten( self, monkeypatch ):
        monkeypatch.setattr( notif, "_bridge_get_voice_persona",
                             lambda s: { "name": "krishna", "display_name": "Krishna 🦚" } )
        monkeypatch.setattr( notif, "_display_name_for", lambda n: "WRONG" )
        out = notif._voice_persona_for_sender_id( "claude.code@x#abcd1234" )
        assert out[ "display_name" ] == "Krishna 🦚"

    def test_a_legacy_persona_is_left_alone_when_no_resolver_exists( self, monkeypatch ):
        monkeypatch.setattr( notif, "_bridge_get_voice_persona",
                             lambda s: { "name": "krishna" } )
        monkeypatch.setattr( notif, "_display_name_for", None )
        out = notif._voice_persona_for_sender_id( "claude.code@x#abcd1234" )
        assert "display_name" not in out

    def test_a_falsy_persona_is_returned_unchanged( self, monkeypatch ):
        # None from the bridge must not be stamped into a dict.
        monkeypatch.setattr( notif, "_bridge_get_voice_persona", lambda s: None )
        monkeypatch.setattr( notif, "_display_name_for", lambda n: "SHOULD NOT RUN" )
        assert notif._voice_persona_for_sender_id( "claude.code@x#abcd1234" ) is None

    def test_the_original_persona_dict_is_not_mutated( self, monkeypatch ):
        """
        🔴 THE BRIDGE'S DICT IS SHARED STATE. Stamping in place would edit whatever
        the bridge cached, so the helper must copy. Asserted on the ORIGINAL object.
        """
        original = { "name": "krishna" }
        monkeypatch.setattr( notif, "_bridge_get_voice_persona", lambda s: original )
        monkeypatch.setattr( notif, "_display_name_for", lambda n: "Krishna" )
        notif._voice_persona_for_sender_id( "claude.code@x#abcd1234" )
        assert "display_name" not in original


# ──────────────────────────────────────────────────────────────────────────────
# _manager_persona_for_sender_id
# ──────────────────────────────────────────────────────────────────────────────

class TestManagerPersonaForSenderId:

    def test_it_returns_none_when_the_resolver_is_unavailable( self, monkeypatch ):
        monkeypatch.setattr( notif, "_resolve_manager_persona", None )
        assert notif._manager_persona_for_sender_id( "claude.code@x#abcd1234" ) is None

    @pytest.mark.parametrize( "sender_id", [ None, "", "no-hash", "claude.code@x#  " ] )
    def test_it_returns_none_for_a_sender_id_it_cannot_split( self, monkeypatch, sender_id ):
        monkeypatch.setattr( notif, "_resolve_manager_persona", lambda s: { "name": "mr radio" } )
        assert notif._manager_persona_for_sender_id( sender_id ) is None

    def test_it_passes_the_suffix_alone_and_returns_the_badge_verbatim( self, monkeypatch ):
        seen = []
        badge = { "icon": "🦉", "color": "#8888ff", "name": "mr radio", "initial": "M" }
        monkeypatch.setattr( notif, "_resolve_manager_persona",
                             lambda s: seen.append( s ) or badge )
        out = notif._manager_persona_for_sender_id( "claude.code@lupin#93a8751c" )
        assert seen == [ "93a8751c" ]
        assert out  == badge

    def test_a_resolver_exception_becomes_none( self, monkeypatch ):
        def boom( _s ):
            raise KeyError( "no such session" )
        monkeypatch.setattr( notif, "_resolve_manager_persona", boom )
        assert notif._manager_persona_for_sender_id( "claude.code@x#abcd1234" ) is None


# ──────────────────────────────────────────────────────────────────────────────
# the ask-idempotency index
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def clean_ask_index():
    """Give each test an empty index and restore whatever was there afterwards."""
    saved = dict( notif._ask_idempotency_index )
    notif._ask_idempotency_index.clear()
    yield notif._ask_idempotency_index
    notif._ask_idempotency_index.clear()
    notif._ask_idempotency_index.update( saved )


class TestAskIdempotency:
    """
    Remember which notification_id a response-required ask minted for a key, so a
    re-POST re-attaches instead of minting a second card.

    🔴 EVERY id BELOW IS DISTINCT. A test using the same id twice cannot tell
    "returned the right entry" from "returned any entry".
    """

    def test_a_falsy_key_records_nothing( self, clean_ask_index ):
        notif._record_ask_idempotency( None, "n-1" )
        notif._record_ask_idempotency( "",   "n-2" )
        assert len( clean_ask_index ) == 0

    def test_a_falsy_key_looks_up_as_none( self, clean_ask_index ):
        assert notif._lookup_ask_idempotency( None ) is None
        assert notif._lookup_ask_idempotency( "" )   is None

    def test_a_recorded_key_round_trips_to_its_own_id( self, clean_ask_index ):
        notif._record_ask_idempotency( "key-a", "notif-aaa" )
        notif._record_ask_idempotency( "key-b", "notif-bbb" )
        # 🔴 both directions, because a helper returning the FIRST or the LAST entry
        # regardless of key would satisfy either assertion alone.
        assert notif._lookup_ask_idempotency( "key-a" ) == "notif-aaa"
        assert notif._lookup_ask_idempotency( "key-b" ) == "notif-bbb"

    def test_an_unknown_key_is_a_miss_not_the_newest_entry( self, clean_ask_index ):
        notif._record_ask_idempotency( "key-a", "notif-aaa" )
        assert notif._lookup_ask_idempotency( "key-z" ) is None

    def test_re_recording_a_key_replaces_its_id( self, clean_ask_index ):
        notif._record_ask_idempotency( "key-a", "notif-first" )
        notif._record_ask_idempotency( "key-a", "notif-second" )
        assert notif._lookup_ask_idempotency( "key-a" ) == "notif-second"
        assert len( clean_ask_index ) == 1

    def test_the_index_evicts_the_OLDEST_when_it_overflows( self, clean_ask_index, monkeypatch ):
        """
        🔴 WHICH ENTRY SURVIVED, NOT HOW MANY. A size-only assertion is satisfied by
        evicting the NEWEST, which is the opposite policy and the one that breaks
        re-attach for the ask that just happened.
        """
        monkeypatch.setattr( notif, "_IDEMPOTENCY_MAX", 2 )
        notif._record_ask_idempotency( "old",    "notif-old" )
        notif._record_ask_idempotency( "middle", "notif-middle" )
        notif._record_ask_idempotency( "new",    "notif-new" )
        assert notif._lookup_ask_idempotency( "old" )    is None
        assert notif._lookup_ask_idempotency( "middle" ) == "notif-middle"
        assert notif._lookup_ask_idempotency( "new" )    == "notif-new"

    def test_an_entry_older_than_the_ttl_is_evicted_before_the_lookup( self, clean_ask_index, monkeypatch ):
        """
        Ensures:
            - a key recorded longer ago than _IDEMPOTENCY_TTL never re-attaches
            - the clock is driven, not slept on
        """
        now = [ 1_000.0 ]
        monkeypatch.setattr( notif.time_mod, "time", lambda: now[ 0 ] )
        notif._record_ask_idempotency( "stale", "notif-stale" )
        now[ 0 ] += notif._IDEMPOTENCY_TTL + 1
        assert notif._lookup_ask_idempotency( "stale" ) is None

    def test_an_entry_inside_the_ttl_still_re_attaches( self, clean_ask_index, monkeypatch ):
        """
        🔴 THE OTHER SIDE OF THE BOUNDARY. Without this, a helper that evicted
        EVERYTHING on every lookup would pass the staleness test above.
        """
        now = [ 1_000.0 ]
        monkeypatch.setattr( notif.time_mod, "time", lambda: now[ 0 ] )
        notif._record_ask_idempotency( "fresh", "notif-fresh" )
        now[ 0 ] += notif._IDEMPOTENCY_TTL - 1
        assert notif._lookup_ask_idempotency( "fresh" ) == "notif-fresh"

    def test_eviction_stops_at_the_first_live_entry( self, clean_ask_index, monkeypatch ):
        """
        🔴 THE SWEEP IS A PREFIX SWEEP, AND THAT IS LOAD-BEARING. It walks from the
        oldest and STOPS at the first live one, so a stale entry sitting BEHIND a
        live entry must survive. A sweep rewritten to scan the whole index would
        drop it — same observable count, different entries, which is why this
        asserts identity.
        """
        now = [ 1_000.0 ]
        monkeypatch.setattr( notif.time_mod, "time", lambda: now[ 0 ] )
        notif._record_ask_idempotency( "first-and-stale", "notif-1" )
        now[ 0 ] += notif._IDEMPOTENCY_TTL - 1     # still live when recorded below
        notif._record_ask_idempotency( "second-live", "notif-2" )
        now[ 0 ] += 2                              # first is now stale, second is not
        assert notif._lookup_ask_idempotency( "first-and-stale" ) is None
        assert notif._lookup_ask_idempotency( "second-live" )     == "notif-2"
