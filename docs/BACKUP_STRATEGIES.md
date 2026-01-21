# Velero Backup Strategies for AKS

This document outlines recommended backup strategies for different scenarios when using Velero on AKS.

## Table of Contents

- [Backup Types](#backup-types)
- [Retention Policies](#retention-policies)
- [Scheduling Strategies](#scheduling-strategies)
- [PVC Backup Methods](#pvc-backup-methods)
- [Application-Specific Considerations](#application-specific-considerations)

## Backup Types

### 1. Full Cluster Backup

Backs up all namespaces and resources in the cluster.

```bash
velero backup create full-cluster-backup \
  --include-namespaces='*' \
  --snapshot-volumes=true
```

**Use cases:**
- Disaster recovery
- Cluster migration
- Major upgrades

**Recommended schedule:** Weekly

### 2. Namespace-Specific Backup

Backs up specific namespaces.

```bash
velero backup create app-backup \
  --include-namespaces=production,staging \
  --snapshot-volumes=true
```

**Use cases:**
- Application-specific backups
- Multi-tenant clusters
- Selective restoration

**Recommended schedule:** Daily

### 3. Resource-Type Backup

Backs up specific resource types.

```bash
velero backup create pvc-backup \
  --include-resources=persistentvolumeclaims,persistentvolumes \
  --snapshot-volumes=true
```

**Use cases:**
- Database backups
- Stateful application data
- Storage-focused recovery

**Recommended schedule:** Every 6 hours for critical data

### 4. Label-Based Backup

Backs up resources matching specific labels.

```bash
velero backup create critical-apps-backup \
  --selector tier=critical \
  --snapshot-volumes=true
```

**Use cases:**
- Priority-based backups
- Environment-specific backups
- Cost optimization (backup only critical resources)

## Retention Policies

### Recommended Retention Schedule

| Backup Type | Frequency | Retention Period | Storage Tier |
|-------------|-----------|------------------|--------------|
| Hourly | Every 6 hours | 2 days | Hot |
| Daily | Once daily | 30 days | Hot → Cool (after 7 days) |
| Weekly | Sunday 3 AM | 90 days | Hot → Cool → Archive |
| Monthly | 1st of month | 1 year | Archive |

### Implementation in values.yaml

```yaml
schedules:
  hourly-critical:
    schedule: "0 */6 * * *"
    template:
      ttl: 48h
      selector: tier=critical
  
  daily-all:
    schedule: "0 2 * * *"
    template:
      ttl: 720h  # 30 days
  
  weekly-all:
    schedule: "0 3 * * 0"
    template:
      ttl: 2160h  # 90 days
  
  monthly-all:
    schedule: "0 4 1 * *"
    template:
      ttl: 8760h  # 365 days
```

## Scheduling Strategies

### Strategy 1: Time-Based Scheduling

**Best for:** Predictable workloads

```yaml
# Daily at 2 AM (low traffic time)
schedule: "0 2 * * *"

# Every 6 hours
schedule: "0 */6 * * *"

# Weekly on Sunday at 3 AM
schedule: "0 3 * * 0"
```

### Strategy 2: Frequency-Based by Criticality

**Best for:** Mixed workload priorities

```yaml
schedules:
  critical-apps:
    schedule: "0 */4 * * *"  # Every 4 hours
    template:
      selector: tier=critical
      ttl: 168h
  
  standard-apps:
    schedule: "0 2 * * *"  # Daily
    template:
      selector: tier=standard
      ttl: 168h
  
  dev-apps:
    schedule: "0 3 * * 0"  # Weekly
    template:
      selector: tier=development
      ttl: 168h
```

### Strategy 3: Application Lifecycle-Based

**Best for:** Multi-environment setups

```yaml
schedules:
  production:
    schedule: "0 */6 * * *"
    template:
      include-namespaces: production
      ttl: 2160h
  
  staging:
    schedule: "0 2 * * *"
    template:
      include-namespaces: staging
      ttl: 168h
  
  development:
    schedule: "0 3 * * 6"  # Saturday
    template:
      include-namespaces: development
      ttl: 72h
```

## PVC Backup Methods

### Method 1: CSI Snapshots (Recommended for AKS)

**Advantages:**
- Fast backup and restore
- Incremental snapshots (cost-effective)
- Native Azure integration
- No agent required

**Configuration:**
```yaml
configuration:
  features: EnableCSI
  volumeSnapshotLocation:
    - name: default
      provider: azure
      config:
        incremental: "true"

schedules:
  daily-with-snapshots:
    template:
      snapshotVolumes: true
      defaultVolumesToFsBackup: false
```

**Use when:**
- Using Azure Managed Disks
- Need fast recovery times
- Have CSI driver installed

### Method 2: File-Based Backup (Restic/Kopia)

**Advantages:**
- Works with any storage type
- More granular backup
- Cross-cloud portable

**Configuration:**
```yaml
deployNodeAgent: true

schedules:
  daily-file-backup:
    template:
      defaultVolumesToFsBackup: true
      snapshotVolumes: false
```

**Use when:**
- Using Azure Files or other non-snapshot storage
- Need cross-platform portability
- Snapshots not available

### Method 3: Hybrid Approach

**Best for:** Mixed storage types

```yaml
# Annotate PVCs for file backup
kubectl annotate pvc my-pvc backup.velero.io/backup-volumes=volume-name

# Schedule uses both methods
schedules:
  hybrid-backup:
    template:
      snapshotVolumes: true  # For managed disks
      defaultVolumesToFsBackup: false  # Except annotated PVCs
```

## Application-Specific Considerations

### Databases (PostgreSQL, MySQL, MongoDB)

**Recommended approach:**

1. **Pre-backup hooks** for consistency:
```yaml
# In pod annotation
pre.hook.backup.velero.io/command: '["/bin/bash", "-c", "pg_dump mydb > /tmp/backup.sql"]'
pre.hook.backup.velero.io/timeout: 3m
```

2. **Frequent snapshots:**
```yaml
schedules:
  database-backup:
    schedule: "0 */4 * * *"  # Every 4 hours
    template:
      include-resources: persistentvolumeclaims
      selector: app=postgresql
      ttl: 720h
```

3. **Long-term archival:**
```yaml
schedules:
  database-monthly:
    schedule: "0 0 1 * *"  # Monthly
    template:
      selector: app=postgresql
      ttl: 8760h  # 1 year
```

### Stateless Applications

**Recommended approach:**

```yaml
schedules:
  stateless-backup:
    schedule: "0 3 * * 0"  # Weekly
    template:
      include-namespaces: app-namespace
      exclude-resources: persistentvolumeclaims
      ttl: 720h
```

### Stateful Sets (Elasticsearch, Kafka, etc.)

**Recommended approach:**

1. **Ordered backup with hooks:**
```yaml
pre.hook.backup.velero.io/command: '["/bin/sh", "-c", "curl -X POST localhost:9200/_flush"]'
```

2. **PVC snapshots:**
```yaml
schedules:
  statefulset-backup:
    schedule: "0 */6 * * *"
    template:
      selector: app=elasticsearch
      snapshotVolumes: true
      ttl: 336h
```

### Kubernetes System Components

**What to exclude:**

```yaml
schedules:
  system-backup:
    template:
      exclude-namespaces:
        - kube-system
        - kube-public
        - kube-node-lease
        - velero
```

## Cost Optimization Tips

### 1. Tiered Backup Strategy

- **Hot data (0-7 days):** Frequent backups, quick access
- **Warm data (7-30 days):** Daily backups, cool storage
- **Cold data (30-90 days):** Weekly backups, archive storage

### 2. Selective Backups

```yaml
# Only backup PVCs with specific label
schedules:
  critical-data:
    template:
      include-resources: persistentvolumeclaims
      selector: backup=true
```

### 3. Incremental Snapshots

Always enable for Azure Managed Disks:
```yaml
volumeSnapshotLocation:
  config:
    incremental: "true"
```

### 4. Lifecycle Policies

Implemented in storage account for automatic tier transitions.

## Testing Your Backup Strategy

### Monthly Restore Drill

```bash
# Create restore test namespace
kubectl create namespace restore-test

# Restore to test namespace
velero restore create test-restore-$(date +%Y%m%d) \
  --from-backup=your-backup-name \
  --namespace-mappings production:restore-test

# Verify
kubectl get all -n restore-test

# Cleanup
kubectl delete namespace restore-test
```

### Validate Backup Completeness

```bash
# Check backup details
velero backup describe backup-name --details

# Verify all expected resources
velero backup describe backup-name --details | grep -i "resource:"
```

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Backup Success Rate**
   - Target: >99%
   - Alert: Any failed backup

2. **Backup Duration**
   - Baseline: Track over time
   - Alert: Duration >2x baseline

3. **Storage Usage**
   - Track growth trends
   - Alert: Unexpected spikes

4. **Restore Time (RTO)**
   - Test monthly
   - Document and track

5. **Data Currency (RPO)**
   - Verify backup freshness
   - Alert: Missed scheduled backups

## Compliance Considerations

### GDPR/Data Residency

- Ensure storage account is in appropriate region
- Enable encryption at rest
- Document data retention policies

### SOC 2/ISO 27001

- Regular restore testing (monthly minimum)
- Access logging enabled
- Retention policy enforcement
- Backup verification procedures

### HIPAA

- Encryption in transit and at rest
- Access controls documented
- Audit trails maintained
- Minimum 6-year retention for some data

## Troubleshooting Common Issues

### Backup Takes Too Long

**Solutions:**
1. Use snapshots instead of file-based backup
2. Exclude unnecessary resources
3. Schedule during low-traffic periods
4. Increase Velero resources

### Snapshots Failing

**Checks:**
1. Verify CSI driver installed
2. Check Azure permissions
3. Validate VolumeSnapshotClass
4. Review Velero logs

### High Storage Costs

**Actions:**
1. Review retention policies
2. Enable lifecycle management
3. Use incremental snapshots
4. Delete old backups programmatically

## Additional Resources

- [Velero Documentation](https://velero.io/docs/)
- [AKS Backup Best Practices](https://learn.microsoft.com/en-us/azure/aks/operator-best-practices-storage)
- [Azure Backup Pricing](https://azure.microsoft.com/pricing/details/backup/)
