"""
Hermetic model/migration drift detector — Half 1 of the drift-detector build.

Plan: src/rnd/v0.1.9/2026.07.19-model-migration-drift-detector-plan.md (§3 Half 1).

THE DEFECT THIS GUARDS
----------------------
A ``mapped_column`` can land in an ORM model before the migration that creates
it. On ``:7999`` uvicorn runs with ``--reload``, so the model edit IS the deploy:
the ORM immediately SELECTs a column the database lacks and every read of that
table 500s. Measured incident 2026-07-19: ``task_items.park_reason_captured_at``,
12 × HTTP 500 on ``/api/tasks`` over 2m28s.

WHAT THIS FILE MEASURES
-----------------------
OPERATIONS, not text. Every file under ``src/migrations/versions/`` is AST-parsed
and the *structural* column-creating operations are collected:

  * ``op.add_column( <table>, sa.Column( <name>, ... ) )``
  * ``op.create_table( <table>, sa.Column( <name>, ... ), ... )``
  * ``op.execute( <sql> )`` — the raw-DDL ``CREATE TABLE`` / ``ALTER TABLE ...
    ADD COLUMN`` statements are parsed out of the SQL string.

A grep for the column name would pass on a docstring mention, a comment, a
``downgrade()``, or an ``add_column`` against the WRONG table. Control B below
exists solely to prove this implementation has not degraded into that grep.

NO DATABASE CONNECTION. Pure static analysis; runs in the ``:7999`` unit tier.

THREE SUBSTRATE FACTS THIS PARSER MUST HANDLE (all verified at source)
---------------------------------------------------------------------
1. ``000000000000_true_baseline_schema.py`` creates its nine tables via
   ``op.execute( _SCHEMA_SQL )`` — a module-level string constant holding raw
   PostgreSQL DDL. A parser that reads only ``op.create_table`` sees NONE of
   those ~70 columns and reports the entire auth schema as drifted.
2. Several migrations pass module-level NAME constants rather than string
   literals — e.g. ``op.add_column( TABLE_NAME, sa.Column( COLUMN_NAME, ... ) )``
   in ``d47487369407``, which is the migration for the incident column itself.
   Module-scope ``NAME = "literal"`` bindings are therefore resolved statically.
3. ``d0e1f2a3b4c5_add_pgvector_vector_store_tables.py`` creates its eight tables
   by calling ``table.create( bind )`` on ``Base.metadata`` tables driven from
   ``VECTOR_STORE_MODELS``. There is no DDL for a parser to read — the migration
   simply *is* whatever the models say. Those tables are therefore structurally
   invisible to this oracle and are scoped out; see ``_metadata_driven_tables``.

NAMED LIMITS (Half 2's ``compare_metadata()`` is what covers these)
-------------------------------------------------------------------
* Literal / module-constant call arguments only. A column added inside a loop,
  through a helper function, or under a computed table name is invisible here.
  ``_collect_migration_columns`` FAILS LOUD on any op whose table or column name
  it cannot resolve rather than silently dropping it — an unresolvable op is a
  hole in the oracle, not a pass.
* Ordering is not modeled. A column added by one revision and dropped by a later
  one still counts as present.
* The eight metadata-driven vector-store tables (fact 3) are outside this
  oracle's reach entirely.
"""

import ast
import glob
import os
import re
import shutil

import pytest

import cosa.utils.util as cu

# Both model modules are imported EXPLICITLY. `Base.registry` is populated as a
# side effect of import, so relying on a transitive import chain would make the
# set of checked tables depend on import order — a detector that silently shrinks.
from cosa.rest.postgres_models import Base
from cosa.rest.db.vector_store_models import VECTOR_STORE_MODELS


MIGRATIONS_DIR = os.path.join( cu.get_project_root(), "src", "migrations", "versions" )

