# WG-1 — Docker image: restore Playwright fonts (12 e2e visual ERRORs)

## Root cause

`docker/lupin/Dockerfile` line 206 runs `python -m playwright install chromium` (no `--with-deps`); the hand-curated apt list at lines 101-114 omits font packages that `--with-deps` previously installed (at minimum `fonts-noto-color-emoji`, `fonts-liberation`, `fonts-freefont-ttf`). Chromium falls back to system defaults → emoji tofu + metric drift → all 12 visual baselines diff.

## Approach

Keep the deterministic hand-curated apt list (preserves the intent of commit 3950d0a, per `feedback_no_auto_promote_tags`). Do NOT revert to `--with-deps`. Authoritatively enumerate the missing fonts and add them.

## Steps

1. Enumerate font packages installed by `--with-deps`:
   ```
   docker run --rm mcr.microsoft.com/playwright:v1.40.0 \
     dpkg -l | grep -E '^ii\s+fonts-' | awk '{print $2}'
   ```
   (Or `playwright install-deps chromium --dry-run` and grep `fonts-`.)
2. Edit `docker/lupin/Dockerfile` lines 101-114 — add the missing font packages to the apt list. Keep the BuildKit cache mount.
3. Build to a candidate tag:
   ```
   docker build -f docker/lupin/Dockerfile -t lupin:1.0.0-fonts .
   ```
4. Smoke-test the candidate locally (optional):
   ```
   docker run --rm lupin:1.0.0-fonts python -m playwright install --dry-run chromium
   ```
5. Bump `docker-compose.yml` lines 34 + 98 to `image: lupin:1.0.0-fonts` on a feature branch.
6. Bounce dev container after queue-empty check: `docker restart lupin-rest-dev` (per `feedback_dev_server_bounce_via_docker`).
7. Regenerate baselines:
   ```
   ./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k visual
   tail -20 /tmp/e2e-ui-latest.log
   ```
8. Re-run e2e visual without `--update-snapshots`:
   ```
   ./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual
   ```
9. Promotion (`lupin:1.0.0-fonts` → `lupin:1.0.0`) is **user-confirmed** — do not automate.

## Acceptance

- `lupin:1.0.0-fonts` builds clean.
- After bump + restart, all 12 visual-baseline pages diff with 0 ERRORs.
- `lupin:1.0.0` tag remains pointing at the pre-rebuild image until user retag.

## Files

- `docker/lupin/Dockerfile` (apt list, ~6 lines added)
- `docker-compose.yml` (2 image-tag bumps; revert at promotion)
- `io/test-suite/visual-baselines/*.png` (12 files regenerated)

## Status

- [ ] Step 1 — enumerate fonts
- [ ] Step 2 — Dockerfile edit
- [ ] Step 3 — build candidate
- [ ] Step 4 — smoke test
- [ ] Step 5 — compose bump
- [ ] Step 6 — bounce dev (USER-COORDINATED)
- [ ] Step 7 — regenerate baselines
- [ ] Step 8 — verification re-run
- [ ] Step 9 — user promotion
