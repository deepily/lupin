// Tests for src/scripts/ts_doc_extract.mjs, the comment extractor of the TS/JS doc checker.
//
// The module under test comes from TS_DOC_EXTRACT_MODULE when that is set (the redden proofs point it at
// a copy with one line broken) and from src/scripts/ts_doc_extract.mjs otherwise.
//
// Run from the repo root, with the coverage gate on the module alone:
//   node_modules/.bin/c8 --100 --include=src/scripts/ts_doc_extract.mjs \
//     node_modules/.bin/tsx --test src/tests/unit/ts_doc_extract/*.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

export const SCRIPT = path.resolve( process.env.TS_DOC_EXTRACT_MODULE ?? path.join( process.cwd(), "src/scripts/ts_doc_extract.mjs" ) );

let mod: any;
before( async () => { mod = await import( pathToFileURL( SCRIPT ).href ); } );

function comments( source: string, name = "a.ts" ): any[] {
    return mod.extractFile( source, name ).comments;
}

function keep( rows: any[], ...fields: string[] ): any[] {
    return rows.map( ( row ) => Object.fromEntries( fields.map( ( field ) => [ field, row[ field ] ] ) ) );
}

// ---------------------------------------------------------------- file header

test( "file header: the first prose comment is <file-header>, after a hashbang and directives", () => {
    const rows = comments( "#!/usr/bin/env node\n// @ts-nocheck\n/*! banner */\n// Header one.\n// Header two.\n\nfunction f() {}\n" );
    assert.deepEqual( keep( rows, "text", "symbol_key", "directive" ), [
        { text: "@ts-nocheck", symbol_key: null, directive: true },
        { text: "! banner", symbol_key: null, directive: true },
        { text: "Header one.\nHeader two.", symbol_key: "<file-header>", directive: false }
    ] );
} );

test( "file header: not given when code comes before the first comment", () => {
    const rows = comments( "const a = 1;\n// later note\nfunction f() {}\n" );
    assert.equal( rows[ 0 ].symbol_key, "FunctionDeclaration|f|1" );
} );

test( "file header: not given when another comment sits between a directive and the first prose comment", () => {
    const rows = comments( "// @ts-nocheck\nconst a = 1;\n// later\nfunction f() {}\n" );
    assert.deepEqual( keep( rows, "symbol_key" ), [ { symbol_key: null }, { symbol_key: "FunctionDeclaration|f|1" } ] );
} );

test( "file header: not given when code comes before a directive that comes before the first prose comment", () => {
    const rows = comments( "x();\n// @ts-ignore\ny();\n// prose\nfunction f() {}\n" );
    assert.deepEqual( keep( rows, "directive", "symbol_key" ), [ { directive: true, symbol_key: null }, { directive: false, symbol_key: "FunctionDeclaration|f|1" } ] );
} );

test( "file header: a trailing comment is never the header", () => {
    const rows = comments( "x(); // trailing\n" );
    assert.deepEqual( keep( rows, "kind", "symbol_key" ), [ { kind: "trailing", symbol_key: "ExpressionStatement||1" } ] );
} );

test( "file header: a file with no comment gives no record, and a file of only a directive gives no header", () => {
    assert.deepEqual( comments( "const a = 1;\n" ), [] );
    assert.deepEqual( keep( comments( "// eslint-disable\n" ), "symbol_key", "directive" ), [ { symbol_key: null, directive: true } ] );
} );

// ---------------------------------------------------------------- directives

