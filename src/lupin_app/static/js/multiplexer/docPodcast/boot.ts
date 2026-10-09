/**
 * Composition root for the doc viewer's "Make a podcast" bundle.
 *
 * Binds the logic in `./docPodcast` to the real `window` and `document`. This file is the esbuild entry
 * (see `src/scripts/build-doc-podcast.sh`) and carries no logic of its own; everything is tested through
 * `docPodcast.ts`.
 */
import { bindDocPodcast } from "./docPodcast";
import type { DocWindowLike } from "./docPodcast";

bindDocPodcast( window as unknown as DocWindowLike, document );
