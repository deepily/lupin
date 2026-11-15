"""
One parse rule for a job's switch: the accordion and the cron wrapper agree.

Maria's review of the remaining-switches work found two parse rules for one value. The cron wrapper took the
configuration manager's boolean parse, which accepts words such as `yes` and `1`. The accordion took
a strict true/false parse. A value like `yes` would have shown as unknown in the accordion while the
cron job ran. Both now call `lupin_mcp.cron_switch_read.parse_switch`.

The same strings go through all three readers below, and each answer is compared with a literal.
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import cron_job_switches as sw
from lupin_mcp import cron_switch_read as csr
from lupin_mcp import job_run

JOB = "probe-job"

# ( the text after the equals sign, what every reader must answer )
CASES = [
    ( "true",    True  ),
    ( "false",   False ),
    ( "True",    True  ),
    ( "FALSE",   False ),
    ( " true ",  True  ),
    ( "yes",     None  ),
    ( "no",      None  ),
    ( "1",       None  ),
    ( "0",       None  ),
    ( "on",      None  ),
    ( "maybe",   None  ),
]


class _Config:
    """A configuration stand-in that answers the key's text, as get_required does."""
    def __init__( self, text ):
        self.text = text

    def get_required( self, key, return_type="string" ):
        assert key == csr.switch_key( JOB )
        return self.text


def _ini( tmp_path, text ):
    path = tmp_path / "probe.ini"
    path.write_text( f"[Block]\n{csr.switch_key( JOB )} = {text}\n" )
    return str( path )


@pytest.mark.parametrize( "text, expected", CASES )
def test_the_shared_parse_answers_the_literal( text, expected ):
    assert csr.parse_switch( text ) is expected


@pytest.mark.parametrize( "text, expected", CASES )
def test_the_disk_reader_and_the_accordion_agree_on_every_string( tmp_path, monkeypatch, text, expected ):
    path = _ini( tmp_path, text )
    monkeypatch.setenv( sw.INI_OVERRIDE_ENV, path )
    assert csr.read_switch( path, JOB ) is expected
    assert sw.read_enabled( JOB ) is expected


@pytest.mark.parametrize( "text, expected", CASES )
def test_the_cron_wrapper_agrees_on_every_string( text, expected ):
    entry = { "job": JOB, "enabled_key": csr.switch_key( JOB ) }
    if expected is None:
        with pytest.raises( ValueError, match="neither true nor false" ):
            job_run.switched_on( entry, _Config( text ) )
    else:
        assert job_run.switched_on( entry, _Config( text ) ) is expected


def test_the_wrapper_names_the_key_and_the_value_it_refused():
    entry = { "job": JOB, "enabled_key": csr.switch_key( JOB ) }
    with pytest.raises( ValueError ) as caught:
        job_run.switched_on( entry, _Config( "yes" ) )
    assert csr.switch_key( JOB ) in str( caught.value ) and "'yes'" in str( caught.value )


@pytest.mark.parametrize( "raw", [ None, "", "   ", 1, True, [ "true" ] ] )
def test_a_value_that_is_not_a_switch_word_is_unknown_and_never_raises( raw ):
    assert csr.parse_switch( raw ) is None


def test_a_missing_or_doubled_key_reads_as_unknown_through_the_disk_reader( tmp_path ):
    absent = tmp_path / "absent.ini"
    absent.write_text( "[Block]\nother = true\n" )
    doubled = tmp_path / "doubled.ini"
    doubled.write_text( f"[Block]\n{csr.switch_key( JOB )} = true\n{csr.switch_key( JOB )} = false\n" )
    assert csr.read_switch( str( absent ), JOB ) is None
    assert csr.read_switch( str( doubled ), JOB ) is None
    assert csr.read_switch( str( tmp_path / "no-such-file.ini" ), JOB ) is None


def test_the_key_is_the_one_the_accordion_names():
    assert csr.switch_key( "duplicate-check" ) == "cron job duplicate-check enabled"
    assert sw.switch_key( "duplicate-check" ) == csr.switch_key( "duplicate-check" )
