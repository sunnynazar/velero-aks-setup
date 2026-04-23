"""Unit tests for scripts/verify_installation.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from verify_installation import (
    CheckResult,
    check_argocd_app,
    check_bsl,
    check_legacy_secret,
    check_namespace,
    check_schedules,
    check_service_account,
    check_velero_cli,
    check_velero_pods,
    check_volume_snapshot_classes,
    check_vsl,
    check_wi_webhook,
)


@pytest.fixture()
def result() -> CheckResult:
    return CheckResult()


@pytest.fixture()
def core():
    return MagicMock()


@pytest.fixture()
def custom():
    return MagicMock()


@pytest.fixture()
def admissions():
    return MagicMock()


# ---------------------------------------------------------------------------
# check_namespace
# ---------------------------------------------------------------------------

class TestCheckNamespace:
    def test_passes_when_namespace_exists(self, core, result):
        core.read_namespace.return_value = MagicMock()
        ok = check_namespace(core, result)
        assert ok is True
        assert result.passed == 1
        assert result.failed == 0

    def test_fails_when_namespace_missing(self, core, result):
        core.read_namespace.side_effect = ApiException(status=404)
        ok = check_namespace(core, result)
        assert ok is False
        assert result.failed == 1


# ---------------------------------------------------------------------------
# check_service_account
# ---------------------------------------------------------------------------

class TestCheckServiceAccount:
    def test_passes_with_workload_identity_annotation(self, core, result):
        sa = MagicMock()
        sa.metadata.annotations = {"azure.workload.identity/client-id": "ci-abc"}
        core.read_namespaced_service_account.return_value = sa

        client_id = check_service_account(core, result)

        assert client_id == "ci-abc"
        assert result.passed == 2  # SA exists + annotation present
        assert result.failed == 0

    def test_fails_when_annotation_missing(self, core, result):
        sa = MagicMock()
        sa.metadata.annotations = {}
        core.read_namespaced_service_account.return_value = sa

        client_id = check_service_account(core, result)

        assert client_id is None
        assert result.failed == 1

    def test_fails_when_sa_not_found(self, core, result):
        core.read_namespaced_service_account.side_effect = ApiException(status=404)
        client_id = check_service_account(core, result)
        assert client_id is None
        assert result.failed == 1


# ---------------------------------------------------------------------------
# check_velero_pods
# ---------------------------------------------------------------------------

class TestCheckVeleroPods:
    def _make_pod(self, phase: str, wi_label: bool = True) -> MagicMock:
        pod = MagicMock()
        pod.status.phase = phase
        pod.metadata.labels = {"azure.workload.identity/use": "true"} if wi_label else {}
        return pod

    def test_passes_when_all_running(self, core, result):
        core.list_namespaced_pod.return_value.items = [
            self._make_pod("Running"),
            self._make_pod("Running"),
        ]
        total, running = check_velero_pods(core, result)
        assert total == 2
        assert running == 2
        assert result.failed == 0

    def test_fails_when_no_pods(self, core, result):
        core.list_namespaced_pod.return_value.items = []
        total, running = check_velero_pods(core, result)
        assert total == 0
        assert result.failed == 1

    def test_fails_when_pods_not_running(self, core, result):
        core.list_namespaced_pod.return_value.items = [
            self._make_pod("Pending"),
            self._make_pod("Running"),
        ]
        total, running = check_velero_pods(core, result)
        assert running == 1
        assert result.failed == 1

    def test_warns_when_wi_label_missing(self, core, result):
        core.list_namespaced_pod.return_value.items = [
            self._make_pod("Running", wi_label=False),
        ]
        check_velero_pods(core, result)
        assert result.warned >= 1


# ---------------------------------------------------------------------------
# check_legacy_secret
# ---------------------------------------------------------------------------

class TestCheckLegacySecret:
    def test_warns_when_secret_exists(self, core, result):
        core.read_namespaced_secret.return_value = MagicMock()
        check_legacy_secret(core, result)
        assert result.warned == 1

    def test_passes_when_secret_absent(self, core, result):
        core.read_namespaced_secret.side_effect = ApiException(status=404)
        check_legacy_secret(core, result)
        assert result.passed == 1
        assert result.warned == 0


# ---------------------------------------------------------------------------
# check_bsl
# ---------------------------------------------------------------------------

class TestCheckBsl:
    def test_passes_when_available(self, custom, result):
        custom.get_namespaced_custom_object.return_value = {"status": {"phase": "Available"}}
        phase = check_bsl(custom, result)
        assert phase == "Available"
        assert result.passed == 1

    def test_fails_when_unavailable(self, custom, result):
        custom.get_namespaced_custom_object.return_value = {"status": {"phase": "Unavailable"}}
        phase = check_bsl(custom, result)
        assert phase == "Unavailable"
        assert result.failed == 1

    def test_fails_when_not_found(self, custom, result):
        custom.get_namespaced_custom_object.side_effect = ApiException(status=404)
        phase = check_bsl(custom, result)
        assert phase == "NotFound"
        assert result.failed == 1


# ---------------------------------------------------------------------------
# check_vsl
# ---------------------------------------------------------------------------

class TestCheckVsl:
    def test_passes_when_vsls_exist(self, custom, result):
        custom.list_namespaced_custom_object.return_value = {"items": [MagicMock(), MagicMock()]}
        count = check_vsl(custom, result)
        assert count == 2
        assert result.passed == 1

    def test_warns_when_none(self, custom, result):
        custom.list_namespaced_custom_object.return_value = {"items": []}
        count = check_vsl(custom, result)
        assert count == 0
        assert result.warned == 1


# ---------------------------------------------------------------------------
# check_volume_snapshot_classes
# ---------------------------------------------------------------------------

class TestCheckVolumeSnapshotClasses:
    def _make_vsc(self, labelled: bool) -> dict:
        labels = {"velero.io/csi-volumesnapshot-class": "true"} if labelled else {}
        return {"metadata": {"labels": labels}}

    def test_passes_with_labelled_vsc(self, custom, result):
        custom.list_cluster_custom_object.return_value = {"items": [self._make_vsc(labelled=True)]}
        count = check_volume_snapshot_classes(custom, result)
        assert count == 1
        assert result.failed == 0

    def test_warns_when_no_labelled_vsc(self, custom, result):
        custom.list_cluster_custom_object.return_value = {"items": [self._make_vsc(labelled=False)]}
        check_volume_snapshot_classes(custom, result)
        assert result.warned >= 1

    def test_warns_when_no_vscs(self, custom, result):
        custom.list_cluster_custom_object.return_value = {"items": []}
        check_volume_snapshot_classes(custom, result)
        assert result.warned == 1


# ---------------------------------------------------------------------------
# check_schedules
# ---------------------------------------------------------------------------

class TestCheckSchedules:
    def test_passes_when_schedules_exist(self, custom, result):
        custom.list_namespaced_custom_object.return_value = {"items": [MagicMock(), MagicMock()]}
        count = check_schedules(custom, result)
        assert count == 2
        assert result.passed == 1

    def test_warns_when_none(self, custom, result):
        custom.list_namespaced_custom_object.return_value = {"items": []}
        check_schedules(custom, result)
        assert result.warned == 1


# ---------------------------------------------------------------------------
# check_velero_cli
# ---------------------------------------------------------------------------

class TestCheckVeleroCli:
    @patch("verify_installation.subprocess.check_output")
    def test_passes_when_cli_present(self, mock_run, result):
        mock_run.return_value = "Client:\n\tVersion: v1.13.0\n"
        version = check_velero_cli(result)
        assert version == "v1.13.0"
        assert result.passed == 1

    @patch("verify_installation.subprocess.check_output")
    def test_warns_when_cli_missing(self, mock_run, result):
        mock_run.side_effect = FileNotFoundError()
        version = check_velero_cli(result)
        assert version is None
        assert result.warned == 1


# ---------------------------------------------------------------------------
# check_argocd_app
# ---------------------------------------------------------------------------

class TestCheckArgocdApp:
    def test_passes_when_synced_and_healthy(self, custom, result):
        custom.get_namespaced_custom_object.return_value = {
            "status": {
                "sync":   {"status": "Synced"},
                "health": {"status": "Healthy"},
            }
        }
        sync, health = check_argocd_app(custom, result)
        assert sync == "Synced"
        assert health == "Healthy"
        assert result.passed == 2

    def test_warns_when_degraded(self, custom, result):
        custom.get_namespaced_custom_object.return_value = {
            "status": {
                "sync":   {"status": "OutOfSync"},
                "health": {"status": "Degraded"},
            }
        }
        check_argocd_app(custom, result)
        assert result.warned == 2

    def test_warns_when_app_not_found(self, custom, result):
        custom.get_namespaced_custom_object.side_effect = ApiException(status=404)
        check_argocd_app(custom, result)
        assert result.warned == 1


# ---------------------------------------------------------------------------
# check_wi_webhook
# ---------------------------------------------------------------------------

class TestCheckWiWebhook:
    def test_passes_when_webhook_present(self, admissions, result):
        admissions.read_mutating_webhook_configuration.return_value = MagicMock()
        ok = check_wi_webhook(admissions, result)
        assert ok is True
        assert result.passed == 1

    def test_fails_when_webhook_absent(self, admissions, result):
        admissions.read_mutating_webhook_configuration.side_effect = ApiException(status=404)
        ok = check_wi_webhook(admissions, result)
        assert ok is False
        assert result.failed == 1
