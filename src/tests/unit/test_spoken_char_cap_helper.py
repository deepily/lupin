"""
Unit tests for cosa.utils.util.get_spoken_char_cap().

This helper is the SINGLE SOURCE OF TRUTH for the cosa-voice spoken-char cap
(the server reject boundary). Both the per-turn TTS brevity rider
(hook_common._brevity_rules) and the caller-side enforcement guard
(cosa_voice_mcp._enforce_spoken_brevity) resolve the cap from this one key +
default so the rider's named number and the enforcement check can never drift.

Ratified basis: PIP S110 (2026-06-15) — the cap is a REJECT BOUNDARY, not a
target; the spoken target is sentence-based.

The helper:
    - reads the "cosa voice spoken char cap" INI key via the singleton
      ConfigurationManager
    - returns an int (the configured value, or SPOKEN_CHAR_CAP_DEFAULT)
    - returns SPOKEN_CHAR_CAP_DEFAULT if the ConfigurationManager constructor
      (or .get()) raises — never propagates

All tests mock ConfigurationManager at its source module path so the helper's
inside-function `from cosa.config.configuration_manager import ConfigurationManager`
resolves to the mock.
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
    assert cu.SPOKEN_CHAR_CAP_INI_KEY == "cosa voice spoken char cap"


def test_default_constant_is_500():
    assert cu.SPOKEN_CHAR_CAP_DEFAULT == 500


# ---------------------------------------------------------------------------
# Happy path — value resolved from config
# ---------------------------------------------------------------------------

@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_configured_value( mock_cm_class ):
    """INI key present — helper returns the configured int verbatim."""
    mock_cm_class.return_value = _patched_cm( get_return_value=420 )

    assert cu.get_spoken_char_cap() == 420


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_default_when_key_absent( mock_cm_class ):
    """
    When the INI key is absent, ConfigurationManager.get() returns the
    `default=SPOKEN_CHAR_CAP_DEFAULT` kwarg passed by the helper.
    """
    mock_cm_class.return_value = _patched_cm( get_return_value=cu.SPOKEN_CHAR_CAP_DEFAULT )

    assert cu.get_spoken_char_cap() == cu.SPOKEN_CHAR_CAP_DEFAULT


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_result_is_int( mock_cm_class ):
    mock_cm_class.return_value = _patched_cm( get_return_value=500 )

    assert isinstance( cu.get_spoken_char_cap(), int )


# ---------------------------------------------------------------------------
# Fail-closed — config error returns the default, never raises
# ---------------------------------------------------------------------------

@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_default_on_constructor_exception( mock_cm_class ):
    """ConfigurationManager constructor raises — helper catches, returns default."""
    mock_cm_class.side_effect = ValueError( "simulated env-var missing" )

    assert cu.get_spoken_char_cap() == cu.SPOKEN_CHAR_CAP_DEFAULT


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_default_on_get_exception( mock_cm_class ):
    """The .get() call raises — helper catches, returns default."""
    mock_instance     = MagicMock()
    mock_instance.get.side_effect = RuntimeError( "config read blew up" )
    mock_cm_class.return_value    = mock_instance

    assert cu.get_spoken_char_cap() == cu.SPOKEN_CHAR_CAP_DEFAULT


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_never_raises_on_arbitrary_exception( mock_cm_class ):
    """Contract is 'never raises' — inject an arbitrary Exception subclass."""
    class CustomException( Exception ): pass
    mock_cm_class.side_effect = CustomException( "anything" )

    try:
        result = cu.get_spoken_char_cap()
    except Exception as e:
        pytest.fail( f"helper raised {type( e ).__name__}: {e}" )

    assert result == cu.SPOKEN_CHAR_CAP_DEFAULT


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
