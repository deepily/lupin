"""
The real lupin_app.main comes back as the same object after each test.

The autouse eviction fixture used to drop it for good, so a class defined there had two
identities across files. The fixture is driven by hand against a stand-in package.
"""
import os
import sys
import types

import pytest


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
            fixture = plugin._evict_real_fastapi_main_after_test
            return fixture.__wrapped__ if hasattr( fixture, "__wrapped__" ) else fixture.__pytest_wrapped__.obj
    raise AssertionError( "src/conftest.py plugin not found" )


@pytest.fixture
def stand_in_package( monkeypatch ):
    """
    Register a stand-in package holding a stand-in main.

    Ensures:
        - both are in sys.modules until the test ends
    """
    pkg  = types.ModuleType( "lupin_app" )
    main = types.ModuleType( "lupin_app.main" )
    pkg.main = main
    monkeypatch.setitem( sys.modules, "lupin_app", pkg )
    monkeypatch.setitem( sys.modules, "lupin_app.main", main )
    return pkg, main


def test_real_main_is_hidden_during_the_test_and_restored_after( request, stand_in_package ):
    pkg, main = stand_in_package
    gen = _fixture_body( request )()
    next( gen )
    # the property the docstring names: nothing for a patch.dict to be defeated by
    assert "lupin_app.main" not in sys.modules
    assert not hasattr( pkg, "main" )
    # the test imports its own copy; it must be discarded, not kept
    other = types.ModuleType( "lupin_app.main" )
    sys.modules[ "lupin_app.main" ] = other
    pkg.main = other
    with pytest.raises( StopIteration ):
        next( gen )
    assert sys.modules[ "lupin_app.main" ] is main
    assert pkg.main is main


def test_absent_main_stays_absent_and_nothing_a_test_loaded_survives( request, stand_in_package ):
    pkg, main = stand_in_package
    del sys.modules[ "lupin_app.main" ]
    del pkg.main
    gen = _fixture_body( request )()
    next( gen )
    loaded = types.ModuleType( "lupin_app.main" )
    sys.modules[ "lupin_app.main" ] = loaded
    pkg.main = loaded
    with pytest.raises( StopIteration ):
        next( gen )
    assert "lupin_app.main" not in sys.modules
    assert not hasattr( pkg, "main" )
