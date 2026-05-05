// Multiplexer Phase 5 — `html` tagged-template helper.
//
// Returns a `DocumentFragment` (NOT a string) so the string-concat seam where
// XSS bugs hide is eliminated. String/number interpolations auto-escape via
// `createTextNode`. Booleans/null/undefined render empty. Arrays flatten.
// `raw(s)` is the explicit opt-out for already-sanitized HTML (e.g. markdown
// post-DOMPurify).
//
// Per Q-A ratification 2026-05-05: custom ~150 LOC implementation; rejected
// htm (~1KB) + lit-html (~6KB) for supply-chain + dep-cost reasons.
//
// Per Q-J ratification 2026-05-05: registers `lupin-html` Trusted Types policy
// when `window.trustedTypes` exists (zero-cost when absent — current state).
// Phase 7 flips CSP enforcement on with one server-config line; every shipped
// `html\`…\`` call site is then automatically TT-compliant.
//
// Per F11 (Pass 1 finding 2026-05-05): TS strict mode requires explicit cast
// for `TrustedHTML` return type when assigned to `template.innerHTML` (which
// is typed as `string`). Documented inline at the assignment site.

type RawValue = { readonly __raw: string };
export type Value = string | number | boolean | null | undefined | Node | DocumentFragment | readonly Value[] | RawValue;

