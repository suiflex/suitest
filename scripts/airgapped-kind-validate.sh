#!/usr/bin/env bash
# M4-4 live air-gap validation on a throwaway kind cluster. Proves the claim
# that matters: with the air-gapped NetworkPolicy applied, a Suitest pod can
# reach the in-cluster Ollama but CANNOT reach the public internet.
#
# kind's default CNI (kindnet) does NOT enforce NetworkPolicy, so this installs
# Calico first. It then applies the *real* chart NetworkPolicy + the in-cluster
# Ollama, drops in a probe pod wearing the chart's selector labels (so the
# default-deny policy governs it), and asserts:
#   - probe -> ollama:11434      ALLOWED  (intra-release egress)
#   - probe -> 1.1.1.1:443       BLOCKED  (public egress denied)
#
# Heavyweight + slow (Calico + image pulls), so it is opt-in: `make`-free, run
# directly or via the manual `m4-airgapped` workflow. Requires: kind, kubectl,
# helm, docker.
set -euo pipefail

CLUSTER="${KIND_CLUSTER:-suitest-airgap}"
CHART="infra/helm/suitest"
VALUES="$CHART/values-airgapped.yaml"
NS="airgap"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cleanup() {
  echo "--- deleting kind cluster $CLUSTER ---"
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "--- creating kind cluster (CNI disabled, Calico enforces NetworkPolicy) ---"
cat <<'EOF' | kind create cluster --name "$CLUSTER" --config -
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
  podSubnet: "192.168.0.0/16"
EOF

echo "--- installing Calico ---"
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.27.0/manifests/calico.yaml
kubectl -n kube-system rollout status ds/calico-node --timeout=180s

kubectl create namespace "$NS"

echo "--- rendering chart (air-gapped overlay), applying NetworkPolicy + Ollama ---"
# Use a public Ollama image here so the harness bootstraps without a private
# registry; the air-gap invariant under test is the *egress policy*, not the
# image source. Egress stays locked so Ollama serves without pulling a model.
helm template suitest "$CHART" -f "$VALUES" \
  --set ollama.image=ollama/ollama:0.3.12 \
  --show-only templates/networkpolicy.yaml \
  --show-only templates/ollama.yaml > /tmp/airgap-manifests.yaml
kubectl -n "$NS" apply -f /tmp/airgap-manifests.yaml

echo "--- waiting for Ollama to serve ---"
kubectl -n "$NS" rollout status deploy/suitest-ollama --timeout=180s

# Extract the selector labels the default-deny policy matches, so the probe is
# governed by it (name + instance from the chart's selectorLabels).
NAME_LABEL="$(kubectl -n "$NS" get networkpolicy suitest-default-deny \
  -o jsonpath='{.spec.podSelector.matchLabels.app\.kubernetes\.io/name}')"
INSTANCE_LABEL="$(kubectl -n "$NS" get networkpolicy suitest-default-deny \
  -o jsonpath='{.spec.podSelector.matchLabels.app\.kubernetes\.io/instance}')"
echo "--- probe wears labels name=$NAME_LABEL instance=$INSTANCE_LABEL ---"

cat <<EOF | kubectl -n "$NS" apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: airgap-probe
  labels:
    app.kubernetes.io/name: "$NAME_LABEL"
    app.kubernetes.io/instance: "$INSTANCE_LABEL"
spec:
  restartPolicy: Never
  containers:
    - name: probe
      image: busybox:1.36
      command: ["sh", "-c", "sleep 600"]
EOF
kubectl -n "$NS" wait --for=condition=Ready pod/airgap-probe --timeout=120s

fail=0

echo "--- assert ALLOWED: probe -> in-cluster Ollama ---"
if kubectl -n "$NS" exec airgap-probe -- \
    wget -q -T 10 -O- http://suitest-ollama:11434/ | grep -qi "ollama"; then
  echo "  PASS  probe reached Ollama"
else
  echo "  FAIL  probe could NOT reach in-cluster Ollama"; fail=1
fi

echo "--- assert BLOCKED: probe -> public internet (1.1.1.1:443) ---"
if kubectl -n "$NS" exec airgap-probe -- \
    wget -q -T 8 -O- https://1.1.1.1/ >/dev/null 2>&1; then
  echo "  FAIL  probe reached the public internet — egress NOT locked"; fail=1
else
  echo "  PASS  public egress denied"
fi

if [ "$fail" -ne 0 ]; then
  echo "AIR-GAP VALIDATION FAILED"; exit 1
fi
echo "PASS  air-gapped deploy validated: in-cluster reachable, public egress denied."
