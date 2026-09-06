// Task-list card — taskListTable template unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { renderTaskListTable } from "../../../../lupin_app/static/js/multiplexer/render/templates/taskListTable";
import { renderDisclosedRow } from "../../../../lupin_app/static/js/multiplexer/render/templates/taskRowDisclosed";
import { rowWidth } from "../../../../lupin_app/static/js/multiplexer/render/rowSchema";
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
// ⚠️ THE ROW RESHAPE (2026-09-05, Rick's keypress ruling) MOVED FIVE FIELDS AND
// THE NINE CONTROLS BEHIND THE ⋯ TOGGLE. The row is no longer one flat <tr>:
// it is THREE — the visible line, a hidden controls row, a hidden error stripe.
//
// These tests are re-pointed at that row rather than deleted, because every
// assertion in them is still about something the operator can see. Only WHERE a
// field lives moved; the `task-col-{field}` class did not, deliberately.
//
// `fieldText` is the one thing the move forces: a DISCLOSED field wraps its
// value next to its own label, so reading the wrapper's textContent would
// silently compare "Blocked bytask-abc" against "task-abc". It reads the value
// span when there is one and the cell itself otherwise, so a visible field and a
// disclosed field answer the same question the same way.
// ---------------------------------------------------------------------------
function rowHost(
  task    : TaskItem,
  zone    : string | null | undefined,
  targets : ReadonlyArray<string> = [],
): HTMLElement {
  const host = document.createElement( "table" );
  host.appendChild( renderDisclosedRow( task, "task-list", zone, targets ) );
  return host;
}

/** The VISIBLE <tr> — the one carrying data-task-id and the status classes. */
function visibleRow( host: HTMLElement ): HTMLElement {
  return host.querySelector<HTMLElement>( "tr.task-row" )!;
}

function fieldText( host: HTMLElement, field: string ): string | undefined {
  const cell = host.querySelector( `.task-col-${ field }` );
  if ( cell === null ) return undefined;
  const value = cell.querySelector( ".task-disclosed-value" );
  return ( value ?? cell ).textContent ?? undefined;
}


// ---------------------------------------------------------------------------
// the disclosed row (shared by all three panes)
// ---------------------------------------------------------------------------

test("disclosed row: full row — status dot+word, class badge, cells, priority tint", () => {
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
  const tr = rowHost(task, "America/New_York");

  assert.ok(visibleRow(tr).classList.contains("task-row"));
  assert.ok(visibleRow(tr).classList.contains("task-status-blocked"));
  assert.equal(tr.querySelector(".task-col-title")?.textContent, "Fix the widget");

  const badge = tr.querySelector(".task-class-badge");
  assert.equal(badge?.textContent, "bug");
  assert.ok(badge?.classList.contains("task-class-bug"));

  // Status cell: a dot span + the status word as a text node.
  const statusCell = tr.querySelector(".task-col-status");
  assert.ok(statusCell?.querySelector(".task-status-dot"));
  assert.match(statusCell?.textContent ?? "", /blocked/);

  assert.equal(fieldText(tr, "blocked"), "task-abc");
  assert.notEqual(fieldText(tr, "chase"), "—"); // formatted
  assert.equal(fieldText(tr, "accountable"), "tiberius");

  const prioCell = tr.querySelector(".task-col-priority");
  assert.equal(prioCell?.textContent, "P1");
  assert.ok(prioCell?.classList.contains("task-prio-high"));

  assert.equal(fieldText(tr, "project"), "lupin");
});

test("disclosed row: defaults — missing status/class, falsy cells → dashes, no prio tint", () => {
  const tr = rowHost({}, undefined);

  assert.ok(visibleRow(tr).classList.contains("task-status-unknown"));
  assert.equal(tr.querySelector(".task-col-title")?.textContent, "(untitled)");

  const badge = tr.querySelector(".task-class-badge");
  assert.equal(badge?.textContent, "task");              // item_class || "task"
  assert.ok(badge?.classList.contains("task-class-task"));

  assert.match(tr.querySelector(".task-col-status")?.textContent ?? "", /unknown/);
  assert.equal(fieldText(tr, "blocked"), "—");
  assert.equal(fieldText(tr, "chase"), "—");
  assert.equal(fieldText(tr, "accountable"), "—");

  const prioCell = tr.querySelector(".task-col-priority");
  assert.equal(prioCell?.textContent, "—");
  // No recognized priority → no heat class (only the base column class).
  assert.equal(prioCell?.className, "task-col-priority");

  assert.equal(fieldText(tr, "project"), "—");
});

