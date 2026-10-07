---
capability: web-client-stores
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.stores.index.createStores@d6129634bc
  - src.lupin_app.static.js.multiplexer.stores.NotificationStore.NotificationStoreImpl.setFilterMode@dd07fd1290
  - src.lupin_app.static.js.multiplexer.stores.TaskListStore.TaskListStoreImpl.startPolling@2173c5b82a
  - src.lupin_app.static.js.multiplexer.stores.coldHistoryHydration.createColdHistoryHydration@afd8f8274b
  - src.lupin_app.static.js.multiplexer.stores.bothBoardsReadBack.bothBoardsReadBack@cd44369864
---
# Web client: stores

The stores hold the multiplexer page's state. Each is built by a `createXStore` function from the event bus, and where needed an API client or storage service. A store announces a change as a `store_*_changed` event, and renderers repaint on it. [[web-client-transport-and-auth]] feeds the bus; panes are in [[web-client-notification-panes]] and [[web-client-task-board-panes]].

## What it does
- `createStores` builds 23 stores in one call and returns them as a `StoreSet`. Its docstring still says 6 and 11.
- Five stores subscribe to server frames, in this construction order: notifications, senders, actionRequired, audio, jobs. The bus runs listeners in registration order, and `stores_integration.test.ts` asserts the order.
- `sessionStrip` and `commons` also listen to `notification_queue_update`, and `missed` to `auth_success`.
- `QaStore` listens to the server frame `tts_job_request` in its constructor. It is built outside the pinned five, so its order is neutral.
- Six stores poll every 60 s: fleetStatus, taskList, holdingArea, flowRatio, finishedTasks, taskRequests. `bootMultiplexer` calls `startPolling` after the panes mount.
- `TaskListStore`, `HoldingAreaStore` and `FinishedTasksStore` also subscribe to `task_store_changed`, inside `startPolling`, and call `refreshAfterWrite`.
- Eight stores persist through `StorageService`: unread counts, session names, owed prompts, reading-pane layout, commons filter, view state, the broadcast card flag and the TTS queue.
- `createColdHistoryHydration` runs the page-load history fetch with a 120 s timeout. It re-runs on the Retry event and reloads when the history window or the Mine mode changes.
- `bothBoardsReadBack` re-reads the task list and the holding area after a promote or demote verdict. It waits for both, then re-raises the first failure.
- `SessionTranscriptStore` and its roster are not in the `StoreSet`. They belong to the console page.

## Don't
- Don't reorder the five server-frame stores in `createStores`. The comment and the test both pin the order.
- Don't build `NotificationStore` without `isAdmin`. `setFilterMode` returns `false` and changes nothing for a non-admin.
- Don't build the task or holding-area stores without `actorProvider`. Nothing fails, but every write is recorded as "anonymous (multiplexer)".
- Don't use `Promise.all` for the two-board read-back. It settles on the first failure while the other read still runs.
- Don't expect `acks` to fold acknowledgements until `bootMultiplexer` calls `stores.acks.start()`.

## Invariants
- `ttsQueue` is built after `actionRequired`, because it asks whether a restored focus is still owed.
- `epicStories` is a one-shot fetch with no poll, and `broadcast` is built from storage alone.
- The history-window pick lives under the raw key `notifications_history_window`, shared with the legacy client, not under a `lupin:` key.
