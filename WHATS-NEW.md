# What's New

The full narrative for the current release. The README carries a short summary and links here.

The narratives for earlier releases are archived at the end of [VERSION-HISTORY.md](VERSION-HISTORY.md), under "Full release narratives". For the older per-feature changelog, see [CHANGELOG.md](CHANGELOG.md).

---

## What's New in v0.2.2 — check for existing code before writing new code

v0.2.2 ran from 30 September to 3 November 2026. It asked one question: **before a seat writes a new function, can it find out whether one already exists**? The answer has three parts: a map of the code, tools that search it, and a merge gate that holds every seat to using them. The branch also measured how well the checker works, and it reports the weak spots as found.

**Reuse before you write**

- **A wiki of the code, written from the code**. About 670 capability pages now describe what each package does and how its parts fit together. A lint check fails when a page falls out of step with the code it describes.
- **Lookup tools every seat can call**. Before writing a definition, a seat asks whether something like it already exists. The tools search an index of every symbol and rank the candidates by meaning. A judging model then picks the ones that do the same job.
- **A merge gate that enforces it**. Every new function, method or class needs a short record of the lookup and its decision. The decision is duplicate, extend an existing symbol, or distinct and why. The gate refuses a merge without one, runs in seconds, and is switched on.
- **A nightly duplicate check**. Each night a job compares the day's new definitions against the rest of the tree, and files what it finds for triage. Its first pass found 41 candidates, and 4 were real duplicates, fixed the same day.

**Measuring the checker against ground truth**

- **Ground truth labelled by a person**. A labelling page let the owner mark 222 pairs of definitions as the same job or not. Every claim about the checker is scored against that set.
- **What helps, and what does not**. A one-line statement of purpose on each definition is what lets a duplicate be found at all. The judging model is the weak stage. On real pairs it ranks well enough to use. Inside a full candidate list, though, it cannot yet tell a duplicate from a look-alike, and that finding sets the next round of experiments.

**Code and docs that stay clean**

- **Docstrings rewritten, and kept that way**. Older model output had filled the docstrings with emphasis, history and references nobody could follow. The [documentation rewrite plan](src/rnd/v0.2.2/2026.09.30-lupin-af-documentation-rewrite-plan/2026.09.30-lupin-af-documentation-rewrite-plan.md) measures how often, with before-and-after examples. A sweep rewrote 3,485 docstrings and took lint findings from 29,838 to 0. A commit gate now stops them coming back.
- **Copy-pasted code merged**. Near-identical copies became shared helpers, which cut the exact clone groups from 129 to 34.
- **A higher test floor**. Coverage was measured at 100% across the whole frame. The unit suite grew from about 27,700 tests to about 43,200, and now runs in parallel. Documentation lint, the reuse check and the Docker smoke tests joined the merge gates.

**Following the project, and steering it**

- **Any document becomes a podcast in one click**. The doc viewer turns an explainer into a narrated episode, so the code and its plans can be followed by ear. Episodes can also be published to Google Drive.
- **One click to approve**. Cards carry links that approve a held task, approve a whole list, or raise one task to top priority. Each link shows a preview first. The fleet's skeleton-crew mode is now a switch in the web clients.
- **Smaller fixes in the clients**. Keep place now holds your scroll inside every card, and audio can no longer play for the wrong request.

**Platform**

- **One server image, on the current agent SDK**. Both servers run one rebuilt image. It carries the current Claude Agent SDK and the same Claude Code version as the host.
- **Tighter access**. The app reaches the database through its own role, with no password in its environment, and the database listens only locally. Guards stop one session from killing another's processes or answering another user's card.
- **A cloud test machine on Vertex**. The cloud test machine now reaches Claude through Google's Vertex service.
