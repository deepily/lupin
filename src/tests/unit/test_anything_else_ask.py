"""
The "Anything else?" ask helper — row `e2099400` (coverage frame ramp).

WHY THIS FILE EXISTS. `anything_else_ask.py` sat at 24% coverage with 45
statements uncovered, and it is not obscure code: it is the single source of
truth for the prompt every session fires when it finishes work, shared by both
the Stop hook and the deferred idle waiter. It entered the coverage denominator
on 2026-08-13 when the frame was widened past `cosa`, and nothing had been
written for it since.

THE MODULE'S OWN CONTRACT IS WHAT MADE IT WORTH TESTING RATHER THAN PADDING:
three of its five functions promise never to raise. `get_session_context` says
"Never raises exceptions"; `fire_anything_else_ask` says "Never raises — all
exceptions handled internally". A promise like that is only worth the test that
proves it, because the caller that relies on it — a Stop hook deciding whether
to block — has no other defence.

WHAT IS PINNED HERE:

· **Both arms of every branch, not just the happy one.** Each helper degrades
  rather than failing, so a test that only exercises success would pass against
  a version that had lost its error handling entirely.

· **The two-way answer normalisation.** `fire_anything_else_ask` collapses
  anything that is not "yes"/"no" into "timeout". Tested with a real timeout
  value AND with junk, because those reach the same line by different routes.

· **The qualifier survives.** A "[comment: ...]" rider is the mechanism by which
  a user redirects a session that was about to stop. Dropping it silently would
  look exactly like the user having said nothing.

· **The message changes shape with the gist.** Two different sentences, and the
  gist one embeds the text — a caller reading the generic message when a gist
  was computed would never know.

⚠️ NOTHING HERE TOUCHES THE NETWORK. `notify_user_sync` is patched at the name
this module imported it under, not at its source, so the patch actually binds.

See: row e2099400 · src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
"""

from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.claude_code.hooks.lib.anything_else_ask import (
    AnythingElseResult,
    build_ask_request,
    fire_anything_else_ask,
    get_session_context,
    summarize_task,
)
from lupin_cli.notifications.notification_models import (
    NotificationPriority,
    ResponseType,
)


MODULE = "lupin_cli.claude_code.hooks.lib.anything_else_ask"


# ---------------------------------------------------------------------------
# summarize_task — returns a gist, or None, and never raises
# ---------------------------------------------------------------------------

class TestSummarizeTask:

    @pytest.mark.parametrize( "empty", [ None, "", "   ", "\n\t " ] )
    def test_empty_input_returns_none_without_constructing_a_gister( self, empty ):
        """The guard is first for a reason — building a Gister costs a model
        load. If this ever stops short-circuiting, every no-op stop pays for it."""
        with patch( "cosa.memory.gister.Gister" ) as MockGister:
            assert summarize_task( empty ) is None
            MockGister.assert_not_called()

    def test_returns_the_gist_on_success( self ):
        with patch( "cosa.memory.gister.Gister" ) as MockGister:
            MockGister.return_value.get_gist.return_value = "fixed the cap"
            assert summarize_task( "I changed CC_MEM_LIMIT to 8G" ) == "fixed the cap"

    def test_an_empty_gist_becomes_none_rather_than_an_empty_string( self ):
        """An empty gist would render as `I'm finished "..."` — worse than the
        generic message, because it looks like the summary failed silently."""
        with patch( "cosa.memory.gister.Gister" ) as MockGister:
            MockGister.return_value.get_gist.return_value = ""
            assert summarize_task( "some real work" ) is None

    def test_a_raising_gister_returns_none_rather_than_propagating( self ):
        """THE PROMISE. The Stop hook calls this on every finish; a model error
        must degrade to the generic message, never take the hook down."""
        with patch( "cosa.memory.gister.Gister", side_effect=RuntimeError( "model unreachable" ) ):
            assert summarize_task( "some real work" ) is None


# ---------------------------------------------------------------------------
# get_session_context — "Never raises exceptions", per its own docstring
# ---------------------------------------------------------------------------

