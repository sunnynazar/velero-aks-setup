#!/bin/bash

###############################################################################
# Velero Azure Setup Script
# Sets up Azure resources for Velero using Workload Identity (no storage keys)
###############################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
print_info "Checking prerequisites..."

for cmd in az kubectl; do
    if ! command_exists "$cmd"; then
        print_error "'$cmd' is not installed. Please install it first."
        exit 1
    fi
done

print_info "Prerequisites check passed!"

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------
if [ -f "../config/config.env" ]; then
    print_info "Loading configuration from config.env..."
    source ../config/config.env
else
    print_warning "config.env not found. Please provide the following information:"

    read -p "Enter Azure Subscription ID: " AZURE_SUBSCRIPTION_ID
    read -p "Enter Resource Group name: " AZURE_RESOURCE_GROUP
    read -p "Enter Azure Region (default: eastus): " AZURE_LOCATION
    AZURE_LOCATION=${AZURE_LOCATION:-eastus}
    read -p "Enter AKS cluster name: " AKS_CLUSTER_NAME
    read -p "Enter Storage Account name prefix (default: velerobackup): " STORAGE_ACCOUNT_PREFIX
    STORAGE_ACCOUNT_PREFIX=${STORAGE_ACCOUNT_PREFIX:-velerobackup}
    read -p "Enter Blob Container name (default: velero-backups): " BLOB_CONTAINER
    BLOB_CONTAINER=${BLOB_CONTAINER:-velero-backups}
    read -p "Enter Managed Identity name (default: velero-identity): " MANAGED_IDENTITY_NAME
    MANAGED_IDENTITY_NAME=${MANAGED_IDENTITY_NAME:-velero-identity}
fi

# Generate a unique storage account name (lowercase, max 24 chars)
TIMESTAMP=$(date +%s)
STORAGE_ACCOUNT="${STORAGE_ACCOUNT_PREFIX}${TIMESTAMP}"
STORAGE_ACCOUNT=$(echo "${STORAGE_ACCOUNT}" | tr '[:upper:]' '[:lower:]' | cut -c1-24)

print_info "Configuration:"
print_info "  Subscription ID:   ${AZURE_SUBSCRIPTION_ID}"
print_info "  Resource Group:    ${AZURE_RESOURCE_GROUP}"
print_info "  Location:          ${AZURE_LOCATION}"
print_info "  AKS Cluster:       ${AKS_CLUSTER_NAME}"
print_info "  Storage Account:   ${STORAGE_ACCOUNT}"
print_info "  Blob Container:    ${BLOB_CONTAINER}"
print_info "  Managed Identity:  ${MANAGED_IDENTITY_NAME}"

read -p "Continue with this configuration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Setup cancelled by user"
    exit 1
fi

# ---------------------------------------------------------------------------
# Azure subscription
# ---------------------------------------------------------------------------
print_info "Setting Azure subscription..."
az account set --subscription "${AZURE_SUBSCRIPTION_ID}"

# ---------------------------------------------------------------------------
# Resource group
# ---------------------------------------------------------------------------
print_info "Checking resource group..."
if az group show --name "${AZURE_RESOURCE_GROUP}" &>/dev/null; then
    print_info "Resource group '${AZURE_RESOURCE_GROUP}' already exists"
else
    print_info "Creating resource group '${AZURE_RESOURCE_GROUP}'..."
    az group create \
        --name "${AZURE_RESOURCE_GROUP}" \
        --location "${AZURE_LOCATION}"
fi

# ---------------------------------------------------------------------------
# Storage account (no public access, HTTPS-only, TLS 1.2)
# ---------------------------------------------------------------------------
print_info "Creating storage account '${STORAGE_ACCOUNT}'..."
az storage account create \
    --name "${STORAGE_ACCOUNT}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --location "${AZURE_LOCATION}" \
    --sku Standard_LRS \
    --kind BlobStorage \
    --access-tier Hot \
    --encryption-services blob \
    --https-only true \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false

