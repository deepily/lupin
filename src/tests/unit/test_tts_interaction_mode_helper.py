"""
Unit tests for cosa.utils.util.get_tts_interaction_mode().

Phase 1 of the TTS Interaction Mode (Solo / Chorus) refactor — verifies the
config helper's value-validation + fail-closed-to-default semantics.

Design doc: src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/10-phase1-ini-plumbing-design.md

The helper:
    - reads the "tts interaction mode" INI key via the singleton ConfigurationManager
    - returns "solo" or "chorus" (the only valid values)
    - returns "chorus" (the operational default per 2026-05-12 override) if the key
      is absent, has an invalid value, returns None, has wrong case, or if the
      ConfigurationManager constructor raises

All tests mock ConfigurationManager at its source module path so the helper's
inside-function `from cosa.config.configuration_manager import ConfigurationManager`
resolves to the mock.
"""

import pytest
from unittest.mock import patch, MagicMock

from cosa.utils import util as cu


# ---------------------------------------------------------------------------
# Helper — build a mocked ConfigurationManager class whose () call returns an
# instance with a configurable .get() return value.
# ---------------------------------------------------------------------------

def _patched_cm( get_return_value ):
    """
    Build a mocked ConfigurationManager class.

    Requires:
        - get_return_value is whatever the mock's .get() method should return
          (string, None, or any other type to exercise validation)

    Ensures:
        - Returns a MagicMock suitable for `mock_cm_class.return_value = ...`
        - The returned mock's .get(...) ignores all args and returns get_return_value
    """
    mock_instance        = MagicMock()
    mock_instance.get.return_value = get_return_value
    return mock_instance


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_chorus_when_key_absent( mock_cm_class ):
    """
    When the INI key is absent, ConfigurationManager.get() returns the
    `default="chorus"` kwarg passed by the helper. Helper should return chorus.
    """
    mock_cm_class.return_value = _patched_cm( get_return_value="chorus" )

    assert cu.get_tts_interaction_mode() == "chorus"


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_solo_explicit( mock_cm_class ):
    """
    INI key explicitly set to 'solo' — helper returns 'solo' (no fail-closed).
    """
    mock_cm_class.return_value = _patched_cm( get_return_value="solo" )

    assert cu.get_tts_interaction_mode() == "solo"


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_chorus_explicit( mock_cm_class ):
    """
    INI key explicitly set to 'chorus' — helper returns 'chorus'.
    """
    mock_cm_class.return_value = _patched_cm( get_return_value="chorus" )

    assert cu.get_tts_interaction_mode() == "chorus"


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_chorus_on_invalid_value( mock_cm_class ):
    """
    Invalid INI value ('monopoly') — helper returns 'chorus' fail-closed to default.
    """
    mock_cm_class.return_value = _patched_cm( get_return_value="monopoly" )

    assert cu.get_tts_interaction_mode() == "chorus"


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_chorus_on_config_exception( mock_cm_class ):
    """
    ConfigurationManager constructor raises (e.g., env var missing) —
    helper catches and returns 'chorus' rather than propagating.
    """
    mock_cm_class.side_effect = ValueError( "simulated env-var missing" )

    assert cu.get_tts_interaction_mode() == "chorus"


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_returns_chorus_on_none_value( mock_cm_class ):
    """
    .get() returns None (defensive — shouldn't happen with default= kwarg,
    but exercised for robustness). Helper returns 'chorus' (None not in valid set).
    """
    mock_cm_class.return_value = _patched_cm( get_return_value=None )

    assert cu.get_tts_interaction_mode() == "chorus"


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_case_sensitivity_solo( mock_cm_class ):
    """
    Upper-case 'SOLO' — INI values are case-sensitive by convention; helper
    fail-closes to 'chorus'. Protects against accidental wrong-case INI edits.
    """
    mock_cm_class.return_value = _patched_cm( get_return_value="SOLO" )

    assert cu.get_tts_interaction_mode() == "chorus"


@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_case_sensitivity_chorus( mock_cm_class ):
    """
    Title-case 'Chorus' — case-sensitive fail-closed to default 'chorus'.
    """
    mock_cm_class.return_value = _patched_cm( get_return_value="Chorus" )

    assert cu.get_tts_interaction_mode() == "chorus"


# ---------------------------------------------------------------------------
# Contract verifications — helper does NOT raise for any of the above paths
# ---------------------------------------------------------------------------

@patch( "cosa.config.configuration_manager.ConfigurationManager" )
def test_never_raises_on_exception( mock_cm_class ):
    """
    The helper's contract is 'never raises'. Verify by injecting an arbitrary
    Exception subclass into the constructor.
    """
    class CustomException( Exception ): pass
    mock_cm_class.side_effect = CustomException( "anything" )

    try:
        result = cu.get_tts_interaction_mode()
    except Exception as e:
        pytest.fail( f"helper raised {type( e ).__name__}: {e}" )

    assert result in ( "solo", "chorus" )


# ---------------------------------------------------------------------------
# Smoke entry point (matches CoSA module convention)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
