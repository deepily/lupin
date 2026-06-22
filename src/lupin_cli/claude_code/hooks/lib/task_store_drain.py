#!/usr/bin/env python3
"""
Spine cutover migration drain — one-shot back-fill of owed native Task* items.

The cutover prerequisite (cascade review §Q(d)): before the
`heartbeat.owed_source_from_store` flag can be flipped on fleet-wide, the
store's owed-row set must MATCH each live session's transcript reality. Until
now the PostToolUse mirror's write-gate only passed for lupin-manager sessions
(bug `9bf1dc4a`), so **worker native Task* items were never mirrored**. A bare
flag-flip would therefore read 0 owed rows for those sessions and silently
stop poking them — a correctness regression.

This module replays each ACTIVE session's transcript and IDEMPOTENTLY creates
a store item for every owed native item it finds, stamping the SAME identity
the mirror would have stamped:

    owner_persona        = the session's canonical voice-persona key
                           (canonical_persona_key: accent/punct-stripped,
                           lowercased, internal spaces kept — store-key parity)
    accountable_manager  = same (mirror's create branch sets both)
    project              = the session's bridge-cwd-anchored project name
    correlation_key      = cc-task:<stable_sid>:g<generation>:<harness_id>
                           (task_store_mirror.build_correlation_key)

Idempotency is store-authoritative: BEFORE every create, the correlation_key
is probed via `GET /api/tasks?correlation_key=…` — if any item already carries
it (a manager-mirrored row, or a row from a prior drain pass), the create is
SKIPPED. So re-running the drain never duplicates, and a session whose items
were already mirrored is a clean no-op.

A per-session COUNT-PARITY check closes the loop: store owed-count (counted by
probing each owed correlation_key for a live owed-status item) must equal the
transcript owed-count. Parity passing per session is the green light that the
flag is safe to flip.

INVARIANTS (mirror's posture): never raises on a single session's failure
(one bad bridge/transcript is logged + skipped, the pass continues); only the
store IO (`client.*`) can fail, and those failures degrade-safe to ( ok=False )
which surfaces in the report — they NEVER fabricate a created/parity result.

Run: `python -m lupin_cli.claude_code.hooks.lib.task_store_drain [--apply]`
(default is a DRY-RUN preview; `--apply` performs the creates).

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.16-store-canonical-task-mgmt-cascade-review.md §Q(d).
"""

import json
import os
from pathlib import Path

from cosa.agents.utils.sender_id import _PROJECT_ALIASES
from lupin_cli.claude_code.hooks.lib.heartbeat_task_state import (
    replay_task_state, replay_task_subjects, OWED_STATUSES,
)
from lupin_cli.claude_code.hooks.lib.task_store_mirror import build_correlation_key
from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
from lupin_cli.claude_code.hooks.lib import task_store_client as client
from lupin_cli.claude_code.hooks.lib import task_store_map as task_map
from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_voice_persona_sessions
from lupin_mcp.persona_normalization import canonical_persona_key


# STORE-side owed statuses (parity to stop.py STORE_OWED_STATUSES). The mirror
# maps a pending harness task -> store "queued" and an in_progress task ->
# "in_progress"; a drain-created item lands at "queued" (the create endpoint
# forces it). Both are owed.
STORE_OWED_STATUSES = ( "queued", "in_progress" )

# Title used only when a TaskCreate carried no subject (replay_task_subjects
# skips blank subjects but still consumes the ordinal, so the id can still be
# owed without a recoverable title).
DRAIN_TITLE_FALLBACK = "(migrated owed task — no subject in transcript)"
DRAIN_BODY           = "Back-filled by the Spine cutover drain (§Q(d)) — owed native Task* item the manager-gated mirror never wrote."


def _read_bridge( path ):
    """
    Read one session-bridge JSON file (degrade-safe).

    Requires:
        - path is a path-like to a bridge file

    Ensures:
        - Returns the parsed dict, or None on any open/parse error
        - NEVER raises
    """
    try:
        with open( path ) as f:
            data = json.load( f )
    except ( OSError, json.JSONDecodeError, ValueError ):
        return None
    return data if isinstance( data, dict ) else None


