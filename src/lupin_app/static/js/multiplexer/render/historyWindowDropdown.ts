/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line.
// Multiplexer history-window picker (2026-09-10, P0 5ebd2aff — Rick's ruling 1,
// "add legacy picker").
//
// Port of the UI half of legacy createHistoryWindowDropdown / toggleHistoryDropdown
// / setHistoryWindow / updateHistoryWindowDisplay (notifications.js:19672-19806)
// with the SAME ids and class names, so a sheet written for legacy's dropdown
// styles this one. Mux idiom: listeners attached to the elements built here, no
// inline onclick, no window globals. The store owns the value, its persistence
// under the legacy key, and the reload (NotificationStore.setHistoryWindow →
// coldHistoryHydration).
//
// One deliberate difference: legacy's updateHistoryWindowDisplay sets the
// button's textContent, which drops the ▼ arrow after the first change. The label
// lives in its own span here, so the arrow stays.

import { HISTORY_WINDOW_OPTIONS, historyWindowLabel, type HistoryWindow } from "../stores/historyWindow";

// Narrowed NotificationStore surface (the production store satisfies it).
export interface HistoryWindowStoreLike {
  historyWindow(): HistoryWindow;
  setHistoryWindow(w: HistoryWindow): void;
}

export interface HistoryWindowDropdownHandle {
  /** The `#history-window-dropdown` element, ready to place in the header. */
  element : HTMLElement;
  /** Repaint the label and the selected item from the store. */
  sync(): void;
  /** Detach the document click-outside listener. */
  dispose(): void;
}

/**
 * Build the history-window picker.
 *
 * Requires:
 *   - `doc` is the document the element will be placed in
 * Ensures:
 *   - `#history-window-dropdown.history-window-dropdown` holds a `button.dropdown-display`
 *     (current window's label + `▼`) and `#history-dropdown-menu.dropdown-menu`
 *     with one `.dropdown-item` per HISTORY_WINDOW_OPTIONS entry, in order; the
 *     current window's item is `.selected`
 *   - clicking the display toggles the menu's `.show`
 *   - clicking an item closes the menu, passes that option's value to
 *     `setHistoryWindow` (the store ignores an unchanged value), and repaints
 *   - a click anywhere outside the dropdown closes the menu
 *   - no click inside the dropdown reaches an ancestor, so the section header
 *     it sits in never collapses from it
 */
export function createHistoryWindowDropdown(store: HistoryWindowStoreLike, doc: Document): HistoryWindowDropdownHandle {
  const root = doc.createElement("div");
  root.id = "history-window-dropdown";
  root.className = "history-window-dropdown";
  root.setAttribute("data-testid", "multiplexer-history-window-dropdown");

  const display = doc.createElement("button");
  display.type = "button";
  display.className = "dropdown-display";
  const labelEl = doc.createElement("span");
  labelEl.className = "dropdown-display-label";
  const arrow = doc.createElement("span");
  arrow.className = "dropdown-arrow";
  arrow.textContent = "▼";
  display.append(labelEl, " ", arrow);

  const menu = doc.createElement("div");
  menu.id = "history-dropdown-menu";
  menu.className = "dropdown-menu";

  const items: Array<{ item: HTMLElement; hours: HistoryWindow }> = [];
  const sync = (): void => {
    const current = store.historyWindow();
    labelEl.textContent = historyWindowLabel(current);
    for (const { item, hours } of items) item.classList.toggle("selected", hours === current);
  };

  for (const option of HISTORY_WINDOW_OPTIONS) {
    const item = doc.createElement("div");
    item.className = "dropdown-item";
    item.textContent = option.label;
    item.addEventListener("click", () => {
      menu.classList.remove("show");
      store.setHistoryWindow(option.hours);
      sync();
    });
    menu.appendChild(item);
    items.push({ item, hours: option.hours });
  }
  root.append(display, menu);

  display.addEventListener("click", () => { menu.classList.toggle("show"); });
  // Clicks inside stop here: the header never sees them, and neither does the
  // document listener below — so that listener only ever hears OUTSIDE clicks.
  root.addEventListener("click", (e) => { e.stopPropagation(); });
  const onDocumentClick = (): void => { menu.classList.remove("show"); };
  doc.addEventListener("click", onDocumentClick);

  sync();
  return {
    element : root,
    sync,
    dispose : () => { doc.removeEventListener("click", onDocumentClick); },
  };
}
