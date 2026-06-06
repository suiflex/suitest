#!/usr/bin/env bash
# M4-4 — assemble an air-gapped deploy bundle for Suitest.
#
# Produces a single tarball containing every container image + the packaged Helm
# chart, so an operator can transfer it to a network with NO outbound internet,
# load the images into a local registry, and `helm install` against the
# in-cluster Ollama (no public model/API calls).
#
# Usage:
#   scripts/airgapped-bundle.sh [TAG] [OUTDIR]
#
# Then, on the air-gapped side:
#   docker load -i suitest-airgapped-<tag>/images/*.tar
#   # retag + push each image to your in-cluster registry, e.g. registry.internal:5000
#   helm install suitest suitest-airgapped-<tag>/suitest-*.tgz \
#       -f infra/helm/suitest/values-airgapped.yaml
set -euo pipefail

TAG="${1:-0.1.0}"
OUTDIR="${2:-dist/suitest-airgapped-${TAG}}"
REGISTRY="${SUITEST_IMAGE_REGISTRY:-ghcr.io/suitest-dev}"
OLLAMA_IMAGE="${SUITEST_OLLAMA_IMAGE:-ollama/ollama:0.3.12}"

images=(
  "${REGISTRY}/suitest-api:${TAG}"
  "${REGISTRY}/suitest-runner:${TAG}"
  "${REGISTRY}/suitest-web:${TAG}"
  "postgres:16"
  "redis:7"
  "minio/minio:latest"
  "${OLLAMA_IMAGE}"
)

mkdir -p "${OUTDIR}/images"
echo "==> Pulling + saving images to ${OUTDIR}/images"
for img in "${images[@]}"; do
  echo "    - ${img}"
  docker pull "${img}"
  safe="$(echo "${img}" | tr '/:' '__')"
  docker save "${img}" -o "${OUTDIR}/images/${safe}.tar"
done

echo "==> Packaging Helm chart"
helm package infra/helm/suitest --version "${TAG}" --destination "${OUTDIR}"

cp infra/helm/suitest/values-airgapped.yaml "${OUTDIR}/values-airgapped.yaml"

echo "==> Bundle ready: ${OUTDIR}"
echo "    images:  $(ls "${OUTDIR}/images" | wc -l)"
echo "    chart:   $(ls "${OUTDIR}"/*.tgz)"
echo
echo "Transfer the whole '${OUTDIR}' directory to the air-gapped network, then:"
echo "  for f in ${OUTDIR}/images/*.tar; do docker load -i \$f; done"
echo "  # retag/push to your local registry, then helm install with values-airgapped.yaml"
