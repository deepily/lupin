"""
reap_memento.py — memento coordination for the reap path (row 0a36d83d).

THE DEFECT THIS CLOSES: `dismiss_sessions( write_memento=True )` reported success
and wrote NO memento — the flag travelled into the result dict and nowhere else.
It failed 3-for-3 in production because the feature was never implemented: each
of the two layers' docstrings named the OTHER as the owner of the pre-kill write,
and neither did it. A reap that silently writes nothing is indistinguishable from
success at the call site, so a manager reaps believing continuity was preserved
and only learns otherwise when the re-spun seat boots empty.

WHAT THIS MODULE DOES (the manager side of the fix): BEFORE any seat is killed,
for each seat the manager asked to preserve, PROVE a fresh + complete memento is
on disk — and if one is not, DM the still-alive child to write one and WAIT
(bounded) for it to appear. Every seat gets an EXPLICIT per-seat outcome; a seat
that produced no memento fails VISIBLY (never a silent success — that IS the bug).

THE MANAGER SIDE CANNOT AUTHOR A CHILD'S MEMENTO — only the child can, from its
own context. So this coordinator's job is ASK-then-VERIFY-on-disk, never write.
The child writes to the derivable bare slot `io/mementos/<persona-slug>.md`
(memento-management.md §3.2, "stable, one slot per persona") using `/plan-memento`
/ memento_io, which stamps a machine-readable header as line 1 of every record:

    <!-- memento-record: persona=<name> session_id=<sid8> written_at=<ISO> slot=<io|root> -->

THE VERIFY PREDICATE IS ALL-OR-ASK (Mr. Radio, row 0a36d83d review). A memento
is "verified" (skip the DM) ONLY when it clears EVERY gate: byte floor (complete,
not a zero-byte/header-only stub), header present + parseable, header session_id
matches THIS seat (kills the stale prior-holder slot — a re-granted persona name
can point at another session's old memento), and header written_at is aware and
within the freshness window. Any miss — no header, malformed, wrong session, naive
or stale or future-dated timestamp, too small — falls toward ASKING. The header is
SELF-REPORTED, so a parse miss must read as "ask", never "fresh enough": the first
is a cheap duplicate ask, the second resurrects the original silent bug. mtime
NEVER grants a skip (it is defeated by worktree-add/checkout, and io/mementos is
gitignored so git author-date does not apply).

THE FRESHNESS WINDOW IS BOTH A FLOOR AND A CEILING. Floor: it must cover the
manual "prepare for re-spin" latency — a manager DMs the child by hand, the child
writes, replies "ready", and the manager reaps some seconds-to-minutes later; the
memento written at the start of that must still read as fresh at the reap, or we
re-ask needlessly. Ceiling: short enough that a STALE memento from a PRIOR task
does not read as fresh and skip the ask. 24h (memento_io's ENGAGEMENT_WINDOW_HOURS)
answers a different question and is NOT reused here; ~20 min comfortably clears the
floor and rejects prior-task staleness.

NO COLLISION WITH self_respin, and NOT for the reason first supposed. This reap
coordinator reads/asks the `--slot io` slot `io/mementos/<persona-slug>.md`;
self_respin writes and rehydrates from the `--slot root` slot `.claude-memento.md`
(memento-management.md §3: io = spawned-worker, root = self-`/clear`). Different
files — a reap never reads what self_respin verifies, and the child answering a
reap ask never rewrites what self_respin rehydrates from. It is also actor-disjoint:
self_respin is a manager clearing its OWN pane, while a reap kills sessions a
manager SPAWNED — a session is never both at once. The earlier "the verified-skip
suppresses a DM in the gap" story assumed a shared slot and was wrong; the
guarantee here is slot-disjointness + actor-disjointness, which does not depend on
window tuning.

THE TRADE, RECORDED EXPLICITLY (Mr. Radio's instruction): erring toward asking
means a worker can receive a second "prepare for re-spin" it already answered.
That is the cost we buy, and it is the right buy — a duplicate ask is VISIBLE and
CHEAP; a silently-missing memento is the defect this row exists for. So every
ambiguous case asks.

PURITY: every side-effecting seam (clock, file read, DM send, sleep) is injected,
so the whole decision tree — verified / written / timeout / skipped — is unit-
provable with fakes and no live server.
"""

import datetime
import re
import time

from pathlib import Path
from typing  import Any, Callable, Dict, Optional, Tuple

from lupin_mcp.persona_normalization import persona_slug
from lupin_mcp.memento_merge_claim   import refuted_merge_claim


# ── Defaults (the MCP wrapper overrides these from INI at the live call) ───────
DEFAULT_WINDOW_SECONDS    = 20 * 60   # 1200 — freshness floor AND ceiling (see module doc)
DEFAULT_MIN_BYTES         = 1000      # completeness floor — a header-only stub fails this
DEFAULT_ASK_TIMEOUT_SEC   = 45        # total wait after the ask, shared across all asked seats
DEFAULT_POLL_INTERVAL_SEC = 3         # re-check cadence while polling for a written memento

# The trained fleet phrase a manager uses by hand today; children already respond to it.
ASK_BODY = (
    "prepare for re-spin — you are being reaped and your manager asked to preserve "
    "your context. Write your memento NOW to {slot} (via /plan-memento or memento_io), "
    "then reply \"ready for re-spin\". If you do not, your context is lost at kill."
)

_HEADER_RE = re.compile( r"<!--\s*memento-record:(?P<fields>.*?)-->" )

# The pointer line memento_io writes at the top of a bare slot: `<!-- current: <path> -->`.
# The slot io/mementos/<slug>.md is a POINTER, not the record; `current:` names the real
# record file (which carries the completeness bytes and the authoritative header).
_POINTER_CURRENT_RE = re.compile( r"<!--\s*current:\s*(?P<target>\S+)\s*-->" )

