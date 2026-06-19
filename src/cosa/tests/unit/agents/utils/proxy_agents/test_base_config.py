"""
Unit tests for cosa/agents/utils/proxy_agents/base_config.py.

Pure credential / api-key resolution. The env is patched with INJECTED fake
values — the real ANTHROPIC_API_KEY_FIREWALLED is NEVER read (cost invariant);
`cu.get_api_key` is mocked. ZERO API spend.
"""
import argparse
from unittest.mock import patch

import pytest

import cosa.agents.utils.proxy_agents.base_config as cfg
from cosa.agents.utils.proxy_agents.base_config import get_credentials, get_anthropic_api_key


# =========================================================================== #
# get_credentials
# =========================================================================== #
def test_get_credentials_from_cli_flags():
    # cli args truthy → short-circuit, env not consulted
    assert get_credentials( cli_email="a@x.com", cli_password="pw" ) == ( "a@x.com", "pw" )


def test_get_credentials_from_env_when_no_cli():
    env = {
        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL"    : "env@x.com",
        "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" : "envpw",
    }
    with patch.dict( "os.environ", env, clear=True ):
        assert get_credentials() == ( "env@x.com", "envpw" )


def test_get_credentials_missing_email_raises():
    with patch.dict( "os.environ", {}, clear=True ):
        with pytest.raises( ValueError, match="No email found" ):
            get_credentials()


def test_get_credentials_missing_password_raises():
    with patch.dict( "os.environ", {}, clear=True ):
        with pytest.raises( ValueError, match="No password found" ):
            get_credentials( cli_email="a@x.com" )


# =========================================================================== #
# get_anthropic_api_key  ( real firewalled key NEVER read — env injected/cleared )
# =========================================================================== #
def test_get_anthropic_api_key_from_env():
    with patch.dict( "os.environ", { "ANTHROPIC_API_KEY_FIREWALLED": "fake-test-key" }, clear=True ):
        assert get_anthropic_api_key() == "fake-test-key"


def test_get_anthropic_api_key_from_file_when_env_absent():
    with patch.dict( "os.environ", {}, clear=True ), \
         patch( "cosa.utils.util.get_api_key", return_value="file-key" ):
        assert get_anthropic_api_key() == "file-key"


def test_get_anthropic_api_key_file_read_raises_returns_none():
    with patch.dict( "os.environ", {}, clear=True ), \
         patch( "cosa.utils.util.get_api_key", side_effect=RuntimeError( "no file" ) ):
        assert get_anthropic_api_key() is None


def test_get_anthropic_api_key_file_returns_none_returns_none():
    with patch.dict( "os.environ", {}, clear=True ), \
         patch( "cosa.utils.util.get_api_key", return_value=None ):
        assert get_anthropic_api_key() is None


# =========================================================================== #
# module constants ( sanity — they back the CLI defaults )
# =========================================================================== #
def test_connection_defaults_present():
    assert cfg.DEFAULT_SERVER_HOST == "localhost"
    assert cfg.DEFAULT_SERVER_PORT == 7999
    assert cfg.RECONNECT_MAX_ATTEMPTS == 10
