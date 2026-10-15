"""
Unit tests for the real-stage check's ranks, control, counts and exit codes.

The stage here is a fake that ranks entries by the words a need shares with an id.
So a changed need or a removed entry changes the answer.
The live run is a separate step, on the real vector set.
"""
import io
import json

import pytest

from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import reuse_real_stage_check as chk
from lupin_mcp import reuse_tools as rt

TARGETS = [ t for _n, t in chk.SEEDS ]
OTHERS  = [ "pkg.other.one", "pkg.other.two", "pkg.other.three" ]


def entries_of( ids ):
    """Ensures: returns minimal entries, one per id."""
    return [ { "id": i } for i in ids ]


class FakeStage:
    """A stage that ranks by shared words between the need and the id, and keeps the K best."""

    K = 128

    def __init__( self, manifest_hash="a" * 64, K=128, hide=() ):
        self.hash, self.K, self.hide = manifest_hash, K, set( hide )
        self.calls = []

    def manifest( self ):
        return { "manifest_hash": self.hash }

    def shortlist( self, need, entries, index_sha, pages ):
        self.calls.append( ( need, len( entries ), index_sha ) )
        words   = set( need.split() )
        ids     = [ e[ "id" ] for e in entries if e[ "id" ] not in self.hide ]
        ranking = sorted( ids, key=lambda i: ( -len( words & set( i.replace( ".", " " ).replace( "_", " " ).split() ) ), i ) )[ :self.K ]
        return { "ids": sorted( ranking ), "ranking": ranking, "manifest_hash": self.hash, "K": self.K }


def seeds_for_fake():
    """Ensures: returns five seeds whose need words are in the target id."""
    return tuple( ( f"find {t.split( '.' )[ -1 ].replace( '_', ' ' )}", t ) for t in TARGETS )


def test_rank_of_is_one_based_and_none_when_absent():
    assert chk.rank_of( "b", [ "a", "b" ] ) == 2
    assert chk.rank_of( "z", [ "a", "b" ] ) is None


def test_check_need_reports_rank_counts_and_membership():
    stage = FakeStage( K=2 )
    row   = chk.check_need( stage, "find decide", "cosa.rest.venue_idle.decide", entries_of( TARGETS + OTHERS ), "sha", [] )
    assert row[ "rank" ] == 1 and row[ "found" ] is True
    assert ( row[ "asked" ], row[ "total" ], row[ "not_asked" ] ) == ( 2, 8, 6 )
    assert row[ "ids_in_entries" ] is True and row[ "ids_unique" ] is True and row[ "K" ] == 2


def test_check_need_flags_ids_outside_the_entries_and_repeats():
    class Bad( FakeStage ):
        def shortlist( self, need, entries, index_sha, pages ):
            return { "ids": [ "x", "x" ], "ranking": [ "x", "x" ], "manifest_hash": self.hash, "K": 128 }
    row = chk.check_need( Bad(), "n", "t", entries_of( [ "t" ] ), "sha", [] )
    assert row[ "ids_in_entries" ] is False and row[ "ids_unique" ] is False and row[ "found" ] is False


def test_run_check_passes_when_targets_found_and_control_absent():
    report = chk.run_check( FakeStage(), entries_of( TARGETS + OTHERS ), "sha", [], seeds=seeds_for_fake(), control=seeds_for_fake()[ 0 ] )
    assert report[ "ok" ] is True
    assert [ r[ "rank" ] for r in report[ "seeds" ] ] == [ 1, 1, 1, 1, 1 ]
    assert report[ "control" ][ "found" ] is False and report[ "control" ][ "total" ] == len( TARGETS + OTHERS ) - 1


def test_run_check_fails_when_a_target_is_not_shortlisted():
    report = chk.run_check( FakeStage( hide=[ TARGETS[ 2 ] ] ), entries_of( TARGETS + OTHERS ), "sha", [], seeds=seeds_for_fake(), control=seeds_for_fake()[ 0 ] )
    assert report[ "ok" ] is False
    assert [ r[ "found" ] for r in report[ "seeds" ] ] == [ True, True, False, True, True ]


def test_run_check_fails_when_the_control_is_still_found():
    class Sticky( FakeStage ):
        def shortlist( self, need, entries, index_sha, pages ):
            got = super().shortlist( need, entries, index_sha, pages )
            if index_sha.endswith( "-without-control" ):
                got[ "ranking" ] = [ TARGETS[ 0 ] ] + got[ "ranking" ]
            return got
    report = chk.run_check( Sticky(), entries_of( TARGETS + OTHERS ), "sha", [], seeds=seeds_for_fake(), control=seeds_for_fake()[ 0 ] )
    assert report[ "control" ][ "found" ] is True and report[ "ok" ] is False


def test_run_check_fails_when_the_shortlist_is_not_the_size_the_stage_promises():
    class Short( FakeStage ):
        def shortlist( self, need, entries, index_sha, pages ):
            got = super().shortlist( need, entries, index_sha, pages )
            got[ "ids" ], got[ "ranking" ] = got[ "ids" ][ :-1 ], got[ "ranking" ][ :-1 ]
            return got
    report = chk.run_check( Short(), entries_of( TARGETS + OTHERS ), "sha", [], seeds=seeds_for_fake(), control=seeds_for_fake()[ 0 ] )
    assert report[ "ok" ] is False
    assert all( r[ "asked" ] < min( r[ "K" ], r[ "total" ] ) for r in report[ "seeds" ] )


