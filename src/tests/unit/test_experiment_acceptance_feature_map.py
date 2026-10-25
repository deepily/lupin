"""
Every experiment feature has an acceptance test, and no test uses a banned locator.

The tests find elements by visible text and role, never by test id or style class.
Each feature in the feature list needs at least one test. These guards read both as text.
"""
import ast
import pathlib
import re

import cosa.utils.util as cu

REPO         = pathlib.Path( cu.get_project_root() )
FEATURE_LIST = REPO / "src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.25-experiment-build-task-feature-list.md"
TEST_DIR     = REPO / "src/tests/experiment_acceptance"
FEATURE_ROW  = re.compile( r"^\| (F\d{2})(?: \(opt\))? \|", re.M )
CITATION     = re.compile( r"pytest\.mark\.feature\( \"(F\d{2})\" \)" )
BANNED       = re.compile( r"get_by_test_id|get_by_placeholder|get_by_alt_text|get_by_title|\.locator\(|query_selector|xpath|css=|data-testid|set_default_timeout|get_attribute|\.or_\(|to_have_class|to_have_css|\.first\b" )
EXPECTED_IDS = [ f"F{n:02d}" for n in range( 1, 15 ) ]


def feature_ids( text ):
    """Return the feature ids in a feature list's tables, in order."""
    return FEATURE_ROW.findall( text )


def cited_ids( texts ):
    """Return the set of feature ids cited in the given test sources."""
    return { found for text in texts for found in CITATION.findall( text ) }


def banned_hits( text ):
    """Return every banned locator pattern found in a test source."""
    return BANNED.findall( text )


def test_feature_list_has_the_expected_fourteen_ids():
    assert feature_ids( FEATURE_LIST.read_text( encoding="utf-8" ) ) == EXPECTED_IDS


def test_every_feature_is_cited_by_at_least_one_acceptance_test():
    sources = [ p.read_text( encoding="utf-8" ) for p in sorted( TEST_DIR.glob( "test_*.py" ) ) ]
    assert len( sources ) == 3, "the draft has three test files"
    assert sorted( cited_ids( sources ) ) == EXPECTED_IDS


def test_no_acceptance_test_cites_an_unknown_feature():
    sources = [ p.read_text( encoding="utf-8" ) for p in TEST_DIR.glob( "test_*.py" ) ]
    assert cited_ids( sources ) <= set( EXPECTED_IDS )


def test_no_acceptance_test_uses_a_banned_locator():
    offenders = { p.name: banned_hits( p.read_text( encoding="utf-8" ) ) for p in TEST_DIR.glob( "*.py" ) }
    assert { name: hits for name, hits in offenders.items() if hits } == {}


def empty_tests( text ):
    """Return the names of test functions whose body has no assert statement and no expect call."""
    names = []
    for node in ast.walk( ast.parse( text ) ):
        if isinstance( node, ast.FunctionDef ) and node.name.startswith( "test_" ):
            asserts = any( isinstance( n, ast.Assert ) for n in ast.walk( node ) )
            expects = any( isinstance( n, ast.Call ) and isinstance( n.func, ast.Name ) and n.func.id == "expect" for n in ast.walk( node ) )
            if not ( asserts or expects ): names.append( node.name )
    return names


def test_every_acceptance_test_asserts_something():
    found = { p.name: empty_tests( p.read_text( encoding="utf-8" ) ) for p in TEST_DIR.glob( "test_*.py" ) }
    assert { name: tests for name, tests in found.items() if tests } == {}


def test_the_empty_test_detector_flags_a_bare_return_and_passes_real_tests():
    assert empty_tests( "def test_a():\n    return\n" ) == [ "test_a" ]
    assert empty_tests( "def test_b():\n    assert 1\n" ) == []
    assert empty_tests( "def test_c(page):\n    expect( page ).to_be_visible()\n" ) == []
    assert empty_tests( "def helper():\n    return\n" ) == []


def test_the_banned_locator_detector_finds_each_banned_form():
    for sample in ( 'page.get_by_test_id( "x" )', 'page.locator( ".btn" )', 'page.query_selector( "a" )', 'page.get_by_placeholder( "e" )', 'css=.a', 'x.get_attribute( "class" )', 'a.or_( b )', 'a.first.click()' ):
        assert banned_hits( sample ), sample
    assert banned_hits( 'page.get_by_role( "button", name="Login" )' ) == []


def test_the_citation_and_row_parsers_find_what_they_should():
    assert feature_ids( "| F01 | x |\n| F13 (opt) | y |\n| Other | z |" ) == [ "F01", "F13" ]
    assert cited_ids( [ '@pytest.mark.feature( "F03" )', "nothing" ] ) == { "F03" }
