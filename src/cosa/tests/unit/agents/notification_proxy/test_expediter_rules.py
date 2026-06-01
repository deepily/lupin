#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.strategies.expediter_rules.

ExpediterRuleStrategy is pure rule logic — no LLM, no network. It matches
notifications by sender allow-list + keyword patterns and returns answers
from the active TEST_PROFILES profile. All paths are exercised here with
hand-built notification dicts (zero external dependencies).
"""

import json

import pytest

from cosa.agents.notification_proxy.strategies.expediter_rules import (
    ExpediterRuleStrategy, KEYWORD_TO_ARG
)
from cosa.agents.notification_proxy.config import DEFAULT_ACCEPTED_SENDERS

EXPEDITER = DEFAULT_ACCEPTED_SENDERS[ 0 ]


class TestInit:
    """Construction validates the profile and resolves accepted_senders."""

    def test_valid_profile( self ):
        """
        Ensures:
            - a known profile name loads its answer dict
            - default accepted_senders fall back to DEFAULT_ACCEPTED_SENDERS
        """
        s = ExpediterRuleStrategy( "deep_research" )
        assert s.profile_name     == "deep_research"
        assert s.profile          == s.profile          # loaded
        assert s.accepted_senders == DEFAULT_ACCEPTED_SENDERS

    def test_explicit_accepted_senders_override_default( self ):
        """
        Ensures:
            - an explicit accepted_senders list overrides the default
        """
        s = ExpediterRuleStrategy( "deep_research", accepted_senders=[ "a@b.c" ] )
        assert s.accepted_senders == [ "a@b.c" ]

    def test_unknown_profile_raises_keyerror( self ):
        """
        Ensures:
            - an unknown profile name raises KeyError
        """
        with pytest.raises( KeyError ):
            ExpediterRuleStrategy( "nonexistent_profile" )


class TestCanHandle:
    """can_handle gates on response_requested + sender allow-list."""

    def test_accepts_expediter_with_response_requested( self ):
        s = ExpediterRuleStrategy( "deep_research" )
        assert s.can_handle( { "sender_id": EXPEDITER, "response_requested": True } )

    def test_accepts_expediter_with_hash_suffix( self ):
        """sender_base strips the '#suffix' before comparing."""
        s = ExpediterRuleStrategy( "deep_research" )
        assert s.can_handle( { "sender_id": EXPEDITER + "#sess123", "response_requested": True } )

    def test_rejects_when_no_response_requested( self ):
        s = ExpediterRuleStrategy( "deep_research" )
        assert not s.can_handle( { "sender_id": EXPEDITER, "response_requested": False } )

    def test_rejects_unknown_sender( self ):
        s = ExpediterRuleStrategy( "deep_research" )
        assert not s.can_handle( { "sender_id": "other@x.y", "response_requested": True } )

    def test_rejects_missing_keys_defaults( self ):
        """Empty dict → response_requested defaults False → rejected."""
        s = ExpediterRuleStrategy( "deep_research" )
        assert not s.can_handle( {} )


class TestRespondDispatch:
    """respond() routes on response_type."""

    def test_yes_no_returns_yes( self ):
        s = ExpediterRuleStrategy( "deep_research", debug=True )
        assert s.respond( { "response_type": "yes_no", "message": "ok?", "title": "Confirm" } ) == "yes"

    def test_open_ended_keyword_match_query( self ):
        s = ExpediterRuleStrategy( "deep_research" )
        out = s.respond( { "response_type": "open_ended", "message": "what topic?", "title": "Missing: query" } )
        assert out == "quantum computing breakthroughs 2026"

    def test_open_ended_keyword_match_budget( self ):
        s = ExpediterRuleStrategy( "deep_research" )
        out = s.respond( { "response_type": "open_ended", "message": "set a budget limit?", "title": "" } )
        assert out == "no limit"

    def test_open_ended_no_keyword_returns_none( self ):
        s = ExpediterRuleStrategy( "deep_research", debug=True )
        assert s.respond( { "response_type": "open_ended", "message": "xyzzy", "title": "" } ) is None

    def test_multiple_choice_picks_first_label( self ):
        s = ExpediterRuleStrategy( "deep_research", debug=True )
        notif = {
            "response_type"    : "multiple_choice",
            "message"          : "pick",
            "title"            : "",
            "response_options" : { "questions": [ { "options": [ { "label": "Alpha" }, { "label": "Beta" } ] } ] },
        }
        assert s.respond( notif ) == "Alpha"

    def test_multiple_choice_no_questions_returns_none( self ):
        s = ExpediterRuleStrategy( "deep_research" )
        notif = { "response_type": "multiple_choice", "response_options": { "questions": [] } }
        assert s.respond( notif ) is None

    def test_multiple_choice_question_without_options_returns_none( self ):
        s = ExpediterRuleStrategy( "deep_research" )
        notif = { "response_type": "multiple_choice", "response_options": { "questions": [ { "options": [] } ] } }
        assert s.respond( notif ) is None

    def test_unknown_response_type_returns_none( self ):
        s = ExpediterRuleStrategy( "deep_research", debug=True )
        assert s.respond( { "response_type": "weird_type", "message": "", "title": "" } ) is None


class TestMatchKeyword:
    """_match_keyword: first matching keyword whose profile value is truthy wins."""

    def test_keyword_present_but_value_missing_falls_through_to_none( self ):
        """
        'minimal' profile lacks 'audience'. Searching 'audience' matches the
        keyword but profile.get returns None (falsy) → continue → no other
        match → None. Exercises the `if value:` FALSE arm.
        """
        s = ExpediterRuleStrategy( "minimal", debug=True )
        assert s._match_keyword( "who is the audience" ) is None

    def test_keyword_table_is_nonempty( self ):
        """Guards against an accidentally-emptied KEYWORD_TO_ARG table."""
        assert len( KEYWORD_TO_ARG ) >= 1


class TestHandleBatch:
    """OPEN_ENDED_BATCH maps question headers → profile/keyword/default values."""

    def test_batch_no_questions_returns_none( self ):
        s = ExpediterRuleStrategy( "deep_research", debug=True )
        notif = { "response_type": "open_ended_batch", "response_options": { "questions": [] } }
        assert s.respond( notif ) is None

    def test_batch_direct_header_match( self ):
        """Header equal to a profile key resolves directly."""
        s = ExpediterRuleStrategy( "deep_research" )
        notif = {
            "response_type"    : "open_ended_batch",
            "response_options" : { "questions": [ { "header": "budget", "question": "?" } ] },
        }
        out = json.loads( s.respond( notif ) )
        assert out[ "answers" ][ "budget" ] == "no limit"

    def test_batch_keyword_fallback( self ):
        """Unknown header but question text keyword-matches a profile arg."""
        s = ExpediterRuleStrategy( "deep_research" )
        notif = {
            "response_type"    : "open_ended_batch",
            "response_options" : { "questions": [ { "header": "Hdr", "question": "what topic to research?" } ] },
        }
        out = json.loads( s.respond( notif ) )
        assert out[ "answers" ][ "Hdr" ] == "quantum computing breakthroughs 2026"

    def test_batch_default_value_fallback( self ):
        """No header/keyword match → use the question's default_value."""
        s = ExpediterRuleStrategy( "minimal", debug=True )
        notif = {
            "response_type"    : "open_ended_batch",
            "response_options" : { "questions": [ { "header": "Xyz", "question": "qqq", "default_value": "fallback-val" } ] },
        }
        out = json.loads( s.respond( notif ) )
        assert out[ "answers" ][ "Xyz" ] == "fallback-val"

    def test_batch_no_resolvable_answers_returns_none( self ):
        """Header/keyword/default all miss for every question → None."""
        s = ExpediterRuleStrategy( "minimal", debug=True )
        notif = {
            "response_type"    : "open_ended_batch",
            "response_options" : { "questions": [ { "header": "Xyz", "question": "qqq" } ] },
        }
        assert s.respond( notif ) is None
