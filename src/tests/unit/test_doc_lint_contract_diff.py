"""
contract_diff: a missing heading and a fallen item count must be findings, in real-shaped input.

The six writer pairs in src/tests/fixtures/contract_diff/writer_pairs.json are tracked docstrings and
the verbatim output of a Sonnet rewrite (see the provenance field there). That writer kept all three
headings, so the renamed-heading cases below are derived from its real output by renaming one heading,
and the dropped-item cases by deleting one item; both derivations are done in the test, in plain sight.
"""

import io
import json
import os
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.doc_lint import contract_diff as cd

with open( os.path.join( cu.get_project_root(), "src", "tests", "fixtures", "contract_diff", "writer_pairs.json" ), encoding="utf-8" ) as handle:
    PAIRS = json.load( handle )[ "pairs" ]


def _source( function, docstring ):
    return f"def {function}():\n    {docstring!r}\n"


def _rows( pair, new=None ):
    return cd.diff_contracts( _source( pair[ "function" ], pair[ "old" ] ), _source( pair[ "function" ], pair[ "new" ] if new is None else new ) )


def _findings( rows ):
    return cd.findings( { "f.py": rows } )


def _drop_first_ensures_item( text ):
    out, seen, inside = [], False, False
    for line in text.split( "\n" ):
        if line.strip() == "Ensures:": inside = True
        elif inside and line.strip().startswith( "- " ) and not seen:
            seen = True
            continue
        out.append( line )
    return "\n".join( out )


def test_the_fixture_is_six_real_pairs_each_with_all_three_headings():
    assert len( PAIRS ) == 6
    for pair in PAIRS:
        for side in ( "old", "new" ):
            assert all( f"{h}:" in pair[ side ] for h in cd.SECTIONS ), ( pair[ "function" ], side )


@pytest.mark.parametrize( "pair", PAIRS, ids=lambda p: p[ "function" ] )
def test_real_writer_output_that_kept_its_headings_and_items_has_no_findings( pair ):
    rows = _rows( pair )
    assert rows and not any( r[ "heading_missing" ] for r in rows ) and all( r[ "lost" ] == [] for r in rows )
    assert _findings( rows ) == []


@pytest.mark.parametrize( "pair", PAIRS[ :3 ], ids=lambda p: p[ "function" ] )
def test_a_renamed_heading_with_every_item_kept_is_exactly_one_finding( pair ):
    renamed = pair[ "new" ].replace( "Ensures:", "Output:" )
    found   = _findings( _rows( pair, renamed ) )
    assert len( found ) == 1 and found[ 0 ].startswith( "HEADING MISSING" ) and "Ensures" in found[ 0 ] and "now under Output" in found[ 0 ], found


# ( pair, index of the old Ensures item that corresponds to the first Ensures item of the new text, which the test deletes )
HAND_DROPS = [ ( 0, 0 ), ( 2, 0 ), ( 4, 3 ) ]


@pytest.mark.parametrize( "index,old_item", HAND_DROPS )
def test_a_renamed_heading_plus_one_dropped_item_is_two_findings_and_names_the_item( index, old_item ):
    pair    = PAIRS[ index ]
    renamed = _drop_first_ensures_item( pair[ "new" ] ).replace( "Ensures:", "Behaviour:" )
    found   = _findings( _rows( pair, renamed ) )
    assert len( found ) == 2, found
    assert found[ 0 ].startswith( "HEADING MISSING" ) and found[ 1 ].startswith( "COUNT FELL" )
    assert cd.parse_sections( pair[ "old" ] )[ "Ensures" ][ old_item ] in found[ 1 ], found


@pytest.mark.parametrize( "index,old_item", HAND_DROPS )
def test_a_dropped_item_under_an_unchanged_heading_is_a_count_finding_that_names_it( index, old_item ):
    pair  = PAIRS[ index ]
    found = _findings( _rows( pair, _drop_first_ensures_item( pair[ "new" ] ) ) )
    assert len( found ) == 1 and found[ 0 ].startswith( "COUNT FELL" ), found
    assert cd.parse_sections( pair[ "old" ] )[ "Ensures" ][ old_item ] in found[ 0 ], found


