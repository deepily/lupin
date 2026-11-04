"""
The live presentation smoke entries skip without a proxy opt-in.

They need --auto-proxy and LUPIN_INTERACTIVE_TESTS=true; with both they run their real check.
Covers the shared gate and both entries.
"""
import pytest

import tests.smoke.test_presentation_live_smoke as presentation_module
import tests.smoke.test_research_to_presentation_live_smoke as research_module
from tests.smoke.utilities.proxy_opt_in import skip_unless_proxy_opt_in


class _Config:
    def __init__( self, auto_proxy ): self.auto_proxy = auto_proxy

    def getoption( self, name, default=None ):
        assert name == "--auto-proxy"
        return self.auto_proxy


class _Request:
    def __init__( self, auto_proxy ): self.config = _Config( auto_proxy )


ENTRIES = [
    pytest.param( presentation_module, "test_presentation_live_endpoint", id="presentation" ),
    pytest.param( research_module, "test_research_to_presentation_live", id="research" ),
]


def test_gate_skips_without_auto_proxy( monkeypatch ):
    monkeypatch.setenv( "LUPIN_INTERACTIVE_TESTS", "true" )
    with pytest.raises( pytest.skip.Exception, match="--auto-proxy" ):
        skip_unless_proxy_opt_in( _Request( auto_proxy=False ) )


def test_gate_skips_without_interactive_flag( monkeypatch ):
    monkeypatch.delenv( "LUPIN_INTERACTIVE_TESTS", raising=False )
    with pytest.raises( pytest.skip.Exception, match="LUPIN_INTERACTIVE_TESTS" ):
        skip_unless_proxy_opt_in( _Request( auto_proxy=True ) )


def test_gate_passes_with_both_case_insensitively( monkeypatch ):
    monkeypatch.setenv( "LUPIN_INTERACTIVE_TESTS", "TRUE" )
    assert skip_unless_proxy_opt_in( _Request( auto_proxy=True ) ) is None


@pytest.mark.parametrize( "module, name", ENTRIES )
def test_entry_skips_and_runs_nothing_without_opt_in( module, name, monkeypatch ):
    ran = [ ]
    monkeypatch.setattr( module, "quick_smoke_test", lambda argv=None: ran.append( argv ) or True )
    monkeypatch.setenv( "LUPIN_INTERACTIVE_TESTS", "true" )
    with pytest.raises( pytest.skip.Exception, match="--auto-proxy" ):
        getattr( module, name )( _Request( auto_proxy=False ) )
    assert ran == [ ]


@pytest.mark.parametrize( "module, name", ENTRIES )
def test_entry_runs_the_real_check_once_with_opt_in( module, name, monkeypatch ):
    ran = [ ]
    monkeypatch.setattr( module, "quick_smoke_test", lambda argv=None: ran.append( "ran" ) or True )
    monkeypatch.setenv( "LUPIN_INTERACTIVE_TESTS", "true" )
    getattr( module, name )( _Request( auto_proxy=True ) )
    assert ran == [ "ran" ]


@pytest.mark.parametrize( "module, name", ENTRIES )
def test_entry_with_opt_in_still_fails_when_the_check_fails( module, name, monkeypatch ):
    monkeypatch.setattr( module, "quick_smoke_test", lambda argv=None: False )
    monkeypatch.setenv( "LUPIN_INTERACTIVE_TESTS", "true" )
    with pytest.raises( AssertionError ):
        getattr( module, name )( _Request( auto_proxy=True ) )
