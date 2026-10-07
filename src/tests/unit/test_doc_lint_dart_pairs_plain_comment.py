"""
dart_pairs pairs a doc block that became a plain comment, or vanished, with what is left.

Store id e19f2d9d-73af-4c5e-8628-76bfb7ef86ae. A `///` block at the old revision was only paired
with a `///` block of the same symbol at the new one. The mobile docstring standard turns a private
member's `///` block into a `//` comment, so the ordinary case was counted `dropped_symbol_gone` and
left out. On the pilot range 20 of 45 changed blocks went that way, including the longest. The claim
judge then said nothing about the blocks whose text was cut the most.

Now a symbol whose declaration is still there is paired. The new text is the `//` comment
directly above it, or empty when there is none. A symbol whose declaration is gone is still dropped.

Seams driven for real: build_pairs over a real two-commit git repository.
"""

import subprocess

import pytest

from cosa.repo.doc_lint import dart_pairs as dp

LONG = " ".join( f"word{i}" for i in range( 35 ) )


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def _range( tmp_path, old_source, new_source ):
    """
    Commit one Dart file twice.

    Ensures:
        - returns ( root, old_rev, new_rev ) for lib/a.dart holding old_source then new_source
    """
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "lib" ).mkdir()
    target = tmp_path / "lib" / "a.dart"
    target.write_text( old_source, encoding="utf-8" )
    _git( tmp_path, "add", "." ); _git( tmp_path, "commit", "-qm", "old" )
    old = _git( tmp_path, "rev-parse", "HEAD" )
    target.write_text( new_source, encoding="utf-8" )
    _git( tmp_path, "add", "-A" ); _git( tmp_path, "commit", "-qm", "new" )
    return tmp_path, old, _git( tmp_path, "rev-parse", "HEAD" )


OLD = f"class A {{\n  /// {LONG}\n  void _helper() {{}}\n}}\n"


def test_a_doc_block_turned_into_a_plain_comment_is_paired_with_the_comment_text( tmp_path ):
    root, old, new = _range( tmp_path, OLD, "class A {\n  // Helper for the pane.\n  // Second line.\n  void _helper() {}\n}\n" )
    pairs, report = dp.build_pairs( root, old, new )
    assert [ p[ "id" ] for p in pairs ] == [ "lib/a.dart::A._helper" ]
    assert pairs[ 0 ][ "old" ] == LONG and pairs[ 0 ][ "new" ] == "Helper for the pane.\nSecond line."
    assert pairs[ 0 ][ "new_kind" ] == "plain_comment" and pairs[ 0 ][ "changed" ] is True
    assert report[ "dropped_symbol_gone" ] == 0 and report[ "paired_plain_comment" ] == 1 and report[ "pairs" ] == 1


def test_a_doc_block_removed_with_its_declaration_kept_is_paired_with_an_empty_text( tmp_path ):
    root, old, new = _range( tmp_path, OLD, "class A {\n  void _helper() {}\n}\n" )
    pairs, report = dp.build_pairs( root, old, new )
    assert [ ( p[ "id" ], p[ "new" ], p[ "new_kind" ] ) for p in pairs ] == [ ( "lib/a.dart::A._helper", "", "none" ) ]
    assert report[ "dropped_symbol_gone" ] == 0 and report[ "paired_no_comment" ] == 1


def test_a_plain_comment_above_the_annotations_still_counts_as_directly_above( tmp_path ):
    root, old, new = _range( tmp_path, OLD, "class A {\n  // Kept note.\n  @override\n  void _helper() {}\n}\n" )
    pairs, _ = dp.build_pairs( root, old, new )
    assert [ ( p[ "new" ], p[ "new_kind" ] ) for p in pairs ] == [ ( "Kept note.", "plain_comment" ) ]


def test_a_plain_comment_separated_by_a_blank_line_is_not_directly_above( tmp_path ):
    root, old, new = _range( tmp_path, OLD, "class A {\n  // Stray note.\n\n  void _helper() {}\n}\n" )
    pairs, report = dp.build_pairs( root, old, new )
    assert [ ( p[ "new" ], p[ "new_kind" ] ) for p in pairs ] == [ ( "", "none" ) ]
    assert report[ "paired_plain_comment" ] == 0


def test_a_triple_slash_block_is_never_taken_as_a_plain_comment( tmp_path ):
    root, old, new = _range( tmp_path, OLD, "class A {\n  /// Still documented.\n  void _helper() {}\n}\n" )
    pairs, report = dp.build_pairs( root, old, new )
    assert [ ( p[ "new" ], p[ "new_kind" ] ) for p in pairs ] == [ ( "Still documented.", "doc" ) ]
    assert report[ "paired_plain_comment" ] == 0 and report[ "paired_no_comment" ] == 0


