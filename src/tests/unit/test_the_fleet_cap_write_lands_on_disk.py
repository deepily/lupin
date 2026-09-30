#!/usr/bin/env python3
"""
THE INI WRITER — does it land on disk, and does it REFUSE when it cannot be sure?

`PUT /api/arbiter/fleet-size-cap` persists Rick's fleet cap by rewriting one line of
`src/conf/lupin-app.ini`. Two failures would leave the endpoint looking perfect:

    1. IT NEVER REACHED THE DISK. An in-memory `set_config` returns cleanly, the GET
       that follows it agrees, the pane repaints — and the value is gone at the next
       restart. Rick's words: "those values are serialized and reused the next time."
       Every test here reads the FILE back rather than trusting a return value.

    2. IT LANDED SOMEWHERE NOBODY READS. Configuration blocks inherit, so a key
       written into the wrong section is enforced by no process while reporting
       success. That is why the writer refuses a duplicated key instead of picking one.

⚠️ THE TESTS WRITE TO `tmp_path`, NEVER TO THE REAL CONFIGURATION FILE. A unit test
that rewrote the live INI would set the fleet cap for every seat on the box.
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import fleet_cap_ini_io as io


KEY = "cc session fleet size cap"


def _ini( tmp_path, body ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( body, encoding="utf-8" )
    return str( path )


# A file shaped like the real one: comments that MENTION the key, alignment padding,
# and a neighbouring key whose name is a strict prefix extension of this one.
WELL_FORMED = """\
[Lupin: Baseline]
# The fleet-wide cap. Set `cc session fleet size cap` here, not in code.
cc session fleet size cap                        = 8
cc session fleet size cap maximum                = 18
cc session spawn write memento default           = true
"""


# ── the happy path, read back from the FILE ─────────────────────────────────────

def test_the_value_reaches_the_disk_and_the_file_says_so( tmp_path ):
    path = _ini( tmp_path, WELL_FORMED )
    assert io.write_int_to_disk( path, KEY, 12 ) == 12
    assert "cc session fleet size cap                        = 12" in \
           open( path, encoding="utf-8" ).read()


def test_the_return_is_a_RE_READ_and_not_the_argument( tmp_path ):
    """
    🔴 THE GUARD THAT MAKES EVERY OTHER RESULT MEAN SOMETHING. Point the reader at a
    DIFFERENT file from the one written and the return must NOT be the argument — an
    echoing implementation returns 12 here and is indistinguishable from a correct one
    on every other test in this file.
    """
    path = _ini( tmp_path, WELL_FORMED )
    io.write_int_to_disk( path, KEY, 12 )
    assert io.read_int_from_disk( path, KEY ) == 12
    # and the re-read is a real parse: corrupt the line and the reader stops agreeing
    text = open( path, encoding="utf-8" ).read().replace( "= 12", "= not-a-number" )
    open( path, "w", encoding="utf-8" ).write( text )
    assert io.read_int_from_disk( path, KEY ) is None


def test_every_other_byte_is_left_alone( tmp_path ):
    """
    The INI is ~2,000 lines of comments and column alignment. `configparser.write()`
    would round-trip the parsed model and destroy all of it, which is why this is a
    line edit. Only the target line may differ.
    """
    path   = _ini( tmp_path, WELL_FORMED )
    before = open( path, encoding="utf-8" ).read().split( "\n" )
    io.write_int_to_disk( path, KEY, 12 )
    after  = open( path, encoding="utf-8" ).read().split( "\n" )

    assert len( before ) == len( after )
    differing = [ i for i, ( b, a ) in enumerate( zip( before, after ) ) if b != a ]
    assert differing == [ 2 ], f"exactly one line may change, saw {differing}"


def test_the_column_alignment_survives( tmp_path ):
    """House style aligns the `=` signs; a writer that collapsed them would reformat
    the file one key at a time, invisibly, over months."""
    path = _ini( tmp_path, WELL_FORMED )
    io.write_int_to_disk( path, KEY, 12 )
    lines = open( path, encoding="utf-8" ).read().split( "\n" )
    assert lines[ 2 ].index( "=" ) == lines[ 3 ].index( "=" )


def test_a_comment_mentioning_the_key_is_not_a_definition( tmp_path ):
    """
    ⚠️ THE MATCH IS ANCHORED AT COLUMN 0. The real file's own comments name this key
    in prose; a searching implementation would count them as definitions and refuse a
    perfectly well-formed file.
    """
    path = _ini( tmp_path, WELL_FORMED )
    assert io.locate_key( path, KEY ).index == 2      # the definition, not the comment


def test_a_longer_key_sharing_this_prefix_is_not_this_key( tmp_path ):
    """`cc session fleet size cap maximum` starts with `cc session fleet size cap`.
    A prefix match would find two definitions and refuse, or worse, write the wrong one."""
    path = _ini( tmp_path, WELL_FORMED )
    io.write_int_to_disk( path, KEY, 12 )
    assert io.read_int_from_disk( path, "cc session fleet size cap maximum" ) == 18


# ── the refusals ────────────────────────────────────────────────────────────────

def test_a_key_defined_TWICE_is_REFUSED_and_nothing_is_written( tmp_path ):
    """
    🔴 THE REFUSAL THIS MODULE EXISTS FOR. Blocks inherit, so two definitions means the
    enforced value depends on which block a process loaded. A writer that picked one
    would report success while the number half the fleet reads never moved.
    """
    path = _ini( tmp_path, WELL_FORMED + "\n[Lupin: Development]\ncc session fleet size cap = 4\n" )
    before = open( path, encoding="utf-8" ).read()

    with pytest.raises( io.KeyDefinedTwice ) as refusal:
        io.write_int_to_disk( path, KEY, 12 )

    assert open( path, encoding="utf-8" ).read() == before, "a refusal must write NOTHING"
    message = str( refusal.value )
    assert "Lupin: Baseline" in message and "Lupin: Development" in message, \
           f"the refusal must name EVERY line it found: {message}"
    # Line numbers are 1-based and are the point: an operator has to be able to GO to
    # them. Derived from the fixture rather than hand-counted, because a hand-counted
    # number is a second place the fixture's shape has to be remembered.
    # ⚠️ THE NAME BEFORE THE `=`, NOT A PREFIX. `startswith( KEY )` also matches
    # `cc session fleet size cap maximum` — the very hazard the writer's anchored regex
    # exists for, re-derived here by hand and got wrong on the first try. Left as a
    # comment because the next person writing a fixture over this file will reach for
    # the same shortcut.
    lines = before.split( "\n" )
    expected = [ i + 1 for i, line in enumerate( lines )
                 if "=" in line and line.split( "=" )[ 0 ].strip() == KEY ]
    assert len( expected ) == 2, f"the fixture must really define it twice: {expected}"
    for number in expected:
        assert f"line {number}" in message, f"the refusal must name line {number}: {message}"


def test_a_key_defined_NOWHERE_is_REFUSED_rather_than_appended( tmp_path ):
    """Inventing the key would put it in whatever section the writer guessed, and the
    section decides which processes read it."""
    path = _ini( tmp_path, "[Lupin: Baseline]\nsomething else = 1\n" )
    before = open( path, encoding="utf-8" ).read()
    with pytest.raises( io.KeyNotFound ):
        io.write_int_to_disk( path, KEY, 12 )
    assert open( path, encoding="utf-8" ).read() == before


def test_the_reader_fails_SOFT_where_the_writer_refuses( tmp_path ):
    """
    The asymmetry is deliberate: the reader runs on the SPAWN path, where a None falls
    back to the configuration manager — the behaviour that existed before this module.
    The writer is an operator action with a human waiting on the answer.
    """
    path = _ini( tmp_path, WELL_FORMED + "\n[Lupin: Development]\ncc session fleet size cap = 4\n" )
    assert io.read_int_from_disk( path, KEY ) is None          # ambiguous → None
    assert io.read_int_from_disk( str( tmp_path / "nope.ini" ), KEY ) is None   # absent → None


def test_the_section_a_definition_lives_in_is_reported( tmp_path ):
    path = _ini( tmp_path, WELL_FORMED )
    assert io.locate_key( path, KEY ).section == "Lupin: Baseline"
