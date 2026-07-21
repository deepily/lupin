#!/usr/bin/env python3
"""
heartbeat_hold_io.py — the hold WRITE/READ/CLEAR *verb*.

    A MECHANISM NOTHING FORCES YOU TO USE IS A RULE WITH EXTRA STEPS.

`write_hold()` has existed in `heartbeat_hold.py` since the hold artifact was
designed, and it is correct. It is also, from a shell, UNREACHABLE: that module
exposes no argparse, no subcommand, and its `__main__` block runs
`quick_smoke_test()` and nothing else. An agent asked to declare a hold has
exactly one act available to it — hand-write the JSON — and so that is what the
fleet did. Measured on the live corpus (Krishna/Clayton, 2026-07-16→18): of the
22 null-TTL hold files on disk, ZERO went through `write_hold`. They carry cargo
the schema has no fields for, and they carry the ttl key ABSENT with zero
literal nulls while `write_hold` always emits the key. Two independent
fingerprints, one answer.

AND THE FLEET WAS NOT BEING SLOPPY — IT WAS FOLLOWING THE DOCTRINE EXACTLY.
`planning-is-prompting → workflow/fleet-pause-resume.md:77` says *"Write the
hold file: `.heartbeat-hold-<FULL-session-id>.json` with `work_owed: true`,
`awaiting: "user:<name>"`, `ttl_seconds: 14400`…"*. That prescribes a FILENAME
AND A JSON SHAPE, and it is the only `heartbeat-hold-` prescription anywhere in
`workflow/` — one grep hit, fleet-wide. A shape can be typed wrong, typed short,
or typed without the ttl key at all, and nothing anywhere notices. The bypass is
not inferred from the corpus; it is written down, at that line. This file exists
so doctrine can prescribe a VERB instead — which is the only form of that
instruction that carries its own enforcement.

WHAT THIS FILE DOES *NOT* DO, stated up front so no later reader over-trusts it:

  1. IT DOES NOT MAKE HAND-WRITING IMPOSSIBLE. Nothing can; `Write` and `>` are
     always in reach. This closes the gap by making the CORRECT act CHEAPER than
     the incorrect one and by giving doctrine something to name. It is a paved
     road, not a wall — and the 0-for-23 measurement is precisely what a missing
     road looks like.
  2. IT ADDS NO VALIDATION OF ITS OWN. Every guard here is `write_hold`'s,
     reached by delegation. Re-implementing the schema in a second place is how
     a writer and its front-end drift, and a drifted front-end is worse than no
     front-end: it mints holds that look official and are not.
  3. THE NON-NUMERIC ttl BRANCH OF `write_hold` IS NOT REACHABLE FROM HERE.
     `--ttl-seconds` is `type=int`, so argparse rejects `"abc"` at exit 2 before
     `write_hold` is ever called. Non-POSITIVE values (`0`, `-5`) DO reach it and
     DO raise. Both refusals are proven in the suite; the distinction is recorded
     rather than papered over, because a docstring that claims a guard it does
     not exercise is the defect this row spent three seats on.

VERIFY BY EXECUTION, NOT BY ASSERTION (memento_io's lesson, taken deliberately):
`write` reads the hold back through the real reader and confirms the hook would
actually HONOR it before printing a success banner. A hold that lands on disk but
cannot defend its session is the exact four-week silence this milestone closed —
so this refuses to report it as a success.

EVERY REFUSAL LEAVES THE DISK AS IT FOUND IT — and that sentence took two tries.
It first read "A REFUSAL LEAVES NOTHING BEHIND", which was true of the
`write_hold` ValueError path (it validates before touching the filesystem: no
file, no `.tmp`, no partial) and FALSE of the verify-by-read path, which exited 3
and left the unhonorable hold sitting there. Rio ⚡ reproduced it: `write
--reason ""` → exit 3, file present, `is_honored` False. **The verb built to stop
minting the 22-file corpus minted one, under a docstring claiming it could not.**

AND UNLINKING WOULD NOT HAVE FIXED IT — the obvious repair is a trap, measured:

    before refresh : honored=True    (a live hold, ttl 14400, defending a session)
    after  refresh : honored=False   (A-1: the bad hold is left)
    after  UNLINK  : no hold at all  (tidier corpus, SAME undefended session)

The destructive act is `write_hold` overwriting a good hold, and it has already
happened by the time this verifies. Unlinking reaches the ping-storm outcome by a
cleaner route. **Only restoring the PREVIOUS hold preserves the defense**, which
is why `cmd_write` captures the prior bytes BEFORE the write. See ROLLBACK there.

TWO DETECTORS. THEY ARE NOW REDUNDANT-BY-DESIGN ON EVERY KNOWN CLASS, AND THAT IS
THE HONEST STATEMENT. An earlier version of this paragraph claimed they "fail over
DIFFERENT evidence" — that claim rested entirely on the empty-`reason` hold, silent
at the writer and caught only by the read-back. **A-1's fix moved that class to the
writer, so the divergence is gone by construction: there is now no enumerated class
detector 2 catches alone.** The sentence is narrowed rather than propped up. The
alternative was leaving `reason` unguarded to keep a docstring true, and the
docstring serves the code, not the reverse. If a real divergence is ever found, this
widens back — with a receipt.

Detector 2 is RETAINED anyway, deliberately, as the general net over classes nobody
has enumerated yet: a base_dir that resolves elsewhere, clock or mtime pathology, a
future schema drift. Three findings today were each "the enumerated class is not the
whole class". Its coverage is therefore a synthetic injection plus the rollback
tests — a guard against causes not yet named, and no test can name them.

ISOLATION IS STILL PROVEN, BUT NOT BY THE MUTATION THIS DOCSTRING FIRST CITED:

    A  strip `write_hold`'s ttl guard      →  5 red  (BOTH detectors — redundancy)
    B  neuter detector 2 ONLY              →  5 red  ⇒ detector 2 is load-bearing
       (`if not is_honored( read_back )` → `if False`)
    C  strip detector 1's non-positive arm →  5 red, detector 2 silent on survivors

    B killed exactly 1 test before the A-1 work and kills 5 after it: the four
    rollback arms exercise detector 2 as well. A detector whose killing set GREW
    while its enumerated divergence class shrank to zero is worth stating plainly
    — the redundancy note above is about which CAUSES the two share, not about
    how much of the suite depends on each.

**B and C are the proof; A is not.** Under A, detector 2 fires as a CONSEQUENCE of
detector 1's failure — one mutation, both detectors, which demonstrates redundancy
and says nothing about isolation. This docstring previously cited A for both and
called them "separately provable by exactly the mutation described above". That is
the over-statement shape this row has now produced four times, committed inside the
sentence warning about it. B and C were run by the reviewer, not the author.

A redundancy is not the defect — an UNISOLATED redundancy is. Keep both, and keep
B and C runnable: the day detector 2 stops having its own killing mutation is the
day it has become decoration.

CARGO — THE VERB REFUSES TO DESTROY WHAT IT CANNOT CARRY (María 🌸, 2026-07-21,
row 955f7eb4). `write_hold` persists EXACTLY `HOLD_SCHEMA_FIELDS` through an
`os.replace`, so writing over a hold that carries non-schema fields —
`note_to_my_successor`, `board`, `harvest_state`, `blocked_rows` — destroys them.
Measured on this verb before the guard:

    cargo BEFORE : ['blocked_rows', 'note_to_my_successor']
    $ write --session-id <same> --reason "still holding"
    HOLD … / honored yes / exit 0          ← success banner
    cargo AFTER  : []

**Exit 0. A-1 and A-4's shape on the SUCCESS path**, which is the worst of the
three: nothing signals it, so there is no moment at which the caller could
notice. And it was found the way the other two were — María ran the prescribed
command against her own live hold and watched her `blocked_rows` ledger vanish.
**A remedy that manufactures the thing it replaces**: this verb exists because 56
hand-written holds accumulated, and prescribing it would have destroyed the
payload in each one on first use, sending the author straight back to hand-editing.

So `write` REFUSES when the existing hold carries cargo, names every field, and
exits 6. There is deliberately NO `--force`: an escape you can take silently is
not a gate, and the payload is irreplaceable. The two ways forward are both acts
you can point at afterwards — move it to a memento (`memento_io.py write`), or
`clear` first if you are genuinely done with it.

THE SPLIT IS DOCTRINE, AND IT IS RIGHT: **a hold is a LIVENESS artifact with a
TTL; a memento is the CONTINUITY record.** Continuity does not belong behind an
expiry — that is precisely how these files became irreplaceable, and why the
95b2ed7f rescue was needed. The verb stays narrow; it takes no cargo parameter
and should not grow one. But narrow is not the same as blind: refusing loudly is
what keeps the narrowness from being paid for by the caller's data.

WHERE THE HOLD LANDS, SAID OUT LOUD (María, same day). `--base-dir` defaults to
`write_hold`'s own default, `cu.get_project_root()` = **LUPIN_ROOT** — correct for
a lupin session and wrong for every other. Measured from a `plan` session:
`read --session-id <mine>` → "no hold found", while the same id with
`--base-dir <PIP root>` → "honored yes". Same file, same session, opposite
verdicts. The default is NOT changed here — diverging from the writer's default
would mint a second write semantics, which is the drift item 2 above forbids — but
every path this verb prints now NAMES THE DIRECTORY, and a not-found says WHERE IT
LOOKED. A null that does not say where it searched is not evidence, and that is
the form in which this one presented.

Invocation (both forms work; the second needs PYTHONPATH to carry `src`):

    python3 $LUPIN_ROOT/src/lupin_cli/claude_code/hooks/lib/heartbeat_hold_io.py \
        write --session-id <full-id> --persona "María 🌸" \
              --reason "holding on the 3-way seam review" \
              --ttl-seconds 14400 --awaiting "user:rick"

    python3 -m lupin_cli.claude_code.hooks.lib.heartbeat_hold_io read --session-id <id>

Exit codes (distinct, so a caller never has to parse the message):
    0  success
    2  usage error, or a value `write_hold` refuses (its ValueError, verbatim)
    3  the hold landed but would NOT be honored — verify-after-write failed
    4  `read`/`clear`: no hold found for that session
    5  `clear`: a hold exists under a MATCHING ID PREFIX but not at this session's
       own path — named, not deleted (see cmd_clear; row 39219cc1 owns the cure)
    6  `write`: the existing hold carries non-schema CARGO this verb cannot
       preserve — named, not destroyed (see the CARGO section below)
"""
import argparse
import json
import os
import sys