test( "directive forms are flagged, and each is its own record", () => {
    const forms = [
        "// @ts-expect-error because", "// @ts-ignore", "// @ts-check", "// eslint-disable-next-line no-x",
        "// eslint-enable", "// eslint-env node", "// c8 ignore next", "// istanbul ignore else", "// v8 ignore next",
        "// prettier-ignore", "// #region parts", "// #endregion", "/// <reference path=\"x\" />",
        "//# sourceMappingURL=x.map", "//@ sourceURL=y", "/*! banner */", "/** @license MIT */", "/* @preserve */"
    ];
    for ( const form of forms ) {
        const rows = comments( `${form}\nconst a = 1;\n` );
        assert.equal( rows.length, 1, form );
        assert.equal( rows[ 0 ].directive, true, form );
        assert.equal( rows[ 0 ].symbol_key, null, form );
    }
} );

test( "directive forms: prose that only resembles one is not a directive", () => {
    for ( const prose of [ "// eslint is slow here", "// see @ts-ignore in the notes", "// a region of memory", "// the license text" ] ) {
        assert.equal( comments( `${prose}\nconst a = 1;\n` )[ 0 ].directive, false, prose );
    }
} );

test( "a directive line inside a prose run splits the run into three records", () => {
    const rows = comments( "// prose before\n// eslint-disable-next-line x\n// prose after\nconst a = 1;\n" );
    assert.deepEqual( keep( rows, "text", "directive", "start_line", "end_line" ), [
        { text: "prose before", directive: false, start_line: 1, end_line: 1 },
        { text: "eslint-disable-next-line x", directive: true, start_line: 2, end_line: 2 },
        { text: "prose after", directive: false, start_line: 3, end_line: 3 }
    ] );
} );

test( "a trailing directive keeps its flag", () => {
    const rows = comments( "const a = 1; // eslint-disable-line x\n" );
    assert.deepEqual( keep( rows, "kind", "directive", "symbol_key" ), [ { kind: "trailing", directive: true, symbol_key: null } ] );
} );

// ---------------------------------------------------------------- runs

test( "line runs: consecutive lines merge, a blank line splits, a block comment splits", () => {
    const rows = comments( "const z = 0;\n// one\n// two\n\n// three\n/* block */\n// four\nfunction f() {}\n" );
    assert.deepEqual( keep( rows, "kind", "text", "start_line", "end_line" ), [
        { kind: "line-run", text: "one\ntwo", start_line: 2, end_line: 3 },
        { kind: "line-run", text: "three", start_line: 5, end_line: 5 },
        { kind: "block", text: "block", start_line: 6, end_line: 6 },
        { kind: "line-run", text: "four", start_line: 7, end_line: 7 }
    ] );
} );

test( "line runs: a trailing comment does not join the run that follows it", () => {
    const rows = comments( "const a = 1; // trail\n// own line\nfunction f() {}\n" );
    assert.deepEqual( keep( rows, "kind", "text" ), [ { kind: "trailing", text: "trail" }, { kind: "line-run", text: "own line" } ] );
} );

test( "line runs: a run keeps indentation after the first space", () => {
    const rows = comments( "//   indented\n//no space\n//\nfunction f() {}\n" );
    assert.equal( rows[ 0 ].text, "  indented\nno space\n" );
} );

// ---------------------------------------------------------------- trailing

test( "trailing: a block comment after code on the same line is trailing", () => {
    const rows = comments( "const a = 1; /* note */\nconst b = 2;\n" );
    assert.deepEqual( keep( rows, "kind", "text" ), [ { kind: "trailing", text: "note" } ] );
} );

test( "trailing: a comment after a comma inside a call is trailing and has no symbol", () => {
    const rows = comments( "foo( a, // first\n     b );\n" );
    assert.deepEqual( keep( rows, "kind", "text", "symbol_key" ), [ { kind: "trailing", text: "first", symbol_key: null } ] );
} );

// ---------------------------------------------------------------- text shape

test( "block text keeps one line per comment line, so line i of the text is file line start_line + i", () => {
    const source = "/**\n * Add two numbers.\n *\n * - item\n *   nested\n */\nfunction add() {}\n";
    const row    = comments( source )[ 0 ];
    assert.equal( row.text, "\nAdd two numbers.\n\n- item\n  nested\n" );
    assert.equal( row.text.split( "\n" ).length, row.end_line - row.start_line + 1 );
    assert.deepEqual( [ row.start_line, row.end_line ], [ 1, 6 ] );
} );

