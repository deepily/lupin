// Tests for ts_extract.js, the compiler script of the symbol index and the dups command.
//
// The script is a command line program, so each case runs it as a child process. The child inherits the
// coverage directory c8 sets, which is how the file is counted. Run from the repo root:
//   node_modules/.bin/c8 --100 --include=src/cosa/repo/symindex/ts_extract.js \
//     node_modules/.bin/tsx --test src/tests/unit/ts_extract/*.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

/** The path of the script under test. */
export const SCRIPT = path.resolve( process.cwd(), "src/cosa/repo/symindex/ts_extract.js" );
const TYPESCRIPT    = path.resolve( process.cwd(), "node_modules/typescript" );

/** Write the files to a fresh directory, run the script on them, return its decoded output. */
function run( files: Record<string, string>, extra: Record<string, unknown> = {} ): any {
    const root = fs.mkdtempSync( path.join( os.tmpdir(), "ts-extract-" ) );
    const abs  = Object.keys( files ).map( ( name ) => {
        const p = path.join( root, name );
        fs.mkdirSync( path.dirname( p ), { recursive: true } );
        fs.writeFileSync( p, files[ name ] );
        return p;
    } );
    const res = spawnSync( process.execPath, [ SCRIPT ], { input: JSON.stringify( { root, files: abs, typescript: TYPESCRIPT, ...extra } ), encoding: "utf8" } );
    fs.rmSync( root, { recursive: true, force: true } );
    assert.equal( res.status, 0, res.stderr );
    return JSON.parse( res.stdout );
}

const SYMBOLS = [
    "/**", " * Adds numbers.", " * Second line.", " */",
    "export function add<T extends number>( a: T, b: T ): T { return a; }",
    "export default function () {}",
    "export class Box<T> {",
    "    prop = 1;",
    "    /** Gets it. */",
    "    get( k: string ): T | undefined { return undefined; }",
    "    private hidden(): void {}",
    "    protected guarded(): void {}",
    "    #secret(): void {}",
    "    constructor( public v: number ) {}",
    "    get size(): number { return 1; }",
    "    set size( n: number ) {}",
    "}",
    "export default class {}",
    "/** Typed arrow. */",
    "export const mul: ( a: number ) => number = ( a ) => a, notFn = 5, bare;",
    "const fe = function ( y ) { return y; };",
    "const { destructured } = { destructured: () => 1 };",
    "/** */",
    "export function emptyDoc() {}",
    "/**",
    " * @param x a parameter",
    " */",
    "export function tagOnly( x ) {}",
    "",
].join( "\n" );

test( "symbols: functions, classes, accessors and typed arrows are listed, private members are not", () => {
    const out = run( { "a.ts": SYMBOLS, "b.js": "function twice( n ) { return n * 2; }\n", "c.tsx": "const view = () => <div/>;\n" } );
    const by  = Object.fromEntries( out.map( ( r: any ) => [ r.file + "#" + r.name, r ] ) );
    assert.equal( by[ "a.ts#add" ].sig, "<T extends number>(a: T, b: T): T" );
    assert.equal( by[ "a.ts#add" ].doc, "Adds numbers." );
    assert.equal( by[ "a.ts#Box" ].kind, "class" );
    assert.equal( by[ "a.ts#Box.get" ].doc, "Gets it." );
    assert.equal( by[ "a.ts#Box.constructor" ].kind, "method" );
    assert.equal( out.filter( ( r: any ) => r.name === "Box.size" ).length, 2 );
    assert.equal( by[ "a.ts#mul" ].sig.startsWith( ": " ), true );
    assert.equal( by[ "a.ts#fe" ].sig, "(y)" );
    assert.equal( by[ "a.ts#emptyDoc" ].doc, "" );
    assert.equal( by[ "a.ts#tagOnly" ].doc, "" );
    assert.equal( by[ "b.js#twice" ].line, 1 );
    assert.ok( by[ "c.tsx#view" ] );
    const names = out.map( ( r: any ) => r.name );
    for ( const hidden of [ "Box.hidden", "Box.guarded", "Box.#secret", "Box.prop", "notFn", "bare", "destructured" ] ) assert.ok( !names.includes( hidden ), hidden );
    assert.equal( by[ "a.ts#add" ].pin.length, 10 );
} );

