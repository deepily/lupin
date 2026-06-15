"""
Task-store structural rules — pure validation for the unified task store (Phase 1).

This module is the ONE place where the task store's structural invariants live
(design §2.2 "enforcement-light to start": the API enforces structural rules;
social/role rules stay practice-layer in v1):

    - status / item_class / gate_class / priority / authority enum membership
    - receipt_refs key whitelist + per-key shape rules (design §4.1 AC1 —
      "receipt validation is not theater-able")
    - typed blocked_by refs ({kind: item|persona|user, id}) (design §2.1)
    - transition rules: terminal states are append-only; ->done requires valid
      receipts; ->blocked requires next_chase_ts (I3) + >=1 typed blocked_by ref

Every function is pure (no DB, no HTTP): callers pass state in, get a list of
human-readable error strings back (empty list == valid). The router maps a
non-empty list to HTTP 422; the repository never sees invalid input.

Canonical design: planning-is-prompting ->
src/rnd/2026.06.11-unified-task-store-design.md (v0.4). Gate rulings (Tiberius,
qid c8c73fde): item_class naming, terminal-state rule, blocked requires >=1 ref,
log_line shape = "<scope>/<rel-path>:<lineno>" with exists check.
"""

import os
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Enums (design §2.1) — plain tuples, app-validated (house style: no PG ENUM)
# ---------------------------------------------------------------------------

VALID_STATUSES         = ( "queued", "claimed", "in_progress", "blocked", "review", "done", "dropped" )
TERMINAL_STATUSES      = ( "done", "dropped" )
VALID_ITEM_CLASSES     = ( "task", "decision", "review_request", "bug", "gate" )
VALID_GATE_CLASSES     = ( "none", "manager", "ricks_court" )
VALID_PRIORITIES       = ( "P0", "P1", "P2", "P3" )
VALID_AUTHORITIES      = ( "standing", "user_direct", "manager_relay" )
VALID_BLOCKED_BY_KINDS = ( "item", "persona", "user" )

# Receipt key whitelist + shape rules (design §4.1 AC1)
RECEIPT_KEY_WHITELIST = ( "commit", "test_run", "qid", "doc_path", "log_line" )

