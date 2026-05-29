# Cross-sub-project handoff — `ask_yes_no` Neither affordance

| Field | Value |
|---|---|
| **Parent commit** | _(pending — session 6d544991 commit hash to be stamped at Phase 6)_ |
| **Date** | 2026-05-11 |
| **Sender session** | 6d544991 Arnold (parent Lupin context) |
| **Affected sub-projects** | CoSA only (`src/cosa/`) |

---

## TL;DR

A new `"neither"` answer path was added to the `extract_qualifier_comment` regex in `src/cosa/utils/notification_utils.py`. The change is **one regex literal + ~6 lines of smoke-test additions**. Parent Lupin commits its own files (frontend + MCP docstring + unit tests + project docs); the **CoSA file edit stays in the working tree** and must be committed in a CoSA-context session.

---

## What changed in CoSA

**File**: `src/cosa/utils/notification_utils.py`

1. `extract_qualifier_comment` regex extended:
   - Before: `r'^(yes|no)\s*(?:\[comment:\s*(.+)\])?$'`
   - After:  `r'^(yes|no|neither)\s*(?:\[comment:\s*(.+)\])?$'`
2. Docstring examples extended to include "neither" cases
3. `quick_smoke_test()` extended with 3 "neither" parse cases + 1 "neither" format case

**File**: `src/cosa/utils/notification_utils.py` (no other CoSA files touched)

**Format helper `format_qualified_response`**: unchanged — it's already answer-agnostic; the `{answer}` interpolation handles "neither" without code change. R1 (wording naturalness for "neither") is monitored during AC review; if it escalates, a 3-line `if answer == "neither":` branch lands in a follow-up.

---

## Why parent Lupin can't commit this

Per `feedback_lupin_only_never_cosa` auto-memory: from a parent Lupin context, Claude must never run `git` inside `src/cosa/`, never investigate submodule state, never ask about cross-submodule commit ordering, never offer to commit CoSA. This is a hard rule. Editing CoSA files from parent context is allowed (per `feedback_cosa_edit_vs_manage_git`), but the commit must happen in a CoSA-context session (where `cwd` is `src/cosa/`).

---

## Action required (CoSA-context session)

When you next open a CoSA-context session (e.g. `cd src/cosa && claude` or equivalent):

1. **Check working tree**: `git status` — expect `notification_utils.py` modified
2. **Verify intent**: `git diff utils/notification_utils.py` — should show the regex extension + smoke-test additions only
3. **Commit**: e.g. `git commit -am "Extend ask_yes_no qualifier regex to accept 'neither' answer"` (or per CoSA's commit-message conventions)
4. **Optional submodule pointer bump**: from parent Lupin, `git -C src/cosa rev-parse HEAD` then `git add src/cosa && git commit` if you want to track the CoSA commit in parent history. This step is OPTIONAL and not blocking.

---

## What this does NOT need

- ❌ No `ResponseType` enum change in `src/cosa/...` (Q4 — kept YES_NO unchanged)
- ❌ No router validation list change in `src/cosa/rest/routers/notifications.py` (Q4)
- ❌ No new endpoint or schema migration

---

## Migration timeline

- **2026-05-11 (this session)**: parent Lupin commit lands with the working-tree CoSA edit visible-but-unstaged
- **Next CoSA-context session**: commits the CoSA edit
- **Indefinite**: no expiry — the parent Lupin frontend gracefully sends `"neither"` strings; the CoSA helper without the regex extension would return `("neither", None)` via the **fallback branch** (line 240-241 of `notification_utils.py`: "Fallback: treat the whole string as the answer"), so functionality is preserved even before the CoSA commit lands — just less explicit in the parser.

The fallback branch behavior is a SOFT migration cushion, not a hard guarantee — get the CoSA commit landed in the next CoSA-context session.

---

## Where to ask

- **Parent Lupin questions**: open a parent-Lupin session, point at this doc
- **CoSA questions**: open a CoSA-context session (`cd src/cosa`), point at this doc
- **Design rationale**: [01-design.md](01-design.md) §1-§3
- **Phase status**: [90-execution-log.md](90-execution-log.md)
