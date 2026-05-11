# [LUPIN-MCP] "Neither" affordance on cosa-voice `ask_yes_no()` — Design

| Field | Value |
|---|---|
| **Status** | ⏳ Phase 0 in progress (this doc) |
| **Session** | 6d544991 (Arnold 🪨, 2026-05-11) |
| **Plan source** | `~/.claude/plans/swirling-watching-hinton.md` (approved 2026-05-11 via ExitPlanMode) |
| **Initiative origin** | TODO.md → "MCP SELF-INTROSPECTION FOLLOW-UPS" → "Add a 'neither' / 'discuss-further' option to cosa-voice `ask_yes_no()`" (filed 2026-05-07 by session 6825e6af during plan-review pipeline) |
| **Cross-sub-projects touched** | LUPIN parent + CoSA submodule (one file: `notification_utils.py`) |

---

## 1. Context

When Claude uses `ask_yes_no()` to gate a plan-review decision, the user has only two answer paths: yes or no (optionally annotated with `[comment: ...]`). Several recent sessions surfaced cases where the question as framed CAN'T be answered with yes/no and what the user actually wants is to SIGNAL THAT — "this question needs re-framing; let's discuss before I decide." Today the only escape hatch is a comment-text on the chosen answer, which forces the user to pick a side they don't want to pick and rely on Claude reading the comment correctly.

**Goal**: a third button alongside Yes/No labelled **Neither**. Return value `"neither"` (or `"neither [comment: ...]"`) — distinct from the existing yes/no strings so Claude can branch on it without parsing comment text.

---

## 2. Q-decisions ratified (FROZEN)

Locked via cosa-voice batch `ask_multiple_choice` 2026-05-11 + reasoned defaults for the rest.

| # | Decision | Value | Source |
|---|----------|-------|--------|
| Q1 | Button label | **Neither** | User-ratified |
| Q2 | Keyboard shortcut | **None** (mouse/touch only) | User-ratified |
| Q3 | Return value string | `"neither"` (lowercase, matches `"yes"`/`"no"` shape) | Reasoned default |
| Q4 | Schema approach | **Extend YES_NO response_value vocabulary** — no new ResponseType, no router validation list change, no CLI model enum change (minimum blast radius) | Reasoned default |
| Q5 | Default-on-timeout | **Unchanged** — `default` param stays `"yes"` or `"no"`, never `"neither"` (preserves existing API contract) | Reasoned default |
| Q6 | Comment qualifier | Works for all three buttons via existing `[comment: ...]` machinery | Reasoned default |
| Q7 | Visual treatment | Neutral color (not yes-green, not no-red — e.g. muted gray/blue) | Reasoned default |

---

## 2a. Comment parsing for "neither" — explicit guarantee

The whole point of the Neither button is to let the user signal **how the question should be re-framed**. The comment field is therefore **load-bearing** when the user picks Neither, not optional.

**Wired end-to-end**:

1. **Frontend** (`notifications.js:13800-13808`) — the existing `.yes-no-comment-container` widget is rendered for ALL three buttons (Yes / No / Neither) without conditional gating. The user can attach a comment to Neither identically to how they attach one to Yes or No.
2. **Submit path** (`notifications.js:16313-16322` `submitYesNoWithComment`) — already generic; it composes `"${response} [comment: ${comment}]"` for any non-empty comment, regardless of which button was clicked. `"neither [comment: re-frame please"]` is the wire format.
3. **Backend parser** (`notification_utils.py:215` `extract_qualifier_comment`, Phase 1) — regex extended to `^(yes|no|neither)\s*(?:\[comment:\s*(.+)\])?$`. Capture group 2 (the qualifier) is identical for all three answers.
4. **Format helper** (`notification_utils.py:244` `format_qualified_response`, Phase 1) — has a **`if answer == "neither":` branch** with re-framed copy:
   > IMPORTANT — The user signaled the question itself needs re-framing and attached a comment: "{qualifier}". You MUST treat this as a direct instruction to re-frame the question, not as a soft yes or no. Read the comment, then ask a clearer follow-up that addresses what they actually want to decide.

   This explicit Claude-directive ensures the comment is not just parsed but **acted on as a re-framing instruction**, not as a soft-no commentary.