def _bootstrap_sys_path():
    """
    Put `<LUPIN_ROOT>/src` on `sys.path` so this file runs as a PATH, not only as
    a module (the CLAUDE.md bootstrap exception — env var, never a `__file__` chain).

    Requires:
        - nothing; a missing LUPIN_ROOT is a normal, non-fatal state (the module
          is already importable when run via `-m` with PYTHONPATH carrying `src`)

    Ensures:
        - Returns True iff `<LUPIN_ROOT>/src` was inserted at sys.path[0]
        - Returns False when LUPIN_ROOT is unset, or the path is already present
          (idempotent — importing this module twice never stacks entries)
        - Never raises
    """
    lupin_root = os.environ.get( "LUPIN_ROOT" )
    if lupin_root is None:
        return False
    src_path = os.path.join( lupin_root, "src" )
    if src_path in sys.path:
        return False
    sys.path.insert( 0, src_path )
    return True


_bootstrap_sys_path()

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import (   # noqa: E402 — after bootstrap
    AWAITING_NONE, DEFAULT_TTL_SECONDS, HOLD_FILENAME_TEMPLATE, _resolve_base_dir,
    clear_hold, hold_cargo_keys, hold_path, is_honored, read_hold,
    read_hold_exact, write_hold,
)


EXIT_OK          = 0
EXIT_REFUSED     = 2
EXIT_NOT_HONORED = 3
EXIT_NO_HOLD     = 4
EXIT_ORPHAN      = 5
EXIT_CARGO       = 6
# 39219cc1 F1 — the exact delete SUCCEEDED and the caller is STILL HELD, because
# this id still resolves to a hold through the reader's prefix fallback. Distinct
# from EXIT_ORPHAN on purpose: that one means "I deleted NOTHING because I will
# not guess"; this one means "I deleted MINE and you are not released". Collapsing
# them would tell a caller who still holds the same thing as a caller who does not.
EXIT_STILL_HELD  = 7


