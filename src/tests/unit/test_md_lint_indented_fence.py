"""
A code fence indented under a list item is a fence to md_lint, not prose.

The fixture is lines 406 to 417 of src/docs/auth/operations-guide.md as it stood at 99ea8d5f9: a
numbered list item whose SQL fence is indented three spaces. Before the fix md_lint read the SQL as
prose and raised 23 findings on it (22 caps, 1 sentence length).
"""

import hashlib
import os

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import md_lint

SOURCE_PATH   = "src/docs/auth/operations-guide.md"
SOURCE_SHA256 = "60ea7c3c4ccda68dcaa2a9c76f78c4b6b99e030644347c5f00206c0c8c1607ac"       # the whole page at 99ea8d5f9
FIXTURE       = "src/tests/fixtures/md_lint/operations-guide-sql-fence-under-list-item.md"
FIXTURE_SHA   = "e22b235bca95a1d9a3eb67cc52cb407ed4066dd840983de7a64ea0f246580c6b"       # the cut, lines 406 to 417


def _fixture():
    with open( os.path.join( cu.get_project_root(), FIXTURE ), encoding="utf-8" ) as handle: return handle.read()


def test_the_fixture_is_the_cut_it_says_it_is():
    text = _fixture()
    assert hashlib.sha256( text.encode( "utf-8" ) ).hexdigest() == FIXTURE_SHA
    lines = text.split( "\n" )
    assert lines[ 0 ] == "1. **Authentication Success Rate**" and lines[ 1 ] == "   ```sql" and lines[ 10 ] == "   ```" and len( lines ) == 13
    assert SOURCE_SHA256 != FIXTURE_SHA                                                  # two different files: the page and the cut


def test_a_sql_fence_indented_under_a_list_item_raises_no_finding():
    assert md_lint.lint_source( SOURCE_PATH, _fixture() ) == []


def test_the_same_words_outside_a_fence_are_still_found():
    prose = "1. **Success rate**\n\n   SELECT COUNT(*) FROM auth_audit_log WHERE created_at > now\n"
    assert {f.rule for f in md_lint.lint_source( SOURCE_PATH, prose )} == { "caps" }


def test_page_rates_ignore_the_fence_content():
    assert md_lint.page_rates( _fixture() )[ "caps_words" ] == 0.0


@pytest.mark.parametrize( "indent", [ " ", "  ", "   ", "    ", "        ", "\t" ] )
@pytest.mark.parametrize( "mark", [ "```", "~~~" ] )
def test_an_indented_fence_is_blanked_to_newlines_and_the_line_count_holds( indent, mark ):
    page    = f"- item\n{indent}{mark}sql\n{indent}SELECT 1\n{indent}{mark}\nafter\n"
    blanked = md_lint.blank_non_prose( page )
    assert blanked == "- item\n\n\n\nafter\n" and blanked.count( "\n" ) == page.count( "\n" )


def test_an_indented_opener_is_closed_by_a_closer_at_another_indentation():
    assert md_lint.blank_non_prose( "  ```\nx\n```\nafter\n" ) == "\n\n\nafter\n"
    assert md_lint.blank_non_prose( "```\nx\n  ```\nafter\n" ) == "\n\n\nafter\n"


def test_a_closer_of_the_other_kind_does_not_close_the_fence():
    page = "  ```\nx\n  ~~~\nafter\n"
    assert md_lint.blank_non_prose( page ) == page


def test_an_unclosed_indented_fence_is_left_as_it_is():
    page = "- item\n  ```sql\nSELECT 1\n"
    assert md_lint.blank_non_prose( page ) == page


def test_two_indented_fences_in_one_page_are_blanked_separately_and_the_text_between_stays():
    page = "- a\n  ```\n  x\n  ```\nbetween\n- b\n  ```\n  y\n  ```\n"
    assert md_lint.blank_non_prose( page ) == "- a\n\n\n\nbetween\n- b\n\n\n\n"


def test_a_fence_at_column_zero_is_blanked_as_before():
    assert md_lint.blank_non_prose( "intro\n```bash\nls\n```\nafter\n" ) == "intro\n\n\n\nafter\n"
    assert md_lint.blank_non_prose( "~~~\nx\n~~~\n" ) == "\n\n\n"


def test_front_matter_and_html_comments_are_still_blanked():
    page = "---\ntitle: t\n---\n<!-- note\nmore -->\n  ```\nx\n  ```\nbody\n"
    assert md_lint.blank_non_prose( page ) == "\n\n\n\n\n\n\n\nbody\n"


def test_a_triple_backtick_inside_a_sentence_does_not_open_a_fence():
    source = "Use ``` in a sentence.\n\nNot code: THIS IS LOUD.\n\n```\ncode\n```\n"
    found  = [ f.rule for f in md_lint.lint_source( "page.md", source ) ]
    assert "caps" in found


def test_text_after_a_closing_fence_is_part_of_the_closer_line():
    assert md_lint.blank_non_prose( "  ```\nx\n  ``` words\nafter\n" ) == "\n\n\nafter\n"
