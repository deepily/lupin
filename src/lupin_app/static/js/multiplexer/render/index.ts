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
  createNotificationsHeaderRenderer,
  type NotificationsHeaderRenderer,
  type NotificationsHeaderRendererOptions,
} from "./NotificationsHeaderRenderer";
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
export {
  createConversationModePinRenderer,
  type ConversationModePinRenderer,
  type ConversationModePinRendererOptions,
} from "./ConversationModePinRenderer";
export {
  createPersonaModalRenderer,
  type PersonaModalRenderer,
  type PersonaModalRendererOptions,
} from "./PersonaModalRenderer";
export {
  createSenderCardRecorderRenderer,
  type SenderCardRecorderRenderer,
  type SenderCardRecorderRendererOptions,
} from "./SenderCardRecorderRenderer";
export {
  createSessionStripRenderer,
  type SessionStripRenderer,
  type SessionStripRendererOptions,
} from "./SessionStripRenderer";
export {
  renderSessionStripIcon,
  updateSessionStripIcon,
  applyManagerBadge,
  personaInitial,
} from "./templates/sessionStripIcon";
export {
  createReadingPaneRenderer,
  type ReadingPaneRenderer,
  type ReadingPaneRendererOptions,
  type ReadingPaneStoreLike,
  type ActionRequiredCountLike,
  type WindowLike,
  type WindowDocLike,
} from "./ReadingPaneRenderer";
export {
  createCommonsActivityRenderer,
  type CommonsActivityRenderer,
  type CommonsActivityRendererOptions,
  type CommonsActivityRendererStores,
  type CommonsActivityApiClient,
} from "./CommonsActivityRenderer";
// Lane E full-parity quartet renderers (2026-06-10).
export {
  createTtsPreviewSliderRenderer,
  type TtsPreviewSliderRenderer,
  type TtsPreviewSliderRendererOptions,
} from "./TtsPreviewSliderRenderer";
export {
  createMissedBadgeRenderer,
  type MissedBadgeRenderer,
  type MissedBadgeRendererOptions,
  type MissedStoreLike,
} from "./MissedBadgeRenderer";
// Lane L4 (v0.1.9) — top nav / logout bar (PORT of lupin-nav.js).
export {
  createNavBarRenderer,
  type NavBarRenderer,
  type NavBarRendererOptions,
  type NavAuthPort,
} from "./NavBarRenderer";
export {
  createFleetStatusRenderer,
  type FleetStatusRenderer,
  type FleetStatusRendererOptions,
  type FleetStoreLike,
} from "./FleetStatusRenderer";
export {
  createTaskListRenderer,
  type TaskListRenderer,
  type TaskListRendererOptions,
  type TaskListStoreLike,
} from "./TaskListRenderer";
// Row 87812328 — the two panes carbon-copied from the legacy client. The
// holding area takes its own poll; the epic board deliberately takes none and
// repaints off the task list's store event.
export {
  createHoldingAreaRenderer,
  HOLDING_AREA_SENTINELS,
  HOLDING_AREA_EMPTY_MESSAGE,
  HOLDING_AREA_COUNT_UNKNOWN,
  type HoldingAreaRenderer,
  type HoldingAreaRendererOptions,
  type HoldingAreaStoreLike,
} from "./HoldingAreaRenderer";
export {
  createEpicBoardRenderer,
  EPIC_BOARD_SIGNIN_MESSAGE,
  EPIC_BOARD_QUERY_UNAVAILABLE_MESSAGE,
  EPIC_BOARD_UNREACHABLE_MESSAGE,
  type EpicBoardRenderer,
  type EpicBoardRendererOptions,
  type EpicBoardTaskStoreLike,
} from "./EpicBoardRenderer";
// Section-toolbar + accordion-collapse parity (2026-06-23).
export {
  createSectionToolbarRenderer,
  type SectionToolbarRenderer,
  type SectionToolbarRendererOptions,
  type SectionToolbarRendererStores,
  type ViewStateStoreLike,
} from "./SectionToolbarRenderer";
// Lane C (v0.1.9) — broadcast-to-all-CC compose card renderer.
export {
  createBroadcastCardRenderer,
  type BroadcastCardRenderer,
  type BroadcastCardRendererOptions,
  type BroadcastCardApiClient,
  type BroadcastRecorderLike,
} from "./BroadcastCardRenderer";
export { html, raw, type Value } from "./html";
export { renderMarkdown, renderMarkdownInline, DOMPURIFY_CONFIG } from "./markdown";
export { formatHM, formatDateKey, formatCountdown, formatDuration } from "./time";
export { keyedListMerge, replaceChildren, type KeyedEntry } from "./dom";
export { configureMetaDisplayCap } from "./templates/jobCard";
/* c8 ignore stop */
