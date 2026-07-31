"""
Unit tests for cosa.utils.util.get_dm_style_contract_enabled().

This helper is the SINGLE SOURCE OF TRUTH for the DM Style Contract toggle
(Phase 1 prompting-only DM brevity/tone A/B, Rick 2026-07-31). It gates BOTH
the send-side MCP `instructions` § DM Style Contract + dm_send docstring
addendum (lupin_mcp.cosa_voice_mcp) and the reply-side rider resolver
(lupin_cli...hook_common._peer_dm_reply_rider), so the two surfaces can never
drift out of sync with each other.

The helper:
    - reads the "dm style contract enabled" INI key via the singleton
      ConfigurationManager
    - returns a bool (the configured value, or DM_STYLE_CONTRACT_DEFAULT)
    - returns DM_STYLE_CONTRACT_DEFAULT (False) if the ConfigurationManager
      constructor (or .get()) raises — never propagates

All tests mock ConfigurationManager at its source module path, mirroring
test_spoken_char_cap_helper.py's convention.
"""

import pytest
from unittest.mock import MagicMock, patch

from cosa.utils import util as cu


def _patched_cm( get_return_value ):
    """
    Build a mocked ConfigurationManager instance.

    Requires:
        - get_return_value is whatever the mock's .get() method should return

    Ensures:
        - Returns a MagicMock suitable for `mock_cm_class.return_value = ...`
        - The returned mock's .get(...) ignores all args and returns get_return_value
    """
    mock_instance                  = MagicMock()
    mock_instance.get.return_value = get_return_value
    return mock_instance


# ---------------------------------------------------------------------------
# Single-source constants
# ---------------------------------------------------------------------------

def test_ini_key_constant():
    assert cu.DM_STYLE_CONTRACT_INI_KEY == "dm style contract enabled"


def test_default_constant_is_false():
    assert cu.DM_STYLE_CONTRACT_DEFAULT is False


# ---------------------------------------------------------------------------
# Happy path — value resolved from config
# ---------------------------------------------------------------------------

@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_configured_true( mock_cm_class ):
    """INI key present and True — helper returns True verbatim."""
    mock_cm_class.return_value = _patched_cm( get_return_value=True )

    assert cu.get_dm_style_contract_enabled() is True


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_configured_false( mock_cm_class ):
    """INI key present and explicitly False — helper returns False verbatim."""
    mock_cm_class.return_value = _patched_cm( get_return_value=False )

    assert cu.get_dm_style_contract_enabled() is False


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_default_when_key_absent( mock_cm_class ):
    """
    When the INI key is absent, ConfigurationManager.get() returns the
    `default=DM_STYLE_CONTRACT_DEFAULT` kwarg passed by the helper.
    """
    mock_cm_class.return_value = _patched_cm( get_return_value=cu.DM_STYLE_CONTRACT_DEFAULT )

    assert cu.get_dm_style_contract_enabled() == cu.DM_STYLE_CONTRACT_DEFAULT


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_result_is_bool( mock_cm_class ):
    mock_cm_class.return_value = _patched_cm( get_return_value=True )

    assert isinstance( cu.get_dm_style_contract_enabled(), bool )


# ---------------------------------------------------------------------------
# Fail-closed — config error returns the default (control/off), never raises
# ---------------------------------------------------------------------------

@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_default_on_constructor_exception( mock_cm_class ):
    """ConfigurationManager constructor raises — helper catches, returns default."""
    mock_cm_class.side_effect = ValueError( "simulated env-var missing" )

    assert cu.get_dm_style_contract_enabled() == cu.DM_STYLE_CONTRACT_DEFAULT


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_default_on_get_exception( mock_cm_class ):
    """The .get() call raises — helper catches, returns default."""
    mock_instance     = MagicMock()
    mock_instance.get.side_effect = RuntimeError( "config read blew up" )
    mock_cm_class.return_value    = mock_instance

    assert cu.get_dm_style_contract_enabled() == cu.DM_STYLE_CONTRACT_DEFAULT


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_never_raises_on_arbitrary_exception( mock_cm_class ):
    """Contract is 'never raises' — inject an arbitrary Exception subclass."""
    class CustomException( Exception ): pass
    mock_cm_class.side_effect = CustomException( "anything" )

    try:
        result = cu.get_dm_style_contract_enabled()
    except Exception as e:
        pytest.fail( f"helper raised {type( e ).__name__}: {e}" )

    assert result == cu.DM_STYLE_CONTRACT_DEFAULT


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
