---
capability: web-client-render-action-required-readonly-and-queue
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredReadOnly.renderActionRequiredReadOnly@ee6da9c1c5
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredReadOnly.renderActionRequiredEmpty@466033654e
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredReadOnly.responseTypeBadge@ea2b636311
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredReadOnly.renderOptionsPreview@29236a3b51
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredQueueRow.typeIcon@19874f8263
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredQueueRow.formatQueueTimeout@57795a95b0
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredQueueRow.renderActionRequiredQueueRow@55895d8984
---
# Action-required read-only card, empty state and queue row

The non-interactive card, the "no pending actions" line and the minimized row for a queued card.

## What it does
- `renderActionRequiredReadOnly( item, countdownMs )` returns an inert `.action-required-widget`. It carries `aria-disabled`, `data-phase6-pending` and a not-allowed cursor.
- It shows the prompt, a type badge, the countdown from `countdownMs` as `mm:ss`, an options preview, "Default: <default or no>" and a notice.
- `responseTypeBadge` names the type as yes/no, multiple choice, open ended or open ended (batch).
- `renderOptionsPreview` shows Yes and No chips, one chip per option label across all questions, or a text placeholder for the two open-ended types.
- `renderActionRequiredEmpty()` returns `#action-required-empty` reading "✓ No pending actions".
- `renderActionRequiredQueueRow( item, position )` returns a `.action-required-minimized` row with `#position`, an icon, the prompt and the timeout. A prompt over 60 characters is cut to 57 plus "...". The row has no button or input.
- `typeIcon` gives ❓ for yes_no, 💬 for open_ended, 📋 for multiple_choice and 📢 for anything else.
- `formatQueueTimeout( seconds )` returns whole minutes as `Nm` from 60 seconds up, and `Ns` below.

## How the parts work together
`ActionRequiredRenderer` paints an active card with the interactive form from [[web-client-render-action-required-interactive]] and the queued items as queue rows. It uses `renderActionRequiredEmpty` when nothing is pending.

## Don't
- Don't expect `renderActionRequiredReadOnly` to be on screen. It has no production caller; only its unit test calls it.
