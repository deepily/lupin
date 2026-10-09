"""
A test that skips when Postgres is unreachable must tell a refused login from no server.

A skip reads green. The helper in tests.helpers.template_database fails a refused test login. It does so
only when the handler's try body calls it. This guard reads every tracked test file. It finds each handler
for OperationalError that calls pytest.skip. The try body must call the helper, or the handler must call
fail_on_a_refusal. A new site that skips on its own cannot slip in.

The lane-B probe returns False in its handler and skips elsewhere. Its own test file guards it.

A broad handler (Exception, SQLAlchemyError, a bare except) that skips is a second way past the helper.
The second census below lists every such file and compares it with a short named list. A new entry has
to be added there with its reason, so a fourth skip on a database connect is a visible decision.

The population is every tracked .py file under the two test roots, counted before the check.
"""

import ast
import os
import subprocess

ROOT    = os.environ[ "LUPIN_ROOT" ]
ROUTES  = ( "drop_database", "create_from_template", "throwaway_database", "fail_on_a_refusal" )


def _population():
    listed = subprocess.run( [ "git", "ls-files", "src/tests", "src/cosa/tests" ], cwd=ROOT, capture_output=True, text=True, check=True ).stdout.split()
    return [ path for path in listed if path.endswith( ".py" ) ]


def _calls( nodes ):
    names = set()
    for node in nodes:
        for sub in ast.walk( node ):
            if isinstance( sub, ast.Call ):
                func = sub.func
                names.add( func.attr if isinstance( func, ast.Attribute ) else getattr( func, "id", "" ) )
    return names


def _skipping_handlers( source ):
    """Return ( try node, handler ) for each OperationalError handler that calls pytest.skip."""
    found = [ ]
    for node in ast.walk( ast.parse( source ) ):
        if not isinstance( node, ast.Try ): continue
        for handler in node.handlers:
            kinds = [ n.id if isinstance( n, ast.Name ) else getattr( n, "attr", "" ) for n in ast.walk( handler.type ) ] if handler.type is not None else [ ]
            if "OperationalError" in kinds and "skip" in _calls( handler.body ): found.append( ( node, handler ) )
    return found


BROAD = ( "Exception", "BaseException", "SQLAlchemyError", "DBAPIError", "InterfaceError" )

# Files whose broad handler skips, and why that is allowed. The first three skip on a database connect
# and are left alone on purpose: they probe a rolled-back temp table, and a refused login there is not
# the failure class this guard exists for. The other five skip on an HTTP login to the app, not Postgres.
BROAD_SKIP_ALLOWED = {
    "src/tests/unit/test_metadata_schema_drift.py"                       : "database connect; drift is unmeasured, not claimed green",
    "src/tests/unit/test_task_promotion_ticket_answer_by_migration.py"   : "database connect; a rolled-back temp table probe with a loud skip",
    "src/tests/unit/test_task_request_columns_migration.py"              : "database connect; a rolled-back temp table probe with a loud skip",
    "src/tests/smoke/test_external_scopes.py"                            : "HTTP login to the app, not a database",
    "src/tests/websocket_smoke/core/test_close_codes.py"                 : "HTTP login to the app, not a database",
    "src/tests/ws_channel_browser/test_ws_circuit_banner.py"             : "HTTP login to the app, not a database",
    "src/tests/ws_channel_browser/test_ws_close_codes.py"                : "HTTP login to the app, not a database",
    "src/tests/ws_channel_browser/test_ws_lifecycle.py"                  : "HTTP login to the app, not a database",
}


def _broad_skip_files( population, read ):
    """Return the files with a broad or bare handler that calls pytest.skip."""
    found = [ ]
    for path in population:
        source = read( path )
        if "skip" not in source: continue
        for node in ast.walk( ast.parse( source ) ):
            if not isinstance( node, ast.Try ): continue
            for handler in node.handlers:
                kinds = [ n.id if isinstance( n, ast.Name ) else getattr( n, "attr", "" ) for n in ast.walk( handler.type ) ] if handler.type is not None else [ "<bare>" ]
                if ( set( kinds ) & set( BROAD ) or "<bare>" in kinds ) and "skip" in _calls( handler.body ):
                    found.append( path )
                    break
    return sorted( set( found ) )


def _read( path ):
    with open( os.path.join( ROOT, path ), encoding="utf-8", errors="replace" ) as handle: return handle.read()


