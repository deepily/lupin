/**
 * List the exported top-level symbols of a script and say which have a doc comment.
 *
 * The existence check reads this output. The comment tokens come from ts_doc_extract.mjs, so a
 * directive, a bang comment and an empty block are never taken for documentation. This script adds
 * the export list and pairs each symbol with the block above it.
 *
 * Usage: node ts_export_extract.mjs --repo-root <dir> <file>...
 *
 * Output, one JSON object per file with these fields:
 *   - kind is "exports", file is the path, reexports is a count
 *   - parse_errors is a list of line and message
 *   - symbols is a list of name, kind, line and documented
 *
 * A symbol is one of these:
 *   - a top-level declaration with the export keyword
 *   - a default export or an export equals assignment
 *   - a name in an export list with no module specifier, declared in the same file
 *   - the declaration named on the right of a CommonJS assignment, found anywhere in the file
 *
 * A re-export from another module is counted in reexports and is not a symbol. So is a list entry
 * that names an import. The doc comment of such a name lives where it is declared.
 *
 * A CommonJS assignment is a write to module.exports, module.exports.name or exports.name. Its
 * symbol is the declaration the right side names, documented by the block above that declaration.
 * A right side that names no declaration of the file makes a symbol named by the assignment target.
 *
 * Declarations with one kind and one name merge into one symbol, so an overload set is one symbol.
 */

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import { extractFile } from "./ts_doc_extract.mjs";

const DECLARED = [
    [ ts.isFunctionDeclaration, "function" ], [ ts.isClassDeclaration, "class" ], [ ts.isInterfaceDeclaration, "interface" ],
    [ ts.isTypeAliasDeclaration, "type" ], [ ts.isEnumDeclaration, "enum" ], [ ts.isModuleDeclaration, "namespace" ],
    [ ts.isImportEqualsDeclaration, "import" ]
];

/**
 * Say whether a statement carries the export keyword.
 */
function isExported( node ) {
    return ts.canHaveModifiers( node ) && ( ts.getModifiers( node ) ?? [] ).some( ( m ) => m.kind === ts.SyntaxKind.ExportKeyword );
}

/**
 * Return every identifier a binding name introduces, destructuring included.
 */
function boundNames( name ) {
    if ( ts.isIdentifier( name ) ) return [ name.text ];
    return name.elements.flatMap( ( element ) => ( ts.isOmittedExpression( element ) ? [] : boundNames( element.name ) ) );
}

/**
 * Return the kind and names a declaration introduces, or null for any other statement.
 *
 * Requires:
 *   - node is a top-level statement
 *
 * Ensures:
 *   - an unnamed default function or class is named default
 */
function declared( node ) {
    if ( ts.isVariableStatement( node ) ) return { kind: "variable", names: node.declarationList.declarations.flatMap( ( d ) => boundNames( d.name ) ) };
    const hit = DECLARED.find( ( [ is ] ) => is( node ) );
    if ( hit === undefined ) return null;
    return { kind: hit[ 1 ], names: [ node.name === undefined ? "default" : node.name.text ] };
}

/**
 * Say whether an expression is a CommonJS export target.
 */
function isCommonjsTarget( left ) {
    if ( ! ts.isPropertyAccessExpression( left ) ) return false;
    const base = left.expression;
    if ( ts.isIdentifier( base ) ) return base.text === "exports" || ( base.text === "module" && left.name.text === "exports" );
    return ts.isPropertyAccessExpression( base ) && ts.isIdentifier( base.expression ) && base.expression.text === "module" && base.name.text === "exports";
}

/**
 * Return every assignment to a CommonJS export target inside a node.
 */
function commonjsAssignments( node ) {
    const found = [];
    const walk  = ( child ) => {
        if ( ts.isBinaryExpression( child ) && child.operatorToken.kind === ts.SyntaxKind.EqualsToken && isCommonjsTarget( child.left ) ) found.push( child );
        ts.forEachChild( child, walk );
    };
    walk( node );
    return found;
}

/**
 * Return the exported symbols of one parsed file with the pairing already decided.
 *
 * Requires:
 *   - sf is a source file made with parent nodes set
 *   - docs is the list of non-directive jsdoc records of the file with a non-blank text
 *
 * Ensures:
 *   - returns { symbols, reexports }, symbols in source order, one per kind and name
 *   - a statement is documented when a block sits between the end of the statement before it and its own first token
 *   - an export list entry is documented by the block above the list or by the local declaration it names
 *   - an export list entry that names no local declaration counts in reexports
 *   - a CommonJS assignment adds one commonjs symbol, unless the name it exports already is a symbol
 */
