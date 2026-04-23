#!/bin/bash

###############################################################################
# Velero E2E Test Script
#
# Test coverage:
#   1. Pre-flight checks (Workload Identity, BSL availability)
#   2. Namespace-only backup & restore
#   3. PVC backup & restore (CSI snapshot + data integrity check)
#   4. Cross-namespace restore
#   5. Cleanup
#
# Usage:
#   ./test-backup-restore.sh [--skip-pvc] [--keep-resources]
#
#   --skip-pvc        Skip the PVC/CSI snapshot test (needs StorageClass)
#   --keep-resources  Do not delete test namespaces and backups at the end
###############################################################################

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SKIP_PVC=false
KEEP_RESOURCES=false
for arg in "$@"; do
    case "$arg" in
        --skip-pvc)        SKIP_PVC=true ;;
        --keep-resources)  KEEP_RESOURCES=true ;;
    esac
done

TESTS_PASSED=0
TESTS_FAILED=0
TS=$(date +%Y%m%d-%H%M%S)
TEST_NS="velero-e2e-${TS}"
RESTORE_NS="velero-e2e-restore-${TS}"
BACKUP_NS="velero-e2e-ns-backup-${TS}"
BACKUP_PVC="velero-e2e-pvc-backup-${TS}"

CREATED_BACKUPS=()
CREATED_RESTORES=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ok()   { echo -e "${GREEN}[PASS]${NC} $1"; ((TESTS_PASSED++)); }
fail() { echo -e "${RED}[FAIL]${NC} $1"; ((TESTS_FAILED++)); }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

section() {
    echo ""
    echo "============================================================"
    echo " $1"
    echo "============================================================"
}

assert_resource_exists() {
    local kind="$1" name="$2" ns="$3"
    if kubectl get "${kind}" "${name}" -n "${ns}" &>/dev/null; then
        ok "${kind} '${name}' exists in namespace '${ns}'"
        return 0
    else
        fail "${kind} '${name}' NOT found in namespace '${ns}'"
        return 1
    fi
}

wait_for_velero_backup() {
    local backup="$1" timeout="${2:-300}"
    info "Waiting up to ${timeout}s for backup '${backup}' to complete..."
    velero backup wait "${backup}" -n velero --timeout="${timeout}s" 2>/dev/null || true
    local phase
    phase=$(velero backup get "${backup}" -n velero -o json 2>/dev/null \
        | grep -o '"phase":"[^"]*"' | head -1 | cut -d'"' -f4 || echo "Unknown")
    echo "${phase}"
}

wait_for_velero_restore() {
    local restore="$1" timeout="${2:-300}"
    info "Waiting up to ${timeout}s for restore '${restore}' to complete..."
    velero restore wait "${restore}" -n velero --timeout="${timeout}s" 2>/dev/null || true
    local phase
    phase=$(velero restore get "${restore}" -n velero -o json 2>/dev/null \
        | grep -o '"phase":"[^"]*"' | head -1 | cut -d'"' -f4 || echo "Unknown")
    echo "${phase}"
}

cleanup() {
    if [ "${KEEP_RESOURCES}" = true ]; then
        warn "Skipping cleanup (--keep-resources set)"
        return
    fi
    info "Cleaning up test resources..."
    kubectl delete namespace "${TEST_NS}"    --ignore-not-found &>/dev/null || true
    kubectl delete namespace "${RESTORE_NS}" --ignore-not-found &>/dev/null || true
    for b in "${CREATED_BACKUPS[@]:-}"; do
        [ -n "${b}" ] && velero backup delete "${b}" -n velero --confirm &>/dev/null || true
    done
    for r in "${CREATED_RESTORES[@]:-}"; do
        [ -n "${r}" ] && velero restore delete "${r}" -n velero --confirm &>/dev/null || true
    done
    info "Cleanup complete"
}

trap cleanup EXIT

