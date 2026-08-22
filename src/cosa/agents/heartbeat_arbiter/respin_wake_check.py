"""
Re-spin wake check — make a re-spin that loses its wake FAIL LOUD (row b0570b67).

WHY THIS EXISTS. On 2026-08-21 Pocholo's self_respin fired its `/clear` at 21:26
and the wake prompt never arrived. The seat sat at an empty prompt for twenty
minutes until Cheech read the pane and typed the wake by hand. The same evening,
Krishna's successor rehydrated from a STALE copy under ~/.claude/mementos rather
than the live record. Two different ways to produce a successor that is
technically alive and actually useless — and BOTH are silent. The seat looks
IDLE rather than BROKEN, so nothing alarms and no peer notices.

RICK RULED THE SHAPE (2026-08-22, three options offered, genuine keypress): do
NOT chase why the wake drops. Verify the successor actually came up, and shout
if it did not. The underlying drop stays in the code and that is an accepted
trade, not an oversight.

THE ORACLE, and why it is ONE artifact for TWO failures. The question "did it
wake?" and the question "did it read the right memento?" have the same witness:
the file the rehydrated seat actually opened at boot. So the successor writes a
BOOT RECEIPT naming that file, and the check reads it:

  · NO RECEIPT past the deadline        ⇒ it never woke                   (Pocholo)
  · RECEIPT naming a mirror-slot copy   ⇒ it woke and read the wrong file (Krishna)
  · RECEIPT naming a long-stale record  ⇒ it woke onto old state
  · RECEIPT naming nothing at all       ⇒ it woke but consumed no seed
  · RECEIPT naming a fresh root record  ⇒ RETURNED

CONSUMER-WRITTEN, ALWAYS. The receipt is written by the REHYDRATED SEAT's own
SessionStart, never by the thing that fired the re-spin. A receipt written by
the injector would prove only that the injector reached its write line —
`tmux send-keys` has no ingestion feedback, so an injector-written proof
certifies itself. Only a seat that genuinely booted can leave this file. Same
discipline as the self_respin wake proof next door
(cosa.agents.heartbeat_arbiter.self_respin_observer).

WHY THE PREDECESSOR'S OWN RECEIPT CANNOT GREEN THE CHECK. A self_respin keeps
its session id, so the seat's PRE-clear boot already left a receipt under that
id. The check therefore never asks "does a receipt exist" — it asks "is there a
receipt dated AFTER the re-spin fired". `fired_at` is the whole guard.

WHERE THE SHOUT GOES. To the manager who fired the re-spin, by DM — not into a
log. The entire defect is that nobody was told; a check that writes a line
nobody reads has reproduced the bug it was built to catch. Delivery is an
injected `alert_fn` seam so the rail is the caller's choice and the decision
tree stays unit-provable.

PURITY. `classify_wake` is a pure function of (receipt, fired_at, now, policy) —
stdlib only, no IO. Every side-effecting seam (disk read, clock, sleep, alert
delivery) is injectable.
"""

import datetime
import glob
import json
import os
import threading
import time

from dataclasses import dataclass
from enum        import Enum


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
    MALFORMED_RECEIPT = "MALFORMED_RECEIPT"  # ALARM: a receipt exists but its stamps are unreadable


@dataclass
class WakeAssessment:
    """One successor's verdict, the human-readable reason, and the alarm flag.

    `memento_path` rides along even on an alarm because the first thing a manager
    reading a STALE_SLOT wants is which file the seat actually opened — an alarm
    that withholds it asks the reader to go find out."""
    session_id   : "str | None"
    persona      : "str | None"
    verdict      : WakeVerdict
    reason       : str
    is_alarm     : bool
    memento_path : "str | None" = None


def _parse_iso( value ):
    """
    Parse an ISO-8601 stamp to an AWARE datetime, or None.

    A NAIVE stamp is rejected rather than assumed-local: this check compares it
    against `fired_at` to decide whether a receipt predates the re-spin, and a
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
        - the repo tests run FIRST, so a repo that happens to live under the
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


def build_receipt_dict( *, session_id, persona, tmux_session, memento_path,
                        memento_written_at, repo_root, booted_at ):
    """
    Build the receipt body a rehydrated seat writes at SessionStart.

    The slot is classified HERE, at write time, because this is the only moment
    the seat's own repo_root is known for certain. A reader resolving the slot
    later would have to guess which repo the seat sat in, and a wrong guess turns
    a mirror read into a clean bill of health.

    Requires:
        - session_id is the seat's session id
        - memento_path is the file the boot path actually opened, or None
        - booted_at is an aware datetime

    Ensures:
        - returns a JSON-serializable dict carrying identity, the boot stamp, the
          memento path, its written_at stamp, and the classified slot
        - memento_slot is SLOT_NONE when no memento resolved
        - never raises
    """
    return {
        "session_id"         : session_id,
        "persona"            : persona,
        "tmux_session"       : tmux_session,
        "booted_at"          : booted_at.isoformat(),
        "memento_path"       : memento_path,
        "memento_written_at" : memento_written_at,
        "memento_slot"       : classify_memento_slot( memento_path, repo_root ),
        "repo_root"          : repo_root,
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
                        repo_root=None, base_dir=None, now=None ):
    """
    Write this seat's boot receipt. Best-effort — a boot must never fail on it.

    Called from the rehydrated seat's SessionStart, INCLUDING the boot where no
    memento resolved. A silent skip on that path would make "woke but consumed
    nothing" indistinguishable from "never woke", which is the whole distinction
    this file exists to draw.

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
            repo_root          = repo_root,
            booted_at          = stamp,
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


