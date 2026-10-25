"""
Whole docstrings, purpose lines and the dropped report in what the judge reads.
"""
import json
import pathlib
import types

import pytest

from cosa.repo.symindex import build as bd
from lupin_mcp import reuse_tools as rt
from tests.unit.include_tests_helpers import AllReuse
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_pack_route import no_jev_key, receipt_of                              # noqa: F401  (no_jev_key is a fixture)
from tests.unit.test_reuse_candidates_client import world                                       # noqa: F401  (a fixture)
from tests.unit.test_reuse_tools import NEED

NOTES = '''def long_doc():
    """Summarise a page.

    Longer text that explains the whole thing.
    """
    return 1


def leaky():
    """Short line.

    Mail ops@example.com for help.
    """
    return 2
'''
OLD_REQUEST_HASH = "dc08a04f2b049aa2ae4abbdbf202ce2c676dc429"      # request_hash( build_request( "read an RSS feed", OLD_RECORD text ) ), computed by the code at d31b9d11f
OLD_RECORD       = { "id": "cosa.feeds.parse_feed", "sig": "( url )", "doc": "Parse an RSS feed.", "file": "src/cosa/feeds.py", "lang": "py" }
SENSITIVE        = "EXCLUDED_SENSITIVE_CONTENT"


@pytest.fixture
def notes_env( tmp_path ):
    """Return ( root, data, out ) for a lupin tree with a long-docstring and a leaking function."""
    root = make_lupin_repo( tmp_path )
    ( root / "src" / "cosa" / "notes.py" ).write_text( NOTES, encoding="utf-8" )
    return root, tmp_path / "data", tmp_path / "out"


def ctx_of( env, transport, **kw ): return rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=transport, **kw )


def asked( fake ): return [ json.dumps( b ) for b in fake.seen ]


def test_entry_text_appends_the_whole_docstring_and_the_purpose_only_when_the_record_has_them():
    base = rt.entry_text( OLD_RECORD )
    assert base == "cosa.feeds.parse_feed( url ) — Parse an RSS feed."
    assert rt.request_hash( rt.build_request( "read an RSS feed", base ) ) == OLD_REQUEST_HASH       # one side is a literal, from the old code
    assert rt.entry_text( { **OLD_RECORD, "doc_full": "Parse an RSS feed. Then more." } ) == base + " | Parse an RSS feed. Then more."
    assert rt.entry_text( { **OLD_RECORD, "purpose": "reads feeds" } ) == base + " | purpose: reads feeds"
    assert rt.entry_text( { **OLD_RECORD, "doc_full": "Parse an RSS feed. Then more.", "purpose": "reads feeds" } ) == base + " | Parse an RSS feed. Then more. | purpose: reads feeds"
    assert rt.entry_text( { **OLD_RECORD, "doc_full": "Parse an RSS feed.", "purpose": "" } ) == base         # a one-line docstring and an empty line add nothing


def test_c1_hits_screens_the_whole_docstring_and_the_purpose_line():
    rec = { "id": "a.f", "sig": "()", "doc": "Fine." }
    assert rt.c1_hits( rec ) == [] and rt.c1_hits( { **rec, "doc_full": "Fine.\nMail ops@example.com." } ) == [ "email" ]
    assert rt.c1_hits( { **rec, "purpose": "calls https://example.com/x" } ) == [ "url" ]
    assert rt.c1_hits( { **rec, "doc_full": "Fine.", "purpose": "clean" } ) == []


def test_sendable_report_names_both_reasons_and_sendable_keeps_its_old_answer():
    clean, leaky, held = { "id": "a.ok", "sig": "()", "doc": "x" }, { "id": "a.bad", "sig": "()", "doc": "x", "doc_full": "x ops@example.com" }, { "id": "held.f", "sig": "()", "doc": "x" }
    kept, dropped = rt.sendable_report( [ clean, leaky, held ], ( "held.", ) )
    assert kept == [ clean ] and dropped == { SENSITIVE: [ "a.bad" ], "EXCLUDED_PREFIX": [ "held.f" ] }
    assert rt.sendable( [ clean, leaky, held ], ( "held.", ) ) == ( [ clean ], [ "a.bad" ] )             # a prefix drop is not in the second list, as before


def test_dropped_view_counts_each_reason_and_shows_the_first_ten_ids_and_nothing_when_clean():
    ids = [ f"a.f{i:02d}" for i in range( 12 ) ]
    assert rt.dropped_view( { SENSITIVE: ids, "EXCLUDED_PREFIX": [ "b.f" ] } ) == { SENSITIVE: { "count": 12, "first_ids": ids[ :10 ] }, "EXCLUDED_PREFIX": { "count": 1, "first_ids": [ "b.f" ] } }
    assert rt.dropped_view( { SENSITIVE: [], "EXCLUDED_PREFIX": [] } ) == {} and rt.DROPPED_IDS_SHOWN == 10


