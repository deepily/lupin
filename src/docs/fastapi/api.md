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
## GET `/api/server-info`

> **Get server info**

Return current config block ID, masked database URL, and environment name.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/init`

> **Hot-reload configuration**

Reload configuration and optionally swap active config block and database connection at runtime.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| config_block_id |  | False |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
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
## POST `/api/notify`

> **Send notification**

Dispatch notification to a user via WebSocket. Supports fire-and-forget or SSE blocking mode for response-required notifications.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| message | string | True | Notification message text |
| type | string | False | Notification type (task, progress, alert, custom) |
| priority | string | False | Priority level (low, medium, high, urgent) |
| target_user | string | True | Target user email address (required - configure in CLI config or pass explicitly) |
| response_requested | boolean | False | Whether notification requires user response (Phase 2.1) |
| response_type |  | False | Response type: yes_no or open_ended (Phase 2.1) |
| timeout_seconds | integer | False | Timeout in seconds for response-required notifications |
| response_default |  | False | Default response value for timeout/offline (Phase 2.1) |
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





### 📦 Request Body 

object

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/notifications/{user_id}`

> **Get user notifications**

Retrieve notifications for a user from the in-memory FIFO queue with optional played filter and count limit.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| user_id | string | True |  |
| include_played | boolean | False | Include played notifications |
| limit | integer | False | Maximum number of notifications to return |


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


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/notifications/generate-gist`

> **Generate session gist**

Use LLM to generate a concise semantic session name from notification messages.





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

Accept base64-encoded MP3, transcribe via Whisper, and queue result as a multimodal job.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| prefix |  | False |  |
| prompt_key | string | False |  |
| prompt_verbose | string | False |  |


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

> **Push job to queue**

Submit a new job to the todo queue. Requires question and websocket_id in request body.





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

> **Cancel running job**

Request graceful cancellation of a running agentic job at its next phase boundary.



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
## POST `/api/claude-code/dispatch`

> **Dispatch Claude Code task**

Launch a Claude Agent SDK task in BOUNDED or INTERACTIVE mode. Returns task_id and WebSocket URL.





### 📦 Request Body 

[DispatchRequest](#dispatchrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [DispatchResponse](#dispatchresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/claude-code/{task_id}/inject`

> **Inject message into session**

Send a follow-up message into an active INTERACTIVE session.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |


### 📦 Request Body 

