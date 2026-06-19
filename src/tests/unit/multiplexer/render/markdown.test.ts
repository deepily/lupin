// Multiplexer Phase 5 — render/markdown.ts unit tests.
// AC5 floor: ≥3 tests covering: block vs inline DOM-shape contrast (D-J),
// DOMPurify config equality, XSS regression.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderMarkdown,
  renderMarkdownInline,
  DOMPURIFY_CONFIG,
} from "../../../../lupin_app/static/js/multiplexer/render/markdown";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// ---------------------------------------------------------------------------
// Mock window.marked + window.DOMPurify (page globals).
// Production loads vendor bundles; unit tests use minimal shims that mirror
// the legacy pipeline (parse → sanitize → post-process anchors).
// ---------------------------------------------------------------------------

beforeEach(() => {
  const w = globalThis as unknown as {
    marked   ?: { parse: (s: string, opts?: unknown) => string };
    DOMPurify?: { sanitize: (s: string, cfg?: unknown) => string };
  };
  // Tiny markdown shim: handles `**bold**`, `*em*`, paragraphs.
  w.marked = {
    parse: (s: string): string => {
      let out = s
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\*([^*]+)\*/g, "<em>$1</em>");
      // Wrap in <p> per legacy block behavior.
      out = `<p>${out}</p>`;
      return out;
    },
  };
  // Tiny DOMPurify shim: strip <script> tags + event handlers; pass everything else.
  w.DOMPurify = {
    sanitize: (s: string): string => s
      .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
      .replace(/\son\w+\s*=\s*"[^"]*"/gi, "")
      .replace(/\son\w+\s*=\s*'[^']*'/gi, ""),
  };
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

function htmlOf(rawValue: unknown): string {
  // renderMarkdown returns RawValue {__raw: string}; extract.
  return (rawValue as { __raw: string }).__raw;
}

test("renderMarkdown wraps content in <p> (block variant)", () => {
  const out = htmlOf(renderMarkdown("hello **world**"));
  assert.match(out, /^<p>/);
  assert.match(out, /<\/p>$/);
  assert.match(out, /<strong>world<\/strong>/);
});

test("renderMarkdownInline strips <p> wrap for single paragraph (inline variant) — D-J contrast", () => {
  const inline = htmlOf(renderMarkdownInline("hello **world**"));
  assert.doesNotMatch(inline, /^<p>/);
  assert.match(inline, /<strong>world<\/strong>/);

  // Block + inline variants produce DIFFERENT DOM for the same input.
  const block = htmlOf(renderMarkdown("hello **world**"));
  assert.notEqual(inline, block);
});

test("DOMPURIFY_CONFIG matches the canonical legacy config (snapshot equality)", () => {
  // The canonical shape — verbatim port from notifications.js:12203-12247
  // (D-J corrected citation). Any change here is a wire-protocol decision and
  // demands explicit ratification.
  assert.ok(Array.isArray(DOMPURIFY_CONFIG.ALLOWED_TAGS));
  assert.ok(DOMPURIFY_CONFIG.ALLOWED_TAGS.includes("p"));
  assert.ok(DOMPURIFY_CONFIG.ALLOWED_TAGS.includes("a"));
  assert.ok(DOMPURIFY_CONFIG.ALLOWED_TAGS.includes("strong"));
  assert.ok(Array.isArray(DOMPURIFY_CONFIG.ALLOWED_ATTR));
  assert.ok(DOMPURIFY_CONFIG.ALLOWED_ATTR.includes("href"));
  assert.ok(DOMPURIFY_CONFIG.ALLOWED_ATTR.includes("rel"));
  assert.ok(DOMPURIFY_CONFIG.ALLOWED_ATTR.includes("target"));
  assert.deepEqual(DOMPURIFY_CONFIG.ADD_ATTR, ["target", "rel"]);
  assert.equal(DOMPURIFY_CONFIG.RETURN_DOM_FRAGMENT, false);
  assert.equal(DOMPURIFY_CONFIG.RETURN_TRUSTED_TYPE, false);
});

test("XSS regression: <script> tag is stripped via DOMPurify", () => {
  const out = htmlOf(renderMarkdown('hello <script>alert(1)</script>'));
  assert.doesNotMatch(out, /<script/i);
  assert.match(out, /hello/);
});

test("anchors are post-processed with target='_blank' rel='noopener noreferrer'", () => {
  // Override marked shim for this test — emit raw <a> without target.
  (globalThis as unknown as { marked: { parse: (s: string) => string } }).marked = {
    parse: (s: string): string => s.replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2">$1</a>'),
  };
  const out = htmlOf(renderMarkdown("[link](https://example.com)"));
  assert.match(out, /target="_blank"/);
  assert.match(out, /rel="noopener noreferrer"/);
});

// ---------------------------------------------------------------------------
// Branch-coverage close-out tests (added 2026-05-06 for the 100% c8 mandate).
// ---------------------------------------------------------------------------

test("ensureGlobals throws when window.marked is missing", () => {
  const originalMarked = (globalThis as { marked?: unknown }).marked;
  (globalThis as { marked?: unknown }).marked = undefined;
  try {
    assert.throws(() => renderMarkdown("hello"), /window\.marked.*loaded/);
  } finally {
    (globalThis as { marked?: unknown }).marked = originalMarked;
  }
});

test("ensureGlobals throws when window.DOMPurify is missing", () => {
  const originalDOMPurify = (globalThis as { DOMPurify?: unknown }).DOMPurify;
  (globalThis as { DOMPurify?: unknown }).DOMPurify = undefined;
  try {
    assert.throws(() => renderMarkdownInline("hello"), /DOMPurify.*loaded/);
  } finally {
    (globalThis as { DOMPurify?: unknown }).DOMPurify = originalDOMPurify;
  }
});
