#!/usr/bin/env python3
"""
Verifies that Velero is correctly deployed with Workload Identity on AKS.

Usage:
    python scripts/verify_installation.py
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

try:
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException
except ImportError:
    pass

VELERO_NAMESPACE = "velero"
ARGOCD_NAMESPACE = "argocd"
WI_WEBHOOK_NAME  = "azure-wi-webhook-mutating-webhook-configuration"


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    passed: int = 0
    warned: int = 0
    failed: int = 0
    _lines: list[str] = field(default_factory=list, repr=False)

    def ok(self, msg: str) -> None:
        print(f"\033[32m[PASS]\033[0m {msg}")
        self.passed += 1

    def warn(self, msg: str) -> None:
        print(f"\033[33m[WARN]\033[0m {msg}")
        self.warned += 1

    def fail(self, msg: str) -> None:
        print(f"\033[31m[FAIL]\033[0m {msg}")
        self.failed += 1


# ---------------------------------------------------------------------------
# Individual checks (each returns early, uses result for recording)
# ---------------------------------------------------------------------------

def check_namespace(core: k8s_client.CoreV1Api, result: CheckResult) -> bool:
    try:
        core.read_namespace(VELERO_NAMESPACE)
        result.ok(f"Namespace '{VELERO_NAMESPACE}' exists")
        return True
    except ApiException:
        result.fail(f"Namespace '{VELERO_NAMESPACE}' not found")
        return False


def check_service_account(core: k8s_client.CoreV1Api, result: CheckResult) -> Optional[str]:
    """Returns the Workload Identity client-id annotation value, or None on failure."""
    try:
        sa = core.read_namespaced_service_account("velero", VELERO_NAMESPACE)
    except ApiException:
        result.fail("ServiceAccount 'velero' not found in namespace velero")
        return None

    result.ok("ServiceAccount 'velero' exists")
    annotations = sa.metadata.annotations or {}
    client_id = annotations.get("azure.workload.identity/client-id", "")
    if client_id:
        result.ok(f"ServiceAccount annotated with Workload Identity client-id: {client_id}")
    else:
        result.fail(
            "ServiceAccount missing annotation 'azure.workload.identity/client-id' "
            "— run setup_azure.py"
        )
    return client_id or None


def check_velero_pods(core: k8s_client.CoreV1Api, result: CheckResult) -> tuple[int, int]:
    """Returns (total, running) pod counts."""
    pods = core.list_namespaced_pod(
        VELERO_NAMESPACE,
        label_selector="app.kubernetes.io/name=velero",
    ).items
    total = len(pods)
    if total == 0:
        result.fail("No Velero pods found")
        return 0, 0

    result.ok(f"Found {total} Velero pod(s)")
    running = sum(1 for p in pods if p.status.phase == "Running")
    if running == total:
        result.ok(f"All {running} pod(s) Running")
    else:
        result.fail(f"{running}/{total} pods Running — check: kubectl logs -n velero deployment/velero")

    # Workload Identity label on pods
    wi_pods = [
        p for p in pods
        if (p.metadata.labels or {}).get("azure.workload.identity/use") == "true"
    ]
    if wi_pods:
        result.ok("Pods carry label 'azure.workload.identity/use=true'")
    else:
        result.warn("Pods missing label 'azure.workload.identity/use=true' — check podLabels in values.yaml")

    return total, running


def check_legacy_secret(core: k8s_client.CoreV1Api, result: CheckResult) -> None:
    try:
        core.read_namespaced_secret("velero-credentials", VELERO_NAMESPACE)
        result.warn("Secret 'velero-credentials' still exists — expected to be absent with Workload Identity")
    except ApiException:
        result.ok("No legacy storage-key secret present")


def check_bsl(custom: k8s_client.CustomObjectsApi, result: CheckResult) -> str:
    """Returns the phase of the default BSL."""
    try:
        bsl = custom.get_namespaced_custom_object(
            group="velero.io", version="v1", namespace=VELERO_NAMESPACE,
            plural="backupstoragelocations", name="default",
        )
        phase = bsl.get("status", {}).get("phase", "Unknown")
        if phase == "Available":
            result.ok("BackupStorageLocation 'default' is Available")
        else:
            result.fail(
                f"BackupStorageLocation 'default' is '{phase}' "
                "— check pod logs for auth/connectivity issues"
            )
        return phase
    except ApiException:
        result.fail("BackupStorageLocation 'default' not found")
        return "NotFound"


def check_vsl(custom: k8s_client.CustomObjectsApi, result: CheckResult) -> int:
    try:
        vsls = custom.list_namespaced_custom_object(
            group="velero.io", version="v1", namespace=VELERO_NAMESPACE,
            plural="volumesnapshotlocations",
        )
        count = len(vsls.get("items", []))
        if count > 0:
            result.ok(f"Found {count} VolumeSnapshotLocation(s)")
        else:
            result.warn("No VolumeSnapshotLocations found — PVC snapshots will not work")
        return count
    except ApiException:
        result.warn("Could not list VolumeSnapshotLocations")
        return 0


def check_volume_snapshot_classes(custom: k8s_client.CustomObjectsApi, result: CheckResult) -> int:
    try:
        vscs = custom.list_cluster_custom_object(
            group="snapshot.storage.k8s.io", version="v1",
            plural="volumesnapshotclasses",
        )
        items = vscs.get("items", [])
        count = len(items)
        if count == 0:
            result.warn("No VolumeSnapshotClasses found — install the AKS CSI snapshot controller")
            return 0

        result.ok(f"Found {count} VolumeSnapshotClass(es)")
        labelled = [
            i for i in items
            if (i.get("metadata", {}).get("labels") or {}).get(
                "velero.io/csi-volumesnapshot-class"
            ) == "true"
        ]
        if labelled:
            result.ok("VolumeSnapshotClass labelled for Velero CSI found")
        else:
            result.warn(
                "No VolumeSnapshotClass has label 'velero.io/csi-volumesnapshot-class=true' "
                "— label one for CSI snapshots to work"
            )
        return count
    except ApiException:
        result.warn("Could not list VolumeSnapshotClasses")
        return 0


def check_schedules(custom: k8s_client.CustomObjectsApi, result: CheckResult) -> int:
    try:
        schedules = custom.list_namespaced_custom_object(
            group="velero.io", version="v1", namespace=VELERO_NAMESPACE,
            plural="schedules",
        )
        count = len(schedules.get("items", []))
        if count > 0:
            result.ok(f"Found {count} Schedule(s)")
        else:
            result.warn("No Schedules found — check values.yaml schedules block")
        return count
    except ApiException:
        result.warn("Could not list Schedules")
        return 0


def check_velero_cli(result: CheckResult) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["velero", "version", "--client-only"], stderr=subprocess.DEVNULL, text=True
        )
        version = next(
            (line.split(":")[-1].strip() for line in out.splitlines() if "Version:" in line),
            "unknown",
        )
        result.ok(f"Velero CLI installed ({version})")
        return version
    except (FileNotFoundError, subprocess.CalledProcessError):
        result.warn(
            "Velero CLI not installed — "
            "install from https://velero.io/docs/main/basic-install/#install-the-cli"
        )
        return None


def check_argocd_app(custom: k8s_client.CustomObjectsApi, result: CheckResult) -> tuple[str, str]:
    """Returns (sync_status, health_status)."""
    try:
        app = custom.get_namespaced_custom_object(
            group="argoproj.io", version="v1alpha1",
            namespace=ARGOCD_NAMESPACE, plural="applications", name="velero",
        )
        sync   = app.get("status", {}).get("sync", {}).get("status", "Unknown")
        health = app.get("status", {}).get("health", {}).get("status", "Unknown")
        sync   == "Synced"   and result.ok(f"ArgoCD sync: {sync}")   or result.warn(f"ArgoCD sync: {sync}")
        health == "Healthy"  and result.ok(f"ArgoCD health: {health}") or result.warn(f"ArgoCD health: {health}")
        return sync, health
    except ApiException:
        result.warn("ArgoCD Application 'velero' not found (skip if not using ArgoCD)")
        return "Unknown", "Unknown"


def check_wi_webhook(admissions: k8s_client.AdmissionregistrationV1Api, result: CheckResult) -> bool:
    try:
        admissions.read_mutating_webhook_configuration(WI_WEBHOOK_NAME)
        result.ok("Azure Workload Identity webhook is installed")
        return True
    except ApiException:
        result.fail(
            "Azure Workload Identity webhook not found — "
            "install azure-workload-identity or enable the AKS addon"
        )
        return False


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all_checks() -> CheckResult:
    try:
        k8s_config.load_kube_config()
    except k8s_config.ConfigException:
        k8s_config.load_incluster_config()

    core      = k8s_client.CoreV1Api()
    custom    = k8s_client.CustomObjectsApi()
    admissions = k8s_client.AdmissionregistrationV1Api()

    result = CheckResult()

    print("\n--- Namespace & Service Account ---")
    ns_ok = check_namespace(core, result)
    if ns_ok:
        check_service_account(core, result)

    print("\n--- Velero Pods ---")
    check_velero_pods(core, result)
    check_legacy_secret(core, result)

    print("\n--- Backup Storage Location ---")
    check_bsl(custom, result)

    print("\n--- Volume Snapshot Location ---")
    check_vsl(custom, result)

    print("\n--- CSI VolumeSnapshotClass ---")
    check_volume_snapshot_classes(custom, result)

    print("\n--- Schedules ---")
    check_schedules(custom, result)

    print("\n--- Velero CLI ---")
    check_velero_cli(result)

    print("\n--- ArgoCD Application ---")
    check_argocd_app(custom, result)

    print("\n--- Workload Identity Webhook ---")
    check_wi_webhook(admissions, result)

    return result


def main() -> None:
    result = run_all_checks()
    print("\n" + "=" * 50)
    print("Verification Summary")
    print(f"  PASS: {result.passed}   WARN: {result.warned}   FAIL: {result.failed}")
    print("=" * 50)
    if result.failed > 0:
        print("\nOne or more checks failed. Check Velero logs:")
        print("    kubectl logs -n velero deployment/velero")
        sys.exit(1)


if __name__ == "__main__":
    main()
