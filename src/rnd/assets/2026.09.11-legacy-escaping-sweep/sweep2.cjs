// Sweep v2: every ${expr} inside an HTML-bearing template literal in notifications.js,
// with identifiers resolved to their declaration in the enclosing function scope.
// Output: TSV line \t kind \t detail \t code, plus a summary.
const fs    = require( "fs" );
const acorn = require( "/mnt/DATA01/include/www.deepily.ai/projects/lupin/node_modules/acorn" );

const path = process.argv[ 2 ];
const src  = fs.readFileSync( path, "utf8" );
const ast  = acorn.parse( src, { ecmaVersion: "latest", sourceType: "script", locations: true } );

const SAFE_CALL = /^(this\.|self\.|ui\.)?(escapeHtml|escapeAttr|_escapeHtml|renderMarkdown|encodeURIComponent|sanitize\w*|DOMPurify\.sanitize)$/;
const code = n => src.slice( n.start, n.end ).replace( /\s+/g, " " );

// Parent links
( function link( n, parent ) {
    if ( !n || typeof n.type !== "string" ) return;
    Object.defineProperty( n, "parent", { value: parent, enumerable: false } );
    for ( const k of Object.keys( n ) ) {
        if ( k === "loc" ) continue;
        const v = n[ k ];
        if ( Array.isArray( v ) ) v.forEach( c => link( c, n ) );
        else if ( v && typeof v.type === "string" ) link( v, n );
    }
} )( ast, null );

const isFn = n => /Function/.test( n.type );

function enclosingFn( n ) {
    for ( let p = n.parent; p; p = p.parent ) if ( isFn( p ) ) return p;
    return null;
}

function* walk( n ) {
    if ( !n || typeof n.type !== "string" ) return;
    yield n;
    for ( const k of Object.keys( n ) ) {
        if ( k === "loc" ) continue;
        const v = n[ k ];
        if ( Array.isArray( v ) ) for ( const c of v ) yield* walk( c );
        else if ( v && typeof v.type === "string" ) yield* walk( v );
    }
}

// Find the binding for `name` visible at `use`: params of enclosing functions, or
// declarators / assignments inside the enclosing function that start before the use.
function resolve( name, use ) {
    for ( let fn = enclosingFn( use ); fn; fn = enclosingFn( fn ) ) {
        for ( const p of fn.params ) {
            for ( const n of walk( p ) ) if ( n.type === "Identifier" && n.name === name ) return { how: "param", fn, node: p };
        }
        const inits = [];
        for ( const n of walk( fn.body ) ) {
            if ( n.start >= use.start ) continue;
            if ( n.type === "VariableDeclarator" ) {
                if ( n.id.type === "Identifier" && n.id.name === name ) inits.push( { how: "decl", node: n.init } );
                else if ( n.id.type !== "Identifier" ) {
                    for ( const m of walk( n.id ) ) if ( m.type === "Identifier" && m.name === name ) inits.push( { how: "destructure", node: n.init } );
                }
            }
            if ( n.type === "AssignmentExpression" && n.left.type === "Identifier" && n.left.name === name ) {
                inits.push( { how: n.operator === "+=" ? "append" : "assign", node: n.right } );
            }
            if ( ( n.type === "ForOfStatement" || n.type === "ForInStatement" ) ) {
                for ( const m of walk( n.left ) ) if ( m.type === "Identifier" && m.name === name ) inits.push( { how: "loopvar", node: n.right } );
            }
        }
        if ( inits.length ) return { how: "local", inits };
    }
    return { how: "unresolved" };
}

function shape( e ) {
    if ( !e ) return "undefined-init";
    if ( e.type === "CallExpression" ) return SAFE_CALL.test( code( e.callee ) ) ? "escaped" : "call:" + code( e.callee ).slice( 0, 60 );
    if ( e.type === "Literal" ) return "literal";
    if ( e.type === "TemplateLiteral" ) return e.expressions.length ? "template" : "literal";
    if ( e.type === "ConditionalExpression" ) {
        const a = shape( e.consequent ), b = shape( e.alternate );
        return ( [ "literal", "template", "escaped" ].includes( a ) && [ "literal", "template", "escaped" ].includes( b ) ) ? "cond-safe-branches" : `cond(${a}|${b})`;
    }
    if ( e.type === "BinaryExpression" && /[-*\/%]/.test( e.operator ) ) return "arith";
    if ( e.type === "BinaryExpression" ) return `binary(${shape( e.left )}${e.operator}${shape( e.right )})`;
    if ( e.type === "LogicalExpression" ) return `logical(${shape( e.left )}${e.operator}${shape( e.right )})`;
    if ( e.type === "Identifier" ) return "ident";
    if ( e.type === "MemberExpression" ) return "member";
    if ( e.type === "UnaryExpression" ) return "unary";
    if ( e.type === "ArrayExpression" ) return "array";
    return e.type;
}

const rows = [];
for ( const node of walk( ast ) ) {
    if ( node.type !== "TemplateLiteral" ) continue;
    const text = node.quasis.map( q => q.value.raw ).join( "" );
    if ( !/<[a-zA-Z\/]/.test( text ) ) continue;
    for ( const e of node.expressions ) {
        let kind = shape( e ), detail = "";
        if ( e.type === "Identifier" ) {
            const r = resolve( e.name, e );
            if ( r.how === "param" ) { kind = "ident:param"; detail = code( r.fn ).slice( 0, 0 ) + ( r.fn.parent && r.fn.parent.type === "MethodDefinition" ? "method " + code( r.fn.parent.key ) : "fn@" + r.fn.loc.start.line ); }
            else if ( r.how === "local" ) {
                const shapes = [ ...new Set( r.inits.map( i => i.how + ":" + shape( i.node ) ) ) ];
                kind   = "ident:local";
                detail = shapes.join( " ; " ).slice( 0, 160 );
            }
            else kind = "ident:unresolved";
        }
        rows.push( { line: e.loc.start.line, kind, detail, code: code( e ).slice( 0, 90 ) } );
    }
}

const counts = {};
rows.forEach( r => { const k = r.kind.startsWith( "call:" ) ? "call(other)" : r.kind; counts[ k ] = ( counts[ k ] || 0 ) + 1; } );
console.log( "TOTAL", rows.length );
console.log( JSON.stringify( counts, null, 1 ) );
fs.writeFileSync( process.argv[ 3 ], rows.map( r => `${r.line}\t${r.kind}\t${r.detail}\t${r.code}` ).join( "\n" ) + "\n" );
