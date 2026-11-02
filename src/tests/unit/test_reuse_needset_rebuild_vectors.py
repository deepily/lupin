"""
The vector rebuild refuses no prior generation, a stale purpose store or a surprise.
"""
import io
import json

import pytest

from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import rebuild_vectors as rv

LIVE_BYTES = b'{"id": "a", "purpose": "does a"}\n'


def write_set( folder, matrices ):
    """Ensures: folder/vectors holds build-info.json and each matrix with the given bytes."""
    vec = folder / "vectors"
    vec.mkdir( parents=True, exist_ok=True )
    ( vec / "build-info.json" ).write_text( "{}", encoding="utf-8" )
    for name, data in matrices.items(): ( vec / name ).write_bytes( data )
    return vec


SAME = { n: n.encode() for n in rv.MATRICES }


def setup( tmp_path, copy_bytes=LIVE_BYTES, prior=None ):
    """Ensures: returns ( prior gen, out dir, live store ) with a purpose copy in the out dir."""
    live = tmp_path / "live" / "purpose.jsonl"
    live.parent.mkdir()
    live.write_bytes( LIVE_BYTES )
    out = tmp_path / "out"
    ( out / "purpose-lines" ).mkdir( parents=True )
    if copy_bytes is not None: ( out / "purpose-lines" / "purpose.jsonl" ).write_bytes( copy_bytes )
    gen = tmp_path / "prior"
    write_set( gen, SAME if prior is None else prior )
    return gen, out, live


def builder( matrices ):
    """Ensures: returns a build function that writes the given matrices under out_dir."""
    def build( root, index, out_dir ):
        write_set( __import__( "pathlib" ).Path( out_dir ), matrices )
        return { "rows": 3 }
    return build


def code_of( **kw ):
    """Ensures: returns the code of the NeedsetError rebuild raises."""
    with pytest.raises( er.NeedsetError ) as e: rv.rebuild( "root", "idx", kw.pop( "out" ), kw.pop( "gen" ), **kw )
    return e.value.code


def test_no_prior_generation_is_refused_before_anything_is_built( tmp_path ):
    gen, out, live = setup( tmp_path )
    built = []
    assert code_of( gen=tmp_path / "nothing", out=out, live_store=live, build=lambda *a: built.append( a ) ) == er.PRIOR_GEN_MISSING
    assert built == []


@pytest.mark.parametrize( "missing", [ "build-info.json", "code.f32", "ids.txt" ] )
def test_a_prior_generation_missing_a_file_is_refused_and_the_file_is_named( tmp_path, missing ):
    gen, out, live = setup( tmp_path )
    ( gen / "vectors" / missing ).unlink()
    with pytest.raises( er.NeedsetError ) as e: rv.check_prior( gen )
    assert e.value.code == er.PRIOR_GEN_MISSING and missing in e.value.detail


def test_a_purpose_store_that_is_not_a_copy_of_the_live_one_is_refused_before_the_build( tmp_path ):
    gen, out, live = setup( tmp_path, copy_bytes=b'{"id": "a", "purpose": "an old line"}\n' )
    built = []
    assert code_of( gen=gen, out=out, live_store=live, build=lambda *a: built.append( a ) ) == er.PURPOSE_STORE_NOT_LIVE
    assert built == []


def test_an_absent_purpose_copy_and_an_unreadable_live_store_are_refused( tmp_path ):
    gen, out, live = setup( tmp_path, copy_bytes=None )
    assert code_of( gen=gen, out=out, live_store=live, build=builder( SAME ) ) == er.PURPOSE_STORE_NOT_LIVE
    ( tmp_path / "again" ).mkdir()
    gen, out, live = setup( tmp_path / "again" )
    live.unlink()
    assert code_of( gen=gen, out=out, live_store=live, build=builder( SAME ) ) == er.PURPOSE_STORE_NOT_LIVE


def test_matrices_identical_to_the_prior_generation_pass_with_nothing_changed( tmp_path ):
    gen, out, live = setup( tmp_path )
    got = rv.rebuild( "root", "idx", out, gen, live_store=live, build=builder( SAME ) )
    assert got == { "build": { "rows": 3 }, "changed": [], "expected": [] }


def test_an_unexpected_matrix_change_is_refused_and_named( tmp_path ):
    gen, out, live = setup( tmp_path )
    with pytest.raises( er.NeedsetError ) as e: rv.rebuild( "root", "idx", out, gen, live_store=live, build=builder( { **SAME, "code.f32": b"changed" } ) )
    assert e.value.code == er.MATRICES_CHANGED and "code.f32" in e.value.detail and "prose.f32" not in e.value.detail


def test_a_change_is_allowed_only_for_the_matrix_it_was_told_to_expect( tmp_path ):
    gen, out, live = setup( tmp_path )
    new = { **SAME, "code.f32": b"changed", "prose.f32": b"changed too" }
    assert code_of( gen=gen, out=out, live_store=live, build=builder( new ), expect=[ "code.f32" ] ) == er.MATRICES_CHANGED
    got = rv.rebuild( "root", "idx", out, gen, live_store=live, build=builder( new ), expect=[ "prose.f32", "code.f32" ] )
    assert got[ "changed" ] == [ "code.f32", "prose.f32" ]


def test_a_matrix_the_build_did_not_write_counts_as_changed( tmp_path ):
    gen, out, live = setup( tmp_path )
    short = { k: v for k, v in SAME.items() if k != "ids.txt" }
    assert code_of( gen=gen, out=out, live_store=live, build=builder( short ) ) == er.MATRICES_CHANGED


def test_main_exits_two_with_the_code_when_refused_and_zero_with_a_report_when_not( tmp_path ):
    gen, out, live = setup( tmp_path )
    argv = [ "--root", "r", "--index", "i", "--out-dir", str( out ), "--prior-gen", str( gen ) ]
    o, e = io.StringIO(), io.StringIO()
    assert rv.main( argv, out=o, err=e, live_store=live, build=builder( { **SAME, "code.f32": b"x" } ) ) == rv.EXIT_REFUSED and "MATRICES_CHANGED" in e.getvalue() and o.getvalue() == ""
    o, e = io.StringIO(), io.StringIO()
    assert rv.main( argv, out=o, err=e, live_store=live, build=builder( SAME ) ) == 0 and json.loads( o.getvalue() )[ "changed" ] == []
    o, e = io.StringIO(), io.StringIO()
    assert rv.main( argv + [ "--expect", "code.f32,," ], out=o, err=e, live_store=live, build=builder( { **SAME, "code.f32": b"x" } ) ) == 0


def test_the_prior_generation_argument_is_required():
    with pytest.raises( SystemExit ): rv.main( [ "--root", "r", "--index", "i", "--out-dir", "o" ] )


def test_the_live_store_path_is_the_production_purpose_store():
    from cosa.repo.symindex import paths
    from cosa.repo.symindex.candidates import storage_paths as sp
    import pathlib, tempfile
    root = pathlib.Path( tempfile.mkdtemp() )
    assert rv.live_purpose_store( root ) == sp.candidate_dir( "purpose", paths.data_dir( root ) ) / "purpose.jsonl"
    assert str( rv.live_purpose_store( root ) ).endswith( "purpose-lines/purpose.jsonl" )
