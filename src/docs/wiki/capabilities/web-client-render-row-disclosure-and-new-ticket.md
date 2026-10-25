---
capability: web-client-render-row-disclosure-and-new-ticket
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.rowDisclosure.renderDiscloseToggle@cd030bd498
  - src.lupin_app.static.js.multiplexer.render.templates.rowDisclosure.renderDiscloseCell@03ca621a08
  - src.lupin_app.static.js.multiplexer.render.templates.rowDisclosure.renderDisclosedField@a63bd83f6f
  - src.lupin_app.static.js.multiplexer.render.templates.rowDisclosure.renderControlsRow@c3a51074b1
  - src.lupin_app.static.js.multiplexer.render.templates.rowDisclosure.renderErrorStripe@9b9343b833
  - src.lupin_app.static.js.multiplexer.render.templates.rowDisclosure.renderRowError@a520b22c4d
  - src.lupin_app.static.js.multiplexer.render.templates.rowDisclosure.toggleDisclosure@764c5d47a3
  - src.lupin_app.static.js.multiplexer.render.templates.rowDisclosure.closeDisclosedRowsIn@1d499d6405
  - src.lupin_app.static.js.multiplexer.render.templates.rowDisclosure.renderRowTableHead@6c5202c885
  - src.lupin_app.static.js.multiplexer.render.newTicketCard.newTicketMicContextId@450f53df85
  - src.lupin_app.static.js.multiplexer.render.newTicketCard.makeNewTicketDictationHook@71e88a678c
  - src.lupin_app.static.js.multiplexer.render.newTicketCard.renderNewTicketButton@c45aa9bccd
  - src.lupin_app.static.js.multiplexer.render.newTicketCard.bodyOfApiErrorMessage@ee9f6aa6bf
  - src.lupin_app.static.js.multiplexer.render.newTicketCard.apiPostTicket@9580197474
---
# Multiplexer row disclosure and new ticket

The shared disclosure parts of a task row, and the new-ticket button that opens the shared create card with dictation.

## Row disclosure (`rowDisclosure`)
- `renderRowTableHead()` builds the shared `<thead>` from the row schema, one `th` per line-one field, in order, plus a blank trailing `task-col-disclose` header labelled `Row controls`.
- `renderDiscloseToggle( taskId )` is a `task-disclose-button` with `aria-expanded="false"`. `renderDiscloseCell( taskId )` is the `task-col-disclose` cell that holds it.
- `renderDisclosedField( field, value )` is a label and a value in separate spans. A string is written as text and a Node is appended with its listeners intact.
- `renderControlsRow( taskId, statusClass, values )` is one hidden full-width `task-controls-row` whose colspan is `rowWidth()`. A field with no value shows an em dash.
- `renderErrorStripe( taskId )` is a hidden `task-row-error-stripe` row. `renderRowError( pane, id, message )` fills the stripe inside `pane` and hides it for an empty message. A missing stripe is a no-op.
- `toggleDisclosure( pane, button )` flips `aria-expanded` and the controls row's `hidden` together, and returns the new state. It never reaches outside `pane`.
- `closeDisclosedRowsIn( scope )` hides every disclosed controls row in a collapsing group, resets its toggle and clears its stripe.

## New ticket (`newTicketCard`)
- `renderNewTicketButton( opts )` is one `＋ New` button. A click opens the shared card with the roster as it stands, and with a recorder the Title and Details fields carry mics.
- `newTicketMicContextId( field )` is `new-ticket-` plus the field. `makeNewTicketDictationHook( recorder, getAuthToken )` returns the hook that records under that id and splices the text at the caret.
- `bodyOfApiErrorMessage( message )` is the text after the first colon and space. A non-string gives an empty string, and no colon gives the message itself.
- `apiPostTicket( post )` adapts the post call. Success is `{ status: 201, body }`. An error with a numeric `status` keeps it, and anything else is `{ status: 0 }`. It never rejects.
