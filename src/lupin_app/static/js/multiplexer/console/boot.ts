// Console page boot entry — `/app/console` (row 27760534, Rick's ruling 2026-09-28).
//
// The esbuild entry for the standalone console bundle (src/scripts/build-console.sh). It only
// binds the real browser globals — the shared EventBus and StorageService singletons, the
// production AuthManager, ApiClient and queue transport — and hands them to bootConsolePage,
// where every decision lives and is unit-tested. Like every other `boot.ts`, this file is an
// entry point that executes page bootstrap on import, so the coverage gate excludes it.
//
// Only the QUEUE transport is started. The console needs the queue socket's
// `cc_transcript_append` / `cc_transcript_state` frames and nothing from the audio socket.

import { eventBus } from "../shared/EventBus";
import { storage } from "../shared/StorageService";
import { createAuthManager } from "../auth/AuthManager";
import { createApiClient } from "../api/ApiClient";
import { createQueueTransport } from "../transport/QueueTransport";
import { bootConsolePage, generateConsoleSessionId } from "./consolePage";

const result = bootConsolePage( {
  doc          : document,
  win          : window,
  location     : window.location,
  storage,
  bus          : eventBus,
  newSessionId : () => generateConsoleSessionId( Math.random ),
  connect      : () => {
    const authManager = createAuthManager( {
      refreshUrl       : "/auth/refresh",
      defaultTimeoutMs : 10_000,
      storage,
      bus              : eventBus,
    } );
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return {
      api   : createApiClient( { baseUrl : window.location.origin, defaultTimeoutMs : 10_000, authManager } ),
      queue : createQueueTransport( { authManager, bus : eventBus, baseUrl : `${ proto }//${ window.location.host }` } ),
    };
  },
} );

console.log( "[console] boot", result.status === "watching" ? { seat : result.seat, sessionId : result.sessionId } : result );
