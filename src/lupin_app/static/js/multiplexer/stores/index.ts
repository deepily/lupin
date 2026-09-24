/* c8 ignore start */
// Re-exports + factory barrel — coverage of this file is measured indirectly
// via the modules it constructs (NotificationStore.ts, SenderStore.ts,
// ActionRequiredStore.ts, AudioStore.ts, JobStore.ts), each of which has its
// own dedicated test suite at 100% per the global mandate. The createStores
// factory is exercised by integration tests at boot. Direct branch coverage
// of a barrel is meaningless. See project CLAUDE.md "100% COVERAGE MANDATE"
// for the c8-ignore exception clause.
// Multiplexer Phase 4 — stores barrel.
//
// `createStores(opts)` returns the canonical 6-store set. Boot.ts wires its
// resolved dependencies through this factory.
//
// Per Pass 1 F12 — CANONICAL SUBSCRIPTION ORDER PINNED:
//   notifications → senders → actionRequired → audio → jobs
// Order matters because EventBus listener invocation is registration-order
// (per the `EventTarget` contract). NotificationStore mutates first (canonical
// record of the notification arrival); SenderStore second (looks up sender +
// bumps last_active); ActionRequiredStore third (only fires for prompts with
// `response_requested === true`); AudioStore + JobStore last (no inter-store
// dependencies). Order is preserved by the construction sequence below + the
// integration test asserts deterministic microtask-boundary ordering.
//
// Per D-D ratification 2026-05-04 PM: `audioTransport` is NOT a parameter.
// AudioStore exposes `.binaryHandler` (named `audioStoreBinaryHandler` for
// AC9). boot.ts calls `transports.audio.start(sessionId, stores.audio.binaryHandler)`
// directly — the transport's existing `start(sessionId, binaryHandler?)`
// contract.

import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";

import type { NotificationStore } from "./NotificationStore";
import { createNotificationStore } from "./NotificationStore";
import type { JobStore } from "./JobStore";
import { createJobStore } from "./JobStore";
import type { SenderStore } from "./SenderStore";
import { createSenderStore } from "./SenderStore";
import type { ActionRequiredStore, ActionRequiredApiClient } from "./ActionRequiredStore";
import { createActionRequiredStore, isActionRequiredLive } from "./ActionRequiredStore";
import type { AudioStore, AudioStoreOptions } from "./AudioStore";
import { createAudioStore } from "./AudioStore";
import type { SessionStripStore } from "./SessionStripStore";
import { createSessionStripStore } from "./SessionStripStore";
import type { ReadingPaneStore } from "./ReadingPaneStore";
import { createReadingPaneStore } from "./ReadingPaneStore";
import type { CommonsStore } from "./CommonsStore";
import { createCommonsStore } from "./CommonsStore";
// Lane E full-parity quartet stores (2026-06-10).
import type { MissedStore } from "./MissedStore";
import { createMissedStore } from "./MissedStore";
import type { PredictionVoteStore } from "./PredictionVoteStore";
import { createPredictionVoteStore } from "./PredictionVoteStore";
import type { FleetStatusStore, FleetApiClient } from "./FleetStatusStore";
import { createFleetStatusStore } from "./FleetStatusStore";
import type { TaskListStore, TaskListApiClient } from "./TaskListStore";
import { createTaskListStore } from "./TaskListStore";
import type { HoldingAreaStore } from "./HoldingAreaStore";
import { createHoldingAreaStore } from "./HoldingAreaStore";
import type { FlowRatioStore, FlowRatioApiClient } from "./FlowRatioStore";
import { createFlowRatioStore } from "./FlowRatioStore";
import type { TaskRequestStore } from "./TaskRequestStore";
import { createTaskRequestStore } from "./TaskRequestStore";
import type { FinishedTasksStore } from "./FinishedTasksStore";
import { createFinishedTasksStore } from "./FinishedTasksStore";
import type { EpicStoriesStore } from "./EpicStoriesStore";
import { createEpicStoriesStore } from "./EpicStoriesStore";
import type { ViewStateStore } from "./ViewStateStore";
import { createViewStateStore } from "./ViewStateStore";
// Lane C (v0.1.9) — broadcast-to-all-CC compose store.
import type { BroadcastStore } from "./BroadcastStore";
import { createBroadcastStore } from "./BroadcastStore";
import type { AckStore } from "./AckStore";
import { createAckStore } from "./AckStore";
// F0 (00b, v0.1.9) — notification-level TTS queue + active-item identity store.
import type { TtsQueueStore } from "./TtsQueueStore";
import { createQaStore, type QaStore } from "./QaStore";
import { createSubmitJobsStore, type SubmitJobsStore, type SubmitJobsApiClient } from "./SubmitJobsStore";
import { createTtsQueueStore } from "./TtsQueueStore";

