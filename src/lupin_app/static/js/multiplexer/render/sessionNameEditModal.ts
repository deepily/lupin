/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer S2c (2026-09-10) — the "Rename Session" modal.
//
// Port of legacy showSessionNameEditModal (notifications.js:18245-18376) with the
// SAME class names and ids, so a sheet that styles the legacy modal styles this
// one. Mux idiom: no inline onclick, no window globals — listeners are attached
// to the elements built here, and the caller receives the name through `onSave`.
//
// NOT PORTED: the 🎤 mic button and its auto-start recording. The hint text is
// changed accordingly — the legacy "Click mic to speak" would name a control
// that is not there.

import { html } from "./html";

export interface SessionNameEditModalOptions {
  doc         : Document;
  currentName : string;
  onSave      : (name: string) => void;
}

/**
 * Open the rename modal on `doc.body`, replacing any modal already open.
 *
 * Requires:
 *   - `doc.body` exists
 * Ensures:
 *   - one `#session-name-edit-modal.session-name-edit-modal` is in the body, with
 *     a "Rename Session" header + × close, an input prefilled with `currentName`
 *     (focused and selected), a hint, and Cancel + Save buttons; no mic button
 *   - Save or Enter: a trimmed, non-empty name is passed to `onSave`; an empty or
 *     whitespace-only name changes nothing. Either way the modal closes
 *   - Cancel, × or Escape close the modal without calling `onSave`
 *   - returns a function that closes the modal (idempotent)
 */
export function openSessionNameEditModal(opts: SessionNameEditModalOptions): () => void {
  const { doc, currentName, onSave } = opts;
  doc.getElementById("session-name-edit-modal")?.remove();

  /* c8 ignore next */ // tagged-template literal: c8 reports a phantom branch on this line; the runtime path is straight-line and runs on every open.
  const frag = html`
    <div id="session-name-edit-modal" class="session-name-edit-modal">
      <div class="session-name-edit-content">
        <div class="session-name-edit-header">
          <span>Rename Session</span>
          <button class="session-name-edit-close" type="button">×</button>
        </div>
        <div class="session-name-edit-body">
          <div class="session-name-input-row">
            <input type="text" id="session-name-input" class="session-name-input" placeholder="Enter session name..." autocomplete="off" />
          </div>
          <div class="session-name-edit-hint">Type a name — Enter saves, Escape cancels</div>
        </div>
        <div class="session-name-edit-footer">
          <button class="session-name-cancel-btn" type="button">Cancel</button>
          <button class="session-name-save-btn" type="button">Save</button>
        </div>
      </div>
    </div>
  ` as DocumentFragment;
  const modal = frag.querySelector(".session-name-edit-modal") as HTMLElement;
  const input = frag.querySelector(".session-name-input") as HTMLInputElement;
  // Set as a property, not interpolated into markup, so any name round-trips.
  input.value = currentName;

  const close = (): void => { modal.remove(); };
  const save  = (): void => {
    const name = input.value.trim();
    if (name !== "") onSave(name);
    close();
  };

  (frag.querySelector(".session-name-edit-close")  as HTMLElement).addEventListener("click", close);
  (frag.querySelector(".session-name-cancel-btn")  as HTMLElement).addEventListener("click", close);
  (frag.querySelector(".session-name-save-btn")    as HTMLElement).addEventListener("click", save);
  input.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Enter") save();
    else if (e.key === "Escape") close();
  });

  doc.body.appendChild(frag);
  input.focus();
  input.select();
  return close;
}
