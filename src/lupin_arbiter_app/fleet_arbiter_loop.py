#!/usr/bin/env python3
"""
Standing fleet-stall arbiter loop for the :8001 lupin-arbiter-app service.

Reuses the `ArbiterConsumerJob` unchanged, so its invariants carry over. It never
auto-assigns, its observer is one-way and additive, and routing comes from lineage.
This module only wires the job in and supervises it.

  - Recycle wrapper (FleetArbiterLoop): the job's `do_all()` returns after the 12h
    `max_duration` cap. A host-side thread that ran it once would then sit dead
    while uvicorn keeps serving. systemd's Restart=always catches process exit,
    not a clean thread return. So FleetArbiterLoop launches a fresh job after
    every clean cap-exit. Runs are sequential, so exactly one job runs at a time.
    That is the :8001-side single instance. The in-process arbiter is a separate
    mechanism, switched off by its own flag, and the two never run together.

  - Out-of-band store: the job's snapshot_sink is overridden to write the
    :8001-local store section "fleet_arbiter", not the :7999 singleton. The
    detection path never touches :7999 (events_tail, who, manager_resolver and
    the sink all read the filesystem).

  - Escalation: notify_fn always posts to the durable `fleet-escalations` commons
    topic and swallows and logs any failure. It also makes a best-effort call to
    an injected, swallowed live_notify_fn. That is the only place a :7999 notify
    may occur. It happens on the escalation path only, never per poll. The
    default is a no-op, so escalation never blocks detection.

  - Warm-up: each fresh job's notify_fn suppresses escalations while
    (now - job_start) < start_period_seconds. The window is per job start, so a
    cold boot, restart or recycle never fires a false escalation.

All seams are injectable (job_factory, gateway, store, clock, log_fn,
live_notify_fn). The recycle, escalation and warm-up logic are therefore fully
unit-tested with fakes. Only the literal external construction
(gateway.from_environment) is excluded from coverage, in app.create_production_app.
"""
import datetime
import json
import os
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional

from lupin_arbiter_app.health_watcher import SystemClock
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, _default_owed_work_fn, _default_known_owners_fn, _default_dm_activity_fn, _default_operator_gates_fn
from cosa.agents.heartbeat_arbiter.operator_gate_routing import DEFAULT_DIGEST_CADENCE_SECONDS
# 6929f4ac outward-twin backstop (§9.2): the per-session hold reader — defaulted
# real here so the :8001 service actually resurfaces a dark session's aged user-gate
# to Rick (without this wiring the seam stays None → the backstop is decorative).
#
# row 011f1f90 (2026-08-06): the default was plain read_hold, which resolves
# fleet_data_root ONLY — so a hold leaked to a repo root was invisible to this VETO
# and the parked session got poked forever. It is now read_hold_via_bridge, which
# sources the session's OWN cwd from its bridge and finds a repo-root hold in ANY
# project. The factory wraps it with the arbiter log_fn (below) so the cwd=None
# fallback is visible, not a silent return to the blind path.
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import read_hold_via_bridge
# The hold sweep is REPORT + RECLAIM as of 2026-07-26 (row 11461241, Rick's direct
# ruling — "wire it: the arbiter calls the janitor"). It was report-only from
# 2026-07-16 while hold files still carried untriaged hand-written memento cargo.
#
# WHAT CHANGED IS THE TRIAGE, NOT THE APPETITE FOR RISK. All five preconditions were
# met and re-verified by measurement before this landed:
#   · the cargo guard is STRUCTURAL — classify_hold_file( allow_cargo_deletion=False )
#     is the DEFAULT, and cargo_bearing ⇒ VERDICT_KEEP. No call site reaches deletion
#     by omission, which is where A0 (this milestone's origin bug) lived.
#   · all 20 cargo-bearing files carry a content-verified rescued record (55/55 keys
#     verbatim), so nothing reapable here is the only copy of anything.
#   · the two-anchor guard is live: prune needs BOTH clocks to agree.
# The reporter is STILL imported and STILL runs — it is the evidence half, and it is
# what makes `deleted` auditable rather than merely asserted.
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import report_hold_files as _default_hold_reporter
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import prune_stale_hold_files as _default_hold_deleter
# 8758d0b1 — the SECOND runtime-state family. Same traversal, its own classifier:
# an HWM file carries no held_at / ttl_seconds / session_id, so the hold classifier
# would keep every one of them forever and report a clean green.
from lupin_cli.claude_code.hooks.lib.dm_inbox_hwm_janitor import report_hwm_files as _default_hwm_reporter
from lupin_cli.claude_code.hooks.lib.dm_inbox_hwm_janitor import sweep_and_reclaim_hwm_files as _default_hwm_deleter
# The three milder bookmark families (ask-answer / task-store-map / heartbeat-acked),
# row bd5c27e1 — the same live-set-gated mechanism as the dm-inbox sweep above.
from lupin_cli.claude_code.hooks.lib.bookmark_janitor import report_bookmark_files as _default_bookmark_reporter
from lupin_cli.claude_code.hooks.lib.bookmark_janitor import sweep_and_reclaim_bookmark_files as _default_bookmark_deleter
from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_voice_persona_sessions as _find_active_voice_persona_sessions
from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_sessions as _find_active_sessions
from lupin_mcp.persona_normalization import canonical_persona_key
from cosa.agents.heartbeat_arbiter.arbiter_journal import make_log_fn


ESCALATION_TOPIC = "fleet-escalations"


def _default_manager_bridge_mtimes( find_fn=None ):
    """
    Map each live persona to the freshest mtime of its bridge file.

    The real reader behind the manager-stale bridge-mtime veto on the :8001 deploy.

    Requires:
        - find_fn is None (the real persona'd bridge scan) or
          () -> iterable of ( path, session_id, persona_dict )

    Ensures:
        - returns { canonical_persona_key : max bridge mtime } across live persona'd
          bridges; a persona with several live sessions keeps the freshest mtime
        - keyed by persona, not session id, so a re-spun twin's fresh bridge (a new
          session id) still vetoes the superseded row's stale poke
        - uses `find_active_voice_persona_sessions` (require_persona=True), which is right here:
          a persona-less session has no key, contributes nothing and cannot veto
          anything, unlike the liveness set where it must count as alive
        - skips bridges with no persona name or an unreadable mtime; never raises here
          (the arbiter's swallow-safe _read_manager_bridge_mtimes wraps it anyway)

    This function is not excluded from coverage. It is reachable and cheap, and a
    coverage exclusion would hide it from the instrument.
    """
    if find_fn is None:
        find_fn = _find_active_voice_persona_sessions
    result = { }
    for path, _sid, persona in find_fn():
        # ONE key guard, not two. `canonical_persona_key` DECLARES `Requires: name is a
        # string or None` and GUARANTEES `None / non-string / empty / whitespace-only ->
        # ""` — so a missing/blank/unkeyable name arrives here as the falsy sentinel and is
        # skipped below. A preceding `if not name: continue` was REDUNDANT BY CONTRACT
        # (deleted 2026-07-16): it could never change the output, which made it an
        # equivalent mutant — unkillable by any test that could ever be written, i.e. a
        # guard that cannot fail, wearing safety's costume. That is the shape this module
        # exists to delete, so it does not get to live here.
        key = canonical_persona_key( ( persona or { } ).get( "name" ) )
        if not key:
            continue                               # no name / unkeyable → no key → cannot veto anything
        try:
            mtime = os.path.getmtime( path )
        except OSError:
            continue                               # unreadable bridge → contributes nothing
        if key not in result or mtime > result[ key ]:
            result[ key ] = mtime
    return result


# Q1 RULING (Rick, 2026-07-16): "Config + host-path translation + parent scan."
# The registered-project config is the known-good list; the parent scan is the
# SAFETY NET for roots the registry does not enumerate (verified: google/harvey-labs
# holds a hold and has zero config mentions). Depth 2 is what that costs — the
# unregistered repos live one level under a non-repo grouping dir (google/).
_HOLD_ROOT_SCAN_MAX_DEPTH = 2


def _registry_container_paths( config_mgr ):
    """
    Return the `external repo <name> path` values from the registered-project config.

    Requires:
        - config_mgr exposes .get( key, default=..., return_type=... )

    Ensures:
        - returns the configured path strings in `external repos` order, container-side
          and untranslated, exactly as configured
        - reads the raw keys and never reuses `_scope_registry.build_scope_registry`,
          which drops any scope whose path does not exist on disk. Every one of these is
          a container path, so on the host that helper returns an empty registry that
          looks like a clean answer
        - a name with no path key, or a blank one, drops out; never raises
    """
    names = config_mgr.get( "external repos", default=[ ], return_type="list-string" )
    paths = [ ]
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        value = config_mgr.get( f"external repo {name} path", default=None )
        if value is None:
            continue
        path = str( value ).strip()
        if path:
            paths.append( path )
    return paths


