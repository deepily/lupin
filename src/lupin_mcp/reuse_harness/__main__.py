"""Entry point: python -m lupin_mcp.reuse_harness."""
import sys

from lupin_mcp.reuse_harness import driver

if __name__ == "__main__":
    sys.exit( driver.main( sys.argv[ 1: ] ) )
