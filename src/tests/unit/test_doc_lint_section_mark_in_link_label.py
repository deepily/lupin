"""
A section mark in a markdown link label has its path in the link target.

The link target counts in full, so a split page's long target such as
../websocket-events/06-close-codes-and-related-docs.md#close-code-semantics is a path.
Before the change only 60 characters after the mark were searched and the target was cut.
"""

import pytest

from cosa.repo.doc_lint import marker_counts
from cosa.repo.doc_lint.md_lint import lint_source

LONG   = "[WebSocket Events §Close Code Semantics](../websocket-events/06-close-codes-and-related-docs.md#close-code-semantics)"
SHORT  = "[WebSocket Events §Close Code Semantics](websocket-events.md#close-code-semantics)"
BARE   = "[WebSocket Events §Close Code Semantics](#close-code-semantics)"


def _bare( text ):
    return [ f.message for f in lint_source( "p.md", "# T\n\n" + text + "\n" ) if f.rule == "bare-ref" ]


def test_a_long_link_target_resolves_the_mark_in_its_label():
    assert _bare( LONG ) == []


def test_a_short_link_target_still_resolves_the_mark():
    assert _bare( SHORT ) == []


def test_a_link_target_that_is_only_an_anchor_does_not_resolve_the_mark():
    assert _bare( BARE ) == [ "section reference '§Close' has no path" ]


def test_a_target_that_is_far_longer_than_the_old_window_resolves_the_mark():
    long_target = "../" + "very-long-folder-name/" * 6 + "page.md#anchor"
    assert _bare( f"[Guide §3 text]({long_target})" ) == []


def test_a_mark_in_prose_before_a_link_is_not_resolved_by_that_links_target():
    text = "See §3 for details and [the guide](../" + "x/" * 40 + "page.md) too."
    assert _bare( text ) == [ "section reference '§3' has no path" ]


def test_a_mark_in_the_text_of_a_link_after_the_label_is_not_in_the_label():
    text = "[label](#a) then §3 then ( ../" + "x/" * 40 + "page.md ) end."
    assert _bare( text ) == [ "section reference '§3' has no path" ]


def test_a_mark_in_a_label_whose_target_has_no_path_stays_bare_with_a_path_far_after():
    text = "[Guide §3](#anchor) and later words " + "w " * 30 + "see ../deep/folder/page.md"
    assert _bare( text ) == [ "section reference '§3' has no path" ]


@pytest.mark.parametrize( "text", [ LONG, SHORT ] )
def test_the_bare_section_refs_helper_agrees_with_the_linter( text ):
    assert marker_counts.bare_section_refs( text ) == []


def test_a_link_target_that_ends_in_a_slash_is_a_folder_and_not_a_path():
    assert _bare( "[Guide §3](../websocket-events/)" ) == [ "section reference '§3' has no path" ]


def test_a_link_target_with_a_dot_and_no_path_does_not_resolve_the_mark():
    assert _bare( "[Guide §3](v1.2)" ) == [ "section reference '§3' has no path" ]


def test_a_stray_closing_bracket_after_a_mark_outside_any_label_does_not_borrow_the_target():
    text = "then §3 and " + "w " * 40 + "](../deep/page.md)"
    assert _bare( text ) == [ "section reference '§3' has no path" ]


def test_a_mark_after_a_closed_link_does_not_borrow_a_later_target():
    text = "[a](#b) then §3 and " + "w " * 40 + "](../deep/page.md)"
    assert _bare( text ) == [ "section reference '§3' has no path" ]
