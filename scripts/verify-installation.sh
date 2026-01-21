#!/bin/bash

###############################################################################
# Velero Installation Verification Script
# This script verifies that Velero is properly installed and configured
###############################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_header() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo "========================================"
echo "Velero Installation Verification"
echo "========================================"
echo ""

# Check if Velero namespace exists
print_header "Checking Velero namespace..."
if kubectl get namespace velero &>/dev/null; then
    print_info "Namespace 'velero' exists"
else
    print_error "Namespace 'velero' not found"
    exit 1
fi
echo ""

# Check if Velero pods are running
print_header "Checking Velero pods..."
VELERO_PODS=$(kubectl get pods -n velero -l app.kubernetes.io/name=velero --no-headers 2>/dev/null | wc -l)
if [ "$VELERO_PODS" -gt 0 ]; then
    print_info "Found $VELERO_PODS Velero pod(s)"
    kubectl get pods -n velero -l app.kubernetes.io/name=velero
    
    # Check if pods are running
    RUNNING_PODS=$(kubectl get pods -n velero -l app.kubernetes.io/name=velero --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
    if [ "$RUNNING_PODS" -eq "$VELERO_PODS" ]; then
        print_info "All Velero pods are running"
    else
        print_warning "Some Velero pods are not running"
    fi
else
    print_error "No Velero pods found"
    exit 1
fi
echo ""

# Check Velero secret
print_header "Checking Velero credentials secret..."
if kubectl get secret velero-credentials -n velero &>/dev/null; then
    print_info "Secret 'velero-credentials' exists"
else
    print_error "Secret 'velero-credentials' not found"
    exit 1
fi
echo ""

# Check backup storage location
print_header "Checking Backup Storage Location..."
if kubectl get backupstoragelocation -n velero &>/dev/null; then
    BSL_COUNT=$(kubectl get backupstoragelocation -n velero --no-headers 2>/dev/null | wc -l)
    if [ "$BSL_COUNT" -gt 0 ]; then
        print_info "Found $BSL_COUNT Backup Storage Location(s)"
        kubectl get backupstoragelocation -n velero
        
        # Check if BSL is available
        AVAILABLE_BSL=$(kubectl get backupstoragelocation -n velero -o jsonpath='{.items[?(@.status.phase=="Available")].metadata.name}' 2>/dev/null)
        if [ -n "$AVAILABLE_BSL" ]; then
            print_info "Backup Storage Location is Available: $AVAILABLE_BSL"
        else
            print_warning "Backup Storage Location is not yet Available. This may take a few minutes."
        fi
    else
        print_error "No Backup Storage Locations found"
    fi
else
    print_error "Unable to check Backup Storage Locations"
fi
echo ""

# Check volume snapshot location
print_header "Checking Volume Snapshot Location..."
if kubectl get volumesnapshotlocation -n velero &>/dev/null; then
    VSL_COUNT=$(kubectl get volumesnapshotlocation -n velero --no-headers 2>/dev/null | wc -l)
    if [ "$VSL_COUNT" -gt 0 ]; then
        print_info "Found $VSL_COUNT Volume Snapshot Location(s)"
        kubectl get volumesnapshotlocation -n velero
    else
        print_warning "No Volume Snapshot Locations found"
    fi
else
    print_warning "Unable to check Volume Snapshot Locations"
fi
echo ""

# Check CSI driver
print_header "Checking CSI VolumeSnapshotClass..."
if kubectl get volumesnapshotclass &>/dev/null; then
    VSC_COUNT=$(kubectl get volumesnapshotclass --no-headers 2>/dev/null | wc -l)
    if [ "$VSC_COUNT" -gt 0 ]; then
        print_info "Found $VSC_COUNT VolumeSnapshotClass(es)"
        kubectl get volumesnapshotclass
    else
        print_warning "No VolumeSnapshotClasses found. PVC snapshots may not work."
    fi
else
    print_warning "Unable to check VolumeSnapshotClasses"
fi
echo ""

# Check scheduled backups
print_header "Checking Scheduled Backups..."
if kubectl get schedule -n velero &>/dev/null; then
    SCHEDULE_COUNT=$(kubectl get schedule -n velero --no-headers 2>/dev/null | wc -l)
    if [ "$SCHEDULE_COUNT" -gt 0 ]; then
        print_info "Found $SCHEDULE_COUNT Scheduled Backup(s)"
        kubectl get schedule -n velero
    else
        print_warning "No Scheduled Backups found"
    fi
else
    print_warning "Unable to check Scheduled Backups"
fi
echo ""

# Check if velero CLI is installed
print_header "Checking Velero CLI..."
if command -v velero &>/dev/null; then
    VELERO_VERSION=$(velero version --client-only 2>/dev/null | grep "Version:" | awk '{print $2}')
    print_info "Velero CLI is installed (Version: $VELERO_VERSION)"
    
    # Run velero backup get if CLI is available
    print_header "Checking existing backups..."
    if velero backup get -n velero &>/dev/null; then
        BACKUP_COUNT=$(velero backup get -n velero --no-headers 2>/dev/null | wc -l)
        if [ "$BACKUP_COUNT" -gt 0 ]; then
            print_info "Found $BACKUP_COUNT backup(s)"
            velero backup get -n velero
        else
            print_info "No backups found yet (this is normal for a new installation)"
        fi
    fi
else
    print_warning "Velero CLI is not installed. Install it for easier management:"
    echo "    https://velero.io/docs/main/basic-install/#install-the-cli"
fi
echo ""

# Check ArgoCD Application (if ArgoCD is installed)
print_header "Checking ArgoCD Application..."
if kubectl get application velero -n argocd &>/dev/null 2>&1; then
    print_info "ArgoCD Application 'velero' exists"
    SYNC_STATUS=$(kubectl get application velero -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null)
    HEALTH_STATUS=$(kubectl get application velero -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null)
    
    if [ "$SYNC_STATUS" = "Synced" ]; then
        print_info "Sync Status: Synced"
    else
        print_warning "Sync Status: $SYNC_STATUS"
    fi
    
    if [ "$HEALTH_STATUS" = "Healthy" ]; then
        print_info "Health Status: Healthy"
    else
        print_warning "Health Status: $HEALTH_STATUS"
    fi
else
    print_warning "ArgoCD Application not found (or ArgoCD not installed)"
fi
echo ""

# Final summary
echo "========================================"
echo "Verification Summary"
echo "========================================"
echo ""
print_info "Velero is installed and running"
echo ""
print_header "Next steps:"
echo "  1. Create a test backup:"
echo "     kubectl create namespace test-velero"
echo "     kubectl create deployment nginx --image=nginx -n test-velero"
echo "     velero backup create test-backup --include-namespaces=test-velero -n velero"
echo ""
echo "  2. Monitor the backup:"
echo "     velero backup describe test-backup -n velero"
echo "     velero backup logs test-backup -n velero"
echo ""
echo "  3. Test restore:"
echo "     kubectl delete namespace test-velero"
echo "     velero restore create --from-backup test-backup -n velero"
echo ""
echo "  4. Monitor scheduled backups:"
echo "     kubectl get backups -n velero -w"
echo ""
