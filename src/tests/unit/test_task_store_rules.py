#!/usr/bin/env python3
"""
Unit tests for cosa.rest.task_store_rules — the pure structural validators of
the unified task store (Phase 1).

Covers every branch of: receipt key whitelist + per-key shape rules (design
§4.1 AC1 — "not theater-able"), typed blocked_by refs, creation enum checks,
and the Phase-1 transition rules (terminal states, receipts-on-done,
chase-ts-on-blocked). Path-bearing receipts (doc_path/log_line) run against a
tmpdir scope-roots injection — no registry, no config, no DB.

100% lines/branches/functions of task_store_rules.py.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_store_rules as rules

# A non-None chase sentinel for the blocked-mint tests. validate_blocked_fields
# only tests `next_chase_ts is None`, so any tz-aware datetime stands in for a
# real ISO-8601 chase time without coupling to a clock.
from datetime import datetime as _dt, timezone as _tz
NOW_TS = _dt( 2026, 6, 12, 9, 0, tzinfo=_tz.utc )


@pytest.fixture
def scope_roots( tmp_path ):
    """A tmpdir-backed scope map with one existing receipt file."""
    ( tmp_path / "src" ).mkdir()
    ( tmp_path / "src" / "receipt.md" ).write_text( "receipt\n" )
    return { "lupin": str( tmp_path ) }


# ---------------------------------------------------------------------------
# validate_receipt_refs — container shape
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "bad_container", [ None, "a-string", [ ], 42, { } ] )
def test_receipts_reject_non_dict_or_empty( bad_container, scope_roots ):
    errors = rules.validate_receipt_refs( bad_container, scope_roots=scope_roots )
    assert len( errors ) == 1 and "non-empty object" in errors[ 0 ]


def test_receipts_reject_unknown_key( scope_roots ):
    errors = rules.validate_receipt_refs( { "vibes": "good" }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "unknown receipt key 'vibes'" in errors[ 0 ]


@pytest.mark.parametrize( "bad_value", [ "", None, 7, [ "x" ] ] )
def test_receipts_reject_non_string_or_empty_values( bad_value, scope_roots ):
    errors = rules.validate_receipt_refs( { "commit": bad_value }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "non-empty string" in errors[ 0 ]


# ---------------------------------------------------------------------------
# validate_receipt_refs — per-key shapes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "good_commit", [ "6be15f4", "6be15f46", "a" * 40 ] )
def test_commit_accepts_7_to_40_hex( good_commit, scope_roots ):
    assert rules.validate_receipt_refs( { "commit": good_commit }, scope_roots=scope_roots ) == [ ]


@pytest.mark.parametrize( "bad_commit", [ "6be15f", "a" * 41, "6BE15F46", "not-hex-at-all", "6be15g46" ] )
def test_commit_rejects_wrong_shapes( bad_commit, scope_roots ):
    errors = rules.validate_receipt_refs( { "commit": bad_commit }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "7-40 lowercase hex" in errors[ 0 ]


def test_test_run_accepts_ts_id( scope_roots ):
    assert rules.validate_receipt_refs( { "test_run": "ts-82ae2446" }, scope_roots=scope_roots ) == [ ]


@pytest.mark.parametrize( "bad_run", [ "ts-82ae244", "ts-82ae24467", "82ae2446", "TS-82ae2446", "ts-82AE2446" ] )
def test_test_run_rejects_wrong_shapes( bad_run, scope_roots ):
    errors = rules.validate_receipt_refs( { "test_run": bad_run }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "ts-<8 hex chars>" in errors[ 0 ]


def test_qid_accepts_canonical_uuid( scope_roots ):
    assert rules.validate_receipt_refs(
        { "qid": "c8c73fde-6ce4-4e8d-83d7-c55b5cce65a3" }, scope_roots=scope_roots
    ) == [ ]


@pytest.mark.parametrize( "bad_qid", [ "c8c73fde", "C8C73FDE-6CE4-4E8D-83D7-C55B5CCE65A3",
                                       "c8c73fde-6ce4-4e8d-83d7-c55b5cce65a", "zzzzzzzz-6ce4-4e8d-83d7-c55b5cce65a3" ] )
def test_qid_rejects_wrong_shapes( bad_qid, scope_roots ):
    errors = rules.validate_receipt_refs( { "qid": bad_qid }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "canonical lowercase UUID" in errors[ 0 ]


def test_doc_path_accepts_existing_scoped_file( scope_roots ):
    assert rules.validate_receipt_refs( { "doc_path": "lupin/src/receipt.md" }, scope_roots=scope_roots ) == [ ]


def test_doc_path_rejects_missing_slash( scope_roots ):
    errors = rules.validate_receipt_refs( { "doc_path": "trust me" }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "<scope>/<relative-path>" in errors[ 0 ]


def test_doc_path_rejects_unknown_scope( scope_roots ):
    errors = rules.validate_receipt_refs( { "doc_path": "narnia/src/receipt.md" }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "not a registered repo scope" in errors[ 0 ]


def test_doc_path_rejects_root_escape( scope_roots ):
    errors = rules.validate_receipt_refs( { "doc_path": "lupin/../../etc/passwd" }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "escapes its scope root" in errors[ 0 ]


def test_doc_path_rejects_nonexistent_file( scope_roots ):
    errors = rules.validate_receipt_refs( { "doc_path": "lupin/src/ghost.md" }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "does not exist" in errors[ 0 ]


def test_log_line_accepts_existing_file_with_lineno( scope_roots ):
    assert rules.validate_receipt_refs( { "log_line": "lupin/src/receipt.md:42" }, scope_roots=scope_roots ) == [ ]


@pytest.mark.parametrize( "bad_log_line", [ "lupin/src/receipt.md", "lupin/src/receipt.md:", "lupin/src/receipt.md:abc" ] )
def test_log_line_rejects_missing_or_non_numeric_lineno( bad_log_line, scope_roots ):
    errors = rules.validate_receipt_refs( { "log_line": bad_log_line }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "<scope>/<rel-path>:<lineno>" in errors[ 0 ]


def test_log_line_rejects_nonexistent_path( scope_roots ):
    errors = rules.validate_receipt_refs( { "log_line": "lupin/src/ghost.md:42" }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "does not exist" in errors[ 0 ]


def test_multiple_violations_all_reported( scope_roots ):
    """Never fail-fast — the caller sees every problem at once."""
    errors = rules.validate_receipt_refs(
        { "commit": "nope", "vibes": "good", "doc_path": "lupin/src/ghost.md" }, scope_roots=scope_roots
    )
    assert len( errors ) == 3


# ── N1 regression: trailing-newline smuggle (cold review, live-proven) ──────
# re.match + `$` matches before a final \n; the shape gate must use fullmatch.

@pytest.mark.parametrize( "key, smuggled", [
    ( "commit",   "abcdef1\n" ),
    ( "test_run", "ts-82ae2446\n" ),
    ( "qid",      "c8c73fde-6ce4-4e8d-83d7-c55b5cce65a3\n" ),
    ( "log_line", "lupin/src/receipt.md:1\n" ),
] )
def test_trailing_newline_smuggle_rejected( key, smuggled, scope_roots ):
    errors = rules.validate_receipt_refs( { key: smuggled }, scope_roots=scope_roots )
    assert len( errors ) == 1, f"'{key}' with trailing newline must be rejected"


def test_full_valid_receipt_set( scope_roots ):
    receipts = {
        "commit"   : "6be15f46",
        "test_run" : "ts-82ae2446",
        "qid"      : "c8c73fde-6ce4-4e8d-83d7-c55b5cce65a3",
        "doc_path" : "lupin/src/receipt.md",
        "log_line" : "lupin/src/receipt.md:1",
    }
    assert rules.validate_receipt_refs( receipts, scope_roots=scope_roots ) == [ ]


# ---------------------------------------------------------------------------
# Default scope roots (registry-backed lazy singleton)
# ---------------------------------------------------------------------------

def test_default_scope_roots_build_once_and_cache( monkeypatch ):
    """Builds from the live registry exactly once, then returns the cached map.

    Registry CONTENTS are environment-owned (host lacks the container mounts,
    so the map may be empty here) — this test owns only the build+cache shape.
    """
    monkeypatch.setattr( rules, "_SCOPE_ROOTS", None )
    first  = rules._get_default_scope_roots()
    second = rules._get_default_scope_roots()
    assert isinstance( first, dict )
    assert second is first                                       # cached, not rebuilt


def test_doc_path_uses_default_roots_when_not_injected( monkeypatch ):
    """scope_roots=None falls through to the registry-backed default map."""
    monkeypatch.setattr( rules, "_SCOPE_ROOTS", { "lupin": "/nonexistent-root" } )
    errors = rules.validate_receipt_refs( { "doc_path": "narnia/foo.md" } )
    assert len( errors ) == 1 and "not a registered repo scope" in errors[ 0 ]


# ---------------------------------------------------------------------------
# validate_blocked_by_refs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "bad_container", [ None, "x", { }, [ ], 42 ] )
def test_blocked_by_rejects_non_list_or_empty( bad_container ):
    errors = rules.validate_blocked_by_refs( bad_container )
    assert len( errors ) == 1 and "non-empty list of typed refs" in errors[ 0 ]


@pytest.mark.parametrize( "bad_ref", [ "rick", { "kind": "user" }, { "id": "rick" },
                                       { "kind": "user", "id": "rick", "extra": True } ] )
def test_blocked_by_rejects_wrong_ref_shape( bad_ref ):
    errors = rules.validate_blocked_by_refs( [ bad_ref ] )
    # Message reworded 2026-07-27 when persona refs gained an optional session_id.
    # The PROPERTY is unchanged: one error, naming the required shape.
    assert len( errors ) == 1 and "must be {kind, id}" in errors[ 0 ]


def test_blocked_by_rejects_bad_kind():
    errors = rules.validate_blocked_by_refs( [ { "kind": "vibe", "id": "x" } ] )
    assert len( errors ) == 1 and "must be one of" in errors[ 0 ]


@pytest.mark.parametrize( "bad_id", [ "", None, 7 ] )
def test_blocked_by_rejects_bad_id( bad_id ):
    errors = rules.validate_blocked_by_refs( [ { "kind": "item", "id": bad_id } ] )
    assert len( errors ) == 1 and ".id must be a non-empty string" in errors[ 0 ]


def test_blocked_by_bad_kind_and_bad_id_both_reported():
    errors = rules.validate_blocked_by_refs( [ { "kind": "vibe", "id": "" } ] )
    assert len( errors ) == 2


def test_blocked_by_accepts_all_kinds():
    refs = [ { "kind": "item", "id": "550e8400-e29b-41d4-a716-446655440000" },
             { "kind": "persona", "id": "rachel" },
             { "kind": "user", "id": "rick" } ]
    assert rules.validate_blocked_by_refs( refs ) == [ ]


# ---------------------------------------------------------------------------
# validate_create
# ---------------------------------------------------------------------------

def test_create_accepts_valid_enums():
    assert rules.validate_create( "task", "none", "P2", "standing" ) == [ ]


def test_create_rejects_each_bad_enum():
    errors = rules.validate_create( "chore", "side-gate", "P9", "divine_right" )
    assert len( errors ) == 4
    assert any( "item_class" in e for e in errors )
    assert any( "gate_class" in e for e in errors )
    assert any( "priority" in e for e in errors )
    assert any( "authority" in e for e in errors )


@pytest.mark.parametrize( "item_class", rules.VALID_ITEM_CLASSES )
def test_create_accepts_every_item_class( item_class ):
    assert rules.validate_create( item_class, "operator", "P0", "user_direct" ) == [ ]


def test_create_accepts_operator_gate_class():
    # AC-A0.2 — the renamed `operator` value is a member of the gate-class enum.
    assert "operator" in rules.VALID_GATE_CLASSES
    assert rules.validate_create( "decision", "operator", "P0", "user_direct" ) == [ ]


def test_create_rejects_retired_ricks_court_gate_class():
    # AC-A0.2 — the retired `ricks_court` value is no longer a member of the
    # gate-class enum (one-name-everywhere, no compat alias) → validation rejects it.
    assert "ricks_court" not in rules.VALID_GATE_CLASSES
    errors = rules.validate_create( "decision", "ricks_court", "P0", "user_direct" )
    assert any( "gate_class" in e and "ricks_court" in e for e in errors )


@pytest.mark.parametrize( "urgency", rules.VALID_URGENCIES )
def test_create_accepts_every_urgency_tier( urgency ):
    # A2 — every urgency tier (urgent/normal/low) is a valid create field.
    assert rules.validate_create( "decision", "operator", "P0", "user_direct", urgency ) == [ ]


def test_create_defaults_urgency_to_normal():
    # A2 — urgency defaults to "normal" (the low-friction default) when omitted.
    assert rules.validate_create( "task", "none", "P2", "standing" ) == [ ]


def test_create_rejects_invalid_urgency():
    # A2 — a junk urgency value is a 422-worthy enum violation.
    errors = rules.validate_create( "decision", "operator", "P0", "user_direct", "panic" )
    assert any( "urgency" in e and "panic" in e for e in errors )


def test_patch_accepts_valid_urgency():
    assert rules.validate_patch( { "urgency": "urgent" } ) == [ ]


def test_patch_rejects_invalid_urgency():
    errors = rules.validate_patch( { "urgency": "panic" } )
    assert any( "urgency" in e and "panic" in e for e in errors )


# ---------------------------------------------------------------------------
# validate_transition
# ---------------------------------------------------------------------------

def test_transition_invalid_to_status_short_circuits():
    errors = rules.validate_transition( "queued", "finished", "standing" )
    assert len( errors ) == 1 and "to_status 'finished'" in errors[ 0 ]


def test_transition_rejects_bad_authority():
    errors = rules.validate_transition( "queued", "claimed", "by-fiat" )
    assert len( errors ) == 1 and "authority 'by-fiat'" in errors[ 0 ]


@pytest.mark.parametrize( "terminal", rules.TERMINAL_STATUSES )
def test_transition_rejects_leaving_terminal_states( terminal ):
    errors = rules.validate_transition( terminal, "queued", "standing" )
    assert len( errors ) == 1 and "append-only" in errors[ 0 ]


def test_transition_rejects_no_op():
    errors = rules.validate_transition( "queued", "queued", "standing" )
    assert len( errors ) == 1 and "no-op transition" in errors[ 0 ]


def test_transition_to_done_requires_receipts():
    errors = rules.validate_transition( "review", "done", "standing" )
    assert len( errors ) == 1 and "receipt_refs" in errors[ 0 ]


def test_transition_to_done_rejects_junk_receipts( scope_roots ):
    errors = rules.validate_transition( "review", "done", "standing",
                                        receipt_refs={ "doc_path": "trust me" }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "<scope>/<relative-path>" in errors[ 0 ]


def test_transition_to_done_accepts_valid_receipts( scope_roots ):
    errors = rules.validate_transition( "review", "done", "standing",
                                        receipt_refs={ "commit": "6be15f46" }, scope_roots=scope_roots )
    assert errors == [ ]


def test_transition_to_blocked_bare_requires_refs_but_no_chase_without_persona():
    # I3 kind-aware (eab1d7da): a bare ->blocked (no blocked_by, no chase) is
    # rejected for the MISSING REFS only. With no persona in blocked_by, no chase
    # is required — the old global "chase always" rule is gone. (Was 2 errors.)
    errors = rules.validate_transition( "in_progress", "blocked", "standing" )
    assert any( "blocked_by" in e for e in errors )
    assert not any( "chase" in e for e in errors ), "no persona ⇒ no chase requirement"


def test_transition_to_blocked_accepts_chase_ts_plus_typed_refs():
    from datetime import datetime, timezone
    errors = rules.validate_transition(
        "in_progress", "blocked", "standing",
        next_chase_ts = datetime( 2026, 6, 12, 9, 0, tzinfo=timezone.utc ),
        blocked_by    = [ { "kind": "user", "id": "rick" } ],
    )
    assert errors == [ ]


# ---------------------------------------------------------------------------
# I3 kind-aware chase requirement (eab1d7da) — blocked_by_has_persona +
# the persona-gated chase rule in validate_transition
# ---------------------------------------------------------------------------

class TestBlockedByHasPersona:
    """The app-layer twin of the CHECK's `blocked_by @> '[{"kind":"persona"}]'`."""

    @pytest.mark.parametrize( "value", [
        None, "not-a-list", 42, { "kind": "persona" },   # non-list → False, never raises
        [ ],                                              # empty → False
        [ { "kind": "user", "id": "rick" } ],             # user only
        [ { "kind": "item", "id": "X" } ],                # item only
        [ { "kind": "user", "id": "rick" }, { "kind": "item", "id": "X" } ],
        [ "garbage", { "no": "kind" } ],                  # malformed refs ignored, no raise
    ] )
    def test_false_when_no_persona_ref( self, value ):
        assert rules.blocked_by_has_persona( value ) is False

    @pytest.mark.parametrize( "value", [
        [ { "kind": "persona", "id": "sam" } ],
        [ { "kind": "user", "id": "rick" }, { "kind": "persona", "id": "sam" } ],
        [ "garbage", { "kind": "persona", "id": "sam" } ],   # survives a malformed sibling
    ] )
    def test_true_when_any_persona_ref( self, value ):
        assert rules.blocked_by_has_persona( value ) is True


