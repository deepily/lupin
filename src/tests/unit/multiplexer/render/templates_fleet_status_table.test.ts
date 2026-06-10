// Multiplexer Lane E WP12 — fleetStatusTable template tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderFleetStatusTable,
  renderFleetRow,
  renderFleetOfflineToggle,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/fleetStatusTable";
import {
  groupFleetByManager,
  type FleetSession,
  type FleetPersonaMap,
} from "../../../../lupin_app/static/js/multiplexer/render/fleetModel";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// ---------------------------------------------------------------------------
// renderFleetOfflineToggle
// ---------------------------------------------------------------------------

test("offline toggle: 'Show offline (N)' when hidden, 'Hide offline (N)' when shown", () => {
  let toggles = 0;
  const handlers = { onToggle: (): void => { toggles += 1; } };
  const show = renderFleetOfflineToggle(3, false, handlers);
  assert.equal(show.querySelector(".fleet-offline-toggle-btn")?.textContent, "Show offline (3)");
  const hide = renderFleetOfflineToggle(3, true, handlers);
  assert.equal(hide.querySelector(".fleet-offline-toggle-btn")?.textContent, "Hide offline (3)");
});

test("offline toggle: button click fires onToggle", () => {
  let toggles = 0;
  const el = renderFleetOfflineToggle(1, false, { onToggle: () => { toggles += 1; } });
  el.querySelector<HTMLButtonElement>(".fleet-offline-toggle-btn")!.click();
  assert.equal(toggles, 1);
});

// ---------------------------------------------------------------------------
// renderFleetRow
// ---------------------------------------------------------------------------

test("row: worker is indented (.fleet-row-worker); manager is .fleet-row-manager", () => {
  const worker = renderFleetRow({ persona: "W", role: "worker" }, true, {});
  assert.ok(worker.classList.contains("fleet-row-worker"));
  const mgr = renderFleetRow({ persona: "M", role: "manager" }, false, {});
  assert.ok(mgr.classList.contains("fleet-row-manager"));
});

test("row: stuck adds .fleet-row-stuck + ✓ cell; not-stuck → — cell", () => {
  const stuck = renderFleetRow({ persona: "W", stuck: true }, true, {});
  assert.ok(stuck.classList.contains("fleet-row-stuck"));
  assert.equal(stuck.querySelector(".fleet-col-stuck")?.textContent, "✓");
  assert.ok(stuck.querySelector(".fleet-col-stuck")?.classList.contains("fleet-stuck-yes"));
  const notStuck = renderFleetRow({ persona: "W" }, true, {});
  assert.equal(notStuck.querySelector(".fleet-col-stuck")?.textContent, "—");
});

test("row: holding 'none'/empty → em-dash; a value renders verbatim", () => {
  assert.equal(renderFleetRow({ holding_on: "none" }, true, {}).querySelector(".fleet-col-holding")?.textContent, "—");
  assert.equal(renderFleetRow({}, true, {}).querySelector(".fleet-col-holding")?.textContent, "—");
  assert.equal(renderFleetRow({ holding_on: "review" }, true, {}).querySelector(".fleet-col-holding")?.textContent, "review");
});

test("row: role/state default to 'worker'/'unknown'; verdict defaults to 'unknown'", () => {
  const r = renderFleetRow({ persona: "X" }, true, {});
  assert.equal(r.querySelector(".fleet-role-badge")?.textContent, "worker");
  assert.ok(r.querySelector(".fleet-role-badge")?.classList.contains("fleet-role-worker"));
  assert.equal(r.querySelector(".fleet-col-state")?.textContent, "unknown");
  assert.equal(r.querySelector(".fleet-col-liveness")?.textContent, "unknown");
});

test("row: liveness verdict + raw-ages tooltip via title", () => {
  const r = renderFleetRow(
    { persona: "X", liveness: { verdict: "live", bridge_age_s: 2, freshest_age_s: 2 } },
    true, {},
  );
  const cell = r.querySelector(".fleet-col-liveness");
  assert.equal(cell?.textContent, "live");
  assert.match(cell!.getAttribute("title")!, /bridge 2s/);
});

