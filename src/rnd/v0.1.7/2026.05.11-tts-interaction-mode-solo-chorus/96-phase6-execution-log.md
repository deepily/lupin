# Phase 6 Execution Log — CLAUDE.md Migration + Skill Rename/Retire

**Date**: 2026-05-12 (PM EDT)
**Owner**: [LUPIN] (Rio session 83ba1e51)
**Companion design doc**: [`15-phase6-claude-md-skills-design.md`](15-phase6-claude-md-skills-design.md)
**Prerequisite**: Phase 5b (rider must emit migrated content before CLAUDE.md is slimmed) — landed earlier in this session.
**Status**: ✅ Complete — code + docs on disk, awaiting Rick commit auth

---

## 1. Global CLAUDE.md surgery

Backup written first: `~/.claude/CLAUDE.md.phase6.bak` (928 lines, pre-surgery state).

Three sections **stripped** (content now in the per-turn server rider after Phase 5b):

| Removed section | New home |
|---|---|
| `### INTERACTIVE TOOL ROUTING (AskUserQuestion → cosa-voice)` | `_routing_reminder()` in hook_common.py (speaker-on rider variant) |
| `### CRITICAL: The User Is NOT Watching the Terminal` | Implicit in the speaker-on rider's notify-after-response rule |
| `### CONVERSATION MODE & TTS RESPONSE BREVITY MANDATE` | `_brevity_rules()` in hook_common.py (speaker-on rider variant) |

One **pointer section added** in their place:
`### SPEAKERPHONE & TTS BEHAVIOR — SERVER-RIDER-DRIVEN` — a short paragraph
explaining that speakerphone/phone-mode behavior is rider-driven, listing the
key per-turn content carried, pointing to the Phase 5 design doc, and noting
the AskUserQuestion fallback path.

Sections **retained** (always-on, not TTS-conditional):
- `### Available MCP Tools` (the tool table)
- `### MCP SESSION STARTUP PROTOCOL` (Phase A/B)
- `### SESSION TOPIC (Stop Hook Context)`
- `### MANDATORY Notification Requirements`
- `### DOCUMENT VIEWER LINKS`
- `### Integration with TodoWrite`

Net file change: 928 → 889 lines (~40 lines removed, ~17 line pointer added).

## 2. Skill rename / retire

- **Retired**: `~/.claude/skills/conversation-mode-guardrails/` — content (USER-ONLY initiation rule + per-turn speaking contract) is now in:
  - The speaker-on rider's monopoly-notice (solo variant) + brevity rules (universal speaker-on)
  - The auto-memory `feedback_conversation_mode_user_only_initiation.md` (durable)
  - The Phase 5 design doc + this execution log (audit trail)

  Backup of the skill content stowed at `~/.claude/.phase6-backups/conversation-mode-guardrails/` (outside the skills directory so it does NOT surface in the active skills list).

- **No update needed**: `~/.claude/skills/cosa-voice-notifications/SKILL.md` — grep for `enter_conversation_mode` / `exit_conversation_mode` / `conversation_mode_active` / `speakerphone` returned ZERO hits. The skill never referenced the toggle MCP tools by name; nothing to rename.

- **No directory found**: `~/.claude/skills/conversation-mode-on/` and `~/.claude/skills/conversation-mode-off/` do NOT exist as skill directories. The `/conversation-mode-on` and `/conversation-mode-off` slash commands are project-local `.claude/commands/*.md` files (see §3).

## 3. Project-local slash commands

Renamed and content-updated (in the Lupin parent repo, will be part of this Phase 6 commit):

- `.claude/commands/conversation-mode-on.md` → `.claude/commands/speakerphone-on.md`
  - Title: "Enable Speakerphone"
  - MCP call: `enable_speakerphone()` (was `enter_conversation_mode()`)
  - Body slimmed: per-turn obligations now defer to the rider rather than re-stating them inline
  - Mode-aware framing: distinguishes solo (displaces) vs chorus (concurrent)
- `.claude/commands/conversation-mode-off.md` → `.claude/commands/speakerphone-off.md`
  - Title: "Disable Speakerphone"
  - MCP call: `disable_speakerphone()` (was `exit_conversation_mode()`)
  - Body slimmed similarly

Git ops: `git rm` on the old filenames; new files staged for the next commit.

## 4. Project documentation touchpoints (per design doc §3.6)

Sweep ran:

```bash
grep -rn 'conversation_mode|conversation mode|enter_conversation_mode|exit_conversation_mode' \
    src/docs/*.md src/workflow/*.md
```

Hits found and fixed:

