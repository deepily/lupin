// Task-list card — taskListModel unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  formatChaseTime,
  formatTaskBlockedBy,
  groupTasksByOwner,
  isOpenStatus,
  taskCellOrDash,
  taskOwnerLabel,
  taskPriorityClass,
  taskStatusClass,
  taskTitleLabel,
  type TaskBlockedRef,
  type TaskItem,
} from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

// ---------------------------------------------------------------------------
// isOpenStatus
// ---------------------------------------------------------------------------

test("isOpenStatus: missing → open (degrade-safe)", () => {
  assert.equal(isOpenStatus(undefined), true);
  assert.equal(isOpenStatus(null), true);
  assert.equal(isOpenStatus(""), true);
});

test("isOpenStatus: terminal → not open; non-terminal → open", () => {
  assert.equal(isOpenStatus("done"), false);
  assert.equal(isOpenStatus("dropped"), false);
  assert.equal(isOpenStatus("in_progress"), true);
  assert.equal(isOpenStatus("blocked"), true);
});

// ---------------------------------------------------------------------------
// labels
// ---------------------------------------------------------------------------

test("taskOwnerLabel: owner preferred; Unassigned fallback", () => {
  assert.equal(taskOwnerLabel({ owner_persona: "rio" }), "rio");
  assert.equal(taskOwnerLabel({ owner_persona: "" }), "Unassigned");
  assert.equal(taskOwnerLabel({}), "Unassigned");
  assert.equal(taskOwnerLabel(null), "Unassigned");
  assert.equal(taskOwnerLabel(undefined), "Unassigned");
});

test("taskTitleLabel: title preferred; (untitled) fallback", () => {
  assert.equal(taskTitleLabel({ title: "fix bug" }), "fix bug");
  assert.equal(taskTitleLabel({ title: "" }), "(untitled)");
  assert.equal(taskTitleLabel({}), "(untitled)");
  assert.equal(taskTitleLabel(null), "(untitled)");
});

// ---------------------------------------------------------------------------
// groupTasksByOwner
// ---------------------------------------------------------------------------

test("groupTasksByOwner: non-array input → empty model", () => {
  const m = groupTasksByOwner(undefined);
  assert.equal(m.totalCount, 0);
  assert.deepEqual(m.groups, []);
});

test("groupTasksByOwner: owner groups sorted alpha; Unassigned bucket LAST", () => {
  const tasks: TaskItem[] = [
    { owner_persona: "zoe", title: "z1", status: "queued" },
    { title: "orphan", status: "queued" },               // no owner → Unassigned
    { owner_persona: "amy", title: "a1", status: "queued" },
    { owner_persona: "amy", title: "a2", status: "queued" }, // same owner → push branch
  ];
  const m = groupTasksByOwner(tasks);
  assert.equal(m.totalCount, 4);
  assert.deepEqual(m.groups.map((g) => g.ownerPersona), ["amy", "zoe", null]);
  assert.equal(m.groups[0]!.tasks.length, 2);             // amy: a1 + a2
  assert.equal(m.groups[2]!.isUnassigned, true);
});

test("groupTasksByOwner: no unassigned → no trailing bucket", () => {
  const m = groupTasksByOwner([{ owner_persona: "amy", title: "a", status: "queued" }]);
  assert.equal(m.groups.length, 1);
  assert.equal(m.groups[0]!.isUnassigned, false);
});

test("groupTasksByOwner: in-group sort — status rank, then priority, then title", () => {
  const tasks: TaskItem[] = [
    { owner_persona: "amy", title: "q", status: "queued", priority: "P1" },
    { owner_persona: "amy", title: "b", status: "blocked", priority: "P3" },   // blocked first (rank)
    { owner_persona: "amy", title: "p2b", status: "queued", priority: "P0" },  // same status, P0 first
    { owner_persona: "amy", title: "p2a", status: "queued", priority: "P0" },  // same status+prio → title sort
  ];
  const m = groupTasksByOwner(tasks);
  assert.deepEqual(
    m.groups[0]!.tasks.map((t) => t.title),
    ["b", "p2a", "p2b", "q"],
  );
});

test("groupTasksByOwner: unknown status + missing priority sort defensively (no throw)", () => {
  const tasks: TaskItem[] = [
    { owner_persona: "amy", title: "weird", status: "frobnicated", priority: "urgent" }, // unknown rank + non-P priority
    { owner_persona: "amy", title: "open", status: "in_progress" },  // known rank, sorts first
    { owner_persona: "amy", title: "noprio" },                       // missing status+priority
  ];
  const m = groupTasksByOwner(tasks);
  // in_progress(rank 1) < unknown(5) ; missing-status also unknown-rank(5) → title tiebreak
  assert.equal(m.groups[0]!.tasks[0]!.title, "open");
});

test("groupTasksByOwner: falsy rows collapse to Unassigned (degrade-safe)", () => {
  const m = groupTasksByOwner([null, undefined]);
  assert.equal(m.totalCount, 2);
  assert.equal(m.groups.length, 1);
  assert.equal(m.groups[0]!.isUnassigned, true);
  assert.equal(m.groups[0]!.tasks.length, 2);
});

