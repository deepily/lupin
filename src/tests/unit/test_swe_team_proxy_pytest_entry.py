"""
The SWE Team proxy smoke entry skips when no proxy will answer its notifications.

Under pytest the hook that starts a proxy never fires, so a proxy exists only when the run
passes --auto-proxy. The smoke runner passes none. The old entry ran all three scenarios
anyway: three 503s and a red :7999 smoke tier (the row for test_swe_team_proxy).
"""
import pytest

import tests.smoke.test_swe_team_proxy as swe_module


class _Config:
    def __init__( self, auto_proxy ): self.auto_proxy = auto_proxy

    def getoption( self, name, default=None ):
        assert name == "--auto-proxy"
        return self.auto_proxy


class _Request:
    def __init__( self, auto_proxy ): self.config = _Config( auto_proxy )


@pytest.fixture
def scenarios_ran( monkeypatch ):
    ran = [ ]
    monkeypatch.setattr( swe_module, "quick_smoke_test", lambda: ran.append( "ran" ) or True )
    return ran


def test_without_auto_proxy_it_skips_and_runs_no_scenario( scenarios_ran, monkeypatch ):
    monkeypatch.setenv( "LUPIN_INTERACTIVE_TESTS", "true" )
    with pytest.raises( pytest.skip.Exception, match="--auto-proxy" ):
        swe_module.test_swe_team_proxy( _Request( auto_proxy=False ) )
    assert scenarios_ran == [ ]


def test_without_the_interactive_flag_it_skips_and_runs_no_scenario( scenarios_ran, monkeypatch ):
    monkeypatch.delenv( "LUPIN_INTERACTIVE_TESTS", raising=False )
    with pytest.raises( pytest.skip.Exception, match="LUPIN_INTERACTIVE_TESTS" ):
        swe_module.test_swe_team_proxy( _Request( auto_proxy=True ) )
    assert scenarios_ran == [ ]


def test_with_both_it_runs_the_scenarios_once( scenarios_ran, monkeypatch ):
    monkeypatch.setenv( "LUPIN_INTERACTIVE_TESTS", "true" )
    swe_module.test_swe_team_proxy( _Request( auto_proxy=True ) )
    assert scenarios_ran == [ "ran" ]


def test_a_failing_run_still_fails_the_test( monkeypatch ):
    monkeypatch.setenv( "LUPIN_INTERACTIVE_TESTS", "true" )
    monkeypatch.setattr( swe_module, "quick_smoke_test", lambda: False )
    with pytest.raises( AssertionError ):
        swe_module.test_swe_team_proxy( _Request( auto_proxy=True ) )