export interface StoreSet {
  notifications  : NotificationStore;
  senders        : SenderStore;
  actionRequired : ActionRequiredStore;
  audio          : AudioStore;
  jobs           : JobStore;
  // WP2 (parity bridge) — CC-session strip model. Constructed LAST so its
  // notification_queue_update listener registers after the canonical five,
  // preserving the pinned cross-store fanout order the integration test
  // asserts (sessionStrip emits its own store_session_strip_changed, which is
  // not in that watched set).
  sessionStrip   : SessionStripStore;
  // WP4 (2026-06-10) — ReadingPaneStore is action-driven (renderer gestures +
  // AR-store changes), NOT a server-frame subscriber, so it sits OUTSIDE the
  // pinned subscription-order chain below; construction order is irrelevant.
  readingPane    : ReadingPaneStore;
  // Lane D (WP3) — commons "Recent Activity" panel store. No inter-store
  // dependency (consumes notification_queue_update independently), so it
  // constructs last; subscription order of the pinned 5 is unaffected.
  commons        : CommonsStore;
  // Lane E quartet — Missed (auth_success surfacing), PredictionVote (vote
  // POST), FleetStatus (60s poll; boot starts polling AFTER mount).
  missed         : MissedStore;
  predictionVote : PredictionVoteStore;
  fleetStatus    : FleetStatusStore;
  taskList       : TaskListStore;
  // Row 87812328 — the holding-area pane's own poll. It is a SECOND query
  // (not_approved is invisible to the task list's), so unlike the epic board it
  // cannot ride the task list's composite; it takes its own 60s timer.
  holdingArea    : HoldingAreaStore;
  // Parity B-1 — the Q&A Interface's model. Action-driven (the pane's gestures) plus
  // one server frame (`tts_job_request`), so it sits outside the pinned
  // subscription-order chain and its construction order is irrelevant.
  qa             : QaStore;
  // Parity B-2 — the four submit cards' model. Action-driven only (no server frame),
  // so its construction order is irrelevant.
  submitJobs     : SubmitJobsStore;
  // Parity A-2 #8 — the Holding Area's flow-ratio gate: three endpoints of its own
  // (the ratio, its settings, the manager-pull toggle), on its own 60 s timer.
  flowRatio      : FlowRatioStore;
  taskRequests   : TaskRequestStore;
  // Row 470b7509 — the finished-tasks pane's own poll. A THIRD door:
  // /api/tasks/events, not /api/tasks, because no terminal-timestamp column
  // exists and /api/tasks therefore cannot answer "what finished today".
  finishedTasks  : FinishedTasksStore;
  // Row 87812328 — the epic board's hand-maintained titles/stories. NOT a poll:
  // a memoized one-shot against a hand-edited file, whose memo covers the
  // FAILURE case too so a down endpoint is not retried on every paint.
  epicStories    : EpicStoriesStore;
  // Section-toolbar + accordion-collapse parity (2026-06-23) — view-preference
  // state (section visibility + accordion collapse), persisted. Order-neutral
  // (subscribes to no server frames), so it appends after the pinned five.
  viewState      : ViewStateStore;
  // Lane C (v0.1.9) — broadcast-to-all-CC compose store. Order-neutral
  // (subscribes to no server frames); persists only its card-open flag.
  broadcast      : BroadcastStore;
  // Row 4f320c27 M1 — the per-broadcast acknowledgement tally.
  acks           : AckStore;
  // F0 (00b, v0.1.9) — notification-level TTS queue + active-item identity.
  // Order-neutral: subscribes to AUDIO-store emissions (store_audio_ended /
  // store_audio_state_change), NOT server frames, so it appends after the
  // pinned five. The active id it owns (current()) is the F0 seam Plan 01 B4 /
  // 02 / 03 / 05 consume; logic-level, no DOM surface of its own.
  ttsQueue       : TtsQueueStore;
}

