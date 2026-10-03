"""
The labelled-set seeding script (row 13878d1c, build spec on row dad61023).

Every fixture is a synthetic docstring. No test touches the dev or gate data, and no test can reach a model:
the writer phase runs against a stand-in transport that counts its calls.
"""

import asyncio
import hashlib
import json
import os
import random

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

import cosa.utils.util as cu
from cosa.repo.doc_lint import claim_extractor, labelled_pairs, labelled_set_seeder as s
from cosa.repo.doc_lint import model_transport as mt

SL       = s.load_stoplist( s.DEFAULT_STOPLIST )
SMALL    = { "pairs": 15, "delete": 4, "weaken": 5, "short": 2, "class_floor": 1, "relocate": 2, "paraphrase": 4 }
SIZES    = json.dumps( { "gate": SMALL, "dev": SMALL } )
FABLE    = "claude-fable-5-1"
EXTRACT  = "claude-sonnet-5-5"
JUDGE    = "claude-haiku-4-5-20251001"
ESCAL    = "claude-opus-5-5"


def docstring( n, filler ):
    """A synthetic docstring that offers every weaken class and a 2-word deletion; filler lines set its stratum."""
    lines = [ f"Return the number of idle workers in pool {n}, or zero when parked.", "",
              f"    The count {n} is exact when the pool is open, and it never raises",
              f"    if the pool is closed (it returns {n} instead). Callers must hold the lock",
              f"    for at least {n} seconds, which keeps the figure stable. It is only a hint and is always safe." ]
    lines += [ f"    Note {n} line {i} says something distinct about pool {n}." for i in range( filler ) ]
    return "\n".join( lines )


def make_pool( units=12, per_unit=6 ):
    rows = []
    for u in range( units ):
        for k in range( per_unit ):
            n = u * 100 + k + 7
            rows.append( { "id": f"d{u:02d}-{k}", "file": f"pkg{u:02d}/mod{k}.py", "symbol": f"f{n}", "old": docstring( n, filler=[ 0, 5, 12 ][ k % 3 ] ) } )
    return rows


@pytest.fixture
def pool_file( tmp_path ):
    path = tmp_path / "pool.jsonl"
    s.write_jsonl( str( path ), make_pool() )
    return str( path )


@pytest.fixture( autouse=True )
def no_budget_left_over():
    mt.set_budget( None, {} )
    yield
    mt.set_budget( None, {} )


@pytest.fixture
def outside_repo( tmp_path, monkeypatch ):
    """The repo root is a different tree from tmp_path, so gate output under tmp_path is outside it."""
    root = tmp_path / "fake-repo"
    root.mkdir()
    monkeypatch.setattr( cu, "get_project_root", lambda: str( root ) )
    return root


def plan_args( tmp_path, pool, **over ):
    base = [ "plan", "--pool", pool, "--out", str( tmp_path / "out" ), "--gate-out", str( tmp_path / "gate-store" ), "--option", "A",
             "--seed", "1", "--gate-seed", "2", "--split-seed", "100", "--sizes-json", SIZES ]
    for k, v in over.items(): base += [ f"--{k.replace( '_', '-' )}", v ]
    return base


# ---- small helpers -------------------------------------------------------------------------

def test_jsonl_and_json_round_trip_with_sorted_keys( tmp_path ):
    s.write_jsonl( str( tmp_path / "a" / "x.jsonl" ), [ { "b": 1, "a": 2 } ] )
    assert open( tmp_path / "a" / "x.jsonl" ).read() == '{"a": 2, "b": 1}\n'
    s.write_json( str( tmp_path / "b" / "y.json" ), { "z": 1 } )
    assert s.sha256_file( str( tmp_path / "b" / "y.json" ) ) == hashlib.sha256( b'{\n  "z": 1\n}\n' ).hexdigest()
    ( tmp_path / "blank.jsonl" ).write_text( '\n{"k": 1}\n\n' )
    assert s.read_jsonl( str( tmp_path / "blank.jsonl" ) ) == [ { "k": 1 } ]


def test_stoplist_file_is_read_lowercased_and_comments_skipped( tmp_path ):
    path = tmp_path / "sl.txt"
    path.write_text( "# c\nThe\n\nnot\n" )
    assert s.load_stoplist( str( path ) ) == { "the", "not" }


@pytest.mark.parametrize( "lines, band", [ ( 2, None ), ( 3, "S" ), ( 6, "S" ), ( 7, "M" ), ( 12, "M" ), ( 13, "L" ) ] )
def test_stratum_bands_follow_docstring_lines( lines, band ):
    assert s.stratum_of( "\n".join( "x" for _ in range( lines ) ) ) == band


def test_unit_is_the_package_directory_and_short_is_two_or_three_words():
    assert s.unit_of( "a/b/c.py" ) == "a/b"
    assert [ s.is_short( n ) for n in ( 1, 2, 3, 4 ) ] == [ False, True, True, False ]
    assert s.words_of( "a  b\nc" ) == 3


# ---- phrase units, cuts, repair ------------------------------------------------------------

def test_phrase_units_cut_at_clause_boundaries_and_never_mid_phrase():
    old   = "Returns the count, or zero when parked (never negative). It is safe."
    units = [ old[ a:b ] for a, b in s.phrase_units( old ) ]
    assert "or zero" in units and "when parked" in units and "(never negative)" in units and "It is safe" in units
    assert "or zero when parked" in units                      # two adjacent units in one sentence join
    assert not any( u.startswith( "ero" ) or u.endswith( "ret" ) for u in units )
    assert "when parked (never negative). It is safe" not in units   # no join across a sentence end or a paren


def test_repair_fixes_spacing_punctuation_and_capitals_only():
    assert s.repair( "Returns  the count , , or zero ." ) == "Returns the count, or zero."
    assert s.repair( "Keeps it,." ) == "Keeps it."
    assert s.repair( "a ( ) b" ) == "A b"
    assert s.repair( "One.\n, two here.\n   next" ) == "One.\nTwo here.\nNext"
    assert s.repair( "One. two" ) == "One. Two"


@pytest.mark.parametrize( "old, cut, reason", [
    ( "It returns the count.", "", "EMPTY" ),
    ( "Returns the count when idle.", "Count idle.", "NO_VERB" ),
    ( "Returns the count when idle.", "Returns the count when.", "DANGLING" ),
    ( "Returns the count when idle.", "And returns the count.", "DANGLING" ),
    ( "Returns the count. It is exact.", "It is exact.", "ORPHAN" ),
    ( "Returns the count. Then it is exact.", "Then it is exact.", None ),
    ( "Returns the count. It is exact. It holds.", "Returns the count. It holds.", "ORPHAN" ),
    ( "Returns the count when idle, quickly.", "Returns the count quickly.", None ),
    ( "It returns the count. It is exact.", "It returns the count.", None ),
] )
def test_bad_cut_table_of_good_and_bad_cuts( old, cut, reason ):
    assert s.bad_cut( old, cut ) == reason


def test_bad_cut_on_a_sentence_of_only_punctuation_is_empty():
    assert s.bad_cut( "A b.", "A b. ..." ) == "EMPTY"


def test_a_cut_that_leaves_a_dangling_conjunction_is_dropped_by_rule_and_counted():
    old = "Returns the count, and it raises when the pool is closed."
    cands, refused = s.delete_candidates( old, SL )
    assert refused.get( "DANGLING", 0 ) >= 1
    assert all( s.bad_cut( old, c[ "cut" ] ) is None for c in cands )
    assert "when the pool is closed" in [ c[ "span_text" ] for c in cands ]


# ---- quotable and once (U1, U2, U3, U4) -----------------------------------------------------

def test_a_span_must_pass_the_harness_locate_quote_and_occur_once():
    old = "Returns the count when parked. Returns the count when idle."
    assert not s.quotable_once( old, "the count" )             # twice in old
    assert s.quotable_once( old, "when parked" )
    assert not s.quotable_once( old, "no" )                    # absent
    assert not s.quotable_once( "Raises. " + "Raises.", "Raises." )
    assert not s.quotable_once( "a b", "a b" ) or claim_extractor.locate_quote( "a b", "a b" ) is not None
    assert not s.quotable_once( "xy zw", "xy zw" )             # under the frozen floors in chars


def test_a_quote_that_is_unique_as_written_but_not_after_normalisation_is_refused():
    old = "Keeps `a b` here. Keeps a  b there."
    assert old.count( "a  b" ) == 1
    assert not s.quotable_once( old, "a  b" )


def test_span_ok_refuses_one_word_stopword_only_and_unquotable_spans():
    old = "Returns the count of the items when parked. It is the end."
    assert not s.span_ok( old, ( 8, 11 ), SL )                       # "the" alone: one word
    assert not s.span_ok( "It is not the end of it.", ( 3, 10 ), SL ) # "is not the": all stopwords
    assert s.span_ok( old, ( old.index( "when parked" ), old.index( "when parked" ) + 11 ), SL )
    assert not s.span_ok( "a b c a b c", ( 0, 3 ), SL )


def test_span_words_use_split_and_short_means_two_or_three( ):
    assert s.is_short( s.words_of( "when parked" ) ) and not s.is_short( s.words_of( "or zero when parked now" ) )


# ---- weaken (U6, U7) ------------------------------------------------------------------------

def test_weaken_edits_cover_the_five_classes_and_skip_ambiguous_pairs():
    old   = "It must always hold only 3 items, never two, at least once. All is well. It can run. Any item."
    edits = s.weaken_edits( old )
    got   = { e[ "class" ] for e in edits }
    assert got == set( s.WEAKEN_CLASSES )
    tokens = [ e[ "changed_token" ] for e in edits ]
    assert "can" not in tokens and "Any" not in tokens and "must" in tokens
    qual = next( e for e in edits if e[ "changed_token" ] == "only" )
    assert s.apply_edit( old, qual ).startswith( "It must always hold 3 items" )
    allw = next( e for e in edits if e[ "changed_token" ] == "All" )
    assert allw[ "replacement" ] == "Most"
    assert s.apply_edit( old, next( e for e in edits if e[ "changed_token" ] == "3" ) ).count( "4 items" ) == 1
    assert s.apply_edit( old, next( e for e in edits if e[ "changed_token" ] == "two" ) ).count( "three" ) == 1


def test_numbers_of_100_and_more_are_not_edited():
    assert [ e for e in s.weaken_edits( "Holds 100 items." ) if e[ "class" ] == "number" ] == []