def _derive_container_host_prefix( container_paths, host_root ):
    """
    Derive the container-to-host path prefix from one verified anchor pair.

    Requires:
        - container_paths is an iterable of configured path strings
        - host_root is an absolute host path to this project

    Ensures:
        - returns ( container_prefix, host_prefix ) from the first entry whose
          trailing component matches host_root's, or None when no anchor exists
        - None means nothing is translated and every config root reports unreachable,
          which is loudly wrong and never silently empty
        - the anchor is the config entry for this project set against
          `cu.get_project_root()`; stripping the shared trailing component gives the
          mapping, so it follows if the projects tree moves or is mounted elsewhere
        - the mapping reconstructs the docker-compose bind-mount of the projects tree to
          /var/external-projects; the config paths are container-side and do not
          exist on the host where the arbiter runs; reusing them unchanged reached none
          of the 45 holds measured
        - the trailing-component match is a hypothesis, not proof; every translated
          path is confirmed to be a real directory in `_translate_container_root`, and
          an unconfirmed one passes through untranslated so it shows as unreachable
    """
    host = Path( host_root )
    for raw in container_paths:
        container = PurePosixPath( str( raw ) )
        if container.name != host.name:
            continue
        container_prefix = str( container.parent )
        if container_prefix in ( "", ".", "/" ):
            continue                                   # no prefix to strip → not an anchor
        return ( container_prefix, str( host.parent ) )
    return None


def _translate_container_root( raw, prefix_pair ):
    """
    Translate one configured container path to its host path, and confirm it exists.

    Requires:
        - raw is a configured path string; prefix_pair is ( container_prefix,
          host_prefix ) or None

    Ensures:
        - returns the host path only when the translation names a real directory
        - returns None when there is no anchor, the path is outside the mapped
          prefix, or the translated path is not a directory
        - the caller passes a None-translated root through untranslated, so it is
          reported as unreachable rather than silently dropped
        - never raises
    """
    if prefix_pair is None:
        return None
    container_prefix, host_prefix = prefix_pair
    path = str( raw )
    stem = container_prefix.rstrip( "/" )
    if path != stem and not path.startswith( stem + "/" ):
        return None                                    # outside the mapped mount
    relative  = path[ len( stem ) : ].lstrip( "/" )
    candidate = Path( host_prefix ) / relative if relative else Path( host_prefix )
    try:
        if candidate.is_dir():
            return str( candidate )
    except OSError:
        pass
    return None


def _is_repo_root( path ):
    """
    Is this directory a repository root (does it hold a `.git`)?

    Requires:
        - path is a Path

    Ensures:
        - returns True iff `<path>/.git` exists; an OSError yields False
    """
    try:
        return ( path / ".git" ).exists()
    except OSError:
        return False


def _scan_parent_for_repo_roots( parent, max_depth=_HOLD_ROOT_SCAN_MAX_DEPTH ):
    """
    Find repo roots the registry does not list, by scanning the projects parent.

    Requires:
        - parent is a path-like directory; max_depth is a positive int

    Ensures:
        - returns the repo-root paths found within max_depth of parent
        - follows no symlinked directories; a per-directory OSError skips that
          directory only; never raises
        - descent stops at a repo, because a repo is a root and the hold sweep recurses
          inside it on its own; walking in here would duplicate that work
        - exists because a registry cannot report what was never written into it:
          `google/harvey-labs` is a git repo with a hold and no mention in the config
        - the default depth of 2 comes from that case: unregistered repos sit one level
          under a non-repo grouping directory (`google/`)
    """
    found = [ ]
    stack = [ ( Path( parent ), 0 ) ]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list( os.scandir( current ) )
        except OSError:
            continue                                   # unreadable dir → skip it, keep scanning
        for entry in entries:
            try:
                is_dir = entry.is_dir( follow_symlinks=False )
            except OSError:
                continue
            if not is_dir:
                continue
            child = Path( entry.path )
            if _is_repo_root( child ):
                found.append( str( child ) )           # a repo IS a root — do not descend
            elif depth + 1 < max_depth:
                stack.append( ( child, depth + 1 ) )
    return found


def _compute_hold_roots( config_mgr, host_root, scan_fn=None ):
    """
    Return the hold-sweep root list: config roots, host translation and parent scan, unioned.

    Requires:
        - config_mgr exposes .get(...); host_root is this project's host path
        - scan_fn is None (the real parent scan) or () -> iterable of root paths

    Ensures:
        - returns the union: translated config roots, then scanned repo roots, with
          host_root always present, deduped on realpath, in a stable order
          (config order first, then scan order)
        - the scan is a safety net, not a replacement: the config names repos the
          scan's depth would miss, and the scan catches repos the config never knew
        - dedupes on resolved realpath, not on `git --git-common-dir`, which identifies
          a repo and not a tree. A worktree and its main repo share one while holding
          different files, so it would drop a worktree root. It is also a relative path
          (".git") that would collide every repo into one identity
        - a config root that cannot be translated or confirmed is emitted untranslated,
          so the sweep reports it in roots_unreachable and the gap stays a number
          instead of a silence (invariant: never silently skipped)
        - never raises
    """
    if scan_fn is None:
        scan_fn = lambda: _scan_parent_for_repo_roots( Path( host_root ).parent )

    container_paths = _registry_container_paths( config_mgr )
    prefix_pair     = _derive_container_host_prefix( container_paths, host_root )

    candidates = [ str( host_root ) ]
    for raw in container_paths:
        translated = _translate_container_root( raw, prefix_pair )
        candidates.append( translated if translated is not None else str( raw ) )
    candidates.extend( str( root ) for root in scan_fn() )
    # THE FLEET DATA ROOT — row 8758d0b1 / f56fc63b. Runtime state now lives OUTSIDE
    # every repo, and the three sources above all yield REPOS: the parent scan
    # appends only directories containing `.git`, so a data dir is invisible to it
    # BY CONSTRUCTION. Measured: seed a parent with `a-repo/.git` + `lupin-data/`
    # and the scan returns ['a-repo'].
    #
    # ⚠️ Omitting this does NOT fail loudly. `roots_swept` stays non-empty because
    # the repos still exist, so the no-roots alarm never fires and the report reads
    # `roots N · files 0 · prunable 0` — indistinguishable from a clean fleet, while
    # BOTH janitors silently stop reclaiming (`enable_hold_deletion` defaults True).
    # That is the smallest line here with the largest blast radius.
    #
    # APPENDED LAST, deliberately: the documented order is "config order first, then
    # scan order", and the first draft of this inserted at index 1 and broke it. The
    # ordering test caught it — that contract is load-bearing for readers comparing
    # a report against a config.
    try:
        from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
        candidates.append( str( fleet_data_root( host_root ) ) )
    except Exception:
        pass                                           # never let root-derivation kill the sweep

    roots, seen = [ ], set()
    for candidate in candidates:
        identity = os.path.realpath( candidate )
        if identity in seen:
            continue                                   # same tree reached twice → sweep once
        seen.add( identity )
        roots.append( candidate )
    return roots


def _default_hold_roots():
    """
    Return the hold-sweep root list from the real config and host root.

    Ensures:
        - returns the unioned config and scan root list (see `_compute_hold_roots`)
        - is production wiring only; every decision lives in `_compute_hold_roots`
          behind injected seams
        - stays thin and is not excluded from coverage: it is reachable and runs in the
          test suite, and an IO-boundary label is not a coverage exemption under the
          100% mandate
    """
    import cosa.utils.util as cu
    from cosa.config.configuration_manager import ConfigurationManager

    return _compute_hold_roots( ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ),
                                cu.get_project_root() )


def janitor_repo_roots( config_mgr, host_root=None ):
    """
    Return the repos the worktree janitor sweeps, read from the INI.

    Requires:
        - config_mgr exposes .get( key, default=, return_type= )
        - host_root is this project's host path, or None (then cu.get_project_root())

    Ensures:
        - returns { "roots": [ host path, ... ], "unresolved": [ name, ... ] }
        - `arbiter worktree janitor repos` names repos by their `external repo <name>`
          entry, so the fleet repo list lives in one registry
        - those paths are container-side, so each is translated to the host with the
          anchor the hold sweep derives; an untranslated path names nothing on the host
        - roots follow the configured order, deduped on realpath
        - a name with no path entry, or whose translation is not a real directory, is
          listed in unresolved and never guessed at
        - a blank or absent key yields roots == [ host_root ], the single-repo behaviour
          from before the repo list existed
        - never raises
    """
    if host_root is None:
        import cosa.utils.util as cu
        host_root = cu.get_project_root()
    try:
        names = config_mgr.get( "arbiter worktree janitor repos", default=[ ], return_type="list-string" ) or [ ]
    except Exception:
        names = [ ]
    names = [ n.strip() for n in names if n and n.strip() ]
    if not names:
        return { "roots": [ str( host_root ) ], "unresolved": [ ] }

    prefix_pair = _derive_container_host_prefix( _registry_container_paths( config_mgr ), host_root )
    roots, unresolved, seen = [ ], [ ], set()
    for name in names:
        raw  = config_mgr.get( f"external repo {name} path", default=None )
        host = _translate_container_root( str( raw ).strip(), prefix_pair ) if raw else None
        if host is None:
            unresolved.append( name )
            continue
        identity = os.path.realpath( host )
        if identity not in seen:
            seen.add( identity )
            roots.append( host )
    return { "roots": roots, "unresolved": unresolved }