class TestKindAwareChaseRule:
    """
    validate_transition's ->blocked chase requirement is now gated on blocker KIND.
    AC2's both-agree contract: the PERSONA case must FAIL and the USER/ITEM-only
    case must PASS the rules layer — a rule rejecting "any blocker" would go red on
    the persona row too and hide a divergence from the CHECK (which rejects only
    persona). This class asserts both arms.
    """

    def test_persona_blocker_null_chase_rejected_naming_the_kind( self ):
        errors = rules.validate_transition(
            "in_progress", "blocked", "standing",
            blocked_by = [ { "kind": "persona", "id": "sam" } ], next_chase_ts=None )
        # NAMES the kind (María's review gate) — not the old generic message.
        assert any( "persona blocker requires a chase" in e for e in errors )

    def test_persona_blocker_with_chase_passes( self ):
        from datetime import datetime, timezone
        errors = rules.validate_transition(
            "in_progress", "blocked", "standing",
            blocked_by    = [ { "kind": "persona", "id": "sam" } ],
            next_chase_ts = datetime( 2026, 7, 22, 9, 0, tzinfo=timezone.utc ) )
        assert errors == [ ]

    @pytest.mark.parametrize( "kind,ident", [ ( "user", "rick" ), ( "item", "550e8400-e29b-41d4-a716-446655440000" ) ] )
    def test_user_or_item_only_null_chase_PASSES_the_rules_layer( self, kind, ident ):
        # THE both-agree arm: this is what makes "blocked on Rick, no schedulable
        # chase" expressible — and what catches a rules layer that rejects on ANY
        # blocker while the CHECK rejects only on persona.
        errors = rules.validate_transition(
            "in_progress", "blocked", "standing",
            blocked_by = [ { "kind": kind, "id": ident } ], next_chase_ts=None )
        assert errors == [ ], f"a {kind}-only null-chase block must pass the rules layer"

    def test_mixed_user_plus_persona_null_chase_rejected( self ):
        # A persona anywhere in the list triggers the requirement (mirrors @> containment).
        errors = rules.validate_transition(
            "in_progress", "blocked", "standing",
            blocked_by = [ { "kind": "user", "id": "rick" }, { "kind": "persona", "id": "sam" } ],
            next_chase_ts=None )
        assert any( "persona blocker requires a chase" in e for e in errors )