def test_a_split_item_that_hides_a_dropped_one_is_the_known_blind_spot_of_a_count():
    pair  = PAIRS[ 3 ]
    old_n = len( cd.parse_sections( pair[ "old" ] )[ "Ensures" ] )
    new_n = len( cd.parse_sections( pair[ "new" ] )[ "Ensures" ] )
    assert new_n == old_n + 1, "precondition: the writer split one item in two"
    assert _findings( _rows( pair, _drop_first_ensures_item( pair[ "new" ] ) ) ) == []


def test_tokens_and_overlap_ignore_case_punctuation_order_stopwords_and_a_plural_s():
    assert cd.tokens( "Returns `the` Formatted-string." ) == { "return", "formatted", "string" }
    assert cd.tokens( "string formatted returns" ) == cd.tokens( "Returns a formatted string" )
    assert cd.overlap( "returns formatted string", "gives back a formatted string" ) == pytest.approx( 2 / 3 )
    assert cd.overlap( "returns x", "completely different" ) == 0.0
    assert cd.overlap( "the a", "anything" ) == 1.0


DOC = '''
Do f.

Requires:
- flush bullet
* star bullet
1. numbered
2) numbered paren
    - nested deeper stays in the section

Ensures:
    - first line
      continues here
    - second

Notes:
    - not a contract section

Raises:
    - ValueError
'''


def test_parse_sections_reads_flush_star_numbered_and_continued_items():
    s = cd.parse_sections( DOC )
    assert s[ "Requires" ] == [ "flush bullet", "star bullet", "numbered", "numbered paren", "nested deeper stays in the section" ]
    assert s[ "Ensures" ] == [ "first line continues here", "second" ]
    assert s[ "Notes" ] == [ "not a contract section" ] and s[ "Raises" ] == [ "ValueError" ]


def test_parse_sections_edges():
    assert cd.parse_sections( None ) == {}
    assert cd.parse_sections( "Just prose.\n\nMore with - dash." ) == {}
    assert cd.parse_sections( "Requires:\n    - a\nTrailing prose\n    - not an item\n" ) == { "Requires": [ "a" ] }
    assert cd.parse_sections( "Args:\n    x: not a bullet\n\nEnsures:\n    - b\n" ) == { "Ensures": [ "b" ] }
    assert cd.parse_sections( "Requires:\n    - a\n\n    - after a blank line is no longer the section\n" ) == { "Requires": [ "a" ] }


CLASS_SRC = '''
class K:
    """
    Class doc.

    Requires:
        - a
    """

    @property
    def p( self ):
        """
        Ensures:
            - getter one
            - getter two
        """

    @p.setter
    def p( self, v ):
        """
        Ensures:
            - setter one
        """

    async def a( self ):
        """
        Raises:
            - nothing
        """

def undocumented():
    pass
'''


def test_definition_sections_track_classes_and_same_name_defs():
    found = cd.definition_sections( CLASS_SRC )
    assert set( found ) == { "K (class)", "K.p", "K.p#2", "K.a", "undocumented" }
    assert found[ "K (class)" ] == { "Requires": [ "a" ] }
    assert found[ "K.p" ][ "Ensures" ] == [ "getter one", "getter two" ] and found[ "K.p#2" ][ "Ensures" ] == [ "setter one" ]
    assert found[ "undocumented" ] == {}


def test_a_class_that_loses_its_contract_and_a_getter_that_loses_an_item_are_seen():
    new = CLASS_SRC.replace( "    Requires:\n        - a\n", "" ).replace( "            - getter two\n", "" )
    rows = {  ( r[ "function" ], r[ "section" ] ) : r for r in cd.diff_contracts( CLASS_SRC, new ) }
    assert rows[ ( "K (class)", "Requires" ) ][ "heading_missing" ] is True and rows[ ( "K (class)", "Requires" ) ][ "lost" ] == [ "a" ]
    assert rows[ ( "K.p", "Ensures" ) ][ "lost" ] == [ "getter two" ] and rows[ ( "K.p", "Ensures" ) ][ "after" ] == 1
    assert rows[ ( "K.p#2", "Ensures" ) ][ "lost" ] == []