# The migration that adds `task_items.park_reason_captured_at` — removed from a
# scratch copy of the versions tree to reconstruct the PRIMARY control state.
_PRIMARY_CONTROL_MIGRATION = "d47487369407_add_task_park_reason_captured_at.py"
_PRIMARY_CONTROL_TABLE     = "task_items"
_PRIMARY_CONTROL_COLUMN    = "park_reason_captured_at"

# Leading tokens in a CREATE TABLE body that introduce a constraint, not a column.
_CONSTRAINT_KEYWORDS = { "primary", "foreign", "unique", "check", "constraint", "exclude", "like" }


class UnresolvableMigrationOp( Exception ):
    """A column-creating op whose table or column name could not be resolved statically.

    Raised rather than skipped: an op this parser cannot read is a blind spot in
    the oracle, and a detector that quietly ignores what it cannot parse is
    indistinguishable from one that cannot fire.
    """


def _module_string_constants( tree ):
    """
    Map module-scope ``NAME = "literal"`` bindings to their string values.

    Requires:
        - tree is a parsed ast.Module

    Ensures:
        - returns a dict of name -> str for module-level assignments whose value
          is a string constant (plain and annotated assignments alike)
        - non-string and non-module-scope bindings are omitted
    """
    constants = {}

    for node in tree.body:

        if isinstance( node, ast.Assign ):
            targets = node.targets
        elif isinstance( node, ast.AnnAssign ):
            targets = [ node.target ]
        else:
            continue

        value = node.value
        if not ( isinstance( value, ast.Constant ) and isinstance( value.value, str ) ): continue

        for target in targets:
            if isinstance( target, ast.Name ): constants[ target.id ] = value.value

    return constants


def _resolve_string( node, constants ):
    """
    Resolve an AST node to a string, statically.

    Requires:
        - node is an ast.expr; constants maps names to string values

    Ensures:
        - returns the string for a literal or a known module-level constant
        - returns None for anything else (f-strings, calls, subscripts, ...)
    """
    if isinstance( node, ast.Constant ) and isinstance( node.value, str ): return node.value
    if isinstance( node, ast.Name ): return constants.get( node.id )

    return None


def _split_top_level( body ):
    """
    Split a CREATE TABLE body on commas that are not nested inside parentheses.

    Requires:
        - body is the text between the outermost parentheses of a CREATE TABLE

    Ensures:
        - returns the top-level comma-separated fragments
        - commas inside VARCHAR( 255 ) / DEFAULT foo( a, b ) do not split
    """
    parts, depth, current = [], 0, []

    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1

        if char == "," and depth == 0:
            parts.append( "".join( current ) )
            current = []
        else:
            current.append( char )

    if current: parts.append( "".join( current ) )

    return parts


def _parse_raw_ddl( sql ):
    """
    Extract ``{table: {columns}}`` from raw PostgreSQL DDL.

    Requires:
        - sql is the text passed to op.execute()

    Ensures:
        - CREATE TABLE [IF NOT EXISTS] bodies yield their column names
        - ALTER TABLE ... ADD COLUMN [IF NOT EXISTS] yields the added column
        - table-level constraint clauses are not mistaken for columns
        - table and column names are lower-cased; SQL line comments are stripped
    """
    found = {}

    for match in re.finditer( r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_]\w*)\s*\(", sql, re.I ):

        table = match.group( 1 ).lower()

        # Walk to the matching close-paren so nested type/DEFAULT parens are spanned.
        depth, end = 0, len( sql ) - 1
        for index in range( match.end() - 1, len( sql ) ):
            if sql[ index ] == "(":
                depth += 1
            elif sql[ index ] == ")":
                depth -= 1
                if depth == 0:
                    end = index
                    break

        body    = re.sub( r"--[^\n]*", "", sql[ match.end() : end ] )
        columns = set()

        for fragment in _split_top_level( body ):
            tokens = fragment.strip().split()
            if not tokens: continue
            if tokens[ 0 ].lower() in _CONSTRAINT_KEYWORDS: continue
            columns.add( tokens[ 0 ].strip( '"' ).lower() )

        found.setdefault( table, set() ).update( columns )

    for match in re.finditer(
        r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([a-zA-Z_]\w*)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_]\w*)",
        sql, re.I
    ):
        found.setdefault( match.group( 1 ).lower(), set() ).add( match.group( 2 ).lower() )

    return found


