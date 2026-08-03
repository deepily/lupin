Yes. **As of June 27, 2026, Claude Code can be configured to use Anthropic Claude models served through Google Cloud Vertex AI / Model Garden / Gemini Enterprise Agent Platform.** The clean path is no longer a proxy hack: Claude Code has first-class Vertex AI support, including a setup wizard in Claude Code **v2.1.98+**, and manual environment-variable configuration. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

Small terminology correction: you are not “hosting Claude Code models” yourself in Model Garden. Google exposes Anthropic Claude **managed publisher models** through Model Garden / Agent Platform; Claude Code then calls the Vertex/Agent Platform API endpoint using your GCP credentials, quota, IAM, and billing. Google’s docs describe the Claude models as fully managed serverless APIs with pay-as-you-go or provisioned-throughput billing. ([docs.cloud.google.com](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude))

## Minimal working setup

Use the wizard when possible:

```bash id="sdc3xr"
claude --version
claude
```

At login, choose:

```text id="13pe4a"
3rd-party platform → Google Vertex AI
```

Then follow the prompts. You can rerun the wizard later from inside Claude Code:

```text id="oztt3y"
/setup-vertex
```

The wizard detects project, region, credentials, model availability, and writes the resulting env configuration into your Claude Code settings file. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

For scripted/manual setup:

```bash id="s0dfio"
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com

gcloud auth application-default login

export CLAUDE_CODE_USE_VERTEX=1
export CLOUD_ML_REGION=global
export ANTHROPIC_VERTEX_PROJECT_ID=YOUR_PROJECT_ID

# Recommended: pin models instead of relying on moving aliases/defaults
export ANTHROPIC_DEFAULT_OPUS_MODEL='claude-opus-4-8'
export ANTHROPIC_DEFAULT_SONNET_MODEL='claude-sonnet-4-6'
export ANTHROPIC_DEFAULT_HAIKU_MODEL='claude-haiku-4-5@20251001'

claude
```

You must also enable/request access to the target Claude models from Model Garden in the GCP project; Anthropic’s Claude Code docs say approval can take **24–48 hours**. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

## Production-grade `~/.claude/settings.json`

For a dev server, I would usually put the provider selection and model pins in Claude Code settings rather than relying on ad hoc shell state:

```json id="126h78"
{
  "gcpAuthRefresh": "gcloud auth application-default login",
  "env": {
    "CLAUDE_CODE_USE_VERTEX": "1",
    "CLOUD_ML_REGION": "us",
    "ANTHROPIC_VERTEX_PROJECT_ID": "your-gcp-project-id",

    "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-4-6",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-5@20251001",

    "API_TIMEOUT_MS": "1200000",
    "BASH_DEFAULT_TIMEOUT_MS": "300000"
  }
}
```

