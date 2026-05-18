#!/usr/bin/env python3
"""
Cascade heartbeat scheduler — wakes the manager session at a fixed cadence
during an active cascaded plan-review run.

Implements postmortem §6.B + playbook §6.4 doctrine. Faithful Python daemon
implementation of the heartbeat shape (manager-only scope, dead-man's-switch,
cascade-complete signal-driven termination).

Launch (one-liner):
  nohup python src/scripts/cascade_heartbeat_scheduler.py \
    --manager tiberius --cadence-active 180 --cadence-idle 300 \
    --strikes 3 --input-plan-topic cascaded-prototype-input-plan \
    > /tmp/cascade-heartbeat.log 2>&1 &

State machine:
  ACTIVE: poke manager every --cadence-active seconds
  TERMINATED: cascade-complete signal detected on input-plan topic, clean exit

Dead-man's-switch: after --strikes consecutive non-responses (no commons
activity from manager) within the active window, fire priority=high notify()
to the user.
"""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# Bootstrap LUPIN_ROOT (per CLAUDE.md PATH MANAGEMENT)
LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if LUPIN_ROOT is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running:\n"
        "  export LUPIN_ROOT=/path/to/lupin"
    )
SRC_PATH = os.path.join( LUPIN_ROOT, "src" )
if SRC_PATH not in sys.path:
    sys.path.insert( 0, SRC_PATH )

import requests
from lupin_mcp.commons_store import CommonsStore


REGISTER_ENDPOINT       = "/api/commons/register-question"
NOTIFY_ENDPOINT         = "/api/notify"
COMMONS_TOPICS_DIR      = Path( LUPIN_ROOT ) / "io" / "commons"
SCHEDULER_SESSION_ID    = "cascade-scheduler"
SCHEDULER_PERSONA_NAME  = "cascade-scheduler"
SCHEDULER_PERSONA_ICON  = "⏱️"
SCHEDULER_PERSONA_COLOR = "#6B6B6B"
USER_EMAIL              = "ricardo.felipe.ruiz@gmail.com"
DEFAULT_KEY_PATH        = Path( LUPIN_ROOT ) / "src" / "conf" / "keys" / "notification-api-claude-code-dev"


def load_api_key( key_path: Path ) -> str:
    return key_path.read_text().strip()


def fire_heartbeat(
    api_base_url : str,
    api_key      : str,
    manager      : str,
    store        : CommonsStore,
    tick_num     : int,
) -> dict:
    """Write a heartbeat entry to dm-<manager>.md + register-question for Phase 3 push."""
    qid   = str( uuid.uuid4() )
    topic = f"dm-{manager.lower()}"
    body  = (
        f"heartbeat-{tick_num} from cascade-scheduler — universal-step-zero: "
        f"disk-read all active topics + dispatch any pending stages"
    )

    # Step 1: write to disk via CommonsStore (uses NEW entry separator post-fix)
    try:
        store.post(
            topic             = topic,
            body              = body,
            sender_session_id = SCHEDULER_SESSION_ID,
            persona_name      = SCHEDULER_PERSONA_NAME,
            persona_icon      = SCHEDULER_PERSONA_ICON,
            persona_color     = SCHEDULER_PERSONA_COLOR,
            metadata          = {
                "kind"              : "heartbeat",
                "question_id"       : qid,
                "recipient_persona" : manager,
                "tick_num"          : tick_num,
            },
        )
    except Exception as e:
        return { "tick": tick_num, "question_id": qid, "store_error": repr( e ) }

    # Step 2: register for Phase 3 push to recipient's listener
    payload = {
        "topic"             : topic,
        "question_id"       : qid,
        "asker_session_id"  : SCHEDULER_SESSION_ID,
        "recipient_persona" : manager,
        "expect_reply"      : False,
        "ttl_seconds"       : 60,
    }
    headers = { "X-API-Key": api_key }
    try:
        resp = requests.post(
            f"{api_base_url}{REGISTER_ENDPOINT}",
            json    = payload,
            headers = headers,
            timeout = 5,
        )
        result = {
            "tick"            : tick_num,
            "question_id"     : qid,
            "register_status" : resp.status_code,
        }
        if 200 <= resp.status_code < 300:
            try:
                body_json = resp.json()
                result[ "dm_dispatched" ] = body_json.get( "dm_dispatched" )
            except Exception:
                pass
        else:
            result[ "register_body" ] = resp.text[ :200 ]
        return result
    except Exception as e:
        return { "tick": tick_num, "question_id": qid, "register_error": repr( e ) }


def fire_dead_mans_switch(
    api_base_url             : str,
    api_key                  : str,
    manager                  : str,
    consecutive_silent_ticks : int,
) -> dict:
    """Fire priority=high notify() to user when manager unresponsive after --strikes ticks."""
    msg = (
        f"Cascade heartbeat: manager '{manager}' unresponsive after "
        f"{consecutive_silent_ticks} consecutive pokes — possible stall"
    )
    params = {
        "message"         : msg,
        "type"            : "alert",
        "priority"        : "high",
        "target_user"     : USER_EMAIL,
        "sender_id"       : "cascade-heartbeat-scheduler",
        "idempotency_key" : f"cascade-dms-{int( time.time() )}",
    }
    try:
        resp = requests.post(
            f"{api_base_url}{NOTIFY_ENDPOINT}",
            params  = params,
            headers = { "X-API-Key": api_key },
            timeout = 10,
        )
        return { "dms_status": resp.status_code, "dms_body": resp.text[ :200 ] }
    except Exception as e:
        return { "dms_error": repr( e ) }