def test_a_deleted_declaration_is_still_dropped_as_gone( tmp_path ):
    root, old, new = _range( tmp_path, OLD, "class A {\n  void other() {}\n}\n" )
    pairs, report = dp.build_pairs( root, old, new )
    assert pairs == [] and report[ "dropped_symbol_gone" ] == 1


def test_a_call_to_the_same_name_inside_another_method_is_not_a_declaration( tmp_path ):
    root, old, new = _range( tmp_path, OLD, "class A {\n  void run() {\n    _helper();\n    return _helper();\n  }\n}\n" )
    pairs, report = dp.build_pairs( root, old, new )
    assert pairs == [] and report[ "dropped_symbol_gone" ] == 1


def test_a_member_moved_to_another_owner_is_dropped_as_gone( tmp_path ):
    root, old, new = _range( tmp_path, OLD, "class A {}\nclass B {\n  void _helper() {}\n}\n" )
    pairs, report = dp.build_pairs( root, old, new )
    assert pairs == [] and report[ "dropped_symbol_gone" ] == 1


def test_a_top_level_function_that_lost_its_doc_block_is_paired_with_an_empty_text( tmp_path ):
    root, old, new = _range( tmp_path, f"/// {LONG}\nvoid _top() {{}}\n", "void _top() {}\n" )
    pairs, _ = dp.build_pairs( root, old, new )
    assert [ ( p[ "id" ], p[ "new_kind" ] ) for p in pairs ] == [ ( "lib/a.dart::_top", "none" ) ]


def test_the_report_counts_old_blocks_under_min_words( tmp_path ):
    root, old, new = _range( tmp_path, f"class A {{\n  /// {LONG}\n  void a() {{}}\n  /// Short.\n  void b() {{}}\n}}\n", "class A {\n  void a() {}\n  void b() {}\n}\n" )
    _, report = dp.build_pairs( root, old, new )
    assert report[ "below_min_words" ] == 1 and report[ "eligible_old" ] == 1


MULTI_HEAD = "class A extends Bloc<E, S>\n    with M<E, S>,\n        N<E, S> {{\n  {body}\n}}\n"


def test_a_member_of_a_class_whose_header_spans_lines_is_paired( tmp_path ):
    old = MULTI_HEAD.format( body=f"/// {LONG}\n  void _helper() {{}}" )
    new = MULTI_HEAD.format( body="// Kept.\n  void _helper() {}" )
    root, old_rev, new_rev = _range( tmp_path, old, new )
    pairs, report = dp.build_pairs( root, old_rev, new_rev )
    assert [ p[ "id" ] for p in pairs ] == [ "lib/a.dart::A._helper" ]
    assert report[ "dropped_symbol_gone" ] == 0


def test_a_call_inside_a_multi_line_header_class_body_is_not_a_declaration( tmp_path ):
    old = MULTI_HEAD.format( body=f"/// {LONG}\n  void _helper() {{}}" )
    new = MULTI_HEAD.format( body="void run() {\n    await _helper();\n  }" )
    root, old_rev, new_rev = _range( tmp_path, old, new )
    _, report = dp.build_pairs( root, old_rev, new_rev )
    assert report[ "dropped_symbol_gone" ] == 1 and report[ "pairs" ] == 0


def test_a_header_ending_in_a_semicolon_opens_no_body():
    assert dp._header_opens_body( [ "class A = B", "    with C;", "  void x() {", "}" ], 0 ) is False


def test_a_header_followed_by_a_column_zero_line_opens_no_body():
    assert dp._header_opens_body( [ "class A extends B", "void x() {}" ], 0 ) is False
    assert dp._header_opens_body( [ "class A extends B" ], 0 ) is False


def test_two_symbols_of_one_file_share_one_read_and_an_import_and_an_empty_class_are_no_symbols( tmp_path ):
    old = f"class A {{\n  /// {LONG}\n  void _one() {{}}\n\n  /// {LONG}\n  void _two() {{}}\n}}\n"
    new = "import 'x.dart';\n\nclass E {\n}\n\nclass A {\n  void _one() {}\n\n  // Note.\n  void _two() {}\n}\n"
    root, old_rev, new_rev = _range( tmp_path, old, new )
    pairs, report = dp.build_pairs( root, old_rev, new_rev )
    assert sorted( ( p[ "id" ], p[ "new_kind" ] ) for p in pairs ) == [ ( "lib/a.dart::A._one", "none" ), ( "lib/a.dart::A._two", "plain_comment" ) ]
    assert report[ "dropped_symbol_gone" ] == 0
