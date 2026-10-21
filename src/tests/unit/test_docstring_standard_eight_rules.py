"""
Pins the eight writing rules on the docstring standard by title, limit and key clause.
"""

import os
import re

import pytest

import cosa.utils.util as cu

PAGE = "src/docs/docstring-standard.md"

RULES = {
    1 : ( "Lead with the claim", [
        "The first sentence says what the thing does or decides",
        "one line of at most 90 characters",
        "followed by a blank line",
        "may be used by automatic indexing tools",
    ] ),
    2 : ( "Say only what the signature doesn't", [
        "focus on explaining what the reader doesn't already know",
    ] ),
    3 : ( "One idea per sentence", [
        "under 25 words",
    ] ),
    4 : ( "No typographic emphasis", [
        "No words in capitals",
        "No glyphs from `EMPHASIS_GLYPHS` in `src/cosa/repo/doc_lint/rule_lists.py`",
        "bold is only for a term's first definition",
        "in code comments, never",
    ] ),
    5 : ( "No rhetoric", [
        "No aphorisms",
        "not X but Y",
        "`deliberately`", "`by construction`", "`load-bearing`", "`the point`",
        "State the constraint and its consequence",
    ] ),
    6 : ( "Every reference resolves", [
        "A path, plus an anchor if needed, or no reference at all",
        "No bare",
    ] ),
    7 : ( "Current state only", [
        "History goes to the commit message, `history.md`, or the R&D doc the `Design:` line points to",
        "No dated `UPDATE` banners",
        "no quoted conversations in code",
        "one-line decision record in `docs/decisions/`",
        "the code links to it",
    ] ),
    8 : ( "Fit the template", [
        "Runbook: prerequisites, steps, verify, rollback",
        "Reference page: at most 1,500 words",
        "Capability page: at most 40 lines",
    ] ),
}

CLAUSES = [ ( number, clause ) for number, ( title, clauses ) in RULES.items() for clause in clauses ]
CLOSING = "The design-by-contract docstring keeps its shape."


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


def _missing( section ):
    """
    List what the section has lost: a rule title, a key clause or the closing sentence.

    Requires:
        - section is the text of the eight-rules section

    Ensures:
        - returns the lost items as strings, empty when nothing is lost
    """
    lost = []
    for number, ( title, clauses ) in RULES.items():
        line = [ l for l in section.splitlines() if l.startswith( f"{number}. **" ) ]
        if len( line ) != 1 or title not in line[ 0 ]:
            lost.append( f"rule {number} title" )
            continue
        lost += [ f"rule {number}: {clause}" for clause in clauses if clause not in line[ 0 ] ]
    if CLOSING not in section: lost.append( "closing sentence" )
    return lost


def test_section_holds_exactly_eight_numbered_rules():
    assert len( re.findall( r"^\d+\. \*\*", _rules_section(), flags=re.MULTILINE ) ) == 8


def test_nothing_is_lost_from_the_page():
    assert _missing( _rules_section() ) == []


@pytest.mark.parametrize( "number, clause", CLAUSES )
def test_dropping_one_clause_is_detected( number, clause ):
    section = _rules_section()
    assert section.count( clause ) == 1
    assert _missing( section.replace( clause, "" ) ) == [ f"rule {number}: {clause}" ]


@pytest.mark.parametrize( "number", sorted( RULES ) )
def test_dropping_a_rule_is_detected( number ):
    kept = "\n".join( l for l in _rules_section().splitlines() if not l.startswith( f"{number}. **" ) )
    assert f"rule {number} title" in _missing( kept )


def test_dropping_the_closing_sentence_is_detected():
    assert _missing( _rules_section().replace( CLOSING, "" ) ) == [ "closing sentence" ]


def test_counted_scope_page_exists_and_is_linked_both_ways():
    root = cu.get_project_root()
    with open( os.path.join( root, PAGE ), encoding="utf-8" ) as handle:
        assert "(docstring-counted-scope.md)" in handle.read()
    with open( os.path.join( root, "src/docs/docstring-counted-scope.md" ), encoding="utf-8" ) as handle:
        assert "(docstring-standard.md#waiving-a-finding)" in handle.read()
