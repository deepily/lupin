# Writer-side `owner_user_id` stamper — design + decision matrix + §6 investigation plan

| Field | Value |
|---|---|
| **Date** | 2026-05-17 |
| **Author** | Arnold 🪨 (session `9ba9a34a`) |
| **Status** | 🟢 **GREEN LIGHT** — all 3 Qs ratified per my recommendations 2026-05-17 PM (see "Ratification Update" below). Implementation still gated on Rick's explicit go-ahead for code. |
| **Surfaced by** | Tiberius 🌑 dispatch under `@all` broadcast `21bb12cd` (Rick out running errands) |
| **Severity** | 🟠 Production-blocking tightening — CoSA-side filter already shipped 2026-05-14 with graceful degradation; writer-side restores strict cross-user isolation |
| **Scope** | Lupin parent only (`src/lupin_cli/claude_code/hooks/`). CoSA-side already shipped, no coordination required per "Independence note" in TODO L202 |
| **Branch** | `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe` |
| **Primary precedent doc** | [`2026.05.14-broadcast-listener-stamps-wrong-user-id.md`](../2026.05.14-broadcast-listener-stamps-wrong-user-id.md) (Option C ratified by Rick) |
| **TODO entry** | L190–L202 ("Writer-side follow-up: `owner_user_id` stamper") |
| **Ratification doc** | [`2026.05.17-coordinator-walkthrough-ratifications.md`](../2026.05.17-coordinator-walkthrough-ratifications.md) (Tiberius, all 13 Qs across the three plans) |

---

## Ratification Update — 2026-05-17 PM

All three open questions ratified by Rick during Tiberius's coordinator walkthrough, **all per my recommendations**:

| Q | My rec | Ratified | Source |
|---|---|---|---|
| Q1 (D1 — credentials mechanism) | Option 2 (`~/.lupin/config[owner]` INI section) | ✅ Option 2 | Walkthrough row 2 |
| Q2 (§6 fix shape) | Fix B (structural read-modify-write) | ✅ Fix B | Walkthrough row 1 |
| Q3 (PR shape) | Bundle Phases 2-5 in one PR | ✅ Bundled | Walkthrough row 3 |

### Two cross-cutting scope additions from Rick (apply to my plan)

**A. Unicode-all-the-way-down (Q8 architectural directive)** — Rick verbatim: *"if we were to use Unicode all the way down to the configuration manager INI file life would be so much simpler. The key values could be the same as the persona's actual name as it is spelled properly, like María, for example."*

How this applies to my plan:
- The new `~/.lupin/config[owner]` section is **role-keyed**, not persona-keyed (keys are `email` + `password`, not a persona name). The directive has no concrete effect on the section keys themselves.
- If a future enhancement adds per-persona owner overrides (e.g., `[owner.maría]`), they MUST use exact unicode spelling per this directive.
- New memory written this session: `feedback_unicode_persona_keys_all_the_way_down.md` so future sessions inherit the convention.

**B. 100% coverage binding (Q9 clarification)** — Rick verbatim: *"I already demand 100% coverage. There is no PR that's going to happen if I have outstanding tests that are failing."*