def _upgrade_calls( tree ):
    """
    Yield every ``op.<attr>( ... )`` Call inside a top-level ``upgrade()``.

    Requires:
        - tree is a parsed ast.Module for a migration revision

    Ensures:
        - only ops in upgrade() are yielded; downgrade() re-adds do not count as
          a column being provided by the migration chain
    """
    for node in tree.body:

        if not isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ): continue
        if node.name != "upgrade": continue

        for inner in ast.walk( node ):
            if not isinstance( inner, ast.Call ): continue
            func = inner.func
            if isinstance( func, ast.Attribute ) and isinstance( func.value, ast.Name ) and func.value.id == "op":
                yield inner, func.attr


def _collect_migration_columns( versions_dir ):
    """
    AST-collect the columns each migration's upgrade() creates.

    Requires:
        - versions_dir contains alembic revision modules

    Ensures:
        - returns {table: {column, ...}} lower-cased, from op.add_column,
          op.create_table, and raw DDL inside op.execute
        - raises UnresolvableMigrationOp if a table or column name in a
          column-creating op cannot be resolved statically
        - never imports or executes a migration module
    """
    tables = {}

    for path in sorted( glob.glob( os.path.join( versions_dir, "*.py" ) ) ):

        with open( path, encoding="utf-8" ) as handle: source = handle.read()

        tree      = ast.parse( source, filename=path )
        constants = _module_string_constants( tree )

        for call, attr in _upgrade_calls( tree ):

            if attr in ( "add_column", "create_table" ) and call.args:

                table = _resolve_string( call.args[ 0 ], constants )
                if table is None:
                    raise UnresolvableMigrationOp(
                        f"{os.path.basename( path )}:{call.lineno} — op.{attr} table name is not a "
                        f"literal or module-level constant; this oracle cannot see it"
                    )

                columns = tables.setdefault( table.lower(), set() )

                for argument in call.args[ 1: ]:

                    is_column_ctor = (
                        isinstance( argument, ast.Call )
                        and isinstance( argument.func, ast.Attribute )
                        and argument.func.attr == "Column"
                        and argument.args
                    )
                    if not is_column_ctor: continue

                    name = _resolve_string( argument.args[ 0 ], constants )
                    if name is None:
                        raise UnresolvableMigrationOp(
                            f"{os.path.basename( path )}:{argument.lineno} — sa.Column name is not a "
                            f"literal or module-level constant; this oracle cannot see it"
                        )

                    columns.add( name.lower() )

            elif attr == "execute" and call.args:

                sql = _resolve_string( call.args[ 0 ], constants )
                # An unresolvable execute() arg is NOT fatal: most are computed
                # DROP/index statements that create no columns. Half 2 covers it.
                if sql is None: continue

                for table, columns in _parse_raw_ddl( sql ).items():
                    tables.setdefault( table, set() ).update( columns )

    return tables


def _metadata_driven_tables():
    """
    Tables whose migration creates them FROM the ORM metadata, not from DDL.

    Requires:
        - VECTOR_STORE_MODELS is the same list d0e1f2a3b4c5 imports

    Ensures:
        - returns the lower-cased table names this AST oracle is structurally
          blind to, derived from the migration's own source of truth (so a ninth
          vector-store model is excluded automatically — this is NOT a
          hand-maintained list, and NOT a baseline of known drift)
    """
    return { model.__tablename__.lower() for model in VECTOR_STORE_MODELS }


