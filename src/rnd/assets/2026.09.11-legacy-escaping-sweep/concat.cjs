const fs = require( "fs" ), acorn = require( "/mnt/DATA01/include/www.deepily.ai/projects/lupin/node_modules/acorn" );
const src = fs.readFileSync( process.argv[ 2 ], "utf8" );
const ast = acorn.parse( src, { ecmaVersion: "latest", locations: true } );
const code = n => src.slice( n.start, n.end ).replace( /\s+/g, " " );
function* walk( n ) { if ( !n || typeof n.type !== "string" ) return; yield n; for ( const k of Object.keys( n ) ) { if ( k === "loc" ) continue; const v = n[ k ]; if ( Array.isArray( v ) ) for ( const c of v ) yield* walk( c ); else if ( v && typeof v.type === "string" ) yield* walk( v ); } }
const tagLit = n => n && ( ( n.type === "Literal" && typeof n.value === "string" && /<[a-zA-Z\/]/.test( n.value ) ) || ( n.type === "TemplateLiteral" && /<[a-zA-Z\/]/.test( n.quasis.map( q => q.value.raw ).join( "" ) ) ) );
let n = 0; const seen = new Set();
const flat = b => ( b.type === "BinaryExpression" && b.operator === "+" ) ? [ ...flat( b.left ), ...flat( b.right ) ] : [ b ];
for ( const b of walk( ast ) ) {
  if ( b.type !== "BinaryExpression" || b.operator !== "+" ) continue;
  if ( b.parent_is_plus ) continue;
  const ops = flat( b );
  if ( !ops.some( tagLit ) ) continue;
  for ( const s of ops ) {
    if ( s.type === "Literal" || s.type === "TemplateLiteral" ) continue;
    if ( seen.has( s.start ) ) continue; seen.add( s.start ); n++;
    console.log( `${s.loc.start.line}\t${code( s ).slice( 0, 100 )}` );
  }
}
console.error( "concat operands next to an HTML literal:", n );
