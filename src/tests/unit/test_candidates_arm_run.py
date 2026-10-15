"""
Unit tests for running one arm against the cached sweep and the known twins.

Every case is hand-built on a six-entry index and a four-answer cache, with the readers passed in as fakes.
Each rule has a case that fails when the rule is removed.
The reserved file is refused, an empty reference is left out of recall, and a member is not its own twin.
"""
import gzip
import json
import types

import pytest

from cosa.repo.symindex.candidates import arm_run
from cosa.repo.symindex.candidates import arms
from cosa.repo.symindex.candidates.errors import CandidateError


def entry( doc_id, name, doc="", file="src/x.py" ):
    """A minimal index entry."""
    return { "id": doc_id, "name": name, "doc": doc, "pin": f"pin-{doc_id}", "file": file, "sig": "()" }


ENTRIES = [ entry( "a", "parse_config", "Read a config file\nmore" ), entry( "b", "load_settings", "Load config settings" ),
            entry( "c", "render_page", "Render a config page", "web/p.js" ), entry( "d", "send_mail", "Send a mail" ),
            entry( "e", "zip_files", "Pack files" ), entry( "x", "helper", "" ) ]
HIGH = { "provides": 0.99, "probabilities": { "0": 0.0, "1": 0.0, "2": 0.0, "3": 1.0 } }
LOW  = { "provides": 0.01, "probabilities": { "0": 1.0, "1": 0.0, "2": 0.0, "3": 0.0 } }


def write_needs( tmp_path, ids=( "n1", "n2" ) ):
    """Write a needs file and return its path."""
    path = tmp_path / "needs.json"
    path.write_text( json.dumps( { "needs": [ { "id": i, "need": f"read config {i}", "exclude": "x", "kind": "duplicate" } for i in ids ] } ) )
    return str( path )


def fake_env( held ):
    """Readers whose cache answers by ( need text, entry name, repeat )."""
    return types.SimpleNamespace( sendable=lambda entries, ex: ( entries, [] ), entry_text=lambda e: e[ "name" ],
                                  pair_key=lambda need, text, model, repeat: ( need, text, repeat ), model="m",
                                  cache=types.SimpleNamespace( get=lambda key: held.get( key ) ) )


def cache_for( needs, high ):
    """A cache where only the entry named in `high` answers high, for every need and repeat."""
    held = {}
    for n in needs:
        for e in ENTRIES:
            for r in arm_run.REPEATS:
                held[ ( f"read config {n}", e[ "name" ], r ) ] = { "answers": { "fit": LOW if e[ "name" ] != high.get( n ) else HIGH } }
    return held


class TestLoadNeeds:
    """The in-sample file is read and the reserved one is refused."""

    def test_returns_the_needs_by_id( self, tmp_path ):
        assert sorted( arm_run.load_needs( write_needs( tmp_path ), "f" * 64 ) ) == [ "n1", "n2" ]

    def test_a_reserved_id_is_refused( self, tmp_path ):
        with pytest.raises( CandidateError ) as caught:
            arm_run.load_needs( write_needs( tmp_path, ( "fresh-01", ) ), "f" * 64 )
        assert caught.value.code == arms.FRESH_NEEDS_REFUSED

    def test_the_reserved_file_is_refused_by_its_hash( self, tmp_path ):
        path = write_needs( tmp_path )
        with pytest.raises( CandidateError ):
            arm_run.load_needs( path, arm_run.sha256_of( path ) )


class TestSnapshots:
    """A snapshot is read and the best one is chosen."""

    def test_entries_come_from_the_gzip( self, tmp_path ):
        path = tmp_path / "s.json.gz"
        path.write_bytes( gzip.compress( json.dumps( { "symbols_jsonl": "\n".join( json.dumps( e ) for e in ENTRIES[ :2 ] ) + "\n\n" } ).encode() ) )
        assert [ e[ "id" ] for e in arm_run.snapshot_entries( str( path ), lambda es, ex: ( es, [] ) ) ] == [ "a", "b" ]

    def test_most_hits_wins_and_a_tie_goes_to_the_first_path( self ):
        hits = { "p1": 3, "p2": 5, "p3": 5 }
        assert arm_run.pick_snapshot( [ "p3", "p1", "p2" ], hits.get ) == ( 5, "p2" )