def _mapped_columns():
    """
    Every mapped class on Base and the columns it declares.

    Requires:
        - both model modules have been imported

    Ensures:
        - returns {tablename: {column, ...}}, lower-cased
    """
    return {
        mapper.class_.__tablename__.lower(): { column.name.lower() for column in mapper.class_.__table__.columns }
        for mapper in Base.registry.mappers
    }


def find_drift( mapped, migrated, skip_tables=frozenset() ):
    """
    Mapped columns that no migration operation creates.

    Requires:
        - mapped and migrated are {table: {column}} maps

    Ensures:
        - returns {table: {column, ...}} for every mapped column absent from the
          migration ops, excluding skip_tables
        - tables with no drift are omitted
    """
    drift = {}

    for table, columns in mapped.items():
        if table in skip_tables: continue
        missing = columns - migrated.get( table, set() )
        if missing: drift[ table ] = missing

    return drift


def _format_drift( drift ):
    """Render a drift map as a diagnosable failure message."""
    return "\n".join(
        f"  {table}: {', '.join( sorted( columns ) )}" for table, columns in sorted( drift.items() )
    )


# ─────────────────────────── the guard ───────────────────────────

def test_no_mapped_column_is_missing_from_the_migration_chain():
    """Every mapped column outside the metadata-driven tables is created by some migration op."""
    drift = find_drift( _mapped_columns(), _collect_migration_columns( MIGRATIONS_DIR ), _metadata_driven_tables() )

    assert not drift, (
        "ORM model columns have no migration that creates them. On :7999 the model edit IS "
        "the deploy, so these columns will 500 every read of their table:\n"
        + _format_drift( drift )
    )


def test_every_column_creating_op_in_the_chain_is_statically_resolvable():
    """No op.add_column / op.create_table in the real chain is invisible to this oracle."""
    _collect_migration_columns( MIGRATIONS_DIR )


def test_metadata_driven_tables_are_scoped_out_for_a_structural_reason():
    """The scoped-out set is exactly the vector-store models, derived from the migration's own list."""
    skipped = _metadata_driven_tables()

    assert skipped, "the metadata-driven scope-out must be non-empty or the reasoning has drifted"

    migrated = _collect_migration_columns( MIGRATIONS_DIR )

    # The point of the scope-out: these tables have NO parseable DDL anywhere in
    # the chain. If one ever gains real DDL, this fails and the scope-out is revisited.
    for table in skipped:
        assert table not in migrated, (
            f"{table} now has parseable migration DDL — it is no longer metadata-driven "
            f"and must be removed from the scope-out"
        )


# ─────────────────────────── controls ───────────────────────────
#
# A detector that has never gone red is indistinguishable from one that cannot.

def _write_migration( directory, name, body ):
    """Write a synthetic revision module into a scratch versions directory."""
    with open( os.path.join( directory, name ), "w", encoding="utf-8" ) as handle: handle.write( body )


def test_primary_control_real_park_reason_captured_at_drift_fires( tmp_path ):
    """
    PRIMARY — the drift that actually produced 12 live 500s on 2026-07-19.

    Reconstructed from REAL artifacts on both sides: the real current mapped
    columns (which declare park_reason_captured_at) against the real versions
    tree with the one migration that adds it removed. That is precisely the
    on-disk state that existed while the model edit had landed and the migration
    had not.

    NOTE, stated rather than hidden: no single commit reproduces this. The model
    and its migration were committed ATOMICALLY in 61a9851d, so the drift never
    existed in committed history — it existed in the working tree, which is
    exactly the --reload hazard. Checking out a historical commit would show a
    healed tree and this control would go green for the wrong reason.
    """
    versions = tmp_path / "versions"
    versions.mkdir()

    for path in glob.glob( os.path.join( MIGRATIONS_DIR, "*.py" ) ):
        if os.path.basename( path ) == _PRIMARY_CONTROL_MIGRATION: continue
        shutil.copy( path, versions )

    assert not ( versions / _PRIMARY_CONTROL_MIGRATION ).exists()

    drift = find_drift( _mapped_columns(), _collect_migration_columns( str( versions ) ), _metadata_driven_tables() )

    assert drift.get( _PRIMARY_CONTROL_TABLE ) == { _PRIMARY_CONTROL_COLUMN }, (
        f"PRIMARY control did not reproduce the incident: expected exactly "
        f"{_PRIMARY_CONTROL_COLUMN} missing from {_PRIMARY_CONTROL_TABLE}, got {drift}"
    )


