"""
Unit tests for `src/scripts/embedding_regen_probe.py` — the script that clones the
embedding tables into a throwaway schema so a regeneration run can be rehearsed
without touching the live tables.

LOAD MECHANISM: `importlib.import_module( "embedding_regen_probe" )` with
`src/scripts` and `src` on `sys.path`, matching the sibling script tests.

NO DATABASE IS REACHED. `get_db` is replaced in the module's own namespace with a
fake session, so the SQL is asserted as TEXT rather than executed. That is the
right level for this script: its whole job is to emit statements, and the property
that matters — the live tables appear only inside SELECTs — is a property of the
strings, checkable without a server.

⚠️ THE SAFETY CLAIM IS TESTED, NOT ASSUMED. The docstring promises the live tables
are read and never written. `test_no_statement_writes_a_live_table` asserts it over
every generated statement rather than trusting the reviewer's eye, because a future
edit that adds an UPDATE against `public.` would otherwise pass every other test
here.
"""

import importlib
import os
import re
import runpy
import sys
from contextlib import contextmanager

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

erp = importlib.import_module( "embedding_regen_probe" )

SCRIPT_PATH = os.path.join( _ROOT, "src", "scripts", "embedding_regen_probe.py" )


# ── a session that records instead of connecting ─────────────────────────────

class _FakeSession:
    """Records executed SQL and answers scalars from a queue."""

    def __init__( self, scalars=() ):
        self.executed  = [ ]
        self.committed = False
        self._scalars  = list( scalars )

    def execute( self, statement, params=None ):
        self.executed.append( ( str( statement ), params ) )
        value = self._scalars.pop( 0 ) if self._scalars else None
        return _FakeResult( value )

    def commit( self ):
        self.committed = True


class _FakeResult:
    def __init__( self, value ): self._value = value
    def scalar( self ):          return self._value


def _install_db( monkeypatch, session ):
    """Replace get_db in the MODULE's namespace — never the real db module."""
    @contextmanager
    def fake_get_db():
        yield session
    monkeypatch.setattr( erp, "get_db", fake_get_db )
    return session


# ── _shadow_columns / _era_predicates ────────────────────────────────────────

def test_shadow_columns_are_the_regen_columns_for_that_table_only():
    assert erp._shadow_columns( "input_and_output" ) == [
        "input_embedding_regen", "output_final_embedding_regen" ]
    assert erp._shadow_columns( "prediction_decisions" ) == [ "question_embedding_regen" ]


def test_shadow_columns_is_empty_for_a_table_no_spec_names():
    assert erp._shadow_columns( "not_a_table" ) == [ ]


def test_era_predicates_cover_both_eras_and_require_source_text():
    labels = [ label for label, _p in erp._era_predicates( "prediction_decisions" ) ]
    assert labels == [ "normalized-era", "current-era" ]
    for _label, predicate in erp._era_predicates( "prediction_decisions" ):
        assert "question IS NOT NULL AND btrim(question) <> ''" in predicate
        assert "question_embedding IS NOT NULL" in predicate


def test_era_predicates_split_on_the_normalized_norm_ceiling():
    """
    The two eras must be complementary about the ceiling — one `<=`, one `>` — or a
    clone drawn from them would either double-count rows or miss a band entirely.
    """
    ceiling = erp.NORMALIZED_NORM_CEILING
    ( _n, normalized ), ( _c, current ) = erp._era_predicates( "input_and_output" )
    assert f"<= {ceiling}" in normalized
    assert f">  {ceiling}" in current


# ── build_statements ─────────────────────────────────────────────────────────

def test_build_statements_creates_the_probe_schema_first():
    assert erp.build_statements( 10 )[ 0 ] == f"CREATE SCHEMA IF NOT EXISTS {erp.PROBE_SCHEMA}"


def test_build_statements_clones_structure_and_restores_the_primary_key():
    """
    The PK is not decoration: LIKE does not copy it, and without it the regeneration
    run's per-row UPDATE by id seq-scans the clone. That is the artifact behind the
    withdrawn throughput figure the script's own comment records.
    """
    statements = erp.build_statements( 10 )
    for table in erp.SOURCE_TABLES:
        target = f"{erp.PROBE_SCHEMA}.{table}"
        assert f"DROP TABLE IF EXISTS {target}" in statements
        assert f"CREATE TABLE {target} (LIKE public.{table} INCLUDING DEFAULTS)" in statements
        assert f"ALTER TABLE {target} ADD PRIMARY KEY (id)" in statements


