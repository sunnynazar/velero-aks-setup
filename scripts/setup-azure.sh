#!/bin/bash

###############################################################################
# Velero Azure Setup Script
# This script sets up all Azure resources required for Velero backups
###############################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
print_info "Checking prerequisites..."

if ! command_exists az; then
    print_error "Azure CLI (az) is not installed. Please install it first."
    exit 1
fi

if ! command_exists kubectl; then
    print_error "kubectl is not installed. Please install it first."
    exit 1
fi

print_info "Prerequisites check passed!"

# Load configuration or prompt for values
if [ -f "../config/config.env" ]; then
    print_info "Loading configuration from config.env..."
    source ../config/config.env
else
    print_warning "config.env not found. Please provide the following information:"
    
    read -p "Enter Azure Subscription ID: " AZURE_SUBSCRIPTION_ID
    read -p "Enter Resource Group name: " AZURE_RESOURCE_GROUP
    read -p "Enter Azure Region (default: eastus): " AZURE_LOCATION
    AZURE_LOCATION=${AZURE_LOCATION:-eastus}
    read -p "Enter Storage Account name prefix (default: velerobackup): " STORAGE_ACCOUNT_PREFIX
    STORAGE_ACCOUNT_PREFIX=${STORAGE_ACCOUNT_PREFIX:-velerobackup}
    read -p "Enter Blob Container name (default: velero-backups): " BLOB_CONTAINER
    BLOB_CONTAINER=${BLOB_CONTAINER:-velero-backups}
fi

# Generate unique storage account name (must be globally unique, lowercase, no special chars)
TIMESTAMP=$(date +%s)
STORAGE_ACCOUNT="${STORAGE_ACCOUNT_PREFIX}${TIMESTAMP}"
# Ensure it's lowercase and max 24 chars
STORAGE_ACCOUNT=$(echo "${STORAGE_ACCOUNT}" | tr '[:upper:]' '[:lower:]' | cut -c1-24)

print_info "Configuration:"
print_info "  Subscription ID: ${AZURE_SUBSCRIPTION_ID}"
print_info "  Resource Group: ${AZURE_RESOURCE_GROUP}"
print_info "  Location: ${AZURE_LOCATION}"
print_info "  Storage Account: ${STORAGE_ACCOUNT}"
print_info "  Blob Container: ${BLOB_CONTAINER}"

read -p "Continue with this configuration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Setup cancelled by user"
    exit 1
fi

# Set Azure subscription
print_info "Setting Azure subscription..."
az account set --subscription "${AZURE_SUBSCRIPTION_ID}"

# Check if resource group exists, create if not
print_info "Checking resource group..."
if az group show --name "${AZURE_RESOURCE_GROUP}" &>/dev/null; then
    print_info "Resource group '${AZURE_RESOURCE_GROUP}' already exists"
else
    print_info "Creating resource group '${AZURE_RESOURCE_GROUP}'..."
    az group create \
        --name "${AZURE_RESOURCE_GROUP}" \
        --location "${AZURE_LOCATION}"
fi

# Create storage account with cost optimization
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

print_info "Storage account created successfully!"

# Get storage account key
print_info "Retrieving storage account access key..."
AZURE_STORAGE_ACCOUNT_ACCESS_KEY=$(az storage account keys list \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --account-name "${STORAGE_ACCOUNT}" \
    --query "[0].value" \
    --output tsv)

# Create blob container
print_info "Creating blob container '${BLOB_CONTAINER}'..."
az storage container create \
    --name "${BLOB_CONTAINER}" \
    --account-name "${STORAGE_ACCOUNT}" \
    --account-key "${AZURE_STORAGE_ACCOUNT_ACCESS_KEY}" \
    --public-access off

# Create lifecycle management policy for cost optimization
print_info "Creating lifecycle management policy..."
cat > /tmp/lifecycle-policy.json <<EOF
{
  "rules": [
    {
      "enabled": true,
      "name": "move-old-backups-to-cool",
      "type": "Lifecycle",
      "definition": {
        "actions": {
          "baseBlob": {
            "tierToCool": {
              "daysAfterModificationGreaterThan": 30
            },
            "tierToArchive": {
              "daysAfterModificationGreaterThan": 90
            },
            "delete": {
              "daysAfterModificationGreaterThan": 180
            }
          },
          "snapshot": {
            "delete": {
              "daysAfterCreationGreaterThan": 90
            }
          }
        },
        "filters": {
          "blobTypes": ["blockBlob"],
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

print_info "Lifecycle policy created successfully!"

# Create credentials file for Kubernetes secret
print_info "Creating credentials file..."
mkdir -p ../config
cat > ../config/credentials-velero <<EOF
AZURE_SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID}
AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP}
AZURE_STORAGE_ACCOUNT_ACCESS_KEY=${AZURE_STORAGE_ACCOUNT_ACCESS_KEY}
EOF

# Create Kubernetes secret
print_info "Creating Kubernetes secret..."
kubectl create namespace velero --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic velero-credentials \
    --namespace velero \
    --from-file=cloud=../config/credentials-velero \
    --dry-run=client -o yaml | kubectl apply -f -

print_info "Kubernetes secret created successfully!"

# Save configuration for future use
cat > ../config/config.env <<EOF
# Azure Configuration for Velero
AZURE_SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID}
AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP}
AZURE_LOCATION=${AZURE_LOCATION}
STORAGE_ACCOUNT=${STORAGE_ACCOUNT}
BLOB_CONTAINER=${BLOB_CONTAINER}
EOF

print_info "Configuration saved to config/config.env"

# Update values.yaml with actual values
print_info "Updating velero/values.yaml with your configuration..."
sed -i "s/<REPLACE_WITH_YOUR_RESOURCE_GROUP>/${AZURE_RESOURCE_GROUP}/g" ../velero/values.yaml
sed -i "s/<REPLACE_WITH_YOUR_STORAGE_ACCOUNT>/${STORAGE_ACCOUNT}/g" ../velero/values.yaml
sed -i "s/<REPLACE_WITH_YOUR_SUBSCRIPTION_ID>/${AZURE_SUBSCRIPTION_ID}/g" ../velero/values.yaml
sed -i "s/velero-backups/${BLOB_CONTAINER}/g" ../velero/values.yaml

print_info "values.yaml updated successfully!"

# Print summary
echo ""
print_info "========================================"
print_info "Azure Setup Complete!"
print_info "========================================"
echo ""
print_info "Resources created:"
print_info "  ✓ Resource Group: ${AZURE_RESOURCE_GROUP}"
print_info "  ✓ Storage Account: ${STORAGE_ACCOUNT}"
print_info "  ✓ Blob Container: ${BLOB_CONTAINER}"
print_info "  ✓ Lifecycle Policy: Configured"
print_info "  ✓ Kubernetes Secret: velero-credentials"
echo ""
print_info "Next steps:"
print_info "  1. Review the updated velero/values.yaml file"
print_info "  2. Deploy Velero using ArgoCD:"
print_info "     kubectl apply -f argocd/velero-application.yaml"
print_info "  3. Verify installation:"
print_info "     kubectl get pods -n velero"
echo ""
print_warning "Security Note: The credentials file is stored at config/credentials-velero"
print_warning "Make sure to add this to .gitignore and never commit it to version control!"
echo ""