def test_a_removed_definition_drops_everything_and_a_new_one_has_no_row():
    old = 'def f():\n    """\n    Ensures:\n        - x\n    """\n'
    new = 'def g():\n    """\n    Ensures:\n        - y\n    """\n'
    rows = cd.diff_contracts( old, new )
    assert [ ( r[ "function" ], r[ "heading_missing" ], r[ "lost" ], r[ "after" ] ) for r in rows ] == [ ( "f", True, [ "x" ], 0 ) ]
    assert cd.diff_contracts( None, new ) == []
    assert cd.diff_contracts( old, None )[ 0 ][ "after" ] == 0


def test_a_section_that_only_exists_after_is_a_row_with_nothing_dropped():
    old = 'def f():\n    """Plain."""\n'
    new = 'def f():\n    """\n    Raises:\n        - ValueError\n    """\n'
    assert cd.diff_contracts( old, new ) == [ { "function": "f", "section": "Raises", "before": 0, "after": 1, "heading_missing": False, "stand_in": None, "lost": [], "changed": [] } ]


def test_a_reworded_item_with_the_count_held_is_not_lost_and_not_a_finding():
    old = 'def f():\n    """\n    Ensures:\n        - returns 1\n    """\n'
    new = 'def f():\n    """\n    Ensures:\n        - gives back one\n    """\n'
    rows = cd.diff_contracts( old, new )
    assert rows[ 0 ][ "lost" ] == [] and _findings( rows ) == []


def test_findings_name_the_count_and_the_lost_items():
    old = 'def f():\n    """\n    Ensures:\n        - a\n        - b\n    """\n'
    new = 'def f():\n    """\n    Ensures:\n        - a\n    """\n'
    assert _findings( cd.diff_contracts( old, new ) ) == [ "COUNT FELL 2 -> 1: f.py f Ensures: b" ]


def test_a_vanished_heading_whose_items_are_now_under_another_name_names_it():
    old = 'def f():\n    """\n    Ensures:\n        - returns the total\n        - never mutates x\n    """\n'
    new = 'def f():\n    """\n    Output:\n        - Gives back the total.\n        - x is never mutated.\n    """\n'
    rows = cd.diff_contracts( old, new )
    assert [ ( r[ "heading_missing" ], r[ "stand_in" ], r[ "after" ], r[ "lost" ] ) for r in rows ] == [ ( True, "Output", 2, [] ) ]
    assert _findings( rows ) == [ "HEADING MISSING: f.py f Ensures (items now under Output)" ]


def test_a_stand_in_must_hold_enough_of_the_old_words_and_never_a_heading_that_already_matched():
    old = 'def f():\n    """\n    Requires:\n        - x is positive\n\n    Ensures:\n        - returns x when x is positive\n    """\n'
    new = 'def f():\n    """\n    Requires:\n        - x is positive\n\n    Notes:\n        - unrelated remark about logging\n    """\n'
    rows = { r[ "section" ] : r for r in cd.diff_contracts( old, new ) }
    assert rows[ "Ensures" ][ "stand_in" ] is None and rows[ "Ensures" ][ "after" ] == 0 and rows[ "Ensures" ][ "lost" ] == [ "returns x when x is positive" ]
    assert rows[ "Requires" ][ "heading_missing" ] is False


def test_likely_lost_picks_the_lowest_overlap_in_old_order_and_zero_picks_nothing():
    before = [ "returns the total", "never mutates x", "raises on empty" ]
    after  = [ "Gives back the total." ]
    assert cd.likely_lost( before, after, 2 ) == [ "never mutates x", "raises on empty" ]
    assert cd.likely_lost( before, after, 0 ) == [] and cd.likely_lost( before, [], 3 ) == before
    assert cd.likely_lost( before, after, -1 ) == [], "a count that rose loses nothing"


def test_likely_lost_returns_old_order_even_when_the_scores_run_the_other_way():
    before = [ "never mutates x", "raises on empty", "returns the total" ]
    assert cd.likely_lost( before, [ "gives back the total x" ], 2 ) == [ "never mutates x", "raises on empty" ]


def _ensures( *items ):
    return 'def f():\n    """\n    Ensures:\n' + "".join( f"        - {i}\n" for i in items ) + '    """\n'