How this applies to my plan:
- The test pyramid already targets 100% lines/branches/functions per the Lupin-wide mandate.
- Binding now extends to **all touched files** in my scope, not just net-new code. Touched files:
  - `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` — new `set_owner_user_id`; existing functions must remain 100% covered
  - `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — new `_stamp_owner_user_id_on_bridge`; existing functions must remain 100% covered
  - `src/lupin_cli/claude_code/hooks/register_session.py` — modified bridge-write at L811-L812 (Fix B); existing carry-forward logic must remain 100% covered
  - `src/lupin_cli/claude_code/hooks/lib/hook_credentials.py` — new `get_owner_credentials`; existing `get_hook_credentials` must remain 100% covered
- Any pre-existing failing test in these four files surfaces during the PR-prep phase and gets fixed in the same PR. Aligns with `feedback_fix_all_failing_tests`.

### Implementation sequence (unchanged, just confirmed)

Phases 2-5 bundled per Q3:
1. `register_session.py` Fix B (carry-forward)
2. `session_bridge.py` `set_owner_user_id`
3. `hook_credentials.py` `get_owner_credentials`
4. `cc_notification_listener.py` `_stamp_owner_user_id_on_bridge` + integration in `run()`
5. `:8000` integration test scheduling (slot-ask after Phases 1-4 land)

### Gate

🟡 **No code touched yet.** Awaiting Rick's explicit "go" per the @all broadcast `21bb12cd` directive ("give you a go or to further review before you can implement").

---

## TL;DR

The 2026-05-14 design ratified Option C (introduce `bridge.owner_user_id` alongside `bridge.user_id`, switch filter to the new field). The CoSA-side filter migration shipped 2026-05-14 with graceful-degradation fallback — all four personas immediately visible. This document plans the **writer-side** follow-up: a `set_owner_user_id` bridge mutator, a `_stamp_owner_user_id_on_bridge` listener-startup stamp, an owner-credentials resolution mechanism, and an investigation of the §6 secondary mystery (Rachel's bridge missing `user_id` despite log-confirmed stamp).

Investigation while gathering context exposed a structural bug in `register_session.py` (the SessionStart hook) that explains §6: the bridge write at L811–L812 is a fresh-write, not read-modify-write, and the carry-forward list (L744–L808) covers only `voice_persona` and `idle_detection.backoff_index`. **Every `/clear` event wipes `user_id` — and would wipe `owner_user_id` on day one of the writer-side rollout** unless this is fixed in the same change set.

**No code changes proposed. Plan-only deliverable.**

---

## Scope reminder (what is and isn't in this doc)

| In scope | Out of scope |
|---|---|
| Owner-resolution mechanism choice + 3-option matrix | CoSA-side filter (shipped) |
| `set_owner_user_id` in `session_bridge.py` | Phase 0 R&D on the `owner_user_id` concept (concluded in 2026.05.14 doc) |
| `_stamp_owner_user_id_on_bridge` in `cc_notification_listener.py` | Multi-human-user deployment scaffolding (deferred per 2026.05.14 §Recommendation) |
| `register_session.py` carry-forward fix (the §6 root cause) | Allow-list filter strategy (Option B from 2026.05.14 — rejected) |
| Test pyramid: unit + smoke + integration | Re-litigating Option C (ratified) |

---

## D1 — Owner-resolution mechanism (decision matrix)

Tiberius's dispatch recommended env vars (`LUPIN_OWNER_EMAIL` + `LUPIN_OWNER_PASSWORD`). Context-gathering surfaced a competing option that fits the established pattern more cleanly. Per `feedback_always_include_pros_cons_recommendation`, all three options carry pros / cons / flip-condition + my-recommendation block.

### Option 1 — Env vars `LUPIN_OWNER_EMAIL` + `LUPIN_OWNER_PASSWORD`

| | |
|---|---|
| **Pattern** | Listener reads `os.environ.get("LUPIN_OWNER_EMAIL")` + `LUPIN_OWNER_PASSWORD` at startup; POSTs to `/auth/login`; stamps result via `set_owner_user_id`. |
| **Read site** | `cc_notification_listener._stamp_owner_user_id_on_bridge` |
| **Set site** | User's `~/.bashrc` (or `direnv`, or `claude` wrapper script). MUST be exported BEFORE `claude` launches so the env propagates Claude → bash hook → python listener. |
| **Pros** | (a) Zero new file format. (b) Trivial to override per-shell for testing. (c) Mirrors existing `--email` / `--password` CLI override path. |
| **Cons** | (a) Footgun: if Ricardo `unset`s the env or starts `claude` from a shell that didn't source `~/.bashrc`, the stamp silently fails and isolation degrades back to graceful-degradation mode. (b) Two places to keep in sync if the owner password rotates (env + the password manager Ricardo actually uses). (c) Violates `feedback_env_var_read_and_set_land_together` posture — set-site is the user's shell config (out of repo tree), read-site is buried in `cc_notification_listener.py`. (d) NEW env-var names — risk of typo / collision (e.g., `LUPIN_USER_EMAIL` vs `LUPIN_OWNER_EMAIL`). |
| **Flip-condition (becomes correct when…)** | Ricardo decides he wants per-`claude`-invocation control over which "owner" identity gets stamped (e.g., to test multi-user isolation by alternating env values across two terminals). Env vars give that knob; config files don't. |

### Option 2 — `~/.lupin/config` `[owner]` section (extends existing INI)

| | |
|---|---|
| **Pattern** | New `[owner]` section in the unified `~/.lupin/config` already used by `hook_credentials.get_hook_credentials()`. Listener calls a new sibling `get_owner_credentials()` that reads `~/.lupin/config[owner]` → `(email, password)`. |
| **Read site** | `hook_credentials.get_owner_credentials()` (new function) → consumed by `cc_notification_listener._stamp_owner_user_id_on_bridge` |
| **Set site** | `~/.lupin/config` (file already exists, already perms-restricted, already loaded once at listener startup) |
| **Pros** | (a) Extends an ESTABLISHED pattern — `hook_credentials.py` already reads this file. (b) Single source of truth — owner creds live next to service creds, both rotate together. (c) Persistent across shells / IDEs / direnv — no "did I source `~/.bashrc`?" failure mode. (d) Honors `feedback_env_var_read_and_set_land_together` — set-site and read-site are both inside `lupin_cli/.../hook_credentials.py`. (e) `lupin-config init` (referenced in `hook_credentials.py:78`) can prompt for owner creds on first run. |
| **Cons** | (a) NEW INI section requires user action (manual edit OR running `lupin-config init`). (b) Slightly more code than env vars (one new function + one new INI section). (c) `~/.lupin/config` is single-user-per-host — multi-tenant hosts would need a different mechanism (but Lupin isn't multi-tenant today). |
| **Flip-condition (becomes correct when…)** | Stays correct under the current single-human-owner-per-host deployment. Flips wrong if Lupin grows multi-tenant on a shared host (each Linux user would need their own `~/.lupin/config`, which they have anyway — so still arguably correct). |

### Option 3 — `/auth/whoami-for-bridge` endpoint

| | |
|---|---|
| **Pattern** | Browser posts the owner's JWT identity to a new endpoint that writes the owner UUID to a per-bridge-PID file the listener can read. Listener reads file at startup. |
| **Read site** | New file under `~/.claude/sessions/cc-owner-{PPID}.id` (or similar) |
| **Set site** | New endpoint `/auth/whoami-for-bridge` POSTed by browser on login |
| **Pros** | (a) Browser is the only place that knows for sure who the human is — semantically cleanest. (b) Forward-compatible with multi-human-user deployments. (c) Stamp can be re-triggered if owner identity changes mid-session. |
| **Cons** | (a) MASSIVE blast radius for what is currently a single-user dev problem. (b) New endpoint + new browser-side logic + new file format + new race between browser-post and listener-read. (c) Defers the stamp to "browser must have logged in first" — but the listener runs at `claude` launch, BEFORE the browser is up. Need a polling-and-retry layer. (d) The 2026.05.14 doc explicitly evaluated this and ruled it heavier than warranted. |
| **Flip-condition (becomes correct when…)** | Lupin adds true multi-human-user-per-host with per-session ownership transfer mid-session. Until then, this is overkill. |

### My recommendation

**Option 2** (`~/.lupin/config` `[owner]` section), not Option 1 (env vars).

**Why I diverge from Tiberius's recommendation**: Tiberius's framing of "mirrors existing listener-creds pattern" is true in spirit but inverted in implementation — the *actual* existing pattern (`hook_credentials.py:50–91`) is **INI-file driven**, NOT env-var-driven. The `--email` / `--password` CLI args are listener-CLI overrides for that INI pattern, not the primary path. Tiberius may have been pattern-matching on the CLI override surface and missed the INI read site.

Option 2 wins on these axes:

1. **Set-site/read-site colocation** — `feedback_env_var_read_and_set_land_together` explicitly warns about the listener Phase 0 DM bug (commit `9bbf298`) that silently failed for 24+ hours because a new `os.environ.get(...)` read site landed without a matching set site. Option 1 reproduces exactly that footgun.
2. **Failure mode under accidental misconfig** — Option 1 fails silently (env unset → silent stamp skip → graceful-degradation persists). Option 2 surfaces a `ValueError` at startup if `[owner]` is missing, just like the existing service-creds path.
3. **Operational consistency** — when the owner password rotates, the user already edits `~/.lupin/config` to update service creds; doing the same for owner creds is one edit, not two.

**Becomes wrong if** Rick says "I want to flip owner identity per `claude` invocation for testing" — then env vars are correct. But the test posture for the `owner_user_id` stamp can be served by unit tests with mock credentials, not by ad-hoc shell juggling.

**Asking Rick to flip the call**: this is a substantive design divergence from Tiberius's recommendation. Rick should ratify whether Option 1 or Option 2 is correct before I write any code. Default if no answer: I'll implement Option 2 per my analysis, but flag the choice in the implementation PR description so it's catchable on review.

---

## D2 — `set_owner_user_id` in `session_bridge.py` (PLAN)

Mirror `set_user_id` (lines 921–970). Signature, semantics, location identical except for the field name.

### Proposed signature

```
def set_owner_user_id( session_id, owner_user_id ):
    """
    Write `owner_user_id` to the bridge file for a given session_id.

    Writer-side follow-up to the 2026-05-14 design (Option C). The
    inter-session-commons broadcast surface filters active sessions by
    `bridge["owner_user_id"] == authenticated_user_id` after CoSA-side
    migration shipped 2026-05-14. This setter is called once at listener
    startup from `_stamp_owner_user_id_on_bridge()`.

    Mirrors `set_user_id` exactly except for field name.

    Requires:
        - session_id is a non-empty string (full UUID or 8-char prefix)
        - owner_user_id is a non-empty string (canonical user UUID from
          `/auth/login` response at `user.id` for the HUMAN owner)

    Ensures:
        - Returns True if bridge was found and successfully updated
        - Returns False if bridge missing, parse-fail, or write-fail
        - Never raises
        - Preserves all other bridge fields (read-modify-write)

    Returns:
        bool: True on successful write
    """
