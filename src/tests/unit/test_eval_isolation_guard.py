"""Unit tests for the paired-eval snapshot-store isolation guard (two checks).

VENUE: :7999 — pure, injected sources, no server, no DB.

Two must-fail CONTROLS carry the SAFETY check, one per direction the old table-name-only
predicate got wrong:
  · test_safety_refuses_a_shared_db_write — the old guard ALLOWED a shared-db write (it
    only compared table names); the new one refuses the fully-qualified dev.solution_snapshots.
  · test_safety_allows_same_table_in_an_isolated_db — the old guard BLOCKED a genuinely
    isolated different-database write with the same table name; the new one allows it.
Each goes red on the old predicate, for the right reason (the database half of the identity).
"""

import os
import sys

import pytest

_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT:
    _SCRIPTS = os.path.join( _LUPIN_ROOT, "src", "scripts" )
    if _SCRIPTS not in sys.path:
        sys.path.insert( 0, _SCRIPTS )

import eval_isolation_guard as guard   # noqa: E402


_SHARED_TABLE = "solution_snapshots"                     # the ORM shipped default table
_SHARED_DEV   = "lupin_db_dev.solution_snapshots"        # the LIVE shared store (never permitted)
_ISO_DEDICATED = "lupin_db_test.v2_paired_snapshots"     # a dedicated isolated store
_ISO_SAME_TABLE = "lupin_db_test.solution_snapshots"     # same table name, ISOLATED by database


class _FakeConfig:
    """Minimal ConfigurationManager stand-in: .get( key, default, return_type )."""
    def __init__( self, values ):
        self.values = values
    def get( self, key, default=None, return_type=None ):
        return self.values.get( key, default )


def _cfg( *, writeback=True, allowlist=None ):
    values = { "v2 snapshot writeback enabled": writeback }
    if allowlist is not None:
        values[ guard.PERMITTED_STORES_KEY ] = allowlist
    return _FakeConfig( values )


# ---------------------------------------------------------------------------
# helpers: parse / db-name / fully-qualified
# ---------------------------------------------------------------------------
def test_parse_permitted_stores_variants():
    assert guard.parse_permitted_stores( None ) == set()
    assert guard.parse_permitted_stores( "   " ) == set()
    assert guard.parse_permitted_stores( "a.b" ) == { "a.b" }
    assert guard.parse_permitted_stores( " a.b , c.d ,, " ) == { "a.b", "c.d" }


def test_db_name_strips_leading_slash_and_ignores_query_fragment():
    assert guard._db_name( "postgresql://u:p@h/lupin_db_test?sslmode=require" ) == "lupin_db_test"
    assert guard._db_name( "postgresql://u:p@h/lupin_db_dev#/lupin_db_test" ) == "lupin_db_dev"


def test_fully_qualified_joins_db_and_table():
    assert guard.fully_qualified( "lupin_db_test", "solution_snapshots" ) == "lupin_db_test.solution_snapshots"


# ---------------------------------------------------------------------------
# SAFETY — require_isolated_snapshot_table
# ---------------------------------------------------------------------------
def test_writeback_off_needs_no_isolation():
    cfg = _cfg( writeback=False )
    # No write happens, so the guard returns None without inspecting the destination.
    assert guard.require_isolated_snapshot_table( cfg, write_target=_SHARED_TABLE, write_database="lupin_db_dev" ) is None


def test_fail_closed_when_allowlist_is_empty_or_absent():
    # Writeback ON, no allowlist configured -> the destination cannot be PROVEN non-live.
    cfg = _cfg( allowlist=None )
    with pytest.raises( guard.IsolationNotConfigured ) as exc:
        guard.require_isolated_snapshot_table( cfg, write_target=_SHARED_TABLE, write_database="lupin_db_test" )
    assert "allowlist is empty" in str( exc.value )
    # An explicitly blank allowlist is the same fail-closed refusal.
    cfg_blank = _cfg( allowlist="   " )
    with pytest.raises( guard.IsolationNotConfigured ):
        guard.require_isolated_snapshot_table( cfg_blank, write_target=_SHARED_TABLE, write_database="lupin_db_test" )


