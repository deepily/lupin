"""
Unit tests for the question-vector backfill script, on in-memory SQLite fixtures.

No test touches a real database. The fixture tables carry the columns the script reads and writes,
with text in place of uuid, json and vector columns.
"""

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

SCRIPT = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts", "backfill_missing_question_vectors.py" )
spec   = importlib.util.spec_from_file_location( "backfill_missing_question_vectors", SCRIPT )
bf     = importlib.util.module_from_spec( spec )
sys.modules[ spec.name ] = bf   # a dataclass resolves its annotations through sys.modules
spec.loader.exec_module( bf )

GO    = { "expect_database": ":memory:", "expect_insert_ids": { "n1", "n2" } }   # the scenario's two asks without a row
DIM   = 768
MODEL = "test-model"
REV   = "abc123"


def good_vector( seed ):
    """A 768-wide vector whose norm sits inside the current model's band (about 20)."""
    value = 20.0 / ( DIM ** 0.5 )
    return [ round( value + seed * 1e-4, 6 ) ] * DIM


def side_file( tmp_path, ids, count=None, header_extra=None, mutate=None ):
    """Write a side file for the ids and return its path."""
    header  = { "kind": "header", "model": MODEL, "revision": REV, "count": len( ids ) if count is None else count }
    header.update( header_extra or { } )
    records = [ { "id": row_id, "model": MODEL, "revision": REV, "vector": good_vector( index ) } for index, row_id in enumerate( ids ) ]
    if mutate: mutate( header, records )
    path = tmp_path / "side.jsonl"
    path.write_text( "\n".join( [ json.dumps( header ) ] + [ json.dumps( record ) for record in records ] ) + "\n", encoding="utf-8" )
    return str( path )


@pytest.fixture
def engine():
    """An in-memory database with the four tables the script touches."""
    eng = sa.create_engine( "sqlite://", poolclass=sa.pool.StaticPool )
    with eng.begin() as conn:
        conn.execute( sa.text( "CREATE TABLE notifications ( id TEXT PRIMARY KEY, message TEXT, recipient_id TEXT, responded_at TEXT, response_value TEXT )" ) )
        conn.execute( sa.text( "CREATE TABLE prediction_log ( notification_id TEXT, category TEXT, response_type TEXT, actual_value TEXT, encoder_version TEXT )" ) )
        conn.execute( sa.text( "CREATE TABLE prediction_decisions ( id TEXT PRIMARY KEY, question TEXT, category TEXT, decision_value TEXT, ratification_state TEXT, "
                               "data_origin TEXT, response_type TEXT, question_embedding TEXT, created_at TEXT, owner_user_id TEXT, answer_source TEXT )" ) )
    return eng


def add_ask( eng, row_id, message="Proceed?", recipient="user-1", source="ui", actual=None, response_type="yes_no", has_row=False, stored_question=None ):
    """Insert one notification, its log row, and optionally an existing case row."""
    actual = actual if actual is not None else { "value": "yes" }
    with eng.begin() as conn:
        conn.execute( sa.text( "INSERT INTO notifications VALUES ( :i, :m, :r, :t, :v )" ),
                      { "i": row_id, "m": message, "r": recipient, "t": "2026-09-01T10:00:00+00:00",
                        "v": json.dumps( { "source": source } ) if source else json.dumps( { } ) } )
        conn.execute( sa.text( "INSERT INTO prediction_log VALUES ( :i, 'cat', :rt, :a, NULL )" ),
                      { "i": row_id, "rt": response_type, "a": json.dumps( actual ) } )
        if has_row:
            conn.execute( sa.text( "INSERT INTO prediction_decisions ( id, question, question_embedding, answer_source ) VALUES ( :i, :q, 'old', 'human' )" ),
                          { "i": row_id, "q": stored_question if stored_question is not None else message.strip() } )


