#!/usr/bin/env python3
"""
Phase 3 persona-slug canonicalization sweep (DRY-RUN by DEFAULT).

Part of the persona-name normalization milestone
(`src/rnd/v0.1.9/2026.06.19-persona-name-normalization/01-centralized-persona-normalization-plan.md`
§Phase 3). After `_dm_topic_for` / `_derive_dm_topic` / `session_spawner` were
routed through the shared `persona_slug` root, a persona's DM-topic file and
spawned tmux sessions should already sit at the canonical slug — the plan
EXPECTS this sweep to be a near no-op, because live bridges hold the pool form
("mr radio", "maria") and so existing topics are already `dm-mr_radio` /
`dm-maria`. This tool proves that, and renames any straggler.

WHY owner-driven (not a blind scan): `io/commons/` holds many `dm-*` topics that
are NOT persona-derived — ad-hoc collection topics (`dm-2-reviewers`), session-id
topics (`dm-07fba31d`), spawned-session topics (`dm-cc-author-mr-radio-1`). A
blind "is this stem already canonical?" check would FALSE-POSITIVE on all of
them (their stems are not personas and need not canonicalize). So the sweep
enumerates KNOWN persona OWNERS and, for each, looks for non-canonical spellings
of *that owner's* topic. An owner with no variant is a clean no-op.

WHAT it does:
  - TOPICS  — for each owner, canonical = `dm-{persona_slug(owner, '_')}.md`.
    Find sibling `dm-*.md` files (commons dir + archive) whose persona_slug
    matches the owner's canonical slug but whose name differs (e.g. `dm-maría.md`
    vs canonical `dm-maria.md`). Report; with `--apply`, rename the variant to
    the canonical name. If the canonical file ALSO exists, this is a MERGE (two
    real files) — the sweep does NOT auto-merge (that is the dedupe-aware job of
    `migrate-dm-topic-case.py`); it reports `merge_required` and skips.
  - TMUX    — for each owner, expected persona slug = `persona_slug(owner, '-')`.
    Report any live `cc-<role>-<personaslug>-<n>` session whose embedded persona
    segment is a non-canonical spelling of an owner. tmux is REPORT-ONLY by
    design: renaming a LIVE session orphans its bridge `tmux_session` linkage, so
    the manager-owned remedy is reap + respawn, never an in-place rename here.

SAFETY:
  - DRY-RUN is the default. `--apply` is required to mutate the filesystem, and
    only ever renames topic FILES (never live tmux sessions).
  - The live cutover is gated for a quiet window by the manager / Rick.

Run:
    export LUPIN_ROOT=/path/to/lupin
    python src/scripts/sweep_persona_slug_canonicalization.py            # dry-run report
    python src/scripts/sweep_persona_slug_canonicalization.py --apply    # rename topic stragglers
    python src/scripts/sweep_persona_slug_canonicalization.py --persona "María" --persona "Mr. Radio"

100% coverage by the companion suite
`src/tests/unit/test_sweep_persona_slug_canonicalization.py` (scan/report/apply
exercised with injected owners, a temp commons dir, and a fake tmux lister).
"""
import argparse
import os
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional


# ── Bootstrap LUPIN_ROOT so we can import lupin_mcp.persona_normalization ──────
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT is None:                                                # pragma: no cover - env guard
    raise RuntimeError(                                                # pragma: no cover
        "LUPIN_ROOT environment variable not set.\n"                   # pragma: no cover
        "  export LUPIN_ROOT=/path/to/lupin"                           # pragma: no cover
    )
_SRC_PATH = os.path.join( _LUPIN_ROOT, "src" )
if _SRC_PATH not in sys.path:                                          # pragma: no cover - path guard
    sys.path.insert( 0, _SRC_PATH )                                    # pragma: no cover

from lupin_mcp.persona_normalization import normalize_for_match, persona_slug


