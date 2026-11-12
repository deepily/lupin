"""
The shared fenced-block reader of the d2, matplotlib and mermaid renderers.
"""
import pytest

from cosa.agents.presentation_generator.renderers.d2_renderer import D2Renderer
from cosa.agents.presentation_generator.renderers.fenced_block import extract_fenced_block
from cosa.agents.presentation_generator.renderers.matplotlib_renderer import MatplotlibRenderer
from cosa.agents.presentation_generator.renderers.mermaid import MermaidRenderer


def test_a_labelled_block_gives_its_stripped_text():
    assert extract_fenced_block( "intro\n```d2\n  a -> b  \n```\nbye", "d2" ) == "a -> b"


def test_an_unlabelled_block_gives_its_text_too():
    assert extract_fenced_block( "```\na -> b\n```", "d2" ) == "a -> b"


def test_a_block_labelled_for_another_language_is_not_read():
    assert extract_fenced_block( "```python\nprint( 1 )\n```", "d2" ) is None


def test_a_fence_that_never_closes_gives_none():
    assert extract_fenced_block( "```d2\na -> b", "d2" ) is None


def test_the_first_of_two_blocks_wins():
    assert extract_fenced_block( "```d2\none\n```\n```d2\ntwo\n```", "d2" ) == "one"


def test_the_label_is_matched_as_text_not_as_a_pattern():
    assert extract_fenced_block( "```c++\nint x;\n```", "c++" ) == "int x;"


@pytest.mark.parametrize( "extract,label,body", [
    ( D2Renderer._extract_d2_code,            "d2",      "a -> b"           ),
    ( MatplotlibRenderer._extract_python_code, "python",  "import numpy"     ),
    ( MermaidRenderer._extract_mermaid,        "mermaid", "graph TD\n  A-->B" ),
] )
def test_each_renderer_reads_its_own_fence_and_keeps_its_own_fallback( extract, label, body ):
    assert extract( f"Here:\n```{label}\n{body}\n```" ) == body
    assert extract( "" ) is None


def test_an_empty_block_gives_an_empty_string_not_none():
    assert extract_fenced_block( "```d2\n```", "d2" ) == ""


def test_a_renderer_does_not_fall_back_past_an_empty_block():
    assert D2Renderer._extract_d2_code( "```d2\n```\na -> b" ) == ""
    assert MermaidRenderer._extract_mermaid( "```mermaid\n```\ngraph TD\n  A-->B" ) == ""
