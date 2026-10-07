/**
 * Extract every comment from TypeScript and JavaScript files as JSON Lines.
 *
 * The documentation linter reads this output and runs the Python text rules over it. The
 * compiler finds the comments, so a double slash inside a string, a template literal or a
 * regular expression literal is never taken for one. A bare scanner cannot tell division from a
 * regular expression, which is why the parse tree is walked instead.
 *
 * Usage: node ts_doc_extract.mjs --repo-root DIR FILE...
 *
 * Output, one JSON object per line. A file record comes first for each file:
 *   { kind: "file", file, ts_version, parse_errors: [ { line, message } ] }
 * then one record per comment, in source order:
 *   { kind, file, text, start_line, end_line, symbol_key, directive, commented_code, tags, ts_version }
 *
 * kind is jsdoc, block, line-run or trailing. A line-run is consecutive leading double slash
 * comments on consecutive lines, merged. A trailing comment follows code on the same line.
 * tags is filled for every comment written with the double-star opener, trailing ones included,
 * because a type cast such as a trailing type tag is type code that the compiler reads.
 * Text line i of a record sits on file line start_line + i, so the reader can report real lines.
 * A directive comment is never merged into a run: each directive line is its own record.
 */

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

// The compiler's enum maps a value back to a name, and the markers declared after a kind share its value
// (VariableStatement and FirstStatement). The entries are reversed so the first declared name wins.
const KIND_NAMES = new Map(
    Object.entries( ts.SyntaxKind )
        .filter( ( [ , value ] ) => typeof value === "number" )
        .reverse()
        .map( ( [ name, value ] ) => [ value, name ] )
);

const DIRECTIVE_BODY = new RegExp(
    "^(@ts-(expect-error|ignore|nocheck|check)\\b"
    + "|eslint-(disable|enable|env)\\b"
    + "|(c8|istanbul|v8) ignore\\b"
    + "|prettier-ignore\\b"
    + "|#(end)?region\\b"
    + "|/\\s*<(reference|amd-module|amd-dependency)\\b"
    + "|[#@]\\s*source(Mapping)?URL=)"
);
const LICENSE_BODY = /^@(license|preserve)\b/;
const STAR_LINE    = /^\s*\*/;
const DECLARATIONS = [
    ts.isVariableStatement, ts.isFunctionDeclaration, ts.isClassDeclaration, ts.isInterfaceDeclaration,
    ts.isTypeAliasDeclaration, ts.isEnumDeclaration, ts.isImportDeclaration, ts.isExportDeclaration
];

/**
 * Strip the delimiter from one double slash comment.
 *
 * Requires:
 *   - raw starts with two slashes
 *
 * Ensures:
 *   - returns the body with the slashes and one following space removed, trailing space dropped
 */
function lineBody( raw ) {
    const body = raw.slice( 2 );
    return ( body.startsWith( " " ) ? body.slice( 1 ) : body ).trimEnd();
}

/**
 * Strip the delimiters and the star margin from one block comment.
 *
 * Requires:
 *   - raw starts with a slash and a star and ends with a star and a slash
 *
 * Ensures:
 *   - returns the same number of lines as raw, so line i of the result is line i of the comment
 *   - a line that starts with a star loses that star and one space
 *   - a line without a star loses the indentation shared by all such lines
 */
function blockBody( raw ) {
    const inner  = raw.slice( 2, -2 );
    const lines  = ( inner.startsWith( "*" ) ? inner.slice( 1 ) : inner ).split( "\n" );
    const rest   = lines.slice( 1 );
    const plain  = rest.filter( ( line ) => line.trim() !== "" && ! STAR_LINE.test( line ) );
    const indent = Math.min( ...plain.map( ( line ) => line.length - line.trimStart().length ) );
    const body   = rest.map( ( line ) => ( STAR_LINE.test( line ) ? line.replace( /^\s*\* ?/, "" ) : line.slice( indent ) ).trimEnd() );
    return [ lines[ 0 ].replace( /^ /, "" ).trimEnd(), ...body ].join( "\n" );
}

/**
 * Say whether a comment is a directive for a tool, and so never prose.
 *
 * Requires:
 *   - raw is the comment as written, body is its stripped text
 *
 * Ensures:
 *   - true for a type, lint, coverage or formatter directive, a region marker, a triple-slash
 *     reference, a source map comment, a bang comment or a license block that starts the comment
 */
