# TODO.md Size Management — Design

**Date**: 2026-05-01
**Author**: Session 92ece47c
**Status**: 🟢 Design approved (verbal go-ahead from user, conversation-mode session)
**Related**: `~/.claude/CLAUDE.md` HISTORY DOCUMENT MANAGEMENT (the model we're mirroring), `~/.claude/CLAUDE.md` TODO.md MANAGEMENT (the gap we're closing), `planning-is-prompting/workflow/todo-management.md` (canonical TODO doc — currently silent on size mgmt)

---

## 1. Problem Statement

`TODO.md` has no size-management protocol. As of session-start today the file sits at **31,518 tokens (126% of the 25k limit)** with **199 pending items**.

The global Claude config has explicit adaptive-archival guidance for `history.md` (17k warning, 19k critical, 8-12k retention target, archives to `history/YYYY-MM-DD-to-DD-history.md`). It has none for `TODO.md`. The PIP canonical workflow doc explicitly says **"TODO.md is NEVER archived"** (line 268) — only soft guidance is *"prune completed items older than 7 days"*.

That guidance has clearly proven insufficient: the in-place prune is easy to skip, and a 199-item TODO file is no longer a working document.

## 2. Goal

Adopt the history.md adaptive-archival pattern for TODO.md, **with one structural adjustment** (see §3) to handle TODO's status-×-age semantics safely.

## 3. The Asymmetry That Matters

`history.md` archival is **mechanical**: cut by date. Every entry is immutable past-tense; the only question is "is this old enough to archive?"

`TODO.md` archival is **semantic**: cut by **status × age**. A 60-day-old `[ ]` pending item is still load-bearing work. A 60-day-old `[x]` completed item is dead weight.

Therefore the algorithm has two phases:

1. **Mechanical**: archive completed `[x]` items + entirely-closed session sections older than the retention window.
2. **Semantic** (optional surface): emit a "stale-pending review" list for any `[ ]` item older than 30 days so the human can decide keep-vs-drop. Never auto-archive pending work.

## 4. Algorithm

### 4.1 Token Thresholds (mirror history.md)

| Severity | Tokens | Notify priority |
|---|---|---|
| 🚨 CRITICAL | ≥19,000 | urgent |
| ⚠️ WARNING | ≥17,000 | high |
| ℹ️ MONITOR | breach forecast <14d | medium |
| ✅ HEALTHY | else | none |

Retention target after archival: **8-12k tokens**.

### 4.2 Section Classification

Walk `TODO.md` from top to bottom. For each `## ` section, classify it as:

| Classification | Definition | Archivable? |
|---|---|---|
| **CLOSED** | All bullets are `[x]` | YES if section date ≥ 14d old |
| **MIXED** | Both `[x]` and `[ ]` | NO — leave in place; only the closed sub-bullets are candidates if cleanly excisable, but conservative default is "leave the whole section" |
| **OPEN** | Has `[ ]` items | NO regardless of age |
| **HEADER/META** | Top metadata block ("Last updated…") | NO |

**Date detection**: Section heading typically embeds `(Session XXX, YYYY-MM-DD)` or includes a date sub-line. If no date can be extracted, treat as **NOT archivable** (conservative fail-safe).

### 4.3 Stale-Pending Surface

Emit a separate report (NOT a file move) listing any `[ ]` item whose containing section is dated >30 days ago. Output shape:

```
🟡 Stale-pending review (12 items, sections >30d old):
  • [LUPIN] Repaint Arnold from dark red → orangey-peach (2026-04-15 section)
  • [LUPIN] Migrate other 7 agent types to ContextVar dispatch (2026-04-22 section)
  ...
Suggest: review each → mark resolved / drop / re-stamp into a current section.
```

The human makes the call; the skill never auto-prunes pending items.

### 4.4 Archive Output

**Directory**: `todo-history/` parallel to `history/` at project root.
**Naming**: `YYYY-MM-DD-to-DD-todo.md` (mirrors history archive convention).
**Multiple archives per period are fine** — high-velocity periods produce more files (per history-management precedent: "no consolidation").

