// Runs the script of Rick's gold page on a fake DOM; prints one JSON line.

/* Usage: node rick_page_question_driver.js <page.html>
   The line holds boxes (what the question box shows per item), drawn and grouped (the order button's label, then the
   item ids and type badges Next walks from the first item), next_open (where "Next unlabelled" lands in the grouped
   order once the first item is answered) and grouped_saved (whether the grouped choice is kept in the saved state). */
const fs   = require( "fs" );
const html = fs.readFileSync( process.argv[ 2 ], "utf8" );
const data = html.match( /<script type="application\/json" id="data">([\s\S]*?)<\/script>/ )[ 1 ];
const code = [ ...html.matchAll( /<script>([\s\S]*?)<\/script>/g ) ].map( m => m[ 1 ] ).join( "\n" );
const els  = {};
function el( id ) {
  if ( !els[ id ] ) els[ id ] = { id, style: {}, textContent: id === "data" ? data : "", className: "", value: "", files: [], children: [],
                                  appendChild( c ) { this.children.push( c ); }, addEventListener() {}, click() {}, select() {}, setSelectionRange() {} };
  return els[ id ];
}
global.document = { getElementById: el, createElement: () => el( "x" + Math.random() ), createTextNode: t => ( { t } ),
                    body: { appendChild() {}, removeChild() {} }, addEventListener() {}, execCommand() { return true; } };
global.window   = { localStorage: { getItem() { return null; }, setItem() {} }, scrollTo() {}, addEventListener() {} };
global.Blob     = function () {};
global.URL      = { createObjectURL() { return ""; }, revokeObjectURL() {} };
// the page script is strict, so its names live in this one eval's scope: hand out what the driver needs
eval( code + "\n;globalThis.page = { go: go, choose: choose, order: order, items: ITEMS, at: function () { return position; }, store: function () { return store; } };" );
const page = globalThis.page;
const id   = () => page.items[ page.at() ].item_id;

function walk() {   // from the first item of the current order, press Next until the position stops moving
  page.go( page.order()[ 0 ] );
  const ids = [], badges = [];
  for ( let n = 0; n < page.items.length; n++ ) {
    ids.push( id() );
    badges.push( els.cardtype.textContent );
    const before = page.at();
    els.next.onclick();
    if ( page.at() === before ) break;
  }
  return { label: els.grouping.textContent, ids, badges };
}

const boxes = page.items.map( ( item, i ) => {
  page.go( i );
  return { item_id: item.item_id, display: els.questionbox.style.display, text: els.question.textContent };
} );
const drawn = walk();
els.grouping.onclick();
const grouped = walk();
page.go( page.order()[ 0 ] );
page.choose( page.items[ page.at() ].relations[ 0 ].label );
els.nextopen.onclick();
console.log( JSON.stringify( { boxes, drawn, grouped, next_open: id(), grouped_saved: page.store().grouped } ) );
