"""
Top-level pytest configuration - bootstraps Python path for all tests.

This file runs BEFORE cosa is importable, so it must use manual
path manipulation. All other test files can then import cosa directly.
"""
import sys
import os

# Bootstrap using LUPIN_ROOT environment variable
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running tests:\n"
        "  export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin\n"
        "  pytest src/tests/"
    )

# Add src to Python path (manual - cosa not yet importable)
src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable - other test files can just: import cosa.utils.util as du
