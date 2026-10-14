// Tests for ts_kind_names.cjs, the kind-name table shared by the two extractor scripts.

import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";

const require_ = createRequire( import.meta.url );
const ts: any = require_( path.resolve( process.cwd(), "node_modules/typescript" ) );
const kindNames = require_( path.resolve( process.cwd(), "src/cosa/repo/symindex/ts_kind_names.cjs" ) );

test( "a kind shared with a marker is named by its real name, not the marker", () => {
    const names = kindNames( ts );
    assert.equal( names.get( ts.SyntaxKind.VariableStatement ), "VariableStatement" );
    assert.equal( ts.SyntaxKind[ ts.SyntaxKind.VariableStatement ], "FirstStatement", "the raw enum lookup is the alias this table replaces" );
    assert.equal( names.get( ts.SyntaxKind.NumericLiteral ), "NumericLiteral" );
} );

test( "every numeric kind maps to the first name declared with that value", () => {
    const names = kindNames( ts );
    const first = new Map<number, string>();
    for ( const [ name, value ] of Object.entries( ts.SyntaxKind ) ) {
        if ( typeof value === "number" && !first.has( value ) ) first.set( value, name );
    }
    assert.ok( first.size > 300 );
    assert.deepEqual( [ ...names.entries() ].sort(), [ ...first.entries() ].sort() );
} );

test( "ts_doc_extract.mjs uses the same table", () => {
    const src = require_( "node:fs" ).readFileSync( path.resolve( process.cwd(), "src/scripts/ts_doc_extract.mjs" ), "utf8" );
    assert.ok( src.includes( "ts_kind_names.cjs" ) && !src.includes( ".reverse()" ) );
    const res = spawnSync( process.execPath, [ "src/scripts/ts_doc_extract.mjs", "--help" ], { encoding: "utf8", cwd: process.cwd() } );
    assert.ok( !( res.stderr || "" ).includes( "Cannot find module" ), res.stderr );
} );
