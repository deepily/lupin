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
    assert len( errors ) == 1 and "must be exactly {kind, id}" in errors[ 0 ]


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


def test_transition_to_blocked_requires_chase_ts_and_refs():
    errors = rules.validate_transition( "in_progress", "blocked", "standing" )
    assert len( errors ) == 2
    assert any( "next_chase_ts" in e for e in errors )
    assert any( "blocked_by" in e for e in errors )


def test_transition_to_blocked_accepts_chase_ts_plus_typed_refs():
    from datetime import datetime, timezone
    errors = rules.validate_transition(
        "in_progress", "blocked", "standing",
        next_chase_ts = datetime( 2026, 6, 12, 9, 0, tzinfo=timezone.utc ),
        blocked_by    = [ { "kind": "user", "id": "rick" } ],
    )
    assert errors == [ ]


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


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
