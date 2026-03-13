# Playwright E2E Testing — data-testid Inventory

**Created**: 2026-02-23
**Status**: Planning Complete — Implementation deferred to v0.1.6 (Phase 2)
**Total Elements**: 180+ across 12 pages + 1 shared navigation component
**Existing data-testids**: 2 (notifications.html section toolbar)

---

## Naming Convention

**Pattern**: `data-testid="page-element-type"`

| Component | Convention | Examples |
|-----------|-----------|----------|
| Page prefix | Shortened page name | `login-`, `register-`, `admin-users-` |
| Section prefix | For multi-section pages | `notifications-qa-`, `notifications-cc-` |
| Element name | Describes purpose | `-email-`, `-search-`, `-submit-` |
| Type suffix | Clarifies element type | `-input`, `-btn`, `-select`, `-link`, `-modal` |
| Modal prefix | For modal-specific elements | `modal-user-detail-`, `modal-role-editor-` |

**Playwright Usage**:
```python
page.get_by_test_id( "login-email-input" ).fill( "user@example.com" )
page.get_by_test_id( "login-submit-btn" ).click()
```

---

## Page 1: Login (`/app/auth/login`)

**File**: `src/fastapi_app/static/html/auth/login.html`
**Elements**: 7

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `login-form` | `login-form` | form | Login form container |
| `email` | `login-email-input` | input[email] | Email address field |
| `password` | `login-password-input` | input[password] | Password field |
| `login-button` | `login-submit-btn` | button | Submit login |
| `loading` | `login-loading-spinner` | div | Loading indicator |
| `error-message` | `login-error-message` | div | Error display |
| `success-message` | `login-success-message` | div | Success display |

**Links** (add testids):

| Element | Proposed data-testid | Purpose |
|---------|---------------------|---------|
| Register link | `login-register-link` | Navigate to registration |

---

## Page 2: Register (`/app/auth/register`)

**File**: `src/fastapi_app/static/html/auth/register.html`
**Elements**: 15

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `register-form` | `register-form` | form | Registration form container |
| `email` | `register-email-input` | input[email] | Email address field |
| `password` | `register-password-input` | input[password] | Password field |
| `confirm-password` | `register-confirm-password-input` | input[password] | Confirm password field |
| `strength-meter-fill` | `register-strength-meter` | div | Password strength bar |
| `strength-text` | `register-strength-text` | span | Strength level text |
| `req-length` | `register-req-length` | li | Length requirement indicator |
| `req-uppercase` | `register-req-uppercase` | li | Uppercase requirement |
| `req-lowercase` | `register-req-lowercase` | li | Lowercase requirement |
| `req-number` | `register-req-number` | li | Number requirement |
| `req-special` | `register-req-special` | li | Special char requirement |
| `register-button` | `register-submit-btn` | button | Submit registration |
| `loading` | `register-loading-spinner` | div | Loading indicator |
| `error-message` | `register-error-message` | div | Error display |
| `success-message` | `register-success-message` | div | Success display |

---

## Page 3: Change Password (`/app/auth/change-password`)

**File**: `src/fastapi_app/static/html/auth/change-password.html`
**Elements**: 14

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `password-form` | `change-pwd-form` | form | Password change form |
| `current-password` | `change-pwd-current-input` | input[password] | Current password |
| `new-password` | `change-pwd-new-input` | input[password] | New password |
| `strength-bar` | `change-pwd-strength-meter` | div | New password strength bar |
| `req-length` | `change-pwd-req-length` | li | Length requirement |
| `req-uppercase` | `change-pwd-req-uppercase` | li | Uppercase requirement |
| `req-lowercase` | `change-pwd-req-lowercase` | li | Lowercase requirement |
| `req-number` | `change-pwd-req-number` | li | Number requirement |
| `confirm-password` | `change-pwd-confirm-input` | input[password] | Confirm new password |
| `submit-button` | `change-pwd-submit-btn` | button | Submit password change |
| — (inline onclick) | `change-pwd-cancel-btn` | button | Cancel / go back |
| `loading` | `change-pwd-loading-spinner` | div | Loading indicator |
| `error-message` | `change-pwd-error-message` | div | Error display |
| `success-message` | `change-pwd-success-message` | div | Success display |