def cmd_write( args ):
    """
    Mint (or refresh) this session's hold — the verb doctrine can prescribe.

    Requires:
        - args carries session_id / persona / reason (all required by the parser)
        - args carries ttl_seconds / awaiting / work_owed / base_dir

    Ensures:
        - Delegates to `write_hold` unchanged — no validation is duplicated here,
          so this front-end can never drift from the writer it fronts
        - Reads the hold BACK through the real reader and returns EXIT_NOT_HONORED
          when the hook would not honor it (verify by execution)
        - AN EXIT_NOT_HONORED REFUSAL LEAVES THE DISK EXACTLY AS IT FOUND IT:
          bytes AND mtime restored when a prior hold existed, artifact unlinked
          when none did. See the ROLLBACK table below — which refusal leaves what
          is stated per path, because a reader who has to infer it will infer
          wrong.
        - Prints the resolved path, the persisted ttl and the honored verdict on
          success, so the caller sees WHAT LANDED rather than "ok"
        - Returns EXIT_OK on success

    Raises:
        - ValueError from `write_hold` for an unusable ttl or an empty reason —
          caught by main() and surfaced verbatim at EXIT_REFUSED, never swallowed
          and never re-worded

    ROLLBACK — WHY THIS PATH UNDOES ITS OWN WRITE (finding A-1, Rio ⚡ 2026-07-21).
    This branch used to print "would NOT be honored" and LEAVE THE ARTIFACT ON
    DISK. Reproduced: `write --reason ""` exited 3 with the file present and
    `is_honored` False — the verb built to stop minting unhonorable holds minted
    one. The empty-reason CAUSE is now refused at the writer, but the PATH is not
    the cause: it fires for any way a hold can land unhonorable, including ones
    neither this file nor `write_hold` knows about yet. So the property is
    enforced here, at the path, rather than patched at the one cause that
    happened to be found.

    A refusal that leaves debris is not a refusal, it is a failed write wearing a
    refusal's exit code — and on a REFRESH the debris replaced something live.
    This is NOT the janitor's bias-to-keep being relaxed: nothing prunes another
    session's hold here. This undoes THIS call's OWN write.

    WHICH REFUSAL LEAVES WHAT — the table, because "a refusal leaves nothing
    behind" was a slogan and it was false three separate ways:

        refusal path                     | left on disk
        ---------------------------------+------------------------------------------
        write_hold ValueError            | nothing (it validates before touching
        (bad ttl, unhonorable reason)    | the filesystem — no file, no .tmp)
        verify-failure, NO prior hold    | nothing (the artifact is unlinked)
        verify-failure, prior hold       | THE PRIOR, byte-exact and mtime-exact,
                                         | whatever state it was in

    THE RESTORE PRESERVES mtime, AND THAT IS NOT FASTIDIOUSNESS. `is_fresh`
    anchors on the FILE MTIME (B1, bug d44b7068), not on `held_at`. Measured: a
    prior hold whose mtime was forced to epoch 0 read `honored=False`; rewriting
    its identical bytes back read `honored=TRUE`. A naive restore RESURRECTS A
    DEAD HOLD — this row's defect inverted, a hold defending a session it should
    not, and a content-only assertion passes straight over it. Hence `os.utime`
    with the captured times, and hence a test that compares mtime rather than
    bytes alone.

    THE PRIOR IS RESTORED WHATEVER ITS STATE — including an already-unhonorable
    hand-written corpus member (ruling: Mr Radio 🦉 + Rio ⚡, 2026-07-21). This
    verb must not silently delete something it did not create. Deleting another
    author's artifact on a failed write is a bigger surprise than leaving it, and
    this verb exists to stop UNACCOUNTABLE hold files, not to start unaccountably
    removing them. Reclamation is the janitor's job, gated, after cargo triage.

    CAPTURE HAPPENS BEFORE THE WRITE, and that ordering is the entire fix: by the
    time the verify runs, `write_hold` has already replaced the original. Read it
    late and every arm of the table above is unimplementable.
    """
    path        = hold_path( args.session_id, base_dir=args.base_dir )
    prior_bytes = None
    prior_times = None
    if path.exists():
        stat_result = path.stat()
        prior_bytes = path.read_bytes()
        prior_times = ( stat_result.st_atime, stat_result.st_mtime )

    # CARGO GUARD — see the module docstring. Refuse BEFORE write_hold touches
    # anything: this is the only point at which the payload still exists.
    #
    # READ THE EXACT PATH, NOT THE RESOLVED ONE (bug 8abdcbbf — mine, shipped in
    # 378f1499). This guard originally read through prefix-tolerant `read_hold`
    # while `write_hold` replaces the EXACT path, so cargo in a prefix SIBLING —
    # a file this call would never touch, and not guaranteed to be this session's
    # — refused the session its hold at exit 6, naming a path that did not exist.
    # A session that cannot write a hold is poked forever: the ping-storm this
    # surface exists to prevent, caused by the guard against a different failure.
    # `write_hold` replaces exactly one file, so that file's cargo is the ONLY
    # cargo this call can destroy — and it is the only cargo the guard may object
    # to. Same defect class as A-4, which is fixed eleven lines down in cmd_clear.
    cargo = hold_cargo_keys( read_hold_exact( args.session_id, base_dir=args.base_dir ) )
    if cargo:
        print( f"REFUSED: the hold at {path} carries {len( cargo )} field(s) this verb does "
               f"not own and cannot preserve:", file=sys.stderr )
        for key in cargo:
            print( f"           {key}", file=sys.stderr )
        print(  "         Writing would REPLACE the file with the hold schema alone and those "
                "fields would be gone — at exit 0, under a success banner.", file=sys.stderr )
        print(  "         A hold is a LIVENESS artifact with a TTL; a memento is the CONTINUITY "
                "record. Continuity does not belong behind an expiry.", file=sys.stderr )
        print(  "         Move it first, then re-run this write:", file=sys.stderr )
        print(  "           python3 $PLANNING_IS_PROMPTING_ROOT/workflow/scripts/memento_io.py "
                "write --persona <you> --session-id <id>", file=sys.stderr )
        print(  "         Genuinely finished with it? `clear` first — deleting it should be an "
                "act you can point at, not a side effect of declaring a hold.", file=sys.stderr )
        return EXIT_CARGO

    hold = write_hold(
        args.session_id, args.persona, args.reason,
        work_owed=args.work_owed, ttl_seconds=args.ttl_seconds,
        awaiting=args.awaiting, base_dir=args.base_dir,
    )

    read_back = read_hold( args.session_id, base_dir=args.base_dir )
    if not is_honored( read_back ):
        if prior_bytes is None:
            path.unlink( missing_ok=True )
            outcome = "nothing was written"
        else:
            path.write_bytes( prior_bytes )
            os.utime( path, prior_times )
            outcome = "the previous hold has been RESTORED (bytes and mtime)"
        print( f"FAILED: the hold this call wrote would NOT be honored — it cannot defend "
               f"this session's quiescence, so {outcome}. Target: {path}", file=sys.stderr )
        return EXIT_NOT_HONORED

    print( f"HOLD     {path}" )
    print( f"ttl      {hold[ 'ttl_seconds' ]}s   awaiting: {hold[ 'awaiting' ]}   "
           f"work_owed: {hold[ 'work_owed' ]}" )
    print(  "honored  yes (read back through the reader the hook uses)" )

    # 39219cc1 F3 — NAME THE DUPLICATE THIS CALL JUST MINTED. One session declaring
    # under both its id forms (the short bridge id `get_session_info` hands it, and
    # the full stable id the hook reads with) gets TWO hold files, each honored,
    # each answering a different reader. That is the unaccountable-hold corpus
    # arriving BY THE PAVED ROAD — a worse class than the hand-written ones, which
    # at least imply an author who chose to skip the mechanism.
    #
    # WARN, DO NOT REFUSE — the line held on Mr Radio's ruling. Losing a hold is
    # worse than owning a duplicate: a session that cannot declare a hold is poked
    # forever, which is exactly what 8abdcbbf did an hour ago. And this verb will
    # not delete or overwrite the sibling either: it may be ANOTHER session's live
    # hold, and destroying it is C2 from this row's reversal.
    siblings = _prefix_siblings( args.session_id, base_dir=args.base_dir )
    if siblings:
        print( f"WARNING: {len( siblings )} other hold file(s) share this ID PREFIX — this "
               f"session may now be holding under more than one id form:", file=sys.stderr )
        for sibling in siblings:
            print( f"           {sibling}", file=sys.stderr )
        print(  "         Each is read by a different id form and each is honored separately. "
                "If they are yours, `clear` the one you no longer want — naming its OWN id.",
                file=sys.stderr )
    return EXIT_OK