def test_a_weakened_clause_with_the_count_held_is_reported_as_changed_not_matched():
    rows = cd.diff_contracts( _ensures( "never mutates x", "returns n >= 3 items" ), _ensures( "mutates x", "returns n > 3 items" ) )
    assert rows[ 0 ][ "lost" ] == [] and rows[ 0 ][ "changed" ] == [ ( "never mutates x", "mutates x" ), ( "returns n >= 3 items", "returns n > 3 items" ) ]
    assert _findings( rows ) == [ "CHANGED: f.py f Ensures: 'never mutates x' -> 'mutates x'", "CHANGED: f.py f Ensures: 'returns n >= 3 items' -> 'returns n > 3 items'" ]


def test_rewording_that_keeps_the_guard_words_is_not_changed_and_a_loss_is_not_a_change():
    assert cd.diff_contracts( _ensures( "never mutates x" ), _ensures( "x is never mutated, ever" ) )[ 0 ][ "changed" ] == []
    assert cd.diff_contracts( _ensures( "never mutates x", "b" ), _ensures( "unrelated words here" ) )[ 0 ][ "changed" ] == []


def test_an_item_split_in_two_keeps_its_guard_in_either_half_and_an_added_guard_is_not_reported():
    assert cd.changed_items( [ "returns the list, and never mutates x" ], [ "returns the list", "never mutates x" ] ) == []
    assert cd.changed_items( [ "mutates x" ], [ "never mutates x" ] ) == []


def test_an_old_item_whose_closest_new_item_belongs_to_a_neighbour_is_lost_not_changed():
    assert cd.changed_items( [ "never mutates x", "mutates x rows" ], [ "mutates x rows" ] ) == []
    assert cd.changed_items( [ "never mutates x" ], [ "x elsewhere" ] ) == [], "a weak match is a loss, not a change"


def test_a_neighbouring_item_with_its_own_never_cannot_vouch_for_a_weakened_one():
    before = [ "never mutates x", "never deletes the x rows" ]
    after  = [ "mutates x", "never deletes the x rows" ]
    assert cd.changed_items( before, after ) == [ ( "never mutates x", "mutates x" ) ]
    rows = cd.diff_contracts( _ensures( *before ), _ensures( *after ) )
    assert _findings( rows ) == [ "CHANGED: f.py f Ensures: 'never mutates x' -> 'mutates x'" ]


def test_guards_and_changed_items_edges():
    assert cd.guards( "never n >= 3 and not >" ) == [ ">", ">=", "never", "not" ]
    assert cd.changed_items( [ "x" ], [] ) == []


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


OLD_FILE = 'def f():\n    """\n    Ensures:\n        - a\n        - b\n    """\n'
NEW_FILE = 'def f():\n    """\n    Output:\n        - a\n        - b\n    """\n'


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "a.py" ).write_text( OLD_FILE, encoding="utf-8" )
    ( tmp_path / "é.py" ).write_text( OLD_FILE, encoding="utf-8" )
    ( tmp_path / "same.py" ).write_text( "x = 1\n", encoding="utf-8" )
    ( tmp_path / "b.dart" ).write_text( "a\n", encoding="utf-8" )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "base" )
    ( tmp_path / "a.py" ).write_text( NEW_FILE, encoding="utf-8" )
    ( tmp_path / "é.py" ).write_text( NEW_FILE, encoding="utf-8" )
    ( tmp_path / "same.py" ).write_text( "x = 2\n", encoding="utf-8" )
    ( tmp_path / "b.dart" ).write_text( "b\n", encoding="utf-8" )
    return tmp_path


def _run( root, *extra ):
    out = io.StringIO()
    rc  = cd.main( [ "--base", "HEAD", "--repo-root", str( root ), *extra ], out=out )
    return rc, out.getvalue()


def test_cli_table_shows_the_finding_column_and_skips_files_without_contracts( repo ):
    rc, text = _run( repo )
    assert rc == 0
    assert text.startswith( "| file | function | section | before | after | finding | likely lost |" )
    assert "| a.py | f | Ensures | 2 | 2 | HEADING MISSING (now Output) | - |" in text
    assert "same.py" not in text and "b.dart" not in text


def test_cli_reads_a_non_ascii_path( repo ):
    assert "| é.py | f | Ensures | 2 | 2 | HEADING MISSING (now Output) | - |" in _run( repo )[ 1 ]


