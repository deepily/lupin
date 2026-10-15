---
capability: gcs-and-api-rate-limit-helpers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.api_resource_manager.ApiResourceManager@c03ce91fde
  - cosa.utils.api_resource_manager.ApiResourceManager.acquire@e45bd02391
  - cosa.utils.api_resource_manager.ApiResourceManager.get_status@091e2c21f8
  - cosa.utils.api_resource_manager.ApiResourceManager.record_call@ce9ae2e949
  - cosa.utils.api_resource_manager.get_arm@5970d5d6ab
  - cosa.utils.api_resource_manager.init_arm@bbd4f6e596
  - cosa.utils.api_resource_manager.reset_arm@ccbbb5b870
  - cosa.utils.gcp_project.parse_env_file@da4de74703
  - cosa.utils.gcp_project.resolve_gcp_location@aada54908b
  - cosa.utils.gcp_project.resolve_gcp_project_id@a5cbca2c7f
  - cosa.utils.util_gcs.gcs_bucket_uri_exists@8853f8e1b2
  - cosa.utils.util_gcs.gcs_uri_to_console_url@6e32866756
  - cosa.utils.util_gcs.read_text_from_gcs@2ce64811b3
  - cosa.utils.util_gcs.validate_gcs_bucket_access@64b62d636e
  - cosa.utils.util_gcs.validate_gcs_credentials@89be809885
  - cosa.utils.util_gcs.write_text_to_gcs@5ba86ec361
---
# GCS text helpers, API resource manager and GCP project lookup

Three helpers in `cosa.utils`. `util_gcs` serves Deep Research report storage, `api_resource_manager` serves the queue status payload, and `gcp_project` serves the Gemini Vertex client.

## What it does
- `write_text_to_gcs( gcs_uri, content, content_type="text/plain", debug=False )` overwrites the blob and returns the uri. `read_text_from_gcs( gcs_uri )` returns the text. A bucket-only uri raises `ValueError`, and a missing SDK raises `RuntimeError`.
- `validate_gcs_credentials()` returns `True` when Application Default Credentials load. `validate_gcs_bucket_access( bucket_uri )` and `gcs_bucket_uri_exists( bucket_uri )` never raise and return `False` when the SDK is missing. `gcs_uri_to_console_url( gcs_uri )` returns a Cloud Console link with the blob path fully percent-encoded, so `/` becomes `%2F`.
- `init_arm()` creates the process-wide `ApiResourceManager` once. `get_arm()` raises `RuntimeError` before `init_arm()`. `reset_arm()` clears it for tests.
- `ApiResourceManager.acquire( provider )` is async. It waits on `WebSearchRateLimiter` for `anthropic_web_search` and returns at once for any other provider. `record_call( provider, tokens=0, latency_ms=0.0 )` records usage for web search only, and `latency_ms` is dropped.
- `get_status()` returns the web-search limiter's status plus `{ "provider_wait_state": "passthrough" }` for `anthropic`, `openai` and `gemini`. The pool-status payload carries it under `api_resource_manager`.
- `parse_env_file( path )` reads a shell env file without running it. A missing file gives `{}`, and a value starting with `$` becomes empty. `resolve_gcp_project_id( environ=None, env_file=None )` reads `LUPIN_GCP_PROJECT_ID` from the environment, then `src/scripts/cloud-run.env`, else raises `RuntimeError`. `resolve_gcp_location()` does the same for `LUPIN_GCP_LOCATION` and falls back to `global`.

## Don't
- Don't treat `validate_gcs_bucket_access` as a write check. It only checks that the bucket exists and can be read.
- Don't expect `acquire` to limit anything but web search. No agent calls the manager yet. `cloud-run.env` is read with `parse_env_file`, never sourced.

## Invariants
- `acquire` and `record_call` import `cosa.agents.deep_research.rate_limiter` lazily, on first web-search use, to avoid an import cycle.
- Project resolution never defaults and never falls back to an API key. The GCS helpers create a new `storage.Client()` on every call.