def cmd_read( args ):
    """
    Print this session's hold as JSON, plus the verdict the hook would reach.

    Requires:
        - args carries session_id and base_dir

    Ensures:
        - Returns EXIT_NO_HOLD (and says so on stderr) when no hold is found —
          an absent hold is a distinct outcome, never an empty success
        - Prints the hold verbatim (including the reader's `_hold_file_mtime_epoch`
          annotation) and the honored verdict; returns EXIT_OK
    """
    hold = read_hold( args.session_id, base_dir=args.base_dir )
    if hold is None:
        # NAME THE DIRECTORY. A not-found that does not say where it looked is an
        # unproven null — and this exact message read "no hold found" to a plan
        # session whose hold was alive one directory over (María, 2026-07-21).
        print( f"no hold found for session {args.session_id} in "
               f"{_resolve_base_dir( args.base_dir )}", file=sys.stderr )
        return EXIT_NO_HOLD
    print( json.dumps( hold, indent=2, ensure_ascii=False ) )
    print( f"honored  {'yes' if is_honored( hold ) else 'NO'}", file=sys.stderr )
    return EXIT_OK


def _prefix_siblings( session_id, base_dir=None ):
    """
    EVERY hold file sharing this session id's 8-char prefix, excluding its own
    exact path — the full orphan set, not the one the reader happened to pick.

    Requires:
        - session_id is a string; base_dir is a path-like / string / None

    Ensures:
        - Returns a sorted list of Paths, `.tmp` atomic-write artifacts excluded
        - Returns [] for an empty session_id, or when the directory is unreadable
        - Never raises

    WHY EVERY MATCH AND NOT JUST THE RESOLVED ONE (A-4, second instance, Rio ⚡
    2026-07-21). `_read_hold_path` returns ONE file — longest-then-lexical — which
    is the right rule for "which should I READ" and no rule at all for "how many
    orphans are there". A refusal that names one orphan while two exist is the
    same defect with better manners: the caller fixes the one they were told about
    and the other keeps defending a session that has moved on. It was found by
    hardening a count-only assertion — "the count WAS 2, and 2 was what I looked
    at."
    """
    if not session_id:
        return [ ]
    exact   = hold_path( session_id, base_dir=base_dir )
    pattern = HOLD_FILENAME_TEMPLATE.format( session_id=session_id[ :8 ] + "*" )
    try:
        matches = list( _resolve_base_dir( base_dir ).glob( pattern ) )
    except OSError:
        return [ ]
    return sorted( p for p in matches if p != exact and not p.name.endswith( ".tmp" ) )


