"""
Make a source-file edit visible to the NEXT import. Opt-in; nothing that does not call this is
affected.

WHY THIS EXISTS (row `d18ce9ef`, measured 2026-08-29). CPython validates a `.pyc` on the source's
**whole-second** mtime plus its **size**. A mutation edit changes neither — `"todo"` -> `"dead"` is
four characters either way, and a scripted loop does the edit and the restore inside one second —
so the interpreter serves the stale bytecode as valid. Measured on `src/cosa/rest/job_state.py`:
source mtime `21:33:22.780`, pyc built `21:33:22.568`; for minutes `grep` said `todo` and `import`
said `dead`.

**The failure points the wrong way.** You restore the file, read it back to confirm, and the
interpreter keeps running the mutant. Mutation testing is how this repo earns its receipts, so a
hazard aimed at it is aimed at the evidence.

**It is CROSS-PROCESS.** This is not `importlib.reload` staleness: a *fresh* pytest reads the stale
`.pyc` off disk. So `sys.modules` bookkeeping alone does not fix it and neither does
`importlib.invalidate_caches()`, which clears finder caches, not pyc validation. The `.pyc` file
itself has to go, or the mtime has to move — this module does both.

SCOPE, stated so nobody reads it as more: this makes YOUR next import honest. It does not change
how the repo compiles, and it cannot help a subprocess that imported before you called it.
Repo-wide options (`compileall --invalidation-mode checked-hash`, which measured self-sustaining at
+3.3%) are priced in `src/rnd/v0.2.1/2026.08.29-stale-pyc-defeats-mutation-testing.md` and are a
separate, still-open decision.

Usage:

    from tests.helpers.pyc_freshness import mutated_source

    with mutated_source( SRC, SRC.read_text().replace( '"todo"', '"dead"' ) ):
        assert subprocess_running_the_suite() != 0     # red, for the right reason
    # restored, and the next import is guaranteed to see the restored bytes
"""

import importlib
import importlib.util
import os
import sys

from contextlib import contextmanager
from pathlib import Path


def bytecode_files_for( source_path ):
    """
    Every cached `.pyc` that could satisfy an import of `source_path`.

    Covers the adjacent `__pycache__/` and, when `sys.pycache_prefix` is set, the mirrored tree
    there — a relocated cache races exactly the same way, measured, so ignoring it would leave the
    hole this module exists to close.

    Requires:
        - source_path names a .py file (it need not exist; a deleted source still has a live .pyc)

    Ensures:
        - returns a list of existing Path objects, possibly empty
    """
    source_path = Path( source_path ).resolve()
    stem        = source_path.stem
    found       = []

    candidates = [ source_path.parent / "__pycache__" ]
    if sys.pycache_prefix:
        # CPython mirrors the ABSOLUTE source path under the prefix, minus the anchor.
        rel = source_path.parent.relative_to( source_path.anchor )
        candidates.append( Path( sys.pycache_prefix ) / rel )

    for cache_dir in candidates:
        if not cache_dir.is_dir(): continue
        found.extend( sorted( cache_dir.glob( f"{stem}.*.pyc" ) ) )

    return found


def refresh_source( source_path ):
    """
    Guarantee the next import of `source_path` reads the bytes now on disk.

    Belt AND suspenders, deliberately, because the two defenses fail differently: deleting the
    `.pyc` handles a cache this process can see, and moving the mtime handles one it cannot (a
    read-only cache dir, a prefix tree we failed to compute, a peer writing concurrently).

    NEITHER IS SUFFICIENT ALONE, and that is measured rather than assumed. Removing the deletion
    and keeping only the mtime bump still fails the `mutated_source` round trip: the restore writes
    the file, the bump lands it on the same whole second the mutation's own `.pyc` recorded, and
    the collision is back. Removing the bump and keeping only the deletion passes every import
    test here — it is the fallback for the caches we cannot delete, not the primary. Receipts:
    mutations H1/H2 in `src/tests/unit/test_pyc_freshness_helper.py`'s history.

    Requires:
        - source_path exists

    Ensures:
        - no stale .pyc for source_path remains in any cache directory we can write
        - the source mtime differs from any whole second a previously-compiled .pyc recorded
        - finder caches are invalidated
    """
    source_path = Path( source_path ).resolve()
    assert source_path.exists(), f"refresh_source: {source_path} does not exist"

    for pyc in bytecode_files_for( source_path ):
        try:
            pyc.unlink()
        except OSError:
            pass                                    # read-only cache dir; the mtime bump below carries it

    # Move the mtime a whole second into the past. FORWARD would be the obvious choice and is the
    # wrong one: a future mtime makes the NEXT compile record a timestamp already in the future, so
    # a later honest edit inside that second is the one that gets swallowed. Backwards cannot
    # collide with a pyc that does not exist yet.
    stat = source_path.stat()
    os.utime( source_path, ( stat.st_atime, stat.st_mtime - 1 ) )

    importlib.invalidate_caches()


def drop_from_sys_modules( dotted_name ):
    """
    Forget an already-imported module and everything under it, so a later import re-reads it.

    Only relevant IN-process; a subprocess has its own `sys.modules` and needs `refresh_source`
    instead. Named separately from `refresh_source` because they solve different halves and a
    caller usually wants one of them, not both.

    Ensures:
        - dotted_name and every submodule of it are absent from sys.modules
        - returns the sorted list of names actually removed
    """
    doomed = [ name for name in sys.modules
               if name == dotted_name or name.startswith( dotted_name + "." ) ]
    for name in doomed:
        del sys.modules[ name ]

    importlib.invalidate_caches()
    return sorted( doomed )


@contextmanager
def mutated_source( source_path, new_text ):
    """
    Replace a source file's text for the duration of the block, then restore it — with the next
    import guaranteed honest on BOTH transitions.

    Both edges matter and only one of them is obvious. The mutation edge is the one people think
    of; the RESTORE edge is the one that bit, because that is where you read the file back, see the
    original, and conclude the mutation is gone while the interpreter still runs it.

    Restoration is in a `finally`, so a failing assertion inside the block still puts the file back.

    Requires:
        - source_path exists and is writable

    Ensures:
        - inside the block, source_path holds new_text and no stale bytecode shadows it
        - on exit, byte-for-byte the original content, likewise unshadowed
        - restoration happens even if the block raises
    """
    source_path = Path( source_path ).resolve()
    original    = source_path.read_bytes()

    try:
        source_path.write_text( new_text, encoding="utf-8" )
        refresh_source( source_path )
        yield source_path
    finally:
        source_path.write_bytes( original )
        refresh_source( source_path )
        assert source_path.read_bytes() == original, (
            f"mutated_source failed to restore {source_path} — the file on disk is NOT what it was. "
            f"Do not trust any result from this block."
        )
