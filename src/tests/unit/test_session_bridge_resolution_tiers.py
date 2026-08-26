"""
The four session-id resolution entry points in `session_bridge` — row `e2099400`.

WHY THESE FOUR. `get_claude_session_id`, `resolve_stable_session_id`,
`wait_for_session_id` and `get_session_metadata` held the module's four largest
dark blocks (lines 442-453, 489-492, 530-542, 745-761). They are the same
question asked four ways — "which seat am I?" — and every caller in the hook
package starts by asking one of them.

🔴 THE PROPERTY THAT MATTERS MOST IS THE CACHING RULE, and it is a safety rule
rather than a performance one. The module caches a resolved id ONLY when the
bridge file was found by pid — never when it was found by the cwd fallback,
because the cwd fallback can select a PEER SEAT sharing the directory. Caching a
neighbour's id would pin this process to the wrong seat for its whole life, and
every later lookup would confirm the wrong answer from cache without re-reading
anything. `sessions_dir.py`'s docstring records what that class of mistake
already cost: three live seats' bridges overwritten in one afternoon.

So the cwd-fallback tests here are not coverage padding — they are the tests
that fail if someone "simplifies" the caching by dropping the source check.

WHAT IS PINNED:

· **The resolution order**: cache, then `CLAUDE_SESSION_ID`, then the bridge
  file, then a fallback uuid. Each tier is checked in isolation AND the
  precedence between them is checked, because a tier that works alone can still
  be shadowed by one above it.

· **A pid-matched id is cached; a cwd-matched id is NOT.** Both directions, with
  a test that asserts the two routes disagree — the control that a single-sided
  test cannot give.

· **Every one of the four falls back rather than raising.** These run on the
  boot path; an unreadable or malformed bridge must degrade to a fallback id,
  not take the session start down.

· **`get_session_metadata` backfills `stable_session_id` but never overwrites
  one.** Old bridges predate the field, and clobbering a real one would break
  the link between a re-spun seat and its original.

· **`wait_for_session_id` polls and then gives up**, returning the fallback
  rather than blocking forever.

⚠️ THE MODULE-LEVEL CACHE IS RESET BEFORE EVERY TEST via
`clear_cached_session_id()`. Without it the first test to resolve an id would
decide the answer for every test after it, and the suite would pass in one order
and fail in another.

⚠️ NO REAL WAITING. `time.sleep` is patched and `time.monotonic` is driven from
a list, so the poll loop is exercised in microseconds.

See: row e2099400
"""

import json
from unittest.mock import patch

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge as sb


MODULE = "lupin_cli.claude_code.hooks.lib.session_bridge"

PID_SOURCE = "ppid"
CWD_SOURCE = sb.SOURCE_CWD_FALLBACK


@pytest.fixture( autouse=True )
def reset_cache( monkeypatch ):
    """The cache is a module global. Left set, the first test to resolve an id
    decides the answer for every test after it."""
    sb.clear_cached_session_id()
    monkeypatch.delenv( "CLAUDE_SESSION_ID", raising=False )
    monkeypatch.delenv( "CLAUDE_TRANSCRIPT_PATH", raising=False )
    yield
    sb.clear_cached_session_id()


def _bridge_file( tmp_path, data ):
    p = tmp_path / "cc-1234.json"
    p.write_text( json.dumps( data ) )
    return p