def test_cli_strict_exits_one_on_a_missing_heading_and_zero_when_clean( repo ):
    assert _run( repo, "--strict" )[ 0 ] == 1
    ( repo / "a.py" ).write_text( OLD_FILE.replace( "- a", "- a." ), encoding="utf-8" )
    ( repo / "é.py" ).write_text( OLD_FILE, encoding="utf-8" )
    assert _run( repo, "--strict" )[ 0 ] == 0


def test_cli_a_rename_with_a_rewrite_shows_the_old_path_losing_everything( repo ):
    _git( repo, "mv", "a.py", "renamed.py" )
    ( repo / "renamed.py" ).write_text( "x = 1\n", encoding="utf-8" )
    _git( repo, "add", "-A" )
    rc, text = _run( repo, "--strict" )
    assert rc == 1 and "| a.py | f | Ensures | 2 | 0 | HEADING MISSING, COUNT FELL | a; b |" in text


def test_cli_json_and_head_revision( repo ):
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-qm", "head" )
    out = io.StringIO()
    rc  = cd.main( [ "--base", "HEAD~1", "--head", "HEAD", "--repo-root", str( repo ), "--json" ], out=out )
    data = json.loads( out.getvalue() )
    assert rc == 0 and sorted( data ) == [ "a.py", "é.py" ]
    assert { "function": "f", "section": "Ensures", "before": 2, "after": 2, "heading_missing": True, "stand_in": "Output", "lost": [], "changed": [] } in data[ "a.py" ]


def test_main_defaults_to_stdout( repo, capsys ):
    cd.main( [ "--base", "HEAD", "--repo-root", str( repo ) ] )
    assert "| file |" in capsys.readouterr().out


def test_cli_bad_revision_raises( repo ):
    with pytest.raises( RuntimeError, match="git diff" ):
        cd.main( [ "--base", "nope", "--repo-root", str( repo ) ], out=io.StringIO() )


# ---- mutation check: each mutant of the module must redden its named test ----

