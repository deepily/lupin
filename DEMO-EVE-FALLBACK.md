# 🚨 DEMO FALLBACK — Presentation Path (2026-08-06 noon)

**If the presentation demo breaks, do THIS. Ten seconds. No debugging.**

```bash
# 1. Check out the last certified-good build
git -C /mnt/DATA01/include/www.deepily.ai/projects/lupin checkout cecc18c7

# 2. Bounce the dev server so it serves that build
/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/bounce-dev-server.sh

# 3. Wait for the "back up" all-clear, then re-run the demo.
```

To return to the working branch afterward: `git checkout wip-v0.2.0-2026.08.03-present-and-demo`

---

## Which DECK to open — a different question from which sha

**Deck ≠ code.** `cecc18c7` below answers *"what code should the server run?"* It says
nothing about which file to open. Do not read the one sha on this card as the answer to
whatever you happen to be asking at 9am.

**USE:** `2026.08.05-at-18:57-UTC-the-lever-one-year-of.pptx` (built from the `…18:53…`
YAML) — **32 slides**, 9,331,512 bytes, 32 slide XMLs, valid zip. Verified independently
by María 🌸 and by me.

> ⚠️ **STALE PENDING REBUILD.** Both existing decks predate Rick's Archimedes strike,
> which lives in slide-1 artwork and presenter notes — that needs a **regeneration, not an
> edit**. If a build made *after* the outline was finalized exists, use that instead.

**DO NOT USE:** `2026.08.05-at-17:21-UTC-one-question-four-scales-a.pptx` (20 slides).
Superseded, **and its slide 2 displays the subtitle "Archimedes, restated for an engineer
who can't type"** — a misstatement of Rick's own position. His wording is that typing is
not impossible, it is expensive and paid for in pain.

*(The `…17:19…` stem is that build's YAML/markdown; `…17:21…` is the rendered deck. Name
the file you would actually open.)*

> 🔎 **If you go looking for that phrase yourself, do not grep the PPTX.** Every slide in
> these decks is a rendered **image**, so the slide XML carries no text at all and a text
> search comes back clean on a deck that plainly shows the line. It has to be read off the
> artwork. The phrase *is* greppable in the build's `.yaml` and `.md` sources.

---

## The shas, safest first

| Sha | State | Deck proof | Use it when |
|---|---|---|---|
| **`cecc18c7`** | **PRIMARY** — clean, committed, Rachel-gated. HEAD as of 2026-08-05 14:34 EDT. Has both the `b04aa599` parser fix and the `api_client` truncation fix. | E2E-green 2026-08-05 14:18 EDT: **5.8 MB PPTX / 15 slides**, terminal state. Served bytes were byte-identical to this commit (api_client md5 `5ae751c0…`). | **First choice if anything goes wrong.** |
| `e8e9c0e9` | deeper fallback — clean, committed, fully certified an earlier session | Job `pr-3e89d1a5`, **6077 KB PPTX / 15 slides** (verified 2026-08-05, prior session) | If `cecc18c7` somehow misbehaves — predates both fixes but generates the same demo deck. |

**Why `e8e9c0e9` still works as a deeper fallback:** the commits above it (`b04aa599`, `cecc18c7`) change only parser *error-message text* and truncation *fail-safe* handling. On the demo's happy path — well-formed model output — all three shas produce the **same deck**; they differ only on malformed or truncated model output.

---

## What was verified today (2026-08-05)

- **Server:** :7999 dev, boot #40, container StartedAt `2026-08-05T17:49:38Z`, stable through the run.
- **Served artifact:** at run time HEAD was `425ee47a` with `api_client.py` uncommitted (md5 `5ae751c0…`). Rachel then gated that change and it was committed as **`cecc18c7`** — byte-identical to the served bytes. So today's run is a **clean green on `cecc18c7`**, `b04aa599` and `425ee47a` beneath it.
- **Result:** genuine terminal-state green — real `.pptx`, 5,795,975 bytes, valid zip, **15 slides**; job terminal (pool inflight 0, consumer not stalled). Parser pipeline carried full content through (30k-char seed tail sentinel reached the deck; audience steer landed).

### ⚠️ Harness caveat (filed, not fixed — no code authority here)

`composed_green.py --mode fixes` printed `ACCEPTANCE: PASS` computed from the Phase-5 `.yaml`. Its `.pptx` check matches by **basename** (`yaml-name` → `.pptx`), but the real deck is written ~3 min later under a **different timestamp** (`18:15-UTC` yaml vs `18:18-UTC` pptx), so the harness's own pptx match **silently missed the real file** and would have green-lit with no PPTX at all. The green today was confirmed by going to disk and reading the actual `.pptx`, not by trusting the harness banner. **Fix owed:** match the pptx by content/newest-in-window, never by basename.

Full receipt: `src/rnd/v0.2.0/2026.08.05-qa-presentation-path-e2e-verification.md`.

*Verified by Tiffany 💍 (Tester), session 505f58ec, 2026-08-05.*