def table_dump( eng ):
    """Return every row of the three writable tables, for before-and-after comparison."""
    with eng.connect() as conn:
        return [ [ tuple( row ) for row in conn.execute( sa.text( f"SELECT * FROM {name} ORDER BY 1" ) ) ]
                 for name in ( "notifications", "prediction_log", "prediction_decisions" ) ]


def scenario( eng ):
    """Two asks to insert (one ui, one without a source) and one existing row to update."""
    add_ask( eng, "n1", message="  First?  " )
    add_ask( eng, "n2", source=None, response_type="multiple_choice", actual={ "answers": { "Q": "A" } } )
    add_ask( eng, "n3", has_row=True, stored_question="drifted" )
    return [ "n1", "n2", "n3" ]


# ------------------------------------------------------------------ side file

def test_side_file_reads_a_valid_file( tmp_path ):
    header, records = bf.read_side_file( side_file( tmp_path, [ "a", "b" ] ) )
    assert header[ "model" ] == MODEL and [ record[ "id" ] for record in records ] == [ "a", "b" ]


@pytest.mark.parametrize( "mutate,fragment", [
    ( lambda h, r: h.update( kind="other" ),                         "not a header" ),
    ( lambda h, r: h.pop( "revision" ),                              "lacks model or revision" ),
    ( lambda h, r: r[ 1 ].update( id="a" ),                          "duplicate id" ),
    ( lambda h, r: r[ 1 ].update( revision="zzz" ),                  "different model or revision" ),
    ( lambda h, r: r[ 1 ].update( model="other" ),                   "different model or revision" ),
    ( lambda h, r: r[ 1 ].update( vector=[ 1.0 ] * 10 ),             "wrong dimension" ),
    ( lambda h, r: r[ 1 ].update( vector=[ 0.01 ] * DIM ),           "norm" ),
] )
def test_side_file_refuses_each_defect( tmp_path, mutate, fragment ):
    with pytest.raises( bf.RefusedPlan, match=fragment ):
        bf.read_side_file( side_file( tmp_path, [ "a", "b" ], mutate=mutate ) )


def test_side_file_refuses_a_count_mismatch( tmp_path ):
    with pytest.raises( bf.RefusedPlan, match="header count 5 but 2 records" ):
        bf.read_side_file( side_file( tmp_path, [ "a", "b" ], count=5 ) )


def test_side_file_refuses_an_empty_file( tmp_path ):
    path = tmp_path / "empty.jsonl"
    path.write_text( "\n", encoding="utf-8" )
    with pytest.raises( bf.RefusedPlan, match="empty" ):
        bf.read_side_file( str( path ) )


# ------------------------------------------------------------------ pure helpers

def test_encoder_version_joins_model_and_revision():
    assert bf.encoder_version_of( { "model": "m", "revision": "r" } ) == "m@r"


@pytest.mark.parametrize( "value,expected", [
    ( { "source": "ui" },          "human" ),
    ( json.dumps( { "source": "ui" } ), "human" ),
    ( { "source": "timeout_default" }, "unknown" ),
    ( { },                         "unknown" ),
    ( None,                        "unknown" ),
] )
def test_answer_source_is_human_only_for_ui( value, expected ):
    assert bf.answer_source_of( value ) == expected


def test_decision_value_takes_the_value_or_sorted_json():
    assert bf.decision_value_of( { "value": "yes" } ) == "yes"
    assert bf.decision_value_of( json.dumps( { "value": "no" } ) ) == "no"
    assert bf.decision_value_of( { "b": 1, "a": 2 } ) == '{"a": 2, "b": 1}'


def test_vector_text_is_pgvector_form():
    assert bf.vector_text( [ 1, 0.5 ] ) == "[1.0,0.5]"


def test_responded_text_handles_text_and_datetime():
    assert bf._responded_text( "2026-01-01T00:00:00+00:00" ) == "2026-01-01T00:00:00+00:00"
    aware = datetime( 2026, 1, 1, 5, 0, tzinfo=timezone.utc )
    assert bf._responded_text( aware ) == "2026-01-01T05:00:00+00:00"


