"""
Pull the code out of a fenced block in a model reply.

The d2, matplotlib and mermaid renderers each ask the model for diagram code and look for the same fence first.
Each renderer keeps its own fallback for a reply that has no fence.

Usage:
    from cosa.agents.presentation_generator.renderers.fenced_block import extract_fenced_block
    code = extract_fenced_block( response_content, "d2" )
"""
import re
from typing import Optional


def extract_fenced_block( response_content: str, label: str ) -> Optional[ str ]:
    """
    Return the text of the first fenced block, whether it carries the label or none.

    Requires:
        - response_content is a string
        - label is the language name after the opening fence, such as "d2"

    Ensures:
        - returns the text between the opening fence and the next closing fence, stripped
        - a fence labelled with another language is not read, because its text would start with that name
        - returns None when no fence closes
    """
    match = re.search( rf"```(?:{re.escape( label )})?\s*\n(.*?)```", response_content, re.DOTALL )
    return match.group( 1 ).strip() if match else None
