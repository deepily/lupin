"""
dart_pairs names every comment line it drops, in the pair row and in the report.

Store id ee9a69e1-52bb-4b67-9e27-ae127dda7920. The directive rule can drop a prose line by mistake, for
example `// note: retries twice`. Dropping it silently would hide a real doc change from the judge, the
defect of the earlier pairing fix. So each dropped line is listed in the pair with its reason, and the report counts them.

Seams driven for real: build_pairs over a two-commit git repository.
"""

from cosa.repo.doc_lint import dart_pairs as dp
from test_doc_lint_dart_pairs_plain_comment import LONG, OLD, _range


def _new( *comment_lines ):
    return "class A {\n" + "".join( f"  // {line}\n" for line in comment_lines ) + "  void _helper() {}\n}\n"


def _pairs( tmp_path, new_source ):
    root, old, new = _range( tmp_path, OLD, new_source )
    return dp.build_pairs( root, old, new )


def test_a_dropped_directive_is_listed_in_the_pair_and_counted_in_the_report( tmp_path ):
    pairs, report = _pairs( tmp_path, _new( "ignore: unused_element" ) )
    assert pairs[ 0 ][ "new_kind" ] == "none" and pairs[ 0 ][ "new" ] == ""
    assert pairs[ 0 ][ "new_dropped" ] == [ { "line": "ignore: unused_element", "reason": "directive" } ]
    assert report[ "dropped_comment_lines" ] == { "directive": 1, "marker": 0, "after_marker": 0 } and report[ "pairs_with_dropped_comment_lines" ] == 1


def test_a_prose_line_the_rule_drops_by_mistake_is_visible_not_silent( tmp_path ):
    pairs, report = _pairs( tmp_path, _new( "Helper for the pane.", "note: retries twice" ) )
    assert pairs[ 0 ][ "new" ] == "Helper for the pane." and pairs[ 0 ][ "new_kind" ] == "plain_comment"
    assert pairs[ 0 ][ "new_dropped" ] == [ { "line": "note: retries twice", "reason": "directive" } ]
    assert report[ "dropped_comment_lines" ][ "directive" ] == 1


def test_a_marker_and_its_continuation_lines_are_named_apart( tmp_path ):
    pairs, report = _pairs( tmp_path, _new( "Helper.", "TODO(rick): later,", "once Y lands." ) )
    assert pairs[ 0 ][ "new_dropped" ] == [ { "line": "TODO(rick): later,", "reason": "marker" }, { "line": "once Y lands.", "reason": "after_marker" } ]
    assert report[ "dropped_comment_lines" ] == { "directive": 0, "marker": 1, "after_marker": 1 }


def test_control_a_pair_that_lost_nothing_has_an_empty_list_and_a_zero_count( tmp_path ):
    pairs, report = _pairs( tmp_path, _new( "Helper for the pane." ) )
    assert pairs[ 0 ][ "new_dropped" ] == [] and report[ "dropped_comment_lines" ] == { "directive": 0, "marker": 0, "after_marker": 0 }
    assert report[ "pairs_with_dropped_comment_lines" ] == 0


def test_a_pair_with_a_doc_block_has_an_empty_list( tmp_path ):
    pairs, _ = _pairs( tmp_path, f"class A {{\n  /// {LONG} more words here.\n  void _helper() {{}}\n}}\n" )
    assert pairs[ 0 ][ "new_kind" ] == "doc" and pairs[ 0 ][ "new_dropped" ] == []
