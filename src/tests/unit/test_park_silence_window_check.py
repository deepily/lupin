"""
The park-expiry integration test names a used-up window instead of blaming the park.

The test parks a row with a chase four seconds ahead and reads the owed count straight
after. If those two calls took the whole window, the park had expired by the time of the
read and the count of 1 is correct. The helper tells that case from a park that bought no
silence at all. Pure logic: no server, no clock.
"""

import pytest

from tests.helpers.park_window import check_park_silence

WINDOW = 4


def test_a_count_of_zero_passes_however_long_it_took():
    check_park_silence( count=0, elapsed=0.2, window=WINDOW )
    check_park_silence( count=0, elapsed=9.0, window=WINDOW )


def test_a_count_of_one_inside_the_window_is_a_park_that_bought_no_silence():
    with pytest.raises( AssertionError ) as e:
        check_park_silence( count=1, elapsed=1.5, window=WINDOW )
    assert "park bought NO silence" in str( e.value )
    assert "WINDOW USED UP" not in str( e.value )


def test_a_count_of_one_after_the_window_names_the_used_up_window():
    with pytest.raises( AssertionError ) as e:
        check_park_silence( count=1, elapsed=5.2, window=WINDOW )
    assert "WINDOW USED UP" in str( e.value )
    assert "park bought NO silence" not in str( e.value )


def test_the_boundary_counts_as_used_up():
    with pytest.raises( AssertionError ) as e:
        check_park_silence( count=1, elapsed=float( WINDOW ), window=WINDOW )
    assert "WINDOW USED UP" in str( e.value )


def test_just_under_the_boundary_is_still_a_silence_failure():
    with pytest.raises( AssertionError ) as e:
        check_park_silence( count=1, elapsed=WINDOW - 0.01, window=WINDOW )
    assert "park bought NO silence" in str( e.value )


def test_the_message_carries_the_elapsed_time_and_the_window():
    with pytest.raises( AssertionError ) as e:
        check_park_silence( count=1, elapsed=5.2, window=WINDOW )
    assert "5.2" in str( e.value )
    assert "4" in str( e.value )
