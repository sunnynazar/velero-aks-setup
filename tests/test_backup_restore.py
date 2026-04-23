"""Unit tests for scripts/test_backup_restore.py."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest
from kubernetes.client.rest import ApiException

from test_backup_restore import (
    Cleanup,
    RunResult,
    create_configmap,
    create_deployment,
    create_namespace,
    create_secret,
    delete_namespace,
    deployment_available_replicas,
    get_bsl_phase,
    get_configmap_value,
    namespace_exists,
    preflight,
    resource_exists,
    wait_for_backup,
    wait_for_restore,
)


@pytest.fixture()
def result() -> RunResult:
    return RunResult()


@pytest.fixture()
def core():
    return MagicMock()


@pytest.fixture()
def apps():
    return MagicMock()


@pytest.fixture()
def custom():
    return MagicMock()


@pytest.fixture()
def admissions():
    return MagicMock()


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

class TestRunResult:
    def test_ok_increments_passed(self, result, capsys):
        result.ok("all good")
        assert result.passed == 1
        assert result.failed == 0

    def test_fail_increments_failed(self, result, capsys):
        result.fail("something broke")
        assert result.failed == 1
        assert result.passed == 0

    def test_assert_true_passes(self, result):
        assert result.assert_true(True, "true condition") is True
        assert result.passed == 1

    def test_assert_true_fails(self, result):
        assert result.assert_true(False, "false condition") is False
        assert result.failed == 1


# ---------------------------------------------------------------------------
# namespace_exists
# ---------------------------------------------------------------------------

class TestNamespaceExists:
    def test_returns_true_when_found(self, core):
        core.read_namespace.return_value = MagicMock()
        assert namespace_exists(core, "my-ns") is True

    def test_returns_false_when_not_found(self, core):
        core.read_namespace.side_effect = ApiException(status=404)
        assert namespace_exists(core, "my-ns") is False


# ---------------------------------------------------------------------------
# resource_exists
# ---------------------------------------------------------------------------

class TestResourceExists:
    def test_configmap_found(self, core):
        core.read_namespaced_config_map.return_value = MagicMock()
        assert resource_exists(core, "configmap", "app-config", "my-ns") is True

    def test_secret_not_found(self, core):
        core.read_namespaced_secret.side_effect = ApiException(status=404)
        assert resource_exists(core, "secret", "app-secret", "my-ns") is False


# ---------------------------------------------------------------------------
# create_namespace (idempotent)
# ---------------------------------------------------------------------------

class TestCreateNamespace:
    def test_creates_when_absent(self, core):
        create_namespace(core, "my-ns")
        core.create_namespace.assert_called_once()

    def test_ignores_conflict(self, core):
        core.create_namespace.side_effect = ApiException(status=409)
        create_namespace(core, "my-ns")  # should not raise

    def test_raises_on_other_errors(self, core):
        core.create_namespace.side_effect = ApiException(status=500)
        with pytest.raises(ApiException):
            create_namespace(core, "my-ns")


# ---------------------------------------------------------------------------
# deployment_available_replicas
# ---------------------------------------------------------------------------

class TestDeploymentAvailableReplicas:
    def test_returns_count(self, apps):
        dep = MagicMock()
        dep.status.available_replicas = 2
        apps.read_namespaced_deployment.return_value = dep
        assert deployment_available_replicas(apps, "nginx", "my-ns") == 2

    def test_returns_zero_when_none(self, apps):
        dep = MagicMock()
        dep.status.available_replicas = None
        apps.read_namespaced_deployment.return_value = dep
        assert deployment_available_replicas(apps, "nginx", "my-ns") == 0

    def test_returns_zero_on_api_error(self, apps):
        apps.read_namespaced_deployment.side_effect = ApiException(status=404)
        assert deployment_available_replicas(apps, "nginx", "my-ns") == 0


# ---------------------------------------------------------------------------
# get_configmap_value
# ---------------------------------------------------------------------------

class TestGetConfigmapValue:
    def test_returns_value(self, core):
        cm = MagicMock()
        cm.data = {"env": "e2e-test"}
        core.read_namespaced_config_map.return_value = cm
        assert get_configmap_value(core, "app-config", "my-ns", "env") == "e2e-test"

    def test_returns_empty_on_missing_key(self, core):
        cm = MagicMock()
        cm.data = {}
        core.read_namespaced_config_map.return_value = cm
        assert get_configmap_value(core, "app-config", "my-ns", "missing") == ""

    def test_returns_empty_on_api_error(self, core):
        core.read_namespaced_config_map.side_effect = ApiException(status=404)
        assert get_configmap_value(core, "app-config", "my-ns", "env") == ""


# ---------------------------------------------------------------------------
# get_bsl_phase
# ---------------------------------------------------------------------------

class TestGetBslPhase:
    def test_returns_available(self, custom):
        custom.get_namespaced_custom_object.return_value = {"status": {"phase": "Available"}}
        assert get_bsl_phase(custom) == "Available"

    def test_returns_not_found_on_exception(self, custom):
        custom.get_namespaced_custom_object.side_effect = ApiException(status=404)
        assert get_bsl_phase(custom) == "NotFound"


# ---------------------------------------------------------------------------
# wait_for_backup / wait_for_restore
# ---------------------------------------------------------------------------

class TestWaitForBackup:
    @patch("test_backup_restore._velero")
    @patch("test_backup_restore.time.sleep", return_value=None)
    def test_returns_completed_phase(self, mock_sleep, mock_velero):
        payload = json.dumps({"status": {"phase": "Completed"}})
        mock_velero.return_value = MagicMock(returncode=0, stdout=payload)
        phase = wait_for_backup("my-backup", timeout=30)
        assert phase == "Completed"

    @patch("test_backup_restore._velero")
    @patch("test_backup_restore.time.sleep", return_value=None)
    @patch("test_backup_restore.time.time", side_effect=[0, 0, 9999])
    def test_returns_timeout_when_no_terminal_phase(self, mock_time, mock_sleep, mock_velero):
        mock_velero.return_value = MagicMock(returncode=0, stdout=json.dumps({"status": {"phase": "InProgress"}}))
        phase = wait_for_backup("my-backup", timeout=10)
        assert phase == "Timeout"


class TestWaitForRestore:
    @patch("test_backup_restore._velero")
    @patch("test_backup_restore.time.sleep", return_value=None)
    def test_returns_failed_phase(self, mock_sleep, mock_velero):
        payload = json.dumps({"status": {"phase": "Failed"}})
        mock_velero.return_value = MagicMock(returncode=0, stdout=payload)
        phase = wait_for_restore("my-restore", timeout=30)
        assert phase == "Failed"


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

class TestPreflight:
    def _running_pod(self) -> MagicMock:
        pod = MagicMock()
        pod.status.phase = "Running"
        return pod

    def _annotated_sa(self) -> MagicMock:
        sa = MagicMock()
        sa.metadata.annotations = {"azure.workload.identity/client-id": "ci-abc"}
        return sa

    @patch("test_backup_restore.subprocess.check_output", return_value=b"Version: v1.13.0")
    def test_passes_when_all_ready(self, mock_sub, core, custom, admissions, result):
        core.list_namespaced_pod.return_value.items = [self._running_pod()]
        core.read_namespaced_service_account.return_value = self._annotated_sa()
        admissions.read_mutating_webhook_configuration.return_value = MagicMock()
        custom.get_namespaced_custom_object.return_value = {"status": {"phase": "Available"}}

        ok = preflight(core, custom, admissions, result)
        assert ok is True
        assert result.failed == 0

    @patch("test_backup_restore.subprocess.check_output", side_effect=FileNotFoundError())
    def test_fails_when_velero_cli_missing(self, mock_sub, core, custom, admissions, result):
        ok = preflight(core, custom, admissions, result)
        assert ok is False

    @patch("test_backup_restore.subprocess.check_output", return_value=b"Version: v1.13.0")
    def test_fails_when_bsl_unavailable(self, mock_sub, core, custom, admissions, result):
        core.list_namespaced_pod.return_value.items = [self._running_pod()]
        core.read_namespaced_service_account.return_value = self._annotated_sa()
        admissions.read_mutating_webhook_configuration.return_value = MagicMock()
        custom.get_namespaced_custom_object.return_value = {"status": {"phase": "Unavailable"}}

        ok = preflight(core, custom, admissions, result)
        assert ok is False


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_skips_when_keep_resources(self, core):
        c = Cleanup(core, keep=True)
        c.track_namespace("test-ns")
        c.track_backup("my-backup")
        c.run()
        core.delete_namespace.assert_not_called()

    @patch("test_backup_restore._velero")
    def test_deletes_tracked_resources(self, mock_velero, core):
        c = Cleanup(core, keep=False)
        c.track_namespace("test-ns")
        c.track_backup("my-backup")
        c.track_restore("my-restore")
        c.run()
        core.delete_namespace.assert_called_once_with("test-ns")
        assert mock_velero.call_count == 2  # backup delete + restore delete