class TestGetClaudeSessionIdResolutionOrder:

    def test_the_env_var_wins_when_set( self, monkeypatch ):
        monkeypatch.setenv( "CLAUDE_SESSION_ID", "from-env" )
        with patch( f"{MODULE}._find_session_file" ) as find:
            assert sb.get_claude_session_id() == "from-env"
        find.assert_not_called()

    def test_the_bridge_file_is_used_when_there_is_no_env_var( self, tmp_path ):
        with patch( f"{MODULE}._find_session_file",
                    return_value=( tmp_path / "cc-1.json", PID_SOURCE ) ), \
             patch( f"{MODULE}._read_session_file", return_value="from-file" ):
            assert sb.get_claude_session_id() == "from-file"

    def test_a_missing_bridge_falls_back_to_the_generated_id( self ):
        with patch( f"{MODULE}._find_session_file", return_value=None ):
            assert sb.get_claude_session_id() == sb._fallback_session_id

    def test_an_unreadable_bridge_falls_back_rather_than_raising( self, tmp_path ):
        """_read_session_file returning None is how it reports a bad file."""
        with patch( f"{MODULE}._find_session_file",
                    return_value=( tmp_path / "cc-1.json", PID_SOURCE ) ), \
             patch( f"{MODULE}._read_session_file", return_value=None ):
            assert sb.get_claude_session_id() == sb._fallback_session_id

    def test_a_cached_value_short_circuits_everything( self, monkeypatch ):
        monkeypatch.setenv( "CLAUDE_SESSION_ID", "first" )
        assert sb.get_claude_session_id() == "first"

        monkeypatch.setenv( "CLAUDE_SESSION_ID", "second" )
        with patch( f"{MODULE}._find_session_file" ) as find:
            assert sb.get_claude_session_id() == "first"    # cache, not the new env
        find.assert_not_called()


class TestTheCachingRuleIsASafetyRule:
    """A cwd-matched id may belong to a PEER SEAT sharing the directory."""

    def test_a_pid_matched_id_is_cached( self, tmp_path ):
        with patch( f"{MODULE}._find_session_file",
                    return_value=( tmp_path / "cc-1.json", PID_SOURCE ) ), \
             patch( f"{MODULE}._read_session_file", return_value="pid-match" ):
            sb.get_claude_session_id()

        with patch( f"{MODULE}._find_session_file" ) as find:
            assert sb.get_claude_session_id() == "pid-match"
        find.assert_not_called()                    # answered from cache

    def test_a_cwd_matched_id_is_returned_but_never_cached( self, tmp_path ):
        """Pinning this process to a neighbour's id would make every later
        lookup confirm the wrong answer without re-reading anything."""
        with patch( f"{MODULE}._find_session_file",
                    return_value=( tmp_path / "cc-1.json", CWD_SOURCE ) ), \
             patch( f"{MODULE}._read_session_file", return_value="cwd-guess" ):
            assert sb.get_claude_session_id() == "cwd-guess"

        with patch( f"{MODULE}._find_session_file" ) as find:
            find.return_value = None
            assert sb.get_claude_session_id() == sb._fallback_session_id
        find.assert_called()                        # re-resolved, not cached

    def test_the_two_routes_disagree_about_caching( self, tmp_path ):
        """THE CONTROL. An implementation that cached unconditionally would
        satisfy the pid test above; one that never cached would satisfy the cwd
        test. Only the pair distinguishes them.

        ⚠️ BOTH ROUTES RESOLVE THE SAME ID ON PURPOSE. An earlier draft gave
        them different ids and compared those — which differ whether or not
        caching happened, so the assertion held under a mutation that cached
        unconditionally. Holding the id fixed makes the ONLY difference
        cached-vs-re-resolved, which is the thing under test."""
        SAME = "identical-id"

        def second_lookup_after( source ):
            sb.clear_cached_session_id()
            with patch( f"{MODULE}._find_session_file",
                        return_value=( tmp_path / "cc-1.json", source ) ), \
                 patch( f"{MODULE}._read_session_file", return_value=SAME ):
                sb.get_claude_session_id()
            with patch( f"{MODULE}._find_session_file", return_value=None ):
                return sb.get_claude_session_id()

        assert second_lookup_after( PID_SOURCE ) == SAME                      # cached
        assert second_lookup_after( CWD_SOURCE ) == sb._fallback_session_id   # re-resolved
        assert second_lookup_after( PID_SOURCE ) != second_lookup_after( CWD_SOURCE )


