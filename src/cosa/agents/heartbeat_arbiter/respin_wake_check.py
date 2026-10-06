"""
Re-spin wake check: make a re-spin that loses its wake fail loudly.

Why this exists: a self_respin fired its clear and the wake prompt never arrived.
The seat sat at an empty prompt for twenty minutes until a peer typed the wake by hand.
Another successor rehydrated from a stale copy under ~/.claude/mementos, not the live record.
Both failures are silent, because the seat looks idle rather than broken.

The chosen shape: never chase why the wake drops. Verify the successor came up, and shout if it did not.
The underlying drop stays in the code as an accepted trade.

One oracle covers both failures. "Did it wake?" and "did it read the right memento?" share one witness,
the file the rehydrated seat opened at boot. The successor writes a boot receipt naming that file:

  - no receipt past the deadline: it never woke
  - receipt naming a mirror-slot copy: it woke and read the wrong file
  - receipt naming a long-stale record: it woke onto old state
  - receipt naming nothing at all: it woke but consumed no seed
  - receipt naming another persona's record: it woke into somebody else's state
  - receipt naming a fresh root record: `RETURNED`

The persona check asks about the reader, not the file. A record can be live and current
and still belong to somebody else, so `WRONG_PERSONA` compares the seat with the record's owner.
The shape follows `reap_memento.verify_seat_memento`, which refuses a prior holder's memento.

The receipt is always written by the rehydrated seat's own SessionStart, never by the injector.
An injector-written receipt would prove only that the injector reached its write line, because
`tmux send-keys` gives no ingestion feedback. Same discipline as `self_respin_observer`.

The predecessor's receipt cannot green the check. A self_respin keeps its session id, so the
pre-clear boot already left a receipt; the check asks for one dated after `fired_at`.

The shout goes by DM to the manager who fired the re-spin, not into a log, because a line nobody
reads reproduces the defect. Delivery is an injected `alert_fn` seam.
`classify_wake` is pure (stdlib only, no IO); every other side effect is injectable.
"""

import datetime
import glob
import hashlib
import json
import os
import re
import threading
import time
import unicodedata

from dataclasses import dataclass
from enum        import Enum
from pathlib     import Path


# The on-disk receipt filename shape: <RECEIPT_PREFIX><session_id>.json, living
# under fleet_data_root() — never the repo root. A hold written to the repo root
# parks a session invisibly because no reader looks there (row 011f1f90); the
# same placement mistake would make this receipt invisible to the same readers.
RECEIPT_PREFIX = ".respin-boot-receipt-"

# How long past `fired_at` a successor may take to leave a receipt before the
# check calls it dead. Pocholo's seat was hand-woken at twenty minutes; a healthy
# boot leaves the receipt in seconds. Ninety seconds sits far outside the healthy
# distribution and far inside the twenty-minute one.
DEFAULT_WAKE_DEADLINE_SECONDS = 90

# How old the memento a successor read may be before it is called stale. A
# re-spin's memento is written minutes before the re-spin fires, so anything past
# an hour is a record from a previous cycle rather than this one.
DEFAULT_MAX_MEMENTO_AGE_SECONDS = 3600

# Poll cadence for the bounded watch.
DEFAULT_POLL_INTERVAL_SECONDS = 3.0


# ── Memento slots ─────────────────────────────────────────────────────────────
# The four directories register_session._memento_dirs enumerates, named. The
# ROOT family is the live record's home and the one the fleet's rule names (the
# memento lives at the repo root, and the root is read first). The MIRROR family
# under ~/.claude/mementos holds copies that go stale on their own schedule —
# that is the slot Krishna's successor read from.
SLOT_ROOT    = "root"       # <repo_root>/.claude-memento-<persona>-<sid8>.md
SLOT_REPO_IO = "repo_io"    # <repo_root>/io/mementos/<persona>-<sid8>.md
SLOT_MIRROR  = "mirror"     # ~/.claude/mementos/<project>/… (both its levels)
SLOT_NONE    = "none"       # nothing resolved
SLOT_UNKNOWN = "unknown"    # resolved, but under none of the known roots

# The slots a successor is allowed to have read. The mirror family is excluded on
# purpose: a copy there is not the live record, and reading it is the Krishna
# failure whether or not its timestamp happens to look recent.
LIVE_SLOTS = ( SLOT_ROOT, SLOT_REPO_IO )


class WakeVerdict( Enum ):
    """What the check concluded about a successor."""
    RETURNED          = "RETURNED"           # woke, read a live + current memento
    PENDING           = "PENDING"            # inside the window, no receipt yet
    DEAD_NO_WAKE      = "DEAD_NO_WAKE"       # ALARM: past deadline, never left a receipt
    SEED_NOT_CONSUMED = "SEED_NOT_CONSUMED"  # ALARM: woke, but resolved no memento at all
    STALE_SLOT        = "STALE_SLOT"         # ALARM: woke, read a mirror copy not the live record
    STALE_MEMENTO     = "STALE_MEMENTO"      # ALARM: woke, read a live slot but an old record
    WRONG_PERSONA     = "WRONG_PERSONA"      # ALARM: woke, read a live+current record belonging to SOMEBODY ELSE
    MALFORMED_RECEIPT = "MALFORMED_RECEIPT"  # ALARM: a receipt exists but its stamps are unreadable