// ---------------------------------------------------------------------------
// taskCellOrDash
// ---------------------------------------------------------------------------

test("taskCellOrDash: falsy / 'none' → em-dash; else the value", () => {
  assert.equal(taskCellOrDash(null), "—");
  assert.equal(taskCellOrDash(undefined), "—");
  assert.equal(taskCellOrDash(""), "—");
  assert.equal(taskCellOrDash("none"), "—");
  assert.equal(taskCellOrDash("P1"), "P1");
});

// ---------------------------------------------------------------------------
// formatTaskBlockedBy — REAL typed-ref ARRAY shape (bug 336289ab; JS parity 2724b80d)
// ---------------------------------------------------------------------------

test("formatTaskBlockedBy: typed-ref ARRAY → 'kind:id' joined with ', '", () => {
  const refs: TaskBlockedRef[] = [
    { kind: "item", id: "82e4eaf0-7968-47f8-8720-d67f0baeb9e2" },
    { kind: "persona", id: "krishna" },
  ];
  assert.equal(
    formatTaskBlockedBy(refs),
    "item:82e4eaf0-7968-47f8-8720-d67f0baeb9e2, persona:krishna",
  );
});

test("formatTaskBlockedBy: ref with no kind → bare id; non-object member → String(member)", () => {
  assert.equal(formatTaskBlockedBy([{ id: "abc" }]), "abc");
  // a non-object array member is coerced (defensive — never throws)
  assert.equal(formatTaskBlockedBy(["raw" as unknown as TaskBlockedRef]), "raw");
});

test("formatTaskBlockedBy: empty array → '' (caller's taskCellOrDash renders the em-dash)", () => {
  assert.equal(formatTaskBlockedBy([]), "");
  assert.equal(taskCellOrDash(formatTaskBlockedBy([])), "—");
});

test("formatTaskBlockedBy: string / null / undefined pass through unchanged (back-compat)", () => {
  assert.equal(formatTaskBlockedBy("decision:abc"), "decision:abc");
  assert.equal(formatTaskBlockedBy(null), null);
  assert.equal(formatTaskBlockedBy(undefined), undefined);
});

// ---------------------------------------------------------------------------
// taskStatusClass
// ---------------------------------------------------------------------------

test("taskStatusClass: every status word maps; unknown/non-string → unknown", () => {
  assert.equal(taskStatusClass("blocked"), "task-status-blocked");
  assert.equal(taskStatusClass("in_progress"), "task-status-active");
  assert.equal(taskStatusClass("claimed"), "task-status-active");
  assert.equal(taskStatusClass("review"), "task-status-review");
  assert.equal(taskStatusClass("queued"), "task-status-queued");
  assert.equal(taskStatusClass("done"), "task-status-done");
  assert.equal(taskStatusClass("dropped"), "task-status-dropped");
  assert.equal(taskStatusClass("  BLOCKED "), "task-status-blocked"); // trim + lowercase
  assert.equal(taskStatusClass("weird"), "task-status-unknown");
  assert.equal(taskStatusClass(null), "task-status-unknown");
  assert.equal(taskStatusClass(undefined), "task-status-unknown");
});

// ---------------------------------------------------------------------------
// taskPriorityClass
// ---------------------------------------------------------------------------

test("taskPriorityClass: P0/P1 high, P2 mid, P3+ low; non-P / non-string → ''", () => {
  assert.equal(taskPriorityClass("P0"), "task-prio-high");
  assert.equal(taskPriorityClass("P1"), "task-prio-high");
  assert.equal(taskPriorityClass("P2"), "task-prio-mid");
  assert.equal(taskPriorityClass("P3"), "task-prio-low");
  assert.equal(taskPriorityClass(" P5 "), "task-prio-low");
  assert.equal(taskPriorityClass("urgent"), "");
  assert.equal(taskPriorityClass(null), "");
  assert.equal(taskPriorityClass(undefined), "");
});

// ---------------------------------------------------------------------------
// formatChaseTime
// ---------------------------------------------------------------------------

test("formatChaseTime: null/absent → em-dash", () => {
  assert.equal(formatChaseTime(null, "America/New_York"), "—");
  assert.equal(formatChaseTime(undefined, "America/New_York"), "—");
  assert.equal(formatChaseTime("", "America/New_York"), "—");
});

test("formatChaseTime: unparseable → em-dash", () => {
  assert.equal(formatChaseTime("not-a-date", "America/New_York"), "—");
});

test("formatChaseTime: valid ISO with zone → MM-DD HH:MM string (non-empty, not dash)", () => {
  const out = formatChaseTime("2026-06-16T14:30:00-04:00", "America/New_York");
  assert.notEqual(out, "—");
  assert.match(out, /\d/);
});

test("formatChaseTime: no zone → browser-local (non-empty)", () => {
  const out = formatChaseTime("2026-06-16T14:30:00Z", undefined);
  assert.notEqual(out, "—");
  assert.match(out, /\d/);
});

test("formatChaseTime: invalid IANA zone → degrades to browser-local (no throw)", () => {
  const out = formatChaseTime("2026-06-16T14:30:00Z", "Not/AZone");
  assert.notEqual(out, "—");
  assert.match(out, /\d/);
});
