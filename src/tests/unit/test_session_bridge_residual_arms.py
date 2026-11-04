"""
Pins the session_bridge arms that no other test reached.

They are the skip arms of the scanners, the two fallbacks of the project resolver and the
error arms of the session-file finder.

Each test builds the files the arm reads. It checks what the function returns because of them.
Where a scanner skips a file, that file holds a decoy. Reading the decoy would change the answer.
"""

import json
import os
import time

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge as sb

DEAD_PID = 2147483646


@pytest.fixture
def sessions( tmp_path, monkeypatch ):
    """An empty bridge directory standing in for SESSION_DIR."""
    monkeypatch.setattr( sb, "SESSION_DIR", tmp_path )
    return tmp_path


def _write( path, data ):
    path.write_text( json.dumps( data ) )
    return path


# ---------------------------------------------------------------- _find_session_file

def test_an_unreadable_proc_stat_falls_through_to_the_cwd_fallback( sessions, monkeypatch ):
    """No /proc entry for the parent is not an error; the cwd fallback still answers."""
    monkeypatch.setattr( sb.os, "getppid", lambda: DEAD_PID )
    bridge = _write( sessions / f"cc-{os.getpid()}.json", { "cwd": os.getcwd() } )

    assert sb._find_session_file() == ( bridge, sb.SOURCE_CWD_FALLBACK )


def test_a_corrupt_bridge_is_skipped_and_the_next_newest_matching_one_answers( sessions, monkeypatch ):
    live_parent = os.getppid()
    monkeypatch.setattr( sb.os, "getppid", lambda: DEAD_PID )
    good = _write( sessions / f"cc-{live_parent}.json", { "cwd": os.getcwd() } )
    bad  = sessions / f"cc-{os.getpid()}.json"
    bad.write_text( "{not json" )
    now = time.time()
    os.utime( good, ( now - 100, now - 100 ) )
    os.utime( bad,  ( now, now ) )

    assert sb._find_session_file() == ( good, sb.SOURCE_CWD_FALLBACK )


# ---------------------------------------------------------------- project_from_bridge_cwd

def test_a_worktree_whose_admin_dir_is_gone_is_named_for_the_repo_its_gitlink_points_at( tmp_path ):
    wt = tmp_path / "lupin-wt-gone"
    wt.mkdir()
    ( wt / ".git" ).write_text( "gitdir: /nowhere/MainRepo/.git/worktrees/lupin-wt-gone\n" )

    assert sb.project_from_bridge_cwd( str( wt ) ) == "mainrepo"


def test_a_gitlink_naming_no_repo_gives_the_directorys_own_lowercased_name( tmp_path ):
    wt = tmp_path / "SomeCheckout"
    wt.mkdir()
    ( wt / ".git" ).write_text( "not a gitlink at all\n" )

    assert sb.project_from_bridge_cwd( str( wt ) ) == "somecheckout"


def test_a_cwd_that_cannot_be_resolved_answers_none( tmp_path ):
    assert sb.project_from_bridge_cwd( str( tmp_path ) + "/bad\0name" ) is None


# ---------------------------------------------------------------- build_sender_id_for_cc

def test_with_no_session_id_given_the_id_comes_from_the_current_session( monkeypatch ):
    monkeypatch.setattr( sb, "get_claude_session_id", lambda: "abcdef1234567890" )
    monkeypatch.setattr( sb, "_resolve_project_from_bridge_cwd", lambda: "someproj" )

    got = sb.build_sender_id_for_cc()

    assert got.endswith( "#abcdef12" )
    assert "someproj" in got


# ---------------------------------------------------------------- find_session_by_id

def test_a_buffer_file_is_never_matched_even_when_it_is_the_newest( sessions ):
    real   = _write( sessions / "cc-4243.json",        { "session_id": "sid-1", "marker": "real" } )
    buffer = _write( sessions / "cc-4242-buffer.json", { "session_id": "sid-1", "marker": "buffer" } )
    now = time.time()
    os.utime( real,   ( now - 100, now - 100 ) )
    os.utime( buffer, ( now, now ) )

    assert sb.find_session_by_id( "sid-1", check_pid=False )[ "marker" ] == "real"