# A spawned session name is `cc-<role>-<persona-slug>-<n>` (session_spawner._slug
# / persona_slug for the persona part, sep="-"). These are the role tokens the
# spawner emits; used to peel role + index off the front/back to recover the
# persona segment.
_SPAWN_ROLES = ( "reviewer", "author", "observer", "manager" )
_SPAWN_NAME_RE = re.compile(
    r"^cc-(?P<role>" + "|".join( _SPAWN_ROLES ) + r")-(?P<persona>.+)-(?P<idx>\d+)$"
)


def topic_stem( filename ) -> str:
    """
    Persona stem of a `dm-<stem>.md` topic file name.

    Requires:
        - filename is a string

    Ensures:
        - "dm-maría.md" -> "maría"; "dm-mr_radio.md" -> "mr_radio"
        - a name not matching `dm-*.md` -> "" (caller skips it)
    """
    if not filename.startswith( "dm-" ) or not filename.endswith( ".md" ):
        return ""
    return filename[ len( "dm-" ): -len( ".md" ) ]


def persona_segment_of_session( session_name ) -> Optional[ str ]:
    """
    Recover the persona segment of a spawned tmux session name.

    Requires:
        - session_name is a string

    Ensures:
        - "cc-author-mr-radio-1" -> "mr-radio"; "cc-reviewer-maría-2" -> "maría"
        - a name not matching the spawn pattern -> None (not persona-derived)
    """
    m = _SPAWN_NAME_RE.match( session_name )
    return m.group( "persona" ) if m else None


def scan_topic_mismatches( commons_dir, owners ) -> List[ Dict[ str, object ] ]:
    """
    Find non-canonical DM-topic files for each known persona owner.

    For owner O the canonical topic stem is `persona_slug(O, "_")`. Matching a
    file to an owner uses the SEPARATOR-AGNOSTIC `normalize_for_match` key, so a
    legacy file under any separator spelling is caught: `dm-mr radio` (space),
    `dm-mr-radio` (hyphen) and `dm-MR.RADIO` all `normalize_for_match` to
    "mrradio" — the same as owner "Mr. Radio" — and rename to the canonical
    `dm-mr_radio`. (Matching on `persona_slug(stem, "_")` instead would MISS the
    hyphen form, since "-" is stripped, not preserved as a "_" boundary.) Compound
    topics (`dm-mr_radio_tiberius`) normalize to a different key and are skipped.

    Requires:
        - commons_dir is a Path to the `io/commons` directory (may be missing)
        - owners is an iterable of persona names (display or pool form)

    Ensures:
        - Returns a list of dicts, one per straggler file:
            { "owner", "current": "dm-<variant>.md", "canonical": "dm-<slug>.md",
              "path": <Path>, "merge_required": <bool> }
          where merge_required is True iff the canonical file already exists
          (so a plain rename would clobber it — defer to migrate-dm-topic-case.py)
        - A canonical-only owner (no variant) contributes nothing (no-op)
        - Deterministic ordering (sorted file paths; live dir before archive)
    """
    commons_dir = Path( commons_dir )
    # Separator-agnostic match key -> (owner, canonical "_"-slug stem).
    owner_by_match = { }
    for owner in owners:
        match_key = normalize_for_match( owner )
        if match_key:
            owner_by_match.setdefault( match_key, ( owner, persona_slug( owner, sep="_" ) ) )

    # All dm-*.md files across the live dir + archive, sorted for determinism.
    dirs  = [ commons_dir, commons_dir / "archive" ]
    files = []
    for d in dirs:
        if d.is_dir():
            files.extend( sorted( d.glob( "dm-*.md" ), key=lambda p: str( p ) ) )

    out = []
    for path in files:
        stem  = topic_stem( path.name )
        match = owner_by_match.get( normalize_for_match( stem ) )
        if match is None:
            continue                       # not a known persona's topic — leave it
        owner, canonical_stem = match
        if stem == canonical_stem:
            continue                       # already canonical — no-op
        canonical_path = path.with_name( f"dm-{canonical_stem}.md" )
        out.append( {
            "owner"          : owner,
            "current"        : path.name,
            "canonical"      : canonical_path.name,
            "path"           : path,
            "merge_required" : canonical_path.exists(),
        } )
    return out