def fire_budget_warning(
    api_base_url : str,
    api_key      : str,
    manager      : str,
    store        : CommonsStore,
    section      : str,
    count        : int,
    threshold    : int,
) -> dict:
    """Post budget-breach DM to manager via CommonsStore + Phase 3 push.

    Matches fire_heartbeat() shape — body lands on dm-<manager> topic and
    register-question pushes the warn into the manager's CC session as
    a COMMONS PEER MESSAGE system-reminder.
    """
    qid   = str( uuid.uuid4() )
    topic = f"dm-{manager.lower()}"
    body  = f"Section {section} exceeded message budget ({count}/{threshold})"

    try:
        store.post(
            topic             = topic,
            body              = body,
            sender_session_id = SCHEDULER_SESSION_ID,
            persona_name      = SCHEDULER_PERSONA_NAME,
            persona_icon      = SCHEDULER_PERSONA_ICON,
            persona_color     = SCHEDULER_PERSONA_COLOR,
            metadata          = {
                "kind"          : "budget_warning",
                "question_id"   : qid,
                "section_topic" : section,
                "count"         : count,
                "threshold"     : threshold,
            },
        )
    except Exception as e:
        return { "section": section, "store_error": repr( e ) }

    payload = {
        "topic"             : topic,
        "question_id"       : qid,
        "asker_session_id"  : SCHEDULER_SESSION_ID,
        "recipient_persona" : manager,
        "expect_reply"      : False,
        "ttl_seconds"       : 60,
    }
    headers = { "X-API-Key": api_key }
    try:
        resp = requests.post(
            f"{api_base_url}{REGISTER_ENDPOINT}",
            json    = payload,
            headers = headers,
            timeout = 5,
        )
        return {
            "section"         : section,
            "register_status" : resp.status_code,
        }
    except Exception as e:
        return { "section": section, "register_error": repr( e ) }


def check_section_budgets(
    section_glob    : str,
    threshold       : int,
    api_base_url    : str,
    api_key         : str,
    manager         : str,
    store           : CommonsStore,
    warned_sections : dict,
) -> None:
    """Side-task: warn manager once per section that exceeds the budget.

    Idempotent — warned_sections dict prevents re-warning a section once
    it has crossed the threshold within this daemon lifetime.
    """
    marker = "<<<__lupin_commons_entry_boundary__>>>"
    for section_file in COMMONS_TOPICS_DIR.glob( section_glob ):
        topic = section_file.stem
        if warned_sections.get( topic ):
            continue
        try:
            count = section_file.read_text( encoding="utf-8" ).count( marker )
        except Exception:
            continue
        if count >= threshold:
            print( f"[cascade-heartbeat] budget breach: {topic} ({count}/{threshold})" )
            result = fire_budget_warning(
                api_base_url, api_key, manager, store, topic, count, threshold
            )
            print( f"[cascade-heartbeat] budget-warn result: {json.dumps( result )}" )
            warned_sections[ topic ] = True


def cascade_is_complete( input_plan_topic: str, initial_size: int ) -> bool:
    """
    Check if input-plan topic has a cascade_complete entry in content added
    AFTER `initial_size` (the file size captured at daemon start).

    Historical cascade_complete entries from PRIOR runs are ignored — this
    is the fix for the bug where a daemon launched in a tree with a Run-1
    `cascade_complete` post on disk would exit immediately at tick 1.
    """
    topic_file = COMMONS_TOPICS_DIR / f"{input_plan_topic}.md"
    if not topic_file.exists():
        return False
    current_size = topic_file.stat().st_size
    if current_size <= initial_size:
        return False
    with topic_file.open( "r", encoding="utf-8" ) as f:
        f.seek( initial_size )
        new_content = f.read()
    # Match either spacing convention in the JSON-stringified metadata
    return '"kind": "cascade_complete"' in new_content or '"kind":"cascade_complete"' in new_content


def manager_responded_since( manager: str, since_ts: float ) -> bool:
    """
    Cheap liveness check: scan all topic files for any mtime > since_ts that
    contains the manager persona name. Crude but adequate — false positives
    (any topic touched by anyone) just RESET the strike counter, which is
    safe-fail (delay rather than spurious DMS).
    """
    manager_lower = manager.lower()
    for topic_file in COMMONS_TOPICS_DIR.glob( "*.md" ):
        try:
            if topic_file.stat().st_mtime <= since_ts:
                continue
            content = topic_file.read_text( encoding="utf-8" )
            if manager_lower in content.lower():
                return True
        except Exception:
            continue
    return False


