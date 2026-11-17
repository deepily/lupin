"""
A fence around the main checkout's lupin-app.ini for tests that write switch keys.

A test that flips a switch must write a temp file. A mutated resolver, or a test that forgets its
override, would send the write to the real file that every cron job reads. This fixture stops that
two ways and then checks a third.

Ensures, for every test that uses it:
    - the INI writers refuse the main checkout's file before they write a byte, and the test fails
    - the file's sha256 is the same after the test as before, or the test fails
    - the main checkout is found with `git rev-parse --git-common-dir`, not with the code under test,
      so a mutated resolver cannot move the fence along with it
"""
import hashlib
import os
import subprocess

import pytest

import cosa.utils.util as cu
from lupin_mcp import fleet_cap_ini_io

WRITERS = ( "_replace_value_line", "write_bool_to_disk", "write_int_to_disk" )


def main_ini_path() -> str:
    """
    The main checkout's configuration file, derived from git alone.

    Ensures:
        - returns `<main checkout>/src/conf/lupin-app.ini` as a real path
        - a plain checkout names its own file
    """
    common = subprocess.run(
        [ "git", "-C", cu.get_project_root(), "rev-parse", "--path-format=absolute", "--git-common-dir" ],
        capture_output=True, text=True, check=True, timeout=10
    ).stdout.strip()
    return os.path.realpath( os.path.join( os.path.dirname( common ), "src", "conf", "lupin-app.ini" ) )


def _sha256( path: str ) -> str:
    with open( path, "rb" ) as handle:
        return hashlib.sha256( handle.read() ).hexdigest()


def raise_fence( monkeypatch, guarded ):
    """
    Make the INI writers refuse one file.

    Requires:
        - guarded is the real path of the file to protect

    Ensures:
        - an INI writer called with that file raises AssertionError and writes nothing
        - returns ( before, refused ): the file's sha256 now, and a list that gains one entry per refusal
    """
    before  = _sha256( guarded )
    refused = []

    def fenced( real ):
        def wrapper( path, *args, **kwargs ):
            if os.path.realpath( str( path ) ) == guarded:
                refused.append( ( real.__name__, str( path ) ) )
                raise AssertionError( f"fence: {real.__name__} was asked to write the main checkout's lupin-app.ini ({guarded}); nothing was written" )
            return real( path, *args, **kwargs )
        wrapper.__name__ = real.__name__
        return wrapper

    for name in WRITERS:
        monkeypatch.setattr( fleet_cap_ini_io, name, fenced( getattr( fleet_cap_ini_io, name ) ) )
    return before, refused


def check_fence( guarded, before, refused ):
    """
    Fail when the fenced file was written, or an attempt was swallowed.

    Ensures:
        - raises AssertionError when any refusal was recorded
        - raises AssertionError when the file's sha256 is not `before`
    """
    assert not refused, f"a test tried to write the main checkout's lupin-app.ini: {refused}"
    assert _sha256( guarded ) == before, f"the main checkout's lupin-app.ini changed during the test ({guarded})"


@pytest.fixture( autouse=True )
def main_ini_fence( monkeypatch ):
    """
    Fence the main checkout's lupin-app.ini for one test.

    Ensures:
        - yields the fenced path; teardown runs check_fence on it
    """
    guarded         = main_ini_path()
    before, refused = raise_fence( monkeypatch, guarded )
    yield guarded
    check_fence( guarded, before, refused )
