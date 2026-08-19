"""
The weather agent must refuse a failed search with a STRING, not the exception object.

ROW c27c2b60. Live symptom, :8000 run ts-dcab007a:
    "primary agent failed: 'HTTPError' object has no attribute 'replace'"

THE CHAIN, corrected from the row's own account (Chloé 🗼, 2026-08-19):
  1. kagiapi's fastgpt() ends with response.raise_for_status(), so a failed Kagi call
     RAISES requests.exceptions.HTTPError out of search_and_summarize_the_web().
  2. weather_agent.run_code's own `except Exception as e` stores the EXCEPTION OBJECT as
     code_response_dict["output"] and as self.error.
  3. agent_base.py:447 hands that object to RawOutputFormatter, whose __init__ does
     raw_output.replace( "<?xml…", "" ) — and THAT is the frame that throws.

So the reported AttributeError names a string method on an exception object, three frames
away from the line the row blamed (weather_agent.py:89 never executes — the raise happens
at :85, one line earlier). The user is told the agent has no `.replace`; nobody is told the
web search failed.

⚠️ WHAT THIS FILE DOES NOT CLAIM, kept from Sam's original warning: it does not establish
WHY the Kagi call failed (auth, quota, network are all still live candidates) and it does
not make the weather agent work. It closes the second, separable defect only — the agent
reporting the wrong error. A green here means the failure is legible, not absent.

Venue: :7999-eligible. LupinSearch is patched, so no network, no Kagi spend, sub-second.
"""

import os
import sys

import pytest

from requests.exceptions import HTTPError

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SRC = os.path.join( _LUPIN_ROOT, "src" )
    if _SRC not in sys.path:
        sys.path.insert( 0, _SRC )

from cosa.agents.weather_agent import WeatherAgent                     # noqa: E402


def _agent_without_construction():
    """
    A WeatherAgent with run_code's inputs set and nothing else.

    AgentBase.__init__ pulls in the config manager, a project root and the solution-snapshot
    machinery — none of which run_code touches. Bypassing __init__ exercises the REAL method
    body (no subclass, no stub) while keeping the test hermetic.
    """
    agent = WeatherAgent.__new__( WeatherAgent )
    agent.reformulated_last_question_asked = "It's 7:00 PM on Tuesday. What's the weather in DC?"
    agent.debug                            = False
    agent.verbose                          = False
    agent.code_response_dict               = {}
    agent.answer                           = None
    agent.error                            = None
    return agent


class _SearchThatFails:
    """LupinSearch stand-in whose web call raises exactly what kagiapi raises."""
    def __init__( self, *args, **kwargs ): pass
    def search_and_summarize_the_web( self ):
        raise HTTPError( "401 Client Error: Unauthorized for url: https://kagi.com/api/v0/fastgpt" )
    def get_results( self, scope="all" ):                              # pragma: no cover - never reached
        raise AssertionError( "get_results must not be called after the search raised" )


class _SearchThatWorks:
    """The happy path, so the refusal below is proven to be about failure and not about everything."""
    def __init__( self, *args, **kwargs ): pass
    def search_and_summarize_the_web( self ): pass
    def get_results( self, scope="all" ):
        return "It is 72 degrees.\n\nWinds are light.\nClear tonight."


def test_a_failed_search_yields_a_STRING_the_formatter_can_process( monkeypatch ):
    """
    The defect, stated as the contract it breaks: code_response_dict["output"] is consumed
    downstream as text (agent_base.py:447 → RawOutputFormatter → .replace). An exception
    object there is a type error waiting three frames away, and the user gets told about a
    missing string method instead of a failed web search.

    RED before the fix: output is an HTTPError instance and .replace() raises AttributeError
    — the exact live symptom.
    """
    monkeypatch.setattr( "cosa.agents.weather_agent.LupinSearch", _SearchThatFails )
    agent  = _agent_without_construction()
    result = agent.run_code()

    assert result[ "return_code" ] == -1                       # still a failure, unchanged
    output = result[ "output" ]
    assert isinstance( output, str ), (
        f"output is {type( output ).__name__}, not str — the formatter will call .replace() on it "
        f"and raise the misleading AttributeError this row is about"
    )
    # The literal downstream operation, run here rather than described: it must not explode.
    output.replace( "<?xml version='1.0' encoding='utf-8'?>", "" )


def test_the_refusal_NAMES_the_failure_instead_of_hiding_it( monkeypatch ):
    """
    A string alone is not enough — "error" would satisfy the type and tell the user nothing.
    The message must carry the exception TYPE and its text, so the next reader learns the web
    search failed and with what, which is the fact the AttributeError was covering up.
    """
    monkeypatch.setattr( "cosa.agents.weather_agent.LupinSearch", _SearchThatFails )
    agent  = _agent_without_construction()
    output = agent.run_code()[ "output" ]

    assert "HTTPError" in output                                # what went wrong
    assert "401" in output                                      # and the detail that identifies it
    assert "search" in output.lower()                           # named as a SEARCH failure, not a generic one


def test_self_error_is_preserved_for_the_caller( monkeypatch ):
    """
    The formatted string is for the user; self.error stays the machine-readable half. Losing
    the original exception in the course of fixing the message would trade one blindness for
    another.
    """
    monkeypatch.setattr( "cosa.agents.weather_agent.LupinSearch", _SearchThatFails )
    agent = _agent_without_construction()
    agent.run_code()
    assert isinstance( agent.error, HTTPError )


def test_the_happy_path_is_untouched( monkeypatch ):
    """
    Control. A successful search must still collapse newlines and set self.answer to the raw
    summary — the refusal must not be reachable when nothing failed.
    """
    monkeypatch.setattr( "cosa.agents.weather_agent.LupinSearch", _SearchThatWorks )
    agent  = _agent_without_construction()
    result = agent.run_code()

    assert result[ "return_code" ] == 0
    assert result[ "output" ] == "It is 72 degrees. Winds are light. Clear tonight."
    assert "\n" not in result[ "output" ]
    assert agent.answer == "It is 72 degrees.\n\nWinds are light.\nClear tonight."
    assert agent.error is None
