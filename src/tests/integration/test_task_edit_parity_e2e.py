"""
Integration test — `task_edit` MCP verb, live HTTP round-trip (plan
`src/rnd/v0.1.9/2026.07.20-generalized-task-field-edit-mcp-parity.md` §6,
AMENDED by plan-review 2026-07-20).

Drives the REAL `task_edit_impl` transport (`lupin_mcp/task_store_tools.py`)
against the live `patch_task` REST route (`routers/tasks.py`, already deployed on
both servers). The MCP verb runs IN THIS TEST PROCESS (imported), so the server
needs no new code — only the ALREADY-SHIPPED `PATCH /api/tasks/{id}` endpoint.

TWO BUCKETS (post-amendment — the MCP verb's set DIVERGES from the server's):
    task_edit FREE-EDIT (5): title · body · priority · gate_class · urgency
    task_edit REFUSED:
      · owner_persona · accountable_manager  — MCP-LAYER refusal (a RAW PATCH
        ACCEPTS these; task_edit strips them and points to `task_reassign`).
        The in-process test is what catches this — assert the IMPL-boundary
        rejection, NOT a server 422.
      · status · blocked_by · next_chase_ts · park_reason ·
        park_reason_captured_at · receipt_refs · correlation_key — server
        extra='forbid' (wire 422), inherited verbatim.

VENUE: :8000 scheduled (submit via POST /api/test-suite/submit). This suite
CREATES + EDITS real Postgres rows, so a write outlives each arm until teardown
drops it — the venue rubric forces the mutating venue (:8000), never :7999.

Arms (amended spec §5 ACs / §6 test plan):
    §6.1 / AC1-2 : the 5 free-edit fields round-trip in ONE call → 200, single event
    AC8          : owner_persona / accountable_manager → CLIENT-SIDE refusal
                   (reason=owner_field_refused, points to task_reassign), no mutation
    §6.2 / AC3   : each of the 7 invariant fields → FORWARDS → server 422
                   (extra='forbid'), no mutation
    §6.3 / AC4   : enum-illegal (priority=P9, gate_class=bogus, empty title) → server 422, no mutation
    AC7b         : smuggled `actor` in updates → FORWARDS + STAMPED-OVER → 200,
                   event.actor==bridge (never 'victim'), the legit field still applies
    AC6          : empty updates={} → server 422 (impl FORWARDS; only the verb rejects it)
    §6.4 / AC5   : terminal item → rejected
    §6.6         : REGRESSION — task_amend still APPEND-ONLY

Impl-boundary shapes pinned to Clayton's FINAL contract (DM 2026-07-20, confirmed
line-by-line): the ONLY client-side rejects (error dict, no wire) are the 2 owner
fields; EVERYTHING else forwards — invariant-7 + empty{} + enum-illegal → server
422, and a smuggled actor is stamped-over (edit succeeds, bridge actor wins).
Re-verify against his committed build before submitting to :8000.

Base URL parameterized via LUPIN_TASK_EDIT_BASE_URL (default the :7999 dev
server; the :8000 test-suite runner targets its own in-container server).
"""

import os
import uuid

import pytest

from lupin_mcp.task_store_tools import (
    task_edit_impl,
    task_amend_impl,
    task_create_impl,
    task_transition_impl,
    task_store_request,
)


BASE_URL = os.environ.get( "LUPIN_TASK_EDIT_BASE_URL", "http://localhost:7999" )
ACTOR    = "tiffany 2e399fd9"   # test actor (prod stamps the bridge identity; here a plain param)

# task_edit's FREE-EDIT set (5 — post-amendment; owner/manager REMOVED).
EDITABLE_FIELDS = ( "title", "body", "priority", "gate_class", "urgency" )

# MCP-LAYER refusals: a raw PATCH accepts these, task_edit strips + points to task_reassign.
OWNER_REFUSED_FIELDS = ( "owner_persona", "accountable_manager" )

# Server extra='forbid' invariant fields (wire 422) — inherited verbatim.
INVARIANT_REFUSED_FIELDS = (
    "status", "blocked_by", "next_chase_ts", "park_reason",
    "park_reason_captured_at", "receipt_refs", "correlation_key",
)

