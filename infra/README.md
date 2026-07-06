# Suitest infrastructure

Two supported deployment shapes. Both default to the **ZERO** tier (no LLM);
workspaces upgrade themselves from the web UI (`Settings → LLM`).

## Layout

```
infra/
├── docker/
│   ├── docker-compose.yml       ← full local/prod-like stack
│   ├── Dockerfile.api           ← FastAPI backend
│   ├── Dockerfile.web           ← Vite build → nginx
│   ├── Dockerfile.runner        ← ARQ worker (MCP step dispatch)
│   ├── Dockerfile.suitest       ← all-in-one image (supervisord)
│   ├── nginx.conf               ← web reverse proxy → api
│   └── supervisord.suitest.conf ← process tree for the all-in-one image
└── helm/suitest/                ← Kubernetes chart
    ├── values.yaml              ← defaults (per-service deployments)
    ├── values-airgapped.yaml    ← air-gapped overrides (LOCAL tier via Ollama)
    └── templates/               ← api/web/runner deployments, PDB, Ollama
```

## Local / production-like (Docker Compose)

```bash
cp .env.example .env      # set SUITEST_AUTH_SECRET + super-admin credentials
make docker-up            # pulls prebuilt ghcr images; = docker compose -f infra/docker/docker-compose.yml --profile zero up -d
open http://localhost:3000
```

Profiles:

- `--profile local` — adds an **Ollama** service for the LOCAL tier
  (air-gapped inference).

Infra-only mode (run the app processes on the host — the day-to-day dev loop):

```bash
docker compose -f infra/docker/docker-compose.yml up -d postgres redis minio
make dev                  # api :4000 + web :3000 + runner
```

## Kubernetes (Helm)

```bash
helm install suitest infra/helm/suitest -f infra/helm/suitest/values.yaml
# air-gapped:
helm install suitest infra/helm/suitest -f infra/helm/suitest/values-airgapped.yaml
```

The chart deploys api/web/runner separately with a PodDisruptionBudget;
Postgres/Redis/object storage are expected as external services (set their
URLs in `values.yaml`).

## CI images

`.github/workflows/ci.yml` (`build-images` job) builds every Dockerfile on
each push — no publish, cache via GHA. Publishing happens on `images-v*` tags:
`.github/workflows/release-images.yml` pushes
`ghcr.io/suiflex/{suitest-api,suitest-runner,suitest-web,suitest}` with both
the version tag and `latest`. The compose file pulls these prebuilt images;
`SUITEST_IMAGE_TAG` pins a version and `make docker-up-prod` builds locally
instead.

Full deployment guide (env vars, TLS, backups, air-gapped checklist):
[docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).
