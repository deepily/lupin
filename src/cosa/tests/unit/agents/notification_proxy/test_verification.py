#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.verification.LlmAnswerVerifier.

The LLM client (LlmClientFactory / its client.run), the prompt-template
processor, cosa.utils.util file/path helpers, and time.sleep are ALL
boundary-mocked → no vLLM call, no filesystem, no real backoff delay,
zero API spend. Real VerificationResponse parsing stays in the loop.
"""

from unittest.mock import MagicMock, patch

import cosa.agents.notification_proxy.verification as verif
from cosa.agents.notification_proxy.verification import LlmAnswerVerifier

GOOD_XML = "<response><match>true</match><confidence>0.8</confidence><reasoning>ok</reasoning></response>"


def _make_verifier( client_run=None, factory_raises=False, debug=False, verbose=False ):
    """
    Build an LlmAnswerVerifier with the LLM factory + template processor mocked.

    Requires:
        - client_run is a callable or side_effect for the fake client's run()
        - factory_raises forces the factory to raise (→ available=False)

    Ensures:
        - returns ( verifier, fake_client ) with all external boundaries mocked
    """
    fake_client = MagicMock()
    if client_run is not None:
        fake_client.run.side_effect = client_run

    factory = MagicMock()
    if factory_raises:
        factory.get_client.side_effect = RuntimeError( "no vLLM" )
    else:
        factory.get_client.return_value = fake_client

    with patch.object( verif, "LlmClientFactory", return_value=factory ), \
         patch.object( verif, "PromptTemplateProcessor", return_value=MagicMock() ):
        v = LlmAnswerVerifier( debug=debug, verbose=verbose )
    return v, fake_client


class TestInit:

    def test_available_when_client_builds( self ):
        v, _ = _make_verifier( client_run=lambda p: GOOD_XML, debug=True )
        assert v.available is True

    def test_unavailable_when_factory_raises( self ):
        v, _ = _make_verifier( factory_raises=True )
        assert v.available is False


class TestVerifyExactMatch:

    def test_exact_match_bypasses_llm( self ):
        """Case-insensitive, whitespace-stripped exact match → true/1.0, no client.run."""
        v, client = _make_verifier( client_run=lambda p: GOOD_XML, debug=True )
        r = v.verify( "  Academic ", "academic" )
        assert r.is_match()
        assert r.get_confidence_float() == 1.0
        client.run.assert_not_called()


class TestVerifyUnavailable:

    def test_unavailable_returns_false_response( self ):
        v, _ = _make_verifier( factory_raises=True, debug=True )
        r = v.verify( "a", "b" )
        assert not r.is_match()
        assert r.get_confidence_float() == 0.0


class TestVerifyLlmPath:

    def _patch_io( self ):
        """Patch cu file/path helpers + the template processor's process_template."""
        cu_mock = MagicMock()
        cu_mock.get_project_root.return_value  = "/root"
        cu_mock.get_file_as_string.return_value = "TEMPLATE"
        return cu_mock

    def test_llm_success_first_attempt( self ):
        v, client = _make_verifier( client_run=lambda p: GOOD_XML, debug=True, verbose=True )
        v._processor.process_template.return_value = "{question_context}{expected}{actual}"
        with patch.object( verif, "cu", self._patch_io() ):
            r = v.verify( "expected answer", "different actual", context="ctx" )
        assert r.is_match()
        client.run.assert_called_once()

    def test_llm_success_debug_off( self ):
        """Same success path with debug False → exercises the if-False debug arms."""
        v, client = _make_verifier( client_run=lambda p: GOOD_XML, debug=False )
        v._processor.process_template.return_value = "{question_context}{expected}{actual}"
        with patch.object( verif, "cu", self._patch_io() ):
            r = v.verify( "expected answer", "different actual" )
        assert r.is_match()

    def test_llm_retries_then_fails( self ):
        """Every attempt raises → retry+backoff arms fire, final returns false response."""
        v, client = _make_verifier( client_run=RuntimeError( "boom" ), debug=True )
        v._processor.process_template.return_value = "{question_context}{expected}{actual}"
        with patch.object( verif, "cu", self._patch_io() ), \
             patch.object( verif.time, "sleep" ) as sleep_mock:
            r = v.verify( "expected answer", "different actual" )
        assert not r.is_match()
        assert r.get_confidence_float() == 0.0
        assert client.run.call_count == 3            # max_attempts
        assert sleep_mock.call_count == 2            # backoff between the 3 attempts


class TestVerifyBatch:

    def test_batch_verifies_each_pair( self ):
        v, _ = _make_verifier( client_run=lambda p: GOOD_XML )
        results = v.verify_batch( [ ( "academic", "Academic" ), ( "no limit", "no limit" ) ] )
        assert len( results ) == 2
        assert all( r.is_match() for r in results )
