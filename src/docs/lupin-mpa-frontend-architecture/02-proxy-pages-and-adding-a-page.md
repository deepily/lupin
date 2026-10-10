> Part 2 of 2 of the [Lupin Frontend Architecture](../lupin-mpa-frontend-architecture.md): the proxy UI pages and how to add a new page.

## Proxy UI Pages

### Ratification Page (`/app/admin/proxy-ratify`)

**Purpose**: Admin queue for reviewing and approving/rejecting proxy decisions.

**Files**:
- `html/auth/admin/proxy-ratify.html` (204 lines)
- `html/auth/admin/js/proxy-ratify.js` (748 lines, 26 functions)
- `html/auth/admin/css/proxy-ratify.css` (534 lines)

**Key UI Elements**:

| Element | ID | Purpose |
|---------|----|---------|
| Summary Cards | `stat-pending`, `stat-approved`, `stat-rejected`, `stat-oldest` | At-a-glance counts |
| Filter Bar | `filter-category`, `filter-trust-level`, `filter-action` | Client-side filtering |
| Bulk Actions | `bulk-actions`, `selected-count` | Multi-select approve/reject |
| Decisions Table | `decisions-tbody` | 8-column table (checkbox, category, question, action, trust, confidence, age, actions) |
| Detail Modal | `detail-modal`, `decision-detail`, `feedback-text` | View + feedback + approve/reject |
| Confirm Modal | `confirm-modal`, `confirm-message` | Bulk rejection confirmation |
| Pagination | `prev-page`, `page-info`, `next-page` | Page navigation |
| Empty State | `empty-state` | No pending decisions |

**API Endpoints Used**:
- `GET /api/proxy/pending/{email}` — Load pending decisions
- `POST /api/proxy/ratify/{id}?approved=true&user_email=...` — Ratify a decision

**Real-time Updates**: WebSocket connection to `/ws/queue/proxy ratify` subscribes to `proxy_decision_new` events and calls `loadPending()` on arrival. Tab-focus also triggers a refresh.

**Functions** (26 total):

| Category | Functions |
|----------|-----------|
| API | `loadPending`, `ratifyDecision` |
| Rendering | `renderSummaryCards`, `renderTable`, `showEmptyState` |
| Badges | `getActionBadge`, `getTrustBadge`, `getRatificationBadge` |
| Filters | `applyFilters`, `clearFilters` |
| Selection | `toggleSelect`, `toggleSelectAll`, `updateBulkActions` |
| Bulk | `bulkApprove`, `bulkReject`, `confirmBulkReject`, `closeConfirmModal` |
| Quick Actions | `quickApprove`, `quickReject` |
| Detail Modal | `showDecisionDetail`, `closeDetailModal`, `modalApprove`, `modalReject` |
| Pagination | `updatePagination`, `previousPage`, `nextPage` |
| Utilities | `formatRelativeTime`, `escapeHtml`, `truncate`, `showElement`, `hideElement` |
| WebSocket | `connectProxyWebSocket` |
| Computed | `computeApprovedToday`, `computeRejectedToday` |

### Trust Dashboard (`/app/admin/proxy-dashboard`)

**Purpose**: Visualize trust levels per SWE category, view recent decisions, and change trust mode.

**Files**:
- `html/auth/admin/proxy-dashboard.html` (132 lines)
- `html/auth/admin/js/proxy-dashboard.js` (488 lines, 20 functions)
- `html/auth/admin/css/proxy-dashboard.css` (397 lines)

**Key UI Elements**:

| Element | ID | Purpose |
|---------|----|---------|
| Mode Bar | `mode-trust-select`, `mode-domain`, `mode-user`, `mode-status-dot` | Trust mode selector + status |
| Trust Cards Grid | `trust-cards-grid` | 6 category cards (3×2 grid) |
| Category Selector | `category-selector` | Filter recent decisions by category |
| Decisions Table | `decisions-tbody` | 6-column table (time, question, action, trust, confidence, state) |
| Pagination | `prev-page`, `page-info`, `next-page` | Page navigation |
| Empty State | `decisions-empty` | No decisions recorded |

**API Endpoints Used**:
- `GET /api/proxy/trust/{email}?domain=swe` — Load trust states per category
- `GET /api/proxy/decisions/swe/{category}?limit=N` — Load recent decisions
- `GET /api/proxy/mode` — Get current trust mode
- `PUT /api/proxy/mode` — Change trust mode (hot-reload)

