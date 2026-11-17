/* c8 ignore next */ // tsx phantom-branch artifact, file header.
// One-click ticket approval in the multiplexer.
//
// A manager asking Rick to approve rows writes each as a bullet with an ordinary markdown link:
// `[approve ☐](/app/tasks/approve?row=<full uuid>) [📋](/app/tasks/view?row=<full uuid>)`.
// Both links are actions, not destinations. The approve click sends the approve move and draws "approved ✅"
// where the link was. The 📋 click reads the row and shows it the way the abstract 📋 shows text.
// A card drawn after a reload is checked once per row id: a row that has left the holding area
// shows "approved ✅" (or its plain status when it was dropped), not a live link.
//
// The sender is `HoldingAreaStore.transitionTask`, not `TaskListStore.transitionTask`.
// The task-list store edits its cached open list first. When the row is missing from that cache
// it resolves as done without sending anything, so the link would say "approved ✅" for a request
// never made. The holding-area sender always posts, never throws, and reports a refusal as a value.

// Row 009d2d53: the logic moved to shared/approve-link.js, which notifications.js reads through
// `window.LUPIN_APPROVE_LINK`. This file keeps the multiplexer's import path and the types.
import type { HoldingAreaStore } from "../stores/HoldingAreaStore";

/* c8 ignore start */ // pure re-exports with no logic of their own: tsx adds an empty never-run range here; the code they name is measured in shared/approve-link.js.
export {
  APPROVE_LINK_PREFIX, PRIORITY_LINK_PARAM, VIEW_LINK_PREFIX, BATCH_APPROVE_PREFIX, BATCH_VIEW_PREFIX, APPROVED_TEXT,
  approveRowId, approvePriorityLink, viewRowId, parseBatchIds, batchLinkOf, batchViewIds, taskOverlayText, taskReaderFor,
  markApproveLinks, observeApproveLinks, applyBatch,
  handleApproveLinkClick, handleApprovePriorityLinkClick, handleViewLinkClick, handleBatchApproveLinkClick, handleBatchViewLinkClick,
} from "../../shared/approve-link.js";
export type { AbstractShower, ApproveLinkRow, BatchLink, PriorityLink, TaskReader } from "../../shared/approve-link.js";
/* c8 ignore stop */

/** The one call the click handlers need, taken from the holding-area store. */
export type ApproveSender = Pick<HoldingAreaStore, "transitionTask">;