test("disclosed row: typed-ref ARRAY blocked_by renders 'kind:id' joined (bug 336289ab)", () => {
  const tr = rowHost(
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
    fieldText(tr, "blocked"),
    "item:82e4eaf0-7968, persona:krishna",
  );
});

test("disclosed row: empty blocked_by array → em-dash cell", () => {
  const tr = rowHost({ title: "x", status: "queued", blocked_by: [] }, undefined);
  assert.equal(fieldText(tr, "blocked"), "—");
});

// ---------------------------------------------------------------------------
// renderTaskListTable
// ---------------------------------------------------------------------------

test("renderTaskListTable: the SHARED ROW_SCHEMA header; owner + Unassigned group headers; rows render", () => {
  const tasks: TaskItem[] = [
    { owner_persona: "amy", title: "a1", status: "queued" },
    { title: "orphan", status: "blocked" },   // → Unassigned
  ];
  const table = renderTaskListTable(groupTasksByOwner(tasks), "America/New_York");

  assert.ok(table.classList.contains("task-list-table"));
  // 🔴 THE COUNT COMES FROM rowWidth(), NOT A LITERAL. It used to read 11 here
  // and 11 again in the row-order test, and the two drifting apart is the exact
  // defect the shared constant exists to make impossible.
  assert.equal(table.querySelectorAll("thead th").length, rowWidth());
  assert.equal(table.querySelector("thead th.task-col-id")?.textContent, "ID");
  // The ⋯ column is headed BLANK on purpose — it names a control, not a field —
  // with the accessible name on aria-label instead.
  const toggleTh = table.querySelector("thead th.task-col-disclose")!;
  assert.equal(toggleTh.textContent, "");
  assert.equal(toggleTh.getAttribute("aria-label"), "Row controls");
  assert.deepEqual(
    Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent),
    ["ID", "Title", "Class", "Status", "Priority", ""],
  );

  const groupHeaders = table.querySelectorAll(".task-group-header");
  assert.equal(groupHeaders.length, 2);
  assert.match(groupHeaders[0]?.textContent ?? "", /amy · 1/);
  const unassigned = table.querySelector(".task-group-unassigned");
  assert.ok(unassigned);
  assert.match(unassigned?.textContent ?? "", /\(Unassigned\)/);

  // Two TASKS — and now three <tr> each, so count the VISIBLE rows only.
  assert.equal(table.querySelectorAll("tbody tr.task-row").length, 2);
  assert.equal(table.querySelectorAll("tbody tr.task-controls-row").length, 2);
  assert.equal(table.querySelectorAll("tbody tr.task-row-error-stripe").length, 2);
  // Every colspan in the table derives from the same width as the header.
  for ( const spanning of Array.from( table.querySelectorAll<HTMLElement>( "tr.task-controls-row > td, tr.task-row-error-stripe > td, .task-group-header > td" ) ) ) {
    assert.equal( spanning.getAttribute( "colspan" ), String( rowWidth() ), "a colspan drifted from rowWidth()" );
  }
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

test("disclosed row: carries data-task-id from the row id", () => {
  const tr = rowHost({ id: "task-42", title: "t", status: "queued" }, undefined);
  assert.equal(visibleRow(tr).getAttribute("data-task-id"), "task-42");
});

test("disclosed row: missing id → data-task-id is empty string (defensive)", () => {
  const tr = rowHost({ title: "t", status: "queued" }, undefined);
  assert.equal(visibleRow(tr).getAttribute("data-task-id"), "");
});

test("disclosed row: Actions cell — priority select has P0–P3, current selected, heat tint", () => {
  const tr = rowHost({ id: "x", title: "t", status: "queued", priority: "P1" }, undefined);
  const sel = tr.querySelector<HTMLSelectElement>(".task-priority-select");
  assert.ok(sel, "priority select present");
  assert.ok(sel?.classList.contains("task-prio-high"), "P1 heat tint reused");
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["P0", "P1", "P2", "P3"]);
  assert.equal(sel?.value, "P1", "current priority pre-selected");
});

test("disclosed row: priority select with no current priority → no heat tint, nothing pre-selected to a P1", () => {
  const tr = rowHost({ id: "x", title: "t", status: "queued" }, undefined);
  const sel = tr.querySelector<HTMLSelectElement>(".task-priority-select");
  assert.equal(sel?.className, "task-priority-select", "no heat class when priority absent");
  // No option matches "", so the browser defaults selection to the first option (P0).
  assert.equal(sel?.value, "P0");
});

