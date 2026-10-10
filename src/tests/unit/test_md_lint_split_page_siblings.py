"""
A label or section mark defined in a sibling part of a split page is not a bare reference.

The fixture is the test-fix-expediter-guide split as committed in c344cd0d3.
The index sits at the old path and four parts sit in the folder beside it.
Read one file at a time, the parts raised 38 bare-ref findings.
Each is a Phase label or section mark that another part of the same page defines.
"""

import hashlib
import os

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import md_lint

FIXTURE_ROOT = "src/tests/fixtures/md_lint/split_pages"
INDEX        = "test-fix-expediter-guide.md"
PARTS        = (
    "test-fix-expediter-guide/01-what-it-does-and-architecture.md",
    "test-fix-expediter-guide/02-six-phase-pipeline.md",
    "test-fix-expediter-guide/03-watchdog-ini-and-enabling.md",
    "test-fix-expediter-guide/04-troubleshooting-and-code-map.md",
)
SHA256       = {
    INDEX    : "79e3f4994b1860ce541c2809670b297a9c9d4913abce7c07c0f1e6ab79d3c910",
    PARTS[ 0 ]: "9b6e33fbaef9b162b997b3fa95ade07e45ebf27a0e53207e437be832f5f93fe7",
    PARTS[ 1 ]: "9589710c4bc59a868ca373048346b522067c1197c9138e3e5b4706ade6b9db78",
    PARTS[ 2 ]: "a9a9ffda2d41b6d892f0371ded25a694c196b2ea30582fc47ea581cef225699b",
    PARTS[ 3 ]: "bc4a8e29ce83fa366098608580c2ab2fc15f385fdca601c7362ce87fe9d525cb",
}
# Bare-ref findings per part read alone, measured on the fixture before the change.
ALONE        = { PARTS[ 0 ]: 9, PARTS[ 1 ]: 3, PARTS[ 2 ]: 17, PARTS[ 3 ]: 9 }


def _root():
    return os.path.join( cu.get_project_root(), FIXTURE_ROOT )


def _read( root, rel ):
    with open( os.path.join( root, rel ), encoding="utf-8" ) as handle: return handle.read()


def _bare( root, rel, with_root=True ):
    findings = md_lint.lint_source( rel, _read( root, rel ), root=root if with_root else None )
    return [ f.message for f in findings if f.rule == "bare-ref" ]


def _write( root, rel, text ):
    path = os.path.join( root, rel )
    os.makedirs( os.path.dirname( path ), exist_ok=True )
    with open( path, "w", encoding="utf-8" ) as handle: handle.write( text )


@pytest.mark.parametrize( "rel", sorted( SHA256 ) )
def test_each_fixture_file_is_the_one_committed_in_c344cd0d3( rel ):
    assert hashlib.sha256( _read( _root(), rel ).encode( "utf-8" ) ).hexdigest() == SHA256[ rel ]


@pytest.mark.parametrize( "rel", PARTS )
def test_a_part_read_without_a_root_keeps_the_findings_it_had_alone( rel ):
    assert len( _bare( _root(), rel, with_root=False ) ) == ALONE[ rel ]


@pytest.mark.parametrize( "rel", [ PARTS[ 0 ], PARTS[ 2 ], PARTS[ 3 ] ] )
def test_a_part_with_siblings_has_no_bare_ref_left( rel ):
    assert _bare( _root(), rel ) == []


def test_part_two_keeps_only_the_label_no_part_defines():
    assert _bare( _root(), PARTS[ 1 ] ) == [ "bare reference 'C1'" ]


def test_the_index_has_no_bare_ref():
    assert _bare( _root(), INDEX ) == []


def test_a_phase_label_is_resolved_by_a_heading_in_another_part():
    messages = _bare( _root(), PARTS[ 0 ], with_root=False )
    assert "bare reference 'Phase 3'" in messages
    assert "### Phase 3: Fix" in _read( _root(), PARTS[ 1 ] )
    assert "bare reference 'Phase 3'" not in _bare( _root(), PARTS[ 0 ] )


