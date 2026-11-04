---
capability: web-client-doc-relative-links
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.docLink.resolveRelativeDocHref@353053c05d
  - src.lupin_app.static.js.multiplexer.render.docLink.rewriteRelativeDocLinks@be4ecf60b2
  - src.lupin_app.static.js.multiplexer.docPodcast.docLinks.bindDocRelativeLinks@42e3e34e3e
---
# Relative links in the doc viewer

A markdown file's links are written to mean "next to this file". The browser would resolve them against `/app/` and land on a 404. These helpers rewrite each one to a doc-viewer link. The doc-link rules are in [[web-client-render-dom-and-doc-links]].

## What it does
- `resolveRelativeDocHref( href, docPath )` returns `/app/docs?path=<scope>/<resolved>` for a relative href, keeping any `#fragment`. `docPath` is the open document's viewer path.
- It returns null, meaning leave the link alone, in these cases.
  - The href is empty, a bare `#anchor`, or starts with a scheme or `//`.
  - The href is root-absolute, which includes an existing doc link.
  - A `../` would climb out of the document's scope.
  - `docPath` has no scope segment.
- `rewriteRelativeDocLinks( root, docPath )` applies that to every `a[href]` under `root`. It returns how many links it changed.
- `bindDocRelativeLinks( win, doc )` runs the rewrite on the viewer's `#doc-viewer-target`. It starts when the page announces its file, or at once if the window global is already set.
- A mutation observer keeps rewriting what is rendered later.

## Don't
- Don't catch the click instead. Rewriting the `href` keeps middle-click and copy-link working.