test("disclosed row: owner select — current owner pre-selected + reassign targets, deduped", () => {
  const tr = rowHost(
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

test("disclosed row: owner select — current owner NOT in targets is prepended", () => {
  const tr = rowHost(
    { id: "x", title: "t", status: "queued", owner_persona: "zoe" },
    undefined,
    ["bob"],
  );
  const sel = tr.querySelector<HTMLSelectElement>(".task-owner-select");
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["zoe", "bob"]);
  assert.equal(sel?.value, "zoe");
});

test("disclosed row: unassigned task → disabled (unassigned) placeholder + targets", () => {
  const tr = rowHost(
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

test("disclosed row: owner select drops blank/empty target entries", () => {
  const tr = rowHost(
    { id: "x", title: "t", status: "queued", owner_persona: "amy" },
    undefined,
    ["", "bob"],   // blank entry must be skipped
  );
  const sel = tr.querySelector<HTMLSelectElement>(".task-owner-select");
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["amy", "bob"]);
});

test("disclosed row: default reassignTargets ([]) → unassigned shows placeholder only", () => {
  const tr = rowHost({ id: "x", title: "t", status: "queued" }, undefined);
  const sel = tr.querySelector<HTMLSelectElement>(".task-owner-select");
  assert.equal(sel?.options.length, 1);
  assert.equal(sel?.options[0]?.value, "");
});

test("disclosed row: Actions cell — one verb select, shared reason input, Submit", () => {
  // Re-pointed from the single-verb Drop control (row-control conversion
  // 2026.09.02). The exhaustive option/legality sweeps live in
  // task_row_control.test.ts; this keeps the template file's own claim that the
  // Actions cell renders the three controls at all.
  const tr = rowHost({ id: "x", title: "t", status: "queued" }, undefined);
  const sel   = tr.querySelector<HTMLSelectElement>(".task-verb-select");
  const input = tr.querySelector<HTMLInputElement>(".task-reason-input");
  const btn   = tr.querySelector<HTMLButtonElement>(".task-submit-button");
  assert.ok(sel, "verb select rendered");
  assert.equal(sel!.options.length, 6, "a placeholder plus five verbs");
  assert.equal(input?.type, "text");
  assert.equal(input?.getAttribute("placeholder"), "reason…");
  assert.equal(btn?.type, "button");
  assert.equal(btn?.textContent, "Submit");
});

// ---------------------------------------------------------------------------
// Row redesign 2026.06.29 — ID cell + title truncation/tooltip + Detail 📄
// ---------------------------------------------------------------------------

test("disclosed row: leading ID cell shows first 8 chars of id; absent → em-dash", () => {
  const tr = rowHost({ id: "3b85863e-ccb9-49", title: "t", status: "queued" }, undefined);
  assert.equal(tr.querySelector(".task-col-id")?.textContent, "3b85863e");
  const tr2 = rowHost({ title: "t", status: "queued" }, undefined);
  assert.equal(tr2.querySelector(".task-col-id")?.textContent, "—");
});

test("disclosed row: real-id ID cell carries the click-to-copy affordance (role/tabindex/title)", () => {
  const cell = rowHost({ id: "3b85863e-ccb9-49", title: "t", status: "queued" }, undefined)
    .querySelector<HTMLElement>(".task-col-id")!;
  assert.equal(cell.getAttribute("role"), "button");
  assert.equal(cell.getAttribute("tabindex"), "0");
  assert.equal(cell.getAttribute("title"), "Click to copy ID");
});

test("disclosed row: empty-string id → em-dash ID cell is INERT (no copy affordance)", () => {
  const cell = rowHost({ id: "", title: "t", status: "queued" }, undefined)
    .querySelector<HTMLElement>(".task-col-id")!;
  assert.equal(cell.textContent, "—");
  assert.equal(cell.getAttribute("role"), null);
  assert.equal(cell.getAttribute("tabindex"), null);
  assert.equal(cell.getAttribute("title"), null);
});

test("disclosed row: absent id → em-dash ID cell is INERT (no copy affordance)", () => {
  const cell = rowHost({ title: "t", status: "queued" }, undefined)
    .querySelector<HTMLElement>(".task-col-id")!;
  assert.equal(cell.getAttribute("role"), null);
});

test("disclosed row: a long title is NOT capped — the WHOLE title, inside its span", () => {
  // 🔴 REVERSED, NOT SUPPRESSED. This asserted a 60-character cap; the JS card it
  // reproduces caps nothing. `_taskTitleLabel` returns the whole title and a
  // two-line `-webkit-line-clamp` bounds it VISUALLY, with the `title=` tooltip
  // recovering the rest on hover. A cap LOSES text; a clamp only hides it.
  // The tooltip half of the old assertion was right and is kept.
  const long = "Z".repeat(90);
  const tr = rowHost({ id: "x", title: long, status: "queued" }, undefined);
  const cell = tr.querySelector(".task-col-title")!;
  assert.equal(cell.textContent, long, "the title was capped — a cap loses text a clamp only hides");
  assert.ok(!cell.textContent!.includes("…"), "an ellipsis means a character cap came back");
  assert.equal(cell.getAttribute("title"), long);
  // The clamp binds on the SPAN, never the <td> — so a title with no span is a
  // title with no bound at all, however correct the stylesheet is.
  const span = cell.querySelector(".task-title")!;
  assert.ok(span, "the load-bearing .task-title span is missing");
  assert.equal(span.textContent, long);
});

test("disclosed row: short title not truncated; tooltip carries the full title", () => {
  const tr = rowHost({ id: "x", title: "short", status: "queued" }, undefined);
  const cell = tr.querySelector(".task-col-title")!;
  assert.equal(cell.textContent, "short");
  assert.equal(cell.getAttribute("title"), "short");
});

test("disclosed row: body present → LIVE 📄 carrying data-task-body/-id", () => {
  const tr = rowHost({ id: "feedface-1", title: "t", status: "queued", body: "detail" }, undefined);
  const emoji = tr.querySelector<HTMLElement>(".task-col-detail .task-detail-emoji")!;
  assert.ok(!emoji.classList.contains("task-detail-empty"));
  assert.equal(emoji.getAttribute("role"), "button");
  assert.equal(emoji.dataset.taskBody, "detail");
  assert.equal(emoji.dataset.taskId, "feedface");   // first 8 of "feedface-1"
});

test("disclosed row: empty-string body → DIMMED 📄 in place (disabled, no dataset)", () => {
  const tr = rowHost({ id: "x", title: "t", status: "queued", body: "" }, undefined);
  const emoji = tr.querySelector<HTMLElement>(".task-col-detail .task-detail-emoji")!;
  assert.ok(emoji.classList.contains("task-detail-empty"));
  assert.equal(emoji.getAttribute("aria-disabled"), "true");
  assert.equal(emoji.dataset.taskBody, undefined);
});

test("disclosed row: null body → DIMMED 📄 (taskBodyIsEmpty true)", () => {
  const tr = rowHost({ id: "x", title: "t", status: "queued", body: null }, undefined);
  assert.ok(tr.querySelector(".task-detail-emoji")!.classList.contains("task-detail-empty"));
});

test("disclosed row: Detail is DISCLOSED and still sits before Actions on line 3", () => {
  // 🔴 THIS TEST USED TO ASSERT THE FLAT ELEVEN-CELL ORDER, and that order is
  // gone — Detail and Actions are line-3 DISCLOSED fields now, not <td>s on the
  // visible line. Reversed rather than deleted: the RELATIVE order it pinned is
  // still a real requirement (read affordance, then edit), it simply lives one
  // level down now.
  const host  = rowHost({ id: "x", title: "t", status: "queued", body: "d" }, undefined, ["amy"]);
  const line3 = host.querySelector( ".task-disclosed-line--actions" )!;
  const order = Array.from( line3.children ).map( ( c ) => ( c as HTMLElement ).className.split( " " )[ 1 ] );
  assert.deepEqual( order, [ "task-col-detail", "task-col-actions" ] );
});

test("disclosed row: the VISIBLE line is ROW_SCHEMA.line1 + the ⋯ cell, in order", () => {
  // The replacement for the retired F2 flat-order assertion. It walks the same
  // schema the renderer walks, so a field added to line1 does not need this test
  // edited — but a REORDER, or a lost disclosure cell, still reddens it.
  const host  = rowHost({ id: "x", title: "t", status: "queued", body: "d" }, undefined, ["amy"]);
  const cells = Array.from( visibleRow( host ).children ).map( ( c ) => ( c as HTMLElement ).className.split( " " )[ 0 ] );
  assert.deepEqual( cells, [
    "task-col-id", "task-col-title", "task-col-class", "task-col-status",
    "task-col-priority", "task-col-disclose",
  ] );
  // The cell count is the colspan every disclosed row and error stripe derives
  // from. If these two ever disagree the table renders perfectly and the
  // controls row quietly stops spanning it.
  assert.equal( cells.length, rowWidth() );
});
