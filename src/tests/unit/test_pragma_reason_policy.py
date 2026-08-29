#!/usr/bin/env python3
"""
Enforce the pragma-reason policy: a `no cover` reason states why a line is
UNREACHABLE; it may not claim that coverage lives somewhere else.

RULED BY CHEECH 2026-08-24 (row ba849968), on this evidence: ten pragmas in the
tree carried a reason citing coverage elsewhere. Five citations held, four were
too vague to falsify as written ("already present under test"), and one was
simply untrue — notify_outbox's daemon loop claimed it was "exercised by the
integration/live drill" when no such drill exists and the integration test
monkeypatches that seam away entirely.

WHY BAN THE SHAPE RATHER THAN CHECK IT. A citing reason reads as rigour BECAUSE
it names a specific place: a vague reason invites scrutiny, a specific one ends
the conversation. But nothing verifies it, so the exemption gets bought on a
claim nobody re-reads — and in row 1a465fc3 that silently removed a method from
a hard gate. A checker that only resolved a named `test_*` identifier would have
passed clean over the four reasons it could not parse, which is this whole
family's defect wearing a linter's clothes.

An unreachability claim is different in kind: it is about the line itself, in
front of the reader, and can be judged without leaving the file.

Origin: src/rnd/v0.2.0/2026.08.23-plausible-and-wrong-seven-vacuity-shapes.md
"""

import os
import re
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


# A line coverage.py would honour as an exemption.
_PRAGMA_RE = re.compile( r"#\s*pragma:\s*no\s*cover(?P<reason>.*)$", re.IGNORECASE )

# Phrasings that claim coverage lives somewhere OTHER than the exempted line.
# Matched against the reason text only, never against code.
_CITING_RE = re.compile(
    r"\b("
    r"cover(?:ed|s)?\s+by"
    r"|exercis(?:ed|es)\s+by"
    r"|prov(?:en|ed)\s+by"
    r"|tested\s+by"
    r"|hit\s+by"
    r"|caught\s+by"
    r"|under\s+test\b"
    r"|(?:covered|exercised|tested)\s+(?:in|at)\s+the\b"
    r"|by\s+the\s+\S+\s+(?:tier|suite|drill|run)\b"
    r")",
    re.IGNORECASE,
)

_SKIP_DIRS = { "__pycache__", ".venv", "node_modules", ".git",
               "lupin-mobile", "lupin-plugin-firefox" }


def _iter_python_files():
    """
    Every .py under src/, excluding sub-repos and build artefacts.

    Ensures:
        - yields absolute paths
        - never descends into a directory named in _SKIP_DIRS
    """
    root = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
    for dirpath, dirnames, filenames in os.walk( root ):
        dirnames[ : ] = [ d for d in dirnames if d not in _SKIP_DIRS ]
        for name in filenames:
            if name.endswith( ".py" ):
                yield os.path.join( dirpath, name )


def _citing_pragmas():
    """
    Find every pragma whose REASON claims coverage lives elsewhere.

    Ensures:
        - returns a list of ( relative path, line number, reason text )
        - only the text AFTER 'no cover' is inspected, so a code line that
          happens to contain the word "covered" cannot trip the check
        - this file is skipped; it necessarily contains every phrase it bans
    """
    root      = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
    offenders  = [ ]
    unreadable = [ ]

    for path in _iter_python_files():
        if os.path.abspath( path ) == os.path.abspath( __file__ ):
            continue
        try:
            with open( path, "rb" ) as handle:
                raw = handle.read()
        except OSError as e:
            # Skip so one bad path cannot take the sweep down — but record it, because a
            # file this sweep never read is a file it never cleared (row 5c3f3d94).
            unreadable.append( f"{path}: {type( e ).__name__}: {e}" )
            continue

        # Decode permissively rather than skipping: a non-UTF8 file used to drop out of the
        # census silently. Replacement preserves newlines, so line numbers stay honest.
        lines = raw.decode( "utf-8", errors="replace" ).splitlines( keepends=True )

        for lineno, line in enumerate( lines, start=1 ):
            match = _PRAGMA_RE.search( line )
            if not match:
                continue
            reason = match.group( "reason" )
            if _CITING_RE.search( reason ):
                offenders.append( ( os.path.relpath( path, root ), lineno, reason.strip() ) )

    return offenders, unreadable


