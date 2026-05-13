# Enable Speakerphone

**Project**: Lupin
**Prefix**: [LUPIN]

---

## Instructions to Claude

When the user invokes this slash command:

1. **Call the cosa-voice MCP tool** `enable_speakerphone()` to flip this session into speakerphone mode (server-canonical bridge file `speakerphone_on=true`).

2. **Confirm the result** in a single short line — speak it via `notify(message="Speakerphone on", priority="high", suppress_ding=False)` so the user gets immediate audio confirmation that the toggle landed (this confirmation ding is intentional — distinguishes the mode-flip from regular speakerphone-mode TTS which suppresses dings).

3. **From this turn forward** — until `disable_speakerphone()` is called or the session restarts — honor the per-turn `<system-reminder>` rider that the cosa-voice MCP server now injects on every inbound user prompt. The rider's body varies by `(tts_interaction_mode, speakerphone_on)` and is the authoritative source of per-turn behavior (acknowledge-receipt rule, brevity, routing, mode-specific framing).

## Usage

```
/speakerphone-on
```

Use when you want Claude to speak its full responses aloud so you can carry on a voice dialogue from a distance, without watching the terminal. In **solo** mode the toggle displaces any other session that currently holds speakerphone; in **chorus** mode multiple sessions can hold it simultaneously. The toggle survives `/clear` within this Claude Code session and resets on a new session start.

## Related

- `/speakerphone-off` — revert to default notification mode (text-only render)
- UI toggle button (📞/🔔/🔊 — varies by mode) in the cosa-voice notification UI sender card header
- Voice phrase: "enable speakerphone" / "speakerphone on" — Claude pattern-matches and calls the MCP tool
