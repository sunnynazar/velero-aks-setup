# Installation Guide

Complete step-by-step guide to install Velero on AKS using ArgoCD.

## Prerequisites Checklist

Before starting, ensure you have:

- [ ] Azure CLI (`az`) installed and authenticated
- [ ] kubectl installed and configured for your AKS cluster
- [ ] Helm 3.x installed
- [ ] ArgoCD installed in your AKS cluster
- [ ] Proper Azure permissions:
  - [ ] Create/manage storage accounts
  - [ ] Create/manage disk snapshots
  - [ ] Read/write access to resource group

## Quick Installation (5 minutes)

### Option 1: Automated Setup

```bash
# 1. Clone the repository
git clone https://github.com/YOUR-USERNAME/velero-aks-setup.git
cd velero-aks-setup

# 2. Run the setup script
chmod +x scripts/setup-azure.sh
./scripts/setup-azure.sh

# 3. Deploy with ArgoCD
kubectl apply -f argocd/velero-application.yaml

# 4. Verify installation
kubectl get pods -n velero
velero backup location get
```

## Detailed Installation

### Step 1: Clone Repository

```bash
git clone https://github.com/YOUR-USERNAME/velero-aks-setup.git
cd velero-aks-setup
```

### Step 2: Configure Azure Settings

Create your configuration file:

```bash
cp config/config.example.env config/config.env
```

Edit `config/config.env` with your values:

```bash
AZURE_SUBSCRIPTION_ID=your-subscription-id
AZURE_RESOURCE_GROUP=velero-rg
AZURE_LOCATION=eastus
STORAGE_ACCOUNT_PREFIX=velerobackup
BLOB_CONTAINER=velero-backups
```

### Step 3: Run Azure Setup

The setup script will:
- Create storage account with cost-optimized settings
- Create blob container for backups
- Configure lifecycle management policies
- Create Kubernetes secret
- Update values.yaml with your configuration

```bash
chmod +x scripts/setup-azure.sh
./scripts/setup-azure.sh
```

**Expected Output:**
```
[INFO] Checking prerequisites...
[INFO] Prerequisites check passed!
[INFO] Configuration:
  Subscription ID: xxxxxxxxx
  Resource Group: velero-rg
  Location: eastus
  Storage Account: velerobackup1234567
  Blob Container: velero-backups
Continue with this configuration? (y/n)
```

### Step 4: Verify Azure Resources

```bash
# Check storage account
az storage account show \
  --name $(grep STORAGE_ACCOUNT config/config.env | cut -d'=' -f2) \
  --resource-group $(grep AZURE_RESOURCE_GROUP config/config.env | cut -d'=' -f2)

# Check blob container
az storage container show \
  --name velero-backups \
  --account-name $(grep STORAGE_ACCOUNT config/config.env | cut -d'=' -f2)

# Verify Kubernetes secret
kubectl get secret velero-credentials -n velero -o yaml
```

### Step 5: Review Velero Configuration

Open `velero/values.yaml` and verify the configuration has been updated with your Azure details:

```yaml
configuration:
  backupStorageLocation:
    - name: default
      provider: azure
      bucket: velero-backups
      config:
        resourceGroup: velero-rg  # Your resource group
        storageAccount: velerobackup1234567  # Your storage account
        subscriptionId: your-subscription-id  # Your subscription
```

**Optional customizations:**

- Adjust backup schedules
- Modify retention periods
- Configure resource limits
- Enable/disable features

### Step 6: Deploy with ArgoCD

#### Option A: Direct Helm Chart Deployment

```bash
kubectl apply -f argocd/velero-application.yaml
```

This uses the Velero Helm chart directly from the official repository.

#### Option B: GitOps Deployment

If you want ArgoCD to pull from your Git repository:

1. Push this repository to your GitHub account
2. Update `argocd/velero-application-git.yaml`:
   ```yaml
   source:
     repoURL: https://github.com/YOUR-USERNAME/velero-aks-setup.git
   ```
3. Apply the application:
   ```bash
   kubectl apply -f argocd/velero-application-git.yaml
   ```

### Step 7: Monitor Deployment

```bash
# Watch ArgoCD application
kubectl get application velero -n argocd -w

# Watch Velero pods
kubectl get pods -n velero -w

# Check ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Open https://localhost:8080
```

### Step 8: Verify Installation

Run the verification script:

```bash
chmod +x scripts/verify-installation.sh
./scripts/verify-installation.sh
```

**Expected Output:**
```
========================================
Velero Installation Verification
========================================

[✓] Namespace 'velero' exists
[✓] Found 1 Velero pod(s)
[✓] All Velero pods are running
[✓] Secret 'velero-credentials' exists
[✓] Found 1 Backup Storage Location(s)
[✓] Backup Storage Location is Available: default
[✓] Found 1 Volume Snapshot Location(s)
[✓] Found 2 VolumeSnapshotClass(es)
[✓] Found 2 Scheduled Backup(s)
```

