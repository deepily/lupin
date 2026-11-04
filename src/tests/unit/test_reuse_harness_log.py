"""
Unit tests of the run log: one line of JSON per record, and no record names the arm.
"""
import json

import pytest

from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import log


def test_records_are_appended_as_json_lines_with_sorted_keys_in_order(tmp_path):
    run_log = log.RunLog( str( tmp_path ) )
    run_log.write( { "event" : "verdict", "run" : "r1", "arm_label" : "x" } )
    run_log.write( { "event" : "stop", "stop" : "cap" } )
    lines = ( tmp_path / log.LOG_FILE ).read_text().splitlines()
    assert lines[ 0 ] == '{"arm_label": "x", "event": "verdict", "run": "r1"}' and json.loads( lines[ 1 ] ) == { "event" : "stop", "stop" : "cap" }


def test_a_record_with_an_arm_key_is_refused_and_writes_nothing(tmp_path):
    with pytest.raises( err.HarnessError ) as caught: log.RunLog( str( tmp_path ) ).write( { "arm" : "with" } )
    assert caught.value.code == err.BAD_SPEC and not ( tmp_path / log.LOG_FILE ).exists()