---

## Page 4: Profile (`/app/auth/profile`)

**File**: `src/fastapi_app/static/html/auth/profile.html`
**Elements**: 16

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `user-email` | `profile-user-email` | span | User's email display |
| `user-id` | `profile-user-id` | span | User's ID display |
| `user-roles` | `profile-user-roles` | div | Role badges |
| `email-verified` | `profile-email-verified` | span | Verification status |
| `account-status` | `profile-account-status` | span | Active/inactive status |
| — (inline onclick) | `profile-change-pwd-btn` | button | Navigate to change password |
| — (inline onclick) | `profile-logout-btn` | button | Logout action |
| `admin-section` | `profile-admin-section` | div | Admin tools section (hidden for non-admin) |
| — (inline onclick) | `profile-admin-dashboard-btn` | button | Navigate to admin dashboard |
| — (inline onclick) | `profile-admin-users-btn` | button | Navigate to user management |
| — (inline onclick) | `profile-admin-snapshots-btn` | button | Navigate to snapshots |
| — (inline onclick) | `profile-admin-ratify-btn` | button | Navigate to ratification |
| — (inline onclick) | `profile-admin-trust-btn` | button | Navigate to trust dashboard |
| `loading` | `profile-loading-spinner` | div | Loading indicator |
| `error-message` | `profile-error-message` | div | Error display |
| `success-message` | `profile-success-message` | div | Success display |

---

## Page 5: Landing (`/app`)

**File**: `src/fastapi_app/static/html/landing.html`
**Elements**: 12

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `greeting` | `landing-greeting` | h2 | User greeting |
| `stat-time-saved` | `landing-stat-time-saved` | span | Time saved statistic |
| `stat-replays` | `landing-stat-replays` | span | Replays statistic |
| `admin-section` | `landing-admin-section` | div | Admin cards (hidden for non-admin) |
| — (card link) | `landing-card-notifications` | a/button | Navigate to notifications |
| — (card link) | `landing-card-profile` | a/button | Navigate to profile |
| — (card link) | `landing-card-users` | a/button | Navigate to user management (admin) |
| — (card link) | `landing-card-snapshots` | a/button | Navigate to snapshots (admin) |
| — (card link) | `landing-card-ratify` | a/button | Navigate to ratification (admin) |
| — (card link) | `landing-card-trust` | a/button | Navigate to trust dashboard (admin) |
| — (card link) | `landing-card-dev-tools` | a/button | Navigate to dev tools (admin) |

---

## Page 6: Notifications (`/app/notifications`)

**File**: `src/fastapi_app/static/html/notifications.html`
**Elements**: ~95 (largest page — 11 collapsible sections)

### Section Toolbar (11 buttons)

| Existing Attr | Proposed data-testid | Element Type | Purpose |
|---------------|---------------------|--------------|---------|
| `data-section="section-qa"` | `notifications-toolbar-qa` | button | Toggle Q&A section |
| `data-section="section-job-submit"` | `notifications-toolbar-jobs` | button | Toggle Job Submission |
| `data-section="action-required-section"` | `notifications-toolbar-action` | button | Toggle Action Required |
| `data-section="tts-queue-section"` | `notifications-toolbar-tts` | button | Toggle TTS Queue |
| `data-section="section-notifications"` | `notifications-toolbar-notifs` | button | Toggle Notifications |
| `data-section="filter-settings-section"` | `notifications-toolbar-filters` | button | Toggle Filter Settings |
| `data-section="section-queues"` | `notifications-toolbar-queues` | button | Toggle Job Queues |
| `data-section="section-time-saved"` | `notifications-toolbar-time` | button | Toggle Time Saved |
| `data-section="section-status"` | `notifications-toolbar-status` | button | Toggle System Status |
| `data-section="section-direct-tts"` | `notifications-toolbar-direct-tts` | button | Toggle Direct TTS |
| `data-section="section-debug"` | `notifications-toolbar-debug` | button | Toggle Debug Info |

