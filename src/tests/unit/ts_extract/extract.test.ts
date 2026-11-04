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

test( "symbols: functions, classes, accessors and typed arrows are listed, private members are listed hidden", () => {
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
    for ( const absent of [ "Box.prop", "notFn", "bare", "destructured" ] ) assert.ok( !names.includes( absent ), absent );      // not a function
    for ( const hidden of [ "Box.hidden", "Box.guarded", "Box.#secret" ] ) assert.equal( by[ "a.ts#" + hidden ].public, false, hidden );     // private, protected and #private: returned, hidden from the public listing
    assert.equal( by[ "a.ts#Box.get" ].public, true );
    assert.ok( out.filter( ( r: any ) => r.public ).length === out.length - 3 );
    assert.equal( by[ "a.ts#add" ].pin.length, 10 );
} );

const LIMITS = { doc_limit: 30, doc_marker: "…" };

test( "doc_full: the whole JSDoc with its tags is folded to one line", () => {
    const out = run( { "d.ts": [
        "/**", " * Adds   two", " * numbers.", " * @param x the x", " * @returns the sum", " * @param y", " * @deprecated", " */",
        "export function add( x, y ) { return x + y; }",
        "/** @deprecated */", "export function old() {}",
        "/** Only a description. */", "export function plain() {}",
        "export function bare() {}", "",
    ].join( "\n" ) }, LIMITS );
    const by = Object.fromEntries( out.map( ( r: any ) => [ r.name, r ] ) );
    assert.equal( by.old.doc_full, "@deprecated" );                       // tags only: no description, no tag name, no tag comment
    assert.equal( by.plain.doc_full, "Only a description." );             // a description and no tags
    assert.equal( by.bare.doc_full, "" );                                 // no JSDoc at all
    assert.equal( by.add.doc_full, "Adds two numbers. @param x the…" );    // a named tag with a comment, an unnamed one, a named one with none: cut at 30
} );

test( "doc_full: with two JSDoc blocks before one definition the block nearest the definition is the one read", () => {
    const out = run( { "two.ts": "/** First block. */\n/** Second block. */\nexport function f() {}\n" }, LIMITS );
    assert.equal( out[ 0 ].doc, "Second block." );                         // doc and doc_full take the same block
    assert.equal( out[ 0 ].doc_full, "Second block." );
} );

test( "end_line: the last line of each definition, one-line, multi-line, private and arrow", () => {
    const src = [
        "export function one() {}",
        "",
        "export function multi( a: number,",
        "                       b: number ) {",
        "    return a + b;",
        "}",
        "export class K {",
        "    private hid() {",
        "        return 1;",
        "    }",
        "}",
        "const arrow = ( a: number ) =>",
        "    a + 1;",
        "",
    ].join( "\n" );
    const spans = Object.fromEntries( run( { "e.ts": src } ).map( ( r: any ) => [ r.name, [ r.line, r.end_line ] ] ) );
    assert.deepEqual( spans, { one: [ 1, 1 ], multi: [ 3, 6 ], K: [ 7, 11 ], "K.hid": [ 8, 10 ], arrow: [ 12, 13 ] } );
} );

test( "doc_full: a text of exactly the limit is kept and a longer one is cut by code points", () => {
    const run1 = ( text: string, limit: number ) => run( { "e.ts": `/** ${text} */\nexport function f() {}\n` }, { doc_limit: limit, doc_marker: "…" } )[ 0 ].doc_full;
    assert.equal( run1( "abcd", 4 ), "abcd" );
    assert.equal( run1( "abcde", 4 ), "abcd…" );
    assert.equal( run1( "𝔘𝔘𝔘𝔘𝔘𝔘", 4 ), "𝔘𝔘𝔘𝔘…" );                          // an astral character counts as one
} );

