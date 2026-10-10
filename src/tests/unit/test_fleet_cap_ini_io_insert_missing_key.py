#!/usr/bin/env python3
"""
Tests for inserting the skeleton crew key when a restored file does not have it.

A configuration file restored from an older backup lacks the key. The switch's writer must
then add the line after the fleet cap maximum line instead of refusing, so the toggle can
still be turned on. The fleet cap writer keeps refusing an absent key.

Every test writes to tmp_path. The live configuration file is never touched.
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import fleet_cap_ini_io as io


SWITCH_KEY = "cc session skeleton crew enabled"
ANCHOR_KEY = "cc session fleet size cap maximum"

OLD_FILE = """\
[Lupin: Baseline]
cc session fleet size cap                        = 8
cc session fleet size cap maximum                = 18
cc session spawn reviewer ack timeout seconds    = 120
"""


def _ini( tmp_path, body=OLD_FILE ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( body, encoding="utf-8" )
    return str( path )


def test_an_absent_key_is_inserted_after_the_anchor_and_aligned( tmp_path ):
    path = _ini( tmp_path )
    assert io.write_bool_to_disk( path, SWITCH_KEY, True, insert_after=ANCHOR_KEY ) is True
    expected = OLD_FILE.replace(
        "cc session fleet size cap maximum                = 18\n",
        "cc session fleet size cap maximum                = 18\n"
        "cc session skeleton crew enabled                 = true\n" )
    assert open( path, encoding="utf-8" ).read() == expected


def test_a_present_key_is_replaced_in_place_even_with_an_anchor( tmp_path ):
    body = OLD_FILE + "cc session skeleton crew enabled                 = false\n"
    path = _ini( tmp_path, body )
    io.write_bool_to_disk( path, SWITCH_KEY, True, insert_after=ANCHOR_KEY )
    assert open( path, encoding="utf-8" ).read() == body.replace( "= false", "= true" )


def test_an_absent_key_without_an_anchor_still_refuses( tmp_path ):
    path = _ini( tmp_path )
    with pytest.raises( io.KeyNotFound ):
        io.write_bool_to_disk( path, SWITCH_KEY, True )
    assert open( path, encoding="utf-8" ).read() == OLD_FILE


def test_an_absent_key_and_an_absent_anchor_refuses_and_names_the_key( tmp_path ):
    body = "[Lupin: Baseline]\nother = 1\n"
    path = _ini( tmp_path, body )
    with pytest.raises( io.KeyNotFound ) as raised:
        io.write_bool_to_disk( path, SWITCH_KEY, True, insert_after=ANCHOR_KEY )
    assert ANCHOR_KEY in str( raised.value )
    assert open( path, encoding="utf-8" ).read() == body


def test_a_duplicated_anchor_refuses( tmp_path ):
    body = OLD_FILE + "[Lupin: Testing]\ncc session fleet size cap maximum = 9\n"
    path = _ini( tmp_path, body )
    with pytest.raises( io.KeyDefinedTwice ):
        io.write_bool_to_disk( path, SWITCH_KEY, True, insert_after=ANCHOR_KEY )
    assert open( path, encoding="utf-8" ).read() == body


def test_the_cap_writer_still_refuses_an_absent_key( tmp_path ):
    path = _ini( tmp_path, "[Lupin: Baseline]\nother = 1\n" )
    with pytest.raises( io.KeyNotFound ):
        io.write_int_to_disk( path, "cc session fleet size cap", 5 )
