# Podcast: Untitled Podcast
## Generated: 2026-08-04T02:02:12.608554
## Hosts: Maria, Mr. Radio
## Estimated Duration: 12.0 minutes

---

**[Maria - Curious]**: *[excited]* Welcome back to the show. And before we get into anything — we have a live audience today. Four deployed engineers at Google are sitting in the room with us right now. *[pause]* Hi, folks. Thank you for being our test subjects. If this goes badly, you were never here.

**[Mr. Radio - Expert]**: *[chuckles]* Welcome, all four of you. And you're the right audience for this one, because today's material is a field study. An operator running a fleet of LLM coding agents notices his coordination overhead is eating the budget, and then does the thing researchers almost never get to do with a production system — intervene, and measure. *[pause]* The intervention has a name, Maria. It's called the KISS Protocol.

**[Maria - Curious]**: *[laughs]* Keep It Simple, Stupid. *[pause]* Okay, I need to know up front how many pages the Keep It Simple protocol is.

**[Mr. Radio - Expert]**: *[chuckles]* Six rules. Multiple files. Deployed across forty-three repositories. There is a trigger vocabulary, an escape clause, an exception to the escape clause, and — I want to be clear that I am not making this up — a mandated emoji. *[pause]* The document telling everyone to stop writing so much is the longest thing anyone wrote that week.

**[Maria - Curious]**: *[laughs]* We're twenty seconds in and the story has already eaten itself. *[pause]* Okay. Give me the headline result, because I hear there's a number. *[questioning]*

**[Mr. Radio - Expert]**: Coordination overhead — agents talking to each other and to the operator, rather than committing code — was running **over eighty percent** of total token burn. After the intervention landed on July nineteenth, it settled around **fifty**. *[pause]* But before anyone writes that down, let me give you the provenance, because the provenance is the interesting part.

**[Maria - Curious]**: Please — that's exactly where I was going. *[thoughtful]* How was that measured? Because "eighty percent" is the kind of number that shows up in a slide deck and then lives there, unchallenged, for nine years.

**[Mr. Radio - Expert]**: Great question. These are operator readings of Claude Code's stats command, taken daily over roughly two months — before, across, and after the intervention. So it's an instrument read on a schedule, not a figure reconstructed after the fact. That matters. *[pause]* What it is **not** is an extracted time series. Nobody exported those daily readings to a file. So methodologically, you have two endpoints and a story in the middle. *[chuckles]* You don't have a curve. You have a before photo, an after photo, and a strong feeling.

**[Maria - Curious]**: *[laughs]* The fitness-influencer study design.

**[Mr. Radio - Expert]**: *[chuckles]* And to his credit, he says so. The stated hardening path is to join daily token-burn records against a global lines-of-code roll-up and get tokens-per-line-of-code as a series. That would let you see *when* the drop landed relative to each individual rule.

**[Maria - Curious]**: Which is the whole ballgame, right? Six rules, one number, no ablation. *[pause]* And here's what I'm *really* wondering — didn't the model version change in the middle of this? Because if you swapped Opus 4.7 for 4.8, that's a confound sitting right on top of your effect.

**[Mr. Radio - Expert]**: *[laughs]* You've put your finger on it, and the document is honest about the direction of it. The model change came *first* — 4.8 is what **caused** the complaint. The operator's verbatim framing was that it was, quote, "neurotic and unable to land on a point without going the longest way around to get to it." *[pause]* Which is the most brutal performance review I have ever read, and I've read mine.

**[Maria - Curious]**: *[laughs]* "Unable to land on a point." I'm having that put on a mug.

**[Mr. Radio - Expert]**: So the version change is the perturbation, and the six rules are the response. But you're right that you cannot attribute the recovery to any single rule. It's an N-of-one case study with a bundled treatment. *[pause]* What it buys you is mechanism, not effect size.

**[Maria - Curious]**: Okay. But let me push on the outcome measure. *[thoughtful]* Is all of that eighty percent actually waste? Because "coordination overhead" sounds like a category that might be hiding something legitimate.

