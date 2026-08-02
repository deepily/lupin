"""
Bridge-directory contact guard — shared logic (row e2ae4102).

WHY THIS MODULE EXISTS
Two unit files drive `register_session.main()` for real and must never leave a
mark on the operator's live bridge directory (`~/.claude/sessions`). The hazard
is genuine (row 8ccc20ab): a hook that resolves its directory from a hardcoded
real path instead of the seam merges into a LIVE session's bridge and can null
that seat's voice_persona.

The old guard fingerprinted the WHOLE real directory before and after EVERY test
and blamed the test for any change. On a busy fleet box that is a FALSE
ACCUSATION: a peer session writes its own bridge while the suite runs, the
fingerprint changes, and the guard points at whichever test happened to be
holding the suite. It detected CONTACT with the directory and reported it as
AUTHORSHIP (row e2ae4102 — three runs one night, fail / clean / fail on identical
code, the signature of a peer's write, not a code defect).

THE TWO-TIER FIX (Direction 3)
  · Concurrent run (the busy box): a SCOPED canary. It watches only entries whose
    name embeds one of the test's OWN synthetic probe ids ("...-probe..."). A peer
    never uses those, so it cannot false-accuse; a regression that hardcodes the
    real path and writes `cc-<probe-id>.json` there is still caught immediately.
    It CANNOT catch a merge into a live seat (that bears a REAL id, not a probe id)
    — which is exactly why the second tier is not optional.
  · Serial gate (a quiescent box, at merge time): the full whole-directory check,
    where any delta IS attributable because no peer is writing. Run ONLY by
    `src/scripts/run-serial-bridge-guard.sh`, wired into CLAUDE.md § PR MERGE
    REQUIREMENTS. If that invocation is removed, the whole-dir hazard guard is
    silently gone — see the marked tests' docstrings.

Everything here is a pure function of its arguments (or of a directory passed in),
so it unit-tests to 100% against a tmp directory with no live sockets and no
concurrency — `test_bridge_dir_guard.py`.
"""

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


# The operator's live bridge directory. Bound here so both callers agree on it.
REAL_SESSIONS_DIR = Path( os.path.expanduser( "~/.claude/sessions" ) )

# Fleet-shared append-only logs — every live listener / idle-waiter writes them
# continuously, so a change is not attributable to the observing test. Named, not
# silently globbed around (row 877794ed).
UNATTRIBUTABLE = frozenset( { "cc-listeners.log", "cc-idle-waiters.log" } )


def fingerprint_dir( directory: Any, session_ids: Iterable[ str ] = None ) -> Dict[ str, str ]:
    """
    Content fingerprint { name: sha256 | "<dir>" | "<unreadable>" } of the
    attributable entries in `directory`.

    Hashes CONTENT, not names or a count: a merge into a live seat leaves the file
    count unchanged and can swap one id for another of equal length, so only a
    content hash sees it (bug 2508b1ce). Globs `*`, not `cc-*.json`, because the
    narrower glob missed `cc-listener-*.stderr` / `.spawn-lock` writes (row
    877794ed); the two fleet-shared logs in `UNATTRIBUTABLE` are the sole names
    dropped.

    Requires:
        - directory is a path-like; it need not exist
        - session_ids is None, or an iterable of substrings to restrict to

    Ensures:
        - a missing directory yields {} (no contact is possible with a dir that
          isn't there)
        - when session_ids is None, EVERY attributable entry is fingerprinted
          (the whole-dir projection used by the serial gate)
        - when session_ids is given, ONLY entries whose name embeds one of them
          are fingerprinted (the scoped projection used by the concurrent canary)
    """
    d = Path( directory )
    if not d.is_dir():
        return { }
    ids = list( session_ids ) if session_ids is not None else None
    out : Dict[ str, str ] = { }
    for p in sorted( d.glob( "*" ) ):
        if p.name in UNATTRIBUTABLE:
            continue
        if ids is not None and not any( sid in p.name for sid in ids ):
            continue
        if p.is_dir():
            out[ p.name ] = "<dir>"
            continue
        try:
            out[ p.name ] = hashlib.sha256( p.read_bytes() ).hexdigest()
        except OSError:
            out[ p.name ] = "<unreadable>"
    return out


def real_dir_fingerprint( session_ids: Iterable[ str ] = None ) -> Dict[ str, str ]:
    """
    `fingerprint_dir` bound to the operator's live `REAL_SESSIONS_DIR`.

    Ensures:
        - returns fingerprint_dir( REAL_SESSIONS_DIR, session_ids )
    """
    return fingerprint_dir( REAL_SESSIONS_DIR, session_ids=session_ids )


def dir_delta( before: Dict[ str, str ], after: Dict[ str, str ] ) -> Tuple[ List[ str ], List[ str ], List[ str ] ]:
    """
    Compare two fingerprints and name what moved.

    Requires:
        - before, after are { name: fingerprint } dicts

    Ensures:
        - returns ( created, removed, changed ), each a sorted list of names:
          created = in after only, removed = in before only, changed = in both
          with a different fingerprint
    """
    created = sorted( set( after ) - set( before ) )
    removed = sorted( set( before ) - set( after ) )
    changed = sorted( n for n in ( set( before ) & set( after ) ) if before[ n ] != after[ n ] )
    return ( created, removed, changed )


def contact_detail( created: List[ str ], removed: List[ str ], changed: List[ str ] ) -> str:
    """
    The firing detail for a contact assertion, or None when nothing moved.

    Kept as a pure function so BOTH tiers assert the same way
    (`assert contact_detail( *dir_delta( before, after ) ) is None, ...`) and so the
    FIRE path itself has a control: a test can feed it a non-empty delta and pin the
    exact text, rather than only ever seeing it return None on a clean run.

    Requires:
        - created, removed, changed are lists of entry names

    Ensures:
        - returns None when all three are empty (no contact — the guard passes)
        - otherwise returns a single string naming each set, with `changed` flagged
          as the dangerous merge-into-a-live-seat case
    """
    if not ( created or removed or changed ):
        return None
    return (
        f"created: {created}\n  removed: {removed}\n  "
        f"CHANGED (merged into a live seat): {changed}"
    )
