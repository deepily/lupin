/**
 * Print the code tokens of TypeScript and JavaScript texts and their code-like comments.
 *
 * The docs-only check for scripts compares two versions of a file with this output.
 * The compiler walks the parse tree. A double slash inside a string, a template literal or a
 * regular expression is therefore never taken for a comment.
 * The comment records come from ts_doc_extract.mjs.
 *
 * Usage: node ts_code_tokens.mjs < texts.json
 *
 * Input: a JSON list of objects with id, name and text.
 * Output: one JSON line per text, in order, holding these fields.
 *
 *   - id is the id of the input object
 *   - errors lists the parser's diagnostics, each with a line and a message
 *   - tokens holds every leaf token outside a documentation comment, as line, kind and text
 *   - directives holds the body of each directive comment
 *   - tags holds the tag and type of each typed documentation tag, for JavaScript files only
 *   - shebang is the first line when it is a hashbang, otherwise null
 *
 * The compiler reads typed documentation tags as type code in JavaScript files.
 */

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import { extractFile } from "./ts_doc_extract.mjs";

const TYPED_NAMES = new Set( [ "template", "typedef", "callback" ] );

/**
 * Say whether a file name is read as JavaScript.
 *
 * Requires:
 *   - name is a string
 *
 * Ensures:
 *   - true for a name ending in .js, .mjs or .cjs, false otherwise
 */
export function isJavaScript( name ) {
    return /\.[mc]?js$/.test( name );
}

/**
 * List the leaf tokens of a parsed file, skipping documentation comment nodes.
 *
 * Requires:
 *   - sf is a ts.SourceFile created with parent pointers
 *
 * Ensures:
 *   - returns [ [ line, kind, text ] ] in source order, the end-of-file token left out
 *   - comments are trivia, so no ordinary comment text appears
 */
export function codeTokens( sf ) {
    const tokens = [];
    const walk = ( node ) => {
        if ( node.kind >= ts.SyntaxKind.FirstJSDocNode && node.kind <= ts.SyntaxKind.LastJSDocNode ) return;
        const children = node.getChildren( sf );
        if ( children.length > 0 ) {
            children.forEach( walk );
            return;
        }
        if ( node.kind === ts.SyntaxKind.EndOfFileToken ) return;
        tokens.push( [ sf.getLineAndCharacterOfPosition( node.getStart( sf ) ).line + 1, node.kind, node.getText( sf ) ] );
    };
    walk( sf );
    return tokens;
}

/**
 * Describe one text for the docs-only comparison.
 *
 * Requires:
 *   - source is the file text and name is its repo-relative path
 *
 * Ensures:
 *   - returns { errors, tokens, directives, tags, shebang }
 *   - errors lists the parser's diagnostics, so a caller can refuse a file that did not parse
 *   - tags is empty for a name that is not JavaScript
 *   - shebang is the first line when it starts with a hash and a bang, otherwise null
 */
export function describe( source, name ) {
    const { file, comments } = extractFile( source, name );
    const kind    = isJavaScript( name ) ? ts.ScriptKind.JS : ts.ScriptKind.TS;
    const sf      = ts.createSourceFile( name, source, ts.ScriptTarget.Latest, true, kind );
    const tags    = [];
    if ( isJavaScript( name ) ) {
        for ( const comment of comments ) {
            for ( const tag of comment.tags ) {
                if ( tag.type ) tags.push( [ tag.tag, tag.type ] );
                else if ( TYPED_NAMES.has( tag.tag ) ) tags.push( [ tag.tag, tag.name ] );
            }
        }
    }
    const first = /^#!.*/.exec( source );
    return {
        errors    : file.parse_errors,
        tokens    : codeTokens( sf ),
        directives: comments.filter( ( comment ) => comment.directive ).map( ( comment ) => comment.text ),
        tags,
        shebang   : first === null ? null : first[ 0 ]
    };
}

/**
 * Read a JSON list of texts and write one description per text as JSON Lines.
 *
 * Requires:
 *   - input is the JSON text of a list of { id, name, text }
 *   - out and err have a write method
 *
 * Ensures:
 *   - returns 0 after writing one line per text, in order
 *   - a text that cannot be described gets a line with an error naming the reason
 *   - returns 2 and writes a usage line to err when the input is not a JSON list
 */
export function run( input, out, err ) {
    let items;
    try {
        items = JSON.parse( input );
    } catch {
        items = null;
    }
    if ( ! Array.isArray( items ) ) {
        err.write( "usage: ts_code_tokens.mjs < texts.json, a JSON list of { id, name, text }\n" );
        return 2;
    }
    for ( const item of items ) {
        let result;
        try {
            result = describe( item.text, item.name );
        } catch ( error ) {
            result = { errors: [ { line: 0, message: `cannot describe: ${error.message}` } ], tokens: [], directives: [], tags: [], shebang: null };
        }
        out.write( JSON.stringify( { id: item.id, ...result } ) + "\n" );
    }
    return 0;
}

if ( import.meta.url === pathToFileURL( path.resolve( process.argv[ 1 ] ?? "" ) ).href ) {
    process.exitCode = run( fs.readFileSync( 0, "utf8" ), process.stdout, process.stderr );
}
