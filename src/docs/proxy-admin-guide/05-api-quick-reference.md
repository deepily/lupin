> Part 5 of 6 of the [Decision Proxy — Admin Guide](../proxy-admin-guide.md): API quick reference.

## 8. Quick Reference: API Endpoints

These are the REST endpoints that power both admin pages. Useful for debugging or
building custom tooling.

| Method | Endpoint | Used By | Description |
|--------|----------|---------|-------------|
| `GET` | `/api/proxy/pending/{user_email}` | Ratification page | Get all pending decisions for a user. Supports `?domain=` and `?category=` filters. |
| `POST` | `/api/proxy/ratify/{decision_id}` | Ratification page | Approve or reject a decision. Query params: `?approved=true&user_email=...&feedback=...` — `user_email` must be the caller's own (403 otherwise), and the `ratified_by` actually recorded comes from the credential, not from it. |
| `DELETE` | `/api/proxy/decision/{decision_id}` | Ratification page | Permanently delete a pending decision. Query param: `?user_email=...`, which must be the caller's own; `deleted_by` is recorded from the credential. Only pending decisions can be deleted. |
| `GET` | `/api/proxy/trust/{user_email}` | Dashboard | Get all trust states for a user. Supports `?domain=` filter. |
| `GET` | `/api/proxy/decisions/{domain}/{category}` | Dashboard | Get recent decision history for a domain+category. Supports `?limit=` param. |
| `GET` | `/api/proxy/mode` | Dashboard | Get current effective trust mode (INI config + running job). |
| `PUT` | `/api/proxy/mode` | Dashboard | Update trust mode. Body: `{"mode": "active", "domain": "swe"}`. Hot-reloads running job if present. |
| `GET` | `/api/proxy/batch-id` | Notifications | Get current proxy batch progress_group_id. |
| `POST` | `/api/proxy/acknowledge` | Notifications | Retire current batch and start a new one. |

### Authentication

Warning: **This section said the opposite until it was corrected, and the sentence it used to carry is why the hole lasted**.
It read: *"All endpoints except `/api/proxy/batch-id` and `/api/proxy/acknowledge` require an authenticated session."*
That was false for five endpoints.
Anyone checking whether this API was safe would have read it and stopped looking.
That is the failure mode of a wrong reassurance, which a wrong instruction does not have.

**Measured at the path**, driving the real router through a TestClient with **no credential at all**, not read off the decorators:

| endpoint | before | now |
|---|---|---|
| `GET /api/proxy/pending/{user_email}` | **200, reached the handler** | **401** without a credential, **403** if the path names another user |
| `GET /api/proxy/trust/{user_email}` | **200, reached the handler** | same gate |
| `GET /api/proxy/batch-id` | 200 | **401** — gated |
| `POST /api/proxy/acknowledge` | 200 | **401** — gated |
| `GET /api/proxy/decisions/{domain}/{category}` | 200 | **401** — gated |
| `POST /api/proxy/ratify/{decision_id}` | **reached the database** | **401** without a credential, **403** if `?user_email=` names another user |
| `DELETE /api/proxy/decision/{decision_id}` | **reached the database** | same gate |
| `GET` / `PUT /api/proxy/mode` | 401 | unchanged — gated |

The two user-keyed routes are **owner-only, with no admin bypass**, per Mr. Radio's ruling.
The email in the path must be the caller's own, matched ignoring case.
The admin pages already satisfy this.
Both `proxy-dashboard.js` and `proxy-ratify.js` set `userEmail` from `getCurrentUser()`, so they only ask for the signed-in user's own data.
`apiCall()` sends the credential by default.

#### The remaining five, closed

Re-measured the same way, with the real router and no credential, **all nine endpoints now answer 401**.
Three things had to happen, and two of them are not "add a decorator".

**`ratify` and `decision` needed a different guard**.
Their `user_email` arrives in the **query** string.
`require_path_identity_owner` reads `request.path_params` and, by choice, raises 500 for a route that names no user in its path.
`require_query_identity_owner` is its sibling in the same module.
It has the same 401 via `require_api_key_or_jwt` and the same 403 for a caller who is not the user named, reading the query instead.
A bare uncredentialed call to either used to answer **422** for the missing `user_email`, which reads like a refusal and is not one.
A route-level `Depends` raising 401 preempts that 422. That was measured with a TestClient, not assumed.

**Their audit columns were recording a claim, not a fact**.
`ratified_by` and `deleted_by` were written from the query string.
The ownership check alone does not repair that.
The check accepts the caller's bare user id and compares email without regard to case, so one person can present three strings that all pass.
Both handlers now take the identity from the credential.
That identity also keys the trust-state counter, where two spellings of one user would have split the counter and given a quietly wrong answer.

**`batch-id` needed its caller fixed first**.
The route was left open because of `swe_team/orchestrator.py`'s proxy-summary fetch, which sent no credential.
It now sends its API key.
Warning: The header helper returns an empty dict rather than raising when no key loads, because its caller must never take a SWE run down.
A misconfigured box therefore degrades to a 401 that the surrounding `try/except` swallows into a warning.
The symptom would be a proxy notification that silently stops updating in place.
The warning names the endpoint, which is the only thing that makes that findable.

Warning: **`acknowledge` has a credential and no owner check, and that is a residue, not a finish**.
An owner check was ruled onto it alongside ratify and delete.
`_proxy_batch_state` is a single process-global counter, not a per-user record.
There is no per-user batch for an owner check to be about.
**Any credentialed caller can still retire another user's displayed batch**.
Making the batch per-user is a design change, not an authorization fix, and it is not done here.
It is carried forward as an open item in the Known Limitations section, with the measurement and what a test watches.

Warning: an earlier version of this paragraph said the route "takes no identity parameter in path, query or body".
That was too strong, and it pointed at the wrong remedy.
The handler signature takes none, and both callers POST body-less.
But `require_api_key_or_jwt` **returns the caller's user id** on both of its branches.
That is `return user_id` for an API key and `return user_info[ "uid" ]` for a JWT.
So an identity is resolved on every successful request.
It is discarded because the route wires the dependency as a bare `dependencies=[ Depends( … ) ]` entry, and FastAPI throws that return value away.
Identity is one wiring change away. The global counter is the actual obstacle.
The correction came from reading the dependency rather than the route.

The admin pages handle authentication automatically via the shared `auth.js` module.

---
