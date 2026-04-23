"""Unit tests for scripts/setup_azure.py.

Azure SDK clients and the Kubernetes client are fully mocked so these tests
run without any cloud credentials or a real cluster.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from setup_azure import (
    ROLE_DISK_SNAPSHOT_CONTRIBUTOR,
    ROLE_READER,
    ROLE_STORAGE_BLOB_DATA_CONTRIBUTOR,
    VeleroConfig,
    assign_role,
    configure_k8s_service_account,
    create_lifecycle_policy,
    ensure_blob_container,
    ensure_managed_identity,
    ensure_resource_group,
    ensure_storage_account,
    ensure_federated_credential,
    patch_values_yaml,
)
from azure.core.exceptions import ResourceNotFoundError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def config() -> VeleroConfig:
    return VeleroConfig(
        subscription_id="sub-123",
        resource_group="velero-rg",
        location="eastus",
        aks_cluster_name="my-aks",
        storage_account="velerobackup12345",
        blob_container="velero-backups",
        managed_identity_name="velero-identity",
    )


@pytest.fixture()
def rg_client():
    return MagicMock()


@pytest.fixture()
def storage_client():
    return MagicMock()


@pytest.fixture()
def auth_client():
    return MagicMock()


@pytest.fixture()
def msi_client():
    return MagicMock()


# ---------------------------------------------------------------------------
# VeleroConfig.from_env
# ---------------------------------------------------------------------------

class TestVeleroConfigFromEnv:
    def test_raises_when_required_vars_missing(self, monkeypatch):
        for var in ["AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZURE_LOCATION", "AKS_CLUSTER_NAME"]:
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(ValueError, match="Missing required"):
            VeleroConfig.from_env()

    def test_loads_from_env(self, monkeypatch):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-abc")
        monkeypatch.setenv("AZURE_RESOURCE_GROUP", "my-rg")
        monkeypatch.setenv("AZURE_LOCATION", "westus")
        monkeypatch.setenv("AKS_CLUSTER_NAME", "my-cluster")
        monkeypatch.setenv("STORAGE_ACCOUNT", "mystorageacct")
        monkeypatch.setenv("BLOB_CONTAINER", "my-container")
        monkeypatch.setenv("MANAGED_IDENTITY_NAME", "my-identity")

        cfg = VeleroConfig.from_env()

        assert cfg.subscription_id == "sub-abc"
        assert cfg.resource_group == "my-rg"
        assert cfg.storage_account == "mystorageacct"
        assert cfg.blob_container == "my-container"
        assert cfg.managed_identity_name == "my-identity"

    def test_generates_storage_account_name_when_absent(self, monkeypatch):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-abc")
        monkeypatch.setenv("AZURE_RESOURCE_GROUP", "my-rg")
        monkeypatch.setenv("AZURE_LOCATION", "westus")
        monkeypatch.setenv("AKS_CLUSTER_NAME", "my-cluster")
        monkeypatch.delenv("STORAGE_ACCOUNT", raising=False)
        monkeypatch.setenv("STORAGE_ACCOUNT_PREFIX", "velerobackup")

        cfg = VeleroConfig.from_env()

        assert cfg.storage_account.startswith("velerobackup")
        assert len(cfg.storage_account) <= 24
        assert cfg.storage_account.islower()


# ---------------------------------------------------------------------------
# ensure_resource_group
# ---------------------------------------------------------------------------

class TestEnsureResourceGroup:
    def test_skips_when_exists(self, rg_client, config):
        rg_client.resource_groups.check_existence.return_value = True
        ensure_resource_group(rg_client, config)
        rg_client.resource_groups.create_or_update.assert_not_called()

    def test_creates_when_absent(self, rg_client, config):
        rg_client.resource_groups.check_existence.return_value = False
        ensure_resource_group(rg_client, config)
        rg_client.resource_groups.create_or_update.assert_called_once()
        args = rg_client.resource_groups.create_or_update.call_args[0]
        assert args[0] == config.resource_group


# ---------------------------------------------------------------------------
# ensure_storage_account
# ---------------------------------------------------------------------------

class TestEnsureStorageAccount:
    def test_returns_existing_id_without_creating(self, storage_client, config):
        existing = MagicMock()
        existing.id = "/subscriptions/sub-123/resourceGroups/velero-rg/providers/Microsoft.Storage/storageAccounts/existing"
        storage_client.storage_accounts.get_properties.return_value = existing

        result = ensure_storage_account(storage_client, config)

        assert result == existing.id
        storage_client.storage_accounts.begin_create.assert_not_called()

    def test_creates_account_when_absent(self, storage_client, config):
        storage_client.storage_accounts.get_properties.side_effect = ResourceNotFoundError("not found")
        new_account = MagicMock()
        new_account.id = "/subscriptions/sub-123/.../newaccount"
        storage_client.storage_accounts.begin_create.return_value.result.return_value = new_account

        result = ensure_storage_account(storage_client, config)

        assert result == new_account.id
        storage_client.storage_accounts.begin_create.assert_called_once()
        params = storage_client.storage_accounts.begin_create.call_args[0]
        assert params[0] == config.resource_group
        assert params[1] == config.storage_account

    def test_new_account_uses_standard_lrs(self, storage_client, config):
        import sys
        models = sys.modules["azure.mgmt.storage.models"]
        models.Sku.reset_mock()
        models.StorageAccountCreateParameters.reset_mock()
        storage_client.storage_accounts.get_properties.side_effect = ResourceNotFoundError("not found")
        storage_client.storage_accounts.begin_create.return_value.result.return_value = MagicMock(id="some-id")

        ensure_storage_account(storage_client, config)

        # Inspect kwargs passed to the mocked Sku and StorageAccountCreateParameters constructors
        sku_kwargs = models.Sku.call_args.kwargs
        assert sku_kwargs.get("name") == "Standard_LRS"

        sap_kwargs = models.StorageAccountCreateParameters.call_args.kwargs
        assert sap_kwargs.get("enable_https_traffic_only") is True
        assert sap_kwargs.get("allow_blob_public_access") is False


# ---------------------------------------------------------------------------
# ensure_blob_container
# ---------------------------------------------------------------------------

class TestEnsureBlobContainer:
    def test_skips_when_exists(self, storage_client, config):
        storage_client.blob_containers.get.return_value = MagicMock()
        ensure_blob_container(storage_client, config)
        storage_client.blob_containers.create.assert_not_called()

    def test_creates_when_absent(self, storage_client, config):
        storage_client.blob_containers.get.side_effect = ResourceNotFoundError("not found")
        ensure_blob_container(storage_client, config)
        storage_client.blob_containers.create.assert_called_once()
        args = storage_client.blob_containers.create.call_args[0]
        assert args[2] == config.blob_container


# ---------------------------------------------------------------------------
# create_lifecycle_policy
# ---------------------------------------------------------------------------

class TestCreateLifecyclePolicy:
    def test_calls_create_or_update_with_default_name(self, storage_client, config):
        create_lifecycle_policy(storage_client, config)
        storage_client.management_policies.create_or_update.assert_called_once()
        args = storage_client.management_policies.create_or_update.call_args[0]
        assert args[0] == config.resource_group
        assert args[1] == config.storage_account
        assert args[2] == "default"

    def test_policy_contains_correct_prefix(self, storage_client, config):
        import sys
        models = sys.modules["azure.mgmt.storage.models"]
        models.ManagementPolicyFilter.reset_mock()

        create_lifecycle_policy(storage_client, config)

        filter_kwargs = models.ManagementPolicyFilter.call_args.kwargs
        prefix_match = filter_kwargs.get("prefix_match", [])
        assert any(config.blob_container in p for p in prefix_match)

    def test_policy_delete_threshold_is_180_days(self, storage_client, config):
        import sys
        models = sys.modules["azure.mgmt.storage.models"]
        models.DateAfterModification.reset_mock()

        create_lifecycle_policy(storage_client, config)

        day_values = [
            c.kwargs.get("days_after_modification_greater_than")
            for c in models.DateAfterModification.call_args_list
        ]
        assert 180 in day_values


# ---------------------------------------------------------------------------
# ensure_managed_identity
# ---------------------------------------------------------------------------

class TestEnsureManagedIdentity:
    def test_returns_existing_identity_without_creating(self, msi_client, config):
        existing = MagicMock(client_id="ci-abc", principal_id="pi-abc", id="/res/id")
        msi_client.user_assigned_identities.get.return_value = existing

        client_id, principal_id, resource_id = ensure_managed_identity(msi_client, config)

        assert client_id == "ci-abc"
        assert principal_id == "pi-abc"
        msi_client.user_assigned_identities.create_or_update.assert_not_called()

    def test_creates_identity_when_absent(self, msi_client, config):
        msi_client.user_assigned_identities.get.side_effect = ResourceNotFoundError("not found")
        new_identity = MagicMock(client_id="ci-new", principal_id="pi-new", id="/res/new")
        msi_client.user_assigned_identities.create_or_update.return_value = new_identity

        client_id, principal_id, resource_id = ensure_managed_identity(msi_client, config)

        assert client_id == "ci-new"
        msi_client.user_assigned_identities.create_or_update.assert_called_once()


# ---------------------------------------------------------------------------
# assign_role
# ---------------------------------------------------------------------------

class TestAssignRole:
    def test_skips_when_already_assigned(self, auth_client, config):
        sub = config.subscription_id
        scope = "/subscriptions/sub-123/resourceGroups/velero-rg"
        role_def_id = (
            f"/subscriptions/{sub}/providers/Microsoft.Authorization"
            f"/roleDefinitions/{ROLE_READER}"
        )
        existing_assignment = MagicMock(role_definition_id=role_def_id)
        auth_client.role_assignments.list_for_scope.return_value = [existing_assignment]

        assign_role(auth_client, sub, "pi-123", ROLE_READER, scope)

        auth_client.role_assignments.create.assert_not_called()

    def test_creates_assignment_when_absent(self, auth_client, config):
        import sys
        models = sys.modules["azure.mgmt.authorization.models"]
        models.RoleAssignmentCreateParameters.reset_mock()
        auth_client.role_assignments.list_for_scope.return_value = []
        scope = "/subscriptions/sub-123/resourceGroups/velero-rg"

        assign_role(auth_client, config.subscription_id, "pi-123", ROLE_READER, scope)

        auth_client.role_assignments.create.assert_called_once()
        params_kwargs = models.RoleAssignmentCreateParameters.call_args.kwargs
        assert params_kwargs.get("principal_id") == "pi-123"
        assert ROLE_READER in params_kwargs.get("role_definition_id", "")


# ---------------------------------------------------------------------------
# ensure_federated_credential
# ---------------------------------------------------------------------------

class TestEnsureFederatedCredential:
    def test_skips_when_exists(self, msi_client, config):
        msi_client.federated_identity_credentials.get.return_value = MagicMock()
        ensure_federated_credential(msi_client, config, "https://issuer.example.com/")
        msi_client.federated_identity_credentials.create_or_update.assert_not_called()

    def test_creates_when_absent(self, msi_client, config):
        import sys
        models = sys.modules["azure.mgmt.msi.models"]
        models.FederatedIdentityCredential.reset_mock()
        msi_client.federated_identity_credentials.get.side_effect = ResourceNotFoundError("not found")

        ensure_federated_credential(msi_client, config, "https://issuer.example.com/")

        msi_client.federated_identity_credentials.create_or_update.assert_called_once()
        cred_kwargs = models.FederatedIdentityCredential.call_args.kwargs
        assert cred_kwargs.get("subject") == "system:serviceaccount:velero:velero"
        assert cred_kwargs.get("issuer") == "https://issuer.example.com/"
        assert "api://AzureADTokenExchange" in cred_kwargs.get("audiences", [])


# ---------------------------------------------------------------------------
# patch_values_yaml
# ---------------------------------------------------------------------------

class TestPatchValuesYaml:
    def test_replaces_all_placeholders(self, tmp_path, config, monkeypatch):
        values_dir = tmp_path / "velero"
        values_dir.mkdir()
        values_file = values_dir / "values.yaml"
        values_file.write_text(
            "resourceGroup: <REPLACE_WITH_YOUR_RESOURCE_GROUP>\n"
            "storageAccount: <REPLACE_WITH_YOUR_STORAGE_ACCOUNT>\n"
            "subscriptionId: <REPLACE_WITH_YOUR_SUBSCRIPTION_ID>\n"
            "clientId: <REPLACE_WITH_YOUR_CLIENT_ID>\n"
            "bucket: velero-backups\n"
        )

        # Patch REPO_ROOT to point at tmp_path
        import setup_azure
        monkeypatch.setattr(setup_azure, "REPO_ROOT", tmp_path)

        patch_values_yaml(config, client_id="ci-abc")

        text = values_file.read_text()
        assert config.resource_group in text
        assert config.storage_account in text
        assert config.subscription_id in text
        assert "ci-abc" in text
        assert config.blob_container in text
        assert "<REPLACE_WITH_YOUR" not in text


# ---------------------------------------------------------------------------
# configure_k8s_service_account
# ---------------------------------------------------------------------------

class TestConfigureK8sServiceAccount:
    @patch("setup_azure.k8s_config")
    @patch("setup_azure.k8s_client")
    def test_creates_namespace_and_annotates_sa(self, mock_k8s_client, mock_k8s_config):
        mock_core = MagicMock()
        mock_k8s_client.CoreV1Api.return_value = mock_core

        configure_k8s_service_account("ci-abc")

        mock_core.create_namespace.assert_called_once()
        mock_core.create_namespaced_service_account.assert_called_once()
        # Inspect kwargs passed to V1ObjectMeta to find the annotation
        meta_calls = mock_k8s_client.V1ObjectMeta.call_args_list
        meta_with_annotations = next(
            (c for c in meta_calls if isinstance(c.kwargs.get("annotations"), dict)),
            None,
        )
        assert meta_with_annotations is not None
        assert meta_with_annotations.kwargs["annotations"]["azure.workload.identity/client-id"] == "ci-abc"

    @patch("setup_azure.k8s_config")
    @patch("setup_azure.k8s_client")
    def test_patches_existing_service_account(self, mock_k8s_client, mock_k8s_config):
        from kubernetes.client.rest import ApiException as KubeApiException
        mock_core = MagicMock()
        mock_k8s_client.CoreV1Api.return_value = mock_core

        conflict = KubeApiException(status=409)
        mock_core.create_namespaced_service_account.side_effect = conflict

        configure_k8s_service_account("ci-abc")

        mock_core.patch_namespaced_service_account.assert_called_once()
