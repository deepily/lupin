# 12 — Rio ⚡ → C4 Author: rest/ AUTH CLUSTER 4 (auth.py + auth/admin routers) Handoff

> **Purpose:** seed a FRESH author to finish the rest/ AUTH lane's last cluster (C4) at
> genuine 100% L/B/F, with zero rediscovery. Written 2026-06-01 by Rio ⚡ (idx3) at the
> approved honest-stop after C1–C3 (19/22 units, all 100%). Manager = Tiberius 👑.
>
> **READ FIRST:** this file, then **`11-rest-greenfield-b5-b7-handoff.md` (Tiffany)** — its
> two GOTCHAS will bite the auth routers HARD (see §Gotchas below). Skim the existing
> router tests in `src/cosa/tests/unit/rest/test_*_router.py` for the proven pattern.

---

## TL;DR — lane state

- **DONE (mine, 19 units @ genuine 100%, banked-pending Clayton):**
  - **C1 leaves (3):** user_id_generator, queue_auth, auth_models.
  - **C2 services (9):** password_service, jwt_service, email_service, email_token_service,
    auth_audit, auth_middleware, refresh_token_service, user_service, admin_service.
  - **C3 repos (7):** api_key, auth_audit_log, email_verification_token, failed_login_attempt,
    password_reset_token, refresh_token, user_repository.
  - **1 pragma total** (manager-applied): `user_id_generator.py:99` dead `return system_id`
    (str.split always yields ≥1 elem). Zero prod bugs found, zero API spend.
