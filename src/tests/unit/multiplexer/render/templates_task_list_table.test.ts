// Task-list card — taskListTable template unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderTaskRow,
  renderTaskListTable,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/taskListTable";
import {
  groupTasksByOwner,
  type TaskItem,
} from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// ---------------------------------------------------------------------------
// renderTaskRow
// ---------------------------------------------------------------------------

test("renderTaskRow: full row — status dot+word, class badge, cells, priority tint", () => {
  const task: TaskItem = {
    title               : "Fix the widget",
    item_class          : "bug",
    status              : "blocked",
    blocked_by          : "task-abc",
    next_chase_ts       : "2026-06-16T14:30:00-04:00",
    accountable_manager : "tiberius",
    priority            : "P1",
    project             : "lupin",
  };
  const tr = renderTaskRow(task, "America/New_York");

  assert.ok(tr.classList.contains("task-row"));
  assert.ok(tr.classList.contains("task-status-blocked"));
  assert.equal(tr.querySelector(".task-col-title")?.textContent, "Fix the widget");

  const badge = tr.querySelector(".task-class-badge");
  assert.equal(badge?.textContent, "bug");
  assert.ok(badge?.classList.contains("task-class-bug"));

  // Status cell: a dot span + the status word as a text node.
  const statusCell = tr.querySelector(".task-col-status");
  assert.ok(statusCell?.querySelector(".task-status-dot"));
  assert.match(statusCell?.textContent ?? "", /blocked/);

  assert.equal(tr.querySelector(".task-col-blocked")?.textContent, "task-abc");
  assert.notEqual(tr.querySelector(".task-col-chase")?.textContent, "—"); // formatted
  assert.equal(tr.querySelector(".task-col-accountable")?.textContent, "tiberius");

  const prioCell = tr.querySelector(".task-col-priority");
  assert.equal(prioCell?.textContent, "P1");
  assert.ok(prioCell?.classList.contains("task-prio-high"));

  assert.equal(tr.querySelector(".task-col-project")?.textContent, "lupin");
});

test("renderTaskRow: defaults — missing status/class, falsy cells → dashes, no prio tint", () => {
  const tr = renderTaskRow({}, undefined);

  assert.ok(tr.classList.contains("task-status-unknown"));
  assert.equal(tr.querySelector(".task-col-title")?.textContent, "(untitled)");

  const badge = tr.querySelector(".task-class-badge");
  assert.equal(badge?.textContent, "task");              // item_class || "task"
  assert.ok(badge?.classList.contains("task-class-task"));

  assert.match(tr.querySelector(".task-col-status")?.textContent ?? "", /unknown/);
  assert.equal(tr.querySelector(".task-col-blocked")?.textContent, "—");
  assert.equal(tr.querySelector(".task-col-chase")?.textContent, "—");
  assert.equal(tr.querySelector(".task-col-accountable")?.textContent, "—");

  const prioCell = tr.querySelector(".task-col-priority");
  assert.equal(prioCell?.textContent, "—");
  // No recognized priority → no heat class (only the base column class).
  assert.equal(prioCell?.className, "task-col-priority");

  assert.equal(tr.querySelector(".task-col-project")?.textContent, "—");
});

// ---------------------------------------------------------------------------
// renderTaskListTable
// ---------------------------------------------------------------------------

test("renderTaskListTable: 8 headers; owner + Unassigned group headers; rows render", () => {
  const tasks: TaskItem[] = [
    { owner_persona: "amy", title: "a1", status: "queued" },
    { title: "orphan", status: "blocked" },   // → Unassigned
  ];
  const table = renderTaskListTable(groupTasksByOwner(tasks), "America/New_York");

  assert.ok(table.classList.contains("task-list-table"));
  assert.equal(table.querySelectorAll("thead th").length, 8);

  const groupHeaders = table.querySelectorAll(".task-group-header");
  assert.equal(groupHeaders.length, 2);
  // amy group header: "amy · 1"
  assert.match(groupHeaders[0]?.textContent ?? "", /amy · 1/);
  // Unassigned bucket header carries the unassigned modifier + literal label.
  const unassigned = table.querySelector(".task-group-unassigned");
  assert.ok(unassigned);
  // The header cell now leads with the accordion chevron (▾/▸) before the label.
  assert.match(unassigned?.textContent ?? "", /\(Unassigned\)/);

  // Two data rows total.
  assert.equal(table.querySelectorAll("tbody .task-row").length, 2);
});