def test_transition_happy_path_plain_move():
    assert rules.validate_transition( "queued", "claimed", "manager_relay" ) == [ ]


# ── N2 regression: receipts validated WHENEVER present, not just ->done ─────
# (§5 receipt-theater guard: junk never lands in the audit trail)

def test_transition_non_done_with_junk_receipts_rejected( scope_roots ):
    errors = rules.validate_transition( "in_progress", "review", "standing",
                                        receipt_refs={ "vibes": "good" }, scope_roots=scope_roots )
    assert len( errors ) == 1 and "unknown receipt key 'vibes'" in errors[ 0 ]


def test_transition_non_done_with_valid_receipts_accepted( scope_roots ):
    errors = rules.validate_transition( "in_progress", "review", "standing",
                                        receipt_refs={ "commit": "6be15f46" }, scope_roots=scope_roots )
    assert errors == [ ]


def test_transition_non_done_without_receipts_needs_none():
    assert rules.validate_transition( "queued", "claimed", "standing", receipt_refs=None ) == [ ]


def test_transition_terminal_violation_suppresses_no_op_check():
    """Terminal check and no-op check are elif — terminal wins, both never stack."""
    errors = rules.validate_transition( "done", "done", "standing", receipt_refs={ "commit": "6be15f46" } )
    # terminal violation + receipts validated (valid here) => exactly the terminal error...
    # receipts ARE validated for to_status=done, and pass; only the terminal error remains
    assert len( errors ) == 1 and "append-only" in errors[ 0 ]


# ── Phase 2: ->dropped requires a non-blank reason (C12 pulled forward) ─────

def test_transition_to_dropped_requires_reason():
    errors = rules.validate_transition( "queued", "dropped", "standing" )
    assert len( errors ) == 1 and "reason is REQUIRED" in errors[ 0 ]


@pytest.mark.parametrize( "bad_reason", [ None, "", "   ", 7, [ "r" ], True ] )
def test_transition_to_dropped_rejects_blank_or_non_string_reason( bad_reason ):
    errors = rules.validate_transition( "queued", "dropped", "standing", reason=bad_reason )
    assert any( "reason is REQUIRED" in e for e in errors )


def test_transition_to_dropped_accepts_non_blank_reason():
    assert rules.validate_transition( "queued", "dropped", "standing", reason="superseded-by-rewrite" ) == [ ]


def test_transition_reason_optional_on_non_dropped_moves():
    assert rules.validate_transition( "queued", "claimed", "standing", reason=None ) == [ ]
    assert rules.validate_transition( "queued", "claimed", "standing", reason="early claim note" ) == [ ]


def test_transition_dropped_reason_error_stacks_with_others():
    # Terminal violation + missing reason both reported (every problem at once).
    errors = rules.validate_transition( "done", "dropped", "standing" )
    assert any( "append-only" in e for e in errors )
    assert any( "reason is REQUIRED" in e for e in errors )
    assert len( errors ) == 2


# ---------------------------------------------------------------------------
# validate_patch (Phase 2.1 — item-field edit)
# ---------------------------------------------------------------------------

def test_patch_empty_is_rejected():
    errors = rules.validate_patch( { } )
    assert len( errors ) == 1 and "at least one editable field" in errors[ 0 ]


def test_patch_single_nullable_field_ok():
    assert rules.validate_patch( { "body": "new body" } ) == [ ]
    assert rules.validate_patch( { "owner_persona": None } ) == [ ]   # clearing a nullable field is fine


@pytest.mark.parametrize( "bad_title", [ None, "", "   " ] )
def test_patch_title_must_be_non_empty( bad_title ):
    errors = rules.validate_patch( { "title": bad_title } )
    assert any( "title must be a non-empty string" in e for e in errors )


def test_patch_rejects_junk_priority_and_gate_class():
    errors = rules.validate_patch( { "priority": "P9", "gate_class": "side-gate" } )
    assert any( "priority" in e for e in errors )
    assert any( "gate_class" in e for e in errors )
    assert len( errors ) == 2


def test_patch_all_editable_fields_valid():
    assert rules.validate_patch( {
        "title"               : "fresh title",
        "body"                : "details",
        "priority"            : "P1",
        "owner_persona"       : "tiffany",
        "accountable_manager" : "tiberius",
        "gate_class"          : "operator",
    } ) == [ ]