@dataclass
class WakeAssessment:
    """One successor's verdict, the human-readable reason, and the alarm flag.

    `memento_path` rides along even on an alarm, because a manager reading a
    `STALE_SLOT` wants to know which file the seat actually opened."""
    session_id   : "str | None"
    persona      : "str | None"
    verdict      : WakeVerdict
    reason       : str
    is_alarm     : bool
    memento_path : "str | None" = None

    # LOCATION, carried as a FIRST-CLASS FIELD for the same reason the holds family
    # carries it (row 011f1f90): a receipt that is ABSENT and a receipt that is
    # MISPLACED read identically, because `find_receipt_by_identity` globs ONE
    # directory non-recursively and anything outside it is simply not seen. So
    # DEAD_NO_WAKE — "it never came back" — is also what a seat gets when it DID
    # come back and wrote its receipt to the wrong root. Two failures, one output,
    # wanting opposite remedies: chase a dead seat, or fix a writer.
    #
    # This is EVIDENCE, not a verdict. The list stays empty on every path that does
    # not look, and populating it changes no verdict and no alarm flag — a reader
    # who ignores it sees exactly what it saw before.
    misplaced    : "list | None" = None

    # THE IDENTITY THE WATCH WAS ARMED ON, carried so the alert can say WHICH SEAT
    # it is shouting about (row 7ad5eba6). Measured 2026-09-03: the live arm hands
    # the watch a `tmux_session` and NO persona and NO session_id — `persona` is not
    # even a parameter of `verify_respin_wake`. On a no-receipt DEAD_NO_WAKE the
    # receipt is absent too, so `persona` and `session_id` BOTH fall back to None and
    # `render_alert` printed "unknown persona / unknown session" on every such alarm,
    # unconditionally. That string is a property of the renderer, not a reading of
    # the seat — and a manager read it as evidence the arm carried no identity,
    # built five one-variable cases on top of it, and reached a wrong diagnosis.
    #
    # A constant that looks like a variable is worse than no field at all. The watch
    # KNEW the seat's tmux name the whole time and was the only thing that did not
    # say it.
    tmux_session : "str | None" = None


def _parse_iso( value ):
    """
    Parse an ISO-8601 stamp to an aware datetime, or None.

    A naive stamp is rejected rather than assumed local. The check compares the
    stamp with `fired_at` to decide whether a receipt predates the re-spin, and a
    wrong-by-hours comparison would green a dead seat.

    Requires:
        - value is an ISO-8601 string, or anything defensively

    Ensures:
        - returns an aware datetime, or None for empty/naive/unparseable input
        - never raises
    """
    if not isinstance( value, str ) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat( value.strip() )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def classify_memento_slot( memento_path, repo_root, mirror_root=None ):
    """
    Name the slot a resolved memento path sits in.

    Requires:
        - memento_path is a path string, or None when nothing resolved
        - repo_root is the seat's repo root path, or None when unknown
        - mirror_root is the ~/.claude/mementos root, or None to derive it

    Ensures:
        - SLOT_NONE when memento_path is empty
        - SLOT_REPO_IO when it sits under <repo_root>/io/mementos
        - SLOT_ROOT when it sits directly at <repo_root>
        - SLOT_MIRROR when it sits anywhere under the mirror root — its top level
          and its own io/mementos sub-slot fail identically, so they are not worth
          distinguishing to a reader
        - SLOT_UNKNOWN when it matches none of them
        - the repo tests run first, so a repo that happens to live under the
          mirror root is still reported as a repo slot
        - never raises
    """
    if not memento_path:
        return SLOT_NONE

    resolved  = os.path.normpath( os.path.abspath( memento_path ) )
    directory = os.path.dirname( resolved )

    if repo_root:
        root = os.path.normpath( os.path.abspath( repo_root ) )
        if directory == os.path.join( root, "io", "mementos" ):
            return SLOT_REPO_IO
        if directory == root:
            return SLOT_ROOT

    mirror = mirror_root if mirror_root else os.path.expanduser( "~/.claude/mementos" )
    mirror = os.path.normpath( os.path.abspath( mirror ) )
    if directory == mirror or directory.startswith( mirror + os.sep ):
        return SLOT_MIRROR

    return SLOT_UNKNOWN


# ---------------------------------------------------------------------------
# The receipt — written by the rehydrated seat, read by the manager's check
# ---------------------------------------------------------------------------

def receipt_path( base_dir, session_id ):
    """
    Path to one seat's boot receipt.

    Requires:
        - base_dir is a directory path
        - session_id is the seat's session id string

    Ensures:
        - returns <base_dir>/<RECEIPT_PREFIX><session_id>.json
        - never raises
    """
    return os.path.join( base_dir, f"{RECEIPT_PREFIX}{session_id}.json" )


_RULE_CHARS = set( "\u2550=-_" )   # the characters a horizontal rule is drawn from


