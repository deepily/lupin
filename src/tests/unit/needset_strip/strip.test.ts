// Tests for needset_strip.js, the compiler script that strips member names for the need set.
//
// The script is a command line program, so each case runs it as a child process. The child inherits the
// coverage directory c8 sets, which is how the file is counted. Run from the repo root:
//   node_modules/.bin/c8 --100 --include=src/lupin_mcp/reuse_needset/needset_strip.js \
//     node_modules/.bin/tsx --test src/tests/unit/needset_strip/*.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

/** The path of the script under test. */
export const SCRIPT = path.resolve( process.cwd(), "src/lupin_mcp/reuse_needset/needset_strip.js" );
const TYPESCRIPT    = path.resolve( process.cwd(), "node_modules/typescript" );

type Target = { file: string, name: string, line: number, module_parts?: string[] };

/** Return the 1-based line of the first line of src that contains needle. */
function lineOf( src: string, needle: string ): number {
    const at = src.split( "\n" ).findIndex( ( l ) => l.includes( needle ) );
    assert.ok( at >= 0, needle );
    return at + 1;
}

/** Run the script on the targets of files written to a fresh directory; return the results. */
function run( files: Record<string, string>, mode: string, targets: Target[] ): any[] {
    const root = fs.mkdtempSync( path.join( os.tmpdir(), "needset-strip-" ) );
    for ( const name of Object.keys( files ) ) fs.writeFileSync( path.join( root, name ), files[ name ] );
    const res = spawnSync( process.execPath, [ SCRIPT ], { input: JSON.stringify( { root, typescript: TYPESCRIPT, mode, targets } ), encoding: "utf8" } );
    fs.rmSync( root, { recursive: true, force: true } );
    assert.equal( res.status, 0, res.stderr );
    return JSON.parse( res.stdout ).results;
}

const SOURCE = [
    "/** Adds numbers.",
    " *  More. */",
    "export function add( a: number ): number {",
    "",
    "    return a;",
    "}",
    "export class Box {",
    "    /** Gets it. */",
    "    get( k: string ) {",
    "        return this.store[ k ];",
    "    }",
    "    constructor( public v: number ) {}",
    "    get size() { return 1; }",
    "    set size( n ) {}",
    "}",
    "export const mul = ( a ) => a * 2;",
    "export const fe = function ( y ) { return y; };",
    "export default function () { return 1; }",
    "for ( const loop = () => 1; ; ) { break; }",
    "const notFn = 5;",
    "let bare;",
    "",
].join( "\n" );

const at = ( name: string, needle: string, src = SOURCE ): Target => ( { file: "a.ts", name, line: lineOf( src, needle ) } );

test( "text: members come back as written, with their doc comment, and lines after the first lose their shared indent", () => {
    const out = run( { "a.ts": SOURCE, "plain.js": "function twice( n ) { return n * 2; }\n", "view.tsx": "const view = () => <div/>;\n" }, "text", [
        at( "add", "export function add" ), at( "Box", "export class Box" ), at( "Box.get", "    get( k" ), at( "Box.constructor", "constructor(" ),
        at( "mul", "export const mul" ), at( "fe", "export const fe" ), at( "loop", "const loop" ),
        { file: "plain.js", name: "twice", line: 1 }, { file: "view.tsx", name: "view", line: 1 },
    ] );
    assert.deepEqual( out.map( ( r ) => r.kind ), [ "function", "class", "method", "method", "function", "function", "function", "function", "function" ] );
    assert.ok( out.every( ( r ) => r.ok === true && r.forbidden === undefined ) );
    assert.ok( out[ 0 ].text.startsWith( "/** Adds numbers.\n *  More. */\nexport function add" ) );
    assert.equal( out[ 2 ].text, "/** Gets it. */\nget( k: string ) {\n    return this.store[ k ];\n}" );
    assert.equal( out[ 3 ].text, "constructor( public v: number ) {}" );
    assert.equal( out[ 4 ].text, "export const mul = ( a ) => a * 2;" );
    assert.equal( out[ 6 ].text, "loop = () => 1" );
    assert.equal( out[ 8 ].text, "const view = () => <div/>;" );
} );

test( "text: accessors are found by line, and what is not a member is an error that names it", () => {
    const out = run( { "a.ts": SOURCE }, "text", [
        at( "Box.size", "get size" ), at( "Box.size", "set size" ), at( "notFn", "const notFn" ), at( "bare", "let bare" ),
        at( "nothing", "export default function" ), { file: "a.ts", name: "add", line: 999 }, { file: "gone.ts", name: "add", line: 1 },
    ] );
    assert.deepEqual( out.slice( 0, 2 ).map( ( r ) => r.text ), [ "get size() { return 1; }", "set size( n ) {}" ] );
    assert.deepEqual( out.slice( 2 ).map( ( r ) => r.ok ), [ false, false, false, false, false ] );
    assert.match( out[ 2 ].error, /no member notFn starts on line 20 of a\.ts/ );
    assert.match( out[ 5 ].error, /no member add starts on line 999/ );
    assert.equal( out[ 6 ].error, "no such file: gone.ts" );
} );

const COUNTER = [
    "export class Counter {",
    "    count = 0;",
    "    bump( step, ...rest ) {",
    "        this.count += step;",
    "        this.total( this.count, Counter.version, utility );",
    "        return rest;",
    "    }",
    "    other( step ) { return step; }",
    "    ab( x ) { return x; }",
    "}",
    "",
].join( "\n" );