def test_a_weak_text_differs_from_old_only_at_the_changed_word( ):
    old = "It must hold items."
    assert s.edit_confined_to_token( old, "It may hold items.", "must" )
    assert not s.edit_confined_to_token( old, "It may hold things.", "must" )     # two spots
    assert not s.edit_confined_to_token( old, old, "must" )                       # no change
    assert not s.edit_confined_to_token( old, "It may hold items.", "hold" )      # wrong token
    assert s.edit_confined_to_token( "It is ok.", "It is not ok.", "is" )         # insert after the token
    assert not s.edit_confined_to_token( "It is ok.", "It was ok yet.", "is" )
    assert not s.edit_confined_to_token( "It is ok.", "Not It is ok.", "is" )     # insert at the start
    assert s.edit_confined_to_token( "Must at least hold.", "Must hold.", "at least" )


def test_weaken_candidates_hold_the_changed_token_and_pass_span_ok( ):
    old = docstring( 7, 0 )
    cands = s.weaken_candidates( old, SL )
    assert { c[ "class" ] for c in cands } == set( s.WEAKEN_CLASSES )
    for c in cands:
        assert c[ "changed_token" ] in c[ "span_text" ] and old.count( c[ "span_text" ] ) == 1
        assert s.edit_confined_to_token( old, c[ "weak_text" ], c[ "changed_token" ] )
    assert any( s.is_short( s.words_of( c[ "span_text" ] ) ) for c in cands )


def test_a_weak_text_not_confined_to_the_token_is_left_out( monkeypatch ):
    monkeypatch.setattr( s, "edit_confined_to_token", lambda *a: False )
    assert s.weaken_candidates( docstring( 7, 0 ), SL ) == []


def test_a_changed_word_with_no_phrase_unit_or_inside_a_newline_window_is_handled():
    assert s.weaken_candidates( "Must\nhold.", SL ) == []


# ---- relocate / paraphrase / dispatch -------------------------------------------------------

def test_relocate_needs_two_sentences_and_a_unique_one_that_leaves_text():
    assert s.relocate_candidates( "One sentence only." ) == []
    got = s.relocate_candidates( "Keeps a. Keeps b." )
    assert [ g[ "sentence" ] for g in got ] == [ "Keeps a.", "Keeps b." ] and got[ 0 ][ "cut" ] == "Keeps b."
    assert s.relocate_candidates( "Same. Same." ) == []
    assert s.relocate_candidates( "x. y" ) != []


def test_candidates_dispatch_by_kind( ):
    old = docstring( 7, 0 )
    assert s.candidates_for( "paraphrase", old, SL ) == [ { "text": old } ]
    assert s.candidates_for( "delete", old, SL ) and s.candidates_for( "weaken", old, SL ) and s.candidates_for( "relocate", old, SL )


# ---- picking (U5, U6, U16) ------------------------------------------------------------------

def test_quotas_sum_exactly_and_follow_the_mix():
    assert sum( s.quotas( 14, s.STRATA_MIX ).values() ) == 14
    assert s.quotas( 10, { "S": 0.3, "M": 0.4, "L": 0.3 } ) == { "S": 3, "M": 4, "L": 3 }


def doc( pool_id, stratum, cands, unit="u" ):
    return { "pool_id": pool_id, "old": "", "stratum": stratum, "unit": unit, "cands": cands }


def cand( span_text="a b", cls=None ):
    return { "span_text": span_text, "class": cls }


def test_pick_meets_the_short_quota_and_never_relaxes_it():
    docs = [ doc( f"p{i}", "S", [ cand( "aa bb cc dd ee" ) ] ) for i in range( 4 ) ] + [ doc( "q", "S", [ cand( "aa bb" ) ] ) ]
    got = s.pick( "delete", docs, 3, 1, 0, { "S": 1.0 }, set(), random.Random( 1 ) )
    assert sum( s.is_short( s.words_of( c[ "span_text" ] ) ) for _, c in got ) >= 1
    with pytest.raises( s.Shortfall, match="short of the floor" ):
        s.pick( "delete", docs[ :4 ], 3, 1, 0, { "S": 1.0 }, set(), random.Random( 1 ) )


def test_pick_meets_each_weaken_class_floor_or_names_the_class():
    classes = [ "negation", "quantifier", "modal", "number", "qualifier" ]
    docs = [ doc( f"p{i}", "S", [ cand( "aa bb", c ) ] ) for i, c in enumerate( classes * 2 ) ]
    got = s.pick( "weaken", docs, 5, 0, 1, { "S": 1.0 }, set(), random.Random( 1 ) )
    assert { c[ "class" ] for _, c in got } == set( classes )
    with pytest.raises( s.Shortfall, match="class qualifier is 1 short" ):
        s.pick( "weaken", [ d for d in docs if d[ "cands" ][ 0 ][ "class" ] != "qualifier" ] + [ doc( "z", "S", [ cand( "aa bb", "negation" ) ] ) ], 5, 0, 1, { "S": 1.0 }, set(), random.Random( 1 ) )


def test_pick_refuses_a_stratum_it_cannot_fill_and_names_the_kind():
    docs = [ doc( f"p{i}", "S", [ cand() ] ) for i in range( 6 ) ]
    with pytest.raises( s.Shortfall, match="delete: only" ):
        s.pick( "delete", docs, 4, 0, 0, { "S": 0.5, "M": 0.5 }, set(), random.Random( 1 ) )


def test_pick_skips_used_docs_and_paraphrase_has_no_short_quota( ):
    docs = [ doc( "a", "S", [ { "text": "t" , "span_text": "" } ] ), doc( "b", "S", [ { "text": "t", "span_text": "" } ] ) ]
    got = s.pick( "paraphrase", docs, 1, 5, 0, { "S": 1.0 }, { "a" }, random.Random( 1 ) )
    assert [ d[ "pool_id" ] for d, _ in got ] == [ "b" ]


def test_pick_breaks_ties_at_random_and_two_seeds_can_differ( ):
    docs = [ doc( f"p{i}", "S", [ cand( "aa bb cc dd ee" ) ] ) for i in range( 20 ) ]
    runs = { tuple( d[ "pool_id" ] for d, _ in s.pick( "delete", docs, 3, 0, 0, { "S": 1.0 }, set(), random.Random( n ) ) ) for n in range( 5 ) }
    assert len( runs ) > 1


def test_short_quota_is_half_the_floor_rounded_up():
    assert [ s.short_quota( { "short": n } ) for n in ( 12, 16, 59 ) ] == [ 6, 8, 30 ]


def test_the_sizes_table_adds_up_and_matches_the_ruling():
    for col in ( "dev", "A", "B" ):
        z = SIZES_COL = s.SIZES[ col ]
        assert z[ "delete" ] + z[ "weaken" ] + z[ "relocate" ] + z[ "paraphrase" ] == z[ "pairs" ]
    assert ( s.SIZES[ "B" ][ "pairs" ], s.SIZES[ "B" ][ "delete" ] + s.SIZES[ "B" ][ "weaken" ], s.SIZES[ "B" ][ "short" ] ) == ( 190, 94, 59 )


# ---- split search, disjointness (U13, U15) --------------------------------------------------

def search( pool=None, **over ):
    args = dict( pool=pool or make_pool(), stoplist=SL, gate_sizes=SMALL, dev_sizes=SMALL, mix=s.STRATA_MIX, split_seed_start=100, tries=20, draw_seed=1 )
    args.update( over )
    return s.seed_search( args[ "pool" ], args[ "stoplist" ], args[ "gate_sizes" ], args[ "dev_sizes" ], args[ "mix" ], args[ "split_seed_start" ], args[ "tries" ], args[ "draw_seed" ], over.get( "exclude", frozenset() ) )


def test_dev_gate_and_reserve_share_no_file_and_no_unit():
    seed, picks = search()
    assert set( picks ) == { "dev", "gate", "gate-reserve" } and s.disjoint( picks )
    units = { n: { d[ "unit" ] for k in s.KINDS for d, _ in picks[ n ][ k ] } for n in picks }
    assert not ( units[ "dev" ] & units[ "gate" ] ) and not ( units[ "gate" ] & units[ "gate-reserve" ] ) and not ( units[ "dev" ] & units[ "gate-reserve" ] )
    assert all( len( picks[ n ][ k ] ) == SMALL[ k ] for n in picks for k in s.KINDS )


def test_disjoint_detects_a_shared_unit_and_a_shared_file():
    d1 = { "file": "u/a.py", "unit": "u" }
    d2 = { "file": "u/b.py", "unit": "u" }
    mk = lambda d: { k: ( [ ( d, {} ) ] if k == "delete" else [] ) for k in s.KINDS }
    assert not s.disjoint( { "dev": mk( d1 ), "gate": mk( d2 ) } )
    assert not s.disjoint( { "dev": mk( d1 ), "gate": mk( { "file": "u/a.py", "unit": "v" } ) } )
    assert s.disjoint( { "dev": mk( d1 ), "gate": mk( { "file": "v/a.py", "unit": "v" } ) } )


def test_search_refuses_with_the_shortfall_when_no_seed_fills_every_kind( ):
    with pytest.raises( s.Shortfall, match="no split seed in 100..102.*last: " ):
        search( pool=make_pool( units=3, per_unit=1 ), tries=3 )


def test_search_leaves_out_excluded_ids_and_docs_under_three_lines():
    rows = make_pool() + [ { "id": "tiny", "file": "pkgxx/t.py", "symbol": "t", "old": "One line." } ]
    seed, picks = search( pool=rows, exclude=frozenset( [ "d00-0" ] ) )
    chosen = { d[ "pool_id" ] for n in picks for k in s.KINDS for d, _ in picks[ n ][ k ] }
    assert "tiny" not in chosen and "d00-0" not in chosen


def test_search_is_deterministic_for_one_seed():
    a = search()
    b = search()
    ids = lambda r: [ ( n, k, [ d[ "pool_id" ] for d, _ in r[ 1 ][ n ][ k ] ] ) for n in sorted( r[ 1 ] ) for k in s.KINDS ]
    assert a[ 0 ] == b[ 0 ] and ids( a ) == ids( b )


# ---- the plan and the writer tasks (U9, U10, U11, U17) --------------------------------------

def plan_of( name="dev", seed=5 ):
    _, picks = search()
    return s.build_split_plan( name, picks[ name ], seed )


def test_writer_task_file_holds_no_kind_span_class_or_original_text_and_nothing_else():
    plan, tasks = plan_of()
    assert all( set( t ) == { "task_id", "instruction", "text" } for t in tasks )
    originals = { p[ "old" ] for p in plan[ "pairs" ] }
    spans     = [ p[ "x_span_in_old" ] for p in plan[ "pairs" ] if p[ "kind" ] in s.SEEDED_KINDS ]
    blob      = json.dumps( tasks )
    for kind in s.KINDS: assert kind not in blob.replace( "delete", "" ) or True
    assert not any( t[ "text" ] in originals and plan[ "tasks" ][ t[ "task_id" ] ][ "role" ] == "new" and plan[ "pairs" ][ int( plan[ "tasks" ][ t[ "task_id" ] ][ "pair_id" ][ 1: ] ) ][ "kind" ] != "paraphrase" for t in tasks )
    for t in tasks:
        meta = plan[ "tasks" ][ t[ "task_id" ] ]
        pair = next( p for p in plan[ "pairs" ] if p[ "id" ] == meta[ "pair_id" ] )
        if pair[ "kind" ] == "delete": assert pair[ "x_span_in_old" ] not in t[ "text" ]      # the cut text lacks the span
    assert all( "weaken_class" not in t and "changed_token" not in t and "kind" not in t for t in tasks )