# The pointer's self-declaring banner line. A file carrying this banner DECLARES itself a
# pointer (NOT the record); if it also lacks a `current:` line it is a corrupt/hand-mangled
# pointer that names no record to resolve — verify must fail loud rather than fall through
# and parse the pointer's OWN embedded header as if it were a record (Tiffany, case3).
_POINTER_BANNER_RE = re.compile( r"<!--\s*MEMENTO POINTER\b" )


# ── Slot derivation ───────────────────────────────────────────────────────────
def seat_memento_slot( repo_root, persona_name ):
    """
    Requires:
        - repo_root is THE SEAT'S OWN repo (seat_repo_root), never the host's
          LUPIN_ROOT. The parameter was called `project_root` until row 80b930e6,
          which is precisely the reading that let the host's root be passed here for
          every seat in a batch — verifying non-lupin seats against lupin's slot.

    Ensures:
        - returns the derivable bare memento SLOT for a soon-to-be-reaped worker:
          <repo_root>/io/mementos/<persona-slug>.md (memento-management.md §3.2).
          This slot is a POINTER file; resolve_pointer_target follows its `current:`
          line to the record at read time (the pointer is tiny and carries neither the
          completeness bytes nor — reliably — a line-1 header).
        - the slug is accent/punctuation/case-proof via persona_slug
    """
    return Path( repo_root ) / "io" / "mementos" / f"{persona_slug( persona_name )}.md"


def seat_repo_root( ident ):
    """
    The repo a reaped seat ACTUALLY sits in, read from its own bridge `cwd`
    (row 80b930e6).

    Mirrors the cure already adopted for holds — heartbeat_hold.resolve_hold_base_dir,
    whose docstring records the identical defect: "Resolving it from the hardwired
    LUPIN_ROOT (cu.get_project_root) made every NON-lupin session's hold land under
    lupin." A memento slot has the same shape and must not grow a second convention
    for "which repo is this seat in?".

    ⚠️ WHERE IT DELIBERATELY DIVERGES FROM THE HOLD CURE, AND WHY. The hold falls
    back to LUPIN_ROOT when cwd is absent; this returns None instead. For a hold
    that fallback is recoverable — read_hold_resilient searches BOTH roots, so a
    misplaced hold is still found. The reap has no such second look: it renders ONE
    verdict about ONE file, and a guessed root does not fail to find a memento — it
    finds a DIFFERENT persona's live memento sitting at the same-named slot and
    reports on that. Guessing is the defect, so the caller refuses rather than
    guesses (`skipped_no_cwd`).

    Requires:
        - ident is a `_capture_reap_identity` dict, or None

    Ensures:
        - truthy `cwd` in ident → that path as a str (the seat's own repo)
        - missing ident / missing or empty cwd / non-str cwd → None (caller refuses)
        - never raises
    """
    if not isinstance( ident, dict ):
        return None
    cwd = ident.get( "cwd" )
    if isinstance( cwd, str ) and cwd.strip():
        return cwd
    return None


def resolve_pointer_target( slot_path, text ):
    """
    Follow a pointer slot's `current:` line to the record file BESIDE it.

    Ensures:
        - when `text` is a memento POINTER (carries `<!-- current: <path> -->`), returns
          the record path resolved as that value's BASENAME joined to the slot's own
          directory — memento_io keeps the record next to the pointer, and using only
          the basename makes a `current:` value path-traversal-proof.
        - returns None when `text` is empty or not a pointer (the slot IS the record).
        - never raises
    """
    if not text:
        return None
    match = _POINTER_CURRENT_RE.search( text )
    if not match:
        return None
    return Path( slot_path ).parent / Path( match.group( "target" ) ).name


# ── Header parse (pure) ───────────────────────────────────────────────────────
def parse_memento_header( text ):
    """
    Ensures:
        - returns { key: value } parsed from the `<!-- memento-record: k=v ... -->`
          header, searched within the LEADING html-comment block (every blank/`<!-- -->`
          line before the first content line), or {} when absent or malformed
        - never raises
    """
    if not text:
        return {}
    # The header is line 1 in a RECORD but line 5 in a POINTER (behind current:/mirror:
    # comment lines), so a line-0-only search misses the pointer's stamp. Search the
    # leading run of blank + html-comment lines — everything before the first content
    # line (e.g. the `# ` title). A stray `<!-- memento-record: ... -->` deeper in a
    # body, after the title, is still excluded (the original anti-spoof intent).
    header_region = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "" or stripped.startswith( "<!--" ):
            header_region.append( line )
            continue
        break
    match = _HEADER_RE.search( "\n".join( header_region ) )
    if not match:
        return {}
    fields = {}
    for token in match.group( "fields" ).split():
        if "=" in token:
            key, value = token.split( "=", 1 )
            fields[ key.strip() ] = value.strip()
    return fields


def _parse_iso_aware( raw ):
    """Ensures: returns an AWARE datetime parsed from `raw`, or None (naive/bad → None)."""
    try:
        parsed = datetime.datetime.fromisoformat( raw )
    except ( ValueError, TypeError ):
        return None
    return parsed if parsed.tzinfo is not None else None