```

### Location in file

Immediately after `set_user_id` (line 970). Keeps the two parallel mutators next to each other for future-reader sanity.

### Unit test cases (Tier 1 — `pytest src/tests/unit/`)

| # | Test name | Scenario | Expected |
|---|---|---|---|
| 1 | `test_set_owner_user_id_writes_field` | Fresh bridge has no `owner_user_id` → call setter → read back | Returns `True`, field present with the supplied value |
| 2 | `test_set_owner_user_id_preserves_other_fields` | Bridge has `voice_persona`, `user_id`, `idle_detection` → call setter → all preserved | All four fields present, only `owner_user_id` mutated |
| 3 | `test_set_owner_user_id_overwrites_existing` | Bridge has stale `owner_user_id` → call setter with new value | New value present |
| 4 | `test_set_owner_user_id_returns_false_when_bridge_missing` | Session id does not match any bridge file | Returns `False`, no exception |
| 5 | `test_set_owner_user_id_returns_false_when_owner_id_empty` | Pass empty string for `owner_user_id` | Returns `False` (mirrors `set_user_id:957–958` empty-guard) |
| 6 | `test_set_owner_user_id_returns_false_when_session_id_empty` | Pass empty string for `session_id` | Returns `False` |
| 7 | `test_set_owner_user_id_with_8char_prefix` | Pass 8-char prefix instead of full UUID | Returns `True` (mirrors `find_session_path_by_id` prefix-match) |
| 8 | `test_set_owner_user_id_distinct_from_user_id` | Bridge has `user_id` = service UUID → set `owner_user_id` = human UUID → read both | Both fields present and distinct (the regression scenario from 2026.05.14 §Diagnosis) |

All 8 use `tempfile.TemporaryDirectory()` + `globals()["SESSION_DIR"] = tmp_dir` pattern from the existing inline smoke (`session_bridge.py:1454–1503`).

**Coverage floor**: 100% lines/branches/functions per the Lupin-wide mandate (`feedback_100pct_coverage_multiplexer` — scope-expanded 2026-05-16). The 8 cases above hit every branch in the proposed `set_owner_user_id` body.

### Inline smoke addendum

Append to existing `if __name__ == "__main__":` block at `session_bridge.py:1454`. Mirror the existing `_persona` round-trip smoke (lines 1483–1501) — set, read, clear semantics. Keeps `python -m lupin_cli.claude_code.hooks.lib.session_bridge` self-validating.

---

## D3 — `_stamp_owner_user_id_on_bridge` in `cc_notification_listener.py` (PLAN)

Mirror `_stamp_user_id_on_bridge` (lines 709–758). The differences:

1. Calls `get_owner_credentials()` (Option 2 — D1) instead of using `self.email` / `self.password`.
2. Stamps via `set_owner_user_id` instead of `set_user_id`.
3. Called from `run()` at line 806 *immediately after* the existing `_stamp_user_id_on_bridge()` call (per Tiberius's dispatch).

### Proposed signature + integration point

```
def _stamp_owner_user_id_on_bridge( self ):
    """
    Writer-side follow-up to 2026-05-14 (Option C). Resolves the HUMAN
    OWNER's user_id via /auth/login using owner credentials, then stamps
    it on the bridge via session_bridge.set_owner_user_id.

    Per `src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md`.

    Best-effort: any failure (creds missing, network, auth, parse, missing
    bridge) is logged and swallowed. CoSA-side graceful-degradation filter
    covers the gap.

    Fires once at `run()` startup, immediately after `_stamp_user_id_on_bridge`.

    Ensures:
        - Never raises publicly. All errors caught + logged.
        - Bridge file is mutated only on full success.
    """
