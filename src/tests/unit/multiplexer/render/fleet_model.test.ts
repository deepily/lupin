// Multiplexer Lane E WP12 — fleetModel (pure) unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  fleetLabelOf,
  fleetLivenessTooltip,
  groupFleetByManager,
  splitFleetByLiveness,
  formatWindowSize,
  formatConsumptionPct,
  formatFleetTimestamp,
  type FleetSession,
} from "../../../../lupin_app/static/js/multiplexer/render/fleetModel";

// ---------------------------------------------------------------------------
// fleetLabelOf
// ---------------------------------------------------------------------------

test("fleetLabelOf: persona preferred", () => {
  assert.equal(fleetLabelOf({ persona: "Tiberius", session_id: "abcdef0123" }), "Tiberius");
});

test("fleetLabelOf: falls back to first-8 of session_id", () => {
  assert.equal(fleetLabelOf({ session_id: "abcdef0123456" }), "abcdef01");
});

test("fleetLabelOf: 'unknown' when neither present or session falsy", () => {
  assert.equal(fleetLabelOf({}), "unknown");
  assert.equal(fleetLabelOf(null), "unknown");
  assert.equal(fleetLabelOf(undefined), "unknown");
});

// ---------------------------------------------------------------------------
// fleetLivenessTooltip
// ---------------------------------------------------------------------------

test("fleetLivenessTooltip: falsy liveness → generic message", () => {
  assert.equal(fleetLivenessTooltip(null), "no liveness data");
  assert.equal(fleetLivenessTooltip(undefined), "no liveness data");
});

test("fleetLivenessTooltip: full ages render with 's' suffix", () => {
  const t = fleetLivenessTooltip({
    bridge_age_s: 1, event_age_s: 2, commons_age_s: 3, idle_prompt_age_s: 4, freshest_age_s: 1,
  });
  assert.equal(t, "bridge 1s · event 2s · commons 3s · idle_prompt 4s · freshest 1s");
});

test("fleetLivenessTooltip: null/undefined ages render 'n/a'", () => {
  const t = fleetLivenessTooltip({ bridge_age_s: null, event_age_s: undefined, commons_age_s: 5 });
  assert.equal(t, "bridge n/a · event n/a · commons 5s · idle_prompt n/a · freshest n/a");
});

// ---------------------------------------------------------------------------
// groupFleetByManager
// ---------------------------------------------------------------------------

test("groupFleetByManager: empty + non-array → zero groups", () => {
  assert.deepEqual(groupFleetByManager([]), { totalCount: 0, groups: [] });
  assert.deepEqual(groupFleetByManager("nope" as unknown), { totalCount: 0, groups: [] });
  assert.deepEqual(groupFleetByManager(undefined), { totalCount: 0, groups: [] });
});

test("groupFleetByManager: a manager with no workers still yields a group", () => {
  const m = groupFleetByManager([{ persona: "Tiberius", role: "manager" }]);
  assert.equal(m.totalCount, 1);
  assert.equal(m.groups.length, 1);
  assert.equal(m.groups[0]!.managerPersona, "Tiberius");
  assert.equal(m.groups[0]!.isUnmanaged, false);
  assert.deepEqual(m.groups[0]!.workers, []);
});

test("groupFleetByManager: workers attach to their manager group", () => {
  const sessions: FleetSession[] = [
    { persona: "Tiberius", role: "manager" },
    { persona: "Rachel", role: "worker", manager: "Tiberius" },
    { persona: "Clayton", role: "worker", manager: "Tiberius" },
  ];
  const m = groupFleetByManager(sessions);
  assert.equal(m.groups.length, 1);
  assert.deepEqual(m.groups[0]!.workers.map((w) => w.persona), ["Clayton", "Rachel"]); // label-sorted
});

test("groupFleetByManager: orphan worker (unknown manager) → Unmanaged bucket, last", () => {
  const sessions: FleetSession[] = [
    { persona: "Tiberius", role: "manager" },
    { persona: "Ghost", role: "worker", manager: "NoSuchManager" },
  ];
  const m = groupFleetByManager(sessions);
  assert.equal(m.groups.length, 2);
  assert.equal(m.groups[m.groups.length - 1]!.isUnmanaged, true);
  assert.deepEqual(m.groups[1]!.workers.map((w) => w.persona), ["Ghost"]);
});

test("groupFleetByManager: multiple managers sorted by label; Unmanaged always last", () => {
  const sessions: FleetSession[] = [
    { persona: "Zoe", role: "manager" },
    { persona: "Anna", role: "manager" },
    { role: "worker" }, // no manager → unmanaged
  ];
  const m = groupFleetByManager(sessions);
  assert.deepEqual(m.groups.map((g) => g.isUnmanaged ? "(unmanaged)" : g.managerPersona),
    ["Anna", "Zoe", "(unmanaged)"]);
});

