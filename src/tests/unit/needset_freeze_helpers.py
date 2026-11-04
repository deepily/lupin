"""
A real index generation and a vector set built from it, for the tests of the frozen copy.

The generation comes from symindex.build on a small fixture repository. The build info comes from freshness.write_build_info.
So the hashes are the ones the real producers write.
"""
import json

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates import freshness as fr
from tests.unit.symindex_helpers import make_repo

BUILT_AT = "2026-10-25T12:00:00+00:00"


def built_pair( base, name="pair", built_at=BUILT_AT, extra_source=None ):
    """
    Build an index generation and a vector set folder under base/name.

    Requires:
        - extra_source is None, or a Python source text added to the fixture repository, so a second call yields another index

    Ensures:
        - returns ( generation folder, vector set folder ); the vector set holds build-info.json made by write_build_info and one other file
    """
    root = make_repo( base / name, "repo" )
    if extra_source is not None: ( root / "pkg" / "extra.py" ).write_text( extra_source, encoding="utf-8" )
    built = sx_build.build( root, base / name / "out" )
    vec   = base / name / "vectors"
    vec.mkdir()
    fr.write_build_info( vec, built[ "header" ], built_at )
    ( vec / "manifest.json" ).write_text( json.dumps( { "stand_in": True } ), encoding="utf-8" )
    return built[ "gen_dir" ], vec


def pair_once( base, name="source_pair" ):
    """Ensures: returns the pair under base/name, built once and found after."""
    if not ( base / name ).exists(): return built_pair( base, name )
    return next( ( base / name / "out" ).glob( "gen-*" ) ), base / name / "vectors"