def main():
    p = argparse.ArgumentParser( description="Cascade heartbeat scheduler" )
    p.add_argument( "--manager",            required=True,                                            help="Manager persona name (e.g. tiberius)" )
    p.add_argument( "--cadence-active",     type=int, default=180,                                    help="Cadence in seconds during active cascade (default 180 = 3 min)" )
    p.add_argument( "--cadence-idle",       type=int, default=300,                                    help="Cadence in seconds during idle phases (default 300 = 5 min)" )
    p.add_argument( "--strikes",            type=int, default=3,                                      help="Consecutive silent ticks before dead-man's-switch (default 3)" )
    p.add_argument( "--input-plan-topic",   default="cascaded-prototype-input-plan",                  help="Topic to watch for cascade_complete signal" )
    p.add_argument( "--api-base-url",       default=None,                                             help="Override LUPIN_API_URL (default :7999)" )
    p.add_argument( "--api-key-path",       default=str( DEFAULT_KEY_PATH ),                          help="Path to API key file" )
    p.add_argument( "--max-ticks",          type=int, default=0,                                      help="Exit after N ticks (0 = unbounded, default)" )
    p.add_argument( "--budget-threshold",   type=int, default=25,                                     help="Per-section message-count budget; warn manager once when any section exceeds (default 25)" )
    p.add_argument( "--section-glob",       default="cascaded-prototype-section-*.md",                help="Filename glob (under io/commons/) for section topic files watched by the budget side-task" )
    args = p.parse_args()

    api_base_url = args.api_base_url or os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
    api_key      = load_api_key( Path( args.api_key_path ) )
    store        = CommonsStore( root=LUPIN_ROOT )

    # Capture initial input-plan topic file size — cascade_complete detection
    # only fires on content added AFTER this point (ignores prior-run posts).
    input_plan_file = COMMONS_TOPICS_DIR / f"{args.input_plan_topic}.md"
    initial_size    = input_plan_file.stat().st_size if input_plan_file.exists() else 0

    print( f"[cascade-heartbeat] started" )
    print( f"  manager              : {args.manager}" )
    print( f"  cadence_active       : {args.cadence_active}s" )
    print( f"  cadence_idle         : {args.cadence_idle}s" )
    print( f"  strikes              : {args.strikes}" )
    print( f"  input_plan_topic     : {args.input_plan_topic}" )
    print( f"  input_plan_size_at_t0: {initial_size} bytes" )
    print( f"  api_base_url         : {api_base_url}" )
    print( f"  max_ticks            : {args.max_ticks if args.max_ticks else 'unbounded'}" )
    print( f"  budget_threshold     : {args.budget_threshold}" )
    print( f"  section_glob         : {args.section_glob}" )

    tick_num                 = 0
    consecutive_silent       = 0
    last_tick_ts             = time.time()
    dms_fired_this_strike    = False
    warned_sections : dict   = {}

    while True:
        tick_num += 1

        # Check for cascade-complete signal (only NEW content since daemon start)
        if cascade_is_complete( args.input_plan_topic, initial_size ):
            print( f"[cascade-heartbeat] cascade_complete signal detected (new content since t0); exiting cleanly at tick {tick_num}" )
            return 0

        # Budget side-task: warn manager once per section that exceeds the budget.
        # Runs BEFORE fire_heartbeat so the warn lands in the manager's queue
        # alongside the same tick's heartbeat-poke.
        check_section_budgets(
            section_glob    = args.section_glob,
            threshold       = args.budget_threshold,
            api_base_url    = api_base_url,
            api_key         = api_key,
            manager         = args.manager,
            store           = store,
            warned_sections = warned_sections,
        )

        # Fire heartbeat
        result = fire_heartbeat( api_base_url, api_key, args.manager, store, tick_num )
        print( f"[cascade-heartbeat] tick {tick_num}: {json.dumps( result )}" )

        # Wait one cadence then check manager liveness
        time.sleep( args.cadence_active )

        if manager_responded_since( args.manager, last_tick_ts ):
            if consecutive_silent > 0:
                print( f"[cascade-heartbeat] manager liveness restored at tick {tick_num}; resetting strike counter" )
            consecutive_silent     = 0
            dms_fired_this_strike  = False
        else:
            consecutive_silent += 1
            print( f"[cascade-heartbeat] no manager activity since tick {tick_num}; consecutive_silent={consecutive_silent}" )
            if consecutive_silent >= args.strikes and not dms_fired_this_strike:
                print( f"[cascade-heartbeat] dead-man's-switch FIRING — {consecutive_silent} consecutive silent ticks" )
                dms_result = fire_dead_mans_switch( api_base_url, api_key, args.manager, consecutive_silent )
                print( f"[cascade-heartbeat] DMS result: {json.dumps( dms_result )}" )
                dms_fired_this_strike = True
                # Continue running; user may revive. DMS won't re-fire until manager
                # comes back (which resets the flag).

        last_tick_ts = time.time()

        if args.max_ticks > 0 and tick_num >= args.max_ticks:
            print( f"[cascade-heartbeat] max-ticks {args.max_ticks} reached; exiting" )
            return 0


if __name__ == "__main__":
    sys.exit( main() or 0 )
