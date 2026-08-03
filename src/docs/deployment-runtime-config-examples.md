# Runtime Configuration Examples - Multi-Environment Docker Deployment

**Date**: 2025-11-15
**Purpose**: Demonstrate runtime environment variable configuration pattern
**Status**: Reference document for deployment workflows

---

## Overview

Lupin uses a **runtime configuration pattern** that enables a single Docker image to be deployed across multiple environments (development, testing, production) without rebuilding.

**Key Principle**: Configuration is selected at **runtime via environment variables**, NOT hardcoded in the Docker image.

---

## How It Works

### ConfigurationManager Environment Variable Support

The `ConfigurationManager` class accepts a special environment variable `LUPIN_CONFIG_MGR_CLI_ARGS` containing space-delimited `key=value` pairs:

```bash
export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"
```

**Format Details**:
- **Space-delimited**: Multiple `key=value` pairs separated by spaces
- **Plus encoding**: `+` is used for spaces in `config_block_id` (e.g., `Lupin:+Development` → `"Lupin: Development"`)
- **Three required keys**: `config_path`, `splainer_path`, `config_block_id`

### Available Configuration Blocks

From `src/conf/lupin-app.ini`:

| Config Block | Storage Backend | Use Case | GCS Bucket |
|--------------|-----------------|----------|------------|
| `Lupin:+Development` | local | Local development | N/A |
| `Lupin:+Testing` | local | Local testing | N/A |
| `Lupin:+Testing-GCS` | gcs | Colleague access deployment | `gs://lupin-lancedb-test/` |
| `Lupin:+Production` | gcs | Production deployment (future) | `gs://lupin-lancedb-prod/` |

---

## Deployment Scenarios

### Scenario 1: Local Development with Docker

**Default Configuration** (uses Dockerfile ENV defaults):

```bash
# Build image
docker build -f docker/lupin/Dockerfile -t lupin:dev .

# Run with defaults (Lupin: Development, local storage)
docker run -p 7999:7999 lupin:dev
```

**Result**: Uses `[Lupin: Development]` config block with local filesystem storage.

---

### Scenario 2: Local Testing with GCS Backend

**Override at Runtime** (test GCS integration locally):

```bash
# Build image (same as scenario 1)
docker build -f docker/lupin/Dockerfile -t lupin:dev .

# Run with Testing-GCS config block
docker run -p 7999:7999 \
  -e LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing-GCS" \
  -v ~/.config/gcloud:/root/.config/gcloud \
  lupin:dev
```

**Result**: Uses `[Lupin: Testing-GCS]` config block with GCS storage (`gs://lupin-lancedb-test/`).

**Note**: GCS credentials mounted from local `~/.config/gcloud` directory.

---

### Scenario 3: Cloud Run Testing Deployment (Current Goal)

**Automated Deployment** (for colleague access):

```bash
# Build image once
./src/scripts/cloud-run-build.sh latest

# Deploy: the monolith cloud-run-deploy.sh path was RETIRED (2026-07-11).
# Deploy via terraform instead: cd src/terraform/envs/test && terraform apply
```

**Manual Deployment** (using gcloud directly):

```bash
# Build and push
docker build -f docker/lupin/Dockerfile -t gcr.io/hello-world-foo-423219/lupin:latest .
docker push gcr.io/hello-world-foo-423219/lupin:latest

# Deploy with testing config
gcloud run deploy lupin-test \
  --project=hello-world-foo-423219 \
  --region=us-central1 \
  --image=gcr.io/hello-world-foo-423219/lupin:latest \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=2Gi \
  --cpu=1 \
  --timeout=300 \
  --min-instances=1 \
  --max-instances=1 \
  --set-env-vars="LUPIN_ROOT=/app,LUPIN_ENV=testing,LUPIN_CONFIG_MGR_CLI_ARGS=config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing-GCS"
```

**Result**: Cloud Run deployment using `[Lupin: Testing-GCS]` with `gs://lupin-lancedb-test/` bucket.

---

### Scenario 4: Cloud Run Production Deployment (Future)

**Automated Deployment** (same image, different config):

```bash
# Use SAME image built in scenario 3
# cloud-run-deploy.sh RETIRED (2026-07-11) — deploy via terraform
# (src/terraform/envs/test) with the production tfvars.
```

**Manual Deployment**:

```bash
# Use SAME image from testing deployment
gcloud run deploy lupin-prod \
  --project=hello-world-foo-423219 \
  --region=us-central1 \
  --image=gcr.io/hello-world-foo-423219/lupin:latest \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=4Gi \
  --cpu=2 \
  --timeout=600 \
  --min-instances=1 \
  --max-instances=10 \
  --set-env-vars="LUPIN_ROOT=/app,LUPIN_ENV=production,LUPIN_CONFIG_MGR_CLI_ARGS=config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Production"
```

**Result**: Production deployment using `[Lupin: Production]` with `gs://lupin-lancedb-prod/` bucket.

---

## Benefits of This Approach

### ✅ Single Image, Multiple Environments

- Build Docker image **once**
- Deploy to dev/test/prod by changing **only** environment variables
- No image rebuilds required for environment switches

### ✅ No Hardcoded Configuration