def census( population, read ):
    """Return ( every skipping file, the files whose skip is not routed through the helper )."""
    skipping, unrouted = [ ], [ ]
    for path in population:
        source = read( path )
        if "OperationalError" not in source: continue
        handlers = _skipping_handlers( source )
        if not handlers: continue
        skipping.append( path )
        for try_node, handler in handlers:
            if not ( _calls( try_node.body ) & set( ROUTES ) or _calls( handler.body ) & set( ROUTES ) ):
                unrouted.append( path )
                break
    return sorted( skipping ), sorted( unrouted )


def test_the_population_is_not_empty():
    assert len( _population() ) > 1000, "git ls-files returned too few test files, so the census below would find nothing"


def test_the_census_finds_the_known_sites():
    skipping, _ = census( _population(), _read )
    assert len( skipping ) >= 12, f"expected the twelve database fixtures at least, found {len( skipping )}: {skipping}"
    assert "src/tests/smoke/test_i3_kind_aware_chase_roundtrip.py" in skipping, "the instrument cannot find a known positive"
    assert "src/tests/e2e/test_ask_answer_handback.py" in skipping


def test_every_skip_on_an_unreachable_database_is_routed_through_the_helper():
    skipping, unrouted = census( _population(), _read )
    assert skipping, "the census found no skipping file, so nothing was checked"
    assert unrouted == [ ], f"these files skip on OperationalError without the helper deciding refused from absent: {unrouted}"


def test_the_check_names_a_site_that_skips_on_its_own():
    own = "import pytest\nfrom sqlalchemy.exc import OperationalError\ndef f():\n    try:\n        connect()\n    except OperationalError as e:\n        pytest.skip( 'down' )\n"
    routed = own.replace( "connect()", "td.drop_database( u, n )" )
    skipping, unrouted = census( [ "a.py", "b.py" ], lambda path: own if path == "a.py" else routed )
    assert skipping == [ "a.py", "b.py" ] and unrouted == [ "a.py" ]


def test_a_handler_that_fails_the_refusal_itself_counts_as_routed():
    source = ( "import pytest\nfrom sqlalchemy.exc import OperationalError\ndef f():\n    try:\n        connect()\n"
               "    except OperationalError as e:\n        td.fail_on_a_refusal( e )\n        pytest.skip( 'down' )\n" )
    assert census( [ "c.py" ], lambda path: source ) == ( [ "c.py" ], [ ] )


def test_an_unrelated_handler_is_not_counted():
    source = "import pytest\ndef f():\n    try:\n        connect()\n    except ValueError:\n        pytest.skip( 'x' )\n    except OperationalError:\n        raise\n"
    assert census( [ "d.py" ], lambda path: source ) == ( [ ], [ ] )


def test_a_tuple_handler_that_skips_is_still_seen():
    source = ( "import pytest\nfrom sqlalchemy.exc import OperationalError\ndef f():\n    try:\n        connect()\n"
               "    except ( OperationalError, ValueError ):\n        pytest.skip( 'down' )\n" )
    assert census( [ "e.py" ], lambda path: source ) == ( [ "e.py" ], [ "e.py" ] )


def test_the_broad_skip_files_are_exactly_the_named_list():
    found = _broad_skip_files( _population(), _read )
    assert found, "the census found no broad skipping file, so nothing was compared"
    assert found == sorted( BROAD_SKIP_ALLOWED ), (
        f"a broad skip appeared or went away. New: {sorted( set( found ) - set( BROAD_SKIP_ALLOWED ) )}. "
        f"Gone: {sorted( set( BROAD_SKIP_ALLOWED ) - set( found ) )}. Add or remove its entry, with the reason." )


def test_every_named_broad_skip_carries_a_reason():
    assert all( reason.strip() for reason in BROAD_SKIP_ALLOWED.values() )


def test_the_broad_census_names_a_fourth_skip_and_a_bare_one():
    broad = "import pytest\ndef f():\n    try:\n        connect()\n    except Exception:\n        pytest.skip( 'x' )\n"
    bare  = broad.replace( "except Exception:", "except:" )
    quiet = broad.replace( "pytest.skip( 'x' )", "raise" )
    sources = { "a.py": broad, "b.py": bare, "c.py": quiet }
    assert _broad_skip_files( sorted( sources ), lambda path: sources[ path ] ) == [ "a.py", "b.py" ]
