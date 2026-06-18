/**
 * Composition root for the Lupin nav-bar standalone bundle.
 *
 * Binds the pure, fully-tested logic in `./lupinNav` to the real
 * `document` / `window` / `localStorage` and schedules the mount. This file
 * is the esbuild entry point (see `src/scripts/build-nav.sh`) and carries no
 * logic of its own — all behaviour lives in (and is unit-tested via)
 * `lupinNav.ts`.
 */
import { mountNav, scheduleMount } from "./lupinNav";

scheduleMount( document, () => mountNav( document, window, localStorage ) );
