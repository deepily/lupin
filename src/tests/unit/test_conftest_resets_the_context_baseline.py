"""
The process-wide context baseline is cleared around every test.

A notify-route test built it and left it set, so test_context_baseline failed only when
run after that test. The src/conftest.py fixture is driven by hand.
"""
import os

import cosa.agents.prediction_engine.context_baseline as cb


def _fixture_body( request ):
    """
    Return the undecorated generator of the src/conftest.py fixture.

    Requires:
        - request is the pytest `request` fixture
    Ensures:
        - returns the generator function
    """
    for plugin in request.config.pluginmanager.get_plugins():
        path = getattr( plugin, "__file__", None )
        if path is not None and os.path.realpath( path ) == os.path.realpath( request.config.rootpath / "src" / "conftest.py" ):
            fixture = plugin._reset_context_baseline_around_test
            return fixture.__wrapped__ if hasattr( fixture, "__wrapped__" ) else fixture.__pytest_wrapped__.obj
    raise AssertionError( "src/conftest.py plugin not found" )


def test_a_baseline_left_set_by_a_test_is_cleared_before_the_next_one_and_after_this_one( request ):
    body = _fixture_body( request )()
    cb._BASELINE, cb._GATE = object(), object()
    next( body )
    assert cb._BASELINE is None and cb._GATE is None
    cb._BASELINE, cb._GATE = object(), object()
    try:
        next( body )
    except StopIteration:
        pass
    assert cb._BASELINE is None and cb._GATE is None
