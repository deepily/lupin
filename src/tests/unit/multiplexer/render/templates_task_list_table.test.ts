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

test("renderTaskRow: typed-ref ARRAY blocked_by renders 'kind:id' joined (bug 336289ab)", () => {
  const tr = renderTaskRow(
    {
      title: "blocked one",
      status: "blocked",
      blocked_by: [
        { kind: "item", id: "82e4eaf0-7968" },
        { kind: "persona", id: "krishna" },
      ],
    },
    undefined,
  );
  // The real API shape is an ARRAY — must NOT crash and must show kind:id labels.
  assert.equal(
    tr.querySelector(".task-col-blocked")?.textContent,
    "item:82e4eaf0-7968, persona:krishna",
  );
});

test("renderTaskRow: empty blocked_by array → em-dash cell", () => {
  const tr = renderTaskRow({ title: "x", status: "queued", blocked_by: [] }, undefined);
  assert.equal(tr.querySelector(".task-col-blocked")?.textContent, "—");
});

// ---------------------------------------------------------------------------
// renderTaskListTable
// ---------------------------------------------------------------------------

test("renderTaskListTable: 11 headers (ID + Detail augment Actions); owner + Unassigned group headers; rows render", () => {
  const tasks: TaskItem[] = [
    { owner_persona: "amy", title: "a1", status: "queued" },
    { title: "orphan", status: "blocked" },   // → Unassigned
  ];
  const table = renderTaskListTable(groupTasksByOwner(tasks), "America/New_York");

  assert.ok(table.classList.contains("task-list-table"));
  assert.equal(table.querySelectorAll("thead th").length, 11);   // ID + 8 data + Detail + Actions
  assert.equal(table.querySelector("thead th.task-col-id")?.textContent, "ID");
  assert.equal(table.querySelector("thead th.task-col-detail")?.textContent, "Detail");
  assert.equal(table.querySelector("thead th.task-col-actions")?.textContent, "Actions");

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

// ---------------------------------------------------------------------------
// Phase 2 — per-row Actions cell (priority/owner edit + drop)
// ---------------------------------------------------------------------------

test("renderTaskRow: carries data-task-id from the row id", () => {
  const tr = renderTaskRow({ id: "task-42", title: "t", status: "queued" }, undefined);
  assert.equal(tr.getAttribute("data-task-id"), "task-42");
});

test("renderTaskRow: missing id → data-task-id is empty string (defensive)", () => {
  const tr = renderTaskRow({ title: "t", status: "queued" }, undefined);
  assert.equal(tr.getAttribute("data-task-id"), "");
});

test("renderTaskRow: Actions cell — priority select has P0–P3, current selected, heat tint", () => {
  const tr = renderTaskRow({ id: "x", title: "t", status: "queued", priority: "P1" }, undefined);
  const sel = tr.querySelector<HTMLSelectElement>(".task-priority-select");
  assert.ok(sel, "priority select present");
  assert.ok(sel?.classList.contains("task-prio-high"), "P1 heat tint reused");
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["P0", "P1", "P2", "P3"]);
  assert.equal(sel?.value, "P1", "current priority pre-selected");
});

test("renderTaskRow: priority select with no current priority → no heat tint, nothing pre-selected to a P1", () => {
  const tr = renderTaskRow({ id: "x", title: "t", status: "queued" }, undefined);
  const sel = tr.querySelector<HTMLSelectElement>(".task-priority-select");
  assert.equal(sel?.className, "task-priority-select", "no heat class when priority absent");
  // No option matches "", so the browser defaults selection to the first option (P0).
  assert.equal(sel?.value, "P0");
});

test("renderTaskRow: owner select — current owner pre-selected + reassign targets, deduped", () => {
  const tr = renderTaskRow(
    { id: "x", title: "t", status: "queued", owner_persona: "amy" },
    undefined,
    ["bob", "amy", "carol"],   // amy duplicates the current owner → collapsed
  );
  const sel = tr.querySelector<HTMLSelectElement>(".task-owner-select");
  assert.ok(sel, "owner select present");
  // current owner "amy" leads; "bob"/"carol" follow; the duplicate "amy" is dropped.
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["amy", "bob", "carol"]);
  assert.equal(sel?.value, "amy", "current owner pre-selected");
});

test("renderTaskRow: owner select — current owner NOT in targets is prepended", () => {
  const tr = renderTaskRow(
    { id: "x", title: "t", status: "queued", owner_persona: "zoe" },
    undefined,
    ["bob"],
  );
  const sel = tr.querySelector<HTMLSelectElement>(".task-owner-select");
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["zoe", "bob"]);
  assert.equal(sel?.value, "zoe");
});

test("renderTaskRow: unassigned task → disabled (unassigned) placeholder + targets", () => {
  const tr = renderTaskRow(
    { id: "x", title: "t", status: "queued" },   // no owner_persona
    undefined,
    ["bob", "carol"],
  );
  const sel = tr.querySelector<HTMLSelectElement>(".task-owner-select");
  const opts = Array.from(sel!.options);
  assert.equal(opts[0]?.value, "");
  assert.equal(opts[0]?.textContent, "(unassigned)");
  assert.equal(opts[0]?.disabled, true);
  assert.deepEqual(opts.slice(1).map(o => o.value), ["bob", "carol"]);
});

