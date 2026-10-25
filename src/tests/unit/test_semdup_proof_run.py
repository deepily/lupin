"""Unit tests for semdup.proof.proof_run: the toy pool, the record and the ledger."""
import asyncio
import json
import re

import pytest

from cosa.repo.doc_lint import harness_runner as hr
from cosa.repo.semdup import blind as bl
from cosa.repo.semdup import config as cf
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import extract as ex
from cosa.repo.semdup import judge as jd
from cosa.repo.semdup.proof import proof_run as pr

SCRUB = bl.scrub_tokens( [ "ARM-WITH" ] )
MARKS = [ "MARKA", "MARKB", "MARKC", "MARKD", "MARKE", "MARKF", "MARKG", "MARKH", "MARKX", "MARKY", "MARKZ" ]
BLOCK = re.compile( r"<(definition|candidate_c\d+)_([0-9a-f]{8})>\n(.*?)\n</\1_\2>", re.DOTALL )
JSCPD = { "version": "5.3.3", "min_tokens": 50, "min_lines": 5, "chosen_in": "test" }


class FakeClient:
    """Embed a text as the counts of the marker words in it."""

    def embed( self, texts, content_type, role ):
        return [ [ float( t.count( m ) ) for m in MARKS ] + [ float( len( t ) % 5 ) ] for t in texts ]

    def info( self ):
        return { "engines": { "code": { "revision": "r1" } } }


class FakeBackend:
    """Rule duplicate on a shared marker word; a second-pass definition with flip is distinct."""

    name               = "max-plan"
    server_label       = "max-plan"
    temperature_record = "unsettable:bounded-cc"

    def __init__( self, per_pass=0, flip=None, garbage_after=None, never=False ):
        self.never         = never
        self.per_pass      = per_pass
        self.flip          = flip
        self.garbage_after = garbage_after
        self.calls         = 0

    async def complete( self, model, system_prompt, user_prompt ):
        self.calls += 1
        if self.garbage_after is not None and self.calls > self.garbage_after: return "not json"
        second = self.per_pass and self.calls > self.per_pass
        blocks = { tag: body for tag, _, body in BLOCK.findall( user_prompt ) }
        mine   = set( re.findall( r"MARK[A-Z]", blocks[ "definition" ] ) )
        out    = []
        for tag, body in blocks.items():
            if tag == "definition": continue
            shared = mine & set( re.findall( r"MARK[A-Z]", body ) )
            if self.never or ( second and self.flip in mine ): shared = set()
            verdict, reason = ( "duplicate", f"both carry {sorted( shared )[ 0 ]}" ) if shared else ( "related", "no marker shared" )
            out.append( { "candidate": tag.replace( "candidate_", "" ), "verdict": verdict, "reason": reason } )
        return json.dumps( { "verdicts": out } )


def source_of( name, marks, n ):
    """Return the source of a function that carries the marker words and a number only it has."""
    tags = ", ".join( f'"{m}"' for m in marks )
    return f"def {name}( items ):\n    tags = [ {tags} ]\n    out = []\n    for item in items:\n        out.append( item * {n} )\n    return out\n"


