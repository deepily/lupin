"""
The mechanical control for the checked-hash rule (row 866f43ce; decision f313fc2d).

WHY THIS EXISTS RATHER THAN MORE DOCUMENTATION. The checked-hash mandate is written down,
prominently, in CLAUDE.md and in two scripts' header comments — and it was broken three times
in one afternoon by people who had read it, two of whom wrote parts of it. That is the easy
half of the argument. The hard half is that the tree DRIFTS WITH NOBODY BREAKING ANY RULE: a
correctly converted tree grew a new timestamp pyc about 2.5 hours after a clean conversion,
through ordinary first-time imports. No purge discipline addresses that, because no purge
happened.

THE MECHANISM, read out of CPython 3.13.7's own import machinery rather than recalled
(`importlib/_bootstrap_external.py`, SourceLoader.get_code ~line 1163):

    if hash_based:  data = _code_to_hash_pyc( code, source_hash, check_source )
    else:           data = _code_to_timestamp_pyc( code, source_mtime, len( source_bytes ) )

`hash_based` is derived from reading an EXISTING pyc. When no pyc exists there is nothing to
inherit a mode from, so the branch falls to timestamp — CPython's default. That is not a bug
and there is no environment variable or flag that changes it: `-B` /
PYTHONDONTWRITEBYTECODE suppress *writing* a pyc, never the MODE of one that does get
written, and `_imp.check_hash_based_pycs` governs *validation* of hash pycs that already
exist, not the mode of new ones.

⇒ SO THE ONLY PLACE TO STAND IS THE WRITE ITSELF. This module patches
`SourceFileLoader._cache_bytecode`, the single funnel every source-import bytecode write
passes through, and rewrites a timestamp header into a checked-hash one before it reaches
disk.

🔴 PATCH THE CONCRETE CLASS, NOT THE BASE — MEASURED, AND THE FIRST CUT GOT IT WRONG.
`SourceFileLoader` DEFINES ITS OWN `_cache_bytecode` (_bootstrap_external.py:1238), which
overrides `SourceLoader._cache_bytecode` (:1058). A patch applied to the base class is
silently never called: the first proof-of-concept did exactly that, reported a clean install,
and left every pyc timestamp-based. It is the same shape as the `-f` trap in the migration
script — a command that succeeds while doing nothing.

THE HEADER SWAP IS EXACT, NOT AN APPROXIMATION. Both pyc headers are 16 bytes:

    timestamp     magic(4) flags(4)=0    mtime(4)  source_size(4)  marshalled code
    checked-hash  magic(4) flags(4)=0b11 source_hash(8)            marshalled code

So bytes 4:16 are replaced and the marshalled code object is passed through untouched. No
unmarshal/remarshal round trip, so this cannot alter the compiled code — the bytes after
offset 16 are the ones CPython already produced.

MEASURED, one first-time import of a two-file package, same-size same-second edit after:

    no interceptor    cache=timestamp      source says 9, fresh interpreter sees 3   STALE
    with interceptor  cache=checked-hash   source says 9, fresh interpreter sees 9   SEEN

🔴 FAIL-OPEN IS NOT DEFENSIVE POLISH HERE, IT IS THE PRICE OF THE PLACEMENT. If this is ever
installed from a sitecustomize it runs inside EVERY python process in the repo, before
anything else. An exception escaping this module would take down every interpreter start —
the test tiers, the servers, the hooks, the scripts. So every path swallows its own errors
and degrades to CPython's stock behaviour, which is exactly the status quo this control
improves on. A control that can brick the fleet is worse than the drift it prevents.

Requires:
    - CPython with 16-byte pyc headers and importlib._bootstrap_external.SourceFileLoader
      (verified against 3.13.7; `install()` refuses and returns False on any interpreter
      whose machinery does not match, rather than guessing)

Ensures:
    - `install()` is idempotent and returns True only when it newly took effect
    - after a successful install, every bytecode write for a source file inside the
      configured roots is checked-hash
    - no path in this module raises to its caller
"""

import os
import struct
import sys
import time

# The flags word lives at bytes 4..8 of every pyc. Bit 0 = hash-based, bit 1 = check_source.
# 0b11 = checked-hash (validated against the source hash on every import).
# 0b01 = UNCHECKED-hash — NEVER revalidated, which is worse for our purposes than timestamp,
#        and is reported separately rather than folded into a pass. Naming the wrong one
#        understates the finding, which is the defect Tiberius found in the shell verifier.
_FLAG_HASH_BASED  = 0b01
_FLAG_CHECK_SOURCE = 0b10
_CHECKED_HASH     = _FLAG_HASH_BASED | _FLAG_CHECK_SOURCE

