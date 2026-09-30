#!/usr/bin/env python3
"""
Landing test for the commons disambiguator's timeout — row abe4188d.

WHY THIS IS NOT A DUPLICATE of the two unit files that already cover the fix.
`test_commons_llm_disambiguator.py` mocks the client, so it proves the disambiguator
hands a timeout to whatever it is given. `test_llm_completion_timeout.py` constructs
the completion client directly, so it proves that client honours one. Neither asks
the question in between: does the client the SHIPPED spec key actually resolves to
honour it?

That seam is where the defect would come back. `commons llm disambiguator timeout
seconds` reaches the transport only along the completion path. Re-point
`llm spec key for commons persona disambiguator` at a chat-mode model tomorrow and
the timeout lands in **kwargs and is dropped in silence — the original defect, in a
different file, with both unit suites still green. So this reads the real config with
no mock on the config seam, and asserts the bound arrives at the socket layer.

The wire is stubbed, never opened: `requests.post` is patched. No network, no spend,
:7999-safe.
"""

from unittest.mock import MagicMock, patch

import pytest

from cosa.agents.llm_client_factory import LlmClientFactory
from cosa.config.configuration_manager import ConfigurationManager

SPEC_KEY    = "llm spec key for commons persona disambiguator"
TIMEOUT_KEY = "commons llm disambiguator timeout seconds"


@pytest.fixture
def real_factory():
    """
    A factory over the REAL ConfigurationManager. Both singletons are reset going in,
    so a mocked factory from another module cannot leak in, and on the way out, so
    this real one cannot leak into a later test.
    """
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
    LlmClientFactory._instance = None
    yield LlmClientFactory()
    LlmClientFactory._instance = None
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )


def test_the_shipped_spec_key_resolves_to_a_client_that_honours_a_timeout( real_factory ):
    """
    Ensures:
        - the client the real spec key resolves to accepts `timeout=` on run()
        - that value reaches requests.post as a positive bound

    Red arms, both real: drop `timeout=` from the requests.post call in
    llm_completion.py, or re-point the spec key at a chat-mode model — in the second
    case requests.post is never reached at all and the mock records no call.
    """
    config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    client = real_factory.get_client( config.get( SPEC_KEY ) )

    ok = MagicMock( status_code=200 )
    ok.json.return_value = { "choices": [ { "text": "<matched_persona/>" } ] }

    # The tokenize probe is a second HTTP call; stub it so this test is about the post.
    with patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) ), \
         patch( "cosa.agents.llm_completion.requests.post", return_value=ok ) as post:
        client.run( "which persona is meant?", timeout=3.0 )

    assert post.call_count == 1, "the spec key no longer routes through the completion path"

    sent = post.call_args.kwargs[ "timeout" ]
    assert sent is not None, "the bound was accepted and then dropped before the wire"
    assert 0 < sent <= 3.0


def test_the_shipped_ini_still_carries_a_timeout_to_configure( real_factory ):
    """
    Ensures:
        - the INI key the disambiguator reads is present and positive

        Deleting it would not break anything loudly — the module default takes over —
        so the only way the loss shows up is a test that names the key.
    """
    configured = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get( TIMEOUT_KEY )

    assert configured is not None
    assert float( configured ) > 0


def test_a_real_transport_timeout_reaches_the_disambiguator_as_a_fallback( real_factory, capsys ):
    """
    The seam, end to end — Rio's blocker, and he was right to call it.

    Every other test in this change proves ONE HALF. The disambiguator suite raises a
    builtin TimeoutError directly at the client mock, which is the half AFTER the
    translation; the llm_completion suite asserts the translation in isolation. Neither
    puts a REAL `requests.exceptions.ConnectTimeout` in at the socket and reads the
    answer out at `disambiguate()`. A defect living exactly in the join — the
    disambiguator constructing a client that does not translate, say — would have left
    both suites green.

    So: real disambiguator, real config, real factory, real CompletionClient, real
    LlmCompletion. Only the socket is a stub.

    Ensures:
        - a transport-level ConnectTimeout comes out as None, not an exception
        - the TIMEOUT branch is what ran

    That second assertion is not decoration. `disambiguate` returns None down at least
    six paths, so `is None` alone cannot say which one fired; the debug trace names it.
    """
    from lupin_mcp.commons_llm_disambiguator import CommonsLlmDisambiguator
    from lupin_mcp.commons_xml_models import PersonaInfo

    import requests

    config   = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    personas = [ PersonaInfo( name="Rachel", icon="🎸" ), PersonaInfo( name="Rio", icon="⚡" ) ]

    with patch( "cosa.agents.model_window.count_tokens", return_value=( 10, 8192 ) ), \
         patch( "cosa.agents.llm_completion.requests.post",
                side_effect=requests.exceptions.ConnectTimeout( "unroutable base_url" ) ):
        answer = CommonsLlmDisambiguator( config, debug=True ).disambiguate( personas, "the R session" )

    assert answer is None

    trace = capsys.readouterr().out
    assert "PHI-4 failed" in trace, "the except clause never caught it — the translation did not survive the chain"
    assert "TimeoutError" in trace, "something else was caught; the transport exception was not translated"
    assert "Haiku fallback stubbed" in trace, "the timeout branch did not route to the fallback"
