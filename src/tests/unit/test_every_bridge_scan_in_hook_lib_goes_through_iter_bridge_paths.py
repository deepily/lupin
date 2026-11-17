"""
Pins for `sessions_dir.iter_bridge_paths`, the one listing of bridge files.

Eight hook-library loops each globbed `cc-*.json` and skipped a name holding "buffer" or
"listener"; they now call the iterator. Two scans keep their own glob, and the census below
pins them by name and count so a ninth copy cannot appear unnoticed:

- `session_bridge._find_session_file`, the cwd fallback, skips no name. It sorts by mtime
  with a `stat()` in the sort key, so an unreadable file raises there.
- `stale_buffer_janitor.list_bridge_live_hashes` skips no name either. It takes an injected
  directory and calls `stat()` inside a `try`.

Folding either in would change what it does. When this was written the live sessions directory
held 23 `cc-*.json` files. None had "buffer" or "listener" in its name. So the skip guards names
that do not occur today.
"""

import os
import re
import subprocess

from lupin_cli.claude_code.hooks.lib.sessions_dir import iter_bridge_paths

BRIDGE_SCAN_RE = re.compile( r'\.glob\(\s*(?:"cc-\*\.json"|BRIDGE_GLOB)' )
HOOK_LIB       = "src/lupin_cli/claude_code/hooks/lib"


class FakeDir:
    """A directory stand-in with only a glob method, as the tests that patch `SESSION_DIR` use."""
    def __init__( self, names ):
        self.names   = names
        self.pattern = None

    def glob( self, pattern ):
        self.pattern = pattern
        return iter( [ self.names[ i ] for i in range( len( self.names ) ) ] )


class Named:
    def __init__( self, name ):
        self.name = name


def test_iter_bridge_paths_yields_bridges_and_skips_sibling_names( tmp_path ):
    for name in ( "cc-1.json", "cc-22.json", "cc-buffer-1.json", "cc-listener-9.json", "cc-3.jsonl", "other.json" ):
        ( tmp_path / name ).write_text( "{}" )
    got = sorted( p.name for p in iter_bridge_paths( tmp_path ) )
    assert got == [ "cc-1.json", "cc-22.json" ]


def test_iter_bridge_paths_is_lazy_and_in_glob_order():
    fake = FakeDir( [ Named( "cc-2.json" ), Named( "cc-listener-1.json" ), Named( "cc-1.json" ) ] )
    gen  = iter_bridge_paths( fake )
    assert fake.pattern is None, "nothing is scanned until the first item is asked for"
    assert next( gen ).name == "cc-2.json"
    assert fake.pattern == "cc-*.json"
    assert [ p.name for p in gen ] == [ "cc-1.json" ]


def test_iter_bridge_paths_over_a_missing_directory_yields_nothing( tmp_path ):
    assert list( iter_bridge_paths( tmp_path / "absent" ) ) == []


def test_every_bridge_scan_in_hook_lib_goes_through_iter_bridge_paths():
    """Census: a bridge glob outside the iterator is a copy, except the two named scans."""
    root  = os.environ[ "LUPIN_ROOT" ]
    files = subprocess.run( [ "git", "ls-files", f"{HOOK_LIB}/*.py" ], cwd=root,
                            capture_output=True, text=True, check=True ).stdout.split()
    assert len( files ) > 30, "the census walked the wrong population"
    found = {}
    for rel in files:
        with open( os.path.join( root, rel ), encoding="utf-8" ) as fh:
            n = len( BRIDGE_SCAN_RE.findall( fh.read() ) )
        if n: found[ rel.rsplit( "/", 1 )[ -1 ] ] = n
    assert found == {
        "sessions_dir.py"         : 1,    # the iterator itself
        "session_bridge.py"       : 1,    # the cwd fallback: no name skip, mtime sort
        "stale_buffer_janitor.py" : 1,    # no name skip, injected directory
    }