def _default_live_session_ids( find_fn=None ):
    """
    Return the live session ids for the hold sweep, persona-less sessions included.

    Requires:
        - find_fn is None (the real bridge scan) or
          ( require_persona=... ) -> iterable of ( path, session_id, persona )

    Ensures:
        - returns the set of live session ids, including persona-less sessions
        - uses require_persona=False because `find_active_voice_persona_sessions`
          delegates to require_persona=True. A live persona-less session (one booted
          when the persona pool was exhausted, or whose allocation failed) would be
          absent from that set, read as positive-dead and have its hold reaped at TTL
          with no grace, which breaks the bias to keep
        - degrade-safe: any scan failure yields None (no authoritative set) rather
          than a partial one. A half-enumerated live set is worse than none, since
          absence from it is what licenses the no-grace prune
        - is not excluded from coverage: it is reachable and cheap, and a bias-to-keep
          guard is the last thing that should go untested; the `find_fn` seam makes the
          degrade-safe path testable without patching a module global
    """
    if find_fn is None:
        find_fn = _find_active_sessions
    try:
        return { sid for _path, sid, _persona in find_fn( require_persona=False ) }
    except Exception:
        return None


# Item A (2026.06.11 receipts design §2.3): the line shape has ONE owner —
# arbiter_journal.make_log_fn (ts + ts_local).
_default_log_fn = make_log_fn( loop="fleet_arbiter" )


# ── escalation output sink (ruling A) ───────────────────────────────────────

def make_escalation_notify_fn(
    gateway       : Any,
    *,
    live_notify_fn : Optional[ Callable[ [ str ], dict ] ] = None,
    log_fn         : Optional[ Callable ]                  = None,
    topic          : str                                   = ESCALATION_TOPIC,
) -> Callable[ [ str ], list ]:
    """
    Build the escalation notify_fn: a durable post plus a best-effort live push.

    It returns the outcome of each channel. Swallowing every failure into one log
    line would let `arbiter_outreach` claim the operator was reached when no
    channel had delivered.

    Ensures:
        - always posts `message` to the durable commons `topic` via the bridge-less
          gateway; returns [{channel:"durable", outcome:"posted"}] on success, or
          outcome "post_error" (+ detail) on failure; a failure is still logged and
          non-fatal, since the primary channel must not kill the loop
        - if live_notify_fn is provided, appends its live-channel outcome dict
          (a blow-up degrades to outcome "http_error", logged and never raised);
          if absent, appends {channel:"live", outcome:"disabled"}, so a disabled
          live hop is a visible per-outreach fact and not a silent gap
        - never raises; the caller journals one arbiter_outreach_result per
          returned outcome under the outreach_id
    """
    log_fn = log_fn if log_fn is not None else _default_log_fn

    def notify_fn( message: str ) -> list:
        results = [ ]
        try:
            gateway.post( topic, message )
            results.append( { "channel": "durable", "outcome": "posted" } )
        except Exception as e:                       # durable post degrade-safe (note 3)
            log_fn( "escalation_post_error", error=str( e ) )
            results.append( { "channel": "durable", "outcome": "post_error",
                              "detail": str( e )[ :160 ] } )
        if live_notify_fn is not None:
            try:
                results.append( live_notify_fn( message ) )
            except Exception as e:                   # best-effort live delivery, degraded to an outcome
                log_fn( "escalation_live_notify_error", error=str( e ) )
                results.append( { "channel": "live", "outcome": "http_error",
                                  "detail": str( e )[ :160 ] } )
        else:
            results.append( { "channel": "live", "outcome": "disabled" } )
        return results

    return notify_fn


# ── warm-up suppressor (ruling B) ───────────────────────────────────────────

def make_warmup_notify_fn(
    inner                : Callable[ [ str ], list ],
    job_started_at       : datetime.datetime,
    start_period_seconds : int,
    clock                : Any,
    log_fn               : Callable,
) -> Callable[ [ str ], list ]:
    """
    Wrap an escalation notify_fn so it suppresses escalations during one job's warm-up.

    The window is keyed on that job's start time. The wrapper returns outcomes, so the
    caller can journal what happened.

    Ensures:
        - while (clock.now() - job_started_at) < start_period_seconds, suppress:
          log `escalation_suppressed_warmup`, do not call inner, and return
          [{channel:"all", outcome:"suppressed_warmup"}]; returning None here would
          let the caller journal the operator as reached anyway
        - at or after the window, pass through to inner and return its outcomes
        - never raises
    """
    def notify_fn( message: str ) -> list:
        if ( clock.now() - job_started_at ).total_seconds() < start_period_seconds:
            log_fn( "escalation_suppressed_warmup", message=message )
            return [ { "channel": "all", "outcome": "suppressed_warmup" } ]
        return inner( message )

    return notify_fn


# ── worktree janitor (row 033538f6) ──────────────────────────────────────────

def make_refusal_notify_fn(
    gateway        : Any,
    *,
    live_notify_fn : Optional[ Callable ] = None,
    log_fn         : Optional[ Callable ] = None,
    topic          : str                  = ESCALATION_TOPIC,
) -> Callable[ [ str, str ], list ]:
    """
    Build the janitor's refusal notify: the escalation channel's shape, plus an abstract.

    Ensures:
        - returns notify( message, abstract ) -> [ outcome dicts ], with the same outcome
          vocabulary as make_escalation_notify_fn (durable posted | post_error; live
          outcome | http_error | disabled)
        - posts message and abstract to the durable topic and hands the abstract to the
          live push as the card's detail, because a refusal notice without its per-tree
          blockers says something is wrong but not what (make_escalation_notify_fn
          carries a message only)
        - never raises; every failure is an outcome value and a log line
    """
    log_fn = log_fn if log_fn is not None else _default_log_fn

    def notify( message: str, abstract: str ) -> list:
        results = [ ]
        try:
            gateway.post( topic, f"{message}\n\n{abstract}" )
            results.append( { "channel": "durable", "outcome": "posted" } )
        except Exception as e:
            log_fn( "worktree_refusal_post_error", error=str( e ) )
            results.append( { "channel": "durable", "outcome": "post_error", "detail": str( e )[ :160 ] } )
        if live_notify_fn is not None:
            try:
                results.append( live_notify_fn( message, abstract=abstract ) )
            except Exception as e:
                log_fn( "worktree_refusal_live_notify_error", error=str( e ) )
                results.append( { "channel": "live", "outcome": "http_error", "detail": str( e )[ :160 ] } )
        else:
            results.append( { "channel": "live", "outcome": "disabled" } )
        return results

    return notify


