"""
Task-store structural rules — pure validation for the unified task store (Phase 1).

This module is the ONE place where the task store's structural invariants live
(design §2.2 "enforcement-light to start": the API enforces structural rules;
social/role rules stay practice-layer in v1):

    - status / item_class / gate_class / priority / urgency / authority enum membership
    - receipt_refs key whitelist + per-key shape rules (design §4.1 AC1 —
      "receipt validation is not theater-able")
    - typed blocked_by refs ({kind: item|persona|user, id}) (design §2.1)
    - transition rules: terminal states are append-only; ->done requires valid
      receipts; ->blocked requires next_chase_ts (I3) + >=1 typed blocked_by ref

Every function is pure (no DB, no HTTP): callers pass state in, get a list of
human-readable error strings back (empty list == valid). The router maps a
non-empty list to HTTP 422; the repository never sees invalid input.

Canonical design: planning-is-prompting ->
src/rnd/2026.06.11-unified-task-store-design.md (v0.4). Gate rulings (Tiberius,
qid c8c73fde): item_class naming, terminal-state rule, blocked requires >=1 ref,
log_line shape = "<scope>/<rel-path>:<lineno>" with exists check.
"""

import os
import re
import subprocess
import uuid
from typing import Optional

from lupin_mcp.persona_normalization import canonical_persona_key


# ---------------------------------------------------------------------------
# Enums (design §2.1) — plain tuples, app-validated (house style: no PG ENUM)
# ---------------------------------------------------------------------------

VALID_STATUSES         = ( "queued", "claimed", "in_progress", "blocked", "parked", "review", "done", "dropped" )
TERMINAL_STATUSES      = ( "done", "dropped" )
VALID_ITEM_CLASSES     = ( "task", "decision", "review_request", "bug", "gate" )

# The deliberate-hold status (2026-07-19). A row is `parked` when a HUMAN ruled it
# not-now: approved, not abandoned, not blocked on anything. `queued` then means,
# honestly, "actually workable now". NON-terminal by design — parking buys bounded,
# self-expiring silence, never an exit.
#
# The VOCABULARY lives here with the other enums (one home for the store's words);
# the READ-TIME predicate over it lives in `task_store_owed`, which imports these.
# The dependency runs owed -> rules and never back, so `task_store_rules` keeps its
# purity contract ("no DB, no HTTP") while the SQLAlchemy twin stays out of it.
PARK_STATUS              = "parked"

# The park ENTRY set. Park is legal from these statuses. This is what makes
# re-admitting expired-parked rows to the owed set an exact RESTORATION rather than
# a widening: such a row provably came from queued/in_progress, so it can never drag
# in a blocked/claimed/review row. A `parked_from_status` COLUMN was rejected — Rick's
# standing rule, a new field where a rule suffices.
#
# ⚠️ ENTRY, not ADMISSION — the two are no longer the same set (store row aa543525,
# 2026-07-27). `parked -> parked` is ALSO legal (see `is_park_legal_from`), but it is
# a RE-ENTRY, not an entry, and it must NOT be added here: this tuple is the set whose
# subset relation to OWED_BASE_STATUSES carries the restoration proof, and `parked` is
# not an owed status. Widening this tuple to include it would trip the import-time
# assert in `task_store_owed` — correctly, because the proof it guards is about where
# parked rows COME FROM, and a re-park introduces no new provenance.
PARK_LEGAL_FROM_STATUSES = ( "queued", "in_progress" )

# The waiting status (store row 00a6bde2, 2026-07-25). Named here for the same reason
# PARK_STATUS is: the word belongs with the other enums, the READ-TIME predicate over
# it (`blocker_is_terminal`) lives in `task_store_owed`.
#
# WHY IT EARNED A CONSTANT. `blocked` is the ONE status that cannot self-heal. A parked
# row's chase expires at read time and it rejoins the owed count with no human action;
# a blocked row's EDGE is never recomputed at all. So the only status with no
# self-healing arm was also the only one with no staleness oracle — six rows sat
# unsatisfiable for up to eight days before two seats found them by hand.
BLOCKED_STATUS           = "blocked"
VALID_GATE_CLASSES     = ( "none", "manager", "operator" )
VALID_PRIORITIES       = ( "P0", "P1", "P2", "P3" )
# proactive-manager A2 (fcb5dbc0): operator-gate TIME-SENSITIVITY, distinct from the
# `priority` IMPORTANCE field. Default "normal". The arbiter (single pusher) routes an
# operator gate by this: urgent→interrupt, normal→digest, low→queue-until-pulled.
VALID_URGENCIES        = ( "urgent", "normal", "low" )
VALID_AUTHORITIES      = ( "standing", "user_direct", "manager_relay" )
VALID_BLOCKED_BY_KINDS = ( "item", "persona", "user" )

# Class-scoped owner guard (persona-key follow-on policy, 2026-07-11 / task
# c03d1870). The OWNED-WORK item classes: an omitted owner_persona on CREATE
# defaults to the creator's persona (see persona_from_created_by) — forgiving,
# never a hard 422. The operator-queue classes (decision/gate) stay ownerless
# BY DESIGN (Rick's court), so they are DELIBERATELY excluded here.
DEFAULT_OWNER_CLASSES  = ( "task", "bug", "review_request" )

# Legal-transition graph (Phase 2.1, ratified 2026-06-15). The RATIFIED graph:
# every NON-terminal status may move to every OTHER status; terminal statuses
# (done/dropped) have NO out-edges (append-only finality); same->same is a no-op.
# This is BEHAVIOR-PRESERVING — it makes the Phase-1 implicit graph EXPLICIT so a
# future tightening has one home (and the mirror-edge regression can prove the
# live hook's edges stay legal). Derived from the enums, never hand-listed.
LEGAL_TRANSITIONS = {
    src: tuple( dst for dst in VALID_STATUSES if dst != src )
    for src in VALID_STATUSES if src not in TERMINAL_STATUSES
}

# Receipt key whitelist + shape rules (design §4.1 AC1)
RECEIPT_KEY_WHITELIST = ( "commit", "test_run", "qid", "doc_path", "log_line" )

# The subset a THIRD PARTY can independently check without taking the closer's word
# (row 9bfb4b73). A ->done receipt must carry at least one of these. The others are
# not junk — they are context — but `doc_path` and `log_line` only prove a file
# exists, which is true whether or not the work landed, and `qid` names a question
# rather than an outcome. None of the three can carry a close on its own.
CHECKABLE_RECEIPT_KEYS = ( "commit", "test_run" )


# ---------------------------------------------------------------------------
# Unscoped-query guard (design 2026.07.07 task_query unscoped-guard — Option B)
# ---------------------------------------------------------------------------
#
# Rick's operational mandate (voice, 2026-07-07): the task DB only grows; make
# task_query FAIL so nobody can pull hundreds/thousands of rows. The guard is a
# REPOSITORY-layer enforcement (universal, un-bypassable by any repo-direct
# caller) that HARD-FAILS a BARE, unscoped query that would return more than
# UNSCOPED_QUERY_THRESHOLD non-terminal rows — UNLESS the caller passes an
# explicit `unscoped_audit=True` (the deliberate-full-sweep escape the arbiter
# and the two UI board cards use).

# The row ceiling for an unscoped pull. Counted NON-terminal always (done/dropped
# are excluded from the count, mirroring the default query payload).
UNSCOPED_QUERY_THRESHOLD = 50

# A non-terse pull returning more than this many rows earns an OBSERVABLE WARN
# (never a failure — María #3 warn-not-fail): a nudge toward terse=True. Distinct
# axis from UNSCOPED_QUERY_THRESHOLD (that gates unscoped SIZE; this nudges
# non-terse WEIGHT), same number by coincidence, not by coupling.
NONTERSE_WARN_THRESHOLD = 50

# The RESPONSE BYTE BUDGET (mini-plan 02 T3, 2026-07-21). `limit` caps ROWS, and a
# row cap is NOT a size cap: measured 2026-07-21, the SAME 100-row default page is
# 21,379 chars terse and 424,209 chars full, because rows carry multi-KB bodies with
# stacked amendments. The one knob that existed governed the wrong quantity, so a
# properly-SCOPED query (owner_persona="mr radio" + include_terminal) still returned
# 387,119 chars ~= 97k tokens into a caller's context.
#
# Serialization stops once the accumulated payload reaches this many characters and
# the response says so (`truncated: true`) alongside the honest `total`. It is a
# SECOND, independent bound beside `limit` — neither subsumes the other, and NEITHER
# may ever stop silently.
#
# 100,000 chars ~= 25k tokens: comfortably above the heaviest measured TERSE page
# (21,379), so the cheap shape is never truncated, while the expensive shape is
# capped at roughly a quarter of the blowup that motivated this.
RESPONSE_CHAR_BUDGET = 100_000

# "scoped" = ANY genuinely-narrowing filter present. Broadened past María's literal
# four (owner_persona/status/item_class/project) to also protect the arbiter's
# operator-gate sweep (gate_class), manager board-audits (accountable_manager), and
# idempotency probes (correlation_key). `urgency` is deliberately EXCLUDED — it is
# too coarse to meaningfully narrow the store, so a bare urgency filter is still
# "unscoped" and still guarded.
SCOPING_FILTERS = (
    "owner_persona", "status", "item_class", "project",
    "gate_class", "accountable_manager", "correlation_key",
    # id_prefix is the NARROWEST filter there is — it names at most a handful of
    # rows by identity. Omitting it here would make `task_query(id_prefix=...)`
    # count as a bare unscoped pull and get rejected by the guard, which is the
    # opposite of what the guard is for (row f45b37a9 remedy 2 / 4288dd53).
    "id_prefix",
)


class UnscopedQueryError( Exception ):
    """
    Raised by TaskRepository.query_tasks when a BARE unscoped query would return
    more than UNSCOPED_QUERY_THRESHOLD non-terminal rows and the caller did NOT
    pass unscoped_audit=True. Carries the offending count + the threshold so the
    router can render an educational HTTP 400 (name the two fixes) and the MCP
    verb can surface a structured error-dict.
    """

    def __init__( self, count: int, threshold: int = UNSCOPED_QUERY_THRESHOLD ):
        self.count     = count
        self.threshold = threshold
        super().__init__(
            f"unscoped task_query would return {count} non-terminal rows "
            f"(> {threshold}) — narrow it with a filter (owner_persona / status / "
            f"item_class / project / gate_class / accountable_manager / "
            f"correlation_key) or pass unscoped_audit=true for a deliberate audit"
        )


def is_unscoped( filters: dict ) -> bool:
    """
    Return True iff NONE of the genuinely-narrowing SCOPING_FILTERS is present
    (non-None) in `filters` — i.e. the query is a bare, un-narrowed full-store
    pull that the guard must size-check.

    Requires:
        - filters is a dict of filter-name -> value (absent keys and explicit
          None both count as "not present")

    Ensures:
        - returns True when every SCOPING_FILTERS entry is absent or None
          (`urgency` is NOT a scoping filter, so a urgency-only query is
          still unscoped)
        - returns False the moment ANY scoping filter carries a non-None value
        - never raises (a missing key is treated as None)
    """
    return not any( filters.get( name ) is not None for name in SCOPING_FILTERS )