# Shape patterns are applied via re.fullmatch ONLY — never re.match + `$`,
# because Python's `$` matches before a trailing newline, letting
# "abcdef1\n" smuggle through the AC1 gate (cold-review N1, live-proven).
COMMIT_PATTERN   = re.compile( r"[0-9a-f]{7,40}" )
TEST_RUN_PATTERN = re.compile( r"ts-[0-9a-f]{8}" )
QID_PATTERN      = re.compile( r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" )
LOG_LINE_PATTERN = re.compile( r"(.+):(\d+)" )


# ---------------------------------------------------------------------------
# Scope-root resolution for doc_path / log_line exists-in-repo checks
# ---------------------------------------------------------------------------

_SCOPE_ROOTS: Optional[dict] = None  # lazy singleton — None means "not built yet"


def _get_default_scope_roots() -> dict:
    """
    Build (once per process) the scope-name -> absolute-root map for receipt
    path validation, reusing the doc-viewer scope registry (design §4.1 AC1:
    doc_path = exists-in-repo check; no new path grammar).

    Requires:
        - ConfigurationManager singleton is constructible (server context)

    Ensures:
        - returns { scope_name: absolute_root } for every registered repo
        - built exactly once; subsequent calls return the cached map
    """
    global _SCOPE_ROOTS
    if _SCOPE_ROOTS is None:
        from cosa.rest.dependencies.config import get_config_manager
        from cosa.rest.routers._scope_registry import build_scope_registry

        registry     = build_scope_registry( get_config_manager() )
        _SCOPE_ROOTS = { name: cfg.root for name, cfg in registry.items() }
    return _SCOPE_ROOTS


def _validate_scoped_path( value: str, scope_roots: Optional[dict] ) -> list:
    """
    Validate a "<scope>/<relative-path>" receipt path: registered scope,
    no root escape, file exists.

    Requires:
        - value is a non-empty string
        - scope_roots is a { scope: abs_root } dict, or None to use the
          process-default registry-backed map

    Ensures:
        - returns [] when the path names an existing file inside a registered
          scope root
        - returns one error string otherwise (unknown scope, escape, missing)
    """
    roots = scope_roots if scope_roots is not None else _get_default_scope_roots()

    if "/" not in value:
        return [ f"receipt path '{value}' must be '<scope>/<relative-path>' (e.g. 'lupin/src/rnd/foo.md')" ]

    scope, rel = value.split( "/", 1 )
    if scope not in roots:
        return [ f"receipt path scope '{scope}' is not a registered repo scope" ]

    root = roots[ scope ].rstrip( os.sep )
    full = os.path.normpath( os.path.join( root, rel ) )
    if full != root and not full.startswith( root + os.sep ):
        return [ f"receipt path '{value}' escapes its scope root" ]

    if not os.path.isfile( full ):
        return [ f"receipt path '{value}' does not exist in scope '{scope}'" ]

    return [ ]


# ---------------------------------------------------------------------------
# Receipt validation (design §4.1 AC1 — "not theater-able")
# ---------------------------------------------------------------------------

def validate_receipt_refs( receipt_refs, scope_roots: Optional[dict] = None ) -> list:
    """
    Validate a receipt_refs object against the key whitelist + per-key shapes.

    Requires:
        - receipt_refs is the candidate receipts value (any type accepted;
          non-dict and empty-dict are rejected with errors, not exceptions)
        - scope_roots: optional { scope: abs_root } override for path checks
          (tests inject tmpdirs; server uses the registry default)

    Ensures:
        - returns [] iff receipt_refs is a non-empty dict whose every key is
          whitelisted and every value passes its shape rule:
            commit   - 7-40 lowercase hex chars
            test_run - "ts-" + 8 hex chars (test-suite job id format)
            qid      - canonical lowercase UUID
            doc_path - "<scope>/<rel>" existing file in a registered scope
            log_line - "<scope>/<rel>:<lineno>" with the file existing
        - a non-empty-but-junk receipt ({doc_path: "trust me"}) returns errors
        - never raises on malformed input — errors are data, not exceptions
    """
    if not isinstance( receipt_refs, dict ) or not receipt_refs:
        return [ f"receipt_refs must be a non-empty object with at least one whitelisted key {RECEIPT_KEY_WHITELIST}" ]

    errors = [ ]
    for key, value in receipt_refs.items():
        if key not in RECEIPT_KEY_WHITELIST:
            errors.append( f"unknown receipt key '{key}' — whitelist: {RECEIPT_KEY_WHITELIST}" )
            continue
        if not isinstance( value, str ) or not value:
            errors.append( f"receipt '{key}' must be a non-empty string" )
            continue

        if key == "commit" and not COMMIT_PATTERN.fullmatch( value ):
            errors.append( f"receipt commit '{value}' must be 7-40 lowercase hex chars" )
        elif key == "test_run" and not TEST_RUN_PATTERN.fullmatch( value ):
            errors.append( f"receipt test_run '{value}' must match 'ts-<8 hex chars>'" )
        elif key == "qid" and not QID_PATTERN.fullmatch( value ):
            errors.append( f"receipt qid '{value}' must be a canonical lowercase UUID" )
        elif key == "doc_path":
            errors.extend( _validate_scoped_path( value, scope_roots ) )
        elif key == "log_line":
            match = LOG_LINE_PATTERN.fullmatch( value )
            if not match:
                errors.append( f"receipt log_line '{value}' must be '<scope>/<rel-path>:<lineno>'" )
            else:
                errors.extend( _validate_scoped_path( match.group( 1 ), scope_roots ) )

    return errors


# ---------------------------------------------------------------------------
# Typed blocked_by refs (design §2.1)
# ---------------------------------------------------------------------------

def validate_blocked_by_refs( blocked_by ) -> list:
    """
    Validate a blocked_by value as a non-empty list of typed refs.

    Requires:
        - blocked_by is the candidate value (any type accepted; non-list and
          empty-list are rejected with errors, not exceptions)

    Ensures:
        - returns [] iff blocked_by is a non-empty list where every entry is
          exactly { "kind": item|persona|user, "id": non-empty string } —
          TYPED refs, never a mixed string field (design §2.1)
        - extra or missing keys on a ref are errors (strict shape — R4
          determinism at exactly the field the oracle queries)
    """
    if not isinstance( blocked_by, list ) or not blocked_by:
        return [ "blocked_by must be a non-empty list of typed refs [{kind, id}]" ]

    errors = [ ]
    for i, ref in enumerate( blocked_by ):
        if not isinstance( ref, dict ) or set( ref.keys() ) != { "kind", "id" }:
            errors.append( f"blocked_by[{i}] must be exactly {{kind, id}}" )
            continue
        if ref[ "kind" ] not in VALID_BLOCKED_BY_KINDS:
            errors.append( f"blocked_by[{i}].kind '{ref['kind']}' must be one of {VALID_BLOCKED_BY_KINDS}" )
        if not isinstance( ref[ "id" ], str ) or not ref[ "id" ]:
            errors.append( f"blocked_by[{i}].id must be a non-empty string" )

    return errors


# ---------------------------------------------------------------------------
# Creation + transition rules
# ---------------------------------------------------------------------------

def validate_create( item_class: str, gate_class: str, priority: str, authority: str ) -> list:
    """
    Validate the enum fields of a new item (creation is always status=queued —
    the creation event stamps "->queued"; transitions move it from there).

    Requires:
        - item_class, gate_class, priority, authority are the candidate
          string values (authority stamps the "->queued" creation event)

    Ensures:
        - returns [] iff all four are members of their enums
        - one error string per offending field otherwise
    """
    errors = [ ]
    if item_class not in VALID_ITEM_CLASSES:
        errors.append( f"item_class '{item_class}' must be one of {VALID_ITEM_CLASSES}" )
    if gate_class not in VALID_GATE_CLASSES:
        errors.append( f"gate_class '{gate_class}' must be one of {VALID_GATE_CLASSES}" )
    if priority not in VALID_PRIORITIES:
        errors.append( f"priority '{priority}' must be one of {VALID_PRIORITIES}" )
    if authority not in VALID_AUTHORITIES:
        errors.append( f"authority '{authority}' must be one of {VALID_AUTHORITIES}" )
    return errors


def validate_transition(
    from_status   : str,
    to_status     : str,
    authority     : str,
    receipt_refs  = None,
    next_chase_ts = None,
    blocked_by    = None,
    reason        = None,
    scope_roots   : Optional[dict] = None,
) -> list:
    """
    Validate one state transition against the Phase-1/2 structural rules.

    The full legal-transition graph is Phase-2+ backlog (design §4.1 C-items);
    enforced here are enum validity + the ratified structural rules only.

    Requires:
        - from_status is the item's CURRENT status (read inside the same DB
          session that will apply the transition)
        - to_status / authority are the candidate values
        - receipt_refs / next_chase_ts / blocked_by / reason are the candidate
          payload fields (each may be None)
        - scope_roots: optional override for receipt path checks (tests)

    Ensures:
        - returns [] iff ALL hold:
            to_status is a valid status and differs from from_status
            authority is a valid authority
            from_status is not terminal (done/dropped are append-only — gate
            ruling #4: the audit invariant made mechanical)
            to_status == done  => receipt_refs passes validate_receipt_refs
            receipt_refs present on ANY transition => it passes
            validate_receipt_refs (cold-review N2 — the §5 receipt-theater
            guard outranks the design letter's done-only wording: junk never
            lands in the audit trail)
            to_status == blocked => next_chase_ts present (I3) AND blocked_by
            passes validate_blocked_by_refs (gate ruling #5)
            to_status == dropped => reason is a non-blank string (C12 pulled
            forward into Phase 2, Tiberius ruling qid b312b0f1 — the T3
            escape hatch must carry its justification)
        - reason is OPTIONAL on every other transition (free text, no shape
          rule — length is capped at the wire by the router's Pydantic model)
        - returns the full list of violations otherwise — every problem at
          once, with ONE exception: an invalid to_status short-circuits
          (the dependent receipt/blocked/reason rules are meaningless without
          a valid target state)
    """
    if to_status not in VALID_STATUSES:
        return [ f"to_status '{to_status}' must be one of {VALID_STATUSES}" ]

    errors = [ ]
    if authority not in VALID_AUTHORITIES:
        errors.append( f"authority '{authority}' must be one of {VALID_AUTHORITIES}" )
    if from_status in TERMINAL_STATUSES:
        errors.append( f"item is terminal ('{from_status}') — done/dropped are append-only, no transitions out" )
    elif to_status == from_status:
        errors.append( f"no-op transition '{from_status}'->'{to_status}' rejected" )

    if to_status == "done" or receipt_refs is not None:
        errors.extend( validate_receipt_refs( receipt_refs, scope_roots ) )
    if to_status == "blocked":
        if next_chase_ts is None:
            errors.append( "next_chase_ts is REQUIRED when transitioning to 'blocked' (I3 — no 'pending X' graves)" )
        errors.extend( validate_blocked_by_refs( blocked_by ) )
    if to_status == "dropped" and ( not isinstance( reason, str ) or not reason.strip() ):
        errors.append( "reason is REQUIRED (non-blank) when transitioning to 'dropped' (C12 — the escape hatch carries its justification)" )

    return errors


# ---------------------------------------------------------------------------
# Item-field edit rules (Phase 2.1 — PATCH /api/tasks/{id})
# ---------------------------------------------------------------------------

PATCH_EDITABLE_FIELDS = ( "title", "body", "priority", "owner_persona", "accountable_manager", "gate_class" )


def validate_patch( fields: dict ) -> list:
    """
    Validate an item-field PATCH (Phase 2.1). `fields` is the dict of EDITABLE
    fields the caller actually set (the router passes
    model_dump(exclude_unset=True) minus actor/authority).

    The forbidden fields — status / blocked_by / next_chase_ts / receipt_refs /
    correlation_key — are excluded STRUCTURALLY by the TaskPatchIn model
    (extra='forbid' → 422 at the wire) and never reach here: an item-PATCH can
    NEVER bypass the transition oracle (reviewer ruling 2026-06-15).

    Requires:
        - fields is a dict of provided editable fields (may be empty)

    Ensures:
        - returns [] iff at least one editable field is set AND every provided
          constrained field is valid:
            title      - non-empty string (the column is NOT NULL)
            priority   - member of VALID_PRIORITIES
            gate_class - member of VALID_GATE_CLASSES
          (body / owner_persona / accountable_manager are nullable free text —
          a provided null clears them; no shape rule beyond the wire max_length)
        - an empty patch (no editable field set) is rejected — a PATCH must
          change something
        - one error string per offending field; never raises
    """
    if not fields:
        return [ f"patch must set at least one editable field {PATCH_EDITABLE_FIELDS}" ]

    errors = [ ]
    if "title" in fields and ( not isinstance( fields[ "title" ], str ) or not fields[ "title" ].strip() ):
        errors.append( "title must be a non-empty string" )
    if "priority" in fields and fields[ "priority" ] not in VALID_PRIORITIES:
        errors.append( f"priority '{fields[ 'priority' ]}' must be one of {VALID_PRIORITIES}" )
    if "gate_class" in fields and fields[ "gate_class" ] not in VALID_GATE_CLASSES:
        errors.append( f"gate_class '{fields[ 'gate_class' ]}' must be one of {VALID_GATE_CLASSES}" )
    return errors


def quick_smoke_test():
    """
    Quick smoke test for task_store_rules — exercises every validator at the
    happy path + one representative rejection each.
    """
    import cosa.utils.util as cu

    cu.print_banner( "Task-Store Rules Smoke Test", prepend_nl=True )

    try:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join( tmp, "receipt.md" )
            with open( doc, "w" ) as f:
                f.write( "receipt\n" )
            roots = { "lupin": tmp }

            print( "Testing receipt validation..." )
            good = { "commit": "6be15f46", "doc_path": "lupin/receipt.md", "log_line": "lupin/receipt.md:1" }
            assert validate_receipt_refs( good, scope_roots=roots ) == [ ]
            assert validate_receipt_refs( { "doc_path": "trust me" }, scope_roots=roots ) != [ ]
            assert validate_receipt_refs( { }, scope_roots=roots ) != [ ]
            print( "✓ receipt whitelist + shapes enforced" )

            print( "Testing blocked_by validation..." )
            assert validate_blocked_by_refs( [ { "kind": "user", "id": "rick" } ] ) == [ ]
            assert validate_blocked_by_refs( [ ] ) != [ ]
            print( "✓ typed blocked_by refs enforced" )

            print( "Testing transition rules..." )
            assert validate_transition( "queued", "claimed", "standing" ) == [ ]
            assert validate_transition( "done", "queued", "standing" ) != [ ]
            assert validate_transition( "review", "done", "standing", receipt_refs={ "commit": "6be15f46" } ) == [ ]
            assert validate_transition( "in_progress", "blocked", "standing" ) != [ ]
            assert validate_transition( "queued", "dropped", "standing" ) != [ ]
            assert validate_transition( "queued", "dropped", "standing", reason="superseded-by-rewrite" ) == [ ]
            print( "✓ terminal / receipts-on-done / blocked / dropped-reason rules enforced" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
