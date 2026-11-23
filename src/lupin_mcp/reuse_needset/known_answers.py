"""
The 512 known answers: the reuse diagnostic set of record.

It replaced the 400-need target. The 512 pools two corpora, the old 124 and the new 388.
Each corpus has its own commit, held in OLD_COMMIT and NEW_COMMIT below.
This module pins the manifest by its sha256 and checks the count.
A reader that loads the set cannot get a different one.
It reads the manifest only. The 400-need path in finalize.py is a separate shape and is unchanged.
"""
import json
import pathlib

from cosa.utils.file_hash import file_sha256
from lupin_mcp.reuse_needset.finalize import _mismatch

MANIFEST_NAME   = "known-answers-512-manifest.json"
MANIFEST_SHA    = "9c89683cb34a9ef02c6b8e20dc32c042fba66039afe844e10848d973ef7a2347"
EXPECTED_COUNT  = 512
OLD_COMMIT      = "c855c62115cdfa8d3a2d19c1ed8f0d409b776d15"
NEW_COMMIT      = "679621e2b234105f1b7cae14ea852bc78e53e7ad"
EXPECTED_SPLIT  = { "old124": 124, "new388": 388 }


def load_known_answers( path, expected_sha=MANIFEST_SHA ):
    """
    Read the 512 manifest and check it is the one of record.

    The file is opened for reading only.

    Requires:
        - path is the known-answers-512-manifest.json of the run folder, projects-data/lupin/reuse-review/needset-runs/2026.11.23-growth

    Ensures:
        - returns { "manifest": the parsed manifest, "need_ids": the old 124 then the new 388 in file order }
        - the file's sha256 equals expected_sha, count is 512, the corpora hold 124 and 388 ids with no id twice, and their commits are OLD_COMMIT and NEW_COMMIT

    Raises:
        - NeedsetError MANIFEST_MISMATCH starting its detail with the failed condition: sha, count, split, ids or commit
    """
    got = file_sha256( pathlib.Path( path ) )
    if got != expected_sha: _mismatch( "sha", f"{path}: sha256 {got} is not {expected_sha}" )
    manifest = json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )
    ids      = manifest[ "old124" ][ "need_ids" ] + manifest[ "new388" ][ "need_ids" ]
    split    = { "old124": len( manifest[ "old124" ][ "need_ids" ] ), "new388": len( manifest[ "new388" ][ "need_ids" ] ) }
    if manifest[ "count" ] != EXPECTED_COUNT or len( ids ) != EXPECTED_COUNT: _mismatch( "count", f"the manifest says {manifest[ 'count' ]} and lists {len( ids )}, expected {EXPECTED_COUNT}" )
    if split != EXPECTED_SPLIT: _mismatch( "split", f"{split}, expected {EXPECTED_SPLIT}" )
    if len( set( ids ) ) != len( ids ): _mismatch( "ids", f"{len( set( ids ) )} unique ids in {len( ids )}" )
    if manifest[ "old124" ][ "corpus_commit" ] != OLD_COMMIT or manifest[ "new388" ][ "corpus_commit" ] != NEW_COMMIT:
        _mismatch( "commit", f"the corpus commits are {manifest[ 'old124' ][ 'corpus_commit' ]} and {manifest[ 'new388' ][ 'corpus_commit' ]}" )
    return { "manifest": manifest, "need_ids": ids }
