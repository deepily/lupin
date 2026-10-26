"""
The enforcement switch of `cosa.rest.flow_ratio_settings`.

The sibling file covers the window and the threshold. This one covers the third setting,
the switch that decides whether the ratio gate refuses a create or only warns.
A string such as "false" is truthy, so the write door must demand a real bool.
"""

import json

import pytest

from cosa.rest import flow_ratio_settings as frs


@pytest.fixture
def isolated( tmp_path, monkeypatch ):
    """Point the override file at tmp_path and reset the cache, with all three settings."""
    target = tmp_path / "flow-ratio-settings.json"
    monkeypatch.setattr( frs, "override_path", lambda: str( target ) )
    monkeypatch.setattr( frs, "_cache", { "window_hours": None, "allow_below": None, "enforcement_active": None } )
    monkeypatch.setattr( frs, "_cache_mtime", None )
    return target


def test_a_stored_true_is_read_back_and_reported_by_the_write( isolated ):
    returned = frs.set_overrides( enforcement_active=True )
    assert returned[ "enforcement_active" ] is True
    assert frs.get_enforcement_active() is True
    assert json.loads( isolated.read_text() )[ "enforcement_active" ] is True


def test_a_stored_false_wins_over_an_ini_that_says_true( isolated, monkeypatch ):
    """False is a stored answer, not an absent one, so the INI is never consulted."""
    frs.set_overrides( enforcement_active=False )
    monkeypatch.setattr( frs, "_ini_value", lambda *a, **k: pytest.fail( "ini read despite a stored value" ) )
    assert frs.get_enforcement_active() is False


def test_with_nothing_stored_the_ini_decides( isolated, monkeypatch ):
    seen = { }
    def ini( key, return_type, fallback ):
        seen.update( key=key, return_type=return_type, fallback=fallback )
        return True
    monkeypatch.setattr( frs, "_ini_value", ini )
    assert frs.get_enforcement_active() is True
    assert seen == { "key": frs.INI_KEY_ENFORCEMENT, "return_type": "boolean", "fallback": frs.FALLBACK_ENFORCEMENT_ACTIVE }


@pytest.mark.parametrize( "given", [ "false", "true", 1, 0, "" ] )
def test_a_value_that_is_not_a_real_bool_is_refused_and_nothing_is_written( isolated, given ):
    with pytest.raises( ValueError, match = "enforcement_active must be a bool" ):
        frs.set_overrides( enforcement_active=given )
    assert not isolated.exists()


def test_setting_enforcement_leaves_the_other_two_settings_alone( isolated ):
    frs.set_overrides( window_hours=48, allow_below=2.5 )
    returned = frs.set_overrides( enforcement_active=True )
    assert ( returned[ "window_hours" ], returned[ "allow_below" ], returned[ "enforcement_active" ] ) == ( 48, 2.5, True )
