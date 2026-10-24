// Extract function/class/method definitions from JS/TS files with the TypeScript compiler.
// stdin : JSON { "root": "<abs dir>", "files": [ "<abs path>", ... ], "typescript": "<path to typescript module>" }
// stdout: JSON [ { file, name, kind, sig, doc, doc_full, pin, line, end_line, public } ... ]   (file relative to root)
// A private, protected or #private class member is reported with "public": false; every other definition is public.
// "doc_limit" and "doc_marker" in the request say how long doc_full may be and what ends a cut one (the Python side owns both values).
// With "mode": "shapes" in the request the output is instead { scanned: [ file ... ], skipped: [ file ... ], defs: [ { file, name, kinds } ... ] }:
// one entry per function-like definition at any depth, private and nested included ("public_only": true drops both),
// kinds being the pre-order node kind names of its body with names, literal values and access modifiers erased, for the duplicate finder.
// With "bodies": true as well, each entry of defs also carries line, end_line, sig, text, calls, declared and public, and each entry of scanned is
// { file, function_like_total, anonymous_walked }: function_like_total is counted by a separate walk over every node, so reported + anonymous_walked
// can be checked against it. Without the flag the output is exactly what it was. The account holds only when "public_only" is off.
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

// The whole JSDoc of a node: description and tags, whitespace folded to single spaces, cut to the requested length.
function fullDoc( node, sf ) {
    const docs = ts.getJSDocCommentsAndTags( node ).filter( ts.isJSDoc );
    if ( docs.length === 0 ) return "";
    const jsdoc = docs[ docs.length - 1 ];
    const tag   = t => [ "@" + t.tagName.text, t.name ? t.name.getText( sf ) : "", ts.getTextOfJSDocComment( t.comment ) || "" ].filter( x => x.length > 0 ).join( " " );
    const text  = [ ts.getTextOfJSDocComment( jsdoc.comment ) || "" ].concat( ( jsdoc.tags || [] ).map( tag ) ).join( " " ).replace( /\s+/g, " " ).trim();
    const chars = Array.from( text );                                    // code points, as Python counts them
    return chars.length > req.doc_limit ? chars.slice( 0, req.doc_limit ).join( "" ) + req.doc_marker : text;
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
    return !!( member.name && ts.isPrivateIdentifier( member.name ) );
}

