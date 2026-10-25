---
capability: web-client-stores-fleet
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.stores.CommonsStore.defaultFilter@fcb14971a9
  - src.lupin_app.static.js.multiplexer.stores.CommonsStore.CommonsStoreImpl@cdd213101e
  - src.lupin_app.static.js.multiplexer.stores.CommonsStore.createCommonsStore@227609516e
  - src.lupin_app.static.js.multiplexer.stores.EpicStoriesStore.EpicStoriesStoreImpl@467c93d4c6
  - src.lupin_app.static.js.multiplexer.stores.EpicStoriesStore.createEpicStoriesStore@2b0e5c47d8
  - src.lupin_app.static.js.multiplexer.stores.FleetStatusStore.FleetStatusStoreImpl@cd7ec820c8
  - src.lupin_app.static.js.multiplexer.stores.FleetStatusStore.serverDetail@f18b0dc420
  - src.lupin_app.static.js.multiplexer.stores.FleetStatusStore.createFleetStatusStore@8832254f92
  - src.lupin_app.static.js.multiplexer.stores.FlowRatioStore.statusOf@7bef36254f
  - src.lupin_app.static.js.multiplexer.stores.FlowRatioStore.refusalText@14d4588c8e
  - src.lupin_app.static.js.multiplexer.stores.FlowRatioStore.FlowRatioStoreImpl@917d594c91
  - src.lupin_app.static.js.multiplexer.stores.FlowRatioStore.createFlowRatioStore@cf9eb930f8
  - src.lupin_app.static.js.multiplexer.stores.SubmitJobsStore.SubmitJobsStoreImpl@10f6a6f23d
  - src.lupin_app.static.js.multiplexer.stores.SubmitJobsStore.scheduledAtOf@7144b81980
  - src.lupin_app.static.js.multiplexer.stores.SubmitJobsStore.schedulingParams@3c29e8c790
  - src.lupin_app.static.js.multiplexer.stores.SubmitJobsStore.errorText@3f111b35ad
  - src.lupin_app.static.js.multiplexer.stores.SubmitJobsStore.createSubmitJobsStore@b7cc56d589
---
# Web client stores: fleet and commons

The stores for fleet status, the flow ratio, submitted jobs, commons entries and epic stories. [[web-client-stores]] covers how they are built. No file in this group imports another; each is loaded on its own by the code that calls it.

## What it does
- `CommonsStore.ts`. `defaultFilter`: Returns the default commons filter with no direction or persona and all kinds. `CommonsStoreImpl`: Holds cached commons entries with their filter, window, and disabled flag. `createCommonsStore`: Build the store.
- `EpicStoriesStore.ts`. `EpicStoriesStoreImpl`: Caches the map of epic stories fetched from the server, loading it at most once. `createEpicStoriesStore`: Build the store. It fetches nothing until `load()` is called, and then only once.
- `FleetStatusStore.ts`. `FleetStatusStoreImpl`: Holds fleet status, size cap and skeleton-crew state for the fleet pane. `serverDetail`: The server's own reason for a refusal, or the status when it gave none. `createFleetStatusStore`: Build the store. It fetches nothing when it is built.
- `FlowRatioStore.ts`. `statusOf`: The HTTP status of a rejection, or null for one that never reached the server. `refusalText`: "<verb> — admin only", "<verb> (HTTP n)", or "<verb> (network)". `FlowRatioStoreImpl`: Holds the flow ratio reading, its settings and the manager pull state for the page. `createFlowRatioStore`: Build the store. It fetches nothing when it is built.
- `SubmitJobsStore.ts`. `SubmitJobsStoreImpl`: Holds status, in-flight flags and candidates for the Submit Agentic Jobs cards. `scheduledAtOf`: `scheduled_at`, or null when the pair is incomplete. `schedulingParams`: The top-level scheduling directives for a v2 body. `errorText`: The message a caller should show for a thrown value of unknown shape. `createSubmitJobsStore`: Build the store.