def test_safety_refuses_a_shared_db_write():
    """MUST-FAIL CONTROL (direction 1). The app would write dev.solution_snapshots — a LIVE
    store. The OLD table-name-only guard, with its isolated cfg set to 'solution_snapshots',
    passed this (table == table). The new guard refuses the fully-qualified destination."""
    cfg = _cfg( allowlist=_ISO_DEDICATED )
    with pytest.raises( guard.IsolationNotConfigured ) as exc:
        guard.require_isolated_snapshot_table( cfg, write_target=_SHARED_TABLE, write_database="lupin_db_dev" )
    assert "NOT in the permitted" in str( exc.value ) and _SHARED_DEV in str( exc.value )


def test_safety_allows_same_table_in_an_isolated_db():
    """MUST-FAIL CONTROL (direction 2). Same table name 'solution_snapshots' but in the
    ISOLATED lupin_db_test database. The OLD table-name-only guard BLOCKED this (table ==
    shared name, != a synthetic isolated cfg). The new guard ALLOWS it — the db isolates."""
    cfg = _cfg( allowlist=_ISO_SAME_TABLE )
    result = guard.require_isolated_snapshot_table( cfg, write_target=_SHARED_TABLE, write_database="lupin_db_test" )
    assert result == _ISO_SAME_TABLE


def test_safety_allows_a_dedicated_isolated_store():
    cfg = _cfg( allowlist=f"{_ISO_DEDICATED}, {_ISO_SAME_TABLE}" )
    result = guard.require_isolated_snapshot_table( cfg, write_target="v2_paired_snapshots", write_database="lupin_db_test" )
    assert result == _ISO_DEDICATED


def test_resolve_write_target_reads_the_real_orm_table():
    # Live control: the guard's table source is the ORM attribute the app writes through.
    # A rename of the shared table is caught here instead of silently defeating the guard.
    assert guard.resolve_write_target() == _SHARED_TABLE


# ---------------------------------------------------------------------------
# VALIDITY — require_arms_distinct_and_clean
# ---------------------------------------------------------------------------
def test_validity_passes_when_arms_are_distinct_and_clean():
    result = guard.require_arms_distinct_and_clean(
        "lupin_db_v1baseline.solution_snapshots", "lupin_db_test.solution_snapshots",
        v1_rowcount=0, v2_rowcount=0,
    )
    assert result == ( "lupin_db_v1baseline.solution_snapshots", "lupin_db_test.solution_snapshots" )


def test_validity_refuses_when_arms_share_a_destination():
    with pytest.raises( guard.PairedTargetsNotIsolated ) as exc:
        guard.require_arms_distinct_and_clean( _ISO_SAME_TABLE, _ISO_SAME_TABLE, v1_rowcount=0, v2_rowcount=0 )
    assert "SAME destination" in str( exc.value )


def test_validity_refuses_when_a_destination_is_dirty():
    with pytest.raises( guard.PairedTargetsNotIsolated ) as exc:
        guard.require_arms_distinct_and_clean( "db1.t", "db2.t", v1_rowcount=5, v2_rowcount=0 )
    assert "START CLEAN" in str( exc.value ) and "db1.t" in str( exc.value )


def test_validity_names_both_dirty_arms():
    with pytest.raises( guard.PairedTargetsNotIsolated ) as exc:
        guard.require_arms_distinct_and_clean( "db1.t", "db2.t", v1_rowcount=3, v2_rowcount=7 )
    msg = str( exc.value )
    assert "db1.t" in msg and "db2.t" in msg