def test_plan_ids_lists_inserts_then_updates():
    plan = bf.Plan( encoder_version="v", inserts=[ { "id": "i" } ], updates=[ { "id": "u" } ] )
    assert plan.ids() == [ "i", "u" ]


# ------------------------------------------------------------------ the plan

def test_plan_splits_inserts_and_updates_and_derives_fields( tmp_path, engine ):
    ids            = scenario( engine )
    header, records = bf.read_side_file( side_file( tmp_path, ids ) )
    with engine.connect() as conn:
        plan = bf.build_plan( conn, header, records )
    assert [ row[ "id" ] for row in plan.inserts ] == [ "n1", "n2" ]
    assert [ row[ "id" ] for row in plan.updates ] == [ "n3" ]
    first, second = plan.inserts
    assert first[ "question" ] == "First?" and first[ "owner_user_id" ] == "user-1" and first[ "answer_source" ] == "human"
    assert first[ "decision_value" ] == "yes" and first[ "ratification_state" ] == "not_required" and first[ "data_origin" ] == "organic"
    assert second[ "answer_source" ] == "unknown" and second[ "decision_value" ] == '{"answers": {"Q": "A"}}'
    assert second[ "response_type" ] == "multiple_choice" and first[ "created_at" ] == "2026-09-01T10:00:00+00:00"
    assert plan.question_drift == 1 and plan.log_rows == 3 and plan.encoder_version == f"{MODEL}@{REV}"


@pytest.mark.parametrize( "build,fragment", [
    ( lambda eng: add_ask( eng, "x", message="   " ),   "empty message" ),
    ( lambda eng: add_ask( eng, "x", recipient="" ),    "no recipient" ),
] )
def test_plan_refuses_an_unusable_ask( tmp_path, engine, build, fragment ):
    build( engine )
    header, records = bf.read_side_file( side_file( tmp_path, [ "x" ] ) )
    with engine.connect() as conn, pytest.raises( bf.RefusedPlan, match=fragment ):
        bf.build_plan( conn, header, records )


def test_plan_refuses_an_id_with_no_notification( tmp_path, engine ):
    header, records = bf.read_side_file( side_file( tmp_path, [ "ghost" ] ) )
    with engine.connect() as conn, pytest.raises( bf.RefusedPlan, match="1 ids have no notification and log row, first ghost" ):
        bf.build_plan( conn, header, records )


def test_counts_report_names_every_number( tmp_path, engine ):
    ids            = scenario( engine )
    header, records = bf.read_side_file( side_file( tmp_path, ids ) )
    with engine.connect() as conn:
        report = bf.format_counts( bf.build_plan( conn, header, records ) )
    assert "rows to insert     : 2" in report and '"human": 1' in report and '"unknown": 1' in report
    assert "vectors to replace : 1" in report and "log rows to stamp  : 3" in report and "differ from the stripped message : 1" in report


# ------------------------------------------------------------------ dry run and apply

def test_dry_run_writes_nothing_and_prints_counts( tmp_path, engine ):
    ids    = scenario( engine )
    before = table_dump( engine )
    out    = []
    code   = bf.run( engine, side_file( tmp_path, ids ), False, None, None, None, out=out.append )
    assert code == 0 and table_dump( engine ) == before
    assert any( "dry run: nothing written" in line for line in out ) and any( "rows to insert     : 2" in line for line in out )


