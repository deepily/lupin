> Part 6 of 6 of the [Decision Proxy — Admin Guide](../proxy-admin-guide.md): known limitations and related documentation.

## 9. Known Limitations

Open items, each with what was measured.
A limitation listed here is **not** fixed.
This section exists because the item below once sat only in the tail of a subsection titled "remaining five, **closed**".
That subsection is in the API endpoint section, and it held the item for two days.
A reader checking for open problems had no reason to look there.
A finding filed under a heading that says *closed* reads as closed.

### 9.1 Any credentialed caller can retire another user's proxy notification batch

**Status**: open. **Route**: `POST /api/proxy/acknowledge`.
**Measured** by reading `src/cosa/rest/routers/decision_proxy.py` and `src/cosa/rest/middleware/api_key_auth.py`.

The batch a user sees in their notifications is identified by one **process-global** counter:

```python
_proxy_batch_state = {
    "hex"        : uuid.uuid4().hex[ :8 ],   # stable per server lifetime
    "generation" : 1,                        # monotonic batch counter
}
```

`acknowledge_batch()` increments `generation` on that one dict.
It is not keyed by user, so every signed-in user shares a single batch id.
The first caller to acknowledge retires it **for everybody**.
The route is credentialed (`require_api_key_or_jwt`, so an uncredentialed call answers 401) and performs no owner check.
That absence is recorded as a residue rather than an oversight.

**What this would look like to a user**: their proxy notification stops updating in place and a new batch begins.
It happens at a moment they did not choose, because somebody else clicked acknowledge.

🟡 **Latent today**. The conditional above matters.
John measured, and recorded on the row, that **no user has ever had a live proxy batch**.
There are zero proxy batch ids and zero ratified rows, so nobody has been hit by this.
Multi-account use is not rare, though.
**68% of active hours have more than one distinct account authenticating**.
The defect becomes real the first time proxy batches are used at all.
Warning: Those two counts are inherited from John's report and are not re-derived here.
The code reading above is mine.
Re-measure before treating either as current.

**The open decision is Rick's**.
Per the row, the choice is between two moves:

- Fix now: per-user batch state keyed on the credential's canonical email, plus the owner check, with both callers changed.
- Leave it documented until proxy batches are switched on.

Mr. Radio's recommendation on the row is to document now and fix before batches go live, which is what this entry is.

**Two claims about this are easy to get wrong**.
Both were checked at the source rather than inferred from the route decorator:

| claim | verdict |
|---|---|
| "The request carries no identity. So an owner check is impossible." | **False**. `require_api_key_or_jwt` returns the caller's user id on both branches. `return user_id` for an `X-API-Key`, `return user_info[ "uid" ]` for a `Bearer` JWT. An identity is resolved on every successful request. |
| "The handler receives that identity." | **False**. The route wires the dependency as `dependencies=[ Depends( require_api_key_or_jwt ) ]`, and FastAPI discards a bare `dependencies=` entry's return value. `async def acknowledge_proxy_batch()` takes no parameters, so nothing reaches it. |

So the blocker is the shared counter, not missing identity.
Wiring the identity into the handler is a one-line change: `user_id: str = Depends( require_api_key_or_jwt )`.
It would buy nothing on its own, because there is still only one batch for the check to be about.
The fix is to key the batch per user, which is a design change.

**Why it has not simply been gated**.
Inventing a required `user_email` parameter would 400 both existing callers.
Those callers are `notifications.js` (`fetch('/api/proxy/acknowledge', { method: 'POST', headers: self.getAuthHeaders() })`, no body) and `ApiClient.acknowledgeProxy()` (no arguments).
It would also gate a counter that is shared regardless.

**What the tests do and do not watch**.
The route is not untested, so say which: "untested" and "tested for something else" call for different work.

| watched | by |
|---|---|
| the counter increments and the old batch id is returned | `test_acknowledge_increments` (`src/cosa/tests/unit/rest/test_decision_proxy_router.py`) |
| an uncredentialed POST answers 401 | `test_proxy_and_reset_routes_refuse_the_uncredentialed.py` |
| a credentialed POST answers 200, not merely "not 401" | `test_a_credential_only_route_admits_any_valid_caller`, same file |
| **the cross-user consequence — that one user's acknowledge retires another's batch** | **nothing** |

The third test's docstring states the design choice in place.
It says these routes carry no owner check because there is no owner in any of them to be.
So the current behaviour is pinned as intended, and the sharing itself is unwatched.
If the batch is later made per-user, no existing test fails to mark the change.
If a refactor widens the sharing, none notices.

---

## Related Documentation

- **Notification API Reference**: `src/docs/notification-api.md` — comprehensive notification system docs
- **WebSocket Events**: `src/docs/websocket-events.md` — event catalog including `proxy_decision_new`
- **Decision Proxy Architecture**: `src/rnd/2026.02.14-swe-team-phase-4-decision-proxy-architecture/`. Design context and 4-layer architecture
- **Automated Interactive Testing**: `src/docs/automated-interactive-testing.md` — proxy auto-answer testing guide
