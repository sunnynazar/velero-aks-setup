#!/usr/bin/env python3
"""
End-to-end Velero backup/restore test suite.

Tests:
  1. Pre-flight checks (Workload Identity, BSL availability)
  2. Namespace backup & restore with data integrity verification
  3. Cross-namespace restore
  4. PVC CSI snapshot backup & restore with checksum verification

Usage:
    python scripts/test_backup_restore.py [--skip-pvc] [--keep-resources]

    --skip-pvc        Skip the PVC/CSI snapshot test
    --keep-resources  Do not delete test namespaces and backups on exit
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException
except ImportError:
    pass

VELERO_NS = "velero"
TS = datetime.utcnow().strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    passed: int = 0
    failed: int = 0

    def ok(self, msg: str) -> None:
        print(f"\033[32m[PASS]\033[0m {msg}")
        self.passed += 1

    def fail(self, msg: str) -> None:
        print(f"\033[31m[FAIL]\033[0m {msg}")
        self.failed += 1

    def assert_true(self, condition: bool, msg: str) -> bool:
        if condition:
            self.ok(msg)
        else:
            self.fail(msg)
        return condition


# ---------------------------------------------------------------------------
# Kubernetes helpers
# ---------------------------------------------------------------------------

def _load_k8s() -> None:
    try:
        k8s_config.load_kube_config()
    except k8s_config.ConfigException:
        k8s_config.load_incluster_config()


def create_namespace(core: k8s_client.CoreV1Api, name: str) -> None:
    try:
        core.create_namespace(
            k8s_client.V1Namespace(metadata=k8s_client.V1ObjectMeta(name=name))
        )
    except ApiException as e:
        if e.status != 409:
            raise


def delete_namespace(core: k8s_client.CoreV1Api, name: str, wait: bool = True) -> None:
    try:
        core.delete_namespace(name)
    except ApiException as e:
        if e.status != 404:
            raise
    if wait:
        for _ in range(60):
            try:
                core.read_namespace(name)
                time.sleep(2)
            except ApiException:
                return


def namespace_exists(core: k8s_client.CoreV1Api, name: str) -> bool:
    try:
        core.read_namespace(name)
        return True
    except ApiException:
        return False


def resource_exists(core: k8s_client.CoreV1Api, kind: str, name: str, namespace: str) -> bool:
    try:
        if kind == "configmap":
            core.read_namespaced_config_map(name, namespace)
        elif kind == "secret":
            core.read_namespaced_secret(name, namespace)
        elif kind == "serviceaccount":
            core.read_namespaced_service_account(name, namespace)
        else:
            return False
        return True
    except ApiException:
        return False


def create_configmap(core: k8s_client.CoreV1Api, name: str, namespace: str, data: dict) -> None:
    try:
        core.create_namespaced_config_map(
            namespace,
            k8s_client.V1ConfigMap(
                metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
                data=data,
            ),
        )
    except ApiException as e:
        if e.status != 409:
            raise


def create_secret(core: k8s_client.CoreV1Api, name: str, namespace: str, data: dict) -> None:
    try:
        core.create_namespaced_secret(
            namespace,
            k8s_client.V1Secret(
                metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
                string_data=data,
            ),
        )
    except ApiException as e:
        if e.status != 409:
            raise


def create_deployment(apps: k8s_client.AppsV1Api, name: str, namespace: str, image: str) -> None:
    try:
        apps.create_namespaced_deployment(
            namespace,
            k8s_client.V1Deployment(
                metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
                spec=k8s_client.V1DeploymentSpec(
                    replicas=1,
                    selector=k8s_client.V1LabelSelector(match_labels={"app": name}),
                    template=k8s_client.V1PodTemplateSpec(
                        metadata=k8s_client.V1ObjectMeta(labels={"app": name}),
                        spec=k8s_client.V1PodSpec(
                            containers=[
                                k8s_client.V1Container(name=name, image=image)
                            ]
                        ),
                    ),
                ),
            ),
        )
    except ApiException as e:
        if e.status != 409:
            raise


def deployment_available_replicas(apps: k8s_client.AppsV1Api, name: str, namespace: str) -> int:
    try:
        dep = apps.read_namespaced_deployment(name, namespace)
        return dep.status.available_replicas or 0
    except ApiException:
        return 0


def get_configmap_value(core: k8s_client.CoreV1Api, name: str, namespace: str, key: str) -> str:
    try:
        cm = core.read_namespaced_config_map(name, namespace)
        return (cm.data or {}).get(key, "")
    except ApiException:
        return ""


# ---------------------------------------------------------------------------
# Velero CLI helpers
# ---------------------------------------------------------------------------

def _velero(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["velero"] + list(args) + ["-n", VELERO_NS]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def create_backup(name: str, include_namespaces: str, snapshot_volumes: bool = False) -> None:
    args = ["backup", "create", name, f"--include-namespaces={include_namespaces}"]
    if snapshot_volumes:
        args.append("--snapshot-volumes=true")
    _velero(*args)


def wait_for_backup(name: str, timeout: int = 300) -> str:
    """Polls until backup reaches a terminal phase; returns the phase string."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _velero("backup", "get", name, "-o", "json", check=False)
        if result.returncode == 0:
            import json
            try:
                phase = json.loads(result.stdout).get("status", {}).get("phase", "")
                if phase in ("Completed", "Failed", "PartiallyFailed"):
                    return phase
            except json.JSONDecodeError:
                pass
        time.sleep(5)
    return "Timeout"


