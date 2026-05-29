# Disable Speakerphone

**Project**: Lupin
**Prefix**: [LUPIN]

---

## Instructions to Claude

When the user invokes this slash command:

1. **Call the cosa-voice MCP tool** `disable_speakerphone()` to revert this session to the default phone-mode (server-canonical bridge file `speakerphone_on=false`).

2. **Confirm the result** in a single short line — speak it via `notify(message="Phone mode (text-only render)", priority="high", suppress_ding=False)` so the user gets audio confirmation. This will be the last automatic notify until speakerphone is re-enabled.

3. **From this turn forward** — return to phone-mode behavior. TTS fires only when YOU explicitly call `notify()`, `converse()`, or `ask_*()`. Do NOT auto-`notify()` after every turn. The per-turn rider that the cosa-voice MCP server injects will reflect the new state and carry the appropriate framing.

## Usage

```
/speakerphone-off
```

Use when you want to stop having Claude speak its full responses and return to selective TTS via explicit `notify()` calls.

## Related

- `/speakerphone-on` — re-enable speakerphone
- UI toggle button (📞/🔔/🔊 — varies by mode) in the cosa-voice notification UI sender card header
- Voice phrase: "disable speakerphone" / "speakerphone off" — Claude pattern-matches and calls the MCP tool
