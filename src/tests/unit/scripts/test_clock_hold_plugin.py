"""
`src/scripts/clock_hold_plugin.py` — the fixed-interval session hold, covered without holding.

A straggler from Rio's two-tier census at `cc336880` (5 statements, the smallest on the zero
list). Claimed by the SOUND direction: `git grep -l -- clock_hold_plugin -- src/tests
src/cosa/tests` was EMPTY at `0f61dd85`, and empty is conclusive — nothing named cannot be
loaded. A hit would have proven nothing.

🔴 WHAT THIS FILE IS CAREFUL ABOUT.

· IT NEVER SLEEPS. The module's whole purpose is a 12-second `time.sleep`, so a test that let
  the real call through would add 12 seconds to the unit tier per case. `time.sleep` is patched
  at the MODULE attribute (`mod.time.sleep`), so a missed patch shows up as a slow test rather
  than as a silent pass — and the recorded argument is what the assertions read.
· THE ENVIRONMENT IS RESTORED. `LUPIN_CLOCK_HOLD_SECONDS` is read at CALL time, not import time,
  so `monkeypatch.delenv`/`setenv` is enough and no module reload is needed. The default case
  DELETES the variable rather than assuming it is unset, because this suite runs in a tier whose
  environment nobody controls.

WHY THE ASSERTIONS ARE ON THE RECORDED SLEEP rather than on elapsed time: elapsed time would
measure the test harness, not the module. The interval the module chose is the entire contract —
the docstring's own claim is that it must exceed the slowest poll interval among the threads
under test, and only the argument says what it chose.
"""

import importlib
import os
import sys

import pytest


_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

mod = importlib.import_module( "clock_hold_plugin" )


@pytest.fixture
def slept( monkeypatch ):
    """
    Replace the module's sleep with a recorder.

    Ensures:
        - returns a list that receives one entry per `time.sleep` call
        - no test in this file can block the tier for the real hold interval
    """
    calls = [ ]
    monkeypatch.setattr( mod.time, "sleep", lambda seconds: calls.append( seconds ) )
    return calls


def test_default_interval_is_twelve_seconds( slept, monkeypatch ):
    """With no environment override the hold is the documented 12.0 seconds."""
    monkeypatch.delenv( "LUPIN_CLOCK_HOLD_SECONDS", raising=False )

    mod.pytest_collection_finish( session=object() )

    assert slept == [ 12.0 ]


def test_default_exceeds_the_watcher_poll_interval( slept, monkeypatch ):
    """
    The default is not an arbitrary number — the docstring requires it to exceed the slowest
    poll interval among the threads under test, which is cosa_voice_mcp's 2.0s watcher. A
    default that dropped below that would make the lever demonstrate nothing.
    """
    monkeypatch.delenv( "LUPIN_CLOCK_HOLD_SECONDS", raising=False )

    mod.pytest_collection_finish( session=object() )

    assert slept[ 0 ] > 2.0


def test_environment_overrides_the_interval( slept, monkeypatch ):
    """LUPIN_CLOCK_HOLD_SECONDS replaces the default, parsed as a float."""
    monkeypatch.setenv( "LUPIN_CLOCK_HOLD_SECONDS", "3.5" )

    mod.pytest_collection_finish( session=object() )

    assert slept == [ 3.5 ]


def test_integer_valued_override_is_still_a_float( slept, monkeypatch ):
    """
    An override written without a decimal point still reaches `time.sleep` as a float.
    Asserted because the module's only conversion is `float( ... )`, and a bare string
    reaching sleep would raise rather than hold.
    """
    monkeypatch.setenv( "LUPIN_CLOCK_HOLD_SECONDS", "7" )

    mod.pytest_collection_finish( session=object() )

    assert slept == [ 7.0 ]
    assert isinstance( slept[ 0 ], float )


def test_zero_disables_the_hold_entirely( slept, monkeypatch ):
    """
    Zero is the off switch: the guard is `hold > 0`, so nothing is slept at all. This is the
    branch that makes the plugin loadable in a run that does not want the hold.
    """
    monkeypatch.setenv( "LUPIN_CLOCK_HOLD_SECONDS", "0" )

    mod.pytest_collection_finish( session=object() )

    assert slept == [ ]


def test_negative_interval_does_not_sleep( slept, monkeypatch ):
    """
    A negative value takes the same off path rather than reaching `time.sleep`, which would
    raise ValueError. The guard is `> 0`, not `!= 0`, and this is the case that proves it.
    """
    monkeypatch.setenv( "LUPIN_CLOCK_HOLD_SECONDS", "-1.0" )

    mod.pytest_collection_finish( session=object() )

    assert slept == [ ]


def test_malformed_override_raises_rather_than_silently_defaulting( slept, monkeypatch ):
    """
    An unparseable interval is a ValueError, not a fallback to 12.0. Recorded because the
    silent default would be the worse behaviour: the run would hold for a length nobody asked
    for while the operator believed their setting had taken.
    """
    monkeypatch.setenv( "LUPIN_CLOCK_HOLD_SECONDS", "not-a-number" )

    with pytest.raises( ValueError ):
        mod.pytest_collection_finish( session=object() )

    assert slept == [ ]


def test_session_argument_is_ignored( slept, monkeypatch ):
    """
    The hook takes pytest's session and does not touch it. Asserted with None, which would
    raise on any attribute access, so the claim is proven rather than assumed.
    """
    monkeypatch.setenv( "LUPIN_CLOCK_HOLD_SECONDS", "1" )

    mod.pytest_collection_finish( session=None )

    assert slept == [ 1.0 ]