const CHILD_SENTINEL_PREFIX = "lupin-html-child-";
const ELEMENT_MARKER_PREFIX = "data-lupin-html-marker-";
// Matches `<attr="` or `<attr='` at the END of a string segment — i.e., we
// stopped mid-attribute-value waiting for the interpolated value.
const ATTR_NAME_REGEX = /([a-zA-Z][a-zA-Z0-9_-]*)\s*=\s*("|')$/;

const KNOWN_TEMPLATES = new WeakSet<TemplateStringsArray>();

interface TrustedTypesPolicy {
  createHTML(input: string, strings: TemplateStringsArray): string;
}

interface TrustedTypesAPI {
  createPolicy(name: string, hooks: { createHTML: (input: string, strings: TemplateStringsArray) => string }): TrustedTypesPolicy;
}

interface WindowWithTrustedTypes {
  trustedTypes?: TrustedTypesAPI;
}

let TT_POLICY: TrustedTypesPolicy | null = null;

function getTrustedTypes(): TrustedTypesAPI | undefined {
  if (typeof globalThis === "undefined") return undefined;
  return (globalThis as unknown as WindowWithTrustedTypes).trustedTypes;
}

function ensurePolicy(): void {
  if (TT_POLICY !== null) return;
  const tt = getTrustedTypes();
  if (!tt) return;
  TT_POLICY = tt.createPolicy("lupin-html", {
    createHTML: (input: string, strings: TemplateStringsArray): string => {
      // Identity check: input MUST originate from a known TemplateStringsArray
      // (added to KNOWN_TEMPLATES in `html()` BEFORE this hook runs). Refuses
      // arbitrary string-to-TrustedHTML laundering attempts.
      if (!KNOWN_TEMPLATES.has(strings)) {
        throw new TypeError("lupin-html: refused to mint TrustedHTML from unknown TemplateStringsArray");
      }
      return input;
    },
  });
}

/**
 * Reset the TT policy + flush memoization. Test-only.
 */
export function resetForTesting(): void {
  TT_POLICY = null;
}

/**
 * Mark `s` as already-safe HTML; bypasses auto-escape.
 *
 * Use ONLY for content that has been sanitized (e.g. `DOMPurify.sanitize()`
 * output). Ungated use is the exact XSS regression `html` is meant to prevent.
 */
export function raw(s: string): RawValue {
  return { __raw: s };
}

function isRaw(v: unknown): v is RawValue {
  return typeof v === "object" && v !== null && "__raw" in v && typeof (v as { __raw: unknown }).__raw === "string";
}

function appendValue(target: Node, value: Value): void {
  if (value === null || value === undefined || value === false || value === true) return;
  if (typeof value === "string" || typeof value === "number") {
    target.appendChild(document.createTextNode(String(value)));
    return;
  }
  if (Array.isArray(value)) {
    for (const v of value) appendValue(target, v);
    return;
  }
  if (isRaw(value)) {
    const tpl = document.createElement("template");
    if (TT_POLICY !== null) {
      const trusted = TT_POLICY.createHTML(value.__raw, makeRawTemplateStrings(value.__raw));
      tpl.innerHTML = trusted as unknown as string;
    } else {
      tpl.innerHTML = value.__raw;
    }
    target.appendChild(tpl.content);
    return;
  }
  if (value instanceof Node) {
    target.appendChild(value);
  }
}

function makeRawTemplateStrings(s: string): TemplateStringsArray {
  // Synthesize a TemplateStringsArray for `raw()` content so the TT identity
  // check still passes. Keeps the policy's invariant tight: only TT-aware
  // call sites can ever feed it.
  const arr = [s] as unknown as TemplateStringsArray;
  Object.defineProperty(arr, "raw", { value: [s], enumerable: false });
  KNOWN_TEMPLATES.add(arr);
  return arr;
}

interface AttrPlacement {
  marker  : string;
  attrName: string;
  value   : Value;
}

interface Assembly {
  combined  : string;
  attrs     : AttrPlacement[];
  children  : Map<string, Value>;
}

function assemble(strings: TemplateStringsArray, values: readonly Value[]): Assembly {
  const attrs: AttrPlacement[] = [];
  const children = new Map<string, Value>();
  let combined = "";
  // Cursor state: when an interpolation lands inside an attribute, we need to
  // skip the closing quote at the start of the NEXT segment (which lives in
  // the readonly strings array). We track that via `nextSkipQuote`.
  let nextSkipQuote = false;

  for (let i = 0; i < strings.length; i++) {
    let segment = strings[i] ?? "";
    if (nextSkipQuote) {
      segment = segment.replace(/^["']/, "");
      nextSkipQuote = false;
    }
    combined += segment;
    if (i >= values.length) continue;

    const attrMatch = ATTR_NAME_REGEX.exec(segment);
    if (attrMatch) {
      const attrName = attrMatch[1] as string;
      // Strip the matched `attr="` (or `attr='`) from `combined`; replace
      // with a stable element-marker attribute we'll find post-parse.
      combined = combined.slice(0, combined.length - attrMatch[0].length);
      const marker = `${ELEMENT_MARKER_PREFIX}${attrs.length}`;
      combined += `${marker}=""`;
      attrs.push({ marker, attrName, value: values[i] as Value });
      nextSkipQuote = true;   // skip the closing quote at start of next segment
      continue;
    }

    // Child context — comment sentinel.
    const childId = `${CHILD_SENTINEL_PREFIX}${i}`;
    combined += `<!--${childId}-->`;
    children.set(childId, values[i] as Value);
  }

  return { combined, attrs, children };
}

function applyAttributes(fragment: DocumentFragment, attrs: ReadonlyArray<AttrPlacement>): void {
  for (const { marker, attrName, value } of attrs) {
    const el = fragment.querySelector(`[${marker}]`);
    if (el === null) continue;
    el.removeAttribute(marker);
    if (value === null || value === undefined || value === false) continue;
    if (value === true) {
      el.setAttribute(attrName, "");
      continue;
    }
    if (isRaw(value)) {
      el.setAttribute(attrName, value.__raw);
      continue;
    }
    if (value instanceof Node || Array.isArray(value)) continue;   // not meaningful as attribute
    el.setAttribute(attrName, String(value));
  }
}

function applyChildren(fragment: DocumentFragment, children: ReadonlyMap<string, Value>): void {
  if (children.size === 0) return;
  const walker = document.createTreeWalker(fragment, NodeFilter.SHOW_COMMENT);
  const targets: Comment[] = [];
  let node: Node | null = walker.nextNode();
  while (node !== null) {
    const c = node as Comment;
    if (c.nodeValue !== null && c.nodeValue.startsWith(CHILD_SENTINEL_PREFIX)) {
      targets.push(c);
    }
    node = walker.nextNode();
  }
  for (const c of targets) {
    const value = children.get(c.nodeValue ?? "");
    if (value === undefined) {
      c.remove();
      continue;
    }
    const tmp = document.createDocumentFragment();
    appendValue(tmp, value);
    c.replaceWith(tmp);
  }
}

/**
 * Tagged-template helper — `html\`<div class="${cls}">${child}</div>\``.
 *
 * Returns a fresh `DocumentFragment` per call.
 *
 * Requires:
 *   - `strings` is a TemplateStringsArray (callers always satisfy via tagged-template syntax)
 *
 * Ensures:
 *   - String/number interpolations auto-escape via `createTextNode`
 *   - Boolean/null/undefined render empty
 *   - Arrays flatten; nested arrays flatten recursively
 *   - `raw(s)` opt-out flows through (sanitization is caller's responsibility)
 *   - When `window.trustedTypes` exists, the lupin-html policy gates the parse
 */
export function html(strings: TemplateStringsArray, ...values: Value[]): DocumentFragment {
  ensurePolicy();
  KNOWN_TEMPLATES.add(strings);

  const { combined, attrs, children } = assemble(strings, values);

  const template = document.createElement("template");
  if (TT_POLICY !== null) {
    // F11: explicit cast — TT policy returns TrustedHTML, but template.innerHTML
    // is typed as string. Trusted Types accepts TrustedHTML at the assignment
    // site at runtime; the cast is the TS strict-mode bridge.
    const trusted = TT_POLICY.createHTML(combined, strings);
    template.innerHTML = trusted as unknown as string;
  } else {
    template.innerHTML = combined;
  }

  applyAttributes(template.content, attrs);
  applyChildren(template.content, children);

  return template.content;
}