export interface CreateStoresOptions {
  eventBus            : EventBus;
  storage             : StorageService;
  // post (ActionRequired / Missed / PredictionVote) + get (FleetStatus) +
  // get/patch/post (TaskList Phase-2 writes). The production ApiClient satisfies
  // all three structurally.
  api                 : ActionRequiredApiClient & FleetApiClient & TaskListApiClient & FlowRatioApiClient
                        & SubmitJobsApiClient;
  // Forward AudioStore options so boot.ts can pass production-side
  // `audioContextFactory`. Tests usually omit (default factory is browser-only).
  audioContextFactory?: AudioStoreOptions["audioContextFactory"];
  // Phase 2 — authenticated-user identity provider for TaskList edit audit
  // `actor` (Q1). Boot wires `() => authManager.getCurrentUserEmail()`; omitted
  // in read-only test constructions (the store defaults to anonymous).
  actorProvider?      : () => string | null;
  // Parity B-1 — the queue socket's session id, the `websocket_id` every v2 door is
  // handed. A thunk, not a string: see the construction site.
  qaSessionId?        : () => string;
  // Parity B-2 (B8) — called after a SUCCESSFUL Claude Code submit and after nothing
  // else. Legacy calls refreshAllQueues() from that card alone.
  onCcSubmitted?      : () => void;
}

/**
 * Construct the canonical 6-store set. Subscription order is pinned at
 * construction time — see file-header comment.
 *
 * Requires:
 *   - opts.eventBus is the production EventBus (or a test instance)
 *   - opts.storage is a configured StorageService
 *   - opts.api is an ApiClient (or stub satisfying ActionRequiredApiClient)
 *
 * Ensures:
 *   - Returns the 11-store set (the 5 server-frame subscribers in pinned order + sessionStrip/readingPane/commons + the Lane E quartet stores)
 *   - Each store's constructor is fully synchronous; the StoreSet is
 *     immediately usable on return
 */
