"""
Fixtures for the include_tests tests: a lupin tree with one test helper.
"""
import pytest

from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_tools import resp

HELPER_ID = "tests.unit.support.helper_for_tests"
HELPER    = 'def helper_for_tests( x ):\n    """Help a test read an RSS feed."""\n    return x\n'


class AllReuse:
    """Answer reuse for every candidate, so each entry asked lands in the shortlist."""

    def __init__( self ): self.seen = []

    def post( self, body ):
        self.seen.append( body ); return resp( 0.95, 0.03, 0.02 )


@pytest.fixture
def tests_env( tmp_path ):
    """Return ( root, data, out, helper_path ) for a lupin tree with src/tests/unit/support.py."""
    root = make_lupin_repo( tmp_path )
    unit = root / "src" / "tests" / "unit"
    unit.mkdir( parents=True )
    ( unit / "support.py" ).write_text( HELPER, encoding="utf-8" )
    return root, tmp_path / "data", tmp_path / "out", unit / "support.py"


def ctx_of( env, transport, **kw ):
    """Return a ReuseContext over the fixture tree."""
    return rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=transport, **kw )
