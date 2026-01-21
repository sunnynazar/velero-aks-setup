# Velero Troubleshooting Guide

Common issues and their solutions when running Velero on AKS.

## Table of Contents

- [Installation Issues](#installation-issues)
- [Backup Issues](#backup-issues)
- [Restore Issues](#restore-issues)
- [Storage Issues](#storage-issues)
- [Performance Issues](#performance-issues)
- [Debugging Tools](#debugging-tools)

## Installation Issues

### Issue: Velero Pod Not Starting

**Symptoms:**
```bash
kubectl get pods -n velero
# Shows pod in CrashLoopBackOff or Error state
```

**Diagnosis:**
```bash
kubectl logs -n velero deployment/velero
kubectl describe pod -n velero -l app.kubernetes.io/name=velero
```

**Common Causes & Solutions:**

1. **Missing or Invalid Credentials**
   ```bash
   # Verify secret exists
   kubectl get secret velero-credentials -n velero
   
   # Check secret contents
   kubectl get secret velero-credentials -n velero -o yaml
   
   # Recreate if needed
   kubectl delete secret velero-credentials -n velero
   ./scripts/setup-azure.sh
   ```

2. **Invalid Azure Configuration**
   - Check storage account name, resource group, subscription ID
   - Verify permissions on Azure resources
   ```bash
   az storage account show --name YOUR_STORAGE_ACCOUNT --resource-group YOUR_RG
   ```

3. **Plugin Installation Failed**
   ```bash
   # Check init containers
   kubectl describe pod -n velero POD_NAME | grep -A 10 "Init Containers"
   
   # Verify plugins loaded
   kubectl exec -n velero deployment/velero -- velero plugin get
   ```

### Issue: Backup Storage Location Not Available

**Symptoms:**
```bash
kubectl get backupstoragelocation -n velero
# Shows "Unavailable" status
```

**Diagnosis:**
```bash
kubectl describe backupstoragelocation default -n velero
```

**Solutions:**

1. **Storage Account Access Issues**
   ```bash
   # Test access from your machine
   az storage container list --account-name YOUR_STORAGE_ACCOUNT
   
   # Check firewall rules
   az storage account show \
     --name YOUR_STORAGE_ACCOUNT \
     --query networkRuleSet
   
   # If firewall enabled, add AKS subnet
   az storage account network-rule add \
     --account-name YOUR_STORAGE_ACCOUNT \
     --subnet SUBNET_ID
   ```

2. **Wrong Storage Account Key**
   ```bash
   # Get new key
   NEW_KEY=$(az storage account keys list \
     --resource-group YOUR_RG \
     --account-name YOUR_STORAGE_ACCOUNT \
     --query "[0].value" -o tsv)
   
   # Update secret
   kubectl create secret generic velero-credentials \
     --namespace velero \
     --from-literal=cloud="AZURE_STORAGE_ACCOUNT_ACCESS_KEY=${NEW_KEY}" \
     --dry-run=client -o yaml | kubectl apply -f -
   
   # Restart Velero
   kubectl rollout restart deployment velero -n velero
   ```

## Backup Issues

### Issue: Backup Stuck in "InProgress" State

**Symptoms:**
```bash
velero backup get
# Shows backup stuck in InProgress for extended time
```

**Diagnosis:**
```bash
velero backup describe BACKUP_NAME --details
velero backup logs BACKUP_NAME
kubectl logs -n velero deployment/velero
```

**Solutions:**

1. **Delete Stuck Backup**
   ```bash
   velero backup delete BACKUP_NAME --confirm
   ```

2. **Check for Resource Locks**
   ```bash
   # Look for resources that might be blocking
   kubectl get events --all-namespaces --sort-by='.lastTimestamp'
   ```

3. **Increase Timeout**
   ```yaml
   # In values.yaml
   configuration:
     volumeSnapshotLocation:
       config:
         apiTimeout: 10m  # Increase from default
   ```

### Issue: PVC Snapshots Not Created

**Symptoms:**
```bash
velero backup describe BACKUP_NAME
# Shows "0 of X snapshots completed"
```

**Diagnosis:**
```bash
# Check VolumeSnapshotClass
kubectl get volumesnapshotclass

# Check CSI driver
kubectl get csidrivers

# Check volume snapshot CRDs
kubectl get crd | grep snapshot
```

**Solutions:**

1. **Install Snapshot CRDs** (if missing)
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/release-6.2/client/config/crd/snapshot.storage.k8s.io_volumesnapshotclasses.yaml
   kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/release-6.2/client/config/crd/snapshot.storage.k8s.io_volumesnapshotcontents.yaml
   kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/release-6.2/client/config/crd/snapshot.storage.k8s.io_volumesnapshots.yaml
   ```

2. **Create VolumeSnapshotClass**
   ```yaml
   apiVersion: snapshot.storage.k8s.io/v1
   kind: VolumeSnapshotClass
   metadata:
     name: csi-azuredisk-vsc
   driver: disk.csi.azure.com
   deletionPolicy: Delete
   parameters:
     incremental: "true"
   ```

3. **Verify Azure Permissions**
   ```bash
   # Check AKS identity has snapshot permissions
   az role assignment list --assignee $(az aks show -g YOUR_RG -n YOUR_CLUSTER --query identityProfile.kubeletidentity.clientId -o tsv)
   ```

### Issue: Backup Partially Failed

**Symptoms:**
```bash
velero backup get
# Shows "PartiallyFailed" status
```

**Diagnosis:**
```bash
velero backup describe BACKUP_NAME --details
velero backup logs BACKUP_NAME | grep -i error
```

**Common Causes:**

1. **Resource Access Issues**
   - Check if Velero service account has proper RBAC
   ```bash
   kubectl describe clusterrole velero
   kubectl describe clusterrolebinding velero
   ```

2. **Webhook Timeouts**
   ```bash
   # Check for webhook issues
   kubectl get validatingwebhookconfigurations
   kubectl get mutatingwebhookconfigurations
   
   # Temporarily disable problematic webhooks
   kubectl delete validatingwebhookconfiguration WEBHOOK_NAME
   ```

3. **Resource Too Large**
   - Exclude large resources not needed for recovery
   ```bash
   velero backup create BACKUP_NAME \
     --exclude-resources=events,backups.velero.io
   ```

## Restore Issues

### Issue: Restore Stuck or Fails

**Symptoms:**
```bash
velero restore get
# Shows restore in "InProgress" or "PartiallyFailed"
```

**Diagnosis:**
```bash
velero restore describe RESTORE_NAME --details
velero restore logs RESTORE_NAME
```

**Solutions:**

1. **Namespace Already Exists**
   ```bash
   # Delete existing namespace first
   kubectl delete namespace TARGET_NAMESPACE
   
   # Or use namespace mapping
   velero restore create RESTORE_NAME \
     --from-backup BACKUP_NAME \
     --namespace-mappings old-ns:new-ns
   ```

2. **Resource Conflicts**
   ```bash
   # Skip existing resources
   velero restore create RESTORE_NAME \
     --from-backup BACKUP_NAME \
     --existing-resource-policy=none
   ```

3. **PVC Restoration Issues**
   ```bash
   # Check PVC status
   kubectl get pvc -n TARGET_NAMESPACE
   
   # Check events
   kubectl get events -n TARGET_NAMESPACE --sort-by='.lastTimestamp'
   
   # Verify storage class exists
   kubectl get storageclass
   ```

### Issue: Restored Pods Not Starting

**Diagnosis:**
```bash
kubectl get pods -n NAMESPACE
kubectl describe pod POD_NAME -n NAMESPACE
kubectl logs POD_NAME -n NAMESPACE
```

**Solutions:**

1. **PVC Not Bound**
   ```bash
   kubectl get pvc -n NAMESPACE
   # If pending, check storage class and provisioner
   ```

2. **Image Pull Issues**
   ```bash
   # Check image pull secrets
   kubectl get secrets -n NAMESPACE
   ```

3. **Resource Constraints**
   ```bash
   # Check node resources
   kubectl top nodes
   kubectl describe nodes
   ```

## Storage Issues

### Issue: High Storage Costs

**Diagnosis:**
```bash
# List all backups
velero backup get

# Check storage usage
az storage blob list \
  --account-name YOUR_STORAGE_ACCOUNT \
  --container-name velero-backups \
  --query "[].{Name:name, Size:properties.contentLength}" \
  --output table
```

**Solutions:**

1. **Implement Lifecycle Policies** (if not already done)
   ```bash
   # Verify lifecycle policy
   az storage account management-policy show \
     --account-name YOUR_STORAGE_ACCOUNT \
     --resource-group YOUR_RG
   ```

2. **Delete Old Backups**
   ```bash
   # List old backups
   velero backup get --output json | jq '.items[] | select(.status.expiration < now) | .metadata.name'
   
   # Delete backups older than X days
   for backup in $(velero backup get --output json | jq -r '.items[] | select(.status.completionTimestamp < "2024-01-01") | .metadata.name'); do
     velero backup delete $backup --confirm
   done
   ```

3. **Optimize Backup Size**
   ```bash
   # Exclude unnecessary resources
   velero backup create BACKUP_NAME \
     --exclude-resources=events,logs \
     --exclude-namespaces=kube-system,kube-public
   ```

### Issue: Cannot Access Storage Account

**Symptoms:**
```bash
# Velero logs show authentication errors
```

**Solutions:**

1. **Check Network Rules**
   ```bash
   # Show network rules
   az storage account show \
     --name YOUR_STORAGE_ACCOUNT \
     --query networkRuleSet
   
   # Allow all networks (not recommended for production)
   az storage account update \
     --name YOUR_STORAGE_ACCOUNT \
     --resource-group YOUR_RG \
     --default-action Allow
   
   # Or add specific IP/subnet
   az storage account network-rule add \
     --account-name YOUR_STORAGE_ACCOUNT \
     --ip-address YOUR_IP
   ```

2. **Rotate Storage Key**
   ```bash
   # Regenerate key
   az storage account keys renew \
     --account-name YOUR_STORAGE_ACCOUNT \
     --resource-group YOUR_RG \
     --key primary
   
   # Update Velero secret
   ./scripts/setup-azure.sh
   ```

## Performance Issues

### Issue: Backup Takes Too Long

**Diagnosis:**
```bash
# Check backup duration
velero backup describe BACKUP_NAME | grep "Started:"
velero backup describe BACKUP_NAME | grep "Completed:"

# Check resource count
velero backup describe BACKUP_NAME --details | grep "Total items"
```

**Solutions:**

1. **Use Snapshots Instead of File Backup**
   ```yaml
   # In values.yaml
   schedules:
     daily-backup:
       template:
         snapshotVolumes: true
         defaultVolumesToFsBackup: false  # Don't use file backup
   ```

2. **Exclude Unnecessary Resources**
   ```bash
   velero backup create BACKUP_NAME \
     --exclude-resources=events,replicasets.apps
   ```

3. **Increase Velero Resources**
   ```yaml
   # In values.yaml
   resources:
     limits:
       cpu: 1000m
       memory: 1Gi
   ```

4. **Parallel Snapshots**
   ```yaml
   # In values.yaml - already optimized
   configuration:
     volumeSnapshotLocation:
       config:
         apiTimeout: 5m
   ```

### Issue: Slow Restore Performance

**Solutions:**

1. **Restore Only What's Needed**
   ```bash
   velero restore create RESTORE_NAME \
     --from-backup BACKUP_NAME \
     --include-namespaces=production
   ```

2. **Use Partial Restore**
   ```bash
   # Restore specific resources
   velero restore create RESTORE_NAME \
     --from-backup BACKUP_NAME \
     --include-resources=deployments,services
   ```

## Debugging Tools

### Enable Debug Logging

```bash
# Temporary (until pod restart)
kubectl set env deployment/velero -n velero VELERO_LOG_LEVEL=debug

# Permanent (in values.yaml)
logLevel: debug
```

### Check All Velero Resources

```bash
# Get all Velero CRDs
kubectl get backups,restores,schedules,backupstoragelocations,volumesnapshotlocations -n velero

# Check specific resource
kubectl get backup BACKUP_NAME -n velero -o yaml
```

### Examine Events

```bash
# Velero namespace events
kubectl get events -n velero --sort-by='.lastTimestamp'

# All events
kubectl get events --all-namespaces --sort-by='.lastTimestamp' | grep -i velero
```

### Check Velero Server Status

```bash
# Port forward to Velero metrics
kubectl port-forward -n velero deployment/velero 8085:8085

# Access metrics (in another terminal)
curl http://localhost:8085/metrics
```

### Common kubectl Commands

```bash
# Get Velero deployment status
kubectl get deployment -n velero

# Check pod logs
kubectl logs -n velero deployment/velero --tail=100 -f

# Describe backup storage location
kubectl describe backupstoragelocation default -n velero

# Get backup in YAML format
kubectl get backup BACKUP_NAME -n velero -o yaml > backup.yaml
```

### Azure CLI Commands

```bash
# List snapshots
az snapshot list --resource-group YOUR_RG --output table

# Check storage account
az storage account show --name YOUR_STORAGE_ACCOUNT --resource-group YOUR_RG

# List blobs
az storage blob list \
  --account-name YOUR_STORAGE_ACCOUNT \
  --container-name velero-backups \
  --output table
```

## Getting Help

### Check Logs in Order

1. **Velero pod logs**
   ```bash
   kubectl logs -n velero deployment/velero --tail=200
   ```

2. **Backup/Restore logs**
   ```bash
   velero backup logs BACKUP_NAME
   velero restore logs RESTORE_NAME
   ```

3. **Kubernetes events**
   ```bash
   kubectl get events -n velero --sort-by='.lastTimestamp'
   ```

### Useful velero Commands

```bash
# Get backup details
velero backup describe BACKUP_NAME --details

# Get restore details
velero restore describe RESTORE_NAME --details

# Download backup logs to file
velero backup logs BACKUP_NAME > backup.log

# Check Velero version
velero version

# Get plugin information
kubectl exec -n velero deployment/velero -- velero plugin get
```

### Create Debug Bundle

```bash
# Collect all relevant information
mkdir velero-debug
velero backup get > velero-debug/backups.txt
velero restore get > velero-debug/restores.txt
kubectl get all -n velero > velero-debug/resources.txt
kubectl describe backupstoragelocation default -n velero > velero-debug/bsl.txt
kubectl logs -n velero deployment/velero --tail=500 > velero-debug/velero-logs.txt
tar -czf velero-debug.tar.gz velero-debug/
```

## Additional Resources

- [Velero Troubleshooting Docs](https://velero.io/docs/main/troubleshooting/)
- [Velero GitHub Issues](https://github.com/vmware-tanzu/velero/issues)
- [Azure AKS Troubleshooting](https://learn.microsoft.com/en-us/azure/aks/troubleshooting)