class Toy:
    """A small closed pool: originals, rewrites, monolith definitions and distractors."""

    def __init__( self, tmp_path, backend=None, parallel=1 ):
        self.root = tmp_path / "tree"
        self.root.mkdir()
        self.count = 0
        origin = lambda names, kind: { n: self.define( n, marks, kind ) for n, marks in names.items() }
        self.o  = origin( { "o1": [ "MARKA" ], "o2": [ "MARKB" ], "o3": [ "MARKC" ] }, "server" )
        self.r  = origin( { "r1": [ "MARKA" ], "r2": [ "MARKB" ], "r3": [ "MARKX" ] }, "new" )
        self.m  = origin( { "m1": [ "MARKD" ], "m2": [ "MARKD" ], "m3": [ "MARKE" ], "m4": [ "MARKE" ], "m5": [ "MARKF" ] }, "server" )
        self.d  = origin( { "d1": [ "MARKY" ], "d2": [ "MARKZ" ], "d3": [ "MARKA" ] }, "server" )
        backend = backend or FakeBackend()
        cfg     = cf.build_config( "max-plan", "unsettable:bounded-cc", "stub", *jd.prompt_parts(), SCRUB, 4000, JSCPD, min_nodes=10 )
        frozen  = tmp_path / "frozen.json"
        cf.freeze( cfg, str( frozen ) )
        self.cfg    = cfg
        self.wiring = { "frozen_path": str( frozen ), "live": cfg, "client": FakeClient(), "cache_dir": tmp_path / "vectors", "scrub": SCRUB,
                        "structural_pairs": lambda defs: [], "backend": backend,
                        "ledger": hr.Ledger( str( tmp_path / "ledger.jsonl" ), jd.ledger_binding( "cli 1", backend ) ), "parallel": parallel,
                        "data_dir": tmp_path / "data", "clock": lambda: "2026-10-24T20:00:00-04:00" }
        self.spec = {
            "planted"       : [ { "original": self.o[ "o1" ], "rewrite": self.r[ "r1" ], "stratum": "fable_planted" },
                                { "original": self.o[ "o2" ], "rewrite": self.r[ "r2" ], "stratum": "opus_work_alike" },
                                { "original": self.o[ "o3" ], "rewrite": self.r[ "r3" ], "stratum": "opus_work_alike" } ],
            "monolith_defs" : list( self.m.values() ), "distractors": list( self.d.values() ),
            "monolith_pairs": [ { "ids": [ self.m[ "m1" ][ "id" ], self.m[ "m2" ][ "id" ] ], "source": "structural" },
                                { "ids": [ self.m[ "m3" ][ "id" ], self.m[ "m4" ][ "id" ] ], "source": "neighbour" },
                                { "ids": [ self.m[ "m1" ][ "id" ], self.m[ "m5" ][ "id" ] ], "source": "nominated" } ],
            "seed": 3, "plant_failures": [], "labels": {} }

    def define( self, name, marks, origin ):
        """Write one function file and return its definition record."""
        self.count += 1
        path = self.root / f"{name}.py"
        path.write_text( source_of( name, marks, self.count + 1 ), encoding="utf-8" )
        return ex.extract_tree( self.root, [ path ], origin )[ "definitions" ][ 0 ]

    def key( self, a, b ):
        """Return the pair key of two toy definitions named by their keys, from any of the groups."""
        every = { **self.o, **self.r, **self.m, **self.d }
        return pr.label_key( every[ a ][ "id" ], every[ b ][ "id" ] )

    def all_labels( self ):
        """Label every known pair and the one extra flag the toy raises."""
        return { self.key( "r1", "o1" ): True, self.key( "r2", "o2" ): True, self.key( "r3", "o3" ): True, self.key( "m1", "m2" ): True,
                 self.key( "m3", "m4" ): True, self.key( "m1", "m5" ): False, self.key( "r1", "d3" ): False }


# ---- resolve_label ----------------------------------------------------------------------------------------------

def test_a_pair_is_true_only_when_both_reviewers_say_so_and_false_when_both_say_false():
    assert pr.resolve_label( True, True ) is True and pr.resolve_label( False, False ) is False


@pytest.mark.parametrize( "first, second, ruling", [ ( True, False, True ), ( True, False, False ), ( False, True, True ), ( False, True, False ) ] )
def test_a_disagreement_takes_the_ruling_and_refuses_to_guess_without_one(first, second, ruling):
    assert pr.resolve_label( first, second, ruling ) is ruling
    with pytest.raises( ValueError, match="no ruling" ): pr.resolve_label( first, second )


# ---- build_pool -------------------------------------------------------------------------------------------------

def test_the_pool_holds_every_definition_once_with_the_rewrites_and_one_side_of_each_monolith_pair_as_new(tmp_path):
    toy  = Toy( tmp_path )
    pool = pr.build_pool( toy.spec, 3 )
    new_names = { d[ "name" ] for d in pool[ "new" ] }
    assert { "r1", "r2", "r3" } <= new_names and len( pool[ "new" ] ) >= 5 and all( d[ "origin" ] == "new" for d in pool[ "new" ] )
    assert len( {d[ "id" ] for d in pool[ "defs" ]} ) == len( pool[ "defs" ] ) and pool[ "sizes" ][ "size" ] == 3 + 3 + 5 + 3
    assert all( d[ "origin" ] == "server" for d in pool[ "defs" ] if d[ "name" ] not in new_names )
    assert all( pool[ "canon" ][ d[ "id" ] ] in { x[ "id" ] for x in toy.m.values() } for d in pool[ "new" ] if d[ "name" ].startswith( "m" ) )