# ---------------------------------------------------------------------------
# assert_paired_isolation — the composing caller (queries counts, then checks)
# ---------------------------------------------------------------------------
def test_assert_paired_isolation_queries_both_stores_and_passes_when_clean():
    seen = []
    def rowcount_fn( target ):
        seen.append( target )
        return 0
    result = guard.assert_paired_isolation( "dbA.t", "dbB.t", rowcount_fn=rowcount_fn )
    assert result == ( "dbA.t", "dbB.t" )
    assert seen == [ "dbA.t", "dbB.t" ]        # BOTH stores were queried, in order


def test_assert_paired_isolation_refuses_a_dirty_arm():
    def rowcount_fn( target ):
        return 9 if target == "dbA.t" else 0
    with pytest.raises( guard.PairedTargetsNotIsolated ) as exc:
        guard.assert_paired_isolation( "dbA.t", "dbB.t", rowcount_fn=rowcount_fn )
    assert "START CLEAN" in str( exc.value ) and "dbA.t" in str( exc.value )


def test_assert_paired_isolation_refuses_shared_destination_at_zero_counts():
    # Rowcounts held at 0/0, so the refusal can ONLY come from the DISTINCT check —
    # this proves the shared-destination branch fired and was not masked by a dirty count.
    def rowcount_fn( target ):
        return 0
    with pytest.raises( guard.PairedTargetsNotIsolated ) as exc:
        guard.assert_paired_isolation( "dbA.t", "dbA.t", rowcount_fn=rowcount_fn )
    assert "SAME destination" in str( exc.value )


# ---------------------------------------------------------------------------
# CORPUS — require_leak_free_corpus (the corpus must not route to arg extraction)
# ---------------------------------------------------------------------------
_SIMPLE_CMDS  = { "agent router go to todo", "agent router go to math",
                  "agent router go to calculator", "agent router go to automatic", "none" }
_AGENTIC_CMDS = { "agent router go to deep research", "agent router go to claude code" }


def test_corpus_passes_when_disjoint_from_arg_extraction():
    # Injected leaky set; the simple commands never route to arg extraction, so it passes.
    result = guard.require_leak_free_corpus( _SIMPLE_CMDS, agentic_commands=_AGENTIC_CMDS )
    assert result == _SIMPLE_CMDS


def test_corpus_refuses_and_names_the_offending_command():
    corpus = _SIMPLE_CMDS | { "agent router go to deep research" }
    with pytest.raises( guard.PairedCorpusExercisesLeak ) as exc:
        guard.require_leak_free_corpus( corpus, agentic_commands=_AGENTIC_CMDS )
    msg = str( exc.value )
    assert "agent router go to deep research" in msg and "b0735467" in msg


def test_corpus_names_every_offender():
    corpus = { "none", "agent router go to deep research", "agent router go to claude code" }
    with pytest.raises( guard.PairedCorpusExercisesLeak ) as exc:
        guard.require_leak_free_corpus( corpus, agentic_commands=_AGENTIC_CMDS )
    msg = str( exc.value )
    assert "agent router go to deep research" in msg and "agent router go to claude code" in msg


def test_agentic_command_names_reads_the_live_registry_and_simple_is_disjoint():
    # LIVE control (the assertion Mr Radio recomputed by hand): the real registry is non-empty,
    # and the shipped 'simple' corpus commands are disjoint from it — so the default paired run
    # never routes to arg extraction. This goes RED the day someone maps a simple command to an
    # JOB_ARG_CONTRACTS entry, which is exactly when the pin's leak would start biting.
    leaky = guard.agentic_command_names()
    assert leaky                                   # registry is populated (not silently empty)
    assert _SIMPLE_CMDS.isdisjoint( leaky )        # 'simple' routes to nothing arg-extracting
    # And the live set genuinely refuses a corpus built from it:
    with pytest.raises( guard.PairedCorpusExercisesLeak ):
        guard.require_leak_free_corpus( { next( iter( leaky ) ) } )


