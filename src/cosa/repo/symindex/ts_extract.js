// Extract function/class/method definitions from JS/TS files with the TypeScript compiler.
// stdin : JSON { "root": "<abs dir>", "files": [ "<abs path>", ... ], "typescript": "<path to typescript module>" }
// stdout: JSON [ { file, name, kind, sig, doc, pin, line } ... ]   (file relative to root)
// With "mode": "shapes" in the request the output is instead { scanned: [ file ... ], skipped: [ file ... ], defs: [ { file, name, kinds } ... ] }:
// one entry per function-like definition at any depth, private and nested included ("public_only": true drops both),
// kinds being the pre-order node kind names of its body with names, literal values and access modifiers erased, for the duplicate finder.
// A pin hashes the node's leaf tokens joined by one space, so comments and whitespace never change it.
const fs     = require( "fs" );
const path   = require( "path" );
const crypto = require( "crypto" );

const req = JSON.parse( fs.readFileSync( 0, "utf8" ) );
const ts  = require( req.typescript );

// The shared table, so this script and ts_doc_extract.mjs name a kind the same way.
const KIND_NAMES = require( path.join( __dirname, "ts_kind_names.cjs" ) )( ts );


// The one place a file's extension picks its parse mode. .tsx must be read as TSX, or its markup is a syntax error.
function scriptKind( abs ) {
    if ( abs.endsWith( ".tsx" ) ) return ts.ScriptKind.TSX;
    return abs.endsWith( ".ts" ) ? ts.ScriptKind.TS : ts.ScriptKind.JS;
}

function firstDocLine( node, sf ) {
    const docs = ts.getJSDocCommentsAndTags( node ).filter( ts.isJSDoc );
    if ( docs.length === 0 ) return "";
    const text = ts.getTextOfJSDocComment( docs[ docs.length - 1 ].comment ) || "";
    const lines = text.split( "\n" ).map( s => s.trim() ).filter( s => s.length > 0 );
    return lines.length > 0 ? lines[ 0 ] : "";
}

function leafTokens( node, sf, acc ) {
    if ( node.kind >= ts.SyntaxKind.FirstJSDocNode && node.kind <= ts.SyntaxKind.LastJSDocNode ) return acc;
    const kids = node.getChildren( sf );
    if ( kids.length === 0 ) { acc.push( node.getText( sf ) ); return acc; }
    for ( const k of kids ) leafTokens( k, sf, acc );
    return acc;
}

function pinOf( node, sf ) {
    const text = leafTokens( node, sf, [] ).join( " " );
    return crypto.createHash( "sha1" ).update( text ).digest( "hex" ).slice( 0, 10 );
}

function params( node, sf ) {
    const tp = node.typeParameters ? "<" + node.typeParameters.map( t => t.getText( sf ) ).join( ", " ) + ">" : "";
    const ps = node.parameters.map( p => p.getText( sf ).replace( /\s+/g, " " ) ).join( ", " );
    const rt = node.type ? ": " + node.type.getText( sf ).replace( /\s+/g, " " ) : "";
    return tp + "(" + ps + ")" + rt;
}

function isPrivate( member ) {
    const mods = ts.getModifiers( member ) || [];
    if ( mods.some( m => m.kind === ts.SyntaxKind.PrivateKeyword || m.kind === ts.SyntaxKind.ProtectedKeyword ) ) return true;
    return member.name && ts.isPrivateIdentifier( member.name );
}


// Compared by numeric kind: the reverse enum lookup answers an alias such as FirstLiteralToken for NumericLiteral.
const LITERALS = new Set( [ ts.SyntaxKind.NumericLiteral, ts.SyntaxKind.StringLiteral, ts.SyntaxKind.BigIntLiteral,
                            ts.SyntaxKind.NoSubstitutionTemplateLiteral, ts.SyntaxKind.RegularExpressionLiteral ] );

function kindName( n ) {
    if ( n.kind === ts.SyntaxKind.PrivateIdentifier ) return "Identifier";
    return LITERALS.has( n.kind ) ? "Literal" : KIND_NAMES.get( n.kind );
}

function preorder( node, acc ) {
    acc.push( kindName( node ) );
    ts.forEachChild( node, c => { if ( !ts.isJSDoc( c ) && !ts.isModifier( c ) ) preorder( c, acc ); } );
    return acc;
}

function isFnLike( n ) {
    return ts.isFunctionDeclaration( n ) || ts.isMethodDeclaration( n ) || ts.isConstructorDeclaration( n ) ||
           ts.isGetAccessorDeclaration( n ) || ts.isSetAccessorDeclaration( n ) || ts.isArrowFunction( n ) || ts.isFunctionExpression( n );
}

