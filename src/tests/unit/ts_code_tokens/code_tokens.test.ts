// Tests for ts_code_tokens.mjs, the token reader of the docs-only check for scripts.
//
// The module under test comes from TS_CODE_TOKENS_MODULE when that is set (the redden proofs point it at
// a copy with one line broken) and from src/scripts/ts_code_tokens.mjs otherwise.
//
// Run from the repo root, with the coverage gate on the module alone:
//   node_modules/.bin/c8 --100 --include=src/scripts/ts_code_tokens.mjs \
//     node_modules/.bin/tsx --test src/tests/unit/ts_code_tokens/*.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

export const SCRIPT = path.resolve( process.env.TS_CODE_TOKENS_MODULE ?? path.join( process.cwd(), "src/scripts/ts_code_tokens.mjs" ) );

let mod: any;
before( async () => { mod = await import( pathToFileURL( SCRIPT ).href ); } );

const words = ( described: any ): string[] => described.tokens.map( ( token: any[] ) => token[ 2 ] );

test( "isJavaScript: .js, .mjs and .cjs are JavaScript, .ts is not", () => {
    assert.deepEqual( [ "a.js", "a.mjs", "a.cjs", "a.ts", "a.js.ts" ].map( mod.isJavaScript ), [ true, true, true, false, false ] );
} );

test( "tokens: comments are trivia, so only code tokens appear, with their lines", () => {
    const described = mod.describe( "// lead\nconst a = 1; /* mid */ const b = 2; // tail\n", "a.ts" );
    assert.deepEqual( words( described ), [ "const", "a", "=", "1", ";", "const", "b", "=", "2", ";" ] );
    assert.deepEqual( described.tokens.map( ( token: any[] ) => token[ 0 ] ), Array( 10 ).fill( 2 ) );
} );

test( "tokens: a comment marker in a string, a template or a regular expression is code", () => {
    const described = mod.describe( "const s = \"// x\"; const t = `/* y */`; const r = /a\\/b/;\n", "a.ts" );
    assert.ok( words( described ).includes( "\"// x\"" ) );
    assert.ok( words( described ).includes( "`/* y */`" ) );
    assert.ok( words( described ).includes( "/a\\/b/" ) );
} );

test( "tokens: documentation comment nodes are skipped, the declaration's tokens stay", () => {
    const described = mod.describe( "/**\n * Doc.\n * @param {string} s the s\n */\nfunction f( s ) { return s; }\n", "a.js" );
    assert.deepEqual( words( described ), [ "function", "f", "(", "s", ")", "{", "return", "s", ";", "}" ] );
} );

test( "tokens: the same code gives the same tokens however it is commented", () => {
    const plain = mod.describe( "let a = 1;\n", "a.ts" );
    const noted = mod.describe( "/** A. */\nlet a = 1; // why\n", "a.ts" );
    assert.deepEqual( words( plain ), words( noted ) );
} );

test( "tokens: each token says whether a line break comes before it, a comment's break included", () => {
    const flags = ( source: string ): number[] => mod.describe( source, "a.ts" ).tokens.map( ( token: any[] ) => token[ 3 ] );
    assert.deepEqual( flags( "return 1;\n" ), [ 0, 0, 0 ] );
    assert.deepEqual( flags( "return\n1;\n" ), [ 0, 1, 0 ] );
    assert.deepEqual( flags( "return /* a\n b */ 1;\n" ), [ 0, 1, 0 ] );
    assert.deepEqual( flags( "return /* a b */ 1;\n" ), [ 0, 0, 0 ] );
    assert.deepEqual( flags( "\n// lead\nreturn 1;\n" ), [ 0, 0, 0 ] );
    assert.deepEqual( flags( "return\r1;\n" ), [ 0, 1, 0 ] );
    assert.deepEqual( flags( "return\u20281;\n" ), [ 0, 1, 0 ] );
    assert.deepEqual( flags( "return\u20291;\n" ), [ 0, 1, 0 ] );
} );

test( "marks: a directive comment is tied to the token that follows it, with its line position", () => {
    const marks = mod.describe( "let a;\n// @ts-ignore\nlet b = f( a );\nlet c; // eslint-disable-line x\nlet d;\n", "a.ts" ).marks;
    assert.deepEqual( marks, [ [ 3, "L:// @ts-ignore" ], [ 14, "T:// eslint-disable-line x" ] ] );
} );

test( "marks: banner, pure and coverage comments count, and plain comments do not", () => {
    const source = "/*! banner */\nlet a = /*#__PURE__*/ f();\n/* c8 ignore next */\n// plain note\nlet b;\n";
    assert.deepEqual( mod.describe( source, "a.ts" ).marks.map( ( mark: any[] ) => mark[ 1 ] ),
        [ "L:/*! banner */", "T:/*#__PURE__*/", "L:/* c8 ignore next */" ] );
} );

