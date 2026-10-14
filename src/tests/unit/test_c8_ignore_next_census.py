"""
Census: every c8 ignore-next comment sits directly above the code it guards.

A c8 ignore-next comment covers the single line after it. A doc block or a
plain comment between the two leaves the ignore guarding the comment. The
branch it was written for then counts as missed.

Requires:
    - git is on the path and the tree is a git checkout

Ensures:
    - every tracked TypeScript and JavaScript line holding a c8 ignore-next
      comment is followed by a code line, with one named exception
    - the exception is a comment on line 1 of a file, the file-header artifact
"""

import re
import subprocess

import pytest

import cosa.utils.util as cu

IGNORE_NEXT = re.compile( r"/\*\s*c8 ignore next\b" )
SUFFIXES    = ( ".ts", ".js", ".mjs" )
COMMENT     = ( "//", "/*", "*" )


def tracked_sources():
    """
    List tracked TypeScript and JavaScript files under src/lupin_app/static/js.

    Ensures:
        - returns repo-relative paths from git, not from a disk walk
    """
    out = subprocess.run(
        [ "git", "ls-files", "src/lupin_app/static/js" ],
        cwd=cu.get_project_root(), capture_output=True, text=True, check=True
    ).stdout.split( "\n" )
    return [ p for p in out if p.endswith( SUFFIXES ) ]


def stranded( lines ):
    """
    Return 1-based line numbers of c8 ignore-next comments not followed by code.

    Requires:
        - lines is a list of source lines

    Ensures:
        - line 1 is never reported (file-header artifact)
        - a following blank line or comment line is reported
    """
    found = [ ]
    for i, line in enumerate( lines ):
        if i == 0 or not IGNORE_NEXT.search( line ): continue
        nxt = lines[ i + 1 ].strip() if i + 1 < len( lines ) else ""
        if nxt == "" or nxt.startswith( COMMENT ): found.append( i + 1 )
    return found


def test_population_is_not_empty():
    files = tracked_sources()
    assert len( files ) > 100
    hits = 0
    for path in files:
        with open( cu.get_project_root() + "/" + path, encoding="utf-8" ) as fh:
            hits += sum( 1 for l in fh if IGNORE_NEXT.search( l ) )
    assert hits > 100


@pytest.mark.parametrize( "text, expected", [
    ( [ "x", "/* c8 ignore next */", "/** doc */", "export function f() {}" ], [ 2 ] ),
    ( [ "x", "/* c8 ignore next */ // why", "// note", "code();" ],            [ 2 ] ),
    ( [ "x", "/* c8 ignore next */", "", "code();" ],                          [ 2 ] ),
    ( [ "x", "/* c8 ignore next */ // why", "code();" ],                       [ ] ),
    ( [ "/* c8 ignore next */ // header", "// head", "code();" ],              [ ] ),
    ( [ "x", "/* c8 ignore next */" ],                                         [ 2 ] ),
] )
def test_detector_finds_planted_cases( text, expected ):
    assert stranded( text ) == expected


def test_no_c8_ignore_next_is_followed_by_a_comment():
    bad = [ ]
    for path in tracked_sources():
        with open( cu.get_project_root() + "/" + path, encoding="utf-8" ) as fh:
            for n in stranded( fh.read().split( "\n" ) ): bad.append( f"{path}:{n}" )
    assert bad == [ ], "c8 ignore next must sit directly above code:\n" + "\n".join( bad )
