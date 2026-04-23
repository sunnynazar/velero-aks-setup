#!/bin/bash

###############################################################################
# GitHub Repository Setup Script
# This script initializes git and pushes to GitHub
###############################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_header() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo "========================================"
echo "GitHub Repository Setup"
echo "========================================"
echo ""

# Check if git is installed
if ! command -v git &> /dev/null; then
    print_error "Git is not installed. Please install git first."
    exit 1
fi

print_info "Git is installed"

# Get GitHub username
read -p "Enter your GitHub username: " GITHUB_USERNAME

if [ -z "$GITHUB_USERNAME" ]; then
    print_error "GitHub username cannot be empty"
    exit 1
fi

# Get repository name
read -p "Enter repository name (default: velero-aks-setup): " REPO_NAME
REPO_NAME=${REPO_NAME:-velero-aks-setup}

print_header "Configuration:"
echo "  GitHub Username: $GITHUB_USERNAME"
echo "  Repository Name: $REPO_NAME"
echo "  Repository URL: https://github.com/$GITHUB_USERNAME/$REPO_NAME"
echo ""

read -p "Continue with this configuration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Setup cancelled"
    exit 1
fi

# Check if already initialized
if [ -d .git ]; then
    print_warning "Git repository already initialized"
    read -p "Reinitialize? This will remove git history. (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf .git
        print_info "Git repository removed"
    else
        print_info "Using existing git repository"
    fi
fi

# Initialize git if needed
if [ ! -d .git ]; then
    print_header "Initializing git repository..."
    git init
    print_info "Git repository initialized"
fi

# Check for sensitive files
print_header "Checking for sensitive files..."
if [ -f "config/config.env" ]; then
    print_warning "Found config/config.env - make sure it's in .gitignore"
fi
if [ -f "config/credentials-velero" ]; then
    print_warning "Found config/credentials-velero - make sure it's in .gitignore"
fi

# Verify .gitignore
if grep -q "config/config.env" .gitignore && grep -q "config/credentials-velero" .gitignore; then
    print_info "Sensitive files are properly ignored"
else
    print_warning "Adding sensitive files to .gitignore"
    echo "config/config.env" >> .gitignore
    echo "config/credentials-velero" >> .gitignore
fi

# Update README with username
print_header "Updating README with your GitHub username..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/YOUR-USERNAME/$GITHUB_USERNAME/g" README.md
    sed -i '' "s/YOUR-USERNAME/$GITHUB_USERNAME/g" argocd/velero-application-git.yaml
    sed -i '' "s/YOUR-USERNAME/$GITHUB_USERNAME/g" docs/INSTALLATION.md
else
    sed -i "s/YOUR-USERNAME/$GITHUB_USERNAME/g" README.md
    sed -i "s/YOUR-USERNAME/$GITHUB_USERNAME/g" argocd/velero-application-git.yaml
    sed -i "s/YOUR-USERNAME/$GITHUB_USERNAME/g" docs/INSTALLATION.md
fi
print_info "Files updated with your GitHub username"

# Add all files
print_header "Staging files..."
git add .
print_info "Files staged"

# Show what will be committed
echo ""
print_header "Files to be committed:"
git status --short
echo ""

read -p "Proceed with commit? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Commit cancelled"
    exit 1
fi

# Create initial commit
print_header "Creating initial commit..."
git commit -m "Initial commit: Velero on AKS with ArgoCD setup

Complete setup for deploying Velero on Azure Kubernetes Service (AKS) 
using ArgoCD for GitOps deployment with cost optimization features.

Features:
- Azure Blob Storage backend with lifecycle policies
- CSI snapshot integration for PVC backups
- Automated daily and weekly backup schedules
- Cost-optimized storage configuration
- ArgoCD Application manifests
- Comprehensive documentation and scripts
"
print_info "Initial commit created"

# Choose authentication method
echo ""
print_header "Choose authentication method:"
echo "1) HTTPS (requires Personal Access Token)"
echo "2) SSH (requires SSH key configured)"
read -p "Enter choice (1 or 2): " AUTH_CHOICE

if [ "$AUTH_CHOICE" = "1" ]; then
    REMOTE_URL="https://github.com/$GITHUB_USERNAME/$REPO_NAME.git"
    print_info "Using HTTPS authentication"
    echo ""
    print_warning "You will need a GitHub Personal Access Token"
    print_warning "Create one at: https://github.com/settings/tokens"
    print_warning "Required scopes: repo"
    echo ""
elif [ "$AUTH_CHOICE" = "2" ]; then
    REMOTE_URL="git@github.com:$GITHUB_USERNAME/$REPO_NAME.git"
    print_info "Using SSH authentication"
    
    # Test SSH connection
    print_header "Testing SSH connection to GitHub..."
    if ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
        print_info "SSH connection successful"
    else
        print_warning "Could not verify SSH connection"
        print_warning "Make sure your SSH key is added to GitHub"
        print_warning "See: https://docs.github.com/en/authentication/connecting-to-github-with-ssh"
    fi
else
    print_error "Invalid choice"
    exit 1
fi

# Add remote
print_header "Adding remote repository..."
if git remote | grep -q "origin"; then
    print_warning "Remote 'origin' already exists, updating..."
    git remote set-url origin "$REMOTE_URL"
else
    git remote add origin "$REMOTE_URL"
fi
print_info "Remote repository added: $REMOTE_URL"

# Set main branch
git branch -M main

# Push to GitHub
echo ""
print_header "Ready to push to GitHub!"
print_warning "Make sure you have created the repository on GitHub first:"
print_warning "  https://github.com/new"
echo ""
read -p "Push to GitHub now? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_warning "Push cancelled. You can push manually later with:"
    echo "  git push -u origin main"
    exit 0
fi

print_header "Pushing to GitHub..."
if git push -u origin main; then
    echo ""
    print_info "========================================"
    print_info "Successfully pushed to GitHub!"
    print_info "========================================"
    echo ""
    print_info "Repository URL: https://github.com/$GITHUB_USERNAME/$REPO_NAME"
    echo ""
    print_header "Next steps:"
    echo "  1. Visit your repository: https://github.com/$GITHUB_USERNAME/$REPO_NAME"
    echo "  2. Add repository topics: velero, aks, azure, kubernetes, backup, argocd"
    echo "  3. Review and update README.md if needed"
    echo "  4. Deploy Velero using ArgoCD:"
    echo "     kubectl apply -f argocd/velero-application-git.yaml"
    echo ""
else
    print_error "Failed to push to GitHub"
    print_warning "Possible issues:"
    echo "  - Repository doesn't exist on GitHub (create it first)"
    echo "  - Authentication failed (check your credentials/SSH key)"
    echo "  - Network issues"
    echo ""
    print_warning "You can try pushing manually:"
    echo "  git push -u origin main"
    exit 1
fi