class TestGetSessionContext:

    def test_returns_topic_and_branch_when_both_resolve( self ):
        with patch( f"{MODULE}.get_session_metadata", return_value={ "session_topic": "Coverage gate" } ), \
             patch( f"{MODULE}.subprocess.check_output", return_value="wip-v0.2.0\n" ):
            assert get_session_context( "/some/repo" ) == ( "Coverage gate", "wip-v0.2.0" )

    def test_branch_is_stripped_of_its_trailing_newline( self ):
        """git rev-parse always emits one. Left in, it lands inside a markdown
        backtick span in the abstract and breaks the rendering."""
        with patch( f"{MODULE}.get_session_metadata", return_value={} ), \
             patch( f"{MODULE}.subprocess.check_output", return_value="  main  \n" ):
            _, branch = get_session_context( "/some/repo" )
            assert branch == "main"

    def test_no_cwd_means_no_git_call_at_all( self ):
        with patch( f"{MODULE}.get_session_metadata", return_value={ "session_topic": "T" } ), \
             patch( f"{MODULE}.subprocess.check_output" ) as check:
            topic, branch = get_session_context( None )
            assert ( topic, branch ) == ( "T", None )
            check.assert_not_called()

    def test_a_broken_bridge_does_not_lose_the_branch( self ):
        """The two lookups are independent and must degrade independently —
        otherwise one missing bridge file costs you both fields."""
        with patch( f"{MODULE}.get_session_metadata", side_effect=OSError( "no bridge" ) ), \
             patch( f"{MODULE}.subprocess.check_output", return_value="wip-x\n" ):
            assert get_session_context( "/some/repo" ) == ( None, "wip-x" )

    def test_a_failing_git_does_not_lose_the_topic( self ):
        with patch( f"{MODULE}.get_session_metadata", return_value={ "session_topic": "T" } ), \
             patch( f"{MODULE}.subprocess.check_output", side_effect=OSError( "not a repo" ) ):
            assert get_session_context( "/nowhere" ) == ( "T", None )

    def test_both_failing_returns_a_pair_of_nones_and_does_not_raise( self ):
        """THE PROMISE, stated in the docstring as 'Never raises exceptions'."""
        with patch( f"{MODULE}.get_session_metadata", side_effect=Exception( "boom" ) ), \
             patch( f"{MODULE}.subprocess.check_output", side_effect=Exception( "boom" ) ):
            assert get_session_context( "/nowhere" ) == ( None, None )


# ---------------------------------------------------------------------------
# build_ask_request — the payload the user actually sees
# ---------------------------------------------------------------------------

class TestBuildAskRequest:

    @pytest.fixture( autouse=True )
    def _quiet_context( self ):
        with patch( f"{MODULE}.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" ), \
             patch( f"{MODULE}.get_session_context", return_value=( None, None ) ):
            yield

    def test_the_gist_is_embedded_in_the_message( self ):
        req = build_ask_request( "sess", gist="shipped the cap fix" )
        assert "shipped the cap fix" in req.message

    def test_without_a_gist_the_message_is_the_generic_one( self ):
        req = build_ask_request( "sess" )
        assert "I've finished the current task" in req.message

    def test_the_two_messages_actually_differ( self ):
        """The control that gives the two tests above their meaning: if the gist
        were dropped on the floor, both would still contain plausible prose."""
        assert build_ask_request( "sess", gist="g" ).message != build_ask_request( "sess" ).message

    def test_the_fixed_fields_are_what_the_stop_hook_relies_on( self ):
        req = build_ask_request( "sess", timeout_seconds=42 )
        assert req.response_type            == ResponseType.YES_NO
        assert req.priority                 == NotificationPriority.MEDIUM
        assert req.timeout_seconds          == 42
        assert req.response_default         == "no"
        assert req.display_qualifier_widget is True
        assert req.sender_id                == "claude.code@lupin.deepily.ai#abc12345"

    def test_response_default_is_no_so_an_unanswered_ask_lets_the_session_stop( self ):
        """A default of "yes" would block every stop the user never answered —
        the session would sit forever believing it had been told to continue."""
        assert build_ask_request( "sess" ).response_default == "no"


