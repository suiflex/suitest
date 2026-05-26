# docs/DEPLOYMENT.md

> Cara deploy Suitest OSS di 3 mode: single-host docker-compose, standalone all-in-one container, dan Helm chart untuk k8s production. Untuk konteks arsitektur baca [ARCHITECTURE.md](./ARCHITECTURE.md). Untuk capability tier (ZERO/LOCAL/CLOUD) baca [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md). Design rationale: [design memo](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md).

---

## 0. Choose your mode

| Mode | Audience | Effort | Skala | Air-gapped |
|------|----------|--------|-------|------------|
| **Compose** | Self-host VPS, homelab, small team (<50 user) | 5 menit | 1 host, vertikal | ya |
| **Standalone** | Demo / hobby / "try in 1 command" | 1 menit | 1 container, ≤10 user | ya |
| **Helm (k8s)** | Production, multi-tenant, multi-region | 30 menit | horizontal autoscale | ya |

Default tier semua mode = **ZERO** (jalan tanpa LLM). Upgrade ke LOCAL/CLOUD dgn set env. Lihat [§5 tier matrix](#5-tier-specific-environment-matrix).

---

## 1. Mode 1 — Single-host docker-compose

### 1.1 5-minute quickstart

```bash
git clone https://github.com/suitest-dev/suitest.git
cd suitest
cp .env.example .env                        # default ZERO tier
docker compose --profile zero up -d
docker compose exec api alembic upgrade head
docker compose exec api python -m packages.db.seed
open http://localhost:8080
```

Login sebagai `admin@example.com` / `changeme`. Ganti password segera.

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
  SUITEST_EMBEDDINGS_BACKEND: ${SUITEST_EMBEDDINGS_BACKEND:-none}

services:
  web:
    image: ghcr.io/suitest-dev/suitest-web:${SUITEST_VERSION:-latest}
    profiles: ["zero", "cloud", "local"]
    ports: ["8080:80"]
    depends_on:
      api: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost/healthz"]
      interval: 30s

  api:
    image: ghcr.io/suitest-dev/suitest-api:${SUITEST_VERSION:-latest}
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
    image: ghcr.io/suitest-dev/suitest-runner:${SUITEST_VERSION:-latest}
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
| ZERO | `docker compose --profile zero up -d` | web, api, runner, postgres, redis, minio |
| CLOUD | `docker compose --profile cloud up -d` | sama dgn ZERO + env LLM provider di-set (no extra container) |
| LOCAL | `docker compose --profile local up -d` | + container `ollama` |

Tip: CLOUD tier hanya butuh env diff, image sama persis. Restart `api` + `runner` setelah edit `.env`.

### 1.4 `.env.example` excerpt (ZERO default)

```env
# === Required ===
POSTGRES_PASSWORD=changeme
SUITEST_AUTH_SECRET=replace-with-32-char-random
SUITEST_ENCRYPTION_KEY=replace-with-base64-32-byte-key

# === Tier dial (ZERO default) ===
SUITEST_LLM_PROVIDER=none
SUITEST_LLM_API_KEY=
SUITEST_LLM_MODEL=
SUITEST_EMBEDDINGS_BACKEND=none

# === To upgrade to CLOUD (uncomment) ===
# SUITEST_LLM_PROVIDER=anthropic
# SUITEST_LLM_API_KEY=sk-ant-...
# SUITEST_LLM_MODEL=claude-sonnet-4-5
# SUITEST_EMBEDDINGS_BACKEND=openai
# SUITEST_EMBEDDINGS_MODEL=text-embedding-3-small
# OPENAI_API_KEY=sk-...   # untuk embeddings backend

# === To upgrade to LOCAL (uncomment + use --profile local) ===
# SUITEST_LLM_PROVIDER=ollama
# SUITEST_LLM_BASE_URL=http://ollama:11434
# SUITEST_LLM_MODEL=ollama/llama3.1
# SUITEST_EMBEDDINGS_BACKEND=fastembed
```

### 1.5 Reverse proxy & TLS

Production compose: tambah `traefik` atau `caddy` di-front sebagai TLS terminator. Contoh dgn Caddy:

```caddy
suitest.example.com {
  reverse_proxy /api/* api:8000
  reverse_proxy /ws/*  api:8000
  reverse_proxy /sse/* api:8000
  reverse_proxy        web:80
}
```

WebSocket & SSE diteruskan ke `api` (handle `Upgrade` header).

---

## 2. Mode 2 — Docker standalone (all-in-one)

Untuk hobbyist / demo. Single image jalan `api` + `runner` + nginx serving `web`, via `supervisord`. Postgres + Redis tetap eksternal (jangan satu image — data hilang saat restart).

### 2.1 One-command try

```bash
docker run --rm -p 8080:80 \
  -e DATABASE_URL=postgresql+asyncpg://u:p@your-pg-host/suitest \
  -e REDIS_URL=redis://your-redis-host:6379/0 \
  -e SUITEST_AUTH_SECRET=$(openssl rand -hex 32) \
  -e SUITEST_ENCRYPTION_KEY=$(openssl rand -base64 32) \
  ghcr.io/suitest-dev/suitest-standalone:latest
```

### 2.2 Image internals (informational)

```
ghcr.io/suitest-dev/suitest-standalone
├── /etc/supervisor/conf.d/
│   ├── api.conf           ← uvicorn apps.api.main:app --port 8000 --workers 2
│   ├── runner.conf        ← arq apps.runner.worker.WorkerSettings
│   └── nginx.conf         ← serve /var/www/web on :80, proxy /api → :8000
├── /opt/suitest/          ← installed Python wheel
└── /var/www/web/          ← built SPA dist
```

### 2.3 Use cases & caveats

- ✅ Quick demo, internal POC, screencast.
- ✅ Air-gapped trial (image self-contained).
- ❌ Tidak untuk production — single point of failure, no horizontal scale.
- ❌ Tidak ada local LLM bundled — set `SUITEST_LLM_*` ke endpoint external bila ingin CLOUD/LOCAL.
- ⚠️ External Postgres harus punya `pgvector` extension (`CREATE EXTENSION vector`).

---

## 3. Mode 3 — Helm chart (k8s production)

### 3.1 Chart structure

```
infra/helm/suitest/
├── Chart.yaml
├── values.yaml                      ← default values (lihat §3.2)
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
  pullSecrets: []                     # untuk private registry / air-gapped

llm:
  provider: none                      # none | anthropic | openai | ollama | ...
  model: ""
  baseUrl: ""
  apiKeySecretRef:                    # reference, never inline
    name: suitest-llm
    key: api-key

embeddings:
  backend: none                       # none | fastembed | openai | cohere
  model: ""
  dim: 384                            # must match backend default

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
    allowLLM: true                    # set false untuk air-gap (selain LOCAL)
    allowExternalIntegrations: true   # jira/linear/slack/github

observability:
  otlpEndpoint: ""
  sentryDsnSecretRef: ""
  prometheusScrape: true

migrations:
  runAsJob: true                      # alembic upgrade head via pre-upgrade hook
```

### 3.3 Install

```bash
helm repo add suitest oci://ghcr.io/suitest-dev/charts
helm install suitest suitest/suitest \
  --version 1.0.0 \
  --namespace suitest --create-namespace \
  -f values-cloud.yaml \
  --set llm.apiKeySecretRef.name=my-llm-secret
```

Upgrade:

```bash
helm upgrade suitest suitest/suitest --version 1.1.0 -f values-cloud.yaml
# pre-upgrade Job runs `alembic upgrade head` automatically
```

### 3.4 HPA detail

Runner di-scale berdasarkan `suitest_runs_queue_depth` (gauge dari `/metrics` `api`). Butuh `prometheus-adapter` atau KEDA. Contoh KEDA:

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

Default `minAvailable: 1` untuk `api` dan `runner`. Override via `values.yaml`.

### 3.7 NetworkPolicy

Default rule:

| Source | Dest | Allowed |
|--------|------|---------|
| web | api | TCP/8000 |
| api | postgres / redis / minio | yes |
| api | LLM provider (egress) | controlled by `networkPolicy.egress.allowLLM` |
| api | integrations (jira/linear/slack/github) | controlled by `allowExternalIntegrations` |
| runner | api | TCP/8000 (callback) |
| runner | MCP server pods | yes |
| runner | LLM provider (egress) | controlled by `allowLLM` |

**Air-gapped**: set `tier=zero`, `networkPolicy.egress.allowLLM=false`, dan pakai internal image registry via `image.pullSecrets`. Embeddings tetap bisa pakai `fastembed` (CPU local, no egress).

---

## 4. Operations

### 4.1 Backup strategy

| Layer | Strategi | Frequency |
|-------|----------|-----------|
| Postgres | `pg_dump --format=custom` ke S3 / object storage | tiap 6 jam |
| Postgres WAL | wal-g / pgbackrest (streaming) | continuous |
| MinIO artifacts | `mc mirror` ke remote bucket | tiap 24 jam |
| Encryption key | sealed-secrets / external KMS — **off-cluster** | manual rotate ≥ 90 hari |

Contoh CronJob (k8s):

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
4. Apply same `SUITEST_ENCRYPTION_KEY` Secret (tanpa ini, LLM config terenkripsi tidak terbaca).
5. Helm install dgn version yang sama persis (mis-match version → alembic mungkin downgrade-blocked).
6. Smoke: login → buka run lama → verify artifact bisa di-download.
7. Run smoke suite Suitest sendiri (dogfood).

Drill **wajib quarterly** untuk production.

### 4.3 Upgrade path

| Step | Aksi |
|------|------|
| 1 | Read CHANGELOG, cek breaking changes (data model, env var rename) |
| 2 | `helm diff upgrade` untuk preview |
| 3 | Migrations: pre-upgrade Job jalankan `alembic upgrade head` (auto via Helm hook) |
| 4 | Blue/green untuk `api`: new ReplicaSet rolling, old drain |
| 5 | `runner` rolling — long-running job di-drain via `SIGTERM` grace `90s` |
| 6 | Verify `/capabilities` mismatch tier (kalau tidak sengaja swap provider) |
| 7 | Rollback: `helm rollback suitest <revision>` — downgrade-safe migrations only |

### 4.4 Resource sizing guidance

| Profile | Active user | Concurrent runs | Postgres | Redis | Runner replicas | API replicas |
|---------|-------------|-----------------|----------|-------|-----------------|--------------|
| Small | ≤25 | ≤5 | 2 vCPU / 4Gi / 20Gi | 1Gi | 1–2 | 2 |
| Medium | 25–250 | 5–25 | 4 vCPU / 16Gi / 100Gi | 4Gi | 2–6 | 3–5 |
| Large | 250–2000 | 25–200 | 8 vCPU / 64Gi / 500Gi + replica | 16Gi | 4–20 | 5–15 |

Catatan: LLM cost scales linearly with run volume in CLOUD tier — set budget guard di Settings → LLM (v1.x).

---

## 5. Tier-specific environment matrix

| Variable | ZERO (default) | LOCAL | CLOUD |
|----------|----------------|-------|-------|
| `SUITEST_LLM_PROVIDER` | `none` | `ollama` / `llamacpp` / `vllm` / `lmstudio` | `anthropic` / `openai` / `gemini` / `groq` / `openrouter` / `azure` / `bedrock` / `vertex` / `deepseek` |
| `SUITEST_LLM_API_KEY` | empty | empty (atau token internal) | required |
| `SUITEST_LLM_MODEL` | empty | `ollama/llama3.1` | provider-specific |
| `SUITEST_LLM_BASE_URL` | empty | `http://ollama:11434` | optional (Azure / OpenAI-compat) |
| `SUITEST_EMBEDDINGS_BACKEND` | `none` *(FTS fallback)* | `fastembed` recommended | `openai` / `cohere` |
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
| API container restart loop | `SUITEST_ENCRYPTION_KEY` salah length | Generate ulang via `openssl rand -base64 32` |
| `GET /capabilities` selalu ZERO meski set env | Lupa restart `api` setelah edit `.env` | `docker compose restart api runner` |
| Runner queue piling up | HPA tidak terhubung / `runs_queue_depth` metric kosong | Cek Prometheus scrape `/metrics` reachable |
| Alembic gagal upgrade | `pgvector` extension belum di-create | `CREATE EXTENSION IF NOT EXISTS vector;` sebagai superuser |
| LLM call timeout di LOCAL | Ollama belum pull model | `docker compose exec ollama ollama pull llama3.1` |
| WS disconnect terus | Ingress timeout < 60s | Set `nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"` |

---

## 7. Referensi silang

- Arsitektur services → [ARCHITECTURE.md](./ARCHITECTURE.md)
- Tier semantics → [CAPABILITY_TIERS.md](./CAPABILITY_TIERS.md)
- Design memo → [design memo](./superpowers/specs/2026-05-26-suitest-oss-pivot-design.md)
