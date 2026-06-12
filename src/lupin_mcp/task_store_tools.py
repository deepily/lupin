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

# Transport timeout for /api/tasks/* calls. Deliberately finite: a hung store
# must surface as a `server_unreachable` error dict, never a hung tool call.
TASK_STORE_TIMEOUT_SECONDS = 10.0


def task_store_request( method, path, api_base_url, api_key, json_body=None, params=None, timeout=TASK_STORE_TIMEOUT_SECONDS ):
    """
    Shared transport for the three task-store wrapper tools.

    Requires:
        - method is "GET" or "POST"
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
    try:
        detail = resp.json().get( "detail" )
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
    """
    payload = {
        "item_class"          : item_class,
        "title"               : title,
        "project"             : project,
        "created_by"          : created_by,
        "authority"           : authority,
        "body"                : body,
        "owner_persona"       : owner_persona,
        "accountable_manager" : accountable_manager,
        "gate_class"          : gate_class,
        "priority"            : priority,
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
    """
    payload = {
        "to_status"     : to_status,
        "actor"         : actor,
        "authority"     : authority,
        "receipt_refs"  : receipt_refs,
        "next_chase_ts" : next_chase_ts,
        "blocked_by"    : blocked_by,
    }
    return task_store_request( "POST", f"/api/tasks/{task_id}/transition", api_base_url, api_key, json_body=payload )


def task_query_impl(
    api_base_url,
    api_key,
    owner_persona       = None,
    status              = None,
    gate_class          = None,
    accountable_manager = None,
    project             = None,
    item_class          = None,
    limit               = None,
    offset              = None,
):
    """
    GET /api/tasks — the deterministic owed-work query (design R4).

    Ensures:
        - returns { tasks, count } verbatim on success
        - omits unset filters entirely (server defaults apply), so a no-arg
          call is "everything, newest first" — the manager board glance
    """
    filters = {
        "owner_persona"       : owner_persona,
        "status"              : status,
        "gate_class"          : gate_class,
        "accountable_manager" : accountable_manager,
        "project"             : project,
        "item_class"          : item_class,
        "limit"               : limit,
        "offset"              : offset,
    }
    params = { key: value for key, value in filters.items() if value is not None }
    return task_store_request( "GET", "/api/tasks", api_base_url, api_key, params=params )
