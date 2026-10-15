---
capability: web-client-task-forms-create
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.shared.agent-select.buildAgentSelectOptions@3119d94b13
  - src.lupin_app.static.js.shared.agent-select.renderAgentSelect@6bb03b6294
  - src.lupin_app.static.js.shared.agent-select.isAutoRoute@64d8c52baf
  - src.lupin_app.static.js.shared.agent-select.argsForCommand@d04d2c64d7
  - src.lupin_app.static.js.shared.agent-select.publishOnWindow@ab88a6de7a
  - src.lupin_app.static.js.shared.task-create.clean@75df8da418
  - src.lupin_app.static.js.shared.task-create.buildNewTicketPayload@09cfdc86e3
  - src.lupin_app.static.js.shared.task-create.detailFrom@fc20c5e565
  - src.lupin_app.static.js.shared.task-create.describeNewTicketResult@754b8aedef
  - src.lupin_app.static.js.shared.task-create.assigneeOptions@8cfad0524b
  - src.lupin_app.static.js.shared.task-create.closeNewTicketCard@64362e0f4c
  - src.lupin_app.static.js.shared.task-create.formRow@51886e66d9
  - src.lupin_app.static.js.shared.task-create.micButton@bad5dfa63a
  - src.lupin_app.static.js.shared.task-create.selectOf@2e8eb70cf1
  - src.lupin_app.static.js.shared.task-create.textInput@b5c6a9d826
  - src.lupin_app.static.js.shared.task-create.openNewTicketCard@1a194ebc7a
  - src.lupin_app.static.js.shared.task-lookup.classifyTaskRef@2f8e58c729
  - src.lupin_app.static.js.shared.task-lookup.taskLookupPath@3f62b07440
  - src.lupin_app.static.js.shared.task-lookup.taskRefRefusalMessage@3b5622f356
---
# Web client task forms: create and lookup

The shared scripts that create a task, look one up and pick an agent. [[web-client-task-board-panes]] describes the board that uses them. `task-create.js` imports `task-lookup.js`.

## What it does
- `agent-select.js`. `buildAgentSelectOptions`: Build the option list for the Q&A card's select. `renderAgentSelect`: Replace a <select>'s contents with the options built from a payload. `isAutoRoute`: Is this select value the Auto-Route sentinel rather than a routing command?. `argsForCommand`: The args to submit alongside a chosen command, given the typed question. `publishOnWindow`: Publish this module's surface for the classic-script consumer.
- `task-create.js`. `clean`: Trimmed string, or "" for anything that is not a string. `buildNewTicketPayload`: Turn what the form holds into the POST body, or say why it cannot be sent. `detailFrom`: The server's `detail`, from a response body that may be JSON text, an object, or nothing useful. `describeNewTicketResult`: Which outcome a create produced, as a state token plus the sentence to show. `assigneeOptions`: The names offered under "Assigned to": every non-blank string across the given lists, once each, sorted. `closeNewTicketCard`: Remove the open card, if any, and its document key listener. Idempotent. `formRow`: Build one labelled row of the form. `micButton`: One field's mic, or null when the caller supplied no way to record. `selectOf`: Builds a select element with one option per value and one selected. `textInput`: Builds a text input with the new-ticket input class and the given placeholder. `openNewTicketCard`: Open the New Ticket card over the page.
- `task-lookup.js`. `classifyTaskRef`: Classify a caller-supplied task reference. Pure — no fetch, no DOM. `taskLookupPath`: Build the lookup URL for a reference, or null if it is not a reference. `taskRefRefusalMessage`: The sentence shown when a ref will not classify. One place, both clients.
