"""
Unit tests for `src/tests/e2e_ui/live_dom_check.py` — row `04735b66`.

WHAT THESE COVER AND WHAT THEY DO NOT, said plainly: these pin the DECISION logic of
`assert_live_dom` against a fake page. The proof that the assertion fires on a real bundle
drop is the two-arm control in `self_test()`, which needs a browser and a live server — arm A
asserts over an untouched page, arm B removes the victim element first. That control is run by
hand against :7999 and is excluded from coverage with its reason on the line.

⚠️ AND ARM B IS A CONSTRUCTED CONTROL, NOT A REAL DRIFT. All 120 TS-declared testids were
present in `boot.js` when it was run, so there was no genuine bundle-drop to point at.
Removing the element is the analogue at the layer that decides the question. Carried forward
here as a named gap rather than covered by the word "proven".
"""
import pathlib, sys

import pytest

sys.path.insert( 0, str( pathlib.Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui" ) )

import live_dom_check as ldc


class FakeLocator:
    def __init__( self, n ): self.n = n
    def count( self ): return self.n


class FakePage:
    """Records the waits it was asked for, so a test can assert the settle actually happened."""
    def __init__( self, counts ):
        self.counts = counts
        self.waited = []

    def locator( self, sel ): return FakeLocator( self.counts[ sel ] )
    def wait_for_timeout( self, ms ): self.waited.append( ms )


def test_it_returns_a_count_per_selector_when_every_one_resolves():
    page = FakePage( { "#a": 1, "#b": 3 } )
    assert ldc.assert_live_dom( page, [ "#a", "#b" ] ) == { "#a": 1, "#b": 3 }


def test_it_does_not_settle_by_default():
    page = FakePage( { "#a": 1 } )
    ldc.assert_live_dom( page, [ "#a" ] )
    assert page.waited == []


def test_it_settles_when_asked():
    page = FakePage( { "#a": 1 } )
    ldc.assert_live_dom( page, [ "#a" ], settle_ms=250 )
    assert page.waited == [ 250 ]


def test_it_fires_on_a_selector_the_running_page_did_not_produce():
    """The whole point. A selector the source names but the bundle dropped must not pass."""
    page = FakePage( { "#a": 1, "#gone": 0 } )
    with pytest.raises( ldc.LiveDomDrift ) as e:
        ldc.assert_live_dom( page, [ "#a", "#gone" ] )
    msg = str( e.value )
    assert "#gone" in msg
    assert "BUILD DRIFT" in msg


def test_it_names_every_missing_selector_not_merely_the_first():
    page = FakePage( { "#a": 0, "#b": 0, "#c": 1 } )
    with pytest.raises( ldc.LiveDomDrift ) as e:
        ldc.assert_live_dom( page, [ "#a", "#b", "#c" ] )
    msg = str( e.value )
    assert "#a" in msg and "#b" in msg
    assert "2 of 3 selectors" in msg


def test_it_refuses_an_empty_selector_list_rather_than_passing_vacuously():
    """A loop over nothing satisfies every assertion in it."""
    with pytest.raises( ldc.LiveDomDrift, match="ZERO selectors" ):
        ldc.assert_live_dom( FakePage( {} ), [] )


def test_a_present_selector_alone_is_not_evidence_the_check_discriminates():
    """The paired arms, in miniature: the SAME call must pass on one page and fire on the
    other. Either arm alone is consistent with a check that cannot fail."""
    assert ldc.assert_live_dom( FakePage( { "#v": 1 } ), [ "#v" ] ) == { "#v": 1 }
    with pytest.raises( ldc.LiveDomDrift ):
        ldc.assert_live_dom( FakePage( { "#v": 0 } ), [ "#v" ] )


# --------------------------------------------------------------------------------------
# _login_tokens
# --------------------------------------------------------------------------------------
class FakeResponse:
    def __init__( self, payload ): self.payload = payload
    def json( self ): return self.payload


class FakeRequests:
    def __init__( self ): self.calls = []
    def post( self, url, json=None, timeout=None ):
        self.calls.append( ( url, json, timeout ) )
        return FakeResponse( { "tokens": { "access_token": "a", "refresh_token": "r" } } )


def test_login_tokens_posts_the_configured_credentials( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "t@example.com" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    rq = FakeRequests()
    assert ldc._login_tokens( rq ) == { "access_token": "a", "refresh_token": "r" }
    url, payload, _timeout = rq.calls[ 0 ]
    assert url.endswith( "/auth/login" )
    assert payload == { "email": "t@example.com", "password": "pw" }


@pytest.mark.parametrize( "present", [ "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL",
                                       "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ] )
def test_login_tokens_refuses_when_either_credential_is_missing( monkeypatch, present ):
    """Refusing loudly beats posting an empty password and reading the 401 as a product fact."""
    for var in ( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL",
                 "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" ):
        monkeypatch.delenv( var, raising=False )
    monkeypatch.setenv( present, "set" )
    with pytest.raises( ValueError, match="LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" ):
        ldc._login_tokens( FakeRequests() )