class TestResolveStableSessionId:

    def test_a_stable_id_in_the_bridge_replaces_the_transient_one( self, tmp_path ):
        path = _bridge_file( tmp_path, { "session_id": "transient",
                                         "stable_session_id": "stable-1" } )
        with patch( f"{MODULE}._find_session_file", return_value=( path, PID_SOURCE ) ):
            assert sb.resolve_stable_session_id( "transient" ) == "stable-1"

    def test_a_bridge_without_the_field_leaves_the_transient_id_alone( self, tmp_path ):
        """Old bridges predate the field. Returning None here would hand every
        caller a null session id."""
        path = _bridge_file( tmp_path, { "session_id": "transient" } )
        with patch( f"{MODULE}._find_session_file", return_value=( path, PID_SOURCE ) ):
            assert sb.resolve_stable_session_id( "transient" ) == "transient"

    def test_a_blank_stable_id_is_treated_as_absent( self, tmp_path ):
        path = _bridge_file( tmp_path, { "stable_session_id": "" } )
        with patch( f"{MODULE}._find_session_file", return_value=( path, PID_SOURCE ) ):
            assert sb.resolve_stable_session_id( "transient" ) == "transient"

    def test_no_bridge_leaves_the_transient_id_alone( self ):
        with patch( f"{MODULE}._find_session_file", return_value=None ):
            assert sb.resolve_stable_session_id( "transient" ) == "transient"

    def test_a_malformed_bridge_leaves_the_transient_id_alone( self, tmp_path ):
        path = tmp_path / "cc-1.json"
        path.write_text( "{ not json" )
        with patch( f"{MODULE}._find_session_file", return_value=( path, PID_SOURCE ) ):
            assert sb.resolve_stable_session_id( "transient" ) == "transient"

    def test_an_unreadable_bridge_leaves_the_transient_id_alone( self, tmp_path ):
        path = _bridge_file( tmp_path, { "stable_session_id": "stable-1" } )
        with patch( f"{MODULE}._find_session_file", return_value=( path, PID_SOURCE ) ), \
             patch( "builtins.open", side_effect=OSError( "gone" ) ):
            assert sb.resolve_stable_session_id( "transient" ) == "transient"

    def test_an_empty_transient_id_is_returned_unchanged_without_a_lookup( self ):
        with patch( f"{MODULE}._find_session_file" ) as find:
            assert sb.resolve_stable_session_id( "" ) == ""
        find.assert_not_called()


class TestWaitForSessionId:

    def test_the_env_var_short_circuits_the_poll_entirely( self, monkeypatch ):
        monkeypatch.setenv( "CLAUDE_SESSION_ID", "from-env" )
        with patch( f"{MODULE}._find_session_file" ) as find, \
             patch( f"{MODULE}.time.sleep" ) as sleep:
            assert sb.wait_for_session_id() == "from-env"
        find.assert_not_called()
        sleep.assert_not_called()

    def test_it_returns_the_id_as_soon_as_the_bridge_appears( self, tmp_path ):
        appearances = [ None, None, ( tmp_path / "cc-1.json", PID_SOURCE ) ]
        with patch( f"{MODULE}._find_session_file", side_effect=appearances ), \
             patch( f"{MODULE}._read_session_file", return_value="late-arrival" ), \
             patch( f"{MODULE}.time.sleep" ), \
             patch( f"{MODULE}.time.monotonic", side_effect=[ 0.0, 1.0, 2.0, 3.0 ] ):
            assert sb.wait_for_session_id( timeout=10.0 ) == "late-arrival"

    def test_an_expired_budget_returns_the_fallback_rather_than_blocking( self ):
        with patch( f"{MODULE}._find_session_file", return_value=None ), \
             patch( f"{MODULE}.time.sleep" ), \
             patch( f"{MODULE}.time.monotonic", side_effect=[ 0.0, 100.0 ] ):
            assert sb.wait_for_session_id( timeout=1.0 ) == sb._fallback_session_id

    def test_a_bridge_that_reads_back_empty_keeps_polling( self, tmp_path ):
        """A half-written file is not an answer."""
        with patch( f"{MODULE}._find_session_file",
                    return_value=( tmp_path / "cc-1.json", PID_SOURCE ) ), \
             patch( f"{MODULE}._read_session_file", side_effect=[ None, "eventually" ] ), \
             patch( f"{MODULE}.time.sleep" ), \
             patch( f"{MODULE}.time.monotonic", side_effect=[ 0.0, 1.0, 2.0, 3.0 ] ):
            assert sb.wait_for_session_id( timeout=10.0 ) == "eventually"

    def test_a_cwd_matched_id_is_not_cached_here_either( self, tmp_path ):
        """Same safety rule as the non-blocking path — the wait does not get a
        weaker one just because it tried harder."""
        with patch( f"{MODULE}._find_session_file",
                    return_value=( tmp_path / "cc-1.json", CWD_SOURCE ) ), \
             patch( f"{MODULE}._read_session_file", return_value="cwd-guess" ), \
             patch( f"{MODULE}.time.sleep" ), \
             patch( f"{MODULE}.time.monotonic", side_effect=[ 0.0, 1.0 ] ):
            assert sb.wait_for_session_id( timeout=10.0 ) == "cwd-guess"

        with patch( f"{MODULE}._find_session_file", return_value=None ):
            assert sb.get_claude_session_id() == sb._fallback_session_id


