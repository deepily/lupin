"""
The card wait report names each reading, and names a missing one.

Venue: :7999 (unit tier). Pure function, no browser.
"""

from tests.helpers.card_wait_report import format_card_wait_report

ACTIVE = { "tag": "INPUT", "class_name": "yes-no-comment-input", "testid": "comment" }


def test_every_reading_appears_on_its_own_labelled_line():
    text = format_card_wait_report( "c1", "<div id=x></div>", ACTIVE, [ "c1", "c2" ] ).splitlines()
    assert text[ 0 ] == "card wait timed out for c1"
    assert text[ 1 ] == "card outerHTML: <div id=x></div>"
    assert text[ 2 ] == "document.activeElement: tag=INPUT class='yes-no-comment-input' data-testid='comment'"
    assert text[ 3 ] == "actionRequired store ids (2): c1, c2"


def test_a_missing_card_is_named_as_missing():
    assert "no element carries this id" in format_card_wait_report( "c1", None, ACTIVE, [ ] )


def test_no_focused_element_is_named():
    assert "document.activeElement: none" in format_card_wait_report( "c1", "<p></p>", None, [ ] )


def test_an_empty_store_says_none_and_an_unreadable_one_says_so():
    assert format_card_wait_report( "c1", "<p></p>", ACTIVE, [ ] ).endswith( "(0): none" )
    assert format_card_wait_report( "c1", "<p></p>", ACTIVE, None ).endswith( "store was not readable" )