def test_a_section_mark_is_resolved_by_a_numbered_heading_in_a_sibling():
    alone = _bare( _root(), PARTS[ 1 ], with_root=False )
    assert "section reference '§5' has no path" in alone and "section reference '§4' has no path" in alone
    assert "section reference '§5' has no path" not in _bare( _root(), PARTS[ 1 ] )
    assert "section reference '§4' has no path" not in _bare( _root(), PARTS[ 1 ] )


PAGE_WITH_PARTS = "# Foo\n\nContents.\n"
PART_ONE        = "# Part 1\n\n## 1. Intro\n\nSee Phase 1 and Phase 7 and §2 and §9 for more.\n"
PART_TWO        = "# Part 2\n\n## 2. Steps\n\n### Phase 1: Start\n\nText.\n"


def _split_tree( tmp_path, index=True, nested=False ):
    root = str( tmp_path )
    if index: _write( root, "foo.md", PAGE_WITH_PARTS )
    _write( root, "foo/01-intro.md", PART_ONE )
    _write( root, "foo/02-steps.md", PART_TWO )
    if nested: _write( root, "foo/sub/03-deep.md", "# Deep\n\n### Phase 7: Deep\n\n## 9. Deep\n" )
    return root


def test_a_label_and_a_section_mark_that_no_sibling_defines_still_fire( tmp_path ):
    messages = _bare( _split_tree( tmp_path ), "foo/01-intro.md" )
    assert "bare reference 'Phase 7'" in messages
    assert "section reference '§9' has no path" in messages
    assert "bare reference 'Phase 1'" not in messages
    assert "section reference '§2' has no path" not in messages


def test_a_folder_without_an_index_beside_it_gives_no_siblings( tmp_path ):
    messages = _bare( _split_tree( tmp_path, index=False ), "foo/01-intro.md" )
    assert "bare reference 'Phase 1'" in messages


def test_a_nested_folder_is_not_read_as_a_sibling( tmp_path ):
    messages = _bare( _split_tree( tmp_path, nested=True ), "foo/01-intro.md" )
    assert "bare reference 'Phase 7'" in messages
    assert "section reference '§9' has no path" in messages


def test_a_page_outside_a_split_gets_no_siblings( tmp_path ):
    root = str( tmp_path )
    _write( root, "lone.md", "# Lone\n\nSee Phase 1 and §2 here.\n" )
    _write( root, "other.md", "# Other\n\n### Phase 1: Start\n\n## 2. Steps\n" )
    messages = _bare( root, "lone.md" )
    assert "bare reference 'Phase 1'" in messages
    assert "section reference '§2' has no path" in messages


def test_a_section_mark_with_a_path_beside_it_is_still_resolved_without_siblings( tmp_path ):
    root = str( tmp_path )
    _write( root, "lone.md", "# Lone\n\nSee §2 of docs/guide.md for the steps.\n" )
    assert _bare( root, "lone.md" ) == []


def test_a_numbered_heading_in_the_page_itself_does_not_resolve_a_lone_page( tmp_path ):
    root = str( tmp_path )
    _write( root, "lone.md", "# Lone\n\n## 2. Steps\n\nSee §2 here.\n" )
    assert _bare( root, "lone.md" ) == [ "section reference '§2' has no path" ]


def test_a_folder_of_dated_archive_files_beside_an_index_is_not_a_split( tmp_path ):
    root = str( tmp_path )
    _write( root, "history.md", "# History\n\nContents.\n" )
    _write( root, "history/2026-05-03-to-06-history.md", "# May\n\nSee Phase 1 here.\n" )
    _write( root, "history/2026-04-22-to-24-history.md", "# April\n\n### Phase 1: Start\n" )
    assert "bare reference 'Phase 1'" in _bare( root, "history/2026-05-03-to-06-history.md" )


def test_only_numbered_parts_count_as_siblings( tmp_path ):
    root = _split_tree( tmp_path )
    _write( root, "foo/notes.md", "# Notes\n\n### Phase 7: Notes\n" )
    assert "bare reference 'Phase 7'" in _bare( root, "foo/01-intro.md" )