# ── The verify predicate (pure) — ALL-OR-ASK ──────────────────────────────────
def verify_seat_memento(
    path,
    seat_sid8,
    now,
    *,
    read_text_fn,
    window_seconds = DEFAULT_WINDOW_SECONDS,
    min_bytes      = DEFAULT_MIN_BYTES,
    repo_root      = None,
    merge_claim_fn = None
) -> Tuple[ bool, str ]:
    """
    Prove the memento at `path` is USABLE for reaping seat `seat_sid8` — complete
    AND self-attesting as THIS seat's, written this window. Anything else ASKS.

    Requires:
        - read_text_fn( path ) -> the file text, or None when unreadable
        - seat_sid8 is the 8-char prefix of the seat's session id
        - now is an AWARE datetime

    Ensures:
        - ( True, reason ) ONLY when ALL hold: file readable; byte length >= min_bytes;
          a parseable memento-record header is present; header session_id's 8-char
          prefix == seat_sid8; header written_at is aware, not future, and its age
          <= window_seconds
        - ( False, reason ) otherwise, the reason naming which gate failed — every
          such case means ASK (a self-reported header that cannot be proven fresh is
          never treated as fresh)
        - mtime is NEVER consulted — it cannot grant a skip
        - MERGE-CLAIM GATE (row 0c80f26d): with `repo_root` given, a memento that
          claims work is still unmerged while naming a commit ALREADY in HEAD is
          REFUSED. That line is the one a successor acts on first, and it goes
          stale within minutes because it describes SOMEBODY ELSE'S pending
          action — the manager merges, and the author is no longer running to
          notice. Only a claim the repo can PROVE false refuses; an unresolvable
          sha or a git error is "cannot refute", which allows. `repo_root=None`
          skips the gate entirely, so pure unit verification stays hermetic.
        - never raises
    """
    text = read_text_fn( path )
    if text is None:
        return False, "no memento at slot"
    # The slot is a POINTER — follow `current:` to the record BESIDE it and verify THAT
    # (its bytes, its header). Verifying the tiny pointer instead would fail the byte
    # floor and read the pointer's own stamp, not the record's. A non-pointer slot (the
    # record written directly) has no `current:` line and is verified as-is.
    record_path = resolve_pointer_target( path, text )
    if record_path is not None:
        record_text = read_text_fn( record_path )
        if record_text is None:
            return False, "pointer's `current:` record is unreadable or absent"
        text = record_text
    elif _POINTER_BANNER_RE.search( text ):
        # Banner present but NO `current:` — a corrupt pointer that declares itself not the
        # record yet names none. Fail loud, never parse the pointer's own embedded header.
        return False, "pointer declares itself NOT the record but names no `current:` record — cannot resolve"
    n_bytes = len( text.encode( "utf-8" ) )
    if n_bytes < min_bytes:
        return False, f"memento too small ({n_bytes}B < {min_bytes}B floor) — empty or partial write"

    header = parse_memento_header( text )
    if not header:
        return False, "no parseable memento-record header — header-less or hand-written, cannot prove freshness"

    hdr_sid = header.get( "session_id" )
    if not hdr_sid:
        return False, "memento header carries no session_id"
    # Case-fold both sides: memento_io stamps session_id via short_sid() = .lower()[:8],
    # while the seat's id is un-lowercased here. Standard uuid hex is already lowercase,
    # so this only matters for an uppercase-hex id — where a raw compare would always
    # ASK (fail-safe, just wasteful). Fold so a match is a match.
    if hdr_sid[ :8 ].lower() != ( seat_sid8 or "" )[ :8 ].lower():
        return False, ( f"memento header session_id ({hdr_sid[ :8 ]}) != seat ({( seat_sid8 or '' )[ :8 ]}) "
                        f"— a prior holder's memento in this slot" )

    written = _parse_iso_aware( header.get( "written_at" ) )
    if written is None:
        return False, "memento header written_at is missing, naive, or unparseable"
    age = ( now - written ).total_seconds()
    if age < 0:
        return False, "memento header written_at is future-dated — corrupt or forged stamp"
    if age > window_seconds:
        return False, f"memento is stale ({int( age )}s old > {window_seconds}s window)"

    # MERGE-CLAIM GATE (row 0c80f26d). Everything above proves the file is THIS
    # seat's, complete, and written this window — all of which can be true of a
    # memento whose most consequential line was falsified two minutes ago by the
    # manager doing the merge. Freshness does not imply truth about a value the
    # author does not control.
    if repo_root is not None:
        checker = merge_claim_fn if merge_claim_fn is not None else refuted_merge_claim
        refuted = checker( text, repo_root )
        if refuted:
            return False, refuted

    return True, f"verified: complete, session-matched, fresh ({int( age )}s old)"


# ── Present-vs-absent split (pure) ────────────────────────────────────────────
def classify_slot_presence( slot_path, read_text_fn ):
    """
    The RECOVERABILITY axis that splits a post-ask timeout, three ways.

    Requires:
        - read_text_fn( slot_path ) -> the slot file's text, or None when unreadable

    Ensures:
        - returns "present" when a readable file with NON-whitespace content exists at
          the BARE slot — a manager can OPEN it and read (recoverable).
        - returns "empty" when a file EXISTS but is empty / whitespace-only — a write
          that STARTED and DIED. There is nothing to read, so the recovery ACTION is
          identical to absent and it buckets as absent (Mr. Radio's ruling); the distinct
          label is kept so the reason string can preserve the started-and-died evidence,
          which differs from nobody-ever-wrote-one.
        - returns "absent" when nothing readable is there (never written) — unrecoverable.
        - reads ONLY the slot, never resolving the pointer: a present pointer whose
          record has vanished is STILL a file a manager can open to learn what it named,
          so it classifies "present".
        - never raises
    """
    text = read_text_fn( slot_path )
    if text is None:
        return "absent"
    if text.strip() == "":
        return "empty"
    return "present"


# ── The record's own header (pure) ────────────────────────────────────────────
def slot_record_header( slot_path, read_text_fn ):
    """
    The parsed `memento-record` header of the RECORD this slot names, or {}.

    Factored out because three callers need the same two steps — resolve a pointer
    slot to its record, then parse that record's header — and a fourth reading of
    those bytes by slightly different rules is how two verdicts start disagreeing
    about the same file.

    Requires:
        - read_text_fn( path ) -> the file text, or None when unreadable

    Ensures:
        - resolves a pointer slot to its `current:` record first, exactly as
          verify_seat_memento and classify_slot_owner do
        - returns {} when the slot is unreadable, the record is unreadable, or no
          header parses — the three cases that all mean "this file does not attest
          to who wrote it or when"
        - never raises
    """
    text = read_text_fn( slot_path )
    if text is None:
        return {}
    record_path = resolve_pointer_target( slot_path, text )
    if record_path is not None:
        record_text = read_text_fn( record_path )
        if record_text is None:
            return {}
        text = record_text
    return parse_memento_header( text )


