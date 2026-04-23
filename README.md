# Velero on AKS with ArgoCD

Production-ready Velero setup for Azure Kubernetes Service using **Workload Identity** (no storage keys), ArgoCD GitOps, CSI snapshots, and cost-optimised Azure storage.

[![CI](https://github.com/sunnynazar/velero-aks-setup/actions/workflows/ci.yml/badge.svg)](https://github.com/sunnynazar/velero-aks-setup/actions/workflows/ci.yml)

## Overview

- Workload Identity auth — no storage account keys created or stored
- GitOps deployment via ArgoCD
- CSI-based PVC snapshots using Azure Managed Disks (incremental)
- Storage lifecycle policies: Hot → Cool → Archive → Delete
- Daily + weekly backup schedules with configurable TTL
- Python scripts with 77 unit tests (no real cluster needed to run them)
- GitHub Actions CI on every push and PR

## Repository Structure

```
velero-aks-setup/
├── argocd/
│   ├── velero-application.yaml       # Deploy from upstream Helm chart
│   └── velero-application-git.yaml  # Deploy from this Git repo
├── velero/
│   ├── Chart.yaml
│   └── values.yaml                  # Helm values (placeholders filled by setup_azure.py)
├── scripts/
│   ├── setup_azure.py               # Provision Azure infra + Workload Identity
│   ├── verify_installation.py       # Health checks incl. Workload Identity
│   └── test_backup_restore.py       # E2E backup/restore tests
├── tests/                           # Unit tests (77 tests, all mocked)
├── config/
│   └── config.example.env           # Template — copy to config.env, never commit
├── docs/
│   ├── INSTALLATION.md
│   ├── BACKUP_STRATEGIES.md
│   └── TROUBLESHOOTING.md
├── requirements.txt                 # Runtime Python dependencies
├── requirements-dev.txt             # Dev dependencies (pytest, ruff)
├── pyproject.toml                   # Ruff + pytest config
└── Makefile                         # make install / test / lint / setup / verify / e2e
```

## Prerequisites

- Python 3.11+
- `az` CLI authenticated to the correct subscription
- `kubectl` configured against the target AKS cluster
- `helm` 3.x
- ArgoCD installed in the cluster
- Azure RBAC: ability to create identities, assign roles, and manage storage

## Quick Start

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Configure
cp config/config.example.env config/config.env
# Fill in: AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_LOCATION, AKS_CLUSTER_NAME

# 3. Provision Azure resources + Workload Identity (idempotent, safe to re-run)
python scripts/setup_azure.py

# 4. Deploy via ArgoCD
kubectl apply -f argocd/velero-application.yaml

# 5. Verify
python scripts/verify_installation.py
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   AKS Cluster                        │
│                                                      │
│  ┌──────────────┐         ┌──────────────┐         │
│  │   ArgoCD     │────────▶│    Velero    │         │
│  │              │         │  (velero SA) │         │
│  └──────────────┘         └──────┬───────┘         │
│                                   │  Workload        │
│                          ┌────────▼────────┐  Identity Token
│                          │  CSI Snapshots  │        │
│                          └────────┬────────┘        │
└───────────────────────────────────┼──────────────────┘
                                    │
              ┌─────────────────────▼──────────────────────┐
              │          Azure AD Workload Identity         │
              │  User-Assigned MI → Federated Credential    │
              │  Roles: Storage Blob Data Contributor       │
              │         Disk Snapshot Contributor + Reader  │
              └─────────────────────┬──────────────────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │     Azure Storage Account      │
                    │  (Standard_LRS, HTTPS-only)    │
                    │  ┌──────────────────────────┐  │
                    │  │  Velero Blob Container   │  │
                    │  │  Lifecycle: 30→90→180d   │  │
                    │  └──────────────────────────┘  │
                    │  ┌──────────────────────────┐  │
                    │  │  Managed Disk Snapshots  │  │
                    │  │  Incremental only        │  │
                    │  └──────────────────────────┘  │
                    └─────────────────────────────────┘
```

## Authentication: Workload Identity

`setup_azure.py` provisions this end-to-end with no manual steps:

1. Creates a **User-Assigned Managed Identity** (`velero-identity`)
2. Assigns minimum required roles:
   - `Storage Blob Data Contributor` on the storage account
   - `Disk Snapshot Contributor` + `Reader` on the resource group
3. Enables **OIDC issuer** and **Workload Identity** on the AKS cluster
4. Creates a **federated credential** linking the identity to `velero/velero` SA
5. Annotates the Kubernetes ServiceAccount with the client ID

The Azure Workload Identity webhook injects a short-lived AAD token into the Velero pod at runtime. No storage keys are ever created or stored.

## Developer Workflow

```bash
make install       # pip install -r requirements-dev.txt
make test          # pytest --cov (77 tests, no real cluster needed)
make lint          # ruff check scripts/ tests/
make setup         # python scripts/setup_azure.py
make verify        # python scripts/verify_installation.py
make e2e           # python scripts/test_backup_restore.py
make e2e-skip-pvc  # python scripts/test_backup_restore.py --skip-pvc
```

## E2E Test Coverage

| Test | What it verifies |
|------|-----------------|
| Pre-flight | Velero pod running, WI annotation, webhook present, BSL Available |
| Namespace backup & restore | Deployment, ConfigMap, Secret backed up and restored; data integrity checked |
| Cross-namespace restore | Restore into a different namespace via `--namespace-mappings` |
| PVC backup & restore | CSI snapshot of a 1Gi PVC; data written pre-backup verified post-restore |

```bash
python scripts/test_backup_restore.py              # Full suite
python scripts/test_backup_restore.py --skip-pvc  # Skip CSI snapshot test
python scripts/test_backup_restore.py --keep-resources  # Preserve test resources
```

## Backup and Restore

```bash
# Manual backup
velero backup create my-backup --include-namespaces=production

# List backups
velero backup get

# Restore
velero restore create --from-backup my-backup

# Cross-namespace restore
velero restore create --from-backup my-backup \
  --namespace-mappings production:production-dr
```

Scheduled backups run automatically:
- **Daily** at 2 AM UTC — 30-day retention
- **Weekly** Sunday at 3 AM UTC — 90-day retention

## Cost Optimisation

| Measure | Saving |
|---------|--------|
| `Standard_LRS` storage | Cheapest redundancy tier |
| Hot → Cool after 30 days | ~60% cheaper |
| Cool → Archive after 90 days | ~90% cheaper |
| Delete after 180 days | No unbounded growth |
| Incremental disk snapshots | 80–90% less storage for subsequent snapshots |
| Node agent disabled | No DaemonSet cost |

Estimated: **~$7–12/month** for a 100 GB cluster.

## Monitoring

Enable Prometheus metrics in `values.yaml`:

```yaml
metrics:
  enabled: true
  serviceMonitor:
    enabled: true   # requires Prometheus Operator
```

Key metrics:
- `velero_backup_success_total`
- `velero_backup_failure_total`
- `velero_backup_duration_seconds`
- `velero_volume_snapshot_success_total`

Example alert:

```yaml
- alert: VeleroBackupFailed
  expr: velero_backup_failure_total{schedule!=""} / velero_backup_attempt_total{schedule!=""} > 0.25
  for: 15m
  labels:
    severity: warning
```

## Troubleshooting

### BSL not Available

```bash
# Check Velero logs for auth errors
kubectl logs -n velero deployment/velero

# Confirm Workload Identity annotation
kubectl get sa velero -n velero -o jsonpath='{.metadata.annotations}'

# Confirm webhook is installed
kubectl get mutatingwebhookconfiguration azure-wi-webhook-mutating-webhook-configuration
```

### PVC Snapshots Not Working

```bash
# Confirm CSI snapshot controller is installed
kubectl get volumesnapshotclass

# Label a VolumeSnapshotClass for Velero
kubectl label volumesnapshotclass <name> velero.io/csi-volumesnapshot-class=true
```

### Backup Stuck

```bash
kubectl logs -n velero deployment/velero
velero backup describe <name> --details -n velero
velero backup delete <name> --confirm -n velero
```

### Debug Logging

```bash
kubectl set env deployment/velero -n velero VELERO_LOG_LEVEL=debug
kubectl get events -n velero --sort-by='.lastTimestamp'
```

## Security

- No storage keys created or stored — Workload Identity only
- Velero pods: non-root (`runAsUser: 65534`), all capabilities dropped, read-only root FS
- Storage account: HTTPS-only, TLS 1.2 minimum, public blob access disabled
- RBAC scoped to minimum required roles
- `config/config.env` and `config/credentials-velero` are git-ignored

## Additional Resources

- [Velero Documentation](https://velero.io/docs/)
- [Azure Workload Identity](https://azure.github.io/azure-workload-identity/docs/)
- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [AKS Best Practices](https://learn.microsoft.com/en-us/azure/aks/best-practices)

## Contributing

Contributions are welcome. Please open an issue or pull request.

## License

MIT — see [LICENSE](LICENSE).