def test_build_statements_samples_both_eras_for_every_source_table():
    statements = erp.build_statements( 10 )
    for table in erp.SOURCE_TABLES:
        for label in ( "normalized-era", "current-era" ):
            assert any( s.startswith( f"INSERT INTO {erp.PROBE_SCHEMA}.{table} " )
                        and s.endswith( f"-- {label}" ) for s in statements )


def test_build_statements_adds_every_shadow_column_at_the_right_dimension():
    statements = erp.build_statements( 10 )
    for table in erp.SOURCE_TABLES:
        for column in erp._shadow_columns( table ):
            assert ( f"ALTER TABLE {erp.PROBE_SCHEMA}.{table} ADD COLUMN IF NOT EXISTS "
                     f"{column} vector({erp.EMBEDDING_DIM})" ) in statements


@pytest.mark.parametrize( "rows, per_era", [ ( 500, 250 ), ( 10, 5 ), ( 3, 1 ), ( 1, 1 ), ( 0, 1 ) ] )
def test_row_budget_is_split_between_the_eras_and_never_reaches_zero( rows, per_era ):
    """
    `max( 1, rows // 2 )` — a request small enough to floor to zero must still copy a
    row, or `create --rows=1` would build an empty clone and report success.
    """
    inserts = [ s for s in erp.build_statements( rows ) if s.startswith( "INSERT" ) ]
    assert inserts
    for statement in inserts:
        assert f"LIMIT {per_era}" in statement


def test_no_statement_writes_a_live_table():
    """
    The script's safety claim, asserted rather than reviewed: whatever a statement
    MODIFIES must live in the probe schema. `public.` is allowed, but only in a read
    position — after `FROM` in the sampling SELECTs, and inside
    `CREATE TABLE ... (LIKE public.x)`, which copies a definition and writes nothing
    to the source.

    ⚠️ THIS ASSERTION WAS WRONG ON ITS FIRST WRITING, and the script was right: it
    demanded the word SELECT before any `public.`, which convicts the LIKE clause.
    A safety test that fails on safe code gets relaxed by the next person in a hurry,
    so it is stated as the property that actually matters instead.
    """
    WRITE_VERBS = ( "INSERT INTO", "UPDATE", "DELETE FROM", "TRUNCATE",
                    "ALTER TABLE", "DROP TABLE", "CREATE TABLE" )
    checked = 0
    for statement in erp.build_statements( 500 ) + erp.drop_statements():
        for verb in WRITE_VERBS:
            if not statement.startswith( verb ): continue
            rest = statement[ len( verb ): ].strip()
            for optional in ( "IF NOT EXISTS ", "IF EXISTS " ):     # DROP TABLE IF EXISTS x
                if rest.startswith( optional ): rest = rest[ len( optional ): ]
            target = rest.split()[ 0 ]
            assert target.startswith( f"{erp.PROBE_SCHEMA}." ), (
                f"{verb} targets {target}, outside the probe schema: {statement}" )
            checked += 1
    # A guard that silently checked nothing would pass just as loudly.
    assert checked >= len( erp.SOURCE_TABLES ) * 3


def test_the_only_live_tables_named_are_the_declared_source_tables():
    """
    Complements the rule above: an unexpected `public.<table>` is caught even though it
    would sit in a legal read position.
    """
    named = set()
    for statement in erp.build_statements( 500 ):
        named.update( re.findall( r"public\.(\w+)", statement ) )
    assert named == set( erp.SOURCE_TABLES )


def test_drop_statements_removes_the_whole_schema_in_one_statement():
    assert erp.drop_statements() == [ f"DROP SCHEMA IF EXISTS {erp.PROBE_SCHEMA} CASCADE" ]


# ── _execute ─────────────────────────────────────────────────────────────────

def test_execute_previews_every_statement_and_touches_nothing_without_apply( monkeypatch, capsys ):
    session = _install_db( monkeypatch, _FakeSession() )
    assert erp._execute( [ "SELECT 1", "SELECT 2" ], apply=False ) == 0
    out = capsys.readouterr().out
    assert "  SELECT 1" in out and "  SELECT 2" in out
    assert "[DRY-RUN] nothing executed" in out
    assert session.executed == [ ]        # the whole point of the dry run


def test_execute_runs_and_commits_every_statement_with_apply( monkeypatch, capsys ):
    session = _install_db( monkeypatch, _FakeSession() )
    assert erp._execute( [ "SELECT 1", "SELECT 2" ], apply=True ) == 0
    assert [ sql for sql, _p in session.executed ] == [ "SELECT 1", "SELECT 2" ]
    assert session.committed is True
    assert "applied." in capsys.readouterr().out


