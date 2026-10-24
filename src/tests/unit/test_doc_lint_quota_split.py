"""
The shared largest-remainder split, pinned to the seeder's old output.
"""
from cosa.repo.doc_lint import labelled_set_seeder as seeder
from cosa.repo.doc_lint import quota_split

# Captured by running the seeder's own quotas at d0bd4f604, before the function moved.
GOLDEN = [
    ( 14,  { "S": 0.3, "M": 0.4, "L": 0.3 },                              { "S": 4,   "M": 6,   "L": 4   } ),
    ( 401, { "a": 1 / 3, "b": 1 / 3, "c": 1 / 3 },                        { "a": 134, "b": 134, "c": 133 } ),
    ( 7,   { "x": 0.5, "y": 0.25, "z": 0.25 },                            { "x": 3,   "y": 2,   "z": 2   } ),
]


def test_quotas_equal_the_seeders_old_output_on_literal_cases():
    for total, mix, expected in GOLDEN:
        assert quota_split.quotas( total, mix ) == expected


def test_the_seeder_imports_the_shared_function_back():
    assert seeder.quotas is quota_split.quotas


def test_parts_sum_to_the_total_and_a_zero_total_gives_zeros():
    assert sum( quota_split.quotas( 10, { "a": 0.3, "b": 0.7 } ).values() ) == 10
    assert quota_split.quotas( 0, { "a": 0.5, "b": 0.5 } ) == { "a": 0, "b": 0 }


def test_a_tie_between_equal_remainders_goes_to_the_smaller_key():
    assert quota_split.quotas( 1, { "b": 0.5, "a": 0.5 } ) == { "a": 1, "b": 0 }