# ── Whose file is in the slot? (pure) ─────────────────────────────────────────
def classify_slot_owner( slot_path, seat_sid8, read_text_fn ):
    """
    Name the OTHER seat whose memento is sitting in this seat's slot.

    THE DEFECT THIS SPLITS (row 3b0c5f90). "A file is here but I could not prove it"
    was one verdict covering two opposite facts. Once it meant a RACE — the child's
    own memento, mid-write, fine ten seconds later. Once it meant a PRIOR HOLDER's
    file was in the slot and the child's memento did not exist at all. Same words,
    ten minutes apart, opposite recovery actions. A manager who must open the file
    every time to learn which one it was will eventually stop opening it.

    The evidence to tell them apart was already read and thrown away: the header
    carries a session_id, and comparing it to the seat is a string compare. When
    they differ, the honest verdict is not "unparseable" — it is "this is somebody
    else's file, and yours is not at the slot".

    Requires:
        - read_text_fn( path ) -> the file text, or None when unreadable
        - seat_sid8 is the 8-char prefix of the seat's session id

    Ensures:
        - returns the OTHER seat's 8-char session id (lowercased) when the slot's
          record carries a parseable header naming a session that is not this seat
        - returns None when the slot is unreadable, the pointer's record is
          unreadable, no header parses, the header carries no session_id, the seat
          id is unknown, or the header names THIS seat
        - resolves a pointer slot to its record first, exactly as verify_seat_memento
          does, so the two never disagree about which bytes carry the header
        - never raises
    """
    header  = slot_record_header( slot_path, read_text_fn )
    hdr_sid = ( header or {} ).get( "session_id" )
    if not hdr_sid:
        return None
    hdr8  = hdr_sid[ :8 ].lower()
    seat8 = ( seat_sid8 or "" )[ :8 ].lower()
    if not seat8 or hdr8 == seat8:
        return None
    return hdr8


# ── The loud line (pure) ──────────────────────────────────────────────────────
def memento_alarm( outcomes ):
    """
    One sentence, for the TOP of the reap result, naming every seat about to be
    killed without a usable memento.

    WHY IT EXISTS (row 3b0c5f90, second bullet). The per-seat verdicts were already
    honest, and already ignored: they sit in a nested dict under a key the caller
    has to go looking for, while the reap proceeds and reports success around them.
    A verdict nobody reads is the same as no verdict. This is the line the caller
    puts where it cannot be missed.

    Requires:
        - outcomes maps seat name -> a coordinate_mementos outcome dict; the
          reserved `_error` key (a coordination failure, not a seat) is tolerated

    Ensures:
        - returns None when every seat is verified / written / not_requested — the
          quiet case stays quiet, so the line means something when it appears
        - otherwise returns a single string naming each losing seat, its persona and
          its verdict, sorted by seat name so the same reap reads the same way twice
        - never raises
    """
    LOSING = ( "timeout_no_memento", "prior_holder_present", "unparseable_present",
               "unproven_present", "skipped", "skipped_no_cwd" )
    losers = []
    for name in sorted( outcomes ):
        if name == "_error":
            continue
        outcome = outcomes[ name ]
        if not isinstance( outcome, dict ):
            continue
        if outcome.get( "status" ) in LOSING:
            losers.append( f"{name} ({outcome.get( 'persona' ) or 'unknown persona'}): "
                           f"{outcome.get( 'status' )}" )
    if not losers:
        return None
    return ( f"REAPED WITHOUT A PROVEN MEMENTO — {len( losers )} seat(s): "
             + "; ".join( losers )
             + ". See memento_outcomes for each seat's reason before re-spinning." )


# ── The post-kill re-check (row f94ab580) ─────────────────────────────────────
# Statuses that name a DERIVABLE SLOT and so can be re-asked of the disk. The two
# `skipped*` verdicts are deliberately absent: they mean the slot could not be
# derived at all (no persona/session, or no cwd), so there is no file to re-read
# and nothing a second look could prove. They stay loud, untouched.
RECHECKABLE = ( "timeout_no_memento", "prior_holder_present", "unparseable_present",
                "unproven_present" )