| File:line | Old | New |
|---|---|---|
| `src/docs/notification-types.md:25` (state-update table) | `conversation_mode_changed` | `speakerphone_changed` |
| `src/docs/notification-types.md:28` (paragraph) | "conversation-mode toggles" | "speakerphone toggles" |
| `src/docs/notification-types.md:48` (action verb example) | `action:conversation_mode_enter` | `action:disable_speakerphone` (real Phase-5 action) |
| `src/docs/notification-types.md:54` (producers line) | `cosa/rest/routers/conversation_mode.py` | `cosa/rest/routers/speakerphone.py` |
| `src/docs/notification-types.md:73-79` (section + body) | `### conversation_mode_changed` + "conversation mode" / `active` field | `### speakerphone_changed` + "speakerphone mode" / `on` field + mode-aware lifecycle pointer + historical field-rename note |
| `src/docs/rest-api-reference.md:234` (response shape) | `conversation_mode_active` field | `speakerphone_on` field |

Post-sweep residual: one intentional historical-rename mention in `notification-types.md:81` (the `conversation_mode_active → speakerphone_on (Phase 2)` parenthetical). Legitimate breadcrumb.

## 5. Files touched

### Global ~/.claude (outside the Lupin repo — NOT git-tracked, persists in Rick's home dir)

- `~/.claude/CLAUDE.md` — surgery + pointer (backup at `~/.claude/CLAUDE.md.phase6.bak`)
- `~/.claude/skills/conversation-mode-guardrails/` — DELETED (backup at `~/.claude/.phase6-backups/conversation-mode-guardrails/`)

### Lupin parent repo (will be committed)

- `.claude/commands/conversation-mode-on.md` — REMOVED (`git rm`)
- `.claude/commands/conversation-mode-off.md` — REMOVED (`git rm`)
- `.claude/commands/speakerphone-on.md` — NEW
- `.claude/commands/speakerphone-off.md` — NEW
- `src/docs/notification-types.md` — terminology + field-name updates (6 edits)
- `src/docs/rest-api-reference.md` — response field-name update (1 edit)
- `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/96-phase6-execution-log.md` — this file

## 6. Verification

| Layer | Check | Result |
|---|---|---|
| Static | `grep -rn 'conversation_mode' src/docs/ src/workflow/` (post-sweep) | One intentional historical-rename mention only |
| Static | `grep 'conversation_mode\|enter_conversation_mode\|exit_conversation_mode' ~/.claude/CLAUDE.md` | One intentional "(formerly conversation mode)" parenthetical in the new pointer |
| Static | `ls ~/.claude/skills/` | Guardrails skill gone; backup outside the dir |
| Static | `ls .claude/commands/ \| grep -iE 'conversation\|speakerphone'` | Two new `speakerphone-*` files; legacy `conversation-mode-*` removed |
| Unit | No unit tests touched in Phase 6 (CLAUDE.md and skill files are not test-asserted) | N/A |

The skills system rescan after the directory rename still shows
`conversation-mode-on` / `conversation-mode-off` in the active session's
cached skills list — these will drop out on next session start or `/clear`
when the skills directory is re-scanned. No action needed.

## 7. Deviations from design doc

| Deviation | Rationale |
|---|---|
| Backup files written at `~/.claude/CLAUDE.md.phase6.bak` and `~/.claude/.phase6-backups/conversation-mode-guardrails/` | Design doc §3.3 used `rm -rf` directly; I retained reversibility because the global CLAUDE.md is not git-tracked. Rick can delete backups at leisure |
| `~/.claude/skills/conversation-mode-on/` and `conversation-mode-off/` skill directories were NEVER present | Design doc §3.2 assumed they existed; in practice the on/off slash commands are project-local `.claude/commands/*.md` files. Worked from the actual file layout, not the assumed one |
| Slimmed slash-command bodies of the per-turn-obligations boilerplate | After Phase 5b the rider carries those obligations; restating them in the slash command body would be duplication. Replaced with a one-line pointer to the rider |
| Did NOT edit `cosa-voice-notifications/SKILL.md` | Grep found zero speakerphone-related references; nothing to update. Per design §3.4 the updates were conditional on existing references |

## 8. Outstanding follow-ups

- **Auto-memory cleanup**: The user's auto-memory still references `conversation-mode-guardrails` as a skill name and `enter_conversation_mode` / `exit_conversation_mode` in some entries. Per design doc §3.6 + §6 Risk #3, auto-memory is user-owned data; Rick updates at leisure
- **Phase 7**: Multiplexer UI + 100% c8 coverage — biggest phase (240–360 min estimated)
- **Phase 8**: Deferred chorus UX color/glyph follow-up

## 9. Memory checks (per design doc §7)

- [[feedback_no_migration_code]] — no aliases for old skill / command names; hard cut with backup for reversibility, not aliasing. ✓
- [[feedback_sweep_for_pattern_offenders]] — full grep across docs + skills + commands; all real hits resolved. ✓
- [[feedback_skip_rnd_doc_for_trivial_fixes]] — this is part of a multi-phase plan; execution log warranted. ✓
- [[feedback_documentation_step_stops_at_doc]] — doc updates are scope-appropriate; no implementation creep. ✓
- [[feedback_lupin_only_never_cosa]] — no CoSA edits this phase. ✓
- [[feedback_never_auto_commit_push]] — no commits yet; awaiting Rick auth. ✓