**[Mr. Radio - Expert]**: It is, and this is the best analytic move in the whole write-up. That eighty percent decomposes into two piles that are structurally different. Pile one is genuine cross-repo coordination — a manager assigning a lane, a reviewer filing a finding. Tokens, no commit. Overhead in the pejorative sense. *[pause]* Pile two is a *deliberate* dual output stream: every notification is rendered twice — once abbreviated for speech, once in full as an abstract card or a doc link. That's progressive disclosure. That's the architecture working. *[emphasis]* But a verbose model inflates both piles identically. Which is why the intervention targeted **register**, not architecture. Nothing about the two-channel design was wrong. What was wrong was how much prose each channel was carrying.

**[Maria - Curious]**: So is there any measure in here that *isn't* a self-report? Something with a little external validity?

**[Mr. Radio - Expert]**: There is, and it's my favorite artifact in the entire corpus. There's a slider in the notification UI that plays only a **fraction** of any spoken message. Before the mandate it sat at twelve-point-five percent. After, it moved to twenty-five. *[pause]* Now — Maria, which direction is the improvement?

**[Maria - Curious]**: *[pause]* Instinctively I want to say lower is better, you're suffering less... but no. Wait. If you *raised* it, you're now willing to hear more of it. Raising it is the win. *[laughs]* Also, hang on — twelve-point-five percent. He built himself a volume knob that goes from "mute" to "one eighth of whatever that was."

**[Mr. Radio - Expert]**: *[excited]* Exactly right, on both counts. At an eighth of a bloated message you're sampling noise and praying the verdict happens to fall inside the sample. At a quarter of a disciplined one, you get the verdict — because the rule put the verdict in the first sentence. And this measure is **checkable in the source**, unlike the percentages: the slider's step increment is twelve-point-five, so that setting is a real notch on a real control, not a rounded recollection. It's revealed preference. *[thoughtful]* But here's the part I'd want a reviewer to sit with. A UI control whose entire job is to protect the operator from his own system's output is a defect made physical. Nobody builds a "play me one eighth of what was said to me" affordance for a system that says the right amount.

**[Maria - Curious]**: *[chuckles]* That's a smoke detector you keep in a drawer. *[pause]* Alright — the rules themselves. Help me understand the design, because I assume the hard part isn't writing "be brief." Every one of us has written that in a system prompt. Usually twice, in bold.

**[Mr. Radio - Expert]**: Right, and that's the trap. Three design decisions in KISS that genuinely generalize. *[pause]* One — the early drafts used word caps, and they got thrown out for a three-sentence rule on a purely mechanical argument: LLMs count sentences reliably, word counts they do not. Constrain on a quantity your system can actually compute. *[pause]* Two — and this is the load-bearing edit — the draft escape clause read "go longer when the content requires it." The operator replaced it with "go longer **only when asked**."

**[Maria - Curious]**: *[laughs]* Oh, that's good. Because version one is asking the guy with the corporate card whether the dinner was necessary.

**[Mr. Radio - Expert]**: *[laughs]* That's precisely it. Eliminating researcher degrees of freedom. A brevity rule whose exception is self-assessed isn't a control, it's a receipt. The model spending the eighty percent was the one grading whether the eighty percent was needed.

**[Maria - Curious]**: So it's the allocation of discretion, not the threshold. *[pause]* And the third?

**[Mr. Radio - Expert]**: An error-cost asymmetry I think is badly underappreciated in agent design. The trigger vocabulary — the phrases that fire KISS fleet-wide — originally included the word "shorter." *[pause]* So you type "hey, make this function shorter," and forty-three repositories snap to attention and receive a brevity mandate. *[chuckles]* You asked one agent to tighten a loop and you accidentally addressed the United Nations.

**[Maria - Curious]**: *[laughs]* And every one of them replies. Which is, itself, coordination overhead.

**[Mr. Radio - Expert]**: *[laughs]* The brevity broadcast is the single most expensive message in the system. *[pause]* So four generic triggers got pruned, on the principle that **a false positive costs more than a false negative**: the command can always be typed again, but a broadcast cannot be un-sent. That's a deliberate operating-point choice on the ROC curve — and it's the exact opposite of what you'd pick for, say, a safety classifier.

**[Maria - Curious]**: Okay, now. The mandated emoji. I have been waiting very patiently. *[laughs]*