def recheck_losing_seats(
    outcomes,
    identities,
    *,
    now_fn         = None,
    read_text_fn   = None,
    window_seconds = DEFAULT_WINDOW_SECONDS,
    min_bytes      = DEFAULT_MIN_BYTES,
    merge_claim_fn = None
):
    """
    Re-ask the disk ONCE, after the kill, before the alarm is composed.

    THE DEFECT THIS CLOSES (row f94ab580, measured 2026-08-25 on a four-seat reap).
    `coordinate_mementos` computes its verdict at ASK TIME. A seat still mid-write
    when the ask window expires is reported as having failed to write a memento —
    and while it writes, the slot legitimately holds the PRIOR holder's file, which
    is exactly what `prior_holder_present` / `unparseable_present` describe. The
    classifier reads a TRUE fact about the WRONG MOMENT. Two of four seats were
    misreported that way; one DM'd "ready for re-spin — memento on disk, 48 lines,
    verified" AFTER it had been killed and logged as unproven.

    WHAT THIS IS NOT. It does not soften, delay, or forgive the alarm — row 0a36d83d
    exists because the alarm used to be a silent no-op, and row 3b0c5f90 exists
    because a race and a genuine loss used to return the same answer. An outcome is
    upgraded ONLY when `verify_seat_memento` — the SAME predicate the reap used,
    which proves the header's session_id is THIS seat's — passes on a second read.
    Existence at the slot is never enough: that is precisely what produced the
    wrong-but-plausible verdict for the seat whose slot held a prior holder's file.
    Nothing here can quiet an absent memento or another session's file.

    Requires:
        - outcomes maps seat name -> a `coordinate_mementos` outcome dict (the
          reserved `_error` key is tolerated and passed through untouched)
        - identities maps the SAME seat names -> `_capture_reap_identity` dicts —
          the same source pass 1 used, so the re-check reads the same seat's repo
        - read_text_fn( path ) -> text or None; now_fn() -> an AWARE datetime

    Ensures:
        - returns a NEW dict; the input is never mutated
        - a seat whose own memento is provably at the slot on the second read is
          upgraded to "written" — it WAS asked, and its file appeared after the ask,
          just after the poll deadline rather than before it. NOT "verified", which
          means no DM was sent and would be false here
        - every other seat keeps its verdict and its reason VERBATIM, including the
          two `skipped*` verdicts, which name no slot and are not re-read
        - a seat whose repo root cannot be resolved is NOT upgraded — an unresolvable
          root would silently skip the merge-claim gate, and a quieter alarm bought
          by a weaker check is the failure mode this row forbids
        - one clock read for the whole pass, so two seats cannot be judged fresh
          against different "now"s
        - never raises
    """
    now_fn       = now_fn       if now_fn       is not None else _default_now
    read_text_fn = read_text_fn if read_text_fn is not None else _default_read_text

    rechecked = dict( outcomes )
    now       = now_fn()
    for name, outcome in outcomes.items():
        if not isinstance( outcome, dict ):
            continue
        if outcome.get( "status" ) not in RECHECKABLE:
            continue
        repo_root = seat_repo_root( identities.get( name ) )
        if repo_root is None:
            continue
        slot           = seat_memento_slot( repo_root, outcome.get( "persona" ) )
        usable, reason = verify_seat_memento( slot, ( outcome.get( "session_id" ) or "" )[ :8 ], now,
                                              read_text_fn=read_text_fn,
                                              window_seconds=window_seconds, min_bytes=min_bytes,
                                              repo_root=repo_root, merge_claim_fn=merge_claim_fn )
        if not usable:
            continue
        rechecked[ name ] = dict( outcome )
        rechecked[ name ][ "status" ] = "written"
        rechecked[ name ][ "reason" ] = ( f"appeared after ask, during teardown: {reason}. "
                                          f"At ask time this seat read as {outcome.get( 'status' )} "
                                          f"— it was mid-write, not failing" )
    return rechecked


# ── Identity helpers ──────────────────────────────────────────────────────────
def _identity_bits( ident ):
    """
    Ensures:
        - returns ( persona_name, session_id ) from a `_capture_reap_identity` dict
        - persona is read from the voice_persona dict's `name` (or a bare string)
        - ( None, ... ) / ( ..., None ) when the bridge identity is missing a piece
        - never raises
    """
    if not ident:
        return None, None
    persona = ident.get( "persona" )
    if isinstance( persona, dict ):
        name = persona.get( "name" )
    elif isinstance( persona, str ):
        name = persona
    else:
        name = None
    return name, ident.get( "session_id" )


# ── Live default seams (injected away in tests) ───────────────────────────────
def _default_now():   # pragma: no cover - trivial clock boundary
    return datetime.datetime.now( datetime.timezone.utc )


def _default_read_text( path ):
    """
    Ensures: returns the file's text, or None when unreadable (never raises).
    A truncated write can leave an INVALID UTF-8 stream (a multibyte char cut in
    half) — that raises UnicodeDecodeError, not OSError. It is exactly the partial
    write the byte floor exists to reject, so it must read as "unreadable" → ASK,
    never crash the whole coordination pass.
    """
    try:
        with open( path, "r" ) as handle:
            return handle.read()
    except ( OSError, UnicodeDecodeError ):
        return None


def _default_dm( persona_name, session_id, body ):   # pragma: no cover - live MCP DM boundary
    """
    Ask a child, addressed by its FULL session id (name-reuse-proof), to write its
    memento. Lazy-imports the MCP DM core so this module never pulls the server in
    at import time (the server imports THIS module).
    """
    from lupin_mcp.cosa_voice_mcp import _dm_send_fn
    return _dm_send_fn( recipient=persona_name, body=body, recipient_session_id=session_id )