def make_worktree_janitor_fn(
    *,
    sandbox_root   : str,
    age_hours      : float,
    ledger_path    : str,
    notify_fn      : Callable[ [ str, str ], list ],
    log_fn         : Callable,
    reconcile_fn   : Optional[ Callable ] = None,
    report_fn      : Optional[ Callable ] = None,
    repo_roots     : Optional[ list ]     = None,
    straggler_fn   : Optional[ Callable[ [ dict ], dict ] ] = None,
    branch_sweep_fn : Optional[ Callable ] = None,
) -> Callable[ [ ], dict ]:
    """
    Build the per-poll janitor the :8001 job calls, covering every fleet repo.

    Ensures:
        - returns janitor() -> one reconcile result per poll: the swept / skipped /
          errors / branches_deleted / branches_kept lists of every repo concatenated,
          plus `repos` ([ {root, swept} ]) and `refusals` (report_refusals' summary)
        - the job's `worktree_janitor_fn` seam must be given this result; when it is
          not, the seam stays None and `worktrees_swept` reads 0 on every poll
        - repo_roots None or empty gives one reconcile at the reconciler's own
          default root (the single-repo behaviour)
        - one repo raising is recorded in errors and the others are still swept
        - a poll that deleted or kept a branch logs `worktree_janitor_branches`
          naming both lists, which reports every unmerged branch the janitor kept
        - a reporting failure never discards the reconcile result, and is logged
        - straggler_fn, when given, is called with the merged reconcile result after
          the refusal report; its summary lands in `stragglers`, and a failure is
          logged as `worktree_straggler_error`. None means inert
        - branch_sweep_fn, when given, runs once per repo after that repo's reconcile,
          as branch_sweep_fn( project_root=root ); its deletions join
          `branches_deleted` / `branches_kept` (so the existing
          `worktree_janitor_branches` log reports them) and its error lands in
          `errors`. None means inert
        - never raises past the job's own swallow-safe seam (which also guards it)
    """
    if reconcile_fn is None:
        from cosa.agents.shared.worktree_reaper import reconcile_worktrees as reconcile_fn
    if report_fn is None:
        from cosa.agents.shared.worktree_refusal_ledger import report_refusals as report_fn
    roots = list( repo_roots ) if repo_roots else [ None ]

    def janitor() -> dict:
        result = { "swept": [ ], "skipped": [ ], "errors": [ ], "branches_deleted": [ ],
                   "branches_kept": [ ], "repos": [ ] }
        for root in roots:
            try:
                one = reconcile_fn( project_root=root, sandbox_root=sandbox_root, age_threshold_hours=age_hours )
            except Exception as e:
                result[ "errors" ].append( f"{root}: janitor raised: {e}" )
                continue
            # Row aec2319f: an archived branch gets a row, and the row needs its repo.
            for kept in one.get( "branches_kept" ) or [ ]:
                kept.setdefault( "repo_root", root )
            for key in ( "swept", "skipped", "errors", "branches_deleted", "branches_kept" ):
                result[ key ].extend( one.get( key ) or [ ] )
            result[ "repos" ].append( { "root": root, "swept": len( one.get( "swept" ) or [ ] ) } )
            if branch_sweep_fn is not None:
                try:
                    bs = branch_sweep_fn( project_root=root )
                    result[ "branches_deleted" ].extend( bs.get( "deleted" ) or [ ] )
                    for kept in bs.get( "kept" ) or [ ]:
                        kept.setdefault( "repo_root", root )
                    result[ "branches_kept" ].extend( bs.get( "kept" ) or [ ] )
                    if bs.get( "error" ): result[ "errors" ].append( f"{root}: {bs[ 'error' ]}" )
                except Exception as e:
                    result[ "errors" ].append( f"{root}: branch sweep raised: {e}" )
        if result[ "branches_deleted" ] or result[ "branches_kept" ]:
            log_fn( "worktree_janitor_branches",
                    deleted = [ o.get( "branch" ) for o in result[ "branches_deleted" ] ],
                    kept    = [ { "branch": o.get( "branch" ), "reason": o.get( "kept_reason" ),
                                  "commits_ahead": o.get( "commits_ahead" ),
                                  # Row aec2319f: an unmerged branch is archived, not kept in
                                  # the list. Where it went, and whether its work had landed.
                                  "archive_ref": o.get( "archive_ref" ), "landed": o.get( "landed" ) }
                                for o in result[ "branches_kept" ] ] )
        try:
            result[ "refusals" ] = report_fn( result, ledger_path, notify_fn, log_fn )
        except Exception as e:
            log_fn( "worktree_refusal_report_error", error=str( e ) )
        if straggler_fn is not None:
            try:
                result[ "stragglers" ] = straggler_fn( result )
            except Exception as e:
                log_fn( "worktree_straggler_error", error=str( e ) )
        return result

    return janitor


def _default_branch_sweep_fn( project_root=None ) -> dict:
    """The real per-repo merged-branch sweep (worktree_reaper.sweep_merged_branches)."""
    from cosa.agents.shared.worktree_reaper import sweep_merged_branches
    return sweep_merged_branches( project_root=project_root )


def make_straggler_fn( *, ledger_path: str, janitor_idle_hours: float, log_fn: Callable,
                       store=None ) -> Callable[ [ dict ], dict ]:
    """
    The real straggler step: refused set → one store row per tree refused over a day.

    Requires:
        - ledger_path is the refusal ledger; the sidecar lives beside it as stragglers.json
        - store is None (→ RepositoryStragglerStore, direct repository writes) or injected

    Ensures:
        - returns fn( reconcile_result ) -> sync_straggler_tickets' summary, judged on the
          same refused set the ledger records (refused_set with the ledger as `previous`)
        - a first sighting is backdated from the tree's idle age minus janitor_idle_hours
        - the summary's "archived" is open_archive_tickets' result for this poll's
          branches_kept: one row per archived branch whose work had not landed
    """
    from cosa.agents.shared.worktree_refusal_ledger import refused_set, load_ledger
    from cosa.agents.shared.worktree_reaper import _newest_mtime_age_hours
    from cosa.agents.shared import worktree_straggler_tickets as st
    store      = store if store is not None else st.RepositoryStragglerStore()
    state_path = os.path.join( os.path.dirname( ledger_path ), "stragglers.json" )

    def straggler( result: dict ) -> dict:
        refused = refused_set( result, load_ledger( ledger_path ) )
        summary = st.sync_straggler_tickets(
            refused, state_path, store, log_fn,
            idle_hours_fn  = lambda p: _newest_mtime_age_hours( p, time.time() ),
            janitor_idle_h = janitor_idle_hours )
        # Row aec2319f: one row per branch archived this poll whose work had not landed.
        summary[ "archived" ] = st.open_archive_tickets( result.get( "branches_kept" ), store, log_fn )
        return summary

    return straggler


# ── eng#7 follow-through watcher factory (build-plan §3b) ───────────────────

def make_follow_through_watcher_factory(
    config_mgr,
    gateway,
    *,
    log_fn : Optional[ Callable ] = None,
) -> Callable[ [ Any ], Any ]:
    """
    Build the factory `(job) -> FollowThroughEscalationWatcher`, called once per job.

    Requires:
        - config_mgr exposes .get( key, default=, return_type= ) (the watcher reads
          the enable flag, tick multiplier, and live `arbiter poll seconds`)
        - gateway exposes send_to( recipient, body ) (the directed manager poke)

    Ensures:
        - returns factory( job ) -> a FollowThroughEscalationWatcher wired with
          config_mgr, the directed-manager-poke escalate_fn, and
          hold_check_fn = job.session_is_not_owed
        - a factory, not a bare instance, resolves the chicken-and-egg in the job
          constructor: hold_check_fn is the arbiter's already-built store-owed
          suppression predicate, so the watcher never duplicates the store read
          and never contends on the poke path
        - the escalate_fn sends one directed poke to the accountable manager through the
          bridge-less gateway when an awaiting:manager item has aged past its threshold
        - gating lives in the watcher: `follow through escalation enabled` (default
          False) makes sweep_once() a no-op, so wiring this in changes nothing at runtime
        - the escalate_fn is degrade-safe: a gateway.send_to blow-up is logged
          (follow_through_escalation_error) and never raised, because escalation
          must never kill a poll (observer invariant)
        - construction is pure in-memory (no DB, clock or hold-file IO until the
          flag is flipped and sweep_once runs); testable with a fake gateway,
          a fake config and a stub job exposing session_is_not_owed
    """
    log_fn = log_fn if log_fn is not None else _default_log_fn

    def _escalate_fn( item, manager, worker, awaited_since ):
        body = ( f"FOLLOW-THROUGH ESCALATION — you ({manager}) owe verification on an aged "
                 f"awaiting-manager item: '{item.title}' (worker {worker}, awaiting since "
                 f"{awaited_since.isoformat()}). Ack it or verify the work." )
        try:
            gateway.send_to( manager, body )
            log_fn( "follow_through_escalation", item=str( item.id ), manager=manager,
                    worker=worker, awaited_since=awaited_since.isoformat() )
        except Exception as e:                       # escalation degrade-safe (observer invariant)
            log_fn( "follow_through_escalation_error", item=str( item.id ), error=str( e ) )

    def factory( job ) -> Any:
        # GATE BEFORE IMPORT (2026-08-10). The watcher module's import chain reaches
        # cosa.rest.db.database -> sqlalchemy -> pgvector -> psycopg2-binary. On the
        # standalone :8001 host venv (deliberately LIGHT — see
        # src/scripts/requirements-arbiter.txt) those are absent, so this import
        # raised ModuleNotFoundError inside the ArbiterConsumerJob ctor and KILLED the
        # fleet-arbiter thread on its first tick — while the flag was OFF. The service
        # stayed active(running) and /health kept returning 200, so the fleet section
        # sat at `status: awaiting, session_count: 0` for two days.
        #
        # Reading the flag FIRST makes the enable-gate mean what the docstring above
        # already promises ("no DB ... until the flag is flipped"): disabled => no
        # import, no DB dependency, nothing to install on the watcher host. The job
        # ctor treats a None watcher as inert (layer (a) of _sweep_follow_through).
        #
        # Re-read per call, NOT hoisted to wiring time: the supervisor rebuilds the
        # job every cycle (run() -> self._job_factory()), so a live config flip is
        # picked up on the next tick without a service restart — the behavior the
        # watcher's own per-sweep flag read already provided.
        # Record: src/rnd/v0.2.0/2026.08.10-arbiter-fleet-loop-silent-death.md — REMOVED by c752ab9e (2026-08-29); recover: git show c752ab9e^:src/rnd/v0.2.0/2026.08.10-arbiter-fleet-loop-silent-death.md
        if not config_mgr.get( "follow through escalation enabled", default=False, return_type="boolean" ):
            log_fn( "follow_through_watcher_inert", reason="follow through escalation enabled = false (no DB import)" )
            return None
        from cosa.rest.follow_through_escalation_watcher import FollowThroughEscalationWatcher
        return FollowThroughEscalationWatcher(
            config_mgr,
            escalate_fn   = _escalate_fn,
            hold_check_fn = job.session_is_not_owed,   # §4.5: reuse the store-owed predicate
        )

    return factory