class TestAnswers:
    """Cached answers are read per need and repeat."""

    def test_reads_every_repeat_and_skips_the_excluded_entry( self, tmp_path ):
        needs   = arm_run.load_needs( write_needs( tmp_path, ( "n1", ) ), "f" * 64 )
        answers, misses = arm_run.load_answers( needs, ENTRIES, fake_env( cache_for( [ "n1" ], { "n1": "parse_config" } ) ) )
        assert sorted( answers ) == [ ( "n1", r ) for r in arm_run.REPEATS ]
        assert sorted( answers[ ( "n1", 1 ) ] ) == [ "a", "b", "c", "d", "e" ]
        assert answers[ ( "n1", 1 ) ][ "a" ] == { "provides": 0.99, "coverage": HIGH[ "probabilities" ] }
        assert misses == 0

    def test_an_entry_with_no_answer_is_counted( self, tmp_path ):
        needs = arm_run.load_needs( write_needs( tmp_path, ( "n1", ) ), "f" * 64 )
        held  = cache_for( [ "n1" ], {} )
        del held[ ( "read config n1", "send_mail", 2 ) ]
        answers, misses = arm_run.load_answers( needs, ENTRIES, fake_env( held ) )
        assert misses == 1
        assert "d" not in answers[ ( "n1", 2 ) ]

    def test_the_hash_moves_when_an_answer_moves( self, tmp_path ):
        needs = arm_run.load_needs( write_needs( tmp_path, ( "n1", ) ), "f" * 64 )
        one, _ = arm_run.load_answers( needs, ENTRIES, fake_env( cache_for( [ "n1" ], { "n1": "parse_config" } ) ) )
        two, _ = arm_run.load_answers( needs, ENTRIES, fake_env( cache_for( [ "n1" ], { "n1": "send_mail" } ) ) )
        assert arm_run.hash_answers( one ) != arm_run.hash_answers( two )
        assert arm_run.hash_answers( one ) == arm_run.hash_answers( one )


class TestMeasure:
    """Recall and replay over hand-built answers."""

    @pytest.fixture
    def setup( self, tmp_path ):
        needs = arm_run.load_needs( write_needs( tmp_path ), "f" * 64 )
        held  = cache_for( [ "n1", "n2" ], { "n1": "parse_config" } )      # n2 has no entry that clears the threshold
        answers, _ = arm_run.load_answers( needs, ENTRIES, fake_env( held ) )
        return needs, answers, arms.build_arm_stages( ENTRIES, {} )

    def test_references_follow_the_decision( self, setup ):
        needs, answers, _ = setup
        first, union = arm_run.references( answers, needs )
        assert first == { "n1": [ "a" ], "n2": [] }
        assert union == { "n1": [ "a" ], "n2": [] }

    def test_empty_reference_needs_are_left_out_of_recall( self, setup ):
        needs, answers, stages = setup
        out = arm_run.measure_arm( "C0", needs, stages, {}, answers, ks=( 5, 6 ) )
        assert out[ "empty" ] == [ "n2" ]
        assert set( out[ "t1_first" ][ 5 ][ "per_need" ] ) == { "n1" }
        assert out[ "t1_first" ][ 6 ][ "mean" ] == 1.0

    def test_the_union_reference_holds_what_any_repeat_shortlisted( self, setup ):
        needs, answers, _ = setup
        answers[ ( "n1", 2 ) ] = { **answers[ ( "n1", 2 ) ], "d": { "provides": 0.99, "coverage": HIGH[ "probabilities" ] } }
        first, union = arm_run.references( answers, needs )
        assert first[ "n1" ] == [ "a" ]
        assert union[ "n1" ] == [ "a", "d" ]

    def test_the_control_replay_agrees_with_itself( self, setup ):
        needs, answers, stages = setup
        out = arm_run.measure_arm( "C0", needs, stages, {}, answers, ks=( 5, ) )
        assert out[ "t2" ][ "control" ][ "agreement" ] == 1.0
        assert sorted( out[ "t2" ] ) == [ "K=128", "K=512", "control" ]


class TestTwins:
    """The known twins and where they land."""

    MANIFEST = { "exact": [ { "members": [ { "id": "a" }, { "id": "b" }, { "id": "c" } ] } ], "near": [ { "members": [ { "id": "d" }, { "id": "e" } ] } ] }

    def test_every_member_gets_the_others_of_its_cluster( self ):
        twins = arm_run.twin_map( self.MANIFEST )
        assert twins[ "a" ] == { "b", "c" }
        assert twins[ "e" ] == { "d" }
        assert all( m not in t for m, t in twins.items() )

    def test_query_is_name_signature_and_first_doc_line( self ):
        assert arm_run.query_text( ENTRIES[ 0 ] ) == "parse_config () Read a config file"
        assert arm_run.query_text( entry( "z", "bare", None ) ) == "bare ()"
        assert arm_run.query_text( { "name": "n", "doc": "", "sig": None } ) == "n"

    def test_ranks_group_by_suffix_and_leave_the_member_out( self ):
        stages = arms.build_arm_stages( ENTRIES, {} )
        twins  = { "a": { "b", "d" }, "c": { "a" }, "d": { "gone" }, "ghost": { "a" } }
        ranks, absent = arm_run.measure_twins( "C0", ENTRIES, twins, stages, {} )
        assert absent == [ "ghost" ]
        assert sorted( ranks ) == [ "js", "py" ]
        assert ranks[ "js" ][ 0 ] is not None
        assert ranks[ "py" ][ 0 ] == 2                                  # a ranks first for its own query; with a left out, its twin b is second
        assert ranks[ "py" ].count( None ) == 1                         # d's only twin is not in the index

    def test_a_file_without_a_suffix_is_other( self ):
        stages = arms.build_arm_stages( [ entry( "a", "alpha", "x", "Makefile" ), entry( "b", "alpha", "x" ) ], {} )
        ranks, _ = arm_run.measure_twins( "C0", [ entry( "a", "alpha", "x", "Makefile" ), entry( "b", "alpha", "x" ) ], { "a": { "b" } }, stages, {} )
        assert list( ranks ) == [ "other" ]