class TestGetSessionMetadata:

    def test_the_env_var_route_reports_its_own_source( self, monkeypatch ):
        monkeypatch.setenv( "CLAUDE_SESSION_ID", "from-env" )
        monkeypatch.setenv( "CLAUDE_TRANSCRIPT_PATH", "/tmp/t.jsonl" )
        meta = sb.get_session_metadata()
        assert meta[ "session_id" ]      == "from-env"
        assert meta[ "transcript_path" ] == "/tmp/t.jsonl"
        assert meta[ "source" ]          == "env_var"

    def test_a_bridge_read_is_stamped_with_its_resolution_route( self, tmp_path ):
        """`resolution_source` is how a reader later tells a pid match from a
        cwd guess — without it the two are indistinguishable in the payload."""
        path = _bridge_file( tmp_path, { "session_id": "s1",
                                         "stable_session_id": "stable-1" } )
        with patch( f"{MODULE}._find_session_file", return_value=( path, CWD_SOURCE ) ):
            meta = sb.get_session_metadata()
        assert meta[ "source" ]            == "session_file"
        assert meta[ "resolution_source" ] == CWD_SOURCE
        assert meta[ "_bridge_path" ]      == str( path )

    def test_a_missing_stable_id_is_backfilled_from_the_session_id( self, tmp_path ):
        path = _bridge_file( tmp_path, { "session_id": "s1" } )
        with patch( f"{MODULE}._find_session_file", return_value=( path, PID_SOURCE ) ):
            assert sb.get_session_metadata()[ "stable_session_id" ] == "s1"

    def test_an_existing_stable_id_is_never_overwritten( self, tmp_path ):
        """Clobbering it would break the link between a re-spun seat and its
        original — which is the only thing stable_session_id is for."""
        path = _bridge_file( tmp_path, { "session_id": "s2", "stable_session_id": "s1" } )
        with patch( f"{MODULE}._find_session_file", return_value=( path, PID_SOURCE ) ):
            assert sb.get_session_metadata()[ "stable_session_id" ] == "s1"

    def test_no_bridge_yields_the_fallback_shape( self ):
        with patch( f"{MODULE}._find_session_file", return_value=None ):
            meta = sb.get_session_metadata()
        assert meta[ "source" ]            == "fallback"
        assert meta[ "session_id" ]        == sb._fallback_session_id
        assert meta[ "stable_session_id" ] == sb._fallback_session_id

    def test_a_malformed_bridge_yields_the_fallback_shape( self, tmp_path ):
        path = tmp_path / "cc-1.json"
        path.write_text( "{ not json" )
        with patch( f"{MODULE}._find_session_file", return_value=( path, PID_SOURCE ) ):
            assert sb.get_session_metadata()[ "source" ] == "fallback"

    def test_an_unreadable_bridge_yields_the_fallback_shape( self, tmp_path ):
        path = _bridge_file( tmp_path, { "session_id": "s1" } )
        with patch( f"{MODULE}._find_session_file", return_value=( path, PID_SOURCE ) ), \
             patch( "builtins.open", side_effect=OSError( "gone" ) ):
            assert sb.get_session_metadata()[ "source" ] == "fallback"

    def test_the_fallback_shape_always_carries_both_id_fields( self ):
        """Callers read stable_session_id unconditionally; a fallback missing it
        would KeyError on the one path least able to afford it."""
        with patch( f"{MODULE}._find_session_file", return_value=None ):
            meta = sb.get_session_metadata()
        assert "session_id" in meta and "stable_session_id" in meta
