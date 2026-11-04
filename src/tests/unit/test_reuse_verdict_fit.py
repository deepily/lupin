"""
The receipt writer that fits the verdict layer's threshold on the labelled set.
"""
import json

import pytest

from lupin_mcp import reuse_verdict_fit as vf


def _row( member, candidate, label, p ):
    return { "member": member, "candidate": candidate, "label": label, "provides": None, "coverage": None, "score": None, "p_overlap": p, "malformed": None, "unasked": False }


def _split():
    return { "fit": [ { "stratum": "exact", "members": [ "a", "b" ] } ], "check": [ { "stratum": "exact", "members": [ "c", "d" ] } ] }


def _rows():
    out = []
    for m, tp in ( ( "a", 0.9 ), ( "b", 0.8 ), ( "c", 0.85 ), ( "d", 0.7 ) ):
        out += [ _row( m, f"{m}-twin", True, tp ), _row( m, f"{m}-n1", False, 0.2 ), _row( m, f"{m}-n2", False, 0.1 ) ]
    return out


def _record():
    return { "format": "stage2-negatives-1", "inputs": { "manifest_sha256": "m" * 64, "symbols_sha256": "s" * 64, "old_stage2_sha256": "o" * 64 },
             "members": { m: { "twins": [ f"{m}-twin" ], "lexical": [ { "id": f"{m}-n1", "score": 0.5 } ], "random": [ f"{m}-n2" ], "held_out": [] } for m in "abcd" } }


def test_the_receipt_names_the_fitted_threshold_the_default_strong_and_the_uncovered_pairs_by_class():
    rec = _record()
    rec[ "members" ][ "a" ][ "lexical" ].append( { "id": "a-gone", "score": 0.3 } )
    got = vf.receipt( rec, _rows(), _split(), 0.05, "r" * 64 )
    assert got[ "format" ] == vf.FORMAT and got[ "rate" ] == 0.05
    assert got[ "threshold" ][ "fitted" ] is True and 0.1 < got[ "threshold" ][ "value" ] <= 0.7
    assert got[ "strong" ] == { "value": 0.9, "fitted": False, "reason": vf.STRONG_REASON }
    assert got[ "uncovered_counts" ] == { "twins": 0, "lexical": 1, "random": 0 } and got[ "uncovered" ][ "lexical" ] == [ [ "a", "a-gone" ] ]
    assert got[ "inputs" ] == { "manifest_sha256": "m" * 64, "symbols_sha256": "s" * 64, "old_stage2_sha256": "o" * 64, "answered_rows_sha256": "r" * 64 }
    assert got[ "set" ] == { "rows": 12, "twin_rows": 4, "held_out": 0, "ignored_rows": 0 }
    assert set( got[ "on_fit" ] ) >= { "false_reuse_rate", "twin_recall" } and set( got[ "on_check" ] ) >= { "false_reuse_rate", "twin_recall" }


def test_the_receipt_refuses_a_set_with_an_uncovered_twin():
    rows = [ r for r in _rows() if r[ "candidate" ] != "a-twin" ]
    with pytest.raises( ValueError, match="twin" ): vf.receipt( _record(), rows, _split(), 0.05, "r" * 64 )


def test_main_writes_the_receipt_once_and_never_over_an_existing_one( tmp_path ):
    paths = { k: tmp_path / f"{k}.json" for k in ( "neg", "rows", "split", "out" ) }
    paths[ "neg" ].write_text( json.dumps( _record() ) )
    paths[ "rows" ].write_text( json.dumps( { "format": "stage2-rows-1", "rows": _rows() } ) )
    paths[ "split" ].write_text( json.dumps( _split() ) )
    argv = [ "--negatives", str( paths[ "neg" ] ), "--rows", str( paths[ "rows" ] ), "--split", str( paths[ "split" ] ), "--rate", "0.05", "--out", str( paths[ "out" ] ) ]
    assert vf.main( argv ) == 0
    written = json.loads( paths[ "out" ].read_text() )
    assert written[ "threshold" ][ "fitted" ] is True and written[ "inputs" ][ "answered_rows_sha256" ]
    with pytest.raises( FileExistsError ): vf.main( argv )


