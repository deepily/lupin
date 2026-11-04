"""
Atomic JSON file helpers shared by the arbiter and worktree ledgers.

The hook library under `lupin_cli/claude_code/hooks/lib` keeps its own copies, because
a hook must not import `cosa`.
"""

import json
import os
import uuid
from pathlib import Path


def write_json_atomic( path, data ) -> None:
    """
    Write `data` to `path` as JSON, replacing the file whole.

    Requires:
        - path is a path-like or string
        - data is JSON-serialisable, or str() of each non-serialisable value is acceptable

    Ensures:
        - the file holds exactly `data`
        - the parent directory is created if absent
        - the write is atomic: a temp file named with a per-writer pid and uuid is
          written, then renamed over the target, so concurrent writers never share a
          temp path and a reader sees the old file or the new one

    Raises:
        - OSError if the target directory cannot be created or written; it is never swallowed
    """
    path = Path( path )
    path.parent.mkdir( parents=True, exist_ok=True )
    tmp  = path.parent / f"{path.name}.{os.getpid()}-{uuid.uuid4().hex}.tmp"
    with open( tmp, "w" ) as f:
        json.dump( data, f, default=str )
    tmp.replace( path )


def load_json_section( path, key ) -> dict:
    """
    Read one top-level dict section from a JSON file.

    Requires:
        - path is a path-like or string
        - key is the name of the section

    Ensures:
        - returns the dict stored under `key`
        - returns {} when the file is absent, unreadable, not valid JSON, not a JSON
          object, or holds a non-dict under `key`; it never raises
    """
    try:
        with open( path, "r", encoding="utf-8" ) as fh:
            data = json.load( fh )
        section = data.get( key ) if isinstance( data, dict ) else None
        return section if isinstance( section, dict ) else {}
    except ( OSError, ValueError ):
        return {}
