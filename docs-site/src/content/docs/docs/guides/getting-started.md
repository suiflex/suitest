---
title: Getting started
description: Run Suitest locally in one command.
---

## Prerequisites

- Docker + Docker Compose

## Boot the stack

```bash
git clone https://github.com/suiflex/suitest
cd suitest
cp .env.example .env
docker compose -f infra/docker/docker-compose.yml --profile zero up -d
```

Open <http://localhost:3000>, log in with the bootstrap super-admin
(`SUITEST_SUPERADMIN_EMAIL` / `SUITEST_SUPERADMIN_PASSWORD`), and you'll land on
an empty dashboard with a **ZERO** badge in the topbar.

## Enable AI (optional)

Add an LLM in **Settings → LLM** — a cloud key (CLOUD tier) or a local server URL
(LOCAL tier). The tier badge updates automatically. Everything works at ZERO
first; AI is enrichment on top.
