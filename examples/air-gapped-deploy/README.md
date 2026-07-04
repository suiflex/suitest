# Example: air-gapped self-host (LOCAL tier)

Run Suitest on Kubernetes with **no outbound internet**, serving the LOCAL LLM
tier from an in-cluster Ollama.

1. On a connected machine, build the transfer bundle:

```bash
scripts/airgapped-bundle.sh 0.1.0
```

2. Move `dist/suitest-airgapped-0.1.0/` to the air-gapped network, load the images
   into your in-cluster registry, then:

```bash
helm install suitest dist/suitest-airgapped-0.1.0/suitest-0.1.0.tgz \
  -f infra/helm/suitest/values-airgapped.yaml \
  --set networkPolicy.egressCidrs={10.0.0.0/8}
```

The `values-airgapped.yaml` overlay enables the in-cluster Ollama and a deny-egress
NetworkPolicy (DNS + intra-release + your datastore CIDRs only) — so AI features
work with zero external calls.
See [docs/DEPLOYMENT.md] and [ROADMAP M4-4].