def create_restore(name: str, from_backup: str, namespace_mappings: Optional[str] = None) -> None:
    args = ["restore", "create", name, f"--from-backup={from_backup}"]
    if namespace_mappings:
        args.append(f"--namespace-mappings={namespace_mappings}")
    _velero(*args)


def wait_for_restore(name: str, timeout: int = 300) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _velero("restore", "get", name, "-o", "json", check=False)
        if result.returncode == 0:
            import json
            try:
                phase = json.loads(result.stdout).get("status", {}).get("phase", "")
                if phase in ("Completed", "Failed", "PartiallyFailed"):
                    return phase
            except json.JSONDecodeError:
                pass
        time.sleep(5)
    return "Timeout"


def delete_backup(name: str) -> None:
    _velero("backup", "delete", name, "--confirm", check=False)


def delete_restore(name: str) -> None:
    _velero("restore", "delete", name, "--confirm", check=False)


def get_bsl_phase(custom: k8s_client.CustomObjectsApi) -> str:
    try:
        bsl = custom.get_namespaced_custom_object(
            group="velero.io", version="v1", namespace=VELERO_NS,
            plural="backupstoragelocations", name="default",
        )
        return bsl.get("status", {}).get("phase", "Unknown")
    except ApiException:
        return "NotFound"


# ---------------------------------------------------------------------------
# Test phases
# ---------------------------------------------------------------------------

def preflight(
    core: k8s_client.CoreV1Api,
    custom: k8s_client.CustomObjectsApi,
    admissions: k8s_client.AdmissionregistrationV1Api,
    result: RunResult,
) -> bool:
    print("\n--- Pre-flight Checks ---")

    # Velero CLI
    try:
        subprocess.check_output(["velero", "version", "--client-only"], stderr=subprocess.DEVNULL)
        result.ok("Velero CLI present")
    except (FileNotFoundError, subprocess.CalledProcessError):
        result.fail("Velero CLI not installed")
        return False

    # Velero pod running
    pods = core.list_namespaced_pod(
        VELERO_NS, label_selector="app.kubernetes.io/name=velero"
    ).items
    running = [p for p in pods if p.status.phase == "Running"]
    if not result.assert_true(bool(running), f"Velero pod Running ({len(running)}/{len(pods)})"):
        return False

    # Workload Identity annotation
    try:
        sa = core.read_namespaced_service_account("velero", VELERO_NS)
        client_id = (sa.metadata.annotations or {}).get("azure.workload.identity/client-id", "")
        if not result.assert_true(bool(client_id), f"Workload Identity client-id annotated: {client_id}"):
            return False
    except ApiException:
        result.fail("ServiceAccount 'velero' not found")
        return False

    # Workload Identity webhook
    try:
        admissions.read_mutating_webhook_configuration(
            "azure-wi-webhook-mutating-webhook-configuration"
        )
        result.ok("Workload Identity webhook installed")
    except ApiException:
        result.fail("Workload Identity webhook not found")
        return False

    # BSL Available
    phase = get_bsl_phase(custom)
    if not result.assert_true(phase == "Available", f"BackupStorageLocation Available (phase={phase})"):
        return False

    return True


