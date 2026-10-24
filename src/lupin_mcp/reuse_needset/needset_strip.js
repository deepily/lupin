// Strips member names for the need writer, or returns the raw member text.
//
// stdin  is JSON: { root, typescript, mode, targets }, where mode is "strip" or "text" and each target is
//        { file (relative to root), name ("Foo.bar"), line, module_parts }.
// stdout is JSON: { results: [ ... ] }, one entry per target in order: { ok, kind, text, forbidden, replaced }
//        on success and { ok: false, error } when the member cannot be found.
// A member is found by the line it starts on and the last part of its name, which is what the symbol index records.
// Mode "strip" replaces the member's name, its class, the module parts, its parameters and the names it reads off
// this, with the same placeholders the Python step uses (name, class, module, arg N and attr N, in capitals).
// Mode "text" returns the member unchanged.
const fs   = require( "fs" );
const path = require( "path" );

const req = JSON.parse( fs.readFileSync( 0, "utf8" ) );
const ts  = require( req.typescript );

const MIN_NAME_LEN = 3;

function scriptKind( abs ) {
    if ( abs.endsWith( ".tsx" ) ) return ts.ScriptKind.TSX;
    return abs.endsWith( ".ts" ) ? ts.ScriptKind.TS : ts.ScriptKind.JS;
}

function lineOf( node, sf ) {
    return sf.getLineAndCharacterOfPosition( node.getStart( sf ) ).line + 1;
}

// The name a declaration answers to, as the symbol index writes it.
function declName( node, sf ) {
    if ( ts.isConstructorDeclaration( node ) ) return "constructor";
    return node.name ? node.name.getText( sf ) : null;
}

function isTarget( node ) {
    if ( ts.isVariableDeclaration( node ) ) return !!node.initializer && ( ts.isArrowFunction( node.initializer ) || ts.isFunctionExpression( node.initializer ) );
    return ts.isFunctionDeclaration( node ) || ts.isClassDeclaration( node ) || ts.isMethodDeclaration( node ) ||
           ts.isConstructorDeclaration( node ) || ts.isGetAccessorDeclaration( node ) || ts.isSetAccessorDeclaration( node );
}

// The first declaration that starts on the target's line and carries the last part of its name.
function findNode( sf, target ) {
    const last = target.name.split( "." ).pop();
    let found  = null;
    const visit = ( node ) => {
        if ( found ) return;
        if ( isTarget( node ) && lineOf( node, sf ) === target.line && declName( node, sf ) === last ) { found = node; return; }
        ts.forEachChild( node, visit );
    };
    visit( sf );
    return found;
}

// The node whose text is the member: the whole statement for a const, so that "export const f = ..." stays together.
function spanNode( node ) {
    if ( ts.isVariableDeclaration( node ) && ts.isVariableDeclarationList( node.parent ) && ts.isVariableStatement( node.parent.parent ) ) return node.parent.parent;
    return node;
}

function indentOf( line ) {
    return line.length - line.trimStart().length;
}

// The member's text from its doc comment (or first token) to its end; lines after the first lose the indent they share.
function memberText( node, sf ) {
    const span  = spanNode( node );
    const docs  = ts.getJSDocCommentsAndTags( span ).filter( ts.isJSDoc );
    const from  = docs.length > 0 ? docs[ 0 ].getStart( sf ) : span.getStart( sf );
    const lines = sf.text.slice( from, span.getEnd() ).split( "\n" );
    const rest  = lines.slice( 1 ).filter( ( l ) => l.trim() !== "" ).map( indentOf );
    const cut   = rest.length > 0 ? Math.min( ...rest ) : 0;
    return lines.map( ( l, i ) => ( i === 0 ? l : l.slice( Math.min( cut, indentOf( l ) ) ) ) ).join( "\n" );
}

function bindingNames( name, acc ) {
    if ( ts.isIdentifier( name ) ) acc.push( name.text );
    else for ( const el of name.elements ) if ( ts.isBindingElement( el ) ) bindingNames( el.name, acc );
    return acc;
}

