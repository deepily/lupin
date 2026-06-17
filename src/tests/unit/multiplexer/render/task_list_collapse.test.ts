// Task-list card — per-persona accordion collapse persistence (TS multiplexer).
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// Includes the JS↔TS PARITY-CHECKLIST test: the localStorage key + the
// "__unassigned__" sentinel are asserted to appear VERBATIM in the in-service
// JS card (notifications.js) so any future drift in either file fails loud.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  TASK_LIST_COLLAPSED_KEY,
  TASK_LIST_UNASSIGNED_KEY,
  ownerKeyForGroup,
  taskGroupIdSlug,
  loadCollapsedOwners,
  saveCollapsedOwners,
  toggleCollapsedOwner,
} from "../../../../lupin_app/static/js/multiplexer/render/taskListCollapse";
import type { TaskGroup } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => { localStorage.clear(); });

// ─────────────────────────── parity contract constants ───────────────────────────

test("constants: the localStorage key + Unassigned sentinel are the documented parity values", () => {
  assert.equal(TASK_LIST_COLLAPSED_KEY, "lupin.taskList.collapsedOwners");
  assert.equal(TASK_LIST_UNASSIGNED_KEY, "__unassigned__");
});

test("PARITY CHECKLIST: notifications.js (JS card) uses the SAME key + sentinel verbatim", () => {
  // Fail loud if EITHER card drifts: the shared localStorage key + sentinel are
  // the cross-UI parity contract (a user moving between the JS and TS cards must
  // see the same per-owner collapse state).
  const HERE = dirname(fileURLToPath(import.meta.url));
  const jsSrc = readFileSync(
    resolve(HERE, "../../../../lupin_app/static/js/notifications.js"),
    "utf8",
  );
  assert.ok(
    jsSrc.includes(`'${TASK_LIST_COLLAPSED_KEY}'`) || jsSrc.includes(`"${TASK_LIST_COLLAPSED_KEY}"`),
    `notifications.js must use the shared key ${TASK_LIST_COLLAPSED_KEY} (parity drift)`,
  );
  assert.ok(
    jsSrc.includes(`'${TASK_LIST_UNASSIGNED_KEY}'`) || jsSrc.includes(`"${TASK_LIST_UNASSIGNED_KEY}"`),
    `notifications.js must use the shared sentinel ${TASK_LIST_UNASSIGNED_KEY} (parity drift)`,
  );
});

// ─────────────────────────── ownerKeyForGroup / taskGroupIdSlug (pure) ───────────────────────────

test("ownerKeyForGroup: owned group → persona; Unassigned group → sentinel", () => {
  const owned: TaskGroup = { ownerPersona: "amy", isUnassigned: false, tasks: [] };
  const orphan: TaskGroup = { ownerPersona: null, isUnassigned: true, tasks: [] };
  assert.equal(ownerKeyForGroup(owned), "amy");
  assert.equal(ownerKeyForGroup(orphan), "__unassigned__");
});

test("taskGroupIdSlug: prefixes + sanitizes non [A-Za-z0-9_-] to '-'; underscores survive", () => {
  assert.equal(taskGroupIdSlug("amy"), "task-group-amy");
  assert.equal(taskGroupIdSlug("__unassigned__"), "task-group-__unassigned__");
  assert.equal(taskGroupIdSlug("a b/c"), "task-group-a-b-c");
});

// ─────────────────────────── load / save / toggle (localStorage) ───────────────────────────

test("loadCollapsedOwners: absent key → empty set", () => {
  assert.equal(loadCollapsedOwners().size, 0);
});

test("loadCollapsedOwners: valid JSON array → Set; non-string members filtered", () => {
  localStorage.setItem(TASK_LIST_COLLAPSED_KEY, JSON.stringify(["amy", "__unassigned__", 5, null]));
  assert.deepEqual([...loadCollapsedOwners()].sort(), ["__unassigned__", "amy"]);
});

test("loadCollapsedOwners: non-array JSON → empty set", () => {
  localStorage.setItem(TASK_LIST_COLLAPSED_KEY, JSON.stringify({ not: "an array" }));
  assert.equal(loadCollapsedOwners().size, 0);
});

test("loadCollapsedOwners: empty-string value → empty set (falsy raw)", () => {
  localStorage.setItem(TASK_LIST_COLLAPSED_KEY, "");
  assert.equal(loadCollapsedOwners().size, 0);
});

test("loadCollapsedOwners: malformed JSON → empty set (catch, no throw)", () => {
  localStorage.setItem(TASK_LIST_COLLAPSED_KEY, "{not json");
  assert.equal(loadCollapsedOwners().size, 0);
});

test("saveCollapsedOwners: writes the set as a JSON array", () => {
  saveCollapsedOwners(new Set(["amy", "bob"]));
  assert.deepEqual(JSON.parse(localStorage.getItem(TASK_LIST_COLLAPSED_KEY) ?? "[]").sort(), ["amy", "bob"]);
});

test("saveCollapsedOwners: a throw inside the write is swallowed (no throw)", () => {
  // Array.from(null) throws "not iterable" INSIDE the try → exercises the catch
  // without depending on a (non-reassignable, in happy-dom) localStorage.setItem.
  saveCollapsedOwners(null as unknown as Iterable<string>);   // must not throw
  assert.equal(localStorage.getItem(TASK_LIST_COLLAPSED_KEY), null, "nothing written on failure");
});

test("toggleCollapsedOwner: absent → adds (true) + persists; present → removes (false)", () => {
  assert.equal(toggleCollapsedOwner("amy"), true);
  assert.deepEqual([...loadCollapsedOwners()], ["amy"]);
  assert.equal(toggleCollapsedOwner("amy"), false);
  assert.equal(loadCollapsedOwners().size, 0);
});