# ---------------------------------------------------------------------------
# Legal-transition graph (Phase 2.1 — Item D, ratified 2026-06-15)
# ---------------------------------------------------------------------------

def test_legal_transitions_graph_shape():
    # Ratified: every NON-terminal status -> every OTHER status; terminals have
    # NO out-edges. Derived from the enums, so this pins the derivation.
    for status in rules.VALID_STATUSES:
        if status in rules.TERMINAL_STATUSES:
            assert status not in rules.LEGAL_TRANSITIONS            # no out-edges from terminal
        else:
            assert set( rules.LEGAL_TRANSITIONS[ status ] ) == set( rules.VALID_STATUSES ) - { status }


@pytest.mark.parametrize( "src", [ s for s in rules.VALID_STATUSES if s not in rules.TERMINAL_STATUSES ] )
def test_every_non_terminal_source_reaches_every_other_status( src ):
    # Each non-terminal source -> every OTHER status is a LEGAL edge (graph layer;
    # payload rules like receipts/reason are validated separately).
    for dst in rules.VALID_STATUSES:
        if dst != src:
            assert dst in rules.LEGAL_TRANSITIONS[ src ]
        else:
            assert dst not in rules.LEGAL_TRANSITIONS[ src ]       # no-op is not a legal edge


def test_transition_rejects_invalid_from_status():
    # D-DELTA: an unknown from_status (free VARCHAR, no enum CHECK) short-circuits
    # to a DATA error — never a KeyError on the LEGAL_TRANSITIONS lookup.
    errors = rules.validate_transition( "bogus", "queued", "standing" )
    assert len( errors ) == 1 and "from_status" in errors[ 0 ] and "must be one of" in errors[ 0 ]


def test_no_op_rejected_via_graph():
    errors = rules.validate_transition( "in_progress", "in_progress", "standing" )
    assert len( errors ) == 1 and "no-op transition" in errors[ 0 ] and "not a legal edge" in errors[ 0 ]


def test_legal_graph_covers_every_live_mirror_edge():
    # D-DELTA-2: derive the store edges the LIVE hook mirror can emit straight
    # from its STATUS_TRANSITIONS map (NO hand-copied list — it rots), plus the
    # queued create-seed and the backward re-queue edges, and assert EVERY one is
    # a legal edge. Guards a future graph tightening from silently breaking the
    # now-LIVE mirror (which would start 422-ing real Task* events).
    from lupin_cli.claude_code.hooks.lib.task_store_mirror import STATUS_TRANSITIONS

    mirror_targets = set( STATUS_TRANSITIONS.values() )            # {queued, in_progress, review, dropped}
    # statuses the mirror SETS and can then transition FROM (dropped is terminal —
    # the mirror never moves out of it); plus the 'queued' create-seed source.
    mirror_sources = { "queued" } | ( mirror_targets - set( rules.TERMINAL_STATUSES ) )
    edges  = { ( src, dst ) for src in mirror_sources for dst in mirror_targets if src != dst }
    edges |= { ( "in_progress", "queued" ), ( "review", "queued" ) }   # explicit backward re-queue

    for src, dst in sorted( edges ):
        assert dst in rules.LEGAL_TRANSITIONS[ src ], f"live mirror edge {src}->{dst} is not legal"

    # terminal-source + no-op are still rejected by the full validator
    assert rules.validate_transition( "done", "queued", "standing" )    != [ ]
    assert rules.validate_transition( "dropped", "queued", "standing" ) != [ ]
    assert rules.validate_transition( "review", "review", "standing" )  != [ ]


# ---------------------------------------------------------------------------
# normalize_patch_fields (reassign §4.1) — the single write-side seam that
# canonicalizes a PATCH's persona-identity fields so a re-owned item stays
# inside the new owner's owed-row set (the 2026-06-18 false-idle guard).
# Cases per spec §4.3: present / absent / explicit-null / accented.
# ---------------------------------------------------------------------------

class TestNormalizePatchFields:

    def test_accented_persona_canonicalized( self ):
        # A hand-supplied display name is folded to the store's canonical key.
        out = rules.normalize_patch_fields( { "owner_persona": "María", "accountable_manager": "Mr. Radio" } )
        assert out == { "owner_persona": "maria", "accountable_manager": "mr radio" }

    def test_non_persona_fields_pass_through_verbatim( self ):
        # Only PATCH_PERSONA_FIELDS are touched — title/body/priority/gate_class
        # are never persona-matched, so they are copied through unchanged.
        fields = { "title": "T", "body": "B", "priority": "P1", "gate_class": "none" }
        assert rules.normalize_patch_fields( fields ) == fields

    def test_explicit_null_owner_preserved_not_collapsed( self ):
        # An explicit None (clear-the-owner) survives — never turned into "" or a
        # canonicalized blank, so unassigning stays a deliberate, auditable clear.
        out = rules.normalize_patch_fields( { "owner_persona": None } )
        assert out == { "owner_persona": None }

    def test_absent_persona_field_stays_absent( self ):
        # No key is invented for a field the caller did not provide.
        out = rules.normalize_patch_fields( { "priority": "P2" } )
        assert "owner_persona" not in out
        assert "accountable_manager" not in out

    def test_empty_string_owner_left_verbatim( self ):
        # A falsy "" is NOT canonicalized (would mint the "" sentinel) — left as-is.
        out = rules.normalize_patch_fields( { "owner_persona": "" } )
        assert out == { "owner_persona": "" }

    def test_input_dict_never_mutated( self ):
        # Returns a NEW dict — the caller's fields are untouched.
        original = { "owner_persona": "María" }
        out = rules.normalize_patch_fields( original )
        assert original == { "owner_persona": "María" }
        assert out is not original

    def test_empty_dict_is_empty_dict( self ):
        assert rules.normalize_patch_fields( { } ) == { }


# ---------------------------------------------------------------------------
# soft_guard_title (design 2026.06.29 task-list row redesign §4.3 / handoff #1)
# The non-destructive soft title guard: an over-long title is NEVER rejected —
# it is trimmed to the cap, with the overflow moved into an EMPTY body so
# nothing is lost; a NON-empty body is never clobbered.
# ---------------------------------------------------------------------------

