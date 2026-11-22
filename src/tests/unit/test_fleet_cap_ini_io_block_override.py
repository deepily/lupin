"""
A VM-only block overrides the base value for the fleet cap and the skeleton crew switch.

Rick ruled on 21 Nov 2026 that the test VM keeps its own settings in the block it loads.
The disk readers and the writer therefore use the active block's definition.
Each test writes a small INI to a temporary folder and reads it back through the production parser.
"""
import pytest

from lupin_mcp import fleet_cap_ini_io as io

KEY  = "cc session fleet size cap"
BODY = (
    "[Lupin: Testing-GCS]\ninherits = Lupin: Development\ncc session fleet size cap = 1\n\n"
    "[Lupin: Development]\ninherits = Lupin: Baseline\nother = 1\n\n"
    "[Lupin: Baseline]\ncc session fleet size cap = 12\n"
)
VM   = { io.BLOCK_ENV: "config_path=/src/conf/x.ini config_block_id=Lupin:+Testing-GCS" }


def _ini( tmp_path, text=BODY ):
    path = tmp_path / "x.ini"
    path.write_text( text, encoding="utf-8" )
    return str( path )


def test_the_block_comes_from_the_environment_variable_the_vm_sets():
    assert io.active_block( VM ) == "Lupin: Testing-GCS"


def test_no_variable_or_no_block_id_reads_as_the_development_block():
    assert io.active_block( {} ) == io.DEFAULT_BLOCK == "Lupin: Development"
    assert io.active_block( { io.BLOCK_ENV: "config_path=/x.ini config_block_id=" } ) == io.DEFAULT_BLOCK


def test_the_process_environment_is_read_when_none_is_given( monkeypatch ):
    monkeypatch.setenv( io.BLOCK_ENV, "config_block_id=Lupin:+Testing" )
    assert io.active_block() == "Lupin: Testing"


def test_the_chain_runs_from_the_block_up_through_its_parents():
    lines = BODY.split( "\n" )
    assert io.inherit_chain( lines, "Lupin: Testing-GCS" ) == [ "Lupin: Testing-GCS", "Lupin: Development", "Lupin: Baseline" ]
    assert io.inherit_chain( lines, "Lupin: Baseline" ) == [ "Lupin: Baseline" ]


def test_a_block_the_file_does_not_hold_is_a_chain_of_one_and_a_cycle_ends():
    assert io.inherit_chain( BODY.split( "\n" ), "Lupin: Nowhere" ) == [ "Lupin: Nowhere" ]
    cycle = "[a]\ninherits = b\n[b]\ninherits = a\n".split( "\n" )
    assert io.inherit_chain( cycle, "a" ) == [ "a", "b" ]


def test_the_vm_block_reads_its_own_value_and_the_host_reads_the_base( tmp_path, monkeypatch ):
    path = _ini( tmp_path )
    monkeypatch.setenv( io.BLOCK_ENV, VM[ io.BLOCK_ENV ] )
    assert io.read_int_from_disk( path, KEY ) == 1
    monkeypatch.delenv( io.BLOCK_ENV )
    assert io.read_int_from_disk( path, KEY ) == 12


def test_the_writer_edits_the_line_the_active_block_reads_and_leaves_the_other_alone( tmp_path, monkeypatch ):
    path = _ini( tmp_path )
    monkeypatch.setenv( io.BLOCK_ENV, VM[ io.BLOCK_ENV ] )
    assert io.write_int_to_disk( path, KEY, 2 ) == 2
    text = open( path, encoding="utf-8" ).read()
    assert "cc session fleet size cap = 2" in text and "cc session fleet size cap = 12" in text
    monkeypatch.delenv( io.BLOCK_ENV )
    assert io.write_int_to_disk( path, KEY, 9 ) == 9
    assert "cc session fleet size cap = 2" in open( path, encoding="utf-8" ).read()


def test_two_definitions_in_one_section_still_refuse( tmp_path ):
    path = _ini( tmp_path, BODY + "cc session fleet size cap = 5\n" )
    assert io.read_int_from_disk( path, KEY ) is None
    with pytest.raises( io.KeyDefinedTwice ) as refusal:
        io.locate_key( path, KEY )
    assert "Lupin: Development" in str( refusal.value ), "the refusal names the block the process loaded"


def test_definitions_only_outside_the_chain_leave_the_file_ambiguous( tmp_path ):
    text = "[Lupin: Development]\ninherits = Lupin: Baseline\n[Lupin: Baseline]\nother = 1\n[Lupin: Production]\n" \
           "cc session fleet size cap = 3\n[Lupin: Testing]\ncc session fleet size cap = 4\n"
    path = _ini( tmp_path, text )
    assert io.read_int_from_disk( path, KEY ) is None
    with pytest.raises( io.KeyDefinedTwice ) as refusal:
        io.locate_key( path, KEY )
    assert "Lupin: Production" in str( refusal.value ) and "Lupin: Testing" in str( refusal.value )
    assert io.pick_definition( text.split( "\n" ), io.find_definitions( text.split( "\n" ), KEY ), "Lupin: Testing" ).section == "Lupin: Testing"


@pytest.fixture( autouse=True )
def _pinned_config_block( monkeypatch ):
    """Pin the loaded block to Development, so the shell's own block never decides a result."""
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", "config_block_id=Lupin:+Development" )