def _project_from_cwd( bridge_cwd, environ=None ):
    """
    Resolve a project name from a bridge's SessionStart cwd (mirror parity).

    Mirrors session_bridge._resolve_project_from_bridge_cwd's algorithm
    (walk up to the nearest `.git` ancestor, alias-normalize the basename) but
    sourced from an ARBITRARY session's bridge cwd rather than the current
    process's bridge — the drain resolves many sessions in one process, so it
    cannot use the current-session resolver. Falls back to the LUPIN_ROOT
    basename (then the live cwd basename) exactly as resolve_project_name does,
    so a session whose bridge had no usable cwd resolves to the same default
    the mirror would have stamped.

    Requires:
        - bridge_cwd is a string path or None
        - environ is a Mapping or None (None -> os.environ)

    Ensures:
        - Returns a lowercase, non-empty project name string
        - A malformed cwd (e.g. an embedded null byte) propagates as ValueError;
          the discover loop is the never-raises boundary that skips such a session
    """
    if environ is None:
        environ = os.environ
    if bridge_cwd:
        candidate = Path( bridge_cwd ).resolve()
        for parent in [ candidate, *candidate.parents ]:
            if ( parent / ".git" ).exists():
                name = parent.name.lower()
                return _PROJECT_ALIASES.get( name, name )
        basename = candidate.name.lower()
        return _PROJECT_ALIASES.get( basename, basename )
    lupin_root = environ.get( "LUPIN_ROOT", "" )
    if lupin_root:
        return Path( lupin_root ).name.lower()
    return Path.cwd().name.lower()


def discover_active_sessions(
    stale_threshold_seconds = 43200,
    environ                 = None,
    _find                   = find_active_voice_persona_sessions,
    _read_bridge            = _read_bridge,
):
    """
    Discover the ACTIVE sessions the drain should back-fill.

    Reuses the voice-persona occupancy scanner (find_active_voice_persona_sessions
    — same PID + mtime staleness filters used by the persona pool) so the drain
    operates on exactly the set of sessions considered live, then re-reads each
    bridge for its transcript_path + cwd.

    Requires:
        - stale_threshold_seconds is a positive int
        - environ is a Mapping or None

    Ensures:
        - Returns a list of session dicts:
          { session_id, transcript_path, persona_lower, project }
        - A bridge that fails to re-read is SKIPPED (degrade-safe)
        - A bridge with no transcript_path is SKIPPED (nothing to replay)
        - A bridge whose cwd is malformed (project resolution raises) is SKIPPED
          (this loop is the module's never-raises boundary)
        - NEVER raises
    """
    sessions = [ ]
    for path, sid, persona in _find( stale_threshold_seconds ):
        data = _read_bridge( path )
        if data is None:
            continue
        transcript_path = data.get( "transcript_path" )
        if not transcript_path:
            continue
        raw_name      = ( persona.get( "name" ) or "unknown" ) if isinstance( persona, dict ) else "unknown"
        persona_lower = canonical_persona_key( raw_name ) or "unknown"
        try:
            project = _project_from_cwd( data.get( "cwd" ), environ=environ )
        except ( OSError, ValueError, RuntimeError ):
            continue                                          # malformed cwd → skip this session
        sessions.append( {
            "session_id"      : sid,
            "transcript_path" : transcript_path,
            "persona_lower"   : persona_lower,
            "project"         : project,
        } )
    return sessions


def _owed_harness_ids( transcript_path, _replay ):
    """
    Replay one transcript and return its owed harness-task ids (in_progress|pending).

    Requires:
        - transcript_path is a path-like / string / None
        - _replay is replay_task_state (injectable)

    Ensures:
        - Returns a list of harness_id strings whose LATEST status is owed
        - NEVER raises (replay_task_state never raises)
    """
    state = _replay( transcript_path )
    return [ hid for hid, status in state.items() if status in OWED_STATUSES ]


