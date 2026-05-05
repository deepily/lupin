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
export { html, raw, type Value } from "./html";
export { renderMarkdown, renderMarkdownInline, DOMPURIFY_CONFIG } from "./markdown";
export { formatHM, formatDateKey, formatCountdown } from "./time";
export { keyedListMerge, replaceChildren, type KeyedEntry } from "./dom";