5. **MCP return value** — `ask_yes_no()` returns `"neither [comment: ...]"` verbatim through the MCP boundary; the receiving Claude session sees the qualified string and can branch on `"neither"` literally OR feed it through `extract_qualifier_comment` + `format_qualified_response` to get the re-framing directive.

**Net effect**: a `Neither` click with a comment like "Did you mean Cosa or Mr. Radio?" yields a return value that explicitly directs Claude to ask a re-framed follow-up question rather than treat ambiguity as a partial yes.

---

## 3. REUSE pre-pass

Helpers + machinery reused as-is. No new utilities introduced.

| Component | Path | Status | Note |
|-----------|------|--------|------|
| Regex parser | `src/cosa/utils/notification_utils.py:215` `extract_qualifier_comment` | **Extend** | Single-character regex change: `(yes\|no)` → `(yes\|no\|neither)` |
| Format helper | `src/cosa/utils/notification_utils.py:244` `format_qualified_response` | **Reuse as-is** | Already answer-agnostic (string-interpolates `{answer}`); "neither" wording validated during AC review (R1) |
| MCP tool | `src/lupin_mcp/cosa_voice_mcp.py:887` `ask_yes_no` | **Docstring only** | Logic pass-through unchanged; helpers handle "neither" automatically |
| HTML render | `src/fastapi_app/static/js/notifications.js:13782-13808` | **Extend** | Add 3rd `<button>` element |
| Click handler | `src/fastapi_app/static/js/notifications.js:13910-13916` | **Reuse as-is** | `dataset.response` already generic |
| Submit handler | `src/fastapi_app/static/js/notifications.js:16313-16322` `submitYesNoWithComment` | **Reuse as-is** | Response string flows through unchanged |
| Comment qualifier widget | `src/fastapi_app/static/js/notifications.js:13797-13808` | **Reuse as-is** | Works for all three buttons |
| Unit test class | `src/tests/unit/test_stop_hook.py:34` `TestExtractQualifierComment` | **Extend** | Add 4 "neither" cases |

---

## 3a. Pass 1 Fitness / Viability

Self-review against fitness criteria (the eight deficiency types from `workflow/plan-review.md` Pass 1). Findings ratified inline; no findings are deferred.

| # | Fitness check | Verdict | Note |
|---|---------------|---------|------|
| F-A | **Phases sized appropriately** — no phase >2hr or <5min | ✅ Pass | All 7 phases bounded. Phase 0 (docs) heaviest at ~30min; Phase 3 (frontend) ~15min; the rest <10min. |
| F-B | **Each phase has explicit DoD + verification** | ✅ Pass | Each phase row in §4 names its verification command. ACs §5 enumerate 10 falsifiable checks. |
| F-C | **EXECUTOR tags present** — every phase marked AI or HUMAN | ✅ Pass | All 7 phases tagged. Phase 7 (MCP restart) is EXECUTOR: HUMAN with explicit fresh-CC-session requirement. |
| F-D | **Cross-cutting concerns surfaced** — config, permissions, schema, observability | ✅ Pass | Q4 explicitly resolves the schema concern (NO new ResponseType). No permissions / observability impact (read-only UX widget). |
| F-E | **Test scope enumerated per layer** | ✅ Pass | Phase 4 has an explicit "Automated testing layers" sub-table marking each layer in-scope/OOS with reason. |
| F-F | **Risk register has mitigation per row** | ✅ Pass | §6 — 4 risks, each with a mitigation column. R1 ratified-as-applied (neither-branch landed in Phase 1, not deferred). |
| F-G | **Out-of-scope is exhaustive** — surfaces a reader might assume are in-scope | ✅ Pass | §7 calls out ResponseType enum, router validation, CLI model enum, keyboard shortcut, mobile sub-project, multiplexer coverage mandate. |
| F-H | **Cross-sub-project surface treated correctly** | ✅ Pass | CoSA file edited but NOT committed from parent; Phase 6.4 explicit; [02-handoff-summary.md](02-handoff-summary.md) seeds the CoSA-context-session TODO. |

**Pass 1 finding count**: 0 Block / 0 Major / 0 Minor — design is internally consistent.