function isDirective( raw, body ) {
    const start = body.trim();
    return raw.startsWith( "/*!" ) || DIRECTIVE_BODY.test( start ) || LICENSE_BODY.test( start );
}

/**
 * Say whether a run of comment lines is commented-out code.
 *
 * Requires:
 *   - text is the stripped text of one run
 *
 * Ensures:
 *   - true only when the text parses as a script with no diagnostics and holds a call, an
 *     assignment or a declaration; prose with a stray semicolon fails to parse, so it is not code
 */
function looksLikeCode( text ) {
    const sf = ts.createSourceFile( "run.ts", text, ts.ScriptTarget.Latest, false, ts.ScriptKind.TS );
    if ( sf.parseDiagnostics.length > 0 ) return false;
    let found = false;
    const walk = ( node ) => {
        if ( ts.isCallExpression( node )
            || ( ts.isBinaryExpression( node ) && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && node.operatorToken.kind <= ts.SyntaxKind.LastAssignment )
            || DECLARATIONS.some( ( is ) => is( node ) ) ) found = true;
        ts.forEachChild( node, walk );
    };
    walk( sf );
    return found;
}

/**
 * Return the text of a name node, or an empty string for a name that is not plain text.
 */
function nameText( node ) {
    return node !== undefined && typeof node.text === "string" ? node.text : "";
}

/**
 * Return the name one declaration contributes to a symbol, or an empty string.
 *
 * Requires:
 *   - node is a parse tree node that is not the source file
 *
 * Ensures:
 *   - a variable statement is named by its first declaration; the declaration itself adds nothing,
 *     so the owner chain never repeats the name
 */
function declName( node ) {
    if ( ts.isVariableDeclaration( node ) ) return "";
    if ( ts.isVariableStatement( node ) ) return nameText( node.declarationList.declarations[ 0 ].name );
    if ( ts.isConstructorDeclaration( node ) ) return "constructor";
    if ( ts.isExportAssignment( node ) ) return "default";
    return nameText( node.name );
}

/**
 * Return the dotted symbol of a node: its enclosing named declarations, then its own name.
 *
 * Requires:
 *   - node is a parse tree node with a parent chain that ends at the source file
 *
 * Ensures:
 *   - returns an empty string when neither the node nor any enclosing declaration has a name
 */
function symbolOf( node ) {
    const owners = [];
    for ( let parent = node.parent; parent.kind !== ts.SyntaxKind.SourceFile; parent = parent.parent ) owners.unshift( declName( parent ) );
    return [ ...owners, declName( node ) ].filter( Boolean ).join( "." );
}

/**
 * Say whether a node is a punctuation mark, a keyword or the end of the file.
 */
function isBareToken( node ) {
    const kind = node.kind;
    return kind === ts.SyntaxKind.EndOfFileToken
        || ( kind >= ts.SyntaxKind.FirstPunctuation && kind <= ts.SyntaxKind.LastPunctuation )
        || ( kind >= ts.SyntaxKind.FirstKeyword && kind <= ts.SyntaxKind.LastKeyword );
}

/**
 * Walk the parse tree and collect the comment ranges with the node each one sits beside.
 *
 * Requires:
 *   - sf is a source file made with parent nodes set
 *
 * Ensures:
 *   - every comment in the file is returned once, as { pos, end, trailing, owner }
 *   - a leading comment's owner is the outermost node that starts where the comment's group ends
 *   - a trailing comment's owner is the outermost node that ends where the comment begins
 *   - owner is undefined when that node is a punctuation mark, a keyword or the end of the file
 */
function collectRanges( sf ) {
    const text    = sf.text;
    const found   = new Map();
    const starts  = new Set();
    const ends    = new Set();
    const add     = ( ranges, trailing, node ) => {
        for ( const range of ranges ?? [] ) {
            if ( ! found.has( range.pos ) ) found.set( range.pos, { pos: range.pos, end: range.end, trailing, owner: isBareToken( node ) ? undefined : node } );
        }
    };
    const visit = ( node ) => {
        if ( node.kind >= ts.SyntaxKind.FirstJSDocNode && node.kind <= ts.SyntaxKind.LastJSDocNode ) return;
        const owns = node.kind !== ts.SyntaxKind.SyntaxList && node.kind !== ts.SyntaxKind.SourceFile;
        if ( owns && ! ends.has( node.getEnd() ) ) {
            ends.add( node.getEnd() );
            add( ts.getTrailingCommentRanges( text, node.getEnd() ), true, node );
        }
        if ( owns && ! starts.has( node.getFullStart() ) ) {
            starts.add( node.getFullStart() );
            add( ts.getLeadingCommentRanges( text, node.getFullStart() ), false, node );
        }
        node.getChildren( sf ).forEach( visit );
    };
    visit( sf );
    return [ ...found.values() ].sort( ( a, b ) => a.pos - b.pos );
}

