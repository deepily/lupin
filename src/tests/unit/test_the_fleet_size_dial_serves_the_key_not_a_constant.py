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


@pytest.fixture( autouse=True )
def _no_ambient_ini( monkeypatch, tmp_path ):
    """
    Point the handler's FRESH DISK READ at a file that does not exist, so the tests
    above keep measuring the FakeConfig they hand it.

    🔴 WHY THIS ARRIVED 2026-09-04. `resolve_fleet_cap` now prefers the value on disk
    over the cached configuration singleton — without that, an operator's slider move
    would not bite until somebody bounced the long-running MCP process. But it means a
    handler test that pins only a FakeConfig is silently answered by the REAL
    `src/conf/lupin-app.ini`: `test_both_numbers_are_read_at_call_time_not_frozen`
    hands it a cap of 3 and the live file says 8.

    ⚠️ AND THE FAILURE WOULD HAVE POINTED THE WRONG WAY. The obvious "fix" is to drop
    the disk read from the handler, which turns these tests green again while leaving
    the pane showing a stale cap after any hand-edit of the INI. Green for the wrong
    reason. The seam is the fix; this fixture is what makes it usable.

    A test that WANTS the disk read pins `config_file_path` itself inside its body,
    which runs after this and therefore wins.
    """
    from lupin_mcp import fleet_size_cap
    monkeypatch.setattr( fleet_size_cap, "config_file_path",
                         lambda: str( tmp_path / "no-such-config.ini" ) )


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
    body = response.json()
    assert body[ "cap" ]     == min( fleet_size_cap.DEFAULT_FLEET_CAP,
                                     fleet_size_cap.DEFAULT_FLEET_CEILING )
    assert body[ "ceiling" ] == fleet_size_cap.DEFAULT_FLEET_CEILING
    # `live` joined the payload 2026-09-04 so the pane can show WHO occupies the cap.
    # The assertion is per-key rather than a whole-body equality because an equality
    # here would break on every future field and say nothing about this one.
    assert "live" in body


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


# ── THE WRITE PATH ───────────────────────────────────────────────────────────────
#
# 🔴 THE DIAL BECAME A THERMOSTAT ON 2026-09-04. It shipped read-only, and the tests
# above were written for that. Rick's spec is a cap "ADJUSTABLE BY A SLIDER", and his
# reason is that a verbal cap failed twice because it depended on managers remembering
# a number — so a control that reports rather than sets does not discharge it.
#
# What these tests are for, and it is not "does the PUT return 200":
#
#   1. THE VALUE NEVER REACHED THE DISK. An in-memory set returns cleanly, the next GET
#      agrees, and the cap is gone at the next restart. Every test here reads the FILE.
#   2. THE RESPONSE ECHOED THE REQUEST. An echo is unfalsifiable — identical whether the
#      write landed, went to a section nobody reads, or never happened. The client
#      repaints from this body, so an echo moves the dial to a number the spawn path is
#      not enforcing, which is the exact defect the whole row exists to close.
#   3. IT ANSWERED AN UNAUTHENTICATED CALLER. `/api/arbiter/*` is guarded; a slider that
#      silently 401s is a dial that appears to work and governs nothing.


def _pin_ini( monkeypatch, tmp_path, body ):
    """Point the handler's writer AND its fresh reader at a throwaway INI."""
    from lupin_mcp import fleet_size_cap
    path = tmp_path / "lupin-app.ini"
    path.write_text( body, encoding="utf-8" )
    monkeypatch.setattr( fleet_size_cap, "config_file_path", lambda: str( path ) )
    return path


REAL_SHAPED_INI = """\
[Lupin: Baseline]
# The fleet-wide cap. Set `cc session fleet size cap` here, not in code.
cc session fleet size cap                        = 8
cc session fleet size cap maximum                = 18
"""


