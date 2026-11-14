"""Census guard: every job that reads a switch has its INI key, and no other job has one."""
import json
import re

import cosa.utils.util as cu

REGISTRY = "/src/conf/job-registry.json"
INI      = "/src/conf/lupin-app.ini"
SPLAINER = "/src/conf/lupin-app-splainer.ini"
HELD_OFF = { "duplicate-check" }


def read( path ):
    with open( cu.get_project_root() + path, encoding="utf-8" ) as handle: return handle.read()


def registry_jobs():
    return json.loads( read( REGISTRY ) )[ "jobs" ]


def switch_values( text ):
    """Ensures: returns { key: value text } for every `cron job <name> enabled = <value>` line."""
    return { m.group( 1 ): m.group( 2 ) for m in re.finditer( r"^(cron job \S+ enabled)\s*=\s*(\S*)\s*$", text, re.MULTILINE ) }


def missing_switches( jobs, ini_text ):
    """
    Ensures: returns the jobs that read a switch but lack a true or false canonical key.

    A job reads a switch when it is cron-managed or names a switch_reader.
    """
    have = switch_values( ini_text )
    return [ j[ "job" ] for j in jobs if ( j.get( "cron_managed" ) or j.get( "switch_reader" ) ) and ( j.get( "enabled_key" ) != f"cron job {j[ 'job' ]} enabled" or have.get( j.get( "enabled_key" ) ) not in ( "true", "false" ) ) ]


def test_the_registry_holds_twelve_cron_managed_jobs_and_each_has_a_switch_in_the_ini():
    jobs = registry_jobs()
    assert len( jobs ) == 24 and len( [ j for j in jobs if j.get( "cron_managed" ) ] ) == 12
    assert missing_switches( jobs, read( INI ) ) == []


def test_a_job_outside_cron_management_carries_a_key_only_when_it_names_the_loop_that_reads_it():
    unmanaged = [ j for j in registry_jobs() if not j.get( "cron_managed" ) ]
    assert len( unmanaged ) == 12
    assert [ j[ "job" ] for j in unmanaged if "enabled_key" in j and not j.get( "switch_reader" ) ] == []
    assert sorted( switch_values( read( INI ) ) ) == sorted( j[ "enabled_key" ] for j in registry_jobs() if "enabled_key" in j )


def test_only_the_duplicate_check_ships_switched_off():
    have = switch_values( read( INI ) )
    assert sorted( k for k, v in have.items() if v == "false" ) == sorted( f"cron job {j} enabled" for j in HELD_OFF )
    assert len( [ v for v in have.values() if v == "true" ] ) == len( [ j for j in registry_jobs() if "enabled_key" in j ] ) - len( HELD_OFF )


def test_every_switch_has_a_splainer_twin():
    assert sorted( switch_values( read( INI ) ) ) == sorted( re.findall( r"^(cron job \S+ enabled)\s*=", read( SPLAINER ), re.MULTILINE ) )


def test_the_guard_goes_red_when_one_switch_is_deleted_from_the_ini():
    cut = "\n".join( l for l in read( INI ).split( "\n" ) if not l.startswith( "cron job disk-report enabled" ) )
    assert cut != read( INI )
    assert missing_switches( registry_jobs(), cut ) == [ "disk-report" ]


def test_the_guard_goes_red_when_a_managed_job_has_no_enabled_key():
    jobs = [ dict( j ) for j in registry_jobs() ]
    first = next( j for j in jobs if j.get( "cron_managed" ) )
    first.pop( "enabled_key" )
    assert missing_switches( jobs, read( INI ) ) == [ first[ "job" ] ]
