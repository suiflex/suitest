---
title: Install on Kubernetes
description: Deploy Suitest to Kubernetes with the bundled Helm chart, including an air-gapped LOCAL-tier configuration.
---

Suitest ships a Helm chart at `infra/helm/suitest/` for production and
multi-replica deployments. The chart deploys the `api`, `web`, and `runner`
components separately; Postgres, Redis, and object storage are expected as
external services.

## What the chart deploys

- `api` Deployment (FastAPI, port 4000) + ClusterIP Service
- `web` Deployment (nginx-served UI, port 80) + ClusterIP Service
- `runner` Deployment (ARQ worker; no Service, it pulls jobs from Redis)
- ConfigMap with LLM, S3, and Redis settings
- Secret with `SUITEST_AUTH_SECRET` and `SUITEST_ENCRYPTION_KEY`
- ServiceAccount, PodDisruptionBudget, optional HorizontalPodAutoscalers,
  optional NetworkPolicy, optional in-cluster Ollama

The chart does not deploy Postgres, Redis, or MinIO, and it does not create an
Ingress. Bring your own datastores and expose the `web` Service with your own
ingress controller or load balancer.

## Requirements

- Kubernetes 1.27 or newer
- Helm 3
- External PostgreSQL 16 with the `pgvector` extension
- External Redis
- External S3-compatible object storage (MinIO, S3, ...)

## Install

The chart is installed from a repository checkout:

```bash
git clone https://github.com/suiflex/suitest && cd suitest

helm install suitest infra/helm/suitest \
  --namespace suitest --create-namespace \
  -f infra/helm/suitest/values.yaml
```

Before the first install, create the Postgres credentials secret the values
reference (`suitest-pg` with `user` and `password` keys by default):

```bash
kubectl -n suitest create secret generic suitest-pg \
  --from-literal=user=suitest \
  --from-literal=password=<strong-password>
```

:::note
The chart has no database migration hook. Run `alembic upgrade head` against
your database before the first start, using the same API image the chart
deploys (the compose stack runs it as
`uv run --project /app alembic upgrade head` from `/app/packages/db`).
:::

## Key values

| Value | Default | Purpose |
|-------|---------|---------|
| `suitest.tier` | `zero` | Deployment tier label (`zero`, `local`) |
| `suitest.autonomyDefault` | `manual` | Default autonomy level |
| `image.registry` | `ghcr.io/suitest-dev` | Image registry |
| `image.apiRepository` / `webRepository` / `runnerRepository` | `suitest-api` / `suitest-web` / `suitest-runner` | Per-component image names |
| `image.tag` | `0.1.0` | Image tag |
| `image.pullSecrets` | `[]` | For private or mirrored registries |
| `llm.enabled` / `llm.provider` / `llm.model` / `llm.baseUrl` | `false` / `none` / empty | LLM wiring (used by the air-gapped overlay) |
| `llm.apiKeySecretRef` | empty | Secret reference for a provider key, never inline |
| `api.replicaCount` / `web.replicaCount` / `runner.replicaCount` | `2` / `2` / `2` | Replicas per component |
| `postgres.host` / `port` / `database` | `postgres` / `5432` / `suitest` | External database location |
| `postgres.userSecretRef` / `passwordSecretRef` | `suitest-pg` | Credential secret references |
| `redis.url` | `redis://redis:6379/0` | External Redis URL |
| `s3.endpoint` / `s3.bucket` | `http://minio:9000` / `suitest-artifacts` | External object storage |
| `serviceAccount.create` | `true` | Dedicated ServiceAccount |

All pods run with a restrictive security context by default: non-root (UID
1000), read-only root filesystem, no privilege escalation, all capabilities
dropped.

## Secrets

On first install the chart generates random values for `SUITEST_AUTH_SECRET`
and `SUITEST_ENCRYPTION_KEY` and stores them in a release Secret. The template
uses a `lookup` guard, so the Secret is created once and kept as-is across
`helm upgrade`: your session signing key and encryption key do not rotate on
upgrade.

:::caution
Back up the release Secret off-cluster. `SUITEST_ENCRYPTION_KEY` encrypts the
per-workspace LLM configurations at rest; if the Secret is lost, those stored
configs become unreadable.
:::

## Scaling and availability

- **Replicas.** `api`, `web`, and `runner` each default to 2 replicas.
- **Autoscaling.** `autoscaling.enabled` is the global gate (default `false`).
  With it on, `api` scales 2 to 10 and `web` 2 to 6 replicas at 70% CPU
  utilization. Tune per component under `autoscaling.api` and
  `autoscaling.web`.
- **PodDisruptionBudget.** Enabled by default with `minAvailable: 1`, so
  voluntary disruptions never take a component fully down.

The runner scales by adding replicas (each pulls jobs from Redis) or by
raising `SUITEST_RUNNER_CONCURRENCY` per process. See the
[environment reference](/docs/reference/environment/) for the runner and MCP
pool tuning variables.

## Network policy

`networkPolicy.enabled` (default `false`) installs a default-deny policy with
an allowlist:

```yaml
networkPolicy:
  enabled: true
  ingressFromNamespaceLabels:
    kubernetes.io/metadata.name: ingress-nginx
  egressCidrs:
    - 10.20.0.0/16   # your postgres / redis / s3 CIDRs
```

`ingressFromNamespaceLabels` selects the namespace of your ingress controller;
`egressCidrs` should list the CIDRs of your datastores. With the policy on,
nothing else gets in or out.

## Air-gapped install (LOCAL tier)

The `values-airgapped.yaml` overlay configures a deployment with no outbound
internet: images from an internal registry mirror, LLM inference from an
in-cluster Ollama, and egress locked to your datastore CIDRs.

```bash
helm install suitest infra/helm/suitest \
  --namespace suitest --create-namespace \
  -f infra/helm/suitest/values-airgapped.yaml
```

What the overlay changes:

```yaml
image:
  registry: registry.internal:5000/suitest   # your in-cluster mirror

suitest:
  tier: local

llm:
  enabled: true
  provider: ollama
  model: llama3.1
  baseUrl: http://suitest-ollama:11434       # the in-cluster Ollama Service

ollama:
  enabled: true
  image: registry.internal:5000/ollama/ollama:0.3.12

networkPolicy:
  enabled: true
  egressCidrs:
    - 10.0.0.0/8                             # replace with your datastore CIDRs

autoscaling:
  enabled: true
```

Push every image (the three Suitest images plus Ollama) to your internal
registry before installing. The in-cluster Ollama defaults to 1 CPU / 4 Gi
requests, 4 CPU / 12 Gi limits, and a 20 Gi persistent volume for models;
adjust under `ollama.resources` and `ollama.persistence`.

## Upgrade

```bash
helm upgrade suitest infra/helm/suitest -f infra/helm/suitest/values.yaml
```

Apply database migrations as part of your upgrade procedure (see the note in
the install section). Rollback with `helm rollback suitest <revision>`.

## Next steps

- [Self-hosting guide](/docs/guides/self-hosting/): TLS, backups, operations
- [Docker Compose install](/docs/install/docker/): single-host alternative
- [Capability tiers](/docs/reference/tiers/): what LOCAL unlocks
- [Environment reference](/docs/reference/environment/)
