---
capability: web-client-render-operator-state-and-keep-place
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.operatorState.whichClass@ed6c67164c
  - src.lupin_app.static.js.multiplexer.render.operatorState.operatorInputKey@c806901c65
  - src.lupin_app.static.js.multiplexer.render.operatorState.operatorInputByKey@f4a8b0ca79
  - src.lupin_app.static.js.multiplexer.render.operatorState.byAttr@1c22908d70
  - src.lupin_app.static.js.multiplexer.render.operatorState.captureOperatorState@fb5a4afb38
  - src.lupin_app.static.js.multiplexer.render.operatorState.restoreOperatorState@38ade5b811
  - src.lupin_app.static.js.multiplexer.render.keepPlace.readKeepPlace@be71c58c24
  - src.lupin_app.static.js.multiplexer.render.keepPlace.keepPlaceIsOn@6eb573c5b2
  - src.lupin_app.static.js.multiplexer.render.keepPlace.paneIsOpen@3d66295cc7
  - src.lupin_app.static.js.multiplexer.render.keepPlace.captureKeepPlace@30f76b2bfc
  - src.lupin_app.static.js.multiplexer.render.keepPlace.restoreKeepPlace@6fef938518
---
# Multiplexer operator state and keep place

Two helpers that carry the operator's context across a repaint: typed input and open controls, and the reader's scroll place in the card list.

## Operator state (`operatorState`)
- `captureOperatorState( container )` reads state off markup about to be replaced. That is inputs, verb selects, pending priorities, error stripes, disclosed rows, and focus with the caret. It reads only inside `container`.
- `restoreOperatorState( container, state, handlers )` puts it back in a fixed order: verbs, priorities, typed values, refusal stripes, opened controls rows, then focus. Anything whose element is absent is skipped, never re-created.
- `operatorInputKey( el )` is `<attr>\0<owner>\0<class>`. The owner is `data-task-id` when non-empty, else `data-filer`. It is null with neither owner or no naming class.
- `operatorInputByKey( container, key )` finds that input in fresh markup, or null for a key that does not have three parts.
- `whichClass( el )` is the first class naming which input it is. `byAttr` finds the first element of a selector whose attribute equals a value.

## Keep place (`keepPlace`)
- `readKeepPlace( storage )` is true only for the stored word `true`. A null storage, another value or a storage that throws gives false. `keepPlaceIsOn()` reads local storage at the moment of asking.
- `paneIsOpen( doc )` is true when `.content-shell` has `pane-open`, so the left column owns the scroll.
- `captureKeepPlace( mount, doc, win )` is null when the reader is at the top. Otherwise it remembers a few cards at or below the strip.
- `restoreKeepPlace( mount, candidates, doc, win )` anchors on the first remembered card still listed that did not move up. It scrolls by how far that card's top moved.