def test_control_a_mapped_column_with_no_migration_op_anywhere_fires( tmp_path ):
    """A — a mapped column that no migration mentions at all must be reported."""
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration( str( versions ), "0001_makes_widgets.py", '''
"""makes widgets"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.create_table( "widgets", sa.Column( "id", sa.Integer() ) )
''' )

    mapped = { "widgets": { "id", "invented_column" } }
    drift  = find_drift( mapped, _collect_migration_columns( str( versions ) ) )

    assert drift == { "widgets": { "invented_column" } }


def test_control_b_column_named_only_in_a_docstring_still_fires( tmp_path ):
    """
    B — NON-OPTIONAL. The column name appears in a docstring, a comment, a
    downgrade(), and an add_column against the WRONG table. A grep passes all
    four. An operation-measuring oracle must still report drift.
    """
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration( str( versions ), "0001_mentions_only.py", '''
"""Adds ghost_column to widgets.

This docstring names ghost_column but no upgrade op creates it.
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    # ghost_column is handled elsewhere
    op.create_table( "widgets", sa.Column( "id", sa.Integer() ) )
    op.add_column( "gadgets", sa.Column( "ghost_column", sa.Text() ) )

def downgrade() -> None:
    op.add_column( "widgets", sa.Column( "ghost_column", sa.Text() ) )
''' )

    mapped = { "widgets": { "id", "ghost_column" } }
    drift  = find_drift( mapped, _collect_migration_columns( str( versions ) ) )

    assert drift == { "widgets": { "ghost_column" } }, (
        "the oracle has degraded into a text search: ghost_column was matched from a "
        "docstring, a comment, a downgrade(), or the wrong table"
    )


# ─────────────────────── parser unit coverage ───────────────────────

def test_raw_ddl_create_table_columns_are_parsed():
    """Baseline-style DDL yields columns and not constraint clauses."""
    parsed = _parse_raw_ddl( """
        -- a comment naming not_a_column
        CREATE TABLE IF NOT EXISTS things (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            label VARCHAR(255) NOT NULL,
            owner_id UUID,
            PRIMARY KEY (id),
            CONSTRAINT fk_owner FOREIGN KEY (owner_id) REFERENCES users(id)
        );
    """ )

    assert parsed == { "things": { "id", "label", "owner_id" } }


def test_raw_ddl_tolerates_empty_fragments_from_a_trailing_comma():
    """A trailing comma yields an empty fragment, which is skipped rather than crashing."""
    assert _parse_raw_ddl( "CREATE TABLE things ( id UUID, label TEXT, );" ) == { "things": { "id", "label" } }


def test_raw_ddl_alter_table_add_column_is_parsed():
    """ALTER TABLE ... ADD COLUMN contributes to the table's column set."""
    assert _parse_raw_ddl( "ALTER TABLE IF EXISTS things ADD COLUMN IF NOT EXISTS extra TEXT;" ) == { "things": { "extra" } }


def test_raw_ddl_with_no_ddl_yields_nothing():
    """Non-DDL execute() payloads contribute nothing."""
    assert _parse_raw_ddl( "DROP INDEX IF EXISTS ix_things_label" ) == {}


