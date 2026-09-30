/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Jobs pane — per-bucket open/closed persistence (parity row A-1c1, Phase 2 A12 B9c).
//
// 🔴 THE KEY AND ITS SHAPE ARE A PARITY CONTRACT SHARED VERBATIM WITH THE JS CARD
// (notifications.js `QUEUE_EXPAND_STATE_KEY`, `saveQueueExpandState`,
// `applyQueueExpandState`), so an operator moving between the two clients sees the
// same buckets open. Ruled by Mr. Radio 🦉 2026-09-16 over a new StorageService key.
// That contract is the ONLY licence this file has to bypass StorageService
// (`shared/StorageService.ts:2-5`), exactly as `taskListCollapse.ts` does:
//   - the localStorage key, underscores and all: `lupin_queue_expand_state`
//   - the shape: a JSON MAP of queue name -> isEXPANDED (true = open)
//   - legacy's QUEUE NAMES, which are not the multiplexer's bucket names: the
//     running bucket is stored as `run`. Writing `running` would be a key legacy
//     never reads, and the two clients would silently disagree.
//
// ⚠️ POLARITY, WRITTEN HERE RATHER THAN INFERRED FROM A NEIGHBOUR: this is a map of
// isEXPANDED, the same sense as `lupin.epicBoard.groupState` and the OPPOSITE of
// `lupin.taskList.collapsedOwners`, which stores COLLAPSED keys. Porting from the
// task-list module inverts every saved choice and fails invisibly.
//
// ⚠️ AND `StorageService.keys()` CANNOT SEE THIS KEY — it only lists `lupin:`-prefixed
// keys. A "clear all Lupin state" sweep built on keys() misses it, along with the
// three `lupin.` dot keys.
//
// An absent bucket means NO CHOICE, and the template's Q-A2 default applies. A save
// MERGES into what is stored rather than overwriting it, because legacy writes all
// five queues at once and a partial mux write must not erase legacy's other four.

import type { JobBucket } from "../shared/types";

/** localStorage key holding the JSON map of legacy queue name -> isEXPANDED. */
export const JOBS_BUCKET_EXPAND_KEY = "lupin_queue_expand_state";

/** The storage surface this module needs; `null` means "no persistence". */
export type BucketExpandStorage = Pick<Storage, "getItem" | "setItem">;

export type BucketExpandState = Partial<Record<JobBucket, boolean>>;

// Multiplexer bucket name -> legacy queue name. Only `running` differs.
const LEGACY_QUEUE_NAME: Record<JobBucket, string> = {
  todo    : "todo",
  running : "run",
  done    : "done",
  dead    : "dead",
  history : "history",
};

const BUCKETS = Object.keys( LEGACY_QUEUE_NAME ) as JobBucket[];

/** Read the raw stored map, or `{}` when absent, unparseable, or not a plain object. */
function readRaw( storage: BucketExpandStorage ): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse( storage.getItem( JOBS_BUCKET_EXPAND_KEY ) ?? "{}" );
    if ( parsed === null || typeof parsed !== "object" || Array.isArray( parsed ) ) return {};
    return parsed as Record<string, unknown>;
  } catch {
    return {};
  }
}

/**
 * Load the operator's saved per-bucket choices.
 *
 * Ensures:
 *   - returns only buckets whose stored value is a boolean, under MULTIPLEXER names
 *   - `null` storage, an absent key, or a corrupt payload -> `{}` (no choices), never a throw
 */
export function loadBucketExpandState( storage: BucketExpandStorage | null ): BucketExpandState {
  if ( storage === null ) return {};
  const raw   = readRaw( storage );
  const state : BucketExpandState = {};
  for ( const bucket of BUCKETS ) {
    const value = raw[ LEGACY_QUEUE_NAME[ bucket ] ];
    if ( typeof value === "boolean" ) state[ bucket ] = value;
  }
  return state;
}

/**
 * Persist one bucket's choice, merged into whatever is already stored.
 *
 * Ensures:
 *   - the stored map carries `bucket`'s LEGACY queue name -> `expanded`
 *   - every other stored entry is preserved, including ones this module does not know
 *   - `null` storage is a no-op; a storage that throws on write (quota, privacy mode)
 *     is swallowed — losing a collapse preference must never break the pane
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function saveBucketExpandChoice( storage: BucketExpandStorage | null, bucket: JobBucket, expanded: boolean ): void {
  if ( storage === null ) return;
  const raw = readRaw( storage );
  raw[ LEGACY_QUEUE_NAME[ bucket ] ] = expanded;
  try {
    storage.setItem( JOBS_BUCKET_EXPAND_KEY, JSON.stringify( raw ) );
  } catch {
    // a full or refused store leaves the in-memory choice intact for this session
  }
}
