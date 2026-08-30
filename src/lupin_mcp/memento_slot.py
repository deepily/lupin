"""
memento_slot.py — prove a memento is AT THE SLOT, not merely at the path you named
(row 8068c65e).

THE DEFECT THIS CLOSES. `self_respin` verified the memento BY THE PATH THE CALLER
HANDED IT. Its check therefore answered "does the file you named exist, and is it
fresh?" — a question whose success criterion is supplied by the same caller whose
mistake it is meant to catch. It is trivially true of a wrong path, so it cannot
fail on the thing that actually goes wrong: the memento sitting somewhere no reader
looks. Two seats hit it in one afternoon (Pocholo 📣 at `--slot root` when the reap
reads `--slot io`; Tiberius 👑 at a bare `~/.claude/mementos/<persona>-<sid>-memento.md`
that is neither slot nor a well-formed mirror), and on the self-respin path NOTHING
reported it — `dismiss_sessions` runs a real memento proof and raises `memento_alarm`;
`self_respin` ran no equivalent.

WHAT A CORRECT CHECK MUST DO, and it is the whole design: DERIVE the location from
the seat's identity and look THERE. The caller's path is then evidence to be
CHECKED, never the criterion. Both legs below can fail; the old check could not.

  LEG 1 — PLACEMENT. The caller's `memento_path` must resolve to one of exactly two
  files, both derived from ( repo_root, persona, session_id, slot ) and neither taken
  from the caller: the slot POINTER, or the slot RECORD for THIS persona and THIS
  session. Anything else aborts, naming both acceptable targets so the seat can fix
  it rather than guess.

  LEG 2 — THE REAP'S OWN PROOF, run against the DERIVED pointer path. This is
  literally `reap_memento.verify_seat_memento` — the predicate `dismiss_sessions`
  already runs — so the two doors ask the same question and a memento that would
  fail a reap can no longer pass a self-respin. It is deliberately NOT a
  reimplementation: a second copy of a predicate is a second thing to drift.

WHY LEG 2 IS NOT REDUNDANT WITH LEG 1, and this is the case that motivated it. The
root slot's pointer is `.claude-memento.md` — PERSONA-LESS, one file shared by every
persona in the repo. Measured 2026-08-30: Pocholo wrote `--slot root` at 14:41 and
his record took the pointer; Mr. Radio wrote at 15:20 and took it back. So a seat's
record can sit correctly at its own derived path (leg 1 passes) while the pointer a
naive reader follows names SOMEBODY ELSE. Leg 2 catches exactly that, because the
pointer's resolved record carries a header `session_id` and it will not be this
seat's.

LAYOUT — mirrors `planning-is-prompting → workflow/scripts/memento_io.py`, which is
the WRITER and the single authority on where a memento goes. This module derives the
same paths so it can look where the writer puts things; it never writes.

    slot=io    POINTER  io/mementos/<persona>.md
               RECORD   io/mementos/<persona>-<sid8>.md
    slot=root  POINTER  .claude-memento.md
               RECORD   .claude-memento-<persona>-<sid8>.md

WHICH SLOT BELONGS TO WHICH DOOR is settled doctrine, not a choice made here:
`reap_memento`'s module docstring records it — a reap reads `io` (the manager reaps
seats it SPAWNED), a self-respin reads `root` (a manager clears its OWN pane). The
drift this module repairs is that `self_respin_core` had no concept of a slot at all,
so the doctrine named a location and the code checked none.

`~/.claude/mementos` IS a legitimate second home — as memento_io's MIRROR_HOME — but
only at `~/.claude/mementos/<repo>/<record-path-relative-to-repo-root>`. A file at its
bare top has no repo segment and is not a mirror; it is a stray, and this module
refuses it as one.

PURITY: every seam (clock, file read, repo-root resolution) is injected, so both legs
are unit-provable with fakes and no repo, no git, and no live server.
"""

import os
import subprocess

