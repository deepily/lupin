---
capability: admin-snapshots-dashboard
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.admin.js.admin-snapshots.AdminSnapshotsDashboard@58f4cff2d1
  - src.lupin_app.static.html.admin.js.admin-snapshots.toggleSynonyms@9f61d7a612
  - src.lupin_app.static.html.admin.js.admin-snapshots.escapeHtml@edf11c97ec
---
# Admin snapshots dashboard

`AdminSnapshotsDashboard` is the script of the admin snapshots page. A person searches stored solution snapshots, reads one, finds similar ones or deletes one. The page script builds one instance, called `dashboard`, when the page loads and calls `init`. It needs `auth.js` ([[auth-token-handling]]) and the `AudioRecorder` ([[web-client-audio-modules]]).

## Start and calls
- `init` runs `setupAuthentication`, binds the buttons with `setupEventListeners`, shows the email with `displayUserInfo` and focuses the voice button. A visitor without a token goes to login with a redirect back, and a non-admin gets an alert and goes to the profile page.
- `apiCall` waits for `ensureValidToken`, sends the Bearer header, and on a 401 refreshes and retries with no retry limit. Other failures throw the server's `detail`.

## Search and results
- `performSearch` needs a non-empty query. It gets `/admin/snapshots/search` with the query, threshold and limit selectors, then `displayResults` draws the table or the empty state, and `updateResultsCount` writes "Found N results".
- `createResultRow` builds one row. The score is coloured exact at 100, high from 90, medium from 75 and low below. The row also holds the question, gist, two preview icons, the date, eight characters of the id hash, and View and Delete buttons.
- `showLoading`, `hideLoading`, `showError` and `hideError` toggle the loading panel and the error line.

## Detail and delete
- `viewDetails` gets `/admin/snapshots/<id>` and fills the detail modal: answers, synonym pairs, runtime statistics, code and summaries. The synonym section opens collapsed, and the global `toggleSynonyms` flips it.
- `closeDetailModal` clears the remembered id. `confirmDelete` shows the question and `deleteSnapshot` sends DELETE, drops the row and recounts. `closeDeleteModal` forgets the id.
- `formatDate` gives the locale date string. The global `escapeHtml` escapes text for markup.

## Voice search
- `handleSearchSTTButtonClick` stops a running recording, ignores a click while processing, and otherwise calls `startSearchVoiceInput`. Ctrl+R does the same and blocks the browser refresh.
- The recorder uploads to `/api/upload-and-transcribe-mp3`. The transcript fills the search box and runs the search. The button shows an elapsed counter out of 30 seconds, yellow from 25.
- Escape cancels a recording without upload (`_cancelSearchRecording`). The `_start`, `_stop`, `_attach` and `_detach` helpers keep the counter and the key listener.

## Previews and similar
- A preview icon calls `showPreviewPopover`, which gets `/admin/snapshots/<id>/preview`. `createPreviewPopover` builds the code or explanation view, `positionPopover` keeps it 20 pixels inside the window, and `closePreviewPopover` removes it and its Escape listener.
- `showSimilarSnapshots` gets `/admin/snapshots/<id>/similar` and fills a code column and an explanation column through `createSimilarResultItem`. Clicking an item opens its detail. Each modal has an Escape listener attached and detached in pairs.
