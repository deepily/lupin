#!/usr/bin/env python3
"""
Idempotent, fail-loud replacement for the previous `sed -i` patch on
pytest-playwright-visual-snapshot's __init__.py.

Why this exists:
  pytest-playwright-visual-snapshot transitively pulls structlog_config,
  which requires starlette >=0.49.1, which conflicts with the FastAPI
  pin's starlette <0.47.0. The package is installed with --no-deps, then
  its __init__.py needs the bare `from structlog_config import ...` line
  wrapped in a try/except so the package loads when structlog_config is
  absent (it is never imported at runtime by the parts we use).

Why a Python script instead of a unified-diff `.patch`:
  A unified diff requires stable surrounding-line context, which drifts
  with every upstream release. This script:
    - locates __init__.py by package metadata (no path hardcoding)
    - is idempotent (no-op if already patched)
    - fails loudly with a specific message when upstream layout drifts
    - smoke-tests the post-patch import so the build aborts here rather
      than at e2e-test time
"""
import importlib
import importlib.util
import sys
from pathlib import Path

PKG       = "pytest_playwright_visual_snapshot"
ORIGINAL  = "from structlog_config import configure_logger"
REPLACEMENT = (
    "try:\n"
    "    from structlog_config import configure_logger\n"
    "except ImportError:\n"
    "    import logging; configure_logger = lambda: logging.getLogger(__name__)"
)
ALREADY_PATCHED_MARKER = "configure_logger = lambda"


def main() -> int:
    spec = importlib.util.find_spec( PKG )
    if spec is None or spec.origin is None:
        print( f"FAIL: package '{PKG}' not found in this environment.", file=sys.stderr )
        return 1

    init_py = Path( spec.origin )
    text    = init_py.read_text( encoding="utf-8" )

    if ALREADY_PATCHED_MARKER in text:
        print( f"Already patched: {init_py}", file=sys.stderr )
    else:
        if ORIGINAL not in text:
            print(
                f"FAIL: expected line not found in {init_py}\n"
                f"  expected: {ORIGINAL!r}\n"
                f"Upstream layout has drifted; inspect and update this script.",
                file=sys.stderr,
            )
            return 1

        count = text.count( ORIGINAL )
        if count != 1:
            print(
                f"FAIL: expected exactly 1 occurrence of {ORIGINAL!r}, "
                f"found {count} in {init_py}.",
                file=sys.stderr,
            )
            return 1

        init_py.write_text( text.replace( ORIGINAL, REPLACEMENT, 1 ), encoding="utf-8" )
        print( f"Patched: {init_py}", file=sys.stderr )

    # Smoke test — import after the patch lands.
    try:
        mod = importlib.import_module( PKG )
    except Exception as exc:
        print( f"FAIL: post-patch import of '{PKG}' raised {type(exc).__name__}: {exc}", file=sys.stderr )
        return 1

    version = getattr( mod, "__version__", "?" )
    print( f"Smoke test passed: '{PKG}' imports cleanly (version {version}).", file=sys.stderr )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