test("groupFleetByManager: a persona-less manager registers no group key; its 'workers' fall unmanaged", () => {
  const sessions: FleetSession[] = [
    { role: "manager" },                              // no persona
    { persona: "W", role: "worker", manager: "X" },   // can't match the persona-less manager
  ];
  const m = groupFleetByManager(sessions);
  // The persona-less manager still gets a (label "unknown") group; the worker is unmanaged.
  const managerGroup = m.groups.find((g) => !g.isUnmanaged);
  assert.ok(managerGroup);
  assert.equal(managerGroup.managerPersona, null);
  assert.deepEqual(managerGroup.workers, []);
  const unmanaged = m.groups.find((g) => g.isUnmanaged);
  assert.ok(unmanaged);
  assert.deepEqual(unmanaged.workers.map((w) => w.persona), ["W"]);
});

test("groupFleetByManager: falsy worker entry collapses to a defensive empty row in Unmanaged", () => {
  const sessions = [null, { persona: "Solo", role: "worker" }] as unknown;
  const m = groupFleetByManager(sessions);
  assert.equal(m.totalCount, 2);
  const unmanaged = m.groups.find((g) => g.isUnmanaged)!;
  // Two unmanaged workers: the defensive empty row + Solo (label-sorted: "Solo" before "unknown").
  assert.equal(unmanaged.workers.length, 2);
  assert.deepEqual(unmanaged.workers.map((w) => fleetLabelOf(w)), ["Solo", "unknown"]);
});

// ---------------------------------------------------------------------------
// splitFleetByLiveness
// ---------------------------------------------------------------------------

test("splitFleetByLiveness: offline only when verdict==='offline'; no-verdict stays live", () => {
  const sessions: FleetSession[] = [
    { persona: "A", liveness: { verdict: "live" } },
    { persona: "B", liveness: { verdict: "offline" } },
    { persona: "C" }, // no liveness → live
  ];
  const { live, offline } = splitFleetByLiveness(sessions);
  assert.deepEqual(live.map((s) => s.persona), ["A", "C"]);
  assert.deepEqual(offline.map((s) => s.persona), ["B"]);
});

test("splitFleetByLiveness: non-array → empty partitions", () => {
  assert.deepEqual(splitFleetByLiveness(null), { live: [], offline: [] });
});

test("splitFleetByLiveness: falsy entry counts as live (defensive empty row)", () => {
  const { live, offline } = splitFleetByLiveness([null] as unknown);
  assert.equal(live.length, 1);
  assert.equal(offline.length, 0);
});

// ---------------------------------------------------------------------------
// formatWindowSize / formatConsumptionPct
// ---------------------------------------------------------------------------

test("formatWindowSize: exact million / thousand / plain / unknown", () => {
  assert.equal(formatWindowSize(1000000), "1M");
  assert.equal(formatWindowSize(2000000), "2M");
  assert.equal(formatWindowSize(200000), "200K");
  assert.equal(formatWindowSize(1500), "1500");
  assert.equal(formatWindowSize(0), "—");
  assert.equal(formatWindowSize(null), "—");
  assert.equal(formatWindowSize(undefined), "—");
  assert.equal(formatWindowSize(-100), "—");
});

test("formatConsumptionPct: numeric → '%'; null/undefined → em-dash", () => {
  assert.equal(formatConsumptionPct(42.5), "42.5%");
  assert.equal(formatConsumptionPct(0), "0%");
  assert.equal(formatConsumptionPct(null), "—");
  assert.equal(formatConsumptionPct(undefined), "—");
});

// ---------------------------------------------------------------------------
// formatFleetTimestamp
// ---------------------------------------------------------------------------

test("formatFleetTimestamp: valid IANA zone formats without throwing", () => {
  const out = formatFleetTimestamp(new Date("2026-06-10T18:30:07Z"), "America/New_York");
  assert.match(out, /\d{2}:\d{2}:\d{2}/);
});

test("formatFleetTimestamp: invalid zone degrades to local (no throw)", () => {
  const out = formatFleetTimestamp(new Date("2026-06-10T18:30:07Z"), "Not/AZone");
  assert.match(out, /\d{2}:\d{2}:\d{2}/);
});

test("formatFleetTimestamp: absent zone uses browser-local", () => {
  const out = formatFleetTimestamp(new Date("2026-06-10T18:30:07Z"), undefined);
  assert.match(out, /\d{2}:\d{2}:\d{2}/);
  assert.equal(formatFleetTimestamp(new Date("2026-06-10T18:30:07Z"), null), out);
});