_HEADER_LEN = 16

# Vendored trees are deliberately NOT converted, matching migrate-pyc-to-checked-hash.sh.
# Nobody mutation-tests third-party code, and `src/cosa/.venv` alone holds 29,303 .py files
# against 2,431 of real Lupin source — converting it would spend the cost of the control on
# 92% noise. The exclusion is what makes this module's population the SAME population the
# migration script measures; without it the two would disagree and neither would be wrong.
_EXCLUDED_PARTS = frozenset( ( ".venv", "node_modules", ".git", "__pypackages__", "site-packages" ) )

_LEDGER_RELATIVE = "io/pyc-mode-ledger.jsonl"


class _Outcome( str ):
    """
    A falsey string, so install()'s two non-True outcomes stay distinguishable
    WITHOUT breaking `if install(): ...` at any existing call site.

    Subclassing str keeps the value printable and comparable; overriding __bool__
    keeps it falsey, like the plain False it replaces.
    """
    __slots__ = ()

    def __bool__( self ): return False


# The two reasons install() does not newly install. BOTH were `False` until
# 2026-08-31 — one value for "the patch is already in place" and for "this
# interpreter cannot be patched", which are opposite facts. A caller reading the
# old False could not tell a working preventer from an impossible one.
ALREADY_INSTALLED       = _Outcome( "already-installed" )
UNSUPPORTED_INTERPRETER = _Outcome( "unsupported-interpreter" )

_installed  = False
_original   = None
_converted  = 0          # writes this process actually rewrote — the install's own receipt


def pyc_mode( data ):
    """
    Name the invalidation mode of a pyc from its header bytes.

    Requires:
        - data is a bytes-like object, or a path to a file that may or may not exist

    Ensures:
        - returns one of "checked-hash", "unchecked-hash", "timestamp", "unreadable"
        - never raises, so a census can report an unreadable file instead of dying on it
    """
    try:
        if isinstance( data, ( bytes, bytearray, memoryview ) ):
            head = bytes( data[ 4:8 ] )
        else:
            with open( data, "rb" ) as handle:
                head = handle.read( 8 )[ 4:8 ]
        if len( head ) < 4: return "unreadable"
        flags = struct.unpack( "<I", head )[ 0 ]
    except Exception:
        return "unreadable"
    if flags & _CHECKED_HASH == _CHECKED_HASH: return "checked-hash"
    if flags & _FLAG_HASH_BASED:               return "unchecked-hash"
    return "timestamp"


def to_checked_hash( data, source_bytes ):
    """
    Rewrite a timestamp pyc's header into a checked-hash one, in place in a copy.

    Requires:
        - data is the full pyc byte string, at least 16 bytes
        - source_bytes is the exact source text the code object was compiled from

    Ensures:
        - returns a bytearray whose bytes past offset 16 are IDENTICAL to the input's,
          so the compiled code object is passed through untouched
        - returns the input unchanged when it is already hash-based or too short to be a pyc
    """
    import _imp
    import importlib._bootstrap_external as bootstrap

    if len( data ) < _HEADER_LEN:      return data
    if pyc_mode( data ) != "timestamp": return data

    out = bytearray( data )
    out[ 4:8  ] = struct.pack( "<I", _CHECKED_HASH )
    out[ 8:16 ] = _imp.source_hash( bootstrap._RAW_MAGIC_NUMBER, source_bytes )
    return out


def _in_scope( source_path, roots ):
    """
    Decide whether a source file is inside the population this control owns.

    Requires:
        - source_path is a filesystem path string
        - roots is an iterable of absolute directory paths ( empty = every path is in scope )

    Ensures:
        - returns False for any path under a vendored directory
        - returns True only when the path sits under one of roots ( or roots is empty )
    """
    try:
        resolved = os.path.abspath( source_path )
        if _EXCLUDED_PARTS & set( resolved.split( os.sep ) ): return False
        if not roots: return True
        return any( resolved.startswith( root.rstrip( os.sep ) + os.sep ) for root in roots )
    except Exception:
        return False


