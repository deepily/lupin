#!/usr/bin/env python3
"""
Census: the PUT route is the only code path that writes a cron job switch key.

Rick's ruling (13 Nov 2026): only the administrator flips these switches, and no seat or manager
may reach a write. A census over the tracked source finds any other writer. Two rules:

    1. `write_switch` is called from the router and nowhere else in source.
    2. No source file that names a `cron job ... enabled` key calls one of the INI writers,
       except the module that owns the key (`cron_job_switches.py`).

The scan reads tracked files (`git ls-files`), skips tests, and proves its own finder on planted text.
"""
import os
import re
import subprocess
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.utils.util as cu

OWNER_MODULE = "src/cosa/rest/cron_job_switches.py"
ROUTER       = "src/cosa/rest/routers/cron_jobs.py"
INI_WRITERS  = ( "write_bool_to_disk", "write_int_to_disk", "_replace_value_line", "set_config" )
KEY_TEXT     = re.compile( r"cron job\b[^\n]{0,40}\benabled|switch_key\s*\(|KEY_TEMPLATE" )
CALLER       = re.compile( r"\bwrite_switch\s*\(" )


def _source_files():
    root   = cu.get_project_root()
    listed = subprocess.run( [ "git", "ls-files", "src/*.py" ], cwd=root, capture_output=True, text=True, check=True ).stdout.split()
    return root, [ p for p in listed if "/tests/" not in p and not p.startswith( "src/tests/" ) ]


def writers_of_the_key( text ):
    """Whether this file's text both names a switch key and calls an INI writer."""
    return bool( KEY_TEXT.search( text ) ) and any( name + "(" in text or name + " (" in text for name in INI_WRITERS )


def test_the_finder_sees_a_planted_writer():
    planted = 'key = f"cron job {job} enabled"\nfleet_cap_ini_io.write_bool_to_disk( path, key, True )\n'
    assert writers_of_the_key( planted )
    assert not writers_of_the_key( 'key = f"cron job {job} enabled"\nvalue = read_value_from_disk( path, key )\n' )
    assert CALLER.search( "cron_job_switches.write_switch( job, on, who )" )


def test_the_census_walks_a_real_population():
    root, files = _source_files()
    assert len( files ) > 500
    assert OWNER_MODULE.removeprefix( "src/" ) in [ f.removeprefix( "src/" ) for f in files ] or OWNER_MODULE in files
    assert ROUTER in files


def test_write_switch_is_called_only_by_the_router():
    root, files = _source_files()
    callers = []
    for path in files:
        if path == OWNER_MODULE: continue
        with open( os.path.join( root, path ), encoding="utf-8", errors="replace" ) as handle:
            if CALLER.search( handle.read() ): callers.append( path )
    assert callers == [ ROUTER ]


def test_no_other_source_file_writes_a_cron_job_switch_key():
    root, files = _source_files()
    offenders = []
    for path in files:
        if path == OWNER_MODULE: continue
        with open( os.path.join( root, path ), encoding="utf-8", errors="replace" ) as handle:
            if writers_of_the_key( handle.read() ): offenders.append( path )
    assert offenders == []