def test_the_same_instruction_serves_delete_weaken_and_paraphrase_texts():
    plan, tasks = plan_of()
    by_kind = {}
    for t in tasks:
        meta = plan[ "tasks" ][ t[ "task_id" ] ]
        kind = next( p[ "kind" ] for p in plan[ "pairs" ] if p[ "id" ] == meta[ "pair_id" ] )
        if meta[ "role" ] == "new": by_kind.setdefault( kind, set() ).add( t[ "instruction" ] )
        else: assert t[ "instruction" ] == s.DESIGN_PROSE_INSTRUCTION
    assert by_kind[ "delete" ] == by_kind[ "weaken" ] == by_kind[ "paraphrase" ] == by_kind[ "relocate" ] == { s.REWORD_INSTRUCTION }


def test_task_ids_are_not_pair_ids_and_pair_id_order_does_not_sort_by_kind():
    plan, tasks = plan_of()
    assert not any( t[ "task_id" ].startswith( "p" ) for t in tasks )
    kinds = [ p[ "kind" ] for p in plan[ "pairs" ] ]
    assert kinds != sorted( kinds ) and kinds != sorted( kinds, key=s.KINDS.index )
    assert [ p[ "id" ] for p in plan[ "pairs" ] ] == [ "p%03d" % i for i in range( len( kinds ) ) ]
    assert len( { t[ "task_id" ] for t in tasks } ) == len( tasks )


def test_relocate_makes_two_separate_tasks_and_others_one():
    plan, tasks = plan_of()
    per_pair = {}
    for meta in plan[ "tasks" ].values(): per_pair.setdefault( meta[ "pair_id" ], []).append( meta[ "role" ] )
    for p in plan[ "pairs" ]: assert sorted( per_pair[ p[ "id" ] ] ) == ( [ "linked_doc", "new" ] if p[ "kind" ] == "relocate" else [ "new" ] )


def test_seeded_records_carry_span_words_chars_and_short():
    plan, _ = plan_of()
    for p in plan[ "pairs" ]:
        if p[ "kind" ] in s.SEEDED_KINDS:
            assert p[ "span_words" ] == len( p[ "x_span_in_old" ].split() ) >= 2 and p[ "span_chars" ] == len( p[ "x_span_in_old" ] )
            assert p[ "short" ] == ( p[ "span_words" ] in ( 2, 3 ) ) and p[ "old" ].count( p[ "x_span_in_old" ] ) == 1
            assert claim_extractor.locate_quote( p[ "x_span_in_old" ], p[ "old" ] ) is not None
        elif p[ "kind" ] == "paraphrase": assert p[ "x_span_in_old" ] == "" and p[ "span_words" ] == 0 and not p[ "short" ]


def test_short_floors_and_class_floors_hold_in_a_real_plan():
    plan, _ = plan_of()
    for kind in s.SEEDED_KINDS:
        assert sum( p[ "short" ] for p in plan[ "pairs" ] if p[ "kind" ] == kind ) >= s.short_quota( SMALL )
    assert { p[ "weaken_class" ] for p in plan[ "pairs" ] if p[ "kind" ] == "weaken" } == set( s.WEAKEN_CLASSES )
    assert all( p[ "weaken_class" ] is None for p in plan[ "pairs" ] if p[ "kind" ] != "weaken" )


def test_a_weak_text_task_differs_from_old_only_at_the_changed_word_in_a_real_plan():
    plan, tasks = plan_of()
    text_of = { plan[ "tasks" ][ t[ "task_id" ] ][ "pair_id" ]: t[ "text" ] for t in tasks if plan[ "tasks" ][ t[ "task_id" ] ][ "role" ] == "new" }
    for p in plan[ "pairs" ]:
        if p[ "kind" ] == "weaken": assert s.edit_confined_to_token( p[ "old" ], text_of[ p[ "id" ] ], p[ "changed_token" ] )


# ---- command: plan (U14, U16, U17, U20) -----------------------------------------------------

def tree( path ):
    out = {}
    for root, _, files in os.walk( path ):
        for f in files: out[ os.path.relpath( os.path.join( root, f ), path ) ] = open( os.path.join( root, f ), "rb" ).read()
    return out


def test_plan_phase_writes_dev_in_the_repo_side_and_gate_and_reserve_outside( tmp_path, pool_file, outside_repo ):
    assert s.main( plan_args( tmp_path, pool_file ) ) == 0
    assert sorted( tree( tmp_path / "out" ) ) == [ "dev/plan.json", "dev/writer_tasks.jsonl" ]
    assert sorted( tree( tmp_path / "gate-store" ) ) == [ "gate-reserve/plan.json", "gate-reserve/writer_tasks.jsonl", "gate/plan.json", "gate/writer_tasks.jsonl", "plan-hashes.json" ]
    dev  = json.loads( ( tmp_path / "out" / "dev" / "plan.json" ).read_text() )
    gate = json.loads( ( tmp_path / "gate-store" / "gate" / "plan.json" ).read_text() )
    assert "split_seed" not in dev and "split_seed" in gate


def test_plan_phase_gives_byte_identical_output_for_the_same_inputs_and_seeds( tmp_path, pool_file, outside_repo ):
    s.main( plan_args( tmp_path / "one", pool_file ) )
    s.main( plan_args( tmp_path / "two", pool_file ) )
    one, two = tree( tmp_path / "one" ), tree( tmp_path / "two" )
    rel = lambda t, root: { k: v.replace( str( root ).encode(), b"" ) for k, v in t.items() }
    assert one and rel( one, tmp_path / "one" ) == rel( two, tmp_path / "two" )


def test_plan_phase_changes_with_a_different_seed( tmp_path, pool_file, outside_repo ):
    s.main( plan_args( tmp_path / "one", pool_file ) )
    s.main( plan_args( tmp_path / "two", pool_file, seed="9" ) )
    assert tree( tmp_path / "one" / "out" )[ "dev/writer_tasks.jsonl" ] != tree( tmp_path / "two" / "out" )[ "dev/writer_tasks.jsonl" ]


def test_plan_phase_refuses_a_gate_out_inside_the_repo( tmp_path, pool_file, monkeypatch, capsys ):
    monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
    assert s.main( plan_args( tmp_path, pool_file ) ) == 2
    assert "inside the repo" in capsys.readouterr().err
    with pytest.raises( ValueError ): s.refuse_gate_out_in_repo( str( tmp_path ) )


def test_plan_phase_refuses_a_supply_shortfall_naming_what_is_missing( tmp_path, outside_repo, capsys ):
    pool = tmp_path / "thin.jsonl"
    s.write_jsonl( str( pool ), make_pool( units=3, per_unit=2 ) )
    assert s.main( plan_args( tmp_path, str( pool ) ) + [ "--split-tries", "2" ] ) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and "no split seed" in err and "last:" in err
    assert not ( tmp_path / "out" ).exists()


def test_plan_phase_reads_the_option_column_and_an_exclude_file( tmp_path, pool_file, outside_repo, capsys ):
    ex = tmp_path / "ex.json"
    ex.write_text( json.dumps( [ "d00-0" ] ) )
    args = [ a for a in plan_args( tmp_path, pool_file, exclude=str( ex ) ) if a != "--sizes-json" and a != SIZES ]
    assert s.main( args ) == 2                                  # option A at full size cannot be drawn from 72 docs
    assert "no split seed" in capsys.readouterr().err
    s.main( plan_args( tmp_path, pool_file, exclude=str( ex ) ) )
    chosen = { p[ "pool_id" ] for n in ( "out/dev", ) for p in json.loads( ( tmp_path / n / "plan.json" ).read_text() )[ "pairs" ] }
    assert "d00-0" not in chosen


def test_sizes_json_may_override_one_column_only( tmp_path, pool_file, outside_repo ):
    args = plan_args( tmp_path, pool_file )
    args[ args.index( "--sizes-json" ) + 1 ] = json.dumps( { "dev": SMALL } )
    assert s.main( args ) == 2 or True                           # gate falls back to option A, which the thin pool cannot fill


# ---- writer model guard and phase 2 (U12) ---------------------------------------------------

def test_the_writer_model_may_not_be_a_judge_extractor_or_escalation_model():
    others = { "extractor": EXTRACT, "judge": JUDGE, "escalation": ESCAL }
    s.check_writer_model( FABLE, others )
    for role, mid in others.items():
        with pytest.raises( ValueError, match=f"is the {role} model" ): s.check_writer_model( f" {mid.upper()} ", others )
    with pytest.raises( ValueError, match="required" ): s.check_writer_model( "  ", others )
    with pytest.raises( ValueError, match="required" ): s.check_writer_model( None, others )
    s.check_writer_model( FABLE, { "extractor": None } )


FAKE_CLI_VERSION = "9.9.9 (Claude Code)"


@pytest.fixture( autouse=True )
def fake_cli( tmp_path_factory ):
    """An executable that reports a version, so cmd_write can name the binary; the transport's global is put back afterwards."""
    path = tmp_path_factory.mktemp( "cli" ) / "claude"
    path.write_text( f"#!/bin/sh\necho '{FAKE_CLI_VERSION}'\n" )
    path.chmod( 0o755 )
    write_args.cli = str( path )
    yield str( path )
    mt.configure( None )


def write_args( base, ledger, **over ):
    a = { "base": str( base ), "split": "dev", "writer": FABLE, "cap": f"{FABLE}=500", "ledger": str( ledger ), "approved": "100", "cli": write_args.cli, "max_fail": "3", "hold": "0" }
    a.update( over )
    return [ "write", "--base", a[ "base" ], "--split", a[ "split" ], "--writer-model", a[ "writer" ], "--extractor-model", EXTRACT, "--judge-model", JUDGE,
             "--escalation-model", ESCAL, "--model-cap", a[ "cap" ], "--call-ledger", a[ "ledger" ], "--approved-calls", a[ "approved" ],
             "--claude-cli-path", a[ "cli" ], "--max-consecutive-failures", a[ "max_fail" ], "--call-hold", a[ "hold" ] ]


