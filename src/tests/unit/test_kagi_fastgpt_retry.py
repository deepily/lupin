"""
A transient Kagi failure must cost the user a wait, not a refusal — and an exhausted one
must still name its status code.

ROW 3598c1d3. On 2026-08-19 at 18:54 EDT (:8000 run ts-dcab007a) the Kagi FastGPT call
behind the weather agent raised requests.HTTPError instead of returning a summary. Four
hypotheses were ruled out with evidence — revoked key, quota, credential reach, container
egress — leaving a momentary upstream fault whose status is permanently unknown, because
KagiSearch.search_fastgpt was a bare single call and the exception died with the request.
Mr. Radio ruled it a missing retry rather than an open investigation.

WHAT THIS FILE PINS, in the order it matters:
  1. one blip no longer reaches the user — first call raises, second succeeds, the weather
     comes back
  2. 🔴 an EXHAUSTED retry still carries its status line into the user-visible refusal.
     Sam proved at 79ea2501 that the refusal names its own status code; a retry that
     summarised the final failure would have silently reverted the only thing that row
     achieved, and the next occurrence would be undiagnosable again
  3. a 401 is not retried at all — a standing answer does not improve by being asked three
     times, and making the user wait for it is a second defect

Venue: :7999-eligible. The kagiapi client is faked and the backoff is zeroed, so the real
LupinSearch → KagiSearch → retry path runs with no network, no Kagi spend and no waiting.
"""

import os
import sys

import pytest

from requests.exceptions import HTTPError, ConnectionError as RequestsConnectionError

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SRC = os.path.join( _LUPIN_ROOT, "src" )
    if _SRC not in sys.path:
        sys.path.insert( 0, _SRC )

import cosa.tools.search_kagi as search_kagi                            # noqa: E402
import cosa.tools.search_lupin_v010 as search_lupin                     # noqa: E402

from cosa.agents.weather_agent import WeatherAgent                      # noqa: E402
from cosa.tools.search_kagi import KagiSearch, kagi_error_is_transient  # noqa: E402


_PAYLOAD = { "meta": { "api_balance": 2.92105 },
             "data": { "output": "It is 72 degrees in Washington DC.", "references": [] } }


class _Response:
    """The only part of a requests.Response the retry predicate reads."""
    def __init__( self, status_code ):
        self.status_code = status_code


def _http_error( status_code ):
    """An HTTPError shaped exactly like the one kagiapi's raise_for_status() produces."""
    return HTTPError( f"{status_code} Client Error: for url: https://kagi.com/api/v0/fastgpt",
                      response=_Response( status_code ) )


class _FakeKagiClient:
    """Stand-in for kagiapi.KagiClient that fails a scripted number of times, then answers."""
    def __init__( self, failures, error, payload=_PAYLOAD ):
        self.failures = failures
        self.error    = error
        self.payload  = payload
        self.calls    = 0
    def fastgpt( self, query=None ):
        self.calls += 1
        if self.calls <= self.failures: raise self.error
        return self.payload
    def summarize( self, url=None, engine=None, summary_type=None ):
        self.calls += 1
        return self.payload


@pytest.fixture
def kagi_client( monkeypatch ):
    """
    Install a fake kagiapi client and zero the backoff, leaving the real code path intact.

    The api-key read is patched too, so the test never touches src/conf/keys and would pass
    on a machine that has no Kagi credential at all.
    """
    holder = {}

    def _install( failures, error ):
        client = _FakeKagiClient( failures, error )
        monkeypatch.setattr( search_kagi.du, "get_api_key", lambda *a, **kw: "not-a-real-key" )
        monkeypatch.setattr( search_kagi, "KagiClient", lambda *a, **kw: client )
        # LupinSearch does not forward retry knobs; zeroing the wait here keeps the test
        # instant while leaving the retry LOOP itself completely real.
        real_kagi_search = search_kagi.KagiSearch
        monkeypatch.setattr( search_lupin, "KagiSearch",
                             lambda **kwargs: real_kagi_search( retry_backoff=0.0, **kwargs ) )
        holder[ "client" ] = client
        return client

    _install.holder = holder
    return _install


def _weather_agent():
    """A WeatherAgent with run_code's inputs set and nothing else — same construction bypass
    as test_weather_agent_search_failure.py, so the REAL method body runs without the config
    manager, the project root or the solution-snapshot machinery."""
    agent = WeatherAgent.__new__( WeatherAgent )
    agent.reformulated_last_question_asked = "It's 7:00 PM on Tuesday. What's the weather in DC?"
    agent.debug                            = False
    agent.verbose                          = False
    agent.code_response_dict               = {}
    agent.answer                           = None
    agent.error                            = None
    return agent


# ──────────────────────────────────────────────────────────────────────────────
# 1. the fix, stated as the user's experience
# ──────────────────────────────────────────────────────────────────────────────

def test_a_transient_failure_on_the_FIRST_call_still_returns_the_weather( kagi_client ):
    """
    The defect this row closes. Before the retry, this exact sequence produced a refusal:
    one 503 anywhere in Kagi's stack and the user was told the weather agent failed.
    """
    client = kagi_client( failures=1, error=_http_error( 503 ) )
    agent  = _weather_agent()
    result = agent.run_code()

    assert client.calls == 2                                    # it failed once and was asked again
    assert result[ "return_code" ] == 0                         # and the user sees a success
    assert result[ "output" ] == "It is 72 degrees in Washington DC."
    assert agent.error is None