- **YOUR LANE — CLUSTER 4 (the last 3 units, ~2826L of FastAPI endpoints):**
  1. `src/cosa/rest/auth.py` (629L) — token-verify orchestrator. **START HERE (simplest).**
  2. `src/cosa/rest/routers/auth.py` (898L) — 10 endpoints + 2 helpers.
  3. `src/cosa/rest/routers/admin.py` (1299L) — 14 endpoints, all `Depends(require_admin)`.
  Tests live at `src/cosa/tests/unit/rest/`. You do NOT commit (manager does, on Clayton's APPROVE).

## Canonical interpreter (NON-NEGOTIABLE)
```
PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python -m pytest \
  src/cosa/tests/unit/rest/<test> --cov=cosa.rest.<mod> --cov-branch --cov-report=term-missing -p no:cacheprovider -q
```
cosa venv (py3.11/pytest9). NOT SDK-adjacent → plain pytest-cov (no run-sdk-cov.sh).

## Boundary ownership — MOCK-ONLY, author NO tests for these
- `cosa.rest.db.*` (database, sqlite_database), `cosa.rest.postgres_models`, and
  `cosa.rest.db.repositories.base` (BaseRepository) = **TIFFANY's** (her B5 db-leaves).
- Your router tests will MOCK the C2 **service** functions (create_user, authenticate_user,
  validate_refresh_token, admin_* etc.) — those are already 100% (mine). Don't re-test them;
  patch them at the ROUTER's namespace (`cosa.rest.routers.auth.<fn>` / `...admin.<fn>`).

---

## Module scope (what each does + the seams)

### auth.py (629L) — START HERE
- `verify_token(token)` async — dispatches by config (`auth mode` JWT/mock/firebase) to
  `verify_jwt_token` / `verify_mock_token` / `verify_firebase_token`. Branchy: cover each mode.
- `verify_jwt_token` → calls `decode_and_validate_token` (jwt_service, mine) → builds user dict.
- `verify_mock_token` → parses `mock_token_email_{email}` form (LEGACY but still code-present).
- `verify_firebase_token` → firebase path; `init_firebase()` + module-level `FIREBASE_INITIALIZED`
  (import-time/lazy state — use the `importlib.reload`-under-patched-state pattern if needed, OR
  patch the firebase admin SDK seam). Firebase likely raises/uninitialized in test → cover the error arm.
- `get_current_user` / `get_current_user_id` / `get_optional_user` — async deps wrapping verify_token.
- Seams to mock: `decode_and_validate_token`, `config_mgr.get` (auth mode), the firebase admin module.
- `quick_smoke_test` + `if __name__` = coverage-EXCLUDED (exclude_also). Don't test them.

### routers/auth.py (898L)
- Endpoints (all async): register, login, refresh, logout, get_current_user, change_password,
  request_verification, verify_email, request_password_reset, reset_password.
- Helpers: `_create_token_response(user_id,email,roles)`, `_user_dict_to_response(user_dict)`.
- Each endpoint calls C2 services (create_user, authenticate_user, create_access/refresh_token,
  store/validate/rotate refresh, send_*_email, log_auth_event, etc.) → MOCK those + assert wiring +
  cover the success + each HTTPException(4xx) arm. `login` takes `request: Request` (mock `.client.host`).

### routers/admin.py (1299L) — heaviest
- 14 endpoints, EVERY ONE gated `admin_user: Dict = Depends(require_admin)` (from auth_middleware, mine).
- They call admin_service.* (list_users, get_user_details, update_user_roles, toggle_user_status,
  admin_reset_password, admin_create_user, admin_delete_user) — MOCK at `cosa.rest.routers.admin.<fn>`.
- One endpoint also `Depends(get_snapshot_manager)`.

---

## ⚠️ GOTCHAS — these WILL bite (full detail in Tiffany's 11-handoff §Gotcha 1 & 2)

1. **`_patch_fastapi_main` dual-key** — `import fastapi_app.main as m` binds via `getattr`, so
   `patch.dict(sys.modules, {'fastapi_app.main': Mock()})` is SILENTLY IGNORED once the real pkg is
   cached → passes solo, FAILS under full-suite order. Fix: patch BOTH keys (`fastapi_app` pkg +
   `fastapi_app.main`). Copy `_patch_fastapi_main` from `test_system_router.py`. (Check whether the
   auth routers import fastapi_app.main; if they don't, you dodge this — but verify.)

2. **FieldInfo 403-trap (THE BIG ONE for these routers)** — when you unit-test an endpoint by
   **calling it directly** (not via TestClient), any param defaulting to `Header(None)` / `Depends(...)`
   / `Query(...)` arrives as the **FieldInfo object**, which is TRUTHY. For the auth routers that means:
   - `authorization: Optional[str] = Header(None)` (get_current_user, change_password) → FieldInfo,
     not None → wrong branch.
   - `admin_user: Dict = Depends(require_admin)` (all 14 admin endpoints) → FieldInfo unless you pass it.
   **Fix: pass EVERY Header/Depends param EXPLICITLY** in the direct call. Build a
   `_call_<endpoint>(self, **overrides)` helper supplying a complete safe kwarg set (model after
   `_call_notify_user` in test_notifications_router.py).

   **Two viable test strategies — pick per endpoint:**
   - **(A) Direct-call + explicit kwargs** (what Tiffany's lane used; fastest for branch coverage).
     Pass `authorization="Bearer x"` / `admin_user={"uid":...,"roles":["admin"]}` explicitly; mock the
     service fns; assert HTTPException arms via `assertRaises`.
   - **(B) TestClient + `app.dependency_overrides`** (cleaner for the Depends(require_admin) gate;
     override `require_admin`/`get_current_user_dependency` to return a fake admin). Heavier setup.
     Recommend (A) for coverage speed, (B) only if a dep is hard to satisfy by direct call.

---

## Reusable patterns I PROVED in C1–C3 (steal these)
- **Chainable SQLAlchemy session mock** (if any router touches a session directly — most don't, they
  call services): `q = session.query.return_value; q.filter.return_value = q; q.order_by.return_value = q`
  (also limit/offset); terminals `q.first/all/count/delete/update/scalar.return_value`.
- **Inherited base method**: `patch.object(repo, "create"/"update"/"get_by_id", ...)` — never test base.py.
- **async endpoints**: `unittest.IsolatedAsyncioTestCase` + `AsyncMock` for awaited seams
  (`patch('cosa.rest.routers.auth.verify_token', new=AsyncMock(return_value=...))`).
- **module-level config/state branches** (firebase init, auth-mode): cover the alternate import-time
  arm via `importlib.reload` under `patch.dict(os.environ, ...)` with a `tearDown` reload-restore
  (see my test_jwt_service.py `TestModuleLevelSecretKeyConfig`).
- **`__main__` CLI** (if any): `runpy.run_path(mod.__file__, run_name="__main__")` + boundary mocks
  (see my test_quantizer / test_hf_downloader from the training lane) — but auth routers have no __main__.
- **config_mgr**: dict-backed side_effect honoring `(key, default, return_type)` (see my `_cfg` in
  test_email_service.py).
- **DbC docstrings** on every test class/method (campaign convention).

## Discipline (charter)
Genuine 100% L/B/F per module; verbatim disk cov in every report. Boundary-mock ALL IO
(DB/JWT/crypto/email/firebase/network) → ZERO real DB/network, ZERO API spend, NEVER read
ANTHROPIC_API_KEY_FIREWALLED. Pragma PROPOSE-only (manager applies). Tripwire any real prod bug
(xfail-strict + pin, NEVER pragma a bug-blocked line) + flag Tiberius. Cluster-paced reporting to
dm-tiberius (he polls; ping explicitly only for bug/ruling/cluster-complete). You do NOT commit.

## Resume checklist
1. cosa venv; `git status src/cosa/tests/unit/rest/` → my 19 auth test files exist; DON'T touch them.
2. Start `auth.py` (simplest, no FieldInfo trap) → then routers/auth → then routers/admin (heaviest).
3. Copy `_patch_fastapi_main` if the routers import fastapi_app.main; pass ALL Header/Depends params explicitly.
4. Per module: read live source → boundary-mock seams → 100% → verbatim disk cov → report to Tiberius.
5. Clayton audits → Tiberius commits on APPROVE. Pragma-propose only; tripwire+flag real bugs.
