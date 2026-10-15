"""
The api.md table-row repair: a split row is joined and every other line is left alone.
"""
import importlib.util
import pathlib

import pytest

import cosa.utils.util as cu

SPEC = importlib.util.spec_from_file_location( "fix_api_md_tables", pathlib.Path( cu.get_project_root() ) / "src" / "scripts" / "fix_api_md_tables.py" )
fix  = importlib.util.module_from_spec( SPEC )
SPEC.loader.exec_module( fix )

SPLIT = "| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)\n |\n## POST `/x`\n"
JOINED = "| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror) |\n## POST `/x`\n"


def test_a_split_row_is_joined_onto_its_line():
    assert fix.join_split_rows( SPLIT ) == JOINED


def test_a_whole_row_a_lone_pipe_after_a_whole_row_and_prose_are_left_alone():
    text = "| a | b |\n |\nA line.\n| c | d\nnot a pipe\n"
    assert fix.join_split_rows( text ) == text


def test_the_repair_is_idempotent_and_keeps_the_line_breaks():
    once = fix.join_split_rows( SPLIT * 3 )
    assert once == JOINED * 3 and fix.join_split_rows( once ) == once
    assert fix.join_split_rows( "" ) == "" and fix.join_split_rows( "a\n\n" ) == "a\n\n"


def test_a_row_at_the_very_end_with_nothing_after_it_is_left_alone():
    assert fix.join_split_rows( "| a | b" ) == "| a | b"


def test_main_rewrites_a_file_that_has_a_split_row_and_not_one_that_does_not( tmp_path ):
    path = tmp_path / "api.md"
    path.write_text( SPLIT, encoding="utf-8" )
    assert fix.main( [ "x", str( path ) ] ) == 0 and path.read_text( encoding="utf-8" ) == JOINED
    stamp = path.stat().st_mtime_ns
    assert fix.main( [ "x", str( path ) ] ) == 0 and path.stat().st_mtime_ns == stamp


def test_main_refuses_a_wrong_argument_count( capsys ):
    assert fix.main( [ "x" ] ) == 2 and "usage" in capsys.readouterr().err
    assert fix.main( [ "x", "a", "b" ] ) == 2


def test_the_generator_script_runs_the_repair_before_it_stamps_the_footer():
    text = ( pathlib.Path( cu.get_project_root() ) / "src" / "scripts" / "generate-api-docs.sh" ).read_text( encoding="utf-8" )
    assert 0 < text.index( "fix_api_md_tables.py" ) < text.index( "Inject timestamp footer" )
