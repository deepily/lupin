> Part 1 of 6 of the [Decision Proxy — Admin Guide](../proxy-admin-guide.md): why, trust levels, contents.

# Decision Proxy — Admin Guide

**Audience**: Lupin administrators who review and ratify proxy decisions

**Pages covered**: `/app/admin/proxy-dashboard` and `/app/admin/proxy-ratify`

**See Also**: End-to-End Trust Proxy Overview (`src/rnd/2026.02.23-trust-proxy-preference-learning/`, not in this tree) — full conceptual walkthrough from cold start to autonomous predictions

---

## Table of Contents

1. [Why the Decision Proxy Exists](#1-why-the-decision-proxy-exists)
2. [How Trust Levels Work](#2-how-trust-levels-work)
3. [The Morning Coffee Workflow](02-morning-coffee-and-trust-dashboard.md#3-the-morning-coffee-workflow)
4. [Trust Dashboard](02-morning-coffee-and-trust-dashboard.md#4-trust-dashboard-appadminproxy-dashboard)
5. [Pending Ratification](03-pending-ratification-and-badges.md#5-pending-ratification-appadminproxy-ratify)
6. [Badge and Color Reference](03-pending-ratification-and-badges.md#6-badge-and-color-reference)
7. [The Trust Feedback Loop](04-trust-feedback-loop.md#7-the-trust-feedback-loop)
8. [Quick Reference: API Endpoints](05-api-quick-reference.md#8-quick-reference-api-endpoints)

---

## 1. Why the Decision Proxy Exists

### The Problem

SWE Team jobs and other agentic workflows generate dozens of decisions that historically required real-time human approval.
Examples are task decomposition sign-offs, dangerous command gating, architecture choices, dependency updates and test strategy confirmations.
Each decision triggers a voice notification and blocks the job until you respond.

**The old model** — real-time, interrupt-driven:

```
Job starts → Decision #1 → [BLOCKS] → You click approve → Decision #2 → [BLOCKS] → ...
```

If you launch a SWE Team job at 8 PM and go to bed, the job stalls at its first decision.
Ten decisions means ten manual interruptions. You're babysitting the agent.

### The New Model

The decision proxy intercepts these decisions and classifies them by category and risk.
It either acts autonomously, at earned trust levels, or queues them for batch review later.

**The new model** — async, batch-driven:

```
Job starts → Proxy handles decisions autonomously → You review over morning coffee
```

**Net effect**: 4 hours of babysitting becomes 15 minutes of batch review.

### The Paradigm Shift

| Aspect | Before (Real-Time) | After (Proxy) |
|--------|---------------------|---------------|
| User attention | Required for every decision | Review in batches |
| Job blocking | Blocks on each decision | Runs continuously |
| Off-hours work | Impossible without babysitting | Fully autonomous |
| Trust model | Binary (allow/deny) | Graduated (Levels 1 to 5) |
| Learning | None | Proxy improves from your feedback |

---

## 2. How Trust Levels Work

### Trust Level Progression

Trust is tracked **per-user, per-domain, per-category**. The SWE domain has 6 categories
(see below), and each starts at Level 1 and progresses independently.

| Level | Name | Behavior | Ratification Required? |
|-------|------|----------|------------------------|
| **Level 1** | Shadow | Observe only — logs what the proxy *would* decide but takes no action. The original notification still reaches you. | No (not_required) |
| **Level 2** | Provisional | Suggests a decision and queues it for ratification. Does not act autonomously. | Yes (pending) |
| **Level 3** | Trusted | Acts when its classification confidence is at least 80% (`l3_act_confidence`). Below that it queues the decision as a suggestion. | Only below 80% |
| **Level 4** | Autonomous | Acts, but queues **destructive** decisions, decisions under 50% confidence (`l4_min_confidence`) and a random 10% audit sample (`l4_audit_rate`). | The queued cases |
| **Level 5** | Full Trust | Acts on all decisions in this category. Ratification available but not required. | No (not_required) |

These levels apply in `ACTIVE` mode. The three numbers are `EngineeringStrategy` arguments
(`swe_team/proxy/engineering_strategy.py`) with these defaults. No `lupin-app.ini` key sets them.
The 10% Level 4 audit draw is `l4_audit_rate` (default 0.10).
The key `swe team trust proxy l4 audit sample rate` is read into `config.py` as `l4_audit_sample_rate`.
It is never passed to the strategy, so changing the key has no effect today (a held task records the gap).
`SUGGEST` mode only suggests from Level 2 up. `SHADOW` mode always shadows.

**Where the level comes from.** Each strategy supplies its own level for a category.
The SWE strategy reads it from the trust tracker, which answers Level 1 for a category it does not know.
No base default of Level 1 sits behind it.

**Category caps.** A category never rises above its cap, whatever it earns.
Shipped caps are 3 for deployment, destructive and architecture, and 5 for testing, dependencies and general.
The `lupin-app.ini` keys `swe engineering proxy deployment cap level`, and the same with `destructive` or `architecture` in place of `deployment`, set the first three.
They now take effect when a SWE job starts.
A value outside 1 to 5 is refused with an error when the job builds its proxy.

**How a category earns its level.** The default count model counts **approved** decisions. Each is weighted
down with age (half-life 14 days, window 30 days). The levels start at 50, 200, 500 and 1000 weighted successes
for Levels 2 to 5. Rejections earn nothing and subtract nothing; the circuit breaker below uses them.
Your ratification adds to the counters and sets no level. A SWE job rebuilds its tracker from the counters at start, and the level follows.
The dashboard shows the level the SWE team orchestrator stores after each answered confirmation and each breaker trip.

### The 6 SWE Categories

| Category | Icon | What It Covers |
|----------|------|----------------|
| **Deployment** | Rocket | Deploy commands, environment changes, release operations |
| **Testing** | Test tube | Test execution approvals, test strategy decisions |
| **Dependencies** | Package | Dependency updates, package installations |
| **Architecture** | Triangular ruler | Architecture choices, refactoring decisions |
| **Destructive** | Warning | File deletions, force pushes, database drops |
| **General** | Gear | Everything else that doesn't fit the above |

### Trust Modes

The proxy operates in one of four modes, set globally from the Trust Dashboard:

| Mode | Description |
|------|-------------|
| **`DISABLED`** | Proxy is off. All decisions go directly to user as before. |
| **`SHADOW`** | Proxy observes and logs decisions but never acts. Good for initial evaluation. |
| **`SUGGEST`** | Proxy suggests decisions and queues them for ratification. Does not act autonomously. |
| **`ACTIVE`** | Proxy acts based on trust levels. This is the production mode. |

### Circuit Breaker

Each category has an independent circuit breaker that protects against automation failures.
It trips on a rejection rate above 15% or on collapsed confidence, demotes the category 2 levels and defers its decisions to you.
The category stays capped until new approvals earn the levels back.
The settings and the demotion rules are in [part 4](04-trust-feedback-loop.md#how-circuit-breakers-protect-against-failures).

| State | Indicator | Meaning |
|-------|-----------|---------|
| **OK** (Closed) | Green dot | Operating normally |
| **`TRIPPED`** (Open) | Red dot | Too many rejections or collapsed confidence — the gate defers in this category |
| **COOLDOWN** | Yellow dot | Recovery period after a trip |

### Active Hours and Deferral

When you are at your desk, the proxy should not answer for you. Before it posts an
automatic answer, it asks whether you are available. It defers to you only when all of
these hold:

1. The strategy decided to **act** and has an answer to post. Shadow, suggest and defer
   decisions post nothing, so nothing changes for them.
2. The time is inside your **active hours**, read in your timezone.
3. You have a live session. The server lists one for your user id, other than the
   proxy's own login.

When it defers, no answer is posted. The question stays in your notifications, as for any
other deferred decision. The Trust Dashboard shows the **defer** badge and the reason
`user available (active hours, connected); the proxy would have answered: ...`. The stored
decision keeps the answer the proxy would have given. The statistics count these as
`decisions_deferred_to_user`.

| `lupin-app.ini` key | Meaning | Shipped value |
|---------------------|---------|---------------|
| `decision proxy active hours start` | Hour (0-23) your active hours begin | `09` |
| `decision proxy active hours end` | Hour (0-23) they end; the end hour itself is outside | `22` |
| `decision proxy timezone` | IANA timezone the hours are read in | `America/Chicago` |
| `decision proxy human user id` | The server user id of **you**, the person the proxy defers to | empty |

**It is off until you name yourself**. With `decision proxy human user id` empty, the
proxy has no one to defer to. It answers exactly as before. To turn it on, set the key to
your user id (the `user_id` your browser session shows in `GET /api/websocket-sessions`).
Then restart the decision proxy process, because the keys are read at start.

**If the server cannot be asked**, the proxy treats you as away and answers as before. That
covers a failed or timed-out sessions request and an unreadable reply. It writes one
warning to its log: `[UserPresence] connectivity feed failed, treating the user as not
connected: <cause>`. This is the ruling "Proxy answers". It is one constant,
`FEED_FAILURE_MEANS_CONNECTED` in `decision_proxy/user_presence.py`. Setting it `True`
would make the proxy defer on doubt. The sessions answer is reused for 10 seconds, so a
connection that opens or closes can take that long to be seen.

**The SWE team gate has its own switch**. The SWE team orchestrator asks the same strategy
in-process. At an `act` decision it approves without asking anyone, whatever the hour.
The key `swe engineering proxy ask before act` changes that. It ships `false`, which keeps
today's behaviour. Set it `true` and an `act` decision no longer approves by itself.
The gate sends the question as a notification, the route the Decision Proxy watches.
The proxy then answers when you are away and defers when you are connected. Other decision kinds (suggest, defer, shadow) behave the same either way. The
orchestrator reads the key when a SWE job starts.

Not measured: whether any SWE job runs in active trust mode today.

---
