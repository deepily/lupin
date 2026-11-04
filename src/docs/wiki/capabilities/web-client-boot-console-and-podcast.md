---
capability: web-client-boot-console-and-podcast
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.boot.phase6cSenderSort@82c0265faf
  - src.lupin_app.static.js.multiplexer.boot.pickRandom@62e50e5d1a
  - src.lupin_app.static.js.multiplexer.boot.generateSessionId@8f4888cd39
  - src.lupin_app.static.js.multiplexer.boot.buildWebSocketBaseUrl@68517da5cd
  - src.lupin_app.static.js.multiplexer.boot.emitLifecycle@ec9db4ad08
  - src.lupin_app.static.js.multiplexer.boot.attachLifecycleListeners@2de151084c
  - src.lupin_app.static.js.multiplexer.console.consolePage.createStandaloneConsolePane@6c52554518
  - src.lupin_app.static.js.multiplexer.console.consolePage.redirectTargetKeepingQuery@c7b447902b
  - src.lupin_app.static.js.multiplexer.console.consolePage.generateConsoleSessionId@b387e63544
  - src.lupin_app.static.js.multiplexer.console.consolePage.bootConsolePage@8d0493d5e0
  - src.lupin_app.static.js.multiplexer.console.consolePage.attachLifecycle@359e218625
  - src.lupin_app.static.js.multiplexer.console.consolePage.requireElement@30e42f326e
  - src.lupin_app.static.js.multiplexer.console.consolePageUrl.buildConsolePageHref@fa37f9535b
  - src.lupin_app.static.js.multiplexer.console.consolePageUrl.parseConsolePageQuery@ff295d4d4e
  - src.lupin_app.static.js.multiplexer.docPodcast.docPodcast.humanSize@5ab061113c
  - src.lupin_app.static.js.multiplexer.docPodcast.docPodcast.confirmCopy@6f8baba9c5
  - src.lupin_app.static.js.multiplexer.docPodcast.docPodcast.refusalText@4629bbf96e
  - src.lupin_app.static.js.multiplexer.docPodcast.docPodcast.readJson@a7f334ac2d
  - src.lupin_app.static.js.multiplexer.docPodcast.docPodcast.createDocPodcast@ad17f414fe
  - src.lupin_app.static.js.multiplexer.docPodcast.docPodcast.bindDocPodcast@077dc607c0
  - src.lupin_app.static.js.multiplexer.wireQaMetrics.wireQaMetrics@13cf7a4d27
---
# Web client boot, console and podcast

The page boot, the console page and the document podcast control of the multiplexer. [[web-client-jobs-and-session-panes]] describes the panes they mount. `boot.ts` imports `wireQaMetrics.ts`. `consolePage.ts` imports `consolePageUrl.ts`.

## What it does
- `boot.ts`. `phase6cSenderSort`: Orders senders with conversation mode active first, then by most recent activity. `pickRandom`: Returns a random element of a non-empty array. `generateSessionId`: Builds a fallback session ID from a random adjective and animal. `buildWebSocketBaseUrl`: Returns this page's WebSocket base URL, using wss on HTTPS pages. `emitLifecycle`: Emits a page or network lifecycle event on the event bus with the current time. `attachLifecycleListeners`: Turns visibility, online, offline and page restore events into lifecycle events.
- `consolePage.ts`. `createStandaloneConsolePane`: The reading-pane collaborator for a page that is the console. `redirectTargetKeepingQuery`: A redirect target whose "where I was" keeps the query string. `generateConsoleSessionId`: A server-valid, per-load queue session id. `bootConsolePage`: Boot the console page. `attachLifecycle`: Forwards page visibility and network online or offline events onto the event bus. `requireElement`: Returns the element with the given id from the document.
- `consolePageUrl.ts`. `buildConsolePageHref`: The console page's URL for one seat. `parseConsolePageQuery`: Read the console page's query string.
- `docPodcast.ts`. `humanSize`: A byte count a person can read. `confirmCopy`: The question the confirmation asks. Names the file and its size. `refusalText`: The sentence for a refusal or a failure, from the server's `{ detail: { code, message } }` when it sent one. `readJson`: Parses a response body as JSON and returns null if it is not valid JSON. `createDocPodcast`: Build the button's behaviour over the page's elements. `bindDocPodcast`: Attach the button to the page.
- `wireQaMetrics.ts`. `wireQaMetrics`: Subscribe the first-audio capture point.