def describe_block( block ):
    """
    Measure the memento block the boot path actually produced.

    This describes the block, the only thing a session sees; every other receipt field describes the file.
    It splits "block came back empty" from "block produced", but a healthy `block_bytes` is no
    proof a seat received anything. That needs an echo from the far end.

    Requires:
        - block is the rendered block string, or "" / None when none was produced

    Ensures:
        - returns a dict with block_bytes, block_sha256, block_headline
        - block_bytes counts UTF-8 bytes, never characters — the two differ on
          emoji-carrying headlines this block is built from
        - a block of None returns all three fields as None — not measured,
          because nothing was supplied. This is a different fact from an empty
          block and the two must never render alike
        - block_sha256 is taken over those same bytes for every supplied input
          including the empty string, so a produced-but-empty block carries a
          stable, recognisable digest that a not-measured null cannot imitate
        - block_headline is None when the block carries no content line
        - never raises
        - a produced block can still be lost in transit between the hook's additionalContext and the session; even an echo leaves two states (not received, received and ignored) rather than zero
        - block_headline is found by a predicate, never by position: the first line
          with content other than the horizontal rule, which survives a blank line
          or a second rule being added above it
    """
    # 🔴 None AND "" ARE DIFFERENT FACTS AND MUST NOT COLLAPSE (CLAYTON 😎,
    # 2026-09-06 — credit CORRECTED 2026-09-06 01:30; the commit that added this
    # line, `32929647`, says "MARÍA'S FINDING" and is WRONG. She RELAYED it; he
    # FOUND it, with the receipt in hand. She made the correction herself,
    # unprompted, against her own credit. A finding attributed to the manager who
    # passed it on tells the next reader THE REVIEW SEAT FOUND NOTHING). `None` means NO BLOCK WAS SUPPLIED — an old caller, or a
    # wiring that dropped it. `""` means a block WAS produced and came back
    # empty, which is state (3), the one thing this instrument exists to name.
    # Rendering both as `0 bytes / e3b0c442…` made those indistinguishable, so
    # the receipt could not tell "the renderer produced nothing" from "nobody
    # asked the renderer" — and that is precisely why the state-3 test was blind
    # to the unwiring arm. `None` is NOT MEASURED and says so.
    if block is None:
        return { "block_bytes": None, "block_sha256": None, "block_headline": None }

    text  = block
    data  = text.encode( "utf-8" )

    headline = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:                          continue
        if set( stripped ) <= _RULE_CHARS:        continue   # a horizontal rule, not content
        headline = stripped
        break

    return {
        "block_bytes"    : len( data ),
        "block_sha256"   : hashlib.sha256( data ).hexdigest(),
        "block_headline" : headline,
    }


def build_receipt_dict( *, session_id, persona, tmux_session, memento_path,
                        memento_written_at, repo_root, booted_at,
                        memento_persona=None, block=None, block_error=None ):
    """
    Build the receipt body a rehydrated seat writes at SessionStart.

    The slot is classified here, at write time, because only now is the seat's own repo_root known.
    A reader resolving it later would have to guess the repo, and a wrong guess turns a
    mirror read into a clean bill of health.

    Requires:
        - session_id is the seat's session id
        - memento_path is the file the boot path actually opened, or None
        - booted_at is an aware datetime

    The two personas are different fields. `persona` is who the seat thinks it is;
    `memento_persona` is who the record says it belongs to. Every other field here
    describes the file, and a file can be live and current while belonging to
    somebody else. Recording the record's own claim lets the reader ask the one
    question the rest cannot.

    Requires:
        - session_id is the seat's session id
        - memento_path is the file the boot path actually opened, or None
        - memento_persona is the persona that file declares itself to belong to,
          or None when the record does not say
        - booted_at is an aware datetime

    Ensures:
        - returns a JSON-serializable dict carrying identity, the boot stamp, the
          memento path, its written_at stamp, its declared persona, the
          classified slot, and the three block_* measurements
        - memento_slot is SLOT_NONE when no memento resolved
        - the block_* fields describe what was produced, never what was
          received — see describe_block
        - block_error names the exception type when the render raised, and is
          None otherwise. Zero bytes with block_error None is a clean empty
          block; zero bytes with a name is a crash, and the two want different
          fixes
        - never raises
    """
    return {
        "session_id"         : session_id,
        "persona"            : persona,
        "tmux_session"       : tmux_session,
        "booted_at"          : booted_at.isoformat(),
        "memento_path"       : memento_path,
        "memento_written_at" : memento_written_at,
        "memento_persona"    : memento_persona,
        "memento_slot"       : classify_memento_slot( memento_path, repo_root ),
        "repo_root"          : repo_root,
        "block_error"        : block_error,
        **describe_block( block ),
    }


def _resolve_base_dir( base_dir ):
    """
    Resolve the receipt directory.

    Ensures:
        - returns base_dir unchanged when given
        - returns fleet_data_root() (lazily imported, to keep this leaf pure) when None
    """
    if base_dir:
        return base_dir
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root   # lazy: keep the leaf pure
    return str( fleet_data_root() )


def write_boot_receipt( *, session_id, persona=None, tmux_session=None,
                        memento_path=None, memento_written_at=None,
                        memento_persona=None, repo_root=None, base_dir=None,
                        now=None, block=None, block_error=None ):
    """
    Write this seat's boot receipt, best-effort because a boot must never fail on it.

    Called from the rehydrated seat's SessionStart, including the boot where no
    memento resolved. A silent skip there would make "woke but consumed nothing"
    look like "never woke", the distinction this file exists to draw.

    Requires:
        - session_id is a non-empty string — the id is the only key the reader
          has, so no receipt is written without one
        - base_dir is a directory path, or None to resolve fleet_data_root()

    Ensures:
        - writes <base_dir>/<RECEIPT_PREFIX><session_id>.json and returns its path
        - returns None on a missing session_id or any IO failure
        - never raises
    """
    if not session_id:
        return None

    try:
        base = _resolve_base_dir( base_dir )
        os.makedirs( base, exist_ok=True )
        stamp = now if now is not None else datetime.datetime.now().astimezone()
        body  = build_receipt_dict(
            session_id         = session_id,
            persona            = persona,
            tmux_session       = tmux_session,
            memento_path       = memento_path,
            memento_written_at = memento_written_at,
            memento_persona    = memento_persona,
            repo_root          = repo_root,
            booted_at          = stamp,
            block              = block,
            block_error        = block_error,
        )
        path = receipt_path( base, session_id )
        with open( path, "w", encoding="utf-8" ) as fh:
            json.dump( body, fh, indent=2 )
        return path
    except ( OSError, TypeError, ValueError, ImportError ):
        return None


