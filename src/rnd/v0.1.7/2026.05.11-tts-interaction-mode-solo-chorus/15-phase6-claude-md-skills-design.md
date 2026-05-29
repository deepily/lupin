# Phase 6 — CLAUDE.md Migration + Skill Rename/Retire

**Date**: 2026.05.12
**Status**: 📝 Design — not yet implemented
**Owner**: [LUPIN]
**Phase**: 6 of 8
**Prerequisites**: Phases 1–5 (rider must be emitting migrated content before CLAUDE.md is slimmed).
**Companion docs**: [`00-index.md`](00-index.md), [`01` (May 12 canonical plan)](2026.05.12-tts-interaction-mode-solo-chorus.md), [`02-background-synthesis.md`](02-background-synthesis.md)
**Execution log**: [`96-phase6-execution-log.md`](96-phase6-execution-log.md) (TBD)

---

## 1. Goal

Move TTS-conditional rules out of static CLAUDE.md and into the per-turn server rider (already emitting them after Phase 5). Rename slash-command skills to match the new naming. Retire the `conversation-mode-guardrails` skill — the rule it encodes (USER-ONLY initiation) lives in MCP tool docstrings + per-turn rider after Phase 4.

After this phase, CLAUDE.md documents only **always-on** notification API; speakerphone/phone-mode behavior is documented in the server-injected rider that all sessions see at every turn.

---

## 2. Scope

### In scope

**Global CLAUDE.md (`~/.claude/CLAUDE.md`)** — three sections REMOVED (content already in rider after Phase 5):

1. `CONVERSATION MODE & TTS RESPONSE BREVITY MANDATE` — brevity rules now in `_brevity_rules()` (speaker-on rider).
2. `INTERACTIVE TOOL ROUTING (AskUserQuestion → cosa-voice)` — now in `_routing_reminder()` (speaker-on rider).
3. `CRITICAL: The User Is NOT Watching the Terminal` — the spirit of this lives in the rider for both speaker-on (active TTS dialogue) and speaker-off (still cosa-voice-first for blocking decisions).

**Sections RETAINED** (always-on regardless of TTS state):

- `CLAUDE CODE NOTIFICATION SYSTEM` intro (MCP tool table).
- `MCP SESSION STARTUP PROTOCOL` (Phase A/B).
- `SESSION TOPIC (Stop Hook Context)`.
- `MANDATORY Notification Requirements` table.
- `DOCUMENT VIEWER LINKS` pattern.
- `Integration with TodoWrite`.

**Section ADDED** — single short pointer near the notification section:

> **Speakerphone / phone-mode behavior is server-rider-driven.** The cosa-voice MCP server injects per-turn rules based on this session's `speakerphone_on` state and the global `tts interaction mode`. Honor the injection as authoritative. CLAUDE.md only documents the always-on notification API.

**Skill files**:

| Action | Old path | New path |
|---|---|---|
| Rename + update | `~/.claude/skills/conversation-mode-on/SKILL.md` | `~/.claude/skills/speakerphone-on/SKILL.md` |
| Rename + update | `~/.claude/skills/conversation-mode-off/SKILL.md` | `~/.claude/skills/speakerphone-off/SKILL.md` |
| Retire (delete) | `~/.claude/skills/conversation-mode-guardrails/SKILL.md` | (gone) |
| Update | `~/.claude/skills/cosa-voice-notifications/SKILL.md` | (same path; tool names + field name updated) |

**Slash commands** (if they exist as separate files in `~/.claude/commands/`):

| Old | New |
|---|---|
| `~/.claude/commands/conversation-mode-on.md` | `~/.claude/commands/speakerphone-on.md` |
| `~/.claude/commands/conversation-mode-off.md` | `~/.claude/commands/speakerphone-off.md` |

### Out of scope

- Project-level `CLAUDE.md` / `CLAUDE.local.md` — no TTS-conditional content there per inspection. No edits.
- Any other workflow files (BFE / TFE guides, etc.) — verify via grep but no edits expected.
- Auto-memory entries that reference old names — these are user data, not code; user can update.

---

## 3. Deliverables

### 3.1 CLAUDE.md surgery

**Step 1 — Locate sections**: grep for the section headings exact-match:

```bash
grep -n '^## CONVERSATION MODE & TTS RESPONSE BREVITY MANDATE' ~/.claude/CLAUDE.md
grep -n '^### INTERACTIVE TOOL ROUTING' ~/.claude/CLAUDE.md
grep -n '^### CRITICAL: The User Is NOT Watching' ~/.claude/CLAUDE.md
```

**Step 2 — Cut each section** (heading + body, ending at the next heading at same or higher level).

**Step 3 — Insert the pointer paragraph** in the surviving notification section, ideally just after `Mandatory Notification Requirements`.

**Step 4 — Audit for cross-references**: grep CLAUDE.md for `conversation mode`, `enter_conversation_mode`, `exit_conversation_mode` after the cuts. Update any survivors to new vocabulary or remove if redundant.

### 3.2 Skill renames

For each `conversation-mode-{on,off}/SKILL.md` directory:

1. Read current content.
2. Update:
   - Title heading: "Conversation Mode On" → "Speakerphone On".
   - Slash-command name in the body.
   - MCP tool call: `mcp__cosa-voice__enter_conversation_mode()` → `mcp__cosa-voice__enable_speakerphone()`.
   - Description / trigger phrases.
3. Move directory: `git mv` if tracked, else `mv`.

### 3.3 Skill retirement

`conversation-mode-guardrails/SKILL.md` deletion:

```bash
rm -rf ~/.claude/skills/conversation-mode-guardrails/
```

