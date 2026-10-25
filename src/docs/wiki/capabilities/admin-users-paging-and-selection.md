---
capability: admin-users-paging-and-selection
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.admin.js.admin-users.formatDate@2320cbd68f
  - src.lupin_app.static.html.auth.admin.js.admin-users.escapeHtml@edf11c97ec
  - src.lupin_app.static.html.auth.admin.js.admin-users.updatePagination@ac08efe32b
  - src.lupin_app.static.html.auth.admin.js.admin-users.previousPage@75473f5e2e
  - src.lupin_app.static.html.auth.admin.js.admin-users.nextPage@52b5ef0f3c
  - src.lupin_app.static.html.auth.admin.js.admin-users.clearFilters@a329a72a20
  - src.lupin_app.static.html.auth.admin.js.admin-users.debounce@1996304b5b
  - src.lupin_app.static.html.auth.admin.js.admin-users.toggleUserSelection@02f49a1c2b
  - src.lupin_app.static.html.auth.admin.js.admin-users.toggleSelectAll@237d23165e
  - src.lupin_app.static.html.auth.admin.js.admin-users.updateSelectAllCheckbox@89c31a70de
  - src.lupin_app.static.html.auth.admin.js.admin-users.updateBatchActionBar@00837711ee
  - src.lupin_app.static.html.auth.admin.js.admin-users.clearSelection@094cb2d445
  - src.lupin_app.static.html.auth.admin.js.admin-users.showElement@a4d9c4cf77
  - src.lupin_app.static.html.auth.admin.js.admin-users.hideElement@d637d9998b
---
# Admin users: paging, filters and selection

The paging, filter, helper and selection functions of the admin users script. The table is on [[admin-users-api-and-table]].

## Paging and filters
- `updatePagination` writes "Page N of M (T users)" and disables Previous on page one and Next on the last page. `previousPage` and `nextPage` call `loadUsers` for the neighbour page.
- The search box reloads page one 300 ms after typing stops, through `debounce`. The role and status selectors reload page one at once. `clearFilters` blanks all three and reloads.
- A click on a modal's backdrop hides it, by assigning `window.onclick`.

## Selection
- `toggleUserSelection` adds or removes one user id. The selection survives paging, because the set is never cleared on a page change.
- `toggleSelectAll` selects or clears the rows on the current page only. `updateSelectAllCheckbox` shows it checked when all of the page is selected, indeterminate when some are, and unchecked otherwise.
- `updateBatchActionBar` shows "N user(s) selected" and the bar when anything is selected. `clearSelection` empties the set and the checkboxes.

## Helpers
- `formatDate` gives "Just now", "N min ago", hours or days up to a week, then the locale date, and "N/A" for no value. It differs from [[admin-time-formatter]].
- `escapeHtml` escapes text for markup. `showElement` and `hideElement` set display by id and ignore a missing element.