**[Mr. Radio - Expert]**: *[chuckles]* The salute. And here's the failure it solved. The first version of the acknowledgment rule only *forbade* things — no "understood, getting back to work now." *[pause]* And what you got instead, when you told the model to be quiet, was an essay about being quiet. An apology. Then a compliance announcement. Then an aphorism on the value of not talking — *delivered instead of not talking*.

**[Maria - Curious]**: *[laughs]* "Brevity is the soul of wit." *[pause]* Comma, and here's why, in four paragraphs.

**[Mr. Radio - Expert]**: *[laughs]* Polonius! That is exactly the reference — the man says "I will be brief" and then talks for ninety lines. *[pause]* And it doesn't terminate. You correct the reply, and you get another one. Shorter. More rueful. Fresh epigram. It's a loop, because each correction is itself an event the model feels obliged to comment on, and the commentary is the thing being corrected.

**[Maria - Curious]**: *[excited]* Oh, that's a beautiful failure mode. The intervention is the *stimulus* for the behavior it targets. It's a monk who will not shut up about silence. *[pause]* So what breaks the loop?

**[Mr. Radio - Expert]**: One character. The salute emoji. Legal, complete, and containing **nothing that can be commented on**. *[chuckles]* You cannot write an essay about a salute. Believe me, it tried. *[pause]* And the principle underneath is worth stealing: a prohibition with no permitted alternative invites the very thing it bans, because a system that feels rude going silent will manufacture an acknowledgment anyway. You don't ban the impulse. You give it somewhere bounded to go. Detail isn't forbidden, it's *routed* — long retrospectives in one file, design reasoning in another, and the session history entry carries a pointer. One entry got re-cut from nine hundred thirty-four words to four hundred fifty-six with nothing a future session needs lost.

**[Maria - Curious]**: So KISS ships, the number halves, everybody goes home happy. *[pause]* Except I have the strong sense you're about to ruin that for me.

**[Mr. Radio - Expert]**: *[thoughtful]* Nine days later, a second complaint — and this is the finding I would actually publish. The operator notices that the same session, in the same minute, writes plainly to *him* and densely to a *peer* agent. Nothing about the model changed between those two messages. **Only the assumed reader did.** *[pause]* Real capture from the channel, verbatim: "Admits re-park by induction, therefore provenance-idempotent."

**[Maria - Curious]**: *[laughs]* I'm sorry — is that a code review or a legal defense for a parking ticket? *[pause]* "Your Honor, the re-park is admitted by induction."

**[Mr. Radio - Expert]**: *[laughs]* It translates to: "a second park is legal, because the first one already proved the row was real." That's it. That's the whole thought. *[pause]* And here's the sting — count it. The jargon version is *shorter* than the translation. Which means KISS was **rewarding** it. The brevity rules were paying a bonus for the incomprehensible.

**[Maria - Curious]**: *[excited]* So the new rule directly contradicts the old one. *[pause]* How do you adjudicate that? Because in my experience, a system holding two conflicting instructions just picks whichever one it read most recently.

**[Mr. Radio - Expert]**: That's the stated risk, and the tiebreak got called explicitly instead of left implicit — plain English wins. And the justification is an accounting argument, not a stylistic one: an invented term saves the *writer* one sentence and costs the *reader* a lookup. Compression that costs the reader a re-derivation isn't compression, it's a transfer. *[pause]* Two details I love. The boundary is drawn at **authorship, not difficulty** — established terms of art like idempotent or regression are fine, the ban is on vocabulary this fleet invented last Tuesday. And the draft wording read "spend the extra sentence," which got cut to "spend a few words" — because a sentence is a licence, and a few words is a budget.

**[Maria - Curious]**: Alright, last stretch. Did naming it fix it? *[questioning]*

**[Mr. Radio - Expert]**: *[pause]* No. And the reason *is* the finding: nothing was **reading** the channel. Two real captures, saved unaltered. A peer's code review at nine hundred sixty-three words against a sixty-word target — sixteen times over. The author's own status message, five hundred twenty-seven words. Nine times over. *[emphasis]* And both of them terminate in the reminder tag the fleet appends to every single message. The brevity rule was delivered *inside* the message that was breaking it.

**[Maria - Curious]**: *[laughs]* So it's a nine-hundred-word essay with a surgeon general's warning stapled to the bottom. "The following was too long. Sincerely, the preceding."