function exportsOf( sf, docs ) {
    const lineOf   = ( pos ) => sf.getLineAndCharacterOfPosition( pos ).line + 1;
    const local    = new Map();
    const localAt  = new Map();
    const assigned = [];
    const symbols  = new Map();
    let reexports  = 0;
    const documentedAt = ( node, prev ) => {
        const first = lineOf( node.getStart( sf ) );
        const floor = prev === undefined ? 0 : lineOf( prev.getEnd() );
        return docs.some( ( d ) => d.start_line > floor && d.end_line <= first );
    };
    const add = ( kind, name, node, documented ) => {
        const key = `${kind}|${name}`;
        const old = symbols.get( key );
        if ( old === undefined ) symbols.set( key, { name, kind, line: lineOf( node.getStart( sf ) ), documented } );
        else old.documented = old.documented || documented;
    };
    const listed = [];
    sf.statements.forEach( ( node, index ) => {
        const documented = documentedAt( node, sf.statements[ index - 1 ] );
        const decl       = declared( node );
        if ( decl !== null ) {
            decl.names.forEach( ( name ) => local.set( name, ( local.get( name ) ?? false ) || documented ) );
            decl.names.forEach( ( name ) => { if ( ! localAt.has( name ) ) localAt.set( name, node ); } );
            if ( isExported( node ) ) decl.names.forEach( ( name ) => add( decl.kind, name, node, documented ) );
        } else if ( ts.isExportAssignment( node ) ) {
            add( "assignment", node.isExportEquals ? "export=" : "default", node, documented );
        } else if ( ts.isExportDeclaration( node ) && node.moduleSpecifier !== undefined ) {
            reexports += 1;
        } else if ( ts.isExportDeclaration( node ) && node.exportClause !== undefined ) {
            node.exportClause.elements.forEach( ( spec ) => listed.push( { spec, node, documented } ) );
        }
        commonjsAssignments( node ).forEach( ( expr ) => assigned.push( { expr, node, documented } ) );
    } );
    listed.forEach( ( { spec, node, documented } ) => {
        const target = ( spec.propertyName ?? spec.name ).text;
        if ( ! local.has( target ) ) reexports += 1;
        else add( "list", spec.name.text, node, documented || local.get( target ) );
    } );
    assigned.forEach( ( { expr, node, documented } ) => {
        const name = ts.isIdentifier( expr.right ) && local.has( expr.right.text ) ? expr.right.text : null;
        if ( name === null ) add( "commonjs", expr.left.getText( sf ), node, documented );
        else if ( ! [ ...symbols.values() ].some( ( s ) => s.name === name ) ) add( "commonjs", name, localAt.get( name ), local.get( name ) );
    } );
    return { symbols: [ ...symbols.values() ].sort( ( a, b ) => a.line - b.line ), reexports };
}

/**
 * Describe the exports of one source text.
 *
 * Requires:
 *   - source is the text of a TypeScript or JavaScript file, fileName is its repo-relative path
 *
 * Ensures:
 *   - returns the record described in the file header
 *   - the file is parsed as ts_doc_extract.mjs parses it, so both agree on the comments
 */
export function exportsRecord( source, fileName ) {
    const scriptKind = /\.[mc]?js$/.test( fileName ) ? ts.ScriptKind.JS : ts.ScriptKind.TS;
    const sf         = ts.createSourceFile( fileName, source, ts.ScriptTarget.Latest, true, scriptKind );
    const { file, comments } = extractFile( source, fileName );
    const docs       = comments.filter( ( c ) => c.kind === "jsdoc" && ! c.directive && c.text.trim() !== "" );
    return { kind: "exports", file: fileName, parse_errors: file.parse_errors, ...exportsOf( sf, docs ) };
}

/**
 * Run the export list over the files named in argv and write JSON Lines to out.
 *
 * Requires:
 *   - argv is [ "--repo-root", <dir>, <file>... ]
 *   - out and err have a write method; readFile takes a path and returns text
 *
 * Ensures:
 *   - returns 0 after writing one record for every file
 *   - a file that cannot be read gets a record with no symbols whose parse_errors holds the reason
 *   - returns 2 and writes a usage line to err when the root or the file list is missing, or an option is unknown
 */
export function main( argv, out, err, readFile = ( file ) => fs.readFileSync( file, "utf8" ) ) {
    let root    = ".";
    const files = [];
    let bad     = false;
    for ( let i = 0; i < argv.length; i += 1 ) {
        if ( argv[ i ] === "--repo-root" ) {
            root = argv[ i + 1 ];
            i += 1;
        } else if ( argv[ i ].startsWith( "--" ) ) bad = true;
        else files.push( argv[ i ] );
    }
    if ( bad || root === undefined || files.length === 0 ) {
        err.write( "usage: ts_export_extract.mjs --repo-root DIR FILE...\n" );
        return 2;
    }
    for ( const file of files ) {
        let record;
        try {
            record = exportsRecord( readFile( path.join( root, file ) ), file );
        } catch ( error ) {
            record = { kind: "exports", file, parse_errors: [ { line: 0, message: `cannot extract: ${error.message}` } ], reexports: 0, symbols: [] };
        }
        out.write( JSON.stringify( record ) + "\n" );
    }
    return 0;
}

if ( import.meta.url === pathToFileURL( path.resolve( process.argv[ 1 ] ?? "" ) ).href ) {
    process.exitCode = main( process.argv.slice( 2 ), process.stdout, process.stderr );
}