class TestSoftGuardTitle:

    def test_under_cap_is_strict_no_op( self ):
        # A title at/under the cap is returned verbatim with NO advisory.
        title = "Harden Face B manager language"
        out   = rules.soft_guard_title( title, None )
        assert out == ( title, None, None )

    def test_exactly_at_cap_is_no_op( self ):
        # The boundary is inclusive — exactly cap chars is NOT over the cap.
        title = "x" * rules.TITLE_SOFT_CAP
        new_title, new_body, advisory = rules.soft_guard_title( title, "existing" )
        assert new_title == title and new_body == "existing" and advisory is None

    def test_over_cap_empty_body_moves_overflow_to_body( self ):
        # Over-cap + empty body: title trimmed to cap, overflow lands in body,
        # and trimmed-title + body reconstructs the original (nothing lost).
        title = "A" * 50 + "B" * 40                              # 90 chars, cap 60
        new_title, new_body, advisory = rules.soft_guard_title( title, None )
        assert len( new_title ) == rules.TITLE_SOFT_CAP
        assert new_title == title[ :rules.TITLE_SOFT_CAP ]
        assert new_body  == title[ rules.TITLE_SOFT_CAP: ]
        assert new_title + new_body == title                    # round-trips — nothing lost
        assert advisory == {
            "trimmed"               : True,
            "original_length"       : 90,
            "cap"                   : rules.TITLE_SOFT_CAP,
            "overflow_moved_to_body": True,
        }

    @pytest.mark.parametrize( "blank_body", [ None, "", "   ", "\n\t " ] )
    def test_over_cap_treats_whitespace_only_body_as_empty( self, blank_body ):
        # None AND whitespace-only bodies both count as "empty" → overflow moves.
        title = "z" * 80
        new_title, new_body, advisory = rules.soft_guard_title( title, blank_body )
        assert new_title == title[ :rules.TITLE_SOFT_CAP ]
        assert new_body  == title[ rules.TITLE_SOFT_CAP: ]
        assert advisory[ "overflow_moved_to_body" ] is True

    def test_over_cap_nonempty_body_RELOCATES_overflow_above_the_body( self ):
        # bug 28fc1fb4. This test previously asserted the DEFECT as correct: it
        # required new_body == body and overflow_moved_to_body == False — i.e. it
        # pinned the silent discard in place and went green on every run. The
        # "ruled tradeoff" it cited forbade CLOBBERING a body; it never licensed
        # deleting the title's remainder, and prepending is not clobbering.
        title = "Q" * 75
        body  = "important pre-existing detail"
        new_title, new_body, advisory = rules.soft_guard_title( title, body )

        assert new_title == title[ :rules.TITLE_SOFT_CAP ]
        assert body in new_body                                  # still never clobbered...
        assert new_body.endswith( body )                         # ...and still last, verbatim
        assert rules.TITLE_OVERFLOW_MARKER in new_body           # findable by grep, store-wide
        assert title[ rules.TITLE_SOFT_CAP: ] in new_body        # the overflow SURVIVED
        assert advisory == {
            "trimmed"               : True,
            "original_length"       : 75,
            "cap"                   : rules.TITLE_SOFT_CAP,
            "overflow_moved_to_body": True,
        }

    def test_over_cap_nonempty_body_ROUND_TRIPS_the_original_title_exactly( self ):
        """
        THE AC THAT CANNOT PASS ON A PLAUSIBLE-BUT-LOSSY IMPLEMENTATION.

        Reconstruct the original title from what was stored: the trimmed title plus
        the overflow line lifted back out of the body must equal the input EXACTLY,
        character for character. An implementation that ellipsised, stripped, or
        word-wrapped the remainder would satisfy every "the overflow is in there
        somewhere" assertion and fail this one.
        """
        title = "A standing order that will not fit: route ALL GCP calls through the Mr Radio role"
        body  = "pre-existing body text\nwith a second line"
        new_title, new_body, _ = rules.soft_guard_title( title, body )

        marker_line, overflow_line, _blank, *rest = new_body.split( "\n" )
        assert marker_line == rules.TITLE_OVERFLOW_MARKER
        assert new_title + overflow_line == title                # EXACT reconstruction
        assert "\n".join( rest ) == body                         # the body, verbatim, intact

    def test_custom_cap_is_honored( self ):
        # The cap is parameterizable — proves the guard is not hard-wired to 60.
        new_title, new_body, advisory = rules.soft_guard_title( "abcdefghij", None, cap=4 )
        assert new_title == "abcd" and new_body == "efghij"
        assert advisory[ "cap" ] == 4 and advisory[ "original_length" ] == 10


class TestUnscopedGuardRules:
    """The unscoped-query guard primitives (design 2026.07.07)."""

    @pytest.mark.parametrize( "scoping_filter", [
        "owner_persona", "status", "item_class", "project",
        "gate_class", "accountable_manager", "correlation_key",
    ] )
    def test_any_scoping_filter_makes_query_scoped( self, scoping_filter ):
        # Every one of the 7 narrowing filters flips is_unscoped to False.
        assert rules.is_unscoped( { scoping_filter: "x" } ) is False

    def test_no_filters_is_unscoped( self ):
        assert rules.is_unscoped( { } ) is True

    def test_all_none_filters_is_unscoped( self ):
        # Explicit None counts as absent — the bare board glance.
        assert rules.is_unscoped( { "owner_persona": None, "status": None } ) is True

    def test_urgency_only_is_unscoped( self ):
        # urgency is deliberately EXCLUDED from the scoping set — too coarse to narrow.
        assert rules.is_unscoped( { "urgency": "urgent" } ) is True

    def test_urgency_plus_scoping_filter_is_scoped( self ):
        # urgency alongside a real narrowing filter is scoped (the filter wins).
        assert rules.is_unscoped( { "urgency": "urgent", "owner_persona": "sam" } ) is False

    def test_scoping_filters_set_membership( self ):
        # Pin the exact scoping set + urgency's exclusion (the guard boolean María reviews).
        #
        # ⚠️ THIS PIN WENT RED ON PURPOSE 2026-07-25 AND ITS ARGUMENT WAS ANSWERED BEFORE
        # IT WAS WIDENED. The pin exists because every addition here EXEMPTS a query shape
        # from the over-threshold guard, so it must be a deliberate, reviewed act rather
        # than a side effect of adding a filter. `id_prefix` (row f45b37a9 remedy 2) was
        # admitted because it does not widen anything: it selects at most a handful of
        # rows BY IDENTITY, making it the narrowest filter in the set. Omitting it would
        # have inverted the guard — `task_query(id_prefix=...)` would count as a bare
        # unscoped pull and be REJECTED for being too broad, which is the one outcome the
        # guard should never produce. `urgency` stays excluded on the original reasoning:
        # it is too coarse to narrow anything.
        assert set( rules.SCOPING_FILTERS ) == {
            "owner_persona", "status", "item_class", "project",
            "gate_class", "accountable_manager", "correlation_key",
            "id_prefix",
        }
        assert "urgency" not in rules.SCOPING_FILTERS

    def test_unscoped_query_error_carries_count_and_threshold( self ):
        err = rules.UnscopedQueryError( 273, 50 )
        assert err.count == 273 and err.threshold == 50
        assert "273" in str( err ) and "unscoped_audit=true" in str( err )

    def test_unscoped_query_error_defaults_threshold_to_constant( self ):
        err = rules.UnscopedQueryError( 99 )
        assert err.threshold == rules.UNSCOPED_QUERY_THRESHOLD

    def test_threshold_constants_are_positive_ints( self ):
        assert isinstance( rules.UNSCOPED_QUERY_THRESHOLD, int ) and rules.UNSCOPED_QUERY_THRESHOLD > 0
        assert isinstance( rules.NONTERSE_WARN_THRESHOLD, int ) and rules.NONTERSE_WARN_THRESHOLD > 0


# ---------------------------------------------------------------------------
# Persona-key follow-on policy (2026-07-11, task c03d1870) — DEFAULT_OWNER_CLASSES,
# persona_from_created_by, build_persona_advisory, _get_known_persona_keys.
# Design: src/rnd/v0.1.9/2026.07.11-persona-key-followon-policy.md
# ---------------------------------------------------------------------------

def test_default_owner_classes_are_the_owned_work_triple():
    assert rules.DEFAULT_OWNER_CLASSES == ( "task", "bug", "review_request" )
    # operator-queue classes are DELIBERATELY excluded (ownerless by design)
    assert "decision" not in rules.DEFAULT_OWNER_CLASSES
    assert "gate" not in rules.DEFAULT_OWNER_CLASSES


@pytest.mark.parametrize( "created_by, expected", [
    ( "mr radio 372f9dc9", "mr radio"    ),   # persona-with-space + 8-hex sid tail stripped
    ( "krishna 38d15e3b",  "krishna"     ),
    ( "María 1a2b3c4d",    "maria"       ),    # accent folded, sid stripped
    ( "krishna",           "krishna"     ),    # no sid tail — canonicalized whole
    ( "agent beef",        "agent beef"  ),    # "beef" is 4 hex (<6 floor) — NOT a sid, kept
    ( "agent 12ab",        "agent 12ab"  ),    # 4-char hex tail below the >=6 floor — kept
] )
def test_persona_from_created_by_strips_sid_tail( created_by, expected ):
    assert rules.persona_from_created_by( created_by ) == expected


@pytest.mark.parametrize( "bad", [ None, "", "   ", "!!!", 123, [ ] ] )
def test_persona_from_created_by_unusable_input_is_empty( bad ):
    assert rules.persona_from_created_by( bad ) == ""


_ROSTER = { "krishna", "mr radio", "tiberius" }


def test_advisory_none_when_both_on_roster():
    assert rules.build_persona_advisory( "krishna", "tiberius", known_keys=_ROSTER ) == ( None, None )


