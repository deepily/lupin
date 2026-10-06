#!/usr/bin/env python3
"""
Stop hook: voice-driven blocking and stop observability.

When the voice buffer has content, blocks the stop and injects that content as
the reason. Claude then processes the user's voice input instead of stopping.
When the buffer is empty, allows the stop.

Safety valve: MAX_STOP_BLOCKS consecutive blocks before force-allowing stop.
Loop prevention: if stop_hook_active is True, the hook is being re-invoked
after a block, so it does not block again.

Install in ~/.claude/settings.json:
    "hooks": {
        "Stop": [{
            "type": "command",
            "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/stop.py\""
        }]
    }
"""
import os
import sys
import time

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:   # pragma: no cover - bootstrap import-guard; src is always on sys.path under pytest
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, log_to_stream, emit_json, send_tts,
    drain_and_acknowledge, format_voice_context, build_stop_block,
    inject_qualifier_via_tmux, get_buffer_path, deliver_pending_peer_dms,
    enrich_voice_context, get_stop_block_count, increment_stop_block_count,
    reset_stop_block_count, get_turn_elapsed_seconds, MAX_STOP_BLOCKS
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, build_sender_id_for_cc, resolve_stable_session_id,
    get_speakerphone, get_session_metadata, get_voice_persona,
    get_idle_detection, set_idle_detection_field, kill_idle_waiter,
    get_last_autonarrated_turn_id, set_last_autonarrated_turn_id,
    find_active_voice_persona_sessions, resolve_project_name,
    canonical_persona_key,
)
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notify_user_async import notify_user_async
from lupin_cli.notifications.notification_models import (
    NotificationRequest, ResponseType, NotificationPriority, AsyncNotificationRequest
)
from cosa.utils.notification_utils import extract_qualifier_comment
from lupin_cli.claude_code.hooks.lib.idle_settings import load_idle_settings
from cosa.config.configuration_manager import ConfigurationManager
from lupin_cli.claude_code.hooks.lib.anything_else_ask import (
    fire_anything_else_ask, summarize_task as _shared_summarize_task,
)
# ── Heartbeat Hook (Branch-C self-poke) — additive, gated, downstream of the
#    stop_hook_active loop guard; voice always wins. Leaf modules are pure +
#    100%-covered; this file holds only the thin adapter. See:
#    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/02-stop-py-seam-factoring-proposal.md
from lupin_cli.claude_code.hooks.lib.heartbeat_hold import (
    read_hold_resilient, get_pending_user_gates, get_last_looked_in_ts,
    get_last_spinup_check_ts, get_last_surfaced_questions_ts,
)
# Scoped loud-at-read: this session's OWN hold declares a ttl that cannot make it
# fresh ⇒ it is never honored ⇒ it is being poked despite holding. One warning,
# once per hold-version. See heartbeat_hold_warn for the cardinality argument.
from lupin_cli.claude_code.hooks.lib.heartbeat_hold_warn import should_warn_unusable_ttl
# 6929f4ac receipts-of-progress — the pure gate-row transforms (outward twin).
from lupin_cli.claude_code.hooks.lib import heartbeat_user_gates
from lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap import (
    get_poke_count, increment_poke_count, DEFAULT_POKE_CAP,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    decide_heartbeat, OUTCOME_POKE, OUTCOME_NOT_OWED, OUTCOME_HONORED, OUTCOME_CAP_REACHED,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_settings import load_heartbeat_settings
from lupin_cli.claude_code.hooks.lib import heartbeat_events
# v2 Track-A — live work-owed oracle (Task* replay from the session transcript).
from lupin_cli.claude_code.hooks.lib.board_sweep import sweep_progress_line
from lupin_cli.claude_code.hooks.lib.memento_verify_tick import verify_tick_line
from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import (
    evaluate_work_owed, partition_inbound_by_age, TODO_IN_PROGRESS, TODO_PENDING,
    format_owed_summary,
    manager_needs_verification, manager_needs_spinup_check, manager_needs_question_surface,
    SPINUP_CHECK_DEBOUNCE_SECONDS, SURFACE_QUESTIONS_DEBOUNCE_SECONDS, SPINUP_BACKLOG_MIN_N,
    MUTE_PROMPT_SENTINEL,
)
# Spine Step-2 (store-canonical task management) — the flag-gated store-count
# owed source. DEFAULT-old (transcript replay) until the fleet cutover flips
# heartbeat.owed_source_from_store. See cascade review §A/§B/§C, lupin ->
# src/rnd/v0.1.8/2026.06.16-store-canonical-task-mgmt-cascade-review.md
from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir
from lupin_cli.claude_code.hooks.lib.task_store_settings import load_task_store_settings
from lupin_cli.claude_code.hooks.lib.task_store_client import read_api_key, query_owed, query_owed_breakdowns, query_blocked_user_rows
# v4 acked-inbound ledger (Rick 2026-06-10) — explicit "looked-at" qids the
# unanswered-inbound gatherer subtracts (spec part (c)).
from lupin_cli.claude_code.hooks.lib.heartbeat_acked_ledger import read_acked_qids
from lupin_cli.claude_code.hooks.lib.heartbeat_task_state import (
    replay_task_state, owed_items_from_state, is_empty_state,
    replay_task_subjects, OWED_STATUSES,
)


def _summarize_task( last_assistant_message ):
    """
    Summarize the last assistant message using Gister (default mode).

    Requires:
        - last_assistant_message is a string or None

    Ensures:
        - Returns a concise gist string on success
        - Returns None on any failure or empty input
    """
    if not last_assistant_message or not last_assistant_message.strip():
        return None

    try:
        from cosa.memory.gister import Gister
        gister = Gister( debug=False, verbose=False )
        gist   = gister.get_gist( last_assistant_message, prompt_key="prompt template for stop hook gist" )
        return gist if gist else None
    except Exception:
        return None


# NOTE: classify_qualifier() is commented out because its synchronous LLM
# call to phi4 exceeds Claude Code's stop hook subprocess timeout (~5-10s).
# Preserved for future use in non-time-critical contexts.
#
# def classify_qualifier( qualifier ):
#     """
#     Classify a user qualifier as 'question' or 'instruction' via phi4 LLM.
#
#     Follows the established agent pattern:
#         1. Load prompt template path from config
#         2. Process template via PromptTemplateProcessor (injects XML example)
#         3. Format with utterance
#         4. Call LLM via LlmClientFactory
#         5. Parse response via QualifierClassification.from_xml()
#
#     Requires:
#         - qualifier is a non-empty string
#
#     Ensures:
#         - Returns QualifierClassification instance on success
#         - Returns None on any failure (LLM unreachable, parse error, etc.)
#     """
#     try:
#         import cosa.utils.util as du
#         from cosa.config.configuration_manager import ConfigurationManager
#         from cosa.agents.llm_client_factory import LlmClientFactory
#         from cosa.agents.io_models.xml_models import QualifierClassification
#         from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
#         from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
#
#         config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
#
#         # Load and process prompt template
#         prompt_template_path = config_mgr.get( "prompt template for qualifier classification" )
#         prompt_template      = du.get_file_as_string( du.get_project_root() + prompt_template_path )
#
#         processor       = PromptTemplateProcessor()
#         prompt_template = processor.process_template( prompt_template, "qualifier classification" )
#         prompt          = prompt_template.format( utterance=qualifier )
#
#         # Call LLM
#         llm_spec_key = config_mgr.get( "llm spec key for qualifier classification" )
#         llm_client   = LlmClientFactory().get_client( llm_spec_key )
#         raw_response = llm_client.run( prompt )
#
#         # Parse structured XML response
#         return QualifierClassification.from_xml( raw_response )
#
#     except ( XMLParsingError, Exception ):
#         return None


# Minimum turn duration (seconds) to consider work "substantive"
MIN_TURN_DURATION_SECONDS = 10


def _should_ask_anything_else( last_assistant_message, session_id ):
    """
    Determine whether the stop hook should prompt "Anything else?"

    Two-signal gate:
        1. Empty last_assistant_message → no work done → skip
        2. Turn duration < threshold → trivial turn → skip

    Requires:
        - last_assistant_message is a string or None
        - session_id is a string

    Ensures:
        - Returns False if no substantive work was done
        - Returns True if both signals indicate real work
    """
    # Signal 1: No assistant output at all
    if not last_assistant_message or not last_assistant_message.strip():
        log_to_stream( "stop", {}, extra={
            "phase"  : "gate_skip",
            "reason" : "empty last_assistant_message"
        } )
        return False

    # Signal 2: Turn was too short
    elapsed = get_turn_elapsed_seconds( session_id )
    if elapsed is not None and elapsed < MIN_TURN_DURATION_SECONDS:
        log_to_stream( "stop", {}, extra={
            "phase"   : "gate_skip",
            "reason"  : "turn_too_short",
            "elapsed" : round( elapsed, 1 )
        } )
        return False

    return True


def _get_session_context( cwd ):
    """
    Read session topic from bridge file + git branch name.

    Requires:
        - cwd is a string path or None

    Ensures:
        - Returns (topic, branch) tuple
        - topic is a string or None (from bridge file's session_topic)
        - branch is a string or None (from git rev-parse)
        - Never raises exceptions
    """
    topic  = None
    branch = None

    # Session topic from bridge file
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import get_session_metadata
        meta  = get_session_metadata()
        topic = meta.get( "session_topic" )
    except Exception:
        pass

    # Git branch
    if cwd:
        try:
            import subprocess
            branch = subprocess.check_output(
                [ "git", "rev-parse", "--abbrev-ref", "HEAD" ],
                cwd=cwd, text=True, timeout=5
            ).strip()
        except Exception:
            pass

    return topic, branch


DEFAULT_IDLE_BEHAVIOR = "idle_announce"
_VALID_IDLE_BEHAVIORS = ( "none", "ask", "idle_announce" )


def _stop_hook_idle_behavior() -> str:
    """
    Read the three-way setting that decides what the Stop hook does on an idle stop.

    The setting is the lupin-app.ini key "stop hook idle behavior" in the [Lupin: Baseline] section.
    It is read through ConfigurationManager under redirect_stdout, because its banners would
    corrupt the JSON on stdout. The hook runs once per turn, so the parse cost is acceptable.

    Ensures:
        - returns one of _VALID_IDLE_BEHAVIORS
        - "none" takes no action and allows the stop silently
        - "ask" takes the legacy path: load_idle_settings, then _arm_idle_waiter
          or _ask_anything_else
        - "idle_announce" (the default) fires one low-priority idle status notify,
          then allows the stop; fleet liveness is tracked elsewhere
        - falls back to DEFAULT_IDLE_BEHAVIOR ("idle_announce") on any error, a
          missing key, or an unrecognized value
        - never raises; never writes to stdout
    """
    import contextlib
    import io
    try:
        with contextlib.redirect_stdout( io.StringIO() ):
            mgr   = ConfigurationManager(
                env_var_name = "LUPIN_CONFIG_MGR_CLI_ARGS",
                silent       = True,
                mute_splainer = True,
            )
            value = mgr.get( "stop hook idle behavior", default=DEFAULT_IDLE_BEHAVIOR, silent=True )
        value = str( value or DEFAULT_IDLE_BEHAVIOR ).strip().lower()
        return value if value in _VALID_IDLE_BEHAVIORS else DEFAULT_IDLE_BEHAVIOR
    except Exception:
        return DEFAULT_IDLE_BEHAVIOR


# ── Role-goal poke echo (role-goals Phase 2-3) ───────────────────────────────
# The compressed, role-selected "north-star goal" line APPENDED to the heartbeat
# self-poke reason so a session re-anchors on what it is ultimately trying to
# achieve, fresh every tick. The text lives as runtime config (retune live, no
# redeploy — D1); CANONICAL human-readable source: planning-is-prompting ->
# workflow/role-goals.md §"Injection: the poke echo". The config READ is IO and
# stays in this shell; the pure decision module only appends the injected string.
_GOAL_LINE_KEYS = {
    "manager"  : "heartbeat manager goal line",
    "worker"   : "heartbeat worker goal line",
    "agnostic" : "heartbeat role-agnostic goal line",
}


def _select_goal_role( session_id, bridge_role ):
    """
    Pick the role ("manager", "worker" or "agnostic") whose goal line the poke echoes.

    A role stamped on the bridge at spawn wins: "manager" gives the manager line and any other role gives "worker".
    Otherwise a declared fleet-roster manager (checked by _is_manager_persona) is "manager".
    Otherwise the result is "agnostic", the fallback when no role is known.

    Requires:
        - session_id is a string
        - bridge_role is the bridge meta "role" value (str) or None

    Ensures:
        - returns one of "manager" | "worker" | "agnostic"; never raises
        - the manager arm for a bridge role is defensive: the spawner only spawns
          worker roles, so a present role normally lands on the worker line
        - the roster check reuses the tested governance helper and fails open
    """
    role = ( bridge_role or "" ).strip().lower()
    if role == "manager":
        return "manager"
    if role:
        return "worker"
    try:
        from lupin_cli.claude_code.hooks.lib.subagent_governance import _is_manager_persona
        if _is_manager_persona( session_id ):
            return "manager"
    except Exception:
        pass
    return "agnostic"


def _heartbeat_goal_line( session_id, bridge_role ):
    """
    Read the goal line for the session's role from the configuration manager.

    The line is appended to the heartbeat self-poke. The read runs under redirect_stdout, like
    _stop_hook_idle_behavior, because the banners would corrupt the hook's stdout JSON channel.

    Requires:
        - session_id is a string
        - bridge_role is the bridge meta "role" value (str) or None

    Ensures:
        - returns the goal-echo string for the role _select_goal_role resolves, or
          "" on any error or missing key
        - an empty goal_line leaves the poke reason byte-identical to the output
          without goal lines, so a failed read never breaks the poke
        - never raises; never writes to stdout
    """
    import contextlib
    import io
    role_kind = _select_goal_role( session_id, bridge_role )
    key       = _GOAL_LINE_KEYS[ role_kind ]
    try:
        with contextlib.redirect_stdout( io.StringIO() ):
            mgr   = ConfigurationManager(
                env_var_name  = "LUPIN_CONFIG_MGR_CLI_ARGS",
                silent        = True,
                mute_splainer = True,
            )
            value = mgr.get( key, default="", silent=True )
        return str( value or "" ).strip()
    except Exception:
        return ""


def _board_sweep_line( session_id, live_owed=None ):
    """
    Resolve this seat's persona from the bridge and read its board-sweep ledger line.

    The gate is keyed on persona, not role. Two sweeping seats both resolve to "worker", so a
    role-keyed line would give both the same total. The seat with the smaller board would then
    stop early, believing it had finished.

    Requires:
        - session_id is a string
        - live_owed is this seat's current owed count, or None when unresolved. None means
          unknown, never zero: an unreachable store must not read as a clear board. The count
          is passed in because the tick already fetched it, while the ledger's frozen
          total_at_start goes stale as the board shrinks.

    Ensures:
        - returns the sweep gate sentence, or "" when this seat has no ledger
          (the normal state of every session that is not sweeping;
          output is identical to before the gate existed)
        - returns a loud line, never "", when a ledger exists but cannot be read: a gate
          that goes quiet because it could not read its own state is the failure it exists
          to prevent
        - a persona that cannot be resolved yields "": no seat, no ledger to address
        - an in-progress sweep ignores live_owed, because its frozen denominator
          is the floor that stops gaming; only the complete arm consults it
        - never raises; never writes to stdout (the hook's JSON channel)
    """
    try:
        persona = get_voice_persona( session_id ) or { }
        name    = persona.get( "name" )
        if not name: return ""
        return sweep_progress_line( name, live_owed=live_owed )
    except Exception:
        # Degrade-safe like _heartbeat_goal_line: a broken bridge read must never take the
        # poke down. This arm is the one place silence is accepted on an error, and only
        # because it means "could not identify the seat", not "could not read the ledger" —
        # the latter is handled loudly inside sweep_progress_line.
        return ""


def _idle_sentence( persona_name, owed_unknown=False, owed=False, total_owed=0 ) -> str:
    """
    Build the first-person idle status sentence used by the idle_announce behavior.

    The Stop idle-announce uses the same hold-aware verdict (_resolve_owed_state) as the
    Notification idle-beacon, so the two never disagree. Precedence: unknown first, then owed
    (work owed but no poke this Stop, for example when the poke cap halted poking), then idle.

    Ensures:
        - owed_unknown True gives "Owed status unknown." (unknown is not idle)
        - owed True gives "Idle, but N item(s) owed.", or "Idle, but work owed."
          when total_owed is 0 (owed via a referent-less signal)
        - the owed phrasing matches the Notification beacon
        - otherwise gives "Momentarily idle." (not owed)
    """
    if owed_unknown:
        return "Owed status unknown."
    if owed:
        if total_owed > 0:
            plural = "" if total_owed == 1 else "s"
            return f"Idle, but {total_owed} item{plural} owed."
        return "Idle, but work owed."
    return "Momentarily idle."


def _announce_idle( session_id, persona_name, owed_unknown=False, owed=False, total_owed=0, muted=False ):
    """
    Fire one low-priority, non-blocking idle status notify for idle_announce.

    The notify is fire-and-forget and low priority, so it never dings and never blocks the Stop.
    When the store was unreachable (owed_unknown True) the poke is suppressed, and the message
    must not claim nothing is owed. That would conflate store-down with count-zero.

    Ensures:
        - posts a low-priority AsyncNotificationRequest carrying _idle_sentence,
          stamped with this session's CC sender_id so it renders as the persona
        - owed_unknown False gives abstract "Heartbeat: idle — nothing owed."
        - owed_unknown True gives an abstract saying owed status is unknown because the
          task store is unreachable, that this is not idle, and to verify manually
          (with no "nothing owed" claim)
        - owed_unknown True and muted True gives the same not-idle verdict, named
          to its actual cause (pokes muted, lookup skipped) rather than blaming the
          store. Both mean we did not measure; only one is an outage, and an operator who
          muted the fleet should not be sent hunting a store that is fine
        - never raises and never blocks the Stop (try/except around the post)
    """
    if owed_unknown and muted:
        abstract = ( "Heartbeat: pokes MUTED (heartbeat.poke_output_enabled = false) — the "
                     "obligations lookup did not run, so owed status is UNKNOWN, not clear. "
                     "Muting buys silence, not an all-clear." )
    elif owed_unknown:
        abstract = "Heartbeat: owed status unknown (task store unreachable) — NOT idle; verify manually."
    elif owed:
        detail   = f"{total_owed} owed referent(s)" if total_owed > 0 else "work owed (referent-less signal)"
        abstract = f"Heartbeat: idle but NOT done — {detail} (hold-aware verdict, e.g. poke-cap reached). Stop + beacon agree."
    else:
        abstract = "Heartbeat: idle — nothing owed."
    try:
        request = AsyncNotificationRequest(
            message   = _idle_sentence( persona_name, owed_unknown=owed_unknown, owed=owed, total_owed=total_owed ),
            priority  = NotificationPriority.LOW,
            sender_id = build_sender_id_for_cc( session_id ),
            abstract  = abstract,
        )
        notify_user_async( request )
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase"      : "idle_announce_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )


def _announce_muted( session_id, persona_name, mute_message ):
    """
    Fire one low-priority beacon for a muted stop, carrying the substitute text verbatim.

    While pokes are muted (heartbeat.poke_output_enabled = false) the operator must see what the workers see.
    A bare idle card would hide the substitute, so the operator could not tell a muted fleet from a quiet one.
    So the beacon names the mute state and puts the configured message, unedited, in the abstract.

    Requires:
        - mute_message is the non-empty configured substitute (the empty or None
          spelling never reaches here; it is the full-silence path)

    Ensures:
        - posts a low-priority AsyncNotificationRequest stamped with this
          session's CC sender_id, so it renders as the persona
        - the abstract carries the substitute verbatim (what workers receive)
        - never raises and never blocks the Stop (mirrors _announce_idle)
    """
    who = persona_name or "A worker"
    try:
        request = AsyncNotificationRequest(
            message   = f"{who} stopped — pokes muted, default message injected.",
            priority  = NotificationPriority.LOW,
            sender_id = build_sender_id_for_cc( session_id ),
            abstract  = ( "Heartbeat: pokes MUTED (heartbeat.poke_output_enabled = false) — no "
                          "live-obligations lookup ran. Injected verbatim to this worker:\n\n"
                          f"{mute_message}" ),
        )
        notify_user_async( request )
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase"      : "muted_announce_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )


def _poke_sentence( persona_name, owed_count ) -> str:
    """
    Build the third-person poke breadcrumb sentence for the user's notification card.

    The form is "<persona> stopped — <specifics>, poked." The function is pure.

    Requires:
        - persona_name is a string or None
        - owed_count is an int >= 0: the total owed referents across all fired
          signals (task items, outstanding delegations and unanswered inbound),
          not just the task count, so a delegation-only poke is not misread as
          self-declared; 0 means a hold-declared owed poke with no referents

    Ensures:
        - owed_count > 0 gives "<who> stopped — N owed item(s), poked."
        - owed_count == 0 gives "<who> stopped — work owed (self-declared), poked."
        - uses "A worker" when the persona name is missing
    """
    who = persona_name or "A worker"
    if owed_count > 0:
        plural = "" if owed_count == 1 else "s"
        return f"{who} stopped — {owed_count} owed item{plural}, poked."
    return f"{who} stopped — work owed (self-declared), poked."


def _announce_poke( session_id, persona_name, owed_count, abstract=None ):
    """
    Fire one low-priority, non-blocking poke breadcrumb to the user's card.

    Low priority matters twice. The client renders it to the card without speech, so it composes
    with the silent decision:block poke without double speech, and it never dings. De-dup rides
    the poke cap: each breadcrumb is a real poke event and the cap bounds them per session.

    Requires:
        - abstract is the receipts string (signals, referents and the verbatim poke
          text) composed degrade-safe by the caller, or None to use the generic line
        - the spoken message stays short for TTS; all receipt detail rides the
          abstract (UI card only, never spoken)

    Ensures:
        - posts a low-priority AsyncNotificationRequest carrying _poke_sentence,
          stamped with this session's CC sender_id so it renders as the persona
        - never raises and never blocks the Stop (try/except; mirrors _announce_idle)
    """
    try:
        request = AsyncNotificationRequest(
            message   = _poke_sentence( persona_name, owed_count ),
            priority  = NotificationPriority.LOW,
            sender_id = build_sender_id_for_cc( session_id ),
            abstract  = abstract or "Heartbeat: stopped with work owed — self-poke fired.",
        )
        notify_user_async( request )
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase"      : "poke_announce_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )


# ── §4 poke-abstract receipts (Rick 2026-06-10) ──────────────────────────────
# The breadcrumb's spoken message stays short; the ABSTRACT carries the receipts:
# (a) the oracle's fired signals + their actual referents (task subjects,
# delegation session names, sender+qid for inbound), and (b) the verbatim poke
# text injected into the worker. Composition is PURE; the caller wraps it
# degrade-safe (any failure ⇒ None ⇒ the generic fallback line). Capped so a
# runaway list can never bloat the card.
_POKE_ABSTRACT_HEADER = "Heartbeat: stopped with work owed — self-poke fired."
_MAX_RECEIPT_ITEMS    = 8          # per-list cap; overflow folds into "+N more"
_MAX_ABSTRACT_CHARS   = 4000       # ~4KB ceiling on the whole abstract


def _receipt_lines( label, items ):
    """A labeled bullet list, truncated at _MAX_RECEIPT_ITEMS with '+N more'. Pure."""
    shown = items[ :_MAX_RECEIPT_ITEMS ]
    lines = [ label ]
    lines.extend( f"  • {it}" for it in shown )
    extra = len( items ) - len( shown )
    if extra > 0:
        lines.append( f"  • …+{extra} more" )
    return lines


def _format_inbound( q ):
    """'from <sender> (qid <short>)' for one open-inbound entry. Pure."""
    sender = q.get( "sender" ) or "unknown"
    qid    = q.get( "question_id" )
    short  = qid[ :8 ] if isinstance( qid, str ) else "?"
    return f"from {sender} (qid {short})"


def _compose_poke_abstract( verdict, owed_task_subjects, delegations, open_inbound, stale_inbound, poke_text ):
    """
    Build the receipts abstract for the poke breadcrumb from its signals and referents.

    The function is pure; the caller wraps it degrade-safe. It lists the fired signals with their
    referents and the verbatim poke text, and caps the whole string at about _MAX_ABSTRACT_CHARS.

    Requires:
        - verdict is the evaluate_work_owed dict (or None)
        - owed_task_subjects is a list[str]; delegations is a list[dict] with
          session_name/session_id; open_inbound and stale_inbound are list[dict]
          (_format_inbound shape)
        - poke_text is the verbatim reason injected into the worker (or None)

    Ensures:
        - returns a non-empty string headed by _POKE_ABSTRACT_HEADER
        - stale_inbound (aged out, not owed) is shown under its own "review, not
          owed" heading, so the reader can triage backlog without it inflating
          the owed count
        - truncates each referent list with "+N more" and the whole abstract at
          the character ceiling
    """
    parts   = [ _POKE_ABSTRACT_HEADER ]
    signals = ( verdict or { } ).get( "signals" ) or [ ]
    if signals:
        parts.append( "Signals (strongest first): " + ", ".join( signals ) )
    if owed_task_subjects:
        parts.extend( _receipt_lines( "Owed Task items:", owed_task_subjects ) )
    if delegations:
        names = [ ( d.get( "session_name" ) or d.get( "session_id" ) or "?" ) for d in delegations ]
        parts.extend( _receipt_lines( "Outstanding delegations (live workers):", names ) )
    if open_inbound:
        parts.extend( _receipt_lines( "Unanswered inbound questions:",
                                      [ _format_inbound( q ) for q in open_inbound ] ) )
    if stale_inbound:
        parts.extend( _receipt_lines( "Stale inbound (review, not owed):",
                                      [ _format_inbound( q ) for q in stale_inbound ] ) )
    if poke_text:
        parts.append( "" )
        parts.append( "Poke text injected into the worker:" )
        parts.append( poke_text )
    text = "  \n".join( parts )
    if len( text ) > _MAX_ABSTRACT_CHARS:
        text = text[ :_MAX_ABSTRACT_CHARS - 1 ] + "…"
    return text


def _build_poke_abstract_safe( verdict, task_state, transcript_path, delegations, open_inbound, stale_inbound, result ):
    """
    Resolve owed task subjects and compose the poke abstract, returning None on any error.

    This degrade-safe wrapper around _compose_poke_abstract replays the transcript for task
    subjects keyed to the owed task ids. A failure gives None, and the breadcrumb falls back to
    the generic line. It never raises, so an enrichment error never breaks the poke.

    Ensures:
        - returns the composed abstract string on success, or None on any error
        - shows stale_inbound (aged out, review not owed) next to the owed
          referents, so backlog is visible without inflating the owed count
        - replays subjects only when at least one task is owed; pokes driven only
          by delegations or inbound skip the extra transcript pass
    """
    try:
        owed_ids = [ tid for tid, status in task_state.items() if status in OWED_STATUSES ]
        subjects = replay_task_subjects( transcript_path ) if owed_ids else { }
        owed_task_subjects = [ ( subjects.get( tid ) or f"task {tid}" ) for tid in owed_ids ]
        poke_text = ( result.get( "hook_output" ) or { } ).get( "reason" )
        return _compose_poke_abstract( verdict, owed_task_subjects, delegations, open_inbound, stale_inbound, poke_text )
    except Exception as e:
        log_to_stream( "stop", { }, extra={
            "phase"      : "poke_abstract_error",
            "error"      : str( e ),
        } )
        return None


