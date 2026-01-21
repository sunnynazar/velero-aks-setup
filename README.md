# Velero on AKS with ArgoCD - Complete Setup

This repository contains all the necessary configurations to deploy Velero on Azure Kubernetes Service (AKS) using ArgoCD with cost optimization and complete PVC backup support.

## 📋 Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Detailed Setup](#detailed-setup)
- [Cost Optimization](#cost-optimization)
- [Backup and Restore](#backup-and-restore)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

## 🎯 Overview

This setup provides:
- ✅ Velero backup solution for AKS clusters
- ✅ GitOps deployment via ArgoCD
- ✅ Automated PVC snapshots using Azure Managed Disks
- ✅ Cost-optimized storage with lifecycle policies
- ✅ Scheduled daily and weekly backups
- ✅ CSI driver integration for modern PVC backups

## 📦 Prerequisites

Before you begin, ensure you have:

- [x] An AKS cluster up and running
- [x] `kubectl` configured to access your cluster
- [x] `az` CLI installed and authenticated
- [x] ArgoCD installed in your cluster
- [x] Helm 3.x installed
- [x] Proper Azure RBAC permissions:
  - Storage Account creation
  - Managed Disk snapshots
  - Resource Group access

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                   AKS Cluster                        │
│                                                      │
│  ┌──────────────┐         ┌──────────────┐         │
│  │   ArgoCD     │────────▶│    Velero    │         │
│  │              │         │   Namespace  │         │
│  └──────────────┘         └──────┬───────┘         │
│                                   │                  │
│                          ┌────────▼────────┐        │
│                          │  PVC Snapshots  │        │
│                          │  (CSI Driver)   │        │
│                          └────────┬────────┘        │
└───────────────────────────────────┼──────────────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │     Azure Storage Account      │
                    │  ┌──────────────────────────┐  │
                    │  │  Velero Blob Container   │  │
                    │  │  - Backup metadata       │  │
                    │  │  - Lifecycle policies    │  │
                    │  └──────────────────────────┘  │
                    │  ┌──────────────────────────┐  │
                    │  │  Managed Disk Snapshots  │  │
                    │  │  - Incremental snapshots │  │
                    │  └──────────────────────────┘  │
                    └─────────────────────────────────┘
```

## 🚀 Quick Start

1. **Clone this repository:**
   ```bash
   git clone https://github.com/YOUR-USERNAME/velero-aks-setup.git
   cd velero-aks-setup
   ```

2. **Run the setup script:**
   ```bash
   chmod +x scripts/setup-azure.sh
   ./scripts/setup-azure.sh
   ```

3. **Update configuration:**
   ```bash
   # Edit with your values
   cp config/config.example.env config/config.env
   vim config/config.env
   ```

4. **Deploy with ArgoCD:**
   ```bash
   kubectl apply -f argocd/velero-application.yaml
   ```

## 📖 Detailed Setup

### Step 1: Azure Infrastructure Setup

Run the Azure setup script to create necessary resources:

```bash
cd scripts
./setup-azure.sh
```

This script creates:
- Storage Account (Standard_LRS for cost optimization)
- Blob Container for Velero backups
- Lifecycle management policies
- Retrieves necessary credentials

### Step 2: Configure Values

Update the `velero/values.yaml` file with your Azure details:

```yaml
configuration:
  backupStorageLocation:
    - name: default
      provider: azure
      bucket: velero-backups
      config:
        resourceGroup: YOUR_RESOURCE_GROUP
        storageAccount: YOUR_STORAGE_ACCOUNT
        subscriptionId: YOUR_SUBSCRIPTION_ID
```

### Step 3: Create Kubernetes Secret

```bash
# The setup script generates this, or create manually:
kubectl create namespace velero

kubectl create secret generic velero-credentials \
  --namespace velero \
  --from-literal=cloud="$(cat config/credentials-velero)"
```

### Step 4: Deploy via ArgoCD

```bash
# Apply the ArgoCD application
kubectl apply -f argocd/velero-application.yaml

# Watch the deployment
kubectl get application velero -n argocd -w
```

### Step 5: Verify Installation

```bash
# Check Velero pods
kubectl get pods -n velero

# Verify backup location
kubectl get backupstoragelocation -n velero

# Check volume snapshot location
kubectl get volumesnapshotlocation -n velero

# Verify CSI driver
kubectl get volumesnapshotclass
```

## 💰 Cost Optimization

This setup implements several cost-saving measures:

### 1. Storage Tier Optimization
- **Standard_LRS** storage account (cheapest option)
- **Hot tier** for recent backups
- **Cool tier** after 30 days (60% cheaper)
- **Archive tier** after 90 days (90% cheaper)
- **Auto-deletion** after 180 days

### 2. Incremental Snapshots
- Only stores changed blocks
- Reduces storage costs by 80-90% for subsequent snapshots

### 3. Optimized Backup Schedule
- Daily backups: 30-day retention
- Weekly backups: 90-day retention
- Customize based on your compliance needs

### 4. Resource Limits
- Minimal CPU/Memory allocation for Velero pods
- Scales only when needed

### 5. Estimated Monthly Costs (example)

For a 100GB cluster:
- Storage Account: ~$2/month
- Snapshots (incremental): ~$5-10/month
- Total: **~$7-12/month**

## 🔄 Backup and Restore

### Create Manual Backup

```bash
# Backup entire cluster
velero backup create full-backup

# Backup specific namespace
velero backup create app-backup --include-namespaces=production

# Backup with PVC snapshots
velero backup create pvc-backup --snapshot-volumes=true

# Backup specific resources
velero backup create db-backup \
  --include-resources=persistentvolumeclaims,persistentvolumes \
  --selector app=postgresql
```

### Restore from Backup

```bash
# List available backups
velero backup get

# Restore entire backup
velero restore create --from-backup full-backup

# Restore specific namespace
velero restore create --from-backup app-backup \
  --include-namespaces=production

# Restore to different namespace
velero restore create --from-backup app-backup \
  --namespace-mappings old-namespace:new-namespace
```

### Scheduled Backups

Backups are automatically created based on the schedule in `values.yaml`:
- **Daily**: 2 AM UTC (30-day retention)
- **Weekly**: 3 AM Sunday UTC (90-day retention)

Customize schedules:
```yaml
schedules:
  custom-backup:
    schedule: "0 */6 * * *"  # Every 6 hours
    template:
      ttl: 168h  # 7 days
```

## 📊 Monitoring

### Check Backup Status

```bash
# List all backups
velero backup get

# Describe specific backup
velero backup describe daily-backup-20240119

# View backup logs
velero backup logs daily-backup-20240119

# Check for failed backups
velero backup get | grep -i failed
```

### Prometheus Metrics

If you have Prometheus Operator installed:

```yaml
# Enable in values.yaml
metrics:
  enabled: true
  serviceMonitor:
    enabled: true
```

Key metrics to monitor:
- `velero_backup_success_total`
- `velero_backup_failure_total`
- `velero_backup_duration_seconds`
- `velero_volume_snapshot_success_total`

### Set Up Alerts

Example Prometheus alert:

```yaml
- alert: VeleroBackupFailed
  expr: velero_backup_failure_total > 0
  for: 5m
  annotations:
    summary: "Velero backup has failed"
```

## 🔧 Troubleshooting

### Common Issues

#### 1. Backup Stuck in Progress
```bash
# Check Velero logs
kubectl logs -n velero deployment/velero

# Delete stuck backup
velero backup delete BACKUP_NAME --confirm
```

#### 2. PVC Snapshots Not Working
```bash
# Verify CSI driver
kubectl get volumesnapshotclass

# Check snapshot CRDs
kubectl get crd | grep snapshot

# Verify Azure permissions
az role assignment list --assignee $(az aks show -g RG -n CLUSTER --query identityProfile.kubeletidentity.clientId -o tsv)
```

#### 3. Authentication Errors
```bash
# Verify secret exists
kubectl get secret velero-credentials -n velero

# Check secret content
kubectl get secret velero-credentials -n velero -o yaml

# Recreate secret
kubectl delete secret velero-credentials -n velero
./scripts/create-secret.sh
```

#### 4. Storage Access Issues
```bash
# Test storage account access
az storage container list --account-name STORAGE_ACCOUNT

# Verify firewall rules
az storage account show --name STORAGE_ACCOUNT --query networkRuleSet
```

### Debug Commands

```bash
# Enable debug logging
kubectl set env deployment/velero -n velero VELERO_LOG_LEVEL=debug

# Check all Velero resources
kubectl get all -n velero

# Describe backup storage location
kubectl describe backupstoragelocation default -n velero

# Check events
kubectl get events -n velero --sort-by='.lastTimestamp'
```

## 🔐 Security Best Practices

1. **Use Managed Identity** instead of storage keys (optional enhancement)
2. **Enable encryption at rest** for storage account
3. **Restrict network access** to storage account
4. **Rotate credentials** regularly
5. **Use Azure Key Vault** for secret management (optional)

## 📚 Additional Resources

- [Velero Documentation](https://velero.io/docs/)
- [Azure Backup Documentation](https://learn.microsoft.com/en-us/azure/backup/)
- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [AKS Best Practices](https://learn.microsoft.com/en-us/azure/aks/best-practices)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📧 Support

For issues and questions:
- Open an issue in this repository
- Check the [Troubleshooting](#troubleshooting) section
- Review Velero Slack channel

---

**Happy Backing Up! 🎉**