from pathlib import Path

from lupin_mcp.persona_normalization import persona_slug
from lupin_mcp.reap_memento          import (
    DEFAULT_MIN_BYTES,
    DEFAULT_WINDOW_SECONDS,
    verify_seat_memento,
)


SLOT_IO   = "io"
SLOT_ROOT = "root"

# The self-respin door's slot. Named rather than inlined so the coupling to
# reap_memento's `io` is visible as a DELIBERATE disjointness, not a coincidence.
SELF_RESPIN_SLOT = SLOT_ROOT


def slot_pointer_path( repo_root, persona, slot=SELF_RESPIN_SLOT ):
    """
    The mutable POINTER file for a slot — what a naive reader follows.

    Requires:
        - repo_root is the seat's own repo root; persona is its persona name
        - slot is SLOT_IO or SLOT_ROOT

    Ensures:
        - slot=io   -> <repo_root>/io/mementos/<persona-slug>.md
        - slot=root -> <repo_root>/.claude-memento.md  (PERSONA-LESS by memento_io's
          own layout — see the module docstring for why that matters)
        - the slug is accent/punctuation/case-proof via persona_slug

    Raises:
        - ValueError on an unknown slot — never a silent fallback to one of them
    """
    root = Path( repo_root )
    if slot == SLOT_IO:   return root / "io" / "mementos" / f"{persona_slug( persona )}.md"
    if slot == SLOT_ROOT: return root / ".claude-memento.md"
    raise ValueError( f"unknown memento slot {slot!r} — expected {SLOT_IO!r} or {SLOT_ROOT!r}" )


def slot_record_path( repo_root, persona, sid8, slot=SELF_RESPIN_SLOT ):
    """
    The IMMUTABLE RECORD file for a slot, for one persona and one session.

    Requires:
        - repo_root, persona as above; sid8 is the session id (only its first 8
          characters are used, lower-cased — memento_io stamps `short_sid()`)
        - slot is SLOT_IO or SLOT_ROOT

    Ensures:
        - slot=io   -> <repo_root>/io/mementos/<persona-slug>-<sid8>.md
        - slot=root -> <repo_root>/.claude-memento-<persona-slug>-<sid8>.md

    Raises:
        - ValueError on an unknown slot
    """
    root  = Path( repo_root )
    slug  = persona_slug( persona )
    short = ( sid8 or "" )[ :8 ].lower()
    if slot == SLOT_IO:   return root / "io" / "mementos" / f"{slug}-{short}.md"
    if slot == SLOT_ROOT: return root / f".claude-memento-{slug}-{short}.md"
    raise ValueError( f"unknown memento slot {slot!r} — expected {SLOT_IO!r} or {SLOT_ROOT!r}" )


def resolve_repo_root( start=None, run_fn=None ):
    """
    The seat's own repo root, resolved the way memento_io resolves it.

    Requires:
        - start is a directory to resolve from (default: the process cwd)
        - run_fn( argv, cwd ) -> stdout str, or None/raise when git cannot answer

    Ensures:
        - returns `git rev-parse --show-toplevel` for `start`, stripped
        - returns None when git is unavailable, errors, or answers blank — the caller
          REFUSES rather than guessing a root (reap_memento.seat_repo_root records why:
          a guessed root does not fail to find a memento, it finds the WRONG one)
        - never raises
    """
    cwd = start if start is not None else os.getcwd()
    run = run_fn if run_fn is not None else _default_git_toplevel
    try:
        out = run( [ "git", "rev-parse", "--show-toplevel" ], cwd )
    except Exception:
        return None
    if not isinstance( out, str ) or not out.strip():
        return None
    return out.strip()


def _default_git_toplevel( argv, cwd ):   # pragma: no cover - subprocess seam
    """Ensures: stdout of `argv` run in `cwd`, or None on any non-zero/failed run."""
    proc = subprocess.run( argv, cwd=cwd, capture_output=True, text=True )
    return proc.stdout if proc.returncode == 0 else None


