"""
Every path in CLAUDE.md's "Where to read more" table names a file that exists.

The table is the pointer slot of the CLAUDE.md template. A pointer to a page that was renamed
or never written reads as help and leads nowhere, so the table is checked against the tree.

Reads: CLAUDE.md at the project root, section `## Where to read more`, the backticked paths in its `Read` column.
"""

import os
import re

import cosa.utils.util as cu

HEADING   = "## Where to read more"
MIN_ROWS  = 10


def _table_rows( text ):
    """
    Return the data rows of the pointer table as lists of cells.

    Requires:
        - text is the full text of CLAUDE.md

    Ensures:
        - the heading appears exactly once, otherwise AssertionError
        - rows are the lines after the `|---|` separator up to the first line that is not a table row

    Raises:
        - AssertionError if the heading is missing or repeated, or the table has no separator row
    """
    assert text.count( HEADING + "\n" ) == 1, f"expected exactly one '{HEADING}' heading in CLAUDE.md"
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


def _read_claude_md():
    with open( os.path.join( cu.get_project_root(), "CLAUDE.md" ), encoding="utf-8" ) as fh:
        return fh.read()


def test_the_pointer_table_is_found_and_not_empty():
    rows = _table_rows( _read_claude_md() )
    assert len( rows ) >= MIN_ROWS, f"the pointer table has {len( rows )} rows; the scan broke or the table was gutted"
    assert all( len( cells ) == 3 for cells in rows ), "every row must have Topic, Read and When cells"
    assert len( _targets( rows ) ) >= len( rows ), "a row names no backticked path"


def test_every_pointer_names_a_file_that_exists():
    root    = cu.get_project_root()
    missing = [ t for t in _targets( _table_rows( _read_claude_md() ) ) if not os.path.isfile( os.path.join( root, t ) ) ]
    assert missing == [], f"CLAUDE.md points at files that do not exist: {missing}"


def test_the_check_can_find_a_missing_target():
    """Positive control: the same predicate must reject a path that is not there."""
    fake = "| Topic | `src/docs/no-such-page-claude-md-pointer-control.md` | when |"
    rows = [ [ c.strip() for c in fake.strip( "|" ).split( "|" ) ] ]
    root = cu.get_project_root()
    assert [ t for t in _targets( rows ) if not os.path.isfile( os.path.join( root, t ) ) ] == [
        "src/docs/no-such-page-claude-md-pointer-control.md" ]
