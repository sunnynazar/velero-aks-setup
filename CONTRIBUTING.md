# Contributing to Velero AKS Setup

Thank you for considering contributing to this project! This document provides guidelines for contributions.

## How to Contribute

### Reporting Issues

If you find a bug or have a suggestion:

1. Check if the issue already exists
2. Create a new issue with:
   - Clear title and description
   - Steps to reproduce (for bugs)
   - Expected vs actual behavior
   - Environment details (AKS version, Velero version, etc.)

### Submitting Changes

1. **Fork the repository**
   ```bash
   # Click "Fork" on GitHub, then clone your fork
   git clone https://github.com/YOUR-USERNAME/velero-aks-setup.git
   cd velero-aks-setup
   ```

2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-bug-fix
   ```

3. **Make your changes**
   - Follow existing code style
   - Update documentation if needed
   - Test your changes

4. **Commit your changes**
   ```bash
   git add .
   git commit -m "Brief description of changes
   
   Detailed explanation of what changed and why."
   ```

5. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

6. **Create a Pull Request**
   - Go to the original repository
   - Click "New Pull Request"
   - Select your branch
   - Describe your changes

## Development Guidelines

### Code Style

- **Bash scripts**: Use shellcheck for validation
- **YAML files**: Use yamllint for validation
- **Documentation**: Use Markdown
- **Commit messages**: Follow conventional commits format

### Testing

Before submitting:

```bash
# Validate YAML files
yamllint velero/values.yaml argocd/*.yaml

# Check bash scripts
shellcheck scripts/*.sh

# Test in a development environment
./scripts/setup-azure.sh
./scripts/verify-installation.sh
./scripts/test-backup-restore.sh
```

### Documentation

- Update README.md if adding new features
- Add comments to complex code sections
- Update relevant documentation in `docs/`
- Include examples for new functionality

## Areas for Contribution

### High Priority

- [ ] Add support for multiple cloud providers
- [ ] Terraform modules for Azure infrastructure
- [ ] GitHub Actions workflows for validation
- [ ] Grafana dashboards for monitoring
- [ ] Additional backup schedule templates

### Medium Priority

- [ ] Disaster recovery runbooks
- [ ] Cost analysis scripts
- [ ] Performance optimization guides
- [ ] Integration with Azure Key Vault
- [ ] Multi-cluster backup strategies

### Documentation

- [ ] Video tutorials
- [ ] More troubleshooting scenarios
- [ ] Migration guides (from other backup solutions)
- [ ] Best practices for specific workloads
- [ ] Compliance documentation templates

## Project Structure

```
velero-aks-setup/
├── README.md              # Main documentation
├── velero/               # Helm chart values
│   ├── values.yaml       # Main configuration
│   └── Chart.yaml        # Chart metadata
├── argocd/               # ArgoCD applications
│   ├── velero-application.yaml
│   └── velero-application-git.yaml
├── scripts/              # Automation scripts
│   ├── setup-azure.sh
│   ├── verify-installation.sh
│   ├── test-backup-restore.sh
│   └── push-to-github.sh
├── config/               # Configuration files
│   └── config.example.env
└── docs/                 # Additional documentation
    ├── INSTALLATION.md
    ├── BACKUP_STRATEGIES.md
    └── TROUBLESHOOTING.md
```

## Pull Request Checklist

Before submitting a PR, ensure:

- [ ] Code follows project style guidelines
- [ ] All tests pass
- [ ] Documentation is updated
- [ ] Commit messages are clear and descriptive
- [ ] Changes are tested in a real environment
- [ ] No sensitive information (credentials, keys) is committed

## Review Process

1. Maintainers will review your PR
2. Address any feedback or requested changes
3. Once approved, PR will be merged
4. Your contribution will be acknowledged in releases

## Code of Conduct

### Our Standards

- Be respectful and inclusive
- Welcome newcomers
- Accept constructive criticism gracefully
- Focus on what's best for the community
- Show empathy towards others

### Unacceptable Behavior

- Harassment or discrimination
- Trolling or insulting comments
- Personal or political attacks
- Publishing others' private information
- Other unprofessional conduct

## Questions?

- Open an issue for questions
- Tag maintainers for urgent matters
- Check existing documentation first

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Recognition

Contributors will be acknowledged in:
- README.md contributors section
- Release notes
- GitHub contributors page

Thank you for contributing! 🎉
