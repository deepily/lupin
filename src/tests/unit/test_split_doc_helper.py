"""
Tests for read_split_page: the index and every part are read, in order.

A page with no parts folder, or an empty one, fails by name.
"""

import pytest

from tests.helpers.split_doc import read_split_page


def test_it_reads_the_index_then_each_part_in_file_name_order( tmp_path ):
    ( tmp_path / "page.md" ).write_text( "INDEX\n", encoding="utf-8" )
    folder = tmp_path / "page"
    folder.mkdir()
    ( folder / "02-b.md" ).write_text( "SECOND\n", encoding="utf-8" )
    ( folder / "01-a.md" ).write_text( "FIRST\n", encoding="utf-8" )
    ( folder / "notes.txt" ).write_text( "IGNORED\n", encoding="utf-8" )

    text = read_split_page( tmp_path, "page.md" )

    assert text.split() == [ "INDEX", "FIRST", "SECOND" ]


def test_a_page_with_no_parts_folder_fails_by_name( tmp_path ):
    ( tmp_path / "page.md" ).write_text( "INDEX\n", encoding="utf-8" )

    with pytest.raises( AssertionError, match="no parts found" ):
        read_split_page( tmp_path, "page.md" )


def test_a_page_with_an_empty_parts_folder_fails_by_name( tmp_path ):
    ( tmp_path / "page.md" ).write_text( "INDEX\n", encoding="utf-8" )
    ( tmp_path / "page" ).mkdir()

    with pytest.raises( AssertionError, match="no parts found" ):
        read_split_page( tmp_path, "page.md" )


def test_a_missing_index_raises_file_not_found( tmp_path ):
    ( tmp_path / "page" ).mkdir()
    ( tmp_path / "page" / "01-a.md" ).write_text( "FIRST\n", encoding="utf-8" )

    with pytest.raises( FileNotFoundError ):
        read_split_page( tmp_path, "page.md" )