test( "marks: bundler magic comments and a comment at the end of the file are kept", () => {
    const marks = mod.describe( "const m = import( /* webpackChunkName: \"a\" */ \"./a.js\" );\n// @ts-nocheck\n", "a.ts" ).marks;
    assert.deepEqual( marks.map( ( mark: any[] ) => mark[ 1 ] ), [ "T:/* webpackChunkName: \"a\" */", "L:// @ts-nocheck" ] );
    assert.equal( marks[ 1 ][ 0 ], 8 );
} );

test( "marks: a documentation block is kept only for the words a tool reads", () => {
    const source = "/**\n * Plain doc.\n */\nlet a;\n/**\n * Doc. @internal\n * @import { T } from './a.js'\n */\nlet b;\n";
    assert.deepEqual( mod.describe( source, "a.ts" ).marks.map( ( mark: any[] ) => mark[ 1 ] ), [ "L:doc:@internal|@import { T } from './a.js'" ] );
} );

test( "tokens: the same text as an identifier and as a contextual keyword differs in the kind field", () => {
    const identifier = mod.describe( "let get = 1;\n", "a.ts" ).tokens.find( ( token: any[] ) => token[ 2 ] === "get" );
    const keyword    = mod.describe( "class A { get a() { return 1; } }\n", "a.ts" ).tokens.find( ( token: any[] ) => token[ 2 ] === "get" );
    assert.notEqual( identifier[ 1 ], keyword[ 1 ] );
} );

test( "describe: directives are the bodies of directive comments, in order", () => {
    const described = mod.describe( "// @ts-nocheck\n// plain\n/* eslint-disable no-console */\nlet a;\n", "a.ts" );
    assert.deepEqual( described.directives, [ "@ts-nocheck", "eslint-disable no-console" ] );
} );

test( "describe: a hashbang is returned and left out of the tokens", () => {
    const described = mod.describe( "#!/usr/bin/env node\nlet a;\n", "a.mjs" );
    assert.equal( described.shebang, "#!/usr/bin/env node" );
    assert.deepEqual( words( described ), [ "let", "a", ";" ] );
    assert.equal( mod.describe( "let a;\n", "a.mjs" ).shebang, null );
} );

test( "describe: JavaScript typed tags, template and typedef names are collected, prose tags are not", () => {
    const source = "/**\n * @param {string} s the s\n * @template T\n * @typedef {Object} Opt\n * @see elsewhere\n */\nfunction f( s ) { return s; }\n";
    assert.deepEqual( mod.describe( source, "a.js" ).tags, [ [ "param", "string" ], [ "template", "T" ], [ "typedef", "Object" ] ] );
} );

test( "describe: a TypeScript file gives no tags", () => {
    assert.deepEqual( mod.describe( "/**\n * @param {string} s the s\n */\nfunction f( s: string ) { return s; }\n", "a.ts" ).tags, [] );
} );

test( "describe: parse errors are listed with their line", () => {
    const described = mod.describe( "let a = 1;\nlet b = ;\n", "a.ts" );
    assert.equal( described.errors[ 0 ].line, 2 );
} );

test( "run: one JSON line per text, in order, with its id", () => {
    let out = "";
    const code = mod.run( JSON.stringify( [ { id: "x", name: "a.ts", text: "let a;\n" }, { id: "y", name: "b.js", text: "let b;\n" } ] ), { write: ( s: string ) => { out += s; } }, { write: () => {} } );
    assert.equal( code, 0 );
    assert.deepEqual( out.trim().split( "\n" ).map( ( l ) => JSON.parse( l ).id ), [ "x", "y" ] );
} );

test( "run: a text that cannot be described gets an error line, not a crash", () => {
    let out = "";
    mod.run( JSON.stringify( [ { id: "z", name: "a.ts", text: null } ] ), { write: ( s: string ) => { out += s; } }, { write: () => {} } );
    assert.match( JSON.parse( out ).errors[ 0 ].message, /^cannot describe: / );
} );

test( "run: input that is not a JSON list exits 2 with usage on stderr", () => {
    let err = "";
    assert.equal( mod.run( "not json", { write: () => {} }, { write: ( s: string ) => { err += s; } } ), 2 );
    assert.match( err, /^usage: / );
    assert.equal( mod.run( "{}", { write: () => {} }, { write: () => {} } ), 2 );
} );

test( "cli: run as a script it reads stdin and prints JSON Lines", () => {
    const run = spawnSync( process.execPath, [ SCRIPT ], { input: JSON.stringify( [ { id: "i", name: "a.ts", text: "let a = 1;\n" } ] ), encoding: "utf8" } );
    assert.equal( run.status, 0, run.stderr );
    assert.equal( JSON.parse( run.stdout ).id, "i" );
} );

test( "cli: importing the module from a script with no argv entry does not run it", () => {
    const run = spawnSync( process.execPath, [ "--input-type=module", "-e", `const m = await import( ${ JSON.stringify( pathToFileURL( SCRIPT ).href ) } ); process.stdout.write( typeof m.run )` ], { encoding: "utf8" } );
    assert.equal( run.status, 0, run.stderr );
    assert.equal( run.stdout, "function" );
} );
