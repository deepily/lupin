"""
Tests for cosa.utils.flag_text.is_flag_on, the one reading of a hand-typed on/off setting.

Each test pins one behaviour. The three callers (the librarian tick switch, the asynchronous
promotion switch and the coverage escape hatch) are checked against the helper by value.
"""

import pytest

from cosa.utils.flag_text import FLAG_ON_WORDS, is_flag_on


def test_the_on_words_are_exactly_these_four():
    assert FLAG_ON_WORDS == ( "true", "1", "yes", "on" )


@pytest.mark.parametrize( "word", [ "true", "1", "yes", "on" ] )
def test_each_on_word_is_on( word ):
    assert is_flag_on( word ) is True


@pytest.mark.parametrize( "word", [ "TRUE", "Yes", "ON", "tRuE" ] )
def test_case_is_ignored( word ):
    assert is_flag_on( word ) is True


@pytest.mark.parametrize( "raw", [ "  true", "yes  ", "\ton\n", " 1 " ] )
def test_surrounding_blanks_are_ignored( raw ):
    assert is_flag_on( raw ) is True


@pytest.mark.parametrize( "raw", [ "false", "0", "no", "off", "", "   ", "banana", "truee", "y", "enabled" ] )
def test_every_other_text_is_off( raw ):
    assert is_flag_on( raw ) is False


def test_none_is_off():
    assert is_flag_on( None ) is False


def test_a_non_string_reads_through_its_text():
    assert ( is_flag_on( True ), is_flag_on( False ), is_flag_on( 1 ), is_flag_on( 0 ) ) == ( True, False, True, False )


def test_inner_blanks_are_not_ignored():
    assert is_flag_on( "tr ue" ) is False


def test_escape_hatch_engaged_reads_through_the_helper():
    from cosa.utils.coverage_contention import ESCAPE_HATCH_ENV, escape_hatch_engaged
    assert escape_hatch_engaged( { ESCAPE_HATCH_ENV: " On " } ) is True
    assert escape_hatch_engaged( { ESCAPE_HATCH_ENV: "0" } ) is False
    assert escape_hatch_engaged( {} ) is False


def test_librarian_switch_reads_through_the_helper():
    from cosa.repo.symindex.librarian_tick import read_enabled
    assert read_enabled( reader=lambda key: " YES " ) is True
    assert read_enabled( reader=lambda key: "0" ) is False
    assert read_enabled( reader=lambda key: None ) is False


def test_asynchronous_switch_reads_through_the_helper( monkeypatch ):
    from cosa.rest import task_promotion_gate as gate
    monkeypatch.setattr( gate, "_ini_value", lambda key, return_type, fallback: " On " )
    assert gate.get_asynchronous_enabled() is True
    monkeypatch.setattr( gate, "_ini_value", lambda key, return_type, fallback: "nope" )
    assert gate.get_asynchronous_enabled() is False
    monkeypatch.setattr( gate, "_ini_value", lambda key, return_type, fallback: None )
    assert gate.get_asynchronous_enabled() is False
