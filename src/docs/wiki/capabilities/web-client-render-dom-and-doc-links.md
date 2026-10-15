---
capability: web-client-render-dom-and-doc-links
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.dom.replaceChildren@fed3680562
  - src.lupin_app.static.js.multiplexer.render.dom.keyedListMerge@fc9792c77b
  - src.lupin_app.static.js.multiplexer.render.dom.placeBefore@a53334537f
  - src.lupin_app.static.js.multiplexer.render.dom.updateAndLocate@e73d45752b
  - src.lupin_app.static.js.multiplexer.render.dom.cssEscape@6428b04fa5
  - src.lupin_app.static.js.multiplexer.render.docLink.normalizeDocLinkHref@ece06e01a1
  - src.lupin_app.static.js.multiplexer.render.docLink.isDocLinkHref@247cc56b79
  - src.lupin_app.static.js.multiplexer.render.docLink.isPaneResidentAnchor@a6526e76db
---
# DOM merge helpers and doc-link rules

`dom.ts` holds the small DOM-update primitives the renderers share, and `docLink.ts` is the one place that decides what a doc link is.

## What it does
- `replaceChildren( parent, incoming )` calls the native `parent.replaceChildren( incoming )`. It gives wholesale replacement one name.
- `keyedListMerge` makes a parent's children match a list of entries, keyed by each element's `data-id-hash`. An `id` attribute is not consulted.
- It removes children whose key is not wanted or is missing, builds missing entries with `create`, and runs the optional `update` on matched ones.
- It then walks the entries in order and moves only elements that are out of position, so unchanged elements keep scroll and focus.
- `updateAndLocate` runs `update` and returns the element now in that place, in case `update` replaced the node.
- `placeBefore` uses `moveBefore` when the browser has it and the element is already a child. It falls back to `insertBefore`.
- `cssEscape` uses `CSS.escape` when present. Otherwise it puts a backslash before every character outside letters, digits, `_` and `-`.
- `normalizeDocLinkHref` strips a leading `http(s)://localhost`, `127.0.0.1` or `0.0.0.0` origin, with its port. It returns null for a null or empty href.
- `isDocLinkHref` is true when the normalized href starts with `/app/docs?path=`.
- `isPaneResidentAnchor` is true when the anchor sits inside `#action-required-content`, `#action-required-section` or `.abstract-tooltip`.

## How the parts work together
Renderers call `keyedListMerge` so a repaint changes only the cards that changed. Doc links go through `isDocLinkHref`, so the markdown emitter and the reading pane agree on what a doc link is. A pane-resident anchor keeps opening a new tab, because routing it into the reading pane would delete the live response buttons.

## Don't
- Don't give two siblings the same `data-id-hash`. Only the first match is reused, and a later duplicate is left where it is.