# ── the standing-job factory ────────────────────────────────────────────────

def build_fleet_arbiter_job_factory(
    gateway              : Any,
    store                : Any,
    *,
    clock                : Optional[ Any ]      = None,
    log_fn               : Optional[ Callable ] = None,
    live_notify_fn       : Optional[ Callable ] = None,
    poll_seconds         : int                  = 60,
    manager_on_duty      : str                  = "manager-on-duty",
    declared_managers    : Optional[ list ]     = None,
    alive_threshold      : int                  = 600,
    quiet_threshold      : int                  = 300,
    tap_min_interval     : int                  = 300,
    ack_window           : int                  = 600,
    stall_window         : int                  = 1800,
    poll_error_escalate_threshold : int         = 3,
    auto_poke_enabled    : bool                 = True,
    # audience scalpel (2026-07-19): AND-gated under auto_poke_enabled
    poke_workers_enabled : bool                 = True,
    poke_managers_enabled: bool                 = True,
    poke_operator_enabled: bool                 = True,
    poke_stall_threshold : int                  = 720,
    poke_max_per_episode : int                  = 3,
    stuck_poke_min_interval_seconds : int       = 0,            # bug 5a1f17f8 (c) fire-throttle (0 → disabled)
    manager_stale_poke_threshold : int          = 2700,
    manager_stale_poke_max_age : int            = 7200,
    # role-goals Phase 2-3: role-selected north-star goal echoes appended to the
    # stuck-poke + manager-staleness poke bodies. "" → inert (poke body unchanged).
    manager_goal_line    : str                  = "",
    worker_goal_line     : str                  = "",
    start_period_seconds : int                  = 120,
    # Item B (2026.06.11 receipts design): the delivery-receipt seams + knobs,
    # threaded verbatim to the job. None seams keep their tier inert.
    dm_push_fn           : Optional[ Callable ] = None,
    tmux_push_fn         : Optional[ Callable ] = None,   # Thread C+D host-side tmux wake hop
    poke_wake_mechanism  : str                  = "tmux", # Thread C+D wake-surface selector (default tmux)
    live_retry_fn        : Optional[ Callable ] = None,
    outreach_ack_window  : int                  = 900,
    reannounce_interval  : int                  = 300,
    reannounce_ttl       : int                  = 86400,
    pending_ledger_path  : Optional[ str ]      = None,
    # F-A (2026.06.11 lineage-persistence design): the restart-surviving carry file.
    lineage_carry_path   : Optional[ str ]      = None,
    offsets_state_path   : Optional[ str ]      = None,          # bug 5a1f17f8 (b): durable event-offset store; None → in-memory (replay on restart)
    # L1 (2026-06-17 arbiter detector gaps): the per-poll owed-work store reader
    # (arbiter = reader #2). Defaults to the real DB reader so the :8001 service
    # activates the store-aware suppression of the false-escalating detectors;
    # injectable for tests (construction is pure — the reader is never CALLED here).
    owed_work_fn         : Optional[ Callable ] = None,
    # 262c59f6 (A): the fleet-wide known-owner-persona reader (distinct owner_persona
    # over all store rows). Defaults to the real DB reader so the :8001 service arms
    # the known-persona fail-safe (a re-spin/label-contamination would-be-DONE persona
    # ∉ known owners → UNKNOWN, never a false MANAGER-DONE); injectable for tests.
    known_owners_fn      : Optional[ Callable ] = None,
    # 6929f4ac (outward-twin backstop): the per-session hold reader + the aged-gate
    # resurface ceiling. hold_reader_fn defaults to the real read_hold so the :8001
    # service resurfaces a DARK session's open, aged user-gate to Rick (None →
    # decorative); injectable for tests (never CALLED at construction).
    hold_reader_fn       : Optional[ Callable ] = None,
    user_gate_resurface_seconds : int           = 1800,
    # A2/A3 (fcb5dbc0): the fleet-wide open-operator-gate store reader + the NORMAL-
    # urgency digest cadence. operator_gates_fn defaults to the real DB reader so the
    # :8001 service activates the operator-gate urgency routing (urgent interrupt /
    # normal digest / low pull-only); injectable for tests (never CALLED here).
    operator_gates_fn    : Optional[ Callable ] = None,
    operator_digest_cadence_seconds : int       = DEFAULT_DIGEST_CADENCE_SECONDS,
    # DM-as-liveness toggle (2026-06-17): (1) the per-poll runtime-flag re-read
    # (None → the job defaults to `lambda: True`; app.py wires a per-poll
    # mtime-gated INI read so the flag is runtime-tunable with no bounce). (2) the
    # SENT-DM store reader — defaults to the real DB reader so the :8001 service
    # activates the 5th signal; injectable for tests (never CALLED at construction).
    count_dm_as_liveness_fn : Optional[ Callable ] = None,
    dm_activity_fn          : Optional[ Callable ] = None,
    # bug 26dd3afb: the MANAGER-STALE bridge-mtime veto reader. Defaulted REAL here
    # (like hold_reader_fn) so the veto is LIVE on the :8001 deploy — without this
    # wiring the seam stays None → the veto is decorative and Tiberius-class false
    # positives recur. A fake overrides it for tests.
    bridge_mtimes_fn        : Optional[ Callable ] = None,
    # eng#7 (2026-06-17): the follow-through aged-escalation watcher factory
    # ((job) -> watcher). None keeps it INERT (no watcher wired); app.py builds the
    # real one (make_follow_through_watcher_factory) so the :8001 job rides it. Even
    # wired, the `follow through escalation enabled`=False flag keeps sweep_once a
    # no-op until a deliberate flip — zero runtime behavior change on wiring-in.
    follow_through_watcher_factory : Optional[ Callable ] = None,
    # ee59d5ed orphan-bridge janitor: default-OFF because it CHANGES fleet-wide reap
    # semantics (every reaped session now durably drops off the operator focus bar).
    # Off → the sweep seam is never wired (None → INERT), zero runtime change on
    # merge; Rick flips `arbiter orphan bridge sweep enabled`=True to activate.
    orphan_bridge_sweep_enabled       : bool = False,
    orphan_bridge_sweep_debounce_polls : int = 2,   # N consecutive dead polls before a reap (safety debounce)
    # row 033538f6: the worktree janitor. Default OFF here so an unconfigured factory stays
    # inert; app.py passes the INI's `arbiter worktree janitor enabled`.
    worktree_janitor_enabled    : bool           = False,
    worktree_janitor_age_hours  : float          = 6.0,
    worktree_sandbox_root       : str            = ".claude/worktrees",
    worktree_refusal_ledger_path : Optional[ str ] = None,
    # row 129cc96b P2: janitor_repo_roots( cfg ) — { roots, unresolved }. None → this
    # project only.
    worktree_janitor_repos      : Optional[ dict ] = None,
) -> Callable[ [ ], ArbiterConsumerJob ]:
    """
    Build the recycle factory: each call returns a fresh ArbiterConsumerJob.

    The job is wired bridge-less to the :8001-local store and the warm-up-wrapped
    escalation sink.

    Ensures:
        - returned factory() builds an ArbiterConsumerJob whose snapshot_sink writes
          store section "fleet_arbiter", and whose notify_fn is warm-up wrapped around
          escalation (durable plus best-effort live), keyed on a fresh per-call
          job start, so warm-up resets on each recycle
        - construction is pure in-memory (no IO until the job runs), so it is
          testable with a fake gateway
    """
    clock  = clock  if clock  is not None else SystemClock()
    log_fn = log_fn if log_fn is not None else _default_log_fn
    # L1: wire the real DB owed-work reader by default so the :8001 service gets
    # store-aware detector suppression; an injected fake overrides it for tests.
    owed_work_fn = owed_work_fn if owed_work_fn is not None else _default_owed_work_fn
    # 262c59f6 (A): wire the real known-owner reader by default so the :8001 service
    # arms the known-persona fail-safe against re-spin/label-contamination false
    # MANAGER-DONE; an injected fake overrides it for tests.
    known_owners_fn = known_owners_fn if known_owners_fn is not None else _default_known_owners_fn
    # DM-as-liveness: wire the real SENT-DM reader by default so the :8001 service
    # activates the 5th signal; an injected fake overrides it for tests. The
    # runtime-flag re-read is wired by app.py (cfg-closed lambda); None here lets
    # the job default to `lambda: True` (feature ON, the INI default).
    dm_activity_fn = dm_activity_fn if dm_activity_fn is not None else _default_dm_activity_fn
    # 6929f4ac: wire the real hold reader by default so the :8001 service activates
    # the outward-twin backstop (open-gate→ACTIVE classify override + dark-session
    # gate resurface); an injected fake overrides it for tests.
    # row 011f1f90: the default is read_hold_via_bridge wrapped with THIS factory's
    # log_fn, so a repo-root hold is now visible to the veto AND the cwd=None
    # fallback (no_bridge / bridge_without_cwd / bridge_error) emits one journal
    # line instead of silently restoring the blind fleet-only read.
    hold_reader_fn = hold_reader_fn if hold_reader_fn is not None else ( lambda sid: read_hold_via_bridge( sid, log_fn=log_fn ) )
    # A2/A3 (fcb5dbc0): wire the real fleet-wide operator-gate reader by default so the
    # :8001 service activates the operator-gate urgency routing; a fake overrides it.
    operator_gates_fn = operator_gates_fn if operator_gates_fn is not None else _default_operator_gates_fn
    # bug 26dd3afb: wire the real persona→bridge-mtime reader by default so the :8001
    # service arms the MANAGER-STALE bridge-mtime veto; an injected fake overrides it.
    bridge_mtimes_fn = bridge_mtimes_fn if bridge_mtimes_fn is not None else _default_manager_bridge_mtimes
    escalation_notify = make_escalation_notify_fn( gateway, live_notify_fn=live_notify_fn, log_fn=log_fn )

    # row 033538f6: built ONCE, outside the recycle factory — it holds no per-job state
    # (the refused set lives in the ledger file, so it survives a recycle and a bounce).
    worktree_janitor_fn = None
    if worktree_janitor_enabled:
        import cosa.utils.util as cu
        ledger_path = worktree_refusal_ledger_path or os.path.join(
            cu.get_project_root(), "io", "worktree-janitor", "refused.json" )
        repos = worktree_janitor_repos or { }
        if repos.get( "unresolved" ):
            log_fn( "worktree_janitor_repo_unresolved", names=repos[ "unresolved" ] )
        worktree_janitor_fn = make_worktree_janitor_fn(
            sandbox_root = worktree_sandbox_root,
            age_hours    = worktree_janitor_age_hours,
            ledger_path  = ledger_path,
            notify_fn    = make_refusal_notify_fn( gateway, live_notify_fn=live_notify_fn, log_fn=log_fn ),
            log_fn       = log_fn,
            repo_roots   = repos.get( "roots" ),
            straggler_fn = make_straggler_fn( ledger_path=ledger_path,
                                              janitor_idle_hours=worktree_janitor_age_hours, log_fn=log_fn ),
            branch_sweep_fn = _default_branch_sweep_fn,
        )

    def factory() -> ArbiterConsumerJob:
        job_start     = clock.now()
        warmup_notify = make_warmup_notify_fn( escalation_notify, job_start, start_period_seconds, clock, log_fn )
        # ee59d5ed orphan-bridge sweep seam. The debounce-state dict is created ONCE
        # per job here and captured by the closure, so the {session_id: consecutive-
        # dead-polls} counter PERSISTS across this job's polls (a recycle resets it —
        # the accepted trade for all arbiter cross-poll state). None when the flag is
        # off → the poll-loop seam stays inert.
        bridge_sweep_fn = None
        if orphan_bridge_sweep_enabled:
            from cosa.agents.shared.orphan_bridge_reaper import reconcile_orphan_bridges
            bridge_dead_polls: dict = { }
            bridge_sweep_fn = lambda: reconcile_orphan_bridges(
                bridge_dead_polls, debounce_threshold=orphan_bridge_sweep_debounce_polls
            )
        return ArbiterConsumerJob(
            commons                    = gateway,
            bridge_sweep_fn            = bridge_sweep_fn,                           # ee59d5ed orphan-bridge janitor (default-off flag)
            worktree_janitor_fn        = worktree_janitor_fn,                       # row 033538f6: never wired on :8001 before
            owed_work_fn               = owed_work_fn,                              # L1 store-aware seam
            known_owners_fn            = known_owners_fn,                           # 262c59f6 (A) known-persona fail-safe seam
            hold_reader_fn             = hold_reader_fn,                            # 6929f4ac outward-twin backstop
            user_gate_resurface_seconds = user_gate_resurface_seconds,             # 6929f4ac aged-gate ceiling
            operator_gates_fn          = operator_gates_fn,                         # A2/A3 operator-gate store reader
            operator_digest_cadence_seconds = operator_digest_cadence_seconds,      # A2/A3 normal-digest cadence
            count_dm_as_liveness_fn    = count_dm_as_liveness_fn,                   # DM-toggle runtime flag (app.py wires cfg read)
            dm_activity_fn             = dm_activity_fn,                            # DM-toggle SENT-DM store reader
            bridge_mtimes_fn           = bridge_mtimes_fn,                          # bug 26dd3afb MANAGER-STALE bridge-mtime veto reader
            poll_seconds               = poll_seconds,
            manager_recipient          = manager_on_duty,
            declared_managers          = declared_managers,
            alive_threshold_seconds    = alive_threshold,
            quiet_threshold_seconds    = quiet_threshold,
            tap_min_interval_seconds   = tap_min_interval,
            manager_ack_window_seconds = ack_window,
            fleet_stall_window_seconds = stall_window,
            poll_error_escalate_threshold = poll_error_escalate_threshold,
            auto_poke_enabled            = auto_poke_enabled,
            poke_workers_enabled         = poke_workers_enabled,      # audience scalpel (2026-07-19)
            poke_managers_enabled        = poke_managers_enabled,
            poke_operator_enabled        = poke_operator_enabled,
            poke_stall_threshold_seconds = poke_stall_threshold,
            poke_max_per_episode         = poke_max_per_episode,
            stuck_poke_min_interval_seconds = stuck_poke_min_interval_seconds,      # bug 5a1f17f8 (c) fire-throttle
            manager_stale_poke_threshold_seconds = manager_stale_poke_threshold,   # post-game F2
            manager_stale_poke_max_age_seconds   = manager_stale_poke_max_age,     # corpse ceiling
            manager_goal_line          = manager_goal_line,                        # role-goals Phase 2-3
            worker_goal_line           = worker_goal_line,                         # role-goals Phase 2-3
            dm_push_fn                  = dm_push_fn,                              # Item B §3.3
            tmux_push_fn                = tmux_push_fn,                            # Thread C+D host-side tmux wake
            poke_wake_mechanism         = poke_wake_mechanism,                     # Thread C+D wake selector
            lineage_carry_path          = lineage_carry_path,                      # F-A lineage carry
            offsets_state_path          = offsets_state_path,                       # bug 5a1f17f8 (b) durable event offsets
            live_retry_fn               = live_retry_fn,                           # Item B §3.5
            outreach_ack_window_seconds = outreach_ack_window,
            reannounce_interval_seconds = reannounce_interval,
            reannounce_ttl_seconds      = reannounce_ttl,
            pending_ledger_path         = pending_ledger_path,
            follow_through_watcher_factory = follow_through_watcher_factory,        # eng#7 §3b
            snapshot_sink              = lambda snap: store.set_section( "fleet_arbiter", snap ),
            render_sink                = lambda line: log_fn( "fleet_arbiter_render", line=line ),
            notify_fn                  = warmup_notify,
            log_fn                     = log_fn,                                   # post-game F1: outreach + gate events → journal
            user_id                    = "system",
            user_email                 = "system@lupin.deepily.ai",
            session_id                 = "lupin-arbiter-app-8001",
        )

    return factory