Claude Code reads env vars from settings at startup, and environment variables override settings fields where both exist. ([code.claude.com](https://code.claude.com/docs/en/env-vars))

## IAM

The pragmatic role is:

```bash id="ejm5uj"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="user:you@example.com" \
  --role="roles/aiplatform.user"
```

For tighter enterprise setups, the required permission called out by Anthropic is:

```text id="btzdso"
aiplatform.endpoints.predict
```

That permission is needed for model invocation and token counting. Anthropic also recommends a dedicated GCP project for Claude Code to simplify cost tracking and access control. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

For a dev server, prefer one of these over long-lived user auth:

```bash id="jhc06u"
# Service account key file, if your security posture allows it
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Or Workload Identity Federation / attached service account where feasible
```

Claude Code uses standard Google ADC resolution. Important gotcha: `GCLOUD_PROJECT`, `GOOGLE_CLOUD_PROJECT`, and the project embedded in `GOOGLE_APPLICATION_CREDENTIALS` can override `ANTHROPIC_VERTEX_PROJECT_ID`. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

## Region strategy

Claude Code supports `global`, `us`, `eu`, and specific regions such as `us-east5`; it chooses the appropriate Vertex hostname, including the multi-region `aiplatform.us.rep.googleapis.com` and `aiplatform.eu.rep.googleapis.com` forms. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

Best default for production is usually:

```bash id="w64dmc"
export CLOUD_ML_REGION=us
```

or:

```bash id="6ppy82"
export CLOUD_ML_REGION=eu
```

rather than a single region, assuming your compliance boundary allows it. Google says U.S. and EU multi-region endpoints improve reliability by routing within the geography while preserving U.S./EU data-residency boundaries. Google also recommends multi-region endpoints for production workloads that need U.S. or EU residency. ([cloud.google.com](https://cloud.google.com/blog/products/ai-machine-learning/multi-region-endpoints-for-claude-available-on-vertex-ai))

Use `global` when maximum availability/cost optimization matters more than regional residency. Use a specific region only when you need strict locality or when a model is only enabled there.

## Model selection best practices

Pin explicit models. Do not rely on `sonnet`, `opus`, or Claude Code’s internal defaults for team rollout.

As of the docs I found, Claude Code’s Vertex default can lag newer releases: without `ANTHROPIC_DEFAULT_OPUS_MODEL`, the `opus` alias resolves to **Opus 4.6**, while you can explicitly pin **Opus 4.8** with:

```bash id="ovrzic"
export ANTHROPIC_DEFAULT_OPUS_MODEL='claude-opus-4-8'
```

Anthropic’s own docs explicitly warn that aliases can lag the newest release and may not be enabled in your project. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

For a coding-heavy setup:

```bash id="5dthmm"
# Highest intelligence / hard refactors
export ANTHROPIC_MODEL='claude-opus-4-8'

# Strong default for cost/perf
export ANTHROPIC_DEFAULT_SONNET_MODEL='claude-sonnet-4-6'

# Cheap background/small-fast tasks if enabled in your project/region
export ANTHROPIC_DEFAULT_HAIKU_MODEL='claude-haiku-4-5@20251001'
```

Google’s Model Garden page lists Claude Opus 4.8 and Sonnet 4.6 as coding/agentic models available on Google Cloud; Google’s Claude model docs describe Opus 4.8 as built for coding and long-running agentic workflows, and Sonnet 4.6 as built for coding, agents, and enterprise workflows. ([cloud.google.com](https://cloud.google.com/products/model-garden/claude))

## 1M context

Claude Code supports 1M context on Vertex for **Opus 4.6+** and **Sonnet 4.6**, and the setup wizard can pin the 1M variant. For manual pinning, Anthropic says to append `[1m]` to the model ID. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

Example:

```bash id="qzalyz"
export ANTHROPIC_MODEL='claude-sonnet-4-6[1m]'
```

Gotcha: 1M context is expensive and can increase token-counting, prompt-caching, and latency sensitivity. I would not use it as the universal default. Use it for large monorepos, large migrations, or sessions where compaction is actively harming performance.

## Prompt caching

Claude Code enables prompt caching automatically on Vertex. You can disable it:

```bash id="ny8rtc"
export DISABLE_PROMPT_CACHING=1
```

or request a 1-hour cache TTL:

```bash id="ey8wb2"
export ENABLE_PROMPT_CACHING_1H=1
```

Anthropic notes that 1-hour cache writes cost more. Google says multi-region endpoints support prompt caching and try to route to the region where your prompt is already cached; Google also recommends sticking to one location per workload for best caching performance. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

Best practice: keep the same `CLOUD_ML_REGION` for the same repo/team/workload. Bouncing between `global`, `us`, `eu`, and specific regions is an anti-pattern if you care about cache hit rate and latency consistency.

## Common gotchas and workarounds

### 1. `404 model not found`

Usually one of these:

```text id="b64z1u"
model not enabled in Model Garden
wrong model ID
model not available in selected region
using global for a model that is regional/multi-region only
using a regional endpoint for a model only available on global/us/eu
wrong project selected by ADC
```

Claude Code’s own troubleshooting says to confirm the model is enabled in Model Garden and verify model availability for the location. If using `CLOUD_ML_REGION=global`, check whether the model supports global; otherwise pin a supported model or override the model-specific region. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

Useful workaround pattern:

```bash id="3yesdk"
export CLOUD_ML_REGION=global

# Override only the model that is not available on global
export VERTEX_REGION_CLAUDE_HAIKU_4_5=us-east5
export VERTEX_REGION_CLAUDE_4_6_SONNET=us
```

Anthropic documents model-specific `VERTEX_REGION_CLAUDE_*` overrides for this exact failure mode. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

### 2. `429` / quota problems

A `429` may mean regional quota/capacity, not that Claude Code is misconfigured. Anthropic recommends checking quotas and, for regional endpoints, ensuring both the primary and small/fast model are supported in the selected region; it also suggests switching to `CLOUD_ML_REGION=global` for better availability. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

Best practice:

```bash id="den2gd"
# Prefer multi-region or global for interactive dev
export CLOUD_ML_REGION=us   # or eu/global

# Make sure Haiku/small-fast is enabled or force it to same primary model
export ANTHROPIC_DEFAULT_HAIKU_MODEL='claude-haiku-4-5@20251001'
```

If you are rolling this out to a team, request quota increases before rollout.

### 3. ADC project precedence surprises

This one bites people constantly. You set:

```bash id="gyzvyl"
export ANTHROPIC_VERTEX_PROJECT_ID=project-a
```

but ADC or `GOOGLE_CLOUD_PROJECT` points to `project-b`, so calls go to the wrong project. Claude Code docs explicitly say `GCLOUD_PROJECT`, `GOOGLE_CLOUD_PROJECT`, and the project inside `GOOGLE_APPLICATION_CREDENTIALS` take precedence over `ANTHROPIC_VERTEX_PROJECT_ID`. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

Debug checklist:

```bash id="0xz5jd"
gcloud config get-value project
echo "$GOOGLE_CLOUD_PROJECT"
echo "$GCLOUD_PROJECT"
echo "$ANTHROPIC_VERTEX_PROJECT_ID"
echo "$GOOGLE_APPLICATION_CREDENTIALS"
gcloud auth application-default print-access-token >/dev/null && echo "ADC OK"
```

### 4. MCP tool search is not always available

Claude Code disables MCP tool search by default on Vertex, so MCP tool definitions load upfront. Anthropic says Vertex supports tool search only for **Claude Sonnet 4.5+** and **Claude Opus 4.5+**; enabling tool search on earlier models can fail because earlier Vertex models reject the required beta header. ([code.claude.com](https://code.claude.com/docs/en/google-vertex-ai))

Safe default:

```bash id="ltq8yh"
unset ENABLE_TOOL_SEARCH
```

Enable only when pinned to a compatible model:

```bash id="ea508m"
export ENABLE_TOOL_SEARCH=true
```

### 5. Historical beta-header / token-counting bug

There was a real Claude Code Vertex bug where Claude Code sent `anthropic-beta` headers to Vertex token-counting calls, producing invalid-request errors, especially around 1M context and web-search beta headers. The GitHub issue was marked closed, but it is worth knowing because the symptom looks like a Vertex/API incompatibility rather than an auth issue. ([github.com](https://github.com/anthropics/claude-code/issues/11154))

Workaround if you see something like `Unexpected value(s) ... for the anthropic-beta header`:

```bash id="moo18w"
claude --version
npm update -g @anthropic-ai/claude-code  # or your install/update path
unset ANTHROPIC_BETAS
unset ENABLE_TOOL_SEARCH
# Temporarily avoid [1m] until confirmed fixed in your installed version
```

### 6. Claude Code is moving fast

The current GitHub releases show very frequent Claude Code releases; v2.1.190 was published June 24, 2026, and v2.1.187 on June 23 included many fixes around agent behavior, remote MCP, structured output, worktrees, and model restrictions. ([github.com](https://github.com/anthropics/claude-code/releases))

Best practice: pin/roll forward intentionally. For a team, avoid “everyone auto-updates whenever.” Test a version with Vertex, MCP, your chosen models, and your repo shape, then roll it out.

## Anti-patterns

Do not do these:

```bash id="za2lu8"
# Anti-pattern: rely on default aliases for a team rollout
claude --model sonnet

# Anti-pattern: let shell/project/ADC point at different GCP projects
export ANTHROPIC_VERTEX_PROJECT_ID=prod-ai
export GOOGLE_CLOUD_PROJECT=random-dev-project

# Anti-pattern: choose a single region without confirming model availability
export CLOUD_ML_REGION=us-central1

# Anti-pattern: enable tool search globally across older models
export ENABLE_TOOL_SEARCH=true

# Anti-pattern: use 1M context for every session
export ANTHROPIC_MODEL='claude-sonnet-4-6[1m]'

# Anti-pattern: mix global/us/eu/region locations for the same workload
# because you will hurt cache predictability and complicate quota debugging.
```

## My recommended baseline for your dev server

For an individual AI/dev workstation or dev server:

```bash id="rjnbnr"
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com
gcloud auth application-default login

cat > ~/.claude/settings.json <<'JSON'
{
  "gcpAuthRefresh": "gcloud auth application-default login",
  "env": {
    "CLAUDE_CODE_USE_VERTEX": "1",
    "CLOUD_ML_REGION": "us",
    "ANTHROPIC_VERTEX_PROJECT_ID": "YOUR_PROJECT_ID",

    "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-4-6",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-5@20251001",

    "API_TIMEOUT_MS": "1200000",
    "BASH_DEFAULT_TIMEOUT_MS": "300000"
  }
}
JSON

claude
```

For day-to-day coding, use Sonnet 4.6 unless the task is a gnarly multi-file architecture/refactor/debugging run. For hard agentic coding, switch to Opus 4.8. For giant repo context, use a `[1m]` model only when needed. For production/team rollout, pin every model, use a dedicated GCP project, request quota ahead of time, standardize on `us`/`eu`/`global`, and keep a known-good Claude Code version.