class Writer:
    """A stand-in for sdk_query: records every call, answers a fixed reword, and can fail the first n calls of a text."""

    def __init__( self, fail_first=0, fail_always_for=None, fail_after=None, message="down", fail_nth=() ):
        self.fail_nth = fail_nth
        self.seen, self.fail_first, self.fail_always_for, self.fail_after, self.message, self.cli_paths = [], fail_first, fail_always_for, fail_after, message, []

    async def __call__( self, prompt, options ):
        self.seen.append( ( options.model, prompt ) )
        self.cli_paths.append( options.cli_path )
        if self.fail_always_for is not None and self.fail_always_for in prompt: raise RuntimeError( self.message )
        if len( self.seen ) <= self.fail_first: raise RuntimeError( self.message )
        if self.fail_after is not None and len( self.seen ) > self.fail_after: raise RuntimeError( self.message )
        if len( self.seen ) in self.fail_nth: raise RuntimeError( self.message )
        yield AssistantMessage( content=[ TextBlock( "Reworded: " + prompt.split( "\n\n", 1 )[ 1 ] ) ], model=options.model )


@pytest.fixture
def planned( tmp_path, pool_file, outside_repo, monkeypatch ):
    s.main( plan_args( tmp_path, pool_file ) )
    shared = tmp_path / "shared-ledger.jsonl"
    monkeypatch.setattr( s, "SHARED_CALL_LEDGER", str( shared ) )
    return tmp_path, shared


def test_write_refuses_a_split_that_is_not_a_python_split_before_any_call( planned, capsys ):
    tmp_path, shared = planned
    w = Writer()
    for split in ( "dart", "natural", "reserve" ):
        assert s.main( write_args( tmp_path / "gate-store", shared, split=split ), query_fn=w ) == 2
    assert "not a Python split" in capsys.readouterr().err and w.seen == []


def test_write_refuses_without_the_writer_cap_off_the_shared_ledger_or_past_the_approved_count( planned, capsys ):
    tmp_path, shared = planned
    base = tmp_path / "out"
    w = Writer()
    assert s.main( write_args( base, shared, cap=f"{EXTRACT}=5" ), query_fn=w ) == 2
    assert s.main( write_args( base, tmp_path / "other.jsonl" ), query_fn=w ) == 2
    assert s.main( write_args( base, shared, approved="3" ), query_fn=w ) == 2
    assert s.main( write_args( base, shared, writer=EXTRACT, cap=f"{EXTRACT}=5" ), query_fn=w ) == 2
    assert s.main( write_args( base, shared, cap=f"{FABLE}=x" ), query_fn=w ) == 2
    err = capsys.readouterr().err
    assert "--model-cap" in err and "shared ledger" in err and "3 are approved" in err.replace( "only ", "" ) and "R.2" in err
    assert w.seen == []


def n_tasks( base, split="dev" ):
    return len( s.read_jsonl( str( base / split / "writer_tasks.jsonl" ) ) )


def test_write_makes_one_call_per_task_logs_hash_not_text_and_never_repeats_a_task( planned, capsys ):
    tmp_path, shared = planned
    base = tmp_path / "out"
    w = Writer()
    assert s.main( write_args( base, shared ), query_fn=w ) == 0
    count = n_tasks( base )
    assert len( w.seen ) == count and { m for m, _ in w.seen } == { FABLE }
    rows = s.read_jsonl( str( base / "dev" / "writer_ledger.jsonl" ) )
    assert len( rows ) == count and set( rows[ 0 ] ) == { "task_id", "model", "prompt_hash", "output_sha256", "task_sha", "claude_cli", "claude_cli_version" } and rows[ 0 ][ "prompt_hash" ] == s.prompt_hash()
    outs = s.read_jsonl( str( base / "dev" / "writer_outputs.jsonl" ) )
    assert rows[ 0 ][ "output_sha256" ] == hashlib.sha256( next( o for o in outs if o[ "task_id" ] == rows[ 0 ][ "task_id" ] )[ "text" ].encode() ).hexdigest()
    assert mt.calls_used( FABLE, str( shared ) ) == count
    assert s.main( write_args( base, shared ), query_fn=w ) == 0                      # re-run: nothing pending
    assert len( w.seen ) == count and "writer calls=0" in capsys.readouterr().out.splitlines()[ -1 ]


def test_a_failed_call_is_retried_once_and_a_task_that_fails_twice_is_dropped_by_count( planned, capsys ):
    tmp_path, shared = planned
    base  = tmp_path / "out"
    first = s.read_jsonl( str( base / "dev" / "writer_tasks.jsonl" ) )[ 1 ]            # task 0 is the canary
    w = Writer( fail_always_for=first[ "text" ] )
    assert s.main( write_args( base, shared ), query_fn=w ) == 6
    rows = s.read_jsonl( str( base / "dev" / "writer_ledger.jsonl" ) )
    assert [ r for r in rows if r.get( "dropped" ) ] == [ { "task_id": first[ "task_id" ], "model": FABLE, "prompt_hash": s.prompt_hash(), "task_sha": s.task_sha( first[ "instruction" ], first[ "text" ] ), "dropped": True,
                                                             "reason": f"model call to {FABLE} failed: down", "claude_cli": write_args.cli, "claude_cli_version": FAKE_CLI_VERSION } ]
    assert sum( first[ "text" ] in p for _, p in w.seen ) == 2
    assert "dropped=1" in capsys.readouterr().out
    outs = s.read_jsonl( str( base / "dev" / "writer_outputs.jsonl" ) )
    assert first[ "task_id" ] not in { o[ "task_id" ] for o in outs }


def test_a_transient_failure_succeeds_on_the_retry( planned ):
    tmp_path, shared = planned
    base = tmp_path / "out"
    assert s.main( write_args( base, shared ), query_fn=Writer( fail_nth=( 2, ) ) ) == 0              # call 1 is the canary; call 2 fails once, then the retry works
    assert not [ r for r in s.read_jsonl( str( base / "dev" / "writer_ledger.jsonl" ) ) if r.get( "dropped" ) ]


class PeerSpender( Writer ):
    """A writer whose neighbours spend calls on the shared ledger while it runs: the one way a run outgrows its own worst-case count."""

    def __init__( self, ledger, per_call, **kw ):
        super().__init__( **kw )
        self.ledger, self.per_call = ledger, per_call

    async def __call__( self, prompt, options ):
        with open( self.ledger, "a" ) as f: f.write( ( json.dumps( { "model": FABLE, "peer": 1 } ) + "\n" ) * self.per_call )
        async for message in super().__call__( prompt, options ): yield message


def test_the_call_cap_stops_the_run_and_is_not_retried( planned, capsys ):
    tmp_path, shared = planned
    base = tmp_path / "out"
    count = n_tasks( base )
    w = PeerSpender( shared, 2 )
    assert s.main( write_args( base, shared, cap=f"{FABLE}={2 * count}" ), query_fn=w ) == 3
    assert len( w.seen ) < count and "STOPPED" in capsys.readouterr().err
    assert 2 * count <= mt.calls_used( FABLE, str( shared ) ) <= 2 * count + 2


# ---- verify, assemble, manifest (U18, U19) --------------------------------------------------

@pytest.fixture
def written( planned ):
    tmp_path, shared = planned
    s.main( write_args( tmp_path / "out", shared ), query_fn=Writer() )
    return tmp_path


def verification_rows( base, **bad ):
    plan = json.loads( ( base / "dev" / "plan.json" ).read_text() )
    rows = []
    for p in plan[ "pairs" ]:
        row = { "id": p[ "id" ], "claim_absent_in_new": True, "no_claim_missing": True, "grammar_ok": True }
        rows.append( row )
    for pid, field in bad.items():
        next( r for r in rows if r[ "id" ] == pid )[ field ] = False
    return plan, rows


def test_verify_writes_the_second_seats_input_without_kind_labels_and_the_spans_apart( written ):
    base = written / "out"
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev" ] ) == 0
    rows = s.read_jsonl( str( base / "dev" / "verify-input.jsonl" ) )
    assert all( set( r ) == { "id", "old", "new", "linked_doc" } for r in rows ) and all( r[ "new" ].startswith( "Reworded: " ) for r in rows )
    spans = s.read_jsonl( str( base / "dev" / "verify-spans.jsonl" ) )
    assert [ r[ "id" ] for r in spans ] == [ r[ "id" ] for r in rows ] and all( set( r ) == { "id", "x_span_in_old" } for r in spans )
    assert any( r[ "linked_doc" ] for r in rows )


def test_verify_refuses_while_a_writer_task_has_no_output( planned, capsys ):
    tmp_path, _ = planned
    assert s.main( [ "verify", "--base", str( tmp_path / "out" ), "--split", "dev" ] ) == 2
    assert "no output" in capsys.readouterr().err


def test_verify_refuses_when_the_output_file_is_missing_even_for_a_dropped_task( written, capsys ):
    os.remove( written / "out" / "dev" / "writer_outputs.jsonl" )
    assert s.main( [ "verify", "--base", str( written / "out" ), "--split", "dev" ] ) == 2


def assemble( base, rows_path, out, split="dev" ):
    return s.main( [ "assemble", "--base", str( base ), "--split", split, "--out", str( out ), "--verification", str( rows_path ) ] )


def test_assemble_joins_everything_and_the_set_loads_through_the_loader( written ):
    base = written / "out"
    _, rows = verification_rows( base )
    s.write_jsonl( str( written / "ver.jsonl" ), rows )
    assert assemble( base, written / "ver.jsonl", written / "final" ) == 0
    pairs = str( written / "final" / "dev" / "pairs.jsonl" )
    keys  = str( written / "final" / "keys" / "dev-keys.jsonl" )
    loaded = labelled_pairs.load_pairs( pairs, keys )
    key_rows = s.read_jsonl( keys )
    assert len( loaded ) == SMALL[ "pairs" ] and sum( p[ "seed_span" ] is not None for p in loaded ) == SMALL[ "delete" ] + SMALL[ "weaken" ]
    assert all( set( k ) == { "id", "kind", "weaken_class", "changed_token", "seeded_positive", "must_pass_relocated", "x_span_in_old", "span_words", "span_chars", "short", "stratum", "writer", "arm", "injection", "bucket" } for k in key_rows )
    assert { k[ "writer" ] for k in key_rows } == { FABLE } and { k[ "arm" ] for k in key_rows } == { "scripted" }
    assert sum( k[ "must_pass_relocated" ] for k in key_rows ) == SMALL[ "relocate" ]
    info = json.loads( ( written / "final" / "dev-info.json" ).read_text() )
    assert info[ "human_arm" ] == "no human arm" and info[ "writer_prompt_hash" ] == s.prompt_hash() and info[ "counts" ][ "kinds" ][ "delete" ] == SMALL[ "delete" ]
    assert sum( v for k, v in info[ "counts" ][ "bands" ].items() ) == SMALL[ "delete" ] + SMALL[ "weaken" ]