### Q&A Section

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `agent-mode` | `notifications-qa-mode-select` | select | Agent mode selector |
| `qa-stt-button` | `notifications-qa-stt-btn` | button | Speech-to-text |
| `qa-input` | `notifications-qa-input` | input[text] | Question input |
| `tts-mode` | `notifications-qa-tts-mode-select` | select | TTS mode |
| `submit-qa` | `notifications-qa-submit-btn` | button | Submit question |
| `qa-metrics` | `notifications-qa-metrics` | div | Q&A metrics display |

### Claude Code Dispatcher Card

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `claude-code-submit-card` | `notifications-cc-card` | div | Card container |
| `cc-project` | `notifications-cc-project-select` | select | Project selector |
| `cc-stt-button` | `notifications-cc-stt-btn` | button | Speech-to-text |
| `cc-prompt` | `notifications-cc-prompt-textarea` | textarea | Prompt input |
| `cc-task-type` | `notifications-cc-task-type-select` | select | Task type |
| `cc-execution-mode` | `notifications-cc-execution-mode-select` | select | Execution mode |
| `cc-dry-run` | `notifications-cc-dry-run-checkbox` | input[checkbox] | Dry run toggle |
| `cc-submit` | `notifications-cc-submit-btn` | button | Submit job |
| `cc-response` | `notifications-cc-response` | pre | Response display |
| `cc-inject-input` | `notifications-cc-inject-input` | input[text] | Follow-up input |
| `cc-inject-btn` | `notifications-cc-inject-btn` | button | Inject message |
| `cc-interrupt-btn` | `notifications-cc-interrupt-btn` | button | Interrupt session |
| `cc-end-btn` | `notifications-cc-end-btn` | button | End session |
| `cc-session-info` | `notifications-cc-session-info` | div | Session info display |

### Research Submission Card

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `research-topic` | `notifications-research-topic-input` | input[text] | Research topic |
| `research-stt-button` | `notifications-research-stt-btn` | button | Speech-to-text |
| `research-budget` | `notifications-research-budget-input` | input[number] | Budget ($0.50-$20) |
| `research-with-podcast` | `notifications-research-podcast-checkbox` | input[checkbox] | Include podcast |
| `research-dry-run` | `notifications-research-dry-run-checkbox` | input[checkbox] | Dry run |
| `submit-research-job` | `notifications-research-submit-btn` | button | Submit research |

### Podcast Submission Card

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `podcast-source` | `notifications-podcast-source-input` | input[text] | Source URL/text |
| `podcast-stt-button` | `notifications-podcast-stt-btn` | button | Speech-to-text |
| `podcast-dry-run` | `notifications-podcast-dry-run-checkbox` | input[checkbox] | Dry run |
| `submit-podcast-job` | `notifications-podcast-submit-btn` | button | Submit podcast |

### SWE Team Submission Card

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `swe-task` | `notifications-swe-task-textarea` | textarea | Task description |
| `swe-stt-button` | `notifications-swe-stt-btn` | button | Speech-to-text |
| `swe-budget` | `notifications-swe-budget-input` | input[number] | Budget |
| `swe-timeout` | `notifications-swe-timeout-input` | input[number] | Timeout |
| `swe-dry-run` | `notifications-swe-dry-run-checkbox` | input[checkbox] | Dry run |
| `swe-trust-mode` | `notifications-swe-trust-mode-select` | select | Trust mode |
| `submit-swe-job` | `notifications-swe-submit-btn` | button | Submit SWE job |

### Action Required Section

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `action-required-section` | `notifications-action-section` | div | Section container |
| `action-required-active-slot` | `notifications-action-active-slot` | div | Active notification |
| `action-required-pending-queue` | `notifications-action-pending-queue` | div | Pending notifications |

### TTS Queue Section

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `tts-pause-btn` | `notifications-tts-pause-btn` | button | Pause TTS |
| `tts-play-btn` | `notifications-tts-play-btn` | button | Resume TTS |
| `tts-clear-all-btn` | `notifications-tts-clear-btn` | button | Clear TTS queue |
| `tts-active-slot` | `notifications-tts-active-slot` | div | Currently playing |
| `tts-pending-queue` | `notifications-tts-pending-queue` | div | Pending TTS queue |

