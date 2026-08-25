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
# dm_topic_for — shared persona_slug root (Phase 4 gateway completeness)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "ident,expected", [
    ( "Bob",        "dm-bob"       ),
    ( "Mr Radio",   "dm-mr_radio"  ),   # internal space → "_"
    ( "mr radio",   "dm-mr_radio"  ),   # already-pool form is idempotent
] )
def test_dm_topic_for_ascii( ident, expected ):
    assert LupinCommonsGateway.dm_topic_for( ident ) == expected


def test_dm_topic_for_accented_persona_FLIP():
    """Phase 4 CONTRACT CHANGE + FLIP guard: `dm_topic_for` now routes through
    the shared `persona_slug` root, so an accented/punctuated persona keys to the
    CANONICAL topic — NOT the split "dm-maría" the old accent-leaky
    `re.sub( r"[^\\w-]+", "_", name, flags=re.UNICODE )` produced. That split was
    the live bug (both io/commons/dm-maría.md AND dm-maria.md existed). Revert
    this seam to the re.UNICODE re.sub → "María" yields "dm-maría" → this
    assertion fails → the test genuinely guards the cutover-durability fix."""
    assert LupinCommonsGateway.dm_topic_for( "María" )     == "dm-maria"
    assert LupinCommonsGateway.dm_topic_for( "Mr. Radio" ) == "dm-mr_radio"


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


# ──────────────────────────────────────────────────────────────────────────
# from_environment — the IO-wiring constructor (row 1a465fc3)
#
# This method used to carry `# pragma: no cover` whose stated reason was
# "exercised by the :8000 integration tier, not unit-mockable in isolation".
# Both halves were false. The integration file it pointed at was three
# `raise NotImplementedError` stubs behind a module-level skip when the pragma
# was written, so the exemption was bought with tests that did not exist. And
# the method IS unit-mockable: every dependency it reaches for is imported
# INSIDE the function body, so it resolves at call time and monkeypatch can
# replace all of it. The pragma is gone; these tests are what replaced it.


class _FakeCommonsStore:
    """CommonsStore double that records the root it was constructed with."""
    def __init__( self, root ):
        self.root = root


def _install_fake_environment( monkeypatch, tmp_path, key_text ):
    """
    Stand up a fake project root with a real key file on disk.

    Requires:
        - tmp_path is a writable directory
        - key_text is the raw bytes to place in the key file, newline included
          when the test wants to prove .strip() runs

    Ensures:
        - cu.get_project_root() returns str( tmp_path )
        - <root>/src/conf/keys/notification-api-claude-code-dev holds key_text
        - lupin_mcp.commons_store.CommonsStore is _FakeCommonsStore

    Returns:
        the project-root string the gateway will see
    """
    import cosa.utils.util as cu
    import lupin_mcp.commons_store as commons_store_module

    key_path = tmp_path / "src" / "conf" / "keys"
    key_path.mkdir( parents=True, exist_ok=True )
    ( key_path / "notification-api-claude-code-dev" ).write_text( key_text )

    project_root = str( tmp_path )
    monkeypatch.setattr( cu, "get_project_root", lambda: project_root )
    monkeypatch.setattr( commons_store_module, "CommonsStore", _FakeCommonsStore )
    return project_root


def test_from_environment_wires_every_dependency( monkeypatch, tmp_path ):
    """
    from_environment builds a gateway wired to the real collaborators.

    Ensures:
        - the API key is read from disk AND stripped of its trailing newline
        - the CommonsStore is constructed with the resolved project root
        - http_post is requests.post, not some other callable
        - sender_session_id and all three persona fields are passed through
    """
    import requests

    project_root = _install_fake_environment( monkeypatch, tmp_path, "  s3cret-key\n" )
    monkeypatch.setenv( "LUPIN_API_URL", "http://example.invalid:9999" )

    gw = LupinCommonsGateway.from_environment(
        sender_session_id = "arb-42",
        persona_name      = "Arbiter",
        persona_icon      = "🫀",
        persona_color     = "#0277BD",
    )

    assert isinstance( gw, LupinCommonsGateway )
    assert gw._api_key           == "s3cret-key", \
        f"api key should be the file contents stripped, got {gw._api_key!r}"
    assert gw._api_base_url      == "http://example.invalid:9999"
    assert isinstance( gw._store, _FakeCommonsStore )
    assert gw._store.root        == project_root, \
        f"CommonsStore should be rooted at the resolved project root, got {gw._store.root!r}"
    assert gw._http_post is requests.post, \
        "http_post should be requests.post — the production HTTP callable"
    assert gw._sender_session_id == "arb-42"
    assert gw._persona_name      == "Arbiter"
    assert gw._persona_icon      == "🫀"
    assert gw._persona_color     == "#0277BD"


