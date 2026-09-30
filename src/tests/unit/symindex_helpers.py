"""
Shared fixture builders for the symbol-index unit tests (helper module, no tests).
"""
import pathlib

PY_UTIL = '''"""Module doc."""
import functools


def public_fn( a, b=1 ) -> int:
    """Adds things.

    More detail.
    """
    return a + b


def _private_fn():
    def nested_helper():
        return 1
    return nested_helper


class Widget:
    """A widget."""

    def __init__( self, x ):
        self.x = x

    def render( self ):
        """Render it."""
        return self.x

    def _hidden( self ):
        return 0

    @property
    def size( self ):
        return 1

    @size.setter
    def size( self, v ):
        self._s = v


class _PrivateClass:
    def method( self ):
        return 1


if functools:
    def conditional_fn():
        return 2
else:
    def conditional_fn():
        return 3

try:
    import json
except ImportError:
    def fallback_fn():
        return 4
'''

ROUTER = '''"""Routes."""
from fastapi import APIRouter

router = APIRouter( prefix="/api" )
plain  = APIRouter()


@router.post( "/notify" )
async def notify_handler():
    return 1


@router.get( "/items/{item_id}" )
def get_item( item_id ):
    return item_id


@plain.get( "/health" )
def health():
    return "ok"


@router.get( dynamic_path )
def skipped_dynamic():
    return 0


def no_decorator():
    return 0
'''

MAIN = '''"""App."""
from fastapi import FastAPI
from . import router as routes_mod

app = FastAPI()
app.include_router( routes_mod.router, prefix="/v2" )
app.include_router( routes_mod.plain )
'''

TS_SAMPLE = '''/**
 * Adds numbers.
 * Extra line.
 */
export function add<T extends number>( a: T, b: T ): T { return a; }

export class Box<T> {
    /** Gets it. */
    get( k: string ): T | undefined { return undefined; }
    private hidden(): void {}
    #secret(): void {}
    constructor( public v: number ) {}
    async put( k: string, v: T ): Promise<void> {}
    get size(): number { return 1; }
    set size( n: number ) {}
}

/** Typed arrow. */
export const mul: ( a: number, b: number ) => number = ( a, b ) => a * b;
const plain = async ( x: string ) => x;
const fe = function ( y ) { return y; };
const notFn = 5;
'''

JS_SAMPLE = '''// Plain helper.
function twice( n ) { return n * 2; }
const thrice = ( n ) => n * 3;
'''


def make_repo( base, name="repo" ):
    """
    Ensures:
        - writes a generic (non-lupin) fixture repository under base/name and returns its path
        - holds python, a router module, a module that include_router's it, TS and JS files,
          and a tests/ directory and a node_modules directory that must be skipped
    """
    root = pathlib.Path( base ) / name
    ( root / "pkg" / "tests" ).mkdir( parents=True )
    ( root / "web" ).mkdir()
    ( root / "node_modules" / "dep" ).mkdir( parents=True )
    ( root / "pkg" / "__init__.py" ).write_text( '"""Package."""\n', encoding="utf-8" )
    ( root / "pkg" / "util.py" ).write_text( PY_UTIL, encoding="utf-8" )
    ( root / "pkg" / "router.py" ).write_text( ROUTER, encoding="utf-8" )
    ( root / "pkg" / "main.py" ).write_text( MAIN, encoding="utf-8" )
    ( root / "pkg" / "tests" / "test_skip.py" ).write_text( "def skipped_in_tests():\n    return 1\n", encoding="utf-8" )
    ( root / "node_modules" / "dep" / "x.js" ).write_text( "function skippedDep() {}\n", encoding="utf-8" )
    ( root / "web" / "app.ts" ).write_text( TS_SAMPLE, encoding="utf-8" )
    ( root / "web" / "lib.js" ).write_text( JS_SAMPLE, encoding="utf-8" )
    return root


FEEDS  = 'def parse_feed( url ):\n    """Parse an RSS feed into Article objects."""\n    return url\n'
MATHX  = 'def add( a, b ):\n    """Add two numbers."""\n    return a + b\n'
SERVE  = 'def serve():\n    """Serve the tools."""\n    return 1\n'


def make_lupin_repo( base, name="lupin" ):
    """
    Ensures:
        - writes a minimal lupin-shaped repository (src/cosa and src/lupin_mcp, three public functions)
          under base/name and returns its path; ids are cosa.feeds.parse_feed, cosa.mathx.add and
          lupin_mcp.tool.serve
    """
    root = pathlib.Path( base ) / name
    ( root / "src" / "cosa" ).mkdir( parents=True ); ( root / "src" / "lupin_mcp" ).mkdir( parents=True )
    ( root / "src" / "cosa" / "feeds.py" ).write_text( FEEDS, encoding="utf-8" )
    ( root / "src" / "cosa" / "mathx.py" ).write_text( MATHX, encoding="utf-8" )
    ( root / "src" / "lupin_mcp" / "tool.py" ).write_text( SERVE, encoding="utf-8" )
    return root