def test_the_PUT_actually_writes_the_file( client, monkeypatch, tmp_path ):
    """
    🔴 THE RECEIPT THAT MATTERS. Rick: "those values are serialized and reused the next
    time." This asserts on the FILE, because every in-memory implementation passes an
    assertion made against the response.
    """
    path = _pin_ini( monkeypatch, tmp_path, REAL_SHAPED_INI )
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 18, CAP_KEY: 8 } ) )

    response = client.put( "/api/arbiter/fleet-size-cap", json={ "cap": 12 } )

    assert response.status_code == 200
    assert "cc session fleet size cap                        = 12" in \
           path.read_text( encoding="utf-8" )


def test_the_response_is_what_the_FILE_says_not_what_was_SENT( client, monkeypatch, tmp_path ):
    """
    🔴 THE ECHO GUARD. The file is changed under the handler between the write and the
    read, so the request value (12) and the file value (5) differ. An echoing
    implementation returns 12 and passes every other test in this file.
    """
    path = _pin_ini( monkeypatch, tmp_path, REAL_SHAPED_INI )
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 18, CAP_KEY: 8 } ) )

    from lupin_mcp import fleet_cap_ini_io
    real_write = fleet_cap_ini_io.write_int_to_disk

    def _write_then_someone_else_edits( ini_path, key, value ):
        real_write( ini_path, key, value )
        real_write( ini_path, key, 5 )        # a concurrent edit, a clamp, a second seat
        return fleet_cap_ini_io.read_int_from_disk( ini_path, key )

    monkeypatch.setattr( fleet_cap_ini_io, "write_int_to_disk", _write_then_someone_else_edits )

    body = client.put( "/api/arbiter/fleet-size-cap", json={ "cap": 12 } ).json()
    assert body[ "cap" ] == 5, "the response must report the FILE, never the request"


def test_a_cap_above_the_ceiling_is_REFUSED_and_nothing_is_written( client, monkeypatch, tmp_path ):
    """
    ⚠️ REFUSED, NOT CLAMPED, and the asymmetry with the READ path is deliberate. The
    reader clamps because it runs on the spawn path and must land somewhere sane. The
    writer refuses because a value silently trimmed to 18 cannot be told apart from a
    request that was ignored — and the operator is right there waiting for the answer.
    """
    path = _pin_ini( monkeypatch, tmp_path, REAL_SHAPED_INI )
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 18, CAP_KEY: 8 } ) )

    response = client.put( "/api/arbiter/fleet-size-cap", json={ "cap": 99 } )

    assert response.status_code == 422
    assert "18" in response.json()[ "detail" ] and "99" in response.json()[ "detail" ]
    assert "= 8" in path.read_text( encoding="utf-8" ), "a refusal writes NOTHING"


def test_a_cap_below_one_is_refused_by_the_model( client, monkeypatch, tmp_path ):
    """`ge=1` is declared on the model, so the refusal names the field rather than
    being hand-rolled in the handler."""
    _pin_ini( monkeypatch, tmp_path, REAL_SHAPED_INI )
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 18, CAP_KEY: 8 } ) )
    assert client.put( "/api/arbiter/fleet-size-cap", json={ "cap": 0 } ).status_code == 422


def test_a_DUPLICATED_key_surfaces_the_writer_s_refusal_as_a_409( client, monkeypatch, tmp_path ):
    """
    The writer declines when the key is defined twice. Passing its message through
    verbatim is what lets an operator FIX the file; swallowing it and returning the old
    cap would report a successful no-op.
    """
    path = _pin_ini( monkeypatch, tmp_path,
                     REAL_SHAPED_INI + "\n[Lupin: Development]\ncc session fleet size cap = 4\n" )
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 18, CAP_KEY: 8 } ) )

    response = client.put( "/api/arbiter/fleet-size-cap", json={ "cap": 12 } )

    assert response.status_code == 409
    assert "Lupin: Development" in response.json()[ "detail" ]
    assert "= 8" in path.read_text( encoding="utf-8" )