def test_from_environment_defaults_base_url_when_env_unset( monkeypatch, tmp_path ):
    """
    The other side of the one branch in from_environment.

    Ensures:
        - with LUPIN_API_URL absent the gateway falls back to localhost:7999
    """
    _install_fake_environment( monkeypatch, tmp_path, "k\n" )
    monkeypatch.delenv( "LUPIN_API_URL", raising=False )

    gw = LupinCommonsGateway.from_environment( sender_session_id="arb-1" )

    assert gw._api_base_url == "http://localhost:7999"


def test_from_environment_defaults_persona_fields( monkeypatch, tmp_path ):
    """
    Ensures:
        - persona_name defaults to "heartbeat-poker"
        - persona_icon and persona_color default to None
    """
    _install_fake_environment( monkeypatch, tmp_path, "k" )
    monkeypatch.delenv( "LUPIN_API_URL", raising=False )

    gw = LupinCommonsGateway.from_environment( sender_session_id="arb-1" )

    assert gw._persona_name  == "heartbeat-poker"
    assert gw._persona_icon  is None
    assert gw._persona_color is None


def test_from_environment_propagates_a_missing_key_file( monkeypatch, tmp_path ):
    """
    A missing API key must FAIL, not yield a gateway that cannot authenticate.

    Ensures:
        - FileNotFoundError reaches the caller when the key file is absent
    """
    import cosa.utils.util as cu
    import lupin_mcp.commons_store as commons_store_module

    monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( commons_store_module, "CommonsStore", _FakeCommonsStore )

    with pytest.raises( FileNotFoundError ):
        LupinCommonsGateway.from_environment( sender_session_id="arb-1" )


# ──────────────────────────────────────────────────────────────────────────
# send_to / read_since / dm_topic_for — the rest of the module (row 1a465fc3)
#
# These were never covered. Removing the from_environment pragma took the file
# from 73% to 77%, which made the REAL gap visible: send_to's push-failure
# handling — the branch whose whole purpose is to log rather than swallow — had
# no test at all. A module that meets the coverage gate only because its
# untested half is exempt is the same defect as a test that cannot fail.


class _RecordingStore:
    """CommonsStore double recording post() kwargs and serving canned read() rows."""
    def __init__( self, read_rows=None ):
        self.posts     = [ ]
        self.reads     = [ ]
        self._read_rows = read_rows if read_rows is not None else [ ]

    def post( self, **kwargs ):
        self.posts.append( kwargs )

    def read( self, topic, since=None, limit=None ):
        self.reads.append( { "topic": topic, "since": since, "limit": limit } )
        return self._read_rows

    def who( self ):
        return [ ]


class _FakeResponse:
    def __init__( self, status_code, text="" ):
        self.status_code = status_code
        self.text        = text


def _recording_gateway( store, http_post ):
    return LupinCommonsGateway(
        sender_session_id = "arb-1",
        api_key           = "k3y",
        api_base_url      = "http://localhost:7999",
        store             = store,
        http_post         = http_post,
        persona_name      = "Arbiter",
        persona_icon      = "🫀",
        persona_color     = "#0277BD",
    )


def test_dm_topic_for_is_accent_and_punctuation_proof():
    """
    Ensures:
        - the topic is always dm-<persona_slug>, matching the other DM seams
        - accents and punctuation collapse rather than splitting the topic
    """
    assert LupinCommonsGateway.dm_topic_for( "Mr Radio" ) == "dm-mr_radio"
    assert LupinCommonsGateway.dm_topic_for( "María" )    == "dm-maria"
    assert LupinCommonsGateway.dm_topic_for( "Mr. Radio" ) == "dm-mr_radio"


