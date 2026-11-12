#!/usr/bin/env python3
"""
reuse_stage1._write_json: sorted, indented, whole, and no temp file left.

Venue: :7999-eligible / local, pure.
"""
import os
import pathlib
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_stage1 as s1


def test_the_record_is_written_sorted_with_one_space_indent_and_a_final_newline( tmp_path ):
    target = tmp_path / "deeper" / "run.json"
    s1._write_json( target, { "b": 1, "a": { "z": [ 1 ], "y": 2 } } )
    assert target.read_text( encoding="utf-8" ) == '{\n "a": {\n  "y": 2,\n  "z": [\n   1\n  ]\n },\n "b": 1\n}\n'
    assert [ p.name for p in target.parent.iterdir() ] == [ "run.json" ]


def test_a_second_write_replaces_the_first_whole( tmp_path ):
    target = tmp_path / "run.json"
    s1._write_json( target, { "old": 1, "gone": 2 } )
    s1._write_json( target, { "new": 3 } )
    assert target.read_text( encoding="utf-8" ) == '{\n "new": 3\n}\n'
    assert [ p.name for p in tmp_path.iterdir() ] == [ "run.json" ]


def test_the_end_to_end_driver_uses_the_same_writer():
    assert e2r._write_json is s1._write_json