def test_no_pragma_reason_claims_coverage_lives_elsewhere():
    """
    Ensures:
        - no `pragma: no cover` reason in the tree claims coverage lives
          somewhere else ("covered by", "exercised by the X tier", "under test")
        - the failure NAMES every offender with file and line, so acting on it
          does not require re-running a search
    """
    offenders, unreadable = _citing_pragmas()

    assert unreadable == [ ], (
        f"{len( unreadable )} file(s) could not be opened, so this policy sweep never "
        f"checked them:\n  " + "\n  ".join( unreadable ) )


    assert not offenders, (
        "A `pragma: no cover` reason must say why the LINE is unreachable. It may not\n"
        "claim coverage lives somewhere else — nothing verifies such a claim, and row\n"
        "1a465fc3 is what happens when one is wrong: a method silently exempted from a\n"
        "hard gate on a citation nobody re-read. Rewrite each of these to state the\n"
        "unreachability, or delete the pragma and test the line.\n\n"
        + "\n".join( f"  {path}:{lineno}  -> {reason}" for path, lineno, reason in offenders )
    )


def test_the_detector_recognises_the_shape_it_bans():
    """
    A negative control. Without it, the test above passes just as happily if the
    regex silently stops matching anything — which is the exact failure mode this
    whole family is about.

    Ensures:
        - every banned phrasing is detected
        - an unreachability reason is NOT flagged
        - the word "covered" in code, outside a pragma, is NOT flagged
    """
    banned = [
        "# pragma: no cover - covered by the unit test",
        "# pragma: no cover - exercised by the :8000 integration tier",
        "# pragma: no cover - proven by test_foo",
        "# pragma: no cover - already present under test",
        "# pragma: no cover - CLI wrapper, exercised by the scheduled paired run",
    ]
    for line in banned:
        reason = _PRAGMA_RE.search( line ).group( "reason" )
        assert _CITING_RE.search( reason ), f"detector missed a banned phrasing: {line!r}"

    allowed = [
        '# pragma: no cover - __name__ is never "__main__" under an import',
        "# pragma: no cover - live httpx call; no branch to exercise without a socket",
        "# pragma: no cover - the guard is false whenever this module is imported",
    ]
    for line in allowed:
        reason = _PRAGMA_RE.search( line ).group( "reason" )
        assert not _CITING_RE.search( reason ), f"detector over-matched an allowed reason: {line!r}"

    # The word appears in CODE, not in a pragma reason — must not match at all.
    assert _PRAGMA_RE.search( "covered_by = compute_coverage()  # not a pragma" ) is None


def test_the_scan_actually_reads_the_tree():
    """
    Guard against the scan reporting clean because it walked nothing. A zero
    finding over a zero population is an absence wearing a pass's clothes, and
    it is the one way this policy could quietly stop being enforced.

    Ensures:
        - the walk finds a substantial number of Python files
        - it finds at least one real `pragma: no cover` somewhere in the tree
    """
    files = list( _iter_python_files() )
    assert len( files ) > 100, \
        f"the scan only saw {len( files )} python files; it is not walking the tree"

    seen_any = False
    for path in files:
        try:
            with open( path, "rb" ) as handle:
                raw = handle.read()
        except OSError:
            # This is the CONTROL loop — it only has to find one pragma anywhere, and its
            # own assertion below reddens if it finds none. An unopenable path here cannot
            # hide anything, so skipping is safe and stays a skip.
            continue
        if _PRAGMA_RE.search( raw.decode( "utf-8", errors="replace" ) ):
            seen_any = True
            break

    assert seen_any, "found no `pragma: no cover` anywhere — the matcher is broken, not the tree clean"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