def test_a_policy_recorded_with_a_band_under_the_floor_is_refused_and_a_band_at_the_floor_is_recorded():
    with pytest.raises( ValueError, match="0.05" ): vf.receipt( _record(), _rows(), _split(), 0.05, "r" * 64, band=0.01 )
    got = vf.receipt( _record(), _rows(), _split(), 0.05, "r" * 64, band=0.05 )
    assert got[ "band" ] == { "value": 0.05, "fitted": False, "reason": vf.BAND_GIVEN_REASON }


def test_without_a_band_the_receipt_says_it_was_not_measured_and_never_invents_one():
    assert vf.receipt( _record(), _rows(), _split(), 0.05, "r" * 64 )[ "band" ] == { "value": None, "fitted": False, "reason": vf.BAND_MISSING_REASON }


def test_main_refuses_a_band_under_the_floor_before_writing( tmp_path ):
    for name, data in ( ( "neg", _record() ), ( "rows", { "rows": _rows() } ), ( "split", _split() ) ): ( tmp_path / f"{name}.json" ).write_text( json.dumps( data ) )
    argv = [ "--negatives", str( tmp_path / "neg.json" ), "--rows", str( tmp_path / "rows.json" ), "--split", str( tmp_path / "split.json" ), "--rate", "0.05", "--out", str( tmp_path / "o.json" ), "--band", "0.02" ]
    with pytest.raises( ValueError, match="0.05" ): vf.main( argv )
    assert not ( tmp_path / "o.json" ).exists()


@pytest.mark.parametrize( "change", [ { "unasked": True, "p_overlap": None }, { "malformed": "x", "p_overlap": 0.9 } ] )
def test_a_twin_that_was_never_asked_or_came_back_unreadable_is_refused_not_scored_as_a_miss( change ):
    rows = [ { **r, **change } if r[ "candidate" ] == "a-twin" else r for r in _rows() ]
    with pytest.raises( ValueError, match="twin" ): vf.receipt( _record(), rows, _split(), 0.05, "r" * 64 )


def _argv( tmp_path, out ):
    for name, data in ( ( "neg", _record() ), ( "rows", { "rows": _rows() } ), ( "split", _split() ) ): ( tmp_path / f"{name}.json" ).write_text( json.dumps( data ) )
    return [ "--negatives", str( tmp_path / "neg.json" ), "--rows", str( tmp_path / "rows.json" ), "--split", str( tmp_path / "split.json" ), "--rate", "0.05", "--out", str( out ) ]


def test_a_file_that_appears_after_the_check_is_never_overwritten_and_no_temporary_file_is_left( tmp_path, monkeypatch ):
    out  = tmp_path / "o.json"
    real = vf.receipt
    def appears( *a, **k ):
        out.write_text( "someone else's receipt" )                 # a concurrent run lands its file between the check and the write
        return real( *a, **k )
    monkeypatch.setattr( vf, "receipt", appears )
    with pytest.raises( FileExistsError ): vf.main( _argv( tmp_path, out ) )
    assert out.read_text() == "someone else's receipt"
    assert sorted( p.name for p in tmp_path.iterdir() ) == [ "neg.json", "o.json", "rows.json", "split.json" ]


def test_the_receipt_appears_whole_under_its_name_and_no_temporary_file_is_left( tmp_path ):
    out = tmp_path / "o.json"
    assert vf.main( _argv( tmp_path, out ) ) == 0
    assert json.loads( out.read_text() )[ "format" ] == vf.FORMAT
    assert sorted( p.name for p in tmp_path.iterdir() ) == [ "neg.json", "o.json", "rows.json", "split.json" ]


def test_the_temporary_file_is_removed_when_the_name_is_taken_at_the_moment_of_linking( tmp_path, monkeypatch ):
    out = tmp_path / "o.json"
    real_link = vf.os.link
    def taken( src, dst ):
        out.write_text( "taken at the last moment" )
        return real_link( src, dst )
    monkeypatch.setattr( vf.os, "link", taken )
    with pytest.raises( FileExistsError ): vf.main( _argv( tmp_path, out ) )
    assert out.read_text() == "taken at the last moment" and sorted( p.name for p in tmp_path.iterdir() ) == [ "neg.json", "o.json", "rows.json", "split.json" ]