def scan_tmux_mismatches( session_names, owners ) -> List[ Dict[ str, object ] ]:
    """
    Find live spawned tmux sessions whose persona segment is non-canonical.

    Requires:
        - session_names is an iterable of tmux session-name strings
        - owners is an iterable of persona names

    Ensures:
        - Returns a list of dicts, one per non-canonical persona-named session:
            { "owner", "session", "persona_segment", "canonical_segment" }
        - Sessions not matching the spawn pattern, or whose persona segment is
          already canonical, contribute nothing
        - REPORT-ONLY: this sweep never renames a live session (that would orphan
          the bridge tmux_session linkage; reap+respawn is the manager remedy)
    """
    owner_by_match = { }
    for owner in owners:
        match_key = normalize_for_match( owner )
        if match_key:
            owner_by_match.setdefault( match_key, ( owner, persona_slug( owner, sep="-" ) ) )

    out = []
    for name in session_names:
        segment = persona_segment_of_session( name )
        if segment is None:
            continue
        match = owner_by_match.get( normalize_for_match( segment ) )
        if match is None:
            continue                       # segment not a known persona
        owner, canonical_segment = match
        if segment == canonical_segment:
            continue                       # already canonical
        out.append( {
            "owner"             : owner,
            "session"           : name,
            "persona_segment"   : segment,
            "canonical_segment" : canonical_segment,
        } )
    return out


def apply_topic_renames( mismatches, *, renamer=None ) -> List[ Dict[ str, object ] ]:
    """
    Rename topic-file stragglers to their canonical name.

    Requires:
        - mismatches is the list returned by `scan_topic_mismatches`
        - renamer is a callable (src_path, dst_path) -> None (defaults to
          os.rename); injectable for tests

    Ensures:
        - Each mismatch with merge_required=False is renamed current -> canonical
        - Each mismatch with merge_required=True is SKIPPED (would clobber) and
          reported with action="skipped_merge_required"
        - Returns a per-file action log:
            { "current", "canonical", "action": "renamed" | "skipped_merge_required" }
    """
    renamer = renamer or ( lambda src, dst: os.rename( src, dst ) )
    log = []
    for m in mismatches:
        if m[ "merge_required" ]:
            log.append( { "current": m[ "current" ], "canonical": m[ "canonical" ],
                          "action": "skipped_merge_required" } )
            continue
        src = m[ "path" ]
        dst = src.with_name( m[ "canonical" ] )
        renamer( src, dst )
        log.append( { "current": m[ "current" ], "canonical": m[ "canonical" ],
                      "action": "renamed" } )
    return log


def discover_owners_from_bridges() -> List[ str ]:                     # pragma: no cover - live env
    """Live persona owners from active voice-persona bridges (non-test path)."""
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_voice_persona_sessions
    owners = []
    for _path, _sid, persona in find_active_voice_persona_sessions():
        if persona and persona not in owners:
            owners.append( persona )
    return owners


def _list_tmux_sessions() -> List[ str ]:                              # pragma: no cover - live env
    """Live tmux session names (non-test path)."""
    import subprocess
    try:
        out = subprocess.run( [ "tmux", "list-sessions", "-F", "#{session_name}" ],
                              capture_output=True, text=True, check=False )
        return [ ln for ln in out.stdout.splitlines() if ln.strip() ]
    except FileNotFoundError:
        return []