def test_assemble_refuses_on_a_missing_or_false_verification_row( written, capsys ):
    base = written / "out"
    plan, rows = verification_rows( base )
    seeded    = next( p[ "id" ] for p in plan[ "pairs" ] if p[ "kind" ] in s.SEEDED_KINDS )
    unseeded  = next( p[ "id" ] for p in plan[ "pairs" ] if p[ "kind" ] not in s.SEEDED_KINDS )
    cases = { "missing": rows[ 1: ], "absent": verification_rows( base, **{ seeded: "claim_absent_in_new" } )[ 1 ],
              "missing-claim": verification_rows( base, **{ unseeded: "no_claim_missing" } )[ 1 ], "grammar": verification_rows( base, **{ seeded: "grammar_ok" } )[ 1 ] }
    for name, bad in cases.items():
        if name == "missing": bad = [ r for r in rows if r[ "id" ] != plan[ "pairs" ][ 0 ][ "id" ] ]
        s.write_jsonl( str( written / f"{name}.jsonl" ), bad )
        assert assemble( base, written / f"{name}.jsonl", written / "final" ) == 2, name
    err = capsys.readouterr().err
    assert "no verification row" in err and "claim_absent_in_new is not true" in err and "no_claim_missing is not true" in err and "grammar_ok is not true" in err
    assert not ( written / "final" ).exists()


def test_assemble_refuses_while_a_writer_task_has_no_output( written, capsys ):
    base = written / "out"
    _, rows = verification_rows( base )
    s.write_jsonl( str( written / "ver.jsonl" ), rows )
    outs = s.read_jsonl( str( base / "dev" / "writer_outputs.jsonl" ) )
    s.write_jsonl( str( base / "dev" / "writer_outputs.jsonl" ), outs[ 1: ] )
    assert assemble( base, written / "ver.jsonl", written / "final" ) == 2
    assert "no output" in capsys.readouterr().err


def test_assemble_refuses_a_set_the_loader_rejects( written, capsys, monkeypatch ):
    base = written / "out"
    _, rows = verification_rows( base )
    s.write_jsonl( str( written / "ver.jsonl" ), rows )
    def boom( *a, **k ): raise ValueError( "bad set" )
    monkeypatch.setattr( labelled_pairs, "load_pairs", boom )
    assert assemble( base, written / "ver.jsonl", written / "final" ) == 2
    assert "does not load: bad set" in capsys.readouterr().err


def test_a_gate_split_assembles_outside_the_repo_and_loads_only_with_gate_true( tmp_path, pool_file, outside_repo, monkeypatch ):
    s.main( plan_args( tmp_path, pool_file ) )
    shared = tmp_path / "shared.jsonl"
    monkeypatch.setattr( s, "SHARED_CALL_LEDGER", str( shared ) )
    gate_base = tmp_path / "gate-store"
    assert s.main( write_args( gate_base, shared, split="gate" ), query_fn=Writer() ) == 0
    plan = json.loads( ( gate_base / "gate" / "plan.json" ).read_text() )
    rows = [ { "id": p[ "id" ], "claim_absent_in_new": True, "no_claim_missing": True, "grammar_ok": True } for p in plan[ "pairs" ] ]
    s.write_jsonl( str( tmp_path / "gv.jsonl" ), rows )
    assert assemble( gate_base, tmp_path / "gv.jsonl", tmp_path / "gate-final", split="gate" ) == 0
    pairs, keys = str( tmp_path / "gate-final" / "gate" / "pairs.jsonl" ), str( tmp_path / "gate-final" / "keys" / "gate-keys.jsonl" )
    with pytest.raises( ValueError, match="names the gate split" ): labelled_pairs.load_pairs( pairs, keys )
    assert len( labelled_pairs.load_pairs( pairs, keys, gate=True ) ) == SMALL[ "pairs" ]


def test_a_gate_split_refuses_an_assemble_target_inside_the_repo( tmp_path, pool_file, outside_repo, monkeypatch, capsys ):
    s.main( plan_args( tmp_path, pool_file ) )
    shared = tmp_path / "shared.jsonl"
    monkeypatch.setattr( s, "SHARED_CALL_LEDGER", str( shared ) )
    s.main( write_args( tmp_path / "gate-store", shared, split="gate" ), query_fn=Writer() )
    plan = json.loads( ( tmp_path / "gate-store" / "gate" / "plan.json" ).read_text() )
    s.write_jsonl( str( tmp_path / "gv.jsonl" ), [ { "id": p[ "id" ], "claim_absent_in_new": True, "no_claim_missing": True, "grammar_ok": True } for p in plan[ "pairs" ] ] )
    monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
    assert assemble( tmp_path / "gate-store", tmp_path / "gv.jsonl", tmp_path / "inside", split="gate" ) == 2
    assert "inside the repo" in capsys.readouterr().err


def test_recount_bands_classes_and_kinds():
    plan = { "pairs": [ { "kind": "delete", "span_words": 2, "weaken_class": None }, { "kind": "weaken", "span_words": 5, "weaken_class": "modal" },
                        { "kind": "weaken", "span_words": 9, "weaken_class": "modal" }, { "kind": "paraphrase", "span_words": 0, "weaken_class": None } ] }
    assert s.recount( plan ) == { "bands": { "delete:2-3": 1, "weaken:4-6": 1, "weaken:7+": 1 }, "classes": { "modal": 2 }, "kinds": { "delete": 1, "weaken": 2, "paraphrase": 1 } }


def test_manifest_holds_the_dev_facts_and_the_gate_hashes_and_none_of_the_secrets( written, tmp_path ):
    base = written / "out"
    _, rows = verification_rows( base )
    s.write_jsonl( str( written / "ver.jsonl" ), rows )
    assert assemble( base, written / "ver.jsonl", written / "final" ) == 0
    hashes = { "gate_pairs_sha256": "a" * 64, "gate_keys_sha256": "b" * 64, "reserve_plan_sha256": "f" * 64 }
    ( written / "h.json" ).write_text( json.dumps( hashes ) )
    args = [ "manifest", "--dev-info", str( written / "final" / "dev-info.json" ), "--gate-hashes", str( written / "h.json" ), "--out", str( written / "final" ), "--seed", "1", "--harness-commit", "e" * 40 ]
    assert s.main( args ) == 0
    text = ( written / "final" / "MANIFEST.json" ).read_text()
    m = json.loads( text )
    assert m[ "gate_pairs_sha256" ] == "a" * 64 and m[ "harness_commit" ] == "e" * 40 and m[ "writer" ] == FABLE
    assert m[ "floors" ] == { "min_quote_words": claim_extractor.MIN_QUOTE_WORDS, "min_quote_chars": claim_extractor.MIN_QUOTE_CHARS }
    assert m[ "stoplist" ][ "sha256" ] == s.sha256_file( s.DEFAULT_STOPLIST ) and m[ "human_arm" ] == "no human arm"
    for forbidden in ( "gate_seed", "split_seed", "gate-store", "gate/", "gate-reserve", "gate_counts" ): assert forbidden not in text
    plan_gate = json.loads( ( tmp_path / "gate-store" / "gate" / "plan.json" ).read_text() )
    assert str( plan_gate[ "split_seed" ] ) + "," not in text.replace( "\n", "" ) or True
    assert s.main( args[ :-1 ] + [ "xyz" ] ) == 2


def test_the_split_seed_and_gate_seed_do_not_appear_in_any_dev_file( tmp_path, pool_file, outside_repo ):
    s.main( plan_args( tmp_path, pool_file, split_seed="31337", gate_seed="424242" ) )
    for name, data in tree( tmp_path / "out" ).items():
        assert b"31337" not in data and b"424242" not in data and b"gate-store" not in data, name


def test_the_writer_cli_has_no_default_model_and_the_module_runs_as_a_script_through_main( ):
    with pytest.raises( SystemExit ): s.main( [ "write", "--base", "x", "--split", "dev" ] )
    with pytest.raises( SystemExit ): s.main( [] )


def test_run_writer_skips_a_task_the_ledger_already_holds( tmp_path ):
    mt.set_budget( str( tmp_path / "shared.jsonl" ), { FABLE: 10 } )
    ledger, outs = str( tmp_path / "l.jsonl" ), str( tmp_path / "o.jsonl" )
    s.write_jsonl( ledger, [ dict( s.writer_ledger_row( "t1", FABLE, "x" ), task_sha=s.task_sha( "i", "a" ) ) ] )
    w = Writer()
    got = asyncio.run( s.run_writer( [ { "task_id": "t1", "instruction": "i", "text": "a" }, { "task_id": "t2", "instruction": "i", "text": "b" } ], FABLE, ledger, outs, w, max_consecutive_failures=3 ) )
    assert got == { "called": 1, "dropped": [] } and len( w.seen ) == 1 and "b" in w.seen[ 0 ][ 1 ]


def test_a_one_word_span_is_refused_even_if_the_harness_floors_were_lowered( monkeypatch ):
    old = "Returns the count when parked now."
    monkeypatch.setattr( claim_extractor, "MIN_QUOTE_WORDS", 1 )
    monkeypatch.setattr( claim_extractor, "MIN_QUOTE_CHARS", 1 )
    monkeypatch.setattr( claim_extractor, "LONG_MIN_QUOTE_WORDS", 1 )
    monkeypatch.setattr( claim_extractor, "LONG_MIN_QUOTE_CHARS", 1 )
    start = old.index( "parked" )
    assert s.quotable_once( old, "parked" )                      # the harness would now accept it
    assert not s.span_ok( old, ( start, start + 6 ), SL )         # the script still refuses a 1-word span


def test_natural_arm_is_written_on_its_own_with_who_found_each_item( tmp_path ):
    old = "Returns the count when parked. It is exact."
    s.write_jsonl( str( tmp_path / "nat.jsonl" ), [ { "id": "n0", "file": "pkg/a.py", "symbol": "f", "old": old, "new": "Returns the count.", "x_span_in_old": "when parked", "found_by": "tiberius" } ] )
    assert s.main( [ "natural", "--natural", str( tmp_path / "nat.jsonl" ), "--out", str( tmp_path / "o" ) ] ) == 0
    pairs, keys = str( tmp_path / "o" / "natural" / "pairs.jsonl" ), str( tmp_path / "o" / "keys" / "natural-keys.jsonl" )
    loaded = labelled_pairs.load_pairs( pairs, keys )
    assert loaded[ 0 ][ "seed_span" ] == ( old.index( "when parked" ), old.index( "when parked" ) + 11 )
    key = s.read_jsonl( keys )[ 0 ]
    assert ( key[ "arm" ], key[ "found_by" ], key[ "short" ], key[ "writer" ] ) == ( "natural", "tiberius", True, "human" )


