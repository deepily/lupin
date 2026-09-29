"""
No browser client under src/lupin_app/static calls a retired door (row 67a2a093).

The census that found ZERO in-repo callers on the twelve retired doors was a one-off
grep on 2026-09-28. It was true when taken and nothing kept it true: the two resume doors
still had three live call sites (notifications.js twice, SubmitJobsStore.ts) until this
row moved them, and a caller left on a 410 fails only when a person clicks the button.

The predicate is "no CODE line in a served .js/.ts file names a retired door's path" — not
"these three lines were changed". A path parameter (`{id_hash}`) matches a template
placeholder (`${jobId}`) or any other non-slash run. Comment lines are skipped, because the
migration notes name the old doors on purpose.
"""
import json
import re
from pathlib import Path

import pytest

from cosa.rest.routers._retired_doors import RETIRED_DOORS
from cosa.utils import util as cu

STATIC = Path( cu.get_project_root() ) / "src" / "lupin_app" / "static"


def _door_regex( door ):
    """/api/jobs/{id_hash}/x -> a regex matching /api/jobs/${jobId}/x, /api/jobs/abc/x, …"""
    parts = re.split( r"(\{[^}]+\})", door )
    body  = "".join( r"[^/'\"`\s]+" if p.startswith( "{" ) else re.escape( p ) for p in parts )
    return re.compile( body + r"(?![\w/-])" )


def _is_comment( line ):
    return line.lstrip().startswith( ( "//", "*", "/*", "#" ) )


def _hits( text, door ):
    rx = _door_regex( door )
    return [ ( n, line.strip() ) for n, line in enumerate( text.splitlines(), 1 )
             if rx.search( line ) and not _is_comment( line ) ]


_HASHED_BUNDLE = re.compile( r"\.[0-9a-f]{12}\.js$" )


def _served_hashed_bundles( root ):
    """
    The content-hashed bundles a manifest.json under `root` names as current.

    static/dist is gitignored build output and every rebuild leaves the previous
    `boot.<hash>.js` behind, so a long-lived checkout carries dozens of bundles no page
    loads. Only the file each dist directory's manifest points at is served.
    """
    served = set()
    for manifest in root.rglob( "manifest.json" ):
        try:    entries = json.loads( manifest.read_text() )
        except ( OSError, ValueError ): continue
        served.update( manifest.parent / v for v in entries.values()
                       if isinstance( v, str ) and _HASHED_BUNDLE.search( v ) )
    return served


def _client_files( root=STATIC ):
    served = _served_hashed_bundles( root )
    return [ p for p in root.rglob( "*" )
             if p.suffix in ( ".js", ".ts" ) and "node_modules" not in p.parts and ".min." not in p.name
             and ( not _HASHED_BUNDLE.search( p.name ) or p in served ) ]


def test_the_corpus_is_found_and_is_not_empty():
    files = _client_files()
    assert len( files ) > 50, f"only {len( files )} client files under {STATIC}"
    assert any( p.name == "notifications.js" for p in files )
    assert any( p.name == "SubmitJobsStore.ts" for p in files )


@pytest.mark.parametrize( "door", sorted( RETIRED_DOORS ), ids=sorted( RETIRED_DOORS ) )
def test_no_client_file_calls_the_retired_door( door ):
    offenders = { str( p.relative_to( STATIC ) ): h for p in _client_files() if ( h := _hits( p.read_text( errors="replace" ), door ) ) }
    assert offenders == {}, f"{door} answers 410 but a client still calls it: {offenders}"


def test_the_detector_finds_the_two_shapes_the_original_callers_had():
    """Positive control: the exact lines this row removed are flagged; a comment is not."""
    old6 = "const response = await this.authedFetch( `/api/jobs/${jobId}/resume-from-checkpoint`, {"
    old7 = '"/api/test-fix-expediter/resume-from", { resume_from: text },'
    assert _hits( old6, "/api/jobs/{id_hash}/resume-from-checkpoint" )
    assert _hits( old7, "/api/test-fix-expediter/resume-from" )
    assert _hits( "// POSTs to /api/test-fix-expediter/resume-from", "/api/test-fix-expediter/resume-from" ) == []
    assert _hits( "await f( '/api/v2/resume-job' )", "/api/test-fix-expediter/resume-from" ) == []


def test_a_stale_hashed_bundle_is_not_scanned_but_the_manifests_target_is( tmp_path ):
    """
    dist/ keeps every earlier build's boot.<hash>.js (gitignored), so only the bundle the
    manifest names may count as a served client. Positive control on the same fixture: the
    current bundle IS in the corpus and its retired-door call IS found.
    """
    dist = tmp_path / "dist" / "multiplexer"
    dist.mkdir( parents=True )
    line = 'fetch( "/api/test-fix-expediter/resume-from" )'
    for name in ( "boot.aaaaaaaaaaaa.js", "boot.bbbbbbbbbbbb.js", "boot.js" ):
        ( dist / name ).write_text( line )
    ( dist / "manifest.json" ).write_text( json.dumps( { "boot.js": "boot.bbbbbbbbbbbb.js", "hash": "bbbbbbbbbbbb" } ) )

    names = sorted( p.name for p in _client_files( tmp_path ) )
    assert names == [ "boot.bbbbbbbbbbbb.js", "boot.js" ], names
    assert _hits( ( dist / "boot.bbbbbbbbbbbb.js" ).read_text(), "/api/test-fix-expediter/resume-from" )


def test_a_manifest_that_is_unreadable_serves_no_hashed_bundle( tmp_path ):
    dist = tmp_path / "d"
    dist.mkdir()
    ( dist / "boot.cccccccccccc.js" ).write_text( "x" )
    ( dist / "manifest.json" ).write_text( "{not json" )
    assert _client_files( tmp_path ) == []
