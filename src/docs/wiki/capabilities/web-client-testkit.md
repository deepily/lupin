---
capability: web-client-testkit
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.testkit.accordionHarness.paneRoot@b3e0647dfa
  - src.lupin_app.static.js.multiplexer.testkit.accordionHarness.mount@596ddd319b
  - src.lupin_app.static.js.multiplexer.testkit.accordionHarness.inertMutation@9958db8807
  - src.lupin_app.static.js.multiplexer.testkit.accordionHarness.fakeTaskStore@cfb3be367f
  - src.lupin_app.static.js.multiplexer.testkit.accordionHarness.fakeHoldingStore@f4e57422b7
  - src.lupin_app.static.js.multiplexer.testkit.accordionHarness.compositeOf@fdb1efe873
  - src.lupin_app.static.js.multiplexer.testkit.accordionHarness.mountRenderers@d28909e289
  - src.lupin_app.static.js.multiplexer.testkit.parityFixture.muxPersona@31a8c25b19
  - src.lupin_app.static.js.multiplexer.testkit.parityFixture.muxSenderRecord@2b0e643d43
  - src.lupin_app.static.js.multiplexer.testkit.parityFixture.muxIncoming@255a0cf0e9
  - src.lupin_app.static.js.multiplexer.testkit.parityFixture.muxOutgoing@acdb1de741
  - src.lupin_app.static.js.multiplexer.testkit.parityFixture.toMuxModel@db7113a028
  - src.lupin_app.static.js.multiplexer.testkit.parityFixture.conversationRow@feda3c75d9
  - src.lupin_app.static.js.multiplexer.testkit.parityFixture.toConversationByDate@0273c719de
  - src.lupin_app.static.js.multiplexer.testkit.parityFixture.toSendersVisible@b86eb28fd7
  - src.lupin_app.static.js.multiplexer.testkit.parityHarness.mount@9ffc88d162
  - src.lupin_app.static.js.multiplexer.testkit.parityHarness.legacyShapes@b6b0df1384
---
# Web client test kit

The harnesses and fixtures that the multiplexer's tests build on. They are test support, not page code. `parityHarness.ts` imports `parityFixture.ts`.

## What it does
- `accordionHarness.ts`. `paneRoot`: Fresh pane root, replacing any prior render so re-mounts are idempotent. `mount`: Builds the accordion test page from a scenario with task list, holding and epic panes. `inertMutation`: A settled mutation handle. `fakeTaskStore`: Returns a task list store stub that serves a fixed composite and does nothing on writes. `fakeHoldingStore`: Returns a holding area store stub that serves a fixed composite. `compositeOf`: Wraps a list of tasks into a task list composite with ok status and the given time zone. `mountRenderers`: Builds the accordion test page from a scenario using real renderers over stub stores.
- `parityFixture.ts`. `muxPersona`: Project a test voice persona onto the five-field client persona shape. `muxSenderRecord`: Convert a scenario sender into a multiplexer sender record. `muxIncoming`: Convert a scenario notification into an incoming multiplexer notification. `muxOutgoing`: Build the synthetic outgoing notification carrying a scenario response value. `toMuxModel`: Map the canonical scenario to the multiplexer component-isolation model. `conversationRow`: Convert a scenario notification into a conversation-by-date row. `toConversationByDate`: Map the canonical scenario to the /api/notifications/conversation-by-date REST shape (per-sender, date-grouped) that both clients hydrate from. `toSendersVisible`: Map the canonical scenario to the /api/notifications/senders-visible REST shape. `count` = total messages for the sender; persona'd senders carry assigned_at (= last_activity) for fidelity with the live shape.
- `parityHarness.ts`. `mount`: Render the scenario into the sender cards container and return the sender count. `legacyShapes`: Return the scenario in the senders-visible and conversation-by-date shapes.
