> Part 3 of 6 of the [Decision Proxy — Admin Guide](../proxy-admin-guide.md): pending ratification and the badge and color reference.

## 5. Pending Ratification (`/app/admin/proxy-ratify`)

The Pending Ratification page is your action-oriented review queue. This is where you
approve or reject decisions the proxy has queued for your review.

### Page Layout Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Home > Admin > Pending Ratification                        │
│                                                             │
│  Decision Proxy — Pending Ratification    [← Back to Admin] │
├─────────────────────────────────────────────────────────────┤
│  Summary Cards                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ Pending  │ │ Approved │ │ Rejected │ │  Oldest  │       │
│  │   12     │ │ Today: 5 │ │ Today: 1 │ │  3h ago  │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
├─────────────────────────────────────────────────────────────┤
│  Filter Bar                                                 │
│  [All Categories ▾] [All Trust Levels ▾] [All Actions ▾]    │
│  [Clear Filters]                                            │
├─────────────────────────────────────────────────────────────┤
│  Bulk Actions (appears when items are selected)             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 3 selected   [Approve Sel.] [Reject Sel.] [Delete S.] │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Decisions Table                                            │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ☐ │ Category │ Question     │Act│Trust│Conf│ Age │ ✓✗│  │
│  │ ☐ │ testing  │ Run tests?   │sug│ L2  │ 85%│ 2h  │ ✓✗│  │
│  │ ☑ │ deps     │ Update lodash│sug│ L1  │ 72%│ 5h  │ ✓✗│  │
│  │ ...                                                │    │
│  └─────────────────────────────────────────────────────┘    │
│  [← Previous]  Page 1 of 1 (12 decisions)  [Next →]        │
└─────────────────────────────────────────────────────────────┘
```

### Summary Cards

Four cards at the top give you an instant pulse check:

| Card | Color Accent | Shows |
|------|-------------|-------|
| **Pending** | Orange left border | Total number of decisions awaiting your review |
| **Approved Today** | Green left border | How many you've approved today |
| **Rejected Today** | Red left border | How many you've rejected today |
| **Oldest Pending** | Gray left border | How old the oldest pending decision is (e.g., "3h ago", "2d ago"). Shows "—" if queue is empty. |

### Filter Bar

Three dropdown filters that apply with **And logic** (all filters must match):

| Filter | Options | Effect |
|--------|---------|--------|
| **Category** | All Categories, Deployment, Testing, Dependencies, Architecture, Destructive, General | Show only decisions in the selected category |
| **Trust Level** | All Trust Levels, Level 1 — Shadow, Level 2 — Provisional, Level 3. Trusted, Level 4 — Autonomous, Level 5 — Full Trust | Show only decisions at the selected trust level |
| **Action** | All Actions, Shadow, Suggest, Act, Defer | Show only decisions with the selected action type |

**Clear Filters**: Resets all three dropdowns to "All" and shows the full list.

Filters are applied client-side for instant response. Changing any filter resets to page 1
and clears any checkbox selections.

### Decisions Table

The main table shows all pending decisions matching your current filters.

| Column | Description |
|--------|-------------|
| **Checkbox** | Select individual decisions for bulk actions. Header checkbox toggles all visible rows on the current page. |
| **Category** | Category badge (e.g., `TESTING`, `DEPS`). Gray pill-shaped badge. |
| **Question** | Decision question text, truncated to 80 characters. Hover for full text. **Click anywhere on the row** (except checkbox or action buttons) to open the detail modal. |
| **Action** | What the proxy decided to do. Color-coded badge (see [Badge Reference](#6-badge-and-color-reference)). |
| **Trust** | Trust level at the time of the decision. Color-coded badge (Levels 1 to 5). |
| **Confidence** | Proxy classification confidence. Color-coded text: green (>80%), orange (50-80%), red (<50%). Shows "—" if null. |
| **Age** | How long ago the decision was created (e.g., "2h ago", "5m ago"). |
| **Actions** | Two inline buttons: **checkmark** (quick approve) and **X** (quick reject). |

### Quick Actions (Inline)

Each row has three small inline buttons in the Actions column:

- **Checkmark button** (green background): Instantly approves the decision with no feedback. The page reloads automatically.
- **X button** (red background): Instantly rejects the decision with no feedback. The page reloads automatically.
- **Trash button** (red background): Permanently deletes the decision after a confirmation prompt. Only pending decisions can be deleted. This does not affect trust state counters.

Use these for rapid triage when you're confident in your decision without needing to see full details.

### Bulk Actions

When one or more checkboxes are selected, a bulk actions bar appears above the table:

- **Selected count**: Shows "N selected" (e.g., "3 selected")
- **Approve Selected**: Approves all selected decisions at once. Success message shows count.
- **Reject Selected**: Opens a confirmation modal ("Are you sure you want to reject N selected decisions?"). Click **Confirm Reject** to proceed, or **Cancel** to abort.
- **Delete Selected**: Opens a confirmation modal warning that deletion is permanent and cannot be undone. Only pending decisions can be deleted. Does not affect trust state counters.

**Select all**: The checkbox in the table header selects/deselects all rows on the **current page only** (not all pages).

### Decision Detail Modal

Click any row in the decisions table to open the detail modal with complete information:

| Field | Description |
|-------|-------------|
| **Category** | Decision category badge |
| **Domain** | Domain identifier (typically "swe") |
| **Action** | Proxy action badge (shadow/suggest/act/defer) |
| **Trust Level** | Trust level badge (Levels 1 to 5) |
| **Confidence** | Classification confidence percentage, color-coded |
| **Sender** | The agent or session that originated the decision (sender_id) |
| **Created** | Full timestamp of when the decision was created |
| **Reason** | Human-readable explanation of why the proxy chose this action |
| **Question** | Full question text in a styled box (not truncated) |
| **Decision Value** | The proxy's suggested answer, if applicable. Only shown if present. |

Below the fields:

- **Feedback textarea**: Optional free-text field where you can add context about why you're approving or rejecting. This feedback is stored with the ratification record.
- **Approve button**: Approves the decision (with optional feedback).
- **Reject button**: Rejects the decision (with optional feedback).
- **Cancel button**: Closes the modal without taking action.

You can also close the modal by clicking outside it or clicking the X in the top-right corner.

### Pagination

- 25 decisions per page
- **Previous/Next buttons**: Navigate between pages. Disabled when at the first/last page.
- **Page info**: Shows "Page X of Y (N decisions)"
- Hidden entirely when all decisions fit on a single page

### Real-Time Updates

The ratification page stays current through two mechanisms:

1. **WebSocket subscription**: Automatically subscribes to `proxy_decision_new` events. When a running job generates a new decision, the table refreshes immediately without manual action.
2. **Tab focus refresh**: When you switch back to the tab (e.g., after clicking a notification link), the page re-fetches all pending decisions.

### Empty State

When there are no pending decisions, the table is replaced with a checkmark icon and
the message: **"No pending decisions. All caught up!"**

---

## 6. Badge and Color Reference

### Action Badges

| Action | Background | Text Color | Meaning |
|--------|-----------|------------|---------|
| **shadow** | Gray (`#e2e8f0`) | Dark gray (`#4a5568`) | Observed only, no action taken |
| **suggest** | Light blue (`#bee3f8`) | Blue (`#2b6cb0`) | Suggestion queued for approval |
| **act** | Light green (`#c6f6d5`) | Green (`#276749`) | Proxy acted autonomously |
| **defer** | Light yellow (`#fefcbf`) | Dark yellow (`#975a16`) | Deferred to human (question forwarded): a tripped breaker, an ambiguous case, or you being available (see [Active Hours and Deferral](01-why-trust-levels-and-contents.md#active-hours-and-deferral)) |

### Trust Level Badges

| Level | Background | Text Color | Card Border | Large Text Color |
|-------|-----------|------------|-------------|------------------|
| **Level 1** | Gray (`#e2e8f0`) | Dark gray (`#4a5568`) | Gray (`#a0aec0`) | Gray (`#a0aec0`) |
| **Level 2** | Light blue (`#bee3f8`) | Blue (`#2b6cb0`) | Blue (`#4299e1`) | Blue (`#4299e1`) |
| **Level 3** | Light green (`#c6f6d5`) | Green (`#276749`) | Green (`#48bb78`) | Green (`#48bb78`) |
| **Level 4** | Light purple (`#e9d8fd`) | Purple (`#553c9a`) | Purple (`#9f7aea`) | Purple (`#9f7aea`) |
| **Level 5** | Light yellow (`#fefcbf`) | Dark yellow (`#975a16`) | Yellow (`#ecc94b`) | Yellow (`#ecc94b`) |

### Ratification State Badges

| State | Background | Text Color | Meaning |
|-------|-----------|------------|---------|
| **pending** | Light orange (`#feebc8`) | Orange (`#c05621`) | Awaiting admin review |
| **approved** | Light green (`#c6f6d5`) | Green (`#276749`) | Admin approved the decision |
| **rejected** | Light red (`#fed7d7`) | Red (`#c53030`) | Admin rejected the decision |
| **N/R** (not_required) | Gray (`#e2e8f0`) | Dark gray (`#4a5568`) | No ratification needed (Level 1 shadow or Level 5 full trust) |

### Confidence Colors

| Range | Color | CSS Class | Meaning |
|-------|-------|-----------|---------|
| **>80%** | Green (`#276749`) | `confidence-high` | High confidence — proxy is sure of its classification |
| **50-80%** | Dark yellow (`#975a16`) | `confidence-medium` | Medium confidence — some ambiguity |
| **<50%** | Red (`#c53030`) | `confidence-low` | Low confidence — classification uncertain |

### Success Rate Bar Colors (Dashboard Cards)

| Range | Color | Meaning |
|-------|-------|---------|
| **>80%** | Green (`#48bb78`) | Healthy — most decisions approved |
| **50-80%** | Yellow (`#ecc94b`) | Caution — notable rejection rate |
| **<50%** | Red (`#f56565`) | Problem — more rejections than approvals |

### Circuit Breaker Status

| Status | Dot Color | Text Color | Meaning |
|--------|----------|------------|---------|
| **OK** (closed) | Green (`#48bb78`) | Green (`#276749`) | Normal operation |
| **`TRIPPED`** (open) | Red (`#f56565`) | Red (`#c53030`) | Auto-demoted — too many rejections |
| **COOLDOWN** | Yellow (`#ecc94b`) | Dark yellow (`#975a16`) | Recovery period after trip |

### Mode Status Dot (Dashboard)

| State | Color | Tooltip | Meaning |
|-------|-------|---------|---------|
| **Running** | Green (`#48bb78`) | "Running job — mode change takes effect immediately" | A SWE Team job is active |
| **Queued** | Yellow (`#ecc94b`) | "Queued for next job: MODE" | Mode change saved, no active job |
| **Idle** | Gray (`#a0aec0`) | "No running job — mode change applies to next job" | No SWE Team job running |

---
