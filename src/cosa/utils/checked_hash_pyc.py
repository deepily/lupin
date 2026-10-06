"""
Mechanical control that rewrites every in-scope bytecode write into checked-hash form.

Written rules were broken by people who had read them. A correctly converted tree
also drifted to timestamp pycs through ordinary first-time imports, with no rule
broken, so no purge discipline helps. The control therefore sits at the write itself.

Requires:
    - CPython with 16-byte pyc headers and importlib._bootstrap_external.SourceFileLoader
      (verified against 3.13.7); `install()` returns UNSUPPORTED_INTERPRETER on
      any interpreter whose machinery does not match, rather than guessing

Ensures:
    - `install()` is idempotent and returns True only when it newly took effect
    - after a successful install, every bytecode write for a source file inside the
      configured roots is checked-hash
    - no path in this module raises to its caller

Why the write is the only place to act. CPython derives hash-based from an existing
pyc. With no pyc there is nothing to inherit a mode from, so it writes a timestamp
pyc. No flag changes that. `-B` and PYTHONDONTWRITEBYTECODE suppress writing, not
the mode of a pyc that is written. `_imp.check_hash_based_pycs` governs validation
of existing hash pycs, not new ones.

So this module patches `SourceFileLoader._cache_bytecode`, the single funnel for
source-import bytecode writes. It swaps a timestamp header for a checked-hash one
before the bytes reach disk. It patches the concrete class, not the base:
SourceFileLoader defines its own `_cache_bytecode`, which overrides the base one.
A patch on the base is never called and reports a clean install while doing nothing.

The header swap is exact. Both headers are 16 bytes. Timestamp is magic(4),
flags(4)=0, mtime(4), source_size(4). Checked-hash is magic(4), flags(4)=0b11,
source_hash(8). Bytes 4:16 are replaced and the marshalled code passes through
untouched, with no unmarshal round trip.

Every path fails open. Installed from a sitecustomize, this runs inside every python
process in the repo, so an escaping exception would stop every interpreter start.
Each path swallows its own errors and degrades to CPython's stock behaviour. A
control that can brick the fleet is worse than the drift it prevents.
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
    A string that refuses to be a boolean, so callers must ask the question they mean.

    `install()` answers "did this call newly install the patch?". `is_installed()`
    answers "is the patch active?". For a caller who meant the second, `ALREADY_INSTALLED`
    is a success, so any truthiness answer is wrong for somebody. A falsey value
    rebuilds the old conflation one level out. A truthy value is wrong for the caller
    who meant the first question. So the implicit bool raises.

    Subclassing str keeps the value printable, comparable and usable in a message;
    only the implicit bool is refused. `install()` still returns a real `True` on the
    newly-installed path, so `if install():` works there. On the ambiguous paths it
    fails loudly and names the remedy.
    """
    __slots__ = ()

    def __bool__( self ):
        raise TypeError(
            f"install() returned {str( self )!r}, which has no truth value: "
            f"'did this call install it?' and 'is the patch active?' are different "
            f"questions and this value answers only the first. Compare it "
            f"explicitly (is chp.ALREADY_INSTALLED / is chp.UNSUPPORTED_INTERPRETER), "
            f"or call is_installed() if you meant 'is the patch active?'."
        )


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
        - returns a bytearray whose bytes past offset 16 are identical to the input's,
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
        - roots is an iterable of absolute directory paths

    Ensures:
        - returns False for any path under a vendored directory
        - returns True only when the path sits under one of roots
        - an empty set must never be read as a universal set in a permission check. The same
          ambiguity has hidden behind a bare False meaning "no need" or "impossible", and behind a
          clean exit meaning "did the work" or "never ran". Each time, two opposite facts shared
          one representation. Fail closed wherever an
          empty value would grant authority: "I was given no roots" never resolves to "I may
          rewrite anything"
        - an empty roots means nothing is in scope, never everything: it fails closed.
          Empty once meant everything, which left the shim unbounded on any interpreter
          started without LUPIN_ROOT, because _default_roots() returns () there. It
          would then have rewritten stdlib bytecode. A control that owns everything by
          default owns things nobody agreed to give it. Fail closed wherever an empty
          value grants authority.
    """
    try:
        resolved = os.path.abspath( source_path )
        if _EXCLUDED_PARTS & set( resolved.split( os.sep ) ): return False
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
        - neither failure value has a truth value: using one in a boolean context
          raises TypeError naming `is_installed()`. Merely falsey values were still
          wrong, because for a caller asking "is the patch active?", ALREADY_INSTALLED
          is a success. Ask the question you mean
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
        - performs no file reads; this may run inside sitecustomize on every interpreter
          start, where reading the session bridge would be both a cost and a failure mode

    Honesty limit, which the ledger's readers must know: this names the session, not
    the human. An action outside a Claude session names only the unix user. A raw
    `rm -rf __pycache__` typed in any shell writes no ledger line at all. That is by
    design; see `record()`.
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

    Why it exists: a tree's invalidation mode once changed (2,416 checked-hash pycs
    to 66) and four people could not agree why, because there was no record to reason
    from. The ledger's value is in its silences as much as its entries. Sanctioned
    tools write a line. An unsanctioned action (a raw purge, a stray compileall, an
    unidentified tool) writes nothing. So a mode change with no adjacent entry is
    positive evidence that no sanctioned tool did it. It does not make every actor
    identifiable, and it should not be sold as if it does.
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
        - returns ( counts_by_mode, offender_paths ) for this interpreter's pycs only
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
          can later be checked against a record instead of against inference
        - prints the roots it actually scanned, so the scope is visible beside the verdict

    This reports and records. It does not convert and it does not block anything.
    Where a converting or refusing control belongs is decided elsewhere, not assumed here.
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
