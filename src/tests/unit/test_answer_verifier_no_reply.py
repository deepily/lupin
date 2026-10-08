"""
An empty model reply is its own outcome of the answer verifier, not a plain false at 0.0.

The model, client and template processor are boundary-mocked: no server, no spend, no
backoff delay. The real VerificationResponse parsing stays in the loop.
"""

from unittest.mock import MagicMock, patch

import cosa.agents.notification_proxy.verification as verif
from cosa.agents.notification_proxy.verification import LlmAnswerVerifier
from cosa.agents.notification_proxy.xml_models import VerificationResponse

GOOD_XML      = "<response><match>true</match><confidence>0.8</confidence><reasoning>ok</reasoning></response>"
MALFORMED_XML = "<response><match>true</match>"


def _verify( replies ):
    """Run one non-exact pair through a verifier whose model returns `replies` in turn."""
    fake_client = MagicMock()
    fake_client.run.side_effect = list( replies )
    factory = MagicMock()
    factory.get_client.return_value = fake_client
    with patch.object( verif, "LlmClientFactory", return_value=factory ), \
         patch.object( verif, "PromptTemplateProcessor", return_value=MagicMock() ):
        v = LlmAnswerVerifier()
    v._processor.process_template.return_value = "{question_context}{expected}{actual}"
    cu_mock = MagicMock()
    cu_mock.get_project_root.return_value   = "/root"
    cu_mock.get_file_as_string.return_value = "TEMPLATE"
    with patch.object( verif, "cu", cu_mock ), patch.object( verif.time, "sleep" ):
        return v.verify( "academic", "scholarly audience" ), fake_client


def test_three_empty_replies_are_a_no_reply_outcome():
    result, client = _verify( [ "", "", "" ] )
    assert isinstance( result, verif.NoReplyVerification )
    assert client.run.call_count == 3


def test_a_no_reply_outcome_still_reads_as_false_at_zero_to_old_callers():
    result, _ = _verify( [ "", "", "" ] )
    assert isinstance( result, VerificationResponse )
    assert result.match == "false"
    assert result.get_confidence_float() == 0.0


def test_a_no_reply_outcome_says_how_many_attempts_got_nothing():
    result, _ = _verify( [ "", "", "" ] )
    assert "no reply" in result.reasoning.lower()
    assert "3 attempts" in result.reasoning


def test_whitespace_only_replies_count_as_empty():
    result, _ = _verify( [ "   ", "\n", " \t " ] )
    assert isinstance( result, verif.NoReplyVerification )


def test_an_empty_reply_followed_by_an_answer_returns_the_answer():
    result, client = _verify( [ "", GOOD_XML ] )
    assert result.is_match()
    assert type( result ).__name__ == "VerificationResponse"
    assert client.run.call_count == 2


def test_replies_that_are_malformed_but_not_empty_stay_a_plain_error():
    result, _ = _verify( [ MALFORMED_XML, MALFORMED_XML, MALFORMED_XML ] )
    assert type( result ).__name__ == "VerificationResponse"
    assert result.match == "false"
    assert "LLM error after 3 attempts" in result.reasoning


def test_two_empty_replies_and_one_malformed_stay_a_plain_error():
    result, _ = _verify( [ "", "", MALFORMED_XML ] )
    assert type( result ).__name__ == "VerificationResponse"
    assert "LLM error after 3 attempts" in result.reasoning
