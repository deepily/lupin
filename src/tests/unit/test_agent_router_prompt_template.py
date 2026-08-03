#!/usr/bin/env python3
"""
Unit tests for the agent-router prompt template.

Guards the defect found 2026-08-02: the completion template carried an
unsubstituted `{{PYDANTIC_XML_EXAMPLE}}` marker, but the only rendering the
router does is `template.format( voice_command=... )` (todo_fifo_queue.py
_get_routing_command). `.format()` collapses `{{X}}` to `{X}` — it does NOT
call PromptTemplateProcessor — so the LLM was shown a literal
`{PYDANTIC_XML_EXAMPLE}` where the response example belongs. With no shape to
copy the model invented `<agent-routing-command>`, CommandResponse.from_xml
rejected it (`command` field missing), the router reported "unknown", and the
push fell through to the web-search else-branch.

These tests render the template exactly as the router does and assert the
response example survives.
"""

import pytest

import cosa.utils.util as du
from cosa.agents.io_models.xml_models import CommandResponse


ROUTER_TEMPLATE_PATH = "/src/conf/prompts/agent-router-template-completion.txt"


@pytest.fixture
def rendered_prompt():
    """The router prompt as _get_routing_command actually builds it."""
    template = du.get_file_as_string( du.get_project_root() + ROUTER_TEMPLATE_PATH )
    return template.format( voice_command="build me a podcast about the KISS protocol" )


class TestAgentRouterPromptTemplate:
    """The rendered prompt must teach the tag CommandResponse parses."""

    def test_no_unsubstituted_marker_survives_rendering( self, rendered_prompt ):
        """
        Neither the raw `{{PYDANTIC_XML_EXAMPLE}}` marker nor its post-format
        `{PYDANTIC_XML_EXAMPLE}` collapse may reach the LLM.

        This is the assertion that fails against the pre-fix template: `.format()`
        turned the marker into `{PYDANTIC_XML_EXAMPLE}` and shipped it verbatim.
        """
        assert "PYDANTIC_XML_EXAMPLE" not in rendered_prompt

    def test_prompt_carries_a_response_example( self, rendered_prompt ):
        """The example block the LoRA was trained on must be present."""
        assert "<response>" in rendered_prompt
        assert "</response>" in rendered_prompt

    def test_example_uses_the_tag_the_parser_requires( self, rendered_prompt ):
        """
        CommandResponse requires `<command>`. The prompt must show that tag —
        not `<agent-routing-command>`, which is the wrapper name from the
        options list and what the model free-styled when shown no example.
        """
        assert "<command></command>" in rendered_prompt
        assert "<agent-routing-command>" not in rendered_prompt.split( "### Input:" )[ -1 ]

    def test_voice_command_is_interpolated( self, rendered_prompt ):
        """The one substitution the router does perform still works."""
        assert "build me a podcast about the KISS protocol" in rendered_prompt
        assert "{voice_command}" not in rendered_prompt


class TestExampleShapeRoundTrips:
    """The shape the prompt teaches must be the shape the parser accepts."""

    def test_taught_shape_parses_as_command_response( self ):
        """
        Fill in the example the prompt shows and parse it with the production
        model. If this ever fails, prompt and parser have drifted apart again.
        """
        response = (
            "<response>\n"
            "    <command>agent router go to podcast generator</command>\n"
            "    <args>document_path=\"brevity-mandate.md\"</args>\n"
            "</response>"
        )

        parsed = CommandResponse.from_xml( response )

        assert parsed.command == "agent router go to podcast generator"
        assert "brevity-mandate.md" in parsed.args

    def test_freestyled_tag_is_rejected( self ):
        """
        The exact payload that broke production on 2026-08-02 must still be a
        parse failure — this test is the control. If it starts passing, the
        guard above is no longer proving anything.
        """
        broken = (
            "<response>\n"
            "    <agent-routing-command>agent router go to research to podcast</agent-routing-command>\n"
            "    <args>document_path=\"the KISS protocol\"</args>\n"
            "</response>"
        )

        with pytest.raises( Exception ):
            CommandResponse.from_xml( broken )
