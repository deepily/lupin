"""
Pins the eight writing rules on the docstring standard page by title and limit.
"""

import os
import re

import pytest

import cosa.utils.util as cu

PAGE = "src/docs/docstring-standard.md"

RULES = [
    ( 1, "Lead with the claim",             [ "90 characters", "blank line" ] ),
    ( 2, "Say only what the signature doesn't", [ "reader doesn't already know" ] ),
    ( 3, "One idea per sentence",           [ "under 25 words" ] ),
    ( 4, "No typographic emphasis",         [ "EMPHASIS_GLYPHS", "in code comments, never" ] ),
    ( 5, "No rhetoric",                     [ "aphorisms", "deliberately", "by construction", "load-bearing", "the point" ] ),
    ( 6, "Every reference resolves",        [ "bare", "no reference at all" ] ),
    ( 7, "Current state only",              [ "commit message", "docs/decisions/", "Design:" ] ),
    ( 8, "Fit the template",                [ "prerequisites, steps, verify, rollback", "1,500 words", "40 lines" ] ),
]


def _rules_section():
    """
    Read the eight-rules section of the docstring standard page.

    Requires:
        - the page holds a "## The eight rules" heading

    Ensures:
        - returns the text from that heading to the next "## " heading
    """
    with open( os.path.join( cu.get_project_root(), PAGE ), encoding="utf-8" ) as handle:
        text = handle.read()
    return text.split( "## The eight rules" )[ 1 ].split( "\n## " )[ 0 ]


def _rule_line( number ):
    """
    Return the one list line that carries rule number.

    Requires:
        - number is 1 through 8

    Ensures:
        - returns the line text, or an empty string when the rule is absent
    """
    lines = [ line for line in _rules_section().splitlines() if line.startswith( f"{number}. **" ) ]
    return lines[ 0 ] if len( lines ) == 1 else ""


def test_section_holds_exactly_eight_numbered_rules():
    numbered = re.findall( r"^\d+\. \*\*", _rules_section(), flags=re.MULTILINE )
    assert len( numbered ) == 8


@pytest.mark.parametrize( "number, title, anchors", RULES )
def test_each_rule_keeps_its_title_and_its_limit( number, title, anchors ):
    line = _rule_line( number )
    assert title in line, f"rule {number} lost its title"
    for anchor in anchors:
        assert anchor in line, f"rule {number} lost {anchor!r}"


def test_counted_scope_page_exists_and_is_linked_from_the_standard():
    root = cu.get_project_root()
    assert os.path.isfile( os.path.join( root, "src/docs/docstring-counted-scope.md" ) )
    with open( os.path.join( root, PAGE ), encoding="utf-8" ) as handle:
        assert "(docstring-counted-scope.md)" in handle.read()