### Queue Filter Settings

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `filter-own-jobs` | `notifications-filter-own-btn` | button | My Jobs Only |
| `filter-all-jobs` | `notifications-filter-all-btn` | button | All Users' Jobs |

### Job Queues Section

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `queue-category-todo` | `notifications-queue-todo` | div | Todo queue |
| `todo-expand` | `notifications-queue-todo-expand-btn` | button | Toggle todo |
| `todo-jobs-container` | `notifications-queue-todo-jobs` | div | Todo job list |
| `queue-category-run` | `notifications-queue-running` | div | Running queue |
| `run-expand` | `notifications-queue-running-expand-btn` | button | Toggle running |
| `queue-category-done` | `notifications-queue-done` | div | Done queue |
| `done-expand` | `notifications-queue-done-expand-btn` | button | Toggle done |
| `queue-category-dead` | `notifications-queue-dead` | div | Dead queue |
| `dead-expand` | `notifications-queue-dead-expand-btn` | button | Toggle dead |

### Time Saved Dashboard

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `time-saved-total` | `notifications-time-total` | span | Total time saved |
| `time-saved-others` | `notifications-time-others` | span | Time saved for others |
| `solutions-created` | `notifications-solutions-created` | span | Solutions count |
| `replays-benefited` | `notifications-replays-benefited` | span | Replays count |
| `top-solutions-list` | `notifications-top-solutions` | div | Top solutions list |

### System Status Section

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `refresh-status-btn` | `notifications-status-refresh-btn` | button | Refresh status |
| `queue-ws-status` | `notifications-ws-queue-status` | span | Queue WS indicator |
| `audio-ws-status` | `notifications-ws-audio-status` | span | Audio WS indicator |
| `auth-status` | `notifications-auth-status` | span | Auth status indicator |
| `logout-button` | `notifications-logout-btn` | button | Logout |
| `reinit-config-btn` | `notifications-config-reload-btn` | button | Reload config |

### Direct TTS Test Section

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `direct-tts-input` | `notifications-direct-tts-input` | input[text] | TTS text input |
| `direct-tts-button` | `notifications-direct-tts-btn` | button | Submit TTS |
| `test-instant-tts` | `notifications-test-instant-tts-btn` | button | Test instant mode |
| `test-reliable-tts` | `notifications-test-reliable-tts-btn` | button | Test reliable mode |
| `stop-audio` | `notifications-stop-audio-btn` | button | Stop audio playback |

---

## Page 7: Admin Dashboard (`/app/admin`)

**File**: `src/fastapi_app/static/html/admin/dashboard.html`
**Elements**: 8

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `userEmail` | `admin-dash-user-email` | span | User email display |
| `logoutBtn` | `admin-dash-logout-btn` | button | Logout |
| — (breadcrumb) | `admin-dash-breadcrumb-home` | a | Home breadcrumb link |
| — (card) | `admin-dash-card-users` | a/div | User Management card |
| — (card) | `admin-dash-card-snapshots` | a/div | Solution Snapshots card |
| — (card) | `admin-dash-card-ratify` | a/div | Decision Ratification card |
| — (card) | `admin-dash-card-trust` | a/div | Trust Dashboard card |

---

## Page 8: Solution Snapshots (`/app/admin/snapshots`)

**File**: `src/fastapi_app/static/html/admin/snapshots.html`
**Elements**: 30

### Header & Navigation

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `user-email` | `snapshots-user-email` | span | User email |
| `logout-btn` | `snapshots-logout-btn` | button | Logout |
| — (breadcrumb) | `snapshots-breadcrumb-home` | a | Home link |
| — (breadcrumb) | `snapshots-breadcrumb-admin` | a | Admin link |

### Search Section

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `search-stt-button` | `snapshots-search-stt-btn` | button | Speech-to-text |
| `search-input` | `snapshots-search-input` | input[text] | Search query |
| `threshold-select` | `snapshots-threshold-select` | select | Similarity threshold |
| `limit-select` | `snapshots-limit-select` | select | Result limit |
| `search-btn` | `snapshots-search-btn` | button | Execute search |
| `results-count` | `snapshots-results-count` | span | Results counter |

