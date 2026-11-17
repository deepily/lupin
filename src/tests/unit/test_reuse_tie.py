"""
The tie from a duplicate to the lookup that should have caught it.

The call logs are fixtures written here in the shape the logging middleware writes, with the caller as `<persona> <session id>`.
The commits are made in a throwaway git repository with fixed committer times, so the "before the commit" cut is exact.
Nothing here calls a model or touches the shared data folder.
"""
import os
import subprocess

import pytest

from lupin_mcp import reuse_tie as rt

RID_A, RID_B, RID_C, RID_D = "a" * 16, "b" * 16, "c" * 16, "d" * 16
ENV = { **os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t" }


def call( who, session, rid, ts, tool="check_exists", error=None ):
    """Ensures: a call log record in the shape the middleware writes."""
    return { "ts": ts, "tool": tool, "caller": f"{who} {session}", "session": session, "receipt_id": rid, "error": error, "args": "{}" }


def row( *pairs ):
    """Ensures: a refusals.jsonl record holding the given ( symbol id, receipt id ) pairs."""
    return { "doc": "d" * 64, "n": 1, "line": "x", "status": "accepted", "reasons": [], "pairs": [ list( p ) for p in pairs ] }


def commit( repo, message, when ):
    """Ensures: makes an empty commit at a fixed committer time and returns its sha."""
    env = { **ENV, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when }
    subprocess.run( [ "git", "-C", str( repo ), "commit", "-q", "--allow-empty", "--no-verify", "-m", message ], check=True, capture_output=True, env=env )
    return subprocess.run( [ "git", "-C", str( repo ), "rev-parse", "HEAD" ], check=True, capture_output=True, text=True, env=ENV ).stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    """Ensures: a throwaway repository, with the commits made by each test."""
    subprocess.run( [ "git", "-C", str( tmp_path ), "init", "-q", "-b", "main" ], check=True, capture_output=True, env=ENV )
    return tmp_path


LOG = [ call( "john", "a1111111", RID_A, "2026-11-02T10:00:00+00:00" ),
        call( "john", "a2222222", RID_B, "2026-11-02T11:00:00+00:00" ),                          # a later session of the same persona
        call( "john", "a2222222", RID_C, "2026-11-02T11:30:00+00:00", tool="fetch_similar" ),     # holds a symbol id, not a need
        call( "john", "a2222222", RID_D, "2026-11-02T11:40:00+00:00", error="CALL_FAILED" ),     # failed
        call( "john", "a2222222", "e" * 16, "2026-11-02T13:00:00+00:00" ),                       # after the commit
        call( "Chloé", "c3333333", "f" * 16, "2026-11-02T11:45:00+00:00" ),
        call( "Mr. Radio", "b4444444", "9" * 16, "2026-11-02T11:50:00+00:00" ) ]
NOON = "2026-11-02T12:00:00+00:00"


def test_the_commit_facts_are_read_from_a_real_commit( repo ):
    sha   = commit( repo, "[LUPIN] Feat: x (John; checked by Chloé)", NOON )
    facts = rt.commit_facts( repo, sha )
    assert facts[ "time" ].isoformat() == NOON and facts[ "message" ].startswith( "[LUPIN] Feat: x (John; checked by Chloé)" )
    with pytest.raises( ValueError, match="is not a commit" ):
        rt.commit_facts( repo, "0" * 40 )


def test_a_ruling_line_names_the_receipt_and_the_commit_is_never_read( tmp_path ):
    got = rt.find_tie( "m.new", [ row( ( "m.new", RID_A ) ) ], LOG, tmp_path / "not-a-repo", "0" * 40 )
    assert got == { "tie": "ruling", "receipt_id": RID_A, "session": "a1111111", "tool": "check_exists" }, "no repository was needed, so the commit was not read"


def test_a_ruling_receipt_that_is_not_in_the_log_still_ties_with_no_session( tmp_path ):
    assert rt.find_tie( "m.new", [ row( ( "m.new", "1" * 16 ) ) ], LOG, tmp_path, "0" * 40 ) == { "tie": "ruling", "receipt_id": "1" * 16, "session": None, "tool": None }


def test_the_latest_record_wins_and_a_fetch_similar_receipt_reports_its_tool( tmp_path ):
    rows = [ row( ( "m.new", RID_A ) ), row( ( "m.other", RID_B ), ( "m.new", RID_C ) ) ]
    got  = rt.find_tie( "m.new", rows, LOG, tmp_path, "0" * 40 )
    assert got[ "receipt_id" ] == RID_C and got[ "tool" ] == "fetch_similar" and got[ "session" ] == "a2222222", "tool tells the caller there is no need text to audit"


def test_a_token_in_the_receipt_place_is_not_a_receipt_and_falls_through_to_the_heuristic( repo ):
    sha = commit( repo, "[LUPIN] Feat: x (John)", NOON )
    got = rt.find_tie( "m.new", [ row( ( "m.new", "excluded" ), ( "m.new", "unindexed" ) ) ], LOG, repo, sha )
    assert got[ "tie" ] == "heuristic" and got[ "receipt_id" ] == RID_B


def test_the_heuristic_takes_the_writers_latest_check_exists_receipt_before_the_commit( repo ):
    sha = commit( repo, "[LUPIN] Feat: x (John; checked and approved by Rachel)", NOON )
    got = rt.find_tie( "m.new", [], LOG, repo, sha )
    assert got == { "tie": "heuristic", "receipt_id": RID_B, "session": "a2222222", "tool": "check_exists", "persona": "john" }
    for other in ( "e" * 16, RID_C, RID_D, "f" * 16 ): assert got[ "receipt_id" ] != other, "not after the commit, not fetch_similar, not failed, not another persona"


def test_accents_and_spaces_are_normalised_and_a_longer_word_is_not_a_persona( repo ):
    sha = commit( repo, "[LUPIN] Fix: y (Chloé)", NOON )
    assert rt.find_tie( "m.new", [], LOG, repo, sha )[ "persona" ] == "chloe"
    sha = commit( repo, "[LUPIN] Fix: z (Mr. Radio)", NOON )
    got = rt.find_tie( "m.new", [], LOG, repo, sha )
    assert got[ "persona" ] == "mr radio" and got[ "receipt_id" ] == "9" * 16 and got[ "session" ] == "b4444444"
    sha = commit( repo, "[LUPIN] Fix: w (Johnson)", NOON )
    assert rt.find_tie( "m.new", [], LOG, repo, sha )[ "tie" ] == "none", "a longer word that contains a persona's name is not that persona"


def test_a_message_that_names_more_than_one_lookup_persona_gives_no_tie_with_a_reason( repo ):
    for message in ( "[LUPIN] Fix: y (John; checked and approved by Chloé)", "[LUPIN] Fix: z (Mr. Radio, then Chloé)", "[LUPIN] Fix: v (Chloé; reviewed with Mr. Radio and John)" ):
        got = rt.find_tie( "m.new", [], LOG, repo, commit( repo, message, NOON ) )
        assert got[ "tie" ] == "none" and "names more than one lookup persona" in got[ "reason" ] and "receipt_id" not in got, message
    assert "chloe, john" in rt.find_tie( "m.new", [], LOG, repo, commit( repo, "[LUPIN] Fix: u (John and Chloé)", NOON ) )[ "reason" ], "the reason names them, sorted"


def test_no_persona_in_the_message_gives_no_tie_with_a_reason( repo ):
    sha = commit( repo, "[LUPIN] Fix: nobody is named here", NOON )
    got = rt.find_tie( "m.new", [], LOG, repo, sha )
    assert got == { "tie": "none", "reason": "the commit message names no persona that made a lookup in the call log" }


def test_a_writer_with_no_lookup_before_the_commit_gives_no_tie_with_a_reason( repo ):
    sha = commit( repo, "[LUPIN] Feat: early (John)", "2026-11-02T09:00:00+00:00" )
    got = rt.find_tie( "m.new", [], LOG, repo, sha )
    assert got == { "tie": "none", "reason": "john made no check_exists lookup before the commit" }
    sha = commit( repo, "[LUPIN] Feat: fetch only (Chloé)", NOON )
    fetch_only = [ call( "Chloé", "c3333333", RID_A, "2026-11-02T11:00:00+00:00", tool="fetch_similar" ) ]
    assert rt.find_tie( "m.new", [], fetch_only, repo, sha ) == { "tie": "none", "reason": "chloe made no check_exists lookup before the commit" }


def test_an_unknown_commit_is_an_error_only_when_the_ruling_gives_no_tie( repo ):
    with pytest.raises( ValueError, match="is not a commit" ):
        rt.find_tie( "m.new", [], LOG, repo, "0" * 40 )
    assert rt.find_tie( "m.new", [ row( ( "m.new", RID_A ) ) ], LOG, repo, "0" * 40 )[ "tie" ] == "ruling"