export function createStores(opts: CreateStoresOptions): StoreSet {
  // ORDER MATTERS — see file header. Do not reorder without also updating
  // the integration test assertion.
  const notifications  = createNotificationStore({ bus: opts.eventBus, storage: opts.storage });
  const senders        = createSenderStore       ({ bus: opts.eventBus, storage: opts.storage });
  // A-2 #2f — the ⏸️ pauses TTS with the countdown. `audio` is constructed on the next line (the
  // order above is pinned), so these closures read it at call time, never at construction.
  // A-1c2 — the queue, pause and stepper survive a reload through the shared StorageService.
  // A-2 #2d — a prompt arriving while TTS plays waits for the current item. `ttsQueue` is built
  // last (it asks this store about a restored focus), so these closures read it at call time too;
  // the store never calls them while it is being constructed.
  const actionRequired = createActionRequiredStore({ bus: opts.eventBus, api: opts.api, storage: opts.storage, audioControl: {
    isPlaying : () => audio.state() === "playing",
    pause     : () => audio.pause(),
    resume    : () => audio.resume(),
  }, ttsSlot: {
    isPlaying : () => ttsQueue.isPlaying(),
    current   : () => ttsQueue.current(),
  } });
  const audio          = createAudioStore        ({
    bus                 : opts.eventBus,
    audioContextFactory : opts.audioContextFactory,
  });
  const jobs           = createJobStore          ({ bus: opts.eventBus });
  // WP2 — LAST (see StoreSet comment): registers after the canonical five so
  // the integration test's pinned fanout order is preserved.
  const sessionStrip   = createSessionStripStore  ({ bus: opts.eventBus });
  // ReadingPaneStore (WP4) — order-independent (no server-frame subscription);
  // hydrates persisted layout mode + split ratio from storage at construction.
  const readingPane    = createReadingPaneStore  ({ bus: opts.eventBus, storage: opts.storage });
  // Lane D (WP3) — commons store, also order-independent of the pinned five.
  const commons        = createCommonsStore      ({ bus: opts.eventBus, storage: opts.storage });

  // Lane E quartet — appended AFTER the canonical 5 (order-neutral: Missed
  // listens only to auth_success; PredictionVote + FleetStatus subscribe to no
  // server frames). FleetStatus does NOT start polling here — boot.ts kicks
  // startPolling() AFTER the renderer mounts (Cheech's rule).
  const missed         = createMissedStore        ({ bus: opts.eventBus, api: opts.api });
  const predictionVote = createPredictionVoteStore({ bus: opts.eventBus, api: opts.api });
  const fleetStatus    = createFleetStatusStore   ({ bus: opts.eventBus, api: opts.api });
  const taskList       = createTaskListStore      ({ bus: opts.eventBus, api: opts.api, actorProvider: opts.actorProvider });
  // ⚠️ actorProvider IS NOT OPTIONAL HERE ANY MORE, AND FORGETTING IT IS SILENT.
  // The holding area now WRITES (the batch verbs), and a store built without a
  // provider records every batch transition as "anonymous (multiplexer)" — a
  // full audit trail, correctly shaped, naming nobody. Nothing fails; the rows
  // just stop being attributable, which is the one property an audit trail is
  // for. Pinned by test_holding_area_store_is_built_with_the_operator.
  const holdingArea    = createHoldingAreaStore   ({ bus: opts.eventBus, api: opts.api, actorProvider: opts.actorProvider });
  const flowRatio      = createFlowRatioStore     ({ bus: opts.eventBus, api: opts.api });
  // Row c9fafb9d — managers' promote/demote requests: both boards' badges and Rick's
  // verdict. After a verdict lands, BOTH panes re-read, because an approval moved the row
  // from one to the other. BOTH take the after-write read: it waits out a poll already in
  // flight and then fetches, so neither pane repaints a row the verdict already moved.
  // ⚠️ NOT `taskList.refresh()`. That SKIPS a collision rather than joining it, so a verdict
  // landing mid-poll got no task-list read at all (Tiffany L1, measured 2026-09-10).
  const taskRequests   = createTaskRequestStore   ({ bus: opts.eventBus, api: opts.api,
    afterVerdict: async () => { await Promise.all( [ taskList.refreshAfterWrite(), holdingArea.refreshAfterWrite() ] ); } });
  const finishedTasks  = createFinishedTasksStore ({ bus: opts.eventBus, api: opts.api });
  const epicStories    = createEpicStoriesStore   ({ api: opts.api });
  // Section-toolbar + accordion-collapse parity — order-neutral; hydrates
  // persisted section-visibility + accordion-collapse maps at construction.
  const viewState      = createViewStateStore     ({ bus: opts.eventBus, storage: opts.storage });
  // Lane C (v0.1.9) — broadcast compose store; order-neutral (no server-frame
  // subscription), persists only card-open. Recipient auto-refresh rides the
  // existing store_session_strip_changed (handled in BroadcastCardRenderer).
  const broadcast      = createBroadcastStore     ({ storage: opts.storage });
  // Row 4f320c27 M1 — the ack tally fold. Its live subscription is NOT started
  // here: boot owns start/stop lifetimes, and a store that subscribed in its own
  // constructor could never be torn down by the caller that built it.
  const acks           = createAckStore           ({ bus: opts.eventBus });
  // F0 (00b) — TTS item-queue store. Order-neutral (subscribes to AudioStore
  // emissions, not server frames). Its active id (current()) is set by the
  // F0-d speak-initiation seam in boot.ts and rolled by its own self-advance.
  // A-1c3 — the queue survives a reload; a restored focus is kept only while its
  // prompt is still owed. actionRequired restored its prompts in its own
  // constructor above, so it can answer now — legacy's order too (notifications.js:596-599).
  const ttsQueue       = createTtsQueueStore      ({
    bus             : opts.eventBus,
    storage         : opts.storage,
    focusItemIsLive : ( idHash ) => {
      const prompt = actionRequired.getById( idHash );
      return prompt !== undefined && isActionRequiredLive( prompt );
    },
  });

  // Parity B-1 — the Q&A store. `sessionId` is read at CALL time because the queue
  // socket's id is resolved in boot before createStores but the contract is "whatever
  // the queue socket is bound to now", and a captured string cannot follow a rebind.
  const qa             = createQaStore({
    bus       : opts.eventBus,
    api       : opts.api,
    /* c8 ignore next */ // production-default fallback: boot always supplies qaSessionId; the empty string is the read-only test construction.
    sessionId : opts.qaSessionId ?? ( () => "" ),
    // Review finding (María 🌸 + Mr. Radio 🦉, 2026-09-23): a job's answer has to be
    // SPOKEN, not only written. It is ENQUEUED rather than played, so it takes its
    // turn behind any utterance already going out — see QaTtsEnqueuer's docstring
    // for why that is a deliberate divergence from legacy's immediacy.
    ttsQueue  : ttsQueue,
    // Legacy getVoiceIdForSender: the sender's own persona voice, or undefined,
    // which omits the key and lets the server speak in its default voice.
    voiceFor  : ( senderId ) => {
      if ( senderId === undefined ) return undefined;
      const voiceId = senders.get( senderId )?.voice_persona?.voice_id;
      return voiceId === undefined || voiceId === "" ? undefined : voiceId;
    },
  });

  // Parity B-2 — the submit cards. Same session-id thunk as the Q&A store: it is the
  // `websocket_id` in the body AND the `X-Session-ID` header on all four doors.
  const submitJobs     = createSubmitJobsStore({
    bus       : opts.eventBus,
    api       : opts.api,
    /* c8 ignore next */ // production-default fallback: boot always supplies qaSessionId.
    sessionId : opts.qaSessionId ?? ( () => "" ),
    ...( opts.onCcSubmitted === undefined ? {} : { onCcSubmitted: opts.onCcSubmitted } ),
  });

  return { notifications, senders, actionRequired, audio, jobs, sessionStrip, readingPane, commons, missed, predictionVote, fleetStatus, taskList, holdingArea, flowRatio, taskRequests, finishedTasks, epicStories, viewState, broadcast, acks, ttsQueue, qa, submitJobs };
}