/**
 * Read the tags of one block comment that has no attached node, with a documented fallback.
 *
 * Requires:
 *   - text is the stripped text of a block comment
 *
 * Ensures:
 *   - returns [ { tag, type, name } ] for each line that starts with an at sign and a word
 *   - type is the text inside the braces after the tag, or null; name is the next word, or null
 */
function fallbackTags( text ) {
    return text.split( "\n" ).flatMap( ( line ) => {
        const match = /^\s*@(\w+)(?:\s+\{([^}]*)\})?(?:\s+([\w$.[\]]+))?/.exec( line );
        return match === null ? [] : [ { tag: match[ 1 ], type: match[ 2 ] ?? null, name: match[ 3 ] ?? null } ];
    } );
}

/**
 * Return the tags of one JSDoc block, from the compiler when the block is attached to a node.
 *
 * Requires:
 *   - range is { pos }, text is its stripped text, owner is the node it sits beside or undefined
 *
 * Ensures:
 *   - returns [ { tag, type, name } ] where type is the type expression text or null
 *   - the compiler's parsed tags are used when the owner carries this block, else the line fallback
 */
function tagsOf( sf, range, text, owner ) {
    const block = owner === undefined ? undefined : ( owner.jsDoc ?? [] ).find( ( doc ) => doc.pos === range.pos );
    if ( block === undefined ) return fallbackTags( text );
    return ( block.tags ?? [] ).map( ( tag ) => ( {
        tag  : tag.tagName.text,
        type : tag.typeExpression === undefined ? null : tag.typeExpression.getText( sf ).replace( /^\{|\}$/g, "" ).trim(),
        name : tag.name === undefined ? null : tag.name.getText( sf )
    } ) );
}

/**
 * Turn the collected ranges into comment records, merging runs and naming symbols.
 *
 * Requires:
 *   - ranges is the sorted result of collectRanges for sf
 *
 * Ensures:
 *   - returns records in source order with symbol_key, directive, commented_code and tags set
 *   - the first comment of the file that is not a directive gets the symbol_key <file-header>
 *     when only whitespace, a hashbang and directive comments come before it
 *   - other symbol_keys are Kind|Owner.member|ordinal, or null when the comment sits beside nothing
 *   - a directive comment has no symbol_key and takes no ordinal, so it never moves a pairing
 */
function buildRecords( sf, fileName, ranges ) {
    const text    = sf.text;
    const shebang = /^#!.*/.exec( text );
    const items   = [];
    let open      = undefined;
    for ( const range of ranges ) {
        const raw     = text.slice( range.pos, range.end );
        const line    = raw.startsWith( "//" );
        const body    = line ? lineBody( raw ) : blockBody( raw );
        const startLn = sf.getLineAndCharacterOfPosition( range.pos ).line + 1;
        const endLn   = sf.getLineAndCharacterOfPosition( range.end ).line + 1;
        const direct  = isDirective( raw, body );
        const jsdoc   = ! line && raw.startsWith( "/**" ) && raw !== "/**/";
        const kind    = range.trailing ? "trailing" : line ? "line-run" : jsdoc ? "jsdoc" : "block";
        if ( kind === "line-run" && ! direct && open !== undefined && open.end_line + 1 === startLn ) {
            open.text += "\n" + body;
            open.end_line = endLn;
            open.end = range.end;
            continue;
        }
        const item = { kind, jsdoc, file: fileName, text: body, start_line: startLn, end_line: endLn, directive: direct, pos: range.pos, end: range.end, range };
        items.push( item );
        open = kind === "line-run" && ! direct ? item : undefined;
    }
    const first  = items.findIndex( ( item ) => ! item.directive );
    const header = first !== -1 && items[ first ].kind !== "trailing" && onlyDirectivesBefore( text, shebang, items.slice( 0, first ), items[ first ].pos );
    const counts = new Map();
    return items.map( ( item, index ) => {
        let symbolKey = null;
        if ( header && index === first ) symbolKey = "<file-header>";
        else if ( ! item.directive && item.range.owner !== undefined ) {
            const key = `${KIND_NAMES.get( item.range.owner.kind )}|${symbolOf( item.range.owner )}`;
            counts.set( key, ( counts.get( key ) ?? 0 ) + 1 );
            symbolKey = `${key}|${counts.get( key )}`;
        }
        return {
            kind          : item.kind,
            file          : item.file,
            text          : item.text,
            start_line    : item.start_line,
            end_line      : item.end_line,
            symbol_key    : symbolKey,
            directive     : item.directive,
            commented_code: item.kind === "line-run" && ! item.directive && looksLikeCode( item.text ),
            tags          : item.jsdoc ? tagsOf( sf, item.range, item.text, item.range.owner ) : [],
            ts_version    : ts.version
        };
    } );
}

