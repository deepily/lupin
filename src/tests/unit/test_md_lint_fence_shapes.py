"""
A fence closes on its own character, as long as its opener, with no text after it.

Two shapes were misread. A four-backtick fence holding a three-backtick example closed at the
inner line. A line of three backticks plus "bash" inside a fence closed it early.
"""

import pytest

from cosa.repo.doc_lint import md_lint


def test_a_four_backtick_fence_holding_a_three_backtick_example_closes_on_the_four():
    page = "````markdown\n```bash\nls\n```\n````\nafter\n"
    assert md_lint.blank_non_prose( page ) == "\n\n\n\n\nafter\n"


def test_a_three_backtick_line_inside_a_four_backtick_fence_is_not_a_closer_even_when_the_fence_never_closes():
    page = "````\n```\nx\n"
    assert md_lint.blank_non_prose( page ) == page


def test_a_closer_longer_than_its_opener_still_closes():
    assert md_lint.blank_non_prose( "```\nx\n`````\nafter\n" ) == "\n\n\nafter\n"
    assert md_lint.blank_non_prose( "~~~\nx\n~~~~~\nafter\n" ) == "\n\n\nafter\n"


def test_a_tilde_fence_of_four_is_not_closed_by_three():
    page = "~~~~\n~~~\nx\n"
    assert md_lint.blank_non_prose( page ) == page


def test_a_line_with_an_info_string_inside_a_fence_does_not_close_it():
    page = "```\nx\n```bash\ny\n```\nafter\n"
    assert md_lint.blank_non_prose( page ) == "\n\n\n\n\nafter\n"


def test_a_fence_whose_only_closer_carries_text_is_left_as_it_is():
    page = "```\nx\n``` words\nafter\n"
    assert md_lint.blank_non_prose( page ) == page


@pytest.mark.parametrize( "tail", [ " ", "   ", "\t" ] )
def test_spaces_after_a_closer_are_not_text( tail ):
    assert md_lint.blank_non_prose( f"```\nx\n```{tail}\nafter\n" ) == "\n\n\nafter\n"


def test_prose_after_a_fence_that_holds_an_example_is_still_linted():
    page   = "````\n```bash\nls\n```\n````\n\nTHIS IS LOUD AND NOT CODE.\n"
    prose  = md_lint.blank_non_prose( page )
    assert "LOUD" in prose and "ls" not in prose
