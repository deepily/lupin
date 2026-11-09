"""
Every bundle a page loads is built by `npm run build`, and the image carries it.

The dist folder is gitignored and dockerignored, so a bundle exists only where something runs its
driver. A page can load `/static/dist/<dir>/...` while no builder produces that dir. The page then works
without the bundle and nobody sees a failure. This file starts from the pages, which are the
consumers. Each dir they name is checked against three builders. They are package.json's `build`
script, the Dockerfile's builder stage, and the Dockerfile's runtime copy.

Venue: :7999-eligible, reads tracked files only.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT  = Path( __file__ ).resolve().parents[ 3 ]
SCRIPTS    = REPO_ROOT / "src" / "scripts"
HTML_DIR   = REPO_ROOT / "src" / "lupin_app" / "static" / "html"
DOCKERFILE = REPO_ROOT / "docker" / "lupin" / "Dockerfile"
BUILDER    = "multiplexer-builder"

DIST_REF = re.compile( r"/static/dist/([A-Za-z0-9_-]+)/" )
DRIVER   = re.compile( r"bash src/scripts/(build-[A-Za-z0-9_-]+\.sh)" )


def drivers_run_by_build( package_text ):
    """Return the driver file names the package.json `build` script runs."""
    return DRIVER.findall( json.loads( package_text )[ "scripts" ][ "build" ] )


def driver_facts( name ):
    """Return the entry file and the dist dir name a driver declares."""
    text = ( SCRIPTS / name ).read_text( encoding="utf-8" )
    return {
        "entry"       : re.search( r'^ENTRY="([^"]+)"', text, re.M ).group( 1 ),
        "outdir_name" : re.search( r'^OUTDIR="[^"]*/dist/([^"/]+)"', text, re.M ).group( 1 ),
    }


def dist_dirs_loaded_by_pages():
    """Return the dist dir names that any tracked page loads."""
    found = set()
    for page in HTML_DIR.glob( "*.html" ):
        found.update( DIST_REF.findall( page.read_text( encoding="utf-8" ) ) )
    return found


def builder_stage( dockerfile_text ):
    """Return the text of the multiplexer-builder stage, up to the next stage."""
    start = dockerfile_text.index( f"AS {BUILDER}" )
    end   = dockerfile_text.find( "\nFROM ", start )
    return dockerfile_text[ start : end if end != -1 else len( dockerfile_text ) ]


def drivers_missing_from_stage( stage_text, drivers ):
    """Return the drivers the builder stage does not copy into /build."""
    return [ d for d in drivers if not re.search( rf"^COPY\s+src/scripts/{re.escape( d )}\s", stage_text, re.M ) ]


def dirs_missing_from_runtime( dockerfile_text, dirs ):
    """Return the dist dirs that no cross-stage copy carries out of the builder."""
    return [ d for d in dirs if f"/build/src/lupin_app/static/dist/{d}" not in dockerfile_text ]


def entries_outside_stage_sources( stage_text, entries ):
    """Return the entry files that no source copy in the builder stage covers."""
    copied = re.findall( r"^COPY\s+(src/lupin_app/static/js/[^\s]+)\s", stage_text, re.M )
    return [ e for e in entries if not any( e.startswith( c.rstrip( "/" ) + "/" ) for c in copied ) ]


PACKAGE = ( REPO_ROOT / "package.json" ).read_text( encoding="utf-8" )
DOCKER  = DOCKERFILE.read_text( encoding="utf-8" )


def test_the_discovery_found_what_it_is_meant_to_find():
    """Pin the floor: a loop over nothing passes every assertion in it."""
    assert { "multiplexer", "console", "doc-podcast" } <= dist_dirs_loaded_by_pages()
    assert { "build-multiplexer.sh", "build-console.sh", "build-doc-podcast.sh" } <= set( drivers_run_by_build( PACKAGE ) )


def test_every_dist_dir_a_page_loads_is_built_by_npm_run_build():
    built   = { driver_facts( d )[ "outdir_name" ] for d in drivers_run_by_build( PACKAGE ) }
    missing = sorted( dist_dirs_loaded_by_pages() - built )
    assert not missing, f"pages load these dist dirs but `npm run build` builds none of them: {missing}"


def test_the_dockerfile_builder_stage_copies_every_driver_npm_run_build_runs():
    missing = drivers_missing_from_stage( builder_stage( DOCKER ), drivers_run_by_build( PACKAGE ) )
    assert not missing, f"the {BUILDER} stage runs `npm run build` without these drivers: {missing}"


def test_the_runtime_stage_copies_every_dist_dir_the_build_produces():
    dirs    = { driver_facts( d )[ "outdir_name" ] for d in drivers_run_by_build( PACKAGE ) }
    missing = dirs_missing_from_runtime( DOCKER, sorted( dirs ) )
    assert not missing, f"built in the {BUILDER} stage and never copied into the image: {missing}"


def test_the_builder_stage_carries_each_drivers_sources():
    entries = [ driver_facts( d )[ "entry" ] for d in drivers_run_by_build( PACKAGE ) ]
    missing = entries_outside_stage_sources( builder_stage( DOCKER ), entries )
    assert not missing, f"the {BUILDER} stage copies no source tree holding these entries: {missing}"


def test_the_podcast_driver_is_in_the_freshness_checkers_census():
    from scripts import check_bundle_freshness as freshness
    assert "build-doc-podcast.sh" in { p.name for p in freshness.discover_bundles( REPO_ROOT ) }


# ---- negative controls: each check fires when its builder is missed ----

def test_NEGATIVE_a_build_script_without_the_podcast_driver_is_caught():
    stripped = PACKAGE.replace( " && bash src/scripts/build-doc-podcast.sh", "" )
    assert stripped != PACKAGE, "the control did not remove anything"
    built = { driver_facts( d )[ "outdir_name" ] for d in drivers_run_by_build( stripped ) }
    assert "doc-podcast" in dist_dirs_loaded_by_pages() - built


def test_NEGATIVE_a_builder_stage_without_the_podcast_copy_is_caught():
    stripped = DOCKER.replace( "COPY src/scripts/build-doc-podcast.sh ./src/scripts/build-doc-podcast.sh\n", "" )
    assert stripped != DOCKER
    assert drivers_missing_from_stage( builder_stage( stripped ), drivers_run_by_build( PACKAGE ) ) == [ "build-doc-podcast.sh" ]


def test_NEGATIVE_a_runtime_stage_without_the_podcast_dir_is_caught():
    stripped = DOCKER.replace( "/build/src/lupin_app/static/dist/doc-podcast", "/build/removed" )
    assert stripped != DOCKER
    assert dirs_missing_from_runtime( stripped, [ "doc-podcast", "console" ] ) == [ "doc-podcast" ]


def test_NEGATIVE_an_entry_outside_every_copied_source_tree_is_caught():
    assert entries_outside_stage_sources( builder_stage( DOCKER ), [ "src/lupin_app/static/js/elsewhere/boot.ts" ] ) \
        == [ "src/lupin_app/static/js/elsewhere/boot.ts" ]
