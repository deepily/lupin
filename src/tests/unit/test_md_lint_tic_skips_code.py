"""
The markdown tic rule skips inline code spans and fenced code, and still refuses the same word in prose.

Row 07d6d4c7: the literal label `genuinely-new` could not be quoted in a page, because rule 5 read
inside the backticks and markdown has no waiver.
"""

import pytest

from cosa.repo.doc_lint import md_lint
from cosa.repo.doc_lint.text_rules import rhetoric_findings

PATH = "src/docs/example.md"


def _tics( source ):
    return [ f for f in md_lint.lint_source( PATH, source ) if f.rule == "tic" ]


def test_a_tic_word_inside_an_inline_code_span_passes():
    assert _tics( "The third label is `genuinely-new` in the review table.\n" ) == []


def test_the_same_word_in_plain_prose_is_still_refused():
    found = _tics( "The third label is genuinely new in the review table.\n" )
    assert [ ( f.line, f.message ) for f in found ] == [ ( 1, "tic phrase 'genuinely'" ) ]


def test_a_tic_word_inside_a_fenced_block_passes():
    assert _tics( "Intro line.\n\n```text\ngenuinely-new\n```\n" ) == []


def test_code_span_and_prose_on_one_line_report_only_the_prose_hit():
    found = _tics( "Label `genuinely-new` is genuinely useful.\n" )
    assert [ f.line for f in found ] == [ 1 ] and len( found ) == 1


def test_an_unclosed_backtick_does_not_hide_the_prose_after_it():
    assert len( _tics( "A stray ` tick then genuinely wrong.\n" ) ) == 1


def test_the_line_number_survives_code_above():
    found = _tics( "```\nx\n```\n\n`ok`\n\nGenuinely late.\n" )
    assert [ f.line for f in found ] == [ 7 ]


def test_a_docstring_reading_keeps_refusing_inside_backticks():
    found = rhetoric_findings( "Uses `genuinely` here.", "a.py", 1 )
    assert len( found ) == 1


def test_a_tic_word_inside_a_double_backtick_span_passes():
    assert _tics( "The third label is ``genuinely-new`` in the review table.\n" ) == []


def test_a_double_backtick_span_holding_a_backtick_passes():
    assert _tics( "Quote ``a ` genuinely b`` as a label.\n" ) == []


def test_a_span_between_two_halves_of_a_word_does_not_join_them():
    assert len( _tics( "The word genu`x`inely is split.\n" ) ) == 0


def test_prose_after_a_double_backtick_span_is_still_refused():
    found = _tics( "Label ``genuinely-new`` is genuinely useful.\n" )
    assert [ f.line for f in found ] == [ 1 ] and len( found ) == 1
