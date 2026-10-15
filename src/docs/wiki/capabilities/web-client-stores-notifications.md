---
capability: web-client-stores-notifications
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.stores.AckStore.foldKey@d11fbb792a
  - src.lupin_app.static.js.multiplexer.stores.AckStore.normalizeText@af2bb36d54
  - src.lupin_app.static.js.multiplexer.stores.AckStore.AckStoreImpl@1d7571f6f8
  - src.lupin_app.static.js.multiplexer.stores.AckStore.createAckStore@03c6869bc8
  - src.lupin_app.static.js.multiplexer.stores.BroadcastStore.BroadcastStoreImpl@c2ac2c8cf7
  - src.lupin_app.static.js.multiplexer.stores.BroadcastStore.createBroadcastStore@9e41ca1e4c
  - src.lupin_app.static.js.multiplexer.stores.MissedStore.coerceCount@1809ebd789
  - src.lupin_app.static.js.multiplexer.stores.MissedStore.MissedStoreImpl@05b89a6881
  - src.lupin_app.static.js.multiplexer.stores.MissedStore.createMissedStore@3e0d329540
  - src.lupin_app.static.js.multiplexer.stores.NotificationStore.describeRejection@576d8b5cda
  - src.lupin_app.static.js.multiplexer.stores.NotificationStore.formatTtsMessage@2d60c259fc
  - src.lupin_app.static.js.multiplexer.stores.NotificationStore.NotificationStoreImpl@9c6f0e3114
  - src.lupin_app.static.js.multiplexer.stores.NotificationStore.createNotificationStore@60d7963881
  - src.lupin_app.static.js.multiplexer.stores.SenderStore.SenderStoreImpl@ddaa3aa9ec
  - src.lupin_app.static.js.multiplexer.stores.SenderStore.createSenderStore@5fc0f9f5a9
  - src.lupin_app.static.js.multiplexer.stores.SessionStripStore.SessionStripStoreImpl@6ca587fff6
  - src.lupin_app.static.js.multiplexer.stores.SessionStripStore.createSessionStripStore@8445ff1047
---
# Web client stores: notifications and senders

The stores behind the notification list, its senders and its broadcast card. [[web-client-stores]] covers how they are built and ordered.

## What it does
- `AckStore.ts`. `foldKey`: Builds the key an ack is stored under: the session ID or a unique anonymous key. `normalizeText`: Returns the value when it is a string and null otherwise. `AckStoreImpl`: Stores broadcast acknowledgements folded by session and emits change events. `createAckStore`: Build the store.
- `BroadcastStore.ts`. `BroadcastStoreImpl`: Holds the broadcast recipient list and the card's open or closed state. `createBroadcastStore`: Build the store. It reads the saved card-open state from storage at once.
- `MissedStore.ts`. `coerceCount`: Coerce an arbitrary server value to a non-negative integer count. `MissedStoreImpl`: Holds the count of undelivered missed notifications. `createMissedStore`: Build the store. It takes the missed count from each `auth_success` event.
- `NotificationStore.ts`. `describeRejection`: Turns a rejection reason into a readable string. `formatTtsMessage`: Builds the spoken text for a notification, prefixing urgent ones with "Urgent!". `NotificationStoreImpl`: Holds the page's notifications: active list, archive, read state and history. `createNotificationStore`: Build the store.
- `SenderStore.ts`. `SenderStoreImpl`: Keeps one record per notification sender, with activity, counts and session names. `createSenderStore`: Build the store.
- `SessionStripStore.ts`. `SessionStripStoreImpl`: Tracks one strip icon per session sender. `createSessionStripStore`: Build the store.