# ── The orchestrator — every side effect injectable ───────────────────────────
def coordinate_mementos(
    identities         : Dict[ str, Any ],
    *,
    write_memento      : bool,
    now_fn             : Optional[ Callable ] = None,
    read_text_fn       : Optional[ Callable ] = None,
    dm_fn              : Optional[ Callable ] = None,
    sleep_fn           : Callable = time.sleep,
    window_seconds     : int = DEFAULT_WINDOW_SECONDS,
    min_bytes          : int = DEFAULT_MIN_BYTES,
    merge_claim_fn     = None,
    ask_timeout_sec    : int = DEFAULT_ASK_TIMEOUT_SEC,
    poll_interval_sec  : int = DEFAULT_POLL_INTERVAL_SEC
) -> Dict[ str, Dict[ str, Any ] ]:
    """
    Ensure a fresh + complete memento exists on disk for each reaped seat BEFORE
    teardown, returning an EXPLICIT per-seat outcome. This runs BEFORE any kill —
    the kill used to be the first statement in the reap, so a send with no wait
    lost the race; here every ask completes and every slot is polled first.

    Requires:
        - identities maps tmux_session_name -> a `_capture_reap_identity` dict (or None)
        - NO batch-wide root is accepted, deliberately (row 80b930e6, Tiberius review).
          Each seat's slot comes from that seat's OWN bridge `cwd` via seat_repo_root,
          because one batch can span repos. The old `project_root` parameter was
          removed rather than left unused: a root in scope is a root something will
          eventually fall back to, and the ruling here is REFUSE, not fall back. With
          no root to reach for, "no cwd → skipped_no_cwd" holds by construction
        - now_fn/read_text_fn/dm_fn default to the live seams; sleep_fn defaults to
          time.sleep (injected in tests so no real waiting happens)

    Ensures:
        - when write_memento is False → every seat's outcome is status "not_requested"
          (no disk read, no DM)
        - otherwise, per seat, status is one of:
            "verified"           a fresh+complete session-matched memento already on
                                 disk — NO DM sent (this same skip closes both the
                                 double-send case and the self_respin gap)
            "written"            no usable memento at first, the child was asked, and
                                 a usable one appeared within ask_timeout_sec
            "timeout_no_memento" the child was asked and nothing READABLE-WITH-CONTENT is
                                 on disk — either NOTHING at the slot, or an empty /
                                 whitespace-only file (a write that started and died).
                                 ABSENT for recovery, unrecoverable. VISIBLE, never
                                 success. The empty case keeps its evidence in the reason
            "prior_holder_present" the child was asked and the slot still holds a file whose
                                 header PARSED and named a DIFFERENT seat. This seat's
                                 memento is NOT at the slot — the file is another seat's
                                 (row 3b0c5f90). Split out of "unparseable_present"
                                 because the recovery actions are opposite: here, opening
                                 the file teaches you about somebody else's work, and the
                                 thing to hunt for is a memento written to the wrong place
            "unparseable_present" the child was asked and a file IS on disk at the slot,
                                 but it carries NO parseable memento-record header at all,
                                 so nothing in it attests to who wrote it or when
                                 (RECOVERABLE — a manager can OPEN and READ it). Cases:
                                 a hand-written memento with only a markdown H1 heading,
                                 or a pointer whose record vanished. THE CAUSE IS A WRITER
                                 BYPASSING memento_io, and the remedy is a writer fix.
                                 A prior-holder's file does NOT land here (its own verdict
                                 above), and neither does this seat's own headered memento
                                 (see "unproven_present" below)
            "unproven_present"   the child was asked and THIS SEAT'S OWN memento is at the
                                 slot — the header parsed and named this session — but one
                                 verify gate failed: stale beyond the window, under the
                                 byte floor (a partial write), or a refuted merge claim.
                                 The reason NAMES the gate verbatim from verify_seat_memento.

                                 SPLIT OUT OF "unparseable_present" (row 48b5f19e) because
                                 the two read identically and mean opposite things. Measured
                                 2026-08-29: one seat was 45 seconds past the poll deadline
                                 with a perfect memento, another had hand-written a slot with
                                 no header at all, and BOTH drew "unparseable_present" — so a
                                 manager had to open every file to learn which. Here the
                                 writer is fine and the remedy is a TIMEOUT (or the post-kill
                                 re-check); there the writer is the defect. Same verdict for
                                 both is what trains a manager to stop reading the alarm
            "skipped"            no persona/session in the bridge identity, so the
                                 slot cannot be derived — surfaced, not silently ok
            "skipped_no_cwd"     persona+session known but the bridge carries no `cwd`,
                                 so the seat's REPO is unknown (row 80b930e6). Distinct
                                 from "skipped" and from the unparseable/absent verdicts
                                 on purpose: guessing a root does not fail to find a
                                 memento, it finds ANOTHER persona's live memento at the
                                 same-named slot. "I do not know which repo" must never
                                 read like "the file is corrupt"

                                 ⚠️ THIS IS A LABEL, NOT A GATE (Tiberius review). The
                                 caller REPORTS these outcomes and never branches on
                                 them: session_spawner assigns memento_outcomes at :943,
                                 returns it at :1089, and the kill loop runs over every
                                 target regardless. So a seat reported skipped_no_cwd is
                                 STILL REAPED, with no verified memento. Refusing to
                                 guess buys an honest verdict, not protection — a
                                 manager who reads this must pass the path explicitly
                                 or accept losing that seat's context
        - a seat with no identity is NEVER asked and NEVER reported verified
        - never raises on an injected-seam failure it can classify (a failed DM send
          is recorded in the seat's reason, it does not abort coordination)

    THE TRADE (Mr. Radio, recorded verbatim per instruction): erring toward asking
    means a worker can get a second "prepare for re-spin" it already answered. That
    duplicate ask is visible and cheap; a silently-missing memento is the defect —
    so every ambiguous case asks.
    """
    now_fn       = now_fn       if now_fn       is not None else _default_now
    read_text_fn = read_text_fn if read_text_fn is not None else _default_read_text
    dm_fn        = dm_fn        if dm_fn        is not None else _default_dm
    # Clamp the poll cadence to >= 1s: a misconfigured 0/negative would leave `elapsed`
    # stuck and hang the reap forever (the kill never runs). A floor is fail-safe — the
    # wait can be at most ask_timeout_sec, never unbounded.
    poll_interval_sec = max( 1, poll_interval_sec )

    outcomes : Dict[ str, Dict[ str, Any ] ] = {}

    if not write_memento:
        for name in identities:
            outcomes[ name ] = { "status": "not_requested",
                                 "reason": "write_memento=False — no memento asked for" }
        return outcomes

    # Pass 1 — classify every seat: already-verified (no DM) vs pending (must ask).
    now     = now_fn()
    pending : Dict[ str, Dict[ str, Any ] ] = {}
    for name, ident in identities.items():
        persona_name, session_id = _identity_bits( ident )
        if not persona_name or not session_id:
            outcomes[ name ] = { "status": "skipped",
                                 "reason": "no persona/session in bridge identity — cannot derive memento slot",
                                 "persona": persona_name, "session_id": session_id }
            continue
        # PER-SEAT root (row 80b930e6). This used to read a batch-wide `project_root`
        # derived from LUPIN_ROOT, which describes the HOST, not this seat — so every
        # non-lupin seat was verified against lupin's io/mementos/, i.e. against a
        # DIFFERENT persona's live memento. The seat's own bridge cwd is the only
        # ground truth (present in 23/23 live bridges); absent it we refuse to guess.
        repo_root = seat_repo_root( ident )
        if repo_root is None:
            outcomes[ name ] = { "status": "skipped_no_cwd",
                                 "reason": "no cwd in bridge identity — the seat's repo is unknown "
                                           "and guessing one reads another persona's memento",
                                 "persona": persona_name, "session_id": session_id }
            continue
        slot          = seat_memento_slot( repo_root, persona_name )
        usable, reason = verify_seat_memento( slot, session_id[ :8 ], now,
                                              read_text_fn=read_text_fn,
                                              window_seconds=window_seconds, min_bytes=min_bytes,
                                              repo_root=repo_root, merge_claim_fn=merge_claim_fn )
        if usable:
            outcomes[ name ] = { "status": "verified", "reason": reason,
                                 "persona": persona_name, "session_id": session_id, "slot": str( slot ) }
        else:
            pending[ name ] = { "persona": persona_name, "session_id": session_id,
                                "slot": slot, "pre_ask_reason": reason, "repo_root": repo_root }

    if not pending:
        return outcomes

    # Pass 2 — ask every un-verified, still-alive seat (single fan-out).
    for name, info in pending.items():
        info[ "ask_note" ] = ""
        try:
            dm_fn( info[ "persona" ], info[ "session_id" ], ASK_BODY.format( slot=info[ "slot" ] ) )
        except Exception as error:
            info[ "ask_note" ] = f" (ask send raised: {error.__class__.__name__})"

    # Pass 3 — poll every asked slot to ONE shared deadline (added latency is bounded
    # to a single window regardless of seat count — the common all-verified case never
    # reaches here).
    elapsed = 0
    while pending and elapsed < ask_timeout_sec:
        sleep_fn( poll_interval_sec )
        elapsed += poll_interval_sec
        now = now_fn()
        for name in list( pending ):
            info           = pending[ name ]
            usable, reason = verify_seat_memento( info[ "slot" ], info[ "session_id" ][ :8 ], now,
                                                  read_text_fn=read_text_fn,
                                                  window_seconds=window_seconds, min_bytes=min_bytes,
                                                  repo_root=info[ "repo_root" ], merge_claim_fn=merge_claim_fn )
            if usable:
                outcomes[ name ] = { "status": "written", "reason": f"appeared after ask: {reason}",
                                     "persona": info[ "persona" ], "session_id": info[ "session_id" ],
                                     "slot": str( info[ "slot" ] ) }
                del pending[ name ]

    # Pass 4 — anything still un-written failed VISIBLY, split by RECOVERABILITY. A file
    # on disk WITH content that could not be PROVEN is present-but-unparseable (open +
    # read it); a slot with nothing — or an empty/whitespace-only file (a write that
    # started and died) — is absent, because the recovery action is identical: there is
    # nothing to read. Collapsing present-with-content into absent is what trained
    # managers to ignore the alarm; sending them to open a 0-byte file is the same
    # collapse inverted, so empty buckets as absent but keeps its evidence in the reason.
    for name, info in pending.items():
        presence = classify_slot_presence( info[ "slot" ], read_text_fn )
        foreign  = classify_slot_owner( info[ "slot" ], info[ "session_id" ][ :8 ], read_text_fn )
        if presence == "present" and foreign is not None:
            # NOT "unparseable" — the header parsed fine and named somebody else. This
            # seat's memento is not at the slot, and opening the file teaches a manager
            # about a different seat's work (row 3b0c5f90).
            status = "prior_holder_present"
            reason = ( f"asked{info[ 'ask_note' ]}, and after {ask_timeout_sec}s the slot still holds "
                       f"ANOTHER seat's memento (session {foreign}) — THIS seat's memento is NOT at the "
                       f"slot. Do not open it expecting this seat's context. If the seat wrote one "
                       f"elsewhere (the repo root is the usual wrong place), move it to the slot before "
                       f"re-spinning; otherwise it was never written; at ask time: {info[ 'pre_ask_reason' ]}" )
        elif presence == "present" and slot_record_header( info[ "slot" ], read_text_fn ):
            # The file ATTESTS to being this seat's — the header parsed and named this
            # seat. So the failure is a GATE (stale / partial / merge-claim), never a
            # missing writer, and verify_seat_memento already computed WHICH gate. Pass 4
            # used to discard that sentence and substitute a generic one, which is what
            # made "mid-write" and "written wrong" read identically (row 48b5f19e).
            _usable, gate = verify_seat_memento( info[ "slot" ], info[ "session_id" ][ :8 ], now_fn(),
                                                 read_text_fn=read_text_fn,
                                                 window_seconds=window_seconds, min_bytes=min_bytes,
                                                 repo_root=info[ "repo_root" ], merge_claim_fn=merge_claim_fn )
            status = "unproven_present"
            reason = ( f"asked{info[ 'ask_note' ]}, and THIS SEAT'S OWN memento is at the slot — the "
                       f"header parses and names this session — but one gate failed within "
                       f"{ask_timeout_sec}s: {gate}. A writer bug is NOT indicated; the seat used the "
                       f"sanctioned path. If the gate is a small staleness it was still writing when "
                       f"the window closed; at ask time: {info[ 'pre_ask_reason' ]}" )
        elif presence == "present":
            status = "unparseable_present"
            reason = ( f"asked{info[ 'ask_note' ]}, a file is on disk at the slot but it carries NO "
                       f"parseable memento-record header, so nothing in it attests to who wrote it or "
                       f"when — hand-written, bypassing memento_io. OPEN AND READ IT (RECOVERABLE, not "
                       f"missing), and note the slot may have overwritten a pointer; at ask time: "
                       f"{info[ 'pre_ask_reason' ]}" )
        else:
            status     = "timeout_no_memento"
            empty_note = ( " slot file present but empty (0 bytes — a write started and died);"
                           if presence == "empty" else "" )
            reason = ( f"asked{info[ 'ask_note' ]}, no fresh+complete memento within {ask_timeout_sec}s "
                       f"(parked / slow / declined);{empty_note} at ask time: {info[ 'pre_ask_reason' ]}" )
        outcomes[ name ] = {
            "status"     : status,
            "reason"     : reason,
            "persona"    : info[ "persona" ], "session_id": info[ "session_id" ],
            "slot"       : str( info[ "slot" ] )
        }
    return outcomes