def test_the_judge_reads_the_whole_docstring_and_an_entry_with_a_secret_only_there_is_dropped_and_reported( notes_env ):
    # red when: c1_hits stops reading doc_full (the address would leave the machine), or prepare discards the dropped ids again
    fake = AllReuse()
    r    = rt.check_exists_impl( NEED, ctx_of( notes_env, fake ), language="py" )
    text = " ".join( asked( fake ) )
    assert "Longer text that explains the whole thing." in text and "ops@example.com" not in text and "cosa.notes.leaky" not in text
    assert r[ "dropped" ] == { SENSITIVE: { "count": 1, "first_ids": [ "cosa.notes.leaky" ] } }
    assert receipt_of( notes_env, r )[ "dropped" ] == r[ "dropped" ]


def test_a_prefix_drop_is_reported_too_and_a_clean_index_reports_nothing( notes_env, tmp_path ):
    held = rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse(), exclude_prefixes=( "cosa.mathx", ) ), language="py" )
    assert held[ "dropped" ][ "EXCLUDED_PREFIX" ] == { "count": 1, "first_ids": [ "cosa.mathx.add" ] }
    ( notes_env[ 0 ] / "src" / "cosa" / "notes.py" ).unlink()
    clean = rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse() ), language="py" )
    assert clean[ "dropped" ] == {} and "dropped" not in receipt_of( notes_env, clean )              # a clean call keeps its receipt bytes


def test_fetch_similar_names_the_pattern_found_in_the_whole_docstring( notes_env ):
    r = rt.fetch_similar_impl( "cosa.notes.leaky", ctx_of( notes_env, AllReuse() ), language="py" )
    assert ( r[ "error" ], r[ "detail" ] ) == ( SENSITIVE, "email" )


def write_purposes( env, rows ):
    path = env[ 1 ].parent / "purpose.jsonl"
    path.write_text( "".join( json.dumps( r ) + "\n" for r in rows ), encoding="utf-8" )
    return path


def pin_of( env, name ):
    gen = bd.current_generation( env[ 2 ] )
    return next( r[ "pin" ] for r in bd.read_searchable( gen ) if r[ "id" ] == name )


def test_a_stored_purpose_line_reaches_the_judge_the_index_sha_and_the_snapshot( notes_env ):
    # red when: prepare stops attaching the line, drops it from the index_sha (a pin that gains a line keeps its search_sha), or from the snapshot
    plain = rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse() ), language="py" )
    pin   = pin_of( notes_env, "cosa.feeds.parse_feed" )
    path  = write_purposes( notes_env, [ { "pin": pin, "purpose": "reads feeds" }, { "pin": pin, "purpose": "second row loses" } ] )
    fake  = AllReuse()
    one   = rt.check_exists_impl( NEED, ctx_of( notes_env, fake, purposes_path=path ), language="py" )
    assert "purpose: reads feeds" in " ".join( asked( fake ) ) and "second row loses" not in " ".join( asked( fake ) )
    assert one[ "index_sha" ] != plain[ "index_sha" ]
    held = { e[ "id" ]: e for e in rt.load_snapshot( ctx_of( notes_env, fake ), one[ "index_sha" ] )[ 0 ] }
    assert held[ "cosa.feeds.parse_feed" ][ "purpose" ] == "reads feeds" and "purpose" not in held[ "cosa.mathx.add" ]
    path = write_purposes( notes_env, [ { "pin": pin, "purpose": "reads feeds, changed" } ] )
    two  = rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse(), purposes_path=path ), language="py" )
    assert two[ "index_sha" ] != one[ "index_sha" ]
    rep  = rt.replay_impl( one[ "receipt_id" ], ctx_of( notes_env, fake, purposes_path=write_purposes( notes_env, [ { "pin": pin, "purpose": "reads feeds" } ] ) ) )
    assert rep[ "status" ] == "ok" and rep[ "differences" ][ "frozen" ] == []


def test_a_purpose_line_that_carries_an_address_drops_its_entry( notes_env ):
    rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse() ), language="py" )                         # builds the index, so a pin can be read
    path = write_purposes( notes_env, [ { "pin": pin_of( notes_env, "cosa.mathx.add" ), "purpose": "mail ops@example.com" } ] )
    r    = rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse(), purposes_path=path ), language="py" )
    assert r[ "dropped" ][ SENSITIVE ] == { "count": 2, "first_ids": [ "cosa.mathx.add", "cosa.notes.leaky" ] }      # the notes entry leaks in its docstring