// The one rule for a function that is hidden from the public listing: a private or protected method, constructor or accessor,
// or a function held in a private or protected class property. The symbol pass and the shapes pass both ask it.
function isHiddenFn( n ) {
    const field = ts.isPropertyDeclaration( n.parent );
    const member = ts.isMethodDeclaration( n ) || ts.isConstructorDeclaration( n ) || ts.isGetAccessorDeclaration( n ) || ts.isSetAccessorDeclaration( n ) || field;
    return member && isPrivate( field ? n.parent : n );
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

const MAX_CALLS = 50;

// Every function-like node of a file, anonymous and nested included, counted without using the definition walk.
function countFnLike( node ) {
    let total = isFnLike( node ) ? 1 : 0;
    ts.forEachChild( node, c => { total += countFnLike( c ); } );
    return total;
}

// The name a call goes by: the identifier called, or the member name of a.b(); anything else (a[0](), f()()) has none.
function calleeName( call ) {
    const e = call.expression;
    if ( ts.isIdentifier( e ) ) return e.text;
    return ts.isPropertyAccessExpression( e ) ? e.name.text : null;
}

// The distinct callee names inside a function, in order of first appearance, at most MAX_CALLS.
function callsOf( fn ) {
    const seen = new Set();
    const visit = n => {
        if ( ts.isCallExpression( n ) || ts.isNewExpression( n ) ) {
            const name = calleeName( n );
            if ( name !== null && seen.size < MAX_CALLS ) seen.add( name );
        }
        ts.forEachChild( n, visit );
    };
    ts.forEachChild( fn, visit );
    return [ ...seen ];
}

// The names bound by a parameter or variable name, which may be a destructuring pattern.
function bindingNames( name, acc ) {
    if ( ts.isIdentifier( name ) ) acc.push( name.text );
    else for ( const el of name.elements ) if ( ts.isBindingElement( el ) ) bindingNames( el.name, acc );
    return acc;
}

// The parameter, variable and property names declared inside a function, not its own name, in order of first appearance.
function declaredIn( fn ) {
    const acc = [];
    const visit = n => {
        if ( ts.isParameter( n ) || ts.isVariableDeclaration( n ) ) bindingNames( n.name, acc );
        else if ( ( ts.isPropertyAssignment( n ) || ts.isShorthandPropertyAssignment( n ) || ts.isPropertyDeclaration( n ) || ts.isMethodDeclaration( n ) ) &&
                  ( ts.isIdentifier( n.name ) || ts.isPrivateIdentifier( n.name ) ) ) acc.push( n.name.text );
        ts.forEachChild( n, visit );
    };
    ts.forEachChild( fn, visit );
    return [ ...new Set( acc ) ];
}

// The source of a function without the indentation of the line it starts on, so the same body reads the same in a class and at the top of a file.
function dedentedText( fn, sf ) {
    const start  = fn.getStart( sf );
    const line   = sf.getLineAndCharacterOfPosition( start ).line;
    const indent = /^[ \t]*/.exec( sf.text.slice( sf.getPositionOfLineAndCharacter( line, 0 ), start ) )[ 0 ];
    const [ first, ...rest ] = fn.getText( sf ).split( "\n" );
    return [ first, ...rest.map( l => indent !== "" && l.startsWith( indent ) ? l.slice( indent.length ) : l ) ].join( "\n" );
}

// The fields a "bodies" request adds to a definition.
function bodiesOf( fn, sf, isPublic ) {
    return { line: sf.getLineAndCharacterOfPosition( fn.getStart( sf ) ).line + 1, end_line: sf.getLineAndCharacterOfPosition( fn.getEnd() ).line + 1,
             sig: params( fn, sf ), text: dedentedText( fn, sf ), calls: callsOf( fn ), declared: declaredIn( fn ), public: isPublic };
}

function shapes( req ) {
    const defs = [], scanned = [], skipped = [];
    for ( const abs of req.files ) {
        const rel  = path.relative( req.root, abs ).split( path.sep ).join( "/" );
        const kind = scriptKind( abs );
        const sf   = ts.createSourceFile( abs, fs.readFileSync( abs, "utf8" ), ts.ScriptTarget.Latest, true, kind );
        // A file the parser reported errors for is skipped whole, as the Python pass skips a file that does not parse.
        if ( sf.parseDiagnostics.length > 0 ) { skipped.push( rel ); continue; }
        const account = req.bodies ? { file: rel, function_like_total: countFnLike( sf ), anonymous_walked: 0 } : null;
        scanned.push( req.bodies ? account : rel );
        const walk = ( node, prefix, nested ) => {
            ts.forEachChild( node, c => {
                if ( ts.isClassDeclaration( c ) || ts.isClassExpression( c ) ) {
                    if ( !c.name ) { walk( c, prefix, nested ); return; }
                    walk( c, prefix.concat( [ c.name.text ] ), nested );
                } else if ( isFnLike( c ) ) {
                    const name = fnName( c, sf );
                    // A function that is the value of a class property is as private as the property.
                    const hidden = isHiddenFn( c );
                    const skip = req.public_only && ( nested || hidden );
                    if ( name === null && req.bodies ) account.anonymous_walked++;
                    if ( name !== null && !skip ) {
                        const entry = { file: rel, name: prefix.concat( [ name ] ).join( "." ), kinds: preorder( c, [] ) };
                        defs.push( req.bodies ? Object.assign( entry, bodiesOf( c, sf, !( nested || hidden ) ) ) : entry );
                    }
                    walk( c, name === null ? prefix : prefix.concat( [ name, "<locals>" ] ), true );
                } else walk( c, prefix, nested );
            } );
        };
        walk( sf, [], false );
    }
    return { scanned, skipped, defs };
}

const out = [];

function emit( file, name, kind, sig, node, sf, docNode, isPublic = true ) {
    const pos = sf.getLineAndCharacterOfPosition( node.getStart( sf ) );
    const end = sf.getLineAndCharacterOfPosition( node.getEnd() );
    out.push( { file, name, kind, sig, doc: firstDocLine( docNode || node, sf ), doc_full: fullDoc( docNode || node, sf ), pin: pinOf( node, sf ),
                line: pos.line + 1, end_line: end.line + 1, public: isPublic } );
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
                if ( ts.isMethodDeclaration( m ) || ts.isConstructorDeclaration( m ) || ts.isGetAccessorDeclaration( m ) || ts.isSetAccessorDeclaration( m ) ) {
                    const mname = ts.isConstructorDeclaration( m ) ? "constructor" : m.name.getText( sf );
                    emit( rel, st.name.text + "." + mname, "method", params( m, sf ), m, sf, null, !isHiddenFn( m ) );
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
