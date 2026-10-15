---
capability: web-client-render-small-widgets
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.dateAccordion.renderDateAccordion@7edeb17851
  - src.lupin_app.static.js.multiplexer.render.filterSettingsReveal.createFilterSettingsReveal@de0b2fcb0e
  - src.lupin_app.static.js.multiplexer.render.historyWindowDropdown.createHistoryWindowDropdown@7b3bfc05ae
  - src.lupin_app.static.js.multiplexer.render.insertTranscriptionText.insertTranscriptionText@e64766cf61
---
# Small render widgets

Four helpers used by the notification and filter panes: a date accordion, a filter-settings reveal, a history-window picker and a caret splice.

## What it does
- `renderDateAccordion( dateKey, notifications, opts, count )` returns a `.date-accordion` div for one `YYYY-MM-DD` date. It carries `data-id-hash` and `data-date-key` set to the date, and starts with `data-collapsed="false"`.
- Its header shows the date, the count in parentheses, a `.date-delete-btn` and a toggle. The count is `count` when given, else `notifications.length`.
- Its messages area holds one notification item per entry, built through `keyedListMerge` in the order given.
- `createFilterSettingsReveal( { toolbar, doc } )` returns a function. When called, it calls `toolbar().showSection` for the filter-settings section, then scrolls that section into view. `showSection` runs first and always. Only the scroll is skipped when the section element is missing.
- `createHistoryWindowDropdown( store, doc )` returns `{ element, sync, dispose }`. The element is `#history-window-dropdown` with one item per history-window option.
- A click on an item closes the menu, sets the window on the store and repaints. A click outside closes the menu. A click inside does not reach an ancestor.
- `insertTranscriptionText( existing, selStart, selEnd, text )` returns `{ value, caret }`. With a caret it replaces the selected range with `text` and returns the index after it.
- With no caret (`null` or `undefined`) it appends `text` and returns a null caret.

## How the parts work together
`toolbar` is a function read at call time, because boot builds the badges before the toolbar renderer exists. The dropdown's `dispose` removes its document click listener, and the notifications header renderer calls it on unmount. The splice is pure, so each caller restores focus and caret itself.