test("row: % Window + Window joined per-persona; missing persona → em-dash", () => {
  const personas: FleetPersonaMap = { Tib: { consumption_pct_of_window: 42.5, window_size: 1000000 } };
  const joined = renderFleetRow({ persona: "Tib" }, false, personas);
  assert.equal(joined.querySelector(".fleet-col-window-pct")?.textContent, "42.5%");
  assert.equal(joined.querySelector(".fleet-col-window")?.textContent, "1M");

  const missing = renderFleetRow({ persona: "NotInMap" }, false, personas);
  assert.equal(missing.querySelector(".fleet-col-window-pct")?.textContent, "—");
  assert.equal(missing.querySelector(".fleet-col-window")?.textContent, "—");

  const noPersona = renderFleetRow({}, false, personas);
  assert.equal(noPersona.querySelector(".fleet-col-window-pct")?.textContent, "—");
});

// ---------------------------------------------------------------------------
// renderFleetStatusTable
// ---------------------------------------------------------------------------

test("table: header row has the eight columns", () => {
  const table = renderFleetStatusTable({ totalCount: 0, groups: [] });
  const ths = table.querySelectorAll("thead th");
  assert.equal(ths.length, 8);
  assert.deepEqual(Array.from(ths).map((t) => t.textContent),
    ["Who", "Role", "State", "Holding on", "Stuck", "Liveness", "% Window", "Window"]);
});

test("table: manager group renders 👑 header + manager row + indented workers", () => {
  const sessions: FleetSession[] = [
    { persona: "Tiberius", role: "manager" },
    { persona: "Rachel", role: "worker", manager: "Tiberius" },
  ];
  const table = renderFleetStatusTable(groupFleetByManager(sessions), {});
  const header = table.querySelector(".fleet-group-header");
  assert.match(header!.textContent!, /Tiberius 👑/);
  assert.equal(header!.querySelector("td")?.colSpan, 8);
  assert.equal(table.querySelectorAll(".fleet-row-manager").length, 1);
  assert.equal(table.querySelectorAll(".fleet-row-worker").length, 1);
});

test("table: Unmanaged group has '(Unmanaged)' header + no manager row", () => {
  const sessions: FleetSession[] = [{ persona: "Solo", role: "worker" }];
  const table = renderFleetStatusTable(groupFleetByManager(sessions), {});
  const header = table.querySelector(".fleet-group-header.fleet-group-unmanaged");
  assert.ok(header);
  assert.equal(header.textContent, "(Unmanaged)");
  assert.equal(table.querySelectorAll(".fleet-row-manager").length, 0);
  assert.equal(table.querySelectorAll(".fleet-row-worker").length, 1);
});

test("table: persona-less manager header falls back to fleetLabelOf(manager)", () => {
  // A manager with only a session_id (no persona) → header uses the sid label.
  const sessions: FleetSession[] = [{ session_id: "deadbeef9999", role: "manager" }];
  const table = renderFleetStatusTable(groupFleetByManager(sessions), {});
  assert.match(table.querySelector(".fleet-group-header")!.textContent!, /deadbeef 👑/);
});

// ---------------------------------------------------------------------------
// Safe-write invariant
// ---------------------------------------------------------------------------

test("source file contains zero .innerHTML= / rawHTML( / .outerHTML= / inline onclick", () => {
  const src = readFileSync(
    "src/lupin_app/static/js/multiplexer/render/templates/fleetStatusTable.ts",
    "utf8",
  );
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  const banned = [/\.innerHTML\s*=/, /\brawHTML\s*\(/, /\.outerHTML\s*=/, /onclick=/];
  for (const re of banned) {
    assert.equal(re.test(stripped), false, `violation: ${re} in fleetStatusTable.ts`);
  }
});
