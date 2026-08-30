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

🔨 THE REPO-WIDE DECISION IS NO LONGER OPEN — Rick ruled YES on 2026-08-30 (row `866f43ce`), so
checked-hash invalidation is the tree's remedy and this helper is the migration path rather than the
answer. Convert with `src/scripts/migrate-pyc-to-checked-hash.sh` (`--verify` to check without
changing anything). On a CONVERTED tree the hazard this module works around is gone by construction,
and calling it is harmless but unnecessary; it still earns its place in a tree you have not converted
and for a file created after the last conversion, since a brand-new source file gets a TIMESTAMP pyc.

⚠️ TWO CORRECTIONS TO WHAT THIS DOCSTRING USED TO SAY, both measured 2026-08-30:
  · "+3.3%" was an ANALYTIC figure and did NOT survive measurement. Across 8 interleaved A/B pairs
    on the real unit tier's import-dominated collection phase, timestamp and checked-hash medians
    were ~15.2s against ~15.1s — the difference is below this measurement's noise floor. See
    `866f43ce` for the numbers and the conditions; quote the row, not the 3.3%.
  · "self-sustaining" is HALF right, and the wrong half is the one that bites. An existing
    checked-hash pyc does stay checked-hash when CPython regenerates it — but a brand-new source
    file gets a timestamp pyc, because there is no prior pyc to inherit a mode from. The migration
    has to be re-run after Python files are added.

Usage:

    from tests.helpers.pyc_freshness import mutated_source

    with mutated_source( SRC, SRC.read_text().replace( '"todo"', '"dead"' ) ):
        assert subprocess_running_the_suite() != 0     # red, for the right reason
    # restored, and the next import is guaranteed to see the restored bytes