def test_apply_inserts_replaces_stamps_and_reads_back( tmp_path, engine ):
    ids  = scenario( engine )
    out  = []
    code = bf.run( engine, side_file( tmp_path, ids ), True, 2, 1, 3, out=out.append, **GO )
    assert code == 0 and "applied and read back" in out[ -1 ]
    with engine.connect() as conn:
        rows    = { row[ 0 ]: row for row in conn.execute( sa.text( "SELECT id, question, question_embedding, owner_user_id, answer_source FROM prediction_decisions" ) ) }
        stamped = conn.execute( sa.text( "SELECT count(*) FROM prediction_log WHERE encoder_version = :v" ), { "v": f"{MODEL}@{REV}" } ).scalar()
    assert set( rows ) == { "n1", "n2", "n3" } and stamped == 3
    assert rows[ "n1" ][ 1 ] == "First?" and rows[ "n1" ][ 3 ] == "user-1" and rows[ "n1" ][ 4 ] == "human" and rows[ "n2" ][ 4 ] == "unknown"
    assert rows[ "n3" ][ 2 ].startswith( "[" ) and rows[ "n3" ][ 2 ] != "old" and rows[ "n3" ][ 4 ] == "human"


@pytest.mark.parametrize( "expected,fragment", [
    ( ( 3, 1, 3 ), "plan inserts 2, expected 3" ),
    ( ( 2, 2, 3 ), "plan updates 1, expected 2" ),
    ( ( 2, 1, 4 ), "plan stamps 3 log rows, expected 4" ),
] )
def test_apply_rolls_back_on_a_wrong_expected_count( tmp_path, engine, expected, fragment ):
    ids    = scenario( engine )
    before = table_dump( engine )
    out    = []
    code   = bf.run( engine, side_file( tmp_path, ids ), True, *expected, out=out.append, **GO )
    assert code == 3 and fragment in out[ -1 ] and table_dump( engine ) == before


def test_apply_refuses_when_an_insert_id_already_has_a_row( tmp_path, engine, monkeypatch ):
    ids    = scenario( engine )
    before = table_dump( engine )
    real   = bf.fetch_existing
    calls  = []
    def stale( conn, wanted ):
        calls.append( 1 )
        return { } if len( calls ) == 1 else real( conn, wanted )   # the plan is built on a stale read: it believes n3 has no row
    monkeypatch.setattr( bf, "fetch_existing", stale )
    out    = []
    code   = bf.run( engine, side_file( tmp_path, ids ), True, 3, 0, 3, out=out.append, **{ **GO, "expect_insert_ids": { "n1", "n2", "n3" } } )
    assert code == 3 and "1 of the 3 insert ids already have a row, first n3" in out[ -1 ] and table_dump( engine ) == before


def test_apply_refuses_when_an_update_id_has_no_row( tmp_path, engine, monkeypatch ):
    ids    = scenario( engine )
    before = table_dump( engine )
    real   = bf.fetch_existing
    calls  = []
    def stale( conn, wanted ):
        calls.append( 1 )
        return { "n1": "x", "n3": "y" } if len( calls ) == 1 else real( conn, wanted )   # the plan believes n1 has a row
    monkeypatch.setattr( bf, "fetch_existing", stale )
    out    = []
    code   = bf.run( engine, side_file( tmp_path, ids ), True, 1, 2, 3, out=out.append, **{ **GO, "expect_insert_ids": { "n2" } } )
    assert code == 3 and "1 of the 2 update ids have no row, first n1" in out[ -1 ] and table_dump( engine ) == before


def test_apply_rolls_back_when_the_read_back_disagrees( tmp_path, engine, monkeypatch ):
    ids    = scenario( engine )
    before = table_dump( engine )
    real   = bf.read_back
    def wrong( conn, plan, expect_rows ): return real( conn, plan, expect_rows + 1 )
    monkeypatch.setattr( bf, "read_back", wrong )
    out    = []
    code   = bf.run( engine, side_file( tmp_path, ids ), True, 2, 1, 3, out=out.append, **GO )
    assert code == 3 and "read-back" in out[ -1 ] and table_dump( engine ) == before


def test_run_refuses_a_bad_side_file_before_opening_the_database( tmp_path ):
    class Boom:
        def connect( self ): raise AssertionError( "database opened" )
    out = []
    assert bf.run( Boom(), side_file( tmp_path, [ "a" ], count=9 ), True, 1, 0, 1, out=out.append, **GO ) == 2
    assert out[ -1 ].startswith( "REFUSED" )