def read_receipt( base_dir, session_id ):
    """
    Read one seat's boot receipt.

    Requires:
        - base_dir is a directory path
        - session_id is the seat's session id

    Ensures:
        - returns the parsed dict, or None when absent/unreadable/not a dict
        - never raises
    """
    try:
        with open( receipt_path( base_dir, session_id ), "r", encoding="utf-8" ) as fh:
            data = json.load( fh )
    except ( OSError, json.JSONDecodeError, ValueError ):
        return None
    return data if isinstance( data, dict ) else None


def _norm( value ):
    """Case-fold a persona name for comparison; a non-string stays None."""
    return value.strip().lower() if isinstance( value, str ) else None


def persona_slugs( value ):
    """
    Every slug a persona name could legitimately have been written as.

    Returns a set because each writer yields a different spelling. The caller reports
    a mismatch only when two such sets are disjoint, meaning no spelling of one is a
    spelling of the other.

    Requires:
        - value is a persona name string, or anything defensively

    Ensures:
        - returns a frozenset of lowercase [a-z0-9-] slugs: the accent-folded
          form, plus the naive form when it differs ("María" -> maria, mar-a)
        - returns an empty frozenset for a non-string, an empty string, or a name
          with no alphanumerics at all (an emoji-only persona) — an unknowable
          identity must never be reported as a mismatched one
        - never raises
        - the set holds both spellings because `memento_io.slugify` does not fold
          accents ("María" becomes "mar-a") while `register_session._persona_slugs`
          folds first and produces "maria"; both spellings name the same seat
        - reducing each side to one canonical slug would report a live roster persona
          as an impostor each time that persona re-spun, and a check that cries wolf
          on a real seat gets switched off
    """
    lowered = _norm( value )
    if not lowered:
        return frozenset()

    # Accent-fold first: NFKD splits a letter from its accent, dropping the
    # combining marks leaves the base letter. This is the form writers produce.
    folded = "".join( ch for ch in unicodedata.normalize( "NFKD", lowered )
                      if not unicodedata.combining( ch ) )

    out = set()
    for candidate in ( folded, lowered ):
        slug = re.sub( r"[^a-z0-9]+", "-", candidate ).strip( "-" )
        if slug:
            out.add( slug )
    return frozenset( out )


def find_receipt_by_identity( base_dir, *, persona=None, tmux_session=None, since=None ):
    """
    Find a successor's receipt when its session id is not known in advance.

    A self_respin keeps its session id, so its caller can read by id. A dismiss-then-spawn
    re-spin cannot, because the successor mints a new id. The persona and the tmux session
    name do carry across, so this matches on those.

    Requires:
        - base_dir is a directory path
        - at least one of persona / tmux_session identifies the seat; with both
          absent nothing is matched, because a blank query must never return some
          arbitrary seat's receipt as if it were the successor's
        - since is an aware datetime, or None for no recency floor

    Ensures:
        - returns the newest matching receipt dict booted at/after `since`, or None
        - a receipt with an unreadable booted_at is skipped when `since` is set,
          because it cannot be shown to postdate the re-spin
        - never raises
    """
    if not persona and not tmux_session:
        return None

    best     = None
    best_key = None
    try:
        paths = sorted( glob.glob( os.path.join( base_dir, f"{RECEIPT_PREFIX}*.json" ) ) )
    except OSError:                                # pragma: no cover - glob on an unreadable dir
        return None

    for path in paths:
        try:
            with open( path, "r", encoding="utf-8" ) as fh:
                data = json.load( fh )
        except ( OSError, json.JSONDecodeError, ValueError ):
            continue
        if not isinstance( data, dict ):
            continue
        if persona and _norm( data.get( "persona" ) ) != _norm( persona ):
            continue
        if tmux_session and data.get( "tmux_session" ) != tmux_session:
            continue

        booted = _parse_iso( data.get( "booted_at" ) )
        if since is not None and ( booted is None or booted < since ):
            continue
        key = booted if booted is not None else datetime.datetime.min.replace( tzinfo=datetime.timezone.utc )
        if best_key is None or key > best_key:
            best, best_key = data, key

    return best


# ---------------------------------------------------------------------------
# The verdict — pure
# ---------------------------------------------------------------------------

def receipt_is_misplaced( path, correct_base_dir ):
    """
    Say whether this receipt file sits outside the directory the check reads.

    Mirrors `heartbeat_hold.hold_is_misplaced`, down to the fail-safe, because the
    two families share one defect and should share one shape.

    Requires:
        - path is a path-like or string; correct_base_dir is the directory the
          finder globs, or None when it could not be resolved

    Ensures:
        - True iff `path`'s immediate parent is not `correct_base_dir`
        - fail-safe: an unresolvable base dir or path returns False — the detector
          never over-flags a receipt it cannot place, because a false "misplaced"
          sends a manager to fix a writer that is working
        - the predicate tests the parent, never ancestry: `find_receipt_by_identity`
          globs `<base_dir>/<prefix>*.json` non-recursively, so a receipt one level
          deeper inside the correct root is as invisible as one in a sibling repo,
          and an ancestry test would call that nested file correctly placed
        - measured: a receipt at <base>/nested/ returns None from the finder just
          as a receipt in a sibling root does
    """
    if correct_base_dir is None:
        return False
    try:
        return Path( path ).resolve().parent != Path( correct_base_dir ).resolve()
    except Exception:
        return False