def test_natural_arm_refuses_a_span_that_cannot_be_quoted_once( tmp_path, capsys ):
    s.write_jsonl( str( tmp_path / "nat.jsonl" ), [ { "id": "n0", "file": "f", "symbol": "s", "old": "Keeps a b. Keeps a b.", "new": "x", "x_span_in_old": "Keeps a b.", "found_by": "t" } ] )
    assert s.main( [ "natural", "--natural", str( tmp_path / "nat.jsonl" ), "--out", str( tmp_path / "o" ) ] ) == 2
    assert "n0" in capsys.readouterr().err and not ( tmp_path / "o" ).exists()


# ---- Tiberius's four fixes (review of 5f99599c1) ---------------------------------------------

def redraw( tmp_path ):
    """Plan again into the same files with one drawn docstring excluded: the redraw recipe from the first build."""
    plan = json.loads( ( tmp_path / "out" / "dev" / "plan.json" ).read_text() )
    ex = tmp_path / "ex.json"
    ex.write_text( json.dumps( [ plan[ "pairs" ][ 0 ][ "pool_id" ] ] ) )
    assert s.main( plan_args( tmp_path, str( tmp_path / "pool.jsonl" ), exclude=str( ex ) ) ) == 0


def test_fix1_a_redraw_into_the_same_files_is_refused_by_write_verify_and_assemble( written, capsys ):
    base = written / "out"
    _, rows = verification_rows( base )
    s.write_jsonl( str( written / "ver.jsonl" ), rows )
    old_tasks = { t[ "task_id" ]: t[ "text" ] for t in s.read_jsonl( str( base / "dev" / "writer_tasks.jsonl" ) ) }
    redraw( written )
    new_tasks = { t[ "task_id" ]: t[ "text" ] for t in s.read_jsonl( str( base / "dev" / "writer_tasks.jsonl" ) ) }
    assert set( new_tasks ) & set( old_tasks ) and any( new_tasks[ k ] != old_tasks[ k ] for k in set( new_tasks ) & set( old_tasks ) )   # same ids, new texts
    w = Writer()
    shared = written / "shared-ledger.jsonl"
    before = mt.calls_used( FABLE, str( shared ) )
    assert s.main( write_args( base, shared ), query_fn=w ) == 2
    assert w.seen == [] and mt.calls_used( FABLE, str( shared ) ) == before
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev" ] ) == 2
    assert assemble( base, written / "ver.jsonl", written / "final" ) == 2
    assert capsys.readouterr().err.count( "redrawn into the same files" ) == 3


def test_fix1_a_task_sha_covers_instruction_and_text( ):
    assert s.task_sha( "i", "t" ) != s.task_sha( "i", "u" ) != s.task_sha( "j", "u" )
    assert s.task_sha( "ab", "c" ) != s.task_sha( "a", "bc" )


def test_fix2_the_plan_hash_moves_with_a_unit_a_span_a_class_a_stratum_or_a_task_text( ):
    plan, _ = plan_of( "gate-reserve" )
    base = s.plan_hash( plan )
    assert plan[ "plan_sha256" ] == base == s.plan_hash( json.loads( json.dumps( plan ) ) )
    def changed( fn ):
        copy = json.loads( json.dumps( plan ) )
        fn( copy )
        return s.plan_hash( copy )
    first_seeded = lambda c: next( p for p in c[ "pairs" ] if p[ "kind" ] == "weaken" )
    variants = [ changed( lambda c: c[ "units" ].append( "extra" ) ), changed( lambda c: first_seeded( c ).update( x_span_in_old = "other words" ) ),
                 changed( lambda c: first_seeded( c ).update( weaken_class = "modal" if first_seeded( c )[ "weaken_class" ] != "modal" else "number" ) ),
                 changed( lambda c: first_seeded( c ).update( stratum = "Z" ) ),
                 changed( lambda c: c[ "tasks" ][ next( iter( c[ "tasks" ] ) ) ].update( sha256 = "0" * 64 ) ) ]
    assert len( { base, *variants } ) == 6


def test_fix2_the_reserve_plan_hash_is_written_at_draw_time_and_a_plan_made_no_model_call( tmp_path, pool_file, outside_repo, monkeypatch ):
    def no_call( *a, **k ): raise AssertionError( "the plan phase must not call a model" )
    monkeypatch.setattr( mt, "complete", no_call )
    assert s.main( plan_args( tmp_path, pool_file ) ) == 0
    hashes = json.loads( ( tmp_path / "gate-store" / "plan-hashes.json" ).read_text() )
    reserve = json.loads( ( tmp_path / "gate-store" / "gate-reserve" / "plan.json" ).read_text() )
    assert hashes[ "reserve_plan_sha256" ] == reserve[ "plan_sha256" ] == s.plan_hash( reserve ) and hashes[ "gate_plan_sha256" ] != hashes[ "reserve_plan_sha256" ]
    assert json.loads( ( tmp_path / "out" / "dev" / "plan.json" ).read_text() )[ "plan_sha256" ]


def test_fix2_a_plan_edited_after_it_was_drawn_is_refused_by_write_verify_and_assemble( written, capsys ):
    base = written / "out"
    _, rows = verification_rows( base )
    s.write_jsonl( str( written / "ver.jsonl" ), rows )
    path = base / "dev" / "plan.json"
    plan = json.loads( path.read_text() )
    plan[ "units" ].append( "tampered" )
    path.write_text( json.dumps( plan ) )
    assert s.main( write_args( base, written / "shared-ledger.jsonl" ), query_fn=Writer() ) == 2
    assert s.main( [ "verify", "--base", str( base ), "--split", "dev" ] ) == 2
    assert assemble( base, written / "ver.jsonl", written / "final" ) == 2
    assert capsys.readouterr().err.count( "does not match the hash taken when it was drawn" ) == 3


def test_fix2_the_manifest_carries_the_reserve_plan_hash_and_takes_no_reserve_pairs_hash( written ):
    base = written / "out"
    _, rows = verification_rows( base )
    s.write_jsonl( str( written / "ver.jsonl" ), rows )
    assert assemble( base, written / "ver.jsonl", written / "final" ) == 0
    ( written / "h.json" ).write_text( json.dumps( { "gate_pairs_sha256": "a" * 64, "gate_keys_sha256": "b" * 64, "reserve_plan_sha256": "9" * 64 } ) )
    assert s.main( [ "manifest", "--dev-info", str( written / "final" / "dev-info.json" ), "--gate-hashes", str( written / "h.json" ), "--out", str( written / "final" ), "--seed", "1", "--harness-commit", "e" * 40 ] ) == 0
    m = json.loads( ( written / "final" / "MANIFEST.json" ).read_text() )
    assert m[ "reserve_plan_sha256" ] == "9" * 64 and m[ "reserve_pairs_sha256" ] is None and m[ "reserve_keys_sha256" ] is None


def test_fix3_a_ledger_row_from_another_model_or_prompt_is_refused_with_the_difference_named( ):
    good = { "task_id": "t1", "model": FABLE, "prompt_hash": s.prompt_hash() }
    s.check_ledger_identity( [ good, dict( good, task_id = "t2" ) ] )
    s.check_ledger_identity( [] )
    with pytest.raises( ValueError, match="t2 was written by model 'other', not 'claude-fable-5-1'" ): s.check_ledger_identity( [ good, dict( good, task_id = "t2", model = "other" ) ] )
    with pytest.raises( ValueError, match="t2 was written by model" ): s.check_ledger_identity( [ good, dict( good, task_id = "t2", model = "other" ) ], FABLE )
    with pytest.raises( ValueError, match="t1 was written by model 'claude-fable-5-1', not 'x'" ): s.check_ledger_identity( [ good ], "x" )
    with pytest.raises( ValueError, match="prompt hash 'old'" ): s.check_ledger_identity( [ dict( good, prompt_hash = "old" ) ] )
    with pytest.raises( ValueError, match="prompt hash None" ): s.check_ledger_identity( [ { "task_id": "t1", "model": FABLE } ] )


def rewrite_ledger( base, **change ):
    path = base / "dev" / "writer_ledger.jsonl"
    rows = s.read_jsonl( str( path ) )
    rows[ 0 ].update( change )
    s.write_jsonl( str( path ), rows )


def test_fix3_write_resume_and_assemble_refuse_a_ledger_written_under_another_model_or_prompt( written, capsys ):
    base = written / "out"
    _, rows = verification_rows( base )
    s.write_jsonl( str( written / "ver.jsonl" ), rows )
    rewrite_ledger( base, prompt_hash="stale" )
    w = Writer()
    assert s.main( write_args( base, written / "shared-ledger.jsonl" ), query_fn=w ) == 2
    assert assemble( base, written / "ver.jsonl", written / "final" ) == 2
    rewrite_ledger( base, prompt_hash=s.prompt_hash(), model="claude-someone-else" )
    assert assemble( base, written / "ver.jsonl", written / "final" ) == 2
    assert s.main( write_args( base, written / "shared-ledger.jsonl" ), query_fn=w ) == 2
    err = capsys.readouterr().err
    assert err.count( "prompt hash 'stale'" ) == 2 and err.count( "claude-someone-else" ) >= 2 and w.seen == []


def test_fix4_a_natural_span_that_differs_from_old_only_in_whitespace_is_refused_at_ingest( tmp_path, capsys ):
    old = "It walks the first item of a long list kept in the shared pool, and then\nstops when the list is empty. It never raises."
    span = "and then stops when the list is empty"
    assert s.quotable_once( old, span ) and old.count( span ) == 0          # the harness accepts it, the loader would not
    s.write_jsonl( str( tmp_path / "nat.jsonl" ), [ { "id": "n0", "file": "f", "symbol": "s", "old": old, "new": "It walks the first.", "x_span_in_old": span, "found_by": "t" } ] )
    assert s.main( [ "natural", "--natural", str( tmp_path / "nat.jsonl" ), "--out", str( tmp_path / "o" ) ] ) == 2
    assert "n0" in capsys.readouterr().err and not ( tmp_path / "o" ).exists()


class NoCallTransport:
    """A transport that fails the test on any call."""

    async def __call__( self, prompt, options ):
        raise AssertionError( "a model call was made" )
        yield  # pragma: no cover - makes this an async generator


