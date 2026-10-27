// Runs the inline script of pair-labelling.html on a fake DOM and API; prints one JSON line.
const fs = require( "fs" );
const html = fs.readFileSync( process.argv[ 2 ], "utf8" );
const script = html.split( "<script>" )[ 1 ].split( "</script>" )[ 0 ];
const els = {}, listeners = {};
const mk = id => els[ id ] || ( els[ id ] = { id, textContent: "", className: "", value: "", checked: false, disabled: false, style: {}, scrollTop: 0, addEventListener: ( ev, fn ) => { listeners[ id + ":" + ev ] = fn; } } );
const docListeners = {};
const labels = {}, pairs = [ 0, 1, 2, 3 ];
const calls = [];
const state = () => { const n = Object.keys( labels ).length; const r = pairs.find( p => !( p in labels ) ); return { total: 4, labelled: n, unsure: 0, resume: r === undefined ? null : r }; };
global.document = { getElementById: mk, addEventListener: ( ev, fn ) => { docListeners[ ev ] = fn; } };
global.window = { location: { search: "?reviewer=rick" } };
global.localStorage = { getItem: () => null, setItem: () => {} };
global.fetch = async ( url, init ) => {
    calls.push( ( init && init.method || "GET" ) + " " + url );
    const ok = body => ( { ok: true, status: 200, json: async () => body } );
    if ( url.includes( "/state" ) ) return ok( state() );
    if ( url.includes( "/item" ) ) { const p = +url.split( "position=" )[ 1 ]; return ok( { item_id: "id" + p, a: "a" + p, b: "b" + p, position: p, total: 4, labelled: Object.keys( labels ).length, label: labels[ p ] || null } ); }
    const b = JSON.parse( init.body ); labels[ +b.item_id.slice( 2 ) ] = { same_job: b.same_job, unsure: b.unsure, note: b.note };
    return ok( state() );
};
const tick = () => new Promise( r => setTimeout( r, 20 ) );
( async () => {
    new Function( "URLSearchParams", "document", "window", "localStorage", "fetch", "return (async()=>{" + script.trim().replace( /^\( async function\(\) \{/, "" ).replace( /\} \)\(\);$/, "" ) + "})()" )( URLSearchParams, document, window, localStorage, fetch );
    await tick();
    const out = { start: els.progress.textContent };
    listeners[ "yes:click" ](); await tick();
    out.after_yes = { progress: els.progress.textContent, status: els.status.textContent, a: els[ "text-a" ].textContent, yes: els.yes.className, marker: els.marker.textContent };
    listeners[ "no:click" ](); await tick();                         // change of mind on the same pair
    out.after_change = { progress: els.progress.textContent, status: els.status.textContent, a: els[ "text-a" ].textContent, yes: els.yes.className, no: els.no.className };
    listeners[ "next:click" ](); await tick(); out.next = els[ "text-a" ].textContent;
    listeners[ "prev:click" ](); await tick(); out.prev = { a: els[ "text-a" ].textContent, status: els.status.textContent };
    docListeners.keydown( { target: { tagName: "BODY" }, key: "ArrowRight" } ); await tick(); out.arrow_right = els[ "text-a" ].textContent;
    docListeners.keydown( { target: { tagName: "BODY" }, key: "ArrowLeft" } ); await tick(); out.arrow_left = els[ "text-a" ].textContent;
    listeners[ "resume:click" ](); await tick(); out.resume = els[ "text-a" ].textContent;
    mk( "goto-pos" ).value = "3"; listeners[ "goto:click" ](); await tick(); out.goto = { a: els[ "text-a" ].textContent, marker: els.marker.textContent };
    mk( "goto-pos" ).value = "1"; listeners[ "goto:click" ](); await tick(); out.goto_back = { a: els[ "text-a" ].textContent, marker: els.marker.textContent };
    mk( "goto-pos" ).value = "99"; listeners[ "goto:click" ](); await tick(); out.goto_out = els[ "text-a" ].textContent;
    const before = els[ "text-a" ].textContent, posts = calls.length;
    for ( const tag of [ "INPUT", "TEXTAREA" ] ) for ( const key of [ "ArrowRight", "1", "2" ] ) { docListeners.keydown( { target: { tagName: tag }, key } ); await tick(); }
    out.typing = { moved: els[ "text-a" ].textContent !== before, fetched: calls.length - posts };
    out.label_posts = calls.filter( c => c.startsWith( "POST" ) ).length;
    console.log( JSON.stringify( out ) );
} )();