**Pass 1 amendments applied during this self-review** (R1 escalation): `format_qualified_response` "neither" branch with re-framed copy was promoted from "deferred to AC review" to "implemented in Phase 1" — see §2a. Original plan deferred this; user feedback ("the comment should be parsed because it gives the AI a hint as to how they want the question re-framed") confirmed the comment-parsing-for-Neither is load-bearing, not optional. The branch now lives in `notification_utils.py:format_qualified_response`.

---

## 3b. Pass 2 Adversarial

Self-adversarial review against the four standard clusters (security, DOS, race, contract-drift) + a fifth cluster specific to UI/UX (user-confusion).

| # | Cluster | Concern | Verdict |
|---|---------|---------|---------|
| A1 | **Security** — can the `"neither"` string be used to bypass yes/no logic in any downstream consumer? | Downstream callers either (a) compare against literal `"yes"`/`"no"` and treat anything else as a soft-no/error (safe), or (b) feed through `extract_qualifier_comment` + `format_qualified_response` and get the explicit "re-frame" directive (safe). No `eval()`, no shell, no SQL — the string is data, not code. | ✅ No exposure |
| A2 | **Security** — can the comment field carry an injection payload? | The comment is treated as opaque text in `format_qualified_response` (f-string interpolation, no shell, no SQL, no HTML render — the result is read by Claude as a natural-language string). Existing yes/no comment field has the same surface and has been live for months without incident. | ✅ No new surface |
| A3 | **DOS** — does the third button enable any new resource exhaustion path? | No — the button is a static HTML element with a `data-response` attribute; clicking it fires the same `submitResponse` codepath that yes/no already uses. No new request shape, no new server endpoint. | ✅ N/A |
| A4 | **Race** — does adding a third button introduce any state-machine race? | The action-required card already handles concurrent click contention via `isResponded` flag (line 16227); the new button hits the same submit handler and inherits the same guard. | ✅ No new race |
| A5 | **Contract drift** — does the `valid_response_types` allowlist or the CLI `ResponseType` enum need to change? | No — Q4 deliberately keeps `response_type="yes_no"`; only the **response_value vocabulary** widens. The router validator at `notifications.py:389` checks `response_type`, not response value, so it's untouched. | ✅ Q4 prevents drift |
| A6 | **Contract drift** — will the `prediction_log_repository.py:54` docstring (lists answer shapes) become stale? | The repo docstring says "yes_no, multiple_choice, open_ended, open_ended_batch" — these are response TYPES, not response VALUES. No update needed. The prediction-hint UI render in `notifications.js:14086` displays whatever `predicted_value` says; for `"neither"` predictions it would render "Neither (X%)" identical to "Yes (X%)" — no new code path needed. | ✅ No drift |
| A7 | **User confusion** — could three buttons confuse users expecting two? | Possible. Mitigation: title attribute `"Neither — the question itself needs re-framing"` provides hover-tooltip context. Visual color (gray, neutral) signals "not a primary answer". The `default-value` highlighting on Yes or No remains, so the user's primary path stays visually prominent. | ⚠️ Mitigated via tooltip + neutral color |
| A8 | **Backward compat** — does pre-existing `extract_qualifier_comment` consumer still work for old "yes"/"no" inputs? | Yes — regex extension is **additive** (`(yes\|no)` → `(yes\|no\|neither)` adds an alternative, doesn't remove). Unit test sweep (50 tests in `test_stop_hook.py`) confirms 12/12 in `TestExtractQualifierComment` pass including all 8 pre-existing yes/no tests. | ✅ Verified |
| A9 | **Stale-cache risk** — frontend changes don't reach users on cached pages | Browser hard-refresh required for `notifications.js` + `.css` updates. Phase 3 verification step calls this out. No service-worker cache to invalidate; the static assets are served fresh from FastAPI auto-reload. | ⚠️ User browser refresh needed; documented |

**Pass 2 finding count**: 0 Block / 0 Major / 2 Minor (A7, A9 — both already mitigated in-doc).

---

## 4. Phases

### Phase 0 — Documentation serialization (DOC GATE)

Per `feedback_phase0_serialization_prominence` + documentation-first protocol — Phase 0 lands BEFORE any code is written.

Create `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/`:

1. `00-index.md` — master nav, Q1-Q7 FROZEN decisions table, REUSE table, idempotency marker stub, doc-conventions status
2. `01-design.md` — this doc
3. `02-handoff-summary.md` — cross-sub-project handoff for CoSA (one CoSA-touching commit needed)
4. `90-execution-log.md` — phase status table, per-phase scaffolds, REUSE pre-pass closure

**EXECUTOR: AI**

### Phase 1 — CoSA backend (regex + smoke test) — **EXECUTOR: AI**

`src/cosa/utils/notification_utils.py`:

1. `extract_qualifier_comment` regex (line 236): `r'^(yes|no)\s*(?:\[comment:\s*(.+)\])?$'` → `r'^(yes|no|neither)\s*(?:\[comment:\s*(.+)\])?$'`
2. Docstring update — add "neither" to Examples
3. `format_qualified_response` — keep answer-agnostic (R1 escalation deferred)
4. `quick_smoke_test` — extend Test 9 with 3 "neither" parse cases; Test 10 with 1 "neither" format case

**Verification**: `python -m cosa.utils.notification_utils` runs clean.

### Phase 2 — Lupin MCP tool docstring — **EXECUTOR: AI**

`src/lupin_mcp/cosa_voice_mcp.py:887-958`:

1. Docstring — add "neither" / "neither [comment: ...]" to `Ensures` (907-909), `Returns` (919-920), `Examples` (922-924)
2. No logic change

**Verification**: `py_compile` clean.

### Phase 3 — Lupin frontend (notifications.js + .css) — **EXECUTOR: AI**

`src/fastapi_app/static/js/notifications.js:13782-13808`:

1. HTML render — add third button. Order: Yes, No, Neither (after No, visual rhythm preserves yes/no primacy)
2. `default-value` class never applied to Neither (Q5)
3. No event handler change (line 13910)
4. No keyboard listener change (line 16229-16244)

`src/fastapi_app/static/css/notifications.css`:

5. Add `.response-button.neither` neutral-color rule (read existing yes/no rules first; avoid green hues per `feedback_no_green_in_persona_pool`)

**Verification (post-implementation)**: manual browser smoke on `:7999` (open `/app/notifications`, trigger test `ask_yes_no()` from parallel terminal, click Neither, confirm response value reaches Claude).

### Phase 4 — Tests — **EXECUTOR: AI**

`src/tests/unit/test_stop_hook.py:34` `TestExtractQualifierComment`:

1. Add 4 test methods (`test_neither_with_comment`, `test_neither_no_comment`, `test_neither_case_insensitive`, `test_neither_with_whitespace`)
2. **Verify**: `pytest src/tests/unit/test_stop_hook.py::TestExtractQualifierComment -v` — existing tests remain green (additive regex)

**Automated testing layers** (per `feedback_comprehensive_automated_testing`):

| Layer | Status |
|-------|--------|
| py_compile | Phase 1 + Phase 2 verification |
| Unit (CoSA helper) | Phase 4 |
| Smoke (CoSA helper) | Phase 1 (inline `quick_smoke_test`) |
| Smoke (MCP tool) | Out of scope — MCP runs as stdio subprocess; verified end-to-end in fresh CC session post-restart (Phase 7) |
| Frontend unit | OUT OF SCOPE — `notifications.js` is pre-multiplexer legacy; `feedback_100pct_coverage_multiplexer` does NOT apply |
| Integration | N/A — no API endpoint change |
| E2E UI | OUT OF SCOPE — covered by Phase 3 manual browser smoke |

### Phase 5 — Docs — **EXECUTOR: AI**

1. `~/.claude/CLAUDE.md` `INTERACTIVE TOOL ROUTING` section (line 385-395) — add note on 3-way return + when to branch on "neither" (re-frame the question rather than treat as soft-no)
2. `src/docs/notification-api.md` — 3 rows updated (line 895, 1646, 1665)
3. `02-handoff-summary.md` — finalize commit-date + verdicts post-implementation

### Phase 6 — TODO + history + commit — **EXECUTOR: AI**

1. `TODO.md` — mark task ✅ DONE; add ☀️ FIRST THING NEXT SESSION for [LUPIN-COSA] commit; refresh Last-updated
2. `history.md` — new session entry: 6d544991 Arnold
3. `.claude-session.md` — update Status to `committed`, add commit hash
4. **Parent Lupin commit ONLY** — `src/cosa/utils/notification_utils.py` stays in working tree for the CoSA-context session (per `feedback_lupin_only_never_cosa`)

### Phase 7 — MCP server restart guidance (informational) — **EXECUTOR: HUMAN**

MCP server is stdio-loaded; current session (6d544991) will NOT see docstring change. CoSA helper + frontend WILL be live after `:7999` auto-reload (no bounce needed per `feedback_fastapi_auto_reload`) + browser hard-refresh. End-to-end MCP verification requires fresh CC session — HUMAN closes + relaunches CC (or `claude mcp restart cosa-voice` if available).

---

## 5. Acceptance Criteria

| # | Criterion | Verified by |
|---|-----------|-------------|
| AC1 | `extract_qualifier_comment("neither")` returns `("neither", None)` | `test_neither_no_comment` |
| AC2 | `extract_qualifier_comment("neither [comment: x]")` returns `("neither", "x")` | `test_neither_with_comment` |
| AC3 | Case-insensitive: `"NEITHER"` → `("neither", None)` | `test_neither_case_insensitive` |
| AC4 | `notification_utils.py` smoke test passes with new cases | `python -m cosa.utils.notification_utils` |
| AC5 | All existing `test_stop_hook.py` yes/no tests remain green | `pytest src/tests/unit/test_stop_hook.py -v` |
| AC6 | `cosa_voice_mcp.py` py_compiles clean after docstring edit | `python -c "import py_compile; ..."` |
| AC7 | Browser renders 3rd "⊘ Neither" button on action-required cards | Manual browser probe on `:7999` |
| AC8 | Clicking Neither submits response value `"neither"` | Browser DevTools Network tab |
| AC9 | Comment qualifier widget works for Neither too | Manual browser probe |
| AC10 | CLAUDE.md INTERACTIVE TOOL ROUTING references the 3rd return value | `grep` after edit |

---

## 6. Risks

| # | Risk | Mitigation |
|---|------|-----------|
| R1 | ~~`format_qualified_response` wording awkward for "neither" answer~~ — ✅ **RESOLVED in Phase 1** | Promoted from "deferred to AC review" to "implemented Phase 1" per Pass 1 self-review (see §3a). The `if answer == "neither":` branch in `notification_utils.py:format_qualified_response` produces re-framed copy directing Claude to ask a clearer follow-up — load-bearing for the comment-parsing-for-Neither guarantee in §2a. |
| R2 | Frontend CSS color clash with existing yes-green / no-red palette | Read existing `.response-button.yes` / `.response-button.no` rules before picking color. Avoid green hues per `feedback_no_green_in_persona_pool`. |
| R3 | Existing keyboard listener at line 16229 only allows Y/N/C/P/Escape — user might expect a third key | Q2 explicitly chose no-shortcut. If feedback after dogfooding asks for one, add D-for-Discuss in separate follow-up. |
| R4 | MCP server restart caveat — current session won't see docstring change | Phase 7 documents the verification path (fresh CC session). |

---

## 7. Out of scope

- New `ResponseType` enum value (Q4)
- Router validation list change (Q4)
- CLI model enum change (`notification_models.py:ResponseType`) (Q4)
- Keyboard shortcut for Neither (Q2)
- `"neither"`-specific copy in `format_qualified_response` unless R1 escalates
- Mobile sub-project — mobile app doesn't render action-required cards
- Multiplexer 100% coverage mandate — `notifications.js` is pre-multiplexer legacy

---

## 8. Critical files

**Edit:**
- `src/cosa/utils/notification_utils.py` (regex + smoke)
- `src/lupin_mcp/cosa_voice_mcp.py` (docstring)
- `src/fastapi_app/static/js/notifications.js` (HTML render)
- `src/fastapi_app/static/css/notifications.css` (neutral button color)
- `src/tests/unit/test_stop_hook.py` (4 new tests)
- `~/.claude/CLAUDE.md` (INTERACTIVE TOOL ROUTING)
- `src/docs/notification-api.md` (3 rows)
- `TODO.md` + `history.md` + `.claude-session.md` (Phase 6)

**Create:**
- `00-index.md`, `01-design.md` (this), `02-handoff-summary.md`, `90-execution-log.md`
