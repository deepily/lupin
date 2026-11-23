"""
The 512 known answers: the manifest of record is pinned by sha and by count.
"""
import json
import pathlib

import pytest

from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import known_answers as ka

DATA = pathlib.Path( __file__ ).resolve().parents[ 1 ] / "data" / "reuse_needset" / ka.MANIFEST_NAME


def condition_of( path, **kw ):
    """Return the condition word load_known_answers fails with."""
    with pytest.raises( er.NeedsetError ) as e: ka.load_known_answers( path, **kw )
    assert e.value.code == er.MANIFEST_MISMATCH
    return e.value.detail.split( ":" )[ 0 ]


def mutated( tmp_path, change ):
    """Write the committed manifest with change applied; return its path and its sha."""
    m = json.loads( DATA.read_text( encoding="utf-8" ) )
    change( m )
    p = tmp_path / ka.MANIFEST_NAME
    p.write_text( json.dumps( m ), encoding="utf-8" )
    return p, ka.file_sha256( p )


def test_the_committed_manifest_is_the_pinned_one_and_holds_512():
    got = ka.load_known_answers( DATA )
    assert ka.file_sha256( DATA ) == "9c89683cb34a9ef02c6b8e20dc32c042fba66039afe844e10848d973ef7a2347"
    assert len( got[ "need_ids" ] ) == 512 and got[ "manifest" ][ "count" ] == 512
    assert len( got[ "manifest" ][ "old124" ][ "need_ids" ] ) == 124 and len( got[ "manifest" ][ "new388" ][ "need_ids" ] ) == 388
    assert got[ "manifest" ][ "old124" ][ "corpus_commit" ].startswith( "c855c621" ) and got[ "manifest" ][ "new388" ][ "corpus_commit" ].startswith( "679621e2" )


def test_a_changed_manifest_fails_the_sha_pin( tmp_path ):
    p, _ = mutated( tmp_path, lambda m: m.update( note="x" ) )
    assert condition_of( p ) == "sha"


def re_pinned( tmp_path, change ):
    """Return the condition load_known_answers fails with after change, with the sha re-pinned."""
    p, sha = mutated( tmp_path, change )
    return condition_of( p, expected_sha=sha )


def test_a_dropped_id_is_a_count_refusal( tmp_path ):
    assert re_pinned( tmp_path, lambda m: m[ "new388" ][ "need_ids" ].pop() ) == "count"


def test_a_wrong_count_field_is_a_count_refusal( tmp_path ):
    assert re_pinned( tmp_path, lambda m: m.update( count=511 ) ) == "count"


def test_an_id_moved_between_corpora_is_a_split_refusal( tmp_path ):
    assert re_pinned( tmp_path, lambda m: m[ "old124" ][ "need_ids" ].append( m[ "new388" ][ "need_ids" ].pop() ) ) == "split"


def test_a_repeated_id_is_an_ids_refusal( tmp_path ):
    def repeat_id( m ): m[ "new388" ][ "need_ids" ][ 0 ] = m[ "old124" ][ "need_ids" ][ 0 ]
    assert re_pinned( tmp_path, repeat_id ) == "ids"


def test_a_wrong_new388_commit_is_a_commit_refusal( tmp_path ):
    def wrong( m ): m[ "new388" ][ "corpus_commit" ] = "0" * 40
    assert re_pinned( tmp_path, wrong ) == "commit"


def test_a_wrong_old124_commit_is_a_commit_refusal( tmp_path ):
    def wrong( m ): m[ "old124" ][ "corpus_commit" ] = "0" * 40
    assert re_pinned( tmp_path, wrong ) == "commit"


def test_the_old_124_come_before_the_new_388():
    got   = ka.load_known_answers( DATA )
    ids   = got[ "need_ids" ]
    old   = got[ "manifest" ][ "old124" ][ "need_ids" ]
    new   = got[ "manifest" ][ "new388" ][ "need_ids" ]
    assert ids[ :124 ] == old and ids[ 124: ] == new and old[ 0 ] != new[ 0 ]