def acceptable_slot_targets( repo_root, persona, sid8, slot=SELF_RESPIN_SLOT ):
    """
    Ensures: the two paths a seat's memento may legitimately BE for this slot —
             ( pointer_path, record_path ). Both are DERIVED from identity; neither
             is ever taken from the caller. That is the whole point of the check.
    """
    return (
        slot_pointer_path( repo_root, persona, slot ),
        slot_record_path( repo_root, persona, sid8, slot ),
    )


def _same_file( a, b ):
    """
    Ensures: True iff `a` and `b` name the same location after symlink + `..`
             resolution — so a relative path, a `./` prefix, or a symlinked repo
             root does not read as a wrong placement.
             A path that cannot be resolved compares False rather than raising.
    """
    try:
        return os.path.realpath( str( a ) ) == os.path.realpath( str( b ) )
    except ( OSError, ValueError, TypeError ):
        return False


def verify_memento_at_slot(
    memento_path,
    *,
    repo_root,
    persona,
    session_id,
    now,
    read_text_fn,
    slot           = SELF_RESPIN_SLOT,
    window_seconds = DEFAULT_WINDOW_SECONDS,
    min_bytes      = DEFAULT_MIN_BYTES,
):
    """
    Prove this seat's memento is AT ITS SLOT — both legs, in order.

    Requires:
        - memento_path is the path the CALLER claims to have written + stamped
        - repo_root is the seat's own repo root (None ⇒ refuse, never guess)
        - persona, session_id identify the seat; now is an AWARE datetime
        - read_text_fn( path ) -> file text, or None when unreadable
        - slot is SLOT_IO or SLOT_ROOT

    Ensures:
        - ( False, reason ) when repo_root is missing/blank — refuses rather than
          resolving a slot against a guessed root
        - LEG 1 ( False, reason ) when memento_path resolves to neither the slot
          pointer nor THIS persona+session's slot record; the reason names both
          acceptable targets
        - LEG 2 ( False, reason ) when the DERIVED pointer fails
          reap_memento.verify_seat_memento — the same predicate dismiss_sessions
          runs (byte floor, parseable header, header session_id == this seat,
          aware + non-future + in-window written_at, pointer `current:` resolved)
        - ( True, reason ) only when BOTH legs pass
        - reads nothing but what read_text_fn returns; writes nothing; never raises
          on an unknown slot reaching it through `slot` (that is a ValueError from
          the path helpers, which is a programming error, not a seat's mistake)
    """
    if not repo_root or not str( repo_root ).strip():
        return False, (
            "cannot resolve this seat's repo root — refusing to check a memento slot against a "
            "guessed root (a guessed root finds the WRONG memento, it does not fail to find one)"
        )

    pointer_path, record_path = acceptable_slot_targets( repo_root, persona, session_id, slot )

    # LEG 1 — PLACEMENT. Derived targets vs the caller's claim.
    if not ( _same_file( memento_path, pointer_path ) or _same_file( memento_path, record_path ) ):
        return False, (
            f"memento is not at this seat's {slot!r} slot: {memento_path} is neither "
            f"{pointer_path} (the slot pointer) nor {record_path} (this session's record). "
            f"Write it with `memento_io.py write --slot {slot}`, which lands the record, the "
            f"mirror AND the pointer in one operation."
        )

    # LEG 2 — the reap's own proof, against the DERIVED pointer (never the caller's path).
    ok, reason = verify_seat_memento(
        str( pointer_path ),
        ( session_id or "" )[ :8 ],
        now,
        read_text_fn   = read_text_fn,
        window_seconds = window_seconds,
        min_bytes      = min_bytes,
    )
    if not ok:
        return False, f"the {slot!r} slot pointer {pointer_path} fails the reap's memento proof: {reason}"

    return True, f"memento is at the {slot!r} slot and clears the reap's memento proof"