- Dockerfile sets **defaults** (local development)
- Runtime overrides via `-e` flag (docker) or `--set-env-vars` (Cloud Run)
- Configuration remains flexible and testable

### ✅ Local Development Workflow Preserved

- `docker run` without flags → uses Development config
- No extra configuration needed for local development
- Backward compatible with existing workflows

### ✅ Easy Environment Promotion

- Test in `testing` environment with `Testing-GCS` config
- Promote same image to `production` with `Production` config
- Identical code/dependencies across environments

---

## Configuration Block Differences

### Development vs Testing-GCS vs Production

| Feature | Development | Testing-GCS | Production |
|---------|-------------|-------------|------------|
| **Storage Backend** | local | gcs | gcs |
| **Database Path** | `/src/conf/.../lupin.lancedb` | `gs://lupin-lancedb-test/` | `gs://lupin-lancedb-prod/` |
| **Warm-up Routine** | false | false | true |
| **Use Case** | Local dev | Colleague testing | Production users |
| **Scale** | Single developer | <100 users | Unlimited |
| **Data Persistence** | Ephemeral (container) | Persistent (GCS) | Persistent (GCS) |

---

## Troubleshooting

### Issue: Wrong config block loaded

**Symptoms**: Application uses unexpected storage backend or paths

**Diagnosis**:
```bash
# Check environment variables inside running container
docker exec <container_id> env | grep LUPIN

# Or in Cloud Run logs
gcloud run services logs read lupin-test --limit=20 | grep "Config block"
```

**Solution**: Verify `LUPIN_CONFIG_MGR_CLI_ARGS` environment variable is set correctly.

---

### Issue: GCS bucket access denied

**Symptoms**: `403 Forbidden` errors when accessing LanceDB on GCS

**Diagnosis**:
```bash
# Check Cloud Run service account permissions
PROJECT_NUMBER=$(gcloud projects describe hello-world-foo-423219 --format='value(projectNumber)')
SERVICE_ACCOUNT="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

# Verify bucket IAM policy
gcloud storage buckets get-iam-policy gs://lupin-lancedb-test
```

**Solution**: Grant storage permissions to Cloud Run service account:
```bash
# Use gcloud storage (NOT gsutil - see Python environment conflict issue below)
gcloud storage buckets add-iam-policy-binding gs://lupin-lancedb-test \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/storage.objectViewer"

gcloud storage buckets add-iam-policy-binding gs://lupin-lancedb-test \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/storage.objectCreator"
```

---

### Issue: gsutil commands fail with Python environment error

**Symptoms**: `gsutil iam ch` commands fail with:
```
TypeError: cannot set 'is_timeout' attribute of immutable type 'TimeoutError'
```

**Root Cause**: The project's `.venv` contains eventlet which conflicts with gsutil's Python dependencies (known Python 3.11 compatibility issue).

**Solution**: Use `gcloud storage` commands instead of `gsutil`:
```bash
# WRONG (causes Python conflict)
gsutil iam ch serviceAccount:$SERVICE_ACCOUNT:roles/storage.objectViewer gs://bucket/

# CORRECT (no Python conflicts)
gcloud storage buckets add-iam-policy-binding gs://bucket/ \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/storage.objectViewer"
```

**Alternative**: If you must use gsutil, run from outside project directory:
```bash
cd /tmp
gsutil iam ch serviceAccount:$SERVICE_ACCOUNT:roles/storage.objectViewer gs://lupin-lancedb-test/
cd -
```

---

### Issue: Local development broken after changes

**Symptoms**: `docker run` without flags no longer works

**Diagnosis**: Check Dockerfile ENV defaults:
```bash
grep "LUPIN_CONFIG_MGR_CLI_ARGS" docker/lupin/Dockerfile
```

**Solution**: Dockerfile should have:
```dockerfile
env LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"
```

---

## Reference Commands

### Build Multi-Environment Image

```bash
# Build once, use everywhere
docker build -f docker/lupin/Dockerfile -t lupin:latest .
```

### Run with Different Configs

```bash
# Development (default)
docker run -p 7999:7999 lupin:latest

# Testing with local storage
docker run -p 7999:7999 \
  -e LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing" \
  lupin:latest

# Testing with GCS storage
docker run -p 7999:7999 \
  -e LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing-GCS" \
  -v ~/.config/gcloud:/root/.config/gcloud \
  lupin:latest
```

### Deploy to Cloud Run

```bash
# cloud-run-deploy.sh RETIRED (2026-07-11, monolith-on-Cloud-Run path).
# Deploy via terraform instead:
#   cd src/terraform/envs/test && terraform apply   # testing (prod: production tfvars)
```

---

## See Also

- **Dockerfile**: `docker/lupin/Dockerfile` - Contains runtime configuration documentation
- **Deployment Scripts**:
  - `src/scripts/cloud-run-build.sh` - Build multi-environment image
  - Deploy: `src/terraform/envs/test` (terraform) — `cloud-run-deploy.sh` retired 2026-07-11 (monolith-on-Cloud-Run path)
- **Configuration File**: `src/conf/lupin-app.ini` - Defines all config blocks
- **ConfigurationManager**: `src/cosa/config/configuration_manager.py` - Handles env var parsing

---

## Version History

- **2025-11-15**: Created documentation for runtime configuration pattern