def test_the_same_seed_gives_the_same_pool_whatever_the_order_and_another_seed_can_choose_differently(tmp_path):
    toy      = Toy( tmp_path )
    first    = pr.build_pool( toy.spec, 3 )
    shuffled = { **toy.spec, "monolith_pairs": list( reversed( toy.spec[ "monolith_pairs" ] ) ), "monolith_defs": list( reversed( toy.spec[ "monolith_defs" ] ) ),
                 "distractors": list( reversed( toy.spec[ "distractors" ] ) ) }
    assert pr.build_pool( shuffled, 3 ) == first
    assert any( pr.build_pool( toy.spec, s )[ "canon" ] != first[ "canon" ] for s in range( 4, 20 ) )


# ---- the toy run ------------------------------------------------------------------------------------------------

def test_the_toy_run_gives_the_hand_computed_figures_pool_size_and_strata(tmp_path):
    toy    = Toy( tmp_path )
    toy.spec[ "labels" ] = toy.all_labels()
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "status" ] == "complete" and record[ "proof" ] == 1
    assert record[ "counts" ] == { "true_pairs": 5, "found": 4, "flags": 5, "correct": 4, "both": record[ "counts" ][ "both" ], "agree": record[ "counts" ][ "both" ] }
    assert record[ "bar" ][ "found" ][ "fraction" ] == "4/5" and record[ "bar" ][ "correct" ][ "fraction" ] == "4/5" and record[ "bar" ][ "agreement" ][ "fraction" ] == "1" and record[ "bar" ][ "passed" ] is True
    assert record[ "pool" ][ "size" ] == 14 == record[ "pool" ][ "new" ] + record[ "pool" ][ "server" ] and record[ "pool" ][ "distractors" ] == 3 and 5 <= record[ "pool" ][ "new" ] <= 6
    assert { name: ( s[ "found" ], s[ "true" ] ) for name, s in record[ "strata" ].items() } == { "fable_planted": ( 1, 1 ), "opus_work_alike": ( 1, 2 ),
                                                                                                   "monolith:structural": ( 1, 1 ), "monolith:neighbour": ( 1, 1 ) }
    assert all( s[ "interval" ] is not None for s in record[ "strata" ].values() ) and record[ "found_in_slot_1" ] == 4
    assert record[ "plant_failures" ] == { "count": 0, "of": 3, "rate": 0.0, "pairs": [] }
    assert record[ "dropped_from_pool" ] == { "count": 0, "ids": [] }


def test_a_second_pass_that_changes_two_flags_lowers_agreement_to_fifty_eight_of_sixty_and_slot_one_finds_one_fewer(tmp_path):
    toy = Toy( tmp_path, backend=FakeBackend( flip="MARKA" ) )
    toy.wiring[ "backend" ].per_pass = len( pr.build_pool( toy.spec, 3 )[ "new" ] )
    toy.spec[ "labels" ] = toy.all_labels()
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "counts" ][ "both" ] == 60 and record[ "counts" ][ "agree" ] == 58 and record[ "bar" ][ "agreement" ][ "fraction" ] == "29/30"
    assert record[ "found_in_slot_1" ] == 3 and record[ "counts" ][ "found" ] == 4 and record[ "bar" ][ "passed" ] is True
    assert record[ "strata" ][ "fable_planted" ][ "found" ] == 1


def test_a_true_pair_the_checker_never_flags_drops_found_below_the_bar_and_the_run_fails(tmp_path):
    toy = Toy( tmp_path )
    toy.spec[ "labels" ] = { **toy.all_labels(), toy.key( "m1", "m5" ): True }
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "counts" ][ "true_pairs" ] == 6 and record[ "bar" ][ "found" ][ "fraction" ] == "2/3" and record[ "bar" ][ "passed" ] is False
    assert record[ "bar" ][ "correct" ][ "passes" ] is True and record[ "strata" ][ "monolith:nominated" ] == { "found": 0, "true": 1, "value": 0.0, "interval": record[ "strata" ][ "monolith:nominated" ][ "interval" ] }


# ---- statuses, plant failures and the kept record ---------------------------------------------------------------

def test_a_run_owing_labels_names_the_pairs_and_keeps_its_record_with_no_bar(tmp_path):
    toy    = Toy( tmp_path )
    toy.spec[ "labels" ] = { toy.key( "r1", "o1" ): True }
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "status" ] == "labels_pending" and "bar" not in record and "counts" not in record
    assert toy.key( "r1", "d3" ) in record[ "owed" ] and toy.key( "r3", "o3" ) in record[ "owed" ] and toy.key( "r1", "o1" ) not in record[ "owed" ]
    assert record[ "owed" ] == sorted( record[ "owed" ] )
    line = json.loads( ( tmp_path / "data" / "semdup" / "proof" / pr.LEDGER_FILE ).read_text( encoding="utf-8" ).splitlines()[ 0 ] )
    assert line[ "status" ] == "labels_pending" and line[ "passed" ] is None