test( "doc_full: tags with names and comments are written out in full under a long limit", () => {
    const full = run( { "d.ts": "/**\n * Adds.\n * @param x the x\n * @returns the sum\n * @param y\n * @deprecated\n */\nexport function add( x, y ) {}\n" }, { doc_limit: 800, doc_marker: "…" } );
    assert.equal( full[ 0 ].doc_full, "Adds. @param x the x @returns the sum @param y @deprecated" );
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

test( "shapes: a variable statement is named by its real kind, never the FirstStatement alias", () => {
    const out = run( { "k.ts": "export function f() { const a = 1; return a; }\n" }, { mode: "shapes" } );
    const kinds = out.defs[ 0 ].kinds;
    assert.ok( kinds.includes( "VariableStatement" ) && !kinds.includes( "FirstStatement" ) );
} );

test( "shapes: public_only drops private members and everything nested", () => {
    const out = run( { "s.ts": SHAPES }, { mode: "shapes", public_only: true } );
    const names = out.defs.map( ( d: any ) => d.name );
    assert.ok( names.includes( "Store.b" ) && names.includes( "wrapper" ) && names.includes( "held" ) );
    assert.ok( !names.includes( "Store._a" ) && !names.includes( "Store.#c" ) );
    assert.ok( !names.some( ( n: string ) => n.includes( "<locals>" ) ) );
} );

test( "shapes: JavaScript and TSX files are read too", () => {
    const out = run( { "a.js": "function twice( n ) { return n * 2; }\n", "b.tsx": "const view = <T,>( n: T ): JSX.Element => <div>{ n as T }</div>;\n" }, { mode: "shapes" } );   // a generic arrow is TSX-only syntax
    assert.deepEqual( out.scanned, [ "a.js", "b.tsx" ] );
    assert.deepEqual( out.defs.map( ( d: any ) => d.name ), [ "twice", "view" ] );
} );

test( "shapes: a function held in a private or protected class property is as private as the property", () => {
    const src = [
        "export class A {",
        "    public p = () => 1;",
        "    private f = () => 2;",
        "    #g = () => 3;",
        "    protected static h = function () { return 4; };",
        "}",
        "",
    ].join( "\n" );
    const names = ( extra: Record<string, unknown> ) => run( { "a.ts": src }, { mode: "shapes", ...extra } ).defs.map( ( d: any ) => d.name );
    assert.deepEqual( names( {} ), [ "A.p", "A.f", "A.#g", "A.h" ] );
    assert.deepEqual( names( { public_only: true } ), [ "A.p" ] );
} );

test( "symbols: a .tsx file is read as TSX, as the shapes pass reads it", () => {
    const out = run( { "v.tsx": "export const view = <T,>( n: T ) => <div>{ n }</div>;\n" } );
    assert.deepEqual( out.map( ( r: any ) => r.name ), [ "view" ] );
} );

test( "shapes: a file the parser reports errors for is skipped, and listed apart from the scanned ones", () => {
    const out = run( { "good.js": "function a( x ) { return x; }\n", "bad.js": "function ( {{{ broken\n" }, { mode: "shapes" } );
    assert.deepEqual( out.scanned, [ "good.js" ] );
    assert.deepEqual( out.skipped, [ "bad.js" ] );
    assert.deepEqual( out.defs.map( ( d: any ) => d.name ), [ "a" ] );
} );

// ---- "bodies": the fields the duplicate checker adds to the shapes pass ------------------------------------------

const HERE      = path.resolve( process.cwd(), "src/tests/unit/ts_extract" );
const FIXTURE   = JSON.parse( fs.readFileSync( path.join( HERE, "bodies-fixture.json" ), "utf8" ) );
const GOLDEN    = JSON.parse( fs.readFileSync( path.join( HERE, "shapes-golden-d0bd4f604.json" ), "utf8" ) );
const bodiesRun = ( files: Record<string, string> = FIXTURE ) => run( files, { mode: "shapes", bodies: true } );
const byName    = ( out: any ) => Object.fromEntries( out.defs.map( ( d: any ) => [ d.file + "#" + d.name, d ] ) );

test( "bodies: without the flag the shapes output equals the golden captured from the script at d0bd4f604", () => {
    // The golden was written by the unchanged script before the flag existed. A golden regenerated by the new code would prove nothing.
    assert.deepEqual( run( FIXTURE, { mode: "shapes" } ), GOLDEN );
} );

test( "bodies: with the flag every definition keeps its shape fields and gains line, end_line, sig, text, calls, declared and public", () => {
    const out = bodiesRun();
    assert.deepEqual( out.defs.map( ( d: any ) => [ d.file, d.name, d.kinds ] ), GOLDEN.defs.map( ( d: any ) => [ d.file, d.name, d.kinds ] ) );
    for ( const d of out.defs ) assert.deepEqual( Object.keys( d ), [ "file", "name", "kinds", "line", "end_line", "sig", "text", "calls", "declared", "public" ] );
} );

test( "bodies: a method, a getter, an arrow in a const and a #private member carry correct lines, signature and text", () => {
    const by = byName( bodiesRun() );
    const pub = by[ "m.ts#Box.pub" ];
    assert.deepEqual( [ pub.line, pub.end_line, pub.sig, pub.public ], [ 4, 10, "(a: number, b: number): number", true ] );
    assert.ok( pub.text.startsWith( "public pub( a: number" ) && pub.text.endsWith( "}" ) );
    const getter = by[ "m.ts#Box.size" ];
    assert.deepEqual( [ getter.line, getter.end_line, getter.sig, getter.public, getter.text ], [ 14, 14, "(): number", true, "get size(): number { return this.count; }" ] );
    const arrow = by[ "m.ts#arrow" ];
    assert.deepEqual( [ arrow.line, arrow.end_line, arrow.public ], [ 17, 17, true ] );
    assert.ok( arrow.text.startsWith( "( x: number" ) );                       // the arrow itself, not the const around it
    const secret = by[ "m.ts#Box.#secret" ];
    assert.deepEqual( [ secret.line, secret.public, secret.text ], [ 12, false, "#secret( q ) { return q; }" ] );
} );

test( "bodies: private, protected and nested definitions are not public; a class property holding an arrow takes its property's access", () => {
    const by = byName( bodiesRun() );
    const pubs = Object.fromEntries( Object.entries( by ).map( ( [ k, d ]: [ string, any ] ) => [ k, d.public ] ) );
    assert.equal( pubs[ "m.ts#Box.priv" ], false );
    assert.equal( pubs[ "m.ts#Box.pub.<locals>.other" ], false );
    assert.equal( pubs[ "m.ts#outer.<locals>.inner" ], false );
    assert.equal( pubs[ "m.ts#Box.cb" ], true );
    assert.equal( pubs[ "m.ts#Box.make" ], true );
    assert.equal( bodiesRun( { "h.ts": "class H { private f = () => 1; protected g() { return 2; } }\n" } ).defs.map( ( d: any ) => d.public ).join(), "false,false" );
} );

test( "bodies: calls are the distinct callee names in order of first appearance, including new and member calls", () => {
    const by = byName( bodiesRun() );
    assert.deepEqual( by[ "m.ts#Box.pub" ].calls, [ "trim", "helper", "getTime", "Date" ] );
    assert.deepEqual( by[ "m.ts#outer" ].calls, [ "filter", "map", "inner" ] );
    assert.deepEqual( by[ "m.ts#Box.make" ].calls, [ "Box" ] );
    assert.deepEqual( by[ "p.js#twice" ].calls, [] );
} );

test( "bodies: a call through an index or a call result has no name and is left out; a private member call keeps its hash", () => {
    const src = "function f( t ) { t[ 0 ](); g()(); this.#p(); }\n";
    assert.deepEqual( bodiesRun( { "c.ts": src } ).defs[ 0 ].calls, [ "g", "#p" ] );
} );

test( "bodies: calls stop at fifty distinct names", () => {
    const body = Array.from( { length: 60 }, ( _, i ) => `c${i}();` ).join( " " );
    const calls = bodiesRun( { "many.ts": `function many() { ${body} }\n` } ).defs[ 0 ].calls;
    assert.equal( calls.length, 50 );
    assert.deepEqual( [ calls[ 0 ], calls[ 49 ] ], [ "c0", "c49" ] );
} );

test( "bodies: declared holds parameters, variables, destructured names and property names, once each, never the function's own name", () => {
    const by = byName( bodiesRun() );
    assert.deepEqual( by[ "m.ts#Box.pub" ].declared, [ "a", "b", "total", "wrapped", "inner", "other" ] );
    assert.deepEqual( by[ "m.ts#arrow" ].declared, [ "x", "y", "z" ] );
    const src = [ "class K {",
                  "    run( [ , first, ...rest ], { a, b: { c } }, again, again2 ) {",
                  "        const shorthand = 1, o = { shorthand, 'quoted-key': 2, [ computed ]: 3, plain: 4 };",
                  "        class Local { field = 1; #hid = 2; method() {} }",
                  "        return o;",
                  "    }",
                  "}", "" ].join( "\n" );
    const declared = bodiesRun( { "d.ts": src } ).defs[ 0 ].declared;
    assert.deepEqual( declared, [ "first", "rest", "a", "c", "again", "again2", "shorthand", "o", "plain", "field", "#hid", "method" ] );          // a local class name is not a property, parameter or variable
} );

test( "bodies: each scanned file reports every function-like node, counted apart from the walk, and the anonymous ones the walk passed over", () => {
    const out = bodiesRun();
    assert.deepEqual( out.scanned, [ { file: "m.ts", function_like_total: 13, anonymous_walked: 1 }, { file: "p.js", function_like_total: 3, anonymous_walked: 1 } ] );
    for ( const file of out.scanned ) {
        const reported = out.defs.filter( ( d: any ) => d.file === file.file ).length;
        assert.equal( reported + file.anonymous_walked, file.function_like_total );
    }
} );

test( "bodies: a file the parser reports errors for is skipped, and the good file is still accounted", () => {
    const out = bodiesRun( { "good.js": "function a( x ) { return x; }\n", "bad.js": "function ( {{{ broken\n" } );
    assert.deepEqual( out.skipped, [ "bad.js" ] );
    assert.deepEqual( out.scanned, [ { file: "good.js", function_like_total: 1, anonymous_walked: 0 } ] );
    assert.deepEqual( bodiesRun( { "good.js": "function a( x ) { return x; }\n" } ).skipped, [] );          // positive control: the repaired file is not skipped
} );

test( "bodies: text loses the indentation of the line the function starts on, so a method reads like the same body at the top of a file", () => {
    const by = byName( bodiesRun() );
    assert.ok( by[ "m.ts#Box.pub" ].text.split( "\n" )[ 1 ].startsWith( "    const total" ) && !by[ "m.ts#Box.pub" ].text.split( "\n" )[ 1 ].startsWith( "        " ) );
    const src = "class C {\n    m( a ) {\n        const t = a;\n        return t;\n    }\n}\nnamespace N {\n    class D {\n        m( a ) {\n            const t = a;\n            return t;\n        }\n    }\n}\n";
    const defs = bodiesRun( { "n.ts": src } ).defs;
    assert.deepEqual( defs.map( ( d: any ) => d.name ), [ "C.m", "D.m" ] );
    assert.equal( defs[ 0 ].text, defs[ 1 ].text );                                // a base of four spaces and a base of eight give the same text
    assert.equal( defs[ 0 ].text, "m( a ) {\n    const t = a;\n    return t;\n}" );
} );

test( "bodies: a line that does not start with the indent, such as the inside of a template literal, is left as it is", () => {
    const src = "class C {\n    m() {\n        return `a\nraw\n`;\n    }\n}\n";
    assert.equal( bodiesRun( { "t.ts": src } ).defs[ 0 ].text, "m() {\n    return `a\nraw\n`;\n}" );
} );
