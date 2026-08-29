"""
The network guard's state is ONE copy, however many times the root conftest is loaded.

Row `89c3900a`, measured 2026-08-28. `src/conftest.py` is loaded TWICE as two separate
module objects. While the guard's state lived in that file, `pytest_runtest_setup` wrote a
test's `allows_outbound_network` marker into one copy's dict and the socket patch actually
installed read a DIFFERENT dict that nobody ever wrote to.

WHAT THAT COST, both of which a green suite hid:
  · every `allows_outbound_network` marker in the repo was INERT on a whole-directory run —
    including the one in the guard's own test sandbox
  · every recorded dial was blamed on `<collection>` instead of on a test, so the census
    the guard prints could not name a culprit on any directory-scoped run

⚠️ WHY the conftest is loaded twice is NOT established, and these tests deliberately do not
depend on it. They pin the PROPERTY that makes the cause irrelevant: the state lives in
`cosa.utils.unit_network_guard`, which has exactly one entry in `sys.modules`, so every copy
of the conftest binds the same objects.

Venue: :7999-eligible — the one dial goes to TEST-NET-1 (192.0.2.0/24, RFC 5737, guaranteed
unroutable) and is expected to fail; nothing here reaches a real service.
"""
import os

import pytest

import cosa.utils.unit_network_guard as ung

ROOT = os.environ[ "LUPIN_ROOT" ]


def _loaded_root_conftests( pluginmanager ):
    """
    Every module object pytest ACTUALLY loaded from `src/conftest.py`, however many there are.

    ⚠️ THIS IS THE REAL POPULATION, not a simulation. An earlier version of these tests spawned
    a subprocess that loaded the conftest twice on purpose. It worked standalone in 0.1s and
    timed out at 60s under pytest, four different ways — full env, stripped env, `-c`, a script
    file. I never established why, and chasing it further was measuring the harness instead of
    the code. Asking the plugin manager what it loaded is both cheaper AND stronger: it pins the
    copies that actually exist in this run rather than two I manufactured.
    """
    root = os.path.join( ROOT, "src", "conftest.py" )
    return [ p for p in pluginmanager.get_plugins()
             if getattr( p, "__file__", None ) and os.path.realpath( p.__file__ ) == os.path.realpath( root ) ]


def test_every_loaded_copy_of_the_root_conftest_shares_one_state_object( pytestconfig ):
    """
    🔴 THE REGRESSION TEST. `src/conftest.py` is loaded more than once — that is the defect
    (row 89c3900a) and it is not fixed here, only made harmless. What must hold is that every
    copy binds the SAME dict, so a marker recorded by one is seen by the guard installed from
    another.

    If someone moves the state back into the conftest, the copies diverge again and this fails.
    """
    copies = _loaded_root_conftests( pytestconfig.pluginmanager )
    assert copies, "no module loaded from src/conftest.py — this test is measuring nothing"
    for copy in copies:
        assert copy._current_test is ung.current_test, (
            "a loaded conftest copy holds a DIFFERENT _current_test than the shared module — "
            "every allows_outbound_network in the repo is inert again"
        )
        assert copy._outbound_attempts is ung.outbound_attempts, (
            "a loaded conftest copy holds a DIFFERENT _outbound_attempts than the shared module"
        )


def test_the_guard_lets_a_marked_test_dial_and_blocks_an_unmarked_one():
    """
    THE CONSEQUENCE, not the mechanism — and they are different claims. Sharing the dict is
    what makes the exemption reachable; being obeyed at the socket is what anyone cares about,
    and it was the consequence that shipped broken behind a green suite.

    Driven through a FAKE `real` so nothing dials: the point is which branch the wrapper takes.
    """
    dialled = []
    wrapped = ung.network_guard( lambda self, address, *a, **kw: dialled.append( address ) )
    saved   = dict( ung.current_test )
    try:
        ung.set_current_test( "a_test_that_declared_the_marker", True )
        wrapped( None, ( "192.0.2.1", 3001 ) )
        assert dialled == [ ( "192.0.2.1", 3001 ) ], "a MARKED test was not allowed through"

        ung.set_current_test( "a_test_that_did_not", False )
        if ung.NETWORK_MODE == "block":
            with pytest.raises( RuntimeError, match="OUTBOUND NETWORK BLOCKED" ):
                wrapped( None, ( "192.0.2.1", 3001 ) )
        else:
            # count/off: recorded (count) or ignored (off), never raised. Asserting the raise
            # here would make the test pass or fail on an environment variable.
            wrapped( None, ( "192.0.2.1", 3001 ) )
    finally:
        ung.set_current_test( saved[ "id" ], saved[ "exempt" ] )
        while ung.outbound_attempts and ung.outbound_attempts[ -1 ][ 0 ].startswith( "a_test_that" ):
            ung.outbound_attempts.pop()


def test_the_conftest_does_not_define_its_own_guard_state():
    """
    THE SINGLE-IMPLEMENTATION PROPERTY, asserted on the source — the same guard row 11253df9
    gap 3 put on the tree-state line, and for the same reason. If someone re-adds a local
    `_current_test = {...}` to the conftest, both places still LOOK right while drifting, and
    nothing else in the suite would notice.
    """
    source = open( os.path.join( ROOT, "src", "conftest.py" ) ).read()
    assert "from cosa.utils.unit_network_guard import" in source, (
        "the conftest no longer imports the shared guard state"
    )
    for name in ( "_outbound_attempts", "_current_test" ):
        assert f"\n{name}" not in source and f"\n{name} " not in source, (
            f"the conftest defines its own {name} again; there must be exactly one"
        )