def test_a_definition_the_judge_could_not_read_makes_the_run_incomplete_and_it_is_still_kept(tmp_path):
    toy    = Toy( tmp_path, backend=FakeBackend( garbage_after=0 ) )
    toy.spec[ "labels" ] = toy.all_labels()
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "status" ] == "incomplete" and len( record[ "unjudged" ][ 0 ] ) == record[ "pool" ][ "new" ] and "bar" not in record
    assert ( tmp_path / "data" / "semdup" / "proof" / "1.json" ).is_file()


def test_a_definition_unreadable_only_in_the_second_pass_still_makes_the_run_incomplete(tmp_path):
    toy       = Toy( tmp_path )
    new_count = len( pr.build_pool( toy.spec, 3 )[ "new" ] )
    toy.wiring[ "backend" ].garbage_after = new_count
    toy.spec[ "labels" ] = toy.all_labels()
    record    = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "unjudged" ][ 0 ] == [] and len( record[ "unjudged" ][ 1 ] ) == new_count
    assert record[ "status" ] == "incomplete" and "bar" not in record


def test_a_checker_that_raises_no_flag_is_recorded_as_no_flags_and_not_as_a_pass(tmp_path):
    toy    = Toy( tmp_path, backend=FakeBackend( never=True ) )
    toy.spec[ "labels" ] = toy.all_labels()
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "status" ] == "no_flags" and record[ "bar" ] is None and "no flag" in record[ "detail" ] and record[ "counts" ][ "flags" ] == 0
    line = json.loads( ( tmp_path / "data" / "semdup" / "proof" / pr.LEDGER_FILE ).read_text( encoding="utf-8" ).splitlines()[ 0 ] )
    assert line[ "status" ] == "no_flags" and line[ "passed" ] is None


def test_a_run_with_no_pair_labelled_true_is_recorded_as_no_true_pairs_with_both_files_written(tmp_path):
    toy    = Toy( tmp_path )
    toy.spec[ "labels" ] = { k: False for k in toy.all_labels() }
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "status" ] == "no_true_pairs" and record[ "bar" ] is None and record[ "counts" ][ "true_pairs" ] == 0 and record[ "counts" ][ "flags" ] > 0
    folder = tmp_path / "data" / "semdup" / "proof"
    line   = json.loads( ( folder / pr.LEDGER_FILE ).read_text( encoding="utf-8" ).splitlines()[ 0 ] )
    assert ( folder / "1.json" ).is_file() and line[ "status" ] == "no_true_pairs" and line[ "passed" ] is None


def test_a_run_with_no_pair_judged_in_both_passes_is_recorded_as_no_common_pairs(tmp_path, monkeypatch):
    toy = Toy( tmp_path )
    toy.spec[ "labels" ] = toy.all_labels()
    real = pr.proof_bar.agreement
    monkeypatch.setattr( pr.proof_bar, "agreement", lambda a, b: { **real( a, b ), "pairs_in_both": 0, "flag_agree": 0 } )
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "status" ] == "no_common_pairs" and record[ "bar" ] is None and ( tmp_path / "data" / "semdup" / "proof" / "1.json" ).is_file()


def test_a_planted_pair_both_reviewers_ruled_not_equivalent_leaves_every_denominator_and_is_counted(tmp_path):
    toy    = Toy( tmp_path )
    failed = toy.key( "r1", "o1" )
    toy.spec[ "plant_failures" ] = [ failed ]
    toy.spec[ "labels" ] = { k: v for k, v in toy.all_labels().items() if k != failed }
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "counts" ][ "true_pairs" ] == 4 and record[ "counts" ][ "found" ] == 3 and record[ "counts" ][ "flags" ] == 4 and record[ "counts" ][ "correct" ] == 3
    assert record[ "plant_failures" ] == { "count": 1, "of": 3, "rate": 1 / 3, "pairs": [ failed ] } and failed not in record.get( "owed", [] )
    assert record[ "bar" ][ "passed" ] is False