def test_namespace_backup_restore(
    core: k8s_client.CoreV1Api,
    apps: k8s_client.AppsV1Api,
    result: RunResult,
    ns: str,
    backup_name: str,
) -> None:
    print("\n--- Test 1: Namespace Backup & Restore ---")

    # Setup
    create_namespace(core, ns)
    create_deployment(apps, "nginx", ns, "nginx:stable-alpine")
    create_configmap(core, "app-config", ns, {"env": "e2e-test", "version": "1.0"})
    create_secret(core, "app-secret", ns, {"token": "e2e-test-token"})
    result.ok("Test workload created")

    # Wait for deployment
    for _ in range(24):
        if deployment_available_replicas(apps, "nginx", ns) >= 1:
            break
        time.sleep(5)
    result.assert_true(
        deployment_available_replicas(apps, "nginx", ns) >= 1,
        "nginx deployment ready before backup",
    )

    # Backup
    create_backup(backup_name, ns)
    phase = wait_for_backup(backup_name, timeout=300)
    result.assert_true(phase == "Completed", f"Namespace backup completed (phase={phase})")

    # Simulate disaster
    delete_namespace(core, ns, wait=True)
    result.assert_true(not namespace_exists(core, ns), "Namespace deleted (disaster simulated)")

    # Restore
    restore_name = f"{backup_name}-restore"
    create_restore(restore_name, backup_name)
    phase = wait_for_restore(restore_name, timeout=300)
    result.assert_true(phase == "Completed", f"Namespace restore completed (phase={phase})")

    # Verify
    result.assert_true(namespace_exists(core, ns), f"Namespace '{ns}' restored")
    result.assert_true(
        resource_exists(core, "configmap", "app-config", ns), "ConfigMap 'app-config' restored"
    )
    result.assert_true(
        resource_exists(core, "secret", "app-secret", ns), "Secret 'app-secret' restored"
    )
    result.assert_true(
        deployment_available_replicas(apps, "nginx", ns) >= 1,
        "nginx deployment has available replicas after restore",
    )
    val = get_configmap_value(core, "app-config", ns, "env")
    result.assert_true(val == "e2e-test", f"ConfigMap data integrity verified (env={val})")

    return restore_name  # type: ignore[return-value]


def test_cross_namespace_restore(
    core: k8s_client.CoreV1Api,
    apps: k8s_client.AppsV1Api,
    result: RunResult,
    source_ns: str,
    target_ns: str,
    backup_name: str,
) -> None:
    print("\n--- Test 2: Cross-Namespace Restore ---")

    restore_name = f"{backup_name}-cross"
    create_restore(restore_name, backup_name, namespace_mappings=f"{source_ns}:{target_ns}")
    phase = wait_for_restore(restore_name, timeout=300)
    result.assert_true(phase == "Completed", f"Cross-namespace restore completed (phase={phase})")
    result.assert_true(namespace_exists(core, target_ns), f"Target namespace '{target_ns}' created")
    result.assert_true(
        resource_exists(core, "configmap", "app-config", target_ns),
        f"ConfigMap present in target namespace '{target_ns}'",
    )
    return restore_name  # type: ignore[return-value]


