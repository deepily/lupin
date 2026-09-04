#!/usr/bin/env python3
"""
THE FLEET-SIZE DIAL'S TWO NUMBERS, AND THE ONE THAT CAN LIE.

`GET /api/arbiter/fleet-size-cap` exists so the operator control can render 1..ceiling
against the cap the spawn path is actually enforcing. Rick ruled by voice 2026-09-03 that
the maximum must be CONFIGURABLE — `cc session fleet size cap maximum`, shipping 18 — so
he can tweak it over time.

🔴 WHAT THESE TESTS ARE FOR, and it is not "does the endpoint return 200". Two failures
would leave the pane looking perfect:

    1. THE CEILING BAKED AS A CONSTANT. Return 18 from code and the endpoint agrees with
       today's INI exactly, forever, including on the day somebody moves the key. Every
       obvious assertion (`ceiling == 18`) passes on the WRONG implementation, which is
       why the tests below drive a config saying 42 and 7 rather than the shipped value.

    2. THE CEILING CLAMPED to the persona pool, the live session count, or anything else.
       A dial silently trimmed below the number the operator typed cannot be told apart
       from a key that was ignored — that reading is why the pool-derived ceiling was
       superseded, and `fleet_size_cap`'s module docstring carries the superseded rule.

⚠️ THE HTML GUARD AT THE BOTTOM IS THE OTHER HALF and it is not decoration. The control
sits in the section CONTENT, never the header bar: the bar's onclick toggles the section,
so a range input up there collapses the panel on every drag. The ratio-gate controls hit
that once already; this pins it so the next mover gets a red instead of a demo.
"""
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Bootstrap — mirrors test_arbiter_router.py
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.routers import arbiter
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt


CAP_KEY     = "cc session fleet size cap"
CEILING_KEY = "cc session fleet size cap maximum"


class FakeConfig:
    """
    A configuration manager answering exactly the two keys the dial reads.

    ⚠️ IT HONOURS ITS INPUT. A fake returning one canned dict whatever it is asked
    cannot tell a handler that reads the ceiling key from one that reads the cap key,
    or from one that reads neither — every assertion written over it would be true by
    construction. This one dispatches on the key and records what it was asked for.
    """

    def __init__( self, values ):
        self.values = dict( values )
        self.asked  = [ ]

    def get( self, key, default=None, return_type="string", silent=False ):
        self.asked.append( key )
        if key in self.values:
            return self.values[ key ]
        return default


@pytest.fixture
def client( monkeypatch ):
    app = FastAPI()
    app.include_router( arbiter.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


def _pin_config( monkeypatch, config ):
    """Point the handler's lazily-imported resolver at `config`."""
    import cosa.rest.dependencies.config as config_dep
    monkeypatch.setattr( config_dep, "get_config_manager", lambda: config )


def test_the_ceiling_is_the_configured_key_and_not_the_shipped_eighteen( client, monkeypatch ):
    """
    A config saying 42 must produce 42.

    🔴 42 IS CHOSEN BECAUSE 18 CANNOT DISCRIMINATE. Asserting `ceiling == 18` against
    the live INI passes just as happily on a handler that returns a literal, which is
    the implementation this endpoint exists to avoid.
    """
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 42, CAP_KEY: 8 } ) )
    body = client.get( "/api/arbiter/fleet-size-cap" ).json()
    assert body[ "ceiling" ] == 42
    assert body[ "cap" ]     == 8


def test_the_ceiling_is_not_clamped_to_the_persona_pool( client, monkeypatch ):
    """
    A two-name pool must not trim a ceiling of 42.

    The pool is the number of seats that can be filled with a NAMED persona; allocation
    falls through it to the overflow persona and then to unbounded Extra-N identities, so
    it is not a ceiling on seats at all. Measured 2026-09-03: 18 requested fills 18, 200
    fills 200.
    """
    config = FakeConfig( {
        CEILING_KEY                    : 42,
        CAP_KEY                        : 8,
        "cc session voice persona pool": "ann,bob",
    } )
    _pin_config( monkeypatch, config )
    assert client.get( "/api/arbiter/fleet-size-cap" ).json()[ "ceiling" ] == 42


