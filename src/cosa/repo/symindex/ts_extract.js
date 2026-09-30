// Extract function/class/method definitions from JS/TS files with the TypeScript compiler.
// stdin : JSON { "root": "<abs dir>", "files": [ "<abs path>", ... ], "typescript": "<path to typescript module>" }
// stdout: JSON [ { file, name, kind, sig, doc, pin, line } ... ]   (file relative to root)
// A pin hashes the node's leaf tokens joined by one space, so comments and whitespace never change it.
const fs     = require( "fs" );
const path   = require( "path" );
const crypto = require( "crypto" );

const req = JSON.parse( fs.readFileSync( 0, "utf8" ) );
const ts  = require( req.typescript );


function firstDocLine( node, sf ) {
    const docs = ts.getJSDocCommentsAndTags( node ).filter( ts.isJSDoc );
    if ( docs.length === 0 ) return "";
    const text = ts.getTextOfJSDocComment( docs[ docs.length - 1 ].comment ) || "";
    const line = text.split( "\n" ).map( s => s.trim() ).find( s => s.length > 0 );
    return line || "";
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
    const mods = ts.canHaveModifiers( member ) ? ts.getModifiers( member ) || [] : [];
    if ( mods.some( m => m.kind === ts.SyntaxKind.PrivateKeyword || m.kind === ts.SyntaxKind.ProtectedKeyword ) ) return true;
    return member.name && ts.isPrivateIdentifier( member.name );
}

const out = [];

function emit( file, name, kind, sig, node, sf, docNode ) {
    const pos = sf.getLineAndCharacterOfPosition( node.getStart( sf ) );
    out.push( { file, name, kind, sig, doc: firstDocLine( docNode || node, sf ), pin: pinOf( node, sf ), line: pos.line + 1 } );
}

for ( const abs of req.files ) {
    const rel  = path.relative( req.root, abs ).split( path.sep ).join( "/" );
    const kind = abs.endsWith( ".ts" ) || abs.endsWith( ".tsx" ) ? ts.ScriptKind.TS : ts.ScriptKind.JS;
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
process.stdout.write( JSON.stringify( out ) );
