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
 *   - tokens holds every leaf token outside a documentation comment, as line, kind, text and break
 *   - break is 1 when a line break, also one inside a comment, comes before the token
 *   - directives holds the body of each directive comment
 *   - marks holds each comment that a tool reads, with the index of the token after it
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

// Comments that a compiler, a linter, a bundler or a coverage tool reads. The start of the comment decides.
const READ_BY_TOOLS = new RegExp(
    "^(?:\\/\\/+|\\/\\*+)\\s*(?:@ts-|eslint|(?:c8|istanbul|v8)\\s+ignore|prettier-ignore|[#@]__(?:PURE|NO_SIDE_EFFECTS)__"
    + "|#?(?:end)?region\\b|\\/\\s*<|[#@]\\s*source(?:Mapping)?URL=|@license|@preserve|@vite-ignore|@flow|@noflow"
    + "|@jsx|@refresh|@vitest|@jest|@babel|webpack[A-Za-z]+\\s*:|tslint:|jshint|jscs|globals?\\s|exported\\b)"
);
const BANNER      = /^\/\*!/;
const DOC_WORDS   = /@(?:internal|import|license|preserve|ts-[a-z-]+)\b[^\n*]*/g;
const LINE_BREAK  = /[\n\r\u2028\u2029]/;

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
 * Name a comment that a tool reads, or say it is plain.
 *
 * Requires:
 *   - raw is the full text of one comment, with its delimiters
 *
 * Ensures:
 *   - returns the comment text for a banner or a directive comment
 *   - returns "doc:" and the tool-read words for a documentation block that has any
 *   - returns null for every other comment
 */
export function signature( raw ) {
    if ( BANNER.test( raw ) || READ_BY_TOOLS.test( raw ) ) return raw.trim();
    if ( raw.startsWith( "/**" ) ) {
        const words = raw.match( DOC_WORDS );
        if ( words !== null ) return "doc:" + words.map( ( word ) => word.trim() ).join( "|" );
    }
    return null;
}

/**
 * List the leaf tokens of a parsed file and the comments that tools read.
 *
 * Requires:
 *   - sf is a ts.SourceFile created with parent pointers
 *
 * Ensures:
 *   - returns { tokens, marks }
 *   - tokens is [ [ line, kind, text, break ] ] in source order, the end-of-file token left out
 *   - break is 1 when a line terminator lies between the previous token and this one, in a comment too
 *   - the first token has break 0, since nothing comes before it
 *   - marks is [ [ index, label ] ], the label starting with L for a comment on its own line and T after code
 *   - index is the number of tokens before the comment, so an end-of-file comment has the token count
 */
export function codeTokens( sf ) {
    const tokens = [];
    const marks  = [];
    const text   = sf.text;
    let previous = 0;
    const mark = ( ranges ) => {
        for ( const range of ranges ?? [] ) {
            const label = signature( text.slice( range.pos, range.end ) );
            if ( label === null ) continue;
            const lineStart = text.lastIndexOf( "\n", range.pos - 1 ) + 1;
            marks.push( [ tokens.length, ( /^[ \t]*$/.test( text.slice( lineStart, range.pos ) ) ? "L:" : "T:" ) + label ] );
        }
    };
    const walk = ( node ) => {
        if ( node.kind >= ts.SyntaxKind.FirstJSDocNode && node.kind <= ts.SyntaxKind.LastJSDocNode ) return;
        const children = node.getChildren( sf );
        if ( children.length > 0 ) {
            children.forEach( walk );
            return;
        }
        mark( ts.getLeadingCommentRanges( text, node.getFullStart() ) );
        if ( node.kind === ts.SyntaxKind.EndOfFileToken ) return;
        const start = node.getStart( sf );
        tokens.push( [
            sf.getLineAndCharacterOfPosition( start ).line + 1,
            node.kind,
            node.getText( sf ),
            tokens.length > 0 && LINE_BREAK.test( text.slice( previous, start ) ) ? 1 : 0
        ] );
        previous = node.getEnd();
        mark( ts.getTrailingCommentRanges( text, previous ) );
    };
    walk( sf );
    return { tokens, marks };
}

/**
 * Describe one text for the docs-only comparison.
 *
 * Requires:
 *   - source is the file text and name is its repo-relative path
 *
 * Ensures:
 *   - returns { errors, tokens, marks, directives, tags, shebang }
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
    const code  = codeTokens( sf );
    return {
        errors    : file.parse_errors,
        tokens    : code.tokens,
        marks     : code.marks,
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
            result = { errors: [ { line: 0, message: `cannot describe: ${error.message}` } ], tokens: [], marks: [], directives: [], tags: [], shebang: null };
        }
        out.write( JSON.stringify( { id: item.id, ...result } ) + "\n" );
    }
    return 0;
}

if ( import.meta.url === pathToFileURL( path.resolve( process.argv[ 1 ] ?? "" ) ).href ) {
    process.exitCode = run( fs.readFileSync( 0, "utf8" ), process.stdout, process.stderr );
}