### Results Table

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `results-tbody` | `snapshots-results-table` | tbody | Results table body |

### Detail Modal

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `detail-modal` | `modal-snapshot-detail` | div | Detail modal container |
| `detail-question-normalized` | `modal-snapshot-question` | div | Normalized question |
| `detail-question-gist` | `modal-snapshot-gist` | div | Question gist |
| `detail-answer` | `modal-snapshot-answer` | div | Answer |
| `detail-answer-conversational` | `modal-snapshot-conversational` | div | Conversational answer |
| `synonyms-toggle` | `modal-snapshot-synonyms-toggle-btn` | button | Toggle synonyms |
| `detail-runtime-stats` | `modal-snapshot-runtime-stats` | pre | Runtime stats |
| `detail-code` | `modal-snapshot-code` | pre | Code |
| `detail-solution-summary` | `modal-snapshot-summary` | div | Solution summary |
| `detail-solution-summary-gist` | `modal-snapshot-summary-gist` | div | Summary gist |
| `detail-id-hash` | `modal-snapshot-id-hash` | span | ID hash |
| `detail-user-id` | `modal-snapshot-user-id` | span | User ID |
| `detail-created-date` | `modal-snapshot-created-date` | span | Created date |
| `find-similar-btn` | `modal-snapshot-find-similar-btn` | button | Find similar |

### Similarity Modal

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `similarity-modal` | `modal-snapshot-similarity` | div | Similarity modal |
| `code-similar-count` | `modal-similarity-code-count` | span | Code match count |
| `explanation-similar-count` | `modal-similarity-explanation-count` | span | Explanation match count |
| `solution-gist-similar-count` | `modal-similarity-gist-count` | span | Gist match count |

### Delete Confirmation Modal

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `delete-modal` | `modal-snapshot-delete` | div | Delete confirmation |
| `confirm-delete-btn` | `modal-snapshot-delete-confirm-btn` | button | Confirm delete |
| `cancel-delete-btn` | `modal-snapshot-delete-cancel-btn` | button | Cancel delete |

---

## Page 9: User Management (`/app/admin/users`)

**File**: `src/fastapi_app/static/html/auth/admin/users.html`
**Elements**: 24

### Search & Filter Bar

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `user-search` | `admin-users-search-input` | input[text] | Search by email |
| `role-filter` | `admin-users-role-filter-select` | select | Filter by role |
| `status-filter` | `admin-users-status-filter-select` | select | Filter by status |
| — (button) | `admin-users-clear-filters-btn` | button | Clear all filters |
| — (button) | `admin-users-back-btn` | button | Back to profile |

### Users Table & Pagination

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `users-tbody` | `admin-users-table` | tbody | Users table body |
| `prev-page` | `admin-users-prev-page-btn` | button | Previous page |
| `next-page` | `admin-users-next-page-btn` | button | Next page |
| `page-info` | `admin-users-page-info` | span | Page counter |

### User Detail Modal

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `user-modal` | `modal-user-detail` | div | User detail modal |
| — (button) | `modal-user-detail-close-btn` | button | Close modal |
| — (button) | `modal-user-detail-edit-roles-btn` | button | Edit roles |
| — (button) | `modal-user-detail-toggle-status-btn` | button | Toggle status |
| — (button) | `modal-user-detail-reset-pwd-btn` | button | Reset password |

### Role Editor Modal

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `role-modal` | `modal-role-editor` | div | Role editor modal |
| `role-admin` | `modal-role-admin-checkbox` | input[checkbox] | Admin role toggle |
| `role-user` | `modal-role-user-checkbox` | input[checkbox] | User role toggle |
| — (button) | `modal-role-save-btn` | button | Save roles |
| — (button) | `modal-role-cancel-btn` | button | Cancel |

### Password Reset Modal

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `password-modal` | `modal-password-reset` | div | Password reset modal |
| `temp-password` | `modal-password-reset-temp` | input[text] | Temp password display |
| — (button) | `modal-password-reset-copy-btn` | button | Copy to clipboard |
| — (button) | `modal-password-reset-done-btn` | button | Done/close |