**Constants**:
- `SWE_CATEGORIES` — 6 categories: deployment, testing, deps, architecture, destructive, general
- `TRUST_LABELS` — Level 1 Shadow, Level 2 Provisional, Level 3 Trusted, Level 4 Autonomous, Level 5 Full Trust

**Trust Card Structure**:
Each of the 6 category cards shows:
- Category icon + label
- Trust level (levels 1 to 5) with color-coded border
- Success rate progress bar
- Total decisions count, rejected count, circuit breaker status

**Functions** (20 total):

| Category | Functions |
|----------|-----------|
| API | `loadTrustStates`, `loadRecentDecisions` |
| Rendering | `renderModeBar`, `updateModeStatusDot`, `renderTrustCards`, `createTrustCard`, `renderRecentDecisions` |
| Mode | `onModeChange` |
| Badges | `getActionBadge`, `getTrustBadge`, `getRatificationBadge` |
| Pagination | `updatePagination`, `previousPage`, `nextPage` |
| Utilities | `formatRelativeTime`, `escapeHtml`, `truncate`, `showElement`, `hideElement` |

---

## Adding a New Page

### Checklist

1. **Create the HTML file** in the appropriate subdirectory under `static/html/`:
   ```
   static/html/auth/admin/my-page.html    # Admin page
   static/html/auth/my-page.html          # Auth-required page
   static/html/my-page.html               # Public page
   ```

2. **Set up the CSS cascade** in `<head>`:
   ```html
   <link rel="stylesheet" href="/static/css/lupin-base.css">
   <!-- Layer 2: domain CSS (pick one) -->
   <link rel="stylesheet" href="/static/html/auth/admin/css/admin.css">
   <!-- Layer 3: page-specific CSS (create if needed) -->
   <link rel="stylesheet" href="/static/html/auth/admin/css/my-page.css">
   <!-- Layer 4: navigation (always last) -->
   <link rel="stylesheet" href="/static/css/lupin-nav.css">
   ```

3. **Load scripts** at the bottom of `<body>`:
   ```html
   <script src="/static/js/lupin-nav.js" defer></script>
   <script src="/static/html/auth/js/auth.js"></script>
   <script src="/static/html/auth/admin/js/my-page.js"></script>
   ```

4. **Add the route** to `_ROUTE_TABLE` in `src/cosa/rest/routers/pages.py`:
   ```python
   _ROUTE_TABLE = {
       # ... existing routes ...
       "/app/admin/my-page" : "html/auth/admin/my-page.html",
   }
   ```
   Then add the corresponding route handler:
   ```python
   @router.get( "/app/admin/my-page", include_in_schema=False )
   async def page_admin_my_page():
       return _serve_file( _ROUTE_TABLE[ "/app/admin/my-page" ] )
   ```

5. **Add to navigation** (optional) — add an entry to `NAV_ITEMS` in `lupin-nav.js`:
   ```javascript
   { label: "My Page", url: "/app/admin/my-page", icon: "wrench", auth: true, admin: true }
   ```

6. **Create the page JS** following the standard structure:
   ```javascript
   // Auth gate
   requireAuth();

   // Initialize on DOM ready
   document.addEventListener( "DOMContentLoaded", async function() {
       const user = await getCurrentUser();
       await loadData();
   });
   ```

7. **Add standard HTML elements** — loading state, error/success messages, breadcrumb:
   ```html
   <div class="breadcrumb">
       <a href="/app">Home</a> <span class="separator">></span>
       <a href="/app/admin">Admin</a> <span class="separator">></span>
       <span class="current">My Page</span>
   </div>
   <div class="error-message" id="error-message"></div>
   <div class="success-message" id="success-message"></div>
   <div class="loading" id="loading">
       <div class="spinner"></div>
       <p class="mt-2">Loading...</p>
   </div>
   <div id="main-content" style="display: none;">
       <!-- Page content -->
   </div>
   ```

8. **Update integration tests** — add the new URL to `test_navigation_links.py`:
   ```python
   # In the @pytest.mark.parametrize list:
   "/app/admin/my-page",
   ```

---

## Related Documentation

- **WebSocket Architecture**: `src/docs/websocket-architecture.md`
- **WebSocket Events**: `src/docs/websocket-events.md`
- **Notification API**: `src/docs/notification-api.md`
- **UI Design Spec (Proxy)**: `src/rnd/v0.1.4/2026.02.14-swe-team-phase-4-decision-proxy-architecture/04-ui-design-ratification-dashboard.md`
- **Testing Validation**: `src/rnd/v0.1.4/2026.02.14-swe-team-phase-4-decision-proxy-architecture/06-testing-validation.md`
