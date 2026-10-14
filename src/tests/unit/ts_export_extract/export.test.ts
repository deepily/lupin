// Tests for ts_export_extract.mjs, the export lister of the doc comment existence check.
//
// Run from the repo root, with the coverage gate on the module alone:
//   node_modules/.bin/c8 --100 --include=src/scripts/ts_export_extract.mjs \
//     node_modules/.bin/tsx --test src/tests/unit/ts_export_extract/*.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

/** The path of the module under test. */
export const SCRIPT = path.resolve( process.cwd(), "src/scripts/ts_export_extract.mjs" );

let mod: any;
before( async () => { mod = await import( pathToFileURL( SCRIPT ).href ); } );

function symbols( source: string, name = "a.ts" ): any[] {
    return mod.exportsRecord( source, name ).symbols.map( ( s: any ) => [ s.kind, s.name, s.documented ] );
}

// ---------------------------------------------------------------- what is a symbol

test( "declarations: each exported kind is one symbol, paired with the block above it", () => {
    const src = [
        "/** f */", "export function f() {}", "export class C {}", "/** i */", "export interface I {}", "export type T = string;",
        "/** e */", "export enum E { A }", "export namespace N {}", "export import R = N.X;", "function hidden() {}"
    ].join( "\n" );
    assert.deepEqual( symbols( src ), [
        [ "function", "f", true ], [ "class", "C", false ], [ "interface", "I", true ], [ "type", "T", false ],
        [ "enum", "E", true ], [ "namespace", "N", false ], [ "import", "R", false ]
    ] );
} );

test( "variables: one symbol per name, destructuring and holes included, all sharing the statement's block", () => {
    const src = "/** v */\nexport const a = 1, { b, c: [ , d ] } = obj;\nexport let e;\n";
    assert.deepEqual( symbols( src ), [
        [ "variable", "a", true ], [ "variable", "b", true ], [ "variable", "d", true ], [ "variable", "e", false ]
    ] );
} );

test( "overloads and merged declarations are one symbol, documented when any of them is", () => {
    const src = "export function o( a: string ): void;\n/** doc */\nexport function o( a: number ): void;\nexport function o( a: any ) {}\n";
    assert.deepEqual( symbols( src ), [ [ "function", "o", true ] ] );
} );

test( "default and equals exports are symbols", () => {
    assert.deepEqual( symbols( "/** d */\nexport default 5;\n" ), [ [ "assignment", "default", true ] ] );
    assert.deepEqual( symbols( "export = thing;\n" ), [ [ "assignment", "export=", false ] ] );
    assert.deepEqual( symbols( "export default function () {}\n" ), [ [ "function", "default", false ] ] );
} );

test( "export lists: a local name takes the block of its declaration, an import is a re-export", () => {
    const src = "/** loc */\nfunction local() {}\nfunction bare() {}\nimport { Imp } from \"./m\";\nexport { local, bare as renamed, Imp };\n";
    const rec = mod.exportsRecord( src, "a.ts" );
    assert.deepEqual( rec.symbols.map( ( s: any ) => [ s.kind, s.name, s.documented ] ), [ [ "list", "local", true ], [ "list", "renamed", false ] ] );
    assert.equal( rec.reexports, 1 );
} );

test( "export lists: the block above the list documents its names", () => {
    assert.deepEqual( symbols( "const a = 1;\n/** group */\nexport { a };\n" ), [ [ "list", "a", true ] ] );
} );

test( "re-exports from another module are counted and are not symbols", () => {
    const rec = mod.exportsRecord( "export { z } from \"./z\";\nexport * from \"./all\";\nexport * as ns from \"./n\";\n", "a.ts" );
    assert.deepEqual( [ rec.symbols, rec.reexports ], [ [], 3 ] );
} );

test( "statements that are not exports add nothing", () => {
    const rec = mod.exportsRecord( "export as namespace Lib;\nexport {};\nconst x = 1;\nfoo();\n", "a.d.ts" );
    assert.deepEqual( [ rec.symbols, rec.reexports ], [ [], 0 ] );
} );

test( "an export statement the parser cannot finish adds nothing and the error is reported", () => {
    const rec = mod.exportsRecord( "export;\n", "a.ts" );
    assert.deepEqual( rec.symbols, [] );
    assert.ok( rec.parse_errors.length > 0 );
} );

// ---------------------------------------------------------------- what is a doc comment