# ---------------------------------------------------------------------------
# CONFIG cross-check — require_config_table_matches_write_target
#
# MUST-FAIL CONTROLS (predict the text first, then break it): a declared table that
# differs from the ORM write target must RAISE (the "wired but pointing wrong" defect),
# and an absent/blank declaration must RAISE too — it can never equal a real table name.
# ---------------------------------------------------------------------------
def _cfg_table( declared ):
    """A fake config carrying only the `v2 snapshot table` declaration (None to omit)."""
    values = {} if declared is None else { guard.CONFIG_SNAPSHOT_TABLE_KEY: declared }
    return _FakeConfig( values )


def test_config_table_match_returns_the_write_target():
    cfg = _cfg_table( "solution_snapshots" )
    assert guard.require_config_table_matches_write_target( cfg, write_target="solution_snapshots" ) == "solution_snapshots"


def test_config_table_match_strips_surrounding_whitespace():
    cfg = _cfg_table( "  solution_snapshots  " )
    assert guard.require_config_table_matches_write_target( cfg, write_target="solution_snapshots" ) == "solution_snapshots"


def test_config_table_drift_refuses_naming_both_values():
    # CONTROL: declared table != ORM write target -> the "wired but pointing wrong" defect.
    cfg = _cfg_table( "v2_paired_snapshots" )
    with pytest.raises( guard.ConfigTableMismatch ) as exc:
        guard.require_config_table_matches_write_target( cfg, write_target="solution_snapshots" )
    msg = str( exc.value )
    assert "v2_paired_snapshots" in msg and "solution_snapshots" in msg


def test_config_table_absent_declaration_refuses():
    # CONTROL: no declaration at all -> blank normalizes to "" which is never a real table.
    cfg = _cfg_table( None )
    with pytest.raises( guard.ConfigTableMismatch ):
        guard.require_config_table_matches_write_target( cfg, write_target="solution_snapshots" )


def test_config_table_blank_declaration_refuses():
    # CONTROL: whitespace-only declaration -> same refusal, distinct from a real name.
    cfg = _cfg_table( "   " )
    with pytest.raises( guard.ConfigTableMismatch ):
        guard.require_config_table_matches_write_target( cfg, write_target="solution_snapshots" )


# ---------------------------------------------------------------------------
# SAFETY (destructive-truncate) — assert_measurement_db
#
# MUST-FAIL CONTROLS: the dev/prod db, a substring-smuggled name, and a non-string
# target each REFUSE — a TRUNCATE is irreversible, so anything but the exact allowlist
# raises before the caller can execute it.
# ---------------------------------------------------------------------------
def test_assert_measurement_db_allows_the_two_measurement_dbs():
    assert guard.assert_measurement_db( "postgresql://u:p@h/lupin_db_test" ) is None
    assert guard.assert_measurement_db( "postgresql://u:p@h/lupin_db_v1baseline" ) is None


def test_assert_measurement_db_ignores_query_and_fragment():
    # The db name is the PATH, so a '/lupin_db_test' smuggled into the query cannot flip a dev url.
    with pytest.raises( guard.NotAMeasurementDatabase ):
        guard.assert_measurement_db( "postgresql://u:p@h/lupin_db_dev?options=/lupin_db_test" )


def test_assert_measurement_db_refuses_the_dev_db():
    # CONTROL: the live dev store must never be truncatable.
    with pytest.raises( guard.NotAMeasurementDatabase ) as exc:
        guard.assert_measurement_db( "postgresql://u:p@h/lupin_db_dev" )
    assert "lupin_db_dev" in str( exc.value )


def test_assert_measurement_db_refuses_a_substring_smuggle():
    # CONTROL: exact-name match, so 'lupin_db_test_shadow' cannot ride in on the prefix.
    with pytest.raises( guard.NotAMeasurementDatabase ):
        guard.assert_measurement_db( "postgresql://u:p@h/lupin_db_test_shadow" )


def test_assert_measurement_db_refuses_a_non_string_target():
    # CONTROL: a missing / non-string url is refused, never coerced.
    with pytest.raises( guard.NotAMeasurementDatabase ):
        guard.assert_measurement_db( None )
