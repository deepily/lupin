// batchSpeak and streamingSpeak share one endpoint swap (row 6b74a018)
//
// The file is plain browser JS in no tsconfig, so it has no c8 number. It ends with a
// CommonJS export that createRequire reads, so the file's own bytes are under test.
//
// Run via:
//   npx tsx --test src/tests/unit/hybrid_tts_js/batch_and_streaming_speak_share_one_endpoint_swap.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE          = dirname( fileURLToPath( import.meta.url ) );
const HYBRID_TTS_JS = resolve( HERE, "../../../lupin_app/static/js/hybrid-tts.js" );
const HybridTTS     = createRequire( import.meta.url )( HYBRID_TTS_JS );

// A bare instance: no constructor, so no WebSocket, IndexedDB or DOM is touched.
function bare( originalSpeak: ( text: string ) => Promise<unknown> ) {
    const tts = Object.create( HybridTTS.prototype );
    tts.apiUrl          = "url-before";
    tts.apiUrlBatch     = "url-batch";
    tts.apiUrlStreaming = "url-streaming";
    tts.originalSpeak   = originalSpeak;
    return tts;
}

for ( const [ method, expected ] of [ [ "batchSpeak", "url-batch" ], [ "streamingSpeak", "url-streaming" ] ] as const ) {
    test( `${method} speaks through ${expected} and restores the previous URL`, async () => {
        const seen: string[] = [];
        const tts = bare( async ( text ) => { seen.push( `${text}@${tts.apiUrl}` ); return "played"; } );

        assert.equal( await tts[ method ]( "hello" ), "played" );
        assert.deepEqual( seen, [ `hello@${expected}` ] );
        assert.equal( tts.apiUrl, "url-before" );
    } );

    test( `${method} restores the previous URL when speaking throws`, async () => {
        const tts = bare( async () => { throw new Error( "boom" ); } );

        await assert.rejects( tts[ method ]( "hello" ), /boom/ );
        assert.equal( tts.apiUrl, "url-before" );
    } );
}

test( "both methods go through the one speakViaEndpoint body", async () => {
    const tts   = bare( async () => "played" );
    const calls: string[][] = [];
    tts.speakViaEndpoint = async ( text: string, url: string ) => { calls.push( [ text, url ] ); return "shared"; };

    assert.equal( await tts.batchSpeak( "a" ), "shared" );
    assert.equal( await tts.streamingSpeak( "b" ), "shared" );
    assert.deepEqual( calls, [ [ "a", "url-batch" ], [ "b", "url-streaming" ] ] );
} );