test( "block text: a one-line jsdoc and an empty block", () => {
    const rows = comments( "/** one line */\nfunction a() {}\n/**/\nfunction b() {}\n" );
    assert.deepEqual( keep( rows, "kind", "text" ), [ { kind: "jsdoc", text: "one line" }, { kind: "block", text: "" } ] );
} );

test( "block text: a plain block without stars loses the shared indentation only", () => {
    const rows = comments( "/* head\n     body one\n       deeper\n\n     body two\n*/\nfunction f() {}\n" );
    assert.equal( rows[ 0 ].kind, "block" );
    assert.equal( rows[ 0 ].text, "head\nbody one\n  deeper\n\nbody two\n" );
} );

test( "block text: a star-margin line loses the star and one space, and trailing spaces", () => {
    const rows = comments( "/* head   \n   *   kept  \n */\nfunction f() {}\n" );
    assert.equal( rows[ 0 ].text, "head\n  kept\n" );
} );

// ---------------------------------------------------------------- tags

test( "tags: the compiler's tags for a block beside a declaration, with type and name", () => {
    const rows = comments( "/**\n * Add.\n * @param {number} a - first\n * @param b - untyped\n * @returns {number} sum\n * @typedef {object} Pair\n */\nfunction add( a, b ) {}\n" );
    assert.deepEqual( rows[ 0 ].tags, [
        { tag: "param", type: "number", name: "a" },
        { tag: "param", type: null, name: "b" },
        { tag: "returns", type: "number", name: null },
        { tag: "typedef", type: "object", name: "Pair" }
    ] );
} );

test( "tags: a type cast written after code on the same line is a trailing record that still carries its tag", () => {
    const rows = comments( "const s = ( /** @type {string} */ ( x ) );\nconst t = 1; /* @type {no} */\n" );
    assert.deepEqual( keep( rows, "kind", "tags" ), [
        { kind: "trailing", tags: [ { tag: "type", type: "string", name: null } ] },
        { kind: "trailing", tags: [] }
    ] );
} );

test( "tags: a block with no tags has an empty list, and other kinds never have tags", () => {
    const rows = comments( "/** just prose */\nfunction f() {}\n/* plain @param {x} y */\nfunction g() {}\n// line @param {x} y\nfunction h() {}\n" );
    assert.deepEqual( keep( rows, "kind", "tags" ), [
        { kind: "jsdoc", tags: [] }, { kind: "block", tags: [] }, { kind: "line-run", tags: [] }
    ] );
} );

test( "tags: a JavaScript file's type tags are read as types", () => {
    const rows = comments( "/** @type {Map<string, number>} */\nconst m = new Map();\n/** @param {string} a\n * @returns {void} */\nfunction f( a ) {}\n", "a.js" );
    assert.deepEqual( rows[ 0 ].tags, [ { tag: "type", type: "Map<string, number>", name: null } ] );
    assert.deepEqual( rows[ 1 ].tags, [ { tag: "param", type: "string", name: "a" }, { tag: "returns", type: "void", name: null } ] );
} );

test( "tags: a block beside nothing falls back to the line reader", () => {
    const rows = comments( "function f() {\n    x();\n    /**\n     * @param {string} a - note\n     * @returns {void}\n     * @private\n     * prose line\n     */\n}\n" );
    assert.equal( rows[ 0 ].symbol_key, null );
    assert.deepEqual( rows[ 0 ].tags, [
        { tag: "param", type: "string", name: "a" }, { tag: "returns", type: "void", name: null }, { tag: "private", type: null, name: null }
    ] );
} );

