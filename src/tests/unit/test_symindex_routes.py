"""
Unit tests for cosa.repo.symindex.routes: prefixes are read from the AST, never from the live app.
"""
import ast
import pathlib

from cosa.repo.symindex import routes as rt
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.build import collect
from tests.unit.symindex_helpers import make_repo

REPO_ROOT = sp.git_toplevel( pathlib.Path( __file__ ).resolve().parent )


def test_prefixed_router_route_keeps_its_prefix( tmp_path ):
    routes = collect( sp.spec_for( make_repo( tmp_path ) ) )[ "routes" ]
    joined = "\n".join( routes )
    assert "POST /v2/api/notify -> repo:pkg.router.notify_handler  (pkg/router.py)" in routes      # router prefix + include prefix + path
    assert "GET /v2/api/items/{item_id}" in joined
    assert "GET /health -> repo:pkg.router.health" in joined                                      # no prefix anywhere
    assert "skipped_dynamic" not in joined and "no_decorator" not in joined                        # non-literal path / no decorator


def test_real_prefixed_router_routes_carry_the_prefix():
    spec   = sp.spec_for( REPO_ROOT )
    routes = collect( spec )[ "routes" ]
    assert any( l.startswith( "GET /admin/" ) and "(src/cosa/rest/routers/admin.py)" in l for l in routes )
    assert any( l.startswith( "GET /api/" ) and "cosa.rest.routers.tasks." in l for l in routes )
    assert any( l.startswith( "POST /api/v2/submit -> cosa.rest.routers.v2_ask." ) for l in routes )        # v2 routes spell /api/v2 in the decorator
    assert not any( l.split( " " )[ 1 ].startswith( "/notify" ) for l in routes if "routers/notifications.py" in l )


def test_scan_file_reads_router_prefixes_and_include_calls():
    tree = ast.parse( "r = APIRouter( prefix='/a' )\nq = fastapi.APIRouter()\napp.include_router( m.r, prefix='/v' )\n"
                      "app.include_router( q )\napp.include_router( make() )\n" )
    routers, includes, imports = rt.scan_file( tree )
    assert routers == { "r": "/a", "q": "" }
    assert includes == [ ( "m", "r", "/v" ), ( None, "q", "" ) ]
    assert imports == {}


def test_scan_file_records_import_aliases():
    tree = ast.parse( "from . import router as routes_mod\nfrom pkg.sub import rr\nimport a.b as z\nimport top\n" )
    assert rt.scan_file( tree )[ 2 ] == { "routes_mod": ( "", "router" ), "rr": ( "sub", "rr" ), "z": ( "a", "b" ), "top": ( "", "top" ) }


def test_route_decorators_accepts_only_literal_paths_on_a_named_receiver():
    fn = ast.parse( "@r.get('/x')\n@r.post(path_var)\n@other.thing('/y')\n@r.put\n@a.b.get('/z')\n@r.websocket('/ws')\ndef f(): pass\n" ).body[ 0 ]
    assert rt.route_decorators( fn ) == [ ( "r", "get", "/x" ), ( "r", "websocket", "/ws" ) ]


def test_resolve_applies_an_include_prefix_only_to_the_router_it_names():
    files = [ { "file": "a.py", "stem": "a", "routers": { "r": "/p" }, "includes": [], "imports": {}, "decorated": [ ( "r", "get", "/x", "a.f" ) ] },
              { "file": "b.py", "stem": "b", "routers": { "r": "" }, "includes": [], "imports": {}, "decorated": [ ( "r", "get", "/x", "b.f" ) ] },
              { "file": "own.py", "stem": "own", "routers": { "q": "/q" }, "includes": [ ( None, "q", "/same" ) ], "imports": {},
                "decorated": [ ( "q", "get", "/y", "own.f" ) ] },
              { "file": "c.py", "stem": "c", "routers": {}, "imports": { "am": ( "", "a" ), "bare": ( "b", "r" ), "m2": ( "x", "nomatch" ) },
                "includes": [ ( "am", "r", "/inc" ), ( None, "bare", "/viaalias" ), ( "plain", "r", "/q2" ), ( None, "nomatch", "/n" ) ],
                "decorated": [ ( "zz", "get", "/skip", "c.f" ) ] } ]
    out = rt.resolve( files )
    assert "GET /inc/p/x -> a.f  (a.py)" in out                                # `am.r`: alias am -> module a
    assert "GET /viaalias/x -> b.f  (b.py)" in out                             # bare alias -> (module b, router r)
    assert "GET /same/q/y -> own.f  (own.py)" in out                           # bare name in the same file
    assert not any( "c.f" in l for l in out )                                  # a receiver that is no known router yields no route
    assert len( out ) == 3


def test_fastapi_application_routes_are_indexed_including_nested_apps( tmp_path ):
    root = make_repo( tmp_path )
    ( root / "pkg" / "server.py" ).write_text( "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get( '/health' )\ndef health():\n    return 1\n\n\n"
                                               "def create_app():\n    inner = FastAPI()\n\n    @inner.post( '/transcribe' )\n    def transcribe():\n        return 2\n    return inner\n", encoding="utf-8" )
    routes = "\n".join( collect( sp.spec_for( root ) )[ "routes" ] )
    assert "GET /health -> repo:pkg.server.health  (pkg/server.py)" in routes
    assert "POST /transcribe -> repo:pkg.server.create_app.<locals>.transcribe  (pkg/server.py)" in routes
