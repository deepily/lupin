# Task-List Card — Per-Persona Accordion Toggle (Design & Build Plan)

**Date**: 2026-06-17 · **Author**: Tiberius 👑 · **Status**: PLAN (for Rick's approval before code)
**Request (Rick, voice 2026-06-17)**: the task-list card is "a mile long." Add a collapse/expand
**accordion on a per-persona (per-owner) basis** so each owner's outstanding items roll up to a
manageable length, collapsible individually. Keep **both** implementations in sync — **JavaScript
notifications.js card FIRST, TypeScript multiplexer card SECOND, at parity.**
**Task item**: `9facd8e0` (P1, owner tiberius). **HELD, never push** (Rick's gate).

---

## 1. Current state (grounded in the live code)

The in-service **JS** card already groups by owner:

- `notifications.js → groupTasksByOwner( tasks )` (~line 9240) → `{ totalCount, groups[] }`,
  each group `{ ownerPersona, isUnassigned, tasks[] }`, owner-sorted alpha, **Unassigned last**.
- `renderTaskListTable( model, ianaZone )` (~line 9347) emits ONE `<table class="task-list-table">`
  with a shared `<thead>` (8 cols) + `<tbody>`. Per group it emits a **`task-group-header`** row
  (`<tr><td colspan="8">owner · N</td></tr>`) followed by that group's `task-row` rows.
- `renderTaskList()` (~9396) assigns the string to `container.innerHTML`; the render fns are PURE
  (string in → string out, no DOM/side-effects). DOM wiring must live in the impure caller.
- Markup: `notifications.html #section-task-list` (~line 848) + section-toolbar 🗒️ button (~line 41).
  Styling: `static/css/task-list.css`.

The **TS** multiplexer card (banked `30848a31`, not yet in service) mirrors this with
`static/js/multiplexer/` `TaskListStore` / `TaskListRenderer` / `templates_task_list_table` /
`task_list_model` (createElement-based, no innerHTML).

**Key observation**: the per-owner group header ALREADY exists and ALREADY shows the count
(`owner · N`). The accordion is a *behavioral* addition on top of an existing structural seam —
not a re-architecture.

## 2. Design

### 2.1 Behavior
- Each **owner group header becomes a clickable accordion bar**: persona label + open-item **count
  badge** (already present) + a **chevron** (▸ collapsed / ▾ expanded).
- **Click** (or Enter/Space) on a header toggles **only that owner's** task rows.
- A collapsed group keeps its header + count visible (no information loss — a collapsed `krishna`
  still reads `krishna · 7`).
- **Expand-all / Collapse-all** control in the `#section-toolbar` beside the 🗒️ entry point.
- **Default state**: expanded on first ever load; thereafter **remember the user's per-persona
  choice** (see persistence). (Open question for Rick — §5 Q1.)

### 2.2 Persistence (per-persona, survives reload)
- Collapsed owners persist in `localStorage` under a single key, e.g.
  `lupin.taskList.collapsedOwners` → JSON array of persona strings (plus a sentinel for the
  Unassigned bucket, e.g. `"__unassigned__"`).
- On render, a group is collapsed iff its owner ∈ the persisted set.
- The **same key shape + same sentinel** is used by BOTH the JS and TS cards so a user moving
  between the two UIs sees consistent collapse state — this IS the parity contract.

### 2.3 Structural approach (JS)
- Render **each owner group as its own `<tbody class="task-group" data-owner="…">`** (header row +
  its task rows inside one tbody), instead of all groups sharing a single `<tbody>`. Collapsing =
  toggling a `.collapsed` class on that tbody; CSS hides `.task-row` inside `.collapsed` while the
  header row stays visible. (Per-group `<tbody>` is valid HTML and makes show/hide a one-class flip.)
- Keep `renderTaskListTable` PURE (emit the chevron glyph + `data-owner` + `aria-expanded` from the
  persisted set passed in as an arg). Wire click/keyboard handlers via **event delegation** on the
  container in the impure `renderTaskList()` caller (single listener, survives re-render).
- `data-owner` + the Unassigned sentinel give the click handler a stable key to toggle + persist.

### 2.4 TS parity
- Mirror §2.1–2.2 in the multiplexer card (createElement, not innerHTML): per-owner group element,
  chevron, click+keyboard toggle, **identical localStorage key + sentinel + default**. Parity
  verified by a checklist (same key, same default, same control labels, same collapsed-count display).

### 2.5 Accessibility
- Header carries `role="button"`, `tabindex="0"`, `aria-expanded`, `aria-controls` → its group.
- Keyboard: Enter/Space toggles; chevron is decorative (`aria-hidden`).

## 3. Acceptance criteria
- **JS layer**: unit tests for the pure render (chevron + aria-expanded reflect the collapsed set;
  per-tbody grouping) + persistence read/write; **E2E** on `notifications.html` — drive a header
  click → assert that owner's `.task-row`s hide while the header + count remain, collapse-all/
  expand-all works, and **state survives a reload** (localStorage). 100% L/B/F on changed code.
- **TS layer**: same behaviors, same coverage bar, parity checklist green.
- Both: HELD on `wip-v0.1.8`, never push. `:8000` is the authoritative E2E venue (Tiberius schedules).

## 4. Sequence (JS first, TS second — Rick's order)
1. **This plan → Rick approval** (design-approval gate Rick asked for).
2. **JS build** (clone-extend the existing group render) + unit + E2E, HELD → fresh-critical review.
3. **TS parity build** + unit + E2E, HELD → fresh-critical review.
4. **Parity verification** (shared localStorage key/default/control) → report to Rick with both held hashes.

## 5. Open questions for Rick
- **Q1 — default state**: (a) expanded-first-load then remember per-persona [proposed], or
  (b) all collapsed by default (maximally compact), or (c) collapse only owners with > N items?
- **Q2 — scope of "persona"**: collapse strictly by `owner_persona` (incl. the Unassigned bucket)?
  The card groups by owner today, so this is the natural axis — confirming it matches your intent.
