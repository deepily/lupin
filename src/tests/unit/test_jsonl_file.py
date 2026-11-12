"""
Unit tests for cosa.utils.jsonl_file.read_jsonl, the reader of a whole JSON Lines file.
"""

import json

import pytest

from cosa.utils.jsonl_file import read_jsonl


def test_returns_every_record_in_file_order( tmp_path ):
    """Records come back in file order, as the values json.loads gave each line."""
    path = tmp_path / "rows.jsonl"
    path.write_text( '{"n": 2}\n{"n": 1}\n[3]\n', encoding="utf-8" )
    assert read_jsonl( path ) == [ { "n": 2 }, { "n": 1 }, [ 3 ] ]


def test_skips_blank_and_whitespace_only_lines( tmp_path ):
    """A blank line and a spaces-only line are skipped, and no record is lost around them."""
    path = tmp_path / "rows.jsonl"
    path.write_text( '\n{"k": 1}\n   \n\n{"k": 2}\n', encoding="utf-8" )
    assert read_jsonl( str( path ) ) == [ { "k": 1 }, { "k": 2 } ]


def test_a_line_separator_inside_a_string_stays_in_its_record( tmp_path ):
    """A raw U+2028 inside a string does not split its record."""
    path = tmp_path / "rows.jsonl"
    path.write_text( json.dumps( { "text": "a\u2028b" }, ensure_ascii=False ) + "\n", encoding="utf-8" )
    assert read_jsonl( path ) == [ { "text": "a\u2028b" } ]


def test_a_missing_file_raises_unless_missing_ok( tmp_path ):
    """A missing file raises, or gives an empty list with missing_ok."""
    path = tmp_path / "nope.jsonl"
    with pytest.raises( FileNotFoundError ):
        read_jsonl( path )
    assert read_jsonl( path, missing_ok=True ) == []


def test_missing_ok_does_not_hide_a_line_that_is_not_json( tmp_path ):
    """A bad line still raises when missing_ok is set."""
    path = tmp_path / "rows.jsonl"
    path.write_text( '{"k": 1}\nnot json\n', encoding="utf-8" )
    with pytest.raises( json.JSONDecodeError ):
        read_jsonl( path, missing_ok=True )