```

### Integration point in `run()`

```
# Around current line 806 in cc_notification_listener.py:
self._stamp_user_id_on_bridge()      # existing — service account
self._stamp_owner_user_id_on_bridge()  # NEW — human owner
```

Sequencing matters: the owner stamp follows the service stamp so both fields end up on the bridge before the listener accepts its first WebSocket event. If the owner stamp fails, the service stamp remains intact (so `user_id` telemetry isn't compromised by an owner-resolution failure).

### Failure-mode handling

Mirror the existing two-tier exception catch (lines 754–758):

| Exception class | Handling |
|---|---|
| `urllib.error.URLError`, `json.JSONDecodeError`, `OSError`, `KeyError`, `ValueError` | Log + silent fallback (CoSA graceful-degradation covers it) |
| `FileNotFoundError` (Option 2: `~/.lupin/config` missing) | Log + silent fallback |
| `ValueError` from `hook_credentials._read_credentials_from_file` (Option 2: section missing) | Log + silent fallback |
| Unexpected `Exception` | Log + silent fallback (defense-in-depth — never kill listener startup) |

### Smoke test (Tier 2 — inline `quick_smoke_test()`)

The existing listener module doesn't have an inline `__main__` smoke (it has `main()` for the CLI). Adding a smoke would require an HTTP-server fixture. Recommend instead:

- **Unit test**: `src/tests/unit/listener/test_cc_notification_listener_owner_stamp.py` (NEW)
  - Patch `urllib.request.urlopen` to return mock `/auth/login` JSON
  - Patch `get_owner_credentials` to return fake `(email, password)`
  - Patch `set_owner_user_id` to record the call
  - Verify: success path, missing-creds path, login-fail path, set_owner_user_id-returns-False path
- **Smoke test**: `src/tests/smoke/test_owner_stamp_smoke.py` (NEW) — calls actual `:7999` `/auth/login` with TEST creds + temp bridge dir; verifies bridge gets stamped.
- **Integration test**: covered in D5 below.

---

## D4 — §6 secondary mystery investigation (Rachel's missing `user_id`)

**Smoking gun found during context-gathering.** No further investigation needed to identify the root cause; only verification + fix.

### Root cause (already identified)

`register_session.py:811–812`:

```
with open( session_file, "w" ) as f:
    json.dump( session_data, f, indent=2 )