test( "a pin ignores comments and whitespace", () => {
    const one = run( { "a.ts": "/** doc */\nfunction f( a ) { return a; }\n" } )[ 0 ].pin;
    const two = run( { "a.ts": "function  f( a ) {\n  // note\n  return a;\n}\n" } )[ 0 ].pin;
    assert.equal( one, two );
} );

const SHAPES = [
    "export class Store {",
    "    private _a( xs: number[] ) { let t = 0; for ( const x of xs ) { t += x * 2; } return t; }",
    "    public b( ys: number[] ) { let u = 0; for ( const y of ys ) { u += y * 5; } return u; }",
    "    #c( zs: number[] ) { return zs.length + 1; }",
    "    constructor( public v: number ) {}",
    "    get size() { return 1; }",
    "    set size( n: number ) {}",
    "}",
    "export function wrapper( list: number[] ) {",
    "    function nested( ws: number[] ) { return ws.map( ( w ) => w + 1 ); }",
    "    return list.map( ( e ) => { function deep() { return 'x'; } return deep(); } );",
    "}",
    "const Anon = class { held() { return 1; } };",
    "const table = { member: function () { return 2; } };",
    "class Holder { field = () => 3; }",
    "",
].join( "\n" );

test( "shapes: every function-like definition is listed with a kind sequence, names and literals erased", () => {
    const out = run( { "s.ts": SHAPES }, { mode: "shapes" } );
    assert.deepEqual( out.scanned, [ "s.ts" ] );
    const names = out.defs.map( ( d: any ) => d.name );
    assert.deepEqual( names, [
        "Store._a", "Store.b", "Store.#c", "Store.constructor", "Store.size", "Store.size",
        "wrapper", "wrapper.<locals>.nested", "wrapper.<locals>.deep", "held", "member", "Holder.field"
    ] );                                                                  // the .map callbacks are walked, never listed
} );

test( "shapes: the two clones have one kind sequence and the literal kinds are merged", () => {
    const out = run( { "s.ts": SHAPES }, { mode: "shapes" } );
    const by  = Object.fromEntries( out.defs.map( ( d: any ) => [ d.name, d.kinds ] ) );
    assert.deepEqual( by[ "Store._a" ].filter( ( k: string ) => k !== "Literal" ), by[ "Store.b" ].filter( ( k: string ) => k !== "Literal" ) );
    assert.ok( by[ "Store.b" ].includes( "Literal" ) && !by[ "Store.b" ].includes( "NumericLiteral" ) && !by[ "Store.b" ].includes( "FirstLiteralToken" ) );
    assert.ok( !by[ "Store.b" ].includes( "PublicKeyword" ) && !by[ "Store._a" ].includes( "PrivateKeyword" ) );
    assert.equal( by[ "Store.#c" ][ 1 ], "Identifier" );
    assert.ok( by[ "wrapper.<locals>.deep" ].includes( "Literal" ) );
} );

test( "shapes: public_only drops private members and everything nested", () => {
    const out = run( { "s.ts": SHAPES }, { mode: "shapes", public_only: true } );
    const names = out.defs.map( ( d: any ) => d.name );
    assert.ok( names.includes( "Store.b" ) && names.includes( "wrapper" ) && names.includes( "held" ) );
    assert.ok( !names.includes( "Store._a" ) && !names.includes( "Store.#c" ) );
    assert.ok( !names.some( ( n: string ) => n.includes( "<locals>" ) ) );
} );

test( "shapes: JavaScript and TSX files are read too", () => {
    const out = run( { "a.js": "function twice( n ) { return n * 2; }\n", "b.tsx": "const view = () => <div/>;\n" }, { mode: "shapes" } );
    assert.deepEqual( out.scanned, [ "a.js", "b.tsx" ] );
    assert.deepEqual( out.defs.map( ( d: any ) => d.name ), [ "twice", "view" ] );
} );