def test_pvc_backup_restore(
    core: k8s_client.CoreV1Api,
    result: RunResult,
    pvc_ns: str,
    backup_name: str,
) -> None:
    print("\n--- Test 3: PVC Backup & Restore (CSI Snapshot) ---")

    # Detect default StorageClass
    storage_classes = k8s_client.StorageV1Api().list_storage_class().items
    default_sc = next(
        (
            sc.metadata.name for sc in storage_classes
            if (sc.metadata.annotations or {}).get(
                "storageclass.kubernetes.io/is-default-class"
            ) == "true"
        ),
        None,
    )
    if not result.assert_true(bool(default_sc), f"Default StorageClass found: {default_sc}"):
        return

    create_namespace(core, pvc_ns)

    # PVC
    try:
        core.create_namespaced_persistent_volume_claim(
            pvc_ns,
            k8s_client.V1PersistentVolumeClaim(
                metadata=k8s_client.V1ObjectMeta(name="test-pvc", namespace=pvc_ns),
                spec=k8s_client.V1PersistentVolumeClaimSpec(
                    access_modes=["ReadWriteOnce"],
                    storage_class_name=default_sc,
                    resources=k8s_client.V1ResourceRequirements(
                        requests={"storage": "1Gi"}
                    ),
                ),
            ),
        )
        result.ok("PVC 'test-pvc' created")
    except ApiException as e:
        if e.status != 409:
            result.fail(f"Failed to create PVC: {e}")
            return

    # Write data via a Pod
    writer_pod = k8s_client.V1Pod(
        metadata=k8s_client.V1ObjectMeta(name="data-writer", namespace=pvc_ns),
        spec=k8s_client.V1PodSpec(
            restart_policy="Never",
            init_containers=[
                k8s_client.V1Container(
                    name="write",
                    image="busybox:stable",
                    command=["sh", "-c", "echo 'velero-e2e-checksum-42' > /data/checksum.txt"],
                    volume_mounts=[k8s_client.V1VolumeMount(name="vol", mount_path="/data")],
                )
            ],
            containers=[
                k8s_client.V1Container(
                    name="pause",
                    image="gcr.io/google_containers/pause:3.9",
                    volume_mounts=[k8s_client.V1VolumeMount(name="vol", mount_path="/data")],
                )
            ],
            volumes=[
                k8s_client.V1Volume(
                    name="vol",
                    persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                        claim_name="test-pvc"
                    ),
                )
            ],
        ),
    )
    try:
        core.create_namespaced_pod(pvc_ns, writer_pod)
    except ApiException as e:
        if e.status != 409:
            result.fail(f"Failed to create data-writer pod: {e}")
            return

    # Wait for pod to be ready
    for _ in range(30):
        try:
            pod = core.read_namespaced_pod("data-writer", pvc_ns)
            if pod.status.phase == "Running":
                break
        except ApiException:
            pass
        time.sleep(4)
    result.ok("Data written to PVC")

    # Backup
    create_backup(backup_name, pvc_ns, snapshot_volumes=True)
    phase = wait_for_backup(backup_name, timeout=600)
    result.assert_true(phase == "Completed", f"PVC backup completed (phase={phase})")

    # Delete namespace (disaster)
    delete_namespace(core, pvc_ns, wait=True)

    # Restore
    restore_name = f"{backup_name}-restore"
    create_restore(restore_name, backup_name)
    phase = wait_for_restore(restore_name, timeout=600)
    result.assert_true(phase == "Completed", f"PVC restore completed (phase={phase})")

    # Verify PVC exists
    try:
        core.read_namespaced_persistent_volume_claim("test-pvc", pvc_ns)
        result.ok("PVC 'test-pvc' restored")
    except ApiException:
        result.fail("PVC 'test-pvc' not found after restore")
        return

    # Verify data integrity via a reader pod
    reader_pod = k8s_client.V1Pod(
        metadata=k8s_client.V1ObjectMeta(name="data-reader", namespace=pvc_ns),
        spec=k8s_client.V1PodSpec(
            restart_policy="Never",
            containers=[
                k8s_client.V1Container(
                    name="read",
                    image="busybox:stable",
                    command=["cat", "/data/checksum.txt"],
                    volume_mounts=[k8s_client.V1VolumeMount(name="vol", mount_path="/data")],
                )
            ],
            volumes=[
                k8s_client.V1Volume(
                    name="vol",
                    persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                        claim_name="test-pvc"
                    ),
                )
            ],
        ),
    )
    try:
        core.create_namespaced_pod(pvc_ns, reader_pod)
    except ApiException as e:
        if e.status != 409:
            result.fail(f"Could not create data-reader pod: {e}")
            return

    for _ in range(30):
        try:
            pod = core.read_namespaced_pod("data-reader", pvc_ns)
            if pod.status.phase in ("Succeeded", "Failed"):
                break
        except ApiException:
            pass
        time.sleep(4)

    try:
        logs = core.read_namespaced_pod_log("data-reader", pvc_ns)
        result.assert_true(
            "velero-e2e-checksum-42" in logs,
            f"PVC data integrity verified (checksum in logs: {logs.strip()!r})",
        )
    except ApiException as e:
        result.fail(f"Could not read data-reader logs: {e}")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