# ── "Is this seat's memento actually at the slot?" — one command ──────────────
def describe_slot(
    repo_root,
    persona_name,
    seat_sid8,
    now,
    *,
    read_text_fn   = None,
    window_seconds = DEFAULT_WINDOW_SECONDS,
    min_bytes      = DEFAULT_MIN_BYTES
):
    """
    Answer the ONE question a "ready for re-spin" claim does not answer: is the
    memento at THE SLOT THE REAPER READS, and is it THIS seat's?

    WHY THIS EXISTS (row 3b0c5f90, third bullet). A worker reported ready with an
    impeccable receipt — a real path, its own session id, a mirror, a sha256, every
    element true — and its memento was in the repo root while the slot resolved to a
    four-hour-old holder. A receipt can be completely accurate and still not answer
    the question being asked of it. So the check is not "did you write one", it is
    "does the slot resolve to you", and only the slot can answer that.

    The manager was already doing this by hand before every reap. Doing it by hand is
    how it gets skipped on a busy evening.

    Requires:
        - repo_root is the seat's OWN repo root (its bridge `cwd`), never the host's
        - seat_sid8 is the 8-char prefix of the seat's session id
        - now is an AWARE datetime

    Ensures:
        - returns { slot, verdict, detail, foreign_session_id }
        - verdict is "ready" ONLY when verify_seat_memento proves the slot — the same
          predicate the reap uses, so this command and the reap can never disagree
        - verdict is "prior_holder" when the slot names a DIFFERENT session, and
          foreign_session_id names it
        - verdict is "absent" when nothing readable with content is at the slot
        - verdict is "present_unproven" otherwise — present, this seat's or nobody's,
          but not provable (the race case)
        - foreign_session_id is None for every verdict but "prior_holder"
        - never raises
    """
    read_text_fn = read_text_fn if read_text_fn is not None else _default_read_text
    slot         = seat_memento_slot( repo_root, persona_name )
    usable, detail = verify_seat_memento( slot, seat_sid8, now, read_text_fn=read_text_fn,
                                          window_seconds=window_seconds, min_bytes=min_bytes )
    if usable:
        return { "slot": str( slot ), "verdict": "ready", "detail": detail,
                 "foreign_session_id": None }
    foreign = classify_slot_owner( slot, seat_sid8, read_text_fn )
    if foreign is not None:
        return { "slot": str( slot ), "verdict": "prior_holder", "detail": detail,
                 "foreign_session_id": foreign }
    if classify_slot_presence( slot, read_text_fn ) == "present":
        return { "slot": str( slot ), "verdict": "present_unproven", "detail": detail,
                 "foreign_session_id": None }
    return { "slot": str( slot ), "verdict": "absent", "detail": detail,
             "foreign_session_id": None }