# A representative, INDIVIDUALLY-legal value per invariant field — proves the
# refusal is STRUCTURAL, not a value-validation accident.
INVARIANT_VALUES = {
    "status"                  : "done",
    "blocked_by"              : [ { "kind": "task", "id": str( uuid.uuid4() ) } ],
    "next_chase_ts"           : "2026-08-01T12:00:00+00:00",
    "park_reason"             : "parked: awaiting Rick",
    "park_reason_captured_at" : "2026-08-01T12:00:00+00:00",
    "receipt_refs"            : [ "commit:deadbeef" ],
    "correlation_key"         : "corr-123",
}


def _api_key():
    """Load the same outbound X-API-Key the MCP verb uses; skip if unreadable."""
    try:
        import cosa.utils.util as du
        return du.get_api_key( "notification-api-claude-code-dev" )
    except Exception:
        return None


@pytest.fixture( scope="module" )
def api_key():
    key = _api_key()
    if key is None:
        pytest.skip( "outbound notification-api-claude-code-dev key unreadable" )
    return key


def _make_probe( api_key, **overrides ):
    """Create one fresh, non-terminal probe row for a mutation arm (status=='queued')."""
    body = {
        "created_by" : ACTOR,
        "item_class" : "task",
        "title"      : "task_edit parity probe (PRE-EDIT)",
        "project"    : "lupin",
        "body"       : "PROBE-ORIGINAL-BODY",
        "priority"   : "P2",
        "gate_class" : "none",
        "urgency"    : "normal",
    }
    body.update( overrides )
    item = task_create_impl( BASE_URL, api_key, **body )
    assert isinstance( item, dict ) and item.get( "status" ) == "queued", f"probe create failed: {item!r}"
    return item


def _drop( api_key, task_id ):
    """Best-effort teardown: transition a probe row to terminal so it stops owing."""
    try:
        task_transition_impl(
            BASE_URL, api_key, ACTOR, task_id, "dropped",
            reason="task_edit parity E2E teardown — probe row retired",
        )
    except Exception:
        pass   # teardown hygiene only; never fail an arm on cleanup


def _fetch( api_key, task_id ):
    """Read the full row back via the deployed single-id query route."""
    body = task_store_request( "GET", f"/api/tasks/{task_id}", BASE_URL, api_key )
    assert isinstance( body, dict ), f"fetch of {task_id} failed: {body!r}"
    return body


def _is_refused( resp ):
    """A task_edit_impl result is a refusal iff it is the error-contract dict."""
    return isinstance( resp, dict ) and resp.get( "status" ) == "error"


@pytest.fixture
def probe( api_key ):
    item = _make_probe( api_key )
    yield item
    _drop( api_key, item[ "id" ] )


# ---------------------------------------------------------------------------
# §6.1 — the 5 free-edit fields round-trip in ONE atomic call → single event
# ---------------------------------------------------------------------------
def test_five_editable_fields_roundtrip_single_event( probe, api_key ):
    """
    AC1/AC2: a single task_edit setting all 5 free-edit fields returns 200,
    reflects every new value, and yields exactly ONE `patched` audit event.
    """
    task_id = probe[ "id" ]
    updates = {
        "title"      : "task_edit parity probe (POST-EDIT)",
        "body"       : "PROBE-EDITED-BODY",
        "priority"   : "P3",           # the C7 demotion the plan exists for
        "gate_class" : "manager",
        "urgency"    : "low",
    }
    resp = task_edit_impl( BASE_URL, api_key, ACTOR, task_id, updates, reason="parity E2E: full 5-field edit" )

    assert not _is_refused( resp ), f"edit failed: {resp!r}"
    item, event = resp[ "item" ], resp[ "event" ]

    assert isinstance( event, dict ),          f"expected ONE event dict: {event!r}"
    assert event[ "transition" ] == "patched", f"expected 'patched' event: {event!r}"

    assert item[ "title" ]      == updates[ "title" ]
    assert item[ "body" ]       == updates[ "body" ]
    assert item[ "priority" ]   == "P3"
    assert item[ "gate_class" ] == "manager"
    assert item[ "urgency" ]    == "low"