def cmd_clear( args ):
    """
    Remove this session's hold — the explicit "I am no longer holding" act.

    Requires:
        - args carries session_id and base_dir

    Ensures:
        - Returns EXIT_NO_HOLD when there is no hold at all (the caller learns its
          hold was already gone rather than being told "cleared")
        - Deletes ONLY the EXACT path for this session id, never a prefix match
        - Returns EXIT_ORPHAN, deleting NOTHING, when a hold exists but resolves
          to a DIFFERENT file than this id names — the orphan is NAMED, not guessed
          at (finding A-3; see below)

    THIS FIXES A FALSE SUCCESS, AND IT REFUSES TO GUESS (A-3 + A-4, Rio ⚡
    2026-07-21). Both halves are needed and neither is "preserve what it did".

    A-4 — WHAT THE SHIPPED CODE DID, measured:

        on disk : .heartbeat-hold-c121037b-aaaa-1111-2222-333344445555.json
        $ clear --session-id c121037b
        CLEARED  …/.heartbeat-hold-c121037b.json    ← a path that never existed
        exit 0
        after   : the original file, UNTOUCHED, still honored

    The verb split its resolution across two functions: the GUARD (`read_hold`,
    prefix-tolerant) found a hold and waved the call through, while the ACTION
    (`clear_hold` + the banner, exact-path) unlinked a file that was not there.
    **The guard vouched for a file the action never touched.** A session clearing
    with the SHORT id — the form `get_session_info()` hands it — was told its hold
    was released, walked away, and the hold kept defending a session that had
    moved on. That is A-1's shape one verb over: report success, artifact wrong.
    And the survivor is exactly what the janitor later finds as an unaccountable
    hold file — a corpus member minted by a successful-looking call to the
    sanctioned verb.

    `read_hold` resolves through `_read_hold_path`, which falls back to a PREFIX
    match so a hold written under the short 8-char bridge id is still found by a
    hook reading with the full stable id (facet 2, bug c121037b). `clear_hold`
    keys on the EXACT path. Read is prefix-tolerant; clear is exact — so `clear`
    can report success while a resolved hold survives, still honored, still
    defending a session that has moved on.

    THE OBVIOUS FIX — "clear whatever read resolved" — IS WORSE THAN THE GAP, and
    this is why it is not here. That prefix match is a READ: resolving to the
    wrong hold costs a missed poke. Wiring `clear` to it makes it A DELETE DECIDED
    BY A WILDCARD:

        on disk : .heartbeat-hold-c121037b-aaaa-1111-2222-333344445555.json
                  (Session A, holding, honored)
        clear --session-id c121037b
            exact path  : .heartbeat-hold-c121037b.json     (absent)
            resolves to : …-aaaa-1111-…-5555.json           ← ANOTHER session's hold

    A call naming neither that id nor any existing file would have destroyed a
    live hold, and its owner would be poked out of a quiescence it correctly
    declared — the ping-storm this row exists to prevent, caused by the fix for
    the row. With multiple prefix matches it is worse still: `_read_hold_path`
    prefers longest-then-lexical, which is the right rule for "which should I
    READ" and an arbitrary one for "which should I DESTROY".

    So: exact-path deletes only, and when the resolver disagrees, SAY SO and exit
    non-zero. A silent gap becomes a loud one, and every deletion decision stays
    on row **39219cc1**, where the write/clear symmetry question belongs. This
    verb REPORTS the asymmetry; it does not paper over it and does not resolve it.
    A verb that refuses to guess is the paved road; a verb that guesses at
    deletion is a new hazard wearing the fix's name.
    """
    exact = hold_path( args.session_id, base_dir=args.base_dir )

    # ONE RESOLUTION FOR THE GUARD AND THE ACTION — that split IS A-4. Decide on the
    # exact path, act on the exact path; nothing here consults the prefix resolver.
    if exact.exists():
        # NAME WHAT IS BEING DESTROYED (C-2, Rio ⚡). `write` refuses to drop cargo
        # and routes the caller HERE — "deleting it should be an act you can point
        # at". A clear that does not say what it removed is not pointable-at, so
        # the sentence in write's refusal would have been writing a cheque this
        # verb didn't honor. Deliberate deletion stays allowed; it stops being silent.
        # Exact reader here too (8abdcbbf). This branch already proved `exact`
        # exists, so `read_hold` would have resolved to the same file — but by
        # CIRCUMSTANCE, not by construction. Naming what a delete destroys must
        # read what the delete destroys; leaving that to a coincidence is how the
        # split above survived review in the first place.
        cargo = hold_cargo_keys( read_hold_exact( args.session_id, base_dir=args.base_dir ) )
        clear_hold( args.session_id, base_dir=args.base_dir )
        print( f"CLEARED  {exact}" )
        if cargo:
            print( f"         ...including {len( cargo )} non-schema field(s) that are now "
                   f"GONE: {', '.join( cargo )}", file=sys.stderr )

        # 39219cc1 F1 — DID THAT ACTUALLY RELEASE THE CALLER? The delete is exact;
        # the READER is prefix-tolerant. So this id can still resolve to a hold —
        # a sibling written under the session's other id form — and the caller who
        # was just told CLEARED walks away STILL HONORED, still defending a
        # quiescence it has left. That is the false success this verb exists to
        # kill, surviving in the branch nobody checked: the sibling test below ran
        # ONLY when the exact path was absent, so the delete path never asked.
        #
        # ASK THE READER THE HOOK USES, rather than inferring the answer from the
        # file list — the verdict a caller cares about is "am I still held", and
        # that is a question only the resolver can answer. Nothing further is
        # deleted: the survivor may be another session's live hold (C2).
        if read_hold( args.session_id, base_dir=args.base_dir ) is not None:
            still = _prefix_siblings( args.session_id, base_dir=args.base_dir )
            print( f"STILL HELD: {exact.name} is gone, but this session id STILL RESOLVES to a "
                   f"hold and is still honored:", file=sys.stderr )
            for sibling in still:
                print( f"           {sibling}", file=sys.stderr )
            print(  "         You are NOT released. That file is read by your other id form; "
                    "clear it by naming ITS id.", file=sys.stderr )
            print(  "         Nothing else was deleted — it may belong to another session, and "
                    "this verb will not guess at a deletion.", file=sys.stderr )
            return EXIT_STILL_HELD
        return EXIT_OK

    siblings = _prefix_siblings( args.session_id, base_dir=args.base_dir )
    if siblings:
        print( f"REFUSED: no hold at this session's own path ({exact}), but "
               f"{len( siblings )} hold(s) share this ID PREFIX:", file=sys.stderr )
        for sibling in siblings:
            print( f"           {sibling}", file=sys.stderr )
        print(  "         Nothing was deleted. Those files may belong to other sessions, and "
                "this verb will not guess at a deletion.", file=sys.stderr )
        print(  "         Re-run with the session id a hold actually names.", file=sys.stderr )
        return EXIT_ORPHAN

    print( f"no hold found for session {args.session_id} in "
           f"{_resolve_base_dir( args.base_dir )}", file=sys.stderr )
    return EXIT_NO_HOLD


