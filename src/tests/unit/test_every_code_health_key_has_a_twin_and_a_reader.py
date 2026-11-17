"""Census of the code-health keys: each has a splainer twin and a known reader."""
import re
import subprocess

import cosa.utils.util as cu
from cosa.repo import code_health_settings as chs

KINDS    = "|".join( re.escape( k ) for k in chs.PER_REPO_KINDS )
KEY_LINE = re.compile( rf"^external repo (\S+) ({KINDS})\s*=", re.MULTILINE )
GLOBAL   = re.compile( rf"^{re.escape( chs.DATA_SUBDIR_KEY )}\s*=", re.MULTILINE )


def read( path ):
    with open( cu.get_project_root() + path, encoding="utf-8" ) as handle: return handle.read()


def keys( text ):
    return sorted( f"external repo {m.group( 1 )} {m.group( 2 )}" for m in KEY_LINE.finditer( text ) ) + [ chs.DATA_SUBDIR_KEY ] * len( GLOBAL.findall( text ) )


def test_the_ini_holds_eight_per_repo_keys_for_lupin_and_one_global_key():
    """The literal count comes from the INI text, not from the table."""
    found = keys( read( "/src/conf/lupin-app.ini" ) )
    assert len( found ) == 9
    assert sorted( found[ :-1 ] ) == sorted( chs.repo_key( "lupin", k ) for k in chs.PER_REPO_KINDS )
    assert found[ -1 ] == chs.DATA_SUBDIR_KEY


def test_every_ini_key_has_a_splainer_twin():
    assert keys( read( "/src/conf/lupin-app.ini" ) ) == keys( read( "/src/conf/lupin-app-splainer.ini" ) )


def test_the_census_goes_red_when_a_twin_is_deleted():
    twin    = read( "/src/conf/lupin-app-splainer.ini" )
    cut     = "\n".join( l for l in twin.split( "\n" ) if not l.startswith( "external repo lupin jev token limit" ) )
    assert keys( read( "/src/conf/lupin-app.ini" ) ) != keys( cut )


def tracked_code():
    out = subprocess.run( [ "git", "ls-files", "--cached", "--others", "--exclude-standard", "src" ], cwd=cu.get_project_root(), capture_output=True, text=True, check=True ).stdout.split()
    return [ p for p in out if p.endswith( ".py" ) and "/tests/" not in p and "/.venv/" not in p ]


def test_every_code_health_key_read_in_code_is_in_the_table():
    """Scan every non-test python file for f-string `external repo {name} <kind>` keys."""
    code = tracked_code()
    assert code
    known, seen, readers = set( chs.PER_REPO_KINDS ) | { "path", "allowed prefixes" }, set(), []
    for rel in code:
        text = read( "/" + rel )
        found = re.findall( r'f"external repo \{[a-z_]+\} ([a-z ]+?)"', text )
        seen.update( found )
        if re.search( r"^DATA_SUBDIR_KEY\s*=", text, re.MULTILINE ): readers.append( rel )
    assert seen and seen <= known, f"unlisted kind: {seen - known}"
    assert readers == [ "src/cosa/repo/code_health_settings.py" ]
    assert len( re.findall( r'^[A-Z_]+_KIND\s*= "', read( "/" + readers[ 0 ] ), re.MULTILINE ) ) == 8
