/**
 * Drive the SHIPPED getOrCreateSessionId() under each failure condition and
 * report which origin the code actually produced.
 *
 * WHY THIS EXISTS. Its sibling test reads notifications.js and asserts the five
 * origins are declared, distinct, and reachable. That is a claim about the TEXT.
 * It cannot see a wiring mistake — two arms tagged with each other's constant
 * still read as five correct tags. Only running the code answers whether a
 * given failure produces the origin it is supposed to.
 *
 * The three methods are sliced out of the real asset by brace-matching and
 * evaluated onto a stub object, so this executes the SHIPPED source rather than
 * a copy of it. A copy would drift, and a test of a copy measures the copy.
 *
 * Usage:  node drive-session-id-fallback.mjs <path to notifications.js>
 * Output: one JSON object on stdout — { results: [ { label, origin, id } ], happyPath }
 */
import { readFileSync } from 'fs';

const SRC = readFileSync( process.argv[ 2 ], 'utf8' );

/**
 * Slice one method's full source out of the class by brace-matching.
 *
 * The parameter list is skipped before the body brace is located: a default
 * value such as `detail = {}` puts braces INSIDE the signature, and a matcher
 * starting there closes after two characters and returns a stub.
 */
function slice( anchor ) {
    const hits = [ ...SRC.matchAll( anchor ) ];
    if ( hits.length !== 1 ) {
        throw new Error( `anchor ${anchor} matched ${hits.length} times, expected exactly 1 — re-point it rather than relaxing it` );
    }

    let parenDepth = 0, afterParams = -1;
    for ( let i = SRC.indexOf( '(', hits[ 0 ].index ); i < SRC.length; i++ ) {
        if ( SRC[ i ] === '(' ) parenDepth++;
        if ( SRC[ i ] === ')' && --parenDepth === 0 ) { afterParams = i; break; }
    }

    const start = SRC.indexOf( '{', afterParams );
    let depth = 0;
    for ( let i = start; i < SRC.length; i++ ) {
        if ( SRC[ i ] === '{' ) depth++;
        if ( SRC[ i ] === '}' && --depth === 0 ) return SRC.slice( hits[ 0 ].index, i + 1 );
    }
    throw new Error( 'unbalanced braces slicing the method body' );
}

const Harness = eval( `(class Harness { ${ [
    slice( /^    async getOrCreateSessionId\(/gm ),
    slice( /^    get FALLBACK_ORIGIN\(\)/gm ),
    slice( /^    tagSessionIdFailure\(/gm ),
    slice( /^    failSessionIdAcquisition\(/gm )
].join( '\n' ) } })` );

function makeStore() {
    const backing = new Map();
    return {
        getItem : key => backing.has( key ) ? backing.get( key ) : null,
        setItem : ( key, value ) => backing.set( key, value )
    };
}

function makeInstance() {
    const instance = new Harness();
    instance.QUEUE_SESSION_KEY           = 'q';
    instance.AUDIO_SESSION_KEY           = 'a';
    instance.SESSION_FALLBACK_REASON_KEY = 'reason';
    instance.log                         = () => {};
    instance.error                       = () => {};
    instance.getAuthHeader               = () => 'Bearer x';
    instance.ensureValidToken            = async () => {};
    return instance;
}

// Each condition breaks EXACTLY ONE thing, so the origin it yields is
// attributable to that one thing and to nothing else.
const CONDITIONS = {
    'token refresh fails' : instance => {
        instance.ensureValidToken = async () => { throw new Error( 'Token refresh failed - cannot proceed with API call' ); };
        // If this is ever reached the token arm is not short-circuiting as claimed.
        global.fetch = async () => { throw new Error( 'fetch must NOT be reached on the token arm' ); };
    },
    'transport failure (tunnel down)' : () => {
        global.fetch = async () => { throw new TypeError( 'Failed to fetch' ); };
    },
    'endpoint answers 502' : () => {
        global.fetch = async () => ( { ok: false, status: 502, statusText: 'Bad Gateway' } );
    },
    'a 200 that is not JSON' : () => {
        global.fetch = async () => ( { ok: true, json: async () => { throw new SyntaxError( 'Unexpected token < in JSON' ); } } );
    },
    'JSON without session_id' : () => {
        global.fetch = async () => ( { ok: true, json: async () => ( { timestamp: 'now' } ) } );
    }
};

const results = [];

for ( const [ label, condition ] of Object.entries( CONDITIONS ) ) {
    const instance      = makeInstance();
    global.localStorage = makeStore();
    condition( instance );

    // Since Rick's 2026-09-02 ruling the method THROWS rather than minting an
    // id. A condition that returns is a regression, so `threw` is recorded and
    // asserted rather than assumed — a driver that only reads the record would
    // pass identically if the fallback came back.
    let threw = false, id = null;
    try { id = await instance.getOrCreateSessionId( 'queue' ); }
    catch ( failure ) { threw = true; }
    const record = JSON.parse( global.localStorage.getItem( 'reason' ) );
    results.push( { label, origin: record.origin, id, threw, message: record.message } );
}

// Control: the server answers normally. Nothing may be recorded — a fallback
// record written on the happy path would make every origin above meaningless,
// because the record would not be evidence of a failure at all.
const control       = makeInstance();
global.localStorage = makeStore();
global.fetch        = async () => ( { ok: true, json: async () => ( { session_id: 'server issued' } ) } );

const happyId     = await control.getOrCreateSessionId( 'queue' );
const happyRecord = global.localStorage.getItem( 'reason' );

// A localStorage that REFUSES every write — full, disabled, or private mode.
// The caller asked for a session id and one is available, so a storage refusal
// must not become a thrown error escaping getOrCreateSessionId(). Guarding only
// the diagnostic write and leaving the primary one bare passes every other
// check here and throws on this one.
const refusing      = makeInstance();
global.localStorage = {
    getItem : () => null,
    setItem : () => { throw new DOMException( 'QuotaExceededError' ); }
};
global.fetch = async () => { throw new TypeError( 'Failed to fetch' ); };

let storageRefusal;
try {
    storageRefusal = { threw: false, id: await refusing.getOrCreateSessionId( 'queue' ), message: null };
} catch ( error ) {
    storageRefusal = { threw: true, id: null, message: String( error && error.message || error ) };
}

// A rejection carrying a NON-OBJECT. `error` is not guaranteed to be an Error:
// a primitive or null reaching the catch makes a bare `error.lupinFallbackOrigin`
// a TypeError inside the catch itself, which escapes the method and denies the
// caller the id. Raised by Tiberius in review.
const nonObjectThrows = [];

for ( const thrown of [ null, undefined, 'a string', 42 ] ) {
    const instance      = makeInstance();
    global.localStorage = makeStore();
    global.fetch        = async () => { throw thrown; };

    let threw = false, id = null;
    try { id = await instance.getOrCreateSessionId( 'queue' ); }
    catch ( error ) { threw = true; }
    const record = JSON.parse( global.localStorage.getItem( 'reason' ) );
    nonObjectThrows.push( { thrown: String( thrown ), threw, id, origin: record.origin } );
}

console.log( JSON.stringify( {
    results,
    happyPath : { id: happyId, wroteFallbackRecord: happyRecord !== null },
    storageRefusal,
    nonObjectThrows
} ) );
