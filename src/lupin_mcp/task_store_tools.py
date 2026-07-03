"""
Task-store MCP wrapper transport — the impl layer behind the `task_create` /
`task_transition` / `task_query` tools registered in cosa_voice_mcp.py.

Spec of record: Lupin `src/rnd/v0.1.8/2026.06.11-task-store-phase1/02-mcp-wrapper-spec.md`.
Wrappers are TRANSPORT only — every structural rule (receipts on ->done,
typed blocked_by + next_chase_ts on ->blocked, terminal-state lockout, enum
membership) lives server-side in `cosa.rest.task_store_rules`; this layer
NEVER pre-validates (no rule duplication, no drift — spec §1).

Failure contract (spec §4):
    - `:7999` unreachable  -> explicit error dict, never raises (callers never
      block a Stop-hook path on the store; fail-open is hook-side, not here)
    - HTTP 422             -> the server's `detail.errors` list VERBATIM — the
      no-confabulation rejection text reaches the model unedited
    - HTTP 404             -> the server's `detail` string verbatim
"""

import requests

from cosa.agents.utils.sender_id import canonicalize_project_name

# Transport timeout for /api/tasks/* calls. Deliberately finite: a hung store
# must surface as a `server_unreachable` error dict, never a hung tool call.
TASK_STORE_TIMEOUT_SECONDS = 10.0


def task_store_request( method, path, api_base_url, api_key, json_body=None, params=None, timeout=TASK_STORE_TIMEOUT_SECONDS ):
    """
    Shared transport for the three task-store wrapper tools.

    Requires:
        - method is "GET", "POST", or "PATCH" (requests.request supports all
          three; PATCH backs the item-field edit / task_reassign seam)
        - path starts with "/api/tasks"
        - api_base_url is the Lupin server base URL (no trailing slash needed)
        - api_key is the outbound X-API-Key value, or None when unloadable

    Ensures:
        - returns the parsed 2xx JSON body verbatim on success
        - returns {"status": "error", "reason": "missing_auth_header", ...}
          when api_key is None (key file unreadable — same failure surface as
          the commons register-question lane)
        - returns {"status": "error", "reason": "server_unreachable", ...}
          on any connection/timeout/transport failure — NEVER raises
        - HTTP 422 -> {"status": "error", "http_status": 422,
          "errors": <detail.errors verbatim>} (spec §2.2 no-confabulation rule);
          a 422 whose detail is not the rules shape (e.g. FastAPI request
          validation) surfaces verbatim under "detail" instead
        - HTTP 404 -> {"status": "error", "http_status": 404,
          "detail": <server detail verbatim>}
        - any other non-2xx -> {"status": "error", "http_status": <code>,
          "detail": <body>}
    """
    if api_key is None:
        return {
            "status" : "error",
            "reason" : "missing_auth_header",
            "detail" : "outbound X-API-Key could not be loaded (src/conf/keys/notification-api-claude-code-dev unreadable?)",
        }

    url     = f"{api_base_url}{path}"
    headers = { "X-API-Key": api_key }

    try:
        resp = requests.request( method, url, headers=headers, json=json_body, params=params, timeout=timeout )
    except requests.exceptions.RequestException as e:
        return {
            "status" : "error",
            "reason" : "server_unreachable",
            "detail" : f"{type( e ).__name__}: {e}",
        }

    if 200 <= resp.status_code < 300:
        return resp.json()

    # Non-2xx: surface the server's words verbatim, never paraphrased.
    # A valid-JSON body is not necessarily a dict (an LB/proxy error shape can
    # be a bare list/str/int) — never call .get on it (F1, review of 1ed3c0dc).
    try:
        body   = resp.json()
        detail = body.get( "detail" ) if isinstance( body, dict ) else body
    except ValueError:
        detail = resp.text

    if resp.status_code == 422 and isinstance( detail, dict ) and "errors" in detail:
        return { "status": "error", "http_status": 422, "errors": detail[ "errors" ] }

    return { "status": "error", "http_status": resp.status_code, "detail": detail }