def test_every_run_is_kept_numbered_in_order_and_the_ledger_only_ever_grows(tmp_path):
    toy    = Toy( tmp_path )
    toy.spec[ "labels" ] = toy.all_labels()
    first  = pr.proof_run( toy.spec, toy.wiring )
    folder = tmp_path / "data" / "semdup" / "proof"
    ledger = folder / pr.LEDGER_FILE
    before = ledger.read_bytes()
    second = pr.proof_run( toy.spec, toy.wiring )
    after  = ledger.read_bytes()
    assert ( first[ "proof" ], second[ "proof" ] ) == ( 1, 2 ) and after.startswith( before ) and len( after.splitlines() ) == 2
    assert [ p.name for p in sorted( folder.glob( "*.json" ) ) ] == [ "1.json", "2.json" ]
    lines = [ json.loads( l ) for l in after.decode( "utf-8" ).splitlines() ]
    assert [ l[ "proof" ] for l in lines ] == [ 1, 2 ] and {l[ "config_sha" ] for l in lines} == { toy.cfg[ "config_sha" ] } and lines[ 0 ][ "passed" ] is True
    assert json.loads( ( folder / "1.json" ).read_text( encoding="utf-8" ) ) == json.loads( json.dumps( first, sort_keys=True ) )


def test_a_live_configuration_that_differs_from_the_frozen_one_stops_the_run_before_any_record(tmp_path):
    toy = Toy( tmp_path )
    toy.wiring[ "live" ] = { **toy.cfg, "body_chars": 1 }
    with pytest.raises( err.SemdupError ) as caught: pr.proof_run( toy.spec, toy.wiring )
    assert caught.value.code == err.CONFIG_DRIFT and not ( tmp_path / "data" ).exists()


def test_a_label_is_read_as_given_so_a_flag_labelled_false_counts_against_correct_only(tmp_path):
    toy = Toy( tmp_path )
    toy.spec[ "labels" ] = { **toy.all_labels(), toy.key( "r1", "d3" ): True }
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "counts" ][ "correct" ] == 5 and record[ "counts" ][ "true_pairs" ] == 5 and record[ "counts" ][ "found" ] == 4


def test_the_next_number_counts_from_one_and_ignores_files_that_are_not_numbered_records(tmp_path):
    assert pr.next_number( tmp_path ) == 1
    ( tmp_path / "1.json" ).write_text( "{}", encoding="utf-8" )
    ( tmp_path / "7.json" ).write_text( "{}", encoding="utf-8" )
    ( tmp_path / "notes.json" ).write_text( "{}", encoding="utf-8" )
    assert pr.next_number( tmp_path ) == 8


def test_append_ledger_adds_a_line_and_never_rewrites_the_ones_before_it(tmp_path):
    path = tmp_path / "l.jsonl"
    pr.append_ledger( path, { "n": 1 } )
    first = path.read_bytes()
    pr.append_ledger( path, { "n": 2 } )
    assert path.read_bytes().startswith( first ) and [ json.loads( l )[ "n" ] for l in path.read_text( encoding="utf-8" ).splitlines() ] == [ 1, 2 ]


def test_a_bar_error_other_than_no_flags_is_not_swallowed_into_a_record(tmp_path, monkeypatch):
    toy = Toy( tmp_path )
    toy.spec[ "labels" ] = toy.all_labels()
    def boom( counts ): raise err.SemdupError( err.RUN_INCOMPLETE, "unexpected" )
    monkeypatch.setattr( pr.proof_bar, "evaluate_bar", boom )
    with pytest.raises( err.SemdupError ) as caught: pr.proof_run( toy.spec, toy.wiring )
    assert caught.value.code == err.RUN_INCOMPLETE and list( ( tmp_path / "data" / "semdup" / "proof" ).glob( "*.json" ) ) == []


def test_a_proof_with_no_planted_pairs_reports_no_plant_failure_rate_and_still_judges_the_monolith(tmp_path):
    toy = Toy( tmp_path )
    toy.spec[ "planted" ] = []
    toy.spec[ "labels" ] = { toy.key( "m1", "m2" ): True, toy.key( "m3", "m4" ): True, toy.key( "m1", "m5" ): False }
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "plant_failures" ] == { "count": 0, "of": 0, "rate": None, "pairs": [] } and record[ "pool" ][ "size" ] == 8
    assert record[ "status" ] == "complete" and record[ "counts" ][ "true_pairs" ] == 2 and record[ "counts" ][ "found" ] == 2 and record[ "counts" ][ "flags" ] == 2