[InjectRequest](#injectrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/claude-code/{task_id}/interrupt`

> **Interrupt active session**

Interrupt the current response in an INTERACTIVE session.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/claude-code/{task_id}/end`

> **End interactive session**

Gracefully end an INTERACTIVE session and close its WebSocket.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/claude-code/{task_id}/status`

> **Get task status**

Return current status, cost, and error state for a Claude Code task.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| task_id | string | True |  |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/claude-code/queue/submit`

> **Submit Claude Code queue job**

Submit a Claude Agent SDK task to the CJ Flow queue in BOUNDED or INTERACTIVE mode.





### 📦 Request Body 

[ClaudeCodeQueueRequest](#claudecodequeuerequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [ClaudeCodeQueueResponse](#claudecodequeueresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
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

> **Submit deep research job**

Create a deep research job and push to the CJ Flow todo queue.





### 📦 Request Body 

[DeepResearchSubmitRequest](#deepresearchsubmitrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [DeepResearchSubmitResponse](#deepresearchsubmitresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
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
## POST `/api/mock-job/submit`

> **Submit mock job**

Submit a zero-cost mock job for queue UI testing with configurable parameters.





### 📦 Request Body 

[MockJobSubmitRequest](#mockjobsubmitrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [MockJobSubmitResponse](#mockjobsubmitresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/mock-job/health`

> **Mock job health check**

Return availability status of the mock job endpoint.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## POST `/api/podcast-generator/submit`

> **Submit podcast generation job**

Submit a podcast generation job. Accepts either a direct file path or a natural language description.





### 📦 Request Body 

[PodcastSubmitRequest](#podcastsubmitrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | 
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/deep-research-to-podcast/submit`

> **Submit research→podcast chained job**

Submit a deep research job that automatically generates a podcast upon completion.





### 📦 Request Body 

[ResearchToPodcastSubmitRequest](#researchtopodcastsubmitrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [ResearchToPodcastSubmitResponse](#researchtopodcastsubmitresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/swe-team/submit`

> **Submit SWE team task**

Submit an engineering task to the SWE Team for async execution via CJ Flow.





### 📦 Request Body 

[SweTeamSubmitRequest](#sweteamsubmitrequest)

### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | [SweTeamSubmitResponse](#sweteamsubmitresponse)
 |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/proxy/acknowledge`

> **Acknowledge proxy batch**

Retire current proxy notification batch and start a new one.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
## GET `/api/proxy/batch-id`

> **Get proxy batch ID**

Return the current proxy batch progress_group_id.





### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
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


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## POST `/api/proxy/ratify/{decision_id}`

> **Ratify decision**

Approve or reject a pending decision. Updates ratification state and trust counters.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| decision_id | string | True |  |
| approved | boolean | True | True to approve, False to reject |
| feedback | string | False | Optional feedback text |
| user_email | string | True | Email of the ratifying user |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## DELETE `/api/proxy/decision/{decision_id}`

> **Delete pending decision**

Hard-delete a decision in pending state. Approved/rejected decisions are protected.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| decision_id | string | True |  |
| user_email | string | True | Email of the user performing deletion (audit) |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
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


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
| 422 | Validation Error | [HTTPValidationError](#httpvalidationerror)
 |
## GET `/api/proxy/decisions/{domain}/{category}`

> **Get decisions by domain**

Return decision history for a specific domain and category combination.



### 🔗 Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| domain | string | True |  |
| category | string | True |  |
| limit | integer | False | Maximum number of decisions to return |


### ✅ Responses

| Status Code | Description | Component |
|-------------|-------------|-----------|
| 200 | Successful Response | ... |
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
---

# 📋 Components



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


## Body_upload_and_transcribe_wav_file_api_upload_and_transcribe_wav_post



| Field | Type | Description |
|-------|------|-------------|
| file | string |  |


## ChangePasswordRequest


Request to change password for authenticated user.


| Field | Type | Description |
|-------|------|-------------|
| current_password | string | Current password for verification |
| new_password | string | New password (min 8 characters, must include uppercase, lowercase, digit, special char) |


## ClaudeCodeQueueRequest


Request body for submitting a Claude Code task to the queue.


| Field | Type | Description |
|-------|------|-------------|
| prompt | string | The task prompt for Claude Code |
| project | string | Target project name (e.g., lupin, cosa) |
| task_type | string | Task type: BOUNDED or INTERACTIVE |
| max_turns | integer | Maximum agentic turns |
| websocket_id |  | WebSocket session ID for notifications |
| dry_run | boolean | If True, simulate execution without running Claude Code |


## ClaudeCodeQueueResponse


Response body for Claude Code queue submission.


| Field | Type | Description |
|-------|------|-------------|
| status | string | Job status (queued) |
| job_id | string | Unique job identifier (cc-{uuid8}) |
| queue_position | integer | Position in the todo queue |
| message | string | Human-readable confirmation message |


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


## DeepResearchSubmitRequest


Request body for submitting a deep research job.


| Field | Type | Description |
|-------|------|-------------|
| query | string | The research query to investigate |
| budget |  | Maximum budget in USD (None = unlimited) |
| websocket_id |  | WebSocket session ID for notifications |
| lead_model |  | Model for lead agent (None = use default) |
| dry_run | boolean | Simulate execution without API calls |
| audience |  | Target audience level: beginner, general, expert, academic |
| audience_context |  | Custom audience description |


## DeepResearchSubmitResponse


Response body for deep research job submission.


| Field | Type | Description |
|-------|------|-------------|
| status | string | Job status (queued) |
| job_id | string | Unique job identifier (dr-{uuid8}) |
| queue_position | integer | Position in the todo queue |
| message | string | Human-readable confirmation message |


## DeleteUserRequest


Request model for admin user deletion.


| Field | Type | Description |
|-------|------|-------------|
| reason |  | Reason for audit trail |


## DispatchRequest


Request model for task dispatch.

Attributes:
    project: Target project name (e.g., "lupin", "cosa")
    prompt: Task description/prompt for Claude Code
    task_type: BOUNDED (Option A) or INTERACTIVE (Option B)


| Field | Type | Description |
|-------|------|-------------|
| project | string |  |
| prompt | string |  |
| task_type |  |  |


## DispatchResponse


Response model for task dispatch.

Attributes:
    task_id: Unique identifier for the dispatched task
    status: Current status ("dispatched", "running", etc.)
    websocket_url: WebSocket URL for streaming responses


| Field | Type | Description |
|-------|------|-------------|
| task_id | string |  |
| status | string |  |
| websocket_url | string |  |


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


## HTTPValidationError



| Field | Type | Description |
|-------|------|-------------|
| detail | array |  |


## InjectRequest


Request model for injecting messages into Option B sessions.


| Field | Type | Description |
|-------|------|-------------|
| message | string |  |


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


## MockJobSubmitRequest


Request body for submitting a mock job.


| Field | Type | Description |
|-------|------|-------------|
| iterations_min | integer | Minimum iterations |
| iterations_max | integer | Maximum iterations |
| sleep_min | number | Minimum sleep seconds |
| sleep_max | number | Maximum sleep seconds |
| failure_probability | number | Probability of failure (0-1) |
| fixed_iterations |  | Override random iterations |
| fixed_sleep |  | Override random sleep |
| description |  | Custom description for queue display |
| websocket_id |  | WebSocket session ID for notifications |
| voice_command |  | Test expeditor: provide a voice command to route through RuntimeArgumentExpeditor |


## MockJobSubmitResponse


Response body for mock job submission.


| Field | Type | Description |
|-------|------|-------------|
| status | string | Job status (queued) |
| job_id | string | Unique job identifier (mock-{uuid8}) |
| queue_position | integer | Position in the todo queue |
| config | object | Resolved job configuration |
| message | string | Human-readable confirmation message |


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


## PodcastMatchingResponse


Response when fuzzy matching is triggered.


| Field | Type | Description |
|-------|------|-------------|
| status | string |  |
| message | string |  |


## PodcastSubmitRequest


Request body for podcast generation submission.

The research_source field is overloaded:
- If it looks like a path → direct mode (immediate job creation)
- If it looks like text → description mode (fuzzy match + confirmation)


| Field | Type | Description |
|-------|------|-------------|
| research_source | string |  |
| target_languages |  |  |
| max_segments |  |  |
| dry_run | boolean |  |
| audience |  |  |
| audience_context |  |  |


## PodcastSubmitResponse


Response for successful job submission.


| Field | Type | Description |
|-------|------|-------------|
| job_id | string |  |
| queue_position | integer |  |
| status | string |  |


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


## RegisterRequest


User registration request.

Requires:
    - email: Valid email address
    - password: String (will be validated for strength)
    - roles: Optional list of roles (defaults to ["user"])


| Field | Type | Description |
|-------|------|-------------|
| email | string | User email address |
| password | string | User password (min 8 chars, must meet strength requirements) |
| roles |  | User roles (defaults to ['user']) |


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


## RequestPasswordResetRequest


Request to send password reset email.


| Field | Type | Description |
|-------|------|-------------|
| email | string | Email address to send reset link |


## ResearchToPodcastSubmitRequest


Request body for research→podcast submission.

Mirrors DeepResearchSubmitRequest with additional podcast parameters.


| Field | Type | Description |
|-------|------|-------------|
| query | string | Research topic/question to investigate |
| budget |  | Maximum budget in USD for Deep Research |
| target_languages |  | ISO language codes for audio generation |
| max_segments |  | Limit TTS to first N segments |
| dry_run | boolean | Simulate execution without API calls |


## ResearchToPodcastSubmitResponse


Response for successful job submission.


| Field | Type | Description |
|-------|------|-------------|
| job_id | string | Unique job identifier (rp-xxxxx format) |
| queue_position | integer | Position in the todo queue |
| message | string | Human-readable confirmation message |


## ResetPasswordResponse


Response model for password reset.


| Field | Type | Description |
|-------|------|-------------|
| message | string |  |
| temporary_password | string |  |
| user | object |  |


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


## SweTeamSubmitRequest


Request body for submitting a SWE Team job.


| Field | Type | Description |
|-------|------|-------------|
| task | string | The engineering task to accomplish |
| dry_run | boolean | Simulate execution without API calls |
| websocket_id |  | WebSocket session ID for notifications |
| lead_model |  | Model for lead agent (None = use default) |
| worker_model |  | Model for worker agents (None = use default) |
| budget |  | Maximum budget in USD (None = use default) |
| timeout |  | Wall-clock timeout in seconds (None = use default) |
| trust_mode |  | Trust mode: disabled, shadow, suggest, active (None = use server default) |


## SweTeamSubmitResponse


Response body for SWE Team job submission.


| Field | Type | Description |
|-------|------|-------------|
| status | string | Job status (queued) |
| job_id | string | Unique job identifier (swe-{uuid8}) |
| queue_position | integer | Position in the todo queue |
| message | string | Human-readable confirmation message |


## TaskTypeEnum


Task type selection for dispatch.




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


## TrustModeUpdateRequest


Request body for updating trust mode at runtime.


| Field | Type | Description |
|-------|------|-------------|
| mode | string |  |
| domain | string | Domain (currently only 'swe') |


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


## VerifyEmailRequest


Request to verify email address with token.


| Field | Type | Description |
|-------|------|-------------|
| token | string | Email verification token from email |


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
