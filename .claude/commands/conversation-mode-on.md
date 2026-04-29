# Enter Conversation Mode

**Project**: Lupin
**Prefix**: [LUPIN]

---

## Instructions to Claude

When the user invokes this slash command:

1. **Call the cosa-voice MCP tool** `enter_conversation_mode()` to flip this session into conversation mode (server-canonical bridge file flag).

2. **Confirm the result** in a single short line — speak it via `notify(message="Conversation mode on", priority="high", suppress_ding=False)` so the user gets immediate audio confirmation that the toggle landed (this confirmation ding is intentional — distinguishes the mode-flip from regular conversation-mode TTS which suppresses dings).

3. **From this turn forward** — until `exit_conversation_mode()` is called or the session restarts — you have **TWO per-turn obligations**:

   **3a. Acknowledge receipt BEFORE tool work begins.** Every user prompt must be greeted with at minimum a brief receipt-acknowledgment notify call BEFORE you fire any tool calls:

   ```
   notify( message="<short ack of what you heard / what you'll do>", suppress_ding=True, priority="high" )
   ```

   A turn that opens with tool calls and never speaks violates the contract — the user is at a distance listening via TTS, not watching the terminal, and they have no way to know their prompt was received. The acknowledgment can be a single short sentence ("Looking into the conversation-mode directives now.") — it does not need to be the full plan. This rule applies even when the substantive response will arrive in a later turn.

   **3b. Speak every closing turn in full.** After tool work completes (or on any turn that produces user-facing text):

   ```
   notify( message=<full text of your response>, suppress_ding=True, priority="high" )
   ```

   - Strip fenced code blocks from the spoken text (TTS-hostile).
   - Skip pre-narration of tool calls (e.g. "running this Bash command…").
   - No length cap — speak the full response.

## Usage

```
/conversation-mode-on
```

Use when you want Claude to speak its full responses aloud so you can carry on a voice dialogue from a distance, without watching the terminal. The toggle survives `/clear` within this Claude Code session and resets to off on a new session.

## Related

- `/conversation-mode-off` — revert to default notification mode
- UI toggle button (📞/🔔) in the cosa-voice notification UI sender card header
- Voice phrase: "enter conversation mode" — Claude pattern-matches and calls the MCP tool