def test_a_transport_failure_with_no_response_at_all_is_also_retried( kagi_client ):
    """A reset connection carries no status. Nothing about it says the request was rejected,
    so it is exactly the case a retry is for."""
    client = kagi_client( failures=1, error=RequestsConnectionError( "connection reset by peer" ) )
    result = _weather_agent().run_code()

    assert client.calls == 2
    assert result[ "return_code" ] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 2. 🔴 the property the retry was allowed to exist on condition of preserving
# ──────────────────────────────────────────────────────────────────────────────

def test_an_EXHAUSTED_retry_still_names_the_status_code_in_the_refusal( kagi_client ):
    """
    🔴 THE NON-NEGOTIABLE. Sam's control at 79ea2501: delete `{e}` from the refusal string and
    test_the_refusal_NAMES_the_failure_instead_of_hiding_it goes red. A retry that ended in a
    tidy summary — "search failed after 3 attempts" — would pass every other test in this file
    and quietly take that property away. After the last attempt the ORIGINAL exception must
    reach the agent, status line and all.
    """
    client = kagi_client( failures=99, error=_http_error( 503 ) )
    agent  = _weather_agent()
    output = agent.run_code()[ "output" ]

    assert client.calls == 3                                    # every attempt spent, none wasted
    assert "HTTPError" in output                                # what went wrong
    assert "503"       in output                                # and the code that identifies it
    assert "search"    in output.lower()                        # named as a SEARCH failure
    assert isinstance( agent.error, HTTPError )                 # the machine-readable half survives too
    assert agent.error.response.status_code == 503              # unwrapped — not a copy, not a summary


# ──────────────────────────────────────────────────────────────────────────────
# 3. a standing answer is not retried
# ──────────────────────────────────────────────────────────────────────────────

def test_a_401_is_delivered_on_the_FIRST_attempt_without_waiting( kagi_client ):
    """
    Retrying an authentication answer cannot change it; it only makes the user wait longer to
    be told the same thing. This is why the retry is filtered by status rather than blanket.
    """
    client = kagi_client( failures=99, error=_http_error( 401 ) )
    output = _weather_agent().run_code()[ "output" ]

    assert client.calls == 1
    assert "401" in output


@pytest.mark.parametrize( "status, transient", [
    ( 429, True ), ( 500, True ), ( 502, True ), ( 503, True ), ( 504, True ), ( 408, True ), ( 425, True ),
    ( 400, False ), ( 401, False ), ( 403, False ), ( 404, False ),
] )
def test_which_statuses_are_worth_another_attempt( status, transient ):
    assert kagi_error_is_transient( _http_error( status ) ) is transient


def test_an_error_carrying_no_response_is_treated_as_transient():
    assert kagi_error_is_transient( RequestsConnectionError( "dns failure" ) ) is True


# ──────────────────────────────────────────────────────────────────────────────
# the surrounding contract, so the retry is not the only thing proven
# ──────────────────────────────────────────────────────────────────────────────

def test_a_healthy_search_makes_exactly_ONE_call( kagi_client ):
    """Control. The guard must be free when nothing is wrong — no extra call, no delay."""
    client = kagi_client( failures=0, error=_http_error( 503 ) )
    assert _weather_agent().run_code()[ "return_code" ] == 0
    assert client.calls == 1


def test_the_shipped_defaults_are_three_attempts_one_second_apart( monkeypatch ):
    """
    The zeroed backoff above is a test convenience; this pins what actually ships, so a
    default silently changed to 1 attempt cannot pass as a working retry.
    """
    monkeypatch.setattr( search_kagi.du, "get_api_key", lambda *a, **kw: "not-a-real-key" )
    monkeypatch.setattr( search_kagi, "KagiClient", lambda *a, **kw: _FakeKagiClient( 0, None ) )
    searcher = KagiSearch( query="what's the weather in DC?" )
    assert ( searcher.max_attempts, searcher.retry_backoff ) == ( 3, 1.0 )


def test_the_retry_announces_itself_so_a_recovered_blip_leaves_a_trace( kagi_client, capsys ):
    """
    A search that quietly succeeded on its second try is indistinguishable from one that never
    had trouble — and the next investigation would start with no record that Kagi wobbled.
    """
    kagi_client( failures=1, error=_http_error( 503 ) )
    _weather_agent().run_code()
    printed = capsys.readouterr().out

    assert "attempt 1/3 failed" in printed
    assert "503"                in printed
    assert "retrying in"        in printed


def test_get_summary_is_untouched_by_this_row( kagi_client ):
    """
    Scope fence, asserted rather than promised. get_summary is the same bare-call shape and is
    a named migration candidate, but it was deliberately NOT changed here — it still makes one
    call and propagates whatever comes back.
    """
    client   = kagi_client( failures=0, error=_http_error( 503 ) )
    searcher = KagiSearch( url="https://weather.com/some/page" )
    assert searcher.get_summary() == _PAYLOAD
    assert client.calls == 1