### Confirmation Dialog

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `confirm-modal` | `modal-user-confirm` | div | Confirmation dialog |
| — (button) | `modal-user-confirm-yes-btn` | button | Confirm action |
| — (button) | `modal-user-confirm-no-btn` | button | Cancel action |

---

## Page 10: Decision Ratification (`/app/admin/proxy-ratify`)

**File**: `src/fastapi_app/static/html/auth/admin/proxy-ratify.html`
**Elements**: 25

### Summary Cards

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `stat-pending` | `ratify-stat-pending` | span | Pending count |
| `stat-approved` | `ratify-stat-approved` | span | Approved today |
| `stat-rejected` | `ratify-stat-rejected` | span | Rejected today |
| `stat-oldest` | `ratify-stat-oldest` | span | Oldest pending |

### Filter Bar

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `filter-category` | `ratify-filter-category-select` | select | Category filter |
| `filter-trust-level` | `ratify-filter-trust-select` | select | Trust level filter |
| `filter-action` | `ratify-filter-action-select` | select | Action filter |
| — (button) | `ratify-clear-filters-btn` | button | Clear filters |
| — (breadcrumb) | `ratify-breadcrumb-home` | a | Home link |
| — (breadcrumb) | `ratify-breadcrumb-admin` | a | Admin link |
| — (button) | `ratify-back-btn` | button | Back to admin |

### Bulk Actions

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `select-all` | `ratify-select-all-checkbox` | input[checkbox] | Select all |
| `selected-count` | `ratify-selected-count` | span | Selection counter |
| — (button) | `ratify-bulk-approve-btn` | button | Approve selected |
| — (button) | `ratify-bulk-reject-btn` | button | Reject selected |

### Decisions Table & Pagination

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `decisions-tbody` | `ratify-decisions-table` | tbody | Decisions table |
| — (button) | `ratify-prev-page-btn` | button | Previous page |
| — (button) | `ratify-next-page-btn` | button | Next page |
| `page-info` | `ratify-page-info` | span | Page counter |

### Decision Detail Modal

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `detail-modal` | `modal-ratify-detail` | div | Decision detail modal |
| `feedback-text` | `modal-ratify-feedback-textarea` | textarea | Feedback input |
| `modal-approve-btn` | `modal-ratify-approve-btn` | button | Approve decision |
| `modal-reject-btn` | `modal-ratify-reject-btn` | button | Reject decision |
| — (button) | `modal-ratify-cancel-btn` | button | Cancel |

### Bulk Reject Confirmation

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `confirm-modal` | `modal-ratify-confirm` | div | Confirm modal |
| `confirm-yes` | `modal-ratify-confirm-yes-btn` | button | Confirm reject |
| — (button) | `modal-ratify-confirm-no-btn` | button | Cancel |

---

## Page 11: Trust Dashboard (`/app/admin/proxy-dashboard`)

**File**: `src/fastapi_app/static/html/auth/admin/proxy-dashboard.html`
**Elements**: 15

### Header & Navigation

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| — (breadcrumb) | `trust-breadcrumb-home` | a | Home link |
| — (breadcrumb) | `trust-breadcrumb-admin` | a | Admin link |
| — (button) | `trust-back-btn` | button | Back to admin |

### Mode Controls

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `mode-trust-select` | `trust-mode-select` | select | Trust mode selector |
| `mode-domain` | `trust-mode-domain` | span | Current domain |
| `mode-user` | `trust-mode-user` | span | Current user |

### Dashboard Content

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `trust-cards-grid` | `trust-cards-grid` | div | Trust cards container |

### Recent Decisions

| Existing ID | Proposed data-testid | Element Type | Purpose |
|-------------|---------------------|--------------|---------|
| `category-selector` | `trust-category-select` | select | Category filter |
| `decisions-tbody` | `trust-decisions-table` | tbody | Decisions table |
| — (button) | `trust-prev-page-btn` | button | Previous page |
| — (button) | `trust-next-page-btn` | button | Next page |
| `page-info` | `trust-page-info` | span | Page counter |