def install( roots=None ):
    """
    Patch the import system so every bytecode write in scope is checked-hash.

    Requires:
        - nothing; safe to call on any interpreter and safe to call repeatedly

    Ensures:
        - returns True only when this call newly installed the patch
        - returns ALREADY_INSTALLED when the patch is already in place
        - returns UNSUPPORTED_INTERPRETER when the import machinery does not match
          what this module knows how to patch
        - ⚠️ BOTH ARE FALSEY, so `if install(): ...` keeps its old meaning, while a
          caller that must tell "the patch is in place" from "the patch is impossible"
          now can. They were ONE value until 2026-08-31, and this docstring stated the
          conflation as if it were a feature — they are opposite facts
        - never raises
    """
    global _installed, _original

    if _installed: return ALREADY_INSTALLED

    try:
        import importlib._bootstrap_external as bootstrap
        target   = bootstrap.SourceFileLoader
        # Patch the CONCRETE class. The base class's method is shadowed by this one, so a
        # patch on SourceLoader is never called — measured, see the module docstring.
        original = target.__dict__[ "_cache_bytecode" ]
    except Exception:
        return UNSUPPORTED_INTERPRETER

    scope = tuple( os.path.abspath( r ) for r in ( roots if roots is not None else _default_roots() ) )

    def _cache_bytecode( self, source_path, cache_path, data ):
        global _converted
        try:
            if _in_scope( source_path, scope ) and pyc_mode( data ) == "timestamp":
                converted = to_checked_hash( data, self.get_data( source_path ) )
                if converted is not data:
                    data = converted
                    _converted += 1
        except Exception:
            pass                    # fail OPEN — fall through with CPython's own bytes
        return original( self, source_path, cache_path, data )

    try:
        target._cache_bytecode = _cache_bytecode
    except Exception:
        # A DIFFERENT moment from the read above — this is the WRITE failing, on a
        # class that refuses assignment. Both mean "this interpreter cannot be
        # patched", and this file's own comment records a test that once passed on
        # the wrong one of the two because both returned a bare False.
        return UNSUPPORTED_INTERPRETER

    _original  = original
    _installed = True
    return True


def uninstall():
    """
    Restore CPython's stock bytecode write path.

    Requires:
        - nothing

    Ensures:
        - returns True only when an installed patch was actually removed
        - never raises
    """
    global _installed, _original
    if not _installed: return False
    try:
        import importlib._bootstrap_external as bootstrap
        bootstrap.SourceFileLoader._cache_bytecode = _original
    except Exception:
        return False
    _installed = False
    _original  = None
    return True


def is_installed():
    """
    Report whether this process's import system is currently patched.

    Requires:
        - nothing

    Ensures:
        - returns the install state as a bool
    """
    return _installed


def converted_count():
    """
    Report how many bytecode writes this process rewrote.

    Requires:
        - nothing

    Ensures:
        - returns a non-negative count; 0 means the patch is installed but nothing
          in scope has been compiled fresh yet, which is the normal steady state
    """
    return _converted


def _default_roots():
    """
    Resolve the source roots this control owns, from LUPIN_ROOT.

    Requires:
        - nothing; a missing LUPIN_ROOT is not an error

    Ensures:
        - returns a tuple of absolute directory paths, possibly empty
    """
    root = os.environ.get( "LUPIN_ROOT" )
    if not root: return ()
    return ( os.path.join( os.path.abspath( root ), "src" ), )


def actor():
    """
    Name who is acting, for the ledger, from environment only.

    Requires:
        - nothing

    Ensures:
        - returns a non-empty string
        - performs NO file reads — this may run inside sitecustomize on every interpreter
          start, where reading the session bridge would be both a cost and a failure mode

    NOTE the honesty limit, which the ledger's readers must know: this names the SESSION,
    not the human, and an action taken outside a Claude session names only the unix user.
    A raw `rm -rf __pycache__` typed in any shell writes no ledger line at all. That is the
    point rather than a gap — see `record()`.
    """
    session = os.environ.get( "CLAUDE_CODE_SESSION_ID", "" )[ :8 ]
    user    = os.environ.get( "USER", "unknown" )
    return f"{user}/{session}" if session else user


def ledger_path( root=None ):
    """
    Locate the append-only mode-change ledger.

    Requires:
        - root is a repo root path, or None to resolve from LUPIN_ROOT

    Ensures:
        - returns an absolute path under the repo's gitignored io/ tree, or None when
          no repo root can be resolved
    """
    base = root or os.environ.get( "LUPIN_ROOT" )
    if not base: return None
    return os.path.join( os.path.abspath( base ), *_LEDGER_RELATIVE.split( "/" ) )


