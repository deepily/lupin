---
capability: web-client-render-items-podcast-links
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.isEmbeddedAudioHref@fd357e00d5
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.isIoFileHref@eb0e192e26
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.filenameForIoDownload@255e66e283
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.dismissPodcastOverlay@f7b16a731e
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.showPodcastOverlay@c26ea5dbd1
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.defaultDeps@9b7a644ec5
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.downloadIoFileWithAuth@dc78229b1d
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.handlePodcastLinkClick@3697d725fa
  - src.lupin_app.static.js.multiplexer.render.podcastLinks.bindPodcastLinks@a4c80d4c72
---
# Podcast links

Claims the Play Here and Download links on a finished podcast card so they work inside the multiplexer page.

## Link tests
- `isEmbeddedAudioHref( href )` is true for an `/app/audio?path=` link that also carries `embed=1`. A plain Listen link and null return false.
- `isIoFileHref( href )` is true for a relative or loopback-absolute `/api/io/file?` link, with or without a download flag.
- `filenameForIoDownload( url, contentDisposition )` returns the header's filename, else the last segment of the `path` query value, else "download".

## Overlay
- `showPodcastOverlay( embedUrl, title )` appends a single `#podcast-overlay` div to the body with a title, a dismiss button and an iframe. It adds `autoplay=1` once and returns the div.
- `dismissPodcastOverlay()` removes that div, which stops the audio. Opening a second player replaces the first.

## Download
- `downloadIoFileWithAuth( url, deps )` reads `lupin_access_token` from local storage and fetches with a bearer header. With no token it alerts and fetches nothing.
- On success it saves the blob through a hidden anchor. A failed answer or thrown error is shown by alert.
- `defaultDeps()` builds the real token reader, fetch, alert and timer. Tests pass their own `deps`.

## Wiring
- `handlePodcastLinkClick( ev, deps )` returns true after claiming a click on one of the two link kinds and calling `preventDefault`. It ignores clicks inside the reading pane's iframe.
- `bindPodcastLinks( deps )` listens for clicks on the document and returns a function that removes the listener. `ReadingPaneRenderer.ts` calls it.

The binder routes every click to the handler, which picks the overlay or the download using the two link tests.
