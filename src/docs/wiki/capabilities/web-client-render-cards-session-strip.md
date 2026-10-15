---
capability: web-client-render-cards-session-strip
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.sessionStripIcon.personaInitial@7560a28a59
  - src.lupin_app.static.js.multiplexer.render.templates.sessionStripIcon.applyManagerBadge@6a13733074
  - src.lupin_app.static.js.multiplexer.render.templates.sessionStripIcon.stripAllocStatus@adb21786e0
  - src.lupin_app.static.js.multiplexer.render.templates.sessionStripIcon.applyAllocStatus@8061605435
  - src.lupin_app.static.js.multiplexer.render.templates.sessionStripIcon.renderSessionStripIcon@d336a6b9f7
  - src.lupin_app.static.js.multiplexer.render.templates.sessionStripIcon.updateSessionStripIcon@86aa228d95
---
# Session strip icon

Builds and refreshes the round persona button that stands for one Claude Code session in the session strip.

## Functions
- `personaInitial( name )` returns the first character upper-cased, or a question mark for an empty or blank name.
- `applyManagerBadge( button, managerPersona )` removes any old badge. For a manager it appends a badge span showing the manager's initial and sets `data-has-manager`. The title reads "Spawned by" plus the name, or "manager" when the name is empty. The `--manager-color` variable is set only for a non-empty color.
- `stripAllocStatus( session )` returns "borrowed" when the persona is borrowed, "inactive" when the session is not active, otherwise null.
- `applyAllocStatus( button, session )` writes that result to `data-alloc-status`, or removes the attribute on null. A stylesheet draws the indicator from it.
- `renderSessionStripIcon( session )` returns a button carrying the sender id, `data-active`, an initial span and a title. The title is the persona name, else the sender id. It sets `--persona-color` for a non-empty color, then applies the badge and alloc status.
- `updateSessionStripIcon( button, session )` repaints active flag, title, initial, badge and alloc status in place. It removes `--persona-color` when the color is empty. It leaves focus and hidden attributes alone.

## Callers
`SessionStripRenderer` calls the render and update pair from its keyed merge. The render index re-exports those two plus `personaInitial` and `applyManagerBadge`. `stripAllocStatus` and `applyAllocStatus` are used only inside this file.

The render and update paths share `applyManagerBadge` and `applyAllocStatus`, so a first paint and a later patch produce the same attributes. The initial sits in its own span so a badge change never overwrites it.