test("renderTaskRow: owner select drops blank/empty target entries", () => {
  const tr = renderTaskRow(
    { id: "x", title: "t", status: "queued", owner_persona: "amy" },
    undefined,
    ["", "bob"],   // blank entry must be skipped
  );
  const sel = tr.querySelector<HTMLSelectElement>(".task-owner-select");
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["amy", "bob"]);
});

test("renderTaskRow: default reassignTargets ([]) → unassigned shows placeholder only", () => {
  const tr = renderTaskRow({ id: "x", title: "t", status: "queued" }, undefined);
  const sel = tr.querySelector<HTMLSelectElement>(".task-owner-select");
  assert.equal(sel?.options.length, 1);
  assert.equal(sel?.options[0]?.value, "");
});

test("renderTaskRow: Actions cell — inline drop reason input + Drop button", () => {
  const tr = renderTaskRow({ id: "x", title: "t", status: "queued" }, undefined);
  const input = tr.querySelector<HTMLInputElement>(".task-drop-reason");
  const btn   = tr.querySelector<HTMLButtonElement>(".task-drop-button");
  assert.equal(input?.type, "text");
  assert.equal(input?.getAttribute("placeholder"), "drop reason…");
  assert.equal(btn?.type, "button");
  assert.equal(btn?.textContent, "Drop");
});

// ---------------------------------------------------------------------------
// Row redesign 2026.06.29 — ID cell + title truncation/tooltip + Detail 📄
// ---------------------------------------------------------------------------

test("renderTaskRow: leading ID cell shows first 8 chars of id; absent → em-dash", () => {
  const tr = renderTaskRow({ id: "3b85863e-ccb9-49", title: "t", status: "queued" }, undefined);
  assert.equal(tr.querySelector(".task-col-id")?.textContent, "3b85863e");
  const tr2 = renderTaskRow({ title: "t", status: "queued" }, undefined);
  assert.equal(tr2.querySelector(".task-col-id")?.textContent, "—");
});

test("renderTaskRow: long title truncated in cell, FULL title in title= tooltip", () => {
  const long = "Z".repeat(90);
  const tr = renderTaskRow({ id: "x", title: long, status: "queued" }, undefined);
  const cell = tr.querySelector(".task-col-title")!;
  assert.equal(cell.textContent, "Z".repeat(60) + "…");
  assert.equal(cell.getAttribute("title"), long);
});

test("renderTaskRow: short title not truncated; tooltip carries the full title", () => {
  const tr = renderTaskRow({ id: "x", title: "short", status: "queued" }, undefined);
  const cell = tr.querySelector(".task-col-title")!;
  assert.equal(cell.textContent, "short");
  assert.equal(cell.getAttribute("title"), "short");
});

test("renderTaskRow: body present → LIVE 📄 carrying data-task-body/-id", () => {
  const tr = renderTaskRow({ id: "feedface-1", title: "t", status: "queued", body: "detail" }, undefined);
  const emoji = tr.querySelector<HTMLElement>(".task-col-detail .task-detail-emoji")!;
  assert.ok(!emoji.classList.contains("task-detail-empty"));
  assert.equal(emoji.getAttribute("role"), "button");
  assert.equal(emoji.dataset.taskBody, "detail");
  assert.equal(emoji.dataset.taskId, "feedface");   // first 8 of "feedface-1"
});

test("renderTaskRow: empty-string body → DIMMED 📄 in place (disabled, no dataset)", () => {
  const tr = renderTaskRow({ id: "x", title: "t", status: "queued", body: "" }, undefined);
  const emoji = tr.querySelector<HTMLElement>(".task-col-detail .task-detail-emoji")!;
  assert.ok(emoji.classList.contains("task-detail-empty"));
  assert.equal(emoji.getAttribute("aria-disabled"), "true");
  assert.equal(emoji.dataset.taskBody, undefined);
});

test("renderTaskRow: null body → DIMMED 📄 (taskBodyIsEmpty true)", () => {
  const tr = renderTaskRow({ id: "x", title: "t", status: "queued", body: null }, undefined);
  assert.ok(tr.querySelector(".task-detail-emoji")!.classList.contains("task-detail-empty"));
});

test("renderTaskRow: Detail cell sits BEFORE the Actions cell (read affordance, then edit)", () => {
  const tr = renderTaskRow({ id: "x", title: "t", status: "queued", body: "d" }, undefined, ["amy"]);
  const cells = Array.from(tr.children).map((c) => (c as HTMLElement).className.split(" ")[0]);
  assert.ok(cells.indexOf("task-col-detail") < cells.indexOf("task-col-actions"));
  assert.equal(cells[0], "task-col-id");   // ID is leftmost
});
