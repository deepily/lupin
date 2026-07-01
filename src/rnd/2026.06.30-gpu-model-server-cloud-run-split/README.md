# GPU model-server → Cloud Run (scale-to-zero) split

Carve the stateless GPU inference (Whisper + 2 text encoders) off the always-on
L4 VM and onto a **Cloud Run GPU service that scales to zero**, then downgrade
the VM to **CPU-only**. Dev + test re-point at the Cloud Run endpoint via a
single env var — no app rewrite.

> **No GCP creds in the prep sessions.** Everything here is design +
> dry-runnable prep (Terraform validate/plan, scripts, config, unit tests).
> Nothing applies to GCP until Rick's word + credentials. PUSH stays Rick's.

## Documents

| Doc | What it covers |
|---|---|
| [01-design.md](./01-design.md) | Architecture, Terraform 2-set split, local→cloud "transmogrification", cold-start/dial-to-zero, security, cost, the 3 execution lanes, verification. |
| [02-vm-downgrade-handoff.md](./02-vm-downgrade-handoff.md) | Cross-repo handoff (Lane 3) for `terraforming-vms`: VM `machine_type` `g2-standard-8` → CPU-only, drop L4/`guest_accelerator` + driver bits, with trade-off table, verification, rollback, sequencing, seed TODOs. |
| [03-cost-reprice.md](./03-cost-reprice.md) | Monthly cost re-price of the ruled config (weekday-warm + VM suspend ≈ $527/mo) vs the on-demand baseline ($623) — the CLEAN-WIN verdict. |
| [04-cost-all-paused-floor.md](./04-cost-all-paused-floor.md) | CONTRAST "all-paused floor": Cloud Run scale-to-zero + VM STOPPED 24/7/30d. Floor ≈ $125/mo (Cloud SQL-dominated); NO L4 reservation exists → GPU floor $0; ~$30/mo if Cloud SQL is also stopped. |
| [05-default-paused-terraform-plan.md](./05-default-paused-terraform-plan.md) | Default-paused terraform (PLAN-ONLY): 3 `envs/test` default flips (min=0, both schedulers off), plan = 2 add/0 change/0 destroy, both cost caveats (Cloud SQL 24/7, Cloud NAT) verified clear, + the Cloud SQL `activation_policy` decision. |

## Lupin-repo artifacts (dry prep, Lanes 2+3)

| Artifact | Purpose |
|---|---|
| `src/scripts/cloud-run-model-server-deploy.sh` | Build → push AR → `gcloud run deploy` the GPU model server (L4, scale-to-zero). DRY-by-default; real deploy gated behind `--apply` + creds. |
| `src/scripts/cloud-run-model-server.env.example` | Model-server-specific deploy overrides (min-instances, limits, ingress, secret, model IDs). |
| `docker-compose.cloud-gpu.yml` | Cloud-GPU compose variant: omits the local GPU container, points the app at the Cloud Run URL via `LUPIN_MODEL_SERVER_URL` (the env switch). |
| `src/tests/unit/test_speech_to_text_provider.py` · `test_embedding_provider_carveout.py` | Cloud-https URL-resolution cases — assert the `LUPIN_MODEL_SERVER_URL` env override wins + a `…run.app` URL resolves. |

## The env switch (why no INI edit is needed)

Both `cosa/memory/speech_to_text_provider.py` and
`cosa/memory/embedding_provider.py` resolve the model-server URL via
`_resolve_model_server_url()`, which reads **`LUPIN_MODEL_SERVER_URL` first**,
then the `model server url` INI key. So local→cloud is one env value —
`http://lupin-model-server:7998` → `https://lupin-model-server-XXXX.run.app` —
no `lupin-app.ini` change, no image rebuild.
