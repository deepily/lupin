/**
 * Composition root for the doc viewer page: podcast button and relative-link rewrite.
 *
 * Binds the logic in `./docPodcast` to the real `window` and `document`. This file is the esbuild entry
 * (see `src/scripts/build-doc-podcast.sh`) and carries no logic of its own; everything is tested through
 * `docPodcast.ts`.
 */
import { bindDocPodcast } from "./docPodcast";
import type { DocWindowLike } from "./docPodcast";
import { bindDocRelativeLinks } from "./docLinks";
import type { DocLinksWindowLike } from "./docLinks";

bindDocPodcast( window as unknown as DocWindowLike, document );
bindDocRelativeLinks( window as unknown as DocLinksWindowLike, document );
