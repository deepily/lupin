---
capability: web-client-render-fleet-status
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.fleetModel.fleetLabelOf@8fe6f54f2e
  - src.lupin_app.static.js.multiplexer.render.fleetModel.fleetLivenessTooltip@9828e5c86f
  - src.lupin_app.static.js.multiplexer.render.fleetModel.asRows@65af67a536
  - src.lupin_app.static.js.multiplexer.render.fleetModel.groupFleetByManager@89de957834
  - src.lupin_app.static.js.multiplexer.render.fleetModel.splitFleetByLiveness@b1f2d6ec25
  - src.lupin_app.static.js.multiplexer.render.fleetModel.formatWindowSize@cc9fcdf82e
  - src.lupin_app.static.js.multiplexer.render.fleetModel.formatConsumptionPct@58a635e2c6
  - src.lupin_app.static.js.multiplexer.render.fleetModel.fleetVerdictClass@f4c223df38
  - src.lupin_app.static.js.multiplexer.render.fleetModel.fleetHeatClass@e3d3e14074
  - src.lupin_app.static.js.multiplexer.render.fleetModel.formatFleetTimestamp@64381b9ac6
  - src.lupin_app.static.js.multiplexer.render.templates.fleetStatusTable.td@5c60588c91
  - src.lupin_app.static.js.multiplexer.render.templates.fleetStatusTable.renderFleetOfflineToggle@48da2ebf4b
  - src.lupin_app.static.js.multiplexer.render.templates.fleetStatusTable.renderFleetRow@d1e762fc9e
  - src.lupin_app.static.js.multiplexer.render.templates.fleetStatusTable.renderFleetStatusTable@328a0b7201
---
# Multiplexer fleet status render

The model helpers and the table builders of the fleet status card: sessions grouped under managers, split by liveness, and drawn as a read-only table.

## Model (`fleetModel`)
- `fleetLabelOf( session )` is the persona, else the first 8 characters of the session id, else `unknown`. `fleetLivenessTooltip( liveness )` joins the bridge, event, commons, idle-prompt and freshest ages, each `n/a` when missing.
- `asRows( sessions )` returns the value when it is an array, else an empty list.
- `groupFleetByManager( sessions )` makes one group per manager, sorted by label. Workers attach to their manager's group, or to one trailing Unmanaged group.
- `splitFleetByLiveness( sessions )` puts a row in the offline list only when `liveness.verdict` is `offline`. Rows with no verdict stay live.
- `formatWindowSize` gives `<n>M` for an exact million, `<n>K` for an exact thousand, else the integer, and a dash for a falsy or non-positive value. `formatConsumptionPct` gives `<pct>%`, or a dash for null.
- `fleetVerdictClass( verdict )` keys on the first word: `live`, `quiet`, `stale` or `offline`, else `fleet-verdict-unknown`. `fleetHeatClass( pct )` is `fleet-pct-low` under 50, `fleet-pct-mid` under 80, else `fleet-pct-high`, and empty when unmeasured.
- `formatFleetTimestamp( date, ianaZone )` formats hours, minutes, seconds and a short zone name, in the IANA zone, or browser-local when it is absent or invalid.

## Table (`fleetStatusTable`)
- `td( className, text )` builds one cell. `renderFleetOfflineToggle( offlineCount, showOffline, handlers )` builds a button labelled `Hide offline (N)` or `Show offline (N)` that calls `onToggle`.
- `renderFleetRow( session, indented, personas )` builds one row of eight columns. It carries a `fleet-verdict-` class, `fleet-row-worker` or `fleet-row-manager`, and `fleet-row-stuck` when stuck. The window and percent cells join from `personas`.
- `renderFleetStatusTable( model, personas )` renders managers as group headers with workers beneath and the Unmanaged group last. It has no action column.