MUTANTS = [
    ( "missing  = bool( before ) and section not in new_sections", "missing  = False", "test_a_renamed_heading_with_every_item_kept_is_exactly_one_finding" ),
    ( "if missing: heading, after = stand_in( before, new_sections, own )", "if missing: heading, after = None, []", "test_a_renamed_heading_with_every_item_kept_is_exactly_one_finding" ),
    ( "if heading in own_headings: continue", "pass", "test_a_stand_in_must_hold_enough_of_the_old_words_and_never_a_heading_that_already_matched" ),
    ( "best, best_score = ( None, [] ), STAND_IN_MIN", "best, best_score = ( None, [] ), 0.0", "test_a_stand_in_must_hold_enough_of_the_old_words_and_never_a_heading_that_already_matched" ),
    ( "return [ before[ i ] for i in sorted( i for _, i in scored[ :count ] ) ]", "return [ before[ i ] for _, i in scored[ :count ] ]", "test_likely_lost_returns_old_order_even_when_the_scores_run_the_other_way" ),
    ( "scored = sorted( ( max( ( overlap( item, new ) for new in after ), default=0.0 ), i ) for i, item in enumerate( before ) )", "scored = sorted( ( 0.0, i ) for i, item in enumerate( before ) )", "test_likely_lost_picks_the_lowest_overlap_in_old_order_and_zero_picks_nothing" ),
    ( "if count <= 0: return []", "", "test_likely_lost_picks_the_lowest_overlap_in_old_order_and_zero_picks_nothing" ),
    ( "if r[ \"after\" ] < r[ \"before\" ]:\n                found.append", "if False:\n                found.append", "test_a_renamed_heading_plus_one_dropped_item_is_two_findings_and_names_the_item" ),
    ( "if r[ \"heading_missing\" ]:\n                now", "if False:\n                now", "test_a_renamed_heading_with_every_item_kept_is_exactly_one_finding" ),
    ( "words = ( w[ :-1 ] if len( w ) > 3 and w.endswith( \"s\" ) else w for w in WORD_REGEX.findall( item.lower() ) )", "words = WORD_REGEX.findall( item.lower() )", "test_tokens_and_overlap_ignore_case_punctuation_order_stopwords_and_a_plural_s" ),
    ( "return { w for w in words if w not in STOPWORDS }", "return set( words )", "test_tokens_and_overlap_ignore_case_punctuation_order_stopwords_and_a_plural_s" ),
    ( "( \" (class)\" if isinstance( child, ast.ClassDef ) else \"\" )", "\"\"", "test_definition_sections_track_classes_and_same_name_defs" ),
    ( "name = base if seen[ base ] == 1 else f\"{base}#{seen[ base ]}\"", "name = base", "test_definition_sections_track_classes_and_same_name_defs" ),
    ( "(?:[-*\\u2022]|\\d+[.)])", "(?:[-])", "test_parse_sections_reads_flush_star_numbered_and_continued_items" ),
    ( "elif name is not None and bullet and len( bullet.group( 1 ) ) >= header_indent:", "elif name is not None and bullet and len( bullet.group( 1 ) ) > header_indent:", "test_parse_sections_reads_flush_star_numbered_and_continued_items" ),
    ( "sections[ name ][ -1 ] += \" \" + line", "pass", "test_parse_sections_reads_flush_star_numbered_and_continued_items" ),
    ( "if set( guards( old ) ) - { g for new in group for g in guards( new ) }: pairs.append", "if False: pairs.append", "test_a_weakened_clause_with_the_count_held_is_reported_as_changed_not_matched" ),
    ( "if overlap( old, best ) < MATCH_MIN: continue", "pass", "test_an_old_item_whose_closest_new_item_belongs_to_a_neighbour_is_lost_not_changed" ),
    ( "if scores and max( scores ) >= STAND_IN_MIN: assigned[ scores.index( max( scores ) ) ].append( new )", "if scores: [ assigned[ k ].append( new ) for k in range( len( scores ) ) if scores[ k ] >= STAND_IN_MIN ]", "test_a_neighbouring_item_with_its_own_never_cannot_vouch_for_a_weakened_one" ),
    ( "if scores and max( scores ) >= STAND_IN_MIN:", "if scores and max( scores ) >= 2:", "test_a_weakened_clause_with_the_count_held_is_reported_as_changed_not_matched" ),
    ( "if not group: continue", "if not group: group = after", "test_an_old_item_whose_closest_new_item_belongs_to_a_neighbour_is_lost_not_changed" ),
    ( "OPERATOR_REGEX.findall( item )", "[]", "test_guards_and_changed_items_edges" ),
    ( "found += [ f\"CHANGED: {where}: {old!r} -> {new!r}\" for old, new in r[ \"changed\" ] ]", "pass", "test_a_weakened_clause_with_the_count_held_is_reported_as_changed_not_matched" ),
    ( "return 1 if args.strict and findings( results ) else 0", "return 0", "test_cli_strict_exits_one_on_a_missing_heading_and_zero_when_clean" ),
    ( "if p.endswith( \".py\" ) ):", "if p.endswith( \".py\" ) and p.isascii() ):", "test_cli_reads_a_non_ascii_path" ),
]


def _mutant_module( old, new ):
    path   = cd.__file__
    source = open( path, encoding="utf-8" ).read()
    assert source.count( old ) == 1, f"anchor must match exactly once: {old!r}"
    module = type( cd )( cd.__name__ )
    module.__file__, module.__package__ = path, cd.__package__
    exec( compile( source.replace( old, new ), path, "exec" ), module.__dict__ )
    return module


@pytest.mark.parametrize( "old,new,named_test", MUTANTS )
def test_each_mutant_reddens_its_named_test( monkeypatch, repo, old, new, named_test ):
    this   = globals()
    func   = this[ named_test ]
    names  = func.__code__.co_varnames[ : func.__code__.co_argcount ]
    kwargs = {}
    if "repo" in names: kwargs[ "repo" ] = repo
    if "pair" in names: kwargs[ "pair" ] = PAIRS[ 0 ]
    if "index" in names: kwargs[ "index" ], kwargs[ "old_item" ] = HAND_DROPS[ 0 ]
    func( **kwargs )
    monkeypatch.setitem( this, "cd", _mutant_module( old, new ) )
    with pytest.raises( Exception ):  # a crash reddens the test as surely as a failed assert
        func( **kwargs )
