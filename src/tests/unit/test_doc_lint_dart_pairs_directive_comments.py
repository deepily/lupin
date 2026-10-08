"""
dart_pairs does not read a tool directive or a task marker as a member's new doc text.

Store id ee9a69e1-52bb-4b67-9e27-ae127dda7920. A `// ignore: unused_element` or `// TODO: remove` line
above a member whose `///` block was removed was returned as that member's new text. The claim judge
would then judge a lint directive as the rewritten docstring.

The rule is a shape, not a word list. A line is a directive or marker, not prose about the member, in three cases.
It is a lowercase word glued to a colon. It is a `dart format` switch. It is a capitals word and a colon,
with an optional owner in parentheses.

Seams driven for real: plain_comments over Dart text, and build_pairs over a two-commit git repository.
"""

import pytest

from cosa.repo.doc_lint import dart_pairs as dp
from test_doc_lint_dart_pairs_plain_comment import LONG, OLD, _range


def _member( *comment_lines ):
    return "class A {\n" + "".join( f"  // {line}\n" for line in comment_lines ) + "  void _h() {}\n}\n"


@pytest.mark.parametrize( "line", [ "coverage:ignore-line", "dart format off", "HACK(rick): remove", "expected_lint: avoid_print", "ignore_for_file: type=lint", "dart format on", "TODO" ] )
def test_a_directive_or_marker_alone_is_no_comment( line ):
    assert dp.plain_comments( _member( line ) ) == {}


def test_prose_before_a_directive_keeps_the_prose_and_drops_the_directive():
    assert dp.plain_comments( _member( "Helper for the pane.", "ignore: unused_element" ) ) == { "A._h": "Helper for the pane." }


def test_a_task_marker_ends_the_text_with_its_continuation_lines():
    assert dp.plain_comments( _member( "Helper for the pane.", "TODO(rick): later,", "once the repo lands." ) ) == { "A._h": "Helper for the pane." }


@pytest.mark.parametrize( "line", [ "Optional and used only for the roster.", "Why: avoids a rebuild.", "HTTP retries stay bounded.", "http://example.com/spec explains it.", "A: the first case." ] )
def test_control_prose_is_still_read_as_the_new_text( line ):
    assert dp.plain_comments( _member( line ) ) == { "A._h": line }


def test_a_member_left_with_only_a_directive_is_paired_with_an_empty_text_not_the_directive( tmp_path ):
    root, old, new = _range( tmp_path, OLD, "class A {\n  // ignore: unused_element\n  void _helper() {}\n}\n" )
    pairs, report = dp.build_pairs( root, old, new )
    assert [ ( p[ "old" ], p[ "new" ], p[ "new_kind" ] ) for p in pairs ] == [ ( LONG, "", "none" ) ]
    assert report[ "paired_no_comment" ] == 1 and report[ "paired_plain_comment" ] == 0


@pytest.mark.parametrize( "line", [ "returns: the cached value, or null.", "note: only used by the roster.", "default: 5 retries", "used by: the router", "See also: foo" ] )
def test_prose_with_words_after_a_lowercase_colon_is_kept( line ):
    assert dp.plain_comments( _member( line ) ) == { "A._h": line }


@pytest.mark.parametrize( "line", [ "a: b", "HTTP: retries stay bounded.", "NOTE: kept for the roster.", "WARNING: not thread safe", "OK" ] )
def test_a_line_that_has_the_shape_of_a_directive_or_marker_is_dropped_even_when_it_is_prose( line ):
    assert dp.plain_comments( _member( line ) ) == {}


def test_a_wrapped_line_that_is_only_an_acronym_ends_the_text_and_drops_its_continuation():
    assert dp.plain_comments( _member( "Opens the pane.", "API", "calls the server" ) ) == { "A._h": "Opens the pane." }
