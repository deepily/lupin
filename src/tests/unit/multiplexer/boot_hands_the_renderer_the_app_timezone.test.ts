// Row 0e5bfa0e — boot must hand the notifications renderer the app timezone when
// /api/config/client answers.
//
// ⚠️ WHAT THIS TEST IS, stated plainly: a SOURCE PIN, the same kind as
// boot_wires_the_jobs_pane_to_the_shared_mine_switch. boot.ts runs bootMultiplexer()
// at import and exports nothing, so the wiring cannot be driven from node. It reads
// the file and asserts the call is there. It cannot prove the handover works.
//
// WHAT PROVES THE BEHAVIOUR: notifications_list_app_timezone.test.ts, which drives the
// real renderer, hands it a zone AFTER the first paint, and asserts the RENDERED TEXT
// moves — including the three cache drops without which the zone is adopted and nothing
// on screen changes. Read that file for the mechanism; this one only pins that boot
// actually calls it.
//
// WHY A PIN IS WORTH HAVING ANYWAY: the option was always optional and boot never
// passed it, for the entire life of the multiplexer. No renderer test can see a boot
// that forgets. That is the exact defect this row was filed for.
//
// Run: npx tsx --test src/tests/unit/multiplexer/boot_hands_the_renderer_the_app_timezone.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// 🔴 RESOLVED FROM THIS FILE, NEVER FROM LUPIN_ROOT — the second measured instance of this
// defect (Krishna 🦚, 2026-09-23; the first was boot_gives_each_socket_its_own_session_id,
// where a 4-argument pin sat green through a 6-argument call because it was reading main's
// boot.ts). LUPIN_ROOT is inherited from the shell and names the MAIN CHECKOUT, so from any
// worktree every pin below was reading — and going green on — a boot.ts that seat never edited.
//
// A source pin that reads the wrong file is not a weak guard. It is a guard for somebody
// else's code, reporting on their behalf inside your run.
//
// ⚠️ THREE MORE FILES STILL CARRY IT, named here rather than fixed because they are not this
// row's: boot_wires_action_required_to_reveal_through_the_toolbar.test.ts,
// boot_wires_the_jobs_pane_to_the_shared_mine_switch.test.ts, and
// notifications_js/the_page_keeps_one_token_of_record.test.ts.
const BOOT_PATH = resolve(
  dirname( fileURLToPath( import.meta.url ) ),
  "../../../lupin_app/static/js/multiplexer/boot.ts",
);
const BOOT_CODE = readFileSync(BOOT_PATH, "utf8")
  .split("\n")
  .filter((line) => !line.trimStart().startsWith("//"))
  .join("\n");

/** Ensures: the body of the single /api/config/client fetch chain, comments stripped. */
function clientConfigChain(): string {
  const calls = [ ...BOOT_CODE.matchAll(/apiClient\.get<([\s\S]*?)\.catch\(/g) ];
  const hits  = calls.filter((c) => (c[ 0 ] as string).includes("/api/config/client"));
  assert.equal(hits.length, 1, `expected exactly one /api/config/client fetch chain, found ${hits.length}`);
  return (hits[ 0 ] as RegExpMatchArray)[ 0 ] as string;
}

test("the positive control: the config fetch is found and still wires the TTS preview flag", () => {
  const chain = clientConfigChain();
  assert.match(chain, /ttsPreviewConfig\.enabled\s*=/, "the TTS wiring vanished — this pin is reading the wrong chain");
});

test("boot hands the renderer the zone from that same fetch", () => {
  const chain = clientConfigChain();
  assert.match(
    chain,
    /renderer\.setAppTimezone\(\s*c\.app_timezone\s*\)/,
    "boot does not call setAppTimezone with the config's app_timezone — every mux timestamp renders in the browser's local zone",
  );
});

test("the request type names app_timezone, so a rename on the wire breaks the build and not the clock", () => {
  const chain = clientConfigChain();
  assert.match(
    chain,
    /app_timezone\?\s*:\s*string/,
    "the fetch's response type does not declare app_timezone; a server-side rename would then be a silent runtime undefined, which is precisely how this bug survived",
  );
});

test("the zone is applied under a truthiness guard, so a missing key leaves today's behaviour alone", () => {
  const chain = clientConfigChain();
  assert.match(
    chain,
    /if\s*\(\s*c\.app_timezone\s*\)/,
    "the call is unguarded: an absent or empty key would push undefined into the renderer and force a needless repaint",
  );
});

// ===========================================================================
// A-2 #4 — the same fetch also hands over the TTS interaction mode.
//
// Same class of defect as the zone above, and the same shape of fix: the value has
// been in /api/config/client's payload all along (system.py:855) and legacy reads it
// from there (notifications.js:901), but this seam never asked for it — so a host
// running SOLO painted the chorus glyphs on every conversation-mode button.
//
// Pinned here for the reason the header of this file gives: no renderer test can see
// a boot that forgets to call the setter. The BEHAVIOUR is proved in
// templates_sender_card.test.ts (the two icon sets) and notifications_list_renderer's
// setter test (adoption + the cache drop).
// ===========================================================================

test("A-2 #4: boot hands the renderer the interaction mode from that same fetch", () => {
  const chain = clientConfigChain();
  assert.match(
    chain,
    /renderer\.setTtsInteractionMode\(/,
    "boot never calls setTtsInteractionMode — a SOLO host shows chorus icons for the life of the page",
  );
} );

test("A-2 #4: the request type names tts_interaction_mode, so a wire rename breaks the build", () => {
  const chain = clientConfigChain();
  assert.match(
    chain,
    /tts_interaction_mode\?\s*:/,
    "the fetch's response type does not name tts_interaction_mode",
  );
} );

test("A-2 #4: anything that is not \"solo\" resolves to chorus — legacy's own fallback", () => {
  // `config.tts_interaction_mode || 'chorus'` (notifications.js:901) and CoSA's
  // get_tts_interaction_mode both fail closed to chorus. A missing key, a typo or a
  // future third mode must not paint monopoly iconography nobody asked for.
  const chain = clientConfigChain();
  assert.match(
    chain,
    /c\.tts_interaction_mode\s*===\s*"solo"\s*\?\s*"solo"\s*:\s*"chorus"/,
    "the mode is passed through without failing closed to chorus",
  );
} );
