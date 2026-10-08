"""
Unit tests that the wiki index lists each capability page once.

The page pack raises on a repeated id.
A second index line for one page is therefore a defect.
"""
import re

import cosa.utils.util as cu

INDEX_LINE = re.compile( r"^- \[\[(?P<slug>[^\]]+)\]\]" )


def index_slug_lines():
    """
    Read the wiki index and return each page line as ( slug, line number ).

    Requires:
        - the wiki index file exists under the project root

    Ensures:
        - returns one tuple per line that starts with a bracketed slug
        - line numbers count from 1

    Raises:
        - FileNotFoundError if the index is missing
    """
    path = cu.get_project_root() + "/src/docs/wiki/INDEX.md"
    with open( path, encoding="utf-8" ) as handle:
        lines = handle.read().splitlines()
    found = []
    for number, text in enumerate( lines, start=1 ):
        match = INDEX_LINE.match( text )
        if match: found.append( ( match.group( "slug" ), number ) )
    return found


def test_the_index_parse_finds_page_lines():
    """The parse must find lines, or the duplicate check below would pass on nothing."""
    assert len( index_slug_lines() ) > 50


def test_no_slug_has_two_index_lines():
    """Each page id appears on exactly one index line; the message names the slug and lines."""
    seen       = {}
    duplicates = []
    for slug, number in index_slug_lines():
        if slug in seen: duplicates.append( f"{slug}: lines {seen[ slug ]} and {number}" )
        else: seen[ slug ] = number
    assert duplicates == [], "INDEX.md repeats a page id: " + "; ".join( duplicates )
