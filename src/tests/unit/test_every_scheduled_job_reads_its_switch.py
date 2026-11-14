"""
Every scheduled job in the registry reads its on/off switch, checked job by job.

Rick, 13 Nov: every job the accordion lists must actually read its switch, "listed out explicitly and
then checked 1 by 1". A job is honoured when it runs through job_run, which is cron_managed. It is
also honoured when it names, in `switch_reader`, the symbol that checks or builds its TickSwitch.

NOT_YET lists the jobs that do not read their switch yet. It only shrinks. A job leaves the list in
the commit that makes it honoured, and a listed job that is already honoured fails the test.
"""
import importlib
import inspect
import json
import os
import pathlib
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import cron_job_switches as sw
from lupin_mcp import cron_switch_read as csr

ROOT          = pathlib.Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
REGISTRY      = json.loads( ( ROOT / "src/conf/job-registry.json" ).read_text() )[ "jobs" ]
INI           = str( ROOT / "src/conf/lupin-app.ini" )
REGISTRY_SIZE = 24      # counted by hand from src/conf/job-registry.json on 14 Nov; change it only with the registry

# Jobs that do not read their switch yet. Remove a job in the commit that makes it read its switch.
NOT_YET = frozenset( {
    "yearly-reminders",
    "notification-expiry", "commons-archival", "notify-outbox", "socket-housekeeping", "side-services",
} )

JOBS     = [ entry[ "job" ] for entry in REGISTRY ]
HONOURED = [ entry for entry in REGISTRY if entry[ "job" ] not in NOT_YET ]
READERS  = [ entry for entry in REGISTRY if "switch_reader" in entry ]
JOB_RUN_READER = "lupin_mcp.job_run:switched_on"     # the reader named by a job whose cron line runs through cron-job.sh, though cron_generate does not write it


def _resolve( reader ):
    """
    Find the symbol a `switch_reader` names.

    Requires:
        - reader is `module.path:Qualified.name`

    Ensures:
        - returns the function or method the string names

    Raises:
        - ImportError or AttributeError when it names nothing
    """
    module_name, _, qualname = reader.partition( ":" )
    target = importlib.import_module( module_name )
    for part in qualname.split( "." ):
        target = getattr( target, part )
    return target


def test_the_registry_holds_the_24_jobs_this_census_was_written_for():
    assert len( JOBS ) == REGISTRY_SIZE
    assert len( set( JOBS ) ) == REGISTRY_SIZE


def test_every_job_on_the_not_yet_list_is_a_registry_job():
    assert NOT_YET <= set( JOBS ), sorted( NOT_YET - set( JOBS ) )


def test_every_job_off_the_not_yet_list_is_honoured():
    assert HONOURED, "the census found no honoured job, so it checked nothing"
    missing = [ entry[ "job" ] for entry in HONOURED if not sw.is_honoured( entry ) ]
    assert missing == [], f"these jobs do not read their switch: {missing}"


def test_no_job_on_the_not_yet_list_is_already_honoured():
    early = sorted( entry[ "job" ] for entry in REGISTRY if entry[ "job" ] in NOT_YET and sw.is_honoured( entry ) )
    assert early == [], f"these jobs read their switch now, so take them off NOT_YET: {early}"


@pytest.mark.parametrize( "entry", HONOURED, ids=lambda entry: entry[ "job" ] )
def test_an_honoured_job_names_its_own_key_and_the_real_ini_file_holds_true_or_false( entry ):
    assert entry.get( "enabled_key" ) == csr.switch_key( entry[ "job" ] )
    assert csr.read_switch( INI, entry[ "job" ] ) in ( True, False ), f"{csr.switch_key( entry[ 'job' ] )} is missing from lupin-app.ini or holds another word"


def test_every_switch_reader_names_a_real_symbol_that_checks_the_switch():
    loops = [ entry[ "job" ] for entry in HONOURED if entry.get( "cron_managed" ) is not True ]
    assert sorted( entry[ "job" ] for entry in READERS ) == sorted( loops ), "every honoured job that cron does not start must name its reader"
    for entry in READERS:
        source = inspect.getsource( _resolve( entry[ "switch_reader" ] ) )
        builds = f'cron_switch_read.for_job( "{entry[ "job" ]}"' in source
        by_run = entry[ "switch_reader" ] == JOB_RUN_READER and "enabled_key" in source     # a cron line through cron-job.sh: job_run reads the key before each run
        assert builds or by_run or ".allowed(" in source, f"{entry[ 'job' ]}: {entry[ 'switch_reader' ]} neither builds its own switch nor calls TickSwitch.allowed"


@pytest.mark.parametrize( "entry", READERS, ids=lambda entry: entry[ "job" ] )
def test_a_switch_reader_job_keeps_its_summary_where_the_switch_writes_failures( entry ):
    assert entry[ "summary_path" ] == f"{{root}}/io/jobs/{entry[ 'job' ]}/job-summary.json"
    assert csr.summary_path_in( "/r", entry[ "job" ] ) == f"/r/io/jobs/{entry[ 'job' ]}/job-summary.json"


def _a_tick_that_checks( switch ):
    """
    A positive control: a tick body that checks its switch.

    Requires:
        - switch is a TickSwitch

    Ensures:
        - returns whether the tick would do its work
    """
    return switch.allowed()


def test_the_symbol_check_finds_a_reader_that_checks_and_refuses_one_that_does_not():
    assert ".allowed(" in inspect.getsource( _a_tick_that_checks )
    assert ".allowed(" not in inspect.getsource( _resolve( "lupin_mcp.cron_switch_read:read_switch" ) )
    assert _resolve( "lupin_mcp.cron_switch_read:TickSwitch.allowed" ) is csr.TickSwitch.allowed
    with pytest.raises( AttributeError ):
        _resolve( "lupin_mcp.cron_switch_read:no_such_symbol" )