```

This is a **fresh-write**, not read-modify-write. `session_data` is rebuilt from the SessionStart payload at lines 744–808. The carry-forward list covers:

- `voice_persona` (lines 768–769, only if `is_context_clear`)
- `idle_detection.backoff_index` (lines 804–807)

**Not in the carry-forward list**: `user_id`, `owner_user_id` (proposed), `last_autonarrated_turn_id`, `session_topic`, `speakerphone_on`, `listener_pid`. Of these, `listener_pid` is re-stamped at Phase 5.5 (line 912) and `voice_persona` is re-allocated at Phase 4.5 (lines 881–898), so they survive. The other four are silently lost on every `/clear`.

### Why Rachel's bridge specifically had no `user_id`

Most likely scenario: a `/clear` fired between her listener's `_stamp_user_id_on_bridge()` call and Rick's observation. The new SessionStart wrote a fresh `session_data` dict without `user_id`. The new listener spawned at Phase 5.5 was supposed to re-stamp via its own `_stamp_user_id_on_bridge()` — but either:

- (a) Listener startup raced the bridge-write (new listener wrote `user_id` BEFORE SessionStart's `json.dump` overwrote it), OR
- (b) Listener stamp failed silently (login timeout, etc.), OR
- (c) Listener PID was inspected between SessionStart-write and listener-stamp-completion

(a) is the most likely race — `_spawn_listener` starts the new listener subprocess (line 912), which races against the `session_file` write a few lines earlier (line 811). The new listener's `_stamp_user_id_on_bridge` may write first, but then SessionStart's fresh-write (line 811) overwrites the listener's stamp.

Wait — re-reading: SessionStart writes the bridge at line 811 BEFORE spawning the listener at line 912. So order is:

```
register_session.py order:
  L811: fresh-write session_data (no user_id)
  L912: spawn listener
        listener._stamp_user_id_on_bridge() → stamps user_id
```

So the listener stamp SHOULD survive. Rachel's missing `user_id` must be a **second-`/clear` race**: clear #1 stamps user_id correctly → clear #2 fires SessionStart again → fresh-write wipes user_id → new listener spawns → its stamp succeeds.

So Rachel's window is the **gap between the SessionStart fresh-write and the new listener's stamp completion**. During that gap (typically 0.3s, per `_spawn_listener` liveness check at line 244), the bridge has no `user_id`. If Rick observed the broadcast UI during exactly that window, he'd see Rachel as the only one stamped (her old listener hadn't been killed yet) — but actually, that's reversed from his observed symptom (Rachel was the ONLY one with NO user_id).

Reframing: Rachel's missing `user_id` may actually be **her old listener never fired its stamp because she's the lone session that started before the Option 2 stamper was deployed**. The other three sessions started after the listener stamp was added, so their new listeners (spawned post-deploy) ran the stamp. Rachel's session predates the deploy → her listener's binary doesn't have the stamp method.

This hypothesis is testable: check Rachel's `cc-listener-{hash}.log` for the timestamp of "user_id stamped on bridge: …" entries. If the log entry exists but no `user_id` in bridge → race. If the log entry is missing → her listener binary is pre-stamp.

### Investigation steps (planning phase only — no execution yet)

1. **Read Rachel's listener log** at `~/.claude/sessions/cc-listener-{08f0e219}.log` (or whatever her current hash is). Look for `[CC-Listener] user_id stamped on bridge: …` lines AND their timestamps.
2. **Read Rachel's centralized log** at `~/.claude/sessions/cc-listeners.log`. Search for `=== SESSION TRANSITION:` lines involving her hashes — counts how many `/clear` events she's had.
3. **Check bridge file mtime vs listener-log stamp-time** — if mtime > stamp-time, bridge was rewritten after stamp → the SessionStart fresh-write bug confirmed.
4. **Reproduce in dev** — open a fresh CC session, observe `user_id` get stamped, fire `/clear`, observe `user_id` disappear from bridge (then re-appear after listener re-stamp). Time the gap.

### Proposed fix (separate from D2/D3 scope, but MUST land in same change set)

`register_session.py` must carry `user_id` (and the about-to-be-introduced `owner_user_id`) forward across `/clear`. Two viable approaches:

#### Fix A — Add to carry-forward list (targeted band-aid)

Add to the `is_context_clear` block at lines 768–807:

```
if is_context_clear and old_data:
    if "user_id" in old_data:
        session_data["user_id"] = old_data["user_id"]
    if "owner_user_id" in old_data:
        session_data["owner_user_id"] = old_data["owner_user_id"]
