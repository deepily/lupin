"""
W4: the worked-examples sheet for Set B reviewers keeps its shape.
"""
import pathlib
import re

import pytest

import cosa.utils.util as cu

SHEET   = pathlib.Path( cu.get_project_root() ) / "src" / "docs" / "labelling" / "set-b-worked-examples.md"
ANSWERS = ( "Same job", "Not the same job" )
GROUPS  = ( "flag", "monolith", "work-alike" )
ROW_RE  = re.compile( r"^\| (\d+) \| (pair-[0-9a-f]{10}) \| (\S+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| (Rule [A-E]) \|$", re.M )


def rows():
    """Return the parsed case rows of the sheet."""
    return ROW_RE.findall( SHEET.read_text() )


def test_the_sheet_keeps_the_three_cases_rick_confirmed_in_order_with_distinct_pairs():
    got = rows()
    assert [ int( r[ 0 ] ) for r in got ] == [ 2, 3, 4 ]
    assert len( { r[ 1 ] for r in got } ) == 3


def test_every_case_names_a_known_group_two_reviewer_answers_a_proposed_answer_and_a_rule_the_sheet_defines():
    text = SHEET.read_text()
    for number, pair, group, a, b, proposed, rule in rows():
        assert group in GROUPS and a.strip() in ANSWERS and b.strip() in ANSWERS and proposed.strip() in ANSWERS, pair
        assert a.strip() != b.strip(), f"{pair}: a worked example of a split needs the two answers to differ"
        assert f"| {rule} | " in text, f"{pair}: rule {rule} is not defined in the sheet"
        assert f"### Case {number}:" in text, f"{pair}: no written case {number}"


def test_the_sheet_says_rick_ruled_and_leaves_the_instructions_alone():
    text = SHEET.read_text()
    assert "ruled by Rick" in text and "proposed, not ruled" not in text and "adds no rules to the instructions" in text


def test_flags_come_first_because_they_hold_most_of_the_disputes():
    groups = [ r[ 2 ] for r in rows() ]
    assert groups[ :2 ] == [ "flag" ] * 2 and "flag" not in groups[ 2: ]


def test_the_row_pattern_actually_matches_a_row_so_an_empty_parse_cannot_pass():
    assert ROW_RE.findall( "| 1 | pair-0123456789 | flag | Same job | Not the same job | Same job | Rule A |" )
    assert not ROW_RE.findall( "| 1 | pair-xyz | flag |" )