def run_sweep(
    *,
    commons_dir   : os.PathLike,
    owners        : List[ str ],
    session_names : List[ str ],
    apply         : bool        = False,
    renamer       : Optional[ Callable ] = None,
    out           : Callable    = print,
) -> Dict[ str, object ]:
    """
    Execute the sweep against explicit inputs and emit a human report.

    Requires:
        - commons_dir is the io/commons Path; owners + session_names are lists
        - apply gates filesystem mutation (topic renames only)

    Ensures:
        - Returns { "topic_mismatches", "tmux_mismatches", "applied", "no_op" }
        - no_op is True iff there were zero topic AND zero tmux mismatches
        - When apply is False, "applied" is [] and nothing is mutated
        - Pure reporting via the injected `out` callable (default print)
    """
    topic_mm = scan_topic_mismatches( commons_dir, owners )
    tmux_mm  = scan_tmux_mismatches( session_names, owners )

    out( f"persona-slug canonicalization sweep  ({'APPLY' if apply else 'DRY-RUN'})" )
    # Log the RESOLVED commons dir (nit, Phase 4 review): the path keys off
    # LUPIN_ROOT, so a sweep launched from a git WORKTREE points at the worktree's
    # (usually empty) io/commons and falsely reports "no-op". Surfacing the path
    # makes that misdirection visible at a glance instead of silently misleading.
    out( f"  commons dir resolved  : {commons_dir}" )
    out( f"  owners scanned        : {len( owners )}" )
    out( f"  topic-file mismatches : {len( topic_mm )}" )
    out( f"  tmux-session mismatches: {len( tmux_mm )}  (report-only)" )

    for m in topic_mm:
        tag = "MERGE-REQUIRED (skipped)" if m[ "merge_required" ] else "rename"
        out( f"  [topic] {m['current']} -> {m['canonical']}  ({m['owner']!r}) [{tag}]" )
    for m in tmux_mm:
        out( f"  [tmux ] {m['session']}  persona {m['persona_segment']!r} -> "
             f"{m['canonical_segment']!r}  ({m['owner']!r})  REPORT-ONLY" )

    applied = []
    if apply:
        applied = apply_topic_renames( topic_mm, renamer=renamer )
        for a in applied:
            out( f"  APPLIED: {a['current']} -> {a['canonical']} [{a['action']}]" )
    elif topic_mm:
        out( "  (dry-run — re-run with --apply to rename topic stragglers)" )

    no_op = not topic_mm and not tmux_mm
    if no_op:
        out( "  ✓ no-op — every persona topic/session is already canonical" )

    return { "topic_mismatches": topic_mm, "tmux_mismatches": tmux_mm,
             "applied": applied, "no_op": no_op }


def main( argv=None, *, owners=None, session_names=None, commons_dir=None,
          renamer=None, out=print ) -> int:
    """
    CLI entry point. Test-injectable: pass owners/session_names/commons_dir to
    bypass live tmux + bridge discovery.

    Ensures:
        - Parses --apply / --persona; defaults to DRY-RUN
        - Returns 0 always (a report, not a gate); mutation only under --apply
    """
    parser = argparse.ArgumentParser( description="Phase 3 persona-slug canonicalization sweep (dry-run by default)" )
    parser.add_argument( "--apply", action="store_true",
                         help="rename topic-file stragglers (default: dry-run report only)" )
    parser.add_argument( "--persona", action="append", default=[],
                         help="explicit owner persona (repeatable); default = live bridges" )
    args = parser.parse_args( argv )

    resolved_owners = owners if owners is not None else ( args.persona or discover_owners_from_bridges() )
    resolved_sessions = session_names if session_names is not None else _list_tmux_sessions()
    resolved_commons = Path( commons_dir ) if commons_dir is not None else Path( _LUPIN_ROOT ) / "io" / "commons"

    run_sweep(
        commons_dir   = resolved_commons,
        owners        = resolved_owners,
        session_names = resolved_sessions,
        apply         = args.apply,
        renamer       = renamer,
        out           = out,
    )
    return 0


if __name__ == "__main__":                                            # pragma: no cover - entry point
    sys.exit( main() )