def test_run_reports_a_refused_plan_from_the_database( tmp_path, engine ):
    out = []
    assert bf.run( engine, side_file( tmp_path, [ "ghost" ] ), False, None, None, None, out=out.append ) == 2
    assert "no notification and log row" in out[ -1 ]


def test_postgres_dry_run_sets_the_transaction_read_only( tmp_path ):
    statements = []
    class FakeDialect: name = "postgresql"
    class FakeConn:
        dialect = FakeDialect()
        def __enter__( self ): return self
        def __exit__( self, *args ): return False
        def begin( self ):
            class T:
                def rollback( self ): statements.append( "rollback" )
            return T()
        def execute( self, statement, *args ):
            statements.append( str( statement ) )
            return type( "R", ( ), { "scalar": lambda self: "scratch" } )()
    class FakeEngine:
        def connect( self ): return FakeConn()
    original = bf.build_plan
    bf.build_plan = lambda conn, header, records: bf.Plan( encoder_version="v" )
    try:
        assert bf.run( FakeEngine(), side_file( tmp_path, [ "a" ] ), False, None, None, None, out=lambda line: None ) == 0
    finally:
        bf.build_plan = original
    assert statements[ :2 ] == [ "SELECT current_database()", "SET TRANSACTION READ ONLY" ] and statements[ -1 ] == "rollback"


def test_vector_sql_casts_only_on_postgres():
    class C:
        def __init__( self, name ): self.dialect = type( "D", ( ), { "name": name } )()
    assert bf._vector_sql( C( "postgresql" ), "vector" ) == "CAST( :vector AS vector )"
    assert bf._vector_sql( C( "sqlite" ), "vector" ) == ":vector"


# ------------------------------------------------------------------ command line

def test_main_needs_every_expect_count_to_apply( tmp_path, capsys ):
    with pytest.raises( SystemExit ) as raised:
        bf.main( [ "--side-file", "x", "--database-url", "sqlite://", "--apply", "--expect-insert", "1" ] )
    assert raised.value.code == 2 and "need --expect-insert" in capsys.readouterr().err


def test_main_dry_run_uses_the_url_and_returns_the_run_code( tmp_path, monkeypatch ):
    seen = { }
    monkeypatch.setattr( bf.sa, "create_engine", lambda url: seen.setdefault( "url", url ) or "engine" )
    monkeypatch.setattr( bf, "run", lambda engine, path, apply, ei, eu, el, **kw: seen.update( apply=apply, path=path ) or 0 )
    assert bf.main( [ "--side-file", "f.jsonl", "--database-url", "sqlite://" ] ) == 0
    assert seen == { "url": "sqlite://", "apply": False, "path": "f.jsonl" }


def test_wrong_interpreter_path_exits_4_before_touching_anything( tmp_path ):
    import subprocess
    result = subprocess.run( [ sys.executable, "-I", SCRIPT, "--side-file", "x", "--database-url", "sqlite://" ],
                             capture_output=True, text=True, env={ } )
    assert result.returncode == 4 and "FATAL: import failed" in result.stderr


def test_apply_touches_only_the_asks_in_the_side_file_and_gives_each_its_own_vector( tmp_path, engine ):
    ids = scenario( engine )
    add_ask( engine, "bystander", has_row=True )   # has a case row and a log row, and is not in the side file
    with engine.connect() as conn:
        bystander_before = [ tuple( row ) for row in conn.execute( sa.text( "SELECT * FROM prediction_decisions WHERE id = 'bystander'" ) ) ]
    path = side_file( tmp_path, ids )
    assert bf.run( engine, path, True, 2, 1, 3, out=lambda line: None, **GO ) == 0
    _, records = bf.read_side_file( path )
    with engine.connect() as conn:
        stored    = { row[ 0 ]: row[ 1 ] for row in conn.execute( sa.text( "SELECT id, question_embedding FROM prediction_decisions" ) ) }
        bystander = [ tuple( row ) for row in conn.execute( sa.text( "SELECT * FROM prediction_decisions WHERE id = 'bystander'" ) ) ]
        versions  = { row[ 0 ]: row[ 1 ] for row in conn.execute( sa.text( "SELECT notification_id, encoder_version FROM prediction_log" ) ) }
    for record in records:
        assert stored[ record[ "id" ] ] == bf.vector_text( record[ "vector" ] )
    assert len( { stored[ record[ "id" ] ] for record in records } ) == 3   # three different vectors, not one copied to all
    assert bystander == bystander_before and stored[ "bystander" ] == "old"
    assert versions[ "bystander" ] is None and all( versions[ row_id ] == f"{MODEL}@{REV}" for row_id in ids )