STORAGE_ACCOUNT_ID=$(az storage account show \
    --name "${STORAGE_ACCOUNT}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --query id --output tsv)

print_info "Storage account created: ${STORAGE_ACCOUNT_ID}"

# ---------------------------------------------------------------------------
# Blob container
# ---------------------------------------------------------------------------
print_info "Creating blob container '${BLOB_CONTAINER}'..."
az storage container create \
    --name "${BLOB_CONTAINER}" \
    --account-name "${STORAGE_ACCOUNT}" \
    --auth-mode login \
    --public-access off

# ---------------------------------------------------------------------------
# Lifecycle management policy
# ---------------------------------------------------------------------------
print_info "Creating lifecycle management policy..."
cat > /tmp/lifecycle-policy.json <<EOF
{
  "rules": [
    {
      "enabled": true,
      "name": "move-old-backups",
      "type": "Lifecycle",
      "definition": {
        "actions": {
          "baseBlob": {
            "tierToCool":    { "daysAfterModificationGreaterThan": 30  },
            "tierToArchive": { "daysAfterModificationGreaterThan": 90  },
            "delete":        { "daysAfterModificationGreaterThan": 180 }
          },
          "snapshot": {
            "delete": { "daysAfterCreationGreaterThan": 90 }
          }
        },
        "filters": {
          "blobTypes":   ["blockBlob"],
          "prefixMatch": ["${BLOB_CONTAINER}/"]
        }
      }
    }
  ]
}
EOF

az storage account management-policy create \
    --account-name "${STORAGE_ACCOUNT}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --policy @/tmp/lifecycle-policy.json

rm /tmp/lifecycle-policy.json
print_info "Lifecycle policy created!"

# ---------------------------------------------------------------------------
# User-Assigned Managed Identity
# ---------------------------------------------------------------------------
print_info "Creating User-Assigned Managed Identity '${MANAGED_IDENTITY_NAME}'..."
az identity create \
    --name "${MANAGED_IDENTITY_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --location "${AZURE_LOCATION}"

IDENTITY_CLIENT_ID=$(az identity show \
    --name "${MANAGED_IDENTITY_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --query clientId --output tsv)

IDENTITY_PRINCIPAL_ID=$(az identity show \
    --name "${MANAGED_IDENTITY_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --query principalId --output tsv)

IDENTITY_RESOURCE_ID=$(az identity show \
    --name "${MANAGED_IDENTITY_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --query id --output tsv)

print_info "Managed Identity client ID: ${IDENTITY_CLIENT_ID}"

# ---------------------------------------------------------------------------
# Role assignments (Storage Blob Data Contributor + Disk Snapshot Contributor)
# ---------------------------------------------------------------------------
print_info "Assigning 'Storage Blob Data Contributor' on the storage account..."
az role assignment create \
    --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
    --assignee-principal-type ServicePrincipal \
    --role "Storage Blob Data Contributor" \
    --scope "${STORAGE_ACCOUNT_ID}"

RESOURCE_GROUP_ID=$(az group show \
    --name "${AZURE_RESOURCE_GROUP}" \
    --query id --output tsv)

print_info "Assigning 'Disk Snapshot Contributor' on the resource group..."
az role assignment create \
    --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
    --assignee-principal-type ServicePrincipal \
    --role "Disk Snapshot Contributor" \
    --scope "${RESOURCE_GROUP_ID}"

print_info "Assigning 'Reader' on the resource group (required for Velero volume discovery)..."
az role assignment create \
    --assignee-object-id "${IDENTITY_PRINCIPAL_ID}" \
    --assignee-principal-type ServicePrincipal \
    --role "Reader" \
    --scope "${RESOURCE_GROUP_ID}"

# ---------------------------------------------------------------------------
# Enable OIDC issuer and Workload Identity on the AKS cluster
# ---------------------------------------------------------------------------
print_info "Enabling OIDC issuer on AKS cluster '${AKS_CLUSTER_NAME}'..."
az aks update \
    --name "${AKS_CLUSTER_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --enable-oidc-issuer \
    --enable-workload-identity

OIDC_ISSUER=$(az aks show \
    --name "${AKS_CLUSTER_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --query "oidcIssuerProfile.issuerUrl" \
    --output tsv)

print_info "OIDC issuer URL: ${OIDC_ISSUER}"

# ---------------------------------------------------------------------------
# Federated credential — links the Velero k8s service account to the identity
# ---------------------------------------------------------------------------
print_info "Creating federated identity credential..."
az identity federated-credential create \
    --name "velero-federated-credential" \
    --identity-name "${MANAGED_IDENTITY_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --issuer "${OIDC_ISSUER}" \
    --subject "system:serviceaccount:velero:velero" \
    --audience "api://AzureADTokenExchange"

print_info "Federated credential created!"

# ---------------------------------------------------------------------------
# Kubernetes namespace & service account (annotated for Workload Identity)
# ---------------------------------------------------------------------------
print_info "Creating Velero namespace and annotated service account..."
kubectl create namespace velero --dry-run=client -o yaml | kubectl apply -f -

kubectl create serviceaccount velero \
    --namespace velero \
    --dry-run=client -o yaml | kubectl apply -f -

kubectl annotate serviceaccount velero \
    --namespace velero \
    --overwrite \
    "azure.workload.identity/client-id=${IDENTITY_CLIENT_ID}"

kubectl label serviceaccount velero \
    --namespace velero \
    --overwrite \
    "azure.workload.identity/use=true"

# ---------------------------------------------------------------------------
# Patch velero/values.yaml with actual values
# ---------------------------------------------------------------------------
print_info "Updating velero/values.yaml..."
sed -i "s|<REPLACE_WITH_YOUR_RESOURCE_GROUP>|${AZURE_RESOURCE_GROUP}|g"   ../velero/values.yaml
sed -i "s|<REPLACE_WITH_YOUR_STORAGE_ACCOUNT>|${STORAGE_ACCOUNT}|g"       ../velero/values.yaml
sed -i "s|<REPLACE_WITH_YOUR_SUBSCRIPTION_ID>|${AZURE_SUBSCRIPTION_ID}|g" ../velero/values.yaml
sed -i "s|<REPLACE_WITH_YOUR_CLIENT_ID>|${IDENTITY_CLIENT_ID}|g"           ../velero/values.yaml
sed -i "s|velero-backups|${BLOB_CONTAINER}|g"                               ../velero/values.yaml
print_info "values.yaml updated!"

# ---------------------------------------------------------------------------
# Save config (no secrets — workload identity needs no stored keys)
# ---------------------------------------------------------------------------
mkdir -p ../config
cat > ../config/config.env <<EOF
# Azure Configuration for Velero (Workload Identity — no secrets stored)
AZURE_SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID}
AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP}
AZURE_LOCATION=${AZURE_LOCATION}
AKS_CLUSTER_NAME=${AKS_CLUSTER_NAME}
STORAGE_ACCOUNT=${STORAGE_ACCOUNT}
BLOB_CONTAINER=${BLOB_CONTAINER}
MANAGED_IDENTITY_NAME=${MANAGED_IDENTITY_NAME}
IDENTITY_CLIENT_ID=${IDENTITY_CLIENT_ID}
IDENTITY_RESOURCE_ID=${IDENTITY_RESOURCE_ID}
OIDC_ISSUER=${OIDC_ISSUER}
EOF

print_info "Configuration saved to config/config.env (no secrets — safe to inspect, but still git-ignored)"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
print_info "========================================"
print_info "Azure + Workload Identity Setup Complete!"
print_info "========================================"
echo ""
print_info "Resources created:"
print_info "  ✓ Storage Account:            ${STORAGE_ACCOUNT}"
print_info "  ✓ Blob Container:             ${BLOB_CONTAINER}"
print_info "  ✓ Lifecycle Policy:           Configured"
print_info "  ✓ Managed Identity:           ${MANAGED_IDENTITY_NAME} (${IDENTITY_CLIENT_ID})"
print_info "  ✓ Role: Storage Blob Data Contributor  → storage account"
print_info "  ✓ Role: Disk Snapshot Contributor      → resource group"
print_info "  ✓ Role: Reader                         → resource group"
print_info "  ✓ Federated Credential:       velero-federated-credential"
print_info "  ✓ K8s Service Account:        velero/velero (annotated)"
echo ""
print_info "Next steps:"
print_info "  1. Review velero/values.yaml"
print_info "  2. Deploy Velero via ArgoCD:"
print_info "     kubectl apply -f argocd/velero-application.yaml"
print_info "  3. Verify installation:"
print_info "     ./verify-installation.sh"
echo ""
print_warning "No storage keys were created or stored. Auth is handled entirely by Workload Identity."
echo ""
