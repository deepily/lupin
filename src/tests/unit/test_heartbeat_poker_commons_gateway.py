#!/usr/bin/env python3
"""
Unit tests for LupinCommonsGateway.last_post_ts persona matching (Phase 2).

The `last_post_ts` lookup matches a persona-addressed recipient against the
commons `who()` rows by persona name. Phase 2 routes that compare through the
one canonical identity key so an accented/punctuated persona ("María",
"Mr. Radio") matches its who()-row persona_name — the same false-idle bug-class
the owed-oracle hit.

The IO-wiring constructor (`from_environment`) is excluded from coverage; these
tests construct the gateway directly with injected fakes (the documented unit
path).
"""
import os
import sys

import pytest


# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_poker_commons_gateway import LupinCommonsGateway
from cosa.agents.heartbeat_poker_job import RecipientSpec


class _FakeStore:
    """Minimal CommonsStore double exposing who() / read()."""
    def __init__( self, who_rows ):
        self._who_rows = who_rows

    def who( self ):
        return self._who_rows

    def read( self, topic, since=None, limit=None ):
        return [ ]


def _gateway( who_rows ):
    return LupinCommonsGateway(
        sender_session_id = "arb-1",
        api_key           = "k",
        api_base_url      = "http://localhost:7999",
        store             = _FakeStore( who_rows ),
        http_post         = lambda *a, **k: None,
        persona_name      = "Arbiter",
    )


def _persona_recipient( name ):
    return RecipientSpec( identifier=name, identifier_type="persona", role="manager" )


def _session_recipient( sid ):
    return RecipientSpec( identifier=sid, identifier_type="session_id", role="manager" )


# ---------------------------------------------------------------------------
# session_id branch (unchanged) — sanity
# ---------------------------------------------------------------------------

def test_session_id_branch_matches_exact():
    gw = _gateway( [ { "session_id": "s1", "last_post_ts": "T1" } ] )
    assert gw.last_post_ts( _session_recipient( "s1" ) ) == "T1"


def test_session_id_branch_no_match_returns_none():
    gw = _gateway( [ { "session_id": "s2", "last_post_ts": "T1" } ] )
    assert gw.last_post_ts( _session_recipient( "s1" ) ) is None


# ---------------------------------------------------------------------------
# persona branch — canonical identity match (Phase 2)
# ---------------------------------------------------------------------------

def test_persona_branch_matches_same_form():
    gw = _gateway( [ { "persona_name": "tiberius", "last_post_ts": "T1" } ] )
    assert gw.last_post_ts( _persona_recipient( "tiberius" ) ) == "T1"


def test_persona_branch_matches_accented_recipient_FLIP():
    # FLIP: the who() row holds the store form "maria"; the recipient is the
    # display form "María". The retired bare .lower() compared "maria" vs
    # "maría" -> MISS (None). canonical_persona_key strips both to "maria" -> hit.
    gw = _gateway( [ { "persona_name": "maria", "last_post_ts": "T-maria" } ] )
    assert gw.last_post_ts( _persona_recipient( "María" ) ) == "T-maria"


def test_persona_branch_matches_punctuated_recipient_FLIP():
    # FLIP: who() row "mr radio" vs recipient display "Mr. Radio". Old .lower()
    # compared "mr radio" vs "mr. radio" -> MISS. Canonical -> both "mr radio".
    gw = _gateway( [ { "persona_name": "mr radio", "last_post_ts": "T-radio" } ] )
    assert gw.last_post_ts( _persona_recipient( "Mr. Radio" ) ) == "T-radio"


def test_persona_branch_first_match_wins_newest_first():
    # who() is newest-first; the first persona match is the most-recent session.
    gw = _gateway( [
        { "persona_name": "Mr. Radio", "last_post_ts": "T-new" },
        { "persona_name": "mr radio",  "last_post_ts": "T-old" },
    ] )
    assert gw.last_post_ts( _persona_recipient( "mr radio" ) ) == "T-new"


def test_persona_branch_no_match_returns_none():
    gw = _gateway( [ { "persona_name": "tiberius", "last_post_ts": "T1" } ] )
    assert gw.last_post_ts( _persona_recipient( "María" ) ) is None


def test_persona_branch_missing_persona_name_is_skipped():
    # A row with no persona_name canonicalizes to "" and cannot match a real
    # recipient (whose canonical key is non-empty).
    gw = _gateway( [ { "last_post_ts": "T1" }, { "persona_name": None, "last_post_ts": "T2" } ] )
    assert gw.last_post_ts( _persona_recipient( "maria" ) ) is None


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
