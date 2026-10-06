#!/usr/bin/env python3
"""
The hold write, read and clear verb: a command line front-end over `write_hold`.

A mechanism nothing forces you to use is a rule with extra steps. `write_hold()` in `heartbeat_hold.py` is correct but unreachable from a shell: that module has no argparse, and its `__main__` block only runs `quick_smoke_test()`.
So an agent asked to declare a hold could only hand-write the JSON, and the fleet did. Of 22 null-TTL hold files measured on disk, none went through `write_hold`.
Two fingerprints agree: they carry cargo the schema has no fields for, and their ttl key is absent while `write_hold` always emits it.
The fleet followed doctrine: `planning-is-prompting/workflow/fleet-pause-resume.md` prescribed a filename and a JSON shape, the only `heartbeat-hold-` prescription in `workflow/`.
A shape can be typed wrong or short with nothing noticing. This file lets doctrine prescribe a verb, the one form of that instruction that carries its own enforcement.

What this file does not do:
  1. It does not make hand-writing impossible. It makes the correct act cheaper than the incorrect one and gives doctrine something to name: a paved road, not a wall.
  2. It adds no validation of its own. Every guard is `write_hold`'s, reached by delegation; a re-implemented schema drifts and mints holds that look official and are not.
  3. The non-numeric ttl branch of `write_hold` is not reachable from here. `--ttl-seconds` is `type=int`, so argparse rejects "abc" at exit 2. Non-positive values (0, -5) do reach it and do raise.

Verify by execution: `write` reads the hold back through the real reader and confirms the hook would honor it before printing success. A hold that lands but cannot defend its session is the four-week silence.
Every refusal leaves the disk as it found it. A `write_hold` ValueError validates before touching the filesystem, so nothing is left. A verify failure restores the prior hold's bytes and mtime, or unlinks the file when none existed.
Unlinking is not the fix. The destructive act is `write_hold` overwriting a good hold, and unlinking leaves the same undefended session by a cleaner route. Only restoring the previous hold preserves the defense, so `cmd_write` captures the prior bytes before the write.

Two detectors guard the write: the writer's own guards, and the read-back honored check. They are redundant on every known class, because the empty-reason class moved to the writer.
The read-back stays as the general net over classes nobody has enumerated: a base_dir that resolves elsewhere, clock or mtime pathology, future schema drift. Its coverage is a synthetic injection plus the rollback tests.
Keep both detectors isolated, since an unisolated redundancy is the defect. Neutering only the read-back (`if not is_honored( read_back )` to `if False`) and stripping the writer's non-positive arm each redden tests on their own.
Stripping `write_hold`'s ttl guard trips both detectors, so it shows redundancy and says nothing about isolation. The day the read-back loses its own killing mutation it has become decoration.

Cargo: `write_hold` persists exactly `HOLD_SCHEMA_FIELDS` through an `os.replace`, so writing over a hold with non-schema fields (`note_to_my_successor`, `board`, `harvest_state`, `blocked_rows`) destroys them.
It did so at exit 0 under a success banner.
Prescribing the verb would have destroyed the payload in each of 56 hand-written holds on first use. So `write` refuses when the existing hold carries cargo, names every field, and exits 6.
There is no `--force`, because an escape taken silently is not a gate. Move the payload to a memento (`memento_io.py write`), or `clear` first when you are done with it.
A hold is a liveness artifact with a TTL; a memento is the continuity record, and continuity does not belong behind an expiry. The verb takes no cargo parameter and should not grow one, but refusing loudly keeps that narrowness from costing the caller's data.

Where the hold lands: `--base-dir` defaults to `write_hold`'s default, `fleet_data_root()` (the `projects-data/<repo>` dir), formerly the project root. From a plan session, `read` without `--base-dir` once said "no hold found" for an id that was honored under another directory.
The default is not changed, because diverging from the writer would mint a second write semantics. Every printed path names its directory.
A not-found says where it looked, since a null that does not say where it searched is not evidence.
Invocation. The second form needs PYTHONPATH to carry `src`:.
    python3 $LUPIN_ROOT/src/lupin_cli/claude_code/hooks/lib/heartbeat_hold_io.py write --session-id <full-id> --persona <name> --reason <why> .
    python3 -m lupin_cli.claude_code.hooks.lib.heartbeat_hold_io read --session-id <id> .
Exit codes are distinct, so a caller never has to parse the message:
    0 success.
    2 usage error, or a value `write_hold` refuses (its ValueError, verbatim).
    3 the hold landed but would not be honored. 4 `read` or `clear` found no hold.
    5 `clear` found a hold under a matching id prefix but not at this session's own path (named, not deleted).
    6 `write` found existing non-schema cargo it cannot preserve (named, not destroyed). 7 `clear` deleted the exact file but this id still resolves to a hold through the reader's prefix fallback.
"""
import argparse
import datetime
import json
import os
import sys


