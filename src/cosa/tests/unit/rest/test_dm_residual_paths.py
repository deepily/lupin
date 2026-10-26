"""
The last uncovered paths of `cosa.rest.routers.dm`.

Each is a fail-soft arm that no happy-path test reaches.
The git stamp falls back to "unknown". The claim counter falls back to zero.
The tutor imports its rewriter when none is passed.
The audit keeps distinct senders up to a cap.
The list read answers 400 for a session id too short to match anything.
"""

import subprocess
from unittest.mock import MagicMock

import pytest

from cosa.rest.routers import dm

_USER = "11111111-1111-1111-1111-111111111111"


class _Done:
    def __init__( self, stdout ): self.stdout = stdout


def test_the_git_stamp_is_the_short_sha_when_git_answers( monkeypatch ):
    seen = { }
    def run( cmd, **kw ):
        seen.update( cmd=cmd, kw=kw )
        return _Done( "abc1234\n" )
    monkeypatch.setattr( subprocess, "run", run )
    assert dm._resolve_git_sha() == "abc1234"
    assert seen[ "cmd" ] == [ "git", "rev-parse", "--short", "HEAD" ] and seen[ "kw" ][ "timeout" ] == 5


@pytest.mark.parametrize( "outcome", [ "empty", "raises" ] )
def test_the_git_stamp_is_unknown_when_git_says_nothing_or_fails( monkeypatch, outcome ):
    def run( cmd, **kw ):
        if outcome == "raises": raise FileNotFoundError( "no git here" )
        return _Done( "  \n" )
    monkeypatch.setattr( subprocess, "run", run )
    assert dm._resolve_git_sha() == "unknown"


def test_the_claim_count_comes_from_the_sentence_counter( monkeypatch ):
    import cosa.agents.dm_tutor.sentences as sentences
    monkeypatch.setattr( sentences, "count_sentences", lambda text: 7 )
    assert dm._count_claims( "anything" ) == 7


def test_a_claim_counter_that_cannot_run_counts_zero_so_the_tutor_never_fires( monkeypatch ):
    import cosa.agents.dm_tutor.sentences as sentences
    def boom( text ): raise RuntimeError( "counter broke" )
    monkeypatch.setattr( sentences, "count_sentences", boom )
    assert dm._count_claims( "The build failed. The log is long." ) == 0


def test_the_tutor_imports_its_own_rewriter_when_none_is_passed( monkeypatch ):
    """Over the trigger with no rewriter given, the default model rewriter is the one asked."""
    import cosa.agents.dm_tutor.agent as agent
    asked = [ ]
    monkeypatch.setattr( agent, "rewrite_dm", lambda text: asked.append( text ) or None )
    config = dict( dm._DM_TUTOR_DEFAULTS, enabled=True, trigger_claims=0 )
    body   = "The build failed."
    out, meta = dm._apply_dm_tutor( body, config=config )
    assert asked == [ body ]
    assert out == body and meta[ "tutor_fired" ] is True and meta[ "tutor_outcome" ] == "model_failed"


@pytest.fixture
def audit():
    dm.reset_dm_project_audit()
    yield dm._dm_project_audit
    dm.reset_dm_project_audit()


def test_a_session_is_named_once_however_often_it_sends( audit ):
    for _ in range( 3 ): dm._record_dm_project( "sess-aaaa", None )
    assert audit[ "un_projected" ] == 3 and audit[ "un_projected_senders" ] == [ "sess-aaaa" ]


def test_the_sender_list_stops_growing_at_the_cap_but_the_counter_keeps_rising( audit, monkeypatch ):
    monkeypatch.setattr( dm, "_DM_AUDIT_SENDER_CAP", 2 )
    for name in ( "s1", "s2", "s3", "s4" ): dm._record_dm_project( name, None )
    assert audit[ "un_projected" ] == 4 and audit[ "un_projected_senders" ] == [ "s1", "s2" ]


def test_a_list_read_with_a_too_short_session_id_is_a_400_and_reads_nothing():
    thread_fn, inbox_fn = MagicMock(), MagicMock()
    out = dm.execute_dm_list(
        thread_id=None, since=None, limit=10, authenticated_user_id=_USER,
        thread_fn=thread_fn, inbox_fn=inbox_fn, session_id="abc", scope="session",
    )
    assert out[ "http_status" ] == 400 and "shorter than" in out[ "detail" ]
    thread_fn.assert_not_called()
    inbox_fn.assert_not_called()