test( "a block must be between the statement before and this one, and must say something", () => {
    const src = [
        "/**/", "export const a = 1;", "/** */", "export const b = 2;", "// @ts-ignore", "/** @ts-ignore */", "export const c = 3;",
        "export const d = 4; /** trailing */", "export const e = 5;", "/** real */ export const f = 6;", "/** one */", "export const g = 7;", "export const h = 8;"
    ].join( "\n" );
    assert.deepEqual( symbols( src ), [
        [ "variable", "a", false ], [ "variable", "b", false ], [ "variable", "c", false ], [ "variable", "d", false ],
        [ "variable", "e", false ], [ "variable", "f", true ], [ "variable", "g", true ], [ "variable", "h", false ]
    ] );
} );

test( "a line comment is not a doc comment", () => {
    assert.deepEqual( symbols( "// not a doc\nexport const a = 1;\n/* nor this */\nexport const b = 2;\n" ), [ [ "variable", "a", false ], [ "variable", "b", false ] ] );
} );

test( "script kind: a .js file is read as JavaScript", () => {
    assert.deepEqual( symbols( "/** d */\nexport function f( a ) {}\n", "a.mjs" ), [ [ "function", "f", true ] ] );
} );

test( "symbols carry the line of the statement's first token", () => {
    const rec = mod.exportsRecord( "\n/** d */\n\nexport function f() {}\n", "a.ts" );
    assert.equal( rec.symbols[ 0 ].line, 4 );
} );

// ---------------------------------------------------------------- main, in process

function sink() {
    const chunks: string[] = [];
    return { write: ( s: string ) => { chunks.push( s ); return true; }, text: () => chunks.join( "" ) };
}

test( "main: writes one record per file and returns 0", () => {
    const out = sink(), err = sink();
    const files: Record<string, string> = { "/r/a.ts": "export const a = 1;\n", "/r/b.ts": "const b = 2;\n" };
    assert.equal( mod.main( [ "--repo-root", "/r", "a.ts", "b.ts" ], out, err, ( p: string ) => files[ p ] ), 0 );
    assert.equal( err.text(), "" );
    const rows = out.text().trim().split( "\n" ).map( ( l: string ) => JSON.parse( l ) );
    assert.deepEqual( rows.map( ( r: any ) => [ r.kind, r.file, r.symbols.length ] ), [ [ "exports", "a.ts", 1 ], [ "exports", "b.ts", 0 ] ] );
} );

test( "main: a file that cannot be read gets a record that says why", () => {
    const out = sink();
    assert.equal( mod.main( [ "--repo-root", "/r", "x.ts" ], out, sink(), () => { throw new Error( "ENOENT" ); } ), 0 );
    assert.deepEqual( JSON.parse( out.text() ).parse_errors, [ { line: 0, message: "cannot extract: ENOENT" } ] );
} );

test( "main: the default reader reads a real file, and the default root is the working directory", () => {
    const out = sink();
    assert.equal( mod.main( [ "src/scripts/ts_export_extract.mjs" ], out, sink() ), 0 );
    const row = JSON.parse( out.text() );
    assert.deepEqual( [ row.file, row.parse_errors ], [ "src/scripts/ts_export_extract.mjs", [] ] );
    assert.deepEqual( row.symbols.map( ( s: any ) => s.name ).sort(), [ "exportsRecord", "main" ] );
    assert.ok( row.symbols.every( ( s: any ) => s.documented ) );
} );

test( "main: usage errors return 2 and write a usage line", () => {
    for ( const argv of [ [], [ "--repo-root", "/r" ], [ "--repo-root" ], [ "--bogus", "a.ts" ] ] ) {
        const out = sink(), err = sink();
        assert.equal( mod.main( argv, out, err, () => "" ), 2, JSON.stringify( argv ) );
        assert.match( err.text(), /^usage: / );
        assert.equal( out.text(), "" );
    }
} );

// ---------------------------------------------------------------- the command line, in a child process

test( "cli: run as a script it prints JSON Lines and exits 0", () => {
    const run = spawnSync( process.execPath, [ SCRIPT, "--repo-root", process.cwd(), "src/scripts/ts_export_extract.mjs" ], { encoding: "utf8" } );
    assert.equal( run.status, 0, run.stderr );
    assert.equal( JSON.parse( run.stdout ).kind, "exports" );
} );

test( "cli: bad arguments exit 2", () => {
    const run = spawnSync( process.execPath, [ SCRIPT ], { encoding: "utf8" } );
    assert.equal( run.status, 2 );
    assert.match( run.stderr, /^usage: / );
} );

test( "cli: importing the module from a script with no argv entry does not run it", () => {
    const run = spawnSync( process.execPath, [ "--input-type=module", "-e", `const m = await import( ${ JSON.stringify( pathToFileURL( SCRIPT ).href ) } ); process.stdout.write( typeof m.main );` ], { encoding: "utf8" } );
    assert.equal( run.status, 0, run.stderr );
    assert.equal( run.stdout, "function" );
} );
