"""
`_is_within` of the Deep Research router: path containment by whole segments.

A bare prefix test lets "/proj/io-secrets" pass as inside "/proj/io".
A pair that shares no common root is outside, and must answer False rather than raise.
"""

import pytest

from cosa.rest.routers.deep_research import _is_within


@pytest.mark.parametrize( "candidate, base, expected", [
    ( "/proj/io",                 "/proj/io", True ),
    ( "/proj/io/reports/a.md",    "/proj/io", True ),
    ( "/proj/io-secrets/a.md",    "/proj/io", False ),
    ( "/proj/other",              "/proj/io", False ),
    ( "relative/path.md",         "/proj/io", False ),
] )
def test_containment_is_by_whole_path_segments( candidate, base, expected ):
    assert _is_within( candidate, base ) is expected