def test_run_check_fails_on_a_manifest_hash_the_stage_does_not_hold():
    class Drift( FakeStage ):
        def shortlist( self, need, entries, index_sha, pages ):
            got = super().shortlist( need, entries, index_sha, pages )
            got[ "manifest_hash" ] = "b" * 64
            return got
    report = chk.run_check( Drift(), entries_of( TARGETS + OTHERS ), "sha", [], seeds=seeds_for_fake(), control=seeds_for_fake()[ 0 ] )
    assert report[ "ok" ] is False


def test_run_check_refuses_fewer_than_five_seeds_and_unknown_targets():
    with pytest.raises( chk.RunRefused, match="at least five" ):
        chk.run_check( FakeStage(), entries_of( TARGETS ), "sha", [], seeds=seeds_for_fake()[ :4 ] )
    with pytest.raises( chk.RunRefused, match="not in the entries" ):
        chk.run_check( FakeStage(), entries_of( TARGETS[ 1: ] ), "sha", [], seeds=seeds_for_fake(), control=seeds_for_fake()[ 1 ] )


def test_summary_lines_show_ranks_absence_and_verdict():
    good = chk.run_check( FakeStage(), entries_of( TARGETS + OTHERS ), "sha", [], seeds=seeds_for_fake(), control=seeds_for_fake()[ 0 ] )
    text = "\n".join( chk.summary_lines( good ) )
    assert "rank      1" in text and "control absent" in text and "overall PASS" in text
    bad = chk.run_check( FakeStage( hide=[ TARGETS[ 0 ] ] ), entries_of( TARGETS + OTHERS ), "sha", [], seeds=seeds_for_fake(), control=seeds_for_fake()[ 1 ] )
    text = "\n".join( chk.summary_lines( bad ) )
    assert "absent" in text and "overall FAIL" in text
    good[ "control" ][ "found" ] = True
    assert "FOUND (check cannot fail)" in "\n".join( chk.summary_lines( good ) )


@pytest.fixture
def wired( monkeypatch, tmp_path ):
    """Ensures: prepare, data_dir and ReuseContext are replaced, so main reads a fixed list."""
    state = { "flags": set(), "entries": entries_of( TARGETS + OTHERS ) }
    class Ctx:
        def __init__( self, top, data, candidate_stage=None ):
            self.pages, self.candidate_stage = [], candidate_stage
    monkeypatch.setattr( rt, "ReuseContext", Ctx )
    monkeypatch.setattr( rt, "data_dir", lambda top: tmp_path )
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( state[ "flags" ], state[ "entries" ], "sha", None ) )
    return state


def test_main_returns_zero_and_writes_the_report( wired, tmp_path ):
    out, err = io.StringIO(), io.StringIO()
    path     = tmp_path / "r.json"
    wired[ "entries" ] = entries_of( TARGETS + OTHERS )
    stage = FakeStage()
    code  = chk.main( [ "--report", str( path ) ], out, err, stage=stage, top=tmp_path )
    assert code == 0 and json.loads( path.read_text() )[ "ok" ] is True and err.getvalue() == ""


def test_main_returns_one_when_a_target_is_missed( wired, tmp_path ):
    out, err = io.StringIO(), io.StringIO()
    stage    = FakeStage( hide=TARGETS[ :1 ] )
    assert chk.main( [], out, err, stage=stage, top=tmp_path ) == 1
    assert "overall FAIL" in out.getvalue()


def test_main_refuses_on_index_flags_candidate_errors_and_unknown_targets( wired, tmp_path ):
    err = io.StringIO()
    wired[ "flags" ] = { "INDEX_STALE" }
    assert chk.main( [], io.StringIO(), err, stage=FakeStage(), top=tmp_path ) == 2 and "INDEX_STALE" in err.getvalue()
    wired[ "flags" ] = set()
    class Boom( FakeStage ):
        def manifest( self ): raise CandidateError( "VECTOR_SET_UNAVAILABLE", "no manifest" )
    err = io.StringIO()
    assert chk.main( [], io.StringIO(), err, stage=Boom(), top=tmp_path ) == 2 and "VECTOR_SET_UNAVAILABLE" in err.getvalue()
    wired[ "entries" ] = entries_of( OTHERS )
    err = io.StringIO()
    assert chk.main( [], io.StringIO(), err, stage=FakeStage(), top=tmp_path ) == 2 and "not in the entries" in err.getvalue()


def test_main_builds_the_production_stage_in_the_tree_when_none_is_given( wired, monkeypatch, tmp_path ):
    seen = {}
    def build( top ):
        seen[ "top" ] = top
        return FakeStage( hide=TARGETS[ :1 ] )
    monkeypatch.setattr( rt, "_candidate_stage", build )
    assert chk.main( [], io.StringIO(), io.StringIO(), top=tmp_path ) == 1
    assert seen[ "top" ] == tmp_path
    monkeypatch.chdir( tmp_path )
    seen.clear()
    chk.main( [], io.StringIO(), io.StringIO() )
    assert seen[ "top" ] == tmp_path
