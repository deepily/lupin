// Jobs page boot entry — `/app/jobs` (row efe188bf).
//
// The esbuild entry for the standalone jobs bundle (src/scripts/build-jobs.sh). It only binds the
// real browser globals — the shared EventBus and StorageService singletons, the production
// AuthManager and ApiClient — and hands them to bootJobsPage, where every decision lives and is
// unit-tested. Like every other `boot.ts`, this file is an entry point that executes page bootstrap
// on import, so the coverage gate excludes it.

import { eventBus } from "../shared/EventBus";
import { storage } from "../shared/StorageService";
import { createAuthManager } from "../auth/AuthManager";
import { createApiClient } from "../api/ApiClient";
import { bootJobsPage } from "./jobsPage";

const result = bootJobsPage( {
  doc      : document,
  location : window.location,
  storage,
  bus      : eventBus,
  connect  : () => createApiClient( {
    baseUrl          : window.location.origin,
    defaultTimeoutMs : 10_000,
    authManager      : createAuthManager( {
      refreshUrl       : "/auth/refresh",
      defaultTimeoutMs : 10_000,
      storage,
      bus              : eventBus,
    } ),
  } ),
} );

console.log( "[jobs] boot", result.status );