def drain_owed_items_for_session(
    settings,
    api_key,
    session,
    base_dir            = None,
    environ             = None,
    apply               = True,
    _replay             = replay_task_state,
    _subjects           = replay_task_subjects,
    _current_generation = task_map.current_generation,
    _query              = client.query_by_correlation_key,
    _create             = client.create_task,
):
    """
    Idempotently back-fill ONE session's owed native Task* items into the store.

    Requires:
        - settings is the load_task_store_settings() dict (api_base_url, timeout)
        - api_key is a string (may be empty — server 401s it)
        - session is a discover_active_sessions() dict
        - apply=True performs creates; apply=False is a DRY-RUN (probe only —
          counts what WOULD be created without writing)

    Ensures:
        - For every owed harness id: build its correlation_key, probe the store;
          a hit (count>0) is SKIPPED (idempotent — never duplicates a
          manager-mirrored or prior-drained row); a miss is CREATED (apply=True)
          or counted as `would_create` (apply=False)
        - Returns a result dict:
          { session_id, persona_lower, project, generation, owed, created,
            skipped, would_create, failed }
        - A store-probe / create transport failure increments `failed` and the
          item is left for a later pass (never a half-written fabrication)
        - NEVER raises
    """
    session_id    = session[ "session_id" ]
    transcript    = session[ "transcript_path" ]
    persona_lower = session[ "persona_lower" ]
    project       = session[ "project" ]

    generation = _current_generation( session_id, base_dir )
    actor      = f"{persona_lower} {session_id[:8]}"
    subjects   = _subjects( transcript )
    owed_ids   = _owed_harness_ids( transcript, _replay )

    created = skipped = would_create = failed = 0
    for harness_id in owed_ids:
        ck = build_correlation_key( session_id, generation, harness_id )
        ok, _status, body = _query( settings, api_key, ck )
        if not ok:
            failed += 1
            continue
        if body.get( "count", 0 ) > 0:
            skipped += 1                       # already present — idempotent
            continue
        if not apply:
            would_create += 1                  # dry-run: count, do not write
            continue
        payload = {
            "item_class"          : "task",
            "title"               : subjects.get( harness_id ) or DRAIN_TITLE_FALLBACK,
            "body"                : DRAIN_BODY,
            "project"             : project,
            "created_by"          : actor,
            "owner_persona"       : persona_lower,
            "accountable_manager" : persona_lower,
            "authority"           : "standing",
            "correlation_key"     : ck,
        }
        ok, _status, _body = _create( settings, api_key, payload )
        if ok:
            created += 1
        else:
            failed += 1

    return {
        "session_id"   : session_id,
        "persona_lower": persona_lower,
        "project"      : project,
        "generation"   : generation,
        "owed"         : len( owed_ids ),
        "created"      : created,
        "skipped"      : skipped,
        "would_create" : would_create,
        "failed"       : failed,
    }


def check_session_parity(
    settings,
    api_key,
    session,
    base_dir            = None,
    _replay             = replay_task_state,
    _current_generation = task_map.current_generation,
    _query              = client.query_by_correlation_key,
):
    """
    Per-session count-parity: store owed-count == transcript owed-count.

    Counts the store-owed side PER SESSION by probing each owed correlation_key
    for a live owed-status item — deliberately NOT via query_owed, whose
    (owner_persona, project) filter would AGGREGATE across every session that
    ever held the same persona. The correlation_key is session+generation
    scoped, so this is the true per-session count.

    Requires:
        - settings / api_key / session as in drain_owed_items_for_session

    Ensures:
        - Returns { session_id, transcript_owed, store_owed, query_ok, parity }
          where store_owed counts owed correlation_keys whose probe returned an
          item in an owed store status, query_ok is True iff EVERY probe
          answered cleanly, and parity is ( query_ok AND store_owed ==
          transcript_owed )
        - A failed probe sets query_ok False (parity cannot be asserted on an
          unreachable store) — never a false-green
        - NEVER raises
    """
    session_id = session[ "session_id" ]
    transcript = session[ "transcript_path" ]

    generation = _current_generation( session_id, base_dir )
    owed_ids   = _owed_harness_ids( transcript, _replay )

    store_owed = 0
    query_ok   = True
    for harness_id in owed_ids:
        ck = build_correlation_key( session_id, generation, harness_id )
        ok, _status, body = _query( settings, api_key, ck )
        if not ok:
            query_ok = False
            continue
        tasks = body.get( "tasks" ) or [ ]
        if any( t.get( "status" ) in STORE_OWED_STATUSES for t in tasks ):
            store_owed += 1

    return {
        "session_id"      : session_id,
        "transcript_owed" : len( owed_ids ),
        "store_owed"      : store_owed,
        "query_ok"        : query_ok,
        "parity"          : query_ok and store_owed == len( owed_ids ),
    }


