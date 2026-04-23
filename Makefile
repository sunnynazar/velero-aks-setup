.PHONY: install test lint setup verify e2e

install:
	pip install -r requirements-dev.txt

test:
	pytest --cov=scripts --cov-report=term-missing

lint:
	ruff check scripts/ tests/

# Run against a real cluster (requires Azure creds + kubeconfig)
setup:
	python scripts/setup_azure.py

verify:
	python scripts/verify_installation.py

e2e:
	python scripts/test_backup_restore.py

e2e-skip-pvc:
	python scripts/test_backup_restore.py --skip-pvc