# Shape patterns are applied via re.fullmatch ONLY — never re.match + `$`,
# because Python's `$` matches before a trailing newline, letting
# "abcdef1\n" smuggle through the AC1 gate (cold-review N1, live-proven).
COMMIT_PATTERN   = re.compile( r"[0-9a-f]{7,40}" )
TEST_RUN_PATTERN = re.compile( r"ts-[0-9a-f]{8}" )
QID_PATTERN      = re.compile( r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" )
LOG_LINE_PATTERN = re.compile( r"(.+):(\d+)" )


# ---------------------------------------------------------------------------
# Scope-root resolution for doc_path / log_line exists-in-repo checks
# ---------------------------------------------------------------------------

_SCOPE_ROOTS: Optional[dict] = None  # lazy singleton — None means "not built yet"


def _get_default_scope_roots() -> dict:
    """
    Build (once per process) the scope-name -> absolute-root map for receipt
    path validation, reusing the doc-viewer scope registry (design §4.1 AC1:
    doc_path = exists-in-repo check; no new path grammar).

    Requires:
        - ConfigurationManager singleton is constructible (server context)

    Ensures:
        - returns { scope_name: absolute_root } for every registered repo
        - built exactly once; subsequent calls return the cached map
    """
    global _SCOPE_ROOTS
    if _SCOPE_ROOTS is None:
        from cosa.rest.dependencies.config import get_config_manager
        from cosa.rest.routers._scope_registry import build_scope_registry

        registry     = build_scope_registry( get_config_manager() )
        _SCOPE_ROOTS = { name: cfg.root for name, cfg in registry.items() }
    return _SCOPE_ROOTS


def _validate_scoped_path( value: str, scope_roots: Optional[dict] ) -> list:
    """
    Validate a "<scope>/<relative-path>" receipt path: registered scope,
    no root escape, file exists.

    Requires:
        - value is a non-empty string
        - scope_roots is a { scope: abs_root } dict, or None to use the
          process-default registry-backed map

    Ensures:
        - returns [] when the path names an existing file inside a registered
          scope root
        - returns one error string otherwise (unknown scope, escape, missing)
    """
    roots = scope_roots if scope_roots is not None else _get_default_scope_roots()

    if "/" not in value:
        return [ f"receipt path '{value}' must be '<scope>/<relative-path>' (e.g. 'lupin/src/rnd/foo.md')" ]

    scope, rel = value.split( "/", 1 )
    if scope not in roots:
        return [ f"receipt path scope '{scope}' is not a registered repo scope" ]

    root = roots[ scope ].rstrip( os.sep )
    full = os.path.normpath( os.path.join( root, rel ) )
    if full != root and not full.startswith( root + os.sep ):
        return [ f"receipt path '{value}' escapes its scope root" ]

    if not os.path.isfile( full ):
        return [ f"receipt path '{value}' does not exist in scope '{scope}'" ]

    return [ ]


def _validate_commit_reachable( sha: str, scope_roots: Optional[dict] ) -> list:
    """
    Check that a receipt commit is REACHABLE FROM SOME BRANCH (row 9bfb4b73).

    Requires:
        - sha has already passed COMMIT_PATTERN (7-40 lowercase hex)
        - scope_roots is a { scope: abs_root } dict, or None for the default map

    Ensures:
        - returns [] when `git branch --all --contains <sha>` names at least one
          branch in at least one registered scope that is a git work tree
        - returns one error when every usable repo was searched and none has the
          sha on a branch — this is the orphaned-object case: a sha left by a
          reset or rebase resolves TODAY and vanishes at the next gc, so a
          receipt pointing at one decays into a receipt pointing at nothing
        - returns one error, naming the reason, when NO registered scope is a
          usable git work tree — the store cannot check, so it REFUSES rather
          than accepting quietly. An unverifiable receipt silently accepted is
          the hole this rule exists to close, with extra steps
        - never raises: a missing git binary, a timeout, or an unreadable repo
          all resolve to the cannot-verify refusal, never to an exception and
          never to a pass

    Searches EVERY registered scope rather than the item's own project because a
    receipt is checked here without the row in hand; a sha found on a branch of
    any repo the store serves is a sha a human can go read.
    """
    roots     = scope_roots if scope_roots is not None else _get_default_scope_roots()
    searched  = [ ]
    unsearched = [ ]

    for scope, root in sorted( roots.items() ):
        if not root or not os.path.isdir( os.path.join( root, ".git" ) ):
            unsearched.append( scope )
            continue
        try:
            proc = subprocess.run(
                [ "git", "-C", root, "branch", "--all", "--contains", sha ],
                capture_output = True,
                text           = True,
                timeout        = 15,
            )
        except ( OSError, subprocess.SubprocessError ):
            unsearched.append( scope )
            continue

        searched.append( scope )
        # A non-zero exit means the object is unknown to THIS repo — not fatal,
        # another scope may still have it. Empty stdout on a zero exit means the
        # object exists but sits on no branch: the orphan case.
        if proc.returncode == 0 and proc.stdout.strip():
            return [ ]

    if not searched:
        return [
            f"receipt commit '{sha}' could NOT be verified — no registered scope is a usable "
            f"git work tree (checked: {sorted( roots ) or 'none'}). The store refuses a receipt "
            f"it cannot check rather than accepting it quietly (row 9bfb4b73)."
        ]

    # WORDING IS LOAD-BEARING (María, 2026-08-15). This refusal must NOT lead with
    # "fabricated". A commit that is perfectly real and on a branch reads exactly
    # like this one when its repo is simply not mounted on the server — and being
    # told your own sha looks fabricated sends an honest person hunting a bug that
    # does not exist. The one cause they will never guess is the unmounted repo, so
    # the message names the repos actually searched and the ones that were not. The
    # refusal is right either way; the accusation is not.
    not_searched = f" NOT searched (no git tree on this server): {unsearched}." if unsearched else ""
    return [
        f"receipt commit '{sha}' could not be found on any branch of the repos this server "
        f"can search: {searched}.{not_searched} If your repo is in that not-searched list, the "
        f"sha is probably fine and simply unreachable from here — cite a ts- test_run instead, "
        f"or a commit from a searched repo, and put this sha in the reason. If your repo IS "
        f"searched, the object is not on any branch: an orphan from a reset or rebase resolves "
        f"today and is gone at the next gc. ANY branch counts, not just main (row 9bfb4b73)."
    ]


# ---------------------------------------------------------------------------
# Receipt validation (design §4.1 AC1 — "not theater-able")
# ---------------------------------------------------------------------------

def validate_receipt_refs( receipt_refs, scope_roots: Optional[dict] = None,
                           require_checkable: bool = False ) -> list:
    """
    Validate a receipt_refs object against the key whitelist + per-key shapes.

    Requires:
        - receipt_refs is the candidate receipts value (any type accepted;
          non-dict and empty-dict are rejected with errors, not exceptions)
        - scope_roots: optional { scope: abs_root } override for path checks
          (tests inject tmpdirs; server uses the registry default)
        - require_checkable: True on a ->done transition (row 9bfb4b73). It adds
          the two CLOSING rules below; every other caller keeps the prior
          shape-only behaviour exactly.

    Ensures:
        - returns [] iff receipt_refs is a non-empty dict whose every key is
          whitelisted and every value passes its shape rule:
            commit   - 7-40 lowercase hex chars
            test_run - "ts-" + 8 hex chars (test-suite job id format)
            qid      - canonical lowercase UUID
            doc_path - "<scope>/<rel>" existing file in a registered scope
            log_line - "<scope>/<rel>:<lineno>" with the file existing
        - a non-empty-but-junk receipt ({doc_path: "trust me"}) returns errors
        - never raises on malformed input — errors are data, not exceptions

    WHAT require_checkable ADDS, AND WHY (row 9bfb4b73)

    A row was closed citing `receipt_refs` that named the closer's own EDITED
    FILE, while the same close's reason said "Uncommitted" — and the store took
    it. Two separate gaps let that through, and both are closed here:

    1. `doc_path` / `log_line` ARE UNVERIFIABLE BY CONSTRUCTION. The check is
       "the file exists", and a file exists whether or not any work landed — you
       can satisfy it by touching a file. So a path may still ACCOMPANY a close,
       but it may no longer BE the close. A ->done receipt must carry at least
       one thing a third party can independently check: a `commit` or a
       `test_run`.

    2. A `commit` WAS CHECKED BY SHAPE ONLY — 7-40 hex characters. "deadbeef"
       passes that. So does a real sha that has since been orphaned by a reset
       or rebase, which resolves today and is gone at the next gc. The commit is
       now required to be REACHABLE FROM SOME BRANCH.

    Deliberately NOT done: classifying a row as "code-bearing" to decide whether
    it needs a commit. That is a category test standing in for the property —
    the same mistake as the `--no-merges` filter and the withdrawn squash-shape
    detector. Every closing row must cite something checkable, full stop.

    ANY branch, never `main`: every commit landed on this branch tonight sits on
    a wip branch, and requiring main would refuse every legitimate pre-merge
    close and push people straight back to citing file paths — reintroducing gap
    1 while looking stricter.

    And when the store CANNOT check — no repo mounted, no scope root that is a
    git work tree — it REFUSES and says so. An unverifiable receipt accepted
    quietly is the same hole with extra steps.
    """
    if not isinstance( receipt_refs, dict ) or not receipt_refs:
        return [ f"receipt_refs must be a non-empty object with at least one whitelisted key {RECEIPT_KEY_WHITELIST}" ]

    errors = [ ]
    for key, value in receipt_refs.items():
        if key not in RECEIPT_KEY_WHITELIST:
            errors.append( f"unknown receipt key '{key}' — whitelist: {RECEIPT_KEY_WHITELIST}" )
            continue
        if not isinstance( value, str ) or not value:
            errors.append( f"receipt '{key}' must be a non-empty string" )
            continue

        if key == "commit" and not COMMIT_PATTERN.fullmatch( value ):
            errors.append( f"receipt commit '{value}' must be 7-40 lowercase hex chars" )
        elif key == "test_run" and not TEST_RUN_PATTERN.fullmatch( value ):
            errors.append( f"receipt test_run '{value}' must match 'ts-<8 hex chars>'" )
        elif key == "qid" and not QID_PATTERN.fullmatch( value ):
            errors.append( f"receipt qid '{value}' must be a canonical lowercase UUID" )
        elif key == "doc_path":
            errors.extend( _validate_scoped_path( value, scope_roots ) )
        elif key == "log_line":
            match = LOG_LINE_PATTERN.fullmatch( value )
            if not match:
                errors.append( f"receipt log_line '{value}' must be '<scope>/<rel-path>:<lineno>'" )
            else:
                errors.extend( _validate_scoped_path( match.group( 1 ), scope_roots ) )

    if require_checkable:
        present = [ k for k in CHECKABLE_RECEIPT_KEYS if isinstance( receipt_refs.get( k ), str ) and receipt_refs[ k ] ]
        if not present:
            errors.append(
                f"a ->done receipt must cite at least one INDEPENDENTLY CHECKABLE ref "
                f"{CHECKABLE_RECEIPT_KEYS} — got only {sorted( receipt_refs )}. A doc_path or "
                f"log_line proves a file exists, which is true whether or not the work landed; "
                f"it may accompany a close but cannot be the close (row 9bfb4b73)."
            )
        # Reachability is checked only on a shape-valid sha — otherwise the caller
        # would get two errors for one mistake, the second of them confusing.
        commit = receipt_refs.get( "commit" )
        if isinstance( commit, str ) and COMMIT_PATTERN.fullmatch( commit ):
            errors.extend( _validate_commit_reachable( commit, scope_roots ) )

    return errors


# ---------------------------------------------------------------------------
# Typed blocked_by refs (design §2.1)
# ---------------------------------------------------------------------------

def validate_blocked_by_refs( blocked_by ) -> list:
    """
    Validate a blocked_by value as a non-empty list of typed refs.

    Requires:
        - blocked_by is the candidate value (any type accepted; non-list and
          empty-list are rejected with errors, not exceptions)

    OPTIONAL `session_id` ON A PERSONA REF (row `00a6bde2` item 6, 2026-07-27).

    A `{kind: "persona", id: <name>}` edge is UNRESOLVABLE BY CONSTRUCTION — there is
    no persona lifecycle in this store to check a name against, so the edge cannot be
    told "still waiting" from "waiting on someone who left". Worse than a dead ref:
    overflow persona names (`extra 1`, `arnold`) are RE-GRANTED after a reap, so a
    stale edge can silently RE-POINT at a different session and be "satisfied" by
    someone who never had the context — a false GREEN, not a false wait.

    ⇒ `session_id` is the discriminator. Accepting it is the WRITE half of the remedy
    and it is worth landing alone, before any checker exists, because the cost of
    delay is ASYMMETRIC: an edge written unstamped today is permanently unresolvable
    by any later instrument, while a stamped one becomes checkable the moment a
    persona-liveness surface lands (blocked on `6f8fd858` — `list_spawned_sessions`
    carries no persona field, and `commons_who` is a posting log where absence means
    silence, not death).

    ⚠️ OPTIONAL, NOT REQUIRED. Making it mandatory would 422 every existing caller
    and every peer that has not been updated — turning a latent correctness gap into
    a live write outage. It is accepted-and-encouraged now; requiring it is a separate
    decision once the fleet's callers actually send it.

    ⚠️ PERSONA-ONLY, ENFORCED. On an `item` ref the id already resolves against this
    store, and a `user` ref has no session at all — so a `session_id` there would be a
    field that looks authoritative and means nothing, which is the shape this row
    exists to kill.

    Requires:
        - blocked_by is the candidate value (any type accepted; non-list and
          empty-list are rejected with errors, not exceptions)

    Ensures:
        - returns [] iff blocked_by is a non-empty list where every entry is
          { "kind": item|persona|user, "id": non-empty string } plus, on a persona
          ref ONLY, an optional non-empty "session_id" — TYPED refs, never a mixed
          string field (design §2.1)
        - unknown keys remain errors (strict shape — R4 determinism at exactly the
          field the oracle queries); `session_id` is the ONE key added to the allowed
          set, and only for persona
        - a `session_id` on a non-persona ref is an ERROR, not silently ignored
    """
    if not isinstance( blocked_by, list ) or not blocked_by:
        return [ "blocked_by must be a non-empty list of typed refs [{kind, id}]" ]

    errors = [ ]
    for i, ref in enumerate( blocked_by ):
        if not isinstance( ref, dict ) or not { "kind", "id" } <= set( ref.keys() ) \
           or not set( ref.keys() ) <= { "kind", "id", "session_id" }:
            errors.append( f"blocked_by[{i}] must be {{kind, id}} plus an optional session_id on a persona ref" )
            continue
        if ref[ "kind" ] not in VALID_BLOCKED_BY_KINDS:
            errors.append( f"blocked_by[{i}].kind '{ref['kind']}' must be one of {VALID_BLOCKED_BY_KINDS}" )
        if not isinstance( ref[ "id" ], str ) or not ref[ "id" ]:
            errors.append( f"blocked_by[{i}].id must be a non-empty string" )
        if "session_id" in ref:
            if ref[ "kind" ] != "persona":
                errors.append(
                    f"blocked_by[{i}].session_id is only meaningful on a {{kind:persona}} ref — "
                    f"an item id already resolves against this store and a user has no session" )
            elif not isinstance( ref[ "session_id" ], str ) or not ref[ "session_id" ]:
                errors.append( f"blocked_by[{i}].session_id must be a non-empty string when present" )

    return errors


def blocked_by_has_persona( blocked_by ) -> bool:
    """
    True iff `blocked_by` contains at least one {kind: "persona"} ref (I3 kind-aware
    chase rule, eab1d7da).

    The application-layer twin of the DB CHECK's `blocked_by @> '[{"kind":"persona"}]'`
    jsonb-containment test: a chase time is REQUIRED for a persona blocker (a peer is
    chaseable, so a chase is honest) and NOT for a user/item-only block (you cannot
    schedule Rick; an item resolves on its own edge). Kept a separate predicate rather
    than inlined so the rule and the CHECK are each expressed once and can be pinned to
    agree by test.

    Deliberately SHAPE-TOLERANT: it reads only well-formed persona refs and ignores
    everything else, because malformed `blocked_by` is `validate_blocked_by_refs`'s
    reject to surface — this predicate must never raise on the same input that function
    is about to reject, or a bad ref would 500 instead of 422.

    Requires:
        - blocked_by is the candidate value (any type accepted; non-list → False)

    Ensures:
        - True iff blocked_by is a list containing a dict ref whose kind == "persona"
        - False for None, non-list, empty list, or a list with no persona ref
        - never raises
    """
    if not isinstance( blocked_by, list ):
        return False
    return any(
        isinstance( ref, dict ) and ref.get( "kind" ) == "persona"
        for ref in blocked_by
    )


def validate_blocked_fields( blocked_by, next_chase_ts ) -> list:
    """
    The ->blocked structural invariant, expressed ONCE (I3 kind-aware chase +
    >=1 typed ref). Shared VERBATIM by validate_transition's ->blocked branch AND
    validate_create_status's blocked-MINT branch — one rule, one home, so a
    transition-into-blocked and a create-as-blocked can never diverge (Rick's
    one-call blocked-mint ruling 2026-07-20 reuses the SAME rule, never a fork).

    Requires:
        - blocked_by / next_chase_ts are the candidate payload fields (each any
          type; None accepted — this NEVER raises on malformed input, it returns
          the error strings the caller maps to 422)

    Ensures:
        - returns [] iff BOTH hold:
            next_chase_ts is present WHEN blocked_by contains a {kind:persona}
            ref (I3 — a peer is chaseable, so a chase is honest; a user/item-only
            block needs none: you cannot schedule Rick, an item resolves on its
            own edge)
            blocked_by passes validate_blocked_by_refs (>=1 typed ref)
        - returns every violation otherwise (both at once)
    """
    errors = [ ]
    if next_chase_ts is None and blocked_by_has_persona( blocked_by ):
        errors.append( "a persona blocker requires a chase time: next_chase_ts is REQUIRED when blocked_by contains a {kind:persona} ref (I3 — a peer is chaseable)" )
    errors.extend( validate_blocked_by_refs( blocked_by ) )
    return errors


# ---------------------------------------------------------------------------
# Task-reference classification — 8-hex prefix support (f45b37a9 leg 1)
# ---------------------------------------------------------------------------
#
# THE DEFECT: every brief, DM and cross-reference in this fleet names rows by
# 8-hex prefix, and NO READ VERB ACCEPTED THAT FORM. `task_get("86ce4c43")`
# returned a 422 uuid_parsing error, so the identifier the fleet actually
# communicates in could not fetch the thing it names.
#
# ⚠️ READS ONLY. The mutating routes keep strict uuid.UUID typing. A prefix that
# resolves to the wrong row on a READ is merely wrong; on a transition it is
# DESTRUCTIVE — it would move a row nobody named. The convenience is worth
# having exactly where the blast radius is zero, and a test asserts the fence.

TASK_REF_FULL    = "full"
TASK_REF_PREFIX  = "prefix"
TASK_REF_INVALID = "invalid"

# A ref must be at least this many hex chars to be a usable prefix. One or two
# characters would match a large fraction of a growing table and the resulting
# "ambiguous" error would name too many candidates to be actionable — the
# unscoped-query defect wearing a different hat.
MIN_TASK_REF_PREFIX_LEN = 4


def hyphenate_compact_prefix( compact_prefix ) -> str:
    """
    Re-insert canonical UUID hyphens into a compact hex prefix. Pure.

    THE ONE IMPLEMENTATION, on purpose. A compact prefix cannot be LIKE-matched
    against the stored id directly: ids render hyphenated, so any prefix longer
    than 8 chars crosses a boundary the compact form does not have. This logic
    lived only inside `TaskRepository.find_by_id_prefix`; the moment a SECOND
    caller needed it (the `id_prefix` query filter) a copy would have been the
    obvious move — and a second copy of a matching rule is how two read paths
    start disagreeing about which rows an identifier names. That is the
    parallel-construction hazard row f45b37a9 is itself about.

    Requires:
        - compact_prefix is lowercase hex with hyphens already stripped, as
          `classify_task_ref` returns for TASK_REF_PREFIX

    Ensures:
        - returns the prefix re-hyphenated at 8-4-4-4-12 positions, truncated to
          the supplied length (no trailing hyphen for an exact-boundary prefix)
        - a prefix shorter than 8 chars is returned unchanged
        - never raises
    """
    chunks = [ ( 0, 8 ), ( 8, 12 ), ( 12, 16 ), ( 16, 20 ), ( 20, 32 ) ]
    parts  = [ compact_prefix[ start:end ] for start, end in chunks if compact_prefix[ start:end ] ]
    return "-".join( parts )


def classify_task_ref( ref ) -> tuple:
    """
    Classify a caller-supplied task reference as a full UUID, a hex prefix, or
    invalid. Pure — no DB, no HTTP.

    Requires:
        - ref is the raw caller value (any type; None and non-strings accepted
          and classified INVALID rather than raising — errors are data)

    Ensures:
        - returns ( kind, value )
        - a canonical UUID (any accepted UUID spelling) -> ( TASK_REF_FULL,
          uuid.UUID instance )
        - a hex string of >= MIN_TASK_REF_PREFIX_LEN chars, hyphens tolerated
          (that is what a partially-copied UUID looks like), -> ( TASK_REF_PREFIX,
          lowercased hex with hyphens stripped ). Lowercased because the stored
          id renders lowercase and the comparison must not depend on how the
          caller happened to paste it
        - anything else -> ( TASK_REF_INVALID, None ). Junk must NEVER classify
          as a prefix: a LIKE built from arbitrary caller text turns an id lookup
          into a search surface
    """
    if not isinstance( ref, str ):
        return ( TASK_REF_INVALID, None )

    candidate = ref.strip()
    if not candidate:
        return ( TASK_REF_INVALID, None )

    try:
        return ( TASK_REF_FULL, uuid.UUID( candidate ) )
    except ( ValueError, AttributeError, TypeError ):
        pass

    compact = candidate.replace( "-", "" ).lower()
    if len( compact ) >= MIN_TASK_REF_PREFIX_LEN and all( c in "0123456789abcdef" for c in compact ):
        return ( TASK_REF_PREFIX, compact )

    return ( TASK_REF_INVALID, None )


# ---------------------------------------------------------------------------
# Per-status field normalization — THE SINGLE SOURCE (86ce4c43 #2, 2026-07-21)
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS AT ALL: `TaskRepository.create_item` and
# `TaskRepository.apply_transition` used to implement these rules INDEPENDENTLY.
# create_item's docstring admitted it — it owned per-status consistency "the same
# way apply_transition does". Two implementations of one invariant by
# acknowledged parallel construction, with NOTHING enforcing agreement: a
# divergence produces a store where a value survives a create and dies on the
# next transition, silently, and green. Both callers now route through here.
#
# THE BEHAVIOR CHANGE: `next_chase_ts` is NO LONGER nulled outside
# blocked/parked. A chase is a SCHEDULE, not a WAIT. "A queued row waits on
# nothing" is true about DEPENDENCIES and says nothing about SCHEDULING — and
# conflating the two is what forced a seat to mark a merely-scheduled row
# `blocked_by {kind:user, id:rick}`, asserting a false dependency on the
# principal (86ce4c43 defect #2). The DB never forbade this: BOTH CHECK
# constraints are one-directional implications that COMPEL a chase in two states
# and forbid one nowhere, so this DELETES AN APPLICATION-LAYER DELETION rather
# than adding a schema capability. No migration.
#
# ⚠️ THE ASYMMETRY IS DELIBERATE: `blocked_by` keeps its per-status clearing
# while the chase does not. A blocked_by ref is a DEPENDENCY whose meaning is
# defined by the blocked status, so a non-blocked row genuinely holds none. A
# chase is independent of status. That distinction IS the fix.
#
# ⚠️ OUT OF SCOPE BY RULING (Mr Radio, 2026-07-21): a queued row with a FUTURE
# chase STILL COUNTS AS OWED. The suppression shape exists in task_store_owed
# (`park_is_active`) and was deliberately NOT copied — `parked` earns its
# exclusion because a HUMAN ruled the row not-now and the chase bounds that
# ruling, with a quoted park_reason the next reader can refute. A chase on a
# queued row is a schedule with nobody's ruling behind it; copying the clause
# would let any caller silence a row from the fleet's liveness oracle with a
# timestamp and no human in the loop. Scheduled-not-owed needs its own
# ratification with stop.py and the arbiter named as consumers.

def normalize_status_fields( status, blocked_by, next_chase_ts ) -> tuple:
    """
    Resolve the status-dependent fields for a write, and REPORT what was dropped.

    The single source of per-status field consistency for BOTH repository write
    paths (create_item and apply_transition). Pure — no DB, no HTTP, no clock.

    A normalizer that CANNOT silently drop (crew doctrine, Rachel 71061fb4): "a
    rule that says 'be loud' is a rule someone forgets; a normalizer that cannot
    silently drop is a mechanism." Anything discarded here is named in the second
    return value, so a caller cannot fail to know it happened. That generalizes
    past this fix to whatever field gets added next.

    Requires:
        - status is the TARGET status (already whitelist-validated by the caller;
          this function normalizes, it does not validate)
        - blocked_by is the candidate typed-ref list, or None
        - next_chase_ts is the candidate chase time, or None

    Ensures:
        - returns ( resolved, dropped )
        - resolved is a dict with EXACTLY the keys "blocked_by" and
          "next_chase_ts"
        - resolved["blocked_by"] is the given list when status == "blocked"
          (None -> []), and [] for EVERY other status — a non-blocked row waits
          on nothing
        - resolved["next_chase_ts"] is ALWAYS the caller's value, on every
          status. The caller alone determines the chase; supplying None means
          None. This is what preserves every existing caller's behavior — the
          only case that changes is the one where a caller supplied a chase and
          it was thrown away
        - dropped is a list of field names whose caller-supplied value was
          DISCARDED — "blocked_by" appears iff a NON-EMPTY blocked_by was emptied
        - dropped is [] (never None) when nothing was discarded, so a legitimate
          zero is readable without a truthiness trap
        - an already-empty blocked_by is NEVER reported as dropped: discarding []
          to [] discards nothing, and reporting it would train readers to ignore
          the list — which is how a real signal becomes noise
    """
    dropped = [ ]

    if status == "blocked":
        resolved_blocked_by = blocked_by if blocked_by is not None else [ ]
    else:
        # Every non-blocked status (including parked) waits on nothing.
        resolved_blocked_by = [ ]
        if blocked_by:
            dropped.append( "blocked_by" )

    return (
        { "blocked_by" : resolved_blocked_by, "next_chase_ts" : next_chase_ts },
        dropped,
    )


# The audit marker a discarded value leaves behind. Kept as a MODULE CONSTANT
# prefix so a future reader can grep the audit trail for discards instead of
# parsing free prose — the whole complaint 86ce4c43 makes about reason strings.
DROPPED_MARKER_PREFIX = "[dropped: "


def compose_drop_marker( dropped, existing_reason=None ) -> Optional[str]:
    """
    Fold a normalizer drop-list into an event reason, so a discard lands in the
    AUDIT TRAIL rather than in a docstring nobody re-reads.

    This is what makes "the normalizer cannot silently drop" a MECHANISM rather
    than a convention: `normalize_status_fields` reporting a discard to a caller
    that binds it to `_dropped` and throws it away is the same silence one layer
    up. Both repository write paths compose their event reason through here.

    Requires:
        - dropped is the normalizer's second return value (a list of field
          names; [] when nothing was discarded)
        - existing_reason is the caller's own reason string, or None

    Ensures:
        - dropped is empty -> returns existing_reason UNCHANGED (including None).
          A no-op discard must not manufacture an audit reason out of nothing,
          or every row grows a marker and the marker stops meaning anything
        - dropped is non-empty -> returns a string containing DROPPED_MARKER_PREFIX
          followed by the comma-joined field names
        - an existing reason is PRESERVED, never replaced — the caller's
          justification and the machine's disclosure both survive
    """
    if not dropped:
        return existing_reason

    marker = f"{DROPPED_MARKER_PREFIX}{', '.join( dropped )}]"
    if existing_reason:
        return f"{existing_reason} {marker}"
    return marker


# ---------------------------------------------------------------------------
# Creation + transition rules
# ---------------------------------------------------------------------------

# The statuses a CREATE may mint (Rick's ruling 2026-07-20). `queued` is the
# default (today's behavior preserved); `blocked` mints an already-blocked row in
# ONE call. Terminal (done/dropped) is rejected — those need receipts / a drop
# reason and an audit history a fresh row has none of. `parked` is rejected — it
# needs park_reason + captured_at and is legal ONLY from queued/in_progress (a
# human ruling EXISTING work not-now), never at mint. `claimed`/`in_progress`/
# `review` are transition-only lifecycle states, not mintable.
CREATE_ALLOWED_STATUSES = ( "queued", "blocked" )

def validate_create( item_class: str, gate_class: str, priority: str, authority: str,
                     urgency: str = "normal" ) -> list:
    """
    Validate the enum fields of a new item (creation is always status=queued —
    the creation event stamps "->queued"; transitions move it from there).

    Requires:
        - item_class, gate_class, priority, authority are the candidate
          string values (authority stamps the "->queued" creation event)
        - urgency is the candidate operator-gate time-sensitivity (default
          "normal"); A2 proactive-manager dimension, distinct from priority

    Ensures:
        - returns [] iff all five are members of their enums
        - one error string per offending field otherwise
    """
    errors = [ ]
    if item_class not in VALID_ITEM_CLASSES:
        errors.append( f"item_class '{item_class}' must be one of {VALID_ITEM_CLASSES}" )
    if gate_class not in VALID_GATE_CLASSES:
        errors.append( f"gate_class '{gate_class}' must be one of {VALID_GATE_CLASSES}" )
    if priority not in VALID_PRIORITIES:
        errors.append( f"priority '{priority}' must be one of {VALID_PRIORITIES}" )
    if authority not in VALID_AUTHORITIES:
        errors.append( f"authority '{authority}' must be one of {VALID_AUTHORITIES}" )
    if urgency not in VALID_URGENCIES:
        errors.append( f"urgency '{urgency}' must be one of {VALID_URGENCIES}" )
    return errors


def validate_create_status( status, blocked_by, next_chase_ts ) -> list:
    """
    Validate the MINT status of a new item (Rick's one-call blocked-mint ruling,
    2026-07-20). A create may mint status = queued OR blocked ONLY.

    This is the STATUS-WHITELIST half of the ruling; the MANAGER-ONLY guard for a
    blocked mint is enforced SEPARATELY in the router (create_task), because it
    needs bridge IO to resolve the caller's role and this module is pure (no DB,
    no HTTP). Keeping the two apart is deliberate: the whitelist is a data rule
    (testable with no config), the guard is an authorization rule.

    Requires:
        - status is the candidate mint status (any string)
        - blocked_by / next_chase_ts are the candidate payload fields (only read
          when status == "blocked"); each any type, None accepted

    Ensures:
        - status not in CREATE_ALLOWED_STATUSES -> one error naming the whitelist
          and WHY the rejected states are off it (done/dropped need receipts +
          audit history; parked needs park_reason + is legal only from
          queued/in_progress; claimed/in_progress/review are transition-only).
          This SHORT-CIRCUITS — the blocked-field rules are meaningless without a
          valid mint status (symmetry with validate_transition's to_status guard)
        - status == "blocked" -> the SAME ->blocked invariant a transition enforces,
          via validate_blocked_fields (>=1 typed ref AND a kind-aware chase) — the
          rule is reused, NEVER forked
        - status == "queued" -> [] (blocked_by / next_chase_ts are ignored — a
          queued mint carries neither, preserving today's behavior exactly)
        - never raises — every violation is a returned string the router maps to 422
    """
    if status not in CREATE_ALLOWED_STATUSES:
        return [
            f"status '{status}' cannot be minted at create — a create may mint only "
            f"{CREATE_ALLOWED_STATUSES}. done/dropped need receipts + audit history, "
            f"parked needs a park_reason and is legal only from queued/in_progress, "
            f"and claimed/in_progress/review are transition-only. Transition after create."
        ]
    if status == "blocked":
        return validate_blocked_fields( blocked_by, next_chase_ts )
    return [ ]


# ---------------------------------------------------------------------------
# Soft title guard (design 2026.06.29 task-list row redesign — §4.3 / handoff #1)
# ---------------------------------------------------------------------------

# The soft title-length cap (handoff #5 / D4): ~60 chars, applied IDENTICALLY to
# this store-side guard AND each client's render-truncation backstop (one number
# at every layer). Tune later if real rows warrant.
#
# ⚠️ "One number at every layer" was FALSE from the day PATCH /api/tasks/{id}
# gained an editable `title` until 2026-07-21: that path never called this guard,
# so the same string was capped at 60 through create and unbounded through PATCH.
# Both write paths now route through soft_guard_title (bug 28fc1fb4). The claim is
# true again — it is recorded here rather than quietly corrected because a comment
# that was wrong for months is evidence about how this file gets maintained.
TITLE_SOFT_CAP = 60

# The marker the relocated title overflow is filed under when the body is NOT
# empty (bug 28fc1fb4, 2026-07-21). It is a literal, greppable line rather than
# a bare prepend so the overflow is recoverable BY SEARCH across the whole store
# — a reader who never saw the write can still find every row whose title was
# cut, and reconstruct the original from `title + overflow`.
TITLE_OVERFLOW_MARKER = "[title overflow — the stored title was trimmed at the cap; the original continues here]"


def soft_guard_title( title, body, cap=TITLE_SOFT_CAP ):
    """
    Non-destructively soft-guard an over-long item title on write (design
    2026.06.29 task-list row redesign §4.3, handoff ruling #1).

    Workers stuff whole paragraphs into the `title` field; the row clients can
    only show ~60 chars and the store's `body` field (the proper home for
    detail) sits underused. This guard fixes the data at its SOURCE — the one
    server-side write path EVERY caller (MCP wrapper, hook, raw POST) flows
    through — so a paragraph-title never lands in the store unguarded. It is
    FAIL-OPEN by ruling: an over-long title is NEVER a rejected write.

    Requires:
        - title is a non-empty string (the column is NOT NULL; the wire model
          already rejects an empty title)
        - body is the candidate body value — a string or None
        - cap is a positive int (the shared ~60 char limit)

    THE OVERFLOW IS NEVER DISCARDED (bug 28fc1fb4, fixed 2026-07-21). It used to
    be relocated ONLY when the body was empty; a non-empty body meant the
    remainder was dropped at exit 0, with `overflow_moved_to_body: false` as the
    sole record that anything was lost. That condition ran BACKWARDS AGAINST NEED:
    it preserved the overflow for title-only rows — where the title IS the content
    and least is at stake — and discarded it for every row carrying a body, which
    is every substantive filing in the store. Sam recorded the same fact from the
    other side without naming it as the mechanism: "the bodies survived only
    because I habitually put everything in the body." The guard protected the
    careless filer and robbed the careful one.

    The original ruling — "an existing body always wins" — forbade CLOBBERING a
    body, and it still holds: the pre-existing body is preserved verbatim, in
    full, and the overflow is filed under TITLE_OVERFLOW_MARKER. Adding to a body
    is not overwriting one, so nothing about that ruling is reversed.

    ⚠️ THE OVERFLOW IS APPENDED, NOT PREPENDED (row a6cb24e8, 2026-08-31). It was
    prepended until now, and prepending damages the body in a way the ruling was
    never asked about: the body's own opening line stops being the first thing a
    reader sees, and a RETITLE over the cap prepends a SECOND marker above the
    first. Tiberius 👑 and Maya 🌻 hit that independently within minutes — a body
    opening with two stacked banners and the fragment "us", the tail of the word
    "Tiberius", with the real opening line buried two blocks down. Both had to be
    unpicked by hand.

    Appending satisfies the same ruling and costs the reader nothing: the body
    still wins, still appears verbatim, and now still STARTS where its author
    started it. Stacked overflows from repeated retitles collect at the foot in
    the order they happened, which is a readable history instead of a corrupted
    head. The marker STRING is deliberately unchanged so the grep-recovery
    property holds for rows written before this.

    ⚠️ WHAT THIS DOES NOT FIX, and nobody should read it as fixing: the trim still
    silently deletes the TAIL of a title, which is where writers put qualifiers —
    "…DECLINED", "CONDITIONAL on…", "…by design". Six instances in one night each
    lost a word whose job was to LIMIT the claim in front of it. The three fixes
    that would address THAT — reject over-cap writes, mark the trim where readers
    are, raise the cap — each collide with something this file or its clients
    already state, so they belong to Rick and not to this change. Row a6cb24e8.

    Requires:
        - title is a non-empty string (the column is NOT NULL; the wire model
          already rejects an empty title)
        - body is the candidate body value — a string or None
        - cap is a positive int (the shared ~60 char limit)

    Ensures:
        - title length <= cap -> returns ( title, body, None ): a strict no-op,
          nothing trimmed, no advisory, body byte-for-byte unchanged
        - title length  > cap -> returns ( title[:cap], new_body, advisory ):
            * the stored title is trimmed to EXACTLY cap chars
            * when body is empty (None / whitespace-only): new_body IS the
              overflow (title[cap:]) — unmarked, because there is nothing for it
              to be distinguished FROM
            * when body is non-empty: new_body is the ORIGINAL BODY VERBATIM,
              then the marker line, then the overflow — in that order. The
              pre-existing body is never truncated, reordered, or rewritten,
              and its FIRST LINE is never displaced (see the append note below)
            * `title + <the overflow substring of new_body>` reconstructs the
              original title EXACTLY, on BOTH arms — nothing is ever lost
            * advisory is { trimmed, original_length, cap,
              overflow_moved_to_body, lost_tail }, and overflow_moved_to_body is
              now True on BOTH arms because both arms relocate
            * `lost_tail` is the exact text cut from the title — the same string
              relocated into the body — so the writer is shown the words they lost
              rather than a count of them. It is advisory ONLY: it changes nothing
              about what is stored, rejects nothing, and leaves the fail-open
              ruling and the exact-reconstruction guarantee untouched
        - never raises; never returns a title longer than cap
    """
    if len( title ) <= cap:
        return title, body, None

    trimmed       = title[ :cap ]
    overflow      = title[ cap: ]
    body_is_empty = body is None or not body.strip()

    advisory = {
        "trimmed"               : True,
        "original_length"       : len( title ),
        "cap"                   : cap,
        "overflow_moved_to_body": True,
        # THE WORDS THAT FELL OFF, not just how many (row a6cb24e8, 2026-08-31).
        # The advisory used to report only a LENGTH, so a writer had to reconstruct
        # what was cut from a number. Seven titles lost their qualifier in one night
        # and nobody noticed, including three seats who had this advisory in hand.
        # `original_length: 106` is a fact about a string; "by design" is the claim
        # you just deleted. Showing the text is what makes the advisory readable at
        # the speed people actually read tool output.
        "lost_tail"             : overflow,
    }
    if body_is_empty:
        return trimmed, overflow, advisory
    return trimmed, f"{body}\n\n{TITLE_OVERFLOW_MARKER}\n{overflow}", advisory


# ---------------------------------------------------------------------------
# Persona roster + policy helpers (persona-key follow-on policy, 2026-07-11)
# ---------------------------------------------------------------------------
#
# Two soft, non-blocking policies spun out of bug 951a22be (design note
# src/rnd/v0.1.9/2026.07.11-persona-key-followon-policy.md):
#
#   (1) UNKNOWN-PERSONA SOFT-FLAG: an owner_persona / accountable_manager that
#       matches NO known persona earns a log-warn + advisory — NEVER a 422 (new
#       / cross-project personas are legitimately absent from any roster).
#   (2) CLASS-SCOPED OWNER DEFAULT: an owned-work item (task/bug/review_request)
#       created without an owner_persona defaults to the creator's persona.
#
# The roster is config-derived, so it is exposed to this pure module by the SAME
# lazy-singleton-with-injectable-override pattern receipt validation already uses
# (_get_default_scope_roots + the scope_roots= param): _get_known_persona_keys()
# builds once from the voice-persona pool; build_persona_advisory takes a
# known_keys= override so every policy branch is unit-testable WITHOUT live config.

_KNOWN_PERSONA_KEYS: Optional[set] = None  # lazy singleton — None means "not built yet"

# A session-id tail on a bridge-stamped created_by ("<persona> <8-hex sid>",
# task_store_tools.py) is >=6 lowercase-hex chars. The >=6 floor keeps a short
# hex-looking persona WORD (e.g. "beef", 4 chars) from being mistaken for a sid
# and stripped off the persona.
_SESSION_ID_TAIL_PATTERN = re.compile( r"[0-9a-f]{6,}" )


def _get_known_persona_keys() -> set:
    """
    Build (once per process) the set of canonical keys for every KNOWN persona,
    reusing the voice-persona pool loader (design D1: the pool loader in
    voice_persona_helpers IS the roster accessor — no second INI reader).

    Twins _get_default_scope_roots: a lazy config-backed singleton, lazily
    importing the config dependency so this pure module stays import-light.

    Requires:
        - ConfigurationManager singleton is constructible (server context)

    Ensures:
        - returns a set of canonical_persona_key values for the allocatable pool
          PLUS the overflow persona (each name canonicalized to the store key —
          the INI keeps mixed case "Rachel"/"Tiberius", the store key is lower)
        - built exactly once; subsequent calls return the cached set
    """
    global _KNOWN_PERSONA_KEYS
    if _KNOWN_PERSONA_KEYS is None:
        from cosa.rest.dependencies.config import get_config_manager
        from cosa.rest.voice_persona_helpers import (
            load_persona_pool_from_config,
            load_overflow_persona_from_config,
        )

        config_mgr = get_config_manager()
        keys       = set()
        for persona in load_persona_pool_from_config( config_mgr ):
            key = canonical_persona_key( persona[ "name" ] )
            if key:
                keys.add( key )
        overflow = load_overflow_persona_from_config( config_mgr )
        if overflow is not None:
            overflow_key = canonical_persona_key( overflow[ "name" ] )
            if overflow_key:
                keys.add( overflow_key )
        _KNOWN_PERSONA_KEYS = keys
    return _KNOWN_PERSONA_KEYS


def persona_from_created_by( created_by ) -> str:
    """
    Extract the canonical persona key from a bridge-stamped created_by string.

    created_by is contract-stamped "<persona> <8-hex session id>"
    (task_store_tools.py, e.g. "mr radio 372f9dc9"). The class-scoped owner
    default (policy 2) needs the persona WITHOUT the session-id tail — but the
    persona itself may contain spaces, so a plain split is wrong. This strips a
    trailing session-id-shaped token (>=6 lowercase-hex chars) and canonicalizes
    the remainder; a created_by with no such tail canonicalizes whole.

    Requires:
        - created_by is the candidate value (any type; only a non-empty str is
          transformed)

    Ensures:
        - None / non-string / empty -> "" (canonical_persona_key's unmatchable
          sentinel — the caller treats "" as "no derivable owner")
        - "<persona> <hex sid>" -> canonical_persona_key( "<persona>" )
          ("mr radio 372f9dc9" -> "mr radio")
        - a value with no session-id-shaped tail -> canonical_persona_key( whole )
          ("krishna" -> "krishna")
    """
    if not created_by or not isinstance( created_by, str ):
        return ""
    parts = created_by.rsplit( " ", 1 )
    if len( parts ) == 2 and _SESSION_ID_TAIL_PATTERN.fullmatch( parts[ 1 ] ):
        candidate = parts[ 0 ]
    else:
        candidate = created_by
    return canonical_persona_key( candidate )


def session_id_from_created_by( created_by ) -> Optional[str]:
    """
    Extract the SESSION-ID tail from a bridge-stamped created_by string — the
    INVERSE of persona_from_created_by.

    created_by is contract-stamped "<persona> <8-hex session id>"
    (task_store_tools.py). The manager-only blocked-MINT guard (create_task) needs
    the SID to resolve the caller's bridge role via is_manager_figure. Returns the
    trailing session-id-shaped token (>=6 lowercase-hex chars), or None when
    created_by carries no such tail — the guard then treats the caller as a
    NON-manager (fail-CLOSED, the correct degrade for a WRITE authorization).

    Requires:
        - created_by is the candidate value (any type; only a non-empty str is
          parsed)

    Ensures:
        - None / non-string / empty -> None
        - "<persona> <hex sid>" -> the hex sid ("Cheech 4d376217" -> "4d376217")
        - a value with no session-id-shaped tail -> None (there is no sid to give,
          and fabricating one would defeat the guard)
    """
    if not created_by or not isinstance( created_by, str ):
        return None
    parts = created_by.rsplit( " ", 1 )
    if len( parts ) == 2 and _SESSION_ID_TAIL_PATTERN.fullmatch( parts[ 1 ] ):
        return parts[ 1 ]
    return None


def build_persona_advisory( owner_persona, accountable_manager, known_keys=None ):
    """
    Flag off-roster persona fields (policy 1) — the pure roster check + advisory
    + folded-marker assembly, shared by the create and reassign (PATCH) paths.

    Each of owner_persona / accountable_manager is canonicalized and tested for
    roster membership; a value matching no known persona is flagged. This NEVER
    rejects — the router attaches the advisory to the response, logs a warn, and
    folds the marker into the event reason, but the write always proceeds.

    Requires:
        - owner_persona / accountable_manager are the candidate values (str or
          None; already canonical from the router's _canon_persona, but this
          re-canonicalizes defensively — idempotent — so it is correct on a raw
          display value too)
        - known_keys is an explicit roster set to test against, or None to use
          the process-default _get_known_persona_keys() singleton (tests inject
          a fixed set; server uses the config-derived default)

    Ensures:
        - returns ( None, None ) when neither field is a non-empty off-roster key
          (an absent / blank / on-roster persona is NOT flagged)
        - otherwise returns ( advisory, marker ):
            * advisory = { field_name: canonical_key } for each off-roster field
              (owner_persona and/or accountable_manager)
            * marker   = a compact "[persona_flag: owner 'x', manager 'y'
              off-roster]" string for folding into the audit-event reason
        - never raises
    """
    roster  = known_keys if known_keys is not None else _get_known_persona_keys()
    flagged = { }
    for field_name, value in ( ( "owner_persona", owner_persona ), ( "accountable_manager", accountable_manager ) ):
        key = canonical_persona_key( value )
        if key and key not in roster:
            flagged[ field_name ] = key

    if not flagged:
        return None, None

    parts = [ ]
    if "owner_persona" in flagged:
        parts.append( f"owner '{flagged[ 'owner_persona' ]}'" )
    if "accountable_manager" in flagged:
        parts.append( f"manager '{flagged[ 'accountable_manager' ]}'" )
    marker = f"[persona_flag: {', '.join( parts )} off-roster]"
    return flagged, marker


def is_blocker_repoint( from_status, to_status, blocked_by, next_chase_ts,
                        current_blocked_by, current_next_chase_ts ):
    """
    Is this `blocked`->`blocked` a genuine RE-POINT (the blocker or its chase
    actually moved), as opposed to a true no-op?

    THE DEFECT THIS OPENS THE DOOR FOR (bee6856a). There was no legal way to
    change WHO a blocked row is blocked on: this edge was refused, `task_edit`
    refuses the invariant-bearing fields, and `task_amend` is body-only. The
    only way through was `blocked -> in_progress -> blocked`, which writes a
    `blocked->in_progress` event asserting work RESUMED on a row where none did.
    A reason string on that event is a mitigation, not a fix — it makes a human
    read prose to un-learn what the structured field says, and any tooling
    counting in_progress transitions is simply lied to. Re-pointing is routine
    (a manager re-spins, a blocking peer is reaped, a decision escalates to the
    user), so the false event recurs by design rather than by accident.

    WHAT THE OLD REJECTION WAS GUARDING: nothing designed. LEGAL_TRANSITIONS is
    derived by `dst != src`, and its header calls that BEHAVIOR-PRESERVING — it
    made the Phase-1 IMPLICIT graph explicit "so a future TIGHTENING has one
    home". Nobody chose to forbid this edge; it was not callable in Phase 1, and
    making the graph explicit froze an accident into a rule.

    ⇒ SCOPED TO `blocked` ALONE, DELIBERATELY. The risk here is WIDENING, not
    un-guarding: a general "permit same-status when the payload differs" would
    silently open queued->queued, in_progress->in_progress, review->review and
    parked->parked — four edges that each write an audit event and mean nothing.
    The graph itself is NOT modified, so the mirror-edge regression and both
    graph-shape tests hold unchanged; this is a carve-out at the point of use.

    Requires:
        - from_status / to_status are valid statuses
        - blocked_by / next_chase_ts are the CANDIDATE payload values
        - current_* are the row's values BEFORE this transition (VALUES, never
          the ORM item — this module is pure and must not import the model)

    Ensures:
        - returns True iff from_status == to_status == "blocked" AND at least
          one of (blocked_by, next_chase_ts) differs from its current value
        - returns False when the current values are absent — a caller that does
          not supply them gets the old behaviour, so the carve-out can never
          fire on absence of evidence (fail CLOSED)
        - returns False for every other status pair, including every other
          same-status pair
        - NEVER relaxes the ->blocked payload rules: this opens an EDGE, and
          validate_blocked_fields still runs on the result
    """
    if from_status != "blocked" or to_status != "blocked":           return False
    if current_blocked_by is None and current_next_chase_ts is None: return False
    return blocked_by != current_blocked_by or next_chase_ts != current_next_chase_ts


def is_park_refresh( from_status, to_status, park_reason, next_chase_ts ):
    """
    Is this `parked`->`parked` a genuine QUOTE REFRESH (re-freezing a park reason
    against the row's current content), as opposed to a true no-op?

    ⚠️ THIS REVERSES A DELIBERATE PRIOR RULING, ON EVIDENCE (row aa543525,
    2026-07-27). `is_blocker_repoint` above scoped its carve-out to `blocked`
    alone and named this very edge as one it was right to leave shut: *"a general
    'permit same-status when the payload differs' would silently open
    queued->queued, in_progress->in_progress, review->review and parked->parked —
    four edges that each write an audit event and MEAN NOTHING."* That reasoning
    was sound for three of the four. It is wrong for `parked`, and the difference
    is mechanical rather than a matter of taste:

        a ->parked write re-stamps `park_reason_captured_at` AND `updated_ts` to
        ONE instant (task_repository), which is the whole definition of a park
        whose justification is current.

    So a re-park is not an event that means nothing — it is the ONLY operation
    that restores the post-park equality invariant. Every other same-status edge
    really would write a nullity.

    THE DEFECT THIS CLOSES, and it is the same shape `is_blocker_repoint` closed.
    `task_store_tools` prescribes *"Re-park to re-freeze the quote"* as the remedy
    for a stale park reason, and that remedy was UNREACHABLE through TWO
    independent gates: park-legality refused `parked` as a source, and this graph
    refused the edge as a no-op. A seat that noticed its own park reason had
    rotted had to go `parked -> queued -> parked`, which CLEARS the quote on the
    way out and writes a `parked->queued` event asserting the row REJOINED the
    owed set — on a row nobody un-parked. A false event, recurring by design.

    ⇒ SCOPED TO `parked` ALONE, DELIBERATELY, for exactly the reason quoted above.
    The graph itself is NOT modified; this is a carve-out at the point of use, so
    the mirror-edge regression and both graph-shape tests hold unchanged.

    NO "payload differs" TEST, and that asymmetry with `is_blocker_repoint` is
    deliberate: a re-park with a byte-identical reason and an identical chase is
    still meaningful, because the capture timestamp moves and that is the point of
    the operation. Requiring a changed quote would refuse the commonest honest
    case — *"I reviewed this park and it is still exactly right."*

    Requires:
        - from_status / to_status are valid statuses
        - park_reason / next_chase_ts are the CANDIDATE payload values

    Ensures:
        - returns True iff from_status == to_status == PARK_STATUS AND the park
          payload is present (non-blank reason AND a chase)
        - returns False when either payload field is absent — fail CLOSED, so a
          caller that omits the park fields gets the old rejection rather than a
          silently-permitted nullity
        - returns False for every other status pair, including every other
          same-status pair
        - NEVER relaxes the ->parked payload rules: this opens an EDGE, and
          validate_park still runs on the result
    """
    if from_status != PARK_STATUS or to_status != PARK_STATUS:            return False
    if not isinstance( park_reason, str ) or not park_reason.strip():     return False
    return next_chase_ts is not None


def validate_transition(
    from_status   : str,
    to_status     : str,
    authority     : str,
    receipt_refs  = None,
    next_chase_ts = None,
    blocked_by    = None,
    reason        = None,
    scope_roots   : Optional[dict] = None,
    park_reason   = None,
    current_blocked_by    = None,
    current_next_chase_ts = None,
) -> list:
    """
    Validate one state transition against the Phase-1/2 structural rules.

    The full legal-transition graph is Phase-2+ backlog (design §4.1 C-items);
    enforced here are enum validity + the ratified structural rules only.

    Requires:
        - from_status is the item's CURRENT status (read inside the same DB
          session that will apply the transition)
        - to_status / authority are the candidate values
        - receipt_refs / next_chase_ts / blocked_by / reason are the candidate
          payload fields (each may be None)
        - scope_roots: optional override for receipt path checks (tests)

    Ensures:
        - returns [] iff ALL hold:
            to_status is a valid status and differs from from_status
            authority is a valid authority
            from_status is not terminal (done/dropped are append-only — gate
            ruling #4: the audit invariant made mechanical)
            to_status == done  => receipt_refs passes validate_receipt_refs
            receipt_refs present on ANY transition => it passes
            validate_receipt_refs (cold-review N2 — the §5 receipt-theater
            guard outranks the design letter's done-only wording: junk never
            lands in the audit trail)
            to_status == blocked => next_chase_ts present (I3) AND blocked_by
            passes validate_blocked_by_refs (gate ruling #5)
            to_status == dropped => reason is a non-blank string (C12 pulled
            forward into Phase 2, Tiberius ruling qid b312b0f1 — the T3
            escape hatch must carry its justification)
        - reason is OPTIONAL on every other transition (free text, no shape
          rule — length is capped at the wire by the router's Pydantic model)
        - returns the full list of violations otherwise — every problem at
          once, with ONE exception: an invalid to_status short-circuits
          (the dependent receipt/blocked/reason rules are meaningless without
          a valid target state)
    """
    if to_status not in VALID_STATUSES:
        return [ f"to_status '{to_status}' must be one of {VALID_STATUSES}" ]
    # from_status comes from a free VARCHAR column (no enum CHECK) on a now-LIVE
    # write path — short-circuit an unknown source as a DATA error (symmetry with
    # to_status above), so the LEGAL_TRANSITIONS[from_status] lookup below can
    # never KeyError. Errors are data, not exceptions (D-DELTA, 2026-06-15).
    if from_status not in VALID_STATUSES:
        return [ f"from_status '{from_status}' must be one of {VALID_STATUSES}" ]

    errors = [ ]
    if authority not in VALID_AUTHORITIES:
        errors.append( f"authority '{authority}' must be one of {VALID_AUTHORITIES}" )
    # Legal-graph adjacency (Phase 2.1 D-DELTA-1): consult the EXPLICIT
    # LEGAL_TRANSITIONS graph. Terminal sources have no out-edges; for a
    # non-terminal source the only target not in "every other status" is
    # from_status itself (to_status is already a valid enum here), so this
    # rejects the no-op — behavior-preserving. The receipt / blocked / dropped
    # payload rules below are PREPENDED-to, never replaced.
    if from_status in TERMINAL_STATUSES:
        errors.append( f"item is terminal ('{from_status}') — done/dropped are append-only, no transitions out" )
    elif to_status not in LEGAL_TRANSITIONS[ from_status ] and not is_blocker_repoint(
        from_status, to_status, blocked_by, next_chase_ts, current_blocked_by, current_next_chase_ts
    ) and not is_park_refresh( from_status, to_status, park_reason, next_chase_ts ):
        errors.append( f"no-op transition '{from_status}'->'{to_status}' rejected — not a legal edge" )

    if to_status == "done" or receipt_refs is not None:
        # require_checkable ONLY on ->done: a receipt attached to any other
        # transition is context, and forcing a commit there would gate progress
        # notes behind work that has not happened yet (row 9bfb4b73).
        # require_checkable ONLY on a ->done that could actually happen. Terminal
        # rows cannot transition at all, so running the closing gate (and its git
        # subprocess) on one spends work to emit a second error about a call that
        # was already refused — noise that makes the real reason harder to find.
        errors.extend( validate_receipt_refs(
            receipt_refs, scope_roots,
            require_checkable=( to_status == "done" and from_status not in TERMINAL_STATUSES ),
        ) )
    if to_status == "blocked":
        # I3 kind-aware chase + >=1 typed ref — the ->blocked invariant, expressed
        # ONCE in validate_blocked_fields and shared VERBATIM with the create-as-
        # blocked mint path (Rick 2026-07-20). A chase time is REQUIRED only when a
        # PERSONA blocks (a peer is chaseable, so a chase is honest); a user/item-only
        # block needs none (you cannot schedule Rick; an item resolves on its own
        # edge). This is the app-layer twin of the DB CHECK; the two agree by test.
        errors.extend( validate_blocked_fields( blocked_by, next_chase_ts ) )
    if to_status == "dropped" and ( not isinstance( reason, str ) or not reason.strip() ):
        errors.append( "reason is REQUIRED (non-blank) when transitioning to 'dropped' (C12 — the escape hatch carries its justification)" )
    if to_status == PARK_STATUS:
        errors.extend( validate_park( from_status, next_chase_ts, park_reason ) )

    # Envelope-tail refusal, row 91ccbc26 (Mr. Radio's ruling 2026-08-29). Runs on
    # EVERY transition, not just ->parked: the probe measured that `reason` carries
    # caller markup exactly as `park_reason` does, and guarding the field we happened
    # to notice while its sibling stays open is half a fix. Placed LAST so a caller
    # who is both mis-transitioning and carrying a captured tag hears about the
    # transition first — that is the error they can act on, and a markup complaint on
    # a write that was going to be refused anyway is noise.
    errors.extend( validate_no_envelope_tail( {
        "park_reason" : park_reason,
        "reason"      : reason,
    } ) )

    return errors


# ---------------------------------------------------------------------------
# Park rules (2026-07-19 — src/rnd/v0.1.9/2026.07.19-parked-status-board-hygiene.md)
# ---------------------------------------------------------------------------
#
# `parked` says a HUMAN ruled this row not-now: approved, not abandoned, not
# blocked on anything. The two required fields are what keep it from becoming a
# quiet graveyard, and each mirrors an existing rule rather than inventing one:
#
#   next_chase_ts — the SAME field ->blocked already requires (I3, "no 'pending
#                   X' graves"). Reused, never duplicated: Rick overruled a
#                   proposed `unpark_when` because the chase already exists.
#                   Expiry is computed at READ time (task_store_owed), so a
#                   passed chase rejoins the owed count with no daemon and no
#                   write-back. An unbounded hold is therefore structurally
#                   unrepresentable — any timestamp eventually passes.
#   park_reason   — MUST quote the row's own decisive sentence. Two catalogs
#                   mis-counted this board by reading titles; the quote is what
#                   makes a park decision refutable by the next reader.
#
# An indefinite hold is NOT a park — it is `dropped` with a reason, because
# dropping is VISIBLE.

def is_park_legal_from( from_status ) -> bool:
    """
    True iff a row may be parked FROM `from_status` — by ENTRY (queued /
    in_progress) or by RE-ENTRY (`parked` -> `parked`, a quote refresh).

    The guarantee this buys: expired-parked ⊆ ex-queued/in_progress, BY
    CONSTRUCTION. That is what lets the owed-set admission take the entire
    expired-parked set without widening any reader's owed definition.

    ⭐ WHY `parked` IS LEGAL HERE WHILE STAYING OUT OF PARK_LEGAL_FROM_STATUSES
    (store row aa543525, 2026-07-27). `task_store_tools` prescribes *"Re-park to
    re-freeze the quote"* as the remedy for a park reason that has gone stale — and
    that remedy was UNREACHABLE: the validator refused it, so a seat that noticed
    its own park reason had rotted had no spellable way to do the right thing. Its
    only recourse was to transition OUT of parked and back, which CLEARS the quote
    (see `task_repository`) and fires an event asserting a status change that never
    conceptually happened. A correct rule and correct advice composed into a hole
    nobody owned.

    THE PROOF STILL HOLDS, by induction on a row's park history:
        base case — the FIRST park requires from_status ∈ PARK_LEGAL_FROM_STATUSES,
                    which is ⊆ OWED_BASE_STATUSES (asserted at import in
                    `task_store_owed`).
        step      — a re-park requires from_status == `parked`, which by the
                    induction hypothesis was itself reached from an owed status.
        ⇒ every parked row's pre-park provenance is queued/in_progress, no matter
          how many times its quote is refreshed. A re-park is IDEMPOTENT with
          respect to provenance, which is exactly why it cannot widen admission.

    So the invariant is about ENTRY, and `PARK_LEGAL_FROM_STATUSES` remains its
    exact carrier. Adding `parked` to that tuple would break the assert while
    proving nothing new — the two questions ("what may ENTER a park?" vs "what may
    be parked FROM?") are kept as separate names for the same reason PARK_STATUS
    and PARK_LEGAL_FROM_STATUSES already are.

    ⚠️ The re-park is what makes the refresh HONEST, not merely possible: the
    repository stamps `updated_ts` and `park_reason_captured_at` to one instant on
    every ->parked write, so a re-park restores the post-park equality invariant —
    which is precisely what "re-freeze the quote" means.

    Requires:
        - from_status is the row's CURRENT status (any value accepted)

    Ensures:
        - True iff from_status is in PARK_LEGAL_FROM_STATUSES, or is PARK_STATUS
        - False for every other status, including blocked/claimed/review and the
          terminal states
        - never raises
    """
    return from_status in PARK_LEGAL_FROM_STATUSES or from_status == PARK_STATUS


def validate_park( from_status, next_chase_ts, park_reason ) -> list:
    """
    Validate a ->parked transition's source status and required fields.

    Requires:
        - from_status is the item's CURRENT status
        - next_chase_ts / park_reason are the candidate payload fields

    Ensures:
        - returns [] iff ALL hold:
            from_status is park-legal — queued / in_progress (ENTRY), or
              already `parked` (RE-ENTRY: a quote refresh; see is_park_legal_from)
            next_chase_ts is present
            park_reason is a non-blank string
        - the source-status rule is what makes the owed-set restoration exact:
          an expired-parked row provably came from queued/in_progress, so
          re-admitting the whole expired-parked set can never drag in a
          blocked/claimed/review row (design §4.2). A `parked_from_status`
          column was REJECTED — a new field where a rule suffices.
        - one error string per violation; never raises
    """
    errors = [ ]
    if not is_park_legal_from( from_status ):
        errors.append(
            f"cannot park from '{from_status}' — park is legal ONLY from "
            f"{PARK_LEGAL_FROM_STATUSES} (this is what keeps the owed-set "
            f"restoration exact rather than widening), or from "
            f"'{PARK_STATUS}' itself to re-freeze a stale quote"
        )
    if next_chase_ts is None:
        errors.append(
            "next_chase_ts is REQUIRED when transitioning to 'parked' (the chase "
            "IS the un-park — parking buys bounded, self-expiring silence, never an exit)"
        )
    if not isinstance( park_reason, str ) or not park_reason.strip():
        errors.append(
            "park_reason is REQUIRED (non-blank) when transitioning to 'parked' — "
            "it MUST quote the row's own decisive sentence, so the park is refutable"
        )
    return errors


# ---------------------------------------------------------------------------
# Item-field edit rules (Phase 2.1 — PATCH /api/tasks/{id})
# ---------------------------------------------------------------------------

PATCH_EDITABLE_FIELDS = ( "title", "body", "priority", "owner_persona", "accountable_manager", "gate_class", "urgency" )

# The persona-identity fields a PATCH may carry — the ONLY fields the
# owed-work oracle compares by canonical key, so the ONLY ones to normalize
# on write (title/body/priority/gate_class are never persona-matched).
PATCH_PERSONA_FIELDS = ( "owner_persona", "accountable_manager" )


def normalize_patch_fields( fields: dict ) -> dict:
    """
    Canonicalize the persona-identity fields of a PATCH on write — the single,
    100%-testable seam that keeps a re-owned item inside the new owner's
    owed-row set (the 2026-06-18 false-idle bug-class guard, §2.2).

    Delegates to the ONE global persona normalizer — `canonical_persona_key`
    (lupin_mcp.persona_normalization) — for `owner_persona` / `accountable_manager`
    ONLY, and ONLY when the field is present AND non-empty: a re-owned item is
    stored under the SAME key the owed-query reads by, so a hand-supplied display
    name ("María", "Mr. Radio") can never split into a row the new owner's query
    misses. An EXPLICIT None (clear-the-owner) is PRESERVED — never collapsed to
    "" or to a canonicalized blank — so unassigning an item stays a deliberate,
    auditable clear. `canonical_persona_key` is idempotent, so this is safe even
    when a caller pre-normalizes.

    Requires:
        - fields is the dict of provided editable fields (the router's
          model_dump(exclude_unset=True) minus actor/authority/reason); may be
          empty

    Ensures:
        - returns a NEW dict (input is never mutated)
        - every key not in PATCH_PERSONA_FIELDS is copied through verbatim
        - a persona field that is present and truthy -> canonical_persona_key( value )
        - a persona field that is present and falsy (None / "") -> left verbatim
          (an explicit None clear survives; canonical_persona_key is NOT applied
          to a falsy value, which would turn None into the "" sentinel)
        - a persona field that is absent -> stays absent (no key is invented)
    """
    normalized = dict( fields )
    for field_name in PATCH_PERSONA_FIELDS:
        if field_name in normalized and normalized[ field_name ]:
            normalized[ field_name ] = canonical_persona_key( normalized[ field_name ] )
    return normalized


def validate_patch( fields: dict ) -> list:
    """
    Validate an item-field PATCH (Phase 2.1). `fields` is the dict of EDITABLE
    fields the caller actually set (the router passes
    model_dump(exclude_unset=True) minus actor/authority).

    The forbidden fields — status / blocked_by / next_chase_ts / receipt_refs /
    correlation_key — are excluded STRUCTURALLY by the TaskPatchIn model
    (extra='forbid' → 422 at the wire) and never reach here: an item-PATCH can
    NEVER bypass the transition oracle (reviewer ruling 2026-06-15).

    Requires:
        - fields is a dict of provided editable fields (may be empty)

    Ensures:
        - returns [] iff at least one editable field is set AND every provided
          constrained field is valid:
            title      - non-empty string (the column is NOT NULL)
            priority   - member of VALID_PRIORITIES
            gate_class - member of VALID_GATE_CLASSES
            urgency    - member of VALID_URGENCIES
          (body / owner_persona / accountable_manager are nullable free text —
          a provided null clears them; no shape rule beyond the wire max_length)
        - an empty patch (no editable field set) is rejected — a PATCH must
          change something
        - one error string per offending field; never raises
    """
    if not fields:
        return [ f"patch must set at least one editable field {PATCH_EDITABLE_FIELDS}" ]

    errors = [ ]
    if "title" in fields and ( not isinstance( fields[ "title" ], str ) or not fields[ "title" ].strip() ):
        errors.append( "title must be a non-empty string" )
    if "priority" in fields and fields[ "priority" ] not in VALID_PRIORITIES:
        errors.append( f"priority '{fields[ 'priority' ]}' must be one of {VALID_PRIORITIES}" )
    if "gate_class" in fields and fields[ "gate_class" ] not in VALID_GATE_CLASSES:
        errors.append( f"gate_class '{fields[ 'gate_class' ]}' must be one of {VALID_GATE_CLASSES}" )
    if "urgency" in fields and fields[ "urgency" ] not in VALID_URGENCIES:
        errors.append( f"urgency '{fields[ 'urgency' ]}' must be one of {VALID_URGENCIES}" )
    return errors


# ─────────────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------
# TOOL-CALL ENVELOPE TAIL — A LOUD REFUSAL (row 91ccbc26)
#
# THE DEFECT. Two writes, sam's and Rio's, on different rows at different
# fragment sizes, silently stored the tail of the writer's own tool-call
# envelope inside a free-text field. Neither failed. Neither warned. Both were
# caught only when a human re-read his own prose later.
#
# WHERE IT ENTERS, established by measurement rather than by the shape of the
# bytes. A differential probe (2026-08-29, Maya) sent one 242-byte canary
# through two entry paths — raw HTTP, and an MCP tool call — and read back an
# identical sha256 both ways. Krishna corroborated independently with an md5
# read straight out of postgres. So the transport and the store are FAITHFUL:
# `park_reason` is `Optional[str]` with only a max_length, and the repository
# does a verbatim assignment. The corruption is composed by the CALLER, above
# the JSON boundary, and nothing this repo owns can prevent it.
#
# WHY THIS REFUSES RATHER THAN ADVISES (Mr. Radio's ruling, 2026-08-29). What a
# boundary CAN fix is the property both incidents shared: silence. A refusal is
# recoverable and known to work — sam's THIRD attempt landed clean — and it
# turns a silent corruption into a loud, actionable failure at the moment the
# author can still fix it.
#
# 🔴 TAIL-ONLY, AND THE NARROWNESS IS THE WHOLE SAFETY ARGUMENT. A corrupted
# write and an HONEST quote are BYTE-IDENTICAL here — proven by deliberately
# sending the exact corruption bytes as legitimate content. Nothing at this
# boundary can read intent. So the signature must be as tight as the evidence
# allows: a CLOSED list of known envelope tags, matched only at the very END of
# the field. A reason may legitimately quote code, angle brackets and all, and
# row 91ccbc26 itself quotes both specimens mid-sentence — a guard that barred
# the characters outright, or that fired on any trailing close-tag, would refuse
# the very rows written about this defect. Under a REFUSAL policy a false
# positive blocks real work, so breadth is a liability; the negative tests in
# test_task_store_markup_tail.py are the load-bearing half of this feature.
#
# The closed list is Krishna's (commit bb73e857), kept over an open regex on
# Mr. Radio's ruling. The tags are assembled from pieces rather than written as
# literals: a real close-tag typed into a source file TERMINATES the tool call
# that writes it — the second failure mode of this same defect, which bit both
# of us while building the fix.
_LT = "<" + "/"
_ENVELOPE_TAGS = (
    _LT + "park_reason>",
    _LT + "invoke>",
    _LT + "parameter>",
    _LT + "function_calls>",
    _LT + "antml:invoke>",
    _LT + "antml:parameter>",
)

# EXACTLY THE THREE FIELDS Mr. Radio RULED, no more. The probe MEASURED that all
# three carry caller markup verbatim: `park_reason` on a park, `reason` on every
# transition, `note` on every amendment. Guarding one while its siblings stay
# open is half a fix. `body` and `title` are composed the same way and are
# presumably exposed too, but nobody has measured them and the ruling did not
# name them — listing an unmeasured field here would imply coverage that the
# call sites do not provide.
MARKUP_PRONE_FIELDS = ( "park_reason", "reason", "note" )


def envelope_tail_tag( text ):
    """
    Name the tool-call closing tag `text` ENDS with, if any.

    Requires:
        - text is anything; only a str can produce a non-None result

    Ensures:
        - returns the offending tag when the value, ignoring trailing
          whitespace, ends with one of _ENVELOPE_TAGS
        - returns None for legitimate content, INCLUDING a value that quotes one
          of these tags anywhere but the very end
        - returns None for a non-str and for a blank value — validate_park and
          the amend handler already own the "missing / blank" message and must
          keep owning it, so this never competes for that error
        - NEVER mutates or truncates: refusal is the caller's job, and the
          caller still holds every byte it sent
    """
    if not isinstance( text, str ): return None
    trimmed = text.rstrip()
    for tag in _ENVELOPE_TAGS:
        if trimmed.endswith( tag ): return tag
    return None


def validate_no_envelope_tail( fields ) -> list:
    """
    Refuse any free-text field ending in a tool-call envelope tag.

    Requires:
        - fields is a dict mapping field name -> candidate value

    Ensures:
        - returns one error string per offending field, naming BOTH the field
          and the tag, and telling the author what to do about it — a refusal
          the author cannot act on is just a different kind of silence
        - returns [] when every value is clean, non-str, or absent
        - reports EVERY violation rather than the first, matching this module's
          existing validators
        - never mutates the input dict and never rewrites a value
    """
    errors = [ ]
    for name in sorted( fields ):
        tag = envelope_tail_tag( fields[ name ] )
        if tag is None: continue
        errors.append(
            f"{name} ends with the tool-call markup '{tag}', which is almost certainly "
            f"your own envelope captured into the text rather than something you wrote. "
            f"Re-send it without the trailing tag. If you genuinely meant to END on that "
            f"tag, add a closing sentence after it."
        )
    return errors


def quick_smoke_test():
    """
    Quick smoke test for task_store_rules — exercises every validator at the
    happy path + one representative rejection each.
    """
    import cosa.utils.util as cu

    cu.print_banner( "Task-Store Rules Smoke Test", prepend_nl=True )

    try:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join( tmp, "receipt.md" )
            with open( doc, "w" ) as f:
                f.write( "receipt\n" )
            roots = { "lupin": tmp }

            print( "Testing receipt validation..." )
            good = { "commit": "6be15f46", "doc_path": "lupin/receipt.md", "log_line": "lupin/receipt.md:1" }
            assert validate_receipt_refs( good, scope_roots=roots ) == [ ]
            assert validate_receipt_refs( { "doc_path": "trust me" }, scope_roots=roots ) != [ ]
            assert validate_receipt_refs( { }, scope_roots=roots ) != [ ]
            print( "✓ receipt whitelist + shapes enforced" )

            print( "Testing blocked_by validation..." )
            assert validate_blocked_by_refs( [ { "kind": "user", "id": "rick" } ] ) == [ ]
            assert validate_blocked_by_refs( [ ] ) != [ ]
            print( "✓ typed blocked_by refs enforced" )

            print( "Testing transition rules..." )
            assert validate_transition( "queued", "claimed", "standing" ) == [ ]
            assert validate_transition( "done", "queued", "standing" ) != [ ]
            assert validate_transition( "review", "done", "standing", receipt_refs={ "commit": "6be15f46" } ) == [ ]
            assert validate_transition( "in_progress", "blocked", "standing" ) != [ ]
            assert validate_transition( "queued", "dropped", "standing" ) != [ ]
            assert validate_transition( "queued", "dropped", "standing", reason="superseded-by-rewrite" ) == [ ]
            print( "✓ terminal / receipts-on-done / blocked / dropped-reason rules enforced" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
