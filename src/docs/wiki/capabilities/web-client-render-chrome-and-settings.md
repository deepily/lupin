---
capability: web-client-render-chrome-and-settings
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.DebugPanelRenderer.DebugPanelRendererImpl@2895e9e636
  - src.lupin_app.static.js.multiplexer.render.DebugPanelRenderer.createDebugPanelRenderer@79dde8f346
  - src.lupin_app.static.js.multiplexer.render.FilterSettingsRenderer.FilterSettingsRendererImpl@e48240a1f5
  - src.lupin_app.static.js.multiplexer.render.FilterSettingsRenderer.createFilterSettingsRenderer@5270834c7e
  - src.lupin_app.static.js.multiplexer.render.NavBarRenderer.NavBarRendererImpl@03beaa91d7
  - src.lupin_app.static.js.multiplexer.render.SectionToolbarRenderer.SectionToolbarRendererImpl@982af9c41e
  - src.lupin_app.static.js.multiplexer.render.SectionToolbarRenderer.createSectionToolbarRenderer@1f4acd3ff0
  - src.lupin_app.static.js.multiplexer.render.SystemStatusRenderer.statusRow@12ed402bc5
  - src.lupin_app.static.js.multiplexer.render.SystemStatusRenderer.SystemStatusRendererImpl@d844fc205d
  - src.lupin_app.static.js.multiplexer.render.SystemStatusRenderer.createSystemStatusRenderer@5f3c4f5db4
---
# Multiplexer chrome and settings renderers

These five renderers draw the multiplexer's fixed page furniture: the nav bar, the section toolbar, and the debug, filter and status panes.

- `NavBarRendererImpl` draws the top nav bar from an injected auth port and the active path. It redraws on every `auth_state_change` event. A second `mount` without `unmount` throws.
- `DebugPanelRendererImpl` is the Debug Information pane. `mount` registers it as the debug sink and `unmount` clears the sink first.
- It shows newest lines first and keeps at most 20, counting the seeded "System starting up..." line. Messages go in as text, never as markup.
- `createDebugPanelRenderer` returns it. The only option is a clock for the `[time]` stamp on each line.
- `FilterSettingsRendererImpl` is the Queue Filter Settings pane with three view-mode buttons and a "Currently viewing:" line. A click calls `store.setFilterMode`, then repaints from the mode the store reports.
- Its pane element has `display` set from the admin check alone. `reveal` does nothing for a non-admin; for an admin it saves visibility and re-applies the display.
- `createFilterSettingsRenderer` returns it. All four options are required: bus, store, view state and the admin check. It repaints when the store announces a `filtered` change.
- `SectionToolbarRendererImpl` draws one toggle button per section. A click flips the saved visibility, the button's `active` class, and the `section-hidden` class and `hidden` attribute on the section.
- Showing a section by click scrolls it into view when its element is found. Hiding does not scroll, and neither does the reconcile at mount.
- `showSection` un-hides a section from code and saves it. It does nothing if the section is already visible, and it works before `mount`.
- `createSectionToolbarRenderer` returns it. Only `stores.viewState` is required; `doc` and `toggles` default to the page document and `SECTION_TOGGLES`.
- `SystemStatusRendererImpl` is the System Status pane: two socket pills, auth, user, two session codes, a health line and a Config reload button.
- Pills follow `connection_state_change` events. The health line is re-read every 90 seconds and touches no socket.
- The ↻ button runs one refresh pass, logs a failure, and always re-enables itself. "Retry now" restarts only transports whose state is `failed`.
- The Config reload button has no admin check in this file. A returned status of `success` shows a green ✓, anything else a red ✗. A thrown error also shows a red ✗ with its message.
- `statusRow` builds one `status-item` row: a bold label, plus a value span with a test id and seeded text. It returns the row, the value element and the label.
- `createSystemStatusRenderer` returns it. The bus, auth, transports, session ids and `reinitConfig` are required; the clock, clipboard and timer functions are for tests.

## How the parts work together

Each renderer mounts into a root element it is given. The debug, filter and status panes build the shared section header. The toolbar flips a section's saved visibility. The filter pane sets its own display from the admin check at mount and in `reveal`, which also saves visibility. See [[web-client-jobs-and-session-panes]] for the job panes beside them.
