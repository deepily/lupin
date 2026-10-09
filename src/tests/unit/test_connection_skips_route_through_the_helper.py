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

A refused login to the app has the same two ways past: a broad handler, and an `if` on the response
status. Both are in the censuses below. The app login itself goes through tests.helpers.app_login, which
skips when nothing answered and fails on any other answer. A skip on a status code needs a named entry
with its reason. A login that skips on a 401 cannot come back as a quiet green.

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

# Files whose broad handler skips, and why that is allowed. All three skip on a database connect and
# are left alone on purpose: they probe a rolled-back temp table, and a refused login there is not
# the failure class this guard exists for. The five that skipped on an HTTP login to the app now call
# tests.helpers.app_login and are gone from this list.
BROAD_SKIP_ALLOWED = {
    "src/tests/unit/test_metadata_schema_drift.py"                       : "database connect; drift is unmeasured, not claimed green",
    "src/tests/unit/test_task_promotion_ticket_answer_by_migration.py"   : "database connect; a rolled-back temp table probe with a loud skip",
    "src/tests/unit/test_task_request_columns_migration.py"              : "database connect; a rolled-back temp table probe with a loud skip",
}

# Files that skip inside an `if` on a response status, and why that is allowed. None of them is a login.
STATUS_SKIP_ALLOWED = {
    "src/tests/integration/test_queue_not_self_filter.py"   : "a push the test environment does not serve; the login is a separate call",
    "src/tests/integration/test_tfe_resume_e2e.py"          : "a submit endpoint that may not exist (404), not a login",
    "src/tests/smoke/test_io_files_endpoint.py"             : "an io file the environment may not hold (404), not a login",
    "src/tests/smoke/test_model_server_smoke.py"            : "a health check on a model server that is not ready, not a login",
    "src/tests/smoke/test_voice_persona_allocation.py"      : "a 404 that means the test and the server read different bridge directories, not a login",
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


def _status_skip_files( population, read ):
    """Return the files with an `if` on a response status whose body calls pytest.skip."""
    found = [ ]
    for path in population:
        source = read( path )
        if "skip" not in source or "status" not in source: continue
        for node in ast.walk( ast.parse( source ) ):
            if not isinstance( node, ast.If ): continue
            reads_status = any( isinstance( sub, ast.Attribute ) and sub.attr in ( "status_code", "status" ) for sub in ast.walk( node.test ) )
            if reads_status and "skip" in _calls( node.body ):
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


def test_the_status_skip_files_are_exactly_the_named_list():
    found = _status_skip_files( _population(), _read )
    assert found, "the census found no status-code skipping file, so nothing was compared"
    assert found == sorted( STATUS_SKIP_ALLOWED ), (
        f"a skip on a response status appeared or went away. New: {sorted( set( found ) - set( STATUS_SKIP_ALLOWED ) )}. "
        f"Gone: {sorted( set( STATUS_SKIP_ALLOWED ) - set( found ) )}. A login that skips on its status must call tests.helpers.app_login instead." )


def test_every_named_status_skip_carries_a_reason():
    assert all( reason.strip() for reason in STATUS_SKIP_ALLOWED.values() )


def test_the_status_census_names_a_login_that_skips_on_its_code_and_ignores_the_rest():
    login   = "import pytest\ndef f( resp ):\n    if resp.status_code != 200:\n        pytest.skip( 'login failed' )\n"
    plain   = login.replace( "pytest.skip( 'login failed' )", "raise RuntimeError" )
    no_code = login.replace( "resp.status_code != 200", "resp is None" )
    tuple_  = login.replace( "resp.status_code", "resp.status" )
    sources = { "a.py": login, "b.py": plain, "c.py": no_code, "d.py": tuple_, "e.py": "x = 1\n" }
    assert _status_skip_files( sorted( sources ), lambda path: sources[ path ] ) == [ "a.py", "d.py" ]


NINE_LOGIN_FILES = (
    "src/tests/smoke/test_external_scopes.py",
    "src/tests/websocket_smoke/core/test_close_codes.py",
    "src/tests/ws_channel_browser/test_ws_circuit_banner.py",
    "src/tests/ws_channel_browser/test_ws_close_codes.py",
    "src/tests/ws_channel_browser/test_ws_lifecycle.py",
    "src/tests/parity_oracle/test_tier1_accordions_cross_client.py",
    "src/tests/parity_oracle/test_tier1_sections_ruled_predicate.py",
    "src/tests/parity_oracle/test_tier2_accordions_appearance.py",
    "src/tests/integration/test_swe_team_pipeline.py",
)


def _login_url_literals( source ):
    """Return the string literals in the code that name /auth/login; docstrings do not count."""
    tree       = ast.parse( source )
    docstrings = { id( node.body[ 0 ].value ) for node in ast.walk( tree )
                   if isinstance( node, ( ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef ) )
                   and node.body and isinstance( node.body[ 0 ], ast.Expr ) and isinstance( node.body[ 0 ].value, ast.Constant ) }
    return [ node.value for node in ast.walk( tree )
             if isinstance( node, ast.Constant ) and isinstance( node.value, str ) and "/auth/login" in node.value and id( node ) not in docstrings ]


def test_the_nine_files_that_skipped_on_a_refused_login_call_the_helper():
    for path in NINE_LOGIN_FILES:
        source = _read( path )
        assert "app_login.login(" in source, f"{path} no longer logs in through tests.helpers.app_login"
        assert _login_url_literals( source ) == [ ], f"{path} posts to /auth/login itself again"


def test_the_login_literal_check_sees_code_and_ignores_a_docstring():
    own  = "def f():\n    return post( '/auth/login' )\n"
    said = "def f():\n    \"\"\"posts to /auth/login\"\"\"\n    return 1\n"
    assert _login_url_literals( own ) == [ "/auth/login" ] and _login_url_literals( said ) == [ ]