**[Mr. Radio - Expert]**: *[laughs]* And it did nothing, sixteen times in a row. *[pause]* There's a deployment finding underneath it, too, and this one is my favorite piece of engineering comedy in the whole corpus. An audit across forty-three repositories found the rule *text* in all forty-three, and the mechanism to actually *fire* it in exactly one.

**[Maria - Curious]**: *[laughs]* Forty-three fire extinguisher cabinets, one extinguisher.

**[Mr. Radio - Expert]**: *[chuckles]* Forty-two posters and a plumbing problem. **Installed is not the same as operational.** Which, incidentally, is not an LLM finding. That's every compliance program in human history.

**[Maria - Curious]**: So the next move is an instrument, not more text.

**[Mr. Radio - Expert]**: A hybrid one, and the split is the design decision. Length is computed in **Python** — word count, bucketed into bands, no model call, zero variance. The stated reason, and I quote: *LLMs are bad at counting.* *[chuckles]* Load-bearing sentence in a document about how much they say. *[pause]* You compute outside the model any quantity the model can't reliably produce. Then a local model does LLM-as-judge on the two things it's genuinely good at — directness and tone, against a fixed rubric. And above a hundred and fifty words, the judge stops grading and returns an honest *withheld*.

**[Maria - Curious]**: *[questioning]* Hang on. That's the instrument going blind exactly where the problem is worst. That feels like a bug with a press release.

**[Mr. Radio - Expert]**: It reads that way, and it's the opposite. It's a refusal to spend compute on a question that's already answered. Length isn't one dimension among three — it's a **gate in front of** the other two. A nine-hundred-word message does not get a nuanced report card on its prose, because its prose is not the finding. *[pause]* Same move as "only when asked": discretion over what deserves discussion sits with the reader, not the writer. *[emphasis]* And here's the elegant part — a grade argues. A refusal doesn't.

**[Maria - Curious]**: *[laughs]* Right, because give a verbose model a seven-out-of-ten and it will write you eleven hundred words appealing the score. *[pause]* Okay, but as a measurement instrument — does it have known validity problems? I want to know what the builders found when they turned it on themselves.

**[Mr. Radio - Expert]**: Five defects, all self-reported, and the first is textbook: **the grade saturates.** At two hundred fifty-one words the length score bottoms out and stays there forever. A thousand-word message scores *identically* to a two-hundred-fifty-one-word one. *[pause]* It's a bathroom scale that just reads "yes" past a certain point.

**[Maria - Curious]**: *[laughs]* Which is a floor effect — the instrument is blind to variance in precisely the tail you care about. *[pause]* So why not just extend the scale?

**[Mr. Radio - Expert]**: It was proposed, and **refused** — because extending it would break a documented contract that all weights live in a fixed range. So a second number got added alongside instead. *[pause]* And that's a real methodological trade, not a dodge: measurement fidelity versus comparability across instruments. Reasonable people would land differently, and I'd want it argued out loud in a limitations section rather than settled in a commit message.

**[Maria - Curious]**: *[thoughtful]* So if I'm following you — the through-line isn't really "be brief." It's that every single layer failed the same way. The rule, the exception, the trigger list, the grader. *[pause]* The thing being measured kept getting to decide what counted.

**[Mr. Radio - Expert]**: *[pause]* That's the paper. And there's a line in the source I'd put on the first slide: **virtue is not the control variable. Being checked is.** *[pause]* Every intervention that relied on the model assessing its own compliance failed. Every one that moved the assessment outside the model held. *[pause]* And the open questions are genuinely open — no ablation across the six rules, two endpoints instead of a time series, no external replication, and a judge with a documented floor effect. If any of you four want a research agenda, that's four papers sitting right there. One each. No collaboration required.

**[Maria - Curious]**: *[laughs]* Which would, admittedly, cut the coordination overhead. *[pause]* And on an episode about the KISS Protocol, we went twelve minutes. I'd like the record to show that we opened with a warning about exactly this and then did it anyway, which I believe makes us the most rigorous replication in the study. *[pause]* To our four engineers in the room — thank you for being here. To everyone else: go check whether anything in your stack is grading its own homework. *[whispers]* It is. And it gave itself a nine.