---

## Page 12: Dev Tools (`/app/admin/dev-tools`)

**File**: `src/fastapi_app/static/html/dev-tools.html`
**Elements**: 14

| Element | Proposed data-testid | Element Type | Purpose |
|---------|---------------------|--------------|---------|
| WebSocket Diagnostics | `devtools-link-ws-diagnostics` | a | WS diagnostics page |
| Event Subscription | `devtools-link-event-subscription` | a | Event sub test |
| Session Persistence | `devtools-link-session-persistence` | a | Session test |
| Session Cleanup | `devtools-link-session-cleanup` | a | Cleanup test |
| Heartbeat Cleanup | `devtools-link-heartbeat-cleanup` | a | Heartbeat test |
| Audio Test | `devtools-link-audio-test` | a | Audio test page |
| Audio Hybrid Mode | `devtools-link-audio-hybrid` | a | Hybrid audio test |
| TTS WebSocket Routing | `devtools-link-tts-routing` | a | TTS routing test |
| Hybrid TTS Module | `devtools-link-tts-hybrid` | a | Hybrid TTS test |
| TTS Cache Test | `devtools-link-tts-cache` | a | TTS cache test |
| Experimental TTS | `devtools-link-tts-experimental` | a | Experimental TTS |
| Chunk Sequencing | `devtools-link-chunk-sequencing` | a | Chunk test |
| PCM Streaming Demo | `devtools-link-pcm-streaming` | a | PCM demo |
| Notification Sounds | `devtools-link-notification-sounds` | a | Sound test |

---

## Shared Component: Navigation Bar (`lupin-nav.js`)

**File**: `src/fastapi_app/static/js/lupin-nav.js`
**Elements**: 12

| Existing Class/Element | Proposed data-testid | Element Type | Purpose |
|-----------------------|---------------------|--------------|---------|
| `.lupin-nav-brand` | `nav-home-link` | a | Home / brand link |
| `.lupin-nav-toggle` | `nav-mobile-toggle-btn` | button | Mobile hamburger menu |
| Notifications link | `nav-notifications-link` | a | Navigate to notifications |
| Profile link | `nav-profile-link` | a | Navigate to profile |
| Admin link | `nav-admin-link` | a | Navigate to admin (admin only) |
| Users link | `nav-admin-users-link` | a | Navigate to users (admin only) |
| Snapshots link | `nav-admin-snapshots-link` | a | Navigate to snapshots (admin only) |
| Ratification link | `nav-admin-ratify-link` | a | Navigate to ratification (admin only) |
| Trust link | `nav-admin-trust-link` | a | Navigate to trust dashboard (admin only) |
| Dev Tools link | `nav-admin-devtools-link` | a | Navigate to dev tools (admin only) |
| `.lupin-nav-email` | `nav-user-email` | span | User email display |
| `.lupin-nav-logout` | `nav-logout-btn` | button | Logout button |
| `.lupin-nav-login` | `nav-login-link` | a | Login link (unauthenticated) |

---

## Summary

| Page | File | Elements | Modals |
|------|------|----------|--------|
| Login | `auth/login.html` | 8 | 0 |
| Register | `auth/register.html` | 15 | 0 |
| Change Password | `auth/change-password.html` | 14 | 0 |
| Profile | `auth/profile.html` | 16 | 0 |
| Landing | `landing.html` | 12 | 0 |
| Notifications | `notifications.html` | ~95 | 0 |
| Admin Dashboard | `admin/dashboard.html` | 8 | 0 |
| Snapshots | `admin/snapshots.html` | 30 | 3 |
| User Management | `auth/admin/users.html` | 24 | 4 |
| Ratification | `auth/admin/proxy-ratify.html` | 25 | 2 |
| Trust Dashboard | `auth/admin/proxy-dashboard.html` | 15 | 0 |
| Dev Tools | `dev-tools.html` | 14 | 0 |
| **Nav Component** | `js/lupin-nav.js` | **13** | **0** |
| **TOTAL** | **13 files** | **~189** | **9** |