# ---------------------------------------------------------------------------
# AC8 — owner_persona / accountable_manager are MCP-LAYER refusals
# ---------------------------------------------------------------------------
@pytest.mark.parametrize( "field", OWNER_REFUSED_FIELDS )
def test_owner_field_mcp_layer_refusal_points_to_reassign( field, probe, api_key ):
    """
    AC8: task_edit REFUSES owner_persona / accountable_manager even though a raw
    PATCH would accept them — the divergence caught only by driving the impl.
    Assert the impl-boundary rejection + NO mutation; message SHOULD name
    task_reassign (checked tolerantly — Clayton's final wording).
    """
    task_id = probe[ "id" ]
    before  = _fetch( api_key, task_id )

    resp = task_edit_impl(
        BASE_URL, api_key, ACTOR, task_id, { field: "Mr. Radio" },
        reason=f"parity E2E: owner-field refusal {field}",
    )

    # Clayton's FINAL contract: CLIENT-SIDE reject, no round-trip, reason=owner_field_refused.
    assert _is_refused( resp ),                          f"{field}: expected MCP-layer refusal, got {resp!r}"
    assert resp.get( "reason" ) == "owner_field_refused", f"{field}: wrong refusal reason: {resp!r}"
    assert "task_reassign" in str( resp ),               f"{field}: refusal must point to task_reassign: {resp!r}"

    after = _fetch( api_key, task_id )
    assert after[ "updated_ts" ] == before[ "updated_ts" ], f"{field}: row mutated despite refusal"


# ---------------------------------------------------------------------------
# §6.2 / AC3 — each server-invariant field refused, no row mutation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize( "field", INVARIANT_REFUSED_FIELDS )
def test_each_invariant_field_refused_no_mutation( field, probe, api_key ):
    """
    AC3: setting any of the 7 invariant fields via task_edit is REFUSED. Per
    Clayton's FINAL contract (correction 2026-07-20) the impl FORWARDS these and
    the server's extra='forbid' 422s them — a SERVER 422 at the impl layer, not a
    client-side reason. No-mutation (updated_ts) is the message-independent proof.
    """
    task_id = probe[ "id" ]
    before  = _fetch( api_key, task_id )

    resp = task_edit_impl(
        BASE_URL, api_key, ACTOR, task_id, { field: INVARIANT_VALUES[ field ] },
        reason=f"parity E2E: refused invariant {field}",
    )

    assert _is_refused( resp ),              f"{field}: expected refusal, got {resp!r}"
    assert resp.get( "http_status" ) == 422, f"{field}: expected server 422 (extra=forbid), got {resp!r}"

    after = _fetch( api_key, task_id )
    assert after[ "status" ]     == before[ "status" ],     f"{field}: status drifted"
    assert after[ "updated_ts" ] == before[ "updated_ts" ], f"{field}: row written despite refusal"


# ---------------------------------------------------------------------------
# §6.3 / AC4 — enum-illegal / empty values → 422, no row mutation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "updates,label",
    [
        ( { "priority"   : "P9" },    "priority-P9" ),
        ( { "gate_class" : "bogus" }, "gate_class-bogus" ),
        ( { "title"      : "   " },   "title-blank" ),
    ],
)
def test_enum_illegal_value_422_no_mutation( updates, label, probe, api_key ):
    """AC4: validate_patch rejects a bad enum / blank title with 422; row unchanged."""
    task_id = probe[ "id" ]
    before  = _fetch( api_key, task_id )

    resp = task_edit_impl( BASE_URL, api_key, ACTOR, task_id, updates, reason=f"parity E2E: {label}" )

    assert _is_refused( resp ), f"{label}: expected 422 refusal, got {resp!r}"
    if "http_status" in resp:
        assert resp[ "http_status" ] == 422, f"{label}: expected 422, got {resp!r}"

    after = _fetch( api_key, task_id )
    assert after[ "updated_ts" ] == before[ "updated_ts" ], f"{label}: row mutated despite invalid value"