/**
 * Say whether only whitespace, a hashbang and directive comments sit before a position.
 *
 * Requires:
 *   - earlier holds the directive items that come before position, in source order
 */
function onlyDirectivesBefore( text, shebang, earlier, position ) {
    let cursor = shebang === null ? 0 : shebang[ 0 ].length;
    for ( const item of earlier ) {
        if ( text.slice( cursor, item.pos ).trim() !== "" ) return false;
        cursor = item.end;
    }
    return text.slice( cursor, position ).trim() === "";
}

/**
 * Extract the comments of one source text.
 *
 * Requires:
 *   - source is the text of a TypeScript or JavaScript file, fileName is its repo-relative path
 *
 * Ensures:
 *   - returns { file, comments }: the file record and the comment records in source order
 *   - a file that does not parse is read as far as the compiler recovers, and parse_errors lists why
 *   - a name ending in .js, .mjs or .cjs is read as JavaScript, anything else as TypeScript
 */
export function extractFile( source, fileName ) {
    const scriptKind = /\.[mc]?js$/.test( fileName ) ? ts.ScriptKind.JS : ts.ScriptKind.TS;
    const sf         = ts.createSourceFile( fileName, source, ts.ScriptTarget.Latest, true, scriptKind );
    const errors     = sf.parseDiagnostics.map( ( diag ) => ( {
        line   : sf.getLineAndCharacterOfPosition( diag.start ).line + 1,
        message: ts.flattenDiagnosticMessageText( diag.messageText, "\n" )
    } ) );
    return {
        file    : { kind: "file", file: fileName, ts_version: ts.version, parse_errors: errors },
        comments: buildRecords( sf, fileName, collectRanges( sf ) )
    };
}

/**
 * Run the extractor over the files named in argv and write JSON Lines to out.
 *
 * Requires:
 *   - argv is [ "--repo-root", DIR, FILE... ]
 *   - out and err have a write method; readFile takes a path and returns text
 *
 * Ensures:
 *   - returns 0 after writing a file record and the comment records for every file
 *   - a file that cannot be read gets a file record whose parse_errors holds the reason
 *   - returns 2 and writes a usage line to err when the root or the file list is missing, or an
 *     option is unknown
 */
export function main( argv, out, err, readFile = ( file ) => fs.readFileSync( file, "utf8" ) ) {
    let root     = ".";
    const files  = [];
    let bad      = false;
    for ( let i = 0; i < argv.length; i += 1 ) {
        if ( argv[ i ] === "--repo-root" ) {
            root = argv[ i + 1 ];
            i += 1;
        } else if ( argv[ i ].startsWith( "--" ) ) bad = true;
        else files.push( argv[ i ] );
    }
    if ( bad || root === undefined || files.length === 0 ) {
        err.write( "usage: ts_doc_extract.mjs --repo-root DIR FILE...\n" );
        return 2;
    }
    for ( const file of files ) {
        let result;
        try {
            result = extractFile( readFile( path.join( root, file ) ), file );
        } catch ( error ) {
            result = { file: { kind: "file", file, ts_version: ts.version, parse_errors: [ { line: 0, message: `cannot extract: ${error.message}` } ] }, comments: [] };
        }
        out.write( JSON.stringify( result.file ) + "\n" );
        result.comments.forEach( ( comment ) => out.write( JSON.stringify( comment ) + "\n" ) );
    }
    return 0;
}

if ( import.meta.url === pathToFileURL( path.resolve( process.argv[ 1 ] ?? "" ) ).href ) {
    process.exitCode = main( process.argv.slice( 2 ), process.stdout, process.stderr );
}