def record( event, counts=None, note="", root=None ):
    """
    Append one line to the durable mode-change ledger.

    Requires:
        - event is a short string naming what happened ( e.g. "convert", "purge", "census" )
        - counts is a mapping of mode name to count, or None

    Ensures:
        - returns the path written, or None when no ledger location could be resolved
        - never raises

    WHY THIS IS THE POINT AND NOT POLISH. On 2026-08-30 the main tree's invalidation mode
    changed — 2,416 checked-hash to 66 — and FOUR people investigated. They produced three
    mutually inconsistent inferences and no answer, and the row records the hunt as
    deliberately abandoned. Nothing was wrong with anyone's reasoning; there was simply no
    record to reason from.

    ⇒ THE LEDGER'S VALUE IS IN ITS SILENCES AS MUCH AS ITS ENTRIES. Sanctioned tools write a
    line. An unsanctioned action — a raw purge, a stray compileall, a tool nobody has
    identified — writes nothing. So a mode change with no adjacent entry is POSITIVE evidence
    that no sanctioned tool did it, which is exactly the question four people could not answer.
    It does not make every actor identifiable, and it should not be sold as if it does.
    """
    path = ledger_path( root )
    if path is None: return None
    line = {
        "ts"      : time.strftime( "%Y-%m-%dT%H:%M:%S%z" ),
        "actor"   : actor(),
        "pid"     : os.getpid(),
        "event"   : event,
        "counts"  : counts or {},
        "note"    : note,
        "argv0"   : ( sys.argv[ 0 ] if sys.argv else "" )[ -120: ],
    }
    try:
        import json
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        with open( path, "a", encoding="utf-8" ) as handle:
            handle.write( json.dumps( line ) + "\n" )
    except Exception:
        return None
    return path


def census( roots ):
    """
    Count the invalidation modes of this interpreter's pycs under roots.

    Requires:
        - roots is an iterable of directory paths

    Ensures:
        - returns ( counts_by_mode, offender_paths ) for THIS interpreter's pycs only
        - excludes vendored trees, other interpreters' pycs, and pytest's assertion-rewritten
          pycs, which compileall neither owns nor can convert
        - never raises
    """
    import sysconfig
    from pathlib import Path

    tag       = sysconfig.get_config_var( "py_version_nodot" ) or ""
    mine      = f"cpython-{tag}.pyc"
    counts    = {}
    offenders = []

    for root in roots:
        try:
            candidates = Path( root ).rglob( "__pycache__/*.pyc" )
        except Exception:
            continue
        for pyc in candidates:
            if _EXCLUDED_PARTS & set( pyc.parts ): continue
            if "-pytest-" in pyc.name:             continue
            if not pyc.name.endswith( mine ):      continue
            mode = pyc_mode( str( pyc ) )
            counts[ mode ] = counts.get( mode, 0 ) + 1
            if mode != "checked-hash": offenders.append( str( pyc ) )
    return counts, offenders


def main( argv=None ):
    """
    Census this tree and append the result to the ledger.

    Requires:
        - argv is a list of directory paths, or None to use the default roots

    Ensures:
        - returns 0 when every pyc this interpreter reads is checked-hash, 1 otherwise
        - writes exactly one ledger line per invocation, so an unexplained mode change
          can later be checked against a record instead of against three inferences
        - prints the roots it actually scanned, so the scope is visible beside the verdict

    NOTE this reports and records; it does NOT convert and it does NOT block anything.
    Placement of a converting or refusing control is Rick's ruling on decision f313fc2d,
    not this module's to assume.
    """
    roots = list( argv ) if argv else list( _default_roots() )
    if not roots:
        print( "no roots to scan — pass directories or set LUPIN_ROOT" )
        return 1

    counts, offenders = census( roots )
    print( "scanned roots:" )
    for root in roots: print( f"    {os.path.abspath( root )}" )
    detail = ", ".join( f"{mode}={n}" for mode, n in sorted( counts.items() ) ) or "none"
    print( f"this interpreter's pycs: {sum( counts.values() )}  ({detail})" )

    written = record( "census", counts, note=f"offenders={len( offenders )}" )
    print( f"ledger: {written}" if written else "ledger: NOT WRITTEN (no resolvable repo root)" )

    if offenders:
        print( f"\n{len( offenders )} pyc(s) are not checked-hash. First 10:" )
        for path in offenders[ :10 ]: print( f"    {path}" )
        return 1
    return 0


if __name__ == "__main__":                       # pragma: no cover - CLI entry, exercised via main()
    sys.exit( main( sys.argv[ 1: ] ) )