// The name a function-like node answers to, or null when it is an anonymous callback (still walked, never reported).
function fnName( n, sf ) {
    if ( ts.isConstructorDeclaration( n ) ) return "constructor";
    if ( n.name ) return n.name.getText( sf );
    const p = n.parent;
    if ( ts.isVariableDeclaration( p ) || ts.isPropertyAssignment( p ) || ts.isPropertyDeclaration( p ) ) return p.name.getText( sf );
    return null;
}

function shapes( req ) {
    const defs = [], scanned = [], skipped = [];
    for ( const abs of req.files ) {
        const rel  = path.relative( req.root, abs ).split( path.sep ).join( "/" );
        const kind = scriptKind( abs );
        const sf   = ts.createSourceFile( abs, fs.readFileSync( abs, "utf8" ), ts.ScriptTarget.Latest, true, kind );
        // A file the parser reported errors for is skipped whole, as the Python pass skips a file that does not parse.
        if ( sf.parseDiagnostics.length > 0 ) { skipped.push( rel ); continue; }
        scanned.push( rel );
        const walk = ( node, prefix, nested ) => {
            ts.forEachChild( node, c => {
                if ( ts.isClassDeclaration( c ) || ts.isClassExpression( c ) ) {
                    if ( !c.name ) { walk( c, prefix, nested ); return; }
                    walk( c, prefix.concat( [ c.name.text ] ), nested );
                } else if ( isFnLike( c ) ) {
                    const name = fnName( c, sf );
                    // A function that is the value of a class property is as private as the property.
                    const field  = ts.isPropertyDeclaration( c.parent );
                    const hidden = ( ts.isMethodDeclaration( c ) || ts.isConstructorDeclaration( c ) || ts.isGetAccessorDeclaration( c ) || ts.isSetAccessorDeclaration( c ) || field ) && isPrivate( field ? c.parent : c );
                    const skip = req.public_only && ( nested || hidden );
                    if ( name !== null && !skip ) defs.push( { file: rel, name: prefix.concat( [ name ] ).join( "." ), kinds: preorder( c, [] ) } );
                    walk( c, name === null ? prefix : prefix.concat( [ name, "<locals>" ] ), true );
                } else walk( c, prefix, nested );
            } );
        };
        walk( sf, [], false );
    }
    return { scanned, skipped, defs };
}

const out = [];

function emit( file, name, kind, sig, node, sf, docNode ) {
    const pos = sf.getLineAndCharacterOfPosition( node.getStart( sf ) );
    out.push( { file, name, kind, sig, doc: firstDocLine( docNode || node, sf ), pin: pinOf( node, sf ), line: pos.line + 1 } );
}

for ( const abs of req.mode === "shapes" ? [] : req.files ) {
    const rel  = path.relative( req.root, abs ).split( path.sep ).join( "/" );
    const kind = scriptKind( abs );
    const sf   = ts.createSourceFile( abs, fs.readFileSync( abs, "utf8" ), ts.ScriptTarget.Latest, true, kind );
    for ( const st of sf.statements ) {
        if ( ts.isFunctionDeclaration( st ) && st.name ) {
            emit( rel, st.name.text, "function", params( st, sf ), st, sf );
        } else if ( ts.isClassDeclaration( st ) && st.name ) {
            emit( rel, st.name.text, "class", "", st, sf );
            for ( const m of st.members ) {
                if ( ( ts.isMethodDeclaration( m ) || ts.isConstructorDeclaration( m ) || ts.isGetAccessorDeclaration( m ) || ts.isSetAccessorDeclaration( m ) ) && !isPrivate( m ) ) {
                    const mname = ts.isConstructorDeclaration( m ) ? "constructor" : m.name.getText( sf );
                    emit( rel, st.name.text + "." + mname, "method", params( m, sf ), m, sf );
                }
            }
        } else if ( ts.isVariableStatement( st ) ) {
            for ( const d of st.declarationList.declarations ) {
                if ( ts.isIdentifier( d.name ) && d.initializer &&
                     ( ts.isArrowFunction( d.initializer ) || ts.isFunctionExpression( d.initializer ) ) ) {
                    emit( rel, d.name.text, "function", d.type ? ": " + d.type.getText( sf ).replace( /\s+/g, " " ) : params( d.initializer, sf ), d, sf, st );
                }
            }
        }
    }
}
process.stdout.write( JSON.stringify( req.mode === "shapes" ? shapes( req ) : out ) );