def find_misplaced_receipts( correct_base_dir, *, persona=None, tmux_session=None,
                             since=None, search_root=None, glob_fn=None ):
    """
    Find receipts for this seat that exist but sit where the finder cannot see them.

    It searches recursively, because that is the only way to see this defect. The
    defect is the finder's non-recursive glob, so a detector using the same glob
    would find nothing and report a clean result.

    Requires:
        - correct_base_dir is the directory `find_receipt_by_identity` globs
        - at least one of persona / tmux_session identifies the seat; with both
          absent nothing is returned, matching find_receipt_by_identity's own rule
          that a blank query must never claim some arbitrary seat's receipt
        - search_root defaults to the parent of correct_base_dir — the zone that
          holds the sibling roots a receipt actually lands in when it goes astray
        - since is an aware datetime, or None for no recency floor

    Ensures:
        - returns a list of {"path", "receipt"} dicts, oldest path first, for every
          matching receipt whose immediate parent is not correct_base_dir
        - a receipt the finder would have found is never included — this reports
          only what the existing read is blind to
        - never raises; an unreadable tree yields []
    """
    if not persona and not tmux_session:
        return []
    if correct_base_dir is None:
        return []

    try:
        base = Path( correct_base_dir ).resolve()
    except Exception:
        return []

    root = search_root if search_root is not None else base.parent

    try:
        if glob_fn is not None:
            paths = sorted( glob_fn( root ) )
        else:
            paths = sorted( glob.glob( os.path.join( str( root ), "**",
                                                     f"{RECEIPT_PREFIX}*.json" ),
                                       recursive=True ) )
    except OSError:                                # pragma: no cover - unreadable tree
        return []

    found = []
    for path in paths:
        if not receipt_is_misplaced( path, base ):
            continue                               # the existing read already sees it
        try:
            with open( path, "r", encoding="utf-8" ) as fh:
                data = json.load( fh )
        except ( OSError, json.JSONDecodeError, ValueError ):
            continue
        if not isinstance( data, dict ):
            continue
        if persona and _norm( data.get( "persona" ) ) != _norm( persona ):
            continue
        if tmux_session and _norm( data.get( "tmux_session" ) ) != _norm( tmux_session ):
            continue
        if since is not None:
            booted = _parse_iso( data.get( "booted_at" ) )
            if booted is None or booted < since:
                continue
        found.append( { "path": path, "receipt": data } )

    return found


