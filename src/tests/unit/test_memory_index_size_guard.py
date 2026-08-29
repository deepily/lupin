"""
Guard: the auto-loaded memory index MEMORY.md must stay under the reader's byte
limit, or its tail pointers are silently truncated on every session load.

Context (row 1417cdbb, Rick's ruling 2026-08-16): MEMORY.md had grown to 25,662
bytes against a 24,986-byte read limit, so tail pointers — all auth/infra
references — were invisible on every load, and a PostToolUse write-error had
frozen the index. The fix split it into per-section MEMORY-<section>.md hub files,
leaving MEMORY.md a short index. The memory directory is NOT git-tracked, so the
split leaves no commit anyone can inspect — this repo test is the only durable
evidence the fix holds and does not silently regress.

Venue: :7999-eligible — read-only, no state mutation, sub-second.
"""

import os
import re
import unittest
from pathlib import Path

# The Claude Code loader silently truncates MEMORY.md past this many bytes,
# dropping the tail on every read. Keep the index strictly under it.
READ_LIMIT_BYTES = 24_986


def _memory_index_path():
    """Resolve this project's auto-loaded memory index.

    The per-project memory directory name is the project root with '/' and '.'
    both mangled to '-' (Claude Code convention), under ~/.claude/projects/.
    Returns None when LUPIN_ROOT is unset so the caller can skip visibly.
    """
    root = os.environ.get( "LUPIN_ROOT" )
    if root is None:
        return None
    mangled = re.sub( r"[/.]", "-", root.rstrip( "/" ) )
    return Path.home() / ".claude" / "projects" / mangled / "memory" / "MEMORY.md"


class TestMemoryIndexSizeGuard( unittest.TestCase ):

    def test_memory_index_stays_under_the_read_limit( self ):
        path = _memory_index_path()
        if path is None or not path.exists():
            # The guard is meaningful only where the memory actually lives; on a
            # machine without it, skip VISIBLY rather than pass silently.
            self.skipTest( f"memory index not present on this machine: {path}" )

        size = path.stat().st_size
        self.assertLess(
            size, READ_LIMIT_BYTES,
            f"MEMORY.md is {size} bytes, at or over the {READ_LIMIT_BYTES}-byte "
            f"read limit — tail pointers are being silently dropped on every load. "
            f"Move a section's pointers into a new MEMORY-<section>.md hub file "
            f"(row 1417cdbb) instead of growing the index."
        )


if __name__ == "__main__":
    unittest.main()