def test_advisory_none_when_fields_absent():
    assert rules.build_persona_advisory( None, None, known_keys=_ROSTER ) == ( None, None )


def test_advisory_flags_off_roster_owner_only():
    advisory, marker = rules.build_persona_advisory( "María", "krishna", known_keys=_ROSTER )
    assert advisory == { "owner_persona": "maria" }
    assert marker == "[persona_flag: owner 'maria' off-roster]"


def test_advisory_flags_off_roster_manager_only():
    advisory, marker = rules.build_persona_advisory( "krishna", "Ziggy Stardust", known_keys=_ROSTER )
    assert advisory == { "accountable_manager": "ziggy stardust" }
    assert marker == "[persona_flag: manager 'ziggy stardust' off-roster]"


def test_advisory_flags_both_off_roster():
    advisory, marker = rules.build_persona_advisory( "María", "Ziggy", known_keys=_ROSTER )
    assert advisory == { "owner_persona": "maria", "accountable_manager": "ziggy" }
    assert marker == "[persona_flag: owner 'maria', manager 'ziggy' off-roster]"


def test_advisory_uses_singleton_when_known_keys_none( monkeypatch ):
    # known_keys=None falls through to the lazy roster singleton (no live config).
    monkeypatch.setattr( rules, "_KNOWN_PERSONA_KEYS", { "krishna" } )
    assert rules.build_persona_advisory( "krishna", None ) == ( None, None )
    advisory, marker = rules.build_persona_advisory( "ghost", None )
    assert advisory == { "owner_persona": "ghost" } and "ghost" in marker


def _mock_config_loaders( monkeypatch, pool, overflow ):
    """Point _get_known_persona_keys's lazy-imported loaders at fixed fakes."""
    import cosa.rest.voice_persona_helpers as vph
    import cosa.rest.dependencies.config as cfg
    monkeypatch.setattr( rules, "_KNOWN_PERSONA_KEYS", None )
    monkeypatch.setattr( cfg, "get_config_manager", lambda: object() )
    monkeypatch.setattr( vph, "load_persona_pool_from_config", lambda cm: pool )
    monkeypatch.setattr( vph, "load_overflow_persona_from_config", lambda cm: overflow )


def test_known_persona_keys_build_once_and_cache( monkeypatch ):
    # pool: one real name + one all-punctuation entry (canon "" → skipped).
    _mock_config_loaders( monkeypatch, [ { "name": "Rachel" }, { "name": "!!!" } ], { "name": "sam" } )
    first  = rules._get_known_persona_keys()
    second = rules._get_known_persona_keys()
    assert first == { "rachel", "sam" }                       # punctuation entry skipped
    assert second is first                                    # cached, not rebuilt


def test_known_persona_keys_overflow_none( monkeypatch ):
    _mock_config_loaders( monkeypatch, [ { "name": "Tiberius" } ], None )
    assert rules._get_known_persona_keys() == { "tiberius" }


def test_known_persona_keys_overflow_empty_key_skipped( monkeypatch ):
    _mock_config_loaders( monkeypatch, [ { "name": "Rio" } ], { "name": "!!!" } )
    assert rules._get_known_persona_keys() == { "rio" }


# ---------------------------------------------------------------------------
# One-call BLOCKED mint (Rick's ruling 2026-07-20, build 1b5483f4):
# validate_create_status · validate_blocked_fields (shared) · session_id_from_created_by
# ---------------------------------------------------------------------------

def test_create_allowed_statuses_are_exactly_queued_and_blocked():
    assert rules.CREATE_ALLOWED_STATUSES == ( "queued", "blocked" )


def test_validate_create_status_queued_ignores_blocked_fields():
    # A queued mint is valid with no blocked_by / next_chase_ts, AND ignores stray
    # ones (they are dropped by the repository) — today's behavior preserved.
    assert rules.validate_create_status( "queued", None, None ) == [ ]
    assert rules.validate_create_status( "queued", [ { "kind": "persona", "id": "x" } ], None ) == [ ]


@pytest.mark.parametrize( "bad", [ "done", "dropped", "parked", "claimed", "in_progress", "review", "bogus" ] )
def test_validate_create_status_rejects_non_whitelisted( bad ):
    errors = rules.validate_create_status( bad, None, None )
    assert len( errors ) == 1 and "cannot be minted at create" in errors[ 0 ]


def test_validate_create_status_blocked_happy_path():
    # A blocked mint with >=1 typed ref + a chase (persona ref requires it) passes.
    assert rules.validate_create_status(
        "blocked", [ { "kind": "persona", "id": "tiberius" } ], NOW_TS
    ) == [ ]


def test_validate_create_status_blocked_persona_ref_requires_chase():
    # I3 kind-aware: a {kind:persona} blocker with no chase is rejected — the SAME
    # message validate_transition emits (proves the rule is shared, not forked).
    errors = rules.validate_create_status( "blocked", [ { "kind": "persona", "id": "tiberius" } ], None )
    assert any( "persona blocker requires a chase time" in e for e in errors )


def test_validate_create_status_blocked_empty_refs_rejected():
    errors = rules.validate_create_status( "blocked", [ ], NOW_TS )
    assert any( "non-empty list of typed refs" in e for e in errors )


def test_validate_create_status_blocked_user_ref_needs_no_chase():
    # A user/item-only block needs NO chase (you cannot schedule Rick) — valid
    # without next_chase_ts, exactly like the transition path.
    assert rules.validate_create_status( "blocked", [ { "kind": "user", "id": "rick" } ], None ) == [ ]


def test_validate_blocked_fields_matches_transition_blocked_branch():
    # The shared helper IS what validate_transition's ->blocked branch calls, so a
    # create-block and a transition-block agree by construction. Assert both agree
    # on the same inputs (one home, no drift).
    persona_no_chase = [ { "kind": "persona", "id": "maria" } ]
    from_create     = rules.validate_blocked_fields( persona_no_chase, None )
    from_transition = rules.validate_transition( "queued", "blocked", "standing", blocked_by=persona_no_chase )
    # every blocked-field error the helper reports also appears in the transition's
    assert from_create and all( e in from_transition for e in from_create )
    # and both accept the same valid input
    assert rules.validate_blocked_fields( persona_no_chase, NOW_TS ) == [ ]


@pytest.mark.parametrize( "created_by, expected", [
    ( "Cheech 4d376217",   "4d376217" ),   # 8-hex tail returned verbatim
    ( "mr radio 372f9dc9", "372f9dc9" ),    # persona-with-space, tail parsed off the LAST space
    ( "krishna",           None       ),    # no tail
    ( "agent beef",        None       ),    # "beef" is 4 hex (<6 floor) — not a sid
] )
def test_session_id_from_created_by( created_by, expected ):
    assert rules.session_id_from_created_by( created_by ) == expected


@pytest.mark.parametrize( "bad", [ None, "", "   ", 123, [ ] ] )
def test_session_id_from_created_by_unusable_input_is_none( bad ):
    assert rules.session_id_from_created_by( bad ) is None


# ---------------------------------------------------------------------------
# validate_park THROUGH validate_transition (Tiffany's finding, 2026-07-21)
# ---------------------------------------------------------------------------
#
# THE GAP WAS THE WIRING, NOT THE RULE. Measured before writing a line: this suite ran
# 253 green while `task_store_rules.py` reported line 853 — `errors.extend( validate_park(
# ... ) )` inside validate_transition — and lines 920-937 — every error body inside
# validate_park — as NEVER EXECUTED. So all three park rules were unreachable from the
# only function the API actually calls, and the board's park semantics rested on code no
# test had run.
#
# That is a different failure from "validate_park is untested": a directly-tested helper
# that nothing routes to is worse, because the green reads as coverage of the FEATURE
# while the feature's only entry point is dark. Every test below therefore goes through
# `validate_transition` — the caller — and never calls `validate_park` directly.
#
# The park contract, for a reader who lands here first: `parked` means a HUMAN ruled this
# row not-now. It is bounded and self-expiring by construction — `next_chase_ts` is
# REQUIRED, so any hold eventually rejoins the owed set at read time, and an indefinite
# hold is structurally unrepresentable. `park_reason` is REQUIRED and must quote the row's
# own decisive sentence, so the park stays refutable by the next reader.

