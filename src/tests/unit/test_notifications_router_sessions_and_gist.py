"""
Unit tests for the last four small endpoints of the notifications router:

    GET  /api/notifications/senders-visible/{user_email}
    GET  /api/notifications/active-conversation/{user_email}
    GET  /api/notifications/project-sessions/{project}/{user_email}
    POST /api/notifications/generate-gist

🔴 THE FIRST ONE STAMPS TWO PERSONA BADGES ONTO EVERY SENDER, and both come from the
SAME argument through two different lookups. The fixtures therefore return different
values for the two, because a handler that crossed them — or called one lookup twice —
produces a perfectly well-formed response that puts the wrong badge on the card.

🔴 THE ACTIVE CONVERSATION IS WHERE A VOICE ANSWER GETS ROUTED, so `null` and a stale
sender id are not equally wrong. `null` means the UI asks; a wrong id sends a spoken
reply to somebody else's thread. Both branches are posed and the null one asserts JSON
null rather than falsiness.

🔴 THE GIST ENDPOINT HAS THREE WAYS TO BE EMPTY and only two of them are obvious:
no keys at all, present-but-empty lists, and lists holding only whitespace. The third
is the one that reaches the LLM if the guard is written as `if not messages`, and it
costs a real API call to learn nothing.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""

import uuid
from datetime import datetime, timedelta, timezone as _tz

import pytest

from tests.helpers.notifications_endpoint_harness import (
    a_uuid, assert_no_accidental_500, make_harness_fixture )

harness = make_harness_fixture()


_EMAIL = "someone@example.com"
_UID   = a_uuid( "sessions-user" )


@pytest.fixture( autouse=True )
def user_lookup( monkeypatch ):
    """Patched on its own module — the handlers import it inside the function body."""
    import cosa.rest.user_service as user_service
    state = { "user": { "id": _UID, "uid": "UID-VALUE" }, "calls": [] }

    def _fake( email ):
        state[ "calls" ].append( email )
        return state[ "user" ]

    monkeypatch.setattr( user_service, "get_user_by_email", _fake )
    return state


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/senders-visible/{user_email}
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheVisibleSenderList:

    _URL = f"/api/notifications/senders-visible/{_EMAIL}"

    @pytest.fixture( autouse=True )
    def _personas( self, monkeypatch ):
        """
        🔴 THE TWO LOOKUPS TAKE THE SAME ARGUMENT AND MUST NOT BE INTERCHANGEABLE.
        They return different, self-naming values so a crossed pair — or one lookup
        called twice — is visible in the response rather than merely plausible.
        """
        import cosa.rest.routers.notifications as notif
        self.voice_args   = []
        self.manager_args = []

        def _voice( sender_id ):
            self.voice_args.append( sender_id )
            return f"VOICE-FOR-{sender_id}"

        def _manager( sender_id ):
            self.manager_args.append( sender_id )
            return f"MANAGER-FOR-{sender_id}"

        monkeypatch.setattr( notif, "_voice_persona_for_sender_id",   _voice )
        monkeypatch.setattr( notif, "_manager_persona_for_sender_id", _manager )

    def _activity( self, sender, hours_ago=1 ):
        return { "sender_id"     : sender,
                 "new_count"     : 2,
                 "last_activity" : datetime.now( _tz.utc ) - timedelta( hours=hours_ago ) }

    def test_each_sender_carries_both_badges_from_its_own_id( self, harness ):
        harness.repo.returns( "get_sender_last_activities_visible",
                              [ self._activity( "SENDER-A" ) ] )
        r = harness.client.get( self._URL )
        assert_no_accidental_500( r )
        item = r.json()[ 0 ]
        assert item[ "voice_persona" ]   == "VOICE-FOR-SENDER-A"
        assert item[ "manager_persona" ] == "MANAGER-FOR-SENDER-A"

    def test_two_senders_get_their_OWN_badges_not_the_first_ones( self, harness ):
        """
        One row cannot tell "stamped per row" from "stamped once and reused". Two rows
        with different ids can, and a reused badge is exactly what a loop-variable slip
        produces.
        """
        harness.repo.returns( "get_sender_last_activities_visible",
                              [ self._activity( "SENDER-A" ), self._activity( "SENDER-B" ) ] )
        body = harness.client.get( self._URL ).json()
        assert body[ 0 ][ "voice_persona" ] == "VOICE-FOR-SENDER-A"
        assert body[ 1 ][ "voice_persona" ] == "VOICE-FOR-SENDER-B"
        assert self.voice_args   == [ "SENDER-A", "SENDER-B" ]
        assert self.manager_args == [ "SENDER-A", "SENDER-B" ]

    def test_the_last_activity_is_serialised_to_a_string( self, harness ):
        harness.repo.returns( "get_sender_last_activities_visible",
                              [ self._activity( "SENDER-A" ) ] )
        assert isinstance( harness.client.get( self._URL ).json()[ 0 ][ "last_activity" ], str )

    def test_the_query_is_scoped_by_recipient_with_hidden_excluded_by_default( self, harness ):
        harness.repo.returns( "get_sender_last_activities_visible", [] )
        harness.client.get( self._URL )
        call = harness.repo.call_to( "get_sender_last_activities_visible" )
        assert call.kwargs[ "recipient_id" ]    == uuid.UUID( _UID )
        assert call.kwargs[ "include_hidden" ]  is False
        assert call.kwargs[ "exclude_job_ids" ] is None

    def test_include_hidden_true_is_forwarded( self, harness ):
        harness.repo.returns( "get_sender_last_activities_visible", [] )
        harness.client.get( f"{self._URL}?include_hidden=true" )
        assert harness.repo.call_to( "get_sender_last_activities_visible" ).kwargs[ "include_hidden" ] is True

    def test_not_mine_forwards_the_users_own_jobs_as_an_exclusion( self, harness ):
        """The ids that travel are the rows to SPARE — forwarding them as an inclusion inverts the filter."""
        import cosa.rest.queue_extensions as qx

        class _Tracker:
            def get_jobs_for_user( self, uid ):
                assert uid == "UID-VALUE"
                return [ "JOB-A" ]

        original = qx.user_job_tracker
        qx.user_job_tracker = _Tracker()
        try:
            harness.repo.returns( "get_sender_last_activities_visible", [] )
            harness.client.get( f"{self._URL}?exclude_own_jobs=true" )
        finally:
            qx.user_job_tracker = original
        assert harness.repo.call_to( "get_sender_last_activities_visible" ).kwargs[ "exclude_job_ids" ] == [ "JOB-A" ]

    def test_the_hours_filter_runs_here_and_drops_the_old_sender( self, harness ):
        harness.repo.returns( "get_sender_last_activities_visible",
                              [ self._activity( "RECENT", 1 ), self._activity( "OLD", 100 ) ] )
        body = harness.client.get( f"{self._URL}?hours=24" ).json()
        assert [ s[ "sender_id" ] for s in body ] == [ "RECENT" ]

    def test_without_the_hours_filter_both_survive( self, harness ):
        harness.repo.returns( "get_sender_last_activities_visible",
                              [ self._activity( "RECENT", 1 ), self._activity( "OLD", 100 ) ] )
        assert len( harness.client.get( self._URL ).json() ) == 2

    def test_an_unknown_user_is_a_404_and_no_query_runs( self, harness, user_lookup ):
        user_lookup[ "user" ] = None
        r = harness.client.get( self._URL )
        assert r.status_code == 404
        assert harness.repo.calls == []

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_sender_last_activities_visible", RuntimeError( "boom" ) )
        assert harness.client.get( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/active-conversation/{user_email}
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheActiveConversation:

    _URL = f"/api/notifications/active-conversation/{_EMAIL}"

    def test_it_returns_the_most_recent_sender( self, harness ):
        harness.repo.returns( "get_active_conversation", "ACTIVE-SENDER-VALUE" )
        r = harness.client.get( self._URL )
        assert_no_accidental_500( r )
        assert r.json()[ "active_sender_id" ] == "ACTIVE-SENDER-VALUE"
        assert r.json()[ "user_email" ]       == _EMAIL

    def test_no_conversation_is_a_json_null_and_still_a_200( self, harness ):
        """
        🔴 THIS FIELD ROUTES A SPOKEN ANSWER. The UI tests it for null and asks the
        user when it is; a string like "" or "None" would read as a real sender and
        send the reply into a thread that does not exist. The null is asserted as
        null, not as falsy.
        """
        harness.repo.returns( "get_active_conversation", None )
        r = harness.client.get( self._URL )
        assert r.status_code == 200
        assert r.json()[ "active_sender_id" ] is None

    def test_it_asks_only_for_the_looked_up_recipient( self, harness ):
        harness.repo.returns( "get_active_conversation", None )
        harness.client.get( self._URL )
        harness.repo.assert_only_called( "get_active_conversation" )
        assert harness.repo.call_to( "get_active_conversation" ).first == uuid.UUID( _UID )

    def test_an_unknown_user_is_a_404( self, harness, user_lookup ):
        user_lookup[ "user" ] = None
        assert harness.client.get( self._URL ).status_code == 404

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_active_conversation", RuntimeError( "boom" ) )
        assert harness.client.get( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/project-sessions/{project}/{user_email}
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheProjectSessions:

    _URL = f"/api/notifications/project-sessions/Lupin/{_EMAIL}"

    def _session( self, sid, active=False ):
        return { "session_id"    : sid,
                 "sender_id"     : f"sender-{sid}",
                 "count"         : 3,
                 "is_active"     : active,
                 "last_activity" : datetime( 2026, 6, 15, 4, 30, tzinfo=_tz.utc ) }

    def test_it_returns_the_sessions_as_the_whole_body( self, harness ):
        harness.repo.returns( "get_sessions_for_project", [ self._session( "S1", True ) ] )
        r = harness.client.get( self._URL )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ 0 ][ "session_id" ] == "S1"
        assert body[ 0 ][ "is_active" ]  is True

    def test_the_project_is_lowercased_before_the_query( self, harness ):
        """
        🔴 THE PATH SEGMENT IS CASE-SENSITIVE AND THE STORED VALUE IS NOT. "Lupin"
        from a UI link must match "lupin" in the rows, so the lowercasing is the whole
        behaviour — and the path is deliberately mixed-case here, because a lowercase
        path would pass with or without it.
        """
        harness.repo.returns( "get_sessions_for_project", [] )
        harness.client.get( self._URL )
        call = harness.repo.call_to( "get_sessions_for_project" )
        assert call.args == ( uuid.UUID( _UID ), "lupin" )

    def test_every_sessions_timestamp_is_serialised_not_just_the_first( self, harness ):
        harness.repo.returns( "get_sessions_for_project",
                              [ self._session( "S1" ), self._session( "S2" ) ] )
        body = harness.client.get( self._URL ).json()
        assert all( isinstance( s[ "last_activity" ], str ) for s in body )

    def test_a_null_last_activity_survives_as_null( self, harness ):
        """The guard, not just the conversion — a bare .isoformat() on None would 500."""
        s = self._session( "S1" )
        s[ "last_activity" ] = None
        harness.repo.returns( "get_sessions_for_project", [ s ] )
        r = harness.client.get( self._URL )
        assert r.status_code == 200
        assert r.json()[ 0 ][ "last_activity" ] is None

    def test_no_sessions_is_an_empty_list_and_not_a_404( self, harness ):
        harness.repo.returns( "get_sessions_for_project", [] )
        r = harness.client.get( self._URL )
        assert r.status_code == 200
        assert r.json() == []

    def test_an_unknown_user_is_a_404( self, harness, user_lookup ):
        user_lookup[ "user" ] = None
        assert harness.client.get( self._URL ).status_code == 404

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_sessions_for_project", RuntimeError( "boom" ) )
        assert harness.client.get( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/notifications/generate-gist
# ═══════════════════════════════════════════════════════════════════════════════

class TestGeneratingASessionGist:

    _URL = "/api/notifications/generate-gist"

    @pytest.fixture( autouse=True )
    def _gister( self, monkeypatch ):
        """
        Replace the Gister on its own module — the handler imports it inside the
        function body, and the real one does a LanceDB read plus an LLM call.
        """
        import cosa.memory.gister as gister_module
        self.seen  = []
        self.title = "GIST-VALUE"
        outer = self

        class _Gister:
            def __init__( self, **kwargs ):
                outer.seen.append( ( "init", kwargs ) )

            def get_gist( self, text, prompt_key=None ):
                outer.seen.append( ( "get_gist", text, prompt_key ) )
                return outer.title

        monkeypatch.setattr( gister_module, "Gister", _Gister )

    def _gist_calls( self ):
        return [ c for c in self.seen if c[ 0 ] == "get_gist" ]

    def test_it_returns_the_generated_title( self, harness ):
        r = harness.client.post( self._URL, json={ "messages": [ "hello world" ] } )
        assert_no_accidental_500( r )
        assert r.json() == { "gist": "GIST-VALUE" }

    def test_abstracts_come_before_messages_in_the_combined_text( self, harness ):
        """
        Abstracts carry the richer signal, so they lead. Order is the whole claim and
        the two words are distinct, which is what makes a swapped concatenation a
        different string rather than the same one.
        """
        harness.client.post( self._URL, json={ "messages"  : [ "MSG" ],
                                               "abstracts" : [ "ABS" ] } )
        assert self._gist_calls()[ 0 ][ 1 ] == "ABS MSG"

    def test_only_the_first_five_of_each_are_sent( self, harness ):
        """
        Six of each, tagged by index, so the test names WHICH were dropped rather than
        only counting them — an off-by-one that kept the last five instead of the
        first five would produce the same length.
        """
        harness.client.post( self._URL, json={
            "messages"  : [ f"m{i}" for i in range( 6 ) ],
            "abstracts" : [ f"a{i}" for i in range( 6 ) ] } )
        combined = self._gist_calls()[ 0 ][ 1 ]
        assert combined == "a0 a1 a2 a3 a4 m0 m1 m2 m3 m4"
        assert "a5" not in combined and "m5" not in combined

    def test_it_asks_for_the_session_title_prompt( self, harness ):
        """The prompt key selects a 3-5 word template; the default one would return prose."""
        harness.client.post( self._URL, json={ "messages": [ "hello" ] } )
        assert self._gist_calls()[ 0 ][ 2 ] == "prompt template for session title"

    def test_an_empty_body_returns_the_placeholder_without_calling_the_llm( self, harness ):
        r = harness.client.post( self._URL, json={} )
        assert r.json() == { "gist": "Empty session" }
        assert self._gist_calls() == []

    def test_present_but_empty_lists_also_short_circuit( self, harness ):
        r = harness.client.post( self._URL, json={ "messages": [], "abstracts": [] } )
        assert r.json() == { "gist": "Empty session" }
        assert self._gist_calls() == []

    def test_whitespace_only_content_short_circuits_too( self, harness ):
        """
        🔴 THE THIRD KIND OF EMPTY, AND THE ONLY ONE THAT COSTS MONEY. The lists are
        non-empty, so the first guard passes them through; only the `combined.strip()`
        check stops a real LLM call that can learn nothing. Removing it is invisible
        to both tests above.
        """
        r = harness.client.post( self._URL, json={ "messages": [ "   ", "\t\n" ] } )
        assert r.json() == { "gist": "Empty session" }
        assert self._gist_calls() == [], "a whitespace-only session reached the LLM"

    def test_a_gister_fault_is_a_500( self, harness, monkeypatch ):
        import cosa.memory.gister as gister_module

        class _Boom:
            def __init__( self, **_kw ): pass
            def get_gist( self, *_a, **_kw ): raise RuntimeError( "model unavailable" )

        monkeypatch.setattr( gister_module, "Gister", _Boom )
        r = harness.client.post( self._URL, json={ "messages": [ "hello" ] } )
        assert r.status_code == 500