// The function-like nodes whose parameters count: the member itself, or every method of a class.
function paramOwners( node ) {
    const out = [];
    const visit = ( n ) => {
        if ( ts.isFunctionLike( n ) ) out.push( n );
        ts.forEachChild( n, visit );
    };
    if ( ts.isClassDeclaration( node ) ) visit( node ); else if ( ts.isVariableDeclaration( node ) ) out.push( node.initializer ); else out.push( node );
    return out;
}

function paramNames( node ) {
    const names = [];
    for ( const fn of paramOwners( node ) ) for ( const p of fn.parameters ) for ( const n of bindingNames( p.name, [] ) ) if ( !names.includes( n ) ) names.push( n );
    return names.filter( ( n ) => n !== "this" );
}

function attrNames( node ) {
    const names = [];
    const visit = ( n ) => {
        if ( ts.isPropertyAccessExpression( n ) && n.expression.kind === ts.SyntaxKind.ThisKeyword ) {
            const t = n.name.text;
            if ( !names.includes( t ) ) names.push( t );
        }
        ts.forEachChild( n, visit );
    };
    visit( node );
    return names;
}

function memberNames( node, sf ) {
    const names = [ declName( node, sf ) ];
    if ( ts.isClassDeclaration( node ) ) for ( const m of node.members ) if ( ts.isMethodDeclaration( m ) ) names.push( m.name.getText( sf ) );
    return names;
}

function escapeRe( s ) {
    return s.replace( /[.*+?^${}()|[\]\\]/g, "\\$&" );
}

function strip( node, sf, target, text ) {
    const parent = node.parent && ts.isClassDeclaration( node.parent ) ? node.parent : null;
    const repl   = new Map();
    const put    = ( name, placeholder ) => { if ( name && !repl.has( name ) ) repl.set( name, placeholder ); };
    if ( ts.isClassDeclaration( node ) ) put( declName( node, sf ), "CLASS" );
    for ( const n of memberNames( node, sf ) ) put( n, "NAME" );
    if ( parent ) put( declName( parent, sf ), "CLASS" );
    for ( const part of target.module_parts || [] ) put( part, "MODULE" );
    paramNames( node ).forEach( ( n, i ) => put( n, "ARG" + ( i + 1 ) ) );
    attrNames( node ).forEach( ( n, i ) => put( n, "ATTR" + ( i + 1 ) ) );
    for ( const name of [ ...repl.keys() ] ) if ( name.length < MIN_NAME_LEN || ( name.startsWith( "__" ) && name.endsWith( "__" ) ) ) repl.delete( name );
    const forbidden = [ ...repl.keys() ].sort( ( a, b ) => b.length - a.length || ( a < b ? -1 : 1 ) );
    if ( forbidden.length === 0 ) return { forbidden, replaced: {}, text };
    const re = new RegExp( "(?<![A-Za-z0-9_$])(" + forbidden.map( escapeRe ).join( "|" ) + ")(?![A-Za-z0-9_$])", "g" );
    return { forbidden, replaced: Object.fromEntries( repl ), text: text.replace( re, ( m ) => repl.get( m ) ) };
}

function kindOf( node ) {
    if ( ts.isClassDeclaration( node ) ) return "class";
    const owner = ts.isVariableDeclaration( node ) ? null : node.parent;
    return owner && ts.isClassDeclaration( owner ) ? "method" : "function";
}

const files   = new Map();
const results = req.targets.map( ( target ) => {
    const abs = path.join( req.root, target.file );
    if ( !files.has( abs ) ) {
        files.set( abs, fs.existsSync( abs ) ? ts.createSourceFile( abs, fs.readFileSync( abs, "utf8" ), ts.ScriptTarget.Latest, true, scriptKind( abs ) ) : null );
    }
    const sf = files.get( abs );
    if ( sf === null ) return { ok: false, error: "no such file: " + target.file };
    const node = findNode( sf, target );
    if ( node === null ) return { ok: false, error: "no member " + target.name + " starts on line " + target.line + " of " + target.file };
    const text = memberText( node, sf );
    if ( req.mode === "text" ) return { ok: true, kind: kindOf( node ), text };
    return Object.assign( { ok: true, kind: kindOf( node ) }, strip( node, sf, target, text ) );
} );
process.stdout.write( JSON.stringify( { results } ) );