class TestPage:
    """The page and the run that writes it."""

    META    = { "run_id": "r", "code_sha": "c", "index_sha": "i", "manifest_hash": "m", "needs_sha": "n", "cache_sha": "k" }
    T1      = { 32: { "mean": 0.5, "mean_size": 31.0 }, 64: { "mean": None, "mean_size": None } }
    MEASURED = { "t1_first": T1, "t1_union": T1, "empty": [ "n2" ],
                 "t2": { "control": { "needs": 2, "flip_rate": 0.0, "agreement": 1.0, "uncached": 0 } } }
    T3      = { "py": { "members": 3, "unranked": 1, "median": 2, "median_all": 3, "within": { 10: 2, 50: 2, 128: 2 } } }

    def page( self, **over ):
        args = dict( meta=self.META, arm="C0", measured=self.MEASURED, t3=self.T3, absent=[ "g" ], pending=[ ( "B1", "vectors" ) ], ruling="RULING TEXT" )
        args.update( over )
        return arm_run.render_partial_page( **args )

    def test_page_carries_numbers_ruling_and_pending_arms( self ):
        text = self.page()
        assert "| 32 | 50.0% | 50.0% | 31 |" in text
        assert "| py | 3 | 1 | 2 | 3 | 2 | 2 | 2 |" in text
        assert "RULING TEXT" in text
        assert "| B1 | vectors |" in text
        assert "not a flip rate" in text
        assert "n2" in text

    def test_missing_meta_is_named( self ):
        with pytest.raises( CandidateError ) as caught:
            self.page( meta={ **self.META, "code_sha": "" } )
        assert "code_sha" in caught.value.detail

    def test_full_run_writes_the_page( self, tmp_path ):
        needs   = write_needs( tmp_path )
        held    = cache_for( [ "n1", "n2" ], { "n1": "parse_config" } )
        snaps   = []
        for name in ( "aaaa.json.gz", "bbbb.json.gz" ):
            path = tmp_path / name
            path.write_bytes( gzip.compress( json.dumps( { "symbols_jsonl": "\n".join( json.dumps( e ) for e in ENTRIES ) } ).encode() ) )
            snaps.append( str( path ) )
        manifest = tmp_path / "manifest.json"
        manifest.write_text( json.dumps( TestTwins.MANIFEST ) )
        out = arm_run.run_arm_report( fake_env( held ), snaps, needs, "f" * 64, str( manifest ), str( tmp_path / "out" / "page.md" ), "abc123" )
        assert out[ "misses" ] == 0 and out[ "needs" ] == 2 and out[ "members" ] == 5
        text = ( tmp_path / "out" / "page.md" ).read_text()
        assert "abc123" in text and "## Arms not measured yet" in text and "| C1 |" in text

    def test_main_wires_the_real_environment( self, tmp_path, monkeypatch, capsys ):
        held = cache_for( [ "n1", "n2" ], { "n1": "parse_config" } )
        ( tmp_path / "snapshots" ).mkdir()
        ( tmp_path / "snapshots" / "aaaa.json.gz" ).write_bytes( gzip.compress( json.dumps( { "symbols_jsonl": "\n".join( json.dumps( e ) for e in ENTRIES ) } ).encode() ) )
        manifest = tmp_path / "manifest.json"
        manifest.write_text( json.dumps( TestTwins.MANIFEST ) )
        monkeypatch.setattr( arm_run, "real_env", lambda data: fake_env( held ) )
        rc = arm_run.main( [ "--data", str( tmp_path ), "--needs", write_needs( tmp_path ), "--fresh-sha", "f" * 64, "--manifest", str( manifest ),
                             "--out", str( tmp_path / "p.md" ), "--code-sha", "abc" ] )
        assert rc == 0
        assert json.loads( capsys.readouterr().out )[ "needs" ] == 2


class TestRealEnv:
    """The real readers are the index's own."""

    def test_builds_a_namespace_over_the_real_modules( self, tmp_path ):
        env = arm_run.real_env( str( tmp_path ) )
        assert env.model == "jev-1.13.0"
        assert callable( env.sendable ) and callable( env.pair_key ) and callable( env.entry_text )
        assert env.cache.get( env.pair_key( "need", "text", env.model, 1 ) ) is None