```

**Pros**: targeted, no behavior change for non-cleared sessions.
**Cons**: every NEW bridge field added in the future needs to be added here too. Maintenance burden + footgun for the next field that gets added (will silently lose it on `/clear` until someone notices).

#### Fix B — Read-modify-write at line 811 (structural fix)

Read existing bridge first, merge `session_data` over it (preserving any fields not in `session_data`'s keys):

```
existing = {}
if os.path.exists(session_file):
    try:
        with open(session_file) as f:
            existing = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
# session_data wins for keys it provides; existing fills in everything else
merged = {**existing, **session_data}
with open(session_file, "w") as f:
    json.dump(merged, f, indent=2)
```

**Pros**: future-proof — any new bridge field automatically survives `/clear`.
**Cons**: could carry forward truly stale fields that we want to drop (e.g., the `conversation_mode_active` v1 field — but that one is handled by `set_speakerphone:842`'s explicit `pop`, so the precedent for "drop legacy keys at the mutation site" is already established).

**My recommendation**: Fix B (structural). Honors `feedback_no_defensive_programming` (fix at source) and the future-proofing pays for itself the first time a new bridge field is added. Mitigates by allowing per-key drops at mutation sites (like the existing `set_speakerphone` precedent).

### Reproducer plan

Write a smoke test `src/tests/smoke/test_session_start_carries_user_id_across_clear.py` that:

1. Creates a temp `SESSION_DIR` with a pre-stamped bridge (`user_id` + `owner_user_id` present).
2. Simulates a `/clear` by calling `register_session.main()` with a payload whose `session_id` differs from the bridge's.
3. Asserts both `user_id` and `owner_user_id` survive on the bridge after the SessionStart write.

Failing test demonstrates the bug; passing test demonstrates Fix B works.

---

## D5 — `:8000` integration test scheduling

### Existing test

`src/tests/smoke/test_broadcast_two_session_e2e.py` already exists. Per CLAUDE.md §TESTING VENUES, this file is in `smoke/` but routes to `:8000` because it mutates state (creates sessions, posts notifications, runs full broadcast cycle). Smoke-folder ≠ :7999.

### Scheduling protocol (per CLAUDE.md §TESTING VENUES + `feedback_test_server_monopolize_mode`)

Submit via `POST /api/test-suite/submit` (not ad-hoc curl, never side-door). Required body fields per `feedback_test_suite_submit_field_pytest_args`:

```
{
  "test_types"            : "smoke",
  "pytest_args"           : "-v -k test_broadcast_two_session",
  "scheduled_at"          : "<user-confirmed slot>",
  "auto_fix_on_failure"   : false
}
```

`auto_fix_on_failure: false` per `feedback_baseline_capture_disable_tfe` — this is a behavior-change regression test, not a baseline capture, but TFE auto-fix on a passing-after-writer-lands transition would just confirm a non-bug. Keep it off.

Use `/schedule-tests` skill per `feedback_use_schedule_tests_skill` — never hand-roll auth + API.

### What the integration verifies

After writer-side lands AND `register_session.py` fix lands:

| Before writer | After writer + Fix B | After writer + Fix B + `/clear` |
|---|---|---|
| 1 of 4 visible (Rachel only) | 4 of 4 visible (graceful-degradation) | 4 of 4 visible (carry-forward) |
| Filter graceful path | Filter strict path | Filter strict path (no clobber) |

Test must include the `/clear` scenario explicitly — the existing `test_broadcast_two_session_e2e.py` may not exercise it. If not, add a sibling test `test_broadcast_survives_clear.py` that fires a SessionStart event mid-suite.

### Slot-ask, not budget-ask

Per `feedback_test_server_monopolize_mode`: the user-ask is "is :8000 free at time T?" — not "do you authorize spend?" Rick has visibility into the schedule that I don't. I'll surface the slot request via `ask_yes_no` once Rick is back and the writer-side code is ready; not now.

---

## Test pyramid summary (per `feedback_comprehensive_automated_testing` + 100% mandate)

| Tier | Venue | Files (NEW unless noted) | Count |
|---|---|---|---|
| `py_compile` | local | `session_bridge.py`, `cc_notification_listener.py`, `register_session.py`, `hook_credentials.py` (if Option 2 chosen) | 4 |
| Unit | :7999 | `src/tests/unit/session_bridge/test_set_owner_user_id.py` | 8 cases |
| Unit | :7999 | `src/tests/unit/listener/test_cc_notification_listener_owner_stamp.py` | 4 cases |
| Unit | :7999 | `src/tests/unit/hook_credentials/test_get_owner_credentials.py` (if Option 2) | 5 cases |
| Unit | :7999 | `src/tests/unit/session_bridge/test_register_session_carries_user_id_across_clear.py` | 3 cases |
| Smoke | :7999 | Inline `__main__` in `session_bridge.py` (extend existing) | 1 round-trip |
| Smoke | :7999 | `src/tests/smoke/test_owner_stamp_smoke.py` | 1 live `/auth/login` round-trip |
| Smoke | :7999 | `src/tests/smoke/test_session_start_carries_user_id_across_clear.py` | 1 reproducer |
| Integration | :8000 | `src/tests/smoke/test_broadcast_two_session_e2e.py` (existing) — re-run | full E2E |

**Coverage**: 100% lines/branches/functions per `feedback_100pct_coverage_multiplexer` Lupin-wide mandate. Every new function gets coverage from at least one unit test; every branch gets exercised; every exception path gets exercised.

---

## Implementation order (when Rick says "go")

Sequencing matters because §6 fix landing AFTER writer-side would expose a 1-`/clear`-wide window where every fresh-stamped bridge gets wiped.

1. **Phase 0 — Documentation prerequisite** (this doc, complete).
2. **Phase 1 — D1 ratification** — Rick picks Option 1 or Option 2 (or pushes back). NO CODE until ratification.
3. **Phase 2 — register_session.py Fix B** (read-modify-write at line 811 + per-key drop precedent). Lands FIRST so writer-side stamps survive `/clear` from day one. Unit + smoke tests for the carry-forward.
4. **Phase 3 — session_bridge.py `set_owner_user_id`** + 8 unit tests + inline smoke addendum.
5. **Phase 4 — hook_credentials.py `get_owner_credentials`** (if Option 2 chosen) + 5 unit tests.
6. **Phase 5 — cc_notification_listener.py `_stamp_owner_user_id_on_bridge`** + 4 unit tests + integration into `run()`.
7. **Phase 6 — `:8000` integration test scheduling** (slot-ask after Phases 2-5 land).
8. **Phase 7 — Documentation cross-links** — update 2026.05.14 doc with "writer-side landed" banner; update TODO.md L196-L200 to mark closed.

Phases 2 and 3-5 could parallelize once D1 ratification lands, but Phase 2 MUST be merge-ready before Phase 5 ships (race window risk).

---

## Open questions for Rick

(Tagged for `ask_multiple_choice` when Rick is back; here as plan-readable summary.)

| # | Question | Default if no answer |
|---|---|---|
| Q1 | **D1 mechanism**: Option 1 (env vars) per Tiberius, OR Option 2 (`~/.lupin/config[owner]`) per my divergent recommendation? | Option 2 (with PR-description flag) |
| Q2 | **§6 fix shape**: Fix A (carry-forward list extension) or Fix B (structural read-modify-write)? | Fix B |
| Q3 | **Implementation merge order**: bundle Phases 2-5 into a single PR, or land Phase 2 first and Phases 3-5 second? | Bundle (single PR; the bug + fix in one diff is easier to review than two coupled PRs) |
| Q4 | **Slot for `:8000` integration run** — once Phases 2-5 are ready, what's a clean window? | Defer to Rick when phases land |

---

## Cross-references

- **Precedent doc** — `src/rnd/v0.1.7/2026.05.14-broadcast-listener-stamps-wrong-user-id.md` (Option C ratified; CoSA-side shipped; §6 hypothesis 1 — confirmed by this investigation)
- **CoSA-side filter** — `src/cosa/rest/routers/commons.py::filter_and_project_sessions` (graceful-degradation branch present at the time of writing; switches to strict isolation automatically once writer lands)
- **CoSA-side regression test** — `src/tests/unit/commons/test_commons_router.py::test_filter_uses_owner_user_id_not_legacy_user_id`
- **Lupin-wide coverage mandate** — `feedback_100pct_coverage_multiplexer` (scope-expanded 2026-05-16)
- **Env-var read/set colocation** — `feedback_env_var_read_and_set_land_together` (the rule Option 1 violates, the basis for my divergent recommendation)
- **Test-server monopolize-mode** — `feedback_test_server_monopolize_mode` + `feedback_use_schedule_tests_skill` + `feedback_test_suite_submit_field_pytest_args`
- **Baseline-capture TFE-disable** — `feedback_baseline_capture_disable_tfe` (relevant for the regression test that crosses a pass/fail boundary mid-rollout)
- **CoSA git boundary** — `feedback_lupin_only_never_cosa` — all work in this design is Lupin-parent only; CoSA-side already shipped, do not touch
- **Cross-target test coverage** — `feedback_tests_must_cover_cross_target_invocations` (not directly applicable here, but kept in mind: the listener stamp could be exercised against a non-default `--host`/`--port` to catch path-resolution drift in test harness)

---

## Status checklist (for execution session)

- [x] D1 ratified by Rick — Option 2 INI file (2026-05-17 PM)
- [x] Q2 ratified by Rick — Fix B structural read-modify-write
- [x] Q3 ratified — bundled Phases 2-5
- [x] `register_session.py` Fix B implemented + 3 carry-forward tests passing
- [x] `set_owner_user_id` implemented + 10 unit tests passing
- [x] `get_owner_credentials` implemented + 5 unit tests passing
- [x] `_stamp_owner_user_id_on_bridge` implemented + 4 unit tests passing
- [x] Inline smoke addenda passing in `session_bridge.py __main__` (Conversation mode + Voice persona + Owner user_id all ✓)
- [x] Reproducer (carry-forward across /clear) covered by `TestCarryForwardReadModifyWrite` × 3
- [x] `py_compile` clean on all four touched files
- [x] Import-chain verified — all new symbols resolve
- [x] Pre-existing inline-smoke failure in `session_bridge.py:1473` fixed (mode-aware default assertion — was hardcoded `False`, broken in chorus mode)
- [x] **Q9 binding satisfied**: 445 tests across 21 files touching the four source files — all passing (0 failing)
- [x] `:8000` integration scheduled + green — `test_commons_traffic_visibility_integration.py`: 5/5 passed, 0 failed, 0 errors, 0 skipped, 12.77s (job `ts-3f8a3e70`). Test container `lupin-rest-test` was bounced via `docker restart` before submission to pick up source changes. Note: `test_broadcast_two_session_e2e.py` was originally cited in the plan as the `:8000` test but is actually `:7999 AI-discretionary` per its own header — ran green standalone on `:7999` in 0.84s. Strict-isolation verification deferred to live broadcast-UI inspection by Rick after listener-restart picks up the new stamping code.
- [ ] 2026.05.14 doc updated with "writer-side landed" banner — awaiting commit ratification
- [ ] TODO.md L196-L200 marked `[x]` with commit refs — awaiting commit ratification
- [ ] history.md entry (per project doc-separation rules) — awaiting commit ratification
- [ ] Rick verifies live broadcast UI shows all 4 personas under strict isolation

---

## Execution log — 2026-05-17 PM

| # | Phase | Result |
|---|---|---|
| 2 | `register_session.py` Fix B (read-modify-write at the bridge write) | ✅ Implemented L808-L831; `py_compile` clean; 3 carry-forward unit tests passing |
| 3 | `session_bridge.set_owner_user_id` + inline smoke addendum | ✅ Implemented; 10 unit tests passing; inline smoke "Owner user_id smoke: ✓ all assertions passed" |
| 4 | `hook_credentials.get_owner_credentials` | ✅ Implemented; 5 unit tests passing |
| 5 | `cc_notification_listener._stamp_owner_user_id_on_bridge` + `run()` integration | ✅ Implemented; called from `run()` immediately after `_stamp_user_id_on_bridge()`; 4 unit tests passing (happy + 3 silent-fallback paths) |
| 6 | `:8000` integration slot-ask | ✅ Rick green-lit slot 2026-05-17 PM; `lupin-rest-test` bounced (healthy in 16s); job `ts-3f8a3e70` submitted via `/api/test-suite/submit` with `auto_fix_on_failure=false`; **5/5 passed in 12.77s**. Report at `test-suite/2026.05.17-at-19:30-EDT-integration-results.md`. |

**Test totals**:
- 22 NEW unit cases written (10 + 3 + 5 + 4)
- 22 NEW + 423 pre-existing = **445 passing in 5.65s** across the 21 test files touching the four source files
- Inline smoke (`python -m lupin_cli.claude_code.hooks.lib.session_bridge`) — 3/3 sections green

**Side-fix landed in the same change set**: `session_bridge.py:1473` had a mode-sensitive smoke assertion hardcoded to `False`. Fixed to use `_get_default_speakerphone()` (the actual mode-aware default helper). Was breaking the inline smoke under chorus mode; Q9 binding required fixing before PR.

End of plan.