def run_drain(
    apply                   = False,
    stale_threshold_seconds = 43200,
    base_dir                = None,
    environ                 = None,
    _load_settings          = load_task_store_settings,
    _read_api_key           = client.read_api_key,
    _discover               = discover_active_sessions,
    _drain                  = drain_owed_items_for_session,
    _parity                 = check_session_parity,
):
    """
    Orchestrate the full drain: discover -> drain each -> parity each -> report.

    Requires:
        - apply=False (default) is a DRY-RUN preview; apply=True writes

    Ensures:
        - Returns a report dict:
          { apply, sessions, totals, drains: [...], parities: [...] }
          where totals aggregates owed/created/skipped/would_create/failed and
          counts how many sessions reached parity
        - One session's failure never aborts the pass (degrade-safe per session)
        - NEVER raises
    """
    settings = _load_settings()
    api_key  = _read_api_key( environ )
    sessions = _discover( stale_threshold_seconds=stale_threshold_seconds, environ=environ )

    drains    = [ ]
    parities  = [ ]
    totals    = { "owed": 0, "created": 0, "skipped": 0, "would_create": 0, "failed": 0, "parity_ok": 0 }
    for session in sessions:
        d = _drain( settings, api_key, session, base_dir=base_dir, environ=environ, apply=apply )
        p = _parity( settings, api_key, session, base_dir=base_dir )
        drains.append( d )
        parities.append( p )
        for k in ( "owed", "created", "skipped", "would_create", "failed" ):
            totals[ k ] += d[ k ]
        if p[ "parity" ]:
            totals[ "parity_ok" ] += 1

    return {
        "apply"    : apply,
        "sessions" : len( sessions ),
        "totals"   : totals,
        "drains"   : drains,
        "parities" : parities,
    }


def format_report( report ):
    """
    Render a run_drain report as a compact human-readable table string.

    Requires:
        - report is a run_drain() result dict

    Ensures:
        - Returns a multi-line string (header + one row per session + totals)
        - NEVER raises
    """
    mode  = "APPLY" if report[ "apply" ] else "DRY-RUN"
    lines = [ f"Spine cutover drain [{mode}] — {report['sessions']} active session(s)" ]
    lines.append( f"{'session':10} {'persona':12} {'owed':>5} {'created':>8} {'skipped':>8} {'would':>6} {'failed':>7} {'parity':>7}" )
    by_sid = { p[ "session_id" ]: p for p in report[ "parities" ] }
    for d in report[ "drains" ]:
        p = by_sid.get( d[ "session_id" ], { } )
        lines.append(
            f"{d['session_id'][:10]:10} {d['persona_lower'][:12]:12} {d['owed']:>5} "
            f"{d['created']:>8} {d['skipped']:>8} {d['would_create']:>6} {d['failed']:>7} "
            f"{('OK' if p.get( 'parity' ) else 'NO'):>7}"
        )
    t = report[ "totals" ]
    lines.append(
        f"TOTAL: owed={t['owed']} created={t['created']} skipped={t['skipped']} "
        f"would_create={t['would_create']} failed={t['failed']} "
        f"parity_ok={t['parity_ok']}/{report['sessions']}"
    )
    return "\n".join( lines )


def main( argv=None ):
    """
    CLI entry point: run the drain and print the report.

    Requires:
        - argv is the arg list (None -> sys.argv[1:]); `--apply` performs writes,
          otherwise a dry-run preview is printed

    Ensures:
        - Prints the formatted report to stdout
        - Returns 0 on a fully-parity-green apply/dry-run, 1 otherwise (so the
          script is usable as a cutover gate in a shell)
    """
    import sys
    if argv is None:
        argv = sys.argv[ 1: ]
    apply  = "--apply" in argv
    report = run_drain( apply=apply )
    print( format_report( report ) )
    all_green = report[ "totals" ][ "parity_ok" ] == report[ "sessions" ] and report[ "totals" ][ "failed" ] == 0
    return 0 if all_green else 1


if __name__ == "__main__":   # pragma: no cover - manual CLI entrypoint
    import sys as _sys
    # Bootstrap: this module runs BEFORE cosa/lupin_cli are importable when
    # invoked directly. Prefer `python -m lupin_cli.claude_code.hooks.lib.task_store_drain`
    # (PYTHONPATH=src), which makes the package imports above resolve.
    raise SystemExit( main( _sys.argv[ 1: ] ) )