test( "tags: a block beside a node that holds no jsdoc falls back too", () => {
    const rows = comments( "const list = [\n    /** @type {number} */\n    first\n];\n" );
    assert.equal( rows[ 0 ].kind, "jsdoc" );
    assert.deepEqual( rows[ 0 ].tags, [ { tag: "type", type: "number", name: null } ] );
} );

// ---------------------------------------------------------------- symbols

test( "symbols: kind, dotted owner and ordinal, with overloads counted in source order", () => {
    const source = [
        "const first = 0;",
        "/** one */", "export function over( a: string ): void;",
        "/** two */", "export function over( a: number ): void;",
        "export function over( a: any ) {}",
        "class K {",
        "    /** field */", "    count = 0;",
        "    /** ctor */", "    constructor() {}",
        "    /** getter */", "    get v() { return 1; }",
        "    /** setter */", "    set v( x ) {}",
        "    /** computed */", "    [ key ]() {}",
        "}",
        "/** default */", "export default function () {}",
        "/** default value */", "export default 42;",
        "/** arrow */", "const arrow = () => {",
        "    // inner", "    x();", "};",
        "/** pattern */", "const { p } = obj;",
        "/** unnamed if */", "if ( a ) {}",
        "/** the interface */", "interface I {", "    /** member */", "    m: string", "}",
        ""
    ].join( "\n" );
    const rows = keep( comments( source ), "text", "symbol_key" );
    assert.deepEqual( rows.map( ( row ) => row.symbol_key ), [
        "FunctionDeclaration|over|1", "FunctionDeclaration|over|2",
        "PropertyDeclaration|K.count|1", "Constructor|K.constructor|1", "GetAccessor|K.v|1", "SetAccessor|K.v|1",
        "MethodDeclaration|K|1",
        "FunctionDeclaration||1", "ExportAssignment|default|1",
        "VariableStatement|arrow|1", "ExpressionStatement|arrow|1",
        "VariableStatement||1", "IfStatement||1",
        "InterfaceDeclaration|I|1", "PropertySignature|I.m|1"
    ] );
} );

test( "symbols: a comment before a closing brace, an else keyword or the end of the file has no symbol", () => {
    const rows = comments( "if ( a ) {\n    x();\n    // before brace\n} // after brace\n/* before else */ else {\n}\n// at the end\n" );
    assert.deepEqual( keep( rows, "text", "kind", "symbol_key" ), [
        { text: "before brace", kind: "line-run", symbol_key: null },
        { text: "after brace", kind: "trailing", symbol_key: "Block||1" },
        { text: "before else", kind: "block", symbol_key: null },
        { text: "at the end", kind: "line-run", symbol_key: null }
    ] );
} );

test( "symbols: kind names are the first name of a value, never First or Last markers", () => {
    const rows = comments( "const first = 0;\n/** v */\nvar v = 1;\n/** c */\nclass C {}\n/** e */\nenum E { A }\n" );
    assert.deepEqual( keep( rows, "symbol_key" ), [
        { symbol_key: "VariableStatement|v|1" }, { symbol_key: "ClassDeclaration|C|1" }, { symbol_key: "EnumDeclaration|E|1" }
    ] );
} );

// ---------------------------------------------------------------- commented code

test( "commented code: true only when the run parses clean and holds a call, assignment or declaration", () => {
    const cases: [ string, boolean ][] = [
        [ "foo( 1 );", true ], [ "x = 1;", true ], [ "const a = 2;", true ], [ "function f() {}", true ],
        [ "import x from 'y';", true ], [ "total += step;", true ],
        [ "Mounted BEFORE the task list purely to match the DOM order the user sees;", false ],
        [ "Legacy: a partial tally at the deadline goes TIMED OUT and stays on screen;", false ],
        [ "a + b;", false ], [ "just_a_name;", false ], [ "if ( a ) {}", false ], [ "this does not parse )", false ]
    ];
    for ( const [ text, code ] of cases ) {
        assert.equal( comments( `// ${text}\nfunction f() {}\n` )[ 0 ].commented_code, code, text );
    }
} );

