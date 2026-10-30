"""
Census guard: no tracked source file names a literal time zone unless exempt.

Rick's rule: the zone comes from configuration, never from the code. The sibling guard
test_every_app_timezone_read_comes_from_configuration only sees files that name the `app timezone`
key. A fallback in a file that never names the key slips past it.
So this guard walks every tracked .py, .js and .ts source file for a zone name written as a string.
A file on the exemption list is owed work. An entry whose literal is gone is stale and fails.
"""
import ast
import re
import subprocess

import cosa.utils.util as du

REGION  = r"(?:America|US|Etc|Europe|Asia|Pacific|Australia|Africa|Atlantic|Indian|Canada|Brazil)"
ZONE_RE = re.compile( rf"^{REGION}/[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+)?$" )
JS_RE   = re.compile( rf"""["'`]{REGION}/[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+)?["'`]""" )
SOURCE  = ( ".py", ".js", ".ts" )
SKIPPED = ( "/tests/", "/rnd/", "/.venv/", "/history/", "/node_modules/", "/dist/", "/ephemera/", "/testkit/", "/test_" )

# path -> why a literal zone is still there. FIX OWED is a fallback that must read configuration.
# LEGIT is a zone the file means on its own account, not a stand-in for the user's zone.
EXEMPT = {
    "src/cosa/agents/decision_proxy/config.py"           : "FIX OWED: DEFAULT_TIMEZONE backs the `decision proxy timezone` key and ~30 constructor calls",
    "src/cosa/agents/heartbeat_arbiter/arbiter_journal.py": "LEGIT: the module's own self-test names a zone",
    "src/cosa/agents/shared/report_writer.py"            : "LEGIT: the report filename convention fixes Eastern ( the EST token )",
    "src/cosa/repo/doc_lint/harness_schedule.py"         : "LEGIT: the harness schedule window is defined as 10:00 to 13:00 Eastern",
    "src/cosa/rest/db/embedding_regeneration.py"         : "LEGIT: the business-hours gate is defined in EDT, its parameter is named hour_edt",
    "src/cosa/utils/edt_timestamp.py"                    : "FIX OWED: None falls back to DEFAULT_TZ_NAME; dm.py passes none",
    "src/lupin_app/static/js/notifications.js"           : "FIX OWED: browser fallbacks when the config fetch fails; needs the :8000 JS tier",
    "src/lupin_mcp/reuse_needset/smoke.py"               : "LEGIT: the smoke schedule window is defined in Eastern, like the harness",
    "src/scripts/dm-experiment/generate_schedule.py"     : "LEGIT: the experiment schedule is defined in Eastern",
    "src/scripts/run-heartbeat-arbiter.py"               : "FIX OWED: a dev script passes a literal zone to the util helper",
}


def literal_zones( path, source ):
    """The zone names written as strings in one source file, as ( line, name ) pairs.

    Python is read with ast, so a docstring or comment naming a zone is not a hit. JavaScript and
    TypeScript are read line by line, skipping full-line comments.
    """
    if path.endswith( ".py" ):
        tree       = ast.parse( source )
        docstrings = { id( n.body[ 0 ].value ) for n in ast.walk( tree )
                       if isinstance( n, ( ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef ) )
                       and n.body and isinstance( n.body[ 0 ], ast.Expr ) and isinstance( n.body[ 0 ].value, ast.Constant ) }
        return [ ( n.lineno, n.value ) for n in ast.walk( tree )
                 if isinstance( n, ast.Constant ) and isinstance( n.value, str ) and id( n ) not in docstrings and ZONE_RE.match( n.value ) ]
    hits = []
    for number, line in enumerate( source.splitlines(), 1 ):
        if line.lstrip().startswith( ( "//", "*", "/*" ) ): continue
        hits.extend( ( number, m.group( 0 ).strip( "\"'`" ) ) for m in JS_RE.finditer( line ) )
    return hits


def _walk_tracked_sources():
    """Return ( paths walked, paths with their literal zones )."""
    root  = du.get_project_root()
    files = subprocess.run( [ "git", "ls-files" ], cwd=root, capture_output=True, text=True, check=True ).stdout.split( "\n" )
    files = [ f for f in files if f.endswith( SOURCE ) and not any( skip in "/" + f for skip in SKIPPED ) ]
    hits  = {}
    for rel in files:
        with open( f"{root}/{rel}", encoding="utf-8" ) as handle:
            found = literal_zones( rel, handle.read() )
        if found: hits[ rel ] = found
    return files, hits


def unexempt( hits ):
    """The hits in files that are not on the exemption list."""
    return { rel: found for rel, found in hits.items() if rel not in EXEMPT }


def test_the_finder_can_find_planted_fallbacks_in_python_and_javascript():
    """Positive control: each planted fallback shape is found; a docstring or comment is not."""
    assert literal_zones( "x.py", 'tz = ZoneInfo( "America/New_York" )  # Fallback' ) == [ ( 1, "America/New_York" ) ]
    assert literal_zones( "x.py", 'def f( tz_name="US/Eastern" ): pass' ) == [ ( 1, "US/Eastern" ) ]
    assert literal_zones( "x.py", 'zone = cfg.get( "k" ) or "Etc/GMT+5"' ) == [ ( 1, "Etc/GMT+5" ) ]
    assert literal_zones( "x.js", "const tz = this.appTimezone || 'America/New_York';" ) == [ ( 1, "America/New_York" ) ]
    assert literal_zones( "x.ts", 'let z = "Europe/Madrid";' ) == [ ( 1, "Europe/Madrid" ) ]
    assert literal_zones( "x.py", 'def f():\n    """Zone, e.g. America/New_York."""\n    # America/Chicago\n    return 1' ) == []
    assert literal_zones( "x.js", "// the zone is 'America/New_York'\n * 'US/Eastern'" ) == []
    assert literal_zones( "x.py", 'name = "a/b"\nroot = "src/cosa/foo"' ) == []


def test_a_planted_fallback_in_the_real_population_reddens_the_guard():
    """Mutant: a hit planted in a file off the list is the only thing left unexempted."""
    _, hits = _walk_tracked_sources()
    planted = { **hits, "src/cosa/rest/db/repositories/notification_repository.py": [ ( 1003, "America/New_York" ) ] }

    assert unexempt( hits ) == {}
    assert list( unexempt( planted ) ) == [ "src/cosa/rest/db/repositories/notification_repository.py" ]


def test_the_census_walks_a_real_population_and_finds_the_known_literals():
    """Assert the loop will find something before it loops."""
    files, hits = _walk_tracked_sources()
    assert len( files ) > 1000, f"only {len( files )} tracked source files walked"
    assert "src/lupin_app/static/js/notifications.js" in hits and "src/cosa/utils/edt_timestamp.py" in hits


def test_no_tracked_source_file_names_a_literal_zone_unless_it_is_exempt():
    """The zone comes from configuration: a literal zone in a file off the exemption list fails."""
    _, hits = _walk_tracked_sources()
    bad     = unexempt( hits )

    assert not bad, "a time zone is written in code, not read from configuration:\n" + "\n".join(
        f"  {rel}:{line} {name!r}" for rel, found in sorted( bad.items() ) for line, name in found )


def test_every_exemption_still_names_a_literal_zone():
    """An entry whose literal is gone is stale and must be deleted, so the list only shrinks."""
    _, hits = _walk_tracked_sources()
    stale   = sorted( rel for rel in EXEMPT if rel not in hits )

    assert not stale, f"stale exemptions, delete them: {stale}"