def find_receipt_by_identity( base_dir, *, persona=None, tmux_session=None, since=None ):
    """
    Find a successor's receipt when its session id is NOT known in advance.

    A self_respin keeps its session id, so its caller can read by id. A re-spin
    done as dismiss-then-spawn cannot: the successor mints a brand-new id the
    manager never sees. What DOES carry across that boundary is the persona and
    the tmux session name, so those are what this matches on.

    Requires:
        - base_dir is a directory path
        - at least one of persona / tmux_session identifies the seat; with both
          absent nothing is matched, because a blank query must never return some
          arbitrary seat's receipt as if it were the successor's
        - since is an aware datetime, or None for no recency floor

    Ensures:
        - returns the NEWEST matching receipt dict booted at/after `since`, or None
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

def classify_wake( receipt, *, fired_at, now,
                   deadline_seconds        = DEFAULT_WAKE_DEADLINE_SECONDS,
                   expect_memento          = True,
                   max_memento_age_seconds = DEFAULT_MAX_MEMENTO_AGE_SECONDS,
                   session_id              = None,
                   persona                 = None ):
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
        - PENDING (no alarm) when no usable receipt yet and now < fired_at + deadline
        - DEAD_NO_WAKE (ALARM) when no receipt and the deadline has passed
        - a receipt dated at/before fired_at is treated as the PREDECESSOR's and
          so as no receipt at all — the guard that stops a self_respin's own
          pre-clear boot from greening its successor's check
        - MALFORMED_RECEIPT (ALARM) when fired_at/now is missing, or a present
          receipt carries an unreadable booted_at once past the deadline
        - SEED_NOT_CONSUMED (ALARM) when it woke, expect_memento, and none resolved
        - STALE_SLOT (ALARM) when it woke and read a slot outside the live family
        - STALE_MEMENTO (ALARM) when it woke, read a live slot, and that record's
          written_at is older than max_memento_age_seconds
        - RETURNED (no alarm) otherwise
        - a live-slot record with NO written_at stamp is RETURNED, not stale: an
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
                               reason=reason, is_alarm=is_alarm, memento_path=memento_path )

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

    Ensures:
        - names the verdict, the persona/session, the reason, and — when one is
          known — the memento file the seat actually opened
        - never raises
    """
    who  = assessment.persona    or "unknown persona"
    sid  = assessment.session_id or "unknown session"
    when = f" (re-spin fired {fired_at.isoformat()})" if fired_at is not None else ""
    tail = f" Memento it opened: {assessment.memento_path}." if assessment.memento_path else ""
    return (
        f"RE-SPIN WAKE CHECK — {assessment.verdict.value} for {who} / {sid}{when}. "
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
        - session_id identifies a same-seat re-spin (self_respin), OR
          persona/tmux_session identify a dismiss-then-spawn successor
        - base_dir is a directory path, or None to resolve fleet_data_root()

    Ensures:
        - returns the FIRST settled WakeAssessment (anything but PENDING), or the
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
        )
        if assessment.verdict is not WakeVerdict.PENDING:
            return assessment
        if now >= deadline:
            # classify_wake cannot return PENDING past the deadline, but a clock
            # that steps backward between the two reads could land us here. Stop
            # rather than spin — a watch that never exits is a leaked thread.
            return assessment
        sleep_fn( min( poll_interval_seconds, max( 0.0, ( deadline - now ).total_seconds() ) ) )


def verify_respin_wake( *, alert_fn, fired_at, **kwargs ):
    """
    Run the bounded watch and SHOUT on failure.

    The shout is the point. The re-spin defect is not that a successor died — it
    is that nobody was told, so the seat read as idle for twenty minutes.
    Delivery is injected so the caller picks the rail (a DM to the firing manager
    in production) and the decision tree stays testable.

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

    A manager that fired a re-spin must not block ninety seconds to learn it
    worked — the watch has to be free, or it will be skipped.

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


def arm_watches_for_spawn( spawn_result, *, alert_fn, fired_at, start_fn=None, **kwargs ):
    """
    Arm one wake watch per seat a re-spin spawn actually launched.

    Requires:
        - spawn_result is the dict session_spawner.spawn_sessions returned
        - alert_fn is the shout rail; fired_at is an aware datetime
        - start_fn is an injected start_wake_watch stand-in, or None

    Ensures:
        - arms a watch ONLY for records whose status is "spawned" — a record that
          failed to launch is already loud at the call site, and a wake alarm on
          top of it would report the same thing twice under a different name
        - watches on the tmux session_name, which is the only identity that
          survives dismiss-then-spawn (the successor mints its own session id)
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
        started.append( starter( alert_fn=alert_fn, fired_at=fired_at,
                                 tmux_session=name, **kwargs ) )
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
