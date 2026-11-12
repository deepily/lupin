"""
The comma-list reader: strip each entry, drop blanks, optionally lowercase.
"""
import pytest

from cosa.utils.csv_text import split_csv


def test_entries_come_back_in_order_stripped():
    assert split_csv( " a , b,c " ) == [ "a", "b", "c" ]


def test_blank_entries_are_dropped():
    assert split_csv( "a,, ,b," ) == [ "a", "b" ]


@pytest.mark.parametrize( "empty", [ None, "", "  ", ",,," ] )
def test_nothing_gives_an_empty_list( empty ):
    assert split_csv( empty ) == []


def test_case_is_kept_unless_asked_to_lower():
    assert split_csv( "Mr Radio, MARIA" ) == [ "Mr Radio", "MARIA" ]
    assert split_csv( "Mr Radio, MARIA", lower=True ) == [ "mr radio", "maria" ]


def test_inner_spaces_are_kept():
    assert split_csv( "mr radio,  two words " ) == [ "mr radio", "two words" ]