class TestTheAbstract:

    @pytest.fixture( autouse=True )
    def _sender( self ):
        with patch( f"{MODULE}.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" ):
            yield

    def test_carries_both_topic_and_branch_when_both_exist( self ):
        with patch( f"{MODULE}.get_session_context", return_value=( "Coverage gate", "wip-x" ) ):
            abstract = build_ask_request( "sess" ).abstract
        assert "Coverage gate" in abstract and "wip-x" in abstract

    def test_carries_whichever_one_resolved( self ):
        with patch( f"{MODULE}.get_session_context", return_value=( "Only topic", None ) ):
            assert "Only topic" in build_ask_request( "sess" ).abstract
        with patch( f"{MODULE}.get_session_context", return_value=( None, "only-branch" ) ):
            assert "only-branch" in build_ask_request( "sess" ).abstract

    def test_is_none_rather_than_an_empty_string_when_neither_resolved( self ):
        """An empty abstract renders as a blank card. None omits it."""
        with patch( f"{MODULE}.get_session_context", return_value=( None, None ) ):
            assert build_ask_request( "sess" ).abstract is None


# ---------------------------------------------------------------------------
# fire_anything_else_ask — "Never raises", per its own docstring
# ---------------------------------------------------------------------------

def _fire( response_value, **kw ):
    """Drive one fire with a stubbed transport. notify_user_sync is patched at
    the name THIS module imported it under, so the patch actually binds."""
    response = MagicMock()
    response.response_value = response_value
    with patch( f"{MODULE}.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" ), \
         patch( f"{MODULE}.get_session_context", return_value=( None, None ) ), \
         patch( f"{MODULE}.notify_user_sync", return_value=response ):
        return fire_anything_else_ask( "sess", **kw )


class TestFireOutcomes:

    def test_yes_is_returned_as_yes( self ):
        assert _fire( "yes" ).answer == "yes"

    def test_no_is_returned_as_no( self ):
        assert _fire( "no" ).answer == "no"

    @pytest.mark.parametrize( "value", [ "timeout", "", None, "maybe", "YES!" ] )
    def test_anything_that_is_not_yes_or_no_normalises_to_timeout( self, value ):
        """Reached by two different routes — a real timeout and junk — so both
        are exercised rather than assumed equivalent."""
        assert _fire( value ).answer == "timeout"

    def test_yes_and_junk_do_not_collapse_to_the_same_answer( self ):
        """The control: a normaliser that returned "timeout" unconditionally
        would satisfy every parametrised case above."""
        assert _fire( "yes" ).answer != _fire( "garbage" ).answer

    def test_the_raw_value_is_preserved_for_the_log( self ):
        assert _fire( "no [comment: try the other branch]" ).raw_value == "no [comment: try the other branch]"

    def test_a_none_raw_value_becomes_an_empty_string_not_none( self ):
        """raw_value is typed str; a None would break any caller formatting it."""
        assert _fire( None ).raw_value == ""


class TestTheQualifierSurvives:

    def test_a_comment_rider_is_extracted_alongside_the_answer( self ):
        """This is how a user redirects a session that was about to stop.
        Dropped silently, it is indistinguishable from them saying nothing."""
        result = _fire( "no [comment: actually check the other branch]" )
        assert result.answer == "no"
        assert result.qualifier is not None
        assert "other branch" in result.qualifier

    def test_a_plain_answer_carries_no_qualifier( self ):
        assert _fire( "no" ).qualifier is None


class TestFireNeverRaises:

    def test_a_transport_failure_becomes_an_error_result( self ):
        """THE PROMISE — 'Never raises, all exceptions handled internally'. The
        Stop hook has no other defence if this is wrong."""
        with patch( f"{MODULE}.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#abc12345" ), \
             patch( f"{MODULE}.get_session_context", return_value=( None, None ) ), \
             patch( f"{MODULE}.notify_user_sync", side_effect=ConnectionError( "server down" ) ):
            result = fire_anything_else_ask( "sess" )

        assert isinstance( result, AnythingElseResult )
        assert result.answer    == "error"
        assert result.qualifier is None
        assert result.raw_value == ""
        assert "server down" in result.error

    def test_a_failure_while_BUILDING_the_request_is_also_caught( self ):
        """The try block covers the build too, not only the send — a bad session
        id must not escape as an exception either."""
        with patch( f"{MODULE}.build_sender_id_for_cc", side_effect=ValueError( "bad session id" ) ):
            result = fire_anything_else_ask( "sess" )

        assert result.answer == "error"
        assert "bad session id" in result.error

    def test_error_is_none_on_every_successful_path( self ):
        """Otherwise a caller checking `if result.error` would treat a good
        answer as a failure."""
        for value in ( "yes", "no", "timeout", "junk" ):
            assert _fire( value ).error is None
