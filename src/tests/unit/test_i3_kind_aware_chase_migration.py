"""
DB-free structural guards for migration 53835fd51f1a (i3_kind_aware_blocked_chase,
eab1d7da). These read the migration script + the ORM model directly — NO Postgres,
so they run in the :7999 unit bucket / plain CI.

The EMPIRICAL up→down→up round-trip that executes the DDL against a live Postgres
lives in src/tests/smoke/test_i3_kind_aware_chase_roundtrip.py (throwaway DB,
skips when no database is reachable). AC5's zero-violator proof against the REAL
populated table is the :8000 integration tier (plan §7).

What THIS module proves DB-free:
  · AC1 parity — the migration's new-CHECK literal matches postgres_models
    VERBATIM (a model/migration divergence is a CHECK that silently means two
    different things on a fresh-from-metadata DB vs a migrated one).
  · chain integrity — the revision exists, chains onto the prior head, single head.
  · downgrade is not a stub — it targets the ORIGINAL global predicate.
  · superset logic — every row the OLD predicate permitted, the NEW one permits
    (the claim that makes AC5's zero-violator true by construction).
"""
import importlib.util

from alembic.script import ScriptDirectory

from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest import task_store_rules as rules


_REVISION      = "53835fd51f1a"
_DOWN_REVISION = "d0caad3ee21e"
_CONSTRAINT    = "ck_task_items_blocked_requires_chase_ts"


def _script_dir():
    return ScriptDirectory.from_config( build_alembic_config( database_url=None ) )


