---
capability: web-client-render-panes-modals-and-state
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.jobsBucketExpand.readRaw@5e9990c621
  - src.lupin_app.static.js.multiplexer.render.jobsBucketExpand.loadBucketExpandState@aa5db74a2a
  - src.lupin_app.static.js.multiplexer.render.jobsBucketExpand.saveBucketExpandChoice@22d4a4fce9
  - src.lupin_app.static.js.multiplexer.render.sessionNameEditModal.openSessionNameEditModal@a24855ee12
  - src.lupin_app.static.js.multiplexer.render.templates.personaModal.renderPersonaPopover@bee8725c3b
---
# Render panes: modals and bucket state

Small pieces under the multiplexer render folder: a persisted open/closed map for job buckets, a rename dialog and a persona popover.

## Bucket expand state
- `readRaw( storage )` is private. It reads the `lupin_queue_expand_state` key and parses it. It returns `{}` for an absent key, a throwing read, bad json, or any value that is not a plain object.
- `loadBucketExpandState( storage )` returns a map of bucket to boolean for `todo`, `running`, `done`, `dead` and `history`. Non-boolean values are dropped, and `null` storage gives `{}`.
- `saveBucketExpandChoice( storage, bucket, expanded )` merges one choice into the stored map and keeps unknown entries. The running bucket is stored under `run`. A throwing write is swallowed, and `null` storage does nothing.
- Only `JobsPaneRenderer` calls the load and save pair. Storage is a map of is-expanded, so true means open.

## Dialogs
- `openSessionNameEditModal( { doc, currentName, onSave } )` appends a rename modal to `doc.body`, replacing any open one. It focuses and selects the prefilled input.
- Save or Enter trims the name, calls `onSave` only when it is non-empty, and closes either way. Cancel, the close button or Escape close without saving. It returns an idempotent close function. `NotificationsListRenderer` is the only caller.
- `renderPersonaPopover( input )` builds a `div.persona-popover` with `popover="auto"` and an id slugged from `sender_id`. It shows an accent strip, the icon and name in the persona colour, and the voice id. A Borrowed line is hidden unless `borrowed` is true.
- The display name row appears only when it is set, non-empty and differs from the name. Its close button uses the declarative popover hide attribute.
- `PersonaModalRenderer` appends the result to its portal. For an existing sender it copies the new children into the open popover instead.

The bucket functions touch only the storage passed in. The rename modal uses the `doc` passed in. `renderPersonaPopover` creates its elements on the global `document`. See [[web-client-render-panes-section-chrome]] for the section headers.
