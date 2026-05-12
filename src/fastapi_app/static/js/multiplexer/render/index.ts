/* c8 ignore start */
// Re-exports barrel — coverage of this file is measured indirectly via the
// modules it re-exports (NotificationsListRenderer.ts, html.ts, markdown.ts,
// time.ts, dom.ts), each of which has its own dedicated test suite at 100%
// per the global mandate. Direct coverage of a barrel file is meaningless —
// each export is exercised by the importing module's tests. See project
// CLAUDE.md "100% COVERAGE MANDATE" for the c8-ignore exception clause.
// Multiplexer Phase 5 — render module barrel.
//
// Per RE-12: factory shape mirrors Phase 4 `createStores` + Phase 3
// `createTransports`.

export {
  createNotificationsListRenderer,
  type NotificationsListRenderer,
  type NotificationsListRendererOptions,
  type NotificationsListRendererStores,
} from "./NotificationsListRenderer";
export {
  createJobsPaneRenderer,
  type JobsPaneRenderer,
  type JobsPaneRendererOptions,
  type JobsPaneRendererStores,
  type JobsPaneApiClient,
} from "./JobsPaneRenderer";
export {
  createActionRequiredRenderer,
  type ActionRequiredRenderer,
  type ActionRequiredRendererOptions,
  type ActionRequiredRendererStores,
  type ActionRequiredStoreLike,
} from "./ActionRequiredRenderer";
export {
  createTtsChromeRenderer,
  type TtsChromeRenderer,
  type TtsChromeRendererOptions,
  type TtsChromeRendererStores,
  type AudioStoreLike,
} from "./TtsChromeRenderer";
export { html, raw, type Value } from "./html";
export { renderMarkdown, renderMarkdownInline, DOMPURIFY_CONFIG } from "./markdown";
export { formatHM, formatDateKey, formatCountdown, formatDuration } from "./time";
export { keyedListMerge, replaceChildren, type KeyedEntry } from "./dom";
export { configureMetaDisplayCap } from "./templates/jobCard";
/* c8 ignore stop */
