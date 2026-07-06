# docs/DEPLOYMENT.md

> How to deploy Suitest OSS in 3 modes: single-host docker-compose, standalone all-in-one container, and Helm chart for k8s production. For architecture context read [ARCHITECTURE.md](./ARCHITECTURE.md). For capability tiers (ZERO/LOCAL/CLOUD) read [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md).
>
> ℹ️ **Built today:** the §1.1 quickstart, the compose stack (`infra/docker/docker-compose.yml` — the authoritative file; web on **3000**, API on **4000**, tag pinned via `SUITEST_IMAGE_TAG`), the all-in-one image `ghcr.io/suiflex/suitest`, and the in-repo chart `infra/helm/suitest` (no migration hook — see the docs-site Kubernetes guide). The annotated YAML/env excerpts and the OCI-chart/HPA sections below are the M3–M4 **target spec** and diverge from the shipped files in places (port numbers, `SUITEST_VERSION`, `SUITEST_LLM_*`). Note: the shipped platform has **no `SUITEST_LLM_*` env vars** — the LLM is configured per workspace in the web UI.
>
> The fastest local install is not compose at all: `npx @suiflex/suitest onboard` boots the whole platform on SQLite in one command (see `packages/suitest-npx/README.md`).

---

## 0. Choose your mode

| Mode | Audience | Effort | Scale | Air-gapped |
|------|----------|--------|-------|------------|
| **Compose** | Self-host VPS, homelab, small team (<50 users) | 5 minutes | 1 host, vertical | yes |
| **Standalone** | Demo / hobby / "try in 1 command" | 1 minute | 1 container, ≤10 users | yes |
| **Helm (k8s)** | Production, multi-tenant, multi-region | 30 minutes | horizontal autoscale | yes |

