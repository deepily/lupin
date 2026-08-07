# Prompt samples — exactly what Phi-4 saw

Four real DMs, one per size band, each as the **verbatim prompt** sent to
Phi-4-14B on `:3001`. Paste one into any other model and compare.

| file | words | placeholders | prompt size | band target |
|---|---|---|---|---|
| `prompt-<80-79w.txt` | 79 | 4 | 3,853 ch | 15% |
| `prompt-80-150-149w.txt` | 149 | 3 | 4,295 ch | 30% |
| `prompt-150-250-249w.txt` | 249 | 7 | 4,791 ch | 45% |
| `prompt-250plus-900w.txt` | 900 | 30 | 8,549 ch | 60% |

Each has an `answerkey-*.txt` beside it with the original message, the
placeholder map, and the verify-tier literals — what a correct answer must
preserve. **Don't paste the answer key into the model**; it is for scoring.

## What a good answer looks like

1. Well-formed `<response>` with `<thoughts>` and a `<compressed>` CDATA block.
2. **Every `[[Lnn]]` present exactly once**, spelling unchanged, attached to the
   same claim it came from.
3. **No invented placeholders.**
4. Every verify-tier literal still present — the bare numbers, ports, `§`
   pointers and mid-sentence glyphs listed in the answer key. These are *not*
   substituted, so a model that "tidies" `31` into `thirty-one` fails here.
5. **Meaningfully shorter.** Phi-4's problem was not fidelity — it was that
   output came back about the same length as input.

## What Phi-4 actually did, for comparison

Measured over 600 live compressions:

| band | target | achieved (attempted basis) |
|---|---|---|
| <80 | 15% | 5.8% |
| 80–150 | 30% | 5.1% |
| 150–250 | 45% | 2.8% |
| 250+ | 60% | 2.6% |

Delivery 22–26%; the rest fell back to the original. **Telling it the target
explicitly did not help** — see the findings doc.

⚠️ The `</stop>` at the end of the injected XML example is a **vLLM stop token**,
not part of the format. Other providers will not need it and may echo it; ignore
it, or delete that one token before pasting.

⚠️ These prompts contain real fleet DM content. Treat as internal.