def test_unbalanced_create_table_does_not_hang_or_crash():
    """A truncated CREATE TABLE degrades to a best-effort parse rather than looping."""
    assert "things" in _parse_raw_ddl( "CREATE TABLE things ( id UUID, label TEXT" )


def test_module_constants_resolve_for_plain_and_annotated_assignments():
    """Both `NAME = "x"` and `NAME: str = "x"` are resolvable; non-strings are not."""
    tree      = ast.parse( 'TABLE = "things"\nCOLUMN: str = "extra"\nCOUNT = 3\nOTHER, PAIR = "a", "b"\n' )
    constants = _module_string_constants( tree )

    assert constants == { "TABLE": "things", "COLUMN": "extra" }
    assert _resolve_string( ast.parse( "TABLE", mode="eval" ).body, constants ) == "things"
    assert _resolve_string( ast.parse( "UNKNOWN", mode="eval" ).body, constants ) is None
    assert _resolve_string( ast.parse( "f'{x}'", mode="eval" ).body, constants ) is None


def test_unresolvable_table_name_raises_rather_than_being_skipped( tmp_path ):
    """A table name this oracle cannot read is a blind spot, and must fail loud."""
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration( str( versions ), "0001_computed_table.py", '''
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column( "pre" + "fix", sa.Column( "c", sa.Text() ) )
''' )

    with pytest.raises( UnresolvableMigrationOp, match="table name" ):
        _collect_migration_columns( str( versions ) )


def test_unresolvable_column_name_raises_rather_than_being_skipped( tmp_path ):
    """Likewise for a column name that is not a literal or module constant."""
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration( str( versions ), "0001_computed_column.py", '''
from alembic import op
import sqlalchemy as sa

PREFIX = "col"

def upgrade() -> None:
    op.add_column( "things", sa.Column( PREFIX + "_x", sa.Text() ) )
''' )

    with pytest.raises( UnresolvableMigrationOp, match="sa.Column name" ):
        _collect_migration_columns( str( versions ) )


def test_unresolvable_execute_argument_is_tolerated( tmp_path ):
    """A computed execute() payload creates no columns and must not raise."""
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration( str( versions ), "0001_computed_execute.py", '''
from alembic import op

def upgrade() -> None:
    for table in ( "a", "b" ):
        op.execute( f"DROP TABLE IF EXISTS {table} CASCADE;" )
''' )

    assert _collect_migration_columns( str( versions ) ) == {}


def test_non_op_calls_and_argless_ops_are_ignored( tmp_path ):
    """Calls that are not op.* — and op.* calls with no arguments — contribute nothing."""
    versions = tmp_path / "versions"
    versions.mkdir()

    _write_migration( str( versions ), "0001_noise.py", '''
from alembic import op
import sqlalchemy as sa

def helper():
    op.add_column( "never_counted", sa.Column( "c", sa.Text() ) )

def upgrade() -> None:
    sa.Column( "not_an_op", sa.Text() )
    op.get_bind()
    op.create_table( "kept", sa.Column( "id", sa.Integer() ), sa.PrimaryKeyConstraint( "id" ) )

def downgrade() -> None:
    op.drop_table( "kept" )
''' )

    assert _collect_migration_columns( str( versions ) ) == { "kept": { "id" } }


def test_find_drift_reports_a_table_absent_from_migrations_entirely():
    """A mapped table with no migration at all reports all of its columns."""
    assert find_drift( { "orphan": { "a", "b" } }, {} ) == { "orphan": { "a", "b" } }
    assert find_drift( { "orphan": { "a" } }, {}, skip_tables={ "orphan" } ) == {}
    assert find_drift( { "t": { "a" } }, { "t": { "a" } } ) == {}


def test_format_drift_renders_every_table_and_column():
    """The failure message names model, table, and column — not just 'drift detected'."""
    rendered = _format_drift( { "t2": { "b" }, "t1": { "a", "c" } } )

    assert rendered == "  t1: a, c\n  t2: b"
