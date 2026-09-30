"""
Live fixtures for the six docstring patterns of the documentation plan.

Each fixture is text copied from the real tree (or, for the deleted tmux runbook, from the
commit before its deletion) and frozen by hash. The linters must find the pattern it stands
for, so a rule that stops matching real text fails here and not in a review.
"""

import hashlib
import json
import os
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import md_lint, text_rules, word_list
from cosa.repo.doc_lint.rule_lists import DOCSTRING_MAX_LINES

FIXTURE_DIR = os.path.join( cu.get_project_root(), "src", "tests", "fixtures", "doc_lint" )

with open( os.path.join( FIXTURE_DIR, "manifest.json" ), encoding="utf-8" ) as handle:
    MANIFEST = json.load( handle )

MARKERS = { 1: "This predicate is the red", 2: "Requires:", 3: "RULING", 4: "FORENSIC UPDATE", 5: "§0 #2", 6: "DO NOT" }


def _text( entry ):
    with open( os.path.join( FIXTURE_DIR, entry[ "file" ] ), encoding="utf-8" ) as handle: return handle.read()


def test_every_pattern_has_at_least_one_fixture_and_the_manifest_lists_each_file_once():
    assert sorted( { e[ "pattern" ] for e in MANIFEST } ) == [ 1, 2, 3, 4, 5, 6 ]
    assert len( { e[ "file" ] for e in MANIFEST } ) == len( MANIFEST )
    assert sorted( f for f in os.listdir( FIXTURE_DIR ) if f != "manifest.json" ) == sorted( e[ "file" ] for e in MANIFEST )


@pytest.mark.parametrize( "entry", MANIFEST, ids=lambda e: e[ "file" ] )
def test_each_fixture_is_frozen_by_hash( entry ):
    assert hashlib.sha256( _text( entry ).encode() ).hexdigest() == entry[ "sha256" ]


@pytest.mark.parametrize( "entry", MANIFEST, ids=lambda e: e[ "file" ] )
def test_the_linters_find_the_pattern_each_fixture_stands_for( entry ):
    word_list.configure_root( cu.get_project_root() )
    text = _text( entry )
    if entry[ "file" ].endswith( ".md" ):
        found = { f.rule for f in md_lint.lint_source( entry[ "source" ], text ) }
    else:
        found = { f.rule for f in text_rules.lint_text( text, entry[ "source" ], entry[ "first_line" ] ) }
    assert set( entry[ "expected_rules" ] ) <= found, sorted( set( entry[ "expected_rules" ] ) - found )


def test_each_pattern_fixture_carries_the_text_that_makes_it_that_pattern():
    by_pattern = {}
    for e in MANIFEST: by_pattern.setdefault( e[ "pattern" ], [] ).append( _text( e ) )
    for pattern, marker in ( ( 1, MARKERS[ 1 ] ), ( 2, MARKERS[ 2 ] ), ( 3, MARKERS[ 3 ] ), ( 4, MARKERS[ 4 ] ), ( 5, MARKERS[ 5 ] ) ):
        assert any( marker in t for t in by_pattern[ pattern ] ), ( pattern, marker )
    assert max( sum( 1 for w in t.split() if w.isupper() and len( w ) > 2 ) for t in by_pattern[ 6 ] ) >= 20


def test_the_incident_history_fixture_is_the_long_docstring_the_length_cap_exists_for():
    entry = next( e for e in MANIFEST if e[ "file" ] == "p2-incident-history-park-reason.txt" )
    assert _text( entry ).strip( "\n" ).count( "\n" ) + 1 > DOCSTRING_MAX_LINES


@pytest.mark.parametrize( "entry", [ e for e in MANIFEST if e[ "repo" ] == "lupin" ], ids=lambda e: e[ "file" ] )
def test_lupin_fixtures_match_the_source_at_their_recorded_sha( entry ):
    shown = subprocess.run( [ "git", "-C", cu.get_project_root(), "show", f"{entry[ 'sha' ]}:{entry[ 'source' ]}" ], capture_output=True, text=True, encoding="utf-8" )
    assert shown.returncode == 0, shown.stderr
    text = _text( entry )
    if entry[ "file" ].endswith( ".md" ): assert shown.stdout == text
    else: assert all( line.strip() in shown.stdout for line in text.split( "\n" ) if line.strip() )


def test_only_lupin_mobile_fixtures_are_unchecked_against_their_source_and_say_so():
    assert { e[ "file" ] for e in MANIFEST if not e[ "provenance_checked_by_test" ] } == { e[ "file" ] for e in MANIFEST if e[ "repo" ] == "lupin-mobile" }
    assert len( [ e for e in MANIFEST if e[ "repo" ] == "lupin-mobile" ] ) == 2