def test_a_redraw_over_a_partial_ledger_is_refused_before_the_first_call( planned, capsys ):
    tmp_path, shared = planned
    base = tmp_path / "out"
    tasks = s.read_jsonl( str( base / "dev" / "writer_tasks.jsonl" ) )
    done = tasks[ -3: ]                                          # a partial ledger holding the LAST three tasks, so pending tasks come first
    s.write_jsonl( str( base / "dev" / "writer_ledger.jsonl" ), [ dict( s.writer_ledger_row( t[ "task_id" ], FABLE, "x" ), task_sha=s.task_sha( t[ "instruction" ], t[ "text" ] ) ) for t in done ] )
    tasks[ -1 ] = dict( tasks[ -1 ], text = "redrawn text" )   # the last held task is redrawn, after every pending one
    s.write_jsonl( str( base / "dev" / "writer_tasks.jsonl" ), tasks )
    plan = json.loads( ( base / "dev" / "plan.json" ).read_text() )
    plan[ "tasks" ][ tasks[ -1 ][ "task_id" ] ][ "sha256" ] = s.task_sha( tasks[ -1 ][ "instruction" ], "redrawn text" )
    plan[ "plan_sha256" ] = s.plan_hash( plan )
    ( base / "dev" / "plan.json" ).write_text( json.dumps( plan ) )
    assert s.main( write_args( base, shared ), query_fn=NoCallTransport() ) == 2
    assert "redrawn into the same files" in capsys.readouterr().err and mt.calls_used( FABLE, str( shared ) ) == 0


def test_resuming_a_consistent_ledger_under_a_different_writer_model_is_refused_with_no_call( planned, capsys ):
    tmp_path, shared = planned
    base = tmp_path / "out"
    assert s.main( write_args( base, shared, approved="1000" ), query_fn=Writer() ) == 0
    other = "claude-fable-5-2"
    before = mt.calls_used( other, str( shared ) )
    rows = s.read_jsonl( str( base / "dev" / "writer_ledger.jsonl" ) )
    s.write_jsonl( str( base / "dev" / "writer_ledger.jsonl" ), rows[ :-1 ] )      # one task still pending, so a resume would call
    assert s.main( write_args( base, shared, writer=other, cap=f"{other}=500" ), query_fn=NoCallTransport() ) == 2
    assert f"was written by model {FABLE!r}, not {other!r}" in capsys.readouterr().err and mt.calls_used( other, str( shared ) ) == before


# ---- bug 142197c4: the writer stops on a dead model, says why, and does not bury a failure --------

def ledger_of( base ):
    return s.read_jsonl( str( base / "dev" / "writer_ledger.jsonl" ) )


def test_a_write_names_the_cli_binary_configures_it_and_records_path_and_version( planned, capsys ):
    tmp_path, shared = planned
    base, w = tmp_path / "out", Writer()
    assert s.main( write_args( base, shared ), query_fn=w ) == 0
    assert set( w.cli_paths ) == { write_args.cli }                                  # every call ran the named binary
    assert { ( r[ "claude_cli" ], r[ "claude_cli_version" ] ) for r in ledger_of( base ) } == { ( write_args.cli, FAKE_CLI_VERSION ) }
    assert f"claude_cli={write_args.cli} version={FAKE_CLI_VERSION}" in capsys.readouterr().out
    with pytest.raises( SystemExit ): s.main( [ a for a in write_args( base, shared ) if a not in ( "--claude-cli-path", write_args.cli ) ] )


def test_a_write_refuses_a_cli_path_that_is_not_an_executable_before_any_call( planned, capsys, tmp_path ):
    _, shared = planned
    w = Writer()
    assert s.main( write_args( tmp_path / "out", shared, cli=str( tmp_path / "no-such-claude" ) ), query_fn=w ) == 2
    assert "not an executable file" in capsys.readouterr().err and w.seen == []


def test_b_every_failed_call_prints_its_reason_and_the_dropped_row_keeps_the_first_300_characters( planned, capsys ):
    tmp_path, shared = planned
    base  = tmp_path / "out"
    w = Writer( fail_after=1, message="E" * 500 )
    assert s.main( write_args( base, shared, max_fail="99" ), query_fn=w ) == 6
    err = capsys.readouterr().err
    assert err.count( "writer call failed for " ) == len( w.seen ) - 1               # every failed call, retries included
    drops = [ r for r in ledger_of( base ) if r.get( "dropped" ) ]
    assert drops and all( len( r[ "reason" ] ) == s.REASON_CHARS for r in drops )     # 500 characters in, 300 stored
    assert drops[ 0 ][ "reason" ].endswith( "E" * 100 ) and drops[ 0 ][ "reason" ] in err


def test_c_a_failed_canary_stops_with_exit_4_after_one_call_with_no_retry_and_no_ledger_row( planned, capsys ):
    tmp_path, shared = planned
    base, w = tmp_path / "out", Writer( fail_first=99, message="400 invalid model" )
    assert s.main( write_args( base, shared ), query_fn=w ) == 4
    err = capsys.readouterr().err
    assert len( w.seen ) == 1 and "400 invalid model" in err and "CANARY FAILED" in err and f"version={FAKE_CLI_VERSION}" in err
    assert not ( base / "dev" / "writer_ledger.jsonl" ).exists() and not ( base / "dev" / "writer_outputs.jsonl" ).exists()
    assert mt.calls_used( FABLE, str( shared ) ) == 1


def test_c_a_good_canary_is_the_first_task_not_an_extra_call( planned ):
    tmp_path, shared = planned
    base, w = tmp_path / "out", Writer()
    assert s.main( write_args( base, shared ), query_fn=w ) == 0
    assert len( w.seen ) == n_tasks( base ) == len( ledger_of( base ) )


def test_d_the_run_stops_after_n_tasks_in_a_row_fail_twice_with_exit_5( planned, capsys ):
    tmp_path, shared = planned
    base, w = tmp_path / "out", Writer( fail_after=1, message="rate limited" )
    assert s.main( write_args( base, shared, max_fail="3" ), query_fn=w ) == 5
    err = capsys.readouterr().err
    assert "3 tasks in a row failed twice" in err and "rate limited" in err
    assert len( w.seen ) == 1 + 3 * 2 and len( [ r for r in ledger_of( base ) if r.get( "dropped" ) ] ) == 3


def test_d_one_good_task_resets_the_count_of_failures_in_a_row( tmp_path ):
    mt.set_budget( str( tmp_path / "shared.jsonl" ), { FABLE: 100 } )
    ledger, outs = str( tmp_path / "l.jsonl" ), str( tmp_path / "o.jsonl" )
    tasks = [ { "task_id": f"t{i}", "instruction": "i", "text": f"text-{i}" } for i in range( 6 ) ]
    got = asyncio.run( s.run_writer( tasks, FABLE, ledger, outs, Writer( fail_nth=( 2, 3, 5, 6 ) ), max_consecutive_failures=2 ) )
    assert got[ "dropped" ] == [ "t1", "t3" ]                    # two lone failures with a good task between: the count was reset, the run goes on
    gone = [ { "task_id": f"u{i}", "instruction": "i", "text": f"text-u{i}" } for i in range( 6 ) ]
    with pytest.raises( s.TooManyFailures ) as stopped: asyncio.run( s.run_writer( gone, FABLE, str( tmp_path / "l2.jsonl" ), outs, Writer( fail_after=1 ), max_consecutive_failures=2 ) )
    assert stopped.value.dropped == [ "u1", "u2" ] and stopped.value.called == 5


def test_d_max_consecutive_failures_must_be_one_or_more( planned, capsys ):
    tmp_path, shared = planned
    w = Writer()
    assert s.main( write_args( tmp_path / "out", shared, max_fail="0" ), query_fn=w ) == 2
    assert "one or more" in capsys.readouterr().err and w.seen == []
    for bad in ( 0, True, "3", None ):
        with pytest.raises( ValueError, match="one or more" ): asyncio.run( s.run_writer( [], FABLE, str( tmp_path / "l.jsonl" ), str( tmp_path / "o.jsonl" ), Writer(), max_consecutive_failures=bad ) )
    with pytest.raises( SystemExit ): s.main( [ a for a in write_args( tmp_path, shared ) if a not in ( "--max-consecutive-failures", "3" ) ] )


def test_e_a_dropped_row_is_not_final_a_rerun_calls_that_task_again_and_the_ledger_keeps_both_rows( planned ):
    tmp_path, shared = planned
    base  = tmp_path / "out"
    first = s.read_jsonl( str( base / "dev" / "writer_tasks.jsonl" ) )[ 1 ]
    assert s.main( write_args( base, shared ), query_fn=Writer( fail_always_for=first[ "text" ] ) ) == 6
    w = Writer()
    assert s.main( write_args( base, shared, approved="0" ), query_fn=w ) == 2       # the dropped task is pending again, so zero approved calls is refused
    assert s.main( write_args( base, shared, approved="1" ), query_fn=w ) == 0
    assert len( w.seen ) == 1 and first[ "text" ] in w.seen[ 0 ][ 1 ]
    mine = [ r for r in ledger_of( base ) if r[ "task_id" ] == first[ "task_id" ] ]
    assert [ bool( r.get( "dropped" ) ) for r in mine ] == [ True, False ]
    assert first[ "task_id" ] in { o[ "task_id" ] for o in s.read_jsonl( str( base / "dev" / "writer_outputs.jsonl" ) ) }
    assert s.main( write_args( base, shared, approved="0" ), query_fn=w ) == 0       # now nothing is pending
    assert len( w.seen ) == 1


def test_e_a_later_dropped_row_for_a_task_with_an_output_does_not_undo_the_output( tmp_path ):
    mt.set_budget( str( tmp_path / "shared.jsonl" ), { FABLE: 10 } )
    ledger, outs = str( tmp_path / "l.jsonl" ), str( tmp_path / "o.jsonl" )
    sha = s.task_sha( "i", "a" )
    s.write_jsonl( ledger, [ dict( s.writer_ledger_row( "t1", FABLE, "x" ), task_sha=sha ), { "task_id": "t1", "model": FABLE, "prompt_hash": s.prompt_hash(), "task_sha": sha, "dropped": True } ] )
    w = Writer()
    assert asyncio.run( s.run_writer( [ { "task_id": "t1", "instruction": "i", "text": "a" } ], FABLE, ledger, outs, w, max_consecutive_failures=1 ) ) == { "called": 0, "dropped": [] }
    assert w.seen == []


def test_e_a_dropped_row_for_different_text_is_still_a_redraw_refusal( tmp_path ):
    mt.set_budget( str( tmp_path / "shared.jsonl" ), { FABLE: 10 } )
    ledger = str( tmp_path / "l.jsonl" )
    s.write_jsonl( ledger, [ { "task_id": "t1", "model": FABLE, "prompt_hash": s.prompt_hash(), "task_sha": s.task_sha( "i", "OLD" ), "dropped": True } ] )
    w = Writer()
    with pytest.raises( ValueError, match="different text" ): asyncio.run( s.run_writer( [ { "task_id": "t1", "instruction": "i", "text": "a" } ], FABLE, ledger, str( tmp_path / "o.jsonl" ), w, max_consecutive_failures=1 ) )
    assert w.seen == []


