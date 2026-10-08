"""
The answer verifier's prompt ends with a newline after "### Response:".

Measured on the LAN Phi-4 (io/tmp/2026.10.07-rio-verifier-empty-answer-diagnosis.md).
Without the newline the server's first token is the end-of-turn token and the reply is
empty. With it the model answers. This pins the shape of the prompt. It does not test
the model, which needs a live server.
"""

import cosa.utils.util as cu
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor

TEMPLATE_PATH = "/src/conf/prompts/notification-proxy-answer-verifier.txt"


def _built_prompt():
    raw       = cu.get_file_as_string( cu.get_project_root() + TEMPLATE_PATH )
    processed = PromptTemplateProcessor( debug=False, verbose=False ).process_template( raw, "notification proxy answer verifier" )
    return processed.format( question_context="", expected="academic", actual="scholarly audience" )


def test_the_built_prompt_ends_with_a_newline_after_the_response_marker():
    assert _built_prompt().endswith( "### Response:\n" )


def test_the_marker_is_still_the_last_line():
    assert _built_prompt().rstrip( "\n" ).endswith( "### Response:" )


def test_the_pair_is_in_the_prompt():
    prompt = _built_prompt()
    assert "Expected answer: academic" in prompt
    assert "Actual answer: scholarly audience" in prompt