// Re-exports so consumers can import everything from the barrel.
export type {
  NotificationStore,
  NotificationStoreOptions,
  NotificationHistoryApiClient,
  HydrateHistoryOptions,
} from "./NotificationStore";
export { createNotificationStore, DEFAULT_HISTORY_WINDOW_HOURS } from "./NotificationStore";
export type { JobStore, JobStoreOptions, JobHistoryApiClient } from "./JobStore";
export { createJobStore } from "./JobStore";
export type { SenderStore, SenderStoreOptions } from "./SenderStore";
export { createSenderStore } from "./SenderStore";
export type {
  ActionRequiredStore,
  ActionRequiredStoreOptions,
  ActionRequiredApiClient,
} from "./ActionRequiredStore";
export { createActionRequiredStore } from "./ActionRequiredStore";
export type { AudioStore, AudioStoreOptions, SchedulableAudioContext, TtsMode } from "./AudioStore";
export type { QaStore, QaStoreOptions, QaApiClient, QaMetrics, QaAgentsPayload, QaFlowResult } from "./QaStore";
export { createQaStore, QA_EMPTY_RESPONSE } from "./QaStore";
export type {
  SubmitJobsStore, SubmitJobsStoreOptions, SubmitJobsApiClient, CardKey,
  CardStatus, TfeCandidate, SchedulingInput,
} from "./SubmitJobsStore";
export { createSubmitJobsStore, FILE_DRIVEN_TEST_TYPES } from "./SubmitJobsStore";
export { createAudioStore } from "./AudioStore";
// WP2 (parity bridge) — SessionStripStore IS part of the canonical store set
// built by createStores() (folded at the boot-integration step per Lane A's
// mount-slot convention); re-exported here for direct consumers/tests too.
export type { SessionStripStore, SessionStripStoreOptions, ServerSenderHydrationRecord } from "./SessionStripStore";
export { createSessionStripStore } from "./SessionStripStore";
// WP4 (2026-06-10) — ReadingPaneStore IS part of the canonical store set built
// by createStores() (Tiberius uniform ruling 2026-06-10: one store registry, no
// boot-direct stragglers). Re-exported here for direct consumers/tests too.
export type { ReadingPaneStore, ReadingPaneStoreOptions } from "./ReadingPaneStore";
export { createReadingPaneStore } from "./ReadingPaneStore";
export type { CommonsStore, CommonsStoreOptions, CommonsHistoryApiClient } from "./CommonsStore";
export { createCommonsStore } from "./CommonsStore";
export type { MissedStore, MissedStoreOptions, MissedApiClient } from "./MissedStore";
export { createMissedStore } from "./MissedStore";
export type {
  PredictionVoteStore,
  PredictionVoteStoreOptions,
  PredictionVoteApiClient,
  PredictionVoteContext,
} from "./PredictionVoteStore";
export { createPredictionVoteStore } from "./PredictionVoteStore";
export type { FleetStatusStore, FleetStatusStoreOptions, FleetApiClient } from "./FleetStatusStore";
export { createFleetStatusStore } from "./FleetStatusStore";
export type { TaskListStore, TaskListStoreOptions, TaskListApiClient } from "./TaskListStore";
export { createTaskListStore } from "./TaskListStore";
export { createHoldingAreaStore } from "./HoldingAreaStore";
export { createFlowRatioStore } from "./FlowRatioStore";
export type { TaskRequestStore, TaskRequestStoreOptions, TaskRequestApiClient } from "./TaskRequestStore";
export { createTaskRequestStore } from "./TaskRequestStore";
export type { FinishedTasksStore, FinishedTasksStoreOptions, FinishedTasksApiClient } from "./FinishedTasksStore";
export { createFinishedTasksStore, FINISHED_TASKS_ENDPOINT } from "./FinishedTasksStore";
export { createEpicStoriesStore } from "./EpicStoriesStore";
export type { ViewStateStore, ViewStateStoreOptions } from "./ViewStateStore";
export { createViewStateStore } from "./ViewStateStore";
// Lane C (v0.1.9) — broadcast compose store.
export type { BroadcastStore, BroadcastStoreOptions, BroadcastRecipient,
              BroadcastSessionsApiClient } from "./BroadcastStore";
export { createBroadcastStore } from "./BroadcastStore";
// F0 (00b, v0.1.9) — TTS item-queue + active-id store.
export type { TtsQueueStore, TtsQueueStoreOptions } from "./TtsQueueStore";
export { createTtsQueueStore } from "./TtsQueueStore";
/* c8 ignore stop */