test( "commented code: a multi-line run is judged as one script", () => {
    const rows = comments( "// const a = 1;\n// foo( a );\nfunction f() {}\n" );
    assert.equal( rows[ 0 ].commented_code, true );
    assert.equal( comments( "// const a = 1;\n// not code here\nfunction f() {}\n" )[ 0 ].commented_code, false );
} );

test( "commented code: never set for a directive, a jsdoc block or a trailing comment", () => {
    const rows = comments( "// eslint-disable foo( 1 );\n/** foo( 1 ); */\nfunction f() {} // foo( 1 );\n" );
    assert.deepEqual( rows.map( ( row ) => row.commented_code ), [ false, false, false ] );
} );

// ---------------------------------------------------------------- the cases that break a bare scanner

test( "golden: slashes inside a regular expression literal are not a comment", () => {
    assert.deepEqual( comments( "const r = /ab+\\/\\//;\nconst s = x.replace( /a\\/\\/b/g, '' );\n" ), [] );
} );

test( "golden: a division is not a regular expression, and a comment after it is found", () => {
    const rows = comments( "const q = a / b // c\nconst r = x = /re/g // trailing\n" );
    assert.deepEqual( keep( rows, "kind", "text", "start_line" ), [
        { kind: "trailing", text: "c", start_line: 1 }, { kind: "trailing", text: "trailing", start_line: 2 }
    ] );
} );

test( "golden: a template literal with a comment inside the substitution", () => {
    const rows = comments( "const t = `head ${ /* c */ x } tail // not a comment`;\n" );
    assert.deepEqual( keep( rows, "kind", "text" ), [ { kind: "trailing", text: "c" } ] );
} );

test( "golden: slashes inside strings are not comments", () => {
    assert.deepEqual( comments( "const u = 'http://example.com/a'; const v = \"// no\"; const w = `// no`;\n" ), [] );
} );

test( "golden: an HTML-style comment is a parse error, reported and not thrown", () => {
    const result = mod.extractFile( "<!-- old style\nconst a = 1;\n", "a.js" );
    assert.ok( result.file.parse_errors.length > 0 );
    assert.deepEqual( result.comments, [] );
} );

// ---------------------------------------------------------------- file record

test( "file record: kind, file, version and parse errors with line numbers", () => {
    const clean = mod.extractFile( "const a = 1;\n", "src/x.ts" ).file;
    assert.deepEqual( [ clean.kind, clean.file, clean.parse_errors ], [ "file", "src/x.ts", [] ] );
    assert.match( clean.ts_version, /^\d+\.\d+\.\d+/ );
    const broken = mod.extractFile( "const a = 1;\nconst = ;\n", "src/y.ts" ).file;
    assert.equal( broken.parse_errors[ 0 ].line, 2 );
    assert.equal( typeof broken.parse_errors[ 0 ].message, "string" );
} );

test( "file record: every comment record carries the version of the compiler", () => {
    const rows = comments( "// note\nconst a = 1;\n" );
    assert.equal( rows[ 0 ].ts_version, mod.extractFile( "", "a.ts" ).file.ts_version );
} );

test( "script kind: .d.ts, .ts, .js, .mjs and .cjs files are all read", () => {
    for ( const name of [ "a.d.ts", "a.ts", "a.js", "a.mjs", "a.cjs" ] ) {
        const rows = comments( "const first = 0;\n/** doc */\nfunction f() {}\n", name );
        assert.deepEqual( keep( rows, "kind", "symbol_key" ), [ { kind: "jsdoc", symbol_key: "FunctionDeclaration|f|1" } ], name );
    }
} );

// ---------------------------------------------------------------- main, in process

function sink() {
    const chunks: string[] = [];
    return { write: ( s: string ) => { chunks.push( s ); return true; }, text: () => chunks.join( "" ) };
}