Rationale: the USER-ONLY initiation rule it documents now lives in:
- MCP tool docstring on `enable_speakerphone` (Phase 4 deliverable).
- The per-turn server rider's monopoly-notice block (solo mode rider, Phase 5 deliverable).
- The decisions log (`90-decisions-log.md`) for audit trail.

Belt-and-suspenders is overkill once two authoritative sources cover it.

### 3.4 `cosa-voice-notifications` skill update

This skill is the API reference for cosa-voice tools. Updates:

- Replace `enter_conversation_mode` → `enable_speakerphone` in tool listings.
- Replace `exit_conversation_mode` → `disable_speakerphone`.
- Update any `conversation_mode_active` → `speakerphone_on`.
- Add a brief mention of `tts_interaction_mode` field in `get_session_info()` response if the skill documents that response.
- Update the slash-command references (`/conversation-mode-on` → `/speakerphone-on`).

### 3.5 Slash-command files

If `~/.claude/commands/conversation-mode-on.md` and `conversation-mode-off.md` exist:

1. Read content.
2. Update body:
   - Title.
   - MCP tool call within.
3. Move to new filename.

If they don't exist as separate files (e.g., slash commands are derived from skill names), this section is a no-op.

### 3.6 Documentation touchpoints (verification, no edits)

After CLAUDE.md surgery, audit these for stale references (find/grep):

| File | Search term | Action if hit |
|---|---|---|
| `src/docs/notification-api.md` | `conversation_mode` | Update to new vocabulary |
| `src/docs/cosa-voice-mcp.md` (if exists) | `enter_conversation_mode` | Update |
| `src/docs/websocket-events.md` | `conversation_mode_changed` | Update to `speakerphone_changed` |
| `src/workflow/agentic-voice-workflow.md` | `conversation_mode` | Update if relevant |
| `src/workflow/cosa-voice-integration.md` (planning-is-prompting) | `conversation_mode` | Update if relevant |
| `auto-memory entries` (`~/.claude/projects/.../memory/`) | various | Audit but defer — user owns these |

---

## 4. Implementation order

1. Sweep audit: grep all referenced files for old vocabulary; build worklist in execution log.
2. CLAUDE.md surgery: cut three sections, insert pointer.
3. Rename `conversation-mode-on` skill directory + update body.
4. Rename `conversation-mode-off` skill directory + update body.
5. Delete `conversation-mode-guardrails` skill directory.
6. Update `cosa-voice-notifications` skill content.
7. Rename slash-command files (if separate).
8. Update documentation touchpoint files (verify, edit if hit).
9. Verify CLAUDE.md still parses correctly (no orphan headings, no broken cross-references).

---

## 5. Verification matrix

| Layer | Check | Venue | Pass criteria |
|---|---|---|---|
| Static check | grep CLAUDE.md for old vocabulary post-surgery | local | Zero hits |
| Static check | grep `~/.claude/skills/` for old vocabulary post-rename | local | Zero hits |
| Static check | grep `~/.claude/commands/` for old slash-command name | local | Zero hits |
| Manual | Start new Claude Code session, verify session-startup reads CLAUDE.md without error | local | Session starts; no parsing complaints |
| Manual | Invoke `/speakerphone-on` slash command | local | Tool fires; bridge flips |
| Manual | Invoke `/speakerphone-off` slash command | local | Tool fires; bridge flips |
| Functional | Voice phrase "enable speakerphone" recognized | :7999 | Tool fires via MCP routing |

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | CLAUDE.md is large; cut might accidentally remove neighboring content | Read 50 lines of context above + below each cut target; verify cuts in a side-by-side diff. |
| 2 | Skill renames break user habit (typing `/conversation-mode-on` from muscle memory) | Acceptable — Rick is the only user, and the rename is intentional. No alias per [[feedback_no_migration_code]]. |
| 3 | Auto-memory entries reference old skill names; future sessions might look up `conversation-mode-guardrails` and fail | User-owned auto-memory; user updates at leisure. The retirement is documented in the decisions log. |
| 4 | `cosa-voice-notifications` skill is referenced from a CLAUDE.md "Detailed Reference" link — link still works (same path, content updated), but in-skill content may need updates | Step 6 of implementation order covers this. |
| 5 | Section heading anchors in CLAUDE.md may be linked from external docs (project plan files, design docs) | Search project docs for `#conversation-mode-tts-response-brevity-mandate` etc. before cut. Update linkers. |
| 6 | Hook code references skill paths (unlikely but possible) | Grep `src/lupin_cli/` for skill names; expected to find nothing. |

---

## 7. Cross-cutting concerns

### Memory check

- [[feedback_no_migration_code]] — no aliases for old skill/command names. ✓
- [[feedback_sweep_for_pattern_offenders]] — sweep is implementation step 1. ✓
- [[feedback_skip_rnd_doc_for_trivial_fixes]] — this phase IS mostly file ops, but as part of a multi-phase plan, the design doc is warranted. ✓
- [[feedback_documentation_step_stops_at_doc]] — N/A; this phase touches real config + skill files, not just docs.

### Naming

- Skill directory names: `speakerphone-on`, `speakerphone-off` (kebab-case, matches `conversation-mode-on` precedent).
- Slash commands: `/speakerphone-on`, `/speakerphone-off` (same).

---

## 8. Implementation timing

Estimated active work: 60–90 minutes including sweep audit + careful CLAUDE.md surgery.

---

## 9. Hand-off to Phase 7

Phase 7 (multiplexer UI) is the last code-touching phase. It reads `tts_interaction_mode` from `get_session_info()` (Phase 4) and renders the mode-appropriate toggle and affordances. Phase 6 has no direct hand-off to Phase 7 — they are independent.