### Step 9: Install Velero CLI (Optional but Recommended)

#### macOS
```bash
brew install velero
```

#### Linux
```bash
wget https://github.com/vmware-tanzu/velero/releases/download/v1.13.0/velero-v1.13.0-linux-amd64.tar.gz
tar -xvf velero-v1.13.0-linux-amd64.tar.gz
sudo mv velero-v1.13.0-linux-amd64/velero /usr/local/bin/
```

#### Windows
```powershell
choco install velero
```

Verify installation:
```bash
velero version
```

### Step 10: Test Backup and Restore

Run the test script:

```bash
chmod +x scripts/test-backup-restore.sh
./scripts/test-backup-restore.sh
```

This will:
1. Create a test namespace with sample application
2. Back up the application
3. Delete the namespace (simulating disaster)
4. Restore from backup
5. Verify all resources are restored

## Post-Installation Configuration

### Configure Automatic Backups

Scheduled backups are already configured in `values.yaml`. To customize:

```bash
# Edit values.yaml
vim velero/values.yaml

# Update the schedules section
schedules:
  daily-backup:
    schedule: "0 2 * * *"  # Change to your preferred time
    template:
      ttl: 720h  # Change retention period
```

After changes, commit and ArgoCD will auto-sync (if auto-sync enabled).

### Set Up Monitoring (Optional)

If you have Prometheus Operator:

```bash
# Edit values.yaml
metrics:
  enabled: true
  serviceMonitor:
    enabled: true

# Apply changes via ArgoCD
git add velero/values.yaml
git commit -m "Enable Prometheus monitoring"
git push
```

### Configure Backup Hooks (Optional)

For database consistency:

```bash
kubectl annotate pod postgresql-0 \
  pre.hook.backup.velero.io/command='["/bin/bash", "-c", "pg_dump mydb > /tmp/backup.sql"]' \
  pre.hook.backup.velero.io/timeout=3m \
  -n production
```

## Verification Checklist

After installation, verify:

- [ ] Velero pods are running
- [ ] Backup storage location is available
- [ ] Volume snapshot location is configured
- [ ] VolumeSnapshotClass exists
- [ ] Scheduled backups are created
- [ ] Test backup completes successfully
- [ ] Test restore works correctly
- [ ] ArgoCD application is synced and healthy

## Common Post-Installation Tasks

### Create First Production Backup

```bash
# Backup specific namespace
velero backup create production-backup \
  --include-namespaces=production \
  --snapshot-volumes=true

# Monitor progress
velero backup describe production-backup --details
```

### Set Up Monitoring Alerts

```bash
# Example Prometheus alert
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: velero-alerts
  namespace: velero
spec:
  groups:
  - name: velero
    rules:
    - alert: VeleroBackupFailed
      expr: velero_backup_failure_total > 0
      for: 5m
      annotations:
        summary: "Velero backup failed"
```

### Document Your Backup Strategy

Create a backup runbook for your team:
- Backup schedules
- Retention policies
- Recovery procedures
- Contact information

## Troubleshooting Installation Issues

### Issue: ArgoCD Application Won't Sync

```bash
# Check application status
kubectl get application velero -n argocd -o yaml

# Force sync
kubectl patch application velero -n argocd \
  --type merge \
  --patch '{"operation":{"sync":{"syncOptions":["Force=true"]}}}'
```

### Issue: Pods in CrashLoopBackOff

```bash
# Check logs
kubectl logs -n velero deployment/velero

# Common fix: Recreate secret
kubectl delete secret velero-credentials -n velero
./scripts/setup-azure.sh
kubectl rollout restart deployment velero -n velero
```

### Issue: Backup Storage Location Unavailable

```bash
# Check storage account access
az storage container list --account-name YOUR_STORAGE_ACCOUNT

# Verify network rules
az storage account show --name YOUR_STORAGE_ACCOUNT --query networkRuleSet
```

For more troubleshooting, see [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Next Steps

1. **Review backup strategies**: See [BACKUP_STRATEGIES.md](docs/BACKUP_STRATEGIES.md)
2. **Set up monitoring**: Configure Prometheus/Grafana
3. **Schedule disaster recovery drills**: Test restores monthly
4. **Document procedures**: Create runbooks for your team
5. **Configure alerts**: Set up notifications for failed backups

## Uninstallation

If you need to remove Velero:

```bash
# Delete ArgoCD application
kubectl delete application velero -n argocd

# Delete namespace
kubectl delete namespace velero

# Delete Azure resources (optional)
az storage account delete \
  --name YOUR_STORAGE_ACCOUNT \
  --resource-group YOUR_RESOURCE_GROUP
```

## Getting Help

- Check [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- Review Velero logs: `kubectl logs -n velero deployment/velero`
- Open an issue in this repository
- Join Velero Slack: [velero.io](https://velero.io)