def build_parser():
    """
    Ensures:
        - Returns the argparse parser for every subcommand
        - `--ttl-seconds` is type=int, so a non-numeric ttl is refused by argparse
          (exit 2) and never reaches `write_hold` — see the module docstring, item 3
        - `--work-owed` / `--no-work-owed` are an explicit pair defaulting to owed:
          a session that bothered to declare a hold is presumed to owe work
    """
    p   = argparse.ArgumentParser(
        prog="heartbeat_hold_io.py",
        description="Declare, inspect and release the per-session heartbeat hold.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers( dest="cmd", required=True )

    def common( sp ):
        sp.add_argument( "--session-id", required=True,
                         help="FULL session id (from get_session_info())" )
        sp.add_argument( "--base-dir", default=None,
                         help="directory holding the artifact (default: the project root, "
                              "exactly as write_hold resolves it)" )

    w = sub.add_parser( "write", help="declare a hold (RECORD + verify-by-read, in ONE call)" )
    common( w )
    w.add_argument( "--persona",     required=True, help="owning persona, e.g. \"María 🌸\"" )
    w.add_argument( "--reason",      required=True, help="why this session is holding" )
    w.add_argument( "--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS,
                    help=f"freshness window in seconds (default: {DEFAULT_TTL_SECONDS})" )
    w.add_argument( "--awaiting",    default=AWAITING_NONE,
                    help="user:<name> / peer:<persona> / commons:<topic> / cadence:<what> / none" )
    w.add_argument( "--work-owed",    dest="work_owed", action="store_true",  default=True )
    w.add_argument( "--no-work-owed", dest="work_owed", action="store_false",
                    help="this session owes nothing — done, never poke" )
    w.set_defaults( func=cmd_write )

    r = sub.add_parser( "read", help="print the hold + the verdict the hook would reach" )
    common( r )
    r.set_defaults( func=cmd_read )

    c = sub.add_parser( "clear", help="release the hold (idempotent on disk; reports if absent)" )
    common( c )
    c.set_defaults( func=cmd_clear )

    return p


def main( argv=None ):
    """
    Ensures:
        - Dispatches to the selected subcommand and returns its exit code
        - A `write_hold` ValueError is printed VERBATIM at EXIT_REFUSED — its
          message explains why an unusable ttl cannot defend a session, and
          re-wording it here would cost the caller that explanation
        - An OSError (unwritable / missing target dir) is reported at EXIT_REFUSED
          rather than escaping as a traceback
    """
    args = build_parser().parse_args( argv )
    try:
        return args.func( args )
    except ( ValueError, OSError ) as e:
        print( f"REFUSED: {e}", file=sys.stderr )
        return EXIT_REFUSED


def quick_smoke_test():
    """
    Self-contained, side-effect-free smoke test (uses a temp dir).

    Ensures:
        - Returns True iff BOTH polarities hold — a valid write lands an honored
          hold, and an invalid ttl is refused with nothing left on disk; raises
          AssertionError otherwise.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        sid = "smokecli-0001"

        assert main( [ "write", "--session-id", sid, "--persona", "Clayton 😎",
                       "--reason", "smoke", "--base-dir", tmp ] ) == EXIT_OK, \
            "valid write must succeed"
        assert main( [ "read", "--session-id", sid, "--base-dir", tmp ] ) == EXIT_OK

        bad = "smokecli-0002"
        assert main( [ "write", "--session-id", bad, "--persona", "Clayton 😎",
                       "--reason", "smoke", "--ttl-seconds", "0",
                       "--base-dir", tmp ] ) == EXIT_REFUSED, "ttl=0 must be refused"
        assert not hold_path( bad, base_dir=tmp ).exists(), "a refused write must leave NOTHING"

        assert main( [ "clear", "--session-id", sid, "--base-dir", tmp ] ) == EXIT_OK
        assert main( [ "clear", "--session-id", sid, "--base-dir", tmp ] ) == EXIT_NO_HOLD

    return True


if __name__ == "__main__":   # pragma: no cover - CLI entrypoint
    sys.exit( main() )
