"""
Census: no duplicate-check text calls the backlog total "owed".

Rick ruled on 14 Nov 2026 that the word misleads. It is kept only where a line explains the old schema 1 and 2 names, because an old line is read through them.
The proof command's "owed" pairs are labels still owed by a reviewer, a different thing, so its two pages are out.
"""
import pathlib
import re
import subprocess

import pytest

ROOT       = pathlib.Path( __file__ ).resolve().parents[ 3 ]
CODE       = ( "src/lupin_mcp/duplicate_check_daily.py", "src/lupin_mcp/duplicate_check_history.py", "src/lupin_mcp/duplicate_check_status.py" )
OTHER_WIKI = ( "src/docs/wiki/INDEX.md", )
PROOF_OWED = ( "src/docs/wiki/capabilities/duplicate-check-proof-command.md", "src/docs/wiki/capabilities/duplicate-check-proof-flag-items.md" )     # labels owed by a reviewer, not the backlog
WORD       = re.compile( r"\bowed\b", re.IGNORECASE )
LEGACY     = ( "schema 3", "schema 1 and 2", "owed is now", "LEGACY_NAME" )     # a line that explains the old names may still say them
PINNED     = { "src/lupin_mcp/duplicate_check_daily.py": 1, "src/lupin_mcp/duplicate_check_history.py": 3,
               "src/docs/wiki/capabilities/duplicate-check-daily-run.md": 1, "src/docs/wiki/capabilities/duplicate-check-run-history.md": 1 }       # the explaining lines, counted on 14 Nov 2026


def tracked( pathspec ):
    """Ensures: returns the tracked files matching the git pathspec, relative to the repo root."""
    out = subprocess.run( [ "git", "ls-files", pathspec ], cwd=ROOT, capture_output=True, text=True, check=True ).stdout
    return out.split()


def wiki_pages():
    """Ensures: returns the tracked backlog wiki pages, without the proof command's."""
    return [ p for p in tracked( "src/docs/wiki/capabilities/duplicate-check-*.md" ) if p not in PROOF_OWED ]


def owed_lines( text ):
    """Ensures: returns the lines that say owed without explaining the old names."""
    return [ l for l in text.splitlines() if WORD.search( l ) and not any( m in l for m in LEGACY ) ]


def explaining_lines( text ):
    """Ensures: returns the lines that say owed and explain the old names."""
    return [ l for l in text.splitlines() if WORD.search( l ) and any( m in l for m in LEGACY ) ]


def test_the_census_finds_a_line_that_calls_the_backlog_owed():
    assert owed_lines( "the run was given 12,347 owed definitions" ) and not owed_lines( "the run was given 12,347 definitions" )
    assert not owed_lines( "Result files before schema 3 called the first two `owed` and `carried`." ) and explaining_lines( "Result files before schema 3 called the first two `owed` and `carried`." )


def test_the_census_walks_the_three_modules_and_every_backlog_wiki_page():
    pages = wiki_pages()
    assert len( pages ) >= 15 and all( p.startswith( "src/docs/wiki/capabilities/duplicate-check-" ) for p in pages )
    assert not set( PROOF_OWED ) & set( pages ) and all( ( ROOT / p ).exists() for p in PROOF_OWED )
    assert all( ( ROOT / p ).exists() for p in CODE + OTHER_WIKI )


@pytest.mark.census
def test_every_duplicate_check_text_avoids_owed():
    files = [ *CODE, *OTHER_WIKI, *wiki_pages() ]
    found = { f: owed_lines( ( ROOT / f ).read_text( encoding="utf-8" ) ) for f in files if f != "src/docs/wiki/INDEX.md" }
    index = [ l for l in ( ROOT / "src/docs/wiki/INDEX.md" ).read_text( encoding="utf-8" ).splitlines() if "duplicate-check" in l and WORD.search( l ) ]
    bad   = { f: ls for f, ls in found.items() if ls }
    assert not bad and not index, f"duplicate-check text calls something owed: {bad} {index}"


def test_the_explaining_lines_are_the_pinned_ones_and_no_more():
    got = { f: len( explaining_lines( ( ROOT / f ).read_text( encoding="utf-8" ) ) ) for f in [ *CODE, *wiki_pages() ] }
    assert { f: n for f, n in got.items() if n } == PINNED