def classify_wake( receipt, *, fired_at, now,
                   deadline_seconds        = DEFAULT_WAKE_DEADLINE_SECONDS,
                   expect_memento          = True,
                   max_memento_age_seconds = DEFAULT_MAX_MEMENTO_AGE_SECONDS,
                   session_id              = None,
                   persona                 = None,
                   tmux_session            = None ):
    """
    Decide what happened to a successor. Pure — no IO, no clock of its own.

    The order of the tests is the design. "Did it wake" is asked first because
    every later question presumes a boot: a seat that never came up cannot have
    read the wrong file. Then the seed questions, cheapest first.

    Requires:
        - receipt is the successor's boot-receipt dict, or None when none exists
        - fired_at is an aware datetime — when the re-spin fired
        - now is an aware datetime
        - deadline_seconds is how long past fired_at a receipt may take to appear
        - expect_memento is False for a re-spin seeded with no memento at all

    Ensures:
        - `PENDING` (no alarm) when no usable receipt yet and now < fired_at + deadline
        - DEAD_NO_WAKE (alarm) when no receipt and the deadline has passed
        - a receipt dated at/before fired_at is treated as the predecessor's and
          so as no receipt at all — the guard that stops a self_respin's own
          pre-clear boot from greening its successor's check
        - MALFORMED_RECEIPT (alarm) when fired_at/now is missing, or a present
          receipt carries an unreadable booted_at once past the deadline
        - SEED_NOT_CONSUMED (alarm) when it woke, expect_memento, and none resolved
        - WRONG_PERSONA (alarm) when the record it read declares a persona that
          differs from the seat's own — checked before slot and age, because a
          record can be live and current and still be somebody else's
        - a mismatch is reported only when both personas yield slugs and no
          spelling of one is a spelling of the other; either side unknown is
          unprovable, and an unprovable mismatch is not an alarm
        - STALE_SLOT (alarm) when it woke and read a slot outside the live family
        - STALE_MEMENTO (alarm) when it woke, read a live slot, and that record's
          written_at is older than max_memento_age_seconds
        - `RETURNED` (no alarm) otherwise
        - a live-slot record with no written_at stamp is `RETURNED`, not stale: an
          undated record is unmeasurable, and inventing an alarm out of an absent
          measurement is how a check earns its way into being ignored
        - never raises
    """
    # Normalize FIRST. A non-dict receipt (a truncated write read back as a bare
    # string, say) must degrade to "no receipt", not blow up inside a check whose
    # whole job is to speak up when something is wrong.
    body = receipt if isinstance( receipt, dict ) else {}
    sid  = session_id if session_id is not None else body.get( "session_id" )
    who  = persona    if persona    is not None else body.get( "persona" )

    def _v( verdict, reason, is_alarm, memento_path=None ):
        return WakeAssessment( session_id=sid, persona=who, verdict=verdict,
                               reason=reason, is_alarm=is_alarm, memento_path=memento_path,
                               tmux_session=tmux_session )

    if fired_at is None or now is None:
        return _v( WakeVerdict.MALFORMED_RECEIPT,
                   "cannot judge the wake: fired_at or now is missing", True )

    deadline = fired_at + datetime.timedelta( seconds=deadline_seconds )
    past_due = now >= deadline

    if not isinstance( receipt, dict ):
        if past_due:
            return _v( WakeVerdict.DEAD_NO_WAKE,
                       f"no boot receipt {int( ( now - fired_at ).total_seconds() )}s after the re-spin fired "
                       f"(deadline {deadline_seconds}s) — the successor never reached a prompt", True )
        return _v( WakeVerdict.PENDING, "no receipt yet, still inside the wake window", False )

    booted = _parse_iso( receipt.get( "booted_at" ) )
    if booted is None:
        if past_due:
            return _v( WakeVerdict.MALFORMED_RECEIPT,
                       "a boot receipt exists but its booted_at is missing, naive, or unparseable, "
                       "so it cannot be shown to postdate the re-spin", True,
                       memento_path=receipt.get( "memento_path" ) )
        return _v( WakeVerdict.PENDING, "receipt present but undated, still inside the wake window", False )

    if booted <= fired_at:
        if past_due:
            return _v( WakeVerdict.DEAD_NO_WAKE,
                       f"the only boot receipt is dated {receipt.get( 'booted_at' )}, at or before the re-spin "
                       f"fired — it belongs to the PREDECESSOR, so no successor has booted", True )
        return _v( WakeVerdict.PENDING,
                   "only the predecessor's receipt so far, still inside the wake window", False )

    path = receipt.get( "memento_path" )
    slot = receipt.get( "memento_slot" )

    if expect_memento and not path:
        return _v( WakeVerdict.SEED_NOT_CONSUMED,
                   "the successor booted but resolved NO memento — it came up blank on a re-spin "
                   "that was supposed to hand it its own prior state", True )

    if path:
        # IS IT YOURS? Asked BEFORE the slot and age questions, and that order is
        # the point. Every other test here is about the FILE — is it live, is it
        # current — and a file can be both while belonging to somebody else. That
        # case used to walk the whole ladder and come out RETURNED, so the one
        # failure where the successor is confidently and coherently wrong was the
        # one failure that wore a green. A manager who reads RETURNED stops
        # looking, which is worse than no check at all.
        #
        # Only a mismatch that can be PROVEN is reported: both names must reduce
        # to a slug. A record that does not say whose it is, or a seat with no
        # allocated persona, cannot be shown to be crossed — and inventing an
        # alarm out of an absent measurement is how a check earns its way into
        # being ignored (the same rule the undated-record case follows below).
        mine   = persona_slugs( who )
        theirs = persona_slugs( body.get( "memento_persona" ) )
        if mine and theirs and mine.isdisjoint( theirs ):
            return _v( WakeVerdict.WRONG_PERSONA,
                       f"the successor booted as '{who}' and read a memento belonging to "
                       f"'{body.get( 'memento_persona' )}' — it has rehydrated somebody else's "
                       f"branches, rows and manager, and every other check on this record passes",
                       True, memento_path=path )

        if slot not in LIVE_SLOTS:
            return _v( WakeVerdict.STALE_SLOT,
                       f"the successor read its memento from the '{slot}' slot, not the live record — "
                       f"a copy there goes stale on its own schedule", True, memento_path=path )

        written = _parse_iso( receipt.get( "memento_written_at" ) )
        if written is not None:
            age = ( now - written ).total_seconds()
            if age > max_memento_age_seconds:
                return _v( WakeVerdict.STALE_MEMENTO,
                           f"the successor read a live-slot memento written {int( age )}s ago "
                           f"(limit {max_memento_age_seconds}s) — a record from a previous cycle",
                           True, memento_path=path )

    return _v( WakeVerdict.RETURNED,
               "the successor booted after the re-spin and read a live, current memento", False,
               memento_path=path )


