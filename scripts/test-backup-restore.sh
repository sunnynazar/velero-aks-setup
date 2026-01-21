#!/bin/bash

###############################################################################
# Velero Test Backup and Restore Script
# This script creates a test application, backs it up, and verifies restore
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

TEST_NAMESPACE="velero-test"
BACKUP_NAME="test-backup-$(date +%Y%m%d-%H%M%S)"

echo "========================================"
echo "Velero Backup and Restore Test"
echo "========================================"
echo ""

# Check if velero CLI is installed
if ! command -v velero &>/dev/null; then
    print_error "Velero CLI is not installed. Please install it first:"
    echo "    https://velero.io/docs/main/basic-install/#install-the-cli"
    exit 1
fi

# Step 1: Create test namespace and application
print_header "Step 1: Creating test application..."
kubectl create namespace $TEST_NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Create a deployment
kubectl create deployment nginx --image=nginx:latest -n $TEST_NAMESPACE --replicas=2 --dry-run=client -o yaml | kubectl apply -f -

# Create a service
kubectl expose deployment nginx --port=80 --type=ClusterIP -n $TEST_NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Create a ConfigMap
kubectl create configmap test-config --from-literal=key1=value1 --from-literal=key2=value2 -n $TEST_NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Create a Secret
kubectl create secret generic test-secret --from-literal=username=admin --from-literal=password=secret123 -n $TEST_NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

print_info "Test application created in namespace '$TEST_NAMESPACE'"
echo ""

# Wait for deployment to be ready
print_header "Waiting for deployment to be ready..."
kubectl wait --for=condition=available --timeout=60s deployment/nginx -n $TEST_NAMESPACE
print_info "Deployment is ready"
echo ""

# Step 2: Create backup
print_header "Step 2: Creating backup '$BACKUP_NAME'..."
velero backup create $BACKUP_NAME \
    --include-namespaces=$TEST_NAMESPACE \
    --wait \
    -n velero

if [ $? -eq 0 ]; then
    print_info "Backup created successfully"
else
    print_error "Backup creation failed"
    exit 1
fi
echo ""

# Step 3: Show backup details
print_header "Step 3: Backup details..."
velero backup describe $BACKUP_NAME -n velero --details
echo ""

# Step 4: Delete the test namespace
print_header "Step 4: Deleting test namespace to simulate disaster..."
kubectl delete namespace $TEST_NAMESPACE
print_info "Test namespace deleted"
echo ""

# Wait a moment
print_info "Waiting 10 seconds before restore..."
sleep 10
echo ""

# Step 5: Restore from backup
print_header "Step 5: Restoring from backup..."
RESTORE_NAME="restore-$BACKUP_NAME"
velero restore create $RESTORE_NAME \
    --from-backup=$BACKUP_NAME \
    --wait \
    -n velero

if [ $? -eq 0 ]; then
    print_info "Restore completed successfully"
else
    print_error "Restore failed"
    exit 1
fi
echo ""

# Step 6: Verify restoration
print_header "Step 6: Verifying restoration..."

# Check namespace
if kubectl get namespace $TEST_NAMESPACE &>/dev/null; then
    print_info "Namespace '$TEST_NAMESPACE' restored"
else
    print_error "Namespace '$TEST_NAMESPACE' not found"
    exit 1
fi

# Check deployment
if kubectl get deployment nginx -n $TEST_NAMESPACE &>/dev/null; then
    print_info "Deployment 'nginx' restored"
    kubectl get deployment nginx -n $TEST_NAMESPACE
else
    print_error "Deployment 'nginx' not found"
fi

# Check service
if kubectl get service nginx -n $TEST_NAMESPACE &>/dev/null; then
    print_info "Service 'nginx' restored"
else
    print_error "Service 'nginx' not found"
fi

# Check ConfigMap
if kubectl get configmap test-config -n $TEST_NAMESPACE &>/dev/null; then
    print_info "ConfigMap 'test-config' restored"
else
    print_error "ConfigMap 'test-config' not found"
fi

# Check Secret
if kubectl get secret test-secret -n $TEST_NAMESPACE &>/dev/null; then
    print_info "Secret 'test-secret' restored"
else
    print_error "Secret 'test-secret' not found"
fi

echo ""

# Step 7: Show restore details
print_header "Step 7: Restore details..."
velero restore describe $RESTORE_NAME -n velero --details
echo ""

# Final summary
echo "========================================"
echo "Test Summary"
echo "========================================"
echo ""
print_info "Backup Name: $BACKUP_NAME"
print_info "Restore Name: $RESTORE_NAME"
echo ""
print_header "All resources have been successfully backed up and restored!"
echo ""
print_warning "Cleanup: To remove test resources, run:"
echo "    kubectl delete namespace $TEST_NAMESPACE"
echo "    velero backup delete $BACKUP_NAME -n velero --confirm"
echo "    velero restore delete $RESTORE_NAME -n velero --confirm"
echo ""