Archive file shape:
```markdown
# TODO Archive: YYYY-MM-DD to YYYY-MM-DD

**Archived from**: TODO.md
**Archive date**: YYYY-MM-DD (Session XXXXXXXX)
**Sections archived**: N closed sections (M bullets total)
**Reason**: Adaptive size-management archival (TODO.md was at XXk tokens)

---

[verbatim copy of archived sections]

---

## Cross-references
- Main TODO: `../TODO.md`
- Adjacent archive: `YYYY-MM-DD-to-DD-todo.md` (or "first archive")
```

After excision, leave a one-liner reference at the bottom of `TODO.md`:
```
## 📦 Archived
- [`todo-history/YYYY-MM-DD-to-DD-todo.md`](todo-history/...) — N closed sections, archived YYYY-MM-DD
```

### 4.5 Operational Modes

Mirror `/history-management` exactly:

| Mode | Behavior |
|---|---|
| `check` (default) | Token count + severity report; no changes |
| `archive` | Run §4.2 + §4.3 + §4.4; preview + user confirmation; then execute |
| `analyze` | Deep stats: closed-section ratio, pending-age distribution, growth velocity |
| `dry-run` | Same as `archive` but prints planned diffs and never writes |

## 5. Failure Modes Considered

| Failure | Mitigation |
|---|---|
| Auto-archive a section that looked CLOSED but had a `[ ]` we missed | Two-pass classify (regex + line-by-line bullet scan); confirmation preview before write |
| Section date not extractable | Fail-safe = NOT archivable |
| User wants to reactivate an archived item later | Archive is verbatim; user grep-searches `todo-history/`, copies row back to TODO.md |
| Archive grows large itself | Same precedent as history archives — they don't get re-archived; PIP doc just says "no consolidation" |
| Stale-pending list grows large | That's a **feature**, not a bug — surfaces neglect that needs human attention |

## 6. Integration Points

- **Session-end workflow** (`/plan-session-end`): inject health-check at Step 0.5 (parallel to history-management), block with WARNING/CRITICAL severity
- **Slash command**: `/todo-size-management [check|archive|analyze|dry-run]` at `.claude/commands/todo-size-management.md`
- **Cross-project follow-up**: once validated locally, lift to `planning-is-prompting/workflow/todo-size-management.md` so other PIP-using projects benefit

## 7. Why This Pattern Stays Local Initially (Phase 3)

The PIP canonical TODO doc says "never archive." Promoting size-management to PIP is a **canonical-policy change**, not a pure code addition. Validate the algorithm against Lupin's TODO.md first (real 31.5k overage, real session-archival history mix), then lift to PIP with battle-tested defaults.

## 8. Out of Scope

- Auto-prune of pending items (NEVER auto)
- Promotion to PIP (Phase 3 follow-up TODO entry only — actual authoring needs a PIP-rooted session)
- Velocity-database tracking (history-management's "future enhancement" — same applies here, defer)
- Per-project threshold overrides (defer)

## 9. Sweep Check

Per feedback memory `feedback_sweep_for_pattern_offenders.md`: are there other oversized markdown indices that could benefit from this? Quick scan:

- ✅ `bug-fix-queue.md` — already managed via bug-fix-mode workflow
- ✅ `history.md` — managed via `/history-management`
- 🟡 `TODO.md` — THIS DOC
- ✅ Implementation tracking docs in `src/rnd/` — short-lived, no overage problem

No additional offenders. Sweep clean.

---

## Acceptance Criteria

1. ✅ Phase 0: design doc + execution log serialized in `src/rnd/v0.1.7/2026.05.01-todo-size-management/`
2. ⏳ Phase 1: `/todo-size-management` slash command exists at `.claude/commands/todo-size-management.md`, mirrors history-management shape, four modes work
3. ⏳ Phase 2: Run `archive` mode against current `TODO.md`; result is ≤12k tokens; archive file created in `todo-history/`; stale-pending surface emitted; user confirms before write
4. ⏳ Phase 3: cross-project `[LUPIN→PIP]` follow-up TODO entry added pointing to the PIP-promotion task

---

## Revision History

- **v1.0** (2026-05-01, Session 92ece47c): Initial design, approved verbally in conversation mode
