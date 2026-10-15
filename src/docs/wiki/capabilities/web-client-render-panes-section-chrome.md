---
capability: web-client-render-panes-section-chrome
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.sectionHeader.renderSectionHeader@c7ad5c77d1
  - src.lupin_app.static.js.multiplexer.render.templates.sectionHeader.formatTitle@16bb7d4e0d
  - src.lupin_app.static.js.multiplexer.render.templates.sectionHeader.headerClickShouldCollapse@d8bdbf81f4
  - src.lupin_app.static.js.multiplexer.render.templates.sectionHeader.setSectionCollapsed@2320c0b7a1
  - src.lupin_app.static.js.multiplexer.render.templates.sectionHeader.wireSectionCollapse@19c38203cc
  - src.lupin_app.static.js.multiplexer.render.templates.sectionToolbar.renderSectionToolbar@7f60ba2645
  - src.lupin_app.static.js.multiplexer.render.templates.navBar.isActivePage@589199b5ab
  - src.lupin_app.static.js.multiplexer.render.templates.navBar.renderNavBar@9e0474995a
---
# Render panes: section chrome

Builders for the bars that frame every multiplexer pane: the section header with its collapse chevron, the visibility toolbar and the top nav bar.

## Section header
- `renderSectionHeader( { icon, title, testid?, actions? } )` returns a handle with `header`, `countEl`, `actionsEl`, `toggleEl`, `setCount` and `setTitle`. The chevron button is always the last child of the actions slot.
- `formatTitle( icon, title )` is the private text builder. It returns the title plus a trailing space, with the icon and a space in front unless the icon is empty. `setTitle` reuses it.
- `headerClickShouldCollapse( target, toggleEl )` says whether a click collapses. It is false for a null target and for a click inside any other button, link, input or select. It is true for the chevron and for any click outside those controls.
- `setSectionCollapsed( section, handle, collapsed )` sets `data-collapsed` on the section and flips the chevron between a down and a right glyph.
- `wireSectionCollapse( section, handle, persist? )` adds one click listener to the header and returns a function that removes it. With `persist`, it applies the stored state first and writes each toggle back.
- Sixteen renderers call `renderSectionHeader` and fifteen call `wireSectionCollapse`. `NotificationsHeaderRenderer` also calls the predicate and `setSectionCollapsed`, and `ActionRequiredRenderer` calls `setSectionCollapsed`.

## Toolbar and nav bar
- `renderSectionToolbar( toggles = SECTION_TOGGLES )` returns `#section-toolbar` with one active `.toolbar-btn` per spec, keyed by `data-section`. `SectionToolbarRenderer` is its only caller in code. A spec may also name `sectionIds` and a `persistKey`. This function ignores both; `SectionToolbarRenderer` reads them.
- `isActivePage( itemUrl, currentPath )` matches `/app` only against itself, with or without a slash. Every other link matches by path prefix. `lupin-nav.js` and `nav/lupinNav.ts` hold their own copies.
- `renderNavBar( data, handlers )` returns `nav#lupin-nav`. Notifications and Profile links show only when authenticated. The right side shows email and a Logout button when authenticated with an email, otherwise a Login link. Logout calls `handlers.onLogout`. A hamburger toggles an open class on the links and right regions. `NavBarRenderer` calls it.

The header builders hand back elements and a handle, and renderers add their own body and persistence. `SectionToolbarRenderer` handles toolbar clicks by `data-section`. See [[web-client-render-panes-modals-and-state]] and [[web-client-render-panes-submit-and-qa]].
