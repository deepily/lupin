"""
Unit tests for cosa.repo.git_loc_delta.csv_writer.

Real public surface (verified via live introspection, not a rendered Read):
    CSV_COLUMNS, CSV_SCHEMA_VERSION,
    write_csv(by_type, path, repo, branch=None, debug=False) -> int,
    write_sidecar(csv_path, repo, branch, rev_range, since, until, debug=False) -> str

Tests use real pandas + tempfile round-trips (the CSV/JSON semantics must be
real to be meaningful): row construction, the (date asc, added desc) sort,
header-only empty output, parent-dir creation arcs, the schema-v2 column set,
and the sidecar JSON shape (incl. None→null fields + the ISO-8601-Z stamp).

Authored by Sam 🎙️ for the CoSA 100% coverage campaign (git_loc_delta group,
handed off from Cheech). Reviewed by Mr. Radio (no self-audit).
"""
import json
import os
import tempfile
from datetime import datetime

import pandas as pd

from cosa.repo.git_loc_delta.csv_writer import (
    CSV_COLUMNS,
    CSV_SCHEMA_VERSION,
    write_csv,
    write_sidecar,
)


def _by_type( **cells ):
    """Build a by_type dict; pass cells as 'date|file_type'=(added,deleted,files,commits)."""
    out = {}
    for key, ( a, d, f, c ) in cells.items():
        date, ftype = key.split( "|" )
        out[ ( date, ftype ) ] = { "added": a, "deleted": d, "files_touched": f, "commits": c }
    return out


class TestWriteCsv:
    """write_csv() — row construction, sort, parent-dir arcs, empty input."""

    def test_writes_rows_with_schema_v2_columns( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "out.csv" )
            n = write_csv(
                _by_type( **{ "2026-05-16|python": ( 10, 2, 1, 1 ) } ),
                path, repo="cosa", branch="wip-x",
            )
            assert n == 1
            df = pd.read_csv( path )
            assert list( df.columns ) == CSV_COLUMNS
            row = df.iloc[ 0 ]
            assert row[ "repo" ] == "cosa"
            assert row[ "branch" ] == "wip-x"
            assert row[ "file_type" ] == "python"
            assert int( row[ "added" ] ) == 10

    def test_rows_sorted_by_date_asc_then_added_desc( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "out.csv" )
            write_csv(
                _by_type( **{
                    "2026-05-17|python":   ( 5, 0, 1, 1 ),
                    "2026-05-16|markdown": ( 3, 0, 1, 1 ),
                    "2026-05-16|python":   ( 100, 0, 1, 1 ),   # same date, larger added → first
                } ),
                path, repo="cosa", branch="wip",
            )
            df = pd.read_csv( path )
            # date ascending: both 05-16 rows before 05-17; within 05-16, added desc.
            assert df.iloc[ 0 ][ "date" ] == "2026-05-16"
            assert int( df.iloc[ 0 ][ "added" ] ) == 100
            assert df.iloc[ 1 ][ "file_type" ] == "markdown"
            assert df.iloc[ 2 ][ "date" ] == "2026-05-17"

    def test_none_branch_becomes_empty_string( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "out.csv" )
            write_csv( _by_type( **{ "2026-05-16|python": ( 1, 0, 1, 1 ) } ), path, repo="cosa" )
            df = pd.read_csv( path, keep_default_na=False )
            assert df.iloc[ 0 ][ "branch" ] == ""

    def test_empty_input_writes_header_only_returns_zero( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "empty.csv" )
            n = write_csv( {}, path, repo="cosa", branch="wip" )
            assert n == 0
            df = pd.read_csv( path )
            assert list( df.columns ) == CSV_COLUMNS
            assert len( df ) == 0

    def test_creates_missing_parent_dir( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "nested", "deep", "out.csv" )   # parents don't exist
            n = write_csv(
                _by_type( **{ "2026-05-16|python": ( 1, 0, 1, 1 ) } ),
                path, repo="cosa", debug=True,
            )
            assert n == 1
            assert os.path.isfile( path )

    def test_existing_parent_dir_no_recreate( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "out.csv" )   # parent (d) already exists
            assert write_csv( _by_type( **{ "2026-05-16|python": ( 1, 0, 1, 1 ) } ), path, repo="cosa" ) == 1

    def test_bare_filename_has_empty_parent( self ):
        # dirname('bare.csv') == '' -> the `if parent` short-circuit (False) is taken.
        with tempfile.TemporaryDirectory() as d:
            prev = os.getcwd()
            os.chdir( d )
            try:
                n = write_csv( _by_type( **{ "2026-05-16|python": ( 1, 0, 1, 1 ) } ), "bare.csv", repo="cosa" )
                assert n == 1
                assert os.path.isfile( os.path.join( d, "bare.csv" ) )
            finally:
                os.chdir( prev )


class TestWriteSidecar:
    """write_sidecar() — JSON metadata shape, None→null, ISO-Z stamp, path."""

    def test_writes_full_metadata( self ):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join( d, "cosa-wip-loc-delta.csv" )
            sidecar = write_sidecar(
                csv_path, repo="cosa", branch="wip", rev_range="main..wip",
                since="2026-05-01", until="2026-05-31", debug=True,
            )
            assert sidecar == csv_path + ".meta.json"
            with open( sidecar ) as f:
                meta = json.load( f )
            assert meta[ "csv_schema_version" ] == CSV_SCHEMA_VERSION
            assert meta[ "repo" ] == "cosa"
            assert meta[ "branch" ] == "wip"
            assert meta[ "rev_range" ] == "main..wip"
            assert meta[ "since" ] == "2026-05-01"
            assert meta[ "until" ] == "2026-05-31"

    def test_generated_at_is_iso_utc_z( self ):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join( d, "x.csv" )
            sidecar = write_sidecar( csv_path, "cosa", None, None, None, None )
            with open( sidecar ) as f:
                meta = json.load( f )
            assert meta[ "generated_at" ].endswith( "Z" )
            # The prefix (minus the trailing 'Z') must be ISO-8601 parseable.
            datetime.fromisoformat( meta[ "generated_at" ][ :-1 ] )

    def test_none_fields_written_as_json_null( self ):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join( d, "x.csv" )
            sidecar = write_sidecar( csv_path, "cosa", None, None, None, None )
            raw = open( sidecar ).read()
            meta = json.loads( raw )
            # Keys present with null values (shape stability for consumers).
            for k in ( "branch", "rev_range", "since", "until" ):
                assert k in meta
                assert meta[ k ] is None