def _has_pending_voice( session_id ) -> bool:
    """
    Peek, without consuming, whether voice input is buffered for this session.

    The heartbeat poke must not fire while voice input is pending, because voice always wins.
    The buffer is not drained here: draining acknowledges the messages, and this branch cannot inject them.
    The peek only suppresses the poke and leaves the buffer to its real consumer.

    Ensures:
        - returns True iff the session's voice-buffer file exists
        - never raises: any path or IO error returns False, which fails open to
          the poke's own work-owed oracle gate
    """
    try:
        return get_buffer_path( session_id ).exists()
    except Exception:
        return False


def _arm_idle_waiter( session_id, last_assistant_message, cwd ):
    """
    Spawn a deferred-ask waiter instead of firing "Anything else?" immediately.

    The waiter sleeps `backoff_minutes[backoff_index]` minutes (from settings.idle_detection), then re-checks the bridge
    for reset signals. If still idle, it fires the same prompt as the legacy path. The backoff_index is read from the
    bridge and kept across Stop fires; UserPromptSubmit resets it to 0. See: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md

    Requires:
        - session_id is a non-empty string
        - last_assistant_message is a string or None (for gist computation)
        - cwd is a string path or None

    Ensures:
        - Kills any prior waiter for this session (idempotent)
        - Computes the gist now and stores it on the bridge, so the waiter need not
          call Gister at wake time
        - Bumps last_interaction_at, stores gist + waiter spawn metadata in bridge
        - Spawns detached idle_waiter.py subprocess
        - Returns the spawned waiter PID, or None on spawn failure
        - Never raises — spawn failure logs and returns None

    Args:
        session_id            : CC session ID
        last_assistant_message: Claude's last response text (for gist)
        cwd                   : Working dir for git-branch resolution

    Returns:
        int or None: Spawned waiter PID, or None on failure
    """
    import datetime
    import subprocess
    from pathlib import Path

    # Pre-compute gist while we have last_assistant_message (waiter doesn't)
    gist = _shared_summarize_task( last_assistant_message )

    # Read current backoff_index — preserved across Stop fires until UserPromptSubmit
    # resets it to 0. UserPromptSubmit fires only on user activity; consecutive
    # Stops without user activity should resume the backoff schedule, not restart it.
    state         = get_idle_detection( session_id ) or { }
    current_index = state.get( "backoff_index", 0 ) or 0

    # Resolve CC PID from bridge (set by SessionStart). Fallback to hook's
    # grandparent walk if bridge doesn't have it.
    meta   = get_session_metadata()
    cc_pid = meta.get( "cc_pid" ) or os.getppid()

    # Kill any stale waiter so we don't end up with parallel asks
    kill_idle_waiter( session_id )

    # Bump last_interaction_at + store gist + carry cwd for the waiter's
    # session-context resolution at wake-time
    set_idle_detection_field(
        session_id,
        last_interaction_at = datetime.datetime.now().astimezone().isoformat( timespec="seconds" ),
        last_task_gist      = gist,
        last_task_cwd       = cwd,
    )

    # Spawn the waiter — mirrors register_session.py:_spawn_listener pattern
    short    = session_id[ :8 ] if session_id else "unknown"
    log_path = sessions_dir() / f"cc-idle-waiter-{short}.log"   # row 8ccc20ab: the one seam

    cmd = [
        sys.executable, "-m", "lupin_cli.claude_code.hooks.lib.idle_waiter",
        "--session-id"   , session_id,
        "--cc-pid"       , str( cc_pid ),
        "--backoff-index", str( current_index ),
    ]
    # Test-mode hook: if env tells us to use a short sleep, propagate it
    test_sleep = os.environ.get( "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS" )
    if test_sleep:
        cmd.extend( [ "--sleep-secs", test_sleep ] )

    env = os.environ.copy()
    env[ "PYTHONUNBUFFERED" ] = "1"
    if _src_path and _src_path not in env.get( "PYTHONPATH", "" ):
        env[ "PYTHONPATH" ] = _src_path + ":" + env.get( "PYTHONPATH", "" )
    if cwd:
        env[ "CC_HOOK_CWD" ] = cwd

    try:
        log_file = open( log_path, "a" )
    except OSError:
        log_file = subprocess.DEVNULL

    try:
        proc = subprocess.Popen(
            cmd,
            stdout            = log_file if log_file is not subprocess.DEVNULL else subprocess.DEVNULL,
            stderr            = log_file if log_file is not subprocess.DEVNULL else subprocess.DEVNULL,
            env               = env,
            start_new_session = True,
        )
        log_to_stream( "stop", {}, extra={
            "phase"         : "idle_waiter_armed",
            "waiter_pid"    : proc.pid,
            "backoff_index" : current_index,
            "cc_pid"        : cc_pid,
        } )
        return proc.pid
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase" : "idle_waiter_spawn_failed",
            "error" : str( e ),
        } )
        return None


def _ask_anything_else( session_id, last_assistant_message=None, cwd=None ):
    """
    Ask the user "Anything else?" via notify_user_sync with a 5-minute timeout.

    Returns the stop hook JSON to emit: block dict if user wants to continue,
    empty dict if user says no / timeout / error.

    Requires:
        - session_id is a string for sender_id resolution
        - last_assistant_message is a string or None
        - cwd is a string path or None (for session context resolution)

    Ensures:
        - Returns dict suitable for emit_json()
        - Notification message includes Gister summary when available
        - Qualifier is classified as question or instruction via LLM
        - "yes" blocks stop (with or without qualifier)
        - "no + qualifier" blocks stop and passes the qualifier as new work
        - Plain "no", timeout, error → allows stop ({})
        - On any exception, returns {} (allow stop gracefully)
    """
    # `phase` names WHERE we got to, so the backstop below can say which step broke
    # instead of emitting a bare exception string. Every callable in this body is
    # already total (see the handler's comment), so a phase that appears in a card is
    # naming OUR glue, not the thing it called.
    phase     = "build_sender_id"
    sender_id = None      # bound BEFORE the try: the handler reads it, and a throw in
                          # build_sender_id_for_cc would otherwise make the handler
                          # itself raise NameError — a backstop that fails is no backstop
    try:
        sender_id = build_sender_id_for_cc( session_id )

        phase = "summarize_task"
        gist = _summarize_task( last_assistant_message )
        if gist:
            message = f'I\'m finished *"...{gist}"*. Is there anything else you want me to do?'
        else:
            message = "I've finished the current task. Is there anything else you'd like me to do?"

        # Build abstract with session-level context
        phase = "session_context"
        topic, branch = _get_session_context( cwd )
        parts = []
        if topic:
            parts.append( f"**Session**: {topic}" )
        if branch:
            parts.append( f"**Branch**: `{branch}`" )
        abstract = "  \n".join( parts ) if parts else None

        phase   = "build_request"
        request = NotificationRequest(
            message                  = message,
            response_type            = ResponseType.YES_NO,
            priority                 = NotificationPriority.MEDIUM,
            timeout_seconds          = 60,
            response_default         = "no",
            title                    = "Stop hook: Anything else?",
            sender_id                = sender_id,
            abstract                 = abstract,
            display_qualifier_widget = True
        )

        phase    = "notify_sync"
        response = notify_user_sync( request )

        phase = "parse_response"
        answer, qualifier = extract_qualifier_comment( response.response_value )

        print( f"[STOP] response: exit_code={response.exit_code}, value='{response.response_value}'", file=sys.stderr )
        print( f"[STOP] parsed: answer='{answer}', qualifier='{qualifier}'", file=sys.stderr )

        log_to_stream( "stop", {}, extra={
            "phase"     : "ask_anything_else",
            "answer"    : answer,
            "qualifier" : qualifier,
            "raw_value" : response.response_value,
            "exit_code" : response.exit_code
        } )

        if answer == "yes":
            if qualifier:
                inject_qualifier_via_tmux( session_id, qualifier )
                log_to_stream( "stop", {}, extra={
                    "phase"  : "qualifier_tmux_inject",
                    "answer" : answer,
                    "text"   : qualifier
                } )
                return build_stop_block( f"User wants to continue. Qualifier injected via tmux: {qualifier}" )
            else:
                reason = "The user wants to continue working. Ask them what they'd like done next."
                log_to_stream( "stop", {}, extra={
                    "phase"  : "qualifier_block",
                    "answer" : answer,
                    "reason" : reason[ :120 ]
                } )
                return build_stop_block( reason )

        if answer == "no" and qualifier:
            inject_qualifier_via_tmux( session_id, qualifier )
            log_to_stream( "stop", {}, extra={
                "phase"  : "qualifier_tmux_inject",
                "answer" : answer,
                "text"   : qualifier
            } )
            return build_stop_block( f"User said no but attached work. Qualifier injected via tmux: {qualifier}" )

        # Plain "no", timeout, error → allow stop
        return {}

    except Exception as e:
        # ⚠️ THE COMMENT HERE USED TO READ "Server down, network error, import error →
        # allow stop gracefully". TWO OF THOSE THREE ARE FALSE, and the sentence was
        # load-bearing: it is why a reviewer concluded this handler cannot tell an
        # outage from a bug and priced a fix at "work at every raise site"
        # (row e3dd1df2). Measured 2026-08-30:
        #
        #   · notify_user_sync is TOTAL. It catches ConnectionError / Timeout /
        #     RequestException / bare Exception and RETURNS a NotificationResponse
        #     (notify_user_sync.py:457-495; its docstring says "No exceptions raised").
        #     A dead :7999 therefore returns response_value=None, extract_qualifier_comment
        #     short-circuits, and we fall out of the `no` path. IT NEVER REACHES HERE.
        #   · Every other callable in the try body is total too — build_sender_id_for_cc,
        #     _summarize_task, _get_session_context, log_to_stream and
        #     inject_qualifier_via_tmux all document "returns None / never raises".
        #   · And send_tts rides notify_user_async to THE SAME SERVER notify_user_sync
        #     would have failed to reach, so an announce-on-outage path could not
        #     announce an outage even if one did arrive.
        #
        # ⇒ This is a BACKSTOP over a body whose components already swallow their own
        # failures. What reaches it is OUR OWN GLUE breaking — a pydantic ValidationError
        # building the request, an AttributeError, an ImportError. "An exception arrived"
        # and "we have a bug" are the same statement at this site, which is exactly the
        # traffic the fleet's liveness path should be loud about. KEPT ON PURPOSE.
        #
        # ⚠️ TWO DIFFERENT NARROWINGS GET ASKED FOR HERE, AND ONLY ONE IS ABOUT TYPES.
        # This note answered the CATCH question and left the BODY question open, so the
        # request came back on 2026-09-02 phrased as "the try spans ~80 lines, narrow it
        # to the code that can genuinely throw." Both are refused, for the SAME reason,
        # and it is worth writing down once so the ask does not return a third time.
        #
        # It is not narrowed to specific types because the caller has NO guard of its
        # own: a raise here kills the hook process before emit_json runs and the
        # session's Stop goes unanswered. Verified 2026-09-02 rather than assumed --
        # the sole call site sits at `result = _ask_anything_else( ... )` immediately
        # above its `emit_json( result )`, outside the nearest enclosing try (which
        # closes over the idle-settings parse and ends before it).
        #
        # And the BODY is not narrowed for the same reason read forwards. The paragraph
        # above establishes that every callable in it is total, so the only thing that
        # can raise is OUR OWN GLUE -- which is spread across all 80 lines rather than
        # concentrated in a few. Wrapping "only the code that can throw" would therefore
        # mean wrapping nearly all of it anyway, while leaving whatever fell outside able
        # to kill the process. A backstop that covers most of a function is not a
        # backstop. THE SPAN IS THE FEATURE: this try exists to guarantee that control
        # reaches emit_json, and that guarantee is exactly as wide as the code before it.
        #
        # ⇒ What WAS narrowed is the only axis that could be: the report. The catch names
        # the PHASE and the session instead of emitting a bare exception string.
        session_tag = ( session_id or "" )[ :8 ]
        send_tts(
            f"Stop hook defect in {phase} for session {session_tag}: "
            f"{type( e ).__name__}: {e}",
            sender_id = sender_id,
        )
        log_to_stream( "stop", {}, extra={
            "phase"      : "ask_anything_else_error",
            "failed_at"  : phase,
            "session_id" : session_tag,
            "error_type" : type( e ).__name__,
            "error"      : str( e ),
        } )
        return {}


# ── Phase 4 — Layer 3 Stop-hook auto-narrate ──────────────────────────────────
#
# Per src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md
# Phase 4: when conv mode is active and Claude's last assistant turn ended
# WITHOUT a notify() call, synthesize one so the user (listening at distance)
# hears the response. Safety net for the case where Claude's cached belief
# about conv mode drifts and it writes console-only.

import json as _json   # local alias to avoid shadowing