def task_create_impl(
    api_base_url,
    api_key,
    created_by,
    item_class,
    title,
    project,
    body                = None,
    owner_persona       = None,
    accountable_manager = None,
    gate_class          = "none",
    priority            = "P2",
    urgency             = "normal",
    source_qid          = None,
    correlation_key     = None,
    authority           = "standing",
):
    """
    POST /api/tasks — create one obligation row (always status=queued).

    Requires:
        - created_by is the bridge-stamped identity ("<persona> <8-hex sid>");
          the CALLER (cosa_voice_mcp) stamps it — it is never a tool param,
          so a session cannot impersonate (spec §2.1)

    Ensures:
        - returns the serialized item dict (201 body) verbatim on success
        - returns the task_store_request error contract otherwise
        - `project` is canonicalized through the shared `_PROJECT_ALIASES` map
          (e.g. "planning-is-prompting" -> "plan") at THIS write seam so the
          stored value matches what the owed-work oracle queries on READ
          (resolve_project_name() aliases identically). Without this, an
          aliased-repo session writes the raw repo name, the oracle queries the
          alias, query_owed returns 0, and the session false-idles while owing
          work (bug c6751cf8). One alias table, no duplication.
    """
    payload = {
        "item_class"          : item_class,
        "title"               : title,
        "project"             : canonicalize_project_name( project ),
        "created_by"          : created_by,
        "authority"           : authority,
        "body"                : body,
        "owner_persona"       : owner_persona,
        "accountable_manager" : accountable_manager,
        "gate_class"          : gate_class,
        "priority"            : priority,
        "urgency"             : urgency,
        "source_qid"          : source_qid,
        "correlation_key"     : correlation_key,
    }
    return task_store_request( "POST", "/api/tasks", api_base_url, api_key, json_body=payload )


def task_transition_impl(
    api_base_url,
    api_key,
    actor,
    task_id,
    to_status,
    receipt_refs  = None,
    next_chase_ts = None,
    blocked_by    = None,
    reason        = None,
    authority     = "standing",
):
    """
    POST /api/tasks/{task_id}/transition — one state change + one audit event.

    Requires:
        - actor is the bridge-stamped identity (caller stamps, never a param)
        - task_id is the item's UUID string (a malformed id is the server's
          422 to report, not ours — transport only)

    Ensures:
        - returns { item, event } (200 body) verbatim on success
        - 422 surfaces the server's detail.errors VERBATIM (spec §2.2)
        - 404 surfaces "task {id} not found" verbatim
        - `reason` passes through verbatim (spec amendment 2026-06-12 / Phase-2
          contract §1.11(B): server-REQUIRED non-empty for ->dropped once the
          C12 pull-forward lands; the pre-Phase-2 server ignores the field)
    """
    payload = {
        "to_status"     : to_status,
        "actor"         : actor,
        "authority"     : authority,
        "receipt_refs"  : receipt_refs,
        "next_chase_ts" : next_chase_ts,
        "blocked_by"    : blocked_by,
        "reason"        : reason,
    }
    return task_store_request( "POST", f"/api/tasks/{task_id}/transition", api_base_url, api_key, json_body=payload )


def task_correlate_impl(
    api_base_url,
    api_key,
    actor,
    task_id,
    correlation_key,
    authority = "standing",
):
    """
    POST /api/tasks/{task_id}/correlate — re-stamp an item's correlation_key
    (cross-session respawn adoption: a successor session ADOPTS an inherited
    item by re-keying it onto its own harness id instead of forking a
    duplicate). The server appends an audited 're-correlated' event (R3).

    Requires:
        - actor is the bridge-stamped identity ("<persona> <8-hex sid>"); the
          CALLER (cosa_voice_mcp) stamps it — never a tool param, so a session
          cannot impersonate (spec §2.1, same lane as task_transition's actor)
        - task_id is the item's UUID string (a malformed id is the server's
          reject to report, not ours — transport only)
        - correlation_key is the new key to stamp (server validates 1..255)

    Ensures:
        - returns { item, event } (200 body) verbatim on success
        - 404 surfaces "task {id} not found" verbatim
        - 422 surfaces the server's detail VERBATIM (spec §2.2) — terminal
          items (no re-keying closed history) and bad authority are the
          server's reject, never pre-checked here
    """
    payload = {
        "correlation_key" : correlation_key,
        "actor"           : actor,
        "authority"       : authority,
    }
    return task_store_request( "POST", f"/api/tasks/{task_id}/correlate", api_base_url, api_key, json_body=payload )


