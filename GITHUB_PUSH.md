# How to Push This Repository to GitHub

Follow these steps to push this repository to your GitHub account.

## Prerequisites

1. GitHub account
2. Git installed on your machine
3. GitHub personal access token (or SSH key configured)

## Step-by-Step Instructions

### 1. Create a New Repository on GitHub

1. Go to https://github.com/new
2. Repository name: `velero-aks-setup` (or your preferred name)
3. Description: "Velero backup solution for AKS with ArgoCD and cost optimization"
4. Choose **Public** or **Private**
5. **DO NOT** initialize with README, .gitignore, or license (we already have these)
6. Click **Create repository**

### 2. Initialize Local Git Repository

```bash
cd velero-aks-setup

# Initialize git repository
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: Velero on AKS with ArgoCD setup"
```

### 3. Connect to GitHub Repository

Replace `YOUR-USERNAME` with your GitHub username:

```bash
# Add remote repository
git remote add origin https://github.com/YOUR-USERNAME/velero-aks-setup.git

# Or if using SSH:
git remote add origin git@github.com:YOUR-USERNAME/velero-aks-setup.git
```

### 4. Push to GitHub

```bash
# Push to main branch
git branch -M main
git push -u origin main
```

### 5. Verify

Visit `https://github.com/YOUR-USERNAME/velero-aks-setup` to see your repository.

## Using Personal Access Token (HTTPS)

If prompted for credentials when pushing:

1. **Create a token:**
   - Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Click "Generate new token (classic)"
   - Select scopes: `repo` (all)
   - Copy the token

2. **Use token as password:**
   ```bash
   Username: YOUR-USERNAME
   Password: YOUR-PERSONAL-ACCESS-TOKEN
   ```

3. **Cache credentials (optional):**
   ```bash
   git config --global credential.helper cache
   # Or store permanently (less secure):
   git config --global credential.helper store
   ```

## Using SSH Key

If you prefer SSH:

1. **Generate SSH key** (if you don't have one):
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   ```

2. **Add to SSH agent:**
   ```bash
   eval "$(ssh-agent -s)"
   ssh-add ~/.ssh/id_ed25519
   ```

3. **Add to GitHub:**
   - Copy public key: `cat ~/.ssh/id_ed25519.pub`
   - GitHub → Settings → SSH and GPG keys → New SSH key
   - Paste and save

4. **Use SSH remote:**
   ```bash
   git remote set-url origin git@github.com:YOUR-USERNAME/velero-aks-setup.git
   ```

## Complete Setup Script

Here's a complete script to automate the process:

```bash
#!/bin/bash

# Variables - CHANGE THESE
GITHUB_USERNAME="YOUR-USERNAME"
REPO_NAME="velero-aks-setup"

# Initialize git
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: Velero on AKS with ArgoCD setup"

# Add remote
git remote add origin https://github.com/${GITHUB_USERNAME}/${REPO_NAME}.git

# Push to GitHub
git branch -M main
git push -u origin main

echo "Repository pushed to https://github.com/${GITHUB_USERNAME}/${REPO_NAME}"
```

Save this as `push-to-github.sh`, update the variables, and run:

```bash
chmod +x push-to-github.sh
./push-to-github.sh
```

## After Pushing

### Update ArgoCD Application

If using the Git-based ArgoCD application, update `argocd/velero-application-git.yaml`:

```yaml
source:
  repoURL: https://github.com/YOUR-USERNAME/velero-aks-setup.git
  targetRevision: main
  path: velero
```

Then commit and push:

```bash
git add argocd/velero-application-git.yaml
git commit -m "Update ArgoCD application with correct repository URL"
git push
```

### Protect Sensitive Files

Make sure these files are in `.gitignore` and never committed:

- `config/config.env` (contains your Azure details)
- `config/credentials-velero` (contains storage account key)

Verify they're ignored:

```bash
git status
# Should not show these files
```

### Add Repository Topics (Optional)

On GitHub, add topics to make your repo more discoverable:
- velero
- aks
- azure
- kubernetes
- backup
- disaster-recovery
- argocd
- gitops
- helm

### Enable GitHub Actions (Optional)

You can add CI/CD workflows later to:
- Validate Helm charts
- Lint YAML files
- Run security scans

## Common Issues

### Error: remote origin already exists
```bash
git remote remove origin
git remote add origin https://github.com/YOUR-USERNAME/velero-aks-setup.git
```

### Error: failed to push some refs
```bash
# If remote has changes you don't have locally
git pull origin main --rebase
git push
```

### Large files warning
```bash
# If you accidentally committed large files
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch PATH/TO/LARGE/FILE' \
  --prune-empty --tag-name-filter cat -- --all
```

## Next Steps

1. **Update README.md** with your specific details
2. **Add repository description** on GitHub
3. **Enable branch protection** for main branch
4. **Add collaborators** if working in a team
5. **Create releases/tags** for versioning

## Repository Maintenance

### Regular updates
```bash
# After making changes
git add .
git commit -m "Description of changes"
git push
```

### Create tags for releases
```bash
git tag -a v1.0.0 -m "Initial release"
git push origin v1.0.0
```

### View repository status
```bash
git status
git log --oneline
git remote -v
```