# ---------------------------------------------------------------------------
# 0. Pre-flight checks
# ---------------------------------------------------------------------------
section "0. Pre-flight Checks"

if ! command -v velero &>/dev/null; then
    fail "Velero CLI not installed — install from https://velero.io/docs/main/basic-install/#install-the-cli"
    exit 1
fi
ok "Velero CLI present"

if ! command -v kubectl &>/dev/null; then
    fail "kubectl not installed"
    exit 1
fi
ok "kubectl present"

# Velero pod running
VELERO_RUNNING=$(kubectl get pods -n velero -l app.kubernetes.io/name=velero \
    --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
if [ "${VELERO_RUNNING}" -gt 0 ]; then
    ok "Velero pod is Running"
else
    fail "No Velero pods Running — deploy Velero first"
    exit 1
fi

# Workload Identity: service account annotation
CLIENT_ID=$(kubectl get serviceaccount velero -n velero \
    -o jsonpath='{.metadata.annotations.azure\.workload\.identity/client-id}' 2>/dev/null || true)
if [ -n "${CLIENT_ID}" ]; then
    ok "Workload Identity client-id annotated on ServiceAccount: ${CLIENT_ID}"
else
    fail "ServiceAccount 'velero' missing Workload Identity annotation — run setup-azure.sh"
    exit 1
fi

# Workload Identity webhook
WEBHOOK=$(kubectl get mutatingwebhookconfiguration \
    azure-wi-webhook-mutating-webhook-configuration --no-headers 2>/dev/null | wc -l)
if [ "${WEBHOOK}" -gt 0 ]; then
    ok "Azure Workload Identity webhook installed"
else
    fail "Azure Workload Identity webhook not found"
    exit 1
fi

# Backup Storage Location available
BSL_PHASE=$(kubectl get backupstoragelocation default -n velero \
    -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
if [ "${BSL_PHASE}" = "Available" ]; then
    ok "BackupStorageLocation 'default' is Available"
else
    fail "BackupStorageLocation 'default' is '${BSL_PHASE}' — auth or connectivity issue"
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. Namespace backup & restore
# ---------------------------------------------------------------------------
section "1. Namespace Backup & Restore"

info "Creating test namespace '${TEST_NS}'..."
kubectl create namespace "${TEST_NS}"

info "Deploying test workload (nginx + configmap + secret)..."
kubectl create deployment nginx \
    --image=nginx:stable-alpine \
    --replicas=2 \
    -n "${TEST_NS}"

kubectl create configmap app-config \
    --from-literal=env=e2e-test \
    --from-literal=version=1.0 \
    -n "${TEST_NS}"

kubectl create secret generic app-secret \
    --from-literal=token=e2e-test-token \
    -n "${TEST_NS}"

kubectl wait --for=condition=available --timeout=120s deployment/nginx -n "${TEST_NS}"
ok "Test workload ready"

info "Creating namespace backup '${BACKUP_NS}'..."
velero backup create "${BACKUP_NS}" \
    --include-namespaces="${TEST_NS}" \
    -n velero

CREATED_BACKUPS+=("${BACKUP_NS}")

NS_PHASE=$(wait_for_velero_backup "${BACKUP_NS}" 300)
if [ "${NS_PHASE}" = "Completed" ]; then
    ok "Namespace backup completed (${BACKUP_NS})"
else
    fail "Namespace backup ended with phase '${NS_PHASE}'"
    velero backup logs "${BACKUP_NS}" -n velero || true
fi

info "Simulating disaster — deleting namespace '${TEST_NS}'..."
kubectl delete namespace "${TEST_NS}"
kubectl wait --for=delete namespace/"${TEST_NS}" --timeout=60s 2>/dev/null || true
ok "Namespace deleted"

RESTORE_NS_NAME="velero-e2e-ns-restore-${TS}"
info "Restoring into original namespace..."
velero restore create "${RESTORE_NS_NAME}" \
    --from-backup="${BACKUP_NS}" \
    -n velero

CREATED_RESTORES+=("${RESTORE_NS_NAME}")

NS_RESTORE_PHASE=$(wait_for_velero_restore "${RESTORE_NS_NAME}" 300)
if [ "${NS_RESTORE_PHASE}" = "Completed" ]; then
    ok "Namespace restore completed"
else
    fail "Namespace restore phase: '${NS_RESTORE_PHASE}'"
    velero restore logs "${RESTORE_NS_NAME}" -n velero || true
fi

assert_resource_exists deployment nginx "${TEST_NS}"
assert_resource_exists configmap app-config "${TEST_NS}"
assert_resource_exists secret app-secret "${TEST_NS}"

REPLICAS=$(kubectl get deployment nginx -n "${TEST_NS}" \
    -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo "0")
if [ "${REPLICAS}" -ge 1 ]; then
    ok "nginx deployment has ${REPLICAS} available replica(s) after restore"
else
    fail "nginx deployment has no available replicas after restore"
fi

CONFIG_VAL=$(kubectl get configmap app-config -n "${TEST_NS}" \
    -o jsonpath='{.data.env}' 2>/dev/null || echo "")
if [ "${CONFIG_VAL}" = "e2e-test" ]; then
    ok "ConfigMap data integrity verified (env=e2e-test)"
else
    fail "ConfigMap data mismatch — got '${CONFIG_VAL}', expected 'e2e-test'"
fi

# ---------------------------------------------------------------------------
# 2. Cross-namespace restore
# ---------------------------------------------------------------------------
section "2. Cross-Namespace Restore"

CROSS_RESTORE_NAME="velero-e2e-cross-restore-${TS}"
info "Restoring '${TEST_NS}' into '${RESTORE_NS}'..."
velero restore create "${CROSS_RESTORE_NAME}" \
    --from-backup="${BACKUP_NS}" \
    --namespace-mappings "${TEST_NS}:${RESTORE_NS}" \
    -n velero

CREATED_RESTORES+=("${CROSS_RESTORE_NAME}")

CROSS_PHASE=$(wait_for_velero_restore "${CROSS_RESTORE_NAME}" 300)
if [ "${CROSS_PHASE}" = "Completed" ]; then
    ok "Cross-namespace restore completed"
else
    fail "Cross-namespace restore phase: '${CROSS_PHASE}'"
fi

assert_resource_exists deployment nginx "${RESTORE_NS}"
assert_resource_exists configmap app-config "${RESTORE_NS}"
ok "Resources present in target namespace '${RESTORE_NS}'"

# ---------------------------------------------------------------------------
# 3. PVC backup & restore (CSI snapshot)
# ---------------------------------------------------------------------------
section "3. PVC Backup & Restore (CSI Snapshot)"

if [ "${SKIP_PVC}" = true ]; then
    warn "Skipping PVC test (--skip-pvc)"
else
    # Detect a usable StorageClass
    STORAGE_CLASS=$(kubectl get storageclass \
        -o jsonpath='{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")].metadata.name}' \
        2>/dev/null | awk '{print $1}')

    if [ -z "${STORAGE_CLASS}" ]; then
        warn "No default StorageClass found — skipping PVC test. Pass --skip-pvc to suppress this warning."
    else
        ok "Using StorageClass '${STORAGE_CLASS}'"

        PVC_NS="velero-e2e-pvc-${TS}"
        kubectl create namespace "${PVC_NS}"

        # PVC with test data written by an init container
        kubectl apply -n "${PVC_NS}" -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: "${STORAGE_CLASS}"
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: data-writer
spec:
  restartPolicy: Never
  initContainers:
    - name: write-data
      image: busybox:stable
      command: [sh, -c, 'echo "velero-e2e-checksum-42" > /data/checksum.txt']
      volumeMounts:
        - mountPath: /data
          name: test-volume
  containers:
    - name: pause
      image: gcr.io/google_containers/pause:3.9
      volumeMounts:
        - mountPath: /data
          name: test-volume
  volumes:
    - name: test-volume
      persistentVolumeClaim:
        claimName: test-pvc
EOF

        info "Waiting for data-writer pod to complete init..."
        kubectl wait --for=condition=ready pod/data-writer -n "${PVC_NS}" --timeout=120s 2>/dev/null || true
        ok "Data written to PVC"

        info "Creating PVC backup '${BACKUP_PVC}'..."
        velero backup create "${BACKUP_PVC}" \
            --include-namespaces="${PVC_NS}" \
            --snapshot-volumes=true \
            -n velero

        CREATED_BACKUPS+=("${BACKUP_PVC}")

        PVC_PHASE=$(wait_for_velero_backup "${BACKUP_PVC}" 600)
        if [ "${PVC_PHASE}" = "Completed" ]; then
            ok "PVC backup completed (${BACKUP_PVC})"
        else
            fail "PVC backup phase: '${PVC_PHASE}'"
            velero backup logs "${BACKUP_PVC}" -n velero || true
        fi

        info "Deleting PVC namespace to simulate disaster..."
        kubectl delete namespace "${PVC_NS}"
        kubectl wait --for=delete namespace/"${PVC_NS}" --timeout=90s 2>/dev/null || true

        PVC_RESTORE_NAME="velero-e2e-pvc-restore-${TS}"
        info "Restoring PVC from backup..."
        velero restore create "${PVC_RESTORE_NAME}" \
            --from-backup="${BACKUP_PVC}" \
            -n velero

        CREATED_RESTORES+=("${PVC_RESTORE_NAME}")

        PVC_RESTORE_PHASE=$(wait_for_velero_restore "${PVC_RESTORE_NAME}" 600)
        if [ "${PVC_RESTORE_PHASE}" = "Completed" ]; then
            ok "PVC restore completed"
        else
            fail "PVC restore phase: '${PVC_RESTORE_PHASE}'"
            velero restore logs "${PVC_RESTORE_NAME}" -n velero || true
        fi

        # Verify PVC restored
        assert_resource_exists pvc test-pvc "${PVC_NS}"

        # Verify data integrity with a reader pod
        kubectl run data-reader \
            --image=busybox:stable \
            --restart=Never \
            -n "${PVC_NS}" \
            --overrides='{
              "spec": {
                "volumes": [{"name":"v","persistentVolumeClaim":{"claimName":"test-pvc"}}],
                "containers": [{"name":"r","image":"busybox:stable",
                  "command":["cat","/data/checksum.txt"],
                  "volumeMounts":[{"mountPath":"/data","name":"v"}]}]
              }
            }' 2>/dev/null || true

        kubectl wait --for=condition=ready pod/data-reader -n "${PVC_NS}" --timeout=60s 2>/dev/null || true
        CHECKSUM=$(kubectl logs data-reader -n "${PVC_NS}" 2>/dev/null || echo "")

        if echo "${CHECKSUM}" | grep -q "velero-e2e-checksum-42"; then
            ok "PVC data integrity verified (checksum matches)"
        else
            fail "PVC data mismatch — got '${CHECKSUM}'"
        fi

        # Add PVC namespace to cleanup list
        kubectl delete namespace "${PVC_NS}" --ignore-not-found &>/dev/null || true
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section "E2E Test Summary"

printf "  Tests passed: %d\n" "${TESTS_PASSED}"
printf "  Tests failed: %d\n" "${TESTS_FAILED}"
echo ""

if [ "${TESTS_FAILED}" -gt 0 ]; then
    echo -e "${RED}Some tests FAILED. Review the output above and check Velero logs:${NC}"
    echo "    kubectl logs -n velero deployment/velero"
    exit 1
else
    echo -e "${GREEN}All tests PASSED.${NC}"
fi
