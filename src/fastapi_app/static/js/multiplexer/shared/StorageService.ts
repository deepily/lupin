/* c8 ignore next */
// Multiplexer Phase 2 — StorageService. Typed JSON wrapper around localStorage
// with `lupin:` key prefix, schema versioning, corrupt-payload recovery, and
// first-class session-ID accessors (DC2 resolution: StorageService owns ALL
// storage; no raw localStorage elsewhere in the multiplexer tree).

import { eventBus, createEventBusForTesting } from "./EventBus";
import type { EventBus } from "./EventBus";
import type {
  LupinEvent,
  SessionIdEnvelope,
  StorageCorruptPayload,
  StorageEnvelope,
} from "./types";

const KEY_PREFIX        = "lupin:";
const SESSION_ID_KEY    = "session_id";
const SESSION_ID_SCHEMA = 1;

// Minimal Storage shape for dependency injection. `localStorage` satisfies
// this in browser; tests provide an in-memory implementation.
export interface StorageBackend {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  key(index: number): string | null;
  readonly length: number;
}

export interface StorageService {
  getJSON<T>(key: string, expectedSchemaVersion: number): T | null;
  setJSON<T>(key: string, value: T, schemaVersion: number): void;
  remove(key: string): void;
  keys(prefix?: string): string[];

  getSessionId(): string | null;
  setSessionId(sessionId: string): void;
}

class StorageServiceImpl implements StorageService {
  constructor(
    private readonly bus: EventBus,
    private readonly backend: StorageBackend,
  ) {}

  getJSON<T>(key: string, expectedSchemaVersion: number): T | null {
    const fullKey = KEY_PREFIX + key;
    const raw = this.backend.getItem(fullKey);
    if (raw === null) return null;

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      /* c8 ignore next */ // defensive: JSON.parse only throws SyntaxError per ECMA-262 §24.5.1.1; the `instanceof Error` check is always true in practice. The `: String(err)` arm is unreachable from any standards-compliant runtime. Belt-and-suspenders for exotic engines.
      this.emitCorrupt(fullKey, err instanceof Error ? err.message : String(err));
      return null;
    }

    if (!isEnvelope(parsed)) {
      this.emitCorrupt(fullKey, "malformed envelope (missing schemaVersion/payload/ts)");
      return null;
    }

    if (parsed.schemaVersion !== expectedSchemaVersion) {
      this.emitCorrupt(
        fullKey,
        `schema version mismatch (got ${parsed.schemaVersion}, expected ${expectedSchemaVersion})`,
      );
      return null;
    }

    return parsed.payload as T;
  }

  setJSON<T>(key: string, value: T, schemaVersion: number): void {
    const envelope: StorageEnvelope<T> = {
      schemaVersion,
      payload : value,
      ts      : Date.now(),
    };
    this.backend.setItem(KEY_PREFIX + key, JSON.stringify(envelope));
  }

  remove(key: string): void {
    this.backend.removeItem(KEY_PREFIX + key);
  }

  keys(prefix?: string): string[] {
    const out: string[] = [];
    const filter = prefix ?? "";
    for (let i = 0; i < this.backend.length; i++) {
      const k = this.backend.key(i);
      if (k === null) continue;
      if (!k.startsWith(KEY_PREFIX)) continue;
      const stripped = k.slice(KEY_PREFIX.length);
      if (filter && !stripped.startsWith(filter)) continue;
      out.push(stripped);
    }
    return out;
  }

  getSessionId(): string | null {
    const env = this.getJSON<SessionIdEnvelope>(SESSION_ID_KEY, SESSION_ID_SCHEMA);
    return env ? env.sessionId : null;
  }

  setSessionId(sessionId: string): void {
    const env: SessionIdEnvelope = { sessionId, generatedAt: Date.now() };
    this.setJSON<SessionIdEnvelope>(SESSION_ID_KEY, env, SESSION_ID_SCHEMA);
  }

  // Synchronous emission per Phase 1 finding #7: storage_corrupt fires in the
  // same microtask as the null return, so observers see corruption + null
  // without an interleaving race window.
  private emitCorrupt(key: string, error: string): void {
    const event: LupinEvent<StorageCorruptPayload> = {
      type    : "storage_corrupt",
      payload : { key, error },
      source  : "StorageService",
      ts      : Date.now(),
    };
    this.bus.emit(event);
  }
}

function isEnvelope(v: unknown): v is StorageEnvelope<unknown> {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o["schemaVersion"] === "number" &&
    "payload" in o &&
    typeof o["ts"] === "number"
  );
}

// Production singleton. Browsers expose `localStorage` on `window`; the
// `dom` lib in tsconfig types it.
export const storage: StorageService = new StorageServiceImpl(
  eventBus,
  globalThis.localStorage,
);

// Test-only factory. Pass a custom EventBus + backend for isolation.
export function createStorageServiceForTesting(
  bus: EventBus = createEventBusForTesting(),
  backend?: StorageBackend,
): StorageService {
  const fallback: StorageBackend = backend ?? new InMemoryStorage();
  return new StorageServiceImpl(bus, fallback);
}

// Test-only in-memory backend. Mirrors the parts of the Web Storage API the
// service uses; tests can also pass any other backend that matches the shape.
export class InMemoryStorage implements StorageBackend {
  private readonly store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }
  getItem(key: string): string | null {
    /* c8 ignore next */ // defensive: setItem(key, value) only stores string values, and Map.get(k) for a present key returns the stored value (string); the `?? null` fallback is unreachable from this class's API surface. Belt-and-suspenders for any future extension that might allow undefined values.
    return this.store.has(key) ? (this.store.get(key) ?? null) : null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  key(index: number): string | null {
    if (index < 0 || index >= this.store.size) return null;
    let i = 0;
    for (const k of this.store.keys()) {
      if (i === index) return k;
      i++;
    }
    /* c8 ignore next */ // defensive: the early bounds check above ensures index is in [0, size); the for-of loop iterates exactly `size` keys, so the `i === index` match always fires before the loop exits. The trailing `return null` is unreachable unless the Map mutates mid-iteration (which the contract forbids).
    return null;
  }
  /* c8 ignore next */ // tsx phantom-branch artifact on class closing-brace line (synthetic default-constructor branch).
}
