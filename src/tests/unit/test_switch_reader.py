"""
Tests of the shared switch reader and of the two readers that call it.

The first two tests read a switch and an unreadable switch. The last two tests check both callers.
"""
import inspect

from cosa.agents.decision_proxy import config as proxy_config
from cosa.agents.prediction_engine import principles_forecast as pf
from cosa.config import switch_reader as sr


class Manager:
    """Stand-in for ConfigurationManager that records what it was asked."""
    asked = []
    value = True
    error = None

    def __init__( self, env_var_name=None ):
        Manager.asked.append( ( "env", env_var_name ) )

    def get( self, key, default=None, return_type=None ):
        Manager.asked.append( ( key, default, return_type ) )
        if Manager.error is not None: raise Manager.error
        return Manager.value


def fresh( value=True, error=None ):
    Manager.asked, Manager.value, Manager.error = [], value, error


def test_a_readable_switch_returns_the_managers_answer_and_passes_key_default_and_type():
    fresh( value=False )
    assert sr.read_switch( Manager, "some key", "False", lambda e: "never" ) is False
    assert Manager.asked == [ ( "env", sr.ENV_VAR_NAME ), ( "some key", "False", "boolean" ) ]
    fresh( value=True )
    assert sr.read_switch( Manager, "some key", False, lambda e: "never" ) is True


def test_an_unreadable_switch_is_off_and_prints_the_callers_line( capsys ):
    fresh( error=RuntimeError( "no ini" ) )
    assert sr.read_switch( Manager, "k", False, lambda e: f"line: {e}" ) is False
    assert capsys.readouterr().out == "line: no ini\n"


def test_a_manager_that_cannot_be_built_is_also_off( capsys ):
    def broken( env_var_name ): raise OSError( "no file" )
    assert sr.read_switch( broken, "k", False, lambda e: e.__class__.__name__ ) is False
    assert capsys.readouterr().out == "OSError\n"


def test_the_two_callers_read_through_the_shared_reader_and_keep_their_own_lines( monkeypatch, capsys ):
    monkeypatch.setattr( pf, "ConfigurationManager", Manager )
    fresh( value=True )
    assert pf.switch_enabled( "a key" ) is True
    assert Manager.asked[ 1 ] == ( "a key", False, "boolean" )
    fresh( error=RuntimeError( "boom" ) )
    assert pf.switch_enabled( "a key" ) is False
    assert capsys.readouterr().out == "[PRINCIPLES] ⚠️ Switch 'a key' unreadable, treated as off: boom\n"

    import cosa.config.configuration_manager as cm
    monkeypatch.setattr( cm, "ConfigurationManager", Manager )
    fresh( value=True )
    assert proxy_config.shadow_forecast_recording_enabled() is True
    assert Manager.asked[ 1 ] == ( proxy_config.SHADOW_FORECAST_RECORDING_KEY, "False", "boolean" )
    fresh( error=RuntimeError( "boom" ) )
    assert proxy_config.shadow_forecast_recording_enabled() is False
    assert capsys.readouterr().out == "[DECISION-PROXY] shadow forecast switch unreadable, recording no forecast: RuntimeError: boom\n"


def test_neither_caller_repeats_the_try_and_the_manager_call():
    for fn in ( pf.switch_enabled, proxy_config.shadow_forecast_recording_enabled ):
        body = inspect.getsource( fn )
        assert "read_switch(" in body and "except Exception" not in body, fn.__name__
