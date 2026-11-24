#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for write_proxy_decision, the writer both decision callers share.

Each test names the repository method that ran and the one that did not.
"""

import contextlib
from unittest.mock import MagicMock, patch

import pytest

from cosa.agents.decision_proxy.decision_writer import write_proxy_decision


def _result( action="act", value="v", reason="r" ):
    return MagicMock( action=action, value=value, category="deployment", confidence=0.8, trust_level=2, reason=reason )


@contextlib.contextmanager
def _database():
    """Fake the session and the repository; yield ( repo, session )."""
    repo    = MagicMock()
    session = MagicMock()
    with patch( "cosa.rest.db.database.get_db" ) as get_db, \
         patch( "cosa.rest.db.repositories.proxy_decision_repository.ProxyDecisionRepository", return_value=repo ):
        get_db.return_value.__enter__.return_value = session
        yield repo, session


def _write( result, **overrides ):
    args = dict(
        result                = result,
        notification_id       = "nid",
        domain                = "swe",
        question              = "q",
        sender_id             = "sid",
        requires_ratification = True,
        shadow_reason_default = "shadow mode",
        shadow_decision_value = "forecast",
    )
    args.update( overrides )
    write_proxy_decision( **args )


def test_shadow_branch_runs_log_shadow_and_not_log_decision():
    with _database() as ( repo, _ ):
        _write( _result( action="shadow" ) )
    repo.log_shadow.assert_called_once()
    repo.log_decision.assert_not_called()
    kwargs = repo.log_shadow.call_args.kwargs
    assert ( kwargs[ "notification_id" ], kwargs[ "domain" ], kwargs[ "sender_id" ] ) == ( "nid", "swe", "sid" )
    assert kwargs[ "decision_value" ] == "forecast"
    assert "action" not in kwargs and "requires_ratification" not in kwargs


def test_decision_branch_runs_log_decision_and_not_log_shadow():
    with _database() as ( repo, _ ):
        _write( _result( action="suggest", value="approved" ), requires_ratification=False )
    repo.log_decision.assert_called_once()
    repo.log_shadow.assert_not_called()
    kwargs = repo.log_decision.call_args.kwargs
    assert ( kwargs[ "action" ], kwargs[ "decision_value" ], kwargs[ "requires_ratification" ] ) == ( "suggest", "approved", False )
    assert kwargs[ "sender_id" ] == "sid"


def test_shadow_branch_uses_the_callers_default_reason_only_when_the_result_has_none():
    with _database() as ( repo, _ ):
        _write( _result( action="shadow", reason=None ), shadow_reason_default="shadow mode" )
        _write( _result( action="shadow", reason=None ), shadow_reason_default="" )
        _write( _result( action="shadow", reason="own" ), shadow_reason_default="shadow mode" )
    reasons = [ c.kwargs[ "reason" ] for c in repo.log_shadow.call_args_list ]
    assert reasons == [ "shadow mode", "", "own" ]


def test_decision_branch_stores_an_empty_reason_when_the_result_has_none_whatever_the_shadow_default():
    with _database() as ( repo, _ ):
        _write( _result( action="act", reason=None ), shadow_reason_default="shadow mode" )
    assert repo.log_decision.call_args.kwargs[ "reason" ] == ""
    repo.log_shadow.assert_not_called()


def test_shadow_branch_cuts_the_question_to_500_characters():
    with _database() as ( repo, _ ):
        _write( _result( action="shadow" ), question="x" * 600 )
    assert len( repo.log_shadow.call_args.kwargs[ "question" ] ) == 500


def test_decision_branch_cuts_the_question_to_500_characters():
    with _database() as ( repo, _ ):
        _write( _result( action="act" ), question="x" * 600 )
    assert len( repo.log_decision.call_args.kwargs[ "question" ] ) == 500


def test_extra_reaches_the_shadow_branch_and_the_decision_branch():
    extra = { "metadata_json": { "a": 1 }, "data_origin": "organic", "rule_agreement": True }
    with _database() as ( repo, _ ):
        _write( _result( action="shadow" ), extra=extra )
        _write( _result( action="act" ), extra=extra )
    for kwargs in ( repo.log_shadow.call_args.kwargs, repo.log_decision.call_args.kwargs ):
        assert ( kwargs[ "metadata_json" ], kwargs[ "data_origin" ], kwargs[ "rule_agreement" ] ) == ( { "a": 1 }, "organic", True )


def test_without_extra_neither_branch_passes_the_extra_fields():
    with _database() as ( repo, _ ):
        _write( _result( action="shadow" ) )
        _write( _result( action="act" ) )
    for kwargs in ( repo.log_shadow.call_args.kwargs, repo.log_decision.call_args.kwargs ):
        assert not { "metadata_json", "data_origin", "rule_agreement" } & set( kwargs )


def test_commit_true_commits_the_session_after_the_shadow_branch():
    with _database() as ( repo, session ):
        _write( _result( action="shadow" ), commit=True )
    repo.log_shadow.assert_called_once()
    session.commit.assert_called_once()


def test_commit_true_commits_the_session_after_the_decision_branch():
    with _database() as ( repo, session ):
        _write( _result( action="act" ), commit=True )
    repo.log_decision.assert_called_once()
    session.commit.assert_called_once()


def test_commit_defaults_to_no_commit():
    with _database() as ( _, session ):
        _write( _result( action="act" ) )
    session.commit.assert_not_called()


@pytest.mark.parametrize( "database", [ "lupin_db_dev", "lupin_db", "lupin_db_prod", "scratch_db", "lupin_db_testing", "contest" ] )
def test_a_write_to_any_non_scratch_database_under_pytest_is_refused_and_no_repository_call_is_made( database ):
    with _database() as ( repo, session ):
        session.get_bind.return_value.url.database = database
        with pytest.raises( RuntimeError, match=database ):
            _write( _result( action="suggest" ) )
    repo.log_decision.assert_not_called()
    repo.log_shadow.assert_not_called()


@pytest.mark.parametrize( "database", [ "lupin_db_test", "lupin_lane_b_test_4242", "test", None ] )
def test_a_write_bound_to_a_scratch_database_or_to_no_named_database_goes_through( database ):
    with _database() as ( repo, session ):
        session.get_bind.return_value.url.database = database
        _write( _result( action="suggest" ) )
    repo.log_decision.assert_called_once()


def test_a_faked_session_whose_bind_names_no_string_goes_through():
    with _database() as ( repo, session ):
        _write( _result( action="suggest" ) )
    repo.log_decision.assert_called_once()


@pytest.mark.parametrize( "database", [ "lupin_db_dev", "lupin_db" ] )
def test_outside_pytest_a_non_scratch_database_write_is_not_refused( monkeypatch, database ):
    monkeypatch.delenv( "PYTEST_CURRENT_TEST" )
    with _database() as ( repo, session ):
        session.get_bind.return_value.url.database = database
        _write( _result( action="suggest" ) )
    repo.log_decision.assert_called_once()