_CHASE = _dt( 2026, 8, 1, 9, 0, tzinfo=_tz.utc )       # this module imports datetime aliased
_REASON = "parked past the Thursday demo — off the demo path entirely"


@pytest.mark.parametrize( "from_status", list( rules.PARK_LEGAL_FROM_STATUSES ) )
def test_transition_to_parked_is_accepted_from_every_legal_source( from_status ):
    """
    The happy path, once per legal source. This is the test that first executes line 853;
    without it the entire park branch of validate_transition is unreachable.
    """
    errors = rules.validate_transition( from_status, rules.PARK_STATUS, "standing",
                                        next_chase_ts=_CHASE, park_reason=_REASON )
    assert errors == [ ], errors


@pytest.mark.parametrize( "from_status", [ "blocked", "claimed", "review" ] )
def test_transition_to_parked_is_refused_from_an_illegal_source( from_status ):
    """
    The source-status rule is what keeps the owed-set restoration EXACT: because an
    expired-parked row provably came from queued/in_progress, re-admitting the whole
    expired-parked set can never drag in a blocked/claimed/review row. Parking a
    `blocked` row would silently widen every reader's owed definition.

    ⚠️ `parked` WAS in this list, with the note "re-parking is not a refresh". Row
    aa543525 (2026-07-27) reversed that ON EVIDENCE — see the re-park tests below.
    It stays OUT of PARK_LEGAL_FROM_STATUSES, which is what actually carries the
    restoration proof; the ENTRY set is unchanged and this test still pins it.
    """
    errors = rules.validate_transition( from_status, rules.PARK_STATUS, "standing",
                                        next_chase_ts=_CHASE, park_reason=_REASON )
    assert any( "cannot park from" in e for e in errors ), errors


def test_reparking_a_parked_row_is_legal_the_prescribed_remedy_is_reachable():
    """
    `task_store_tools` prescribes *"Re-park to re-freeze the quote"* for a park
    reason that has gone stale. That remedy was refused by TWO INDEPENDENT GATES —
    park-legality (source not in PARK_LEGAL_FROM_STATUSES) and the LEGAL_TRANSITIONS
    no-op edge — so the one action the documentation named as the fix could not be
    spelled at all. Row aa543525.

    ⚠️ WHY THIS IS AN END-TO-END TEST AND NOT A PREDICATE TEST. Fixing park-legality
    alone still left the edge refused, and the ONLY thing that surfaced the second
    gate was a red test. A unit test on `is_park_legal_from` would have gone green
    while the operation stayed impossible — the instrument would have answered a
    narrower question than the reader believed, which is this row's whole subject.
    """
    errors = rules.validate_transition( rules.PARK_STATUS, rules.PARK_STATUS, "standing",
                                        next_chase_ts=_CHASE, park_reason=_REASON )
    assert errors == [ ], errors


def test_repark_still_requires_its_payload_the_carve_out_fails_closed():
    """
    The carve-out opens an EDGE, never the ->parked payload rules. A re-park missing
    its reason or its chase must still be refused — otherwise the escape hatch
    becomes a way to write the nullity event the no-op rejection existed to prevent.
    """
    no_reason = rules.validate_transition( rules.PARK_STATUS, rules.PARK_STATUS, "standing",
                                           next_chase_ts=_CHASE, park_reason="   " )
    assert no_reason != [ ], "a blank-reason re-park was permitted — the carve-out did not fail closed"

    no_chase = rules.validate_transition( rules.PARK_STATUS, rules.PARK_STATUS, "standing",
                                          next_chase_ts=None, park_reason=_REASON )
    assert no_chase != [ ], "a chase-less re-park was permitted — the carve-out did not fail closed"


@pytest.mark.parametrize( "status", [ "queued", "in_progress", "review" ] )
def test_the_other_same_status_edges_stay_shut( status ):
    """
    The carve-out is scoped to `parked` ALONE. `is_blocker_repoint`'s docstring is
    right that a general "same status when the payload differs" rule would open four
    edges writing audit events that mean nothing; `parked` is the lone exception,
    because a ->parked write re-stamps the capture timestamp and so changes real
    state. The other three must stay shut.

    THIS IS THE GUARD THAT PROVES THE CARVE-OUT DID NOT GENERALIZE — without it,
    widening `is_park_refresh` to any same-status pair would pass every other test
    in this file.
    """
    errors = rules.validate_transition( status, status, "standing",
                                        next_chase_ts=_CHASE, park_reason=_REASON )
    assert any( "no-op transition" in e for e in errors ), errors


def test_transition_to_parked_requires_a_chase_time():
    """
    No chase means an unbounded hold, and an unbounded hold is what `dropped` is for —
    because dropping is VISIBLE. The chase IS the un-park.
    """
    errors = rules.validate_transition( "queued", rules.PARK_STATUS, "standing",
                                        next_chase_ts=None, park_reason=_REASON )
    assert any( "next_chase_ts is REQUIRED" in e for e in errors ), errors


@pytest.mark.parametrize( "bad_reason", [ None, "", "   ", "\n\t ", 123, [ ] ] )
def test_transition_to_parked_requires_a_non_blank_string_reason( bad_reason ):
    """
    Blank-but-present is the interesting half: `park_reason=""` satisfies a presence check
    and says nothing, which is exactly how two catalogs mis-counted this board by reading
    titles. Non-string types are included because the field arrives off the wire.
    """
    errors = rules.validate_transition( "queued", rules.PARK_STATUS, "standing",
                                        next_chase_ts=_CHASE, park_reason=bad_reason )
    assert any( "park_reason is REQUIRED" in e for e in errors ), errors


def test_transition_to_parked_reports_every_violation_at_once():
    """
    One error per violation, not first-wins. A caller fixing a park payload should learn
    everything wrong with it in one round trip rather than discovering the next problem
    after fixing the last — and this is also what pins "never raises".
    """
    errors = rules.validate_transition( "blocked", rules.PARK_STATUS, "standing",
                                        next_chase_ts=None, park_reason="  " )
    assert len( errors ) == 3, errors
    assert any( "cannot park from"        in e for e in errors )
    assert any( "next_chase_ts is REQUIRED" in e for e in errors )
    assert any( "park_reason is REQUIRED"   in e for e in errors )


def test_park_rules_do_not_fire_on_transitions_that_are_not_parks():
    """
    THE NEGATIVE CONTROL. A guard that fires everywhere is an outage — and a park rule
    leaking onto ordinary transitions would demand a chase time and a reason on every
    queued->in_progress move in the fleet. Same payload shape, different destination.
    """
    errors = rules.validate_transition( "queued", "in_progress", "standing",
                                        next_chase_ts=None, park_reason=None )
    assert not any( "park" in e for e in errors ), errors


# ---------------------------------------------------------------------------
# bee6856a — re-pointing a blocker must not require a false in_progress hop
# ---------------------------------------------------------------------------
#
# THE DEFECT: there was no legal way to change WHO a blocked row is blocked on.
# `blocked->blocked` was refused, `task_edit` refuses the invariant-bearing
# fields, and `task_amend` is body-only — so the only way through was the detour
# `blocked -> in_progress -> blocked`, which writes a `blocked->in_progress`
# event asserting work resumed on a row where none did (events 4082/4083 on
# 36e479ed are the receipt). A reason string is a mitigation, not a fix: it
# makes a human read prose to un-learn what the structured field says.
#
# WHAT THE OLD REJECTION WAS GUARDING: nothing designed. LEGAL_TRANSITIONS is
# derived by `dst != src`, and its header calls the construct BEHAVIOR-
# PRESERVING — it made the Phase-1 IMPLICIT graph explicit "so a future
# TIGHTENING has one home". `blocked->blocked` was simply not callable in
# Phase 1; making the graph explicit froze an accident into a rule.
#
# ⇒ The risk here is WIDENING, not un-guarding. The carve-out is therefore
#   scoped to `blocked` ALONE, and the third test below is the fence on that:
#   it asserts the hole is EXACTLY ONE STATUS WIDE. Without it, "permit
#   same-status when the payload differs" would silently open queued->queued,
#   in_progress->in_progress, review->review and parked->parked — four legal
#   edges that each write an audit event and mean nothing. That widening would
#   be silent AND green, which is the failure mode this row exists to stop.

