"""
(d) Adversarial auth probe — hit GET /api/epic-stories with NO credential and
watch it refuse, then compare its refusal to GET /api/tasks' refusal on the same
app. Reading the decorator is not proof; this exercises the dependency.

No curl. TestClient only.
"""
import os, sys

lupin_root = "/mnt/DATA01/include/www.deepily.ai/projects/lupin-wt-review-epic-1a6b2a84"
os.environ[ "LUPIN_ROOT" ] = lupin_root
sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.routers import tasks as tasks_router

app = FastAPI()
app.include_router( tasks_router.router )
client = TestClient( app, raise_server_exceptions=False )

rows = []
fails = 0

def probe( label, method, url, **kw ):
    global fails
    r = client.request( method, url, **kw )
    rows.append( ( label, url, r.status_code ) )
    return r

# --- no credential at all -------------------------------------------------
stories_none = probe( "no key", "GET", "/api/epic-stories" )
tasks_none   = probe( "no key", "GET", "/api/tasks" )

# --- wrong credential -----------------------------------------------------
stories_bad  = probe( "bad key", "GET", "/api/epic-stories", headers={ "X-API-Key": "not-a-real-key" } )
tasks_bad    = probe( "bad key", "GET", "/api/tasks",        headers={ "X-API-Key": "not-a-real-key" } )

stories_jwt  = probe( "junk bearer", "GET", "/api/epic-stories", headers={ "Authorization": "Bearer garbage" } )
tasks_jwt    = probe( "junk bearer", "GET", "/api/tasks",        headers={ "Authorization": "Bearer garbage" } )

print( f"{'case':<14}{'endpoint':<24}{'status'}" )
for label, url, code in rows:
    print( f"{label:<14}{url:<24}{code}" )

def check( name, ok, detail="" ):
    global fails
    print( ( "PASS  " if ok else "FAIL  " ) + name + ( "" if ok else f"   -> {detail}" ) )
    if not ok: fails += 1

check( "d1 /api/epic-stories REFUSES an unauthenticated request",
       stories_none.status_code in ( 401, 403 ), stories_none.status_code )
check( "d2 it refuses with the SAME status /api/tasks uses",
       stories_none.status_code == tasks_none.status_code,
       f"stories={stories_none.status_code} tasks={tasks_none.status_code}" )
check( "d3 a WRONG api key is refused identically on both",
       stories_bad.status_code == tasks_bad.status_code and stories_bad.status_code in ( 401, 403 ),
       f"stories={stories_bad.status_code} tasks={tasks_bad.status_code}" )
check( "d4 a JUNK bearer token is refused identically on both",
       stories_jwt.status_code == tasks_jwt.status_code and stories_jwt.status_code in ( 401, 403 ),
       f"stories={stories_jwt.status_code} tasks={tasks_jwt.status_code}" )
check( "d5 the refusal leaks NO story content",
       "epic:" not in stories_none.text, stories_none.text[ :200 ] )

# --- the dependency is literally the same object --------------------------
import inspect
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

def deps_of( fn ):
    return [ p.default.dependency for p in inspect.signature( fn ).parameters.values()
             if hasattr( p.default, "dependency" ) ]

stories_deps = deps_of( tasks_router.get_epic_stories )
check( "d6 the guard is the SAME callable /api/tasks depends on",
       require_api_key_or_jwt in stories_deps, stories_deps )

print( f"\nFAILURES: {fails}" )
sys.exit( 0 if fails == 0 else 1 )