def test_the_fresh_DISK_value_beats_the_cached_configuration_singleton( client, monkeypatch, tmp_path ):
    """
    🔴 THE HALF THAT MAKES THE DIAL BITE. `ConfigurationManager` is a process-lifetime
    singleton with no reload, and the cap is enforced in the long-running host MCP
    process. Without a fresh read, an operator's write reaches the file and the enforcing
    process keeps its boot-time number until somebody bounces it — a control that changes
    nothing until a restart, which is what held this slider back in the first place.

    The config here says 8 and the FILE says 12. The disk must win.
    """
    _pin_ini( monkeypatch, tmp_path, REAL_SHAPED_INI.replace( "= 8", "= 12" ) )
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 18, CAP_KEY: 8 } ) )

    body = client.get( "/api/arbiter/fleet-size-cap" ).json()
    assert body[ "cap" ] == 12, "a stale singleton must not outvote the file on disk"


def test_an_unreadable_file_falls_back_to_the_configuration_manager( client, monkeypatch, tmp_path ):
    """Fail-soft: the fresh read is an improvement on the singleton, never a new way
    for the pane to break."""
    from lupin_mcp import fleet_size_cap
    monkeypatch.setattr( fleet_size_cap, "config_file_path",
                         lambda: str( tmp_path / "does-not-exist.ini" ) )
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 18, CAP_KEY: 6 } ) )
    assert client.get( "/api/arbiter/fleet-size-cap" ).json()[ "cap" ] == 6


# ── THE GUARD ───────────────────────────────────────────────────────────────────

def test_BOTH_verbs_are_REFUSED_without_a_credential( monkeypatch, tmp_path ):
    """
    🔴 REFUSED, NOT IGNORED, AND BOTH VERBS. This test builds its own app WITHOUT the
    dependency override the other tests use, so the real guard runs.

    A write endpoint that answered an unauthenticated caller would let anyone who can
    reach the port set the fleet cap. And a slider that silently 401s is the mirror
    failure — a dial that appears to work and governs nothing.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from lupin_mcp import fleet_size_cap

    path = tmp_path / "lupin-app.ini"
    path.write_text( REAL_SHAPED_INI, encoding="utf-8" )
    monkeypatch.setattr( fleet_size_cap, "config_file_path", lambda: str( path ) )

    app = FastAPI()
    app.include_router( arbiter.router )
    bare = TestClient( app )

    for call in ( lambda: bare.get( "/api/arbiter/fleet-size-cap" ),
                  lambda: bare.put( "/api/arbiter/fleet-size-cap", json={ "cap": 12 } ) ):
        response = call()
        assert response.status_code in ( 401, 403 ), \
               f"the guard must REFUSE, saw {response.status_code}"

    assert "= 8" in path.read_text( encoding="utf-8" ), \
           "and the refused write must not have touched the file"


def test_the_GET_reports_the_live_manager_worker_split( client, monkeypatch, tmp_path ):
    """
    The pane shows WHO is occupying the cap, counted the same way the gate counts it.
    Two derivations of one number agree on every ordinary day and diverge on exactly
    the day somebody needs them.
    """
    _pin_ini( monkeypatch, tmp_path, REAL_SHAPED_INI )
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 18, CAP_KEY: 8 } ) )
    monkeypatch.setattr( arbiter, "_live_fleet_counts",
                         lambda: { "total": 5, "managers": 2, "workers": 3 } )

    body = client.get( "/api/arbiter/fleet-size-cap" ).json()
    assert body[ "live" ] == { "total": 5, "managers": 2, "workers": 3 }


def test_an_unreadable_fleet_degrades_the_split_to_null_not_the_pane_to_an_error(
        client, monkeypatch, tmp_path ):
    """A census that cannot be taken must cost the split, never the cap."""
    _pin_ini( monkeypatch, tmp_path, REAL_SHAPED_INI )
    _pin_config( monkeypatch, FakeConfig( { CEILING_KEY: 18, CAP_KEY: 8 } ) )

    def _boom():
        raise RuntimeError( "no bridges here" )

    monkeypatch.setattr( arbiter, "_live_fleet_counts", _boom )
    response = client.get( "/api/arbiter/fleet-size-cap" )
    assert response.status_code == 200 and response.json()[ "live" ] is None
