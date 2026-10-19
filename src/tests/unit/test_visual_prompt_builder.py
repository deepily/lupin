"""
Unit tests for the visual prompt builders of the presentation generator.

Twin refactor slice presentation-prompts: the d2, matplotlib and Mermaid builders share one assembler.
The literal strings below were captured from the three builders before the refactor.
"""

import pytest

from cosa.agents.presentation_generator.prompts.d2 import get_d2_prompt
from cosa.agents.presentation_generator.prompts.matplotlib import get_matplotlib_prompt
from cosa.agents.presentation_generator.prompts.visual import get_mermaid_prompt, build_visual_prompt

D2_TITLED = (
    "Slide title: Title\nVisual type: architecture\nSuggested D2 pattern: containers with nested components\n\n"
    "Description:\nsystem architecture overview\n\n"
    "Generate a D2 diagram for this slide. Output ONLY the d2 code block."
)
MPL_TITLED = (
    "Slide title: Title\nVisual type: chart\nSuggested chart type: pie chart\n\n"
    "Description:\npie chart of market share\n\n"
    "Generate Python code using matplotlib to create this chart. Output ONLY the python code block."
)
MERMAID_TITLED = (
    "Slide title: Title\nVisual type: diagram\nSuggested Mermaid type: sequenceDiagram\n\n"
    "Description:\nsequence of calls between services\n\n"
    "Generate a Mermaid diagram for this slide. Output ONLY the mermaid code block."
)


def _without_title( prompt ):
    return prompt.split( "\n", 1 )[ 1 ]


class TestBuilders:

    @pytest.mark.parametrize( "build, args, expected", [
        ( get_d2_prompt,         ( "architecture", "system architecture overview" ),     D2_TITLED ),
        ( get_matplotlib_prompt, ( "chart",        "pie chart of market share" ),        MPL_TITLED ),
        ( get_mermaid_prompt,    ( "diagram",      "sequence of calls between services" ), MERMAID_TITLED ),
    ] )
    def test_titled_and_untitled_output_is_unchanged( self, build, args, expected ):
        assert build( *args, "Title" ) == expected
        assert build( *args ) == _without_title( expected )
        assert build( *args, slide_title = "" ) == _without_title( expected )


class TestBuildVisualPrompt:

    def test_assembles_title_type_hint_description_and_instruction_in_order( self ):
        out = build_visual_prompt( "kind", "desc", "T", "Suggested X", "xval", "Do it." )
        assert out == "Slide title: T\nVisual type: kind\nSuggested X: xval\n\nDescription:\ndesc\n\nDo it."

    def test_empty_title_leaves_the_title_line_out( self ):
        out = build_visual_prompt( "kind", "desc", "", "Suggested X", "xval", "Do it." )
        assert out.startswith( "Visual type: kind\n" )