def test_arming_twice_is_a_no_op():
    """
    A double-loaded conftest calls `arm()` twice. Without idempotence the guard wraps itself:
    every dial recorded twice, and a block-mode count nobody can reconcile against the run.

    Read from the module's own state rather than re-armed here — the guard is already armed
    (or deliberately disarmed) by the time this runs, and re-arming it inside the tier would
    change the instrument the whole tier is being measured with.
    """
    assert ung.arm() is False, "arm() re-patched an already-armed (or disarmed) process"


def test_set_current_test_mutates_in_place_rather_than_rebinding():
    """
    A rebind would hand every caller holding `from ... import current_test` a stale object —
    reintroducing the two-copies defect one level down, inside the fix for it.
    """
    held  = ung.current_test
    saved = dict( held )
    try:
        ung.set_current_test( "probe::nodeid", True )
        assert ung.current_test is held, "set_current_test rebound the dict instead of mutating it"
        assert held[ "id" ] == "probe::nodeid" and held[ "exempt" ] is True
    finally:
        ung.set_current_test( saved[ "id" ], saved[ "exempt" ] )


# ═════════════════════════════════════════════════════════════════════════════
# is_loopback — the arms that decide what the guard is allowed to touch
# ═════════════════════════════════════════════════════════════════════════════
# These are the guard's ONLY exemption that is not a marker, so they decide silently.
# Getting one wrong either breaks a legitimate TestClient run — after which somebody
# switches the guard off, which is worse than no guard — or lets a real dial through.

@pytest.mark.parametrize( "address, expected, why", [
    ( "/tmp/some.sock",         True,  "AF_UNIX: not a tuple, so not a routed address" ),
    ( (),                       True,  "empty tuple carries no host to judge" ),
    ( ( "127.0.0.1", 8000 ),    True,  "plain loopback" ),
    ( ( "localhost", 8000 ),    True,  "loopback by name" ),
    ( ( "0.0.0.0", 8000 ),      True,  "the any-address bind" ),
    ( ( "", 8000 ),             True,  "empty host" ),
    ( ( "::1", 8000 ),          True,  "IPv6 loopback" ),
    ( ( "127.42.7.9", 8000 ),   True,  "the whole 127/8 block, not just .0.1" ),
    ( ( "192.0.2.1", 3001 ),    False, "a routed address — the case the guard exists for" ),
    ( ( 12345, 3001 ),          False, "a non-string host is not loopback by default" ),
] )
def test_is_loopback_decides_each_address_shape( address, expected, why ):
    assert ung.is_loopback( address ) is expected, why


def test_the_guard_passes_a_loopback_dial_straight_through_without_recording_it():
    """
    THE BRANCH THAT MUST NOT RECORD. TestClient and the real-socket liveness arms bind
    127.0.0.1 deliberately; if those showed up in the outbound census, the census would be
    noise and the block-mode verdict would fail runs that did nothing wrong.
    """
    dialled = []
    wrapped = ung.network_guard( lambda self, address, *a, **kw: dialled.append( address ) )
    before  = len( ung.outbound_attempts )
    saved   = dict( ung.current_test )
    try:
        ung.set_current_test( "an_unmarked_test", False )
        wrapped( None, ( "127.0.0.1", 8000 ) )
        assert dialled == [ ( "127.0.0.1", 8000 ) ], "a loopback dial was not passed through"
        assert len( ung.outbound_attempts ) == before, "a loopback dial was recorded as outbound"
    finally:
        ung.set_current_test( saved[ "id" ], saved[ "exempt" ] )


def test_the_guard_is_inert_when_the_mode_is_off( monkeypatch ):
    """
    THE DEFAULT PATH, and the one the whole fleet runs on outside the unit tier.

    `off` is what integration and e2e runs get — they legitimately use the network and their
    runners do not set the variable. A guard that recorded or raised there would break lanes
    it was never meant to touch. Exercised by monkeypatching the module global, which is what
    the wrapper reads at call time, rather than by re-importing under a different environment.
    """
    monkeypatch.setattr( ung, "NETWORK_MODE", "off" )
    dialled = []
    wrapped = ung.network_guard( lambda self, address, *a, **kw: dialled.append( address ) )
    before  = len( ung.outbound_attempts )
    saved   = dict( ung.current_test )
    try:
        ung.set_current_test( "an_unmarked_test", False )
        wrapped( None, ( "192.0.2.1", 3001 ) )              # routed, unmarked, and still fine
        assert dialled == [ ( "192.0.2.1", 3001 ) ], "an off-mode dial was not passed through"
        assert len( ung.outbound_attempts ) == before, "an off-mode dial was recorded"
    finally:
        ung.set_current_test( saved[ "id" ], saved[ "exempt" ] )


def test_count_mode_records_without_raising( monkeypatch ):
    """
    COUNT IS NOT A WEAKER BLOCK — it is the census mode, and it exists because block mode's
    first offender fires at collection and takes the rest of the tier with it. A census that
    stops at its first finding is not a census.
    """
    monkeypatch.setattr( ung, "NETWORK_MODE", "count" )
    wrapped = ung.network_guard( lambda self, address, *a, **kw: None )
    saved   = dict( ung.current_test )
    before  = len( ung.outbound_attempts )
    try:
        ung.set_current_test( "an_unmarked_test", False )
        wrapped( None, ( "192.0.2.1", 3001 ) )              # records, does NOT raise
        assert len( ung.outbound_attempts ) == before + 1, "count mode did not record the dial"
        assert ung.outbound_attempts[ -1 ][ 0 ] == "an_unmarked_test", (
            "the recorded attempt does not name the test that made it — the blame defect"
        )
    finally:
        ung.set_current_test( saved[ "id" ], saved[ "exempt" ] )
        del ung.outbound_attempts[ before: ]
