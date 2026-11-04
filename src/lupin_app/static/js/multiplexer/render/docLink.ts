/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line (same as TtsQueueStore.ts:1, wireTtsIntent.ts:1, ttsPreview.ts:1).
// Multiplexer — the ONE place that decides what a doc link is and how it opens.
//
// Row 47759aa3. Before this module the answer lived in two places per client:
// ReadingPaneRenderer held a private `normalizeDocLinkHref` plus its own
// `DOC_LINK_PREFIX`, and markdown.ts independently stamped `target="_blank"`
// onto every anchor it emitted. Those two copies disagreed, and the
// disagreement was the bug: a doc link rendered with `_blank` opened a new tab
// whenever the renderer's interception did not claim the click first.
//
// 🔴 THE DUPLICATION *WAS* THE DEFECT, so the fix is one predicate, imported.
// Measured 2026-09-26 on :7999: in vertical layout the interception bailed and
// every one of the 5 live doc anchors fell through to its baked-in `_blank`.
// A guard that has to out-run a fallback loses eventually; removing the
// fallback is what makes the in-app path the only path.

/** Every in-app doc link starts here, after loopback normalization. */
export const DOC_LINK_PREFIX = "/app/docs?path=";

// `http://localhost:7999/app/docs?…` and `/app/docs?…` are the same document.
// Senders emit both, so the prefix test must run on a normalized href or it
// silently misses the absolute form.
const LOOPBACK_PREFIX_RE = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?/;

/**
 * Strip an absolute loopback origin so an href can be compared and fetched
 * relative to whatever host is serving the page.
 *
 * Returns null for a null/empty href — callers treat that as "not a doc link"
 * rather than as an error, because an `<a>` with no href is ordinary markup.
 */
export function normalizeDocLinkHref( href: string | null ): string | null {
  if (href === null || href === "") return null;
  return href.replace(LOOPBACK_PREFIX_RE, "");
}

/**
 * True when this href addresses the in-app doc viewer, in either the relative
 * or the absolute-loopback form.
 *
 * This is the predicate `markdown.ts` consults before stamping `_blank`, and
 * the one `ReadingPaneRenderer` consults before claiming a click — so the
 * emitter and the interceptor cannot drift apart again.
 */
export function isDocLinkHref( href: string | null ): boolean {
  const normalized = normalizeDocLinkHref(href);
  return normalized !== null && normalized.startsWith(DOC_LINK_PREFIX);
}

/**
 * The two surfaces whose doc links must KEEP opening a new tab.
 *
 * Not an oversight and not a style choice — the Reading Pane is SHARED with
 * the live action-required response buttons, and opening a doc into it calls
 * `replaceChildren`, which would delete the buttons the user was mid-way
 * through pressing. Legacy paid for this twice: bug 11c01fbc for the card,
 * then 17ce50a5 for the tooltip, which is fixed-position and appended to
 * <body>, so an ancestry test against the card alone misses it.
 *
 * María ratified the carve-out 2026-09-26 and it does not contradict Rick's
 * ruling: his population is doc links in the NOTIFICATION HISTORY, and every
 * one of those now opens in-app.
 */
export const PANE_RESIDENT_SELECTOR = "#action-required-content, #action-required-section, .abstract-tooltip";

/**
 * True when this anchor lives on a pane-resident surface, so routing it into
 * the pane would destroy the surface it was clicked from.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (same as ttsPreview.ts:109); the body below is fully covered.
export function isPaneResidentAnchor( anchor: Element ): boolean {
  return anchor.closest(PANE_RESIDENT_SELECTOR) !== null;
}

// An href that names its own scheme (`https:`, `mailto:`, `data:`) or is protocol-relative (`//host`).
const SCHEME_OR_NETWORK_RE = /^([a-z][a-z0-9+.-]*:|\/\/)/i;

/**
 * Turn a relative markdown href into a doc-viewer link.
 *
 * A markdown file's own links are written for GitHub: `src/rnd/x.md` means "next to this file".
 * The viewer left them alone, so the browser resolved them against `/app/` and landed on `/app/src/rnd/x.md`,
 * a 404, even though the target exists. This function is the only place that resolves them.
 *
 * Requires:
 *   - `href` is the raw `href` attribute, or null
 *   - `docPath` is the open document's viewer path, `<scope>/<rel>` (the page's own `?path=` value)
 *
 * Ensures:
 *   - returns `/app/docs?path=<scope>/<resolved>` (plus any `#fragment`) for a relative href
 *   - returns null, meaning "leave this link alone", for an empty href, a bare `#anchor`, a scheme or
 *     protocol-relative URL, a root-absolute path (this includes existing `/app/docs?path=` links), and a
 *     `../` that would climb out of the document's scope
 */
export function resolveRelativeDocHref( href: string | null, docPath: string ): string | null {
  if (href === null || href === "" || href.startsWith("#") || href.startsWith("/")) return null;
  if (SCHEME_OR_NETWORK_RE.test(href)) return null;

  const hashAt   = href.indexOf("#");
  const fragment = hashAt === -1 ? "" : href.slice(hashAt);
  const noHash   = hashAt === -1 ? href : href.slice(0, hashAt);
  const queryAt  = noHash.indexOf("?");
  const rel      = queryAt === -1 ? noHash : noHash.slice(0, queryAt);

  let decoded: string;
  try { decoded = decodeURIComponent(rel); } catch (_e) { return null; }

  // The first segment is the scope; it is the floor a `..` may not go below.
  const stack = docPath.split("/").filter((s) => s !== "");
  if (stack.length < 2) return null; // no scope segment, so nothing to resolve inside
  stack.pop();
  for (const seg of decoded.split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") {
      if (stack.length <= 1) return null;
      stack.pop();
    } else {
      stack.push(seg);
    }
  }
  return DOC_LINK_PREFIX + encodeURIComponent(stack.join("/")).replace(/%2F/g, "/") + fragment;
}

/**
 * Rewrite relative links under a root to their doc-viewer form.
 *
 * Anchors, absolute URLs and links already pointing at the viewer are left exactly as they were.
 *
 * Requires: `root` is the element holding the rendered markdown; `docPath` is as for {@link resolveRelativeDocHref}.
 * Ensures: only `href` attributes of links that resolve are changed; returns how many were.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (same as isPaneResidentAnchor above); the body below is fully covered.
export function rewriteRelativeDocLinks( root: ParentNode, docPath: string ): number {
  let changed = 0;
  root.querySelectorAll("a[href]").forEach((a) => {
    const resolved = resolveRelativeDocHref(a.getAttribute("href"), docPath);
    if (resolved === null) return;
    a.setAttribute("href", resolved);
    changed++;
  });
  return changed;
}