def _bootstrap_sys_path():
    """
    Put `<LUPIN_ROOT>/src` on `sys.path` so this file runs as a path, not only a module.

    This is the CLAUDE.md bootstrap exception: it uses the env var, never a `__file__` chain.

    Requires:
        - nothing; a missing LUPIN_ROOT is a normal, non-fatal state (the module
          is already importable when run via `-m` with PYTHONPATH carrying `src`)

    Ensures:
        - Returns True iff `<LUPIN_ROOT>/src` was inserted at sys.path[0]
        - Returns False when LUPIN_ROOT is unset, or the path is already present
          (idempotent, so importing this module twice never stacks entries)
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
    AWAITING_NONE, DEFAULT_TTL_SECONDS, HOLD_FILENAME_TEMPLATE, _now,
    _resolve_base_dir, clear_hold, hold_cargo_keys, hold_path, hold_search_dirs, is_honored,
    read_hold, read_hold_exact, read_hold_resilient, write_hold,
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


# THE THREE STAMPS THE POKE NAMES AND THIS CLI COULD NOT SET (bug 1dcaf65c).
#
# The Stop-hook poke says "look in on your workers (stamp
# last_looked_in_on_workers_ts)". The field is real, `write_hold` has taken it as
# a kwarg since A1, and `get_last_looked_in_ts` reads it to debounce the inward
# twin — but `write` exposed no flag for it, nor for its two siblings. A manager
# who reads the poke, runs the sanctioned verb and finds no flag is left with the
# hand-written JSON that CLAUDE.md bans and row 011f1f90 counts 33 of. The
# instruction and the tool disagreed, and the tool is the one people obey.
#
# ONE TABLE, NOT THREE PARALLEL LISTS. The argparse dest, the flag spelling and
# the schema field are declared together so a fourth stamp cannot be added to the
# parser and forgotten in the pass-through — which is the shape of the bug being
# closed, one layer up.
STAMP_ARGS = (
    ( "looked_in",          "--looked-in",          "last_looked_in_on_workers_ts",
      "manager worker-verification look-in" ),
    ( "spinup_check",       "--spinup-check",       "last_spinup_check_ts",
      "manager spin-up check (Face A)" ),
    ( "surfaced_questions", "--surfaced-questions", "last_surfaced_questions_ts",
      "surfaced-questions sweep (Face B)" ),
)

STAMP_NOW = "now"


def _resolve_stamp( value, flag ):
    """
    Turn one `--looked-in` family flag value into the ISO string `write_hold` stores.

    Requires:
        - value is None, the literal "now", or an ISO-8601 timestamp string
        - flag is the flag spelling, used only to name the offender in a refusal

    Ensures:
        - Returns None when value is None: the flag was not passed, and the
          stamp stays whatever write_hold defaults it to
        - Returns an aware, seconds-precision ISO string for "now" (any case,
          surrounding whitespace tolerated), in UTC like the `held_at` that `write_hold` stamps
        - Returns the seconds-precision ISO form of an explicit offset-bearing
          timestamp, offset preserved exactly as the caller wrote it

    Raises:
        - ValueError naming the flag and the value when it cannot be dated
        - ValueError when the timestamp parses but carries no offset

    It refuses instead of passing the string through. Every reader of these fields degrades to None on an unparseable stamp, so `manager_needs_verification` reads the manager as never having looked in.
    So `--looked-in yesterday` would land under a success banner and leave the manager poked as before. Refuse it at the front door, where the typo is.

    A zone-less timestamp is refused rather than assumed to be UTC. `_parse_iso` assumes UTC, but `_iso_age_seconds` calls `.timestamp()` on the naive datetime, which Python resolves in local time.
    On a UTC-4 host one naive stamp dates 14400 seconds apart depending on the reader, most of a debounce window. A guessed zone gives an error that reads as a plausible timestamp and debounces the wrong way. A caller who knows the zone can always state it, so the verb should not pick it.

    `"now"` resolves through `_now()` to aware UTC, as `write_hold` writes `held_at`, so the house format is offset-bearing and only input that does not meet it is refused.
    One `fromisoformat` call gives both the datable and the offset verdict, because two parsers are how two guards end up disagreeing about one value.
    """
    if value is None:
        return None
    if str( value ).strip().lower() == STAMP_NOW:
        return _now().isoformat( timespec="seconds" )

    text = str( value ).strip()
    if text.endswith( "Z" ):                      # Zulu is an offset; 3.10 cannot read it
        text = text[ :-1 ] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat( text )
    except ValueError:
        parsed = None

    if parsed is None:
        raise ValueError(
            f"{flag} must be \"{STAMP_NOW}\" or an ISO-8601 timestamp, got {value!r} — every "
            f"reader of this field degrades to None on a stamp it cannot date, so this would "
            f"land under a success banner and still read as NEVER RUN, leaving you poked."
        )
    if parsed.tzinfo is None:
        raise ValueError(
            f"{flag} needs a UTC offset, got {value!r} — this verb will not pick a timezone you "
            f"did not give it. A zone-less stamp is read as UTC by one reader and as LOCAL time "
            f"by another, so it silently dates wrong by the host offset. Write it as "
            f"{text}+00:00 (or your real offset), or pass \"{STAMP_NOW}\"."
        )
    return parsed.isoformat( timespec="seconds" )


def _undo_this_write( path, prior_bytes, prior_times ):
    """
    Put the disk back the way this call found it, and say what that meant.

    Requires:
        - prior_bytes and prior_times were captured before the write (None when no hold existed)

    Ensures:
        - with no prior hold, the artifact is unlinked and it returns "nothing was written"
        - with a prior hold, its bytes and mtime are restored (see cmd_write on
          why mtime matters) and it returns the restored wording
    """
    if prior_bytes is None:
        path.unlink( missing_ok=True )
        return "nothing was written"
    path.write_bytes( prior_bytes )
    os.utime( path, prior_times )
    return "the previous hold has been RESTORED (bytes and mtime)"


def cmd_write( args ):
    """
    Mint or refresh this session's hold, the verb doctrine can prescribe.

    Requires:
        - args carries session_id / persona / reason (all required by the parser)
        - args carries ttl_seconds / awaiting / work_owed / base_dir
        - args carries looked_in / spinup_check / surfaced_questions, each None,
          the literal "now", or an ISO-8601 timestamp

    Ensures:
        - Passes the three debounce stamps straight through to `write_hold`'s existing kwargs,
          resolving "now" and normalizing an explicit timestamp to its aware form;
          an undatable value is refused at `EXIT_REFUSED` before anything is written
        - Names each stamp that landed in the banner, because the caller's reason
          for passing one is to clear a poke and "ok" does not say whether it is
        - Delegates to `write_hold` unchanged, so no validation is duplicated here
          and this front-end can never drift from the writer it fronts
        - Reads the hold back through the real reader and through the Stop hook's own search from the current
          directory, and returns `EXIT_NOT_HONORED` when the hook would not honor it or would find a different hold first
        - An `EXIT_NOT_HONORED` refusal leaves the disk exactly as it found it: bytes
          and mtime restored when a prior hold existed, artifact unlinked when none did
        - Prints the resolved path, the persisted ttl and the honored verdict on
          success, so the caller sees what landed rather than "ok"
        - Returns `EXIT_OK` on success

    Raises:
        - ValueError from `write_hold` for an unusable ttl or an empty reason,
          caught by main() and surfaced verbatim at `EXIT_REFUSED`, never swallowed and never re-worded

    When the existing hold carries non-schema cargo it returns `EXIT_CARGO`, naming every field and writing nothing.
    Rollback fires for any way a hold can land unhonorable, including causes nobody has found, so it is enforced at the path and not patched at one cause. It undoes only this call's own write.
    Which refusal leaves what: a `write_hold` ValueError leaves nothing, since it validates first. A verify failure with no prior hold unlinks; with a prior hold it leaves the prior, byte-exact and mtime-exact.
    The restore keeps mtime because `is_fresh` anchors on the file mtime, not `held_at`: a prior hold with mtime forced to epoch 0 read not honored, yet rewriting identical bytes read honored.
    A naive restore would resurrect a dead hold, hence `os.utime` with the captured times. The prior is restored whatever its state, since this verb must not silently delete what it did not create; reclamation is the janitor's job.
    Capture happens before the write, because `write_hold` has already replaced the original by the time the verify runs.
    """
    # STAMPS FIRST, BEFORE THE DISK IS TOUCHED AT ALL (bug 1dcaf65c). A mistyped
    # `--looked-in` is a usage error, and refusing it here — ahead of the cargo
    # guard, ahead of the prior-hold capture — makes "every refusal leaves the
    # disk as it found it" true by construction on this path rather than by a
    # rollback that has to be maintained.
    stamps = { field: _resolve_stamp( getattr( args, dest ), flag )
               for dest, flag, field, _label in STAMP_ARGS }

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
        awaiting=args.awaiting, base_dir=args.base_dir, **stamps,
    )

    read_back = read_hold( args.session_id, base_dir=args.base_dir )
    if not is_honored( read_back ):
        outcome = _undo_this_write( path, prior_bytes, prior_times )
        print( f"FAILED: the hold this call wrote would NOT be honored — it cannot defend "
               f"this session's quiescence, so {outcome}. Target: {path}", file=sys.stderr )
        return EXIT_NOT_HONORED

    # 🔴 ROW 6698d40f (c): "honored yes" USED TO BE A FALSE GREEN. The read-back above
    # opens the file this call wrote, at the path this call chose, so it cannot fail on
    # WHERE the hold landed. The Stop hook never reads a path it is handed: it searches
    # `hold_search_dirs( cwd )` and takes the FIRST hold it finds. Measured on María's
    # seat, 2026-09-14 22:54: this verb printed "honored yes" for a hold in
    # projects-data/planning-is-prompting, a directory the hook did not search then, and
    # the next stop poked "No fresh hold". So the verdict now comes from the hook's own
    # search, run from where the caller stands. A different hold found first (a stale
    # hand-written one at the repo root, say) fails it too, because that is the one the
    # hook would read.
    cwd       = os.getcwd()
    hook_sees = read_hold_resilient( args.session_id, cwd=cwd )
    if hook_sees != read_back:
        outcome  = _undo_this_write( path, prior_bytes, prior_times )
        searched = ", ".join( str( base ) for base in hold_search_dirs( cwd ) )
        seen     = "no hold at all" if hook_sees is None else "a DIFFERENT hold first"
        print( f"FAILED: the Stop hook would not read this hold. Searching from {cwd} it finds "
               f"{seen}, so {outcome}. Target: {path}. The hook searches, in order: {searched}. "
               f"Drop --base-dir, or clear the hold that shadows it.", file=sys.stderr )
        return EXIT_NOT_HONORED

    print( f"HOLD     {path}" )
    print( f"ttl      {hold[ 'ttl_seconds' ]}s   awaiting: {hold[ 'awaiting' ]}   "
           f"work_owed: {hold[ 'work_owed' ]}" )
    print( f"honored  yes (found by the Stop hook's own search from {cwd})" )

    # NAME THE STAMP THAT LANDED. The caller passed `--looked-in now` to clear a
    # poke; "ok" does not tell them the poke is cleared, and the value that landed
    # is the only thing the debounce actually reads.
    for _dest, flag, field, label in STAMP_ARGS:
        if hold[ field ] is not None:
            print( f"stamped  {label}: {hold[ field ]}   ({flag})" )

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
    Every hold file sharing this session id's 8-char prefix, except its own exact path.

    Requires:
        - session_id is a string; base_dir is a path-like / string / None

    Ensures:
        - Returns a sorted list of Paths, `.tmp` atomic-write artifacts excluded
        - Returns [] for an empty session_id, or when the directory is unreadable
        - Never raises

    It returns every match and not just the resolved one. `_read_hold_path` returns one file, longest-then-lexical, which is right for which to read and no rule for how many orphans exist.
    A refusal naming one orphan while two exist leaves the other defending a session that has moved on.
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
    Remove this session's hold, the explicit "I am no longer holding" act.

    Requires:
        - args carries session_id and base_dir

    Ensures:
        - Returns `EXIT_NO_HOLD` when there is no hold at all (the caller learns its
          hold was already gone rather than being told "cleared")
        - Deletes only the exact path for this session id, never a prefix match
        - Returns `EXIT_ORPHAN`, deleting nothing, when a hold exists but resolves
          to a different file than this id names: the orphan is named, not guessed at

    Why exact path only: `read_hold` falls back to a prefix match so a hold written under the short bridge id is still found by a hook reading the full id, but `clear_hold` keys on the exact path.
    The shipped code let the prefix-tolerant guard wave the call through while the exact-path action unlinked a file that was not there. A session clearing with the short id was told its hold was released while it stayed honored. That surviving hold is what the janitor later finds as an unaccountable hold file.
    Clearing whatever the reader resolved is worse than the gap, because it makes a delete decided by a wildcard. An id naming no file could destroy another session's live hold. Its owner would then be poked out of a quiescence it correctly declared, the ping-storm this verb exists to prevent.
    With several prefix matches the longest-then-lexical rule is arbitrary for choosing what to destroy. So when the resolver disagrees the verb names the orphans and exits non-zero: it reports the asymmetry and does not guess.
    After an exact delete it asks the hook's reader again. When the id still resolves to a hold, it prints the survivors and returns `EXIT_STILL_HELD`, deleting nothing else.
    It also names any non-schema fields the delete destroyed, so a deliberate deletion stays allowed but is never silent.
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
    Build the argparse parser with the write, read and clear subcommands.

    Ensures:
        - Returns the argparse parser for every subcommand
        - `--ttl-seconds` is type=int, so a non-numeric ttl is refused by argparse
          (exit 2) and never reaches `write_hold`; see the module docstring, third item
        - `--work-owed` / `--no-work-owed` are an explicit pair defaulting to owed:
          a session that bothered to declare a hold is presumed to owe work
        - `write` carries one flag per `STAMP_ARGS` row, each defaulting to None so
          an unpassed flag leaves the stamp to `write_hold`
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
                         help="directory holding the artifact (default: fleet_data_root() "
                              "= the projects-data/<repo> dir, exactly as write_hold resolves it)" )

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
    for dest, flag, _field, label in STAMP_ARGS:
        w.add_argument( flag, dest=dest, default=None,
                        help=f"stamp the {label} — \"now\" or an ISO-8601 timestamp" )
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
    Run the selected subcommand and return its exit code.

    Ensures:
        - Dispatches to the selected subcommand and returns its exit code
        - A `write_hold` ValueError is printed verbatim at `EXIT_REFUSED`; its
          message explains why an unusable ttl cannot defend a session, and
          re-wording it here would cost the caller that explanation
        - An OSError (unwritable or missing target dir) is reported at `EXIT_REFUSED`
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
        - Returns True iff both polarities hold: a valid write lands an honored
          hold, and an invalid ttl is refused with nothing left on disk; raises
          AssertionError otherwise.
    """
    import tempfile

    # STAND IN THE TEMP DIR WHILE WRITING TO IT. `write` asks the Stop hook's own search,
    # run from the cwd, whether it finds the hold (row 6698d40f), and the hook searches a
    # session's cwd first. The cwd is restored whether the asserts pass or not.
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir( tmp )
        try:
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
        finally:
            os.chdir( here )

    return True


if __name__ == "__main__":   # pragma: no cover - CLI entrypoint
    sys.exit( main() )
