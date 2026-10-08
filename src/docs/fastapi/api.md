# Lupin FastAPI

A FastAPI migration of the Lupin agent system

## 🌍 Base URL


| URL | Description |
|-----|-------------|


## 🔐 Authentication



## Security Schemes

| Name              | Type              | Description              | Scheme              | Bearer Format             |
|-------------------|-------------------|--------------------------|---------------------|---------------------------|
| HTTPBearerWith401 | http |  | bearer |  |
| HTTPBearer | http |  | bearer |  |

# 🛠️ APIs

## POST `/auth/register`

> **Register new user**

Create new user account with email and password. Returns user info and JWT token pair.





### 📦 Request Body 

[RegisterRequest](#registerrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 201 | Successful Response | [RegisterResponse](#registerresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/auth/login`

> **User login**

Authenticate user with email and password. Returns user info and JWT token pair. Includes rate limiting and account lockout (Phase 8).





### 📦 Request Body 

[LoginRequest](#loginrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [LoginResponse](#loginresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/auth/refresh`

> **Refresh access token**

Exchange refresh token for new token pair. Old refresh token is revoked (token rotation).





### 📦 Request Body 

[RefreshRequest](#refreshrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [RefreshResponse](#refreshresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/auth/logout`

> **User logout**

Revoke refresh token to logout user. Access token remains valid until expiration.





### 📦 Request Body 

[LogoutRequest](#logoutrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [LogoutResponse](#logoutresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/auth/me`

> **Get current user**

Get current user information from access token. Requires Authorization header.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [UserResponse](#userresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PUT `/auth/change-password`

> **Change password**

Change password for authenticated user. Requires current password verification.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### 📦 Request Body 

[ChangePasswordRequest](#changepasswordrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [cosa__rest__auth_models__MessageResponse](#cosa__rest__auth_models__messageresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/auth/request-verification`

> **Request email verification**

Resend email verification link to authenticated user.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [cosa__rest__auth_models__MessageResponse](#cosa__rest__auth_models__messageresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/auth/verify-email`

> **Verify email address**

Verify email address using token from verification email.





### 📦 Request Body 

[VerifyEmailRequest](#verifyemailrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [cosa__rest__auth_models__MessageResponse](#cosa__rest__auth_models__messageresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/auth/request-password-reset`

> **Request password reset**

Send password reset email to user. Returns success even if email not found (security).





### 📦 Request Body 

[RequestPasswordResetRequest](#requestpasswordresetrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [cosa__rest__auth_models__MessageResponse](#cosa__rest__auth_models__messageresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/auth/reset-password`

> **Reset password**

Reset password using token from password reset email.





### 📦 Request Body 

[cosa__rest__auth_models__ResetPasswordRequest](#cosa__rest__auth_models__resetpasswordrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [cosa__rest__auth_models__MessageResponse](#cosa__rest__auth_models__messageresponse)
 |
| 401 | Unauthorized | [ErrorResponse](#errorresponse)
 |
| 400 | Bad Request | [ErrorResponse](#errorresponse)
 |
| 500 | Internal Server Error | [ErrorResponse](#errorresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/admin/users`

> **List all users**

Get paginated list of users with optional filters. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| limit | integer | False |  |
| offset | integer | False |  |
| search |  | False |  |
| role |  | False |  |
| status_filter |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [UserListResponse](#userlistresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/admin/users`

> **Create new user**

Create a new user account with specified roles. Auto-verifies email. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### 📦 Request Body 

[CreateUserRequest](#createuserrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 201 | Successful Response | [CreateUserResponse](#createuserresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/admin/users/{user_id}`

> **Get user details**

Get detailed information for specific user. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_id | string | True |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [UserDetailsResponse](#userdetailsresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/admin/users/{user_id}`

> **Delete user**

Permanently delete user account. Cannot delete self or sole admin. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_id | string | True |  |
| authorization |  | False |  |


### 📦 Request Body 



### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [cosa__rest__routers__admin__MessageResponse](#cosa__rest__routers__admin__messageresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PUT `/admin/users/{user_id}/roles`

> **Update user roles**

Update roles for specific user. Prevents self-demotion. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_id | string | True |  |
| authorization |  | False |  |


### 📦 Request Body 

[UpdateRolesRequest](#updaterolesrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [cosa__rest__routers__admin__MessageResponse](#cosa__rest__routers__admin__messageresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PUT `/admin/users/{user_id}/status`

> **Toggle user status**

Activate or deactivate user account. Prevents self-deactivation. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_id | string | True |  |
| authorization |  | False |  |


### 📦 Request Body 

[UpdateStatusRequest](#updatestatusrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [cosa__rest__routers__admin__MessageResponse](#cosa__rest__routers__admin__messageresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/admin/users/{user_id}/reset-password`

> **Admin password reset**

Generate temporary password for user. Password shown once only. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_id | string | True |  |
| authorization |  | False |  |


### 📦 Request Body 

[cosa__rest__routers__admin__ResetPasswordRequest](#cosa__rest__routers__admin__resetpasswordrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [ResetPasswordResponse](#resetpasswordresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/admin/users/batch-delete`

> **Batch delete users**

Delete multiple user accounts at once. Reuses single-user safety checks. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### 📦 Request Body 

[BatchDeleteUsersRequest](#batchdeleteusersrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [BatchDeleteUsersResponse](#batchdeleteusersresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/admin/snapshots/search`

> **Search solution snapshots**

Search snapshots by question text using vector similarity. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| q | string | True |  |
| threshold | number | False |  |
| limit | integer | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [SearchSnapshotsResponse](#searchsnapshotsresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/admin/snapshots/{id_hash}`

> **Get snapshot details**

Retrieve full snapshot details by ID. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| id_hash | string | True |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [SnapshotDetailResponse](#snapshotdetailresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/admin/snapshots/{id_hash}`

> **Delete snapshot**

Permanently delete snapshot from database. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| id_hash | string | True |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [cosa__rest__routers__admin__MessageResponse](#cosa__rest__routers__admin__messageresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/admin/snapshots/{id_hash}/preview`

> **Get snapshot preview**

Get code and explanation preview for hover display. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| id_hash | string | True |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [SnapshotPreviewResponse](#snapshotpreviewresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/admin/snapshots/{id_hash}/similar`

> **Find similar snapshots**

Find snapshots with similar code or explanation. Requires admin role.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| id_hash | string | True |  |
| code_threshold | number | False |  |
| explanation_threshold | number | False |  |
| limit | integer | False |  |
| ensure_top_result | boolean | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [SimilarSnapshotsResponse](#similarsnapshotsresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/admin/admin/refresh-source`

> **Force test server to reload source (test env only)**

Re-execs the uvicorn process in place so bind-mounted source edits take effect. Gated by LUPIN_ENV in {test,testing} AND config 'admin refresh source enabled'. Discards in-memory state.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 202 | Successful Response | [RefreshSourceResponse](#refreshsourceresponse)
 |
| 401 | Unauthorized |  |
| 403 | Forbidden - Admin role required |  |
| 404 | Not Found |  |
| 500 | Internal Server Error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/`

> **Root health check**

Basic health check returning service name, status, version, and timestamp.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/health`

> **Lightweight health check**

Minimal health endpoint for high-frequency monitoring. Returns status and timestamp.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/busy`

> **Is a job running on this server right now?**

Queue occupancy for the managed-bounce guard (row 08919110) and the venue-idle check (row e6b8fe56): inflight_agentic_jobs, run_queue_size, todo_queue_size and the monopolize slot. Unauthenticated by design so a host shell script can read it with no credential, and UNFILTERED — unlike /api/get-queue/{q}, which shows only the caller's own jobs. Adds nothing to /health.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/code-identity`

> **Which code is this process actually running?**

The git sha, branch and load time captured at MODULE IMPORT — not re-read per request.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/server-info`

> **Get server info**

Return current config block ID, masked database URL, and environment name.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/init`

> **Hot-reload configuration**

Reload configuration and optionally swap active config block and database connection at runtime. ADMIN ONLY.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| config_block_id |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 401 | Unauthorized — no bearer token |  |
| 403 | Forbidden — the admin role is required |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/prediction-engine/reset`

> **Reset PredictionEngine singleton**

Destroy and re-create the PredictionEngine singleton with current config. Used by integration tests to ensure LanceDB table isolation between tests. Requires a credential; clears the decision rows only when drop_table is passed true.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| drop_table | boolean | False |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 401 | Unauthorized — no valid API key or bearer token |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/get-session-id`

> **Generate session ID**

Generate and return a unique two-word session ID for WebSocket routing.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/auth-test`

> **Auth Test**

Test endpoint to verify authentication is working.

Example usage:
curl -H "Authorization: Bearer mock_token_alice" http://localhost:8000/api/auth-test

Returns:
    dict: Current user information





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/websocket-sessions`

> **List WebSocket sessions**

Return all active WebSocket sessions with total and per-user connection counts.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/websocket-sessions/cleanup`

> **Cleanup stale sessions**

Trigger manual cleanup of sessions older than specified max age.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| max_age_hours |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/debug/websocket-state`

> **Debug WebSocket state**

Expose complete internal WebSocket manager state for troubleshooting. Debug endpoint.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/config/client`

> **Get client config**

Return client-side timing configuration including token refresh, heartbeat, and timezone.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/config/similarity-confirmation`

> **Get similarity confirmation toggle**

Return the current runtime state of the similarity confirmation feature.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/config/similarity-confirmation`

> **Set similarity confirmation toggle**

Toggle the similarity confirmation feature at runtime. Returns new and previous values.





### 📦 Request Body 

[SimilarityConfirmationRequest](#similarityconfirmationrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/system/bounce`

> **Bounce the dev server**

Request a managed restart of :7999 via the host-side watcher. Warns the fleet, restarts the container, and the restarted server self-emits the all-clear.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/notify`

> **Send notification**

Dispatch notification to a user via WebSocket. Supports fire-and-forget or SSE blocking mode for response-required notifications.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| message | string | True | Notification message text |
| type | string | False | Notification type (task, progress, alert, custom) |
| direction | string | False | Communication direction (provenance axis, orthogonal to type): human_to_ai | ai_to_ai | ai_to_human. Defaults to ai_to_human (AI speaking to the user). |
| priority | string | False | Priority level (low, medium, high, urgent) |
| target_user | string | True | Target user email address (required - configure in CLI config or pass explicitly) |
| response_requested | boolean | False | Whether notification requires user response (Phase 2.1) |
| response_type |  | False | Response type: yes_no or open_ended (Phase 2.1) |
| timeout_seconds | integer | False | Timeout in seconds for response-required notifications |
| response_default |  | False | Default response value for timeout/offline (Phase 2.1) |
| human_only | boolean | False | Reserve this ask for a HUMAN (or its offline default) only — the auto-answer proxy must NOT answer it. Rides the WS event so the NotificationProxy Responder skips it (row 804afce6). |
| title |  | False | Terse technical title for voice-first UX (Phase 2.1) |
| sender_id |  | False | Sender ID (e.g., claude.code@lupin.deepily.ai). Auto-extracted from [PREFIX] in message if not provided. |
| response_options |  | False | JSON string of options for multiple_choice type. Structure: {questions: [{question, header, multi_select, options: [{label, description}]}]} |
| abstract |  | False | Supplementary context for the notification (plan details, URLs, markdown). Displayed alongside message in action-required cards. |
| job_id |  | False | Agentic job ID for routing to job cards (e.g., dr-a1b2c3d4, mock-12345678) |
| queue_name |  | False | Queue where job is running (run/todo/done). Used for provisional job card registration when notifications arrive before job is fetched. |
| suppress_ding | boolean | False | Suppress notification sound (ding) while still speaking message via TTS. Used for conversational TTS from queue operations. |
| progress_group_id |  | False | Progress group ID for in-place DOM updates. Notifications sharing this ID update a single element instead of appending new ones. |
| prediction_hint_override |  | False | JSON override for prediction_hint (testing/debug). Bypasses PredictionEngine. |
| display_qualifier_widget | boolean | False | Render yes/no qualifier comment widget expanded by default with softer instructional text. |
| session_name |  | False | Human-readable session name for UI header display. Updates sender-session-name span in notification history card. |
| idempotency_key |  | False | UUID idempotency key to prevent duplicate notifications on retry. Same key = same notification, skip push/persist. |
| persist | boolean | False | Whether to persist a forensic DB row (default True — byte-identical prior behavior). Set False for delivery-only re-attempts (e.g. arbiter re-announce-on-return) so repeated retries of an already-persisted advisory never mint duplicate rows (bug e1bbe011). Live WebSocket delivery + the offline/online outcome are unaffected; only the DB insert is skipped. |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/notify/response`

> **Submit notification response**

Submit user response to a response-required notification. Signals the waiting SSE stream and persists to PostgreSQL.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

object

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/undelivered`

> **Get undelivered (missed) notifications**

Pull-able AFK inbox (messaging-coordination plane, lever D): the authenticated user's notifications that never reached them (state created/queued) — what they missed while offline.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| limit | integer | False | Maximum undelivered notifications to return |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/answers-owed`

> **Get answers owed to a persona (late-answer handback pull inbox)**

Persona-keyed pull inbox (§4.4): answered asks not yet handed back to the session that asked. Retrieval matches sender_persona ALONE (ruling 6); session_hash8 sets the earlier-session flag but NEVER filters. Serving does NOT mark delivered — that is the companion /ack (ack-on-consume).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| persona | string | True | The persona whose owed answers to pull (retrieval key — ruling 6, matched alone). |
| session_hash8 |  | False | Requesting session's 8-char hash. Sets the earlier-session flag on each envelope; NEVER filters (ruling 6). |
| since |  | False | ISO responded_at cursor — only answers responded AFTER it. Cursor advances on responded_at, not created_at. |
| limit | integer | False | Maximum owed answers to return. |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/notifications/answers-owed/ack`

> **Ack a handed-back answer (mark delivered)**

Setter (b)/(c) of the §4.3 receipt-gated contract: stamp answer_delivered_at for a notification the client has CONSUMED. Ack on consume, never on serve — a dropped serve response must leave the answer owed. The row is never deleted (ruling 2).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

object

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/response/{notification_id}`

> **Read one notification's response state (re-attach poll target)**

PURE READ (§4.5 E-b) of {state, response_value, responded_at} for one notification. The MCP re-attach poll reads this after its SSE stream dies to learn whether the human answered. **No ack** — serving does NOT set answer_delivered_at; the ack is the explicit companion POST /answers-owed/ack. Registered BEFORE /notifications/{user_id} so the static path is not captured as a {user_id}.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| notification_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/notifications/undelivered/dismiss`

> **Dismiss (reset) undelivered notifications**

Reset the 'N missed while away' badge: soft-dismiss (is_hidden=True) the authenticated user's undelivered notifications (state created/queued). State is preserved (audit trail); the badge and pull-able inbox both drop to zero.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/notify/prediction-vote/{notification_id}`

> **Vote on a prediction hint (thumbs up/down → training signal)**

Record the user's 👍/👎 on a prediction hint. up→approved (reinforce in future CBR retrieval), down→rejected (negative vote — steer away). Writes one human-confirmed organic case into the prediction CBR store; idempotent per notification (re-vote flips state in place).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| notification_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[PredictionVoteRequest](#predictionvoterequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/broadcast-acks/{broadcast_id}`

> **Get the saved acks for one broadcast**

Rebuild one broadcast's ack tally from the SAVED notification rows — which seats acked, with what status, and when. One row per acking session, latest ack wins. Scoped to the authenticated account, which is the broadcast originator. Reads REGARDLESS of delivery state, so an ack that reached a live socket is still returned after a reload; this is not the undelivered inbox and does not share its skip-delivered filter.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| broadcast_id | string | True |  |
| limit | integer | False | Maximum ack rows to scan before the latest-per-session fold |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/{user_id}`

> **Get user notifications**

Retrieve notifications for a user from the in-memory FIFO queue, with an optional played filter, priority filter, ordering and count limit. Default order is QUEUE order, where urgent and high sit at the front; pass sort=oldest for creation order.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_id | string | True |  |
| include_played | boolean | False | Include played notifications |
| limit | integer | False | Maximum number of notifications to return |
| priorities |  | False | Keep only these priorities (urgent, high, medium, low), applied BEFORE the limit. Repeat the parameter or comma-separate the values. |
| sort | string | False | queue: the queue's order, urgent and high first. oldest: creation time, oldest first. |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/{user_id}/next`

> **Get next notification**

Fetch the next unplayed notification for a user without modifying its played state.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/notifications/{notification_id}/played`

> **Mark notification played**

Mark a notification as played with timestamp. Persists to the io_tbl database.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| notification_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/notifications/{notification_id}`

> **Delete notification**

Permanently remove a single notification from the FIFO queue and io_tbl database.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| notification_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/notifications/bulk/{user_email}`

> **Bulk delete notifications**

Delete all notifications for a user from PostgreSQL with optional time window filter.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_email | string | True |  |
| hours |  | False | Filter to notifications within N hours (None = all) |
| exclude_own_jobs | boolean | False | Only delete notifications NOT from user's own jobs (admin 'not mine' filter) |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/senders/{user_email}`

> **List notification senders**

Return all distinct senders who have sent notifications to a user with last activity and count.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_email | string | True |  |
| hours |  | False | Filter to senders active within N hours |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/conversation/{sender_id}/{user_email}`

> **Get sender conversation**

Retrieve time-windowed conversation thread between a specific sender and recipient.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| sender_id | string | True |  |
| user_email | string | True |  |
| hours | integer | False | Window size in hours (default: 24) |
| anchor |  | False | ISO timestamp to anchor window around |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/notifications/conversation/{sender_id}/{user_email}`

> **Delete sender conversation**

Permanently delete all notifications from a specific sender to a recipient.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| sender_id | string | True |  |
| user_email | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/conversation-by-date/{sender_id}/{user_email}`

> **Get conversation by date**

Return notifications grouped by date for accordion-style UI rendering.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| sender_id | string | True |  |
| user_email | string | True |  |
| hours | integer | False | Window size in hours (default: 168 = 7 days) |
| anchor |  | False | ISO timestamp to anchor window around |
| include_hidden | boolean | False | Include hidden/archived notifications |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/notifications/date/{sender_id}/{user_email}/{date_string}`

> **Soft-delete by date**

Soft-delete all notifications from a sender on a specific date by setting is_hidden flag.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| sender_id | string | True |  |
| user_email | string | True |  |
| date_string | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/sender-dates/{sender_id}/{user_email}`

> **Get sender date summaries**

Return lightweight date headers with counts for building accordion UI.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| sender_id | string | True |  |
| user_email | string | True |  |
| include_hidden | boolean | False | Include hidden/archived notifications |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/senders-visible/{user_email}`

> **List visible senders**

Enhanced sender list respecting is_hidden flag with unread counts for notification badges.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_email | string | True |  |
| hours |  | False | Filter to senders with activity within N hours |
| include_hidden | boolean | False | Include hidden notifications in counts |
| exclude_own_jobs | boolean | False | Exclude notifications from user's own jobs (admin 'not mine' filter) |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/active-conversation/{user_email}`

> **Get active conversation**

Return the sender_id of the most recent notification for voice response routing.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_email | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/project-sessions/{project}/{user_email}`

> **List project sessions**

Return all Claude Code sessions for a project with activity counts and active status.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| project | string | True |  |
| user_email | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/notifications/generate-gist`

> **Generate session gist**

Use LLM to generate a concise semantic session name from notification messages.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

object

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/upload-and-transcribe-mp3`

> **Transcribe MP3 audio**

Accept base64-encoded MP3 and transcribe via Whisper. An agent request goes to the v2 ask flow (needs a signed-in user); plain dictation comes straight back.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| prefix |  | False |  |
| prompt_key | string | False |  |
| prompt_verbose | string | False |  |
| websocket_id |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/get-speech`

> **Synthesize speech (OpenAI)**

Generate TTS audio via OpenAI and stream to the client's WebSocket session.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/get-speech-elevenlabs`

> **Synthesize speech (ElevenLabs)**

Generate low-latency TTS audio via ElevenLabs and stream to WebSocket.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/upload-and-transcribe-wav`

> **Transcribe WAV audio**

Accept a WAV file upload, transcribe via Whisper, and return transcription text.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| prefix |  | False |  |


### 📦 Request Body 

[Body_upload_and_transcribe_wav_file_api_upload_and_transcribe_wav_post](#body_upload_and_transcribe_wav_file_api_upload_and_transcribe_wav_post)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/push`

> **GONE — use /api/v2/ask**

GONE (410). Use /api/v2/ask. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/push-agentic`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## GET `/api/queue/pool-status`

> **CJ Flow agentic-pool state**

Returns inflight/pending counts and max workers for the agentic ThreadPoolExecutor. Phase 2 (v0.1.7 CJ Flow async multi-lane).





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/get-queue/{queue_name}`

> **Get queue contents**

Retrieve jobs from a named queue (todo/run/done/dead) with role-based user filtering.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| queue_name | string | True |  |
| user_filter |  | False | User filter: omit for self, '*' for all (admin), or specific user_id (admin) |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/reset-queues`

> **Reset all queues**

Clear all five queues (todo, run, done, dead, notification) and return items-cleared summary.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/get-job-interactions/{job_id}`

> **Get job interactions**

Retrieve notification interaction history for a job with progress deduplication.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| job_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/jobs/{job_id}/message`

> **Send message to job**

Send a user-initiated message to a running agentic job via WebSocket notification.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| job_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/jobs/{job_id}/cancel`

> **Cancel a queued or running job**

Cancel a job whether it has started or not. A job still waiting in the todo queue is removed outright; a running agentic job is asked to stop gracefully at its next phase boundary.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| job_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/queue/{queue_name}/all`

> **Delete all jobs from a queue**

Bulk remove all jobs from todo, run, done, or dead queue. Admins clear the entire queue; regular users delete only their own jobs.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| queue_name | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/queue/{queue_name}/{job_id}`

> **Remove job from queue**

Forcefully remove a job from todo, run, done, or dead queue.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| queue_name | string | True |  |
| job_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/job-history`

> **Query job history**

Paginated history of agentic jobs from PostgreSQL persistence. Admin sees all jobs; regular users see only their own. A `user_filter` a regular user is not entitled to is REFUSED with 403, never ignored.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| status |  | False | Filter by status: pending, running, completed, failed, interrupted |
| job_type |  | False | Filter by job type: deep_research, podcast, claude_code, swe_team, research_to_podcast |
| limit | integer | False | Results per page (max 100) |
| offset | integer | False | Pagination offset |
| days |  | False | Time window in days (e.g. 7, 14, 30). None = all time. |
| exclude_ids |  | False | Comma-separated job IDs to exclude (for live queue deduplication) |
| user_filter |  | False | User filter: omit for the default view, '*' for all users (admin), or a specific user_id (admin). Same vocabulary and same 403 as /api/get-queue/{queue_name}. |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/job-history/{job_id}`

> **Get job detail**

Retrieve a single job's full history record by ID hash.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| job_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/job-history/{job_id}`

> **Delete job from history**

Hard delete a job history record. Admin or job owner only.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| job_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/job-history/all`

> **Bulk delete job history**

Delete all job history records matching the given time window. Admins delete across all users; regular users delete only their own records.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| days |  | False | Time window: 1, 7, 14, 30, or 'all'. Defaults to 'all'. |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/job-history/{job_id}/retry`

> **GONE — use /api/v2/ask**

GONE (410). Use /api/v2/ask. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## PATCH `/api/queue/todo/{job_id}/pause`

> **Pause a todo queue job**

Set paused=True on a todo queue job. Consumer skips it until resumed.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| job_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PATCH `/api/queue/todo/{job_id}/resume`

> **Resume a paused todo queue job**

Set paused=False and notify consumer to recalculate eligibility.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| job_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/jobs/{id_hash}/resume-from-checkpoint`

> **GONE — use /api/v2/resume-job**

GONE (410). Use /api/v2/resume-job. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/test-fix-expediter/resume-from`

> **GONE — use /api/v2/resume-job**

GONE (410). Use /api/v2/resume-job. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## GET `/api/delete-snapshot/{id}`

> **Delete job snapshot**

Delete a completed job snapshot by ID. Phase 1 stub.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/get-answer/{id}`

> **Get job audio answer**

Return audio for a completed job. Phase 1 stub serving placeholder audio.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/websocket-sessions/stats`

> **Get WebSocket statistics**

Return detailed connection statistics and subscription pattern breakdown.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/websocket-sessions/{session_id}`

> **Get session details**

Return detailed info for a specific WebSocket session by ID.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| session_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/websocket-sessions/{session_id}`

> **Force disconnect session**

Forcefully disconnect a specific WebSocket session.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| session_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PUT `/api/websocket-sessions/single-session-policy`

> **Set single-session policy**

Enable or disable the single-session-per-user enforcement policy.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| enabled | boolean | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/websocket-events`

> **List available events**

Return sorted list of all available WebSocket event types.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/claude-code/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/claude-code/queue/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/embeddings/generate`

> **Generate embedding**

Generate an embedding vector for a single text string using the GPU model.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[EmbedRequest](#embedrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [EmbedResponse](#embedresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/embeddings/batch`

> **Batch generate embeddings**

Generate embedding vectors for multiple texts in a single call.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[EmbedBatchRequest](#embedbatchrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [EmbedBatchResponse](#embedbatchresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/embeddings/info`

> **Get embedding info**

Return provider name, dimensions, and readiness status of the embedding model.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [EmbedInfoResponse](#embedinforesponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/mode/available`

> **List available modes**

List all selectable agent modes including system mode.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [AvailableModesResponse](#availablemodesresponse)
 |
## GET `/api/mode/current`

> **Get current mode**

Return the authenticated user's current agent mode.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [ModeResponse](#moderesponse)
 |
## POST `/api/mode/current`

> **Set current mode**

Set the user's agent mode to a specific key or null for system mode.





### 📦 Request Body 

[ModeSetRequest](#modesetrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [ModeChangeResponse](#modechangeresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/mode/current`

> **Clear current mode**

Clear the user's agent mode back to system default.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [ModeChangeResponse](#modechangeresponse)
 |
## GET `/api/stats/time-saved`

> **Get user time-saved stats**

Return per-user aggregate stats on time saved by cached solution replays.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| days | integer | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/stats/time-saved/global`

> **Get global time-saved stats**

Return global time-saved leaderboard across all users with top replayed solutions.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/deep-research/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## GET `/api/deep-research/report`

> **Get research report**

Retrieve a research report by local path or GCS URI as raw Markdown.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| path | string | True | Local file path or GCS URI (gs://bucket/path/file.md) |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | string
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/deep-research/health`

> **Deep research health check**

Report GCS availability and local research directory status.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/io/file`

> **Serve IO file**

Serve files from the io/ directory with extension validation and traversal protection.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| path | string | True | Relative path within io/ directory |
| download | boolean | False | Force download with Content-Disposition: attachment |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/io/health`

> **IO files health check**

Report io/ directory status and file counts in research and podcast subdirectories.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/docs/file`

> **Serve a project documentation file or directory listing via the unified scope registry**

Polymorphic file/directory endpoint. The `path` query parameter MUST be `<project>/<rel>` — the first segment names a registered project (see /api/docs/scopes); the remainder is resolved under that project's root, subject to the project's `.docview.yml` whitelist (if present) plus the universal secrets blocklist floor. The legacy `?scope=` query parameter is RETIRED — its presence triggers 400 with an educational pointer to the canonical form (policy flipped from silent-ignore to aggressive-400 on 2026-05-21). JWT auth required.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| path | string | True | Path of the form `<project>/<rel>`; URL-decoded automatically. First segment names the registered project. |
| scope | string | False | RETIRED — presence triggers 400 with educational error. Use `path=<project>/<rel>` form instead. Retired per Q-R2 of 2026-05-15 doc-viewer scope unification; aggressive-400 policy ratified 2026-05-21. |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/docs/scopes`

> **List registered doc-viewer scopes (admin / debugging utility)**

Returns the unified scope registry as a JSON object. Each entry shows scope name, root path, allowed_prefixes, allowed_root_files (from manifest if present), and a source marker ('manifest' vs 'ini-only'). Phase 3 of doc-viewer scope unification; consumed primarily by cosa-voice MCP integration for runtime scope discovery.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/docs/upload`

> **Upload a file into a doc-viewer folder (admins only)**

Multipart form: `dir` = `<project>/<rel-dir>` (or `io/<rel-dir>`), `file` = the file, `on_conflict` = refuse|replace|rename (default refuse). The target folder must pass every guard the viewer applies to reading (whitelist, secrets blocklists, traversal, symlink landing). 201 → {path, name, size, view_url, replaced}; 400 bad name/type/path or credential content; 403 folder not writable on this server; 404 folder missing; 409 name taken (detail carries `suggested_name`); 413 over the size cap.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### 📦 Request Body 

[Body_upload_docs_file_api_docs_upload_post](#body_upload_docs_file_api_docs_upload_post)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 201 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/docs/health`

> **Docs files health check**

Report registered scopes (with manifest presence + on-disk reachability) plus the io/ directory status and the full MEDIA_TYPES extension list. Unauthenticated.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/mock-job/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## GET `/api/mock-job/health`

> **Mock job health check**

Return availability status of the mock job endpoint.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/podcast-generator/submit`

> **GONE — use /api/v2/ask**

GONE (410). Use /api/v2/ask. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/presentation-generator/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/deep-research-to-podcast/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/deep-research-to-presentation/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/swe-team/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/bug-fix-expediter/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/test-suite/submit`

> **GONE — use /api/v2/submit**

GONE (410). Use /api/v2/submit. REMOVE BY 2026-12-31.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 410 | Successful Response | ... |
## POST `/api/proxy/acknowledge`

> **Acknowledge proxy batch**

Retire current proxy notification batch and start a new one. Requires a credential.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 401 | Unauthorized — no valid credential |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/proxy/batch-id`

> **Get proxy batch ID**

Return the current proxy batch progress_group_id. Requires a credential.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 401 | Unauthorized — no valid credential |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/proxy/pending/{user_email}`

> **Get pending decisions**

Retrieve pending decisions awaiting ratification for a user with optional domain/category filter.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_email | string | True |  |
| domain |  | False | Filter by domain (e.g., 'swe') |
| category |  | False | Filter by category |
| limit | integer | False | Maximum number of decisions to return |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 401 | Unauthorized — no valid credential |  |
| 403 | Forbidden — the path names a different user |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/proxy/ratify/{decision_id}`

> **Ratify decision**

Approve or reject a pending decision. Updates ratification state and trust counters. Owner-only.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| decision_id | string | True |  |
| approved | boolean | True | True to approve, False to reject |
| feedback | string | False | Optional feedback text |
| user_email | string | True | Email of the ratifying user — must be the authenticated caller |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 401 | Unauthorized — no valid credential |  |
| 403 | Forbidden — the query names a different user |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/proxy/decision/{decision_id}`

> **Delete pending decision**

Hard-delete a decision in pending state. Approved/rejected decisions are protected. Owner-only.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| decision_id | string | True |  |
| user_email | string | True | Email of the user performing deletion — must be the authenticated caller |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 401 | Unauthorized — no valid credential |  |
| 403 | Forbidden — the query names a different user |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/proxy/trust/{user_email}`

> **Get trust state**

Return all trust state records for a user across domains and categories.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_email | string | True |  |
| domain |  | False | Filter by domain |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 401 | Unauthorized — no valid credential |  |
| 403 | Forbidden — the path names a different user |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/proxy/decisions/{domain}/{category}`

> **Get decisions by domain**

Return decision history for a specific domain and category combination. Requires a credential.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| domain | string | True |  |
| category | string | True |  |
| limit | integer | False | Maximum number of decisions to return |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 401 | Unauthorized — no valid credential |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/proxy/mode`

> **Get trust mode**

Return current effective trust mode from INI config and any running job orchestrator.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## PUT `/api/proxy/mode`

> **Update trust mode**

Hot-reload trust mode at runtime. Persists to INI and updates running proxy if available.





### 📦 Request Body 

[TrustModeUpdateRequest](#trustmodeupdaterequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/admin/peer-queue/{queue_name}`

> **Proxy a queue read to a peer Lupin server**

Admin-only. Forwards the caller's JWT to the peer's /api/get-queue/{name} and returns the response. Peer host must be in the 'peer queue allowed hosts' whitelist.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| queue_name | string | True |  |
| host | string | True | Peer docker-compose service:port (e.g. lupin-rest-test:7999) |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [PeerQueueResponse](#peerqueueresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/admin/peer-queue-watch/start`

> **Start a background peer-queue drain watcher**

Admin-only. Spawns an asyncio task that polls the peer queue and fires a high-priority notification on drain. One active watcher per admin; re-calling replaces the prior.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### 📦 Request Body 

[WatchStartRequest](#watchstartrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [WatchActionResponse](#watchactionresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/admin/peer-queue-watch/stop`

> **Stop the caller's peer-queue watcher**

Admin-only. Idempotent — returns 'not_active' if no watcher was running.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [WatchActionResponse](#watchactionresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/admin/peer-queue-watch/status`

> **Get current peer-queue watcher status**

Admin-only. Returns live state for this admin's watcher (if any).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [WatchStatusResponse](#watchstatusresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/cosa-voice/speakerphone/{session_id}`

> **Get speakerphone flag for a session**

Returns the speakerphone_on flag from the cosa-voice session bridge file.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| session_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/cosa-voice/speakerphone/{session_id}`

> **Set speakerphone flag for a session**

Writes speakerphone_on to the bridge file and broadcasts a speakerphone_changed WebSocket event so all connected UI tabs sync. In solo mode, activating displaces any other active session. In chorus mode, multiple sessions can be active simultaneously.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| session_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[SpeakerphoneBody](#speakerphonebody)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/cosa-voice/voice-persona/pool`

> **Pool snapshot — allocatable pool, occupied names, free slots**

Returns the configured pool plus current occupancy. Diagnostics endpoint; does not allocate.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/cosa-voice/voice-persona/{session_id}`

> **Read voice persona for a session**

Returns the voice_persona dict from the cosa-voice session bridge file, or null when none is set.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| session_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/cosa-voice/voice-persona/{session_id}/allocate`

> **Allocate a voice persona for a session**

Idempotent: if a persona is already set on the bridge and no `requested_persona_name`/`persona_chain` query param is supplied, returns it without re-allocating. When `requested_persona_name` is supplied: atomically allocates the named persona with strict 422/409 errors on miss. When `persona_chain` is supplied: STRICT ordered-fallback walk — comma-separated names tried in order, first FREE one allocated; a `*` element means 'then take anything free'; a chain exhausted without `*` is a LOUD fail (409 + `voice_persona_conflict` notification, NO silent random fallback). Used by the SessionStart hook for both spawn-injected and per-repo env-var chains. Mutually exclusive with `requested_persona_name`. `declared_managers` (CSV, optional — the hook threads its project's COSA_VOICE_MANAGERS__<PROJECT> roster) reserves those names OUT of the random and chain-`*` draws; explicit `requested_persona_name` and NAMED chain elements can still claim them.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| session_id | string | True |  |
| previous_persona_name |  | False |  |
| requested_persona_name |  | False |  |
| persona_chain |  | False |  |
| declared_managers |  | False |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/cosa-voice/voice-persona/{session_id}/release`

> **Release the voice persona allocated to a session**

Clears the voice_persona field on the bridge and broadcasts a voice_persona_released event.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| session_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/cosa-voice/voice-persona/sample`

> **Synthesize a voice sample for the persona-reference page**

Returns audio/mpeg bytes inline. The voice_id MUST belong to the configured persona pool — arbitrary voice_ids are rejected so this endpoint cannot be used as a general-purpose TTS oracle.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[VoicePersonaSampleRequest](#voicepersonasamplerequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ...... |
| 400 | voice_id is not in the configured persona pool |  |
| 503 | ElevenLabs API unavailable or returned an error |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/multiplexer/config`

> **Multiplexer client-config**

Returns display-tuning values that the multiplexer boot path fetches once at startup. Values are sourced from `ConfigurationManager` INI (`[Lupin: Baseline]` section). No auth required (no PII, no state).





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [MultiplexerConfigResponse](#multiplexerconfigresponse)
 |
## GET `/api/commons/active-sessions`

> **List active CC sessions belonging to the authenticated user**

Returns same-user-scoped active sessions with persona info for the broadcast recipient preview.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/commons/broadcast-to-cc-sessions`

> **Fan out a broadcast to active CC sessions belonging to the authenticated user**

Posts a per-recipient `broadcasts` entry + a per-session listener notification for each active CC session belonging to the caller. Returns the broadcast_id + recipient count + any failed recipients.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[BroadcastRequestBody](#broadcastrequestbody)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/commons/broadcast-history`

> **List recent commons traffic for the broadcast-card Recent Activity surface**

Aggregates entries across all commons topics (excluding the configurable blacklist — defaults to presence + system-events) and returns them newest-first, scoped to the authenticated user. Powers the broadcast-card Recent Activity stream. Per src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md (AC1, AC4-AC6).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| since |  | False |  |
| hours |  | False |  |
| limit | integer | False |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/arbiter/fleet-snapshot`

> **Heartbeat-arbiter fleet snapshot (direct-state visibility)**

Returns the arbiter's latest full-fleet snapshot: per-session STATE + orthogonal LIVENESS (honest last-seen ages + verdict). Mirrors GET /api/queue/pool-status. v2.1 (arbiter design 03 §10.4).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/arbiter/fleet-snapshot`

> **Push a fleet snapshot (standalone-arbiter ingress)**

The standalone Heartbeat Arbiter pushes its latest snapshot here; the in-pool arbiter updates the server singleton directly. Auth: X-API-Key or Bearer JWT. v2.1 (arbiter design 03 §10.4 C2).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[FleetSnapshotIn](#fleetsnapshotin)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/arbiter/fleet-state`

> **Lupin Arbiter App single-pane (reverse-proxy to :8001/state)**

NEW authoritative surface (L4): PULLS the single-pane composite (health watcher + fleet arbiter snapshot) from the standalone lupin-arbiter-app service at :8001/state (R3 — :8001 never pushes). Auth: X-API-Key or Bearer JWT. Supersedes /api/arbiter/fleet-snapshot.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/arbiter/context-pressure`

> **Published per-persona context-headroom service (read-only)**

Returns the persona-keyed context-headroom map: per worker, the tokens remaining before its soft budget line (1M window → 50%, 200K → 75%; config-tunable). Thin reverse-proxy that PULLS :8001/state and returns JUST the `context_pressure` section. Pure sensor read — no side effects. Auth: X-API-Key or Bearer JWT. Design: src/rnd/v0.1.8/2026.06.07-managing-context-memory/2026.06.09-context-pressure-published-headroom-service-design.md §4-5.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/arbiter/fleet-size-cap`

> **The fleet-size dial: the live cap and the configured ceiling**

Read-only. Returns { cap, ceiling } computed AT CALL TIME from the configuration manager, so the operator control renders 1..ceiling against the number the spawn path is actually enforcing. Auth: X-API-Key or Bearer JWT — the same guard as the fleet pane, because anyone who can see the fleet should see the cap governing it.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PUT `/api/arbiter/fleet-size-cap`

> **Set the fleet-size cap — writes through to configuration and persists**

Writes `cc session fleet size cap` to the configuration FILE and returns what it ACTUALLY PERSISTED, re-read from disk. Refuses a value outside 1..`cc session fleet size cap maximum`. Auth: X-API-Key or Bearer JWT — the same guard as the GET.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[FleetSizeCapIn](#fleetsizecapin)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/tasks`

> **Create a task-store item**

Creates one obligation row (always status=queued) plus its '->queued' creation event. Auth: X-API-Key or Bearer JWT. Design §2.2 (v0.4, Rick-ruled F4: managers-first writes).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[TaskCreateIn](#taskcreatein)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 201 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks`

> **Query task-store items**

The deterministic owed-work query (R4): exact-match filters, AND semantics, newest first. Junk enum filter values are rejected (422), never silently empty. count_only=true returns {count} as a true COUNT(*) without serializing any rows (the owed-count token win, §G). terse=true returns the at-a-glance projection (id/title/status/blocked_by/next_chase_ts/priority/park_reason_stale — drops body) for cheap 'see my list' queries. Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| owner_persona |  | False |  |
| status |  | False |  |
| gate_class |  | False |  |
| urgency |  | False |  |
| accountable_manager |  | False |  |
| project |  | False |  |
| item_class |  | False |  |
| correlation_key |  | False |  |
| id_prefix |  | False |  |
| count_only | boolean | False |  |
| terse | boolean | False |  |
| include_terminal | boolean | False |  |
| unscoped_audit | boolean | False |  |
| owed_only | boolean | False |  |
| hide_parked | boolean | False |  |
| updated_since |  | False |  |
| updated_until |  | False |  |
| limit | integer | False |  |
| offset | integer | False |  |
| char_budget |  | False |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/tasks/{task_id}/transition`

> **Transition a task-store item**

Applies one state change + appends one audit event. ->done REJECTS without valid receipt_refs (T3, §4.1 AC1); ->blocked REQUIRES next_chase_ts (I3) + typed blocked_by refs; done/dropped are terminal. Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[TaskTransitionIn](#tasktransitionin)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/tasks/{task_id}/correlate`

> **Re-stamp a task-store item's correlation key**

Phase-2 cross-session respawn adoption: a successor session re-registers its harness task id onto an inherited item instead of forking a duplicate. Appends an audited 're-correlated' event (R3). Terminal items are rejected. Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[TaskCorrelateIn](#taskcorrelatein)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/tasks/{task_id}/unpark-ask`

> **Ask the operator to approve un-parking a parked row**

A manager asks; the server makes the card (bound to this row and the move parked to queued, in a field only the server writes), pushes it, and returns its id. After the operator answers yes, the manager cites the id as the approval_card receipt on the parked-to-queued transition. One unanswered card per row and park. Auth: X-API-Key or Bearer JWT, and a manager seat.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[UnparkAskIn](#unparkaskin)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/tasks/{task_id}/amend`

> **Append an amendment to a task-store item's body**

Phase-2.2 append-only body amendment: appends a persona-stamped + UTC-timestamped block to an item's body WITHOUT rewriting the existing text (distinct from PATCH body, which overwrites) and appends an 'amended' audit event. status / the oracle fields are never touched. A TERMINAL item is ALLOWED (Rick 2026-08-02): the block is marked a post-terminal addendum and the event is stamped 'amended_post_terminal' — a closed row stays closed. A blank note and a bad authority are rejected (every violation at once). Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[TaskAmendIn](#taskamendin)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/approval-settings`

> **Read every approval setting in force, and where each came from**

Same auth as /api/tasks. Values are the EFFECTIVE ones the gates will use, not the raw file contents.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PATCH `/api/tasks/approval-settings`

> **Write an approval setting — Rick only**

Rick's ruling 2026-09-08: "Only the server writes it." Gated on a signature-validated login account, never on a caller-declared name. Booleans must be REAL booleans: the string "false" is truthy and is refused at the model rather than coerced.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[ApprovalSettingsRequest](#approvalsettingsrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/manager-pull`

> **Read whether pulling work into in_progress is currently switched off**

Returns the live toggle state and where it came from. Same auth as /api/tasks.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PATCH `/api/tasks/manager-pull`

> **Switch pulling work into in_progress on or off**

Rick's control (row 458e9947). Admin only. The body must carry a REAL boolean — the string "false" is refused rather than coerced, because it is truthy and would switch the toggle the wrong way.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### 📦 Request Body 

[ManagerPullRequest](#managerpullrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/request-badges`

> **How many pending promote/demote requests each board badge shows**

TWO INDEPENDENT COUNTS, NEVER A SUM (Rick via Mr. Radio, 2026-09-09). The task-area badge counts DEMOTE requests and the holding-area badge counts PROMOTE requests, because a badge sits on the list the row is in NOW, not the list it is asking to reach. Both keys are always present, so a caller never has to tell zero from absent. Auth: X-API-Key or Bearer JWT — a manager may file a request and READ its state; only the verdict is the operator's.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/tasks/{task_id}/request`

> **File a manager's request that Rick promote or demote one row**

MANAGERS ONLY, ONE ROW PER CALL (row c9fafb9d, rule 3; Rick 2026-09-04, no batches). A request ASKS and never moves: the row's status is untouched, it waits on Rick's board with no expiry, and no answer means no. Body `{move: admit|demote, reason, actor, deletion_task_id?}`. SWORD OF DAMOCLES (row ab8c5728): while `sword_of_damocles_active` is on, an admit must name `deletion_task_id` — a live ticket the requester owns, dropped when Rick approves; a demote may not name one. 404 no row · 422 not a requestable move, a blank reason, a missing/self/nonexistent pledge, or a pledge on a demote · 409 the row cannot make that move, a request is already pending, or the pledge is finished or already pledged · 403 not a manager, or the pledge is not the requester's own. Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[RequestFileIn](#requestfilein)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/tasks/{task_id}/request-verdict`

> **Record the operator's verdict on a pending promote/demote request**

RICK ALONE (row c9fafb9d, rules 1 and 2 one layer over). A manager may FILE a request and read its state; the answer is his — if a manager could answer their own request, the request door would BE a way to promote without him, which is the thing it exists to prevent. A verdict is FINAL: to ask again, file a new request. `approved` PERFORMS the move through the transition door's own gates (admit -> queued; demote -> not_approved with `next_chase_ts`); `denied` leaves the row exactly where it is. An approved admit that pledged a `deletion_task_id` DROPS that ticket in the same transaction, or nothing happens (Sword of Damocles, row ab8c5728); a pledge that has died since filing is 409 and the request stays pending for the manager to re-file. Auth: X-API-Key or Bearer JWT, but the operator check binds to the AUTHENTICATED ACCOUNT — a typed name confers nothing.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[RequestVerdictIn](#requestverdictin)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PATCH `/api/tasks/{task_id}`

> **Edit a task-store item's mutable fields**

Phase-2.1 item edit: PATCH whitelisted fields (title/body/priority/owner_persona/accountable_manager/gate_class) on a NON-terminal item; appends a 'patched' audit event with the field delta. status/blocked_by/next_chase_ts/receipt_refs/correlation_key can NEVER be PATCHed (they ride the transition oracle — naming one is a 422). Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[TaskPatchIn](#taskpatchin)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/{task_id}`

> **Get one task-store item**

Returns one item by full UUID or by an 8-hex id prefix (the form every brief and cross-reference uses). An ambiguous prefix returns 422 naming every candidate — never a silent first match. Prefix resolution is READ-ONLY; mutating routes require a full UUID. Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/events`

> **Query the cross-item event stream**

Fleet-wide audit (design backlog): the append-only event trail across ALL items, filtered by actor / transition / to_status / project / time range (since/until on event ts), newest first. Each event carries the owning item's `title`, eager-loaded. `to_status=done` matches every *->done event whatever the source status, which the exact-match `transition` filter cannot express; an unknown value is a 422 naming the valid set, never an empty result. Distinct from /tasks/{id}/events (one item). Declared BEFORE /tasks/{task_id} so the static path wins over the UUID path converter. Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| actor |  | False |  |
| transition |  | False |  |
| to_status |  | False |  |
| project |  | False |  |
| since |  | False |  |
| until |  | False |  |
| limit | integer | False |  |
| offset | integer | False |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/flow-ratio`

> **Closed-vs-new ratio over a rolling window**

Returns { created, closed, ratio, verdict, room_for, close_needed, headroom, window_hours, allow_below, window_start, project } counted in SQL. The board's header and the creation gate are both thin consumers of this ONE payload, which is what stops them disagreeing with each other.

**TWO CAPACITY NUMBERS, AND THEY DIFFER BY EXACTLY ONE. RENDER `room_for`.**

- `room_for` — **the display number, and the ruled one.** How many more creates leave the ratio still under the threshold AFTER they land (LOOP semantics). `0` means AT CAPACITY BUT STILL LEGAL and is rendered as the word `FULL`. `null` when the gate already refuses — that case is `close_needed`, not zero.
- `headroom` — **the gate boundary. Diagnostic only, do NOT display.** The exact count the gate would admit, which is ALWAYS EXACTLY ONE MORE than `room_for` wherever there is any room, because the gate judges each create against the counts BEFORE it lands.
- `close_needed` — closures required before the gate would admit again; `0` when it already admits, `null` when no number of closures opens it (a zero threshold).

**Worked example — created 10, closed 13, allow_below 1.00:**

| field | value | meaning |
|---|---|---|
| `room_for` | **2** | render this: `· Room for 2 more` |
| `headroom` | **3** | the gate really would admit 3 |

The gate takes 3 because it judges create #3 at 12/13 = 0.92 BEFORE that row lands; only create #4, judged at 13/13 = 1.00, is refused. The display says 2 because after 3 creates the ratio is no longer under the threshold. **`headroom` is always `room_for` + 1 wherever there is any room** — they agree only when both are 0.
The one-lower display is Rick's ruling of 2026-09-05 13:11:13 EDT, by keypress, on the option labelled "Keep your three states - badge under-reports by one" (receipt: notifications row `819dc891`, `state = responded`, `source = ui`, and the time above is **`responded_at`** — that table also carries `created_at` (when the question went out) and `expires_at`, and reading either as the answer time is how this stamp got mis-stated twice). It is deliberate: the display errs toward saying there is no room while the gate would still accept one, which is the safer error for a moratorium. A consumer that renders `headroom` to "fix" the off-by-one also destroys the `FULL` state, which he ratified separately — the number and the word are one choice, not two.

Auth: X-API-Key or Bearer JWT (same guard as /api/tasks).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| window_hours |  | False |  |
| project |  | False |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/flow-ratio/settings`

> **Read the operator's live ratio window + threshold**

Returns the live { window_hours, allow_below } and, for each, whether it comes from an operator override or from config. Same auth as /api/tasks.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PATCH `/api/tasks/flow-ratio/settings`

> **Set the operator's ratio window + threshold**

Persists an override for either value. ADMIN ONLY — this moves the threshold the CREATE gate refuses on, fleet-wide, so it is a policy change and not a display preference.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### 📦 Request Body 

[FlowRatioSettingsRequest](#flowratiosettingsrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/tasks/flow-ratio/settings`

> **Clear the operator override, returning to config**

Removes the persisted override so the INI defaults govern again. ADMIN ONLY.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/promotions`

> **List promotion tickets - the visibility surface for pending asks**

Defaults to state=pending: what is waiting on Rick right now. The task row itself cannot provide this - a row awaiting promotion is still not_approved, which task_store_rules puts outside every board query BY DESIGN. Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| state |  | False | ticket state, or 'all' |
| limit | integer | False |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/promotions/{ticket_id}`

> **Get one promotion ticket - the caller's poll target**

The outcome of an asynchronous promotion. A resolved ticket carries response_body, the exact { item, event } a synchronous 200 would have returned. Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| ticket_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/tasks/{task_id}/events`

> **Get a task-store item's audit trail**

Returns the append-only per-item event trail (R3): every transition with actor, authority, and receipt refs. Auth: X-API-Key or Bearer JWT.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/epic-stories`

> **Get the hand-maintained epic story text**

Returns src/conf/epic-stories.json as-is: a map of `epic:<slug>` -> { title, story }, plus a `_README` key. Hand-maintained — a manager minting a new epic adds its line in the same turn. An epic with NO entry is not an error: the consumer renders a de-slugged key and no story, which is the visible nudge to write one. Auth: X-API-Key or Bearer JWT (the same guard as /api/tasks).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/fcm/register-token`

> **Register a mobile device's FCM token for the silent-relay wake channel**

Upsert keyed on token (S6 §3.1): re-registering a known token refreshes its user binding instead of duplicating it. Multiple devices per user allowed. The mobile app calls this on login, onTokenRefresh, and every WS reconnect (idempotent belt for parent-restart registry loss).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[RegisterTokenRequest](#registertokenrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/fcm/unregister-token`

> **Unregister a mobile device's FCM token (best-effort logout path)**

Idempotent: unregistering an unknown token still returns 200 (S6 §3.1 amended 2026-06-12 — POST replaces the proxy-fragile DELETE-with-JSON-body shape).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[UnregisterTokenRequest](#unregistertokenrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/fcm/push-pause`

> **Admin: pause (or resume) ALL mobile wake pushes, in memory only**

Sets `fcm wake push enabled` False in the ConfigurationManager's memory — never the INI — and, with `minutes`, arms a timer that restores the boot-time value. A second pause replaces the first timer; `paused: false` resumes now. `minutes` is capped at 24 h (400 above it). A server restart clears the pause (row 7df08e59, Rick's R1.4 ruling).



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### 📦 Request Body 

[PushPauseRequest](#pushpauserequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/fcm/push-pause`

> **Admin: read the mobile push pause state**

Returns { paused, resumes_at, set_by, set_at, push_enabled }. `push_enabled` is the live key, so the answer is never a guess.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/heartbeat/poke-mute`

> **Read the fleet switch for the heartbeat Stop poke**

Returns { muted, set_by, set_at }. A missing or unreadable switch file reads as not muted.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## PUT `/api/heartbeat/poke-mute`

> **Admin: turn the heartbeat Stop poke off or back on, fleet-wide**

Body { muted: bool }. Takes effect on each seat's next stop. No timer: it stays as set until an admin flips it. API-key callers and non-admin users get 403.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[PokeMuteRequest](#pokemuterequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/dm/send`

> **Send a notification-native AI↔AI direct message (body inline)**

Notification-native peer DM: resolves the recipient persona/session (same-user scoped) and delivers the message body INLINE via a direction='ai_to_ai' notification — no commons board, no claim-check, no commons_read re-fetch. Returns 201 with {message_id, thread_id}, or 422 (RecipientResolutionError) if the recipient can't be resolved.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[DmSendRequest](#dmsendrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/dm/respond`

> **Reply to a peer DM in-thread (body inline, reply_to + thread_id required)**

Threaded peer-DM reply: a /api/dm/send whose `reply_to` (message answered) and `thread_id` (conversation) are mandatory. Resolves the recipient (same-user scoped), persists a direction='ai_to_ai' notification carrying the body inline + threading, and pushes it to the recipient session. Returns 201 with {message_id, thread_id}, or 422 if the recipient can't be resolved.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### 📦 Request Body 

[DmRespondRequest](#dmrespondrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/dm/get`

> **Fetch a single peer DM by message id**

Returns one direction='ai_to_ai' DM by its message id, scoped to the caller. 404 if it does not exist, is not a DM, or belongs to another user; 400 if message_id is not a UUID.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| message_id | string | True |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/dm/list`

> **List or poll peer DMs — a thread (thread_id) or the inbox**

With `thread_id`, returns that conversation oldest-first; without it, returns peer DMs newest-first. SCOPING: the credential authenticates a USER (a per-project service account), NOT a session — pass `session_id` (your 8-char session hash) to narrow to DMs actually ADDRESSED to you. WITHOUT it the read is ACCOUNT-WIDE and returns every DM sent by any session on that account, including conversations you are not party to. `scope=account` explicitly requests that wide read. The response echoes the `scope` actually applied. `session_id` may be a FULL session id OR its 8-char prefix — it is normalized server-side, so the `recipient_session` from a send receipt can be fed straight back. `since` (ISO 8601) tails only newer messages (poll); `limit` is clamped to [1, 200]. 400 if `since` is malformed; 422 if `scope` is not session|account.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| thread_id |  | False |  |
| since |  | False |  |
| limit | integer | False |  |
| session_id |  | False |  |
| scope | string | False |  |
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/dm/project-audit`

> **Read the un-projected-DM audit — the step-2 gate evidence**

Returns the live `sender_project` audit counters: `projected`, `un_projected`, the distinct offender sessions (capped), and the window start. WHY THIS EXISTS: the audit has been generated correctly since 2026-07-21 and was readable ONLY by grepping `docker logs lupin-rest-dev`, so the gate it existed to inform sat four days unread — the fifth instance of row 67fe3be1 (disclosures nobody consumes). The counters reset on every server restart, and `:7999` runs --reload, so `since` is load-bearing: a low count usually means a recent reload, not a quiet fleet. ⚠️ `un_projected=0` alone proves nothing — a window with NO DM traffic reports 0/0 and reads exactly like a clean one. Always read `projected` alongside it.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/dm/length-audit`

> **Read the DM length audit — evidence for the Phase 1 verbosity A/B**

Returns the live DM body length counters: `count`, `total_chars`, `total_words`, `total_sentences`, derived `avg_chars`/`avg_words`/`avg_sentences`, and the window start. Snapshot this endpoint before and after each control/treatment run of the DM Verbosity Reduction A/B (src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/) to get a quantified delta rather than a vibes-based one. Counters reset on server restart, same as the project-audit; `since` is load-bearing for the same reason.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/dm/quality-audit`

> **Read the DM quality audit — evidence for the Phase 2 verbosity A/B**

Returns the live DM Quality Judge counters: `count`, the running `total_length_weight`/`total_directness_weight`/`total_tone_weight`/`total_overall_weight`, the derived `avg_length`/`avg_directness`/`avg_tone`/`avg_overall`, and the window start. This is the SECOND A/B axis (the first is `/length-audit`): it accumulates ONLY during TREATMENT windows (the judge runs only when `dm quality judgment enabled` is True), so a control window reports count=0. Snapshot before and after a treatment run and read the avg_overall trend against the length-audit's avg_words trend (src/rnd/v0.1.9/2026.07.31-dm-verbosity-reduction/). Counters reset on server restart; `since` is load-bearing, same as the other audits.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| x-api-key |  | False |  |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/v2/agents`

> **V2 Agents**

List every command the registry knows, as a pure projection of `REGISTRY`.

Requires:
    - an authenticated user (get_current_user).

Ensures:
    - `agents` carries one entry per `REGISTRY` command — set-equal to `REGISTRY`,
      which is the first gate assertion.
    - the CRUD fork is applied exactly as resolve() applies it, by calling
      resolve() itself rather than reimplementing the fork.
    - `auto_route` carries the sentinel option, so the page hand-writes no
      option at all.
    - never 500s for an unknown-shaped spec: every field read is declared on
      AgentSpec or on the command's JOB_ARG_CONTRACTS entry.

This is the read endpoint the front end needs. The Q&A card's agent list used to be
sixteen hand-typed `<option>` tags in notifications.html, one of five hand-maintained
lists describing the same set. This door is how that list stops being written by hand.

Pure projection means every registry command appears exactly once, carrying its own
fields. Nothing is filtered here, not the two expediters, not the control command and
not `none`. A client renders what it should by reading `user_initiable` (the Q&A
dropdown) or `speakable` (a voice surface). If the door filtered, the set-equality
that proves the door matches the table would stop being checkable.

It depends on the flow because it needs `crud_enabled`. The labels must name the agent
that will actually run, so `todo` reads "todo (CRUD)" when the fork is on. Reading the
INI key `crud for dataframes agents enabled` here would be a fourth read, and a fourth
read is a fourth thing to drift. The flow already holds the value it routes with, so
the label a user picks and the agent they get cannot disagree. The 503 that comes with
the dependency is coherent. When `v2 flow enabled` is off, /api/v2/submit is off too,
and a dropdown that drives it has nothing to drive.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [AgentsResponse](#agentsresponse)
 |
## POST `/api/v2/ask`

> **V2 Ask**

Route one question through CJ Flow v2 and return the terminal result.

Requires:
    - an authenticated user (get_current_user) carrying uid + email.
    - request.question is a non-empty string ≤ 4000 chars (Field-validated).

Ensures:
    - returns AskResponse; never 500 for an agent/replay/router/extract
      failure — AskFlow degrades each to the receptionist.
    - user_id / user_email come from the token, never the client body.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| X-Lupin-Lineage-Token |  | False |  |


### 📦 Request Body 

[AskRequest](#askrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [AskResponse](#askresponse)
 |
| 403 | parent_id_hash names the test-suite job holding the monopoly slot and the caller may not claim its lineage; the body names the reason |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/v2/ask-audio`

> **Ask Audio**

Transcribe a spoken question and ask it, in one request with a two-part reply.

Requires:
    - an authenticated user carrying uid + email
    - file is audio the transcriber reads; websocket_id, when given, is a query parameter

Ensures:
    - a non-200 means nothing was asked: 401 identity, 503 flow disabled or GPU OOM,
      500 any other failure reading, saving or transcribing the audio, 422 empty speech
    - a 200 body is NDJSON: a transcript line, then exactly one ask or error line
    - the ask is started before the response exists, so a client that disconnects after
      line 1 does not cancel it; its answer still reaches the session's WebSocket
    - the uploaded audio is removed on every path

Raises:
    - HTTPException 401 / 422 / 500 / 503 as above



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| websocket_id |  | False |  |
| speak | boolean | False |  |
| interactive | boolean | False |  |


### 📦 Request Body 

[Body_ask_audio_api_v2_ask_audio_post](#body_ask_audio_api_v2_ask_audio_post)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/v2/transcribe`

> **Transcribe**

Transcribe spoken audio and return the words, asking nothing.

Requires:
    - an authenticated user carrying uid + email
    - file is audio the transcriber reads; its extension (.ogg, .wav, …) picks the decoder

Ensures:
    - 200 body is { transcription, trace: { stt_ms, upload_bytes } }, the transcript stripped
    - 401 identity; 422 a missing file part, an empty upload, or no speech recognised;
      503 with Retry-After on GPU OOM; 500 with one fixed detail for any other failure
      reading, saving, transcribing or logging — never the exception text
    - the uploaded audio is removed on every path, and one io row is written on success

Raises:
    - HTTPException 401 / 422 / 500 / 503 as above

This serves a client that must show the transcript before deciding to send it, such as
the phone's Quick Ask review and its focus-mode voice reply. It is /api/v2/ask-audio with
the ask removed, so it takes no flow dependency and is not behind the `v2 flow enabled`
gate.





### 📦 Request Body 

[Body_transcribe_api_v2_transcribe_post](#body_transcribe_api_v2_transcribe_post)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [TranscribeResponse](#transcriberesponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/v2/submit`

> **V2 Submit**

Run work whose command is already decided — the door beside /api/v2/ask.

Two doors survive at v2. `ask` takes a bare question and works out what it is.
`submit` takes work whose command the caller has already chosen, so it skips routing
and argument extraction entirely.

Requires:
    - an authenticated user (get_current_user) carrying uid + email.
    - request.command is a non-empty routing command (Field-validated), and
      request.args carries every argument that command requires.

Ensures:
    - returns AskResponse; never 500 for a routing or agent failure — the flow
      degrades to the receptionist exactly as it does on `ask`.
    - user_id / user_email come from the token, never the client body.
    - a command missing arguments comes back status='needs_input' with args_missing
      filled in, and is never parked: there is no human behind a submit to answer it.
    - scheduled_at / monopolize / parent_id_hash reach the built job only on the
      agentic path, which is the only path that builds one; on the other paths the
      flow records that they were dropped rather than discarding them in silence.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| X-Lupin-Lineage-Token |  | False |  |


### 📦 Request Body 

[SubmitRequest](#submitrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [AskResponse](#askresponse)
 |
| 403 | parent_id_hash names the test-suite job holding the monopoly slot and the caller may not claim its lineage; the body names the reason |  |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/v2/resume`

> **V2 Resume**

Resume a parked v2 flow with the human's answer — the second turn.

Requires:
    - an authenticated user (get_current_user).
    - request.pending_id is a parked id; request.answer is the reply (Field-validated).

Ensures:
    - returns AskResponse; an expired/unknown pending_id degrades to a
      needs_input refusal (status='expired'), never a 500.
    - resume runs off the event loop, in a worker thread. Running it on the loop
      itself would make /health time out during a call.





### 📦 Request Body 

[ResumeRequest](#resumerequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [AskResponse](#askresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/v2/resume-job`

> **V2 Resume Job**

Resume a stalled job from its saved checkpoint and queue the new job.

Requires:
    - an authenticated user (get_current_user) carrying uid + email.
    - request.resume_from names a stalled job with a checkpoint, by id_hash,
      `tfe-` id, plan document path, or description.

Ensures:
    - a job-id-shaped resume_from that is not a `tfe-` id goes straight to the
      factory (the old `/api/jobs/{id_hash}/resume-from-checkpoint` behaviour);
      everything else goes through the TFE resolver (the old
      `/api/test-fix-expediter/resume-from` behaviour, including its `ambiguous`
      answer with candidates and no job pushed).
    - returns status='resumed' with the new job id and its resume phase, and
      queue_position = the todo queue's size right after the push.
    - the model / thinking-effort overrides reach the reconstructed job; None
      overrides are ignored.

Raises:
    - HTTPException 404 when the target is unknown, not stalled, has no checkpoint,
      or cannot be reconstructed — and, on the direct path, when the caller does not own
      the job and is not an admin (the same text, so a refusal never reveals existence).





### 📦 Request Body 

[ResumeJobRequest](#resumejobrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [ResumeJobResponse](#resumejobresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/cc-transcript-roster`

> **Watchable-seat roster for the CC transcript console (admin)**

A projection of /api/arbiter/fleet-state carrying `project`, `last_ts` and `transcript_watchable` per seat. Admin-gated IN ITS OWN RIGHT — fleet-state's own gate (require_api_key_or_jwt) is looser, and the console is admin-only (ruling Q5). An unreachable arbiter is reported as unreachable, never as an empty fleet.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/cc-transcript/{cc_session_id}`

> **CC transcript backlog and gap repair (admin)**

Serves display blocks from a seat's transcript in ONE OF THREE DIRECTIONS. `tail_bytes` reads BACKWARD from the end of the file — the open, per ruling Q6, which a forward-only contract cannot express. `before_offset` pages backward from a known offset (load-earlier). `since_offset` reads forward (gap repair). Every offset lands on a complete-line boundary. `cc_session_id` is the seat's stable_session_id, the FULL id that survives a /clear — never the 8-character form used elsewhere in the fleet.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| cc_session_id | string | True |  |
| tail_bytes |  | False | Read the LAST N bytes (backward). Omit N or pass 0 for the whole file. |
| before_offset |  | False | Page BACKWARD from this offset — 'load earlier'. |
| since_offset |  | False | Read FORWARD from this offset — gap repair. |
| max_bytes | integer | False | Bound the window. 0 means unbounded. |
| authorization |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
---

# 📋 Components



## AgentOption


One registry command, projected for a client that has to render it.


| Field | Type | Description |
|-------|------|-------------|
| command | string | The full routing string — the value a client sends back as `command` on /api/v2/submit |
| display_name | string | What to SHOW the user — the dropdown's option text, a proper name ('Date & Time'). CRUD-forked, so it names the agent that will actually run |
| label | string | What the user HEARS — lowercase prose for spoken text ('date and time'). A different register from display_name, not a duplicate of it; CRUD-forked too |
| cls | string | conversational | agentic | control | none |
| description |  | One-line help text; None for commands nobody picks by hand |
| speakable | boolean | Belongs in the voice router prompt |
| user_initiable | boolean | A person may start this by typing into the Q&A card. NOT derived from `speakable` — see registry.AgentSpec |
| aliases | array | Registered short forms |
| required_args | array | Argument names this command needs before it can run |
| arg_questions | object | Per-argument question text, for an inline argument interview |
| job_prefix |  | Agentic job-id prefix (dr, pg, cc, swe, …); None for non-agentic |


## AgentsResponse


Response for GET /api/v2/agents.


| Field | Type | Description |
|-------|------|-------------|
| auto_route |  |  |
| agents | array |  |


## ApprovalSettingsRequest


One or more approval settings to write; an omitted field is left unchanged.

That makes this a patch rather than a replace. Every field is optional.

The fields are `StrictBool`, not `bool`, and that is the whole safety of the door.
Pydantic's lenient bool coerces the string "false", and `bool( "false" )` is True. A
lenient model would let a caller switch a gate on by sending the word "off".

`extra="forbid"` is a choice, not a default. Pydantic ignores unknown fields unless told
otherwise. A typo'd key such as `enforcment_active` would then return 200 having changed
nothing, and the operator would conclude the switch is broken. The rest of this router
ignores extras. That was rejected here, because a setting ignored in silence is a
failure mode this file documents at length.


| Field | Type | Description |
|-------|------|-------------|
| enforcement_active |  | True makes the approval gate REFUSE; False makes it advise only. |
| default_to_holding |  | True mints new tickets into the holding area. |
| manager_pull_disabled |  | True switches pulling into in_progress OFF for everyone but an approver. |
| approvers |  | Persona names permitted to admit out of the holding area. |
| approver_accounts |  | login email -> approver persona. |
| sword_of_damocles_active |  | True makes an admit request name a deletion ticket the requester owns (row ab8c5728). |


## AskRequest


Request body for POST /api/v2/ask.


| Field | Type | Description |
|-------|------|-------------|
| question | string | The user's natural-language question |
| websocket_id |  | WebSocket session ID for TTS routing |
| speak | boolean | Dispatch the answer as a TTS notification |
| interactive | boolean | Whether a human is there to answer. Two effects: a missing argument parks and asks (else the call returns needs_input), and a near-match cache hit is confirmed before it is replayed (else the match is declined and the question is routed normally) |
| parent_id_hash |  | id_hash of the monopolize job whose own request this is. When it matches the pool's active monopolizer, the queued executor stamps it on the job as spawned_by_id_hash, so the consumer's Gate B admits the job through the intake hold instead of deferring it as a foreign writer (same field, same meaning as on /api/v2/submit). Absent = today's behaviour exactly |


## AskResponse


The terminal result of one v2 request.


| Field | Type | Description |
|-------|------|-------------|
| path | string | replay | agent | needs_input | receptionist |
| status | string | done | waiting | parked | needs_input | expired | failed |
| route_reason | string | Why this branch was taken |
| answer |  | The conversational answer (or first question) |
| answer_raw |  | The unformatted answer |
| command |  | The resolved routing command |
| args_known | array | Argument names successfully extracted |
| args_missing | array | Argument names still required |
| pending_id |  | Parked-request id when interactive + needs_input |
| job_id |  | Executor job id (replay id_hash, etc.) |
| snapshot_id |  | Written-back snapshot id, or null |
| replayed_snapshot_id |  | id_hash of the cached row this request REPLAYED (set on both the served and the failed replay); null when nothing was replayed. Distinct from `snapshot_id`, which is the WRITE-BACK id and is null on a warm pass by construction, and from `job_id`, which means a queue job on the agent path |
| similarity |  | Best cache-candidate similarity |
| wrote_snapshot | boolean | Whether a snapshot was written back |
| cache_hit | boolean | Whether this was a tier-1 exact replay |
| spoke | boolean | Whether a TTS notification was dispatched |
| timings_ms | object | Per-stage millisecond offsets |
| trace_id | string | The request's trace id |
| error |  | Degradation error string, when a stage failed |
| queue_position |  | The todo queue's size right after this request's job was queued — a snapshot taken at submit time, not kept current; null when nothing was queued (replay, inline agent, needs_input, failure) |
| submit_details |  | What the command's builder learned about the job it built or declined to build — set only by commands that report it (agent router go to mock job: its resolved `config`, and for a cancelled expeditor test the notification status). Null otherwise |


## AutoRouteOption


The dropdown's "no command named, let the router decide" entry.

It is carried in the response rather than hand-written into the page. The front end
then holds no agent list of its own, not even the one legitimate option. See
registry.AUTO_ROUTE_VALUE for why that is a named sentinel and not an exemption
written into a guard.


| Field | Type | Description |
|-------|------|-------------|
| value | string | Sentinel option value; never a registry command |
| label | string | What to show the user |
| description | string | One-line help text |


## AvailableModesResponse


Response for listing available modes.


| Field | Type | Description |
|-------|------|-------------|
| modes | array |  |


## BatchDeleteResult


Result for a single user in batch delete.


| Field | Type | Description |
|-------|------|-------------|
| user_id | string |  |
| success | boolean |  |
| message | string |  |


## BatchDeleteUsersRequest


Request model for batch user deletion.


| Field | Type | Description |
|-------|------|-------------|
| user_ids | array | List of user IDs to delete (max 50) |
| reason |  | Reason for audit trail |


## BatchDeleteUsersResponse


Response model for batch user deletion.


| Field | Type | Description |
|-------|------|-------------|
| results | array |  |
| total_deleted | integer |  |
| total_failed | integer |  |


## Body_ask_audio_api_v2_ask_audio_post



| Field | Type | Description |
|-------|------|-------------|
| file | string |  |


## Body_transcribe_api_v2_transcribe_post



| Field | Type | Description |
|-------|------|-------------|
| file | string |  |


## Body_upload_and_transcribe_wav_file_api_upload_and_transcribe_wav_post



| Field | Type | Description |
|-------|------|-------------|
| file | string |  |


## Body_upload_docs_file_api_docs_upload_post



| Field | Type | Description |
|-------|------|-------------|
| dir | string | Target folder, `<project>/<rel-dir>` or `io/<rel-dir>` |
| file | string | The file to store |
| on_conflict | string | refuse | replace | rename |


## BroadcastRequestBody


POST /broadcast-to-cc-sessions request body.


| Field | Type | Description |
|-------|------|-------------|
| message | string |  |
| broadcast_id |  |  |
| require_ack | boolean |  |
| include_originator | boolean |  |


## ChangePasswordRequest


Request to change password for authenticated user.


| Field | Type | Description |
|-------|------|-------------|
| current_password | string | Current password for verification |
| new_password | string | New password (min 8 characters, must include uppercase, lowercase, digit, special char) |


## CodeSimilarityResult


Individual result for code/explanation/gist similarity search.


| Field | Type | Description |
|-------|------|-------------|
| id_hash | string | Unique identifier (MD5 hash) |
| question_preview | string | Truncated question (100 chars) |
| code_preview | string | Truncated code (200 chars) |
| solution_summary_preview | string | Truncated explanation (200 chars) |
| solution_summary_gist | string | Concise gist of solution_summary |
| similarity | number | Similarity score (0-100) |
| created_date | string | Creation timestamp |


## CreateUserRequest


Request model for admin user creation.


| Field | Type | Description |
|-------|------|-------------|
| email | string | Email address for new user |
| password | string | Initial password |
| roles | array | Roles to assign (admin, user) |


## CreateUserResponse


Response model for user creation.


| Field | Type | Description |
|-------|------|-------------|
| message | string |  |
| user | object |  |
| user_id | string |  |


## DeleteUserRequest


Request model for admin user deletion.


| Field | Type | Description |
|-------|------|-------------|
| reason |  | Reason for audit trail |


## DmRespondRequest


POST /api/dm/respond request body: a threaded peer-DM reply.

Identical to DmSendRequest except `reply_to` and `thread_id` are required.
A reply must name the message it answers and the conversation it continues.


| Field | Type | Description |
|-------|------|-------------|
| sender_session_id | string |  |
| body | string |  |
| reply_to | string |  |
| thread_id | string |  |
| recipient_session_id |  |  |
| recipient_persona |  |  |
| sender_persona |  |  |
| sender_icon |  |  |
| sender_project |  |  |


## DmSendRequest


POST /api/dm/send request body for a notification-native AI to AI DM.

The recipient is addressed by persona name (preferred) or explicit session id.
Resolution is same-user scoped. The message body travels inline, with no claim-check.
Threading is carried by `reply_to` (the message being answered) and `thread_id`
(conversation correlation, defaulting to a fresh id server-side when omitted).
`sender_persona` and `sender_icon` carry the sender's identity, so the recipient can
frame it as "[DM from <persona> <icon>]".


| Field | Type | Description |
|-------|------|-------------|
| sender_session_id | string |  |
| body | string |  |
| recipient_session_id |  |  |
| recipient_persona |  |  |
| sender_persona |  |  |
| sender_icon |  |  |
| reply_to |  |  |
| thread_id |  |  |
| sender_project |  |  |


## EmbedBatchRequest


Request body for batch embedding generation.


| Field | Type | Description |
|-------|------|-------------|
| texts | array |  |
| content_type | string |  |


## EmbedBatchResponse


Response for batch embeddings.


| Field | Type | Description |
|-------|------|-------------|
| embeddings | array |  |
| dimensions | integer |  |
| count | integer |  |


## EmbedInfoResponse


Response for provider info.


| Field | Type | Description |
|-------|------|-------------|
| provider | string |  |
| dimensions | integer |  |
| status | string |  |


## EmbedRequest


Request body for single-text embedding generation.


| Field | Type | Description |
|-------|------|-------------|
| text | string |  |
| content_type | string |  |


## EmbedResponse


Response for single embedding.


| Field | Type | Description |
|-------|------|-------------|
| embedding | array |  |
| dimensions | integer |  |


## ErrorResponse


Error response for authentication endpoints.

Contains:
    - detail: Error message
    - error_code: Optional error code


| Field | Type | Description |
|-------|------|-------------|
| detail | string | Error message |
| error_code |  | Error code for client handling |


## FleetSizeCapIn


Body for PUT /api/arbiter/fleet-size-cap, the one number the operator is setting.

`ge=1` is declared here rather than hand-rolled in the handler, so Pydantic refuses
a nonsense value with a 422 naming the field. The upper bound is not declared here
and cannot be. The ceiling is `cc session fleet size cap maximum`, read at call time,
so the handler checks it against the live key.


| Field | Type | Description |
|-------|------|-------------|
| cap | integer | The fleet-wide session cap to persist. |


## FleetSnapshotIn


Push body for POST /api/arbiter/fleet-snapshot (the standalone-arbiter path).

Shape mirrors fleet_render.build_snapshot output. Validated by Pydantic
(constraints declared here, never hand-rolled if/raise) — `session_count`
is coerced to a non-negative int; `sessions` defaults to an empty list.


| Field | Type | Description |
|-------|------|-------------|
| generated_at |  |  |
| session_count | integer |  |
| sessions | array |  |


## FlowRatioSettingsRequest


A PATCH of the operator's ratio controls. Every field is optional.

Omitting a field leaves it alone and does not reset it. An operator dragging the
threshold slider must not silently revert a window someone else set, so this is a
partial update rather than a replace.


| Field | Type | Description |
|-------|------|-------------|
| window_hours |  | Rolling window the ratio is counted over, in hours. |
| allow_below |  | The gate opens on a ratio STRICTLY BELOW this number. |


## HTTPValidationError



| Field | Type | Description |
|-------|------|-------------|
| detail | array |  |


## LoginRequest


User login request.

Requires:
    - email: User email address
    - password: User password


| Field | Type | Description |
|-------|------|-------------|
| email | string | User email address |
| password | string | User password |


## LoginResponse


User login response.

Contains:
    - message: Success message
    - user: User information
    - tokens: JWT token pair


| Field | Type | Description |
|-------|------|-------------|
| message | string | Success message |
| user |  | User information |
| tokens |  | JWT token pair |


## LogoutRequest


User logout request.

Requires:
    - refresh_token: Refresh token to revoke


| Field | Type | Description |
|-------|------|-------------|
| refresh_token | string | Refresh token to revoke |


## LogoutResponse


User logout response.

Contains:
    - message: Success message


| Field | Type | Description |
|-------|------|-------------|
| message | string | Success message |


## ManagerPullRequest


A flip of the operator's manager-pull toggle. One field, and it is required.

The field is `StrictBool`, not `bool`. Pydantic's lenient bool accepts the string "true",
and `bool( "false" )` is True. A lenient field would let a caller sending "false" switch
the toggle on while believing they had turned it off. This endpoint exists to make that
defect unreachable, and accepting it here would put it back one layer up. The reader still
parses strings, for the operator who hand-edits the file, but nothing should ever arrive
as one.


| Field | Type | Description |
|-------|------|-------------|
| disabled | boolean | True switches pulling into in_progress OFF for everyone but an approver. |


## ModeChangeResponse


Response for mode changes.


| Field | Type | Description |
|-------|------|-------------|
| user_id | string |  |
| mode |  |  |
| display_name | string |  |
| is_system_mode | boolean |  |
| previous_mode |  |  |
| message | string |  |


## ModeInfo


Information about a single mode.


| Field | Type | Description |
|-------|------|-------------|
| key | string |  |
| display_name | string |  |
| description | string |  |


## ModeResponse


Response for mode queries.


| Field | Type | Description |
|-------|------|-------------|
| user_id | string |  |
| mode |  |  |
| display_name | string |  |
| is_system_mode | boolean |  |


## ModeSetRequest


Request body for setting user mode.


| Field | Type | Description |
|-------|------|-------------|
| mode |  |  |


## MultiplexerConfigResponse


Display-tuning values for the multiplexer front-end.

Field names use snake_case to match server convention. Keys here become
properties on the JSON object that `boot.ts` reads via
`configureMetaDisplayCap(serverConfig)`.


| Field | Type | Description |
|-------|------|-------------|
| multiplexer_max_meta_display_bytes | integer |  |
| tts_preview_fraction | number |  |


## PeerQueueResponse


One-shot peer queue snapshot.


| Field | Type | Description |
|-------|------|-------------|
| peer_host | string |  |
| queue_name | string |  |
| fetched_at | string |  |
| total_jobs | integer |  |
| upstream | object | Raw upstream response body |


## PokeMuteRequest



| Field | Type | Description |
|-------|------|-------------|
| muted | boolean |  |


## PredictionVoteRequest


Body for POST /api/notify/prediction-vote/{notification_id}.

The client supplies the hint context it is voting on. `question` and `response_type`
are optional. The endpoint resolves them from the persisted notification when the client
omits them, because notification.message is persisted. The prediction hint's
predicted_value is not persisted, so the client must supply predicted_value.


| Field | Type | Description |
|-------|------|-------------|
| vote | string |  |
| predicted_value |  |  |
| question |  |  |
| category |  |  |
| response_type |  |  |


## PushPauseRequest



| Field | Type | Description |
|-------|------|-------------|
| paused | boolean |  |
| minutes |  |  |


## RefreshRequest


Token refresh request.

Requires:
    - refresh_token: Valid refresh token JWT


| Field | Type | Description |
|-------|------|-------------|
| refresh_token | string | Refresh token from previous login |


## RefreshResponse


Token refresh response.

Contains:
    - message: Success message
    - tokens: New JWT token pair


| Field | Type | Description |
|-------|------|-------------|
| message | string | Success message |
| tokens |  | New JWT token pair |


## RefreshSourceResponse


Response model for refresh-source endpoint.


| Field | Type | Description |
|-------|------|-------------|
| status | string |  |
| pid | integer |  |
| env | string |  |


## RegisterRequest


User registration request.

Requires:
    - email: Valid email address
    - password: String (will be validated for strength)
    - roles: Optional; only ["user"] is accepted (the route is unauthenticated)


| Field | Type | Description |
|-------|------|-------------|
| email | string | User email address |
| password | string | User password (min 8 chars, must meet strength requirements) |
| roles |  | Only ['user'] is accepted here; any other role is refused with 403. Admins grant roles via /admin/users. |


## RegisterResponse


User registration response.

Contains:
    - message: Success message
    - user: User information
    - tokens: JWT token pair


| Field | Type | Description |
|-------|------|-------------|
| message | string | Success message |
| user |  | User information |
| tokens |  | JWT token pair |


## RegisterTokenRequest



| Field | Type | Description |
|-------|------|-------------|
| token | string |  |
| platform | string |  |
| user_email | string |  |


## RequestFileIn


A manager's request that the operator promote or demote one row.

`move` is validated for membership in the lifecycle module, for the reason
`RequestVerdictIn` gives. `actor` carries the session id the manager check reads. It
is recorded beside the authenticated identity and confers nothing on its own.


| Field | Type | Description |
|-------|------|-------------|
| move | string | admit | demote |
| reason | string | why this row should move — Rick reads it on his board |
| actor | string | persona + session id filing the request |
| deletion_task_id |  | admit only: a live ticket you own, dropped when Rick approves |


## RequestPasswordResetRequest


Request to send password reset email.


| Field | Type | Description |
|-------|------|-------------|
| email | string | Email address to send reset link |


## RequestVerdictIn


The operator's answer to a pending promote/demote request.

`verdict` is validated for membership in the lifecycle module and not here. A second copy
of the legal set is a second thing to keep in sync. The refusal it produces there
already explains why 'pending' is not a verdict.


| Field | Type | Description |
|-------|------|-------------|
| verdict | string | approved | denied |
| next_chase_ts |  |  |
| reason |  | Rick's note on the move; the transition records it beside the request |


## ResetPasswordResponse


Response model for password reset.


| Field | Type | Description |
|-------|------|-------------|
| message | string |  |
| temporary_password | string |  |
| user | object |  |


## ResumeJobRequest


Request body for POST /api/v2/resume-job.


| Field | Type | Description |
|-------|------|-------------|
| resume_from | string | A stalled job's id_hash, or (TFE) a job id, a plan document path, or a description of the job |
| lead_model_override |  | Per-resume lead model; the INI default applies when absent |
| worker_model_override |  | Per-resume worker model; the INI default applies when absent |
| thinking_effort |  | Extended-thinking level for this resume |


## ResumeJobResponse


The result of one resume-job request.


| Field | Type | Description |
|-------|------|-------------|
| status | string | resumed | ambiguous |
| resumed_job_id |  | The NEW job's id_hash (resumed only) |
| original_job_id |  | The stalled job that was resumed (resumed only) |
| resume_from_phase |  | Phase ordinal the new job resumes from |
| phase_name |  | Phase name the new job resumes from |
| resume_count |  | How many times this lineage has been resumed |
| queue_position |  | Todo-queue size right after the new job was pushed; null when nothing was pushed |
| source_type |  | How resume_from was resolved: job_id | plan_path | fuzzy | direct |
| matched_path |  | The plan path that matched, when source_type is plan_path |
| confidence |  | Resolver confidence |
| candidates |  | Possible matches, when status is ambiguous |
| diagnostic |  | Why the resolver answered as it did |


## ResumeRequest


Request body for POST /api/v2/resume — the second turn of a parked flow.


| Field | Type | Description |
|-------|------|-------------|
| pending_id | string | The parked-request id returned by a prior needs_input response |
| answer | string | The human's reply to the parked question |
| websocket_id |  | WebSocket session ID for TTS routing |
| speak | boolean | Dispatch the answer as a TTS notification |


## SearchSnapshotsResponse


Response model for snapshot search endpoint.


| Field | Type | Description |
|-------|------|-------------|
| results | array |  |
| total | integer |  |
| query | string |  |


## SimilarSnapshotsResponse


Response model for similar snapshots endpoint.


| Field | Type | Description |
|-------|------|-------------|
| source_id_hash | string | ID hash of source snapshot |
| source_question | string | Question from source snapshot |
| code_similar | array | Snapshots with similar code |
| explanation_similar | array | Snapshots with similar explanations |
| total_code_matches | integer | Count of code-similar snapshots |
| total_explanation_matches | integer | Count of explanation-similar snapshots |


## SimilarityConfirmationRequest



| Field | Type | Description |
|-------|------|-------------|
| enabled | boolean |  |


## SnapshotDetailResponse


Response model for detailed snapshot information.


| Field | Type | Description |
|-------|------|-------------|
| id_hash | string |  |
| question | string |  |
| question_normalized | string |  |
| question_gist | string |  |
| answer | string |  |
| answer_conversational | string |  |
| runtime_stats | object |  |
| code | array |  |
| solution_summary | string |  |
| solution_summary_gist | string |  |
| synonymous_questions | object |  |
| synonymous_question_gists | object |  |
| created_date | string |  |
| user_id | string |  |


## SnapshotPreviewResponse


Response model for hover preview data.


| Field | Type | Description |
|-------|------|-------------|
| id_hash | string | Unique identifier (MD5 hash) |
| code_preview | string | First 300 chars of joined code |
| solution_summary_gist | string | Concise gist of solution_summary |
| question | string | Full question text |


## SnapshotSearchResult


Individual search result for solution snapshot.


| Field | Type | Description |
|-------|------|-------------|
| id_hash | string | Unique identifier (MD5 hash) |
| question_preview | string | Truncated question (100 chars) |
| question_gist | string | Condensed semantic summary |
| created_date | string | Creation timestamp |
| score | number | Similarity score (0-100) |


## SpeakerphoneBody


POST body for setting speakerphone state.

Requires:
    - on is a bool (True to enable speakerphone, False to disable)


| Field | Type | Description |
|-------|------|-------------|
| on | boolean |  |


## SubmitRequest


Request body for POST /api/v2/submit — work whose command is already decided.

`question` is optional here and required on `ask`, which is the whole difference
between the two doors. `ask` is handed prose and has to work out what it means.
`submit` is handed the answer up front. The text is only carried along for the
record and for anything downstream that shows the user what ran.

The last three fields are queue directives, not arguments. That is why they are
top-level fields rather than keys inside `args`. `args` is checked against the
command's own argument contract. A scheduling instruction put there would have to be
written into some agent's contract as though the agent took it, and no agent does.
Each retiring door declared these same three on its own request model. They arrive
here for the same reason, and are passed on only when the caller actually set one.


| Field | Type | Description |
|-------|------|-------------|
| command | string | The routing command, e.g. 'agent router go to weather' |
| args | object | Every argument the command requires — no extraction is performed |
| question |  | Optional human-readable text for the record |
| websocket_id |  | WebSocket session ID for TTS routing |
| speak | boolean | Dispatch the answer as a TTS notification |
| scheduled_at |  | ISO datetime to defer execution to (None = run when the queue reaches it). The off-peak scheduling rule is built on this field |
| monopolize | boolean | Run exclusively, holding every other job until this one finishes |
| parent_id_hash |  | id_hash of the monopolize job that SPAWNED this one. When it matches the pool's active monopolizer, the consumer's Gate B admits this child THROUGH the intake hold instead of deferring it as a foreign writer (bugs 3a14292b, 5ed4f187). Reaches the job as spawned_by_id_hash |


## TaskAmendIn


Body for POST /api/tasks/{id}/amend, an append-only body amendment.

It appends a persona-stamped, UTC-timestamped block to the body of a non-terminal item
without rewriting the existing text. This is the durable-record seam for a live item whose
scope is legitimately reframed mid-flight. It differs from PATCH `body`, which overwrites,
because an amend can never lose prior spec history. `note` is the text appended. `reason`
stamps the audit event, mirroring the PATCH reason discipline, and falls back to an
auto-marker when absent. `actor` and `authority` stamp the event, not the item.


| Field | Type | Description |
|-------|------|-------------|
| note | string | the amendment text appended to the item body (original preserved verbatim) |
| actor | string | persona + session id performing the amendment |
| authority | string |  |
| reason |  | free-text justification stamping the 'amended' audit event; falls back to an auto-marker when absent |


## TaskCorrelateIn


Body for POST /api/tasks/{id}/correlate, the cross-session respawn adoption seam.

It re-stamps an item's correlation_key onto a successor session's harness task id instead of
forking a duplicate item. The handler rejects terminal items, so closed history is never
re-keyed. It also validates the authority enum there, so the rules live in one place.


| Field | Type | Description |
|-------|------|-------------|
| correlation_key | string |  |
| actor | string | persona + session id performing the re-correlation |
| authority | string |  |


## TaskCreateIn


Create body for POST /api/tasks.

Creation defaults to status=queued, and the creation event stamps "->queued". The handler
validates enum membership for item_class, gate_class, priority and authority through
`task_store_rules.validate_create`. The rules live in one place and are not duplicated
per layer.

`status` may also be "blocked", which mints an already-blocked row in one call. A blocked
mint carries `blocked_by` (at least one typed ref) and `next_chase_ts`, which a persona
blocker requires. `rules.validate_create_status` enforces both and reuses the same
`->blocked` invariant a transition applies. A blocked mint is also manager-only, guarded in
the handler through `is_manager_figure`. `status` is otherwise limited to queued or blocked.
The statuses done, dropped, parked, claimed, in_progress and review are not mintable.

The create door narrows both paragraphs above. With the holding default on, an omitted
status mints `not_approved`. An explicit live status (queued or blocked) is refused with 403
unless the row is P0 or the caller is the operator's validated login. See
`task_approval_settings.refusal_for_live_mint`. A seat's one-call blocked mint is therefore
retired, and the manager guard still covers the two paths that pass.


| Field | Type | Description |
|-------|------|-------------|
| item_class | string |  |
| title | string |  |
| project | string |  |
| created_by | string | persona + session id of the creator |
| authority | string |  |
| body |  |  |
| owner_persona |  |  |
| accountable_manager |  |  |
| gate_class | string |  |
| priority | string |  |
| urgency | string |  |
| status | string | mint status — queued (default) or blocked (manager-only, one-call blocked mint) |
| blocked_by |  | typed refs [{kind, id}] — REQUIRED (>=1) for a blocked mint; ignored for queued |
| next_chase_ts |  | ISO-8601 chase time — REQUIRED for a blocked mint whose blocked_by names a {kind:persona} ref (I3) |
| source_qid |  |  |
| correlation_key |  |  |


## TaskPatchIn


Body for PATCH /api/tasks/{id}, an item-field edit.

It edits the mutable presentation and ownership fields of a non-terminal item. `status`,
`blocked_by`, `next_chase_ts`, `receipt_refs` and `correlation_key` are left out of this body.
They ride the transition oracle (`validate_transition`) and the /correlate
seam, never an item PATCH. `extra='forbid'` makes that a hard wire-level invariant, because
naming any of them is a 422 and not a silent drop. PATCH can therefore never bypass the
oracle. `actor`, `authority` and `reason` stamp the audit event, not the item. `reason` is
not an editable field. It is the manager-supplied "why" for a reassignment, and when absent
the event records the auto-generated field delta.


| Field | Type | Description |
|-------|------|-------------|
| title |  |  |
| body |  |  |
| priority |  |  |
| owner_persona |  |  |
| accountable_manager |  |  |
| gate_class |  |  |
| urgency |  |  |
| actor | string | persona + session id performing the edit |
| authority | string |  |
| reason |  | free-text justification for the edit (e.g. why a task was reassigned); stamps the 'patched' audit event, falling back to the field delta when absent |


## TaskTransitionIn


Transition body for POST /api/tasks/{id}/transition.

Structural rules (terminal states, receipts on ->done, next_chase_ts +
typed blocked_by on ->blocked, non-blank reason on ->dropped) are
validated by task_store_rules.validate_transition in the handler.


| Field | Type | Description |
|-------|------|-------------|
| to_status | string |  |
| actor | string | persona + session id performing the transition |
| authority | string |  |
| receipt_refs |  |  |
| next_chase_ts |  |  |
| blocked_by |  |  |
| reason |  | free-text justification; REQUIRED non-blank for ->dropped (C12) |
| park_reason |  | REQUIRED non-blank for ->parked; MUST quote the row's OWN decisive sentence, not a paraphrase |
| asynchronous |  | opt in to the asynchronous promotion path (202 + ticket). Boolean ONLY — a string is refused. Ignored unless the operator flag 'task approval promotion ask asynchronous' is on. |


## TokenResponse


JWT token pair response.

Contains:
    - access_token: Short-lived JWT for API access
    - refresh_token: Long-lived JWT for token refresh
    - token_type: Always "bearer"
    - expires_in: Access token expiration in seconds


| Field | Type | Description |
|-------|------|-------------|
| access_token | string | Short-lived access token (30 min) |
| refresh_token | string | Long-lived refresh token (7 days) |
| token_type | string | Token type (always 'bearer') |
| expires_in | integer | Access token expiration time in seconds |


## TranscribeResponse


The transcript line of /api/v2/ask-audio, without its `type` and without an ask.


| Field | Type | Description |
|-------|------|-------------|
| transcription | string |  |
| trace |  |  |


## TranscribeTrace



| Field | Type | Description |
|-------|------|-------------|
| stt_ms | number |  |
| upload_bytes | integer |  |


## TrustModeUpdateRequest


Request body for updating trust mode at runtime.


| Field | Type | Description |
|-------|------|-------------|
| mode | string |  |
| domain | string | Domain (currently only 'swe') |


## UnparkAskIn


Body for POST /api/tasks/{id}/unpark-ask, a manager asking for the operator's approval.

The row id comes from the path and never from the body. A caller cannot ask about one row
and have the card bound to another. `actor` is the declared persona and session id, which
finds the manager session and words the card.


| Field | Type | Description |
|-------|------|-------------|
| actor | string |  |


## UnregisterTokenRequest



| Field | Type | Description |
|-------|------|-------------|
| token | string |  |


## UpdateRolesRequest


Request model for updating user roles.


| Field | Type | Description |
|-------|------|-------------|
| roles | array | List of roles to assign (admin, user) |


## UpdateStatusRequest


Request model for updating user status.


| Field | Type | Description |
|-------|------|-------------|
| is_active | boolean | Set user active status |


## UserDetailsResponse


Response model for user details endpoint.


| Field | Type | Description |
|-------|------|-------------|
| id | string |  |
| email | string |  |
| roles | array |  |
| email_verified | boolean |  |
| is_active | boolean |  |
| created_at | string |  |
| last_login_at |  |  |
| audit_log_count | integer |  |
| failed_login_count | integer |  |


## UserListResponse


Response model for list users endpoint.


| Field | Type | Description |
|-------|------|-------------|
| users | array |  |
| total | integer |  |
| limit | integer |  |
| offset | integer |  |


## UserResponse


User information response.

Contains:
    - id: User UUID
    - email: User email address
    - roles: List of user roles
    - email_verified: Email verification status
    - is_active: Account active status
    - created_at: Account creation timestamp
    - last_login_at: Last login timestamp (optional)


| Field | Type | Description |
|-------|------|-------------|
| id | string | User unique identifier (UUID) |
| email | string | User email address |
| roles | array | User roles |
| email_verified | boolean | Email verification status |
| is_active | boolean | Account active status |
| created_at | string | Account creation timestamp (ISO 8601) |
| last_login_at |  | Last login timestamp (ISO 8601) |


## ValidationError



| Field | Type | Description |
|-------|------|-------------|
| loc | array |  |
| msg | string |  |
| type | string |  |
| input |  |  |
| ctx | object |  |


## VerifyEmailRequest


Request to verify email address with token.


| Field | Type | Description |
|-------|------|-------------|
| token | string | Email verification token from email |


## VoicePersonaSampleRequest



| Field | Type | Description |
|-------|------|-------------|
| voice_id | string |  |
| text | string |  |


## WatchActionResponse


Generic response for start/stop actions.


| Field | Type | Description |
|-------|------|-------------|
| status | string |  |
| message | string |  |


## WatchStartRequest


Start a peer-queue watcher.


| Field | Type | Description |
|-------|------|-------------|
| host | string | Peer host:port (must be in whitelist) |
| signal | string | Drain signal: 'run' or 'run+todo' |
| interval_seconds | integer | Poll interval (10-600s) |
| stable_for | integer | Consecutive zero polls required |
| priority | string | Notification priority on drain |


## WatchStatusResponse


Current watcher state for the requesting admin.


| Field | Type | Description |
|-------|------|-------------|
| active | boolean |  |
| host |  |  |
| signal |  |  |
| interval_seconds |  |  |
| stable_for |  |  |
| started_at |  |  |
| last_poll_at |  |  |
| last_run |  |  |
| last_todo |  |  |
| consecutive_zero | integer |  |
| last_error |  |  |
| drained_at |  |  |


## cosa__rest__auth_models__MessageResponse


Generic message response.


| Field | Type | Description |
|-------|------|-------------|
| message | string | Status message |


## cosa__rest__auth_models__ResetPasswordRequest


Request to reset password with token.


| Field | Type | Description |
|-------|------|-------------|
| token | string | Password reset token from email |
| new_password | string | New password (min 8 characters, must include uppercase, lowercase, digit, special char) |


## cosa__rest__routers__admin__MessageResponse


Generic message response.


| Field | Type | Description |
|-------|------|-------------|
| message | string |  |
| user |  |  |


## cosa__rest__routers__admin__ResetPasswordRequest


Request model for admin password reset.


| Field | Type | Description |
|-------|------|-------------|
| reason |  | Optional reason for audit trail |

---
_Auto-generated on 2026.10.08 10:30:05 by `src/scripts/generate-api-docs.sh`_