test( "main: writes a file record then comment records for every file, and returns 0", () => {
    const out = sink(), err = sink();
    const files: Record<string, string> = { "/r/a.ts": "// one\nconst a = 1;\n", "/r/b.ts": "const b = 2;\n" };
    const code = mod.main( [ "--repo-root", "/r", "a.ts", "b.ts" ], out, err, ( p: string ) => files[ p ] );
    assert.equal( code, 0 );
    assert.equal( err.text(), "" );
    const lines = out.text().trim().split( "\n" ).map( ( l: string ) => JSON.parse( l ) );
    assert.deepEqual( lines.map( ( l: any ) => [ l.kind, l.file ] ), [ [ "file", "a.ts" ], [ "line-run", "a.ts" ], [ "file", "b.ts" ] ] );
} );

test( "main: a file that cannot be read gets a file record that says why", () => {
    const out = sink();
    const code = mod.main( [ "--repo-root", "/r", "missing.ts" ], out, sink(), () => { throw new Error( "ENOENT: no such file" ); } );
    assert.equal( code, 0 );
    const row = JSON.parse( out.text() );
    assert.deepEqual( row.parse_errors, [ { line: 0, message: "cannot extract: ENOENT: no such file" } ] );
} );

test( "main: the default reader reads a real file under the repo root", () => {
    const out = sink();
    const code = mod.main( [ "--repo-root", process.cwd(), "src/lupin_app/static/js/nav/boot.ts" ], out, sink() );
    assert.equal( code, 0 );
    const first = JSON.parse( out.text().split( "\n" )[ 0 ] );
    assert.deepEqual( [ first.kind, first.file, first.parse_errors ], [ "file", "src/lupin_app/static/js/nav/boot.ts", [] ] );
} );

test( "main: usage errors return 2 and write a usage line", () => {
    for ( const argv of [ [], [ "--repo-root", "/r" ], [ "--repo-root" ], [ "--bogus", "a.ts" ] ] ) {
        const out = sink(), err = sink();
        assert.equal( mod.main( argv, out, err, () => "" ), 2, JSON.stringify( argv ) );
        assert.match( err.text(), /^usage: / );
        assert.equal( out.text(), "" );
    }
} );

test( "main: the default root is the working directory", () => {
    const out = sink();
    const code = mod.main( [ "src/lupin_app/static/js/nav/boot.ts" ], out, sink() );
    assert.equal( code, 0 );
    assert.equal( JSON.parse( out.text().split( "\n" )[ 0 ] ).parse_errors.length, 0 );
} );

// ---------------------------------------------------------------- the command line, in a child process

test( "cli: run as a script it prints JSON Lines for the named files and exits 0", () => {
    const run = spawnSync( process.execPath, [ SCRIPT, "--repo-root", process.cwd(), "src/lupin_app/static/js/nav/boot.ts" ], { encoding: "utf8" } );
    assert.equal( run.status, 0, run.stderr );
    const lines = run.stdout.trim().split( "\n" ).map( ( l ) => JSON.parse( l ) );
    assert.equal( lines[ 0 ].kind, "file" );
    assert.ok( lines.length >= 2 );
} );

test( "cli: bad arguments exit 2 and print usage on stderr", () => {
    const run = spawnSync( process.execPath, [ SCRIPT ], { encoding: "utf8" } );
    assert.equal( run.status, 2 );
    assert.match( run.stderr, /^usage: / );
    assert.equal( run.stdout, "" );
} );

test( "cli: importing the module from a script with no argv entry does not run it", () => {
    const run = spawnSync( process.execPath, [ "--input-type=module", "-e", `const m = await import( ${ JSON.stringify( pathToFileURL( SCRIPT ).href ) } ); process.stdout.write( typeof m.main );` ], { encoding: "utf8" } );
    assert.equal( run.status, 0, run.stderr );
    assert.equal( run.stdout, "function" );
} );