def render_alert( assessment, *, fired_at=None ):
    """
    Compose the line the manager is shouted at with.

    Requires:
        - assessment is a WakeAssessment

    The identity clause has three states, not two. It used to render `persona or
    "unknown persona"` and `session_id or "unknown session"`. On the live path the
    arm supplies neither, only `tmux_session`, and a no-receipt DEAD_NO_WAKE has no
    receipt to fall back to, so every such alert read "unknown persona / unknown
    session". A string that never varies reads as evidence about the arm, which
    misleads the reader, so the three states now render as different words:
      - identity known: "<persona> / <session id>"
      - identity not supplied: names the tmux session it was armed on and says
        that no persona or session id reached the watch; the tmux name is the one
        identity that survives a re-spin
      - nothing known at all: says so outright, rather than dressing an empty
        hand as an unknown seat

    Requires:
        - assessment is a WakeAssessment

    Ensures:
        - names the verdict, the identity, the reason, and — when one is known — the
          memento file the seat actually opened
        - the three identity states above render as three distinguishable strings, so
          a reader can tell "we were never told who this is" from "we were told and
          it is unknown"
        - never raises
    """
    who  = assessment.persona
    sid  = assessment.session_id
    tmux = assessment.tmux_session

    if who or sid:
        # At least one real identity. Keep the long-standing shape, and keep naming
        # the missing half as unknown — here that genuinely IS an unknown, because
        # something identified this seat and this field was not it.
        subject = f"{who or 'unknown persona'} / {sid or 'unknown session'}"
    elif tmux:
        subject = ( f"the seat armed as tmux session {tmux} — no persona or session id "
                    f"reached the watch, so this line cannot name who it was" )
    else:
        subject = "a seat the watch was given NO identity for — not an unknown seat, an unnamed one"

    when = f" (re-spin fired {fired_at.isoformat()})" if fired_at is not None else ""
    tail = f" Memento it opened: {assessment.memento_path}." if assessment.memento_path else ""
    return (
        f"RE-SPIN WAKE CHECK — {assessment.verdict.value} for {subject}{when}. "
        f"{assessment.reason}.{tail} "
        f"The seat will read as IDLE rather than broken, so nothing else will alarm on it."
    )


# ---------------------------------------------------------------------------
# The bounded watch — polls, then shouts
# ---------------------------------------------------------------------------

def check_respin_wake( *, fired_at, session_id=None, persona=None, tmux_session=None,
                       base_dir=None, deadline_seconds=DEFAULT_WAKE_DEADLINE_SECONDS,
                       expect_memento=True,
                       max_memento_age_seconds=DEFAULT_MAX_MEMENTO_AGE_SECONDS,
                       poll_interval_seconds=DEFAULT_POLL_INTERVAL_SECONDS,
                       now_fn=None, sleep_fn=None, read_fn=None ):
    """
    Poll for the successor's boot receipt until it settles or the deadline passes.

    Requires:
        - fired_at is an aware datetime
        - session_id identifies a same-seat re-spin (self_respin), or
          persona/tmux_session identify a dismiss-then-spawn successor
        - base_dir is a directory path, or None to resolve fleet_data_root()

    Ensures:
        - returns the first settled WakeAssessment (anything but `PENDING`), or the
          post-deadline assessment when it never settles
        - sleeps at most poll_interval_seconds and never past the deadline — a
          check that outlives its own window is a check nobody waits for
        - never raises
    """
    now_fn   = now_fn   if now_fn   is not None else ( lambda: datetime.datetime.now().astimezone() )
    sleep_fn = sleep_fn if sleep_fn is not None else time.sleep

    base = _resolve_base_dir( base_dir )

    def _read():
        if read_fn is not None:
            return read_fn()
        if session_id:
            return read_receipt( base, session_id )
        return find_receipt_by_identity( base, persona=persona, tmux_session=tmux_session, since=fired_at )

    deadline = fired_at + datetime.timedelta( seconds=deadline_seconds )

    while True:
        now        = now_fn()
        assessment = classify_wake(
            _read(), fired_at=fired_at, now=now,
            deadline_seconds        = deadline_seconds,
            expect_memento          = expect_memento,
            max_memento_age_seconds = max_memento_age_seconds,
            session_id              = session_id,
            persona                 = persona,
            tmux_session            = tmux_session,
        )
        if assessment.verdict is not WakeVerdict.PENDING:
            # THE ONE PLACE THE TWO FAILURES ARE CONFUSABLE. DEAD_NO_WAKE means the
            # finder saw nothing — which is equally true of a seat that never woke
            # and of one that woke and wrote its receipt somewhere the finder does
            # not look. Only here is the extra scan worth its cost, and only here
            # does it tell the reader something the verdict cannot.
            #
            # The verdict and the alarm are left EXACTLY as classify_wake set them.
            # Deciding what to DO about a misplaced receipt is an operator call, not
            # this function's; all it does is stop the reader having to guess which
            # of two failures they are looking at.
            if assessment.verdict is WakeVerdict.DEAD_NO_WAKE:
                assessment.misplaced = find_misplaced_receipts(
                    base, persona=persona, tmux_session=tmux_session, since=fired_at )
            return assessment
        if now >= deadline:
            # classify_wake cannot return PENDING past the deadline, but a clock
            # that steps backward between the two reads could land us here. Stop
            # rather than spin — a watch that never exits is a leaked thread.
            return assessment
        sleep_fn( min( poll_interval_seconds, max( 0.0, ( deadline - now ).total_seconds() ) ) )


def verify_respin_wake( *, alert_fn, fired_at, **kwargs ):
    """
    Run the bounded watch and call alert_fn when the verdict is an alarm.

    The defect is that nobody was told a successor died, not the death itself. Delivery is
    injected so the caller picks the rail (a DM to the firing manager in production)
    and the decision tree stays testable.

    Requires:
        - alert_fn is a callable taking one message string
        - fired_at is an aware datetime
        - remaining kwargs are check_respin_wake's

    Ensures:
        - returns the final WakeAssessment
        - calls alert_fn exactly once when the verdict is an alarm, never otherwise
        - an alert_fn that raises is swallowed: a failed shout must not also cost
          the caller the verdict it was waiting on
    """
    assessment = check_respin_wake( fired_at=fired_at, **kwargs )
    if assessment.is_alarm:
        try:
            alert_fn( render_alert( assessment, fired_at=fired_at ) )
        except Exception:
            pass
    return assessment