test("renderTaskListTable: empty model → header-only table, no rows", () => {
  const table = renderTaskListTable(groupTasksByOwner([]), undefined);
  assert.equal(table.querySelectorAll(".task-group-header").length, 0);
  assert.equal(table.querySelectorAll(".task-row").length, 0);
});

// ---------------------------------------------------------------------------
// Per-persona accordion markup
// ---------------------------------------------------------------------------

test("renderTaskListTable: each owner is its own <tbody.task-group> with data-owner + id slug", () => {
  const tasks: TaskItem[] = [
    { owner_persona: "amy", title: "a1", status: "queued" },
    { title: "orphan", status: "blocked" },   // → Unassigned
  ];
  const table = renderTaskListTable(groupTasksByOwner(tasks), undefined, new Set());

  const amy = table.querySelector<HTMLElement>('tbody.task-group[data-owner="amy"]');
  const una = table.querySelector<HTMLElement>('tbody.task-group[data-owner="__unassigned__"]');
  assert.ok(amy, "amy tbody present");
  assert.ok(una, "unassigned tbody present (sentinel)");
  assert.equal(amy?.id, "task-group-amy");
  assert.equal(una?.id, "task-group-__unassigned__");
  // no single shared tbody wrapping all groups
  assert.equal(table.querySelectorAll("tbody.task-group").length, 2);
});

test("renderTaskListTable: expanded group → no collapsed class, ▾ chevron, aria-expanded=true", () => {
  const table = renderTaskListTable(
    groupTasksByOwner([{ owner_persona: "amy", title: "a1", status: "queued" }]),
    undefined,
    new Set(),
  );
  const tbody = table.querySelector<HTMLElement>('tbody.task-group[data-owner="amy"]');
  const header = tbody?.querySelector(".task-group-header");
  assert.ok(!tbody?.classList.contains("collapsed"));
  assert.equal(header?.getAttribute("aria-expanded"), "true");
  assert.equal(header?.getAttribute("role"), "button");
  assert.equal(header?.getAttribute("tabindex"), "0");
  assert.equal(header?.getAttribute("aria-controls"), "task-group-amy");
  assert.equal(tbody?.querySelector(".task-group-chevron")?.textContent, "▾");
  assert.equal(tbody?.querySelector(".task-group-chevron")?.getAttribute("aria-hidden"), "true");
});

test("renderTaskListTable: collapsed owner → collapsed class, ▸ chevron, aria-expanded=false", () => {
  const table = renderTaskListTable(
    groupTasksByOwner([
      { owner_persona: "amy", title: "a1", status: "queued" },
      { owner_persona: "bob", title: "b1", status: "queued" },
    ]),
    undefined,
    new Set(["amy"]),
  );
  const amy = table.querySelector<HTMLElement>('tbody.task-group[data-owner="amy"]');
  const bob = table.querySelector<HTMLElement>('tbody.task-group[data-owner="bob"]');
  assert.ok(amy?.classList.contains("collapsed"), "amy collapsed");
  assert.equal(amy?.querySelector(".task-group-header")?.getAttribute("aria-expanded"), "false");
  assert.equal(amy?.querySelector(".task-group-chevron")?.textContent, "▸");
  // bob (not in the set) stays expanded
  assert.ok(!bob?.classList.contains("collapsed"), "bob expanded");
});

test("renderTaskListTable: Unassigned collapses via the sentinel key", () => {
  const table = renderTaskListTable(
    groupTasksByOwner([{ title: "orphan", status: "blocked" }]),
    undefined,
    new Set(["__unassigned__"]),
  );
  const una = table.querySelector<HTMLElement>('tbody.task-group[data-owner="__unassigned__"]');
  assert.ok(una?.classList.contains("collapsed"));
});

test("renderTaskListTable: omitting collapsedOwners defaults to all-expanded (first-load default)", () => {
  const table = renderTaskListTable(
    groupTasksByOwner([{ owner_persona: "amy", title: "a1", status: "queued" }]),
    undefined,
  );   // no 3rd arg → default new Set()
  assert.equal(table.querySelectorAll("tbody.task-group.collapsed").length, 0);
  assert.equal(table.querySelector(".task-group-header")?.getAttribute("aria-expanded"), "true");
});