test( "strip: a class loses its own name, its methods, its parameters and the names it reads off this", () => {
    const [ got ] = run( { "a.ts": COUNTER }, "strip", [ { file: "a.ts", name: "Counter", line: 1, module_parts: [ "md", "utility" ] } ] );
    assert.equal( got.kind, "class" );
    assert.deepEqual( got.forbidden, [ "Counter", "utility", "count", "other", "total", "bump", "rest", "step" ] );
    assert.deepEqual( got.replaced, { Counter: "CLASS", bump: "NAME", other: "NAME", utility: "MODULE", step: "ARG1", rest: "ARG2", count: "ATTR1", total: "ATTR2" } );
    for ( const name of got.forbidden ) assert.ok( !new RegExp( "\\b" + name + "\\b" ).test( got.text ), name );
    assert.ok( got.text.includes( "CLASS" ) && got.text.includes( "NAME(" ) && got.text.includes( "this.ATTR1 += ARG1;" ) );
    assert.ok( got.text.includes( "ab( x )" ), "names under three characters are kept" );
} );

test( "strip: a method takes the placeholder of the class around it", () => {
    const [ got ] = run( { "a.ts": COUNTER }, "strip", [ { file: "a.ts", name: "Counter.bump", line: 3, module_parts: [ "md", "utility" ] } ] );
    assert.equal( got.kind, "method" );
    assert.deepEqual( got.replaced, { bump: "NAME", Counter: "CLASS", utility: "MODULE", step: "ARG1", rest: "ARG2", count: "ATTR1", total: "ATTR2" } );
    assert.ok( got.text.includes( "CLASS.version" ) && got.text.includes( "MODULE" ) );
} );

test( "strip: destructured, rest and this parameters give their names and an omitted array slot gives none", () => {
    const src = "export function split( this: Foo, { aaa, bbb: [ , ccc ] }: Opts, [ , ddd ]: number[] ) { return aaa + ccc + ddd; }\n";
    const [ got ] = run( { "a.ts": src }, "strip", [ { file: "a.ts", name: "split", line: 1 } ] );
    assert.deepEqual( got.replaced, { split: "NAME", aaa: "ARG1", ccc: "ARG2", ddd: "ARG3" } );
    assert.equal( got.text, "export function NAME( this: Foo, { ARG1, bbb: [ , ARG2 ] }: Opts, [ , ARG3 ]: number[] ) { return ARG1 + ARG2 + ARG3; }" );
} );

test( "strip: short names and dunder names stay, and a member with nothing to replace comes back unchanged", () => {
    const src = "export function go( a ) { return a; }\nexport function __dunder__( input ) { return input; }\n";
    const out = run( { "a.ts": src }, "strip", [ { file: "a.ts", name: "go", line: 1 }, { file: "a.ts", name: "__dunder__", line: 2 } ] );
    assert.deepEqual( out[ 0 ].forbidden, [] );
    assert.deepEqual( out[ 0 ].replaced, {} );
    assert.equal( out[ 0 ].text, "export function go( a ) { return a; }" );
    assert.deepEqual( out[ 1 ].forbidden, [ "input" ] );
    assert.equal( out[ 1 ].text, "export function __dunder__( ARG1 ) { return ARG1; }" );
} );

test( "strip: a method of an unnamed class has no class name to replace", () => {
    const src = "export default class {\n    m( aaa ) { return aaa; }\n}\n";
    const [ got ] = run( { "a.ts": src }, "strip", [ { file: "a.ts", name: "m", line: 2 } ] );
    assert.deepEqual( got.replaced, { aaa: "ARG1" } );
} );

test( "strip: the same name met twice keeps its first placeholder", () => {
    const src = "export class Same {\n    Same( Same ) { return Same; }\n}\n";
    const [ got ] = run( { "a.ts": src }, "strip", [ { file: "a.ts", name: "Same", line: 1 } ] );
    assert.deepEqual( got.replaced, { Same: "CLASS" } );
} );

test( "strip: a function held in a const loses the const's name and the function's parameters", () => {
    const [ got ] = run( { "a.ts": SOURCE }, "strip", [ at( "mul", "export const mul" ) ] );
    assert.equal( got.kind, "function" );
    assert.equal( got.text, "export const NAME = ( a ) => a * 2;" );
    assert.deepEqual( got.replaced, { mul: "NAME" } );
} );

test( "shape: a class and a function give their node kind names, with names and literals erased and modifiers left out", () => {
    const src = "export class Tiny {\n    m( a ) { return 1; }\n}\nexport function tf( b: string ) { return \"x\" + `y`; }\n";
    const out = run( { "a.ts": src }, "shape", [ { file: "a.ts", name: "Tiny", line: 1 }, { file: "a.ts", name: "tf", line: 4 } ] );
    assert.deepEqual( out[ 0 ], { ok: true, kind: "class", kinds: [ "ClassDeclaration", "Identifier", "MethodDeclaration", "Identifier", "Parameter", "Identifier", "Block", "ReturnStatement", "Literal" ] } );
    assert.equal( out[ 1 ].kind, "function" );
    assert.deepEqual( out[ 1 ].kinds.slice( 0, 4 ), [ "FunctionDeclaration", "Identifier", "Parameter", "Identifier" ] );
    assert.ok( out[ 1 ].kinds.includes( "BinaryExpression" ) && out[ 1 ].kinds.filter( ( k: string ) => k === "Literal" ).length === 2 );
} );

test( "shape: a private identifier is one kind with the plain ones", () => {
    const src = "export class Priv {\n    #hidden = 1;\n    show() { return this.#hidden; }\n}\n";
    const [ got ] = run( { "a.ts": src }, "shape", [ { file: "a.ts", name: "Priv", line: 1 } ] );
    assert.ok( !got.kinds.includes( "PrivateIdentifier" ) && got.kinds.includes( "Identifier" ) );
} );