def test_both_numbers_are_read_at_call_time_not_frozen( client, monkeypatch ):
    """
    Move the config between two calls and BOTH answers must move.

    ⚠️ TWO CALLS, ONE CLIENT, ONE PROCESS. A handler that resolved config at import — or
    cached the first answer — returns the same body twice and is indistinguishable from a
    correct one on any single-call test.
    """
    config = FakeConfig( { CEILING_KEY: 42, CAP_KEY: 8 } )
    _pin_config( monkeypatch, config )

    first = client.get( "/api/arbiter/fleet-size-cap" ).json()
    config.values[ CEILING_KEY ] = 7
    config.values[ CAP_KEY ]     = 3
    second = client.get( "/api/arbiter/fleet-size-cap" ).json()

    assert ( first[ "ceiling" ], first[ "cap" ] )   == ( 42, 8 )
    assert ( second[ "ceiling" ], second[ "cap" ] ) == ( 7, 3 )


def test_a_cap_above_the_ceiling_is_clamped_to_the_ceiling( client, monkeypatch ):
    """A dial cannot paint a handle off its own track: cap clamps into 1..ceiling."""
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 10, CAP_KEY: 99 } ) )
    body = client.get( "/api/arbiter/fleet-size-cap" ).json()
    assert body[ "cap" ] == 10 and body[ "ceiling" ] == 10


def test_an_unreadable_config_degrades_to_a_number_rather_than_a_500( client, monkeypatch ):
    """
    The pane must degrade to the module defaults, not to an error.

    Same fail-soft the spawn path uses: a config that cannot be read is not a reason to
    take the operator's view of the fleet down.
    """
    import cosa.rest.dependencies.config as config_dep

    def _boom():
        raise RuntimeError( "no config manager here" )

    monkeypatch.setattr( config_dep, "get_config_manager", _boom )
    response = client.get( "/api/arbiter/fleet-size-cap" )
    assert response.status_code == 200

    from lupin_mcp import fleet_size_cap
    assert response.json() == {
        "cap"     : min( fleet_size_cap.DEFAULT_FLEET_CAP, fleet_size_cap.DEFAULT_FLEET_CEILING ),
        "ceiling" : fleet_size_cap.DEFAULT_FLEET_CEILING,
    }


# ── THE MARKUP HALF ──────────────────────────────────────────────────────────────

def _notifications_html():
    root = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    path = os.path.join( root, "src", "lupin_app", "static", "html", "notifications.html" )
    with open( path ) as handle:
        return handle.read()


def test_the_dial_sits_in_the_section_content_and_not_on_the_toggling_header_bar():
    """
    🔴 THE ONE PLACEMENT THAT BREAKS IT. `#section-fleet-status`'s header bar carries
    `onclick="toggleSection('fleet-status-section')"`, so a range input inside that div
    collapses the panel on every drag. Rick's word was "the fleet accordion header";
    "header" means the TOP OF THE SECTION CONTENT, which is what this pins.

    The assertion is ORDER-BASED rather than a substring search, because the control's
    markup would be found by a search wherever it sat.
    """
    html = _notifications_html()
    section = html.index( 'id="section-fleet-status"' )
    header  = html.index( "toggleSection('fleet-status-section')", section )
    content = html.index( 'id="fleet-status-section"', header )
    control = html.index( 'data-testid="fleet-size-cap-controls"', section )
    table   = html.index( 'data-testid="fleet-status-container"', section )

    assert header < content < control < table, (
        "the dial must sit after the section-content opener and before the table — "
        f"header={header} content={content} control={control} table={table}"
    )


def test_the_markup_carries_no_max_attribute_for_the_slider():
    """
    THE CEILING IS NOT WRITTEN IN THE HTML, and this is the assertion that keeps it out.

    A `max="18"` here would be a second source of truth that agrees with the key exactly
    until somebody moves the key, at which point the control silently disagrees with what
    the spawn path enforces — which is the failure the configurable-maximum ruling was
    made to prevent.
    """
    html    = _notifications_html()
    start   = html.index( 'data-testid="fleet-size-cap"' )
    element = html[ html.rindex( "<input", 0, start ) : html.index( "/>", start ) ]
    assert 'min="1"' in element, "the FLOOR is fixed at 1 and does belong in the markup"
    assert "max=" not in element, f"the ceiling must come from the key at call time: {element!r}"
