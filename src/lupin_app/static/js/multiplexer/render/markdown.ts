/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 5 — markdown rendering wrapper.
//
// Reuses the page-loaded `window.marked` + `window.DOMPurify` globals (Q-E
// ratification 2026-05-05). DOMPurify config + post-process target/rel
// rewriting port verbatim from `notifications.js:12203-12247` (block) per D-J
// ratification. Inline variant (no `<p>` wrap) ports from `:12279-12305`.
//
// Per Q-E, bundling `marked` + `DOMPurify` would add ~50KB to boot.js;
// reusing page globals keeps the renderer dependency footprint minimal.
//
// Both functions return a `RawValue` (`{__raw: string}`) so callers pass the
// result directly into `html\`…${renderMarkdown(text)}…\`` — the helper
// flows raw HTML through DocumentFragment construction (sanitized content).

import { raw } from "./html";
import type { Value } from "./html";

interface MarkedAPI {
  parse(input: string, opts?: { breaks?: boolean; gfm?: boolean }): string;
}
interface DOMPurifyAPI {
  sanitize(input: string, config?: Record<string, unknown>): string;
}

interface WindowGlobals {
  marked    ?: MarkedAPI;
  DOMPurify ?: DOMPurifyAPI;
}

// The multiplexer's DOMPurify config. Originally ported from legacy `notifications.js`; the two
// have since diverged, so read this object, not that file, for what the multiplexer allows.
//
// 🔴 NO `USE_PROFILES`, AND IT MUST STAY OUT (row 5ae3ce90). DOMPurify applies a profile AFTER
// `ALLOWED_TAGS` / `ALLOWED_ATTR` and resets both lists to the whole profile, so the explicit
// lists below were being ignored. Measured in Chromium 145 with the vendored DOMPurify 3.3.1: with
// `USE_PROFILES: { html: true }` a sender's <form>, <input>, <button>, <style>, style= and
// <details> all reached the bubble. Pinned in a real browser by
// src/tests/e2e_ui/test_the_bubble_sanitizer_keeps_only_its_allowlist.py, and by the config
// test in markdown.test.ts.
export const DOMPURIFY_CONFIG = {
  ALLOWED_TAGS : [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "strong", "em", "b", "i", "u", "s", "mark", "small", "del", "ins",
    "ul", "ol", "li",
    "blockquote", "pre", "code",
    "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "div", "span",
  ],
  ALLOWED_ATTR : [
    "href", "src", "alt", "title",
    "target", "rel",
    "class", "id",
    // marked writes a `|:-:|` column as align="…" on its th/td. Without this an aligned table renders unaligned.
    "align",
  ],
  // `mailto:` + standard web schemes; deny `javascript:` + data: by exclusion.
  ALLOWED_URI_REGEXP : /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.\-:]|$))/i,
  ADD_ATTR : [ "target", "rel" ],
  RETURN_DOM_FRAGMENT     : false,
  RETURN_TRUSTED_TYPE     : false,
};

function ensureGlobals(): { marked: MarkedAPI; DOMPurify: DOMPurifyAPI } {
  /* c8 ignore next */ // defensive: typeof window is "undefined" only in pre-DOM Node runtime; happy-dom's GlobalRegistrator (tests) AND every real browser provide window. The fallback to globalThis exists for non-browser contexts that don't apply to the multiplexer.
  const win = (typeof window !== "undefined" ? window : globalThis) as unknown as WindowGlobals;
  if (!win.marked || !win.DOMPurify) {
    throw new Error("multiplexer/render/markdown: window.marked + window.DOMPurify must be loaded before render");
  }
  return { marked: win.marked, DOMPurify: win.DOMPurify };
}

function postProcessAnchors(html: string): string {
  // Rewrite anchor target/rel — verbatim port from `notifications.js:12203-12247`.
  // Every `<a href="...">` gets `target="_blank" rel="noopener noreferrer"`.
  return html.replace(
    /<a\s+(?![^>]*\btarget=)([^>]*?)>/gi,
    '<a $1 target="_blank" rel="noopener noreferrer">',
  );
}

/**
 * Block-level markdown renderer — wraps content in `<p>` paragraphs.
 *
 * Suitable for full-paragraph notification bodies. Per D-J ratification, this
 * is the verbatim port from `notifications.js:12203-12247`.
 *
 * Returns a `RawValue` for direct use inside `html\`...\`` interpolations.
 */
export function renderMarkdown(text: string): Value {
  const { marked, DOMPurify } = ensureGlobals();
  const parsed = marked.parse(text, { breaks: true, gfm: true });
  const sanitized = DOMPurify.sanitize(parsed, DOMPURIFY_CONFIG);
  return raw(postProcessAnchors(sanitized));
}

/**
 * Inline markdown renderer — strips the wrapping `<p>` paragraph.
 *
 * Suitable for chat-bubble `.message-text` inside `.sender-message` where
 * `<p>`-wrapping is wrong (visible double-margin / break-out). Per D-J
 * ratification, ports from `notifications.js:12279-12305`.
 *
 * Returns a `RawValue` for direct use inside `html\`...\`` interpolations.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderMarkdownInline(text: string): Value {
  const { marked, DOMPurify } = ensureGlobals();
  const parsed = marked.parse(text, { breaks: true, gfm: true });
  const sanitized = DOMPurify.sanitize(parsed, DOMPURIFY_CONFIG);
  // Strip leading + trailing `<p>` … `</p>` wrap. Match legacy inline behavior:
  // single-paragraph inputs render flat; multi-paragraph inputs keep their
  // internal `<p>` boundaries.
  const stripped = sanitized
    .replace(/^\s*<p>([\s\S]*?)<\/p>\s*$/i, "$1");
  return raw(postProcessAnchors(stripped));
}
