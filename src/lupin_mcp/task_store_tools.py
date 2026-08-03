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
from lupin_mcp.outbound_api_key import outbound_key_failure_detail

# Transport timeout for /api/tasks/* calls. Deliberately finite: a hung store
# must surface as a `server_unreachable` error dict, never a hung tool call.
TASK_STORE_TIMEOUT_SECONDS = 10.0

# task_edit exposes 5 of the server's 7 PATCH_EDITABLE_FIELDS: the two OWNER
# fields are deliberately excluded so owner-change stays on the single
# mandatory-reason `task_reassign` path. A raw PATCH would ACCEPT owner fields —
# the MCP-layer refusal below is the ONLY thing barring them, asserted at this
# boundary, never a server 422. Invariant-bearing fields remain refused by the
# server's `extra="forbid"` (inherited); actor/authority/reason are neutralized
# by stamping them LAST (a caller key cannot shadow the bridge identity).
TASK_EDIT_OWNER_FIELDS = ( "owner_persona", "accountable_manager" )


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
          the commons register-question lane), whose `detail` names the
          concrete cause: absent file, or mode + owner uid when it is present
          but unreadable by this process
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
            "detail" : outbound_key_failure_detail( path ),
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
    status              = "queued",
    blocked_by          = None,
    next_chase_ts       = None,
    source_qid          = None,
    correlation_key     = None,
    authority           = "standing",
):
    """
    POST /api/tasks — create one obligation row (DEFAULT status=queued).

    Requires:
        - created_by is the bridge-stamped identity ("<persona> <8-hex sid>");
          the CALLER (cosa_voice_mcp) stamps it — it is never a tool param,
          so a session cannot impersonate (spec §2.1)

    Ensures:
        - returns the serialized item dict (201 body) verbatim on success
        - returns the task_store_request error contract otherwise
        - `status` defaults to "queued" (today's behavior); pass "blocked" to
          MINT an already-blocked row in one call (Rick 2026-07-20). A blocked
          mint carries `blocked_by` (>=1 typed ref [{kind, id}]) and
          `next_chase_ts` (ISO-8601 — REQUIRED when a {kind:persona} ref is
          present, I3). Transport only: the status whitelist, the ->blocked
          invariant, AND the MANAGER-ONLY guard are all enforced SERVER-side and
          surface verbatim (a non-manager blocked mint is a 403, a bad status /
          missing chase is a 422) — this layer NEVER pre-validates.
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
        "status"              : status,
        "blocked_by"          : blocked_by,
        "next_chase_ts"       : next_chase_ts,
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
    park_reason   = None,
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
        - `park_reason` passes through verbatim: server-REQUIRED non-blank for
          ->parked, and it MUST quote the row's OWN decisive sentence rather
          than paraphrase it (that quote is what makes a park refutable by the
          next reader instead of re-derived)
    """
    payload = {
        "to_status"     : to_status,
        "actor"         : actor,
        "authority"     : authority,
        "receipt_refs"  : receipt_refs,
        "next_chase_ts" : next_chase_ts,
        "blocked_by"    : blocked_by,
        "reason"        : reason,
        "park_reason"   : park_reason,
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

    A TERMINAL item is ALLOWED (Rick's ruling 2026-08-02): amend is the ONE write
    verb accepted on a done/dropped row — a gate verdict written after a worker
    self-closes needs a durable home. The server marks it a post-terminal addendum
    and stamps an 'amended_post_terminal' event; status is not moved.

    Ensures:
        - returns { item, event } (200 body) verbatim on success
        - 404 surfaces "task {id} not found" verbatim
        - 422 surfaces the server's detail VERBATIM (spec §2.2) — a blank note and
          a bad authority are the server's reject, never pre-checked here. A
          terminal item is NO LONGER a 422: it lands as a post-terminal addendum
    """
    payload = {
        "note"      : note,
        "reason"    : reason,
        "actor"     : actor,
        "authority" : authority,
    }
    return task_store_request( "POST", f"/api/tasks/{task_id}/amend", api_base_url, api_key, json_body=payload )


def task_edit_impl(
    api_base_url,
    api_key,
    actor,
    task_id,
    updates,
    reason    = None,
    authority = "standing",
):
    """
    PATCH /api/tasks/{task_id} — edit one or more of the 5 FREE-EDIT fields
    (`title` · `body` · `priority` · `gate_class` · `urgency`) of a NON-terminal
    item, atomically, in one txn + one audit event.

    The thin transport behind the `task_edit` MCP verb (design §4, MCP parity for
    PATCH), riding the SAME `/api/tasks/{id}` endpoint `task_reassign` uses. It
    carries ONE piece of new logic: an OWNER-FIELD REFUSAL. `task_edit`'s set (5)
    is a deliberate SUBSET of the server's 7-key `PATCH_EDITABLE_FIELDS` — the two
    owner fields (`owner_persona`, `accountable_manager`) are excluded so
    owner-change stays on the single mandatory-reason `task_reassign` path. A raw
    PATCH would ACCEPT owner fields, so this refusal MUST happen HERE, at the MCP
    boundary — it is not an inherited server 422.

    Everything else stays inherited/thin:
      - invariant fields (`status`, `blocked_by`, `next_chase_ts`, `park_reason`,
        `park_reason_captured_at`, `receipt_refs`, `correlation_key`) are refused
        by the server's `extra="forbid"` → 422 (not pre-checked here);
      - `actor`/`authority`/`reason` are stamped LAST, so a caller key of the same
        name in `updates` cannot shadow the bridge identity (basic anti-spoof);
      - value validation (bad enum / empty title) stays server-side (validate_patch).

    Requires:
        - actor is the bridge-stamped identity ("<persona> <8-hex sid>"); the
          CALLER (cosa_voice_mcp) stamps it — never a tool param, so a session
          cannot impersonate (spec §4, same lane as task_reassign's actor)
        - task_id is the item's UUID string (a malformed id is the server's 422
          to report, not ours — transport only)
        - updates is a dict of {field: value} (the verb enforces non-empty-dict
          before this is reached)

    Ensures:
        - an OWNER field in `updates` aborts with an error dict BEFORE any
          round-trip: {"status":"error","reason":"owner_field_refused",
          "detail":<points to task_reassign>}
        - otherwise: PATCH body is the `updates` dict PLUS bridge-stamped
          authority + reason + actor, with `actor` stamped LAST
        - returns { item, event } (200 body) verbatim on success
        - 404 surfaces "task {id} not found" verbatim
        - 422 surfaces the server's detail VERBATIM (invariant field via
          extra=forbid / bad enum / empty title / terminal item — the server's reject)
    """
    for key in updates:
        if key in TASK_EDIT_OWNER_FIELDS:
            return { "status" : "error", "reason" : "owner_field_refused",
                     "detail" : f"task_edit cannot change '{key}' — use task_reassign (the owner-change path, with a mandatory reason + manager_relay authority)" }
    payload = dict( updates )
    payload[ "authority" ] = authority
    payload[ "reason" ]    = reason
    payload[ "actor" ]     = actor    # stamped LAST — a caller key cannot shadow the bridge identity
    return task_store_request( "PATCH", f"/api/tasks/{task_id}", api_base_url, api_key, json_body=payload )


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
    id_prefix           = None,
    limit               = None,
    offset              = None,
    terse               = False,
    include_terminal    = False,
    unscoped_audit      = False,
    include_parked      = False,
):
    """
    GET /api/tasks — the deterministic owed-work query (design R4).

    Ensures:
        - returns { tasks, count, total, has_more, truncated, warnings } verbatim
          on success — a THIN PROXY, so the truthful-envelope fields (mini-plan
          02, 2026-07-21) reach the agent rather than dying at this seam. `count`
          is the PAGE length and saturates at `limit`; `total` is the true
          filter-matching count and `has_more` is the field to branch on. A
          pre-mini-plan-02 server simply returns the two-key shape
        - omits unset filters entirely (server defaults apply), so a no-arg
          call is "everything, newest first" — the manager board glance
        - `correlation_key` exact-match filter passes through (spec amendment
          2026-06-12 / Phase-2 contract §1.11(C); pre-Phase-2 server ignores it)
        - `id_prefix` filters BY IDENTITY and accepts the 8-hex form every brief,
          DM and cross-reference in this fleet is written in — or a full UUID,
          which is normalized server-side (row f45b37a9 remedy 2, closing
          4288dd53). Until this shipped, `task_query` had NO id filter at all and
          `task_get` demanded a full UUID, so the identifier the fleet
          communicates in could not fetch the thing it names. Junk 422s rather
          than reaching SQL: a LIKE built from arbitrary caller text would turn an
          id lookup into a search surface. It counts as a SCOPING filter, so an
          id_prefix query is never rejected by the unscoped-size guard.
        - terse=True (§G token win) requests the at-a-glance projection
          (id/title/status/blocked_by/next_chase_ts/priority/park_reason_stale
          — body dropped);
          passed to the server as the canonical lowercase "true" (a pre-§G
          server simply ignores the unknown param and returns full rows)
        - include_terminal=True includes done/dropped rows on an un-status'd
          query (default: terminal rows excluded — the 89->2 payload collapse);
          unscoped_audit=True is the deliberate-full-sweep escape past the
          unscoped-size guard. Both are forwarded ONLY when truthy, as the
          canonical lowercase "true" (mirror of terse), so a pre-guard server
          simply ignores the unknown params.
        - the `project` filter is canonicalized through the shared
          `_PROJECT_ALIASES` map (mirror of the write seam) so an agent-facing
          query by the raw repo name still matches the canonically-stored rows
          (read == write; the same alias the oracle applies — bug c6751cf8)
        - PARKED-STATUS (2026-07-19): park-ACTIVE rows are HIDDEN by default —
          the server suppresses them (hide_parked defaults true). A parked row
          whose next_chase_ts has PASSED is NOT parked any more and stays
          VISIBLE: it has rejoined the owed count, and a row that pokes you
          while staying invisible on the board is the exact incoherence this
          build removes. Surface the parked set with include_parked=True or by
          asking for status="parked" directly (the audit surface). Forwarded
          ONLY when truthy, as the canonical lowercase "true" (mirror of terse),
          so a pre-parked server ignores the unknown param.
        - PARK-REASON STALENESS (2026-07-19): every row carries
          `park_reason_stale` (bool), in the TERSE projection as well as the
          full shape — a flag only the full row carried would be a flag nobody
          reads. True means the row's BODY CHANGED AFTER its `park_reason` quote
          was frozen, so the quote is no longer known to describe the row.
          ADVISORY ONLY: it changes no owed-ness, unparks nothing, blocks
          nothing. Re-park to re-freeze the quote. Rows parked before this
          shipped, and rows never parked, report False.
          ⚠️ FIXED 2026-07-26 (bug 54924128): it used to read `updated_ts`, which
          EVERY write bumps, so a priority-only edit during a board recut defamed
          a correct quote — every parked row in the store was falsely flagged when
          it was found. It now reads `body_changed_ts`. The fix ships no backfill,
          so the flag stays quiet on each existing row until that row's body next
          changes; a pre-2026-07-26 `true` should be re-checked, not trusted.
        - STRANDED BLOCKERS (2026-07-25, row 00a6bde2): every row also carries
          `blocker_terminal` (bool), likewise in TERSE as well as the full shape.
          True means this row is `blocked` on an ITEM that is already done or
          dropped — or that no longer resolves at all — so the wait can never be
          satisfied by the mechanism the row is relying on. The row is not
          waiting, it is STRANDED, and it reads identically to waiting. Six live
          instances were found BY HAND on 2026-07-25, one unsatisfiable for eight
          days, because `blocked` is the one status that cannot self-heal and had
          no staleness oracle. ADVISORY, exactly like park_reason_stale: it
          transitions nothing. THE DISPOSITION IS SPLIT — a `done` blocker means
          the precondition actually happened (the row should rejoin); a `dropped`
          one means somebody decided otherwise (a silent rejoin would overturn
          it). Persona- and user-kind blockers NEVER set this flag: neither has a
          resolvable lifecycle, so an absence there is silence, not death.
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
        "id_prefix"           : id_prefix,
        "limit"               : limit,
        "offset"              : offset,
    }
    params = { key: value for key, value in filters.items() if value is not None }
    if terse:            params[ "terse" ]            = "true"
    if include_terminal: params[ "include_terminal" ] = "true"
    if unscoped_audit:   params[ "unscoped_audit" ]   = "true"
    # include_parked flips the server-side default OFF; only sent when asked, so
    # an older server (no such param) keeps today's behavior rather than 400ing.
    if include_parked:   params[ "hide_parked" ]       = "false"
    return task_store_request( "GET", "/api/tasks", api_base_url, api_key, params=params )


def task_get_impl( api_base_url, api_key, task_id ):
    """
    GET /api/tasks/{task_id} — fetch ONE store row by its UUID (4288dd53).

    The failure this closes, named because the MCP docstring is the only doc
    most seats read: a filtered query's empty result is NOT evidence a row is
    absent — a row can be sitting at offset=15 of a limit=15 page and read as
    gone. `task_query` can only ASK A FILTER and scan its results, so "does row
    X exist / what does it say" has to be inferred from a page's silence, and
    silence is not an answer. This asks about ONE row directly.

    THIN PROXY — no server change. The route (routers/tasks.py get_task) is
    already live and authenticated; this exposes it to the MCP surface and does
    nothing else. Same auth/transport/error contract as every other store verb,
    because it rides the same `task_store_request` transport:

    Requires:
        - task_id is the item's UUID string. A malformed id is the SERVER's
          reject to surface (422), never pre-checked here — transport only, no
          rule duplication (spec §1).

    Ensures:
        - 200 → the FULL serialized item verbatim (including `body`, never the
          terse projection) — this is the whole point: you asked for the row,
          you get the row
        - 404 → an ERROR DICT carrying the server's detail verbatim
          ("task {id} not found"). NEVER an empty success, NEVER None: an absent
          row rendered as a silent nothing is the exact confusion this verb
          exists to kill
        - 422 (malformed UUID) → the server's detail verbatim, not a client-side
          raise
        - api_key None / server unreachable → the shared error-dict contract
          (missing_auth_header / server_unreachable); NEVER raises
    """
    return task_store_request( "GET", f"/api/tasks/{task_id}", api_base_url, api_key )