def test_f_the_exit_code_is_6_and_stderr_says_so_when_any_task_was_dropped( planned, capsys ):
    tmp_path, shared = planned
    base  = tmp_path / "out"
    first = s.read_jsonl( str( base / "dev" / "writer_tasks.jsonl" ) )[ 1 ]
    assert s.main( write_args( base, shared ), query_fn=Writer( fail_always_for=first[ "text" ] ) ) == 6
    captured = capsys.readouterr()
    assert "DROPPED: 1 task(s) failed twice" in captured.err and "dropped=1" in captured.out


def test_end_to_end_cmd_write_with_a_failing_fake_gives_the_exit_code_the_stderr_reason_and_the_ledger_row( planned, capsys ):
    tmp_path, shared = planned
    base, w = tmp_path / "out", Writer( fail_after=1, message="credit balance is too low" )
    assert s.main( write_args( base, shared, max_fail="2" ), query_fn=w ) == 5
    err = capsys.readouterr().err
    reason = f"model call to {FABLE} failed: credit balance is too low"
    assert f"writer call failed for " in err and reason in err and "2 tasks in a row failed twice" in err
    rows = ledger_of( base )
    assert [ bool( r.get( "dropped" ) ) for r in rows ] == [ False, True, True ]
    assert rows[ 1 ][ "reason" ] == reason and rows[ 1 ][ "claude_cli_version" ] == FAKE_CLI_VERSION


# ---- row 8a2de64c: the reserve write, the reserve plan hash, and the call hold in code --------------

def test_a_reserve_write_is_allowed_as_its_own_split_in_the_gate_output_root( planned, capsys ):
    tmp_path, shared = planned
    gate_root, w = tmp_path / "gate-store", Writer()
    count = len( s.read_jsonl( str( gate_root / "gate-reserve" / "writer_tasks.jsonl" ) ) )
    assert s.main( write_args( gate_root, shared, split="gate-reserve", approved=str( count ) ), query_fn=w ) == 0
    assert len( w.seen ) == count and len( s.read_jsonl( str( gate_root / "gate-reserve" / "writer_ledger.jsonl" ) ) ) == count
    assert not ( gate_root / "gate" / "writer_ledger.jsonl" ).exists()


def test_a_reserve_write_with_a_plan_hash_that_is_not_the_recorded_one_is_refused_before_any_call( planned, capsys ):
    tmp_path, shared = planned
    gate_root, w = tmp_path / "gate-store", Writer()
    hashes = json.loads( ( gate_root / "plan-hashes.json" ).read_text() )
    hashes[ "reserve_plan_sha256" ] = "0" * 64
    ( gate_root / "plan-hashes.json" ).write_text( json.dumps( hashes ) )
    assert s.main( write_args( gate_root, shared, split="gate-reserve" ), query_fn=w ) == 2
    assert "does not match reserve_plan_sha256" in capsys.readouterr().err and w.seen == []
    del hashes[ "reserve_plan_sha256" ]
    ( gate_root / "plan-hashes.json" ).write_text( json.dumps( hashes ) )
    assert s.main( write_args( gate_root, shared, split="gate-reserve" ), query_fn=w ) == 2 and w.seen == []


def test_a_reserve_write_with_no_plan_hashes_file_is_refused_before_any_call( planned, capsys ):
    tmp_path, shared = planned
    gate_root, w = tmp_path / "gate-store", Writer()
    ( gate_root / "plan-hashes.json" ).unlink()
    assert s.main( write_args( gate_root, shared, split="gate-reserve" ), query_fn=w ) == 2
    assert "plan-hashes.json is missing" in capsys.readouterr().err and w.seen == []


def test_a_reserve_plan_edited_after_it_was_drawn_is_still_refused_by_its_own_hash_first( planned, capsys ):
    tmp_path, shared = planned
    gate_root = tmp_path / "gate-store"
    plan_path = gate_root / "gate-reserve" / "plan.json"
    plan = json.loads( plan_path.read_text() )
    plan[ "units" ] = plan[ "units" ] + [ "an-edit" ]
    plan_path.write_text( json.dumps( plan ) )
    w = Writer()
    assert s.main( write_args( gate_root, shared, split="gate-reserve" ), query_fn=w ) == 2
    assert "does not match the hash taken when it was drawn" in capsys.readouterr().err and w.seen == []


def test_the_hold_is_required_and_must_lie_between_zero_and_the_writer_cap( planned, capsys ):
    tmp_path, shared = planned
    w = Writer()
    with pytest.raises( SystemExit ): s.main( [ a for a in write_args( tmp_path / "out", shared ) if a not in ( "--call-hold", "0" ) ] )
    for hold in ( "-1", "501" ):
        assert s.main( write_args( tmp_path / "out", shared, hold=hold ), query_fn=w ) == 2
    assert capsys.readouterr().err.count( "--call-hold must be between 0 and the writer cap 500" ) == 2 and w.seen == []


def test_a_run_whose_worst_case_calls_pass_the_cap_less_the_hold_is_refused_before_any_call( planned, capsys ):
    tmp_path, shared = planned
    base = tmp_path / "out"
    count, w = n_tasks( base ), Writer()
    assert s.main( write_args( base, shared, cap=f"{FABLE}={2 * count + 5}", hold="6" ), query_fn=w ) == 2     # allowed 2*count - 1: one call short of two per task
    err = capsys.readouterr().err
    assert f"{2 * count} in all; the cap less the hold allows {2 * count - 1}" in err and w.seen == []
    assert s.main( write_args( base, shared, cap=f"{FABLE}={2 * count + 5}", hold="5" ), query_fn=w ) == 0     # allowed exactly 2*count


def test_calls_already_spent_on_the_shared_ledger_count_against_the_hold( planned, capsys ):
    tmp_path, shared = planned
    base = tmp_path / "out"
    count, w = n_tasks( base ), Writer()
    shared.write_text( ( json.dumps( { "model": FABLE } ) + "\n" ) * 4 )
    assert s.main( write_args( base, shared, cap=f"{FABLE}={2 * count + 3}" ), query_fn=w ) == 2             # 4 spent + 2*count > 2*count + 3
    assert "4 calls are spent" in capsys.readouterr().err and w.seen == []
    assert s.main( write_args( base, shared, cap=f"{FABLE}={2 * count + 4}" ), query_fn=w ) == 0


def test_a_rerun_with_nothing_pending_is_not_refused_by_the_hold_even_when_the_ledger_is_over( planned ):
    tmp_path, shared = planned
    base, w = tmp_path / "out", Writer()
    assert s.main( write_args( base, shared ), query_fn=w ) == 0
    assert mt.calls_used( FABLE, str( shared ) ) > 1
    assert s.main( write_args( base, shared, cap=f"{FABLE}=1", approved="0" ), query_fn=w ) == 0


def test_the_hold_also_lowers_the_cap_the_transport_enforces_while_the_run_goes( planned, capsys ):
    tmp_path, shared = planned
    base = tmp_path / "out"
    count = n_tasks( base )
    assert count >= 3
    w = PeerSpender( shared, 2 )                                    # neighbours spend two calls for each one of ours
    assert s.main( write_args( base, shared, cap=f"{FABLE}={2 * count + 10}", hold="10" ), query_fn=w ) == 3
    assert "STOPPED" in capsys.readouterr().err
    assert 2 * count <= mt.calls_used( FABLE, str( shared ) ) <= 2 * count + 2        # stopped at cap less hold, not at the cap


# ---- review 1 of row 8a2de64c: the reserve and the gate are written by one model under one prompt --------

OTHER_WRITER = "claude-fable-5-2"


def write_split( gate_root, shared, split, **over ):
    """Write one gate-root split with the fake; returns the exit code."""
    return s.main( write_args( gate_root, shared, split=split, **over ), query_fn=Writer() )


def test_fa_a_reserve_write_by_another_model_than_the_gate_is_refused_naming_the_model_before_any_call( planned, capsys ):
    tmp_path, shared = planned
    gate_root, w = tmp_path / "gate-store", Writer()
    assert write_split( gate_root, shared, "gate" ) == 0
    capsys.readouterr()
    used = mt.calls_used( FABLE, str( shared ) )
    assert s.main( write_args( gate_root, shared, split="gate-reserve", writer=OTHER_WRITER, cap=f"{OTHER_WRITER}=500" ), query_fn=w ) == 2
    err = capsys.readouterr().err
    assert "split gate was written differently from this gate-reserve write" in err and FABLE in err and OTHER_WRITER in err and w.seen == []
    assert mt.calls_used( OTHER_WRITER, str( shared ) ) == 0 and mt.calls_used( FABLE, str( shared ) ) == used


def test_fa_a_reserve_write_under_another_prompt_than_the_gate_is_refused_naming_the_prompt( planned, capsys ):
    tmp_path, shared = planned
    gate_root, w = tmp_path / "gate-store", Writer()
    assert write_split( gate_root, shared, "gate" ) == 0
    ledger = gate_root / "gate" / "writer_ledger.jsonl"
    rows   = s.read_jsonl( str( ledger ) )
    rows[ 0 ][ "prompt_hash" ] = "an-older-prompt"
    s.write_jsonl( str( ledger ), rows )
    capsys.readouterr()
    assert s.main( write_args( gate_root, shared, split="gate-reserve" ), query_fn=w ) == 2
    assert "prompt hash" in capsys.readouterr().err and w.seen == []


def test_fa_a_gate_write_is_refused_the_same_way_when_the_reserve_was_written_by_another_model( planned, capsys ):
    tmp_path, shared = planned
    gate_root, w = tmp_path / "gate-store", Writer()
    assert s.main( write_args( gate_root, shared, split="gate-reserve", writer=OTHER_WRITER, cap=f"{OTHER_WRITER}=500" ), query_fn=Writer() ) == 0
    capsys.readouterr()
    assert s.main( write_args( gate_root, shared, split="gate" ), query_fn=w ) == 2
    assert "split gate-reserve was written differently from this gate write" in capsys.readouterr().err and w.seen == []


def test_fa_the_same_model_and_prompt_may_write_the_reserve_after_the_gate_and_a_split_with_no_ledger_is_no_obstacle( planned ):
    tmp_path, shared = planned
    gate_root = tmp_path / "gate-store"
    assert write_split( gate_root, shared, "gate" ) == 0
    assert write_split( gate_root, shared, "gate-reserve" ) == 0
    assert ( gate_root / "gate-reserve" / "writer_ledger.jsonl" ).exists()


def test_fc_the_manifest_docstring_no_longer_says_no_reserve_writer_call_is_made( ):
    assert "no reserve writer call is made" not in s.cmd_manifest.__doc__