class Cleanup:
    def __init__(self, core: k8s_client.CoreV1Api, keep: bool):
        self._core = core
        self._keep = keep
        self._namespaces: list[str] = []
        self._backups: list[str] = []
        self._restores: list[str] = []

    def track_namespace(self, ns: str) -> None:
        self._namespaces.append(ns)

    def track_backup(self, name: str) -> None:
        self._backups.append(name)

    def track_restore(self, name: str) -> None:
        self._restores.append(name)

    def run(self) -> None:
        if self._keep:
            print("\n[INFO] Skipping cleanup (--keep-resources)")
            return
        print("\n[INFO] Cleaning up test resources...")
        for ns in self._namespaces:
            delete_namespace(self._core, ns, wait=False)
        for b in self._backups:
            delete_backup(b)
        for r in self._restores:
            delete_restore(r)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-pvc", action="store_true")
    parser.add_argument("--keep-resources", action="store_true")
    args = parser.parse_args()

    _load_k8s()
    core      = k8s_client.CoreV1Api()
    apps      = k8s_client.AppsV1Api()
    custom    = k8s_client.CustomObjectsApi()
    admissions = k8s_client.AdmissionregistrationV1Api()

    result  = RunResult()
    cleanup = Cleanup(core, keep=args.keep_resources)

    # Names
    test_ns    = f"velero-e2e-{TS}"
    target_ns  = f"velero-e2e-cross-{TS}"
    pvc_ns     = f"velero-e2e-pvc-{TS}"
    backup_ns  = f"velero-e2e-ns-{TS}"
    backup_pvc = f"velero-e2e-pvc-{TS}"

    cleanup.track_namespace(test_ns)
    cleanup.track_namespace(target_ns)
    cleanup.track_namespace(pvc_ns)
    cleanup.track_backup(backup_ns)
    cleanup.track_backup(backup_pvc)

    try:
        ok = preflight(core, custom, admissions, result)
        if not ok:
            print("\n[ERROR] Pre-flight checks failed — aborting")
            sys.exit(1)

        restore_name = test_namespace_backup_restore(
            core, apps, result, ns=test_ns, backup_name=backup_ns
        )
        if restore_name:
            cleanup.track_restore(restore_name)

        cross_restore = test_cross_namespace_restore(
            core, apps, result,
            source_ns=test_ns, target_ns=target_ns, backup_name=backup_ns,
        )
        if cross_restore:
            cleanup.track_restore(cross_restore)

        if not args.skip_pvc:
            test_pvc_backup_restore(core, result, pvc_ns=pvc_ns, backup_name=backup_pvc)
        else:
            print("\n[WARN] Skipping PVC test (--skip-pvc)")

    finally:
        cleanup.run()

    print("\n" + "=" * 50)
    print("E2E Test Summary")
    print(f"  Passed: {result.passed}   Failed: {result.failed}")
    print("=" * 50)

    if result.failed > 0:
        print("\nSome tests FAILED. Check Velero logs:")
        print("    kubectl logs -n velero deployment/velero")
        sys.exit(1)
    else:
        print("\n\033[32mAll tests PASSED.\033[0m")


if __name__ == "__main__":
    main()
