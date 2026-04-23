#!/usr/bin/env python3
"""
Provisions Azure infrastructure for Velero using Workload Identity.
No storage keys are created or stored at any point.

Usage:
    cp config/config.example.env config/config.env
    # fill in values, then:
    python scripts/setup_azure.py
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.authorization import AuthorizationManagementClient
    from azure.mgmt.authorization.models import RoleAssignmentCreateParameters
    from azure.mgmt.containerservice import ContainerServiceClient
    from azure.mgmt.containerservice.models import ManagedCluster, ManagedClusterOIDCIssuerProfile
    from azure.mgmt.msi import ManagedServiceIdentityClient
    from azure.mgmt.msi.models import Identity, FederatedIdentityCredential
    from azure.mgmt.resource import ResourceManagementClient
    from azure.mgmt.resource.resources.models import ResourceGroup
    from azure.mgmt.storage import StorageManagementClient
    from azure.mgmt.storage.models import (
        BlobContainer,
        DateAfterCreation,
        DateAfterModification,
        Encryption,
        EncryptionService,
        EncryptionServices,
        ManagementPolicy,
        ManagementPolicyAction,
        ManagementPolicyBaseBlob,
        ManagementPolicyDefinition,
        ManagementPolicyFilter,
        ManagementPolicyRule,
        ManagementPolicySchema,
        ManagementPolicySnapAction,
        Sku,
        StorageAccountCreateParameters,
    )
except ImportError:
    # Allow module to be imported for unit testing with mocked clients
    pass

try:
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Stable Azure built-in role definition GUIDs
ROLE_STORAGE_BLOB_DATA_CONTRIBUTOR = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
ROLE_DISK_SNAPSHOT_CONTRIBUTOR     = "7efff54f-a5b4-42b5-a1c5-5411624f0a64"
ROLE_READER                        = "acdd72a7-3385-48ef-bd42-f606fba81ae7"

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class VeleroConfig:
    subscription_id: str
    resource_group: str
    location: str
    aks_cluster_name: str
    storage_account: str
    blob_container: str
    managed_identity_name: str

    @classmethod
    def from_env(cls) -> "VeleroConfig":
        env_file = REPO_ROOT / "config" / "config.env"
        if env_file.exists():
            _load_env_file(env_file)

        missing = []
        required = {
            "AZURE_SUBSCRIPTION_ID": "subscription_id",
            "AZURE_RESOURCE_GROUP":  "resource_group",
            "AZURE_LOCATION":        "location",
            "AKS_CLUSTER_NAME":      "aks_cluster_name",
        }
        values: dict = {}
        for env_key, attr in required.items():
            val = os.environ.get(env_key, "").strip()
            if not val:
                missing.append(env_key)
            values[attr] = val

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        # Optional with defaults
        prefix = os.environ.get("STORAGE_ACCOUNT_PREFIX", "velerobackup").strip()
        storage_account = os.environ.get("STORAGE_ACCOUNT", "").strip()
        if not storage_account:
            timestamp = str(int(time.time()))
            raw = f"{prefix}{timestamp}"
            storage_account = re.sub(r"[^a-z0-9]", "", raw.lower())[:24]

        values["storage_account"]       = storage_account
        values["blob_container"]        = os.environ.get("BLOB_CONTAINER", "velero-backups").strip()
        values["managed_identity_name"] = os.environ.get("MANAGED_IDENTITY_NAME", "velero-identity").strip()

        return cls(**values)

    def save(self, extra: dict) -> None:
        env_file = REPO_ROOT / "config" / "config.env"
        lines = [
            "# Azure Configuration for Velero (Workload Identity — no secrets stored)\n",
            f"AZURE_SUBSCRIPTION_ID={self.subscription_id}\n",
            f"AZURE_RESOURCE_GROUP={self.resource_group}\n",
            f"AZURE_LOCATION={self.location}\n",
            f"AKS_CLUSTER_NAME={self.aks_cluster_name}\n",
            f"STORAGE_ACCOUNT={self.storage_account}\n",
            f"BLOB_CONTAINER={self.blob_container}\n",
            f"MANAGED_IDENTITY_NAME={self.managed_identity_name}\n",
        ]
        for k, v in extra.items():
            lines.append(f"{k}={v}\n")
        env_file.write_text("".join(lines))
        log.info("Configuration saved to %s", env_file)


def _load_env_file(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


# ---------------------------------------------------------------------------
# Azure resource provisioning (each function is independently testable)
# ---------------------------------------------------------------------------

def ensure_resource_group(rg_client: ResourceManagementClient, config: VeleroConfig) -> None:
    if rg_client.resource_groups.check_existence(config.resource_group):
        log.info("Resource group '%s' already exists", config.resource_group)
        return
    log.info("Creating resource group '%s'", config.resource_group)
    rg_client.resource_groups.create_or_update(
        config.resource_group,
        ResourceGroup(location=config.location),
    )
    log.info("Resource group created")


def ensure_storage_account(
    storage_client: StorageManagementClient, config: VeleroConfig
) -> str:
    """Creates the storage account if absent and returns its resource ID."""
    try:
        account = storage_client.storage_accounts.get_properties(
            config.resource_group, config.storage_account
        )
        log.info("Storage account '%s' already exists", config.storage_account)
        return account.id
    except ResourceNotFoundError:
        pass

    log.info("Creating storage account '%s'", config.storage_account)
    poller = storage_client.storage_accounts.begin_create(
        config.resource_group,
        config.storage_account,
        StorageAccountCreateParameters(
            sku=Sku(name="Standard_LRS"),
            kind="BlobStorage",
            location=config.location,
            access_tier="Hot",
            enable_https_traffic_only=True,
            minimum_tls_version="TLS1_2",
            allow_blob_public_access=False,
            encryption=Encryption(
                services=EncryptionServices(blob=EncryptionService(enabled=True)),
                key_source="Microsoft.Storage",
            ),
        ),
    )
    account = poller.result()
    log.info("Storage account created: %s", account.id)
    return account.id


def ensure_blob_container(
    storage_client: StorageManagementClient, config: VeleroConfig
) -> None:
    try:
        storage_client.blob_containers.get(
            config.resource_group, config.storage_account, config.blob_container
        )
        log.info("Blob container '%s' already exists", config.blob_container)
        return
    except ResourceNotFoundError:
        pass

    log.info("Creating blob container '%s'", config.blob_container)
    storage_client.blob_containers.create(
        config.resource_group,
        config.storage_account,
        config.blob_container,
        BlobContainer(public_access="None"),
    )
    log.info("Blob container created")


def create_lifecycle_policy(
    storage_client: StorageManagementClient, config: VeleroConfig
) -> None:
    log.info("Applying lifecycle management policy")
    storage_client.management_policies.create_or_update(
        config.resource_group,
        config.storage_account,
        "default",
        ManagementPolicy(
            policy=ManagementPolicySchema(
                rules=[
                    ManagementPolicyRule(
                        name="move-old-backups",
                        enabled=True,
                        type="Lifecycle",
                        definition=ManagementPolicyDefinition(
                            filters=ManagementPolicyFilter(
                                blob_types=["blockBlob"],
                                prefix_match=[f"{config.blob_container}/"],
                            ),
                            actions=ManagementPolicyAction(
                                base_blob=ManagementPolicyBaseBlob(
                                    tier_to_cool=DateAfterModification(
                                        days_after_modification_greater_than=30
                                    ),
                                    tier_to_archive=DateAfterModification(
                                        days_after_modification_greater_than=90
                                    ),
                                    delete=DateAfterModification(
                                        days_after_modification_greater_than=180
                                    ),
                                ),
                                snapshot=ManagementPolicySnapAction(
                                    delete=DateAfterCreation(
                                        days_after_creation_greater_than=90
                                    )
                                ),
                            ),
                        ),
                    )
                ]
            )
        ),
    )
    log.info("Lifecycle policy applied")


def ensure_managed_identity(
    msi_client: ManagedServiceIdentityClient, config: VeleroConfig
) -> tuple[str, str, str]:
    """Returns (client_id, principal_id, resource_id)."""
    try:
        identity = msi_client.user_assigned_identities.get(
            config.resource_group, config.managed_identity_name
        )
        log.info("Managed identity '%s' already exists", config.managed_identity_name)
    except ResourceNotFoundError:
        log.info("Creating managed identity '%s'", config.managed_identity_name)
        identity = msi_client.user_assigned_identities.create_or_update(
            config.resource_group,
            config.managed_identity_name,
            Identity(location=config.location),
        )
        log.info("Managed identity created")

    return identity.client_id, identity.principal_id, identity.id


def assign_role(
    auth_client: AuthorizationManagementClient,
    subscription_id: str,
    principal_id: str,
    role_guid: str,
    scope: str,
) -> None:
    """Assigns a built-in role to a principal; skips if already assigned."""
    role_definition_id = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
        f"/roleDefinitions/{role_guid}"
    )

    # Check for an existing assignment to keep the operation idempotent
    existing = list(
        auth_client.role_assignments.list_for_scope(
            scope,
            filter=f"principalId eq '{principal_id}'",
        )
    )
    for assignment in existing:
        if assignment.role_definition_id.lower() == role_definition_id.lower():
            log.info("Role '%s' already assigned on scope '%s'", role_guid, scope)
            return

    log.info("Assigning role '%s' on scope '%s'", role_guid, scope)
    auth_client.role_assignments.create(
        scope,
        str(uuid.uuid4()),
        RoleAssignmentCreateParameters(
            role_definition_id=role_definition_id,
            principal_id=principal_id,
            principal_type="ServicePrincipal",
        ),
    )
    log.info("Role assigned")


def enable_aks_workload_identity(
    aks_client: ContainerServiceClient, config: VeleroConfig
) -> str:
    """Enables OIDC issuer + Workload Identity on the AKS cluster; returns OIDC issuer URL."""
    cluster: ManagedCluster = aks_client.managed_clusters.get(
        config.resource_group, config.aks_cluster_name
    )

    oidc_enabled = (
        cluster.oidc_issuer_profile is not None
        and cluster.oidc_issuer_profile.enabled
    )
    wi_enabled = (
        cluster.security_profile is not None
        and cluster.security_profile.workload_identity is not None
        and cluster.security_profile.workload_identity.enabled
    )

    if oidc_enabled and wi_enabled:
        log.info("OIDC issuer and Workload Identity already enabled")
        return cluster.oidc_issuer_profile.issuer_url

    log.info("Enabling OIDC issuer and Workload Identity on cluster '%s'", config.aks_cluster_name)
    cluster.oidc_issuer_profile = ManagedClusterOIDCIssuerProfile(enabled=True)
    if cluster.security_profile is None:
        from azure.mgmt.containerservice.models import ManagedClusterSecurityProfile
        cluster.security_profile = ManagedClusterSecurityProfile()
    from azure.mgmt.containerservice.models import ManagedClusterSecurityProfileWorkloadIdentity
    cluster.security_profile.workload_identity = ManagedClusterSecurityProfileWorkloadIdentity(
        enabled=True
    )
    poller = aks_client.managed_clusters.begin_create_or_update(
        config.resource_group, config.aks_cluster_name, cluster
    )
    updated: ManagedCluster = poller.result()
    issuer_url = updated.oidc_issuer_profile.issuer_url
    log.info("OIDC issuer URL: %s", issuer_url)
    return issuer_url


def ensure_federated_credential(
    msi_client: ManagedServiceIdentityClient,
    config: VeleroConfig,
    oidc_issuer: str,
) -> None:
    credential_name = "velero-federated-credential"
    try:
        msi_client.federated_identity_credentials.get(
            config.resource_group, config.managed_identity_name, credential_name
        )
        log.info("Federated credential '%s' already exists", credential_name)
        return
    except ResourceNotFoundError:
        pass

    log.info("Creating federated credential '%s'", credential_name)
    msi_client.federated_identity_credentials.create_or_update(
        config.resource_group,
        config.managed_identity_name,
        credential_name,
        FederatedIdentityCredential(
            issuer=oidc_issuer,
            subject="system:serviceaccount:velero:velero",
            audiences=["api://AzureADTokenExchange"],
        ),
    )
    log.info("Federated credential created")


def configure_k8s_service_account(client_id: str) -> None:
    """Creates the velero namespace and annotates the ServiceAccount for Workload Identity."""
    try:
        k8s_config.load_kube_config()
    except k8s_config.ConfigException:
        k8s_config.load_incluster_config()

    core = k8s_client.CoreV1Api()

    # Namespace
    try:
        core.create_namespace(
            k8s_client.V1Namespace(metadata=k8s_client.V1ObjectMeta(name="velero"))
        )
        log.info("Namespace 'velero' created")
    except ApiException as e:
        if e.status == 409:
            log.info("Namespace 'velero' already exists")
        else:
            raise

    # Service account
    sa = k8s_client.V1ServiceAccount(
        metadata=k8s_client.V1ObjectMeta(
            name="velero",
            namespace="velero",
            annotations={"azure.workload.identity/client-id": client_id},
            labels={"azure.workload.identity/use": "true"},
        )
    )
    try:
        core.create_namespaced_service_account("velero", sa)
        log.info("ServiceAccount 'velero' created and annotated")
    except ApiException as e:
        if e.status == 409:
            # Patch existing SA
            core.patch_namespaced_service_account("velero", "velero", sa)
            log.info("ServiceAccount 'velero' patched with Workload Identity annotation")
        else:
            raise


def patch_values_yaml(config: VeleroConfig, client_id: str) -> None:
    values_path = REPO_ROOT / "velero" / "values.yaml"
    text = values_path.read_text()
    replacements = {
        "<REPLACE_WITH_YOUR_RESOURCE_GROUP>":  config.resource_group,
        "<REPLACE_WITH_YOUR_STORAGE_ACCOUNT>": config.storage_account,
        "<REPLACE_WITH_YOUR_SUBSCRIPTION_ID>": config.subscription_id,
        "<REPLACE_WITH_YOUR_CLIENT_ID>":       client_id,
        "velero-backups":                      config.blob_container,
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    values_path.write_text(text)
    log.info("velero/values.yaml updated")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def provision(config: VeleroConfig) -> None:
    credential = DefaultAzureCredential()
    sub = config.subscription_id

    rg_client      = ResourceManagementClient(credential, sub)
    storage_client = StorageManagementClient(credential, sub)
    auth_client    = AuthorizationManagementClient(credential, sub)
    aks_client     = ContainerServiceClient(credential, sub)
    msi_client     = ManagedServiceIdentityClient(credential, sub)

    ensure_resource_group(rg_client, config)

    storage_id = ensure_storage_account(storage_client, config)
    ensure_blob_container(storage_client, config)
    create_lifecycle_policy(storage_client, config)

    client_id, principal_id, identity_resource_id = ensure_managed_identity(msi_client, config)

    rg_id = f"/subscriptions/{sub}/resourceGroups/{config.resource_group}"
    assign_role(auth_client, sub, principal_id, ROLE_STORAGE_BLOB_DATA_CONTRIBUTOR, storage_id)
    assign_role(auth_client, sub, principal_id, ROLE_DISK_SNAPSHOT_CONTRIBUTOR, rg_id)
    assign_role(auth_client, sub, principal_id, ROLE_READER, rg_id)

    oidc_issuer = enable_aks_workload_identity(aks_client, config)
    ensure_federated_credential(msi_client, config, oidc_issuer)

    configure_k8s_service_account(client_id)
    patch_values_yaml(config, client_id)

    config.save({
        "IDENTITY_CLIENT_ID":   client_id,
        "IDENTITY_RESOURCE_ID": identity_resource_id,
        "OIDC_ISSUER":          oidc_issuer,
    })

    log.info("=== Provisioning complete. No storage keys were created. ===")
    log.info("Next: kubectl apply -f argocd/velero-application.yaml")
    log.info("Then: python scripts/verify_installation.py")


def main() -> None:
    try:
        config = VeleroConfig.from_env()
    except ValueError as e:
        log.error("%s", e)
        sys.exit(1)

    log.info("Subscription:      %s", config.subscription_id)
    log.info("Resource Group:    %s", config.resource_group)
    log.info("Location:          %s", config.location)
    log.info("AKS Cluster:       %s", config.aks_cluster_name)
    log.info("Storage Account:   %s", config.storage_account)
    log.info("Blob Container:    %s", config.blob_container)
    log.info("Managed Identity:  %s", config.managed_identity_name)

    answer = input("Continue? [y/N] ").strip().lower()
    if answer != "y":
        log.info("Cancelled")
        sys.exit(0)

    provision(config)


if __name__ == "__main__":
    main()