def _migration_module():
    """Import the migration script as a module so its constants are readable."""
    path = _script_dir().get_revision( _REVISION ).path
    spec = importlib.util.spec_from_file_location( "i3_migration", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _model_check_literal():
    """The blocked-chase CheckConstraint literal on the live ORM model."""
    from cosa.rest.postgres_models import TaskItem
    for constraint in TaskItem.__table__.constraints:
        if getattr( constraint, "name", None ) == _CONSTRAINT:
            return str( constraint.sqltext )
    raise AssertionError( f"model has no CheckConstraint named {_CONSTRAINT!r}" )


# ---------------------------------------------------------------------------
# Chain integrity
# ---------------------------------------------------------------------------

def test_revision_present_and_chains_onto_prior_head():
    rev = _script_dir().get_revision( _REVISION )
    assert rev is not None, f"migration {_REVISION!r} missing from the chain"
    assert rev.down_revision == _DOWN_REVISION, (
        f"down_revision must be {_DOWN_REVISION!r} (prior head), got {rev.down_revision!r}" )


def test_chain_has_a_single_head():
    heads = list( _script_dir().get_heads() )
    assert len( heads ) == 1, f"expected exactly one head, got {heads!r}"


# ---------------------------------------------------------------------------
# AC1 — model / migration parity (VERBATIM)
# ---------------------------------------------------------------------------

def test_migration_new_check_matches_model_verbatim():
    module = _migration_module()
    assert module.KIND_AWARE_PREDICATE == _model_check_literal(), (
        "migration upgrade predicate diverged from the postgres_models CheckConstraint "
        "literal — the CHECK would mean two different things on a fresh vs migrated DB" )


def test_migration_upgrade_target_is_the_kind_aware_predicate():
    module = _migration_module()
    # The kind-aware predicate must carry the persona-containment clause.
    assert "blocked_by @> '[{\"kind\": \"persona\"}]'::jsonb" in module.KIND_AWARE_PREDICATE
    assert "status != 'blocked'" in module.KIND_AWARE_PREDICATE


def test_downgrade_target_is_the_original_global_predicate_not_a_stub():
    module = _migration_module()
    # Downgrade must RESTORE the old global rule (a real reversal). Proven by the
    # constant it swaps to — the persona clause must be ABSENT from it.
    assert module.GLOBAL_PREDICATE == "status != 'blocked' OR next_chase_ts IS NOT NULL"
    assert "persona" not in module.GLOBAL_PREDICATE
    # And the two are genuinely different, or "downgrade" would be a no-op masquerade.
    assert module.GLOBAL_PREDICATE != module.KIND_AWARE_PREDICATE


# ---------------------------------------------------------------------------
# Superset logic — the claim behind AC5 (zero violators, no backfill)
# ---------------------------------------------------------------------------

class TestNewPredicateIsSupersetOfOld:
    """
    The new CHECK permits every row the old one did, PLUS null-chase non-persona
    blocks. Proven here at the app-twin level (blocked_by_has_persona mirrors the
    CHECK's @> containment) so the "zero existing violators" claim is grounded in
    logic, not asserted. The DB-backed count against real rows is AC5 on :8000.

    Old CHECK permitted a blocked row IFF next_chase_ts IS NOT NULL.
    New CHECK permits a blocked row IFF chase set OR no persona blocker.
    ⇒ old-permitted (chase set) ⊆ new-permitted (chase set OR no persona). Any row
      with a chase passes BOTH; rows the new one adds are exactly null-chase +
      no-persona, which the old one REJECTED. Superset, never stricter.
    """

    # ( blocked_by, chase_set, old_permits, new_permits )
    ROWS = [
        ( [ { "kind": "persona", "id": "sam" } ],  True,  True,  True  ),   # chase → both
        ( [ { "kind": "persona", "id": "sam" } ],  False, False, False ),   # persona+null → both reject
        ( [ { "kind": "user", "id": "rick" } ],    True,  True,  True  ),   # chase → both
        ( [ { "kind": "user", "id": "rick" } ],    False, False, True  ),   # NEW admits, old rejected
        ( [ { "kind": "item", "id": "X" } ],       False, False, True  ),   # NEW admits, old rejected
    ]

    def _old_permits( self, chase_set ):
        return chase_set                                          # status=blocked ⇒ needs chase

    def _new_permits( self, blocked_by, chase_set ):
        return chase_set or not rules.blocked_by_has_persona( blocked_by )

    def test_truth_table_matches_expectation( self ):
        for blocked_by, chase_set, exp_old, exp_new in self.ROWS:
            assert self._old_permits( chase_set ) is exp_old, ( blocked_by, chase_set )
            assert self._new_permits( blocked_by, chase_set ) is exp_new, ( blocked_by, chase_set )

    def test_new_is_a_strict_superset_never_stricter( self ):
        # For EVERY row: old-permitted ⇒ new-permitted (superset). And at least one
        # row the new admits that the old rejected (strict), or the migration would
        # be a rename with no behavior change to justify it.
        added = 0
        for blocked_by, chase_set, _o, _n in self.ROWS:
            old = self._old_permits( chase_set )
            new = self._new_permits( blocked_by, chase_set )
            assert not ( old and not new ), f"row NARROWED — not a superset: {blocked_by} chase={chase_set}"
            if new and not old:
                added += 1
        assert added > 0, "new predicate admits nothing the old rejected — no superset gain"


# ---------------------------------------------------------------------------
# upgrade() / downgrade() / _swap_predicate() — DB-free, mocked op + inspector.
# The live DDL round-trip is the smoke test; this pins the CONTROL FLOW (drop
# before create, no-op when the table is absent, create-only when the
# constraint is absent) deterministically, for 100% line+branch on the migration.
# ---------------------------------------------------------------------------

class _FakeInspector:
    def __init__( self, has_table, constraints ):
        self._has_table   = has_table
        self._constraints = constraints

    def get_table_names( self ):
        return [ "task_items" ] if self._has_table else [ ]

    def get_check_constraints( self, table ):
        return [ { "name": n } for n in self._constraints ]


class _FakeOp:
    """Records drop/create calls; get_bind() is a harmless sentinel."""
    def __init__( self ):
        self.calls = [ ]

    def get_bind( self ):
        return "bind-sentinel"

    def drop_constraint( self, name, table, type_ ):
        self.calls.append( ( "drop", name, table, type_ ) )

    def create_check_constraint( self, name, table, condition ):
        self.calls.append( ( "create", name, table, condition ) )


def _patched_migration( monkeypatch, has_table, constraints ):
    """Load the migration module and swap its `op` + `inspect` for fakes."""
    module = _migration_module()
    fake_op = _FakeOp()
    monkeypatch.setattr( module, "op", fake_op )
    monkeypatch.setattr( module, "inspect", lambda _bind: _FakeInspector( has_table, constraints ) )
    return module, fake_op


class TestMigrationControlFlow:

    def test_upgrade_drops_then_creates_kind_aware( self, monkeypatch ):
        module, op = _patched_migration( monkeypatch, has_table=True, constraints=[ _CONSTRAINT ] )
        module.upgrade()
        assert op.calls == [
            ( "drop",   _CONSTRAINT, "task_items", "check" ),
            ( "create", _CONSTRAINT, "task_items", module.KIND_AWARE_PREDICATE ),
        ]

    def test_downgrade_drops_then_creates_global( self, monkeypatch ):
        module, op = _patched_migration( monkeypatch, has_table=True, constraints=[ _CONSTRAINT ] )
        module.downgrade()
        assert op.calls == [
            ( "drop",   _CONSTRAINT, "task_items", "check" ),
            ( "create", _CONSTRAINT, "task_items", module.GLOBAL_PREDICATE ),
        ]

    def test_absent_table_is_a_noop( self, monkeypatch ):
        module, op = _patched_migration( monkeypatch, has_table=False, constraints=[ ] )
        module.upgrade()
        assert op.calls == [ ]                                  # fresh-from-metadata DB: nothing to migrate

    def test_absent_constraint_creates_without_dropping( self, monkeypatch ):
        # The drop is guarded by presence; a partial/re-run state with the CHECK
        # already gone still converges to the new constraint via create-only.
        module, op = _patched_migration( monkeypatch, has_table=True, constraints=[ ] )
        module.upgrade()
        assert op.calls == [ ( "create", _CONSTRAINT, "task_items", module.KIND_AWARE_PREDICATE ) ]
