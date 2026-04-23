#!/bin/bash

###############################################################################
# Velero Installation Verification Script
# Verifies Velero deployment with Workload Identity on AKS
###############################################################################

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
WARN=0
FAIL=0

ok()   { echo -e "${GREEN}[PASS]${NC} $1"; ((PASS++)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; ((WARN++)); }
fail() { echo -e "${RED}[FAIL]${NC} $1"; ((FAIL++)); }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

section() {
    echo ""
    echo "--- $1 ---"
}

# ---------------------------------------------------------------------------
section "Namespace & Service Account"
# ---------------------------------------------------------------------------

if kubectl get namespace velero &>/dev/null; then
    ok "Namespace 'velero' exists"
else
    fail "Namespace 'velero' not found"
fi

if kubectl get serviceaccount velero -n velero &>/dev/null; then
    ok "ServiceAccount 'velero' exists"

    CLIENT_ID=$(kubectl get serviceaccount velero -n velero \
        -o jsonpath='{.metadata.annotations.azure\.workload\.identity/client-id}' 2>/dev/null || true)
    if [ -n "${CLIENT_ID}" ]; then
        ok "ServiceAccount annotated with Workload Identity client-id: ${CLIENT_ID}"
    else
        fail "ServiceAccount missing annotation 'azure.workload.identity/client-id' — Workload Identity will not work"
    fi
else
    fail "ServiceAccount 'velero' not found in namespace velero"
fi

# ---------------------------------------------------------------------------
section "Velero Pods"
# ---------------------------------------------------------------------------

TOTAL=$(kubectl get pods -n velero -l app.kubernetes.io/name=velero --no-headers 2>/dev/null | wc -l)
if [ "${TOTAL}" -gt 0 ]; then
    ok "Found ${TOTAL} Velero pod(s)"
    kubectl get pods -n velero -l app.kubernetes.io/name=velero
    RUNNING=$(kubectl get pods -n velero -l app.kubernetes.io/name=velero \
        --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
    if [ "${RUNNING}" -eq "${TOTAL}" ]; then
        ok "All ${RUNNING} pod(s) are Running"
    else
        fail "${RUNNING}/${TOTAL} pod(s) Running — check: kubectl logs -n velero deployment/velero"
    fi
else
    fail "No Velero pods found"
fi

# Check that pods carry the Workload Identity label
WI_LABEL=$(kubectl get pods -n velero -l "app.kubernetes.io/name=velero,azure.workload.identity/use=true" \
    --no-headers 2>/dev/null | wc -l)
if [ "${WI_LABEL}" -gt 0 ]; then
    ok "Pods have label 'azure.workload.identity/use=true'"
else
    warn "Pods are missing label 'azure.workload.identity/use=true' — check podLabels in values.yaml"
fi

# Verify no legacy secret is being used
if kubectl get secret velero-credentials -n velero &>/dev/null; then
    warn "Secret 'velero-credentials' still exists — expected to be unused with Workload Identity"
else
    ok "No legacy storage-key secret present"
fi

# ---------------------------------------------------------------------------
section "Backup Storage Location"
# ---------------------------------------------------------------------------

BSL_COUNT=$(kubectl get backupstoragelocation -n velero --no-headers 2>/dev/null | wc -l)
if [ "${BSL_COUNT}" -gt 0 ]; then
    ok "Found ${BSL_COUNT} BackupStorageLocation(s)"
    kubectl get backupstoragelocation -n velero
    AVAIL=$(kubectl get backupstoragelocation -n velero \
        -o jsonpath='{.items[?(@.status.phase=="Available")].metadata.name}' 2>/dev/null)
    if [ -n "${AVAIL}" ]; then
        ok "BackupStorageLocation Available: ${AVAIL}"
    else
        fail "BackupStorageLocation not Available — auth or network issue (check pod logs)"
    fi
else
    fail "No BackupStorageLocations found"
fi

# ---------------------------------------------------------------------------
section "Volume Snapshot Location"
# ---------------------------------------------------------------------------

VSL_COUNT=$(kubectl get volumesnapshotlocation -n velero --no-headers 2>/dev/null | wc -l)
if [ "${VSL_COUNT}" -gt 0 ]; then
    ok "Found ${VSL_COUNT} VolumeSnapshotLocation(s)"
    kubectl get volumesnapshotlocation -n velero
else
    warn "No VolumeSnapshotLocations found — PVC snapshots will not work"
fi

# ---------------------------------------------------------------------------
section "CSI VolumeSnapshotClass"
# ---------------------------------------------------------------------------

VSC_COUNT=$(kubectl get volumesnapshotclass --no-headers 2>/dev/null | wc -l)
if [ "${VSC_COUNT}" -gt 0 ]; then
    ok "Found ${VSC_COUNT} VolumeSnapshotClass(es)"
    kubectl get volumesnapshotclass

    # Check that at least one has the Velero label
    VELERO_VSC=$(kubectl get volumesnapshotclass \
        -l velero.io/csi-volumesnapshot-class=true --no-headers 2>/dev/null | wc -l)
    if [ "${VELERO_VSC}" -gt 0 ]; then
        ok "VolumeSnapshotClass labelled for Velero CSI found"
    else
        warn "No VolumeSnapshotClass has label 'velero.io/csi-volumesnapshot-class=true' — label one for CSI snapshots to work"
    fi
else
    warn "No VolumeSnapshotClasses found — install the AKS CSI snapshot controller"
fi

# ---------------------------------------------------------------------------
section "Scheduled Backups"
# ---------------------------------------------------------------------------

SCHED_COUNT=$(kubectl get schedule -n velero --no-headers 2>/dev/null | wc -l)
if [ "${SCHED_COUNT}" -gt 0 ]; then
    ok "Found ${SCHED_COUNT} Schedule(s)"
    kubectl get schedule -n velero
else
    warn "No Schedules found — check values.yaml schedules block"
fi

# ---------------------------------------------------------------------------
section "Velero CLI"
# ---------------------------------------------------------------------------

if command -v velero &>/dev/null; then
    VER=$(velero version --client-only 2>/dev/null | grep "Version:" | awk '{print $2}')
    ok "Velero CLI installed (${VER})"
    BACKUP_COUNT=$(velero backup get -n velero --no-headers 2>/dev/null | wc -l)
    if [ "${BACKUP_COUNT}" -gt 0 ]; then
        ok "Found ${BACKUP_COUNT} backup(s)"
        velero backup get -n velero
    else
        info "No backups yet (normal for a new installation)"
    fi
else
    warn "Velero CLI not installed — install from https://velero.io/docs/main/basic-install/#install-the-cli"
fi

# ---------------------------------------------------------------------------
section "ArgoCD Application"
# ---------------------------------------------------------------------------

if kubectl get application velero -n argocd &>/dev/null 2>&1; then
    ok "ArgoCD Application 'velero' exists"
    SYNC=$(kubectl get application velero -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null)
    HEALTH=$(kubectl get application velero -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null)
    [ "${SYNC}" = "Synced" ]   && ok "Sync: ${SYNC}"   || warn "Sync: ${SYNC}"
    [ "${HEALTH}" = "Healthy" ] && ok "Health: ${HEALTH}" || warn "Health: ${HEALTH}"
else
    warn "ArgoCD Application 'velero' not found (skip if not using ArgoCD)"
fi

# ---------------------------------------------------------------------------
section "Workload Identity Webhook"
# ---------------------------------------------------------------------------

WEBHOOK=$(kubectl get mutatingwebhookconfiguration \
    azure-wi-webhook-mutating-webhook-configuration --no-headers 2>/dev/null | wc -l)
if [ "${WEBHOOK}" -gt 0 ]; then
    ok "Azure Workload Identity webhook is installed"
else
    fail "Azure Workload Identity webhook not found — install azure-workload-identity chart or use 'az aks addon enable'"
fi

# ---------------------------------------------------------------------------
echo ""
echo "========================================"
echo "Verification Summary"
printf "  PASS: %d   WARN: %d   FAIL: %d\n" "${PASS}" "${WARN}" "${FAIL}"
echo "========================================"

if [ "${FAIL}" -gt 0 ]; then
    echo ""
    echo "One or more checks failed. Run 'kubectl logs -n velero deployment/velero' to investigate."
    exit 1
fi
echo ""