# ── recycle supervisor ──────────────────────────────────────────────────────

class FleetArbiterLoop:
    """
    Runs one ArbiterConsumerJob at a time, relaunching a fresh one on each clean cap-exit.

    This is the :8001-side fleet-arbiter supervisor. It runs the job on a background
    thread, and the relaunch fixes the 12h self-perpetuation gap. Runs are sequential,
    so only one job runs at a time.
    """

    def __init__(
        self,
        job_factory          : Callable[ [ ], ArbiterConsumerJob ],
        *,
        log_fn               : Optional[ Callable ] = None,
        hold_janitor_fn      : Optional[ Callable ] = None,
        hold_deleter_fn      : Optional[ Callable ] = None,
        hold_roots_fn        : Optional[ Callable ] = None,
        live_session_ids_fn  : Optional[ Callable ] = None,
        enable_hold_deletion : bool = False,
        hwm_janitor_fn       : Optional[ Callable ] = None,
        hwm_deleter_fn       : Optional[ Callable ] = None,
        enable_hwm_deletion  : bool = False,
        bookmark_janitor_fn  : Optional[ Callable ] = None,
        bookmark_deleter_fn  : Optional[ Callable ] = None,
        enable_bookmark_deletion : bool = False,
        construct_retry_seconds : float = 60.0,
    ) -> None:
        self._job_factory    = job_factory
        self._log_fn         = log_fn if log_fn is not None else _default_log_fn
        # b39562e4 pt2 → 2026-07-16: the hold sweep, REPORT-ONLY. Runs once per
        # supervisor cycle (each arbiter start + ~12h recycle). All three seams are
        # injectable so tests never touch the real project root, and so the two
        # UNRULED questions (which roots? which live-set?) are answered by the
        # caller rather than assumed here.
        self._hold_janitor_fn     = hold_janitor_fn if hold_janitor_fn is not None else _default_hold_reporter
        self._hold_deleter_fn     = hold_deleter_fn if hold_deleter_fn is not None else _default_hold_deleter
        self._hold_roots_fn       = hold_roots_fn if hold_roots_fn is not None else _default_hold_roots
        self._live_session_ids_fn = live_session_ids_fn if live_session_ids_fn is not None else _default_live_session_ids
        # Reclamation switch (11461241, Rick's ruling "wire it"). **DEFAULT FALSE, and
        # that is not timidity — it is this milestone's own rule applied to itself.**
        #
        # A0, the origin bug of this whole family, was a CALL SITE that reached
        # deletion by OMITTING a guard. `classify_hold_file` was therefore given
        # `allow_cargo_deletion=False` as its default so that omission is the SAFE
        # state. A constructor whose omitted parameter DELETES is that same bug in a
        # new place — and it was in the first draft of this diff, three lines under a
        # docstring citing A0 as the reason not to do it. Caught by Mr Radio 🦉.
        #
        # Deletion is therefore opt-IN, stated out loud at the one production call
        # site Rick authorized. Every other construction — tests, tools, any future
        # caller — is report-only unless it says otherwise.
        self._enable_hold_deletion = bool( enable_hold_deletion )
        # 8758d0b1 — the DM-inbox HWM family gets its OWN seams and its OWN switch,
        # per Rick's ruling 2026-07-26. NOT folded into enable_hold_deletion: the two
        # families have different failure modes, and coupling them means disabling
        # hold deletion after a cargo scare would silently stop HWM cleanup too,
        # with the pile resuming growth and nobody noticing.
        #
        # ⚠️ Reaping a LIVE session's HWM SILENTLY SWALLOWS its un-surfaced DMs
        # (measured; surface_dm_inbox:327-328 blanks context when `seeded` is False,
        # and a missing file reads as unseeded). That is 59f355e0 re-created. So this
        # switch defaults FALSE for the same reason enable_hold_deletion does — an
        # omitted parameter must never be the one that deletes.
        self._hwm_janitor_fn      = hwm_janitor_fn if hwm_janitor_fn is not None else _default_hwm_reporter
        self._hwm_deleter_fn      = hwm_deleter_fn if hwm_deleter_fn is not None else _default_hwm_deleter
        self._enable_hwm_deletion = bool( enable_hwm_deletion )
        # The three milder bookmark families ride the same seam, their own switch —
        # FALSE by default for the same reason: an omitted parameter must never delete.
        self._bookmark_janitor_fn      = bookmark_janitor_fn if bookmark_janitor_fn is not None else _default_bookmark_reporter
        self._bookmark_deleter_fn      = bookmark_deleter_fn if bookmark_deleter_fn is not None else _default_bookmark_deleter
        self._enable_bookmark_deletion = bool( enable_bookmark_deletion )
        self._stop           = threading.Event()
        self._current_job    = None
        self._thread         = None
        self.cycles          = 0
        # Back-off between failed job CONSTRUCTIONS (2026-08-10). Without a pause a
        # persistent ctor fault (e.g. a missing dependency) would spin the thread hot
        # and flood the journal. Injectable so a unit test can drive the retry path
        # without a real sleep.
        self._construct_retry_seconds = float( construct_retry_seconds )

    def run( self ) -> None:
        """
        Poll-supervisor loop: build a job, run it to its cap or cancel, relaunch.

        Ensures:
            - relaunches a fresh job after each clean cap-exit until stop()
            - a job blow-up is swallowed and logged (the supervisor outlives one bad job)
            - a job construction blow-up is likewise swallowed, logged and retried on
              the next cycle; see the comment at the try below
            - exits promptly when stop() has been signalled
            - never raises
        """
        while not self._stop.is_set():
            self._sweep_hold_files()             # b39562e4 pt2: hold janitor — REPORT-ONLY (deletes nothing)
            self._sweep_hwm_files()              # 8758d0b1: DM-inbox HWM janitor — its own switch
            self._sweep_bookmark_files()         # bd5c27e1: ask-answer / task-map / acked — its own switch
            # CONSTRUCTION IS INSIDE THE GUARD (2026-08-10). This line used to sit
            # OUTSIDE any try, so a raise in the job ctor propagated out of run(),
            # killed the thread, and never retried — the supervisor's stated promise
            # ("the supervisor outlives one bad job") covered do_all() only. A
            # ModuleNotFoundError in the ctor's watcher-factory therefore turned a
            # missing dependency into a permanently dead loop that no health surface
            # reported. Retrying keeps a transient/self-healing fault self-healing,
            # and makes a persistent one LOUD (one log line per cycle) instead of
            # silent-once-at-boot.
            # Record: src/rnd/v0.2.0/2026.08.10-arbiter-fleet-loop-silent-death.md — REMOVED by c752ab9e (2026-08-29); recover: git show c752ab9e^:src/rnd/v0.2.0/2026.08.10-arbiter-fleet-loop-silent-death.md
            try:
                job = self._job_factory()
            except Exception as e:
                self._log_fn( "fleet_arbiter_job_construct_error", error=f"{type( e ).__name__}: {e}" )
                if self._stop.wait( self._construct_retry_seconds ):
                    break
                continue
            self._current_job = job
            self.cycles += 1
            self._log_fn( "fleet_arbiter_job_start", cycle=self.cycles )
            try:
                summary = job.do_all()
            except Exception as e:                   # a job blow-up must not kill the supervisor
                self._log_fn( "fleet_arbiter_job_error", error=str( e ) )
                summary = None
            if self._stop.is_set():
                break
            self._log_fn( "fleet_arbiter_recycle", reason="clean cap-exit — relaunching", summary=summary )

    def _sweep_hold_files( self ) -> None:
        """
        Classify every `.heartbeat-hold-*` file, then reclaim the ones proven prunable.

        Ensures:
            - calls the injected report fn with both the injected roots and the
              injected live set; emits `fleet_arbiter_hold_report` every tick with
              roots_swept, files_seen and the classification tallies, empty or not
            - emits `fleet_arbiter_hold_report_no_roots` (a distinct event) when the
              sweep reached zero roots, because "swept nothing" is the opposite fact
              from "found nothing" and a lone zero cannot tell them apart
            - surfaces skipped-but-hold-bearing dirs and unreachable roots rather
              than silently omitting them
            - deletes only what the same-clock classification marked prunable, and
              never a cargo-bearing hold; emits `deleted` and `deletion_enabled`
              every tick so neither is inferred from silence
            - the report and the janitor are two functions over one decision rule
              (`classify_hold_file`), so the logged tally proves what was deleted only if
              both classify at the same instant; `now` is frozen once here and passed to
              both. A file crossing its TTL between two calls would be logged as kept and
              deleted anyway
            - never passes the cargo guard: both callees default
              `allow_cargo_deletion=False`, so cargo-bearing holds are kept structurally.
              Passing True from here would let a call site reach deletion by omission
            - always passes the roots and the live set. Without roots the sweep would read
              one directory non-recursively. Without the live set the positive-dead branch
              of the janitor would be unreachable in production
            - reports on every tick, not only a non-empty result, so a total-failure sweep
              never looks like a healthy tick
            - swallows and logs any exception (the janitor must never kill the
              supervisor); a deletion failure does not suppress the report, which
              is emitted before reclamation is attempted
        """
        try:
            roots  = list( self._hold_roots_fn() or [ ] )
            live   = self._live_session_ids_fn()
            now    = datetime.datetime.now( datetime.timezone.utc )   # ONE clock: evidence AND act
            report = self._hold_janitor_fn( base_dirs=roots, live_session_ids=live, now=now )
            counts = report[ "counts" ]
            if not report[ "roots_swept" ]:
                # LOUD: reached no roots at all. Not the same fact as "nothing to reap".
                self._log_fn( "fleet_arbiter_hold_report_no_roots",
                              roots_requested   = report[ "roots_requested" ],
                              roots_unreachable = report[ "roots_unreachable" ] )
            if report[ "location_zone" ] is None:
                # LOUD: the location zone was UNJUDGEABLE (unresolved or fail-closed
                # shallow), so misplaced=0 below is NOT a clean bill of health — the
                # detector could not judge location at all. Distinct event so a
                # fail-closed zone never masquerades as "no leaks" (row 011f1f90).
                self._log_fn( "fleet_arbiter_hold_location_unjudged",
                              files_seen = report[ "files_found" ] )
            self._log_fn( "fleet_arbiter_hold_report",
                          roots_swept             = report[ "roots_swept" ],
                          roots_unreachable       = report[ "roots_unreachable" ],
                          files_seen              = report[ "files_found" ],
                          prunable                = counts[ "prunable" ],
                          kept                    = counts[ "keep" ],
                          cargo_bearing           = counts[ "cargo_bearing" ],
                          ttl_unusable            = counts[ "ttl_unusable" ],
                          anchor_disagreement     = counts[ "anchor_disagreement" ],
                          # row 011f1f90: LOCATION as a first-class field, NOT folded into
                          # cargo_bearing. The resilient veto now makes a misplaced hold
                          # FUNCTION, so this count + the paths are the surviving signal that
                          # the file is still in the wrong place. deleting them stays Rick's call.
                          location_zone           = report[ "location_zone" ],
                          misplaced               = counts[ "misplaced" ],
                          misplaced_paths         = report[ "misplaced_paths" ],
                          kept_reasons            = counts[ "reachable_but_kept_reasons" ],
                          skipped_dirs_with_holds = report[ "skipped_dirs_with_holds" ],
                          deletion_enabled        = self._enable_hold_deletion,
                          deleted                 = report[ "deleted" ] )
        except Exception as e:                   # janitor must never kill the supervisor
            self._log_fn( "fleet_arbiter_hold_janitor_error", error=str( e ) )
            return                               # no classification ⇒ nothing is proven prunable

        if not self._enable_hold_deletion:
            return
        try:
            # SAME roots, SAME live-set, SAME `now` as the report above — and the
            # cargo guard left at its default False. The report's `prunable` tally is
            # therefore a PREDICTION of this call's result, which is what makes the
            # pair auditable: if `deleted` and `prunable` ever disagree, the disagreement
            # itself is the finding.
            pruned = self._hold_deleter_fn( base_dirs=roots, live_session_ids=live, now=now )
            self._log_fn( "fleet_arbiter_hold_reclaimed",
                          deleted           = len( pruned ),
                          predicted_prunable = counts[ "prunable" ],
                          agrees            = ( len( pruned ) == counts[ "prunable" ] ),
                          paths             = pruned )
        except Exception as e:               # reclamation must never kill the supervisor
            self._log_fn( "fleet_arbiter_hold_reclaim_error", error=str( e ) )

    def _sweep_hwm_files( self ) -> None:
        """
        Classify every `.dm-inbox-hwm-*` file, then reclaim what is orphaned and aged.

        Ensures:
            - emits `fleet_arbiter_hwm_report` every cycle with roots, files_seen and
              tallies, empty or not, so "swept nothing" is never inferred from silence
            - emits `fleet_arbiter_hwm_report_no_roots` as a distinct event when the sweep
              reached zero roots ("swept nothing" is the opposite fact from "found
              nothing", and one zero cannot tell them apart)
            - deletes only when enable_hwm_deletion is set, and only what the
              same-clock classification marked prunable
            - is a sibling of _sweep_hold_files, not an extension: the two families share
              a traversal and nothing else. An HWM file has no `held_at`, `ttl_seconds` or
              `session_id`, so the hold classifier would keep every one forever and report
              a clean green
            - passes one frozen `now_ts` to the report and the act, with the same live set,
              so the report's `prunable` tally predicts the deletion count and a
              disagreement is itself the finding
            - treats the live set as correctness-critical: reaping a live session's HWM
              makes its next reconcile read as first-ever activation (`seeded` False),
              which records the inbox as seen and silently swallows every un-surfaced DM.
              `_default_live_session_ids` returning None keeps everything
            - swallows and logs any exception; a janitor must never kill the supervisor
        """
        try:
            roots  = list( self._hold_roots_fn() or [ ] )     # same roots — same runtime-state family location
            live   = self._live_session_ids_fn()
            now_ts = time.time()                              # ONE clock: evidence AND act
            report = self._hwm_janitor_fn( base_dirs=roots, live_session_ids=live, now_ts=now_ts )
            counts = report[ "counts" ]
            if not report[ "roots_swept" ]:
                self._log_fn( "fleet_arbiter_hwm_report_no_roots",
                              roots_requested   = report[ "roots_requested" ],
                              roots_unreachable = report[ "roots_unreachable" ] )
            self._log_fn( "fleet_arbiter_hwm_report",
                          roots_swept       = report[ "roots_swept" ],
                          roots_unreachable = report[ "roots_unreachable" ],
                          files_seen        = report[ "files_found" ],
                          prunable          = counts[ "prunable" ],
                          kept              = counts[ "keep" ],
                          kept_reasons      = counts[ "reachable_but_kept_reasons" ],
                          live_set_present  = ( live is not None ),
                          deletion_enabled  = self._enable_hwm_deletion )
        except Exception as e:                   # janitor must never kill the supervisor
            self._log_fn( "fleet_arbiter_hwm_janitor_error", error=str( e ) )
            return                               # no classification ⇒ nothing is proven prunable

        if not self._enable_hwm_deletion:
            return
        try:
            pruned = self._hwm_deleter_fn( base_dirs=roots, live_session_ids=live, now_ts=now_ts )
            self._log_fn( "fleet_arbiter_hwm_reclaimed",
                          deleted            = len( pruned ),
                          predicted_prunable = counts[ "prunable" ],
                          agrees             = ( len( pruned ) == counts[ "prunable" ] ),
                          paths              = pruned )
        except Exception as e:               # reclamation must never kill the supervisor
            self._log_fn( "fleet_arbiter_hwm_reclaim_error", error=str( e ) )

    def _sweep_bookmark_files( self ) -> None:
        """
        Classify the three milder bookmark families, then reclaim what is orphaned and aged.

        Ensures:
            - covers `.ask-answer-hwm-*`, `.task-store-map-*` and `.heartbeat-acked-*`
            - emits `fleet_arbiter_bookmark_report` every cycle (per-family tallies), so
              "swept nothing" is never inferred from silence
            - emits `fleet_arbiter_bookmark_report_no_roots` as a distinct event on zero roots
            - deletes only when enable_bookmark_deletion is set, and only what the
              same-clock, same-live-set classification marked prunable
            - is a sibling of _sweep_hwm_files, kept separate from the dm-inbox sweep:
              mis-deleting that family silently loses DMs, so it keeps its own proven
              module, while these three are milder (one yields a benign duplicate and two
              regenerate)
            - never reaps a live session's bookmark at any age, and a None live set keeps
              everything
            - shares one frozen `now_ts` between report and act, so the report's `prunable`
              tally predicts the deletion count and a disagreement is itself the finding
            - swallows and logs any exception; a janitor must never kill the supervisor
        """
        try:
            roots  = list( self._hold_roots_fn() or [ ] )     # same roots — same runtime-state family location
            live   = self._live_session_ids_fn()
            now_ts = time.time()                              # ONE clock: evidence AND act
            report = self._bookmark_janitor_fn( base_dirs=roots, live_session_ids=live, now_ts=now_ts )
            counts = report[ "counts" ]
            if not report[ "roots_swept" ]:
                self._log_fn( "fleet_arbiter_bookmark_report_no_roots",
                              roots_requested   = report[ "roots_requested" ],
                              roots_unreachable = report[ "roots_unreachable" ] )
            self._log_fn( "fleet_arbiter_bookmark_report",
                          roots_swept       = report[ "roots_swept" ],
                          roots_unreachable = report[ "roots_unreachable" ],
                          files_seen        = report[ "files_found" ],
                          prunable          = counts[ "prunable" ],
                          kept              = counts[ "keep" ],
                          kept_reasons      = counts[ "reachable_but_kept_reasons" ],
                          per_family        = counts[ "per_family" ],
                          live_set_present  = ( live is not None ),
                          deletion_enabled  = self._enable_bookmark_deletion )
        except Exception as e:                   # janitor must never kill the supervisor
            self._log_fn( "fleet_arbiter_bookmark_janitor_error", error=str( e ) )
            return                               # no classification ⇒ nothing is proven prunable

        if not self._enable_bookmark_deletion:
            return
        try:
            pruned = self._bookmark_deleter_fn( base_dirs=roots, live_session_ids=live, now_ts=now_ts )
            self._log_fn( "fleet_arbiter_bookmark_reclaimed",
                          deleted            = len( pruned ),
                          predicted_prunable = counts[ "prunable" ],
                          agrees             = ( len( pruned ) == counts[ "prunable" ] ),
                          paths              = pruned )
        except Exception as e:               # reclamation must never kill the supervisor
            self._log_fn( "fleet_arbiter_bookmark_reclaim_error", error=str( e ) )

    def start( self ) -> None:
        """Spawn the daemon supervisor thread."""
        self._thread = threading.Thread( target=self.run, name="fleet-arbiter-loop", daemon=True )
        self._thread.start()

    def stop( self ) -> None:
        """Signal stop, cancel the in-flight job, and join the thread."""
        self._stop.set()
        if self._current_job is not None:
            try:
                self._current_job.request_cancel()
            except Exception as e:                   # cancel must never raise out of stop()
                self._log_fn( "fleet_arbiter_cancel_error", error=str( e ) )
        if self._thread is not None:
            self._thread.join( timeout=5 )