def test_apply_refuses_the_wrong_database_before_any_read_of_the_plan( tmp_path, engine ):
    ids    = scenario( engine )
    before = table_dump( engine )
    out    = []
    code   = bf.run( engine, side_file( tmp_path, ids ), True, 2, 1, 3, out=out.append, **{ **GO, "expect_database": "lupin_db_dev" } )
    assert code == 2 and "connected to ':memory:', expected 'lupin_db_dev'" in out[ -1 ] and table_dump( engine ) == before
    assert out[ 0 ] == "database           : :memory:" and not any( "rows to insert" in line for line in out )


def test_apply_refuses_when_the_expected_insert_ids_differ_by_a_swap( tmp_path, engine ):
    ids    = scenario( engine )
    before = table_dump( engine )
    out    = []
    swapped = { "n1", "n3" }   # same size as the plan's two inserts, one id swapped for an id that has a row
    code   = bf.run( engine, side_file( tmp_path, ids ), True, 2, 1, 3, out=out.append, **{ **GO, "expect_insert_ids": swapped } )
    assert code == 3 and "1 extra (first ['n2']), 1 missing (first ['n3'])" in out[ -1 ] and table_dump( engine ) == before


def test_apply_refuses_without_an_expected_insert_id_list( tmp_path, engine ):
    ids  = scenario( engine )
    out  = []
    code = bf.run( engine, side_file( tmp_path, ids ), True, 2, 1, 3, out=out.append, expect_database=":memory:" )
    assert code == 3 and "no expected insert id list" in out[ -1 ]


def test_rehearsal_runs_every_step_then_rolls_back( tmp_path, engine ):
    ids    = scenario( engine )
    before = table_dump( engine )
    out    = []
    code   = bf.run( engine, side_file( tmp_path, ids ), False, 2, 1, 3, out=out.append, rehearse=True, **GO )
    assert code == 0 and "rehearsal read back, then rolled back" in out[ -1 ] and '"rows": 3' in out[ -1 ]
    assert table_dump( engine ) == before


def test_main_passes_the_database_and_id_file_through( tmp_path, monkeypatch ):
    idfile = tmp_path / "ids.txt"
    idfile.write_text( "n1\n\nn2\n", encoding="utf-8" )
    seen = { }
    monkeypatch.setattr( bf.sa, "create_engine", lambda url: "engine" )
    monkeypatch.setattr( bf, "run", lambda *args, **kwargs: seen.update( args=args, kwargs=kwargs ) or 0 )
    argv = [ "--side-file", "f", "--database-url", "u", "--rehearse", "--expect-insert", "2", "--expect-update", "1", "--expect-log", "3",
             "--expect-database", "scratch", "--expect-insert-ids", str( idfile ) ]
    assert bf.main( argv ) == 0
    assert seen[ "kwargs" ] == { "rehearse": True, "expect_database": "scratch", "expect_insert_ids": { "n1", "n2" } }


def test_main_refuses_apply_with_rehearse( capsys ):
    with pytest.raises( SystemExit ):
        bf.main( [ "--side-file", "x", "--database-url", "u", "--apply", "--rehearse" ] )
    assert "exclusive" in capsys.readouterr().err
