# 06 — Apply + With-Creds Green-Bar Verification (2026-07-01)

**Author**: Tiberius 👑 (session b75d199b) · **Status**: ✅ COMPLETE — service live, green-bar passed
**Closes**: `c3fafac5` (apply) · `dde6d45f` (push runbook) · `dab6cdfa` (parent split)

## Outcome

`lupin-model-server` is **live on Cloud Run** (scale-to-zero L4, INTERNAL_ONLY):

- **URL**: `https://lupin-model-server-um6r4fv7nq-uc.a.run.app`
- **Image**: `us-central1-docker.pkg.dev/hello-world-foo-423219/lupin-images/lupin-model-server:0.1.0` (digest `sha256:d9b61e818b1380bd9b112e735d46177c286f4c18efb7abe684d06a1876cfc144`)
- **Apply**: `2 added, 0 changed, 1 destroyed` (service destroy-replace of the tainted image-not-found revision + `allUsers` invoker IAM)
- **Condition**: `Ready=True`; service created in 1m2s

## Green-bar (executed from VPC VM `vms-2025-10-13-2117-28`, dev-vpc/dev-internal-subnet)

| Probe | Result |
|---|---|
| `GET /health` (no-auth) | **200** `{"status":"ready","models_loaded":["whisper","code_rank_embed","nomic_embed_text_v1_5"],"vram_used_mb":2496}` |
| `POST /embeddings/generate` + X-API-Key (Secret Manager `lupin-notification-api-key`) | **200**, `dim=768` |
| `POST /transcribe` + X-API-Key (1s synth WAV → live Whisper) | **200**, text returned |
| `POST /embeddings/generate` with bogus `ck_live_*` key | **401** (auth layer live) |
| `GET /health` from public internet | **404** GFE (INTERNAL_ONLY enforced) |

Arnold's with-creds green-bar spec (#6 true-green gate) satisfied — executed by Tiberius directly (fleet was empty; single-probe scope did not justify a worker spawn).

## Two apply-time bugs found on the way (both invisible to `terraform plan`)

1. **Image-not-found** (pre-existing, known): the AR push had never happened. Fixed by pushing the already-built local `lupin-model-server:0.1.0` (20.1GB) with an ADC-token `docker login`. tfvars pins `model_server_image_tag = "0.1.0"` (no mutable `:latest`).
2. **Subnetwork-not-found (NEW, found this session)**: `model_server_vpc_subnetwork` was never set (default `""`). The module emits the `vpc_access.network_interfaces` block whenever `vpc_network` is non-empty, and the Cloud Run API treats an empty subnetwork as "use the subnet **named like the network**" (`dev-vpc`) — which does not exist. The real us-central1 subnet is **`dev-internal-subnet`** (10.0.1.0/24). Fixed by pinning the short-form self-link in the git-ignored `terraform.tfvars`:
   `model_server_vpc_subnetwork = "projects/hello-world-foo-423219/regions/us-central1/subnetworks/dev-internal-subnet"`

   ⚠️ **Follow-on filed**: `envs/test/variables.tf` describes the empty default as "Empty → no VPC access block", but the module (`modules/cloud-run-model-server/main.tf` `dynamic "vpc_access"`) gates ONLY on `vpc_network` — doc/behavior mismatch that turned a missing var into an apply-time API error instead of a clean skip.

## Notes

- **Cross-repo PGA/DNS worry is empirically moot for this VM**: the run.app URL resolved and was accepted as internal traffic from `vms-2025-10-13-2117-28` with no additional VPC config. Subnet-level PGA on `dev-internal-subnet` evidently suffices; `lupin-host-test` (TERMINATED, still g2-standard-8+L4 — VM downgrade handoff not yet applied) shares the environment and should inherit the same path when started.
- **Cost posture**: min=0 (scale-to-zero) — the warm instance from verification idles back to $0 floor. Default-paused design (Clayton D2) intact.
- **Ledger note**: only ONE command ultimately needed Rick's hands — his mid-session unblock cleared the classifier; docker tag/push + terraform apply then ran under session permissions.
