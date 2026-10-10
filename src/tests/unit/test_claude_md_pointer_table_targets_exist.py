"""
The pointers in both CLAUDE.md files name things that exist.

The pointer table is a slot of the CLAUDE.md template. A pointer to a renamed or missing page leads nowhere.
Every named path and every named heading is therefore checked against the tree.

Reads: CLAUDE.md and src/cosa/CLAUDE.md, section `## Where to read more`, the paths in the `Read` column.
It also reads each backticked path followed by `§ "heading"` anywhere in either file.
"""

import os
import re

import pytest

import cosa.utils.util as cu

HEADING = "## Where to read more"
FILES   = ( "CLAUDE.md", "src/cosa/CLAUDE.md" )
MIN_ROWS = { "CLAUDE.md" : 10, "src/cosa/CLAUDE.md" : 5 }


def _table_rows( text ):
    """
    Return the data rows of the pointer table as lists of cells.

    Requires:
        - text is the full text of a CLAUDE.md file

    Ensures:
        - the heading appears exactly once, otherwise AssertionError
        - rows are the lines after the `|---|` separator up to the first line that is not a table row

    Raises:
        - AssertionError if the heading is missing or repeated, or the table has no separator row
    """
    assert text.count( HEADING + "\n" ) == 1, f"expected exactly one '{HEADING}' heading"
    section = text.split( HEADING + "\n", 1 )[ 1 ].split( "\n## ", 1 )[ 0 ]
    lines   = section.splitlines()
    starts  = [ i for i, ln in enumerate( lines ) if re.match( r"^\|\s*-+\s*\|", ln ) ]
    assert starts, "the pointer table has no |---| separator row"
    rows = []
    for ln in lines[ starts[ 0 ] + 1 : ]:
        if not ln.startswith( "|" ): break
        rows.append( [ c.strip() for c in ln.strip().strip( "|" ).split( "|" ) ] )
    return rows


def _targets( rows ):
    """Return every backticked path in the second column of the rows."""
    found = []
    for cells in rows:
        found.extend( re.findall( r"`([^`]+)`", cells[ 1 ] ) )
    return found


def _anchors( text ):
    """Return ( path, heading ) for each backticked path followed by § "heading"."""
    return re.findall( r"`([^`]+\.md)` § \"([^\"]+)\"", text )


def _read( rel ):
    with open( os.path.join( cu.get_project_root(), rel ), encoding="utf-8" ) as fh:
        return fh.read()


def _missing( rows, root ):
    return [ t for t in _targets( rows ) if not os.path.exists( os.path.join( root, t ) ) ]


def _unanchored( anchors, root ):
    """Return the ( path, heading ) pairs whose page has no such heading."""
    bad = []
    for path, heading in anchors:
        full = os.path.join( root, path )
        if not os.path.isfile( full ): bad.append( ( path, heading ) ); continue
        with open( full, encoding="utf-8" ) as fh:
            lines = [ ln for ln in fh.read().splitlines() if ln.startswith( "#" ) ]
        if not any( heading in ln for ln in lines ): bad.append( ( path, heading ) )
    return bad


@pytest.mark.parametrize( "rel", FILES )
def test_the_pointer_table_is_found_and_not_empty( rel ):
    rows = _table_rows( _read( rel ) )
    assert len( rows ) >= MIN_ROWS[ rel ], f"{rel}: {len( rows )} rows; the scan broke or the table was gutted"
    assert all( len( cells ) == 3 for cells in rows ), f"{rel}: every row must have Topic, Read and When cells"
    assert len( _targets( rows ) ) >= len( rows ), f"{rel}: a row names no backticked path"


@pytest.mark.parametrize( "rel", FILES )
def test_every_pointer_names_something_that_exists( rel ):
    missing = _missing( _table_rows( _read( rel ) ), cu.get_project_root() )
    assert missing == [], f"{rel} points at paths that do not exist: {missing}"


@pytest.mark.parametrize( "rel", FILES )
def test_every_named_heading_exists_in_its_page( rel ):
    root    = cu.get_project_root()
    anchors = _anchors( _read( rel ) )
    bad     = _unanchored( anchors, root )
    assert bad == [], f"{rel} names headings that are not in the page: {bad}"


def test_the_anchor_check_finds_the_testing_venues_anchor():
    """The anchor that prompted the check is in the scan, so the check sees something."""
    anchors = _anchors( _read( "CLAUDE.md" ) )
    assert ( "src/docs/doctrine/testing-venues.md", "The `:7999` suite list" ) in anchors, anchors


def test_the_checks_can_find_a_missing_target_and_a_missing_heading():
    """Positive controls: both predicates reject a path and a heading that are absent."""
    root = cu.get_project_root()
    fake = [ [ "Topic", "`src/docs/no-such-page-claude-md-pointer-control.md`", "when" ] ]
    assert _missing( fake, root ) == [ "src/docs/no-such-page-claude-md-pointer-control.md" ]
    bad = _unanchored( [ ( "src/docs/doctrine/testing-venues.md", "No such heading, control" ) ], root )
    assert bad == [ ( "src/docs/doctrine/testing-venues.md", "No such heading, control" ) ]
