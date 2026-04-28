# Exit Conversation Mode

**Project**: Lupin
**Prefix**: [LUPIN]

---

## Instructions to Claude

When the user invokes this slash command:

1. **Call the cosa-voice MCP tool** `exit_conversation_mode()` to revert this session to the default notification mode (server-canonical bridge file flag).

2. **Confirm the result** in a single short line — speak it via `notify(message="Notification mode (default)", priority="high", suppress_ding=False)` so the user gets audio confirmation. This will be the LAST automatic notify until conversation mode is re-entered.

3. **From this turn forward** — return to normal notification mode behavior. TTS only fires when YOU explicitly call `notify()`, `converse()`, or `ask_*()`. Do NOT auto-`notify()` after every turn.

## Usage

```
/conversation-mode-off
```

Use when you want to stop having Claude speak its full responses and return to selective TTS via explicit `notify()` calls.

## Related

- `/conversation-mode-on` — re-enter conversation mode
- UI toggle button (📞/🔔) in the cosa-voice notification UI sender card header
- Voice phrase: "exit conversation mode" — Claude pattern-matches and calls the MCP tool
