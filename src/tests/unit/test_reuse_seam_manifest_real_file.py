"""
Seam: the frozen twin manifest, the real file, read by the real loader.

The fixture is the manifest file of the recall baseline, byte for byte (sha256 recorded below).
Until now the loader was read only against synthetic manifests.
A real file of another shape would have stopped every step of a live run at its start.
The sample is the committed frozen sample. Nothing here sends a request.
"""
import hashlib
import json
import pathlib

import pytest

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_stage2_fit as fit

FIXTURES = pathlib.Path( __file__ ).resolve().parent.parent / "fixtures" / "reuse_e2e"
MANIFEST = FIXTURES / "manifest-baseline-2026.10.06.json"
SAMPLE   = FIXTURES / "sample-by-component-58-42-seed-20261007.json"
MANIFEST_SHA = "bfbfceab399cf753093f0c9ee0bec73a0de00738a0696126a669e129de466941"


def test_the_fixture_is_the_manifest_the_code_and_the_sample_both_name():
    assert hashlib.sha256( MANIFEST.read_bytes() ).hexdigest() == MANIFEST_SHA == e2e.MANIFEST_SHA256
    assert json.loads( SAMPLE.read_text( encoding="utf-8" ) )[ "manifest_sha256" ] == MANIFEST_SHA


def test_the_real_manifest_loads_through_the_loader_into_one_entry_per_distinct_member():
    twins  = e2e.load_twins( MANIFEST )
    counts = json.loads( MANIFEST.read_text( encoding="utf-8" ) )[ "counts" ]
    assert len( twins ) == counts[ "distinct_members" ] == 376
    assert all( m not in ts and ts for m, ts in twins.items() )          # nobody is their own twin; everybody has one
    assert twins == fit.twin_map_from_manifest( json.loads( MANIFEST.read_text( encoding="utf-8" ) ) )


def test_every_member_of_the_frozen_sample_has_a_twin_in_the_real_manifest():
    twins   = e2e.load_twins( MANIFEST )
    members = e2e.load_sample( SAMPLE )
    assert len( members ) == 100 and all( twins.get( m ) for m in members )
    manifest = json.loads( MANIFEST.read_text( encoding="utf-8" ) )
    exact    = { i[ "id" ] for r in manifest[ "exact" ] for i in r[ "members" ] }
    assert sum( 1 for m in members[ :58 ] if m in exact ) == 56 and not any( m in exact for m in members[ 58: ] )


def test_the_loader_refuses_the_real_file_under_any_other_hash():
    with pytest.raises( e2e.FrozenInputRefused, match="sha256" ): e2e.load_twins( MANIFEST, "0" * 64 )