_CHASE_A = "2026-07-22T09:00:00-04:00"
_CHASE_B = "2026-07-23T09:00:00-04:00"


def test_repoint_permitted_when_the_blocker_actually_changes():
    # The row's reason for existing: re-point `blocked_by` with NO status detour.
    errors = rules.validate_transition(
        "blocked", "blocked", "standing",
        next_chase_ts         = _CHASE_A,
        blocked_by            = [ { "kind": "user", "id": "rick" } ],
        current_blocked_by    = [ { "kind": "persona", "id": "mr radio" } ],
        current_next_chase_ts = _CHASE_A,
    )
    assert errors == [ ], errors


def test_repoint_permitted_when_only_the_chase_time_changes():
    # Re-scheduling the chase on an unchanged blocker is the same act: a real
    # payload change, no work resumed, no in_progress event owed.
    errors = rules.validate_transition(
        "blocked", "blocked", "standing",
        next_chase_ts         = _CHASE_B,
        blocked_by            = [ { "kind": "persona", "id": "arnold" } ],
        current_blocked_by    = [ { "kind": "persona", "id": "arnold" } ],
        current_next_chase_ts = _CHASE_A,
    )
    assert errors == [ ], errors


def test_true_no_op_blocked_to_blocked_is_still_rejected():
    # The part of the OLD behaviour worth keeping. Same blocker, same chase =>
    # nothing changed, so the event would be pure noise in the audit trail.
    errors = rules.validate_transition(
        "blocked", "blocked", "standing",
        next_chase_ts         = _CHASE_A,
        blocked_by            = [ { "kind": "persona", "id": "arnold" } ],
        current_blocked_by    = [ { "kind": "persona", "id": "arnold" } ],
        current_next_chase_ts = _CHASE_A,
    )
    assert len( errors ) == 1 and "no-op transition" in errors[ 0 ], errors


def test_blocked_to_blocked_without_current_values_is_still_rejected():
    # A caller that does NOT supply the current values gets the old behaviour —
    # fail CLOSED. The carve-out must never fire on absence of evidence.
    errors = rules.validate_transition(
        "blocked", "blocked", "standing",
        next_chase_ts = _CHASE_A,
        blocked_by    = [ { "kind": "persona", "id": "arnold" } ],
    )
    assert any( "no-op transition" in e for e in errors ), errors


@pytest.mark.parametrize( "status", [ s for s in rules.VALID_STATUSES
                                      if s not in rules.TERMINAL_STATUSES and s != "blocked" ] )
def test_the_carve_out_is_exactly_one_status_wide( status ):
    # THE FENCE (Arnold 5bcd3ad6, and the reason this row's real risk is in the
    # legal-graph rather than the signature): every OTHER non-terminal self-edge
    # stays rejected even when the payload differs. If this goes green for any
    # status other than `blocked`, the carve-out has widened past its warrant.
    errors = rules.validate_transition(
        status, status, "standing",
        next_chase_ts         = _CHASE_B,
        blocked_by            = [ { "kind": "user", "id": "rick" } ],
        current_blocked_by    = [ { "kind": "persona", "id": "mr radio" } ],
        current_next_chase_ts = _CHASE_A,
    )
    assert any( "no-op transition" in e for e in errors ), f"{status}->{status} must stay illegal: {errors}"


def test_repoint_still_enforces_the_blocked_payload_invariant():
    # The carve-out opens an EDGE; it does not relax ->blocked's payload rules.
    # A re-point with an empty blocked_by is still refused by I3 / ruling #5.
    errors = rules.validate_transition(
        "blocked", "blocked", "standing",
        next_chase_ts         = _CHASE_B,
        blocked_by            = [ ],
        current_blocked_by    = [ { "kind": "persona", "id": "mr radio" } ],
        current_next_chase_ts = _CHASE_A,
    )
    assert errors, "an empty blocked_by must still fail the ->blocked invariant"
    assert not any( "no-op transition" in e for e in errors ), errors


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )


# ── persona blocked_by refs may carry a session_id (row 00a6bde2 item 6) ──────
#
# A {kind:"persona", id:<name>} edge is UNRESOLVABLE BY CONSTRUCTION — this store has
# no persona lifecycle to check a name against. Worse than a dead ref: overflow names
# (`extra 1`, `arnold`) are RE-GRANTED after a reap, so a stale edge can silently
# RE-POINT at a different session and be "satisfied" by someone who never had the
# context. That is a false GREEN, not a false wait, and it is the more dangerous half.

def test_a_persona_ref_may_carry_a_session_id():
    assert rules.validate_blocked_by_refs(
        [ { "kind": "persona", "id": "maria",
            "session_id": "697e9fef-881d-42ea-9e1f-9b6cebafb6e6" } ] ) == [ ]


def test_a_persona_ref_WITHOUT_a_session_id_is_still_legal():
    """
    ⚠️ OPTIONAL, NOT REQUIRED. Making it mandatory would 422 every existing caller and
    every peer not yet updated — converting a latent correctness gap into a live write
    outage. Requiring it is a separate decision, once the fleet's callers actually send it.
    """
    assert rules.validate_blocked_by_refs( [ { "kind": "persona", "id": "maria" } ] ) == [ ]


@pytest.mark.parametrize( "kind", [ "item", "user" ] )
def test_a_session_id_on_a_NON_persona_ref_is_an_error( kind ):
    """
    ⚠️ NOT SILENTLY IGNORED. An item id already resolves against this store and a user
    has no session, so a session_id there is a field that LOOKS authoritative and means
    nothing — the exact shape row 00a6bde2 exists to kill. Accepting-and-ignoring it
    would put a second addressee on the row that no reader can act on.
    """
    errors = rules.validate_blocked_by_refs( [ { "kind": kind, "id": "x", "session_id": "s" } ] )
    assert len( errors ) == 1 and "only meaningful on a {kind:persona}" in errors[ 0 ]


def test_an_empty_session_id_is_rejected_rather_than_treated_as_absent():
    """A present-but-blank stamp is worse than none: it reads as "resolved to nothing"."""
    assert rules.validate_blocked_by_refs(
        [ { "kind": "persona", "id": "maria", "session_id": "" } ] ) != [ ]


def test_unknown_keys_are_STILL_rejected():
    """
    THE NEGATIVE CONTROL. `session_id` is the ONE key added to the allowed set. If the
    shape check had been loosened to "anything goes" instead, this passes and the strict
    typing the oracle depends on is gone — with every other test here still green.
    """
    assert rules.validate_blocked_by_refs(
        [ { "kind": "persona", "id": "maria", "wat": 1 } ] ) != [ ]
    assert rules.validate_blocked_by_refs( [ { "kind": "persona" } ] ) != [ ]


def test_a_stamped_persona_ref_is_still_NOT_an_item_blocker():
    """
    `blocker_terminal` must stay blind to persona edges — stamping one does not give it
    an oracle, it gives a FUTURE oracle something to resolve. Treating a stamped edge as
    resolvable today would flag every persona-blocked row as dead.
    """
    from cosa.rest.task_store_owed import item_blocker_ids
    assert item_blocker_ids( [ { "kind": "persona", "id": "maria", "session_id": "s" } ] ) == [ ]


def test_the_persona_chase_requirement_is_unaffected_by_the_stamp():
    """I3 — a peer is chaseable, so a persona blocker still requires next_chase_ts."""
    assert rules.blocked_by_has_persona(
        [ { "kind": "persona", "id": "maria", "session_id": "s" } ] ) is True
    assert rules.validate_blocked_fields(
        [ { "kind": "persona", "id": "maria", "session_id": "s" } ], None ) != [ ]