def test_a_missing_purpose_file_means_no_lines( notes_env, tmp_path ):
    r = rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse(), purposes_path=tmp_path / "absent.jsonl" ), language="py" )
    plain = rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse() ), language="py" )
    assert r[ "index_sha" ] == plain[ "index_sha" ]


def test_a_snapshot_written_before_the_new_keys_replays_its_frozen_text( notes_env, monkeypatch ):
    # The judged records carry no doc_full here, as a receipt from before this change did; the replay, with the new code, must rebuild that old text.
    real = bd.read_searchable
    monkeypatch.setattr( rt.sx_build, "read_searchable", lambda gen, tests=False: [ { k: v for k, v in r.items() if k != "doc_full" } for r in real( gen, tests ) ] )
    fake = AllReuse()
    old  = rt.check_exists_impl( NEED, ctx_of( notes_env, fake ), language="py" )
    assert "Longer text" not in " ".join( asked( fake ) )
    monkeypatch.undo()
    rep = rt.replay_impl( old[ "receipt_id" ], ctx_of( notes_env, fake ) )
    assert rep[ "status" ] == "ok" and rep[ "differences" ][ "frozen" ] == []
    assert "doc_full" not in rt.load_snapshot( ctx_of( notes_env, fake ), old[ "index_sha" ] )[ 0 ][ 0 ]


def test_a_packed_context_reads_purposes_from_its_candidate_stage( notes_env, monkeypatch ):
    stage = types.SimpleNamespace( purposes_path=pathlib.Path( "/x/purpose.jsonl" ) )
    monkeypatch.setattr( rt, "_packed_settings", lambda top: { "candidate_stage": stage } )
    assert rt.context_from_environment( notes_env[ 0 ] ).purposes_path == pathlib.Path( "/x/purpose.jsonl" )
    monkeypatch.setattr( rt, "_packed_settings", lambda top: {} )
    assert rt.context_from_environment( notes_env[ 0 ] ).purposes_path is None


# --- a purpose file that ends in a line still being written ---------------------------------------------------------------------------------

TORN = '{"pin": "p9", "purp'


def test_read_purposes_skips_and_reports_a_torn_last_line_and_still_refuses_a_damaged_one( tmp_path ):
    from cosa.repo.symindex.candidates import search
    path = tmp_path / "purpose.jsonl"
    path.write_text( json.dumps( { "pin": "pa", "purpose": "first" } ) + "\n" + TORN, encoding="utf-8" )
    torn = []
    assert search.read_purposes( path, torn ) == { "pa": "first" } and torn == [ TORN ]
    assert search.read_purposes( path ) == { "pa": "first" }                                 # no list asked for: skipped without a report
    path.write_text( TORN + "\n" + json.dumps( { "pin": "pa", "purpose": "first" } ) + "\n", encoding="utf-8" )
    with pytest.raises( ValueError ): search.read_purposes( path, [] )                    # a bad line before the last is a damaged file
    path.write_text( "", encoding="utf-8" )
    assert search.read_purposes( path, torn ) == {}


def test_a_torn_last_line_of_the_purpose_file_does_not_stop_a_call_and_is_named_in_the_result( notes_env ):
    # red when: prepare lets the JSON error out (every call would raise while the file is being rewritten)
    rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse() ), language="py" )                         # builds the index, so a pin can be read
    path = write_purposes( notes_env, [ { "pin": pin_of( notes_env, "cosa.feeds.parse_feed" ), "purpose": "reads feeds" } ] )
    path.write_text( path.read_text( encoding="utf-8" ) + TORN, encoding="utf-8" )
    fake = AllReuse()
    r    = rt.check_exists_impl( NEED, ctx_of( notes_env, fake, purposes_path=path ), language="py" )
    assert r[ "status" ] == "ok" and "purpose: reads feeds" in " ".join( asked( fake ) )                # the whole line before it is still used
    assert [ n[ "note" ] for n in r[ "notes" ] ] == [ "PURPOSE_LINE_TORN" ] and "purpose.jsonl" in r[ "notes" ][ 0 ][ "detail" ]
    assert receipt_of( notes_env, r )[ "notes" ] == r[ "notes" ]
    clean = rt.check_exists_impl( NEED, ctx_of( notes_env, AllReuse() ), language="py" )
    assert clean[ "notes" ] == [] and "notes" not in receipt_of( notes_env, clean )


def test_the_candidate_stage_reads_a_purpose_file_with_a_torn_last_line( world ):
    # red when: the stage's own read of the file raises, which failed every packed check_exists
    from tests.unit.test_reuse_candidates_client import lookup
    make, _, _, root, *_ = world
    path = root / "purposes.jsonl"
    path.write_text( path.read_text( encoding="utf-8" ) + TORN, encoding="utf-8" )
    assert lookup( make() )[ "ids" ]
