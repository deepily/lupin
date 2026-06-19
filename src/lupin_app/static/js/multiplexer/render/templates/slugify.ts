/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6c Node A — slugify helper (Recon-A5).
//
// Maps a sender_id (legacy format `claude.code@lupin.deepily.ai#c7333045`)
// to an HTML-id-safe slug suitable for the `popovertarget` attribute on
// persona-badge buttons and the `id` attribute on persona-popover modals.
//
// The HTML `id` attribute permits any non-whitespace char per spec, but
// querySelector requires CSS-escaping for many of them. Using a slug
// containing only `[a-zA-Z0-9_-]` sidesteps both id-validity quirks AND
// CSS-selector escaping needs at the cost of an irreversible transformation
// (slugify is one-way; the renderer never needs to reverse it).
//
// Used by both:
//   - `senderCard.ts` (Step A1 — builds the `popovertarget` attribute on
//     the persona-badge button)
//   - `personaModal.ts` (Step A2 — builds the matching `id` attribute on
//     the popover root element)
//
// Hosting in a shared helper file ensures the two sites stay in sync.

/**
 * Replace every char outside `[a-zA-Z0-9_-]` with `-`. Used for HTML-id-safe
 * slugs derived from sender_ids.
 *
 * Requires:
 *   - `senderId` is a non-empty string (caller's invariant).
 *
 * Ensures:
 *   - Returns a string of the same length, with all non-id-safe chars
 *     replaced by `-`. Same input always produces same output.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function slugifySenderId( senderId: string ): string {
  return senderId.replace(/[^a-zA-Z0-9_-]/g, "-");
}
