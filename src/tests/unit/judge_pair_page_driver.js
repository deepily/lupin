// Runs the script of the forecast-pair page on a fake DOM; prints one JSON line.

/* Usage: node judge_pair_page_driver.js <page.html> <steps.json> [<saved-state.json>]
   Each step is [ name, argument... ]: go <index>, choose <field> <value>, note <text>, next, prev, nextopen,
   restore <text>, or view. A view appends what the page shows. The line holds views, export (the export lines),
   saved (the stored state) and key (the storage key). */
const fs    = require( "fs" );
const html  = fs.readFileSync( process.argv[ 2 ], "utf8" );
const steps = JSON.parse( fs.readFileSync( process.argv[ 3 ], "utf8" ) );
const data  = html.match( /<script type="application\/json" id="data">([\s\S]*?)<\/script>/ )[ 1 ];
const code  = [ ...html.matchAll( /<script>([\s\S]*?)<\/script>/g ) ].map( m => m[ 1 ] ).join( "\n" );
const els   = {};
function make( id ) {
  const el = { id, style: {}, className: "", value: "", files: [], children: [], disabled: false, text: id === "data" ? data : "",
               appendChild( c ) { this.children.push( c ); }, click() {}, focus() {}, select() {}, setSelectionRange() {} };
  Object.defineProperty( el, "textContent", { get() { return this.text; }, set( v ) { this.text = String( v ); this.children = []; } } );
  return el;
}
const el = id => els[ id ] || ( els[ id ] = make( id ) );
const storage = {};
let storageKey = null;
const preset = process.argv[ 4 ] ? fs.readFileSync( process.argv[ 4 ], "utf8" ) : null;
global.document = { getElementById: el, createElement: () => make( "new" ), body: { appendChild() {}, removeChild() {} } };
global.window   = { localStorage: { getItem( k ) { return k in storage ? storage[ k ] : preset; }, setItem( k, v ) { storageKey = k; storage[ k ] = v; } }, scrollTo() {} };
eval( code + "\n;globalThis.page = { go: go, choose: choose, lines: exportLines, restore: restoreText };" );
const page  = globalThis.page;
const views = [];
const buttons = id => el( id ).children.map( b => ( { text: b.textContent, chosen: b.className === "chosen", disabled: b.disabled } ) );
function view() {
  const shown = id => el( id ).textContent;
  views.push( { pos: shown( "pos" ), done: shown( "done" ), section: shown( "section" ), card: shown( "cardtext" ), answer: shown( "answer" ), forecast: shown( "forecast" ),
                options: el( "optionsbox" ).style.display, readersbox: el( "readersbox" ).style.display, readers: shown( "readers" ),
                choices: buttons( "choices" ), kinds: buttons( "kinds" ), note: el( "note" ).value, note_disabled: el( "note" ).disabled,
                restorestatus: shown( "restorestatus" ), exportstatus: shown( "exportstatus" ) } );
}
for ( const [ name, a, b ] of steps ) {
  if ( name === "go" ) page.go( a );
  else if ( name === "choose" ) page.choose( a, b );
  else if ( name === "note" ) { el( "note" ).value = a; el( "note" ).oninput(); }
  else if ( name === "restore" ) page.restore( a );
  else if ( name === "view" ) view();
  else el( name ).onclick();
}
console.log( JSON.stringify( { views, export: page.lines(), saved: JSON.parse( storage[ storageKey ] ), key: storageKey } ) );