def _read_last_assistant_message( transcript_path ):
    """
    Read a transcript JSONL file and return its last assistant-role message dict.

    Transcripts are line-delimited JSON. Each message has `type` ("user" or
    "assistant") and `message.content`, a list of content blocks. The function
    iterates all lines and remembers the most recent assistant message.

    Requires:
        - transcript_path is a non-empty string path

    Ensures:
        - Returns the last assistant message dict or None
        - Returns None on missing file, parse error, or no assistant
        - Never raises

    Args:
        transcript_path: Path to JSONL transcript file

    Returns:
        dict or None: Last assistant message
    """
    if not transcript_path or not os.path.isfile( transcript_path ):
        return None
    last_assistant = None
    try:
        with open( transcript_path ) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    msg = _json.loads( line )
                except _json.JSONDecodeError:
                    continue
                if msg.get( "type" ) == "assistant":
                    last_assistant = msg
    except OSError:
        return None
    return last_assistant


def _turn_has_notify_call( assistant_msg ):
    """
    Report whether the assistant message holds an mcp__cosa-voice__notify tool call.

    If it does, Claude narrated the turn itself and auto-narrate must pass through.

    Requires:
        - assistant_msg is a dict from _read_last_assistant_message

    Ensures:
        - Returns True if any content block has type="tool_use" and
          name=="mcp__cosa-voice__notify"
        - Returns False otherwise (incl. on shape mismatch / missing fields)
        - Never raises

    Args:
        assistant_msg: Assistant message dict

    Returns:
        bool: Whether Claude self-narrated
    """
    try:
        content = assistant_msg.get( "message", { } ).get( "content", [ ] )
        for block in content:
            if isinstance( block, dict ):
                if block.get( "type" ) == "tool_use" and block.get( "name" ) == "mcp__cosa-voice__notify":
                    return True
    except Exception:
        pass
    return False


def _extract_narratable_text( assistant_msg ):
    """
    Extract speakable text from an assistant message, without code blocks.

    The function concatenates the text blocks, strips fenced code blocks and trims
    whitespace.

    Requires:
        - assistant_msg is a dict from _read_last_assistant_message

    Ensures:
        - Returns concatenated text from all "text" content blocks
        - Fenced code blocks stripped via strip_fenced_code_blocks
          (imported from lupin_mcp.cosa_voice_mcp, the same implementation the
          MCP server uses)
        - Returns empty string if no text content or on shape mismatch

    Args:
        assistant_msg: Assistant message dict

    Returns:
        str: Narratable text (may be empty)
    """
    try:
        content = assistant_msg.get( "message", { } ).get( "content", [ ] )
        parts   = [ ]
        for block in content:
            if isinstance( block, dict ) and block.get( "type" ) == "text":
                text = block.get( "text", "" )
                if text:
                    parts.append( text )
        joined = "\n\n".join( parts ).strip()
        if not joined:
            return ""
        try:
            from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks
            joined = strip_fenced_code_blocks( joined )
        except Exception:
            pass  # Stripping is best-effort
        return joined.strip()
    except Exception:
        return ""