# ---------------------------------------------------------------- find_active_speakerphone_sessions

def test_no_bridge_directory_means_no_speakerphone_sessions( tmp_path, monkeypatch ):
    monkeypatch.setattr( sb, "SESSION_DIR", tmp_path / "absent" )

    assert sb.find_active_speakerphone_sessions() == []


def test_buffer_and_listener_files_and_idless_files_are_not_speakerphone_sessions( sessions, monkeypatch ):
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    _write( sessions / "cc-1-buffer.json",   { "speakerphone_on": True, "session_id": "from-buffer" } )
    _write( sessions / "cc-2-listener.json", { "speakerphone_on": True, "session_id": "from-listener" } )
    _write( sessions / "cc-3.json",          { "speakerphone_on": True } )
    keep = _write( sessions / "cc-4.json",   { "speakerphone_on": True, "session_id": "kept" } )

    assert sb.find_active_speakerphone_sessions() == [ ( keep, "kept" ) ]


# ---------------------------------------------------------------- prune_dead_persona_bridges

def test_a_bridge_that_cannot_be_rewritten_is_not_counted_as_pruned( sessions, monkeypatch ):
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: True )
    dead = _write( sessions / f"cc-{DEAD_PID}.json", { "voice_persona": { "name": "maria" } } )

    real_write = sb.atomic_write_json
    monkeypatch.setattr( sb, "atomic_write_json", lambda path, data: False )
    assert sb.prune_dead_persona_bridges() == 0
    assert json.loads( dead.read_text() )[ "voice_persona" ] == { "name": "maria" }

    monkeypatch.setattr( sb, "atomic_write_json", real_write )
    assert sb.prune_dead_persona_bridges() == 1
    assert json.loads( dead.read_text() )[ "voice_persona" ] is None


# ---------------------------------------------------------------- find_active_sessions

def test_a_live_bridge_with_no_session_id_is_reported_as_unreadable_when_asked( sessions, monkeypatch ):
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    nameless = _write( sessions / "cc-5.json", { "voice_persona": { "name": "maria" } } )
    unreadable = []

    assert sb.find_active_sessions( unreadable_out=unreadable ) == []
    assert unreadable == [ nameless ]


def test_the_same_bridge_is_dropped_quietly_when_no_report_list_is_given( sessions, monkeypatch ):
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    _write( sessions / "cc-5.json", { "voice_persona": { "name": "maria" } } )

    assert sb.find_active_sessions() == []


# ---------------------------------------------------------------- find_session_by_tmux

def test_buffer_and_listener_files_are_never_matched_by_their_tmux_session( sessions ):
    """Both decoys name the tmux session asked for; only a scan that skips them answers None."""
    _write( sessions / "cc-77-buffer.json",   { "tmux_session": "work", "marker": "buffer" } )
    _write( sessions / "cc-78-listener.json", { "tmux_session": "work", "marker": "listener" } )
    _write( sessions / f"cc-{os.getpid()}.json", { "tmux_session": "other", "marker": "real" } )

    assert sb.find_session_by_tmux( "work" ) is None
    assert sb.find_session_by_tmux( "other" )[ "marker" ] == "real"


# ---------------------------------------------------------------- find_dead_sessions

def test_buffer_and_listener_files_never_make_a_candidate_dead( sessions, monkeypatch ):
    """The decoys carry a dead cc_pid and the candidate id. Skipping them leaves it alive."""
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: True )
    _write( sessions / "cc-91-buffer.json",   { "session_id": "cand-buffer-0001",   "cc_pid": DEAD_PID } )
    _write( sessions / "cc-92-listener.json", { "session_id": "cand-listener-0002", "cc_pid": DEAD_PID } )
    candidates = [ "cand-buffer-0001", "cand-listener-0002" ]

    assert sb.find_dead_sessions( candidates ) == set()

    _write( sessions / f"cc-{DEAD_PID}.json", { "session_id": "cand-buffer-0001" } )
    assert sb.find_dead_sessions( candidates ) == { "cand-buffer-0001" }