"""

import importlib
import importlib.util
import marshal
import os
import struct
import sys

from contextlib import contextmanager
from pathlib import Path



class StalePycError( RuntimeError ):
    """
    Raised when cached bytecode that could shadow a source edit cannot be removed.

    A LOUD failure is the whole point. The hazard this module exists for is one that reports
    success — you restore the file, read it back, and the interpreter keeps running the mutant. A
    helper that quietly half-worked would reproduce exactly that, one layer up, and the caller
    would take the green as proof.
    """

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

    survivors = []
    for pyc in bytecode_files_for( source_path ):
        try:
            pyc.unlink()
        except OSError as exc:
            survivors.append( ( pyc, exc ) )

    if survivors:
        detail = "\n".join( f"  {pyc}  ({exc.__class__.__name__}: {exc})" for pyc, exc in survivors )
        raise StalePycError(
            f"could NOT delete cached bytecode for {source_path}:\n{detail}\n\n"
            f"This is refused rather than warned about. The mtime bump is a FALLBACK for caches we "
            f"cannot see, not a substitute for the delete — measured (mutation H1): with the delete "
            f"removed, the mutate/restore round trip still reads stale bytecode, because the restore "
            f"lands on the same whole second the mutation's own .pyc recorded.\n"
            f"Proceeding would hand you a result that looks clean and is not.\n\n"
            f"CLEAR THE CACHE AND RE-RUN:\n"
            f"  find src -name '__pycache__' -type d -exec rm -rf {{}} +"
        )

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



# ---------------------------------------------------------------------------
# Detector — find bytecode that is SHADOWING its own source right now
# ---------------------------------------------------------------------------

def _shadow_verdict( source_path ):
    """
    Is `source_path` currently shadowed by a `.pyc` that CPython will accept as valid?

    Three states, kept distinct on purpose — collapsing "no cached bytecode" into "fine" is how a
    scan that examined nothing reports a clean bill of health:
        True   -> a timestamp pyc claims validity for this source and holds DIFFERENT code
        False  -> checked, and it is fine (no shadow)
        None   -> not assessable (no pyc cached, hash-based pyc, or the source will not compile)

    Hash-based pycs return None rather than False: CPython validates those itself, so this detector
    has nothing to add and should not take credit for them.

    ⚠️ THE COMPARISON IS BY CODE OBJECT, NOT BY MARSHAL BYTES, and that is not a style choice.
    Measured 2026-08-29: comparing `marshal.dumps( marshal.loads( stored ) )` against a fresh
    `marshal.dumps` reported **1093 shadowing pycs** across `src/cosa` where the true count was
    **zero**. `marshal` is not canonical — it emits back-references, so re-dumping objects that are
    equal produces different bytes. Code objects compare by value; marshal bytes do not.
    """
    cache = Path( importlib.util.cache_from_source( str( source_path ) ) )
    if not cache.exists(): return None

    raw = cache.read_bytes()
    if len( raw ) < 16: return None

    flags = struct.unpack( "<I", raw[ 4:8 ] )[ 0 ]
    if flags & 1: return None                            # hash-based; CPython checks it itself

    recorded_mtime, recorded_size = struct.unpack( "<II", raw[ 8:16 ] )
    stat = source_path.stat()
    if recorded_mtime != int( stat.st_mtime ) or recorded_size != stat.st_size:
        return False                                     # CPython will invalidate it normally

    try:
        stored = marshal.loads( raw[ 16: ] )
        fresh  = compile( source_path.read_bytes(), str( source_path ), "exec", dont_inherit=True )
    except ( SyntaxError, ValueError, EOFError, TypeError ):
        return None

    return stored != fresh


def find_shadowing_bytecode( roots ):
    """
    Scan for sources whose cached bytecode differs from the file on disk while still passing
    CPython's validity check — i.e. code that WILL be run in place of what is written.

    Requires:
        - roots is a non-empty iterable of existing directories

    Ensures:
        - returns ( shadowed, examined ): the list of offending source Paths, and the count of
          sources that were actually ASSESSABLE (a cached, timestamp-based pyc present)
        - raises if roots is empty or names a missing directory

    `examined` is returned, not logged, because it is the only thing separating "clean" from
    "looked at nothing". A caller that ignores it can assert a green over an empty scan.
    """
    roots = [ Path( r ) for r in roots ]
    assert roots, "find_shadowing_bytecode: no roots given — an empty scan reports clean"
    for root in roots:
        assert root.is_dir(), f"find_shadowing_bytecode: root does not exist: {root}"

    shadowed, examined = [], 0
    for root in roots:
        for source in sorted( root.rglob( "*.py" ) ):
            if ".venv" in source.parts: continue
            verdict = _shadow_verdict( source )
            if verdict is None: continue
            examined += 1
            if verdict: shadowed.append( source )

    return shadowed, examined


def describe_shadowing( shadowed ):
    """
    The failure text. Separate from the assertion so the message itself can be tested — a remedy
    that is only reachable by making a test fail is a remedy nobody checks.

    Ensures:
        - names every offending file
        - states the cache clear as the remedy, as a runnable command
    """
    listing = "\n".join( f"  {path}" for path in shadowed )
    return (
        f"{len( shadowed )} source file(s) are being SHADOWED by stale cached bytecode. Python is "
        f"running code that is NOT what these files contain:\n{listing}\n\n"
        f"CPython validates a .pyc on the source's whole-second mtime PLUS its size. An edit that "
        f"changes neither — which every same-size mutation does, inside one second — is invisible, "
        f"so the stale bytecode is served as valid (row d18ce9ef).\n"
        f"Nothing you read from these files right now describes what will execute. Treat any test "
        f"result involving them as void until this is cleared.\n\n"
        f"REMEDY — clear the cached bytecode and re-run:\n"
        f"  find src -name '__pycache__' -type d -exec rm -rf {{}} +\n\n"
        f"To avoid causing this from a test that edits sources, use the mutate_source fixture in "
        f"this module rather than writing the file directly."
    )

# ---------------------------------------------------------------------------
# Pytest fixture — opt in by IMPORTING it into your test module:
#
#     from tests.helpers.pyc_freshness import mutate_source     # noqa: F401
#
#     def test_something( mutate_source ):
#         mutate_source( SRC, SRC.read_text().replace( '"todo"', '"dead"' ) )
#         ...                                    # restored automatically at teardown
#
# Deliberately NOT registered in any conftest.py: a fixture that arrives without being asked for
# is not opt-in, and this one edits files on disk. Importing it by name is the whole registration.
# ---------------------------------------------------------------------------

import pytest


@pytest.fixture
def mutate_source():
    """
    Mutate one or more source files for the length of a test; restore every one at teardown.

    Restoration runs even when the test fails, and it runs for EVERY file touched even if an
    earlier restore raises — a partial restore is how one red test leaves production source
    mutated for every seat sharing the checkout.

    LOUD BY CONSTRUCTION, which is the point rather than a nicety. Two ways this refuses instead of
    warning:
      - a `.pyc` it cannot delete raises `StalePycError` naming the cache clear (see
        `refresh_source`); a mutation probe running against shadowed bytecode produces a result
        that looks clean and is not;
      - a file whose restored bytes do not match what was read at setup raises at teardown, so a
        corrupted tree is reported by the test that corrupted it rather than by whoever runs next.

    Ensures:
        - returns a callable ( path, new_text ) -> Path
        - every mutated path holds its original bytes after teardown, verified
        - teardown attempts every file before re-raising anything
    """
    originals = {}

    def _mutate( source_path, new_text ):
        source_path = Path( source_path ).resolve()
        if source_path not in originals:
            originals[ source_path ] = source_path.read_bytes()
        source_path.write_text( new_text, encoding="utf-8" )
        refresh_source( source_path )
        return source_path

    yield _mutate

    failures = []
    for source_path, original in originals.items():
        try:
            source_path.write_bytes( original )
            refresh_source( source_path )
            if source_path.read_bytes() != original:
                failures.append( f"{source_path}: restored bytes do not match the original" )
        except Exception as exc:                    # keep going; every other file still needs restoring
            failures.append( f"{source_path}: {exc.__class__.__name__}: {exc}" )

    if failures:
        raise StalePycError(
            "mutate_source could NOT return the tree to its original state:\n  "
            + "\n  ".join( failures )
            + "\n\nDo not trust this test's result, and check the files above before running "
              "anything else — other seats share this checkout.\n"
              "CLEAR THE CACHE AND RE-RUN:\n"
              "  find src -name '__pycache__' -type d -exec rm -rf {} +"
        )