def _try_auto_narrate( session_id, payload ):
    """
    In conversation mode, speak the last assistant turn via send_tts if it had no notify call.

    This is the third-layer safety net for conversation mode.
    See: src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md

    Requires:
        - session_id is a non-empty string
        - payload is a dict (Stop-hook payload)
        - conv mode is already verified active by the caller

    Ensures:
        - Reads transcript_path from payload (or bridge metadata fallback)
        - If last assistant turn already contains notify() ToolUseBlock,
          pass through (Claude self-narrated)
        - If last_autonarrated_turn_id matches current turn id, pass through
          (already narrated this turn — re-fire dedup)
        - Otherwise: extract narratable text, strip code, call send_tts
          with priority='high' + suppress_ding=True (conv-mode params),
          stamp the turn id in the bridge for future dedup
        - Never raises (failures are logged via log_to_stream)
    """
    transcript_path = payload.get( "transcript_path" ) or ""
    if not transcript_path:
        try:
            meta            = get_session_metadata()
            transcript_path = meta.get( "transcript_path" ) or ""
        except Exception:
            transcript_path = ""
    if not transcript_path:
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "no transcript_path",
            "session_id" : session_id,
        } )
        return

    last_msg = _read_last_assistant_message( transcript_path )
    if not last_msg:
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "no assistant message in transcript",
            "session_id" : session_id,
        } )
        return

    if _turn_has_notify_call( last_msg ):
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "claude self-narrated",
            "session_id" : session_id,
        } )
        return

    turn_id = last_msg.get( "uuid" ) or last_msg.get( "id" ) or ""
    if turn_id and get_last_autonarrated_turn_id( session_id ) == str( turn_id ):
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "already auto-narrated this turn",
            "session_id" : session_id,
            "turn_id"    : turn_id,
        } )
        return

    narration = _extract_narratable_text( last_msg )
    if not narration:
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_skip",
            "reason"     : "no narratable text",
            "session_id" : session_id,
        } )
        return

    # Synthesize narration with conv-mode params
    try:
        send_tts(
            narration,
            priority      = "high",
            suppress_ding = True
        )
        if turn_id:
            set_last_autonarrated_turn_id( session_id, turn_id )
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_fired",
            "session_id" : session_id,
            "turn_id"    : turn_id,
            "char_count" : len( narration ),
        } )
    except Exception as e:
        log_to_stream( "stop", { }, extra={
            "phase"      : "auto_narrate_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )


def _notify_cap_reached( session_id ):
    """
    Log that the heartbeat poke cap was reached, for observability only.

    The record is log-only. A user-facing async notify is deferred. The only sync hook primitive is
    notify_user_sync. It blocks on the server response and would hang the Stop hook.
    log_to_stream is non-blocking and needs no server. Its records can be searched in the io/claude_code_hooks/ captures.

    Requires:
        - session_id is a string

    Ensures:
        - Emits a "heartbeat_cap_reached" log record carrying session_id and
          poke_count (searchable); never raises, never blocks the stop
    """
    log_to_stream( "stop", {}, extra={
        "phase"      : "heartbeat_cap_reached",
        "session_id" : session_id,
        "poke_count" : get_poke_count( session_id ),
        # v1.1: also fire a user-facing async notify here (§0 #6) — deferred;
        # notify_user_sync is SSE-blocking and cannot be used in a Stop hook.
    } )


def _emit_genuine_idle( session_id, persona_name, cap ):
    """
    Emit the idle declaration beacon, only on the transition into idle.

    Called only when this Stop is idle (not owed and an empty task set). De-dup is delegated to
    heartbeat_events.is_idle_transition, so a quiet streak writes one beacon, not one per Stop.
    The beacon is fire-and-forget: a write or read failure never breaks the poke path.

    Requires:
        - session_id is a string
        - persona_name is a string or None
        - cap is the per-session poke-cap int

    Ensures:
        - Appends one outcome="idle" event iff this is the transition into idle
        - work_owed=False (idle); no reason
        - Never raises, never blocks the stop
    """
    try:
        if heartbeat_events.is_idle_transition( session_id ):
            heartbeat_events.emit_outcome(
                session_id,
                persona_name,
                heartbeat_events.EVENT_IDLE,
                get_poke_count( session_id ),
                cap,
                work_owed = False,
                awaiting  = None,
            )
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase"      : "heartbeat_idle_emit_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )


def _dm_topic_for( persona_name ):
    """
    Derive the commons DM-topic name ("dm-<slug>") for a persona.

    The slug comes from the shared `persona_slug` root, so it ignores accents and agrees with the store's
    canonical persona key: "Mr. Radio" gives "dm-mr_radio" and "María" gives "dm-maria".
    The separator "_" keeps the `dm-<persona>` topic-file convention (spaces become underscores).

    Requires:
        - persona_name is a string or None

    Ensures:
        - Returns "dm-<slug>" matching the server-side topic pattern
        - Accent/punctuation in the persona collapses to the canonical form
    """
    from lupin_mcp.persona_normalization import persona_slug
    return f"dm-{persona_slug( persona_name, sep='_' )}"


def _gather_outstanding_delegations( session_id ):
    """
    List this manager's spawned workers that are still alive and not yet reaped.

    An alive, unreaped child is owed work, so the manager must never idle-announce while workers are out.
    The lineage manifest (spawned-<session_id>.json, written by the spawner and pruned by `dismiss_sessions`)
    names the child tmux sessions. They are intersected with find_active_voice_persona_sessions, the arbiter's liveness.

    Requires:
        - session_id is this session's (stable) id string

    Ensures:
        - Returns [ { "session_name", "session_id" }, ... ] for each manifest
          child whose bridge is live; [] for non-managers (no manifest)
        - when all children are dead or reaped the result is [], so no delegation
          signal fires and idle is allowed
        - Any error returns []; never raises, never blocks the Stop
        - The bridge scan runs only when the manifest is non-empty, so workers
          pay a single cheap manifest stat per Stop
    """
    try:
        import json
        from lupin_mcp.session_spawner import _manifest_path, _read_manifest
        names = { r.get( "session_name" )
                  for r in _read_manifest( _manifest_path( session_id ) )
                  if isinstance( r, dict ) and r.get( "session_name" ) }
        if not names:
            return [ ]
        alive = [ ]
        for path, child_sid, _persona in find_active_voice_persona_sessions():
            try:
                with open( path ) as f:
                    bridge = json.load( f )
            except ( OSError, ValueError ):
                continue
            tmux = bridge.get( "tmux_session" ) if isinstance( bridge, dict ) else None
            if tmux in names:
                alive.append( { "session_name": tmux, "session_id": child_sid } )
        return alive
    except Exception:
        return [ ]


def _is_same_session( entry_sid, session_id ):
    """
    Match two session ids when either is a prefix of the other.

    Commons entries carry short 8-character ids while the hook holds the full
    stable uuid. This mirrors the arbiter and resolver matchers.

    Ensures:
        - True when either id equals or is a prefix of the other; False if
          either is falsy
    """
    if not entry_sid or not session_id:
        return False
    return ( entry_sid == session_id
             or entry_sid.startswith( session_id )
             or session_id.startswith( entry_sid ) )


def _gather_unanswered_inbound_questions( session_id ):
    """
    Find inbound commons DMs this session has not handled, split into owed and stale.

    The signal covers any directed message on this persona's dm-<persona> topic, not authored by this session,
    that this session has not handled. It feeds the oracle's unanswered_inbound_question signal.
    Persona names are pooled and reused, so the topic holds prior holders' briefs.

    Requires:
        - session_id is this session's (stable) id string

    Ensures:
        - Returns { "owed": [ {question_id, ts, sender}, ... ],
                    "stale": [ {question_id, ts, sender}, ... ] }
        - handled means this session posted a threaded reply (a commons entry it
          authored whose metadata.in_reply_to equals that DM's question_id); an
          unhandled DM, read or not, question or assignment, is owed work
        - tenure floor: only DMs stamped at or after this session's
          voice_persona.assigned_at count; a missing assigned_at disables the floor,
          which biases toward poking, and the poke cap bounds the cost
        - four clears apply: (a) expect_reply=False inbound is never owed, since acks,
          verdicts and status pings demand no threaded reply; (b) a threaded reply by
          this session clears the qid; (c) a qid in this session's
          .heartbeat-acked-<sid>.json ledger counts as looked at and is subtracted;
          (e) a still-unhandled qid older than INBOUND_STALE_AFTER_SECONDS is stale
        - owed holds fresh, unhandled, reply-expected, unacked inbound; stale is the
          same set cut by age, shown for review in the receipts and never owed
        - sender is the originating session id, used only for the poke-abstract receipt
        - qid-less entries are excluded as untrackable: they cannot be thread-matched,
          and every send_to or ask_async DM carries one
        - Entries authored by this session never count as inbound
        - Returns {"owed":[],"stale":[]} when the session has no persona, no
          LUPIN_ROOT, or no DM topic, and on any error (never raises, never
          blocks the Stop)
    """
    empty = { "owed": [ ], "stale": [ ] }
    try:
        persona = get_voice_persona( session_id )
        name    = persona.get( "name" ) if isinstance( persona, dict ) else None
        if not name:
            return empty
        commons_root = os.environ.get( "LUPIN_ROOT" )
        if not commons_root:
            return empty
        from lupin_mcp.commons_store import CommonsStore
        entries = CommonsStore( commons_root ).read( _dm_topic_for( name ), limit=50 )

        tenure_floor = persona.get( "assigned_at" )    # ISO-8601 str or None
        acked        = read_acked_qids( session_id )   # (c) bulk-marked "looked at"
        # "Handled" keys: in_reply_to of entries THIS session authored.        (b)
        handled = { ( e.get( "metadata" ) or { } ).get( "in_reply_to" )
                    for e in entries
                    if isinstance( e, dict )
                    and _is_same_session( e.get( "sender_session_id" ), session_id ) }
        candidates = [ ]
        for e in entries:
            if not isinstance( e, dict ):
                continue
            if _is_same_session( e.get( "sender_session_id" ), session_id ):
                continue                                 # my own post — not inbound
            md  = e.get( "metadata" ) or { }
            qid = md.get( "question_id" )
            if not qid:
                continue                                 # untrackable (no thread key)
            if md.get( "expect_reply" ) is False:        # (a) fire-and-forget — never owed
                continue
            if qid in acked:                             # (c) looked-at ledger
                continue
            ts = e.get( "ts" )
            # ISO-8601 strings in one zone compare lexicographically.
            if tenure_floor and isinstance( ts, str ) and ts < tenure_floor:
                continue
            if qid in handled:                           # (b) my threaded reply cleared it
                continue
            candidates.append( {
                "question_id" : qid,
                "ts"          : ts,
                "sender"      : e.get( "sender_session_id" ),   # for the poke-abstract receipt
            } )
        owed, stale = partition_inbound_by_age( candidates, time.time() )   # (e) age-out
        return { "owed": owed, "stale": stale }
    except Exception:
        return empty


# ── Spine Step-2 (store-canonical task management) store-count seam ───────────
# STORE_OWED_STATUSES was DELETED here on 2026-07-19 (PARKED-STATUS). It named
# the owed set locally, and had already forked into 4 copies (here,
# task_store_drain.py, the arbiter, rules.py). The owed set now lives SERVER-side
# behind query_owed's `owed_only=true`: queued U in_progress U (parked AND NOT
# park-active). Deleted rather than re-pointed — a constant that no longer exists
# cannot drift, and a status tuple held HERE could neither see a park-expiry
# rejoin (an expired parked row still reads status="parked") nor avoid
# double-counting one across a per-status loop.
# Membership is otherwise UNCHANGED: blocked / claimed / review are still not
# owed to this reader. Design: src/rnd/v0.1.9/2026.07.19-parked-status-board-hygiene.md


def _owed_count_from_store( session_id ):
    """
    Resolve this session's owed-row count from the unified task store.

    It replaces the transcript-replay owed source when the store source is on. The query is scoped by owner
    only: the canonical persona key, or "unknown" when the bridge has none. There is no project filter.
    A seat in one repo can own rows filed under another. A wrong project returns zero, like a finished seat.

    Requires:
        - session_id is the resolved stable session id string

    Ensures:
        - Returns ( count, ok, breakdown, priority_breakdown ): ok is True iff the
          store answered cleanly; count is the server-computed owed-row count
          (0 when not ok); breakdown is { status: count } over that same set, or {}
          when the server omitted it (see _synthesize_owed_items for how an empty
          breakdown degrades); priority_breakdown is the matching split by priority
        - store unreachable, timeout, or malformed config or body gives
          ( 0, False, {}, {} ); the caller does not poke, because it never
          guesses on a bad read
        - never raises
    """
    try:
        settings = load_task_store_settings()
        api_key  = read_api_key()
        persona  = get_voice_persona( session_id )
        # Route the persona name through the SAME canonical key the WRITE seam
        # uses (accent/punct-stripped, lowercased, spaces kept) so an accented /
        # punctuated persona ("María", "Mr. Radio") matches its store rows
        # ("maria", "mr radio") instead of false-idling on a bare-.lower() miss.
        # Idempotent → safe whether the bridge holds the display or pool form.
        persona_key = canonical_persona_key( persona.get( "name" ) if isinstance( persona, dict ) else None ) or "unknown"
        # 🔴 NO PROJECT FILTER (Rick, 2026-07-27, found by going dark for half an hour).
        #
        # This used to pass `project=resolve_project_name()`. That encodes an assumption
        # this fleet does not hold: ONE SESSION, ONE REPO. A seat sitting in
        # planning-is-prompting resolves to "plan" while owning rows filed under "lupin"
        # — which is not an edge case here, it is the normal shape of cross-repo work.
        #
        # MEASURED on the session that surfaced it:
        #     query_owed( "maria", project="plan"  ) -> owed=0   {}
        #     query_owed( "maria", project="lupin" ) -> owed=3   {queued: 3}
        # Three workable P1/P2 rows, and the oracle reported an idle seat. No poke fired
        # for ~30 minutes and nothing anywhere said a row had been filtered out.
        #
        # ⇒ ZERO IS THE WORST VALUE THIS FILTER CAN RETURN. A wrong project does not
        # produce an error or a suspicious number — it produces "nothing owed", which is
        # indistinguishable from a genuinely finished seat. Same class as `d23147e8`
        # (a scoping parameter returning a clean, plausible, SMALLER count), landing on
        # the one value that reads as healthy.
        #
        # A PERSONA'S OWED WORK IS THEIRS REGARDLESS OF WHICH REPO THE SEAT SITS IN.
        # The owner filter is the correct and sufficient scope; the project filter was
        # never narrowing a too-broad answer, it was hiding a correct one.
        ok, count, breakdown, priority_breakdown = query_owed_breakdowns(
            settings, api_key, persona_key )
        return count, ok, breakdown, priority_breakdown
    except Exception:
        return 0, False, { }, { }


def _user_chase_until_from_store( session_id, now_epoch ):
    """
    Resolve this session's per-user gate-deferral instant from the task store.

    The instant is the soonest future next_chase_ts among this owner's rows blocked by a user
    (blocked_by kind "user"). While it is in the future, is_user_deferred suppresses this session's
    hold-file gates, so a store deferral stops re-asking. No key links the two, and none should be added.

    Requires:
        - session_id is the resolved stable session id string
        - now_epoch is the caller's injected "now" (POSIX seconds)

    Ensures:
        - Returns the minimum future user-chase epoch (float), or None when the
          store has no such row
        - Fails toward liveness: a store outage or bad read returns None (do not
          suppress). Suppressing on an unknown read could bury an open user
          decision; an outage is transient and the storm it resumes is bounded.
        - Routes the persona through the same canonical key as the owed-count read
        - Never raises
    """
    try:
        settings    = load_task_store_settings()
        api_key     = read_api_key()
        persona     = get_voice_persona( session_id )
        persona_key = canonical_persona_key( persona.get( "name" ) if isinstance( persona, dict ) else None ) or "unknown"
        ok, rows = query_blocked_user_rows( settings, api_key, persona_key )
        if not ok:
            return None
        return heartbeat_user_gates.derive_user_chase_until( rows, now_epoch )
    except Exception:
        return None


# The store's owed statuses, mapped onto the oracle's TODO vocabulary (c191be39).
#
# `parked` maps to PENDING (Rick's ruling, plan §4.3a): an admitted parked row has
# provably EXPIRED — park-active rows never survive owed admission — so it is owed
# and workable, but it is neither in_progress nor pending in the oracle's native
# vocabulary. It rides `pending` because that bucket already means "owned, not
# begun", which is the closest true statement available.
#
# ACCEPTED COST, named so nobody rediscovers it as a defect: a reader cannot
# distinguish a never-started row from a rejoined one without opening it. Option
# (b), restoring the pre-park status, is NOT AVAILABLE — verified 2026-07-20,
# there is no pre-park status column (only park_reason + park_reason_captured_at);
# recovering it would mean walking task_events per row, i.e. a per-row join on an
# endpoint built as one cheap COUNT(*) that fires every turn.
STORE_STATUS_TO_TODO_STATUS = {
    "in_progress" : TODO_IN_PROGRESS,
    "queued"      : TODO_PENDING,
    "parked"      : TODO_PENDING,
}


def _synthesize_owed_items( count, breakdown=None ):
    """
    Build synthetic owed todo items that carry their real status.

    The store seam yields a count, but evaluate_work_owed consumes a list of owned dicts in the shape
    owed_items_from_state emits ({ status, owned_by_me }). Status is carried from the server's `GROUP BY`.
    Stamping every item in progress would misreport queued rows and make the unstarted-todo signal unreachable.

    Requires:
        - count is a non-negative int
        - breakdown is { store_status: count } or None/{} (server omitted it)

    Ensures:
        - With a breakdown: returns one item per counted row, each stamped with its
          mapped todo status (queued and parked give pending, in_progress gives
          in_progress). Total length is sum( breakdown.values() ).
        - An unknown store status (one the map does not name) falls back to
          TODO_IN_PROGRESS and is still counted. A new status must never vanish
          from the owed list: over-reporting urgency is recoverable, but dropping
          it makes a session go quiet while owing work.
        - Without a breakdown ({} or None): returns count items stamped in_progress.
          The count still governs the poke; only the status detail is coarse.
        - count 0 with an empty breakdown gives [] (no owed work)
    """
    if not breakdown:
        return [ { "status": TODO_IN_PROGRESS, "owned_by_me": True } for _ in range( count ) ]

    items = [ ]
    for store_status, status_count in breakdown.items():
        todo_status = STORE_STATUS_TO_TODO_STATUS.get( store_status, TODO_IN_PROGRESS )
        items.extend( { "status": todo_status, "owned_by_me": True } for _ in range( status_count ) )
    return items


# Proactive-manager mechanism (fcb5dbc0, Lane A1) — the spawn-cap default that
# bounds Face A's idle-crew-capacity test (INI `cc session spawn max reviewers`).
DEFAULT_SPAWN_CAP = 8


def _backlog_count_from_store( session_id ):
    """
    Resolve this manager's queued plus in_progress count from the task store.

    It is the Face A backlog source, queried by accountable_manager=me, unlike _owed_count_from_store.
    A manager's spin-up decision keys on the chase-list it is accountable for.
    A non-manager has about zero such rows, so Face A never nudges a plain worker.

    Requires:
        - session_id is the resolved stable session id string

    Ensures:
        - Returns ( count, ok ): ok is True iff the store answered cleanly; count
          is the summed queued and in_progress count accountable to this persona
          (0 when not ok)
        - store unreachable, timeout, or malformed gives ( 0, False ); Face A does
          not nudge on a bad read, because it never guesses
        - never raises
    """
    try:
        settings    = load_task_store_settings()
        api_key     = read_api_key()
        persona     = get_voice_persona( session_id )
        persona_key = canonical_persona_key( persona.get( "name" ) if isinstance( persona, dict ) else None ) or "unknown"
        project     = resolve_project_name()
        # The breakdown is DISCARDED here on purpose: Face A keys on the SIZE of
        # the chase-list, not its status mix. Unpacked rather than sliced so a
        # future arity change fails loudly at this line instead of silently
        # rebinding `count` to a dict.
        ok, count, _breakdown = query_owed( settings, api_key, persona_key,
                                            project=project, owner_field="accountable_manager" )
        return count, ok
    except Exception:
        return 0, False


def _has_idle_crew_capacity( delegations, cap ):
    """
    Report whether this manager has room to spawn another worker under the spawn cap.

    The predicate is pure. It is true when the count of this manager's live delegated workers is below the cap.
    A manager already at the cap has no idle capacity. It is never nudged to spin up more, because it could not act.

    Requires:
        - delegations is the gathered live-worker list (truthy means alive), or None
        - cap is the spawn-concurrency cap (positive int)

    Ensures:
        - Returns True iff len( live workers ) < cap; never raises
    """
    live = len( [ d for d in ( delegations or [ ] ) if d ] )
    return live < cap


def _resolve_proactive_manager_config():
    """
    Read the proactive-manager spin-up and surface settings from lupin-app.ini.

    It mirrors _stop_hook_idle_behavior: ConfigurationManager runs under redirect_stdout, because
    its banners would corrupt the hook's stdout JSON channel.

    Ensures:
        - Returns a dict { spinup_threshold_s, surface_threshold_s,
          spinup_backlog_min, spawn_cap } of positive ints
        - any error, missing key, or non-positive value falls back to its default
          (SPINUP_CHECK_DEBOUNCE_SECONDS, SURFACE_QUESTIONS_DEBOUNCE_SECONDS,
          SPINUP_BACKLOG_MIN_N, DEFAULT_SPAWN_CAP)
        - never raises; never writes to stdout
    """
    import contextlib
    import io

    defaults = {
        "spinup_threshold_s"  : SPINUP_CHECK_DEBOUNCE_SECONDS,
        "surface_threshold_s" : SURFACE_QUESTIONS_DEBOUNCE_SECONDS,
        "spinup_backlog_min"  : SPINUP_BACKLOG_MIN_N,
        "spawn_cap"           : DEFAULT_SPAWN_CAP,
    }
    keys = {
        "spinup_threshold_s"  : "stop hook spinup check threshold seconds",
        "surface_threshold_s" : "stop hook surface questions threshold seconds",
        "spinup_backlog_min"  : "stop hook spinup backlog min",
        "spawn_cap"           : "cc session spawn max reviewers",
    }
    try:
        with contextlib.redirect_stdout( io.StringIO() ):
            mgr = ConfigurationManager(
                env_var_name  = "LUPIN_CONFIG_MGR_CLI_ARGS",
                silent        = True,
                mute_splainer = True,
            )
            out = { }
            for field, ini_key in keys.items():
                out[ field ] = _positive_int_or_default(
                    mgr.get( ini_key, default=defaults[ field ], silent=True ), defaults[ field ] )
        return out
    except Exception:
        return dict( defaults )


def _positive_int_or_default( value, default ):
    """
    Coerce a config value to a positive int, else return `default` (pure).

    Bool is an int subclass — rejected so a stray True/False never slips through
    as 1/0. A string of digits is accepted (INI values arrive as strings).

    Ensures:
        - Returns int( value ) when it is (or parses to) a positive int
        - Returns default on None / bool / non-positive / unparseable; never raises
    """
    if isinstance( value, bool ):
        return default
    try:
        ivalue = int( value )
    except ( TypeError, ValueError ):
        return default
    return ivalue if ivalue > 0 else default


def _empty_owed_state( config_error, enabled, poke_muted=False, mute_message="", mute_poke_cap=None ):
    """
    Build the owed-state bundle for paths that return before any lookup runs.

    Those paths are a malformed config and a disabled or muted heartbeat. They skip the hold read,
    transcript replay and store query. That keeps the "no reads when disabled" contract.
    The bundle holds every key the full bundle has. It sets owed=False and total_owed=0,
    so idle consumers render a plain "Momentarily idle.".

    A muted bundle carries poke_muted and mute_message (heartbeat.poke_output_enabled = false).
    When mute_message is non-empty, _run_heartbeat still emits it in the poke's place.
    owed_unknown is True when muted. There owed=False stands in for a lookup that never ran.
    Reporting it as known would put "nothing owed" on the operator's card.
    Config error and disabled keep owed_unknown False.
    """
    return {
        "config_error"       : config_error,
        "enabled"            : enabled,
        "poke_muted"         : poke_muted,
        "mute_message"       : mute_message,
        "mute_poke_cap"      : mute_poke_cap,
        "outcome"            : None,
        "owed"               : False,
        # ⚠️ MUTED ⇒ owed_unknown TRUE, and this is the whole point of the line.
        # Two of the three mute outcomes (full silence, and cap-reached) return
        # None from _run_heartbeat, so main() falls through to the idle-announce.
        # The mute short-circuits BEFORE the hold read, the transcript replay and
        # the store query — by design — so owed=False here is not a measurement,
        # it is a default standing in for a lookup that never ran. Reported as
        # owed_unknown=False it becomes "Heartbeat: idle — nothing owed." on the
        # operator's card: the exact UNKNOWN-as-NOT-OWED conflation _announce_idle
        # was written to kill after the :7999 outage whole-fleet false-idle.
        # Muting must buy SILENCE, never a false all-clear.
        # (config_error / heartbeat-disabled keep the legacy False — those are
        # long-standing contracts the Stop-hook tests pin, and neither is a
        # switch an operator flips across a live fleet expecting quiet.)
        "owed_unknown"       : bool( poke_muted ),
        "total_owed"         : 0,
        "result"             : None,
        "verdict"            : None,
        "settings"           : None,
        "hold"               : None,
        "poke_count"         : 0,
        "task_state"         : { },
        "owed_items"         : [ ],
        "delegations"        : [ ],
        "open_inbound"       : [ ],
        "stale_inbound"      : [ ],
        "needs_verification" : False,
        "open_gates"         : [ ],
        "due_gates"          : [ ],
    }


def _resolve_owed_state( session_id, transcript_path=None, cwd=None ):
    """
    Compute the hold-aware owed-work verdict shared by the poke and both idle consumers.

    The self-poke (_run_heartbeat), the Stop idle-announce and the Notification idle-beacon all call it,
    so they never disagree on whether a session is idle. It runs the full oracle through decide_heartbeat,
    which honors the hold, the poke count and the obligation overrides. The raw store count is hold-blind.

    Requires:
        - session_id is the resolved stable session id
        - transcript_path is the Stop-payload transcript_path, or None (the
          beacon may not carry it; the store owed source needs neither it nor the replay)
        - cwd is the Stop-payload cwd, or None (passed to read_hold_resilient so a
          hold written under the session's worktree cwd is found)

    Ensures:
        - Returns a bundle dict with the idle-consumer view and every local the
          _run_heartbeat side-effect tail needs: { config_error, enabled,
          poke_muted, mute_message, mute_poke_cap, outcome, owed, owed_unknown,
          total_owed, result, verdict, settings, hold, poke_count, task_state,
          owed_items, delegations, open_inbound, stale_inbound,
          needs_verification, open_gates, due_gates }
        - owed is True when outcome is OUTCOME_POKE or OUTCOME_CAP_REACHED: work is
          owed whether or not the cap halted poking. The honored-hold and not-owed
          outcomes give owed False, so a held in_progress row is not owed on both consumers.
        - total_owed = owed_items + delegations + open_inbound, the same referent
          count the poke breadcrumb reports
        - owed_unknown is True when the store owed source is on and the store
          read failed (unknown is not idle), or when pokes are muted
        - returns _empty_owed_state before any hold read, transcript replay or
          store query on a malformed config (config_error), a disabled heartbeat,
          or a muted poke; it never reads on those paths, which keeps the "no reads when
          disabled" contract
        - never raises on well-formed input
    """
    try:
        settings = load_heartbeat_settings()
    except ValueError as e:
        # Malformed heartbeat config — fail SAFE (never poke on bad config).
        log_to_stream( "stop", {}, extra={
            "phase"      : "heartbeat_settings_invalid",
            "session_id" : session_id,
            "error"      : str( e ),
        } )
        return _empty_owed_state( config_error=True, enabled=False )

    if not settings[ "enabled" ]:
        return _empty_owed_state( config_error=False, enabled=False )

    # ── Runtime poke MUTE (Rick 2026-07-22) ────────────────────────────────────
    # A settings.json switch that silences the poke WITHOUT disabling the
    # heartbeat block, re-read on every Stop (fresh hook process ⇒ toggling
    # mid-session takes effect on the very next Stop). Short-circuits BEFORE the
    # hold read / transcript replay / store query — muted means the live-
    # obligations lookup does not run at all, so a noisy or wrong board cannot
    # distract the worker. The substitute text (possibly "") rides out for
    # _run_heartbeat to emit in the poke's place.
    # .get() keeps a settings dict minted before this key existed working as
    # before (the loader always supplies it; only stubs can omit it).
    if not settings.get( "poke_output_enabled", True ):
        return _empty_owed_state( config_error=False, enabled=False,
                                  poke_muted=True,
                                  mute_message=settings.get( "poke_disabled_message", "" ),
                                  mute_poke_cap=settings.get( "poke_cap", DEFAULT_POKE_CAP ) )

    # Resolve the hold resiliently across BOTH the session's OWN cwd (facet 3,
    # threaded from the Stop payload) AND the project root where write_hold
    # defaults (base_dir=None → cu.get_project_root). Bug 1789f197: a worker whose
    # cwd is a git worktree wrote its hold under LUPIN_ROOT but the cwd-only read
    # missed it → relentless false re-pokes despite a fresh honored hold.
    hold       = read_hold_resilient( session_id, cwd=cwd )
    # A hold whose ttl_seconds is absent/unusable can NEVER be fresh ⇒ never
    # honored ⇒ this session gets poked anyway, silently, forever. Say so — ONCE
    # per hold-version, to this session only, about its OWN file (the hook reads
    # exactly one hold; the 40+ others are the JANITOR's glob and stay silent).
    if should_warn_unusable_ttl( session_id, hold ):
        log_to_stream( "stop", {}, extra={
            "phase"      : "heartbeat_hold_ttl_unusable",
            "session_id" : session_id,
            "ttl_seconds": hold.get( "ttl_seconds" ),
            "warning"    : ( "This hold declares no usable ttl_seconds — it is NOT honored and this "
                             "session is being poked despite holding. Re-declare via write_hold." ),
        } )
    poke_count = get_poke_count( session_id )
    # v2: REAL work-owed verdict from the session's own Task* state, replayed
    # from its transcript (§0.3). owned_by_me TRUE by construction; :7999-free;
    # the reader never raises (missing/empty transcript ⇒ no owed work).
    # v2.1 perf: replay the transcript ONCE and derive BOTH the owed-items and
    # the genuine-idle empty-set signal from the single state (the Stop hook
    # fires every turn — halves the per-Stop transcript reads).
    task_state = replay_task_state( transcript_path )
    # ── O1 (cascade review O1) — LOCAL, store-INDEPENDENT signals gathered FIRST ─
    # v3 (Rick 2026-06-09): feed the two live signals the oracle defined but
    # production never populated — (a) MANAGER: alive un-reaped spawned workers
    # (a supervising manager owes review/reap even with zero Task* items, so it
    # must never idle-announce while workers are out); (b) WORKER: open inbound
    # assignment DMs not yet answered with a threaded reply. Both gatherers are
    # degrade-safe IO shells (any error ⇒ [] ⇒ signal silent, never block).
    # These are filesystem / bridge reads (NO :7999 dependency), so they MUST
    # still evaluate + poke during a store outage. Gathering them BEFORE the
    # store-count seam below is the O1 fix: a store-down owed-count that fails
    # safe to 0 (§C) can no longer suppress a pending-delegation / unanswered-
    # inbound poke — only the store-owed COUNT fails safe, never the local signals.
    delegations = _gather_outstanding_delegations( session_id )
    inbound       = _gather_unanswered_inbound_questions( session_id )
    open_inbound  = inbound[ "owed" ]    # fresh, reply-expected, un-acked → owed
    stale_inbound = inbound[ "stale" ]   # aged-out → surfaced for review, NOT owed
    # ── Thread B (Rick 2026-06-16, "remove for the moment") ────────────────────
    # The arbiter's OWN manager-stale poke-DMs land on this session's dm-topic and
    # were counted as owed inbound → self-referential owed-count inflation that
    # re-pokes on the arbiter's own poke. Gate the OWED-inbound feed behind
    # settings.json heartbeat.count_inbound_questions_as_owed (DEFAULT False =
    # removed; flip True to restore the v3 worker-inbound poke). Short-circuit so
    # the settings key is read ONLY when there is owed inbound to drop — the ~17
    # empty-inbound poke paths never touch the key. stale_inbound (review-only,
    # never feeds the verdict or the poke) is untouched.
    if open_inbound and not settings[ "count_inbound_questions_as_owed" ]:
        open_inbound = [ ]
    # ── Spine Step-2 (flag-gated) — owed-items SOURCE ──────────────────────────
    # DEFAULT = the transcript-replay path (owed_items_from_state below). When
    # heartbeat.owed_source_from_store is on, the owed COUNT comes from the
    # unified task store instead (the session's OWN rows). §B: ONLY this source
    # swaps — task_state is still replayed ABOVE and feeds the genuine-idle
    # beacon + poke abstract unchanged, and the delegations + inbound signals
    # ABOVE are untouched. §C: a store that is unreachable / slow / malformed
    # FAILS SAFE — owed_items contributes 0 (an empty list) + a distinct quiet
    # hot-path log phase. This is NO LONGER an early return (O1 fix): the local
    # delegations / inbound signals gathered ABOVE must still reach the verdict
    # and poke during a store outage — only the store-owed COUNT fails safe.
    # replay_task_state stays the degraded fallback behind the flag (flip it back
    # to restore the old source instantly — §A rollback). NOT deleted.
    # owed_unknown distinguishes UNKNOWN (store source ON but unreachable) from
    # genuine NOT-OWED (store answered, count 0). Only the store path can be
    # UNKNOWN; the transcript-replay path is always determinate. Threaded out so
    # the idle-announce beacon does NOT claim "nothing owed" during a store
    # outage (the poke is already suppressed by the §C fail-safe below).
    owed_unknown = False
    # Bound UNCONDITIONALLY so the board-sweep gate below can read them on every path.
    # `None` (not 0) is the honest "unknown": the transcript-replay path has no store
    # count at all, and rendering that as 0 would tell a sweeping seat its board is
    # clear on the strength of a source that was never consulted.
    store_count     = None
    store_ok        = False
    store_priorities = { }
    if settings[ "owed_source_from_store" ]:
        store_count, store_ok, store_breakdown, store_priorities = _owed_count_from_store( session_id )
        if not store_ok:
            log_to_stream( "stop", {}, extra={
                "phase"      : "heartbeat_store_unreachable",
                "session_id" : session_id,
            } )
            owed_items   = [ ]
            owed_unknown = True
        else:
            owed_items = _synthesize_owed_items( store_count, store_breakdown )
    else:
        owed_items = owed_items_from_state( task_state )
    # ── 6929f4ac receipts-of-progress — TWO new owed signals off the hold ──────
    # Both are PURE predicates over the (already-read) hold + the delegations
    # gathered above; no extra IO, no :7999 dependency, never raise.
    #   (a) INWARD twin (§3-§5): a MANAGER owes a fresh worker-verification
    #       receipt — workers OUT *and* its last look-in is stale (debounce, Rick
    #       10 min). The worker-set itself gates manager-scope: a non-manager has
    #       an empty manifest ⇒ no delegations ⇒ never a verification debt. The
    #       agent CLEARS it by stamping last_looked_in_on_workers_ts when it
    #       verifies (explicit v1; the poke reason instructs the stamp).
    #   (b) OUTWARD twin (§9): any OPEN (unanswered) user-gate is owed work that
    #       must be RE-SURFACED — keeps the session alive to re-ask Rick. The
    #       Stop hook CANNOT call ask_* (SSE-blocking, 1s budget) — it only keeps
    #       the session awake + NAMES the due gates in the poke; the AGENT
    #       re-fires the ask_* + stamps last_asked_ts (per the §9.1 doctrine).
    #       Parallel to outstanding_delegation: ANY open gate ⇒ owed (design §9.2).
    now_epoch          = time.time()
    last_look_in_ts    = get_last_looked_in_ts( hold )
    needs_verification = manager_needs_verification(
        delegations, last_look_in_ts, now_epoch,
        threshold_seconds = settings[ "verification_threshold_seconds" ] )
    user_gates    = get_pending_user_gates( hold )
    open_gates    = heartbeat_user_gates.open_gates( user_gates )      # every not-answered gate (tracked; arbiter aged-backstop set)
    # be56bff8 per-USER deferral: a gate the seat deferred in the STORE
    # (task_transition -> blocked + future next_chase_ts — the deferral verb a seat
    # actually has) must go quiet, but the hold-file row it never touched has no own
    # chase to strip. So derive the per-user chase from the store and suppress ALL of
    # this session's gates while the user is deferred. ONLY queried when there ARE
    # open gates (the common zero-gate Stop pays no round-trip); fail-safe to None
    # (no suppression) on a bad read so a store outage never buries an open decision.
    user_chase_until = _user_chase_until_from_store( session_id, now_epoch ) if open_gates else None
    # bug 75f392c0 relief valve: a gate deferred to a FUTURE scheduled chase (an
    # offline user with a next_chase_ts) or one that spent its re-ask budget with
    # no chase scheduled is NOT eligible to poke this Stop — pokeable_gates strips
    # those out. due_gates already filters through it (re-ask cadence on top); Face
    # B's re-surface debounce below is fed pokeable so a deferred gate never
    # re-triggers the surface either. open_gates stays the tracked/observability set.
    pokeable_gates = heartbeat_user_gates.pokeable_gates( user_gates, now_epoch, user_chase_until )  # relief-valve-eligible
    due_gates     = heartbeat_user_gates.due_gates( user_gates, now_epoch, user_chase_until )  # re-ask NOW (poke detail)
    # ── Proactive-manager mechanism (fcb5dbc0, A1) — TWO new debounced signals ──
    # Both ride the SAME pure-debounce shape as the 6929f4ac inward twin, gated on
    # the per-manager stamps in the hold (survive /clear). Config (per-face
    # thresholds + backlog floor + spawn cap) is INI-resolved once per Stop;
    # fail-safe to defaults. Both gatherers are degrade-safe — a store outage / a
    # parked non-manager simply never fires the signal (never a false poke).
    #   Face A (item 11): backlog this manager is ACCOUNTABLE for >= floor AND idle
    #     crew capacity AND the spin-up-check debounce elapsed → NUDGE "spin up a
    #     crew" (the manager decides + acts of its own accord). The store read is
    #     fail-safe: on a not-ok read Face A stays silent (never guess).
    #   Face B (item 1): >=1 open operator gate AND the per-manager re-surface
    #     debounce elapsed → re-fire the operator-gate asks (one debounce, D3).
    pm_config          = _resolve_proactive_manager_config()
    last_spinup_ts     = get_last_spinup_check_ts( hold )
    last_surfaced_ts   = get_last_surfaced_questions_ts( hold )
    backlog_count, backlog_ok = _backlog_count_from_store( session_id )
    needs_spinup_check = backlog_ok and manager_needs_spinup_check(
        backlog_count,
        _has_idle_crew_capacity( delegations, pm_config[ "spawn_cap" ] ),
        last_spinup_ts, now_epoch,
        threshold_seconds = pm_config[ "spinup_threshold_s" ],
        backlog_min_n     = pm_config[ "spinup_backlog_min" ] )
    needs_question_surface = manager_needs_question_surface(
        pokeable_gates, last_surfaced_ts, now_epoch,   # 75f392c0: deferred/capped gates don't re-surface
        threshold_seconds = pm_config[ "surface_threshold_s" ] )
    # Relief-valve observability (75f392c0): greppable count of gates suppressed
    # this Stop (open but not pokeable — deferred to a future chase or budget-spent)
    # so the "why isn't it re-asking?" question is answerable from the log stream.
    _deferred_gate_count = len( open_gates ) - len( pokeable_gates )
    if _deferred_gate_count:
        log_to_stream( "stop", {}, extra={
            "phase"                : "heartbeat_gate_relief_valve",
            "session_id"           : session_id,
            "open_user_gates"      : len( open_gates ),
            "pokeable_user_gates"  : len( pokeable_gates ),
            "deferred_user_gates"  : _deferred_gate_count,
        } )
    # One line carrying total + status split + priority split, replacing the two
    # count sentences. Empty on the transcript-replay path (no store breakdown),
    # where evaluate_work_owed falls back to its own wording.
    owed_summary = format_owed_summary( store_breakdown, store_priorities ) if store_ok else ""
    verdict    = evaluate_work_owed(
        todo_items                   = owed_items,
        unanswered_inbound_questions = open_inbound,
        outstanding_delegations      = delegations,
        needs_verification           = needs_verification,
        open_user_gates              = due_gates,   # bug d0d7f068: the obligation-OVERRIDE + poke key on DUE gates (reask-interval elapsed), NOT any-open — an open-but-not-due gate stays tracked in the hold (still "not answered") but must NOT poke through an honored hold every Stop. Its re-ask cadence IS reask_interval_s; the row's existence, not per-Stop poking, is the not-done tracker. (open_gates still logged below for observability.)
        needs_question_surface       = needs_question_surface,
        needs_spinup_check           = needs_spinup_check,
        owed_summary                 = owed_summary,
    )
    # Role-selected north-star goal echo (role-goals Phase 2-3) — APPENDED to the
    # poke reason so the session re-anchors on its goal every tick. Role comes from
    # the bridge (spawned workers stamp it at spawn); a declared fleet-roster
    # manager is detected via _is_manager_persona so it gets the Manager line at
    # its OWN self-poke too; otherwise the role-agnostic fallback (D2). The config
    # read (runtime-tunable) lives here in the IO shell; decide_heartbeat only
    # appends the injected string. Degrade-safe: "" ⇒ pre-role-goals reason.
    try:
        _bridge_role = get_session_metadata().get( "role" )
    except Exception:
        _bridge_role = None
    goal_line  = _heartbeat_goal_line( session_id, _bridge_role )
    # Rick's 2026-07-25 board-sweep gate. PERSONA-scoped, not role-scoped: both sweeping
    # seats resolve to `worker`, so the role goal line above physically cannot say "22" to
    # one and "71" to the other. Silent for every seat with no ledger — i.e. everyone not
    # sweeping — and LOUD (never "") when a ledger exists but cannot be read.
    # store_count is the live owed count fetched ~100 lines above for the oracle;
    # None (not 0) when the store could not be read, so the COMPLETE arm says
    # UNKNOWN instead of rendering a store outage as a clear board.
    _live_owed = store_count if ( settings[ "owed_source_from_store" ] and store_ok ) else None
    sweep_line = _board_sweep_line( session_id, live_owed=_live_owed )

    # Row 505e5c12 — the standing tick for `memento_io.py verify`, which had no caller
    # and had not run in 6d14h while a bare slot (a live data-loss window) sat waiting.
    # Self-throttled to once a day by its own ledger, so this call is a cheap no-op on
    # all but one tick; it REPORTS and never repairs. Appended to the sweep line rather
    # than given its own channel because both are "before you stop, look at this".
    # It cannot raise — every path inside returns a string.
    memento_line = verify_tick_line()
    if memento_line:
        sweep_line = f"{sweep_line}\n{memento_line}" if sweep_line else memento_line

    result     = decide_heartbeat( hold, verdict, poke_count, settings[ "poke_cap" ],
                                   goal_line=goal_line, sweep_line=sweep_line )

    return {
        "config_error"       : False,
        "enabled"            : True,
        "poke_muted"         : False,
        "mute_message"       : "",
        "mute_poke_cap"      : None,
        "outcome"            : result[ "outcome" ],
        "owed"               : result[ "outcome" ] in ( OUTCOME_POKE, OUTCOME_CAP_REACHED ),
        "owed_unknown"       : owed_unknown,
        "total_owed"         : len( owed_items ) + len( delegations ) + len( open_inbound ),
        "result"             : result,
        "verdict"            : verdict,
        "settings"           : settings,
        "hold"               : hold,
        "poke_count"         : poke_count,
        "task_state"         : task_state,
        "owed_items"         : owed_items,
        "delegations"        : delegations,
        "open_inbound"       : open_inbound,
        "stale_inbound"      : stale_inbound,
        "needs_verification" : needs_verification,
        "open_gates"         : open_gates,
        "due_gates"          : due_gates,
    }


def _run_heartbeat( session_id, transcript_path, cwd=None, state=None ):
    """
    Apply the heartbeat poke side effects and return ( hook_output, owed_unknown ).

    It is the side-effecting shell around _resolve_owed_state: poke count, cap note, emit_outcome, idle beacon,
    breadcrumb and tmux inject. `state` is an optional pre-resolved _resolve_owed_state bundle, passed by main()
    so the poke and the idle-announce share one computation. None resolves it here, with identical behavior.

    Requires:
        - transcript_path is the Stop-hook payload's transcript_path (str/None)
        - called downstream of the stop_hook_active loop guard, only when no voice
          input is pending (voice always wins; never poke on a re-fire)

    Ensures:
        - Returns ( hook_output, owed_unknown ); applies the increment (on poke),
          cap note (at cap), fire-and-forget emit and poke breadcrumb side effects
        - hook_output is the {"decision":"block","reason": ...} dict on OUTCOME_POKE
          only (the caller emits it and skips the idle path); it is None when
          disabled, malformed, honored, not owed or cap reached
        - owed_unknown rides the store-unreachable fail-safe, so the idle beacon says
          "owed status unknown" instead of "nothing owed"
        - Disabled or malformed config gives ( None, False ) with no reads (the
          bundle returns before any hold, transcript or store IO)
        - Muted pokes: a non-empty substitute below the poke cap is delivered like
          a poke (count increment, operator beacon, tmux inject, block) and returns
          ( block, False ); an empty substitute or a reached cap returns ( None, False )
    """
    state = state if state is not None else _resolve_owed_state( session_id, transcript_path, cwd )
    # Runtime mute (heartbeat.poke_output_enabled = false): the obligations
    # lookup was skipped upstream. A NON-EMPTY substitute is delivered exactly
    # like a real poke — block + tmux inject (Rick 2026-07-22: the block alone is
    # silent re-prompt context on a stopped session; the keystroke is what makes
    # the worker actually receive it) — plus the operator beacon carrying the
    # same text verbatim, so Rick sees what the workers see. An empty/None
    # substitute is the full-silence path: no output, no inject, no beacon.
    if state.get( "poke_muted" ):
        mute_message = state.get( "mute_message" ) or ""
        # The substitute is a POKE and is budgeted like one. Without the cap the
        # inject re-fired every Stop forever: it creates a new turn, that turn
        # ends in a Stop, which injects again — nobody typing, no bound (observed
        # live 2026-07-22, two self-turns before it was caught). The cap file is
        # shared with the real poke and is reopened only by genuine user typing,
        # which is why the injected text carries MUTE_PROMPT_SENTINEL: without
        # that marker UserPromptSubmit reads the substitute as user
        # re-engagement and resets the very budget meant to bound it (c121037b).
        poke_count = get_poke_count( session_id )
        cap        = state.get( "mute_poke_cap" ) or DEFAULT_POKE_CAP
        capped     = poke_count >= cap
        log_to_stream( "stop", {}, extra={
            "phase"       : "heartbeat_poke_muted",
            "session_id"  : session_id,
            "has_message" : bool( mute_message ),
            "poke_count"  : poke_count,
            "cap"         : cap,
            "capped"      : capped,
        } )
        if mute_message and not capped:
            increment_poke_count( session_id )
            persona = get_voice_persona( session_id )
            _announce_muted( session_id, persona.get( "name" ) if persona else None, mute_message )
            inject_qualifier_via_tmux( session_id,
                                       f"{MUTE_PROMPT_SENTINEL} {mute_message}", wrap=False )
            return build_stop_block( mute_message ), False
        return None, False
    if state[ "config_error" ] or not state[ "enabled" ]:
        return None, False
    settings           = state[ "settings" ]
    hold               = state[ "hold" ]
    task_state         = state[ "task_state" ]
    owed_items         = state[ "owed_items" ]
    delegations        = state[ "delegations" ]
    open_inbound       = state[ "open_inbound" ]
    stale_inbound      = state[ "stale_inbound" ]
    owed_unknown       = state[ "owed_unknown" ]
    needs_verification = state[ "needs_verification" ]
    open_gates         = state[ "open_gates" ]
    due_gates          = state[ "due_gates" ]
    verdict            = state[ "verdict" ]
    result             = state[ "result" ]

    if result[ "should_increment" ]:
        increment_poke_count( session_id )
    if result[ "should_notify_cap" ]:
        _notify_cap_reached( session_id )

    # ── EMIT NOW, CONSUME LATER (María §0 #2) ──────────────────────────────────
    # Fire-and-forget poke-OUTCOME record so the v2 agentic Poker lands later as
    # a PURE CONSUMER (zero Hook retrofit). emit_outcome SELF-FILTERS (writes
    # only for {poke, honored, cap_reached}; no-op on not_owed/unknown) — called
    # unconditionally, no branching. Writes to the FLEET dir
    # ~/.claude/heartbeat-events/ (outside the repo); :7999-free. The try/except
    # makes emission NEVER a dependency of the poke: if it fails the poke still
    # proceeds (the §0 #2 invariant) — belt to emit_outcome's never-raises belt.
    persona      = get_voice_persona( session_id )
    persona_name = persona.get( "name" ) if persona else None

    # ── Live oracle log line (2026-06-05, Rick) — "signs of life" every Stop ──
    # Greppable in the stop log stream (`docker logs … | grep heartbeat_oracle`):
    # the work-owed verdict + decision outcome + poke count, so you can watch the
    # Oracle's state update in real time and confirm it's accurate + current.
    log_to_stream( "stop", {}, extra={
        "phase"      : "heartbeat_oracle",
        "session_id" : session_id,
        "persona"    : persona_name,
        "outcome"      : result[ "outcome" ],
        "work_owed"    : verdict[ "work_owed" ],
        "owed_items"   : len( owed_items ),
        "delegations"  : len( delegations ),
        "open_inbound"  : len( open_inbound ),
        # stale_inbound REMOVED from the oracle log (item 6fc8d78d, Tiberius
        # 2026-07-07): María's watch measured it 0/12891 — never populated on
        # production data, so it was pure noise in the greppable oracle stream. The
        # underlying mechanism (partition_inbound_by_age + the "review, not owed"
        # poke-abstract display) is a working, fully-tested feature and STAYS — it
        # simply never triggers in prod because real inbound is handled/acked before
        # it ages out. Only the dead LOG field is pruned, per her "prune or wire".
        "needs_verification" : needs_verification,            # 6929f4ac inward twin
        "open_user_gates"    : len( open_gates ),             # 6929f4ac outward twin (owed)
        "due_user_gates"     : len( due_gates ),              # 6929f4ac outward twin (re-ask now)
        "poke_count"   : get_poke_count( session_id ),
        "cap"          : settings[ "poke_cap" ],
        "awaiting"     : ( hold.get( "awaiting" ) if hold else None ),
    } )

    try:
        heartbeat_events.emit_outcome(
            session_id,
            persona_name,
            result[ "outcome" ],
            get_poke_count( session_id ),                       # POST-increment
            settings[ "poke_cap" ],
            work_owed = verdict[ "work_owed" ],                 # v2: REAL bool (was null in v1)
            awaiting  = ( hold.get( "awaiting" ) if hold else None ),
            reason    = result[ "hook_output" ].get( "reason" ),  # poke text, else None
        )
    except Exception as e:
        log_to_stream( "stop", {}, extra={
            "phase"      : "heartbeat_emit_error",
            "session_id" : session_id,
            "error"      : str( e ),
        } )
    # ── end emit ──
    #
    # NOTE (Thread A, 2026-06-06): the 2026-06-05 on-behalf "poke-report" scaffold
    # (_heartbeat_state_sentence + _send_poke_report, a per-Stop /api/notify PUSH)
    # was DROPPED here — superseded by v2.1 direct-state visibility, which makes
    # liveness a cheap centrally-PULLED bridge-mtime age instead of an expensive
    # per-Stop push (the push was the FM-7 load multiplier). The poke, oracle log,
    # and genuine-idle beacon below all remain live. See
    # src/rnd/v0.1.8/2026.06.06-heartbeat-poke-scaffold-vs-v2.1-supersession.md.

    # ── 2b: genuine-idle DECLARATION beacon (Rick §6.2 = Option B) ─────────────
    # Edge-triggered: declare idle ONLY on the TRANSITION into genuine-idle
    # (not_owed AND an empty Task* set), de-duped against the last emitted event
    # so a quiet streak emits ONE beacon, not one per Stop. Fire-and-forget.
    if result[ "outcome" ] == OUTCOME_NOT_OWED and is_empty_state( task_state ):
        _emit_genuine_idle( session_id, persona_name, settings[ "poke_cap" ] )

    if result[ "outcome" ] == OUTCOME_POKE:
        # §4 breadcrumb (Rick 2026-06-09 + receipts 2026-06-10): the hook caught
        # a stopped-with-owed worker → low-pri card notify. The SHORT spoken
        # message counts ALL owed referents (Task + delegation + inbound — the
        # Mr. Radio cosmetic fix), and the ABSTRACT carries the receipts (fired
        # signals + their referents + the verbatim poke text). Both the abstract
        # build and _announce_poke are degrade-safe (never block the poke);
        # de-dup rides the poke-cap. Fires for BOTH branches (shared adapter).
        total_owed = len( owed_items ) + len( delegations ) + len( open_inbound )
        abstract   = _build_poke_abstract_safe(
            verdict, task_state, transcript_path, delegations, open_inbound, stale_inbound, result
        )
        _announce_poke( session_id, persona_name, total_owed, abstract=abstract )
        # ── f0d79d71 (Krishna 2026-06-16; María root-cause) — tmux pairing ──────
        # The poke emits decision:block (the logging + continue RECEIPT), but on a
        # genuinely-STOPPED session the block alone is silent re-prompt context
        # with no submit — it does NOT produce the continuation turn. The keystroke
        # nudge is what fires it. Mirror the battle-tested pairing at stop.py:705 &
        # 722 (qualifier-continue) and peer-DM delivery (hook_common.py:849): inject
        # the poke reason ALONGSIDE the emit. wrap=False = VERBATIM (a system poke,
        # not a human-voice reply) → NO speakerphone rider → silent, so it composes
        # with auto-narrate without double-speak. This single site is the shared
        # adapter for BOTH poke branches (speakerphone main():1446 + Branch-C 1526),
        # exactly like _announce_poke above. EXACTLY-ONE-CONTINUATION: the
        # stop_hook_active guard (main():1424) means a re-fire never re-enters
        # _run_heartbeat, and poke_cap bounds OUTCOME_POKE — so the block+inject
        # pair fires at most once per quiescence, never a double-submit.
        poke_reason = result[ "hook_output" ].get( "reason" )
        if poke_reason:
            inject_qualifier_via_tmux( session_id, poke_reason, wrap=False )
        return result[ "hook_output" ], owed_unknown
    return None, owed_unknown


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Extract stop_hook_active for loop prevention
    stop_hook_active = payload.get( "stop_hook_active", "NOT_PRESENT" )

    # Log full payload for empirical analysis
    log_payload( "stop", payload )

    # Resolve session_id: payload first, then session bridge fallback
    session_id = resolve_stable_session_id( payload.get( "session_id", "" ) ) or get_claude_session_id()

    speakerphone_on = get_speakerphone( session_id )

    # Speakerphone: FIRST run the Phase 4 auto-narrate safety net — synthesize
    # a notify() if Claude's last turn ended without one (silent-console-only
    # failure mode). Stays UPSTREAM of the loop guard (pre-split position): it
    # carries its own per-turn dedup (last_autonarrated_turn_id). Per
    # src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md
    if speakerphone_on:
        try:
            _try_auto_narrate( session_id, payload )
        except Exception as e:
            log_to_stream( "stop", { }, extra={
                "phase"      : "auto_narrate_error",
                "session_id" : session_id,
                "error"      : str( e ),
            } )

    # Loop prevention: if stop_hook_active is True, we already blocked once —
    # don't block again (would create infinite loop). §3 (2026-06-09): now
    # UPSTREAM of the speakerphone heartbeat path too, so the never-poke-on-a-
    # re-fire invariant holds for BOTH branches. (A speakerphone re-fire exits
    # silently here — no idle-announce: the previous Stop was just blocked, so
    # the session is mid-work, not idle.)
    if stop_hook_active is True:
        emit_json( {} )
        sys.exit( 0 )

    if speakerphone_on:
        # ── §3 split (Rick's reframe, 2026-06-09) ──────────────────────────────
        # The old all-or-nothing speakerphone early-exit was written narrowly to
        # skip the BLOCKING "Anything else?" ask, but it bailed out 75 lines
        # upstream of the heartbeat self-poke — so NO speakerphone session was
        # ever poked (every manager runs speakerphone; the fleet's first line of
        # defense was dark for exactly them). Split: speakerphone still
        # suppresses ONLY the blocking ask — NOT the poke, NOT the breadcrumb.
        # The poke's own work-owed oracle is the real gate (a worker actively in
        # dialogue has no owed-and-stopped state); NO AFK gate. The poke rides
        # the Stop-hook `reason` field (decision:block) — a silent re-prompt,
        # not a TTS utterance, so it composes with auto-narrate above without
        # double-speak (María Q2; auto-narrate only re-speaks Claude's LAST
        # turn, never the injected reason).
        #
        # Branch-C invariant (voice always wins): peek at the voice buffer
        # WITHOUT draining — pending voice ⇒ no poke, buffer left untouched.
        # bug aa403e03: resolve the shared hold-aware verdict ONCE and thread it
        # into BOTH the poke decision and the idle-announce, so the Stop hook and
        # the Notification idle-beacon never disagree on owed-vs-idle.
        idle_state = None
        if not _has_pending_voice( session_id ):
            idle_state = _resolve_owed_state( session_id, payload.get( "transcript_path" ), payload.get( "cwd" ) )
            heartbeat_output, _ = _run_heartbeat( session_id, payload.get( "transcript_path" ), payload.get( "cwd" ), state=idle_state )
            if heartbeat_output is not None:
                log_to_stream( "stop", {}, extra={
                    "phase"      : "speakerphone_poke",
                    "session_id" : session_id,
                } )
                emit_json( heartbeat_output )
                return
        else:
            # Pending buffered peer DM(s), §6a. The speakerphone branch returns
            # below BEFORE the main format_voice_context drain (~line 1480), so
            # without this a peer DM to a manager (every manager runs speakerphone)
            # would sit unseen until idle_prompt. Drain + tmux-deliver each DM with
            # NO voice rider, then allow the stop. (The buffer holds only DMs — the
            # voice path injects directly without buffering — so any returned voice
            # list is empty in practice.)
            deliver_pending_peer_dms( session_id )
            log_to_stream( "stop", {}, extra={
                "phase"      : "speakerphone_peer_dm_deliver",
                "session_id" : session_id,
            } )
            emit_json( {} )
            return

        # Silent idle-announce (Rick, 2026-06-08 — unchanged by the §3 split).
        # _announce_idle posts at LOW priority, which the client renders to the
        # DOM card WITHOUT TTS (notifications.js gates speech on high/urgent
        # only) — a subtle bubble, no chorus-TTS spam. Gated to idle_announce
        # ONLY: `ask`/`none` stay fully silent in speakerphone (the blocking
        # ask is correctly skipped). "Nothing owed" is a turn-boundary
        # approximation accepted by Rick (no-poke ⇒ the oracle found nothing
        # owed, or the heartbeat is disabled/held/capped).
        if _stop_hook_idle_behavior() == "idle_announce":
            persona      = get_voice_persona( session_id )
            persona_name = persona.get( "name" ) if persona else None
            _announce_idle( session_id, persona_name,
                            owed_unknown = idle_state[ "owed_unknown" ],
                            owed         = idle_state[ "owed" ],
                            total_owed   = idle_state[ "total_owed" ],
                            muted        = idle_state.get( "poke_muted", False ) )

        # Speakerphone/chorus sessions skip ONLY the blocking "Anything else?"
        # prompt path below (it would interrupt the user's live voice
        # dialogue); the heartbeat poke + breadcrumb above now run for them
        # (§3, 2026-06-09 — the poke-fix this comment used to deny).
        log_to_stream( "stop", {}, extra={
            "phase"      : "speakerphone_skip",
            "session_id" : session_id,
        } )
        emit_json( {} )
        sys.exit( 0 )

    # Drain voice buffer and acknowledge buffered messages
    messages  = drain_and_acknowledge( session_id )
    voice_ctx = format_voice_context( messages )

    if voice_ctx:
        # Check block counter — safety valve
        count = get_stop_block_count( session_id )
        if count >= MAX_STOP_BLOCKS:
            reset_stop_block_count( session_id )
            send_tts( "Stop — max blocks reached, allowing stop" )
            emit_json( {} )
        else:
            increment_stop_block_count( session_id )
            send_tts( "Stop — blocking with voice input" )
            emit_json( build_stop_block( enrich_voice_context( voice_ctx, messages ) ) )
    else:
        # No voice input → ask user "Anything else?" via notification.
        # Two paths gated by ~/.claude/settings.json idle_detection.enabled:
        #   - enabled=true (default, NEW): arm a deferred waiter and allow stop
        #     immediately. The waiter sleeps for backoff_minutes[index] minutes,
        #     then re-checks the bridge and fires the same prompt only if the
        #     session is still idle. See:
        #     src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
        #   - enabled=false (LEGACY): fire the prompt immediately as before.
        reset_stop_block_count( session_id )

        # ── Heartbeat self-poke (additive; gated; voice already lost above) ──
        # Downstream of the stop_hook_active loop guard (never poke on a
        # re-fire) and only in Branch C (no voice_ctx → voice always wins).
        # Returns a block dict ONLY when the heartbeat pokes; otherwise None →
        # fall through to the existing idle-waiter / "Anything else?" path.
        # transcript_path (Stop payload) feeds the v2 Task*-replay work-owed oracle.
        # cwd (Stop payload) resolves the per-session hold base (c121037b facet 3).
        # bug aa403e03: resolve the shared hold-aware verdict ONCE and thread it into
        # BOTH the poke decision and the idle-announce (consistency with the beacon).
        idle_state = _resolve_owed_state( session_id, payload.get( "transcript_path" ), payload.get( "cwd" ) )
        heartbeat_output, _ = _run_heartbeat( session_id, payload.get( "transcript_path" ), payload.get( "cwd" ), state=idle_state )
        if heartbeat_output is not None:
            emit_json( heartbeat_output )
            return
        # ── end heartbeat ──

        # ── Idle-Stop behavior (Thread A — 3-way enum) ────────────────────────
        # On a no-poke (idle) Stop, `lupin-app.ini [Lupin: Baseline] stop hook
        # idle behavior` selects the action. v2.1 direct-state visibility owns
        # fleet liveness now, so the legacy idle-waiter is no longer the default:
        #   - "idle_announce" (DEFAULT) → fire ONE low-pri idle status notify
        #     (the persona speaks its idle state), then allow the stop.
        #   - "ask"   → the legacy path verbatim: deferred idle-waiter
        #     (idle_detection enabled) or the immediate "Anything else?" prompt.
        #   - "none"  → take no action, just allow the stop (silent).
        idle_behavior = _stop_hook_idle_behavior()

        if idle_behavior == "ask":
            last_assistant_message = payload.get( "last_assistant_message" )
            cwd                    = payload.get( "cwd" )

            try:
                settings = load_idle_settings()
            except ValueError as e:
                log_to_stream( "stop", {}, extra={
                    "phase" : "idle_settings_invalid",
                    "error" : str( e ),
                } )
                settings = { "enabled": False, "backoff_minutes": [] }

            if settings[ "enabled" ]:
                _arm_idle_waiter( session_id, last_assistant_message, cwd )
                emit_json( {} )  # allow stop; waiter will fire later if still idle
            else:
                result = _ask_anything_else( session_id, last_assistant_message, cwd=cwd )
                emit_json( result )
        elif idle_behavior == "idle_announce":
            persona      = get_voice_persona( session_id )
            persona_name = persona.get( "name" ) if persona else None
            _announce_idle( session_id, persona_name,
                            owed_unknown = idle_state[ "owed_unknown" ],
                            owed         = idle_state[ "owed" ],
                            total_owed   = idle_state[ "total_owed" ],
                            muted        = idle_state.get( "poke_muted", False ) )
            emit_json( {} )  # allow stop — v2.1 owns liveness; this is a courtesy ping
        else:   # "none": silent allow-stop
            emit_json( {} )

if __name__ == "__main__":
    main()