def test_send_to_posts_to_disk_then_pushes():
    """
    The happy path: the disk post is authoritative, the push carries the body inline.

    Ensures:
        - the commons entry lands on the recipient's dm- topic with the poke metadata
        - the push goes to /api/dm/send with the api key header and a 5s timeout
        - the push thread_id EQUALS the disk post's question_id, so receipts correlate
    """
    store = _RecordingStore()
    calls = [ ]

    def _http_post( url, json=None, headers=None, timeout=None ):
        calls.append( { "url": url, "json": json, "headers": headers, "timeout": timeout } )
        return _FakeResponse( 200 )

    gw = _recording_gateway( store, _http_post )
    gw.send_to( _persona_recipient( "María" ), "poke body" )

    assert len( store.posts ) == 1, "the disk post is authoritative and must always happen"
    post = store.posts[ 0 ]
    assert post[ "topic" ]             == "dm-maria"
    assert post[ "body" ]              == "poke body"
    assert post[ "sender_session_id" ] == "arb-1"
    assert post[ "metadata" ][ "kind" ]              == "heartbeat"
    assert post[ "metadata" ][ "recipient_persona" ] == "María"

    assert len( calls ) == 1
    call = calls[ 0 ]
    assert call[ "url" ]                == "http://localhost:7999/api/dm/send"
    assert call[ "headers" ]            == { "X-API-Key": "k3y" }
    assert call[ "timeout" ]            == 5
    assert call[ "json" ][ "body" ]     == "poke body"
    assert call[ "json" ][ "sender_project" ] == "lupin"
    assert call[ "json" ][ "thread_id" ] == post[ "metadata" ][ "question_id" ], \
        "thread_id must equal the disk post's question_id or receipts cannot correlate"


def test_send_to_logs_a_transport_failure_and_does_not_raise( capsys ):
    """
    A refused connection must not lose the poke and must not be silent.

    Ensures:
        - the disk post still happened, so the poke survives
        - send_to returns normally rather than propagating
        - one HEARTBEAT_POKE_SEND_FAILED line names the recipient on stderr
    """
    store = _RecordingStore()

    def _boom( *args, **kwargs ):
        raise ConnectionError( "refused" )

    gw = _recording_gateway( store, _boom )
    gw.send_to( _persona_recipient( "tiberius" ), "poke body" )

    assert len( store.posts ) == 1, "the disk post must survive a push failure"
    stderr = capsys.readouterr().err
    assert "[HEARTBEAT_POKE_SEND_FAILED]" in stderr
    assert "recipient=tiberius" in stderr
    assert "status=None" in stderr, "a transport failure has no HTTP status"
    assert "refused" in stderr


def test_send_to_logs_a_non_2xx_response( capsys ):
    """
    requests.post returns a Response on a 413 rather than raising, so the refusal
    only surfaces if the status code is inspected.

    Ensures:
        - a >=400 reply produces the same greppable failure line, WITH its status
    """
    store = _RecordingStore()
    gw    = _recording_gateway( store, lambda *a, **k: _FakeResponse( 413, "too large" ) )
    gw.send_to( _persona_recipient( "tiberius" ), "poke body" )

    stderr = capsys.readouterr().err
    assert "[HEARTBEAT_POKE_SEND_FAILED]" in stderr
    assert "status=413"  in stderr
    assert "too large"   in stderr


def test_send_to_is_silent_on_success( capsys ):
    """
    Ensures:
        - a 2xx push logs nothing, so the failure line stays a real signal
    """
    gw = _recording_gateway( _RecordingStore(), lambda *a, **k: _FakeResponse( 204 ) )
    gw.send_to( _persona_recipient( "tiberius" ), "poke body" )

    assert capsys.readouterr().err == ""


def test_read_since_asks_the_store_for_entries_after_the_cursor():
    """
    Ensures:
        - the topic and since cursor reach the store unchanged
        - the limit is high enough not to silently truncate a backlog
        - the store's rows are returned verbatim
    """
    rows  = [ { "body": "a" }, { "body": "b" } ]
    store = _RecordingStore( read_rows=rows )
    gw    = _recording_gateway( store, lambda *a, **k: _FakeResponse( 200 ) )

    assert gw.read_since( "dm-maria", "2026-08-24T00:00:00Z" ) == rows
    assert store.reads == [ { "topic": "dm-maria", "since": "2026-08-24T00:00:00Z", "limit": 100_000 } ]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