# ── _status ──────────────────────────────────────────────────────────────────

def test_status_says_so_when_the_probe_schema_does_not_exist( monkeypatch, capsys ):
    session = _install_db( monkeypatch, _FakeSession( scalars=[ 0 ] ) )
    assert erp._status() == 0
    assert f"schema {erp.PROBE_SCHEMA} does not exist" in capsys.readouterr().out
    assert len( session.executed ) == 1        # stopped before counting any table


def test_status_counts_every_source_table_when_the_schema_exists( monkeypatch, capsys ):
    _install_db( monkeypatch, _FakeSession( scalars=[ 1, 12, 34 ] ) )
    assert erp._status() == 0
    out = capsys.readouterr().out
    assert "input_and_output" in out and "12" in out
    assert "prediction_decisions" in out and "34" in out


# ── main ─────────────────────────────────────────────────────────────────────

def _argv( monkeypatch, *args ):
    monkeypatch.setattr( sys, "argv", [ "embedding_regen_probe.py", *args ] )


def test_main_defaults_to_status_when_no_command_is_given( monkeypatch, capsys ):
    _argv( monkeypatch )
    _install_db( monkeypatch, _FakeSession( scalars=[ 0 ] ) )
    assert erp.main() == 0
    assert "does not exist" in capsys.readouterr().out


def test_main_defaults_to_status_when_the_first_token_is_a_flag( monkeypatch, capsys ):
    """`--apply` alone must not be read as a command."""
    _argv( monkeypatch, "--apply" )
    _install_db( monkeypatch, _FakeSession( scalars=[ 0 ] ) )
    assert erp.main() == 0
    assert "does not exist" in capsys.readouterr().out


def test_main_create_previews_without_apply_and_reports_the_row_budget( monkeypatch, capsys ):
    _argv( monkeypatch, "create", "--rows=40" )
    session = _install_db( monkeypatch, _FakeSession() )
    assert erp.main() == 0
    out = capsys.readouterr().out
    assert "CREATE probe clone (40 stale rows per table):" in out
    assert "LIMIT 20" in out
    assert session.executed == [ ]


def test_main_create_uses_the_default_budget_when_rows_is_not_given( monkeypatch, capsys ):
    _argv( monkeypatch, "create" )
    _install_db( monkeypatch, _FakeSession() )
    assert erp.main() == 0
    assert "CREATE probe clone (500 stale rows per table):" in capsys.readouterr().out


def test_main_create_executes_when_apply_is_passed( monkeypatch, capsys ):
    _argv( monkeypatch, "create", "--rows=4", "--apply" )
    session = _install_db( monkeypatch, _FakeSession() )
    assert erp.main() == 0
    assert session.committed is True
    assert any( "CREATE SCHEMA" in sql for sql, _p in session.executed )
    assert "applied." in capsys.readouterr().out


def test_main_drop_previews_the_teardown( monkeypatch, capsys ):
    _argv( monkeypatch, "drop" )
    session = _install_db( monkeypatch, _FakeSession() )
    assert erp.main() == 0
    out = capsys.readouterr().out
    assert "DROP probe schema:" in out
    assert f"DROP SCHEMA IF EXISTS {erp.PROBE_SCHEMA} CASCADE" in out
    assert session.executed == [ ]


def test_main_rejects_an_unknown_command_with_a_non_zero_code( monkeypatch, capsys ):
    _argv( monkeypatch, "obliterate" )
    assert erp.main() == 1
    assert "unknown command 'obliterate'; valid: status / drop / create" in capsys.readouterr().out


# ── the __main__ guard ───────────────────────────────────────────────────────

def test_running_the_script_exits_with_mains_return_code( monkeypatch, capsys ):
    """
    `runpy` re-executes the file, so the module-level `get_db` import is real again —
    the unknown-command path is used because it returns before reaching a database.
    """
    _argv( monkeypatch, "obliterate" )
    with pytest.raises( SystemExit ) as exc:
        runpy.run_path( SCRIPT_PATH, run_name="__main__" )
    assert exc.value.code == 1
    assert "unknown command" in capsys.readouterr().out


def test_running_the_script_without_lupin_root_refuses_to_guess( monkeypatch ):
    """The bootstrap contract: no LUPIN_ROOT is a loud RuntimeError, never a guess."""
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( RuntimeError, match="LUPIN_ROOT not set" ):
        runpy.run_path( SCRIPT_PATH, run_name="__main__" )
