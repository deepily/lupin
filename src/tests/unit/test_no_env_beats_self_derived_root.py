"""
CLASS GUARD for the wrong-tree defect Pocholo 📣 found on 2026-08-30.

THE SHAPE, not the two instances:

    LUPIN_ROOT="${LUPIN_ROOT:-$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )}"

A script that can work out its own tree from BASH_SOURCE, and then lets an
inherited environment variable beat that answer. The fallback is correct; the
override is what breaks it, because every seat's shell exports LUPIN_ROOT
pointing at the MAIN checkout. Run such a script from a worktree and it operates
on a tree you are not in, and says it succeeded.

WHY A GUARD RATHER THAN A THIRD HAND-FIX. Two were repaired by hand
(purge-pycache.sh, migrate-pyc-to-checked-hash.sh) and a sweep immediately found
a third. Repairing found instances is a habit; this fails when a FOURTH appears.

Deliberately narrow: it fires only on scripts that derive the root from their own
location and then discard it. A script defaulting to a hardcoded absolute path is
a different shape -- there the variable is the only way to aim it at all, and
removing it would break the script rather than fix it.
"""
import re
import subprocess
from pathlib import Path

REPO = Path( __file__ ).resolve().parents[ 3 ]

# The offending shape: an override whose default is derived from BASH_SOURCE.
SELF_DERIVED_BUT_OVERRIDABLE = re.compile(
    r'LUPIN_ROOT="\$\{LUPIN_ROOT:-\$\(\s*cd\s+"\$\(\s*dirname\s+"\$\{BASH_SOURCE'
)

# Known member, NOT yet repaired and not repairable as a drive-by: it does
# `rm -rf .venv` in whatever tree it resolves, and its own header documents the
# override as the supported way to aim it. Removing it is a ruling, not a tidy-up.
# Recorded here so the exception is visible and cannot quietly become the norm.
KNOWN_UNRESOLVED = { "src/scripts/build-local-venv.sh" }


def _tracked_shell_scripts():
    out = subprocess.run( [ "git", "ls-files", "*.sh", "src/scripts/*" ],
                          cwd=REPO, capture_output=True, text=True, check=True )
    return [ line for line in out.stdout.splitlines() if line.strip() ]


def test_no_script_lets_an_inherited_root_beat_its_own_location():
    offenders = set()

    for rel in _tracked_shell_scripts():
        path = REPO / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text( encoding="utf-8" )
        except UnicodeDecodeError:
            continue
        if SELF_DERIVED_BUT_OVERRIDABLE.search( text ):
            offenders.add( rel )

    assert offenders == KNOWN_UNRESOLVED, (
        f"changed membership of the wrong-tree class: {sorted( offenders )}\n"
        f"expected exactly: {sorted( KNOWN_UNRESOLVED )}\n"
        "A NEW name here means a script can be aimed at another seat's tree by an\n"
        "inherited LUPIN_ROOT -- derive from BASH_SOURCE unconditionally instead.\n"
        "A name DISAPPEARING here means the exception was repaired: delete it from\n"
        "KNOWN_UNRESOLVED rather than leaving a stale allowance behind."
    )


def test_the_two_repaired_scripts_are_not_in_the_class():
    # Named explicitly: the guard above is an equality, so a bug that emptied the
    # scan would satisfy it as long as the exception set emptied too. This asserts
    # the scan can still SEE the repaired files at all.
    for rel in ( "src/scripts/purge-pycache.sh",
                 "src/scripts/migrate-pyc-to-checked-hash.sh" ):
        text = ( REPO / rel ).read_text( encoding="utf-8" )
        assert 'LUPIN_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." && pwd )"' in text, rel
        assert not SELF_DERIVED_BUT_OVERRIDABLE.search( text ), rel