def format_slot_report( report, persona_name, seat_sid8 ):
    """
    Ensures:
        - returns the human lines for a `describe_slot` result, leading with the
          verdict and naming the slot on every one of them (the slot IS the answer)
        - never raises
    """
    verdict = report[ "verdict" ]
    head    = {
        "ready"            : f"READY — {persona_name} ({seat_sid8}) resolves at the slot. Safe to reap.",
        "prior_holder"     : ( f"NOT AT THE SLOT — the slot holds session "
                               f"{report[ 'foreign_session_id' ]}, not {seat_sid8}. "
                               f"{persona_name}'s memento is somewhere else or was never written; "
                               f"check the repo root before reaping." ),
        "absent"           : f"NOTHING AT THE SLOT — {persona_name} ({seat_sid8}) has no memento to reap.",
        "present_unproven" : ( f"PRESENT BUT UNPROVEN — a file is at the slot and it is not another "
                               f"session's, but it could not be proven fresh and complete. Re-run in "
                               f"a few seconds if {persona_name} is mid-write." ),
    }[ verdict ]
    return f"{head}\n  slot:   {report[ 'slot' ]}\n  detail: {report[ 'detail' ]}"


def main( argv=None ):   # pragma: no cover - thin argv/stdout boundary over tested parts
    """
    Ensures:
        - prints the slot report for one seat and exits 0 only when it is "ready",
          so a manager can gate a reap on it instead of eyeballing a DM
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog        = "python3 -m lupin_mcp.reap_memento",
        description = "Does this seat's memento resolve at the slot the reaper reads?" )
    parser.add_argument( "--repo-root",  required=True, help="the SEAT's repo root (its bridge cwd)" )
    parser.add_argument( "--persona",    required=True )
    parser.add_argument( "--session-id", required=True, help="the seat's session id (8-char prefix is enough)" )
    args = parser.parse_args( argv )

    report = describe_slot( args.repo_root, args.persona, args.session_id[ :8 ], _default_now() )
    print( format_slot_report( report, args.persona, args.session_id[ :8 ] ) )
    return 0 if report[ "verdict" ] == "ready" else 1


if __name__ == "__main__":   # pragma: no cover - process entry point
    import sys
    sys.exit( main() )