def start_wake_watch( *, alert_fn, fired_at, thread_factory=None, **kwargs ):
    """
    Run `verify_respin_wake` on a daemon thread so the caller returns immediately.

    A manager that fired a re-spin must not block for ninety seconds to learn it
    worked. The watch has to be free, or it will be skipped.

    Requires:
        - alert_fn is a callable taking one message string
        - fired_at is an aware datetime
        - thread_factory is an injected threading.Thread stand-in, or None

    Ensures:
        - starts a daemon thread and returns it, without waiting
        - an exception inside the watch is swallowed by the thread body
        - never raises
    """
    def _body():
        try:
            verify_respin_wake( alert_fn=alert_fn, fired_at=fired_at, **kwargs )
        except Exception:
            pass

    factory = thread_factory if thread_factory is not None else threading.Thread
    thread  = factory( target=_body, daemon=True, name="RespinWakeCheck" )
    thread.start()
    return thread


def arm_watches_for_spawn( spawn_result, *, alert_fn, fired_at, start_fn=None,
                           base_dir_for=None, **kwargs ):
    """
    Arm one wake watch per seat a re-spin spawn actually launched.

    Requires:
        - spawn_result is the dict session_spawner.spawn_sessions returned
        - alert_fn is the shout rail; fired_at is an aware datetime
        - start_fn is an injected start_wake_watch stand-in, or None
        - base_dir_for is an injected callable taking one spawn record and
          returning that seat's data root, or None to keep today's behaviour

    The resolver is injected, never imported. Resolving a project name to a repo
    root lives in `lupin_mcp.session_spawner`, and importing it here would drag
    requests, urllib3, certifi and websockets into a module the :8001 arbiter
    loads on a light venv. There a missing import kills a worker thread while the
    process stays `active` and /health still answers 200. This module keeps even
    `fleet_data_root` behind a function-local import for the same reason, so the
    caller resolves and this leaf only forwards.

    Ensures:
        - arms a watch only for records whose status is "spawned" — a record that
          failed to launch is already loud at the call site, and a wake alarm on
          top of it would report the same thing twice under a different name
        - watches on the tmux session_name, which is the only identity that
          survives dismiss-then-spawn (the successor mints its own session id)
        - each watch reads the seat's own data root when base_dir_for supplies
          one — the boot-receipt writer already keys on the spawned seat's repo
          (register_session, `fleet_data_root( repo_root )`), so a reader keyed on
          the firing manager's ambient LUPIN_ROOT looks in the wrong directory for
          any cross-repo spawn and reports DEAD_NO_WAKE for a seat that woke fine
        - a base_dir_for that returns None, or raises, leaves that record on the
          ambient default: a resolver failure must never cost the watch itself
        - an explicit base_dir in kwargs wins over base_dir_for — a caller naming
          one directory outright is not overridden by a per-record guess
        - returns the list of started watch handles
        - a spawn_result of the wrong shape arms nothing rather than raising
    """
    starter = start_fn if start_fn is not None else start_wake_watch
    if not isinstance( spawn_result, dict ):
        return []

    started = []
    for record in spawn_result.get( "spawned" ) or []:
        if not isinstance( record, dict ):
            continue
        if record.get( "status" ) != "spawned":
            continue
        name = record.get( "session_name" )
        if not name:
            continue
        per_record = dict( kwargs )
        if base_dir_for is not None and "base_dir" not in per_record:
            try:
                resolved = base_dir_for( record )
            except Exception:
                resolved = None          # a resolver failure must not cost the watch
            if resolved:
                per_record[ "base_dir" ] = resolved
        started.append( starter( alert_fn=alert_fn, fired_at=fired_at,
                                 tmux_session=name, **per_record ) )
    return started


def quick_smoke_test():
    """Exercise the decision tree against fakes — no disk, no clock."""
    import cosa.utils.util as du

    du.print_banner( "respin_wake_check smoke test", prepend_nl=True )

    fired = datetime.datetime( 2026, 8, 21, 21, 26, tzinfo=datetime.timezone.utc )
    later = fired + datetime.timedelta( seconds=200 )
    woke  = ( fired + datetime.timedelta( seconds=5 ) ).isoformat()

    cases = [
        ( "no receipt, past deadline (Pocholo)", None, WakeVerdict.DEAD_NO_WAKE ),
        ( "read the mirror copy (Krishna)",
          { "booted_at": woke, "memento_slot": SLOT_MIRROR,
            "memento_path": "/home/x/.claude/mementos/lupin/.claude-memento-krishna-1234abcd.md" },
          WakeVerdict.STALE_SLOT ),
        ( "woke blank, no memento",
          { "booted_at": woke, "memento_slot": SLOT_NONE, "memento_path": None },
          WakeVerdict.SEED_NOT_CONSUMED ),
        ( "healthy return",
          { "booted_at": woke, "memento_slot": SLOT_ROOT,
            "memento_path": "/repo/.claude-memento-maya-9e0b977d.md",
            "memento_written_at": fired.isoformat() },
          WakeVerdict.RETURNED ),
    ]

    ok = 0
    for label, receipt, expected in cases:
        got  = classify_wake( receipt, fired_at=fired, now=later )
        hit  = got.verdict is expected
        ok  += 1 if hit else 0
        print( f"  {'✓' if hit else '✗'} {label:34s} -> {got.verdict.value}" )

    print( f"✓ respin_wake_check smoke test complete ({ok}/{len( cases )})" )


if __name__ == "__main__":
    quick_smoke_test()