# ---------------------------------------------------------------------------
# AC7b — dict-smuggle: envelope keys in `updates` cannot spoof audit identity
# ---------------------------------------------------------------------------
def test_dict_smuggle_actor_is_stamped_over( probe, api_key ):
    """
    AC7b (security smoke): Rick waived the explicit smuggle-guard — a smuggled
    `actor` in `updates` is NOT rejected but STAMPED-OVER. task_edit_impl spreads
    updates then stamps actor/authority/reason LAST, so updates={"actor":"victim"}
    FORWARDS, the edit SUCCEEDS, and the audit event carries the REAL bridge actor
    (never 'victim'). Assert the stamp-over, not an error dict. Only `actor` is
    exercised (authority/reason arms dropped per the ruling).
    """
    task_id = probe[ "id" ]
    updates = { "actor": "victim", "priority": "P3" }

    resp = task_edit_impl( BASE_URL, api_key, ACTOR, task_id, updates, reason="parity E2E: actor stamp-over" )

    # Forwards + succeeds (the guard is waived) — NOT an error dict.
    assert not _is_refused( resp ),                 f"actor-smuggle should forward+succeed, got {resp!r}"
    event, item = resp[ "event" ], resp[ "item" ]
    # The bridge actor wins; the injected 'victim' is overwritten, never audited.
    assert event[ "actor" ] == ACTOR,               f"actor spoofed → {event[ 'actor' ]!r}"
    assert "victim" not in str( event[ "actor" ] ), "'victim' leaked into audit actor"
    # The legitimate field in the same dict still applies (P3 demotion).
    assert item[ "priority" ] == "P3",              f"legit field not applied: {item!r}"


# ---------------------------------------------------------------------------
# AC6 — empty updates={} → 422
# ---------------------------------------------------------------------------
def test_empty_updates_rejected( probe, api_key ):
    """
    AC6: an edit that sets nothing is rejected. SURFACE NOTE (Clayton): the
    task_edit VERB rejects {} client-side, but task_edit_IMPL (what this test
    calls) has no whitelist key to reject, so it FORWARDS → server 422
    (validate_patch empty-patch). Hence a real http_status 422 here, not a
    client-side reason.
    """
    task_id = probe[ "id" ]
    before  = _fetch( api_key, task_id )

    resp = task_edit_impl( BASE_URL, api_key, ACTOR, task_id, {}, reason="parity E2E: empty updates" )

    assert _is_refused( resp ),                  f"empty updates should be refused, got {resp!r}"
    assert resp.get( "http_status" ) == 422,     f"expected server 422 on empty updates, got {resp!r}"

    after = _fetch( api_key, task_id )
    assert after[ "updated_ts" ] == before[ "updated_ts" ], "empty updates mutated the row"


# ---------------------------------------------------------------------------
# §6.4 / AC5 — terminal item rejected
# ---------------------------------------------------------------------------
def test_terminal_item_edit_rejected( api_key ):
    """AC5: a done/dropped item refuses any edit ('no edits to closed history')."""
    item    = _make_probe( api_key, title="task_edit parity probe (TERMINAL)" )
    task_id = item[ "id" ]
    trans   = task_transition_impl(
        BASE_URL, api_key, ACTOR, task_id, "dropped",
        reason="parity E2E: retire to terminal for the reject arm",
    )
    assert not _is_refused( trans ), f"could not drop probe: {trans!r}"

    resp = task_edit_impl( BASE_URL, api_key, ACTOR, task_id, { "priority": "P1" }, reason="parity E2E: edit terminal" )

    assert _is_refused( resp ), f"terminal edit should be refused: {resp!r}"
    if "http_status" in resp:
        assert resp[ "http_status" ] == 422, f"expected 422 on terminal edit, got {resp!r}"
    # No teardown — the row is already terminal.


# ---------------------------------------------------------------------------
# §6.6 — REGRESSION: task_amend stays APPEND-ONLY (no field overwrite)
# ---------------------------------------------------------------------------
def test_task_amend_still_append_only( probe, api_key ):
    """
    Guards against semantic bleed: task_amend must APPEND to body (original
    preserved) and must NOT have become a field-setter.
    """
    task_id  = probe[ "id" ]
    original = _fetch( api_key, task_id )[ "body" ]
    assert "PROBE-ORIGINAL-BODY" in ( original or "" ), f"probe body unexpected: {original!r}"

    resp = task_amend_impl( BASE_URL, api_key, ACTOR, task_id, "AMEND-APPENDED-NOTE", reason="parity E2E: amend regression" )
    assert not _is_refused( resp ), f"amend failed: {resp!r}"

    after = _fetch( api_key, task_id )[ "body" ]
    assert "PROBE-ORIGINAL-BODY" in after, f"amend OVERWROTE the original body: {after!r}"
    assert "AMEND-APPENDED-NOTE"  in after, f"amend did not append the note: {after!r}"


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