def task_reassign_impl(
    api_base_url,
    api_key,
    actor,
    task_id,
    new_owner_persona,
    reason,
    new_manager = None,
    authority   = "manager_relay",
):
    """
    PATCH /api/tasks/{task_id} — re-own an item (ownership ONLY, never status).

    The thin transport behind the `task_reassign` MCP verb (design §4.2). Builds
    the item-PATCH body and rides the SAME `/api/tasks/{id}` endpoint Rick's
    multiplexer uses for owner edits; the server is the single normalization +
    audit seam (it canonicalizes the persona fields via `normalize_patch_fields`
    and appends one `patched` event carrying `reason`). Transport stays thin —
    no client-side normalization, no pre-validation (a bad id / blank reason is
    the server's reject to report, not ours).

    Requires:
        - actor is the bridge-stamped identity ("<persona> <8-hex sid>"); the
          CALLER (cosa_voice_mcp) stamps it — never a tool param, so a session
          cannot impersonate (spec §4.2, same lane as task_transition's actor)
        - task_id is the item's UUID string (a malformed id is the server's 422
          to report, not ours — transport only)
        - new_owner_persona is the handoff target's name (the server normalizes
          it to the canonical owed-query key)
        - reason is the manager's non-empty justification (the verb enforces
          non-empty; here it passes through verbatim to stamp the audit event)

    Ensures:
        - PATCH body carries owner_persona + reason + actor + authority always
        - accountable_manager is included ONLY when new_manager is not None — an
          omitted new_manager leaves the chasing manager UNCHANGED (design Q6),
          because the server's model_dump(exclude_unset=True) would otherwise
          read an explicit null as "clear the manager"
        - status is NEVER in the body — PATCH is walled off from the state
          machine (design D4); a handoff that should also re-queue is a separate
          task_transition
        - returns { item, event } (200 body) verbatim on success
        - 404 surfaces "task {id} not found" verbatim
        - 422 surfaces the server's detail.errors VERBATIM (terminal item / bad
          authority / blank reason are the server's reject, never pre-checked)
    """
    payload = {
        "owner_persona" : new_owner_persona,
        "reason"        : reason,
        "actor"         : actor,
        "authority"     : authority,
    }
    if new_manager is not None:
        payload[ "accountable_manager" ] = new_manager
    return task_store_request( "PATCH", f"/api/tasks/{task_id}", api_base_url, api_key, json_body=payload )


def task_amend_impl(
    api_base_url,
    api_key,
    actor,
    task_id,
    note,
    reason    = None,
    authority = "standing",
):
    """
    POST /api/tasks/{task_id}/amend — append a persona-stamped block to an item's
    body (APPEND-ONLY; the original body is preserved verbatim server-side) +
    append an audited 'amended' event. The mid-flight scope-reframe seam
    (Krishna's 2026-07-02 friction): a live item whose spec is legitimately
    reframed gets the new spec appended to its DURABLE body, so a successor
    rehydrating from the store reads the current spec inline instead of chasing
    it through scratchpad checklists / code comments / transition reasons.

    Distinct from task_reassign's PATCH (which OVERWRITES `body`): an amend can
    never lose prior spec history.

    Requires:
        - actor is the bridge-stamped identity ("<persona> <8-hex sid>"); the
          CALLER (cosa_voice_mcp) stamps it — never a tool param, so a session
          cannot impersonate (spec §2.1, same lane as task_transition's actor)
        - task_id is the item's UUID string (a malformed id is the server's
          reject to report, not ours — transport only)
        - note is the amendment text (server validates 1..4000 + non-blank)

    Ensures:
        - returns { item, event } (200 body) verbatim on success
        - 404 surfaces "task {id} not found" verbatim
        - 422 surfaces the server's detail VERBATIM (spec §2.2) — terminal items
          (no amending closed history), a blank note, and a bad authority are the
          server's reject, never pre-checked here
    """
    payload = {
        "note"      : note,
        "reason"    : reason,
        "actor"     : actor,
        "authority" : authority,
    }
    return task_store_request( "POST", f"/api/tasks/{task_id}/amend", api_base_url, api_key, json_body=payload )


def task_query_impl(
    api_base_url,
    api_key,
    owner_persona       = None,
    status              = None,
    gate_class          = None,
    urgency             = None,
    accountable_manager = None,
    project             = None,
    item_class          = None,
    correlation_key     = None,
    limit               = None,
    offset              = None,
    terse               = False,
):
    """
    GET /api/tasks — the deterministic owed-work query (design R4).

    Ensures:
        - returns { tasks, count } verbatim on success
        - omits unset filters entirely (server defaults apply), so a no-arg
          call is "everything, newest first" — the manager board glance
        - `correlation_key` exact-match filter passes through (spec amendment
          2026-06-12 / Phase-2 contract §1.11(C); pre-Phase-2 server ignores it)
        - terse=True (§G token win) requests the at-a-glance projection
          (id/title/status/blocked_by/next_chase_ts/priority — body dropped);
          passed to the server as the canonical lowercase "true" (a pre-§G
          server simply ignores the unknown param and returns full rows)
        - the `project` filter is canonicalized through the shared
          `_PROJECT_ALIASES` map (mirror of the write seam) so an agent-facing
          query by the raw repo name still matches the canonically-stored rows
          (read == write; the same alias the oracle applies — bug c6751cf8)
    """
    filters = {
        "owner_persona"       : owner_persona,
        "status"              : status,
        "gate_class"          : gate_class,
        "urgency"             : urgency,
        "accountable_manager" : accountable_manager,
        "project"             : canonicalize_project_name( project ),
        "item_class"          : item_class,
        "correlation_key"     : correlation_key,
        "limit"               : limit,
        "offset"              : offset,
    }
    params = { key: value for key, value in filters.items() if value is not None }
    if terse:
        params[ "terse" ] = "true"
    return task_store_request( "GET", "/api/tasks", api_base_url, api_key, params=params )