Default tier for all modes = **ZERO** (runs without an LLM). Upgrade to LOCAL/CLOUD by configuring an LLM provider per workspace in the web UI (Settings → LLM) — not via env vars. The [§5 tier matrix](#5-tier-specific-environment-matrix) describes the older env-based dial (spec only).

---

## 1. Mode 1 — Single-host docker-compose

### 1.1 5-minute quickstart

```bash
git clone https://github.com/suiflex/suitest.git
cd suitest
cp .env.example .env                        # default ZERO tier; set secrets + superadmin
make docker-up                              # pulls prebuilt ghcr.io/suiflex/suitest-* images + boots
open http://localhost:3000
```

Migrations run automatically (the one-shot `migrate` service). App images are
prebuilt on GHCR per `images-v*` release; `SUITEST_IMAGE_TAG=<version>` pins
one, `make docker-up-prod` builds from source instead. Log in with the
`SUITEST_SUPERADMIN_EMAIL` / `SUITEST_SUPERADMIN_PASSWORD` you set in `.env`.

### 1.2 `docker-compose.yml` (annotated)

```yaml
version: "3.9"

x-suitest-env: &suitest-env
  DATABASE_URL: postgresql+asyncpg://suitest:${POSTGRES_PASSWORD}@postgres:5432/suitest
  REDIS_URL: redis://redis:6379/0
  SUITEST_AUTH_SECRET: ${SUITEST_AUTH_SECRET}
  SUITEST_ENCRYPTION_KEY: ${SUITEST_ENCRYPTION_KEY}
  SUITEST_S3_ENDPOINT: http://minio:9000
  SUITEST_S3_BUCKET: ${SUITEST_S3_BUCKET:-suitest-runs}
  SUITEST_S3_ACCESS_KEY: ${SUITEST_S3_ACCESS_KEY:-minioadmin}
  SUITEST_S3_SECRET_KEY: ${SUITEST_S3_SECRET_KEY:-minioadmin}
  SUITEST_LLM_PROVIDER: ${SUITEST_LLM_PROVIDER:-none}
  SUITEST_LLM_API_KEY: ${SUITEST_LLM_API_KEY:-}
  SUITEST_LLM_MODEL: ${SUITEST_LLM_MODEL:-}
  SUITEST_LLM_BASE_URL: ${SUITEST_LLM_BASE_URL:-}

services:
  web:
    image: ghcr.io/suiflex/suitest-web:${SUITEST_VERSION:-latest}
    profiles: ["zero", "cloud", "local"]
    ports: ["8080:80"]
    depends_on:
      api: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost/healthz"]
      interval: 30s

  api:
    image: ghcr.io/suiflex/suitest-api:${SUITEST_VERSION:-latest}
    profiles: ["zero", "cloud", "local"]
    environment: *suitest-env
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_started }
      minio: { condition: service_healthy }
    ports: ["8000:8000"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      start_period: 30s

  runner:
    image: ghcr.io/suiflex/suitest-runner:${SUITEST_VERSION:-latest}
    profiles: ["zero", "cloud", "local"]
    environment: *suitest-env
    depends_on:
      api: { condition: service_healthy }
    deploy:
      replicas: 2

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: suitest
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: suitest
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "suitest"]
      interval: 10s

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes: ["redisdata:/data"]

  minio:
    image: minio/minio:latest
    command: ["server", "/data", "--console-address", ":9001"]
    environment:
      MINIO_ROOT_USER: ${SUITEST_S3_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${SUITEST_S3_SECRET_KEY:-minioadmin}
    volumes: ["miniodata:/data"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/ready"]

  # ── LOCAL tier add-on (opt-in via --profile local) ─────────────────────
  ollama:
    image: ollama/ollama:latest
    profiles: ["local"]
    volumes: ["ollamadata:/root/.ollama"]
    ports: ["11434:11434"]
    # set SUITEST_LLM_PROVIDER=ollama
    # set SUITEST_LLM_BASE_URL=http://ollama:11434

volumes:
  pgdata:
  redisdata:
  miniodata:
  ollamadata:

networks:
  default:
    name: suitest
```

### 1.3 Profile flags per tier

| Tier | Command | Container set |
|------|---------|---------------|
| ZERO | `make docker-up` (= `docker compose -f infra/docker/docker-compose.yml --profile zero up -d`) | web, api, runner, postgres, redis, minio |
| CLOUD | `make docker-up-cloud` | same as ZERO (no extra container; configure the provider in the web UI) |
| LOCAL | `make docker-up-local` | + `ollama` container |

Tip: the container set is (almost) the same across tiers — the tier is raised per workspace from the web UI (Settings → LLM), not by editing `.env`.

If you want Langfuse for LLM observability, run it from [Langfuse's own compose file](https://github.com/langfuse/langfuse) and point the OTEL/Langfuse env of `api`/`runner` at it — it is not bundled in Suitest's compose stack.

### 1.4 `.env.example` excerpt (ZERO default)

```env
# === Required ===
POSTGRES_PASSWORD=suitest
SUITEST_AUTH_SECRET=replace-with-32-char-random-hex
SUITEST_ENCRYPTION_KEY=replace-with-base64-32-byte-key

# === Super-admin bootstrap (first-install login) ===
SUITEST_SUPERADMIN_EMAIL=
SUITEST_SUPERADMIN_PASSWORD=
SUITEST_SUPERADMIN_WORKSPACE_NAME=Default Workspace
```

There is no LLM env dial: the tier is upgraded per workspace from the web UI
(Settings → LLM), and the key is stored AES-GCM encrypted in the database.

### 1.5 Reverse proxy & TLS

Production compose: add `traefik` or `caddy` in front as the TLS terminator. Example with Caddy:

```caddy
suitest.example.com {
  reverse_proxy /api/* api:4000
  reverse_proxy /ws/*  api:4000
  reverse_proxy /sse/* api:4000
  reverse_proxy        web:80
}
```

WebSocket & SSE are forwarded to `api` (handles the `Upgrade` header).

---

## 2. Mode 2 — Docker standalone (all-in-one)

For hobbyists / demos. A single image runs `api` + `runner` + nginx serving `web`, via `supervisord`. Postgres + Redis stay external (do not put them in one image — data is lost on restart).

### 2.1 One-command try

```bash
docker run --rm -p 3000:80 \
  -e SUITEST_DATABASE_URL=postgresql+asyncpg://u:p@your-pg-host/suitest \
  -e SUITEST_REDIS_URL=redis://your-redis-host:6379/0 \
  -e SUITEST_AUTH_SECRET=$(openssl rand -hex 32) \
  -e SUITEST_ENCRYPTION_KEY=$(openssl rand -base64 32) \
  ghcr.io/suiflex/suitest:latest
```

### 2.2 Image internals (informational)

```
ghcr.io/suiflex/suitest        (infra/docker/Dockerfile.suitest)
├── supervisord.suitest.conf
│   ├── api      ← uvicorn --factory suitest_api.main:create_app --port 4000
│   ├── runner   ← arq suitest_runner.worker.WorkerSettings
│   └── nginx    ← serve the web dist on :80, proxy /api → :4000
└── (EXPOSE 80 4000)
```

### 2.3 Use cases & caveats

- ✅ Quick demo, internal POC, screencast.
- ✅ Air-gapped trial (image self-contained).
- ❌ Not for production — single point of failure, no horizontal scale.
- ❌ No local LLM bundled — set `SUITEST_LLM_*` to an external endpoint if you want CLOUD/LOCAL.
- ⚠️ External Postgres must have the `pgvector` extension (`CREATE EXTENSION vector`).

---

## 3. Mode 3 — Helm chart (k8s production)

### 3.1 Chart structure

```
infra/helm/suitest/
├── Chart.yaml
├── values.yaml                      ← default values (see §3.2)
├── values-zero.yaml                 ← preset ZERO tier
├── values-cloud.yaml                ← preset CLOUD tier
├── values-local.yaml                ← preset LOCAL tier (in-cluster Ollama)
└── templates/
    ├── _helpers.tpl
    ├── configmap.yaml
    ├── secret.yaml
    ├── web-deployment.yaml
    ├── web-service.yaml
    ├── web-ingress.yaml
    ├── api-deployment.yaml
    ├── api-service.yaml
    ├── api-hpa.yaml
    ├── api-pdb.yaml
    ├── runner-deployment.yaml
    ├── runner-hpa.yaml
    ├── runner-pdb.yaml
    ├── postgres-statefulset.yaml    ← opt-in, default external
    ├── redis-statefulset.yaml       ← opt-in, default external
    ├── minio-statefulset.yaml       ← opt-in, default external
    ├── migration-job.yaml           ← init container / pre-upgrade hook
    ├── networkpolicy.yaml
    └── serviceaccount.yaml
```

### 3.2 `values.yaml` schema (annotated)

```yaml
suitest:
  version: "1.0.0"
  tier: zero                          # zero | cloud | local
  autonomyDefault: manual             # manual | assist | semi_auto | auto

image:
  registry: ghcr.io/suitest-dev
  pullPolicy: IfNotPresent
  pullSecrets: []                     # for private registry / air-gapped

llm:
  provider: none                      # none | anthropic | openai | ollama | ...
  model: ""
  baseUrl: ""
  apiKeySecretRef:                    # reference, never inline
    name: suitest-llm
    key: api-key

web:
  replicaCount: 2
  resources:
    requests: { cpu: 50m, memory: 64Mi }
    limits:   { cpu: 200m, memory: 128Mi }

api:
  replicaCount: 3
  hpa:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
  resources:
    requests: { cpu: 200m, memory: 512Mi }
    limits:   { cpu: 1000m, memory: 1Gi }
  podDisruptionBudget:
    minAvailable: 1

runner:
  replicaCount: 2
  hpa:
    enabled: true
    minReplicas: 1
    maxReplicas: 12
    metrics:
      - type: External
        external:
          metric: { name: suitest_runs_queue_depth }
          target: { type: AverageValue, averageValue: "10" }
  resources:
    requests: { cpu: 500m, memory: 1Gi }
    limits:   { cpu: 2000m, memory: 4Gi }

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: suitest.example.com
      paths: [{ path: /, pathType: Prefix }]
  tls:
    - secretName: suitest-tls
      hosts: [suitest.example.com]

postgres:
  embedded: false                     # true → deploy in-chart StatefulSet
  external:
    host: postgres.db.svc
    port: 5432
    database: suitest
    userSecretRef: { name: suitest-pg, key: user }
    passwordSecretRef: { name: suitest-pg, key: password }

redis:
  embedded: false
  external:
    url: redis://redis.cache.svc:6379/0

s3:
  embedded: false                     # true → deploy MinIO StatefulSet
  external:
    endpoint: https://s3.us-east-1.amazonaws.com
    bucket: suitest-runs
    credentialsSecretRef: { name: suitest-s3 }

persistence:
  postgres: { size: 50Gi, storageClass: gp3 }
  redis:    { size: 5Gi,  storageClass: gp3 }
  minio:    { size: 200Gi, storageClass: gp3 }

probes:
  api:
    liveness:  { path: /health, periodSeconds: 30 }
    readiness: { path: /ready,  periodSeconds: 10 }
  web:
    liveness:  { path: /healthz, periodSeconds: 30 }

networkPolicy:
  enabled: true
  egress:
    allowLLM: true                    # set false for air-gap (except LOCAL)
    allowExternalIntegrations: true   # jira/linear/slack/github

observability:
  otlpEndpoint: ""
  sentryDsnSecretRef: ""
  prometheusScrape: true

migrations:
  runAsJob: true                      # (spec) migration Job — the shipped chart has no hook; run alembic manually
```

### 3.3 Install

The chart ships in-repo (no published OCI/chart repo yet):

```bash
helm install suitest infra/helm/suitest -f infra/helm/suitest/values.yaml
# air-gapped (LOCAL tier via in-cluster Ollama):
helm install suitest infra/helm/suitest -f infra/helm/suitest/values-airgapped.yaml
```

Upgrade:

```bash
helm upgrade suitest infra/helm/suitest -f infra/helm/suitest/values.yaml
# the chart has no migration hook: run `alembic upgrade head` against the
# database first, using the same API image the chart deploys
```

### 3.4 HPA detail

The runner is scaled based on `suitest_runs_queue_depth` (a gauge from the `api` `/metrics`). Requires `prometheus-adapter` or KEDA. KEDA example:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: suitest-runner }
spec:
  scaleTargetRef: { name: suitest-runner }
  minReplicaCount: 1
  maxReplicaCount: 12
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring.svc:9090
        metricName: suitest_runs_queue_depth
        threshold: "10"
        query: max(suitest_runs_queue_depth)
```

### 3.5 Probes

| Pod | Liveness | Readiness | Startup |
|-----|----------|-----------|---------|
| api | `GET /health` | `GET /ready` (DB+Redis+S3 check) | 60s grace |
| runner | TCP 8080 (built-in healthz) | TCP + Redis ping | 30s |
| web | `GET /healthz` | `GET /healthz` | 10s |

### 3.6 PodDisruptionBudget

Default `minAvailable: 1` for `api` and `runner`. Override via `values.yaml`.

### 3.7 NetworkPolicy

Default rules:

| Source | Dest | Allowed |
|--------|------|---------|
| web | api | TCP/8000 |
| api | postgres / redis / minio | yes |
| api | LLM provider (egress) | controlled by `networkPolicy.egress.allowLLM` |
| api | integrations (jira/linear/slack/github) | controlled by `allowExternalIntegrations` |
| runner | api | TCP/8000 (callback) |
| runner | MCP server pods | yes |
| runner | LLM provider (egress) | controlled by `allowLLM` |

**Air-gapped**: set `tier=zero`, `networkPolicy.egress.allowLLM=false`, and use an internal image registry via `image.pullSecrets`.

---

## 4. Operations

### 4.1 Backup strategy

| Layer | Strategy | Frequency |
|-------|----------|-----------|
| Postgres | `pg_dump --format=custom` to S3 / object storage | every 6 hours |
| Postgres WAL | wal-g / pgbackrest (streaming) | continuous |
| MinIO artifacts | `mc mirror` to remote bucket | every 24 hours |
| Encryption key | sealed-secrets / external KMS — **off-cluster** | manual rotate ≥ 90 days |

Example CronJob (k8s):

```yaml
apiVersion: batch/v1
kind: CronJob
metadata: { name: suitest-pgbackup }
spec:
  schedule: "0 */6 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: dump
              image: postgres:16
              command: ["/bin/sh", "-c"]
              args:
                - |
                  pg_dump $DATABASE_URL --format=custom \
                    | aws s3 cp - s3://suitest-backup/pg/$(date +%F-%H).dump
              envFrom: [{ secretRef: { name: suitest-backup-env }}]
```

### 4.2 Restore drill

1. Provision fresh cluster / namespace.
2. Restore Postgres: `pg_restore --clean --if-exists -d $DATABASE_URL <dump>`.
3. Restore MinIO: `mc mirror s3://remote/ minio/local/`.
4. Apply the same `SUITEST_ENCRYPTION_KEY` Secret (without it, encrypted LLM configs are unreadable).
5. Helm install with the exact same version (version mismatch → alembic may be downgrade-blocked).
6. Smoke: log in → open an old run → verify artifacts can be downloaded.
7. Run Suitest's own smoke suite (dogfood).

The drill is **mandatory quarterly** for production.

### 4.3 Upgrade path

| Step | Action |
|------|------|
| 1 | Read CHANGELOG, check breaking changes (data model, env var renames) |
| 2 | `helm diff upgrade` for a preview |
| 3 | Migrations: run `alembic upgrade head` before the upgrade (the shipped chart has no Helm hook) |
| 4 | Blue/green for `api`: new ReplicaSet rolling, old drains |
| 5 | `runner` rolling — long-running jobs are drained via `SIGTERM` with `90s` grace |
| 6 | Verify `/capabilities` for a tier mismatch (in case a provider was swapped unintentionally) |
| 7 | Rollback: `helm rollback suitest <revision>` — downgrade-safe migrations only |

### 4.4 Resource sizing guidance

| Profile | Active user | Concurrent runs | Postgres | Redis | Runner replicas | API replicas |
|---------|-------------|-----------------|----------|-------|-----------------|--------------|
| Small | ≤25 | ≤5 | 2 vCPU / 4Gi / 20Gi | 1Gi | 1–2 | 2 |
| Medium | 25–250 | 5–25 | 4 vCPU / 16Gi / 100Gi | 4Gi | 2–6 | 3–5 |
| Large | 250–2000 | 25–200 | 8 vCPU / 64Gi / 500Gi + replica | 16Gi | 4–20 | 5–15 |

Note: LLM cost scales linearly with run volume in CLOUD tier — set a budget guard in Settings → LLM (v1.x).

### 4.5 Concurrency & MCP pool tuning

Five env vars drive the runner's parallelism and the MCP layer's fair-queue backpressure. Set them per replica via Helm `values.yaml` or per process via `.env`.

| Env var | Default | Description |
|---------|---------|-------------|
| `SUITEST_RUNNER_CONCURRENCY` | `4` | Number of ARQ jobs the runner executes in parallel per worker process. Scale horizontally by increasing runner replicas; scale vertically by raising this. Aliased by the legacy `SUITEST_RUNNER_MAX_JOBS_CONCURRENT`. |
| `SUITEST_RUNNER_MAX_RETRIES` | `2` | Per-job ARQ retry budget. ARQ re-enqueues a coroutine up to this many times on transient failure before marking the job failed. |
| `SUITEST_RUNNER_JOB_TIMEOUT_SECONDS` | `1800` | Hard wall-clock budget for one `run_test_case` invocation. Long E2E suites set this higher; per-step timeouts are enforced separately at the MCP provider level (`call_timeout_seconds`). |
| `SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE` | `16` | Per-workspace ceiling on concurrent MCP sessions across all providers. Enforced via a fair FIFO `asyncio.Condition` queue (see [MCP_PLUGINS.md § 8](./MCP_PLUGINS.md)). |
| `SUITEST_MCP_QUEUE_TIMEOUT_SECONDS` | `30` | How long an MCP acquire may wait for a workspace slot before raising `McpPoolExhausted` (surfaced as step error `reason=POOL_EXHAUSTED`). |

Rule of thumb: per replica, `SUITEST_RUNNER_CONCURRENCY × average_steps_per_run` should not exceed `SUITEST_MCP_MAX_SESSIONS_PER_WORKSPACE` when all runs target the same workspace, or the queue will routinely back up. Multi-tenant deployments are fine with much higher concurrency because the cap is *per-workspace*.

---

## 5. Tier-specific environment matrix

| Variable | ZERO (default) | LOCAL | CLOUD |
|----------|----------------|-------|-------|
| `SUITEST_LLM_PROVIDER` | `none` | `ollama` / `llamacpp` / `vllm` / `lmstudio` | `anthropic` / `openai` / `gemini` / `groq` / `openrouter` / `azure` / `bedrock` / `vertex` / `deepseek` |
| `SUITEST_LLM_API_KEY` | empty | empty (or an internal token) | required |
| `SUITEST_LLM_MODEL` | empty | `ollama/llama3.1` | provider-specific |
| `SUITEST_LLM_BASE_URL` | empty | `http://ollama:11434` | optional (Azure / OpenAI-compat) |
| Extra service | — | `ollama` container / external | — (use SaaS) |
| Egress required | NO (air-gap OK) | NO (in-cluster LLM) | YES (LLM API) |
| AI features | OFF | ON | ON |
| Compose profile | `--profile zero` | `--profile local` | `--profile cloud` |
| Helm values preset | `values-zero.yaml` | `values-local.yaml` | `values-cloud.yaml` |

Behavior detail per tier (endpoints, validation, runner decision tree): [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md).

### 5.1 LOCAL LLM backend compatibility for k8s production deploy

Not every LOCAL backend can be packaged as a server-side container. Picking the right backend matters for Helm/Kubernetes deploys:

| Backend | Containerizable | Recommended for prod |
|---------|:--------------:|:--------------------:|
| Ollama | ✓ (official Docker image `ollama/ollama`) | ✓ — CPU or GPU node, simplest default |
| vLLM | ✓ (official Docker image `vllm/vllm-openai`, requires GPU) | ✓ — GPU node pool, highest throughput |
| llama.cpp | ✓ (server mode `ggerganov/llama.cpp:server`) | ✓ — CPU-only edge, lightweight |
| LM Studio | ✗ (desktop GUI app, no headless container) | ✗ — dev/laptop only |

For production LOCAL tier, use **Ollama** (CPU/GPU) or **vLLM** (GPU); **llama.cpp** is also valid for CPU-only edge deploys. **LM Studio** works for dev but is **not deployable to k8s** due to lack of a headless container — leave it for local laptop experimentation and switch to Ollama/vLLM before deploying. The Helm chart's `values-local.yaml` preset ships with Ollama in-cluster by default ([§3.1](#31-chart-structure)).

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| API container restart loop | `SUITEST_ENCRYPTION_KEY` has the wrong length | Regenerate via `openssl rand -base64 32` |
| `GET /capabilities` always ZERO even with env set | Forgot to restart `api` after editing `.env` | `docker compose restart api runner` |
| Runner queue piling up | HPA not connected / `runs_queue_depth` metric empty | Check that the Prometheus scrape `/metrics` is reachable |
| Alembic upgrade fails | `pgvector` extension not created yet | `CREATE EXTENSION IF NOT EXISTS vector;` as superuser |
| LLM call timeout on LOCAL | Ollama has not pulled the model yet | `docker compose exec ollama ollama pull llama3.1` |
| WS keeps disconnecting | Ingress timeout < 60s | Set `nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"` |

---

## 7. Cross-references

- Services architecture → [ARCHITECTURE.md](./ARCHITECTURE.md)
- Tier semantics → [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md)
