"""Unit tests for the shared agreement statistics."""
import pytest

from cosa.utils import agreement_stats as st


def test_mcnemar_exact_hand_values():
    assert st.mcnemar_exact( 0, 0 ) == 1.0
    assert st.mcnemar_exact( 5, 5 ) == 1.0
    assert st.mcnemar_exact( 0, 6 ) == pytest.approx( 2 / 64 )
    assert st.mcnemar_exact( 1, 9 ) == pytest.approx( 2 * 11 / 1024 )
    assert st.mcnemar_exact( 9, 1 ) == st.mcnemar_exact( 1, 9 )


def test_percentile_interpolates_and_handles_edges():
    assert st.percentile( [], 0.5 ) is None
    assert st.percentile( [ 10.0, 0.0 ], 0.5 ) == 5.0
    assert st.percentile( [ 1.0, 2.0, 3.0 ], 0.0 ) == 1.0
    assert st.percentile( [ 1.0, 2.0, 3.0 ], 1.0 ) == 3.0
    assert st.percentile( [ 4.0 ], 0.9 ) == 4.0
    assert st.percentile( [ 1.0, 2.0, 3.0, 4.0 ], 0.25 ) == pytest.approx( 1.75 )
